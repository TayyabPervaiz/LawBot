"""
Stage-Aware Benchmark Evaluation Suite for the Pakistan Law Bot (Phase 2A).

Measures, per revised plan Section 6:
1. Stage-aware expected behavior: a question must be ANSWERED only if every
   law in its `answered_by` is currently loaded (and it is not typed
   out_of_scope); otherwise it must be REFUSED. Cross-contamination is
   caught automatically: when a new law loads, old refusal questions flip
   to answers with no dataset edits.
2. Citation precision AND recall against `expected_citations`.
3. Refusal quality: refused answers must not cite sections (that is
   hallucination).
4. Not-covered calibration (`type == "not_covered_by_text"`): the bot must
   say the loaded provisions do not address the question.
5. Grounding trace: citations whose section was never retrieved are listed
   as unsupported.

Verification discipline (revised plan Rule 5): questions whose
`verified_by` is null are run but EXCLUDED from reported percentages,
because their ground truth has not been checked by the owner against the
official text.

Modes:
  python -m tests.evaluate --offline   # no LLM, no API key: stage logic +
                                       # registry checks + dataset sanity
  python -m tests.evaluate             # full run (needs Groq key + index)
"""

import re
import sys
import json
import time
from pathlib import Path

import src.law_registry as registry

BENCHMARK_PATH = Path(__file__).parent / "benchmark_dataset.json"


def load_benchmark() -> list[dict]:
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_citation_precision_recall(answer: str, expected_citations: list[dict]) -> dict:
    """
    Precision: share of CITED sections that were expected.
    Recall: share of EXPECTED sections that were cited.
    Fuzzy matching ("Section 15" matches "Section 15(1)(a)").
    """
    if not expected_citations:
        return {"precision": None, "recall": None, "expected": [], "cited": [], "missing": []}

    expected = [c["section"] for c in expected_citations]
    cited_raw = re.findall(r"Section\s+(\d+[A-Za-z]?)", answer, re.IGNORECASE)
    cited = sorted(set(cited_raw))

    missing = [s for s in expected if s not in cited]
    correct_citations = [s for s in cited if s in expected]

    precision = round(len(correct_citations) / len(cited), 3) if cited else 0.0
    recall = round((len(expected) - len(missing)) / len(expected), 3)

    return {
        "precision": precision,
        "recall": recall,
        "expected": expected,
        "cited": cited,
        "missing": missing,
    }


def check_refusal(answer: str) -> dict:
    """Out-of-scope answers must refuse and must not cite sections."""
    answer_lower = answer.lower()
    refusal_indicators = [
        "outside" in answer_lower and "scope" in answer_lower,
        "falls outside" in answer_lower,
        "not covered" in answer_lower,
        "currently covers" in answer_lower and "consult" in answer_lower,
    ]
    is_refused = any(refusal_indicators)
    has_citation = bool(re.search(r"Section\s+\d+", answer, re.IGNORECASE))

    if is_refused and not has_citation:
        return {"passed": True, "reason": "Correctly refused without citing sections"}
    if is_refused and has_citation:
        return {"passed": False, "reason": "Refused BUT cited sections (partial hallucination)"}
    if not is_refused and not has_citation:
        return {"passed": False, "reason": "Did not refuse (no refusal language found)"}
    return {"passed": False, "reason": "Did not refuse AND cited sections (full hallucination)"}


def check_not_covered(answer: str) -> dict:
    """not_covered_by_text answers must explicitly say the provisions are silent."""
    answer_lower = answer.lower()
    ok = (
        ("do not" in answer_lower and ("address" in answer_lower or "cover" in answer_lower))
        or ("does not" in answer_lower and ("address" in answer_lower or "cover" in answer_lower))
    )
    return {"passed": ok, "reason": "Calibrated not-covered" if ok else "Did not declare the provisions silent"}


def check_content_compliance(answer: str, must_contain: list, must_not_contain: list) -> dict:
    answer_lower = answer.lower()
    missing = [s for s in must_contain if s.lower() not in answer_lower]
    forbidden = [s for s in must_not_contain if s.lower() in answer_lower]
    return {
        "passed": not missing and not forbidden,
        "missing": missing,
        "forbidden_found": forbidden,
    }


