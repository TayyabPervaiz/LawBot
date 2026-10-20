"""
Automated Benchmark Evaluation Suite for the Pakistan Law Bot.

This is the quality gate — it measures:
1. Citation Precision: Does the bot cite the correct sections for in-scope queries?
2. Refusal Accuracy: Does the bot properly refuse out-of-scope queries?
3. Content Compliance: Does the response contain/avoid required/forbidden strings?
4. Disclaimer Presence: Does every response include the legal disclaimer?

Design decisions:
- Citation matching is fuzzy: "Section 15" matches "Section 15(1)(a)" and
  "[Punjab Rented Premises Act, 2009 - Section 15]". This prevents false
  negatives from formatting variations.
- Refusal detection checks for scope-boundary keywords rather than exact strings,
  because the LLM may phrase refusals differently each time.
- The suite can run in two modes:
  (a) Full mode (default): Calls the actual LLM via Groq API
  (b) Scope-only mode (--scope-only): Tests only the pre-LLM scope detection
      (no API key needed, instant, good for development)
"""

import re
import sys
import json
import time
from pathlib import Path

from src.config import PROCESSED_DATA_DIR


# ---------------------------------------------------------------------------
# Test Data Loading
# ---------------------------------------------------------------------------

BENCHMARK_PATH = Path(__file__).parent / "benchmark_dataset.json"


def load_benchmark() -> list[dict]:
    """Load the benchmark test cases from JSON."""
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Evaluation Helpers
# ---------------------------------------------------------------------------

def check_citation_precision(answer: str, expected_sections: list[str]) -> dict:
    """
    Check if the answer cites the expected statutory sections.

    Uses fuzzy matching: "Section 15" matches "Section 15(1)", "Section 15(a)",
    "[Act Name - Section 15]", etc.

    Returns:
        {
            "passed": bool,
            "expected": ["15", "6"],
            "found": ["15"],
            "missing": ["6"],
        }
    """
    if not expected_sections:
        return {"passed": True, "expected": [], "found": [], "missing": []}

    found = []
    missing = []

    for section in expected_sections:
        # Match "Section 15" anywhere, including "Section 15(1)(a)" and formatted citations
        pattern = rf"Section\s+{re.escape(section)}\b"
        if re.search(pattern, answer, re.IGNORECASE):
            found.append(section)
        else:
            missing.append(section)

    return {
        "passed": len(missing) == 0,
        "expected": expected_sections,
        "found": found,
        "missing": missing,
    }


def check_refusal(answer: str, question_type: str) -> dict:
    """
    Check if out-of-scope questions are properly refused.

    A proper refusal must:
    - Mention that the question is outside scope
    - NOT cite any statutory section (citing sections = hallucinating)

    Returns:
        {"passed": bool, "reason": str}
    """
    if question_type != "out_of_scope":
        return {"passed": True, "reason": "N/A (in-scope question)"}

    answer_lower = answer.lower()

    # Check for refusal indicators
    refusal_indicators = [
        "outside" in answer_lower and "scope" in answer_lower,
        "outside this scope" in answer_lower,
        "falls outside" in answer_lower,
        "not covered" in answer_lower,
        "specialized in" in answer_lower and "tenancy" in answer_lower,
        "specialized in" in answer_lower and "rent" in answer_lower,
    ]

    is_refused = any(refusal_indicators)

    # Check that no sections are cited (that would be hallucination)
    has_citation = bool(re.search(r"Section\s+\d+", answer, re.IGNORECASE))

    if is_refused and not has_citation:
        return {"passed": True, "reason": "Correctly refused without citing sections"}
    elif is_refused and has_citation:
        return {"passed": False, "reason": "Refused BUT cited sections (partial hallucination)"}
    elif not is_refused and not has_citation:
        return {"passed": False, "reason": "Did not refuse (no refusal language found)"}
    else:
        return {"passed": False, "reason": "Did not refuse AND cited sections (full hallucination)"}


def check_content_compliance(answer: str, must_contain: list[str], must_not_contain: list[str]) -> dict:
    """
    Check if the answer contains required strings and avoids forbidden strings.

    Returns:
        {"passed": bool, "missing": [...], "forbidden_found": [...]}
    """
    answer_lower = answer.lower()

    missing = [s for s in must_contain if s.lower() not in answer_lower]
    forbidden_found = [s for s in must_not_contain if s.lower() in answer_lower]

    return {
        "passed": len(missing) == 0 and len(forbidden_found) == 0,
        "missing": missing,
        "forbidden_found": forbidden_found,
    }


def check_disclaimer(answer: str) -> dict:
    """
    Check if the response includes a legal disclaimer.

    Returns:
        {"passed": bool, "reason": str}
    """
    answer_lower = answer.lower()

    has_disclaimer = (
        "disclaimer" in answer_lower
        or ("legal information" in answer_lower and "legal advice" in answer_lower)
        or ("not formal legal advice" in answer_lower)
        or ("consult" in answer_lower and "advocate" in answer_lower)
    )

    return {
        "passed": has_disclaimer,
        "reason": "Disclaimer present" if has_disclaimer else "No disclaimer found",
    }


# ---------------------------------------------------------------------------
# Scope-Only Evaluation (No API key needed)
# ---------------------------------------------------------------------------

