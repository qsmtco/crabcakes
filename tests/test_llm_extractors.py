"""Tests for agent/llm/extractors.py — response extraction functions.

Extracted from agent/runtime.py (Phase B3). Tests the public names
(no underscore). The _get_response_format lazy-import helper is mocked
to avoid depending on runtime's _RESPONSE_FORMAT population.
"""

import json
from unittest.mock import patch

import pytest

from agent.llm.extractors import (
    extract_tool_calls,
    extract_text_content,
    extract_usage,
)


# ======================================================================
# Helpers
# ======================================================================

def _openai_fmt():
    """Mock _get_response_format to return OpenAI format mapping."""
    return {"openai": "openai", "minimax": "openai", "openrouter": "openai",
            "zai": "openai", "anthropic": "anthropic"}


# ======================================================================
# extract_tool_calls (spec §B.9 cases 23-25)
# ======================================================================


class TestExtractToolCalls:

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_tool_calls_openai_format(self, _mock):
        """OpenAI-format response: choices[0].message.tool_calls parsed."""
        response = {
            "choices": [{"message": {"tool_calls": [
                {"id": "call_1", "function": {"name": "write_file",
                 "arguments": '{"path": "x.py", "content": "hi"}'}},
            ]}}],
        }
        calls = extract_tool_calls(response, "openai")
        assert len(calls) == 1
        assert calls[0][0] == "call_1"
        assert calls[0][1] == "write_file"
        assert calls[0][2] == {"path": "x.py", "content": "hi"}

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_tool_calls_anthropic_format(self, _mock):
        """Anthropic-format response: content blocks with tool_use parsed."""
        response = {
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "read_file",
                 "input": {"path": "y.py"}},
            ],
        }
        calls = extract_tool_calls(response, "anthropic")
        assert len(calls) == 1
        assert calls[0][0] == "toolu_1"
        assert calls[0][1] == "read_file"
        assert calls[0][2] == {"path": "y.py"}

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_tool_calls_empty_choices(self, _mock):
        """No choices in OpenAI response → empty list."""
        assert extract_tool_calls({}, "openai") == []
        assert extract_tool_calls({"choices": []}, "openai") == []

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_tool_calls_synthetic_id_for_empty_id(self, _mock):
        """Empty/None id → synthetic call_XXXXXX id (QTR-FIX)."""
        response = {
            "choices": [{"message": {"tool_calls": [
                {"id": "", "function": {"name": "ls", "arguments": "{}"}},
                {"id": None, "function": {"name": "pwd", "arguments": "{}"}},
            ]}}],
        }
        calls = extract_tool_calls(response, "openai")
        assert len(calls) == 2
        assert calls[0][0].startswith("call_")
        assert calls[1][0].startswith("call_")

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_tool_calls_malformed_json_args_raises(self, _mock):
        """Malformed JSON string arguments → json.loads raises (verbatim behavior)."""
        response = {
            "choices": [{"message": {"tool_calls": [
                {"id": "c1", "function": {"name": "x", "arguments": "not-json"}},
            ]}}],
        }
        with pytest.raises(json.JSONDecodeError):
            extract_tool_calls(response, "openai")


# ======================================================================
# extract_text_content (spec §B.9 cases 26-27)
# ======================================================================


class TestExtractTextContent:

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_text_content_openai(self, _mock):
        """OpenAI-format: choices[0].message.content returned."""
        response = {"choices": [{"message": {"content": "Hello world"}}]}
        assert extract_text_content(response, "openai") == "Hello world"

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_text_content_anthropic(self, _mock):
        """Anthropic-format: text content blocks joined into a string."""
        response = {"content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ]}
        assert extract_text_content(response, "anthropic") == "Hello world"

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_text_content_empty_choices(self, _mock):
        """No choices → empty string."""
        assert extract_text_content({}, "openai") == ""
        assert extract_text_content({"choices": []}, "openai") == ""


# ======================================================================
# extract_usage (spec §B.9 cases 28-30)
# ======================================================================


class TestExtractUsage:

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_usage_openai(self, _mock):
        """OpenAI: prompt_tokens/completion_tokens."""
        response = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        assert extract_usage(response, "openai") == (100, 50)

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_usage_anthropic(self, _mock):
        """Anthropic: input_tokens/output_tokens."""
        response = {"usage": {"input_tokens": 200, "output_tokens": 80}}
        assert extract_usage(response, "anthropic") == (200, 80)

    @patch("agent.llm.extractors._get_response_format", return_value=_openai_fmt())
    def test_extract_usage_missing(self, _mock):
        """No usage key → (0, 0)."""
        assert extract_usage({}, "openai") == (0, 0)
        assert extract_usage({"usage": None}, "openai") == (0, 0)


# ======================================================================
# Backward-compat re-exports
# ======================================================================


class TestReExports:

    def test_runtime_reexport_extract_tool_calls(self):
        """Legacy underscore name importable from agent.runtime."""
        from agent.runtime import _extract_tool_calls
        assert _extract_tool_calls is extract_tool_calls

    def test_runtime_reexport_extract_text_content(self):
        from agent.runtime import _extract_text_content
        assert _extract_text_content is extract_text_content

    def test_runtime_reexport_extract_usage(self):
        from agent.runtime import _extract_usage
        assert _extract_usage is extract_usage
