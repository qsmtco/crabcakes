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

    def test_minimax_stream_finish_reason_error_signals_done(self):
        """finish_reason='error' produces a done event."""
        from agent.llm.minimax_provider import MiniMaxProvider

        lines = [
            b'data: {"choices":[{"delta":{},"finish_reason":"error"}]}',
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

    def test_minimax_stream_finish_reason_error_with_error_data(self):
        """finish_reason='error' with error dict yields error event before done."""
        from agent.llm.minimax_provider import MiniMaxProvider

        lines = [
            b'data: {"error":{"code":429,"message":"Quota exceeded"},"choices":[{"delta":{},"finish_reason":"error"}]}',
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

        types = [ev.type for ev in events]
        assert "error" in types, f"expected error event, got types={types}"
        assert events[-1].type == "done"
        assert types.index("error") < types.index("done")
        error_ev = [ev for ev in events if ev.type == "error"][0]
        assert error_ev.data.get("error", {}).get("code") == 429

    def test_minimax_stream_finish_reason_content_filter_signals_done(self):
        """finish_reason='content_filter' produces a done + error event."""
        from agent.llm.minimax_provider import MiniMaxProvider

        lines = [
            b'data: {"choices":[{"delta":{},"finish_reason":"content_filter"}]}',
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

        types = [ev.type for ev in events]
        assert "error" in types, f"expected error event for content_filter, got types={types}"
        assert events[-1].type == "done"
        error_ev = [ev for ev in events if ev.type == "error"][0]
        assert error_ev.data.get("error", {}).get("code") == 400, f"expected 400, got {error_ev.data.get('error', {})}"
        assert error_ev.data.get("error", {}).get("reason") == "content_filter"


class TestHandleFinishFrame:
    """Direct unit tests for _handle_finish_frame (module-level helper in minimax_provider.py).

    Tests the shared helper in isolation without needing SSE streaming or
    mock responses. Each test constructs a dict as it would arrive from
    parse_sse_line and inspects the yielded SSEEvent list.
    """

    def _run(self, d: dict) -> list:
        from agent.llm.minimax_provider import _handle_finish_frame
        return list(_handle_finish_frame(d))

    def test_stop(self):
        """finish_reason='stop' → delta + done, no error."""
        events = self._run({
            "choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}],
        })
        types = [ev.type for ev in events]
        assert "text_delta" in types
        assert types[-1] == "done"
        assert "error" not in types

    def test_tool_calls(self):
        """finish_reason='tool_calls' → delta + done, no error."""
        events = self._run({
            "choices": [{"delta": {"tool_calls": []}, "finish_reason": "tool_calls"}],
        })
        assert events[-1].type == "done"
        assert "error" not in [ev.type for ev in events]

    def test_length(self):
        """finish_reason='length' → delta + done, no error."""
        events = self._run({
            "choices": [{"delta": {"content": "partial"}, "finish_reason": "length"}],
        })
        assert events[-1].type == "done"
        assert "error" not in [ev.type for ev in events]

    def test_error_with_data(self):
        """finish_reason='error' with error dict → error event + done."""
        events = self._run({
            "error": {"code": 429, "message": "Rate limit"},
            "choices": [{"delta": {}, "finish_reason": "error"}],
        })
        types = [ev.type for ev in events]
        assert "error" in types, f"expected error event, got {types}"
        assert types[-1] == "done"
        assert types.index("error") < types.index("done")
        err = events[[ev.type for ev in events].index("error")]
        assert err.data["error"]["code"] == 429

    def test_error_without_data(self):
        """finish_reason='error' without error dict → no error event, just done."""
        events = self._run({
            "choices": [{"delta": {}, "finish_reason": "error"}],
        })
        types = [ev.type for ev in events]
        assert "error" not in types, f"unexpected error event, got {types}"
        assert types[-1] == "done"

    def test_content_filter(self):
        """finish_reason='content_filter' → error event with code=400, reason='content_filter' + done."""
        events = self._run({
            "choices": [{"delta": {}, "finish_reason": "content_filter"}],
        })
        types = [ev.type for ev in events]
        assert "error" in types, f"expected error event, got {types}"
        err = events[[ev.type for ev in events].index("error")]
        assert err.data["error"]["code"] == 400, f"expected 400, got {err.data['error']}"
        assert err.data["error"]["reason"] == "content_filter"
        assert "filtered" in err.data["error"]["message"].lower()
        assert types[-1] == "done"

    def test_missing_finish_reason(self):
        """No finish_reason → deltas but no done/error event."""
        events = self._run({
            "choices": [{"delta": {"content": "hello"}}],
        })
        types = [ev.type for ev in events]
        assert "done" not in types
        assert "error" not in types

    def test_empty_choices(self):
        """Empty choices with no error → no events (no delta, no done)."""
        events = self._run({"choices": []})
        assert len(events) == 0, f"expected no events, got {len(events)}"

    def test_top_level_error(self):
        """Top-level error dict with empty choices → error event + done."""
        events = self._run({
            "error": {"code": 429, "message": "Rate limit exceeded"},
            "choices": [],
        })
        types = [ev.type for ev in events]
        assert "error" in types, f"expected error event, got {types}"
        assert types[-1] == "done"
        err = events[[ev.type for ev in events].index("error")]
        assert err.data["error"]["code"] == 429

    def test_top_level_error_with_choices(self):
        """Top-level error AND finish_reason='error' → prefer error path (yields once)."""
        events = self._run({
            "error": {"code": 429, "message": "Rate limit"},
            "choices": [{"delta": {}, "finish_reason": "error"}],
        })
        types = [ev.type for ev in events]
        # Should only have one error event (top-level path fires first, returns)
        error_count = sum(1 for ev in events if ev.type == "error")
        assert error_count == 1, f"expected 1 error event, got {error_count}"
        assert types[-1] == "done"

    def test_usage_included(self):
        """finish_reason='stop' with usage dict → usage event before done."""
        events = self._run({
            "choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        })
        types = [ev.type for ev in events]
        assert "usage" in types, f"expected usage event, got {types}"
        assert types.index("usage") < types.index("done")

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
        """_call_llm_streaming must call get_provider(caller_key).stream().

        This is a regression guard: if the dispatch reverts to
        _get_provider(caller_key).stream (via get_provider), this test fails because
        mock_provider.stream would never be called via the registry path.
        """
        from unittest.mock import MagicMock, patch
        from agent.llm.streaming import SSEEvent
        from agent.config import AgentConfig, LLMProviderConfig
        from agent.runtime import AgentRuntime

        mock_provider = MagicMock()
        mock_provider.stream.return_value = iter([
            SSEEvent(type="text_delta", data={"content": "hi"}),
            SSEEvent(type="done", data={}),
        ])

        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test-key", default_model="gpt-4o",
                )
            },
            default_provider="openai", default_model="openai/gpt-4o",
            max_tool_iterations=5, tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()

        with patch("agent.runtime._get_provider", return_value=mock_provider):
            rt._call_llm_streaming(
                session_key="test-stream",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                model="openai/gpt-4o",
                caller_key="openai",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30.0,
            )

        assert mock_provider.stream.called, (
            "Expected _call_llm_streaming to dispatch through get_provider().stream()"
        )
        rt.stop()