def check_disclaimer(answer: str) -> dict:
    answer_lower = answer.lower()
    has_disclaimer = (
        "disclaimer" in answer_lower
        or ("legal information" in answer_lower and "legal advice" in answer_lower)
    )
    return {"passed": has_disclaimer, "reason": "Disclaimer present" if has_disclaimer else "No disclaimer found"}


# ---------------------------------------------------------------------------
# Stage-aware expectation logic (revised plan Section 6.2)
# ---------------------------------------------------------------------------

def expected_stage(question: dict, loaded: set[str]) -> dict:
    """
    Decide what the bot is EXPECTED to do for this question at this stage.

    Returns {"action": "answer"|"refuse", "must_refuse_locked": bool}
    """
    if question.get("type") == "out_of_scope" and not question.get("answered_by"):
        # Foreign-jurisdiction style: no law can ever answer it.
        return {"action": "refuse", "must_refuse_locked": True}
    if question.get("type") == "out_of_scope":
        # Refusable-now questions (FIR, Khula, WhatsApp): refuse until their
        # laws are loaded, answer once they are.
        if set(question.get("answered_by", [])) <= loaded:
            return {"action": "answer", "must_refuse_locked": False}
        return {"action": "refuse", "must_refuse_locked": True}
    # in_scope / multi_law / not_covered_by_text
    if set(question.get("answered_by", [])) <= loaded:
        return {"action": "answer", "must_refuse_locked": False}
    return {"action": "refuse", "must_refuse_locked": True}


# ---------------------------------------------------------------------------
# Offline evaluation (registry + dataset sanity, no API, no index)
# ---------------------------------------------------------------------------

def evaluate_offline() -> bool:
    benchmark = load_benchmark()
    loaded = set(registry.loaded_law_ids())

    print("\n" + "=" * 70)
    print("  OFFLINE STAGE LOGIC EVALUATION (no API key required)")
    print(f"  Loaded laws: {sorted(loaded) or 'NONE'}")
    print("=" * 70)

    all_ok = True
    for test in benchmark:
        stage = expected_stage(test, loaded)
        # Sanity expectations we can enforce without the bot:
        # 1) every answered_by must exist in the registry;
        # 2) expected_citations' law_ids must exist;
        # 3) stage action must be computed.
        reg_ok = all(registry.get_law(l) is not None for l in test["answered_by"])
        cite_ok = all(registry.get_law(c["law_id"]) is not None for c in test["expected_citations"])
        citation_pending = test.get("verified_by") is None

        row_ok = reg_ok and cite_ok
        all_ok = all_ok and row_ok
        status = "PASS" if row_ok else "FAIL"

        print(
            f"  {status} | {test['id']:7} | stage={stage['action']:6} | "
            f"type={test['type']:20} | verified={'YES' if not citation_pending else 'no '} | "
            f"{test['question'][:58]}"
        )
        if not row_ok:
            if not reg_ok:
                print(f"          unknown law_id in answered_by: {test['answered_by']}")
            if not cite_ok:
                print(f"          unknown law_id in expected_citations")

    print(f"\n  Dataset structure: {'PASS' if all_ok else 'FAIL'}")
    print(f"  Questions: {len(benchmark)} | owner-verified: "
          f"{sum(1 for t in benchmark if t.get('verified_by'))}/{len(benchmark)}")
    if sum(1 for t in benchmark if t.get('verified_by')) == 0:
        print("  [WARN] No question is owner-verified yet — full-run percentages "
              "will be reported EXCLUSIVELY as flagged-unverified until GATE 1.")
    return all_ok


# ---------------------------------------------------------------------------
# Full evaluation (requires API key + indexed store)
# ---------------------------------------------------------------------------

