"""
Offline unit tests for src/retrieval.py pure logic: tokenization, BM25,
RRF fusion, hint boosts, jurisdiction awareness.

`search()` itself needs the embedding model + ChromaDB, so it is NOT tested
here (covered indirectly by the owner-gated index/benchmark stages).
"""

import src.retrieval as retrieval
import src.law_registry as registry


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def test_tokenize_lowercases_drops_stopwords_and_short_tokens():
    toks = retrieval.tokenize("Can the landlord EVICT me, or not? I ask of it.")
    assert all(t == t.lower() for t in toks)
    for banned in ("the", "can", "or", "not", "i", "of", "it", "me"):
        assert banned not in toks
    assert "landlord" in toks and "evict" in toks


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def test_bm25_ranks_matching_doc_first():
    docs = [
        ["landlord", "evict", "tenant", "tribunal"],
        ["rent", "deposit", "refund", "agreement"],
        ["fir", "police", "arrest", "bail"],
    ]
    bm25 = retrieval.BM25(docs)
    scores = bm25.scores(["evict", "tenant"])
    assert scores[0] > max(scores[1], scores[2])
    empty = retrieval.BM25(docs).scores(["nothing", "matches"])
    assert all(s == 0.0 for s in empty)


def test_bm25_empty_inputs_are_safe():
    assert retrieval.BM25([]).scores(["x"]) == []   # empty corpus -> no scores
    # empty query -> no scores at all (retrieval() guards on this too)
    assert retrieval.BM25([["a", "b"]]).scores([]) == []


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------

def test_rrf_fuse_ranks_consistently_top_docs_higher():
    fused = retrieval.rrf_fuse([[0, 1, 2]], k=60)
    assert fused[0] > fused[1] > fused[2]

    # Doc appearing high in both rankings beats docs high in only one
    fused3 = retrieval.rrf_fuse([[0, 1], [0, 2]], k=60)
    assert fused3[0] > fused3[1] and fused3[0] > fused3[2]


def test_rrf_fuse_is_symmetric_for_mirror_rankings():
    fused = retrieval.rrf_fuse([[0, 1], [1, 0]], k=60)
    assert abs(fused[0] - fused[1]) < 1e-12


def test_rrf_fuse_skips_none_entries():
    fused = retrieval.rrf_fuse([[0, None]], k=60)
    assert set(fused) == {0}


# ---------------------------------------------------------------------------
# Hint boosts (soft only — must never gate a law)
# ---------------------------------------------------------------------------

def test_hint_boost_counts_exact_keyword_hits_with_cap():
    meta = {"law_id": "peca_2016"}  # keywords include "whatsapp" and "fia"
    two_hits = retrieval.hint_boost("My landlord messages me on WhatsApp; should I report to FIA?", meta)
    assert two_hits == 1.0 + 2 * 0.05

    three_hits = retrieval.hint_boost("WhatsApp harassment, FIA complaint, online hacking", meta)
    assert three_hits == 1.0 + 3 * 0.05  # capped at 3 hits


def test_hint_boost_is_identity_without_registry_entry():
    assert retrieval.hint_boost("any question", {"law_id": "not_a_law"}) == 1.0
    assert retrieval.hint_boost("any question", {}) == 1.0


# ---------------------------------------------------------------------------
# Jurisdiction awareness
# ---------------------------------------------------------------------------

def test_jurisdiction_note_fires_for_other_province():
    # Current real state: only tenancy (Punjab) is on disk.
    note = retrieval.jurisdiction_note("Can my landlord evict me in Sindh?")
    assert note is not None
    assert "Punjab" in note and "Sindh" in note


def test_jurisdiction_note_silent_for_punjab_and_unmentioned_province():
    assert retrieval.jurisdiction_note("Can my landlord evict me in Punjab?") is None
    assert retrieval.jurisdiction_note("Can my landlord evict me?") is None


# ---------------------------------------------------------------------------
# 1-A. Relevance Threshold & Normalization (Wave 1-A)
# ---------------------------------------------------------------------------

