# tests/test_kb_server.py
# Unit tests for agent/kb_server.py — KB HTTP server.
#
# Tests cover:
#   - Health check endpoint
#   - Chat completions (KB hit, out-of-scope, no user message)
#   - Error handling (malformed body, wrong method, wrong path)
#   - Server lifecycle (start, running check, stop)
#   - kb_lookup integration (mocked to verify call-through)

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import urllib.error
from unittest import mock

import pytest

from agent import kb_server
from agent.kb_server import (
    KB_OUT_OF_SCOPE,
    KB_SERVER_PORT,
    _format_chunks,
    _extract_last_user_message,
    _make_response,
    is_kb_server_running,
    start_kb_server,
    stop_kb_server,
)
from agent.kb_lookup import KBChunk


# ── Helpers ────────────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find a free port for testing (avoids hardcoding 18790)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 5.0) -> None:
    """Wait until the server responds on /health or timeout."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(0.05)
    pytest.fail(f"KB server on port {port} did not start within {timeout}s")


def _post(port: int, path: str, body: dict | str) -> tuple[int, dict]:
    """POST to the server and return (status_code, response_json)."""
    url = f"http://127.0.0.1:{port}{path}"
    if isinstance(body, str):
        data = body.encode("utf-8")
    else:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(port: int, path: str) -> tuple[int, dict | None]:
    """GET from the server and return (status_code, response_json)."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, json.loads(body) if body else None


@pytest.fixture
def kb_server_instance():
    """Start and stop a KB server on a free port for each test."""
    port = _find_free_port()

    # Mock is_index_available so the server starts even without a real index
    with mock.patch.object(kb_server, "is_index_available", return_value=True):
        thread = start_kb_server(port=port)
        if thread is None:
            pytest.skip("Could not start KB server")
        _wait_for_server(port)
        yield port
        stop_kb_server()

    # Ensure clean state after test
    if is_kb_server_running():
        stop_kb_server()


# ── Unit tests for pure functions ──────────────────────────────────────────────


class TestMakeResponse:
    def test_structure(self):
        resp = _make_response("hello world")
        assert resp["object"] == "chat.completion"
        assert resp["model"] == "local-kb"
        assert resp["id"].startswith("chatcmpl-kb-")
        choices = resp["choices"]
        assert len(choices) == 1
        assert choices[0]["message"]["role"] == "assistant"
        assert choices[0]["message"]["content"] == "hello world"
        assert choices[0]["finish_reason"] == "stop"

    def test_usage_zero(self):
        resp = _make_response("test")
        assert resp["usage"]["prompt_tokens"] == 0
        assert resp["usage"]["completion_tokens"] == 0

    def test_unique_ids(self):
        r1 = _make_response("a")
        r2 = _make_response("b")
        assert r1["id"] != r2["id"]


class TestFormatChunks:
    def test_single_chunk(self):
        chunk = KBChunk(
            id="c1",
            source="knowledge/install.md",
            section="Installing on Ubuntu",
            text="Run apt install ...",
            score=0.9,
        )
        text = _format_chunks([chunk])
        assert "Based on the CrabCakes knowledge base" in text
        assert "knowledge/install.md" in text
        assert "Installing on Ubuntu" in text
        assert "Run apt install ..." in text

    def test_multiple_chunks(self):
        chunks = [
            KBChunk(id="c1", source="s1", section="a", text="text1", score=0.9),
            KBChunk(id="c2", source="s2", section="b", text="text2", score=0.8),
        ]
        text = _format_chunks(chunks)
        assert "text1" in text
        assert "text2" in text
        assert "s1" in text
        assert "s2" in text

    def test_empty_list(self):
        text = _format_chunks([])
        assert "Based on the CrabCakes knowledge base" in text


class TestExtractLastUserMessage:
    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert _extract_last_user_message(msgs) == "hello"

    def test_last_user_after_system(self):
        msgs = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "install help"},
        ]
        assert _extract_last_user_message(msgs) == "install help"

    def test_multiple_users_returns_last(self):
        msgs = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "second question"},
        ]
        assert _extract_last_user_message(msgs) == "second question"

    def test_no_user_message(self):
        msgs = [{"role": "system", "content": "you are helpful"}]
        assert _extract_last_user_message(msgs) is None

    def test_empty_messages(self):
        assert _extract_last_user_message([]) is None

    def test_none_messages(self):
        assert _extract_last_user_message(None) is None

    def test_empty_content(self):
        msgs = [{"role": "user", "content": ""}]
        assert _extract_last_user_message(msgs) is None

    def test_whitespace_content(self):
        msgs = [{"role": "user", "content": "   "}]
        assert _extract_last_user_message(msgs) is None


# ── HTTP integration tests ─────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check(self, kb_server_instance):
        port = kb_server_instance
        status, body = _get(port, "/health")
        assert status == 200
        assert body == {"status": "ok"}


