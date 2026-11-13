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
import threading
from collections import Counter

from src import config
from src import law_registry as registry


# ---------------------------------------------------------------------------
# Tokenization (shared by BM25 and hints)
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)

# A minimal stopword list: words common enough in legal questions that BM25
# would otherwise rank every section by them.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "been", "can", "could", "should", "would", "will",
    "do", "does", "did", "my", "me", "i", "you", "your", "his", "her", "he",
    "she", "it", "its", "this", "that", "these", "those", "what", "how",
    "when", "where", "who", "whom", "which", "if", "as", "by", "at", "from",
    "with", "without", "not", "no", "have", "has", "had", "get", "got",
    "kya", "hai", "ko", "se", "ka", "ki", "ke", "mein", "aur", "ye", "woh",
}


def tokenize(text: str) -> list[str]:
    return [
        t for t in _TOKEN_PATTERN.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 1
    ]


# Citizen questions use ordinary language (e.g. "increase", "cutoff", "deposit")
# while Pakistani statutory provisions use formal terms (e.g. "enhancement", "amenities", "security").
LEGAL_SYNONYMS = {
    # Tenancy synonyms (English, Roman Urdu, Urdu)
    "increase": ["enhancement", "rate"],
    "raise": ["enhancement", "rate"],
    "hike": ["enhancement", "rate"],
    "cutoff": ["discontinue", "sever", "amenities"],
    "shutoff": ["discontinue", "sever", "amenities"],
    "deposit": ["security", "pagri"],
    "evict": ["eviction", "possession", "vacate"],
    "eviction": ["possession", "vacate", "tribunal"],
    "enforce": ["execution", "order"],
    "enforced": ["execution", "order"],
    "enforcement": ["execution", "order"],
    "exempt": ["exemption"],
    "exempted": ["exemption"],
    "exemption": ["exempt"],
    "kiraya": ["rent", "tenancy", "rented"],
    "kirayedar": ["tenant", "rented", "premises"],
    "kirayedari": ["tenancy", "agreement", "lease"],
    "makan": ["premises", "building", "rented"],
    "malik": ["landlord", "owner"],
    "bedakhal": ["eviction", "vacate", "possession"],
    "bedakhli": ["eviction", "possession", "tribunal"],
    "nikalna": ["eviction", "possession", "vacate"],
    "کرایہ": ["rent", "tenancy", "premises"],
    "بے_دخلی": ["eviction", "possession", "tribunal"],
    "دخل": ["eviction", "possession", "vacate", "tribunal"],
    "رینٹ": ["rent", "tribunal", "premises"],
    "ٹربیونل": ["tribunal", "rent", "order", "eviction"],
    "حکم": ["order", "tribunal", "decision"],
    "مالک": ["landlord", "owner", "premises"],
    "مکان": ["premises", "building", "rented"],
    "کرایہ_دار": ["tenant", "rented", "premises"],
    "نوٹس": ["notice", "eviction", "period"],
    "sahulat": ["amenities", "electricity", "water", "discontinue"],
    "sahuliyat": ["amenities", "electricity", "water", "discontinue"],
    "سہولیات": ["amenities", "electricity", "water", "discontinue"],

    # Cybercrime synonyms (PECA 2016)
    "hack": ["unauthorized", "access"],
    "hacked": ["unauthorized", "access"],
    "hacking": ["unauthorized", "access"],
    "impersonation": ["identity", "unauthorized"],
    "impersonate": ["identity", "unauthorized"],
    "phishing": ["fraud", "forgery"],
    "harassment": ["cyberbullying", "stalking", "dignity"],
    "harassing": ["cyberbullying", "stalking", "dignity"],
    "photos": ["modesty", "photograph"],
    "pictures": ["modesty", "photograph"],
    "tasveer": ["modesty", "photograph", "information"],
    "tasveeren": ["modesty", "photograph", "information"],
    "blackmail": ["extortion", "threat", "harassment", "dignity"],
    "ہراساں": ["harassment", "cyberbullying", "dignity"],
    "بلیک_میل": ["blackmail", "extortion", "threat", "dignity"],
    "تصویر": ["photograph", "modesty", "information"],
    "جعلی": ["fake", "identity", "unauthorized", "fraud"],

    # Family law synonyms (MFLO 1961, FCA 1964, DMMA 1939)
    "khula": ["dissolution", "faskh", "dower"],
    "divorce": ["talaq", "dissolution"],
    "talaq": ["divorce", "notice", "arbitration"],
    "mehr": ["dower", "nikahnama"],
    "meher": ["dower", "nikahnama"],
    "mahr": ["dower", "nikahnama"],
    "nafaqa": ["maintenance", "adequate"],
    "nafaqah": ["maintenance", "adequate"],
    "kharcha": ["maintenance", "adequate", "family"],
    "custody": ["guardianship", "visitation", "child"],
    "parwarish": ["custody", "guardianship", "maintenance"],
    "polygamy": ["second", "wife", "permission"],
    "remarriage": ["second", "wife", "permission"],
    "wedding": ["nikah", "marriage", "registration"],
    "shadi": ["nikah", "marriage", "registration"],
    "nikahnama": ["nikah", "marriage", "registration", "dower"],
    "نکاح": ["marriage", "nikah", "registration"],
    "طلاق": ["divorce", "talaq", "notice"],
    "خلع": ["dissolution", "khula", "dower"],
    "مہر": ["dower", "nikahnama"],
    "نفقہ": ["maintenance", "adequate"],
    "بچے": ["child", "custody", "maintenance"],
    "دوسری_شادی": ["second", "wife", "permission"],
    "خاندان": ["family", "court", "reconciliation"],

    # Consumer protection synonyms (Punjab Consumer Protection Act 2005)
    "defective": ["faulty", "defect", "damage"],
    "broken": ["defective", "defect", "faulty"],
    "refund": ["return", "price", "reimbursement"],
    "warranty": ["guarantee", "express"],
    "receipt": ["invoice", "bill", "cash"],
    "overcharging": ["price", "exhibited"],
    "fake": ["misleading", "deceptive", "representation"],
    "complaint": ["claim", "consumer", "court"],
    "kharab": ["defective", "defect", "faulty", "damage"],
    "naqis": ["defective", "defect", "faulty"],
    "wapsi": ["refund", "return", "reimbursement"],
    "raseed": ["receipt", "invoice", "cash"],
    "harjana": ["damages", "compensation", "consumer"],
    "قیمت": ["price", "exhibited"],
    "رسید": ["receipt", "invoice"],
    "خراب": ["defective", "defect", "faulty"],
    "واپسی": ["refund", "return", "reimbursement"],
    "وارنٹی": ["warranty", "guarantee"],
    "ہرجانہ": ["damages", "compensation", "consumer"],

    # Criminal law synonyms (Pakistan Penal Code 1860 & Code of Criminal Procedure 1898)
    "fir": ["information", "cognizable", "police"],
    "murder": ["qatl", "amd", "death", "homicide"],
    "killing": ["qatl", "culpable", "homicide"],
    "theft": ["stealing", "dishonestly", "property"],
    "robbery": ["dacoity", "extortion", "hurt"],
    "extortion": ["blackmail", "threat", "injury"],
    "fraud": ["cheating", "deceiving", "fraudulently"],
    "bail": ["bailable", "surety", "bond", "release"],
    "arrest": ["custody", "warrant", "detention"],
    "remand": ["custody", "magistrate", "investigation"],
    "challan": ["report", "police", "investigation"],
    "cheque": ["dishonestly", "dishonoured", "bank"],
    "bounce": ["cheque", "dishonestly", "bank"],
    "chori": ["theft", "dishonestly", "property", "stolen"],
    "daku": ["dacoity", "robbery"],
    "qatl": ["murder", "culpable", "homicide", "death"],
    "marpeet": ["hurt", "assault", "force"],
    "dhamki": ["intimidation", "threat", "injury", "extortion"],
    "zamanat": ["bail", "bailable", "surety", "bond"],
    "giraftar": ["arrest", "custody", "detention"],
    "giraftari": ["arrest", "custody", "detention"],
    "thana": ["police", "station", "officer", "fir"],
    "muqadma": ["case", "offence", "cognizable", "trial"],
    "dhoka": ["cheating", "fraud", "deceiving"],
    "jaalsazi": ["forgery", "fraud", "document"],
    "ghar": ["dwelling", "house", "building", "theft", "property"],
    "saza": ["punishment", "imprisonment", "fine"],
    "darj": ["recorded", "information", "cognizable", "fir"],
    "bayan": ["statement", "police", "examination"],
    "رشوت": ["gratification", "illegal", "public"],
    "قتل": ["murder", "qatl", "amd", "death"],
    "چوری": ["theft", "stolen", "property", "dwelling"],
    "ڈکیتی": ["dacoity", "robbery"],
    "ضمانت": ["bail", "surety", "bond", "bailable"],
    "گرفتاری": ["arrest", "custody", "detention"],
    "تھانہ": ["police", "station", "fir", "information"],
    "سزا": ["punishment", "imprisonment", "fine"],
    "دھوکہ": ["cheating", "fraud", "deceiving"],
    "چیک": ["cheque", "dishonoured", "bank"],
    "بیان": ["statement", "police", "examination"],
    "درخواست": ["application", "complaint", "magistrate"],
    "دست": ["cognizable", "police", "arrest", "information"],
    "اندازی": ["cognizable", "police", "arrest"],
    "جرم": ["offence", "cognizable", "investigation"],
    "فوجداری": ["criminal", "procedure", "crpc", "police", "154"],
}


