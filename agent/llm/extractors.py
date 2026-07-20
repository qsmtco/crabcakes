"""Response extractors for LLM API responses.

Extracted from agent/runtime.py (Phase B3). Parses tool calls, text content,
and token usage from both OpenAI and Anthropic response formats. Pure functions
except for the response_format lookup (lazy import from runtime).

Note: _is_empty_content stays in runtime.py — it is used at non-extractor sites.
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)


def _get_response_format() -> dict:
    """Get the response format mapping (populated by runtime at startup).

    Lazy import to avoid circular dependency: runtime.py imports this module
    for the extractor functions, so we cannot import runtime at module top.
    """
    from agent.runtime import _RESPONSE_FORMAT
    return _RESPONSE_FORMAT


def extract_tool_calls(response: dict, provider: str) -> list[tuple[str, str, dict]]:
    """
    Extract tool calls from an API response dict.

    Returns [(call_id, tool_name, arguments)].

    Handles OpenAI, MiniMax, and Anthropic formats.
    """
    calls = []
    fmt = _get_response_format().get(provider, "openai")

    if fmt == "openai":
        # OpenAI/MiniMax Chat Completions format
        choices = response.get("choices", [])
        if not choices:
            return []
        delta = choices[0].get("delta", {})
        message = choices[0].get("message", delta)

        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                # QTR-FIX: use `or` so that None / empty-string ids fall through
                # to the synthetic fallback instead of propagating as an empty
                # tool_call_id. The previous form `tc.get("id", default)` only
                # substituted when the key was absent — explicit None / "" slipped
                # through and later matched `if not call_id` guards in unexpected
                # places. See `_extract_tool_calls (empty-id fallback)` regression
                # test for the synthetic-id contract.
                call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                name = func.get("name", "")
                args_raw = func.get("arguments", "{}")
                if isinstance(args_raw, str):
                    args = json.loads(args_raw)
                else:
                    args = args_raw or {}
                calls.append((call_id, name, args))

    elif fmt == "anthropic":
        # Anthropic Messages API format
        content = response.get("content", [])
        if not isinstance(content, list):
            return []
        for block in content:
            if block.get("type") == "tool_use":
                # QTR-FIX: same None / empty-string fallback as the OpenAI path.
                call_id = block.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                name = block.get("name", "")
                args = block.get("input", {})
                calls.append((call_id, name, args))

    return calls


def extract_text_content(response: dict, provider: str) -> str:
    """Extract text content from an API response."""
    fmt = _get_response_format().get(provider, "openai")

    if fmt == "openai":
        choices = response.get("choices", [])
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        return msg.get("content", "") or ""

    elif fmt == "anthropic":
        content = response.get("content", [])
        if not isinstance(content, list):
            return ""
        parts = [b.get("text", "") for b in content if b.get("type") == "text"]
        return "".join(parts)

    return ""


def extract_usage(response: dict, provider: str = "openai") -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from API response."""
    usage = response.get("usage")
    if not usage:
        return 0, 0
    fmt = _get_response_format().get(provider, "openai")
    if fmt == "anthropic":
        return (
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
    # OpenAI / MiniMax
    return (
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )
