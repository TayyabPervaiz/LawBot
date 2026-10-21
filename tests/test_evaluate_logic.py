"""
Offline unit tests for tests/evaluate.py's stage-aware check functions.

The harness's live-LLM path is NOT tested here — that is owner-gated.
"""

import json

from tests.evaluate import (
    load_benchmark,
    check_citation_precision_recall,
    check_refusal,
    check_not_covered,
    check_content_compliance,
    check_disclaimer,
    expected_stage,
    evaluate_offline,
)


# ---------------------------------------------------------------------------
# Benchmark dataset sanity (stage-aware format per revised plan Section 6.1)
# ---------------------------------------------------------------------------

def test_benchmark_entries_have_required_fields():
    benchmark = load_benchmark()
    assert len(benchmark) >= 10, "benchmark must not shrink below the original 10"
    for case in benchmark:
        for field in ("id", "question", "language", "type", "answered_by"):
            assert field in case, f"case missing field {field}: {case.get('id')}"
        assert case["type"] in {"in_scope", "multi_law", "not_covered_by_text", "out_of_scope"}
    ids = [c["id"] for c in benchmark]
    assert len(ids) == len(set(ids)), "duplicate benchmark ids"


# ---------------------------------------------------------------------------
# Citation precision + recall (fuzzy matching)
# ---------------------------------------------------------------------------

def test_citation_precision_matches_subsections_and_bracket_format():
    answer = ("Landlord must apply to the Rent Tribunal "
              "[Punjab Rented Premises Act, 2009 - Section 15(1)(a)].")
    res = check_citation_precision_recall(answer, [{"law_id": "tenancy_punjab_2009", "section": "15"}])
    assert res["missing"] == [] and res["recall"] == 1.0
    assert "15" in res["cited"]
    assert res["precision"] == 1.0  # every cited section was expected


def test_citation_precision_penalizes_unexpected_citations():
    res = check_citation_precision_recall(
        "Cite Section 15 and Section 99.",
        [{"law_id": "x", "section": "15"}],
    )
    assert res["precision"] == 0.5  # 1 of 2 cited sections expected
    assert res["recall"] == 1.0


def test_citation_recall_reports_missing_expected_sections():
    res = check_citation_precision_recall(
        "Only Section 15 is cited here.",
        [{"law_id": "x", "section": "15"}, {"law_id": "x", "section": "6"}],
    )
    assert res["missing"] == ["6"] and res["recall"] == 0.5


def test_citation_check_no_expectations():
    res = check_citation_precision_recall("Anything", [])
    assert res == {"precision": None, "recall": None, "expected": [], "cited": [], "missing": []}


# ---------------------------------------------------------------------------
# Refusal / not-covered calibration
# ---------------------------------------------------------------------------

def test_refusal_accepts_clean_refusal_without_citations():
    ok = "This falls outside my scope; please consult an advocate."
    assert check_refusal(ok)["passed"] is True


def test_refusal_flags_refusal_that_cites_sections():
    res = check_refusal("Outside scope; but see Section 5 anyway.")
    assert res["passed"] is False and "partial hallucination" in res["reason"]


def test_refusal_flags_missing_refusal_language():
    assert check_refusal("Here is how you file an FIR.")["passed"] is False


def test_not_covered_calibration():
    assert check_not_covered(
        "The provided provisions of the Act do not address this specific issue."
    )["passed"] is True
    assert check_not_covered("Here is the confident answer you did not ask for.")["passed"] is False


# ---------------------------------------------------------------------------
# Content compliance + disclaimer
# ---------------------------------------------------------------------------

def test_content_compliance_tracks_missing_and_forbidden():
    ok = check_content_compliance("The rent agreement governs.", ["rent"], ["punishment"])
    assert ok["passed"] is True and ok["missing"] == [] and ok["forbidden_found"] == []

    bad = check_content_compliance("Rent is free forever.", ["tribunal"], ["free"])
    assert bad["passed"] is False
    assert bad["missing"] == ["tribunal"] and bad["forbidden_found"] == ["free"]


def test_disclaimer_detection():
    assert check_disclaimer("--- Disclaimer: information, not advice.")["passed"] is True
    assert check_disclaimer("legal information ... not legal advice")["passed"] is True
    assert check_disclaimer("just an answer")["passed"] is False


# ---------------------------------------------------------------------------
# Stage-aware expectation logic (revised plan Section 6.2)
# ---------------------------------------------------------------------------

def test_out_of_scope_locked_refusal_without_any_law():
    q = {"type": "out_of_scope", "answered_by": []}
    assert expected_stage(q, loaded=set()) == {"action": "refuse", "must_refuse_locked": True}


def test_fir_question_refuses_now_but_answers_once_ppc_is_loaded():
    q = {"id": "CRIM-001", "type": "out_of_scope", "answered_by": ["ppc_1860", "crpc_1898"]}
    # Today: neither law is loaded -> refuse (locked)
    assert expected_stage(q, loaded=set())["action"] == "refuse"
    # After Phase 2D: both loaded -> must answer, not refuse
    assert expected_stage(q, loaded={"ppc_1860", "crpc_1898"})["action"] == "answer"
    # Partially loaded -> still refuse
    assert expected_stage(q, loaded={"ppc_1860"})["action"] == "refuse"


def test_in_scope_tenancy_question_follows_loaded_state():
    q = {"type": "in_scope", "answered_by": ["tenancy_punjab_2009"]}
    # Tenancy file currently exists on disk, but logic must be state-based:
    assert expected_stage(q, loaded=set())["action"] == "refuse"
    assert expected_stage(q, loaded={"tenancy_punjab_2009"})["action"] == "answer"


# ---------------------------------------------------------------------------
# Offline evaluator runs end-to-end without an API key or index
# ---------------------------------------------------------------------------

def test_evaluate_offline_runs_and_reports(tmp_path, capsys):
    # The full offline check should not raise and should return a bool.
    result = evaluate_offline()
    assert isinstance(result, bool)
    assert "OFFLINE" in capsys.readouterr().out
