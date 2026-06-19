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
import os
import threading
import urllib.request
import urllib.error
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

# ── Synthesis layer (KB Enhancement) ──────────────────────────────────────────

# Free, no-auth Llama endpoint verified 2026-06-17. If the endpoint changes,
# update this constant — the rest of the synthesis code is endpoint-agnostic.
# Read at call time (not import time) so env var changes take effect without
# process restart — adversarial audit BUG #2.
_SYNTHESIS_ENDPOINT_DEFAULT = "https://devtoolbox-api.devtoolbox-api.workers.dev/ai/generate"


def _get_synthesis_url() -> str:
    """Return the synthesis endpoint URL, overridable via CRABCAKES_KB_SYNTHESIS_URL."""
    return os.environ.get("CRABCAKES_KB_SYNTHESIS_URL", _SYNTHESIS_ENDPOINT_DEFAULT)

# Hard timeout on the synthesis call. 3.0s = 6× the measured ~500ms latency
# of the free endpoint. Tuned to keep Auxilium feeling responsive even when
# the endpoint is slow. If the call takes longer, we time out and fall back
# to the raw formatted chunks.
_SYNTHESIS_TIMEOUT_SECONDS = 3.0

# Toggle: "0" disables synthesis (returns raw chunks as today). Anything else
# (including unset, "1", "true", "yes", typo'd values) enables it. Default ON.
def _synthesis_enabled() -> bool:
    """Return True unless CRABCAKES_KB_SYNTHESIS=0 is set in the environment."""
    return os.environ.get("CRABCAKES_KB_SYNTHESIS", "1") != "0"

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


