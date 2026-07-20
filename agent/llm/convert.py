"""Anthropic message and tool format converters.

Extracted from agent/runtime.py (Phase B2). Pure functions — convert
OpenAI-format message/tool dicts to Anthropic's content-block format.
No network, no GTK, no state.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def convert_messages_for_anthropic(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format message dicts → Anthropic message format.

    Handles:
    - system: stripped, returned as user role with text content
    - assistant with tool_calls: converted to Anthropic content blocks
    - tool: converted to Anthropic tool_result blocks
    - all others: passed through as-is
    """
    api_messages: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            content_text = msg.get("content", "")
            if content_text:
                api_messages.append({"role": "user", "content": content_text})
        elif role == "assistant" and msg.get("tool_calls"):
            content_blocks: list[dict] = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                args_str = tc["function"]["arguments"]
                if isinstance(args_str, str):
                    try:
                        args_str = json.loads(args_str)
                    except Exception as e:
                        # Phase 9: log instead of silently passing. Malformed
                        # JSON args may indicate upstream provider corruption;
                        # a debug message lets the developer trace it without
                        # disrupting the message conversion.
                        logger.debug("Failed to parse tool-call args JSON: %s", e)
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": args_str,
                })
            api_messages.append({"role": "assistant", "content": content_blocks})
        elif role == "tool":
            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": msg["content"],
                }],
            })
        else:
            api_messages.append(msg)
    return api_messages


def convert_tools_for_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool dicts → Anthropic tool schema.

    Input:  [{"function": {"name", "description", "parameters"}}}]
    Output: [{"name", "description", "input_schema"}]

    Defensive: defaults missing 'description' to '' and missing/'None'
    'parameters' to {} so malformed upstream tool dicts don't crash
    with KeyError. Anthropic accepts input_schema={} (no required params).
    """
    result: list[dict] = []
    for t in tools:
        fn = t.get("function") or {}
        params = fn.get("parameters")
        if not isinstance(params, dict):
            params = {}
        entry: dict[str, object] = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": params,
        }
        result.append(entry)
    return result