def tokenize_query(text: str) -> list[str]:
    """Tokenize query and expand with statutory legal synonyms."""
    base = tokenize(text)
    expanded = list(base)
    for t in base:
        if t in LEGAL_SYNONYMS:
            expanded.extend(LEGAL_SYNONYMS[t])
    return expanded


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

_corpus_cache: dict = {
    "count": -1,
    "ids": [],
    "docs": [],
    "metas": [],
    "bm25": None,
}
_corpus_lock = threading.Lock()


def _get_corpus(collection) -> tuple[list[str], list[str], list[dict], BM25 | None]:
    """(chunk_ids, chunk_texts, chunk_metadatas, bm25_index) of the whole collection. Cached with lock."""
    count = collection.count()
    with _corpus_lock:
        if count != _corpus_cache["count"]:
            got = collection.get(include=["documents", "metadatas"])
            docs = got["documents"] or []
            _corpus_cache["ids"] = got["ids"] or []
            _corpus_cache["docs"] = docs
            _corpus_cache["metas"] = got["metadatas"] or []
            _corpus_cache["bm25"] = BM25([tokenize(d) for d in docs] if docs else [])
            _corpus_cache["count"] = count
        return (
            _corpus_cache["ids"],
            _corpus_cache["docs"],
            _corpus_cache["metas"],
            _corpus_cache["bm25"],
        )


