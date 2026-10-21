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