def evaluate_full() -> bool:
    from src.bot import ask

    benchmark = load_benchmark()
    loaded = set(registry.loaded_law_ids())

    print("\n" + "=" * 70)
    print("  FULL STAGE-AWARE BENCHMARK EVALUATION")
    print(f"  Loaded laws: {sorted(loaded) or 'NONE'}")
    print("=" * 70)

    results = []
    n_api_calls = 0

    for test in benchmark:
        stage = expected_stage(test, loaded)
        verified = test.get("verified_by") is not None

        print(f"\n  --- {test['id']}: {test['question']}")
        print(f"      stage={stage['action']} | verified={verified}")

        start = time.time()
        try:
            result = ask(test["question"])
            elapsed = time.time() - start
            n_api_calls += 1
            answer = result["answer"]

            refusal_check = check_refusal(answer)
            content_check = check_content_compliance(
                answer, test.get("must_contain", []), test.get("must_not_contain", [])
            )
            disclaimer_check = check_disclaimer(answer)
            citation_check = check_citation_precision_recall(
                answer, test.get("expected_citations", [])
            )
            not_covered_check = (
                check_not_covered(answer)
                if test["type"] == "not_covered_by_text"
                else None
            )

            if stage["action"] == "refuse":
                overall = refusal_check["passed"] and content_check["passed"]
            elif test["type"] == "not_covered_by_text":
                overall = not_covered_check["passed"] and content_check["passed"]
            else:
                overall = (
                    citation_check["recall"] is not None
                    and citation_check["recall"] >= 1.0
                    and content_check["passed"]
                    and disclaimer_check["passed"]
                )
                # Grounding trace: unsupported citations are a failure even
                # when recall is perfect.
                if result.get("citations", {}).get("unsupported"):
                    overall = False

            test_result = {
                "id": test["id"],
                "question": test["question"],
                "type": test["type"],
                "stage_action": stage["action"],
                "verified": verified,
                "overall_pass": overall,
                "citation": citation_check,
                "refusal": refusal_check,
                "content": content_check,
                "disclaimer": disclaimer_check,
                "not_covered": not_covered_check,
                "unsupported_citations": result.get("citations", {}).get("unsupported", []),
                "time_seconds": round(elapsed, 2),
                "answer_preview": (answer[:200] + "...") if len(answer) > 200 else answer,
            }

            status = "PASS" if overall else "FAIL"
            flagged = "" if verified else "  (UNVERIFIED — excluded from reported %)"
            print(f"      {status}{flagged} ({elapsed:.1f}s)")
            if not overall:
                if stage["action"] == "answer" and citation_check["missing"]:
                    print(f"        Citation: FAIL - missing {citation_check['missing']}")
                if test_result["unsupported_citations"]:
                    print(f"        Grounding: FAIL - unsupported citations "
                          f"{test_result['unsupported_citations']}")
                if not refusal_check["passed"]:
                    print(f"        Refusal: FAIL - {refusal_check['reason']}")
                if not content_check["passed"]:
                    print(f"        Content: FAIL - {content_check}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"      ERROR ({elapsed:.1f}s): {e}")
            test_result = {
                "id": test["id"], "question": test["question"],
                "type": test["type"], "stage_action": stage["action"],
                "verified": verified, "overall_pass": False,
                "error": str(e), "time_seconds": round(elapsed, 2),
            }

        results.append(test_result)
        time.sleep(2)  # free-tier politeness

    # --- Summary (verified questions only, per plan Rule 5) ---
    print("\n" + "=" * 70)
    print("  EVALUATION SUMMARY")
    print("=" * 70)

    scored = [r for r in results if r.get("verified")]
    unverified = [r for r in results if not r.get("verified")]

    if scored:
        passed = sum(1 for r in scored if r.get("overall_pass"))
        print(f"  Verified questions:  {passed}/{len(scored)} passed ({passed/len(scored)*100:.0f}%)")
    else:
        print("  Verified questions:  NONE — no percentage is reported (plan Rule 5).")
    print(f"  Unverified (run, excluded from %): {len(unverified)}")
    for r in unverified:
        mark = "PASS" if r.get("overall_pass") else "FAIL"
        print(f"    - {r['id']} [{mark}] {r.get('question', '')[:60]}")
    print(f"  LLM API calls this run: {n_api_calls} "
          f"(cached answers are reused across runs)")

    results_path = Path(__file__).parent / "evaluation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_on": time.strftime("%Y-%m-%d %H:%M:%S"),
            "loaded_laws": sorted(loaded),
            "n_verified": len(scored),
            "n_unverified": len(unverified),
            "results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Detailed results saved to: {results_path}")

    if scored and all(r.get("overall_pass") for r in scored):
        print("\n  [OK] ALL VERIFIED TESTS PASSED")
        return True
    if not scored:
        # No verified ground truth yet: a full run cannot pass the gate.
        print("\n  [WARN] Gate cannot pass without owner-verified questions (GATE 1).")
        return False
    print("\n  [WARN] verified failures above")
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--offline" in sys.argv:
        ok = evaluate_offline()
    else:
        ok = evaluate_full()
    sys.exit(0 if ok else 1)