def evaluate_scope_only():
    """
    Test only the pre-LLM scope detection.
    No API key required. Instant results. Good for development.
    """
    from src.generator import detect_scope

    benchmark = load_benchmark()

    print("\n" + "=" * 70)
    print("  SCOPE DETECTION EVALUATION (No API key required)")
    print("=" * 70)

    passed = 0
    failed = 0

    for test in benchmark:
        expected_in_scope = test["type"] == "in_scope"
        result = detect_scope(test["question"])
        actual_in_scope = result["in_scope"]

        ok = actual_in_scope == expected_in_scope
        if ok:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        topic = result["detected_topic"] or "-"
        print(f"  {status} | Q{test['id']:2d} | "
              f"expected={expected_in_scope!s:5s} got={actual_in_scope!s:5s} | "
              f"topic={topic:20s} | {test['question']}")

    print(f"\n  Results: {passed}/{passed+failed} passed")
    print(f"  Scope Detection Accuracy: {passed/(passed+failed)*100:.1f}%")

    if failed == 0:
        print("\n  [OK] All scope detection tests passed!")
    else:
        print(f"\n  [WARN] {failed} scope detection test(s) failed.")

    return failed == 0


# ---------------------------------------------------------------------------
# Full Evaluation (Requires API key + indexed vector store)
# ---------------------------------------------------------------------------

def evaluate_full():
    """
    Run the complete evaluation: scope detection + retrieval + LLM generation.
    Requires: Groq API key configured, vector store indexed.
    """
    from src.bot import ask

    benchmark = load_benchmark()

    print("\n" + "=" * 70)
    print("  FULL BENCHMARK EVALUATION")
    print("  Testing scope detection + retrieval + LLM generation")
    print("=" * 70)

    results = []
    total_time = 0

    for test in benchmark:
        print(f"\n  --- Test Q{test['id']}: {test['question']}")
        print(f"      Type: {test['type']} | Expected sections: {test['expected_sections']}")

        start = time.time()
        try:
            result = ask(test["question"])
            elapsed = time.time() - start
            total_time += elapsed

            answer = result["answer"]

            # Run all checks
            citation_check = check_citation_precision(answer, test["expected_sections"])
            refusal_check = check_refusal(answer, test["type"])
            content_check = check_content_compliance(answer, test["must_contain"], test["must_not_contain"])
            disclaimer_check = check_disclaimer(answer)

            # Determine overall pass/fail
            if test["type"] == "in_scope":
                overall_pass = (
                    citation_check["passed"]
                    and content_check["passed"]
                    and disclaimer_check["passed"]
                )
            else:
                overall_pass = (
                    refusal_check["passed"]
                    and content_check["passed"]
                )

            test_result = {
                "id": test["id"],
                "question": test["question"],
                "type": test["type"],
                "overall_pass": overall_pass,
                "citation": citation_check,
                "refusal": refusal_check,
                "content": content_check,
                "disclaimer": disclaimer_check,
                "time_seconds": round(elapsed, 2),
                "answer_preview": answer[:200] + "..." if len(answer) > 200 else answer,
            }

            status = "PASS" if overall_pass else "FAIL"
            print(f"      {status} ({elapsed:.1f}s)")

            if not citation_check["passed"]:
                print(f"        Citation: FAIL - missing sections {citation_check['missing']}")
            if not refusal_check["passed"]:
                print(f"        Refusal: FAIL - {refusal_check['reason']}")
            if not content_check["passed"]:
                if content_check["missing"]:
                    print(f"        Content: FAIL - missing: {content_check['missing']}")
                if content_check["forbidden_found"]:
                    print(f"        Content: FAIL - forbidden found: {content_check['forbidden_found']}")
            if not disclaimer_check["passed"]:
                print(f"        Disclaimer: FAIL - {disclaimer_check['reason']}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"      ERROR ({elapsed:.1f}s): {e}")
            test_result = {
                "id": test["id"],
                "question": test["question"],
                "type": test["type"],
                "overall_pass": False,
                "error": str(e),
                "time_seconds": round(elapsed, 2),
            }

        results.append(test_result)

        if test["type"] == "in_scope":
            time.sleep(5)

    # --- Summary ---
    print("\n" + "=" * 70)
    print("  EVALUATION SUMMARY")
    print("=" * 70)

    in_scope_tests = [r for r in results if r["type"] == "in_scope"]
    out_scope_tests = [r for r in results if r["type"] == "out_of_scope"]

    in_scope_pass = sum(1 for r in in_scope_tests if r.get("overall_pass", False))
    out_scope_pass = sum(1 for r in out_scope_tests if r.get("overall_pass", False))
    total_pass = in_scope_pass + out_scope_pass
    total_tests = len(results)

    # Citation precision (in-scope only)
    citation_correct = sum(
        1 for r in in_scope_tests
        if r.get("citation", {}).get("passed", False)
    )

    # Refusal accuracy (out-of-scope only)
    refusal_correct = sum(
        1 for r in out_scope_tests
        if r.get("refusal", {}).get("passed", False)
    )

    print(f"\n  Overall:            {total_pass}/{total_tests} passed "
          f"({total_pass/total_tests*100:.0f}%)")
    print(f"  Citation Precision: {citation_correct}/{len(in_scope_tests)} "
          f"({citation_correct/max(len(in_scope_tests),1)*100:.0f}%)")
    print(f"  Refusal Accuracy:   {refusal_correct}/{len(out_scope_tests)} "
          f"({refusal_correct/max(len(out_scope_tests),1)*100:.0f}%)")
    print(f"  Total Time:         {total_time:.1f}s "
          f"(avg {total_time/max(total_tests,1):.1f}s per question)")

    # Save results
    results_path = Path(__file__).parent / "evaluation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Detailed results saved to: {results_path}")

    if total_pass == total_tests:
        print("\n  [OK] ALL TESTS PASSED!")
    else:
        failed = [r for r in results if not r.get("overall_pass", False)]
        print(f"\n  [WARN] {len(failed)} test(s) failed:")
        for r in failed:
            print(f"    - Q{r['id']}: {r['question']}")

    return total_pass == total_tests


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--scope-only" in args:
        success = evaluate_scope_only()
    else:
        success = evaluate_full()

    sys.exit(0 if success else 1)
