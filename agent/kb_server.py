# agent/kb_server.py
# Local HTTP server that wraps kb_lookup and mimics the OpenAI
# /v1/chat/completions API. The agent runtime calls it as a standard
# OpenAI-compatible provider — zero runtime changes needed.
#
# Architecture:
#   - Pure stdlib (http.server, threading, json, uuid)
#   - No GTK, no network at import time
#   - Server starts explicitly via start_kb_server()
#   - Binds to 127.0.0.1 only (no external access)
#   - Single-threaded request handling (KB lookup is <500ms)
#
# Public API:
#   start_kb_server(port=18790) -> threading.Thread | None
#   stop_kb_server() -> None
#   is_kb_server_running() -> bool
#   KB_SERVER_PORT = 18790
#   KB_OUT_OF_SCOPE = "[KB_OUT_OF_SCOPE]"

from __future__ import annotations

import json
import logging
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from agent.kb_lookup import kb_lookup, is_index_available

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

KB_SERVER_PORT = 18790
KB_OUT_OF_SCOPE = "[KB_OUT_OF_SCOPE]"

# Higher threshold than kb_lookup's default (0.3) to reduce false positives.
_KB_MIN_SCORE = 0.35
_KB_TOP_K = 5

# Top-score confidence threshold. Even if chunks pass _KB_MIN_SCORE, if the
# highest-scoring chunk is below this value, the question is treated as
# out-of-scope. This prevents weak false-positive matches (e.g. score 0.43)
# from returning irrelevant KB content for questions the KB can't actually answer.
_KB_CONFIDENCE_THRESHOLD = 0.55

# ── Module-level server state ──────────────────────────────────────────────────

_server: HTTPServer | None = None
_server_thread: threading.Thread | None = None
_lock = threading.Lock()


# ── Response builders ──────────────────────────────────────────────────────────


def _make_response(content: str) -> dict[str, Any]:
    """Build an OpenAI Chat Completions response dict."""
    return {
        "id": f"chatcmpl-kb-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": "local-kb",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }


def _make_error_response(message: str) -> dict[str, Any]:
    """Build an OpenAI-style error dict."""
    return {"error": {"message": message}}


def _format_chunks(chunks: list) -> str:
    """Format KB chunks into a single content string."""
    parts = ["Based on the CrabCakes knowledge base:\n"]
    for chunk in chunks:
        parts.append(
            f"\n---\n**Source:** {chunk.source} :: {chunk.section}\n\n{chunk.text}\n"
        )
    return "".join(parts)


def _extract_last_user_message(messages: list[dict]) -> str | None:
    """Extract the last user message from an OpenAI messages array.

    Returns None if no user message is found or content is empty.
    """
    if not isinstance(messages, list):
        return None
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                # Strip relay prefixes like "[Project Chat asks]: " that are added
                # by /ask forwarding. These prefixes skew the embedding and cause
                # false-positive KB matches (e.g. "Project Chat asks" matches
                # project/agent KB content even when the actual question is
                # out-of-scope like "What is quantum physics?").
                import re
                content = re.sub(r"^\[.*?\s+asks\]:\s*", "", content)
                return content.strip() if content.strip() else None
    return None


# ── Request handler ────────────────────────────────────────────────────────────


class _KBRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the KB server."""

    # Suppress default per-request logging (too noisy for a localhost server).
    def log_message(self, format: str, *args: Any) -> None:
        pass

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, _make_error_response("Not found"))

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send_json(404, _make_error_response("Not found"))
            return

        # Read and parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, _make_error_response("Empty request body"))
            return

        try:
            raw_body = self.rfile.read(content_length)
            body = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json(400, _make_error_response(f"Malformed JSON: {e}"))
            return

        if not isinstance(body, dict):
            self._send_json(400, _make_error_response("Request body must be a JSON object"))
            return

        # Extract the last user message
        messages = body.get("messages", [])
        question = _extract_last_user_message(messages)

        if question is None:
            # No user message → out of scope
            self._send_json(200, _make_response(KB_OUT_OF_SCOPE))
            return

        # Query the KB
        try:
            chunks = kb_lookup(
                question,
                top_k=_KB_TOP_K,
                min_score=_KB_MIN_SCORE,
            )
        except Exception as e:
            logger.warning("kb_server: kb_lookup failed: %s; returning out-of-scope", e)
            chunks = []

        if not chunks:
            self._send_json(200, _make_response(KB_OUT_OF_SCOPE))
            return

        # Confidence check: if the best chunk's score is below the high-confidence
        # threshold, treat as out-of-scope. This catches weak false-positive matches
        # that pass _KB_MIN_SCORE but aren't actually relevant.
        top_score = chunks[0].score if chunks else 0.0
        if top_score < _KB_CONFIDENCE_THRESHOLD:
            logger.debug(
                "kb_server: top score %.3f < %.3f confidence threshold — returning out-of-scope for %r",
                top_score, _KB_CONFIDENCE_THRESHOLD, question[:80],
            )
            self._send_json(200, _make_response(KB_OUT_OF_SCOPE))
            return

        content = _format_chunks(chunks)
        self._send_json(200, _make_response(content))

    # ── PUT / DELETE / etc → 405 ──────────────────────────────────────────────

    def do_PUT(self) -> None:
        self._send_json(405, _make_error_response("Method not allowed"))

    def do_DELETE(self) -> None:
        self._send_json(405, _make_error_response("Method not allowed"))

    def do_PATCH(self) -> None:
        self._send_json(405, _make_error_response("Method not allowed"))

    # ── Helper ────────────────────────────────────────────────────────────────

    def _send_json(self, status: int, body: dict) -> None:
        """Send a JSON response with the given status code."""
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


# ── Public lifecycle API ───────────────────────────────────────────────────────


def start_kb_server(port: int = KB_SERVER_PORT) -> threading.Thread | None:
    """Start the KB HTTP server as a daemon thread.

    Returns the thread if started, or None if already running or if the
    port is unavailable. Safe to call multiple times — subsequent calls
    are no-ops if the server is already running.

    Args:
        port: Port to listen on (default 18790).

    Returns:
        The daemon thread, or None if already running or failed to start.
    """
    global _server, _server_thread

    with _lock:
        if _server is not None:
            logger.debug("kb_server: already running on port %d", port)
            return _server_thread

        if not is_index_available():
            logger.info("kb_server: KB index not available, not starting server")
            return None

        try:
            server = HTTPServer(("127.0.0.1", port), _KBRequestHandler)
        except OSError as e:
            logger.warning("kb_server: failed to bind 127.0.0.1:%d: %s", port, e)
            return None

        thread = threading.Thread(
            target=server.serve_forever,
            name=f"kb-server-{port}",
            daemon=True,
        )
        thread.start()

        _server = server
        _server_thread = thread
        logger.info("kb_server: listening on http://127.0.0.1:%d", port)
        return thread


def stop_kb_server() -> None:
    """Stop the KB HTTP server if running.

    Calls server.shutdown() to cleanly stop the serve_forever loop,
    then server.server_close() to release the socket.
    """
    global _server, _server_thread

    with _lock:
        if _server is None:
            return

        logger.info("kb_server: shutting down")
        try:
            _server.shutdown()
            _server.server_close()
        except Exception as e:
            logger.warning("kb_server: error during shutdown: %s", e)
        finally:
            _server = None
            _server_thread = None


def is_kb_server_running() -> bool:
    """Return True if the KB server is currently running."""
    with _lock:
        return _server is not None