def invalidate_corpus_cache() -> None:
    with _corpus_lock:
        _corpus_cache.update(count=-1, ids=[], docs=[], metas=[], bm25=None)


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


def _apply_threshold_and_normalize(
    candidates: list[dict] | dict[str, float],
    min_score: float = config.RETRIEVAL_MIN_SCORE,
    top_k: int = config.TOP_K_RESULTS,
) -> tuple[list[dict], bool]:
    """
    Apply relevance threshold to RAW fused scores, then normalize 0..1 relative
    to the top candidate.

    CRITICAL (Plan Wave 1-A): Threshold must use the raw fused score (before normalization).
    Normalizing first forces the top hit to 1.0, making the threshold check dead.
    """
    if not candidates:
        return [], True

    # Normalize input format (accepts either list of chunk dicts or dict {id: score})
    if isinstance(candidates, dict):
        cand_list = [
            {"id": str(k), "fused_score": float(v), "raw_fused_score": float(v)}
            for k, v in candidates.items()
        ]
    else:
        cand_list = [dict(c) for c in candidates]

    if not cand_list:
        return [], True

    # Sort descending by raw score
    cand_list.sort(
        key=lambda c: -(c.get("raw_fused_score", c.get("fused_score", 0.0)) or 0.0)
    )

    raw_best = cand_list[0].get("raw_fused_score", cand_list[0].get("fused_score", 0.0)) or 0.0
    below_threshold = raw_best < min_score

    best = cand_list[0].get("fused_score") or 1.0
    top = []
    for c in cand_list[:top_k]:
        item = dict(c)
        if "raw_fused_score" not in item:
            item["raw_fused_score"] = item.get("fused_score", 0.0)
        item["fused_score"] = round(item.get("fused_score", 0.0) / best, 4) if best > 0 else 0.0
        top.append(item)

    return top, below_threshold


