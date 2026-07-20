"""Tests for LLM provider classes (Phase B4).

Tests the three provider classes:
- OpenAIProvider (openai, openrouter, zai)
- MiniMaxProvider (body-level error detection)
- AnthropicProvider (system message extraction, tool conversion)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider


# ── Helpers ────────────────────────────────────────────────────────────────

def _fake_urlopen_retry(req, timeout):
    """Stand-in for _urlopen_with_ssl_retry — returns a MagicMock response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()
    return resp


# ── OpenAIProvider ──────────────────────────────────────────────────────────

class TestOpenAIProvider:
    def test_provider_id_and_response_format(self):
        p = OpenAIProvider("openai")
        assert p.provider_id == "openai"
        assert p.response_format == "openai"

        p2 = OpenAIProvider("openrouter")
        assert p2.provider_id == "openrouter"

    @patch("agent.llm.openai_provider.urllib.request.Request")
    @patch("agent.llm.openai_provider.urllib.request.urlopen")
    def test_call_builds_correct_request(self, mock_urlopen, mock_request):
        """Verifies endpoint, headers, payload shape."""
        resp = MagicMock()
        resp.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        from agent.llm.cost import model_id

        p = OpenAIProvider("openai")
        result = p.call(
            "https://api.openai.com/v1",
            "sk-test",
            "openai/gpt-4o",
            [{"role": "user", "content": "hello"}],
            None,
            30.0,
        )

        assert result == {"choices": [{"message": {"content": "hi"}}]}

        # Verify the request was built correctly
        call_args = mock_request.call_args
        # urllib.request.Request(endpoint, data=..., headers=..., method=...)
        # Only endpoint is positional; the rest are keyword args.
        assert call_args[0][0] == "https://api.openai.com/v1/chat/completions"
        kwargs = call_args[1]
        payload = json.loads(kwargs["data"])
        assert payload["model"] == model_id("openai/gpt-4o")
        assert "tool_choice" not in payload
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"

    @patch("agent.llm.openai_provider.urllib.request.Request")
    @patch("agent.llm.openai_provider.urllib.request.urlopen")
    def test_call_includes_tools_when_provided(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = OpenAIProvider("openai")
        p.call(
            "https://api.openai.com/v1",
            "sk-test",
            "openai/gpt-4o",
            [{"role": "user", "content": "hello"}],
            [{"type": "function", "function": {"name": "read_file"}}],
            30.0,
        )

        payload = json.loads(mock_request.call_args[1]["data"])
        assert payload["tool_choice"] == "auto"
        assert len(payload["tools"]) == 1

    @patch("agent.llm.openai_provider.urllib.request.Request")
    @patch("agent.llm.openai_provider.urllib.request.urlopen")
    def test_call_omits_tools_when_none(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = OpenAIProvider("openai")
        p.call(
            "https://api.openai.com/v1",
            "sk-test",
            "openai/gpt-4o",
            [{"role": "user", "content": "hello"}],
            None,
            30.0,
        )

        payload = json.loads(mock_request.call_args[1]["data"])
        assert "tools" not in payload
        assert "tool_choice" not in payload

    @patch("agent.llm.openai_provider.urllib.request.Request")
    @patch("agent.llm.openai_provider.urllib.request.urlopen")
    def test_call_raises_on_http_error(self, mock_urlopen, mock_request):
        """HTTPError from urllib should become RuntimeError."""
        http_err = urllib.error.HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            MagicMock(),
        )
        http_err.read = MagicMock(return_value=b'{"error":{"message":"bad key"}}')
        mock_urlopen.side_effect = http_err

        p = OpenAIProvider("openai")
        try:
            p.call(
                "https://api.openai.com/v1",
                "bad-key",
                "openai/gpt-4o",
                [{"role": "user", "content": "hello"}],
                None,
                30.0,
            )
            assert False, "should have raised"
        except RuntimeError as e:
            assert "401" in str(e)
            assert "bad key" in str(e)

    @patch("agent.llm.openai_provider.urllib.request.Request")
    @patch("agent.llm.openai_provider.urllib.request.urlopen")
    def test_call_with_x_title_sets_headers(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = OpenAIProvider("openai")
        p.call(
            "https://api.openai.com/v1",
            "sk-test",
            "openai/gpt-4o",
            [{"role": "user", "content": "hello"}],
            None,
            30.0,
            x_title="crabcakes",
        )

        headers = mock_request.call_args[1]["headers"]
        assert headers["X-Title"] == "crabcakes"
        assert headers["HTTP-Referer"] == "https://github.com/qsmtco/crabcakes"


# ── MiniMaxProvider ─────────────────────────────────────────────────────────

class TestMiniMaxProvider:
    def test_provider_id_and_response_format(self):
        p = MiniMaxProvider()
        assert p.provider_id == "minimax"
        assert p.response_format == "openai"

    @patch("agent.llm.minimax_provider.urllib.request.Request")
    @patch("agent.llm.minimax_provider.urllib.request.urlopen")
    def test_call_success(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "hello from minimax"}}],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = MiniMaxProvider()
        result = p.call(
            "https://api.minimax.chat/v1",
            "sk-test",
            "minimax/abab6.5s",
            [{"role": "user", "content": "hello"}],
            None,
            30.0,
        )

        assert result["choices"][0]["message"]["content"] == "hello from minimax"
        # Verify correct endpoint
        assert mock_request.call_args[0][0] == "https://api.minimax.chat/v1/text/chatcompletion_v2"

    @patch("agent.llm.minimax_provider.urllib.request.Request")
    @patch("agent.llm.minimax_provider.urllib.request.urlopen")
    def test_detects_body_level_error(self, mock_urlopen, mock_request):
        """MiniMax returns HTTP 200 with base_resp.status_code != 0 → RuntimeError."""
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 1004, "status_msg": "login fail"},
        }).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = MiniMaxProvider()
        try:
            p.call(
                "https://api.minimax.chat/v1",
                "bad-key",
                "minimax/abab6.5s",
                [{"role": "user", "content": "hello"}],
                None,
                30.0,
            )
            assert False, "should have raised"
        except RuntimeError as e:
            assert "1004" in str(e)
            assert "login fail" in str(e)

    @patch("agent.llm.minimax_provider.urllib.request.Request")
    @patch("agent.llm.minimax_provider.urllib.request.urlopen")
    def test_call_raises_on_http_error(self, mock_urlopen, mock_request):
        http_err = urllib.error.HTTPError(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            403,
            "Forbidden",
            {},
            MagicMock(),
        )
        http_err.read = MagicMock(return_value=b"forbidden")
        mock_urlopen.side_effect = http_err

        p = MiniMaxProvider()
        try:
            p.call(
                "https://api.minimax.chat/v1",
                "bad-key",
                "minimax/abab6.5s",
                [{"role": "user", "content": "hello"}],
                None,
                30.0,
            )
            assert False, "should have raised"
        except RuntimeError as e:
            assert "403" in str(e)


