"""
Hybrid Retrieval for the Pakistan Law Bot (Phase 2A, revised plan Section 5.4).

Replaces the Phase-1 keyword "Topic Router" and its binary scope filter with:

    1. Vector search across ALL loaded laws (no law filter on the default path).
    2. BM25 keyword search over the same corpus.
    3. Reciprocal Rank Fusion (RRF) of the two rankings.
    4. Optional local cross-encoder reranker (config.RERANK_MODEL, off by default).
    5. Relevance threshold: below config.RETRIEVAL_MIN_SCORE the caller answers
       "the loaded laws do not cover this question".
    6. Linked definitions: chunks from a law's registry
       `always_include_sections` are appended when that law was hit.
    7. Soft keyword hints: a small score boost from registry hint_keywords.
       Hints NEVER exclude or gate a law.

The ChromaDB metadata filter stays available for tests/debugging only.
"""

import re
import math
from collections import Counter

from src import config
from src import law_registry as registry


# ---------------------------------------------------------------------------
# Tokenization (shared by BM25 and hints)
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# A minimal stopword list: words common enough in legal questions that BM25
# would otherwise rank every section by them.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "been", "can", "could", "should", "would", "will",
    "do", "does", "did", "my", "me", "i", "you", "your", "his", "her", "he",
    "she", "it", "its", "this", "that", "these", "those", "what", "how",
    "when", "where", "who", "whom", "which", "if", "as", "by", "at", "from",
    "with", "without", "not", "no", "have", "has", "had", "get", "got",
}


def tokenize(text: str) -> list[str]:
    return [
        t for t in _TOKEN_PATTERN.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 1
    ]


# ---------------------------------------------------------------------------
# BM25 (pure python — no new dependencies, corpus is small enough)
# ---------------------------------------------------------------------------

class BM25:
    """Minimal Okapi BM25 over the document corpus."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = len(docs)
        self.doc_lens = [len(d) for d in docs]
        self.avg_len = sum(self.doc_lens) / max(self.doc_count, 1)
        self.term_freqs = [Counter(d) for d in docs]
        self.doc_freq = Counter()
        for d in docs:
            self.doc_freq.update(set(d))
        self._docs = docs

    def score(self, query_tokens: list[str], index: int) -> float:
        tf_counter = self.term_freqs[index]
        dl = self.doc_lens[index] or 1
        score = 0.0
        for term in query_tokens:
            tf = tf_counter.get(term, 0)
            if tf == 0:
                continue
            df = self.doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.doc_count - df + 0.5) / (df + 0.5))
            score += idf * (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * dl / self.avg_len)
            )
        return score

    def scores(self, query_tokens: list[str]) -> list[float]:
        if self.doc_count == 0 or not query_tokens:
            return []
        return [self.score(query_tokens, i) for i in range(self.doc_count)]


# ---------------------------------------------------------------------------
# Corpus cache (chunk texts for BM25, refreshed when ChromaDB count changes)
# ---------------------------------------------------------------------------

_corpus_cache: dict = {"count": -1, "ids": [], "docs": [], "metas": []}


def _get_corpus(collection) -> tuple[list[str], list[str], list[dict]]:
    """(chunk_ids, chunk_texts, chunk_metadatas) of the whole collection. Cached."""
    count = collection.count()
    if count != _corpus_cache["count"]:
        got = collection.get(include=["documents", "metadatas"])
        _corpus_cache["ids"] = got["ids"] or []
        _corpus_cache["docs"] = got["documents"] or []
        _corpus_cache["metas"] = got["metadatas"] or []
        _corpus_cache["count"] = count
    return _corpus_cache["ids"], _corpus_cache["docs"], _corpus_cache["metas"]


def invalidate_corpus_cache() -> None:
    _corpus_cache.update(count=-1, ids=[], docs=[], metas=[])


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def rrf_fuse(rankings: list[list[int | None]], k: int = config.RRF_K) -> dict[int, float]:
    """
    Fuse several rankings (lists of corpus indices, best first) with RRF.

    Returns {corpus_index: fused_score}.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            if idx is None:
                continue
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


# ---------------------------------------------------------------------------
# Soft keyword hints (boost only — never exclude)
# ---------------------------------------------------------------------------

def hint_boost(question: str, metadata: dict) -> float:
    """Small relative boost if the question hits the law's hint_keywords."""
    law = registry.get_law(metadata.get("law_id") or "")
    if not law or not law.get("hint_keywords"):
        return 1.0
    q = question.lower()
    hits = sum(1 for kw in law["hint_keywords"]
               if re.search(r"\b" + re.escape(kw.lower()) + r"\b", q))
    return 1.0 + min(hits, 3) * config.HINT_BOOST


# ---------------------------------------------------------------------------
# Optional cross-encoder reranker (disabled unless config.RERANK_MODEL is set)
# ---------------------------------------------------------------------------

_reranker_cache: dict = {}


def _get_reranker():
    """Lazily load the CrossEncoder named in config.RERANK_MODEL, or None."""
    name = config.RERANK_MODEL
    if not name:
        return None
    if "reranker" not in _reranker_cache:
        from sentence_transformers import CrossEncoder
        print(f"Loading reranker '{name}'...")
        _reranker_cache["reranker"] = CrossEncoder(name)
    return _reranker_cache["reranker"]


