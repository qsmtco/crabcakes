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