def linked_section_keys(top_hits: list[dict], question: str = "", reg=None) -> list[tuple[str, str]]:
    """
    Identify (law_id, section_number) definition chunks required by the laws
    present in top_hits that are not already present in top_hits.

    CRITICAL (Plan Wave 1-B): Extras are keyed by (law_id, section_number) of
    chunks already in top_hits, never from a global section number.

    Definition sections are always injected when a law is hit. The
    `always_include_sections` lists in the registry are deliberately kept
    small (1–2 sections per law), so the context overhead is minimal and the
    benefit (the LLM always has the definitions it needs) outweighs the cost.
    The `question` parameter is accepted for future conditional-injection
    work and is forwarded by the search() call site.
    """
    if reg is None:
        reg = registry

    have = set()
    seen_laws: list[str] = []
    for c in top_hits:
        meta = c.get("metadata") or {}
        lid = meta.get("law_id")
        sec = str(meta.get("section_number", ""))
        if lid:
            if sec:
                have.add((lid, sec))
            if lid not in seen_laws:
                seen_laws.append(lid)

    missing_pairs: list[tuple[str, str]] = []
    for lid in seen_laws:
        if hasattr(reg, "get_law"):
            law_entry = reg.get_law(lid)
        elif isinstance(reg, dict):
            law_entry = reg.get(lid)
        else:
            law_entry = registry.get_law(lid)

        if not law_entry:
            continue

        always_secs = law_entry.get("always_include_sections") or []
        for sec in always_secs:
            pair = (lid, str(sec))
            if pair not in have and pair not in missing_pairs:
                missing_pairs.append(pair)

    return missing_pairs


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
    # Wave 4-M5: BM25 index is cached alongside corpus docs
    corpus_ids, corpus_docs, corpus_metas, bm25 = _get_corpus(collection)
    bm25_scores = bm25.scores(tokenize_query(question)) if corpus_docs and bm25 else []

    vector_ranking = [h["id"] for h in vector_hits]
    bm25_ranking = (
        [corpus_ids[i] for i in sorted(range(len(bm25_scores)), key=lambda j: -bm25_scores[j])[:pool]]
        if bm25_scores else []
    )

    # 3) RRF fusion over chunk ids
    fused = rrf_fuse([vector_ranking, bm25_ranking], k=config.RRF_K)

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
            "raw_fused_score": score,
            "fused_score": score,
        })

    if not candidates:
        return {"results": [], "below_threshold": True}

    # 4) Optional reranker
    candidates = rerank(question, candidates)

    # 5) Soft hint boost (never excludes, never modifies raw_fused_score used by threshold)
    for c in candidates:
        boost = hint_boost(question, c["metadata"])
        c["fused_score"] *= boost
        # IMPORTANT: raw_fused_score must NOT be overwritten — the threshold check
        # in step 6 uses it to decide "covered vs not covered". Hint boost is cosmetic.

    # 6) Apply threshold and normalize (threshold uses raw fused score)
    top, below = _apply_threshold_and_normalize(
        candidates, min_score=config.RETRIEVAL_MIN_SCORE, top_k=top_k
    )

    # 7) Linked definitions from the registry (always_include_sections)
    # Extras are keyed by (law_id, section_number) of chunks already in top, never global.
    # Definitions are only injected when the question semantically needs them (see linked_section_keys).
    needed_pairs = linked_section_keys(top, question=question, reg=registry)
    for law_id, meta_section in needed_pairs:
        extra = vs.query(
            question, top_k=3, where={"$and": [
                {"law_id": law_id},
                {"section_number": meta_section},
            ]}
        )
        for e in extra:
            e_meta = e.get("metadata") or {}
            if e_meta.get("law_id") == law_id and str(e_meta.get("section_number")) == str(meta_section):
                e["fused_score"] = 1.0  # linked definitions always relevant
                e["raw_fused_score"] = 1.0
                top.append(e)
                break

    return {"results": top, "below_threshold": below}


# --- Province/jurisdiction awareness (revised plan Section 5.4 point 6) ---
PROVINCE_PATTERN = re.compile(
    r"\b(sindh|balochistan|baluchistan|khyber\s*pakhtunkhwa|kp\b|nwfp|"
    r"islamabad|punjab)\b",
    re.IGNORECASE,
)


def jurisdiction_note(question: str) -> str | None:
    """
    If the question names a province different from a loaded provincial law's
    jurisdiction (e.g. asking about Sindh when the loaded tenancy law is for Punjab),
    return a note that the loaded law applies to its own province.
    None when not applicable.
    """
    hit = PROVINCE_PATTERN.search(question)
    if not hit:
        return None
    mentioned = hit.group(1).lower()
    if "punjab" in mentioned:
        return None  # Punjab is what is loaded
    loaded = registry.loaded_laws()
    provincial = [e for e in loaded if e.get("jurisdiction") and e.get("jurisdiction") != "Federal"]
    if not provincial:
        return None  # all loaded laws are federal, which apply everywhere
    prov_names = sorted({e["jurisdiction"] for e in provincial})
    prov_str = ", ".join(prov_names)
    return (
        f"Note: provincial laws currently loaded apply to {prov_str} "
        f"(you asked about {hit.group(0).strip()}). If your situation is "
        "governed by another province's law, please confirm with an advocate."
    )
