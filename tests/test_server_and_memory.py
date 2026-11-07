"""
Unit tests for Pakistan Law Bot web server and conversation memory (Phase 3).
"""

import json
import urllib.request
import urllib.error
import threading
import time
import pytest
from http.server import ThreadingHTTPServer

from src.server import LawBotHandler
from src.bot import _is_followup_query, ask
from src.config import TOP_K_RESULTS
from src import law_registry as registry


@pytest.fixture(scope="module")
def live_server():
    """Start an ephemeral test server on localhost."""
    server = ThreadingHTTPServer(("127.0.0.1", 8089), LawBotHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield "http://127.0.0.1:8089"
    server.shutdown()


def test_followup_query_detector():
    """Test follow-up detection for conversational turns (Wave 3-H)."""
    assert _is_followup_query("What is the penalty for it?") is True
    assert _is_followup_query("Can he do this?") is True
    assert _is_followup_query("What about appeal?") is True
    assert _is_followup_query("What about the deposit?") is True
    assert _is_followup_query("is it bailable?") is True
    assert _is_followup_query("zamanat kaise hogi?") is True
    # Standalone queries must NOT be classified as follow-ups just because they are short:
    assert _is_followup_query("What is murder?") is False
    assert _is_followup_query("How do I file an FIR for armed motorcycle theft in Lahore?") is False


def test_api_laws_endpoint(live_server):
    """GET /api/laws returns all 8 loaded laws."""
    req = urllib.request.Request(f"{live_server}/api/laws")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "laws" in data
        assert data["count"] >= 8
        law_ids = [l["id"] for l in data["laws"]]
        assert "ppc_1860" in law_ids
        assert "crpc_1898" in law_ids
        assert "peca_2016" in law_ids
        assert "tenancy_punjab_2009" in law_ids
        assert "punjab_consumer_2005" in law_ids


def test_api_stats_endpoint(live_server):
    """GET /api/stats returns knowledge base statistics."""
    req = urllib.request.Request(f"{live_server}/api/stats")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ready"
        assert data["indexed_chunks"] >= 1600
        assert data["loaded_laws_count"] >= 8


def test_static_index_serving(live_server):
    """GET / serves index.html."""
    req = urllib.request.Request(f"{live_server}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "Pakistan Law Bot" in html
        assert "chat-input" in html


def test_static_css_and_js_serving(live_server):
    """GET /style.css and /app.js serve static files."""
    req_css = urllib.request.Request(f"{live_server}/style.css")
    with urllib.request.urlopen(req_css) as resp:
        assert resp.status == 200
        css = resp.read().decode("utf-8")
        assert "--accent-emerald" in css

    req_js = urllib.request.Request(f"{live_server}/app.js")
    with urllib.request.urlopen(req_js) as resp:
        assert resp.status == 200
        js = resp.read().decode("utf-8")
        assert "conversationHistory" in js


def test_empty_collection_returns_setup_error_not_refusal(monkeypatch):
    """
    Plan Wave 2-F: If collection count is 0, ask() always returns a setup error
    (in_scope True, not_covered False, no legal refusal wording), regardless of verbose.
    """
    class FakeEmptyCollection:
        def count(self):
            return 0

    class FakeVectorStore:
        def get_or_create_collection(self):
            return FakeEmptyCollection()

    import src.bot as bot
    monkeypatch.setattr(bot, "_get_vector_store", lambda: FakeVectorStore())

    # Ask without verbose (production default)
    res = bot.ask("Can my landlord evict me?", verbose=False)
    assert "knowledge base is empty" in res["answer"].lower()
    assert "python -m src.bot --index" in res["answer"]
    assert res["in_scope"] is True
    assert res["not_covered"] is False
    assert "do not explicitly address" not in res["answer"]


def test_api_ask_request_body_size_limit(live_server):
    """Wave 3-J: Request body exceeding 32 KiB returns HTTP 413 Payload Too Large."""
    oversized_payload = json.dumps({"question": "x" * 35000}).encode("utf-8")
    req = urllib.request.Request(
        f"{live_server}/api/ask",
        data=oversized_payload,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 413


def test_api_ask_top_k_clamped(live_server, monkeypatch):
    """Wave 3-J: top_k parameter clamped to 1..20, defaulting to TOP_K_RESULTS."""
    recorded = {}

    def fake_ask(question, conversation_history=None, top_k=None, verbose=False):
        recorded["top_k"] = top_k
        return {
            "answer": "Mock answer",
            "in_scope": True,
            "citations": {},
            "source_sections": [],
            "not_covered": False,
        }

    monkeypatch.setattr("src.bot.ask", fake_ask)

    # 1. Exceeds max (999 -> clamped to 20)
    req = urllib.request.Request(
        f"{live_server}/api/ask",
        data=json.dumps({"question": "test", "top_k": 999}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert recorded["top_k"] == 20

    # 2. Below min (-5 -> clamped to 1)
    req = urllib.request.Request(
        f"{live_server}/api/ask",
        data=json.dumps({"question": "test", "top_k": -5}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert recorded["top_k"] == 1

    # 3. Default when omitted -> TOP_K_RESULTS
    req = urllib.request.Request(
        f"{live_server}/api/ask",
        data=json.dumps({"question": "test"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert recorded["top_k"] == TOP_K_RESULTS