def rerank(question: str, candidates: list[dict]) -> list[dict]:
    """Re-score fused candidates with a cross-encoder; falls back to input order."""
    ce = _get_reranker()
    if ce is None or not candidates:
        return candidates
    scores = ce.predict([(question, c["text"]) for c in candidates])
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def search(question: str, top_k: int = config.TOP_K_RESULTS, where: dict | None = None) -> dict:
    """
    Hybrid retrieval across all loaded laws.

    Returns:
        {
            "results": list of chunk dicts with "text", "metadata", "distance",
                       "fused_score" (normalized 0..1 relative to the best hit),
            "below_threshold": True if the best fused score is under
                               config.RETRIEVAL_MIN_SCORE (caller should answer
                               "not covered by the loaded laws"),
        }
    """
    from src import vector_store as vs  # lazy: heavy import (embedding model)

    collection = vs.get_or_create_collection()
    if collection.count() == 0:
        return {"results": [], "below_threshold": True}

    # 1) Vector ranking across ALL laws (`where` only used by tests/debug)
    pool = config.CANDIDATE_POOL_SIZE
    vector_hits = vs.query(question, top_k=max(pool, top_k), where=where)

    # 2) BM25 keyword ranking over the same corpus (corpus keeps chunk ids,
    #    so both rankings fuse on the common key: chunk id)
    corpus_ids, corpus_docs, corpus_metas = _get_corpus(collection)
    bm25 = BM25([tokenize(d) for d in corpus_docs] if corpus_docs else [])
    bm25_scores = bm25.scores(tokenize(question)) if corpus_docs else []

    vector_ranking = [h["id"] for h in vector_hits]
    bm25_ranking = (
        [corpus_ids[i] for i in sorted(range(len(bm25_scores)), key=lambda j: -bm25_scores[j])[:pool]]
        if bm25_scores else []
    )

    # 3) RRF fusion over chunk ids
    fused = rrf_fuse([vector_ranking, bm25_ranking])

    text_by_id = {
        h["id"]: {"text": h["text"], "metadata": h["metadata"], "distance": h["distance"]}
        for h in vector_hits
    }
    bm25_data = {
        cid: {"text": corpus_docs[i], "metadata": corpus_metas[i], "distance": None}
        for i, cid in enumerate(corpus_ids)
    }

    candidates: list[dict] = []
    for rank_id, score in sorted(fused.items(), key=lambda kv: -kv[1])[:pool]:
        data = text_by_id.get(rank_id) or bm25_data.get(rank_id)
        if data is None:
            continue
        candidates.append({
            "id": rank_id,
            "text": data["text"],
            "metadata": data["metadata"],
            "distance": data["distance"],
            "fused_score": score,
        })

    if not candidates:
        return {"results": [], "below_threshold": True}

    # 4) Optional reranker
    candidates = rerank(question, candidates)

    # 5) Soft hint boost (never excludes)
    for c in candidates:
        c["fused_score"] *= hint_boost(question, c["metadata"])

    # 6) Normalize to best hit and apply threshold
    best = candidates[0]["fused_score"] or 1.0
    for c in candidates:
        c["fused_score"] = round(c["fused_score"] / best, 4)

    top = candidates[:top_k]

    # 7) Linked definitions from the registry (always_include_sections)
    linked_ids = {}
    for c in top:
        law = registry.get_law((c["metadata"] or {}).get("law_id") or "")
        if law and law.get("always_include_sections"):
            linked_ids.setdefault(law["title"], set()).update(law["always_include_sections"])

    if linked_ids:
        required_sections = {s for secs in linked_ids.values() for s in secs}
        have = {t["metadata"].get("section_number") for t in top}
        missing = required_sections - have
        if missing:
            for meta_section in missing:
                law_id = [
                    mid for mid, law in registry.get_registry().items()
                    if law.get("always_include_sections") and meta_section in law["always_include_sections"]
                ]
                if not law_id:
                    continue
                extra = vs.query(
                    question, top_k=3, where={"$and": [
                        {"law_id": law_id[0]},
                        {"section_number": meta_section},
                    ]}
                )
                for e in extra:
                    if e["metadata"].get("section_number") == meta_section:
                        e["fused_score"] = 1.0  # linked definitions always relevant
                        top.append(e)
                        break

    below = top[0]["fused_score"] < config.RETRIEVAL_MIN_SCORE
    return {"results": top, "below_threshold": below}


# --- Province/jurisdiction awareness (revised plan Section 5.4 point 6) ---
PROVINCE_PATTERN = re.compile(
    r"\b(sindh|balochistan|baluchistan|khyber\s*pakhtunkhwa|kp\b|nwfp|"
    r"islamabad|punjab)\b",
    re.IGNORECASE,
)


def jurisdiction_note(question: str) -> str | None:
    """
    If the question names a province different from the loaded laws'
    jurisdiction, return a note that the loaded law applies to its own
    province (e.g. Punjab). None when not applicable.
    """
    hit = PROVINCE_PATTERN.search(question)
    if not hit:
        return None
    mentioned = hit.group(1).lower()
    if "punjab" in mentioned:
        return None  # Punjab is what is loaded
    loaded = registry.loaded_laws()
    provinces = sorted({e.get("jurisdiction") for e in loaded if e.get("jurisdiction")})
    if not provinces or "Federal" in provinces:
        return None  # federal laws answer everywhere
    if any(p.startswith("Punjab") for p in provinces):
        return (
            "Note: the laws currently loaded apply to Punjab "
            f"(you asked about {hit.group(0).strip()}). If your situation is "
            "governed by another province's law, please confirm with an advocate."
        )
    return None