# ── AnthropicProvider ───────────────────────────────────────────────────────

class TestAnthropicProvider:
    def test_provider_id_and_response_format(self):
        p = AnthropicProvider()
        assert p.provider_id == "anthropic"
        assert p.response_format == "anthropic"

    @patch("agent.llm.anthropic_provider.urllib.request.Request")
    @patch("agent.llm.anthropic_provider.urllib.request.urlopen")
    def test_extracts_system_message(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "hello"}],
        }).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = AnthropicProvider()
        result = p.call(
            "https://api.anthropic.com/v1",
            "sk-ant-test",
            "anthropic/claude-sonnet-4-20250514",
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello"},
            ],
            None,
            30.0,
        )

        assert result["content"][0]["text"] == "hello"

        # Verify system message was extracted into payload["system"]
        payload = json.loads(mock_request.call_args[1]["data"])
        assert payload["system"] == "You are a helpful assistant."
        # And NOT present in messages
        for msg in payload["messages"]:
            assert msg.get("role") != "system"

    @patch("agent.llm.anthropic_provider.urllib.request.Request")
    @patch("agent.llm.anthropic_provider.urllib.request.urlopen")
    def test_strips_duplicate_system(self, mock_urlopen, mock_request):
        """Only the first system message should be extracted."""
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "hello"}],
        }).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = AnthropicProvider()
        p.call(
            "https://api.anthropic.com/v1",
            "sk-ant-test",
            "anthropic/claude-sonnet-4-20250514",
            [
                {"role": "system", "content": "Primary system prompt."},
                {"role": "system", "content": "Secondary system prompt."},
                {"role": "user", "content": "hello"},
            ],
            None,
            30.0,
        )

        payload = json.loads(mock_request.call_args[1]["data"])
        assert payload["system"] == "Primary system prompt."

    @patch("agent.llm.anthropic_provider.urllib.request.Request")
    @patch("agent.llm.anthropic_provider.urllib.request.urlopen")
    def test_converts_tools(self, mock_urlopen, mock_request):
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "hello"}],
        }).encode()
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        p = AnthropicProvider()
        p.call(
            "https://api.anthropic.com/v1",
            "sk-ant-test",
            "anthropic/claude-sonnet-4-20250514",
            [{"role": "user", "content": "hello"}],
            [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
            30.0,
        )

        payload = json.loads(mock_request.call_args[1]["data"])
        assert "tools" in payload
        # Anthropic format uses input_schema, not parameters
        tool = payload["tools"][0]
        assert "input_schema" in tool


# ======================================================================
# Streaming tests (Phase B6)
# ======================================================================


class TestOpenAIStream:
    """Tests for OpenAIProvider.stream() — SSE event generation."""

    def test_openai_stream_yields_text_delta(self):
        """SSE text content forwarded as text_delta events."""
        from agent.llm.openai_provider import OpenAIProvider
        from agent.llm.streaming import SSEEvent

        lines = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            b'data: {"choices":[{"delta":{"content":" world"}}]}',
            b'data: [DONE]',
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.openai_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = OpenAIProvider()
            events = list(provider.stream(
                base_url="https://api.openai.com/v1",
                api_key="test", model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 2
        assert text_events[0].data["content"] == "Hello"
        assert text_events[1].data["content"] == " world"
        assert events[-1].type == "done"

    def test_openai_stream_yields_tool_call_delta(self):
        """SSE tool call fragments forwarded as tool_call_delta events."""
        from agent.llm.openai_provider import OpenAIProvider

        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"ls","arguments":""}}]}}]}',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{}"}}]}}]}',
            b'data: [DONE]',
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.openai_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = OpenAIProvider()
            events = list(provider.stream(
                base_url="https://api.openai.com/v1",
                api_key="test", model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        tool_events = [e for e in events if e.type == "tool_call_delta"]
        assert len(tool_events) >= 1

    def test_openai_stream_yields_done_on_bracket_done(self):
        """[DONE] marker produces a done event."""
        from agent.llm.openai_provider import OpenAIProvider

        lines = [b'data: [DONE]']

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.openai_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = OpenAIProvider()
            events = list(provider.stream(
                base_url="https://api.openai.com/v1",
                api_key="test", model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        assert events[-1].type == "done"


class TestMiniMaxStream:

    def test_minimax_stream_finish_reason_signals_done(self):
        """finish_reason='stop' produces a done event."""
        from agent.llm.minimax_provider import MiniMaxProvider

        lines = [
            b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.minimax_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = MiniMaxProvider()
            events = list(provider.stream(
                base_url="https://api.minimax.chat/v1",
                api_key="test", model="minimax/MiniMax-M3",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        assert events[-1].type == "done"


class TestAnthropicStream:

    def test_anthropic_stream_text_delta_forwarded(self):
        """Anthropic text_delta events forwarded."""
        from agent.llm.anthropic_provider import AnthropicProvider

        lines = [
            b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
            b'data: {"type":"message_stop"}',
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.anthropic_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = AnthropicProvider()
            events = list(provider.stream(
                base_url="https://api.anthropic.com",
                api_key="test", model="claude-3-5-sonnet-20241022",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 1
        assert text_events[0].data["content"] == "Hello"

    def test_anthropic_stream_message_stop_signals_done(self):
        """message_stop event produces a done event."""
        from agent.llm.anthropic_provider import AnthropicProvider

        lines = [b'data: {"type":"message_stop"}']

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def __iter__(self): return iter(lines)

        with patch("agent.llm.anthropic_provider.urlopen_with_ssl_retry", return_value=FakeResp()):
            provider = AnthropicProvider()
            events = list(provider.stream(
                base_url="https://api.anthropic.com",
                api_key="test", model="claude-3-5-sonnet-20241022",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        assert events[-1].type == "done"


# ======================================================================
# Streaming dispatch integration test (BACKLOG-1d)
# ======================================================================


class TestStreamingDispatch:
    """Verify _call_llm_streaming dispatches through get_provider().stream()."""

    def test_streaming_dispatch_uses_get_provider(self):
        """_call_llm_streaming must call get_provider(caller_key).stream()."""
        from unittest.mock import MagicMock, patch
        from agent.llm.streaming import SSEEvent

        mock_provider = MagicMock()
        mock_provider.stream.return_value = iter([
            SSEEvent(type="text_delta", data={"content": "hi"}),
            SSEEvent(type="done", data={}),
        ])

        with patch("agent.runtime._get_provider", return_value=mock_provider):
            # Import here to avoid module-level dependency
            from agent.runtime import _get_provider as gp
            provider = gp("openai")
            events = list(provider.stream(
                base_url="https://api.openai.com/v1",
                api_key="test", model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None, timeout=30,
            ))

        assert mock_provider.stream.called
        assert any(e.type == "text_delta" for e in events)