def test_normalization_must_not_run_before_threshold():
    """
    Plan Wave 1-A: Threshold must evaluate the RAW fused score.
    If normalization runs before threshold, top hit becomes 1.0 and below_threshold
    can almost never be True.
    """
    # Low raw scores below threshold (0.10, 0.08 < 0.35) -> below_threshold True
    candidates_low = {"A": 0.10, "B": 0.08}
    top_low, below_low = retrieval._apply_threshold_and_normalize(candidates_low, min_score=0.35)
    assert below_low is True
    # Verify normalization still happened for display: A is 1.0, B is 0.08/0.10 = 0.8
    assert top_low[0]["id"] == "A"
    assert top_low[0]["fused_score"] == 1.0
    assert top_low[1]["id"] == "B"
    assert top_low[1]["fused_score"] == 0.8

    # High raw scores above threshold (0.90, 0.40 >= 0.35) -> below_threshold False
    candidates_high = {"A": 0.90, "B": 0.40}
    top_high, below_high = retrieval._apply_threshold_and_normalize(candidates_high, min_score=0.35)
    assert below_high is False
    assert top_high[0]["id"] == "A"
    assert top_high[0]["fused_score"] == 1.0
    assert top_high[1]["id"] == "B"
    assert top_high[1]["fused_score"] == round(0.40 / 0.90, 4)


# ---------------------------------------------------------------------------
# 1-B. Linked Definitions Keyed by (law_id, section) (Wave 1-B)
# ---------------------------------------------------------------------------

def test_linked_section_keys_pulls_only_for_matching_act():
    """
    Plan Wave 1-B: Definition sections must be keyed to (law_id, section_number)
    of chunks actually in top_hits, never global section numbers across all laws.
    """
    # 1. Top hits only consumer law -> only ("punjab_consumer_2005", "2")
    top_consumer = [{"metadata": {"law_id": "punjab_consumer_2005", "section_number": "15"}}]
    extras_consumer = retrieval.linked_section_keys(top_consumer)
    assert extras_consumer == [("punjab_consumer_2005", "2")]

    # 2. Top hits PECA + tenancy (tenancy has empty always_include_sections) -> extra PECA "2" only
    top_peca_tenancy = [
        {"metadata": {"law_id": "peca_2016", "section_number": "10"}},
        {"metadata": {"law_id": "tenancy_punjab_2009", "section_number": "15"}},
    ]
    extras_pt = retrieval.linked_section_keys(top_peca_tenancy)
    assert extras_pt == [("peca_2016", "2")]
    # Confirm consumer or MFLO definitions are NEVER injected into PECA/tenancy query
    assert ("punjab_consumer_2005", "2") not in extras_pt
    assert ("mflo_1961", "2") not in extras_pt

    # 3. Two laws both needing "2" -> both (law_id, "2") pairs
    top_two = [
        {"metadata": {"law_id": "peca_2016", "section_number": "10"}},
        {"metadata": {"law_id": "punjab_consumer_2005", "section_number": "15"}},
    ]
    extras_two = retrieval.linked_section_keys(top_two)
    assert set(extras_two) == {("peca_2016", "2"), ("punjab_consumer_2005", "2")}


def test_bm25_cached_with_corpus():
    """Wave 4-M5: BM25 object is cached alongside corpus docs and refreshed on count change."""
    class FakeCollection:
        def __init__(self, count):
            self._count = count
        def count(self):
            return self._count
        def get(self, include=None):
            return {
                "ids": [f"doc_{i}" for i in range(self._count)],
                "documents": [f"Text for section {i}" for i in range(self._count)],
                "metadatas": [{"section": str(i)} for i in range(self._count)],
            }

    retrieval.invalidate_corpus_cache()
    col1 = FakeCollection(3)
    ids1, docs1, metas1, bm25_1 = retrieval._get_corpus(col1)
    assert bm25_1 is not None
    assert bm25_1.doc_count == 3

    # Subsequent call with same count returns the exact same cached BM25 instance
    ids2, docs2, metas2, bm25_2 = retrieval._get_corpus(col1)
    assert bm25_1 is bm25_2

    # Invalidation clears the cached instance
    retrieval.invalidate_corpus_cache()
    ids3, docs3, metas3, bm25_3 = retrieval._get_corpus(col1)
    assert bm25_3 is not bm25_1