class TestChatCompletions:
    def test_chat_completions_kb_hit(self, kb_server_instance):
        port = kb_server_instance
        mock_chunks = [
            KBChunk(
                id="c1",
                source="knowledge/install.md",
                section="Installing on Ubuntu",
                text="Run apt install python3-gi python3-gi-cairo",
                score=0.92,
            ),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "local-kb",
                    "messages": [
                        {"role": "user", "content": "How do I install on Ubuntu?"}
                    ],
                },
            )
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert "knowledge/install.md" in content
        assert "Installing on Ubuntu" in content
        assert "apt install" in content
        assert body["model"] == "local-kb"

    def test_chat_completions_out_of_scope(self, kb_server_instance):
        port = kb_server_instance
        with mock.patch.object(kb_server, "kb_lookup", return_value=[]):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "local-kb",
                    "messages": [
                        {"role": "user", "content": "quantum physics equations"}
                    ],
                },
            )
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == KB_OUT_OF_SCOPE

    def test_chat_completions_no_user_message(self, kb_server_instance):
        port = kb_server_instance
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "local-kb",
                "messages": [
                    {"role": "system", "content": "you are a helpful assistant"}
                ],
            },
        )
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == KB_OUT_OF_SCOPE

    def test_chat_completions_malformed_body(self, kb_server_instance):
        port = kb_server_instance
        status, body = _post(port, "/v1/chat/completions", "{not valid json")
        assert status == 400
        assert "error" in body

    def test_chat_completions_wrong_method(self, kb_server_instance):
        port = kb_server_instance
        # GET on /v1/chat/completions → 404 (no GET handler for that path)
        status, _ = _get(port, "/v1/chat/completions")
        assert status == 404

    def test_chat_completions_wrong_path(self, kb_server_instance):
        port = kb_server_instance
        status, body = _post(
            port,
            "/v1/wrong",
            {"model": "local-kb", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert status == 404


class TestServerLifecycle:
    def test_server_lifecycle(self):
        port = _find_free_port()
        try:
            with mock.patch.object(kb_server, "is_index_available", return_value=True):
                thread = start_kb_server(port=port)
                assert thread is not None
                assert is_kb_server_running() is True
                _wait_for_server(port)

                stop_kb_server()
                assert is_kb_server_running() is False
        finally:
            if is_kb_server_running():
                stop_kb_server()

    def test_start_when_port_in_use(self):
        port = _find_free_port()
        # Occupy the port
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        try:
            with mock.patch.object(kb_server, "is_index_available", return_value=True):
                thread = start_kb_server(port=port)
                assert thread is None  # should fail gracefully
                assert is_kb_server_running() is False
        finally:
            blocker.close()

    def test_start_when_index_missing(self):
        port = _find_free_port()
        with mock.patch.object(kb_server, "is_index_available", return_value=False):
            thread = start_kb_server(port=port)
            assert thread is None
            assert is_kb_server_running() is False


class TestConfidenceThreshold:
    """Tests for the top-score confidence threshold.

    Even when kb_lookup returns chunks (passing _KB_MIN_SCORE=0.35),
    if the highest-scoring chunk is below _KB_CONFIDENCE_THRESHOLD (0.55),
    the server returns [KB_OUT_OF_SCOPE].
    """

    def test_weak_match_returns_out_of_scope(self, kb_server_instance):
        """Chunks with top score 0.43 (below 0.55) → [KB_OUT_OF_SCOPE]."""
        port = kb_server_instance
        weak_chunks = [
            KBChunk(id="c1", source="knowledge/setup.md", section="Install",
                    text="some weakly related text", score=0.43),
            KBChunk(id="c2", source="knowledge/features.md", section="Features",
                    text="another weak match", score=0.41),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=weak_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "What is the meaning of life?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == KB_OUT_OF_SCOPE

    def test_strong_match_returns_chunks(self, kb_server_instance):
        """Chunks with top score 0.72 (above 0.55) → formatted KB content."""
        port = kb_server_instance
        strong_chunks = [
            KBChunk(id="c1", source="knowledge/setup.md", section="Install",
                    text="Run apt install to install crabcakes", score=0.72),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=strong_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How do I install?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content != KB_OUT_OF_SCOPE
        assert "knowledge/setup.md" in content
        assert "apt install" in content

    def test_boundary_score_at_threshold_returns_chunks(self, kb_server_instance):
        """Top score exactly at 0.55 → returns chunks (>= threshold)."""
        port = kb_server_instance
        boundary_chunks = [
            KBChunk(id="c1", source="knowledge/test.md", section="Test",
                    text="boundary test content", score=0.55),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=boundary_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "test question"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content != KB_OUT_OF_SCOPE

    def test_boundary_score_just_below_returns_out_of_scope(self, kb_server_instance):
        """Top score 0.549 (just below 0.55) → [KB_OUT_OF_SCOPE]."""
        port = kb_server_instance
        just_below_chunks = [
            KBChunk(id="c1", source="knowledge/test.md", section="Test",
                    text="almost confident enough", score=0.549),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=just_below_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "test question"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == KB_OUT_OF_SCOPE


# ── Synthesis tests ───────────────────────────────────────────────────────────


class TestSynthesis:
    """Tests for the synthesis layer in the local-kb provider.

    The synthesis layer is opt-in via the CRABCAKES_KB_SYNTHESIS env var
    (default ON). Each test mocks _try_synthesize to verify both the
    happy path and the fallback paths.
    """

    def test_synthesis_success_returns_synthesized(self, kb_server_instance, monkeypatch):
        """_try_synthesize returns a string → response content is that string."""
        port = kb_server_instance
        monkeypatch.setattr(kb_server, "_try_synthesize",
                            lambda q, c: "Synthesized: do `apt install`.")
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How to install?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == "Synthesized: do `apt install`."
        assert "**Source:**" not in content  # NOT the raw formatted chunks

    def test_synthesis_failure_returns_raw_chunks(self, kb_server_instance, monkeypatch):
        """_try_synthesize returns None → response content is _format_chunks output."""
        port = kb_server_instance
        monkeypatch.setattr(kb_server, "_try_synthesize", lambda q, c: None)
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How to install?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert "Based on the CrabCakes knowledge base" in content
        assert "knowledge/install.md" in content

    def test_synthesis_disabled_by_env_var(self, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=0 → _try_synthesize returns None immediately."""
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "0")
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_enabled_by_default(self, monkeypatch):
        """No env var set → _synthesis_enabled() returns True."""
        monkeypatch.delenv("CRABCAKES_KB_SYNTHESIS", raising=False)
        assert kb_server._synthesis_enabled() is True

    def test_synthesis_env_var_one_enables(self, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=1 → enabled."""
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "1")
        assert kb_server._synthesis_enabled() is True

    def test_synthesis_env_var_zero_disables(self, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=0 → disabled."""
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "0")
        assert kb_server._synthesis_enabled() is False

    def test_synthesis_handles_timeout(self, monkeypatch):
        """_try_synthesize catches TimeoutError → returns None."""
        def fake_urlopen(req, timeout):
            raise TimeoutError("synthesis timed out")
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_http_error(self, monkeypatch):
        """_try_synthesize catches HTTPError → returns None."""
        req = urllib.request.Request("http://127.0.0.1:1/")
        def fake_urlopen(urlopen_req, timeout):
            raise urllib.error.HTTPError(urlopen_req.full_url, 503, "Service Unavailable",
                                         {}, None)
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_url_error(self, monkeypatch):
        """_try_synthesize catches URLError (DNS/network) → returns None."""
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("Name or service not known")
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_body_level_error(self, monkeypatch):
        """Endpoint returns {"error": "..."} → returns None."""
        class FakeResp:
            def read(self):
                return b'{"error": "rate limited"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp())
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_empty_response(self, monkeypatch):
        """Endpoint returns {"response": ""} → returns None."""
        class FakeResp:
            def read(self):
                return b'{"response": ""}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp())
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_error_prefixed_string(self, monkeypatch):
        """Endpoint returns {"response": "Error: ..."} → returns None."""
        class FakeResp:
            def read(self):
                return b'{"response": "Error: something went wrong"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp())
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_passes_question_and_chunks(self, kb_server_instance, monkeypatch):
        """_try_synthesize is called with (question, chunks) from the request."""
        port = kb_server_instance
        captured = {}
        def fake_synthesize(q, c):
            captured["question"] = q
            captured["chunks"] = c
            return "synthesized"
        monkeypatch.setattr(kb_server, "_try_synthesize", fake_synthesize)
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How to install?"}],
            })
        assert captured["question"] == "How to install?"
        assert len(captured["chunks"]) == 1
        assert captured["chunks"][0].source == "knowledge/install.md"


class TestKBLookupIntegration:
    def test_kb_server_uses_kb_lookup(self, kb_server_instance):
        port = kb_server_instance
        mock_chunks = [
            KBChunk(
                id="c1",
                source="knowledge/install.md",
                section="Install",
                text="Install GTK4 with apt",
                score=0.95,
            ),
        ]
        with mock.patch.object(
            kb_server, "kb_lookup", return_value=mock_chunks
        ) as mock_lookup:
            _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "local-kb",
                    "messages": [
                        {"role": "system", "content": "system prompt"},
                        {"role": "user", "content": "How do I install?"},
                    ],
                },
            )
            mock_lookup.assert_called_once()
            call_args = mock_lookup.call_args
            # First positional arg should be the last user message
            assert call_args[0][0] == "How do I install?"

    def test_kb_lookup_exception_returns_out_of_scope(self, kb_server_instance):
        port = kb_server_instance
        with mock.patch.object(
            kb_server, "kb_lookup", side_effect=RuntimeError("boom")
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "local-kb",
                    "messages": [
                        {"role": "user", "content": "anything"}
                    ],
                },
            )
        assert status == 200
        assert body["choices"][0]["message"]["content"] == KB_OUT_OF_SCOPE
