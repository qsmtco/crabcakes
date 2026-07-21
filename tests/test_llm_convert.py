"""Tests for agent/llm/convert.py — Phase B2.

Tests the public names (no underscore) extracted from runtime.py.
"""

from __future__ import annotations

import pytest
from agent.llm.convert import convert_messages_for_anthropic, convert_tools_for_anthropic


# ── convert_messages_for_anthropic ──────────────────────────────────────────

class TestConvertMessagesForAnthropic:
    """Test convert_messages_for_anthropic — message format conversion."""

    def test_convert_system_message_to_user(self):
        """System role → user role with same content."""
        result = convert_messages_for_anthropic([
            {"role": "system", "content": "You are helpful."}
        ])
        assert result == [{"role": "user", "content": "You are helpful."}]

    def test_convert_system_message_empty_content_skipped(self):
        """System with empty content → not included in output."""
        result = convert_messages_for_anthropic([
            {"role": "system", "content": ""}
        ])
        assert result == []

    def test_convert_user_message_passthrough(self):
        """User role without tool_calls → passed through as-is."""
        result = convert_messages_for_anthropic([
            {"role": "user", "content": "Hello"}
        ])
        assert result == [{"role": "user", "content": "Hello"}]

    def test_convert_assistant_with_tool_calls(self):
        """Assistant with tool_calls → content blocks with tool_use type."""
        result = convert_messages_for_anthropic([
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/foo.txt"}',
                        }
                    }
                ]
            }
        ])
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        blocks = result[0]["content"]
        assert isinstance(blocks, list)
        assert blocks[0]["type"] == "tool_use"
        assert blocks[0]["id"] == "call_123"
        assert blocks[0]["name"] == "read_file"
        assert blocks[0]["input"] == {"path": "/tmp/foo.txt"}

    def test_convert_assistant_with_text_and_tool_calls(self):
        """Assistant with content + tool_calls → text block + tool_use blocks."""
        result = convert_messages_for_anthropic([
            {
                "role": "assistant",
                "content": "Let me read that file.",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/x.txt"}',
                        }
                    }
                ]
            }
        ])
        blocks = result[0]["content"]
        assert len(blocks) == 2
        assert blocks[0] == {"type": "text", "text": "Let me read that file."}
        assert blocks[1]["type"] == "tool_use"

    def test_convert_tool_message_to_tool_result(self):
        """Tool role → user role with tool_result content block."""
        result = convert_messages_for_anthropic([
            {
                "role": "tool",
                "tool_call_id": "call_xyz",
                "content": "file contents here",
            }
        ])
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [{
            "type": "tool_result",
            "tool_use_id": "call_xyz",
            "content": "file contents here",
        }]

    def test_convert_tool_call_args_json_parsing(self):
        """String args → parsed to dict in input field."""
        result = convert_messages_for_anthropic([
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "search",
                            "arguments": '{"query": "hello", "limit": 5}',
                        }
                    }
                ]
            }
        ])
        block = result[0]["content"][0]
        assert block["input"] == {"query": "hello", "limit": 5}

    def test_convert_tool_call_args_already_dict(self):
        """Dict args → passed through as-is."""
        result = convert_messages_for_anthropic([
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c2",
                        "function": {
                            "name": "search",
                            "arguments": {"query": "hi"},
                        }
                    }
                ]
            }
        ])
        block = result[0]["content"][0]
        assert block["input"] == {"query": "hi"}

    def test_convert_malformed_tool_call_args_json(self):
        """Malformed JSON string → kept as string (no crash, logged)."""
        result = convert_messages_for_anthropic([
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c3",
                        "function": {
                            "name": "bad_tool",
                            "arguments": "not-json",
                        }
                    }
                ]
            }
        ])
        block = result[0]["content"][0]
        # Stays as string when JSON parsing fails
        assert block["input"] == "not-json"


# ── convert_tools_for_anthropic ─────────────────────────────────────────────

class TestConvertToolsForAnthropic:
    """Test convert_tools_for_anthropic — tool schema conversion."""

    def test_convert_tools_basic(self):
        """Function dict with name/description/parameters → name/description/input_schema."""
        result = convert_tools_for_anthropic([
            {
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                }
            }
        ])
        assert result == [{
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}},
        }]

    def test_convert_tools_missing_description_defaults_empty(self):
        """Missing description → ''."""
        result = convert_tools_for_anthropic([
            {
                "function": {
                    "name": "bare_tool",
                    "parameters": {"type": "object"},
                }
            }
        ])
        assert result[0]["description"] == ""

    def test_convert_tools_none_parameters_defaults_empty_dict(self):
        """None parameters → {}."""
        result = convert_tools_for_anthropic([
            {
                "function": {
                    "name": "no_params",
                    "description": "desc",
                    "parameters": None,
                }
            }
        ])
        assert result[0]["input_schema"] == {}

    def test_convert_tools_non_dict_parameters_defaults_empty_dict(self):
        """Non-dict parameters → {}."""
        result = convert_tools_for_anthropic([
            {
                "function": {
                    "name": "bad_params",
                    "parameters": "not-a-dict",
                }
            }
        ])
        assert result[0]["input_schema"] == {}


# ── Backward-compat re-exports ──────────────────────────────────────────────

class TestBackwardCompatReexports:
    """Verify that runtime.py re-exports the converters under underscore names."""

    def test_runtime_reexport_convert_messages(self):
        """from agent.llm.convert import convert_messages_for_anthropic works."""
        from agent.llm.convert import convert_messages_for_anthropic
        assert callable(convert_messages_for_anthropic)
        result = convert_messages_for_anthropic([
            {"role": "system", "content": "Hi"}
        ])
        assert result == [{"role": "user", "content": "Hi"}]

    def test_runtime_reexport_convert_tools(self):
        """from agent.runtime import _convert_tools_for_anthropic works."""
        from agent.runtime import _convert_tools_for_anthropic
        assert callable(_convert_tools_for_anthropic)
        result = _convert_tools_for_anthropic([
            {"function": {"name": "t", "description": "d", "parameters": {}}}
        ])
        assert result == [{"name": "t", "description": "d", "input_schema": {}}]
