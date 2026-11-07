"""
Lightweight, Multi-threaded HTTP Server for Pakistan Law Bot Web UI.

Provides REST API endpoints:
  - GET  /api/laws   : metadata for all loaded laws
  - GET  /api/stats  : total indexed chunks, model name, active laws
  - POST /api/ask    : RAG query execution with conversation memory
  - GET  /*          : static files from static/ directory
"""

import sys
import json
import mimetypes
from pathlib import Path
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

from src.config import PROJECT_ROOT, LLM_MODEL, EMBEDDING_MODEL, TOP_K_RESULTS
from src import law_registry as registry

STATIC_DIR = PROJECT_ROOT / "static"
MAX_REQUEST_BODY_BYTES = 32 * 1024  # 32 KiB limit (Wave 3-J)


class LawBotHandler(SimpleHTTPRequestHandler):
    """Custom request handler with REST API and static file serving."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/laws":
            self._handle_api_laws()
        elif path == "/api/stats":
            self._handle_api_stats()
        elif path == "/api/health":
            self._send_json({"status": "ok", "app": "Pakistan Law Bot"})
        else:
            # Fall back to static files
            if path == "/" or not path:
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ask":
            self._handle_api_ask()
        elif path in ("/api/webhook/twilio", "/api/whatsapp"):
            self._handle_api_whatsapp()
        else:
            self._send_json({"error": "Endpoint not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_api_laws(self):
        """Return all loaded laws with metadata and section counts."""
        try:
            loaded = registry.get_loaded_laws()
            laws_data = []
            for law_id, meta in loaded.items():
                laws_data.append({
                    "id": law_id,
                    "title": meta.get("title"),
                    "short_title": meta.get("short_title"),
                    "year": meta.get("year"),
                    "category": meta.get("category"),
                    "jurisdiction": meta.get("jurisdiction"),
                    "expected_section_count": meta.get("expected_section_count"),
                    "source_url": meta.get("source_url"),
                    "amended_up_to": meta.get("amended_up_to"),
                    "hint_keywords": meta.get("hint_keywords", [])[:8],
                })
            self._send_json({"laws": laws_data, "count": len(laws_data)})
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_api_stats(self):
        """Return system statistics."""
        try:
            from src import vector_store as vs
            col = vs.get_or_create_collection()
            count = col.count()
            loaded_laws = registry.get_loaded_laws()
            self._send_json({
                "indexed_chunks": count,
                "loaded_laws_count": len(loaded_laws),
                "llm_model": LLM_MODEL,
                "embedding_model": EMBEDDING_MODEL,
                "status": "ready" if count > 0 else "empty",
            })
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_api_ask(self):
        """Process a legal query with body size cap and clamped top_k (Wave 3-J)."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self._send_json({"error": "Empty body"}, status=HTTPStatus.BAD_REQUEST)
                return

            if content_len > MAX_REQUEST_BODY_BYTES:
                self._send_json(
                    {"error": f"Request body exceeds {MAX_REQUEST_BODY_BYTES} bytes limit"},
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return

            body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(body)

            question = data.get("question", "").strip()
            history = data.get("history", [])

            # Clamp top_k to 1..20; default from config.TOP_K_RESULTS
            raw_top_k = data.get("top_k", TOP_K_RESULTS)
            try:
                top_k = max(1, min(20, int(raw_top_k)))
            except (ValueError, TypeError):
                top_k = TOP_K_RESULTS

            if not question:
                self._send_json({"error": "Question is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            from src.bot import ask
            result = ask(question, conversation_history=history, top_k=top_k, verbose=False)

            self._send_json({
                "question": question,
                "answer": result.get("answer", ""),
                "in_scope": result.get("in_scope", True),
                "citations": result.get("citations", {}),
                "source_sections": result.get("source_sections", []),
                "not_covered": result.get("not_covered", False),
            })
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_api_whatsapp(self):
        """Process incoming WhatsApp/Twilio webhook and reply with TwiML XML (Phase 3 Task 3-4)."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self._send_twiml("Please send a legal question regarding Pakistani law.")
                return

            if content_len > MAX_REQUEST_BODY_BYTES:
                self._send_twiml("Request payload too large.")
                return

            body = self.rfile.read(content_len).decode("utf-8")
            from urllib.parse import parse_qs
            post_data = parse_qs(body)
            # Twilio delivers message in "Body" field
            raw_question = post_data.get("Body", [""])[0].strip()

            if not raw_question:
                self._send_twiml("Please send a valid legal question regarding Pakistani law.")
                return

            from src.bot import ask
            result = ask(raw_question, verbose=False)
            answer = result.get("answer", "")

            # Truncate answer to 1550 chars if exceeding WhatsApp limits while keeping disclaimer
            if len(answer) > 1550:
                answer = answer[:1500] + "...\n\n[Response truncated for WhatsApp]"

            self._send_twiml(answer)
        except Exception as e:
            self._send_twiml(f"An error occurred while retrieving legal information: {str(e)}")

    def _send_twiml(self, message: str, status: HTTPStatus = HTTPStatus.OK):
        """Send a standard Twilio TwiML XML response."""
        import xml.sax.saxutils as saxutils
        escaped = saxutils.escape(message)
        xml_resp = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'    <Message>{escaped}</Message>\n'
            '</Response>'
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(xml_resp)))
        self.end_headers()
        self.wfile.write(xml_resp)

    def _send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Localhost-only server: CORS * allows local browser interactions
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Clean terminal logging
        sys.stdout.write(f"  [Web] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the Pakistan Law Bot HTTP server."""
    if not STATIC_DIR.exists():
        STATIC_DIR.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((host, port), LawBotHandler)
    url = f"http://{host}:{port}"
    print()
    print("=" * 64)
    print(f"  🏛️  PAKISTAN LAW BOT — Web Interface Ready")
    print(f"  URL: {url}")
    print("=" * 64)
    print("  Serving static assets from:", STATIC_DIR)
    print("  Press Ctrl+C to stop server.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port=port)
