"""
Test suite for Pakistan Law Bot Phase 3:
- Multilingual Support (Urdu Script & Roman Urdu)
- Cross-lingual retrieval recall
- Multilingual out-of-scope refusals
- WhatsApp / Twilio Webhook endpoint
"""

import json
import urllib.request
import urllib.parse
from pathlib import Path
import pytest

from src.config import PROJECT_ROOT
from src.retrieval import search
from src.generator import detect_scope
from src.bot import _is_followup_query, ask
from tests.test_server_and_memory import live_server


MULTILINGUAL_BENCHMARK_PATH = PROJECT_ROOT / "tests" / "benchmark_multilingual.json"


@pytest.fixture(scope="module")
def multilingual_dataset():
    with open(MULTILINGUAL_BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_multilingual_out_of_scope_detection(multilingual_dataset):
    """Test that Urdu and Roman Urdu queries outside scope correctly trigger refusals."""
    oos_questions = [q for q in multilingual_dataset["questions"] if q.get("type") == "out_of_scope"]
    assert len(oos_questions) >= 4

    for item in oos_questions:
        q_text = item["question"]
        scope = detect_scope(q_text)
        assert scope["in_scope"] is False, f"Failed to mark out-of-scope: '{q_text}'"
        assert scope["detected_topic"] == item["refusal_topic"], (
            f"Expected topic '{item['refusal_topic']}', got '{scope['detected_topic']}' for '{q_text}'"
        )


def test_multilingual_cross_lingual_retrieval(multilingual_dataset):
    """Test that Urdu and Roman Urdu queries retrieve the relevant statutory sections."""
    factual_questions = [q for q in multilingual_dataset["questions"] if q.get("type") == "factual"]
    assert len(factual_questions) >= 16

    hits = 0
    total = len(factual_questions)
    failures = []

    for item in factual_questions:
        q_text = item["question"]
        expected_law = item.get("law_id")
        expected_sections = [str(s).upper() for s in item.get("expected_sections", [])]

        res = search(q_text, top_k=8)
        retrieved_chunks = res["results"]

        # Collect retrieved section numbers for the expected law
        found_sections = []
        for c in retrieved_chunks:
            meta = c.get("metadata") or {}
            c_law = meta.get("law_id")
            c_sec = str(meta.get("section_number", "")).upper()
            if not expected_law or c_law == expected_law:
                found_sections.append(c_sec)

        # Check if at least one expected section is in the top-8 retrieved chunks
        match = any(sec in found_sections for sec in expected_sections)
        if match:
            hits += 1
        else:
            failures.append({
                "id": item["id"],
                "question": q_text,
                "expected": expected_sections,
                "found": found_sections[:4],
            })

    recall_rate = hits / total
    print(f"\n[Multilingual Retrieval] {hits}/{total} ({recall_rate * 100:.1f}%) questions hit expected sections.")
    if failures:
        for f in failures:
            print(f"  MISS {f['id']}: expected {f['expected']}, got top: {f['found']}")

    # Cross-lingual retrieval target: at least 85% top-8 recall on zero-shot multilingual queries
    assert recall_rate >= 0.85, f"Cross-lingual retrieval recall too low: {recall_rate:.1%}"


def test_multilingual_followup_query_detector():
    """Verify follow-up query detection for Urdu and Roman Urdu conversational phrases."""
    # Roman Urdu follow-ups
    assert _is_followup_query("aur agar landlord na mane to?") is True
    assert _is_followup_query("iski saza kitni hogi?") is True
    assert _is_followup_query("kya wo bail le sakta hai?") is True
    assert _is_followup_query("zamanat kaise hogi?") is True

    # Urdu script follow-ups
    assert _is_followup_query("اور اگر مالک مکان انکار کر دے؟") is True
    assert _is_followup_query("اس کی سزا کیا ہے؟") is True
    assert _is_followup_query("ضمانت کیسے ملے گی؟") is True

    # Standalone queries should not be classified as follow-ups
    assert _is_followup_query("قتل کیا ہے؟") is False
    assert _is_followup_query("FIR darj karwane ka tareeqa kya hai?") is False


def test_twilio_whatsapp_webhook_endpoint(live_server):
    """Test POST /api/webhook/twilio returns valid TwiML XML."""
    post_body = urllib.parse.urlencode({
        "Body": "Can landlord cutoff water supply in Punjab?",
        "From": "whatsapp:+923001234567",
        "To": "whatsapp:+14155238886",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{live_server}/api/webhook/twilio",
        data=post_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "application/xml" in content_type
        xml_text = resp.read().decode("utf-8")
        assert "<Response>" in xml_text
        assert "<Message>" in xml_text
        assert "</Message>" in xml_text
        assert "</Response>" in xml_text
        # Check that answer contains Section 12 or disclaimer
        assert "Section" in xml_text or "Disclaimer" in xml_text