def _try_synthesize(question: str, chunks: list, formatted_chunks: str | None = None) -> str | None:
    """Synthesize a friendly answer from KB chunks using the free Llama endpoint.

    Returns the synthesized string on success, or None on ANY failure
    (timeout, network error, HTTP 4xx/5xx, body-level error, empty response,
    response starting with "Error:"). The caller falls back to the raw
    formatted chunks when this returns None.

    Args:
        question: The user's question (last user message from the request).
        chunks: The KBChunk list returned by kb_lookup (already passed
            the confidence threshold).
        formatted_chunks: Pre-formatted chunks string (avoids double-call —
            adversarial audit BUG #3). If None, _format_chunks is called internally.

    Returns:
        Synthesized answer string, or None on any failure.

    Note:
        The endpoint takes a single concatenated prompt string, not an
        OpenAI-shaped messages array. We build the prompt as:
          [instruction prefix] + [_format_chunks(chunks)] + [user question]
    """
    if not _synthesis_enabled():
        return None

    # Guard against bad input (adversarial audit BUG #6 — docstring says
    # "returns None on ANY failure" but None/invalid chunks would raise).
    if not isinstance(question, str) or not question:
        return None
    if not isinstance(chunks, list) or not chunks:
        return None

    # Build the synthesis prompt. Mirrors the system prompt's intent at
    # prompts/system/auxilium.md:73-85 (Phase 2 — LLM Synthesis Mode):
    # ground the answer in the chunks, be concise, no "Based on the KB" preface.
    if formatted_chunks is None:
        formatted_chunks = _format_chunks(chunks)
    prompt = (
        "You are a helpful assistant for a software project. "
        "Use the following knowledge base context to answer the user's question. "
        "Be concise and friendly. If the context does not contain the answer, say so.\n\n"
        f"{formatted_chunks}\n\n"
        f"User question: {question}"
    )

    payload = json.dumps({"prompt": prompt, "max_tokens": 500}).encode("utf-8")
    req = urllib.request.Request(
        _get_synthesis_url(),
        data=payload,
        headers={
            "Content-Type": "application/json",
            # Cloudflare blocks requests with no User-Agent (returns 403).
            # urllib.request sends "Python-urllib/3.x" by default, but
            # being explicit avoids future surprises.
            "User-Agent": "CrabCakes-KB-Synthesis/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_SYNTHESIS_TIMEOUT_SECONDS) as resp:
            body = resp.read()
            parsed = json.loads(body)
    except (urllib.error.URLError, OSError) as e:
        # Network error, timeout (TimeoutError ⊂ OSError), DNS failure,
        # connection refused, HTTP error (HTTPError ⊂ URLError)
        logger.debug("kb_server: synthesis call failed: %s; falling back to raw chunks", e)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Endpoint returned non-JSON or unreadable bytes
        logger.debug("kb_server: synthesis response unparseable: %s; falling back", e)
        return None

    # Body-level error: {"error": "..."} or {"error": {"message": "..."}}
    if isinstance(parsed, dict) and "error" in parsed:
        logger.debug("kb_server: synthesis body-level error: %s; falling back", parsed["error"])
        return None

    # Extract the response field. Defensive against missing field or non-string.
    response_text = parsed.get("response", "") if isinstance(parsed, dict) else ""
    if not isinstance(response_text, str):
        logger.debug("kb_server: synthesis response not a string (type=%s); falling back",
                     type(response_text).__name__)
        return None

    response_text = response_text.strip()
    if not response_text:
        logger.debug("kb_server: synthesis returned empty string; falling back")
        return None

    # Defensive: if the model returned an error-shaped string, fall back.
    # Catches cases like "Error: ..." or "I cannot answer that..." (false-positive risk
    # is low because the prompt is a synthesis instruction, not an open-ended one).
    if response_text.lower().startswith("error:"):
        logger.debug("kb_server: synthesis returned error-shaped string; falling back")
        return None

    return response_text


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
                return content
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
        elif self.path == "/agents":  # LOW-3: list all registered agent ids
            try:
                from agent.special_agents import get_special_agents
                agents = get_special_agents()
                agent_ids = [a.display_name for a in agents]
                self._send_json(200, {"agents": agent_ids})
            except Exception:
                self._send_json(200, {"agents": []})
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

        # Format chunks once — reused by both synthesis prompt and fallback
        # (adversarial audit BUG #3: was calling _format_chunks twice on failure path).
        formatted = _format_chunks(chunks)
        # Attempt synthesis first; fall back to formatted chunks on any failure.
        synthesized = _try_synthesize(question, chunks, formatted_chunks=formatted)
        content = synthesized if synthesized is not None else formatted
        self._send_json(200, _make_response(content))

    # ── PUT / DELETE / etc → 405 ──────────────────────────────────────────────

    def do_PUT(self) -> None:
        self._send_json(405, _make_error_response("Method not allowed"))

    def do_DELETE(self) -> None:  # LOW-2: delete agent by id
        import re as _re
        _m = _re.match(r"/agents/([^/]+)", self.path)
        if not _m:
            self._send_json(404, _make_error_response("Not found"))
            return
        agent_id = _m.group(1)
        try:
            from agent.special_agents import unregister_special_agent
            unregister_special_agent(agent_id)
            logger.info("kb_server: deleted agent %s", agent_id)
            self._send_json(204, {})
        except Exception as e:
            logger.warning("kb_server: failed to delete agent %s: %s", agent_id, e)
            self._send_json(500, _make_error_response(f"Failed to delete agent: {e}"))

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
            # A-10: Clear error message with address, OS error, and hint
            import errno as _errno
            _hint = (
                f"  Hint: set CRABCAKES_KB_PORT to an available port, "
                f"or stop the process using port {port}."
            )
            if hasattr(e, "errno") and e.errno == _errno.EADDRINUSE:
                logger.error(
                    "kb_server: cannot bind 127.0.0.1:%d — address already in use "
                    "(errno %d: %s).%s",
                    port, e.errno, e.strerror, _hint,
                )
            else:
                logger.error(
                    "kb_server: cannot bind 127.0.0.1:%d — %s (errno %s).%s",
                    port, e.strerror or str(e),
                    getattr(e, "errno", "?"), _hint,
                )
            return None

        thread = threading.Thread(
            target=server.serve_forever,
            name=f"kb-server-{port}",
            daemon=True,
        )
        thread.start()

        _server = server
        _server_thread = thread
        _bound_addr = server.server_address
        logger.info("kb_server: listening on http://%s:%d (bound to %s)",
                     _bound_addr[0], _bound_addr[1], _bound_addr)  # LOW-7
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
