# agent/runtime.py
# AgentRuntime — LLM API client with tool loop.
#
# Manifest:
#   - Reads: config.json, conversations/*.json, project files
#   - Writes: conversations/*.json
#   - Network: LLM API (OpenAI, MiniMax, Anthropic)
#   - No GTK; callbacks are dispatched via GLib.idle_add if GLib is provided
#
# Architecture: this is the core agent loop. It owns conversations, calls LLM APIs,
# executes tools, and manages cost tracking. All GTK/netscape calls go through
# callbacks dispatched to the caller.

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, TypedDict

if TYPE_CHECKING:
    from models.conversation import Conversation
    from agent.config import LLMProviderConfig

from agent.enforcement import check as _enforcement_check

# KB provider sentinel — imported lazily to avoid requiring kb_server when KB is unused.
try:
    from agent.kb_server import KB_OUT_OF_SCOPE
except ImportError:
    KB_OUT_OF_SCOPE = "[KB_OUT_OF_SCOPE]"


# ── Streaming call interface (PHASE-FOLLOWUP-1) ──────────────────────────────────

class StreamingCallKwargs(TypedDict, total=False):
    """Single source of truth for `_call_llm_streaming` parameters.

    Both the method signature and the regression test reference this TypedDict.
    If a field is added or removed here, the test will fail until the method
    and all call sites are updated to match.
    """
    session_key: str
    base_url: str
    api_key: str
    model: str
    caller_key: str
    messages: list[dict]
    tools: list[dict] | None
    timeout: float
    x_title: str


# Public API — symbols explicitly exported for external use (PHASE-FOLLOWUP-5)
__all__ = [
    "AgentRuntime",
    "SSEEvent",
    "StreamingCallKwargs",
    "_extract_tool_calls",
    "_extract_text_content",
    "_extract_usage",
    "_cost_for_model",
    "_PROVIDER_CALLERS",
    "_PROVIDER_STREAMERS",
]

logger = logging.getLogger(__name__)

# ── Cost tables (USD per 1M tokens) ─────────────────────────────────────────

_OPENAI_COST = {"prompt": 2.5, "completion": 10.0}    # GPT-4o
_MINIMAX_COST = {"prompt": 0.5, "completion": 1.0}   # MiniMax-M2
_ANTHROPIC_COST = {"prompt": 3.0, "completion": 15.0} # Claude 3.5

_PROVIDER_COSTS: dict[str, dict[str, float]] = {
    "openai": _OPENAI_COST,
    "minimax": _MINIMAX_COST,
    "anthropic": _ANTHROPIC_COST,
    "openrouter": _OPENAI_COST,  # varies by model, using openai as fallback
    "zai": _OPENAI_COST,        # free tier, no cost
}


def _model_id(model: str) -> str:
    """Strip the provider prefix, returning the model ID sent to the API.

    'minimax/MiniMax-M2.7'       -> 'MiniMax-M2.7'
    'openrouter/deepseek/deepseek-v4-pro' -> 'deepseek/deepseek-v4-pro'
    """
    parts = model.split("/", 1)
    return parts[1] if len(parts) > 1 else parts[0]


def _cost_for_model(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost in USD for a model call."""
    provider = model.split("/")[0] if "/" in model else model
    costs = _PROVIDER_COSTS.get(provider, _OPENAI_COST)
    return (prompt_tokens / 1_000_000 * costs["prompt"] +
            completion_tokens / 1_000_000 * costs["completion"])


# ── Provider adapters ──────────────────────────────────────────────────────────

def _call_openai(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
    """Call OpenAI Chat Completions API (also used by OpenRouter, ZAI)."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": _model_id(model),
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if x_title:
        headers["HTTP-Referer"] = "https://github.com/qsmtco/crabcakes"
        headers["X-Title"] = x_title
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenAI API error {e.code} {e.reason}: {body}"
        ) from e


def _call_minimax(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
    """Call MiniMax ChatCompletion v2 API."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
    payload = {
        "model": _model_id(model),
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            # MiniMax returns body-level errors with HTTP 200:
            # {"base_resp":{"status_code":1004,"status_msg":"login fail..."}}
            base_resp = result.get("base_resp", {})
            status_code = base_resp.get("status_code", 0)
            if status_code != 0:
                status_msg = base_resp.get("status_msg", "unknown error")
                raise RuntimeError(
                    f"MiniMax API error (status_code={status_code}): {status_msg}"
                )
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MiniMax API error {e.code} {e.reason}: {body}"
        ) from e


def _call_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
    """Call Anthropic Messages API."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/messages"
    # Anthropic uses a different message format — convert OpenAI tool format
    # tool_calls: "content": [{"type": "tool_use", ...}] + tool_results: role: "user" / "content": [{"type": "tool_result", ...}]
    system_msg = None
    api_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            # Convert OpenAI tool_calls to Anthropic content blocks
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                args_str = tc["function"]["arguments"]
                if isinstance(args_str, str):
                    try:
                        args_str = json.loads(args_str)
                    except Exception:
                        pass
                content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": args_str,
                })
            api_messages.append({"role": "assistant", "content": content})
        elif msg["role"] == "tool":
            # Convert OpenAI tool result to Anthropic format
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

    payload: dict[str, Any] = {
        "model": _model_id(model),
        "messages": api_messages,
        "max_tokens": 4096,
    }
    if system_msg:
        payload["system"] = system_msg
    if tools:
        # Convert OpenAI tool format to Anthropic tool format (Bug #9 fix)
        anthropic_tools = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"]["parameters"],
            }
            for t in tools
        ]
        payload["tools"] = anthropic_tools

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Anthropic API error {e.code} {e.reason}: {body}"
        ) from e


_PROVIDER_CALLERS: dict[str, Any] = {
    "openai": _call_openai,
    "minimax": _call_minimax,
    "anthropic": _call_anthropic,
    "openrouter": _call_openai,  # OpenAI-compatible API
    "zai": _call_openai,        # OpenAI-compatible API
}


# Response format families — derived from caller configuration.
# Any provider using _call_openai or _call_minimax returns OpenAI-format responses.
# Used by _extract_text_content, _extract_tool_calls, _extract_usage to avoid
# hardcoding provider name lists.
_RESPONSE_FORMAT: dict[str, str] = {}
for _pk, _caller in _PROVIDER_CALLERS.items():
    if _caller is _call_anthropic:
        _RESPONSE_FORMAT[_pk] = "anthropic"
    else:
        _RESPONSE_FORMAT[_pk] = "openai"  # openai, minimax, openrouter, zai, etc.


# ── SSE Streaming (Phase 1.3b) ─────────────────────────────────────────────────

import re
import ssl
import urllib.request
from collections import namedtuple

# SSE event types
SSEEvent = namedtuple("SSEEvent", ["type", "data"])
# Types: 'text_delta', 'tool_call_delta', 'tool_call_done', 'done'


def _sse_lines(resp) -> list[bytes]:
    """Read all SSE lines from an HTTP response. Handles chunked transfer encoding."""
    # Read line-by-line (not byte-by-byte) — avoids 100-1000x syscall overhead
    for line in resp:
        yield line.strip()


def _parse_sse_line(line: bytes) -> SSEEvent | None:
    """Parse one SSE line into an SSEEvent. Returns None for non-data lines."""
    line = line.strip()
    if not line or line.startswith(b":"):
        return None
    if line.startswith(b"data: "):
        data = line[6:]
    elif line.startswith(b"data:"):
        data = line[5:].lstrip()
    else:
        return None
    if data == b"[DONE]" or data == b"DONE":
        return SSEEvent(type="done", data={})
    try:
        return SSEEvent(type="raw", data=json.loads(data.decode("utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# Transient SSL/network errors that warrant a retry.
_RETRYABLE_SSL_ERRORS = frozenset({
    "SSLV3_ALERT_BAD_RECORD_MAC",
    "SSLV3_ALERT_BAD_RECORD_MD5",
    "TLSV1_ALERT_DECRYPTION_FAILED",
    "TLSV1_ALERT_RECORD_OVERFLOW",
    "SSL_ERROR_SYSCALL",
})

_MAX_SSL_RETRIES = 3
_SSL_RETRY_BASE_MS = 500


def _urlopen_with_ssl_retry(req, timeout, *, max_retries=_MAX_SSL_RETRIES):
    """Like urllib.request.urlopen but retries on transient SSL errors."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except ssl.SSLError as e:
            reason = str(e)
            # Only retry on known transient errors
            is_retryable = any(tok in reason for tok in _RETRYABLE_SSL_ERRORS)
            if not is_retryable or attempt == max_retries:
                raise
            last_exc = e
            wait_s = (_SSL_RETRY_BASE_MS / 1000) * (2 ** attempt)
            logger.warning(
                "[ssl-retry] attempt %d/%d for %s — %s; retrying in %.1fs",
                attempt + 1, max_retries, req.full_url, reason, wait_s,
            )
            time.sleep(wait_s)
    raise last_exc  # should not reach here


def _stream_openai_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
):
    """Yield SSE events from OpenAI Chat Completions streaming API (also used by OpenRouter, ZAI)."""
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": _model_id(model),
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if x_title:
        headers["HTTP-Referer"] = "https://github.com/qsmtco/crabcakes"
        headers["X-Title"] = x_title
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
        for line in _sse_lines(resp):
            ev = _parse_sse_line(line)
            if ev is None:
                continue
            if ev.type == "done":
                yield SSEEvent(type="done", data={})
                return
            if ev.type != "raw":
                continue
            d = ev.data
            delta = d.get("choices", [{}])[0].get("delta", {})
            # Text content delta (guard against null content from OpenRouter)
            content = delta.get("content")
            if content is not None:
                yield SSEEvent(type="text_delta", data={"content": content})
            # Tool call deltas
            tc_delta = delta.get("tool_calls", [])
            for tcd in tc_delta:
                idx = tcd.get("index", 0)
                if "function" in tcd:
                    fname = tcd["function"].get("name") or ""
                    fargs = tcd["function"].get("arguments", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
            # OpenAI-compatible providers emit a usage chunk at the end of the stream,
            # typically in a frame with empty choices. Capture and forward it.
            # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.1.1 (BUG #3 fix).
            usage = d.get("usage")
            if usage:
                yield SSEEvent(type="usage", data={"usage": usage})


def _stream_minimax_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
):
    """Yield SSE events from MiniMax ChatCompletion streaming API (OpenAI-compatible)."""
    endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
    payload = {
        "model": _model_id(model),
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
        # MiniMax may return a body-level error with HTTP 200 (not SSE).
        # Check the first non-empty line before entering SSE parsing.
        first_line = None
        for line in _sse_lines(resp):
            if line.strip():
                first_line = line
                break
        if first_line is not None:
            # Check if this is a non-SSE JSON error response
            try:
                parsed = json.loads(first_line.decode("utf-8"))
                base_resp = parsed.get("base_resp", {})
                status_code = base_resp.get("status_code", 0)
                if status_code != 0:
                    status_msg = base_resp.get("status_msg", "unknown error")
                    raise RuntimeError(
                        f"MiniMax API error (status_code={status_code}): {status_msg}"
                    )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # Not JSON — likely SSE data, fall through

            # First line wasn't an error — process it as SSE
            ev = _parse_sse_line(first_line)
            if ev is not None:
                if ev.type == "done":
                    yield SSEEvent(type="done", data={})
                    return
                if ev.type == "raw":
                    d = ev.data
                    delta = d.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content is not None:
                        yield SSEEvent(type="text_delta", data={"content": content})
                    tc_delta = delta.get("tool_calls", [])
                    for tcd in tc_delta:
                        idx = tcd.get("index", 0)
                        if "function" in tcd:
                            fname = tcd["function"].get("name") or ""
                            fargs = tcd["function"].get("arguments", "") or ""
                            yield SSEEvent(type="tool_call_delta", data={
                                "index": idx, "name": fname, "arguments": fargs
                            })
                    finish_reason = d.get("choices", [{}])[0].get("finish_reason")
                    if finish_reason in ("stop", "tool_calls", "length"):
                        # Phase CB-3: capture usage before signaling done.
                        usage = d.get("usage")
                        if usage:
                            yield SSEEvent(type="usage", data={"usage": usage})
                        yield SSEEvent(type="done", data={})
                        return

        for line in _sse_lines(resp):
            ev = _parse_sse_line(line)
            if ev is None:
                continue
            if ev.type == "done":
                yield SSEEvent(type="done", data={})
                return
            if ev.type != "raw":
                continue
            d = ev.data
            delta = d.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content")
            if content is not None:
                yield SSEEvent(type="text_delta", data={"content": content})
            tc_delta = delta.get("tool_calls", [])
            for tcd in tc_delta:
                idx = tcd.get("index", 0)
                if "function" in tcd:
                    fname = tcd["function"].get("name") or ""
                    fargs = tcd["function"].get("arguments", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
            # MiniMax signals stream end via finish_reason, not [DONE]
            finish_reason = d.get("choices", [{}])[0].get("finish_reason")
            if finish_reason in ("stop", "tool_calls", "length"):
                # Phase CB-3: capture usage before signaling done.
                usage = d.get("usage")
                if usage:
                    yield SSEEvent(type="usage", data={"usage": usage})
                yield SSEEvent(type="done", data={})
                return


def _stream_anthropic_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
):
    """Yield SSE events from Anthropic Messages streaming API."""
    endpoint = f"{base_url.rstrip('/')}/messages"
    # Strip system message and extract api_messages format
    system_msg = None
    api_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        else:
            api_messages.append(msg)

    payload: dict[str, Any] = {
        "model": _model_id(model),
        "messages": api_messages,
        "max_tokens": 4096,
        "stream": True,
    }
    if system_msg:
        payload["system"] = system_msg
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
        for line in _sse_lines(resp):
            ev = _parse_sse_line(line)
            if ev is None:
                continue
            if ev.type == "done":
                yield SSEEvent(type="done", data={})
                return
            if ev.type != "raw":
                continue
            d = ev.data
            etype = d.get("type", "")
            if etype == "content_block_delta":
                delta = d.get("delta", {})
                dtype = delta.get("type", "")
                if dtype == "text_delta":
                    yield SSEEvent(type="text_delta", data={"content": delta.get("text", "")})
                elif dtype == "tool_use_delta":
                    idx = d.get("index", 0)
                    fname = delta.get("name") or ""
                    fargs = delta.get("input", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
            elif etype == "message_delta":
                # Anthropic emits usage in message_delta events at the end of the stream.
                # The data shape is: {"type": "message_delta", "usage": {"input_tokens": N, "output_tokens": M}, ...}
                # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.1.3 (BUG #3 fix).
                usage = d.get("usage")
                if usage:
                    yield SSEEvent(type="usage", data={"usage": usage})
            elif etype == "message_stop":
                yield SSEEvent(type="done", data={})
                return


_PROVIDER_STREAMERS: dict[str, Any] = {
    "openai": _stream_openai_events,
    "minimax": _stream_minimax_events,
    "anthropic": _stream_anthropic_events,
    "openrouter": _stream_openai_events,  # OpenAI-compatible SSE
    "zai": _stream_openai_events,        # OpenAI-compatible SSE
}






# ── Tool call normalization ─────────────────────────────────────────────────────

def _extract_tool_calls(response: dict, provider: str) -> list[tuple[str, str, dict]]:
    """
    Extract tool calls from an API response dict.

    Returns [(call_id, tool_name, arguments)].

    Handles OpenAI, MiniMax, and Anthropic formats.
    """
    calls = []
    fmt = _RESPONSE_FORMAT.get(provider, "openai")

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
                call_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")
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
                call_id = block.get("id", f"call_{uuid.uuid4().hex[:8]}")
                name = block.get("name", "")
                args = block.get("input", {})
                calls.append((call_id, name, args))

    return calls


def _extract_text_content(response: dict, provider: str) -> str:
    """Extract text content from an API response."""
    fmt = _RESPONSE_FORMAT.get(provider, "openai")

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


def _extract_usage(response: dict, provider: str = "openai") -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from API response."""
    usage = response.get("usage")
    if not usage:
        return 0, 0
    fmt = _RESPONSE_FORMAT.get(provider, "openai")
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


# ── KB synthesis helper ───────────────────────────────────────────────────────

def _format_chunks_for_llm(chunks: list) -> str:
    """Format KB chunks as context for LLM synthesis.

    Takes a list of KBChunk objects and returns a formatted string
    suitable for injection into LLM messages as context.
    """
    if not chunks:
        return ""
    parts = ["[KB Context — relevant documentation chunks:]"]
    for chunk in chunks:
        parts.append(f"\nSource: {chunk.source} :: {chunk.section}\n{chunk.text}\n")
    parts.append("[End KB Context]\n")
    return "\n".join(parts)


# ── Conversation persistence ──────────────────────────────────────────────────

def _conversations_dir() -> str:
    """Return the conversations directory, creating it if needed."""
    from utils.config import get_config_dir
    d = os.path.join(get_config_dir(), "conversations")
    os.makedirs(d, exist_ok=True)
    return d


def _save_conversation_to_disk(conv: "Conversation", session_key: str) -> str:
    """Save a conversation to <conversations_dir>/<session_key>.json."""
    path = os.path.join(_conversations_dir(), f"{session_key}.json")
    data = {
        "session_key": session_key,
        "agent_name": conv.agent_name,
        "project_path": conv.project_path,
        "model": conv.model,
        "messages": [
            {
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "content": m.content,
                "tool_calls": [
                    {
                        "call_id": tc.call_id,
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                    }
                    for tc in (m.tool_calls or [])
                ],
                "tool_call_id": getattr(m, "tool_call_id", None),
                "tokens_used": m.tokens_used,
                "timestamp": m.timestamp.isoformat() if hasattr(m.timestamp, "isoformat") else m.timestamp,
            }
            for m in conv.messages
        ],
        "system_prompt": conv.system_prompt,
        "total_tokens": conv.total_tokens,
        "total_cost": conv.total_cost,
        "step_count": conv.step_count,
        "allowed_tools": conv.allowed_tools,
        "api_key": conv.api_key,
        "mcp_servers": list(conv.mcp_servers) if conv.mcp_servers else [],
        "si_enforcement": conv.si_enforcement,
        "agent_role": conv.agent_role,
        "fallback_provider": conv.fallback_provider,
        "fallback_model": conv.fallback_model,
        "app_title": conv.app_title,
        "created_at": conv.created_at.isoformat() if hasattr(conv.created_at, "isoformat") else conv.created_at,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _load_conversation_from_disk(session_key: str) -> tuple["Conversation", dict] | None:
    """Load a conversation from disk. Returns (Conversation, metadata) or None."""
    path = os.path.join(_conversations_dir(), f"{session_key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    from models.conversation import Conversation, Message, MessageRole

    messages = []
    for mdata in data.get("messages", []):
        from models.conversation import ToolCall
        tool_calls = []
        for tcdata in mdata.get("tool_calls", []):
            tool_calls.append(
                ToolCall(
                    call_id=tcdata["call_id"],
                    tool_name=tcdata["tool_name"],
                    arguments=tcdata.get("arguments", {}),
                )
            )
        msg = Message(
            role=MessageRole(mdata["role"]),
            content=mdata.get("content", ""),
            tool_calls=tool_calls,
            tool_call_id=mdata.get("tool_call_id"),
            tokens_used=mdata.get("tokens_used", 0),
        )
        messages.append(msg)

    conv = Conversation(
        agent_name=data["agent_name"],
        project_path=data.get("project_path"),
        model=data.get("model", ""),
        system_prompt=data.get("system_prompt", ""),
        messages=messages,
        total_tokens=data.get("total_tokens", 0),
        total_cost=data.get("total_cost", 0.0),
        step_count=data.get("step_count", 0),
        allowed_tools=data.get("allowed_tools"),
        api_key=data.get("api_key"),
        app_title=data.get("app_title", ""),
        mcp_servers=data.get("mcp_servers", []),
        si_enforcement=data.get("si_enforcement"),
        agent_role=data.get("agent_role", ""),
        fallback_provider=data.get("fallback_provider"),
        fallback_model=data.get("fallback_model"),
    )
    return conv, data


# ── AgentRuntime ──────────────────────────────────────────────────────────────

class AgentRuntime:
    """
    Core agent loop: manages conversations, calls LLM APIs, executes tools.

    Thread-safe: all public methods are thread-safe. Callbacks are dispatched
    via GLib.idle_add if GLib is provided (for GTK thread safety), otherwise
    called directly in the caller's thread.

    Args:
        config: AgentConfig with provider credentials and limits.
        GLib: Optional GLib module for thread-safe GTK dispatch.
        on_text_delta: (session_key, delta_text) — streaming text delta (Phase 1.3b).
        on_tool_call_start: (session_key, tool_name, args) — tool call started.
        on_tool_call_result: (session_key, tool_name, result) — tool completed.
        on_tool_call_approval_needed: (session_key, tool_name, args) → bool | None — approval needed.
        on_response_complete: (session_key, full_text) — final response ready.
        on_token_usage: (session_key, tokens, cost) — usage info.
        on_token_breakdown: (session_key, breakdown_dict) — §4.15 per-turn token budget breakdown.
            The breakdown dict includes three additional keys when the context-bloat
            fix (BUG #1, Phase CB-1) has shipped:
              - trimmed_this_turn (bool): True if messages were removed this iteration
              - messages_remaining (int): post-trim message count
              - messages_removed_this_turn (int): number of messages removed (0 if none)
        on_error: (session_key, error_message) — error occurred.
    """

    def __init__(
        self,
        config: Any,            # AgentConfig — imported lazily to avoid circular
        *,
        GLib=None,
        on_text_delta: Callable | None = None,
        on_tool_call_start: Callable | None = None,
        on_tool_call_result: Callable | None = None,
        on_tool_call_approval_needed: Callable | None = None,
        on_response_complete: Callable | None = None,
        on_token_usage: Callable | None = None,
        on_token_breakdown: Callable | None = None,
        on_error: Callable | None = None,
        on_enforcement_status: Callable | None = None,
    ):
        self._config = config
        self._GLib = GLib
        self._on_text_delta = on_text_delta
        self._on_tool_call_start = on_tool_call_start
        self._on_tool_call_result = on_tool_call_result
        self._on_tool_call_approval_needed = on_tool_call_approval_needed
        self._on_response_complete = on_response_complete
        self._on_token_usage = on_token_usage
        self._on_token_breakdown = on_token_breakdown
        self._last_trim_removed = 0  # set per iteration in _run_loop; read by the breakdown callback
        self._on_error = on_error
        self._on_enforcement_status = on_enforcement_status

        # Phase CB-3: per-session list of pending stuck messages to send as
        # transient prefixes on the next LLM call.
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        self._pending_stuck_messages: dict[str, list[str]] = {}

        # conversation_key → Conversation
        self._conversations: dict[str, Any] = {}
        # session_key → pending_approval {tool_name, args, result_event, result_ref}
        self._pending_approvals: dict[str, dict] = {}
        self._cancelled: set[str] = set()  # cancelled session keys
        self._cancel_requested: bool = False  # immediate cancel signal for running thread
        self._lock = threading.Lock()
        self._running = False

        # §E: Stuck detection — per-session tool call history for detecting loops
        # session_key → list[dict{"tool", "args_hash", "iteration"}]
        self._tool_history: dict[str, list[dict]] = {}
        self._tool_history_lock = threading.Lock()

    # ── Dispatch helpers ───────────────────────────────────────────────────────

    def _dispatch(self, callback: Callable | None, *args: Any, **kwargs: Any) -> None:
        """Dispatch a callback thread-safely via GLib.idle_add or directly."""
        if callback is None:
            return
        def inner():
            try:
                callback(*args, **kwargs)
            except Exception:
                logger.exception("Callback %s raised", callback)
        if self._GLib is not None:
            self._GLib.idle_add(inner)
        else:
            inner()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the runtime. Loads saved conversations from disk."""
        self._running = True
        logger.info("AgentRuntime started")

    def stop(self) -> None:
        """Stop the runtime. Saves all conversations."""
        with self._lock:
            self._running = False
            for sk, conv in list(self._conversations.items()):
                try:
                    _save_conversation_to_disk(conv, sk)
                except Exception:
                    logger.exception("Failed to save conversation %s", sk)
        logger.info("AgentRuntime stopped")

    def is_running(self) -> bool:
        return self._running

    # ── Conversation management ─────────────────────────────────────────────────

    def create_conversation(
        self,
        agent_name: str,
        session_key: str,
        project_path: str | None = None,
        model: str | None = None,
        allowed_tools: list[str] | None = None,  # NEW
        mcp_servers: list[str] = None,  # NEW: Phase B MCP servers
        agent_role: str = "",
        si_enforcement: bool | None = None,      # per-agent enforcement override
        api_key: str | None = None,             # per-agent API key override
        app_title: str = "",                    # app identifier (e.g. "crabcakes")
        fallback_provider: str | None = None,    # KB fallback provider (from agent def)
        fallback_model: str | None = None,       # KB fallback model (from agent def)
    ) -> str:
        """
        Create a new conversation for an agent.

        Returns the session_key (same as the argument).

        Args:
            allowed_tools: If provided, only these tool names are available to
                          the agent. If None, all tools are available.
            mcp_servers: List of MCP server names to connect for this conversation.
            si_enforcement: If True/False, overrides global enforcement for this
                           agent. If None, uses global config.
            app_title: App identifier — flows from gateway displayName into
                      the conversation so agents know the source application.
        """
        # Phase B BUG #22: Clean up existing MCP connections before replacing conversation
        if session_key in self._conversations:
            try:
                from utils.mcp_client import disconnect_all
                disconnect_all(session_key)  # Clean up MCP for this conversation
            except Exception:
                pass  # Best effort cleanup

        from agent.context import build_system_prompt
        from models.conversation import Conversation

        if model is None:
            model = self._config.default_model

        # Build tool list — use allowed_tools if provided, otherwise all tools
        from agent.tools import get_all_tools
        if allowed_tools is not None:
            all_tools = get_all_tools()
            tool_names = [t.name for t in all_tools if t.name in allowed_tools]
        else:
            tools = get_all_tools()
            tool_names = [t.name for t in tools]
        # Phase CB-2: pass the model's context window so the system prompt budget
        # can cap file context. Resolve from the default provider's config.
        default_provider_name = self._config.default_provider
        default_provider_cfg = self._config.providers.get(default_provider_name) if default_provider_name else None
        if default_provider_cfg and getattr(default_provider_cfg, "max_tokens", None):
            model_max_for_budget = int(default_provider_cfg.max_tokens)
        else:
            model_max_for_budget = 128_000  # fallback per CB-1

        system_prompt = build_system_prompt(
            agent_name, project_path, tool_names,
            agent_role=agent_role,
            model_max_tokens=model_max_for_budget,
        )

        conv = Conversation(
            agent_name=agent_name,
            agent_role=agent_role,
            project_path=project_path,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers if mcp_servers else [],
            model=model,
            system_prompt=system_prompt,
            si_enforcement=si_enforcement,
            api_key=api_key,
            app_title=app_title,
            fallback_provider=fallback_provider or self._config.fallback_provider,
            fallback_model=fallback_model or self._config.fallback_model,
        )

        with self._lock:
            self._conversations[session_key] = conv

        logger.info("Created conversation %s for agent %s", session_key, agent_name)
        return session_key

    def get_conversation(self, session_key: str) -> Any | None:  # Conversation | None
        """Get a conversation by session key."""
        return self._conversations.get(session_key)

    def send_message(self, session_key: str, text: str) -> None:
        """
        Send a user message. Runs the tool loop in a background thread.

        Loop:
        1. Append user message
        2. Build API messages (system + history)
        3. Call LLM API
        4. If tool calls: execute (with approval gating for exec_command)
        5. If text: fire on_response_complete
        6. Check cost_limit / step_limit
        """
        # Reset fallback flag for this new user message
        conv = self._conversations.get(session_key)
        if conv is not None:
            conv._fallback_attempted = False

        t = threading.Thread(target=self._run_loop, args=(session_key, text), daemon=True)
        t.start()

    def cancel(self, session_key: str) -> None:
        """Cancel an in-progress conversation."""
        with self._lock:
            # Mark as cancelled so _run_loop's check will catch it
            self._cancelled.add(session_key)
            # Signal the running thread to break out of the loop immediately
            self._cancel_requested = True
            for sk in list(self._pending_approvals):
                if sk.startswith(session_key):
                    ev = self._pending_approvals[sk]["event"]
                    self._pending_approvals[sk]["result"] = None
                    ev.set()
            self._dispatch(self._on_error, session_key, "Cancelled by user")
            logger.info("Cancelled session %s", session_key)
        # §E: Clean up stuck-detection history when conversation ends
        self._cleanup_tool_history(session_key)

    # ── Tool loop ─────────────────────────────────────────────────────────────

    def _inject_kb_context(self, messages: list[dict], kb_context: str, text: str) -> list[dict]:
        """Inject KB context into the most recent user message.

        Modifies a copy of messages. The KB context is prepended to the last
        user message's content so the LLM sees it as part of the current turn.

        Args:
            messages: The full message list from to_api_messages().
            kb_context: Formatted KB context string from _format_chunks_for_llm().
            text: The current user message text (used as a fallback search key).

        Returns:
            A new message list with KB context injected into the last user message.
        """
        # Build a shallow copy — only the modified message is a new dict
        injected = list(messages)
        # Find the last user message and prepend KB context to it
        for i in range(len(injected) - 1, -1, -1):
            if injected[i].get("role") == "user":
                original_content = injected[i].get("content", "")
                injected[i] = {
                    "role": "user",
                    "content": f"{kb_context}\n\nUser question: {original_content or text}",
                }
                return injected
        # No user message found — return unchanged
        return messages

    def _compute_model_max(self, conv: "Conversation") -> int:
        """Return the model's context window for the current conversation's provider.

        Resolution order:
          1. conv.model's provider's max_tokens in self._config.providers (when > 0)
          2. 128_000 fallback (matches the §4.15 default; same constant used
             by the old inline calculation at the former lines 1198-1201)

        Returns 128_000 when:
          - conv.model is None and self._config.default_provider is not configured
          - the resolved provider config has max_tokens <= 0 or None
          - any exception during provider lookup
        """
        FALLBACK = 128_000
        try:
            provider_name = (
                conv.model.split("/")[0]
                if conv.model and "/" in conv.model
                else self._config.default_provider
            )
            if not provider_name:
                return FALLBACK
            provider_cfg = self._config.providers.get(provider_name)
            if provider_cfg is None:
                return FALLBACK
            if not getattr(provider_cfg, "max_tokens", None):
                return FALLBACK
            return int(provider_cfg.max_tokens)
        except Exception:
            logger.exception("[model-max] failed to resolve provider max_tokens; using fallback")
            return FALLBACK

    def _prepare_kb_synthesis(
        self,
        conv: "Conversation",
        text: str,
        messages: list[dict],
        kb_cache: str | None,
    ) -> tuple[list[dict], str | None, str | None]:
        """Prepare KB-synthesis messages for the primary LLM call (Tier 2).

        If conv.agent_role == "helper", runs kb_lookup on the current user
        message (or reuses the cached result) and injects the chunks into
        the messages list. Returns (messages_for_call, kb_context, new_cache).
        For non-auxilium agents or empty KB results, returns
        (messages, None, None) — no injection, no change to the messages.

        The per-turn cache is the caller's responsibility. Pass the current
        cache value in kb_cache; assign the returned new_cache back to the
        caller's variable. This keeps the cache in _run_loop's scope so
        it survives across tool-loop iterations.

        Called once per tool-loop iteration. kb_lookup is invoked at most
        once per _run_loop invocation: the per-turn cache (passed in via
        kb_cache, returned via the new_cache element of the tuple) is set
        to a non-None value on the first call — the formatted string for
        matches, or the empty string for no-results or exceptions. The
        empty-string sentinel is what makes the cache an actual invariant
        (rather than "cached only on success"); it prevents re-querying a
        failing backend on every iteration and prevents re-querying for
        off-topic user messages that have no KB coverage.
        """
        # Gate: only fire for auxilium (type-safe, case-insensitive)
        is_helper = (
            isinstance(conv.agent_role, str)
            and conv.agent_role.strip().lower() == "helper"
        )
        if not is_helper:
            return messages, None, None

        # Per-turn cache: only fetch on first call within a turn.
        # After the first call, new_cache is ALWAYS set (to the formatted
        # string for matches, or to "" for no-results / exception). The
        # empty-string sentinel is what makes this an actual cache invariant
        # rather than "sometimes a cache when KB has something to say."
        new_cache = kb_cache
        if new_cache is None:
            try:
                from agent.kb_lookup import kb_lookup
                chunks = kb_lookup(text, top_k=5, min_score=0.35)
                new_cache = _format_chunks_for_llm(chunks)
            except Exception:
                new_cache = ""  # queried, but failed; do not retry

        kb_context = new_cache
        messages_for_call = messages
        if kb_context:
            messages_for_call = self._inject_kb_context(messages, kb_context, text)
        return messages_for_call, kb_context, new_cache

    def _run_loop(self, session_key: str, text: str) -> None:
        """Background thread: run the full tool loop for one user message."""
        with self._lock:
            if not self._running:
                return
            conv = self._conversations.get(session_key)
            if conv is None:
                self._dispatch(self._on_error, session_key, "No conversation found")
                return

        try:
            # Step 1: add user message
            conv.add_user_message(text)
            logger.debug("[tool-loop] sk=%s starting user_msg_len=%d model=%s",
                         session_key, len(text), conv.model or self._config.default_model)

            # Step 2: loop until no tool calls or limit hit
            iteration = 0
            max_iter = self._config.max_tool_iterations

            # Per-turn cache: KB chunks fetched once and reused for the entire
            # multi-iteration loop. The user question is the same throughout;
            # re-running kb_lookup on every iteration is wasted work and tokens.
            _kb_cache_for_turn: str | None = None

            while iteration < max_iter:
                # Check immediate cancel signal first
                if self._cancel_requested:
                    self._cancel_requested = False
                    self._dispatch(self._on_error, session_key, "Cancelled")
                    return
                # Check cancellation before each iteration
                with self._lock:
                    if session_key in self._cancelled:
                        self._cancelled.discard(session_key)
                        self._dispatch(self._on_error, session_key, "Cancelled")
                        return
                iteration += 1
                logger.debug("[tool-loop] sk=%s iteration=%d/%d", session_key, iteration, max_iter)

                # Build API messages
                from models.conversation import MessageRole
                messages = conv.to_api_messages()

                # Context-bloat fix (BUG #1) — cap history before each LLM call.
                # Conversation.trim_to_token_limit() is unit-tested at
                # tests/test_conversation.py:249 (TestConversationTrim) and
                # tests/test_phase4.py:280 (summary-on-trim). It preserves the
                # system prompt and the last 4 messages, and (per §4.10) injects
                # a budget-aware summary when >= 8 messages remain.
                model_max = self._compute_model_max(conv)
                messages_count_before = len(conv.messages)
                conv.trim_to_token_limit(model_max)
                messages_count_after = len(conv.messages)
                self._last_trim_removed = messages_count_before - messages_count_after

                # Get tools for this agent (filtered by allowed_tools if set)
                from agent.tools import get_tool_definitions_for_api
                tools = get_tool_definitions_for_api(conv.allowed_tools)

                # Phase B: Merge MCP tools if configured
                if conv.mcp_servers:
                    try:
                        from utils.mcp_client import get_tools_for_api
                        mcp_tools = get_tools_for_api(
                            conv.mcp_servers,
                            session_key if session_key != "_unknown" else None,
                        )
                        tools.extend(mcp_tools)
                    except Exception as e:
                        logger.warning(f"Failed to load MCP tools for {session_key}: {e}")

                # KB synthesis (Tier 2): prepare messages with KB context if applicable.
                # The helper is called once per tool-loop iteration, but kb_lookup itself
                # only runs once per _run_loop invocation (gated by the per-turn cache
                # passed in via kb_cache). The cache survives across iterations.
                messages_for_call, kb_context, _kb_cache_for_turn = self._prepare_kb_synthesis(
                    conv, text, messages, _kb_cache_for_turn
                )
                response = self._call_llm(session_key, messages_for_call, tools)

                # Extract content and tool calls
                # Determine provider from conversation model
                model = conv.model or self._config.default_model
                loop_provider = model.split("/")[0] if "/" in model else model
                text_content = _extract_text_content(response, loop_provider)
                tool_calls_raw = _extract_tool_calls(response, loop_provider)

                # Record usage
                prompt_tok, comp_tok = _extract_usage(response, loop_provider)
                cost = _cost_for_model(conv.model, prompt_tok, comp_tok)
                conv.record_usage(prompt_tok + comp_tok, cost)
                self._dispatch(self._on_token_usage, session_key, prompt_tok + comp_tok, cost)

                # §4.15 — Token budget breakdown for observability.
                # Reuses the model_max that the trim call above already computed.
                if self._on_token_breakdown is not None:
                    breakdown = conv.get_token_breakdown(model_max)
                    breakdown["trimmed_this_turn"] = self._last_trim_removed > 0
                    breakdown["messages_remaining"] = len(conv.messages)
                    breakdown["messages_removed_this_turn"] = self._last_trim_removed
                    self._dispatch(self._on_token_breakdown, session_key, breakdown)
                    self._last_trim_removed = 0

                logger.debug("[tool-loop] sk=%s llm response: text_len=%d tool_calls=%d tokens=%d cost=%.4f",
                             session_key, len(text_content or ""), len(tool_calls_raw),
                             prompt_tok + comp_tok, cost)

                if not tool_calls_raw:
                    # Text-only response — but check for empty/missing content
                    # which may indicate a provider error that wasn't raised (e.g. body-level
                    # error that slipped through, or malformed response with no choices)
                    if not text_content and not response.get("choices"):
                        logger.warning("[tool-loop] sk=%s LLM returned no choices and no content — treating as error",
                                       session_key)
                        conv.add_assistant_message("", [])
                        self._dispatch(self._on_error, session_key,
                                        "Agent returned no content. This may indicate a configuration error "
                                        "or an issue with the LLM provider.")
                        self._auto_save(session_key, conv)
                        return

                    # ── KB fallback chain ────────────────────────────────────
                    # If the primary provider returned [KB_OUT_OF_SCOPE] and a
                    # fallback_provider is configured, retry with the fallback
                    # model. One-shot guard prevents infinite loops.
                    if (
                        text_content == KB_OUT_OF_SCOPE
                        and conv.fallback_provider
                        and not getattr(conv, "_fallback_attempted", False)
                    ):
                        conv._fallback_attempted = True
                        logger.info(
                            "[tool-loop] sk=%s KB_OUT_OF_SCOPE — retrying with fallback provider %s",
                            session_key, conv.fallback_provider,
                        )
                        original_model = conv.model
                        # Resolve fallback model the same way the primary path does:
                        #   f"{provider_name}/{provider.default_model}"
                        # See AgentRuntimeHandler._resolve_agent_model() at ui/handlers/agent_runtime_handler.py
                        fallback_provider_name = conv.fallback_provider
                        fallback_provider_cfg = self._config.providers.get(fallback_provider_name) if fallback_provider_name else None
                        if fallback_provider_cfg and fallback_provider_cfg.default_model:
                            default_model = fallback_provider_cfg.default_model
                            if "/" in default_model:
                                fallback_model = default_model
                            else:
                                fallback_model = f"{fallback_provider_name}/{default_model}"
                        else:
                            # Provider not configured — fall back to provider name (runtime will error clearly)
                            fallback_model = fallback_provider_name
                        conv.model = fallback_model
                        try:
                            # Inject KB context into fallback LLM call. Uses the
                            # same helper as the Tier 2 primary-call path so
                            # both paths share one format string.
                            messages_with_context = self._inject_kb_context(messages, kb_context, text)
                            fb_response = self._call_llm(session_key, messages_with_context, tools)
                            fb_provider = fallback_model.split("/")[0] if "/" in fallback_model else fallback_model
                            fb_text = _extract_text_content(fb_response, fb_provider)
                            fb_tool_calls = _extract_tool_calls(fb_response, fb_provider)
                            # Use fallback response as the text content
                            text_content = fb_text
                            tool_calls_raw = fb_tool_calls
                            # Record fallback usage
                            fb_prompt, fb_comp = _extract_usage(fb_response, fb_provider)
                            fb_cost = _cost_for_model(fallback_model, fb_prompt, fb_comp)
                            conv.record_usage(fb_prompt + fb_comp, fb_cost)
                            self._dispatch(self._on_token_usage, session_key, fb_prompt + fb_comp, fb_cost)
                            logger.debug("[tool-loop] sk=%s fallback response: text_len=%d tool_calls=%d",
                                         session_key, len(fb_text or ""), len(fb_tool_calls))
                        except Exception as e:
                            logger.warning("[tool-loop] sk=%s fallback call failed: %s", session_key, e)
                            # Fallback failed — show the original sentinel (or error message)
                        finally:
                            conv.model = original_model

                    # Text-only response — done
                    logger.debug("[tool-loop] sk=%s text-only response, dispatching on_response_complete len=%d",
                                 session_key, len(text_content or ""))
                    conv.add_assistant_message(text_content, [])
                    self._dispatch(self._on_response_complete, session_key, text_content)
                    self._check_and_stop_on_limit(session_key, conv)
                    self._auto_save(session_key, conv)
                    return

                # Tool calls — execute each
                logger.debug("[tool-loop] sk=%s executing %d tool calls", session_key, len(tool_calls_raw))
                from models.conversation import ToolCall, ToolCallStatus
                from agent.tools import execute_tool

                # Create assistant message once, attach all tool calls — fixes data corruption
                # (was: conv.messages[-1].tool_calls.append(tc) — appended to USER message)
                tool_call_objects = [
                    ToolCall(call_id=call_id, tool_name=tool_name, arguments=args)
                    for call_id, tool_name, args in tool_calls_raw
                ]
                conv.add_assistant_message(text_content, tool_call_objects)

                for call_id, tool_name, args in tool_calls_raw:
                    tc = next(tc for tc in tool_call_objects if tc.call_id == call_id)

                    # Approval gating for exec_command — fires BEFORE tool_call_start
                    # so the approval card appears first. Non-approval tools skip this.
                    if tool_name == "exec_command":
                        approved = self._dispatch_approval(session_key, tool_name, args)
                        logger.debug("[tool-loop] sk=%s exec_command approval: %s", session_key, approved)
                        if approved is False or approved is None:  # None = timeout = denial
                            tc.mark_failed("exec_command requires PM approval — request denied or timed out")
                            conv.add_tool_result(call_id, tc.result or "denied")
                            self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied")
                            continue

                    # Tool call start — fires AFTER approval (for exec_command)
                    # so the "running" card is truthful: the tool is actually about to run.
                    self._dispatch(self._on_tool_call_start, session_key, tool_name, args)
                    tc.mark_executing()

                    # Execute tool
                    import agent.tools as agent_tools_module
                    from agent.tools import execute_tool, set_approval_callback, _approval_callback
                    logger.debug("[tool-loop] sk=%s executing tool: %s args_keys=%s",
                                 session_key, tool_name, list(args.keys()))
                    # Bypass exec_command's internal approval check — the runtime already
                    # confirmed PM approval via _dispatch_approval above (returned True).
                    prev_cb = _approval_callback
                    set_approval_callback(lambda *a: True)
                    try:
                        result = execute_tool(tool_name, args, conv.project_path or "/tmp", session_key)
                    finally:
                        set_approval_callback(prev_cb)
                    logger.debug("[tool-loop] sk=%s tool %s result: success=%s output_len=%d",
                                 session_key, tool_name, result.success, len(result.output or ""))

                    # === ENFORCEMENT LAYER HOOK ===
                    # Two-level gate: (1) global config enabled, (2) per-agent SI override
                    global_enabled = self._config.enforcement.enabled
                    agent_enabled = conv.si_enforcement if conv.si_enforcement is not None else True
                    if tool_name in ("write_file", "edit_file") and global_enabled and agent_enabled:
                        enf_result = _enforcement_check(
                            tool_name, args, result,
                            conv.project_path or "/tmp",
                            self._config.enforcement,
                        )
                        if enf_result.appended_message:
                            result = dataclasses.replace(
                                result,
                                output=(result.output or "") + "\n" + enf_result.appended_message,
                            )
                            for check in enf_result.checks:
                                self._dispatch(
                                    self._on_enforcement_status,
                                    session_key, tool_name,
                                    {
                                        "tier": check.tier,
                                        "file": check.file,
                                        "passed": check.passed,
                                        "detail": check.detail,
                                    },
                                )
                    # === END ENFORCEMENT HOOK ===

                    # §E: Stuck detection — record this tool call and check for loops
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
                        # Phase CB-3: store as transient signal, NOT in conv.messages.
                        # The next LLM call will prepend it to the request's messages list.
                        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
                        self._pending_stuck_messages.setdefault(session_key, []).append(stuck_msg)

                    # Record tool result — ToolResult dataclass stays clean
                    tc.mark_completed(result.output if result.success else result.error or "")
                    tool_result_text = tc.result or ""

                    conv.add_tool_result(call_id, tool_result_text)
                    self._dispatch(self._on_tool_call_result, session_key, tool_name, tool_result_text)

                # Check cost/step limits after tool execution
                if self._check_and_stop_on_limit(session_key, conv):
                    return

            # Max iterations reached
            conv.add_assistant_message("[max tool iterations reached]", [])
            self._dispatch(self._on_error, session_key, "Max tool iterations reached")
            self._auto_save(session_key, conv)

        except Exception as e:
            logger.exception("Error in tool loop for %s", session_key)
            self._dispatch(self._on_error, session_key, str(e))

    def _dispatch_approval(self, session_key: str, tool_name: str, args: dict) -> bool | None:
        """
        Dispatch approval request. Returns True/False if callback resolves immediately,
        or None if the callback is async (waits for PM).
        """
        if self._on_tool_call_approval_needed is None:
            return False

        result_ref: list = [None]
        event = threading.Event()

        approval_key = f"{session_key}:{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._pending_approvals[approval_key] = {
                "event": event,
                "result_ref": result_ref,
            }

        # Dispatch to callback — PM must click Approve/Deny to resolve.
        # do_approval() MUST NOT set event or result_ref. Those are only set
        # by approve_exec() when the PM clicks. Setting them here causes the
        # event to fire immediately (before PM clicks), making approval meaningless.
        def do_approval():
            try:
                self._on_tool_call_approval_needed(session_key, tool_name, args)
            except Exception:
                logger.exception("Approval callback raised exception")

        if self._GLib is not None:
            self._GLib.idle_add(do_approval)
        else:
            t = threading.Thread(target=do_approval, daemon=True)
            t.start()

        # Wait for approval (with timeout).
        # approve_exec() sets event and result_ref when PM clicks.
        # If timeout expires, treat as denial so the tool loop doesn't execute.
        timed_out = not event.wait(timeout=60)
        if timed_out:
            result_ref[0] = False
        return result_ref[0]

    @staticmethod
    def _resolve_caller_key(provider_cfg: "LLMProviderConfig | None", model: str) -> str:
        """Return the API caller key for a provider.

        Uses provider_cfg.caller (explicit, persisted in providers.yaml).
        If empty, returns empty string — the caller will then fail with a
        clear "no caller" error.
        """
        if provider_cfg is not None and provider_cfg.caller:
            return provider_cfg.caller.lower()
        return ""

    def _call_llm(
        self,
        session_key: str,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """
        Make a single LLM API call. Uses SSE streaming when on_text_delta is set
        (Phase 1.3b), otherwise falls back to blocking.
        """
        # Phase CB-3: prepend pending stuck messages as transient prefixes.
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        pending = self._pending_stuck_messages.pop(session_key, [])
        if pending:
            stuck_prefix = {
                "role": "user",
                "content": (
                    "[Stuck-detection intervention — please consider a different approach]\n\n"
                    + "\n\n---\n\n".join(pending)
                ),
            }
            messages = [stuck_prefix] + messages
            logger.debug("[stuck-injection] sk=%s: prepended %d stuck message(s)", session_key, len(pending))

        # Use self._config (already loaded once at startup) — Bug #12 fix
        config = self._config

        conv = self._conversations.get(session_key)
        if conv is None:
            raise ValueError("No conversation found")

        model = conv.model or config.default_model
        provider_name = model.split("/")[0] if "/" in model else model

        provider_cfg = config.providers.get(provider_name)
        if provider_cfg is None:
            # If the agent specified a provider explicitly (model has a prefix like
            # "openrouter/"), don't silently fall back to the wrong provider — raise
            # a clear error so the user knows to configure it.
            if "/" in model and config.providers:
                raise ValueError(
                    f"Provider '{provider_name}' is not configured. "
                    f"Add it to Settings → Providers (or agent.json), "
                    f"or set an API key in the agent editor. "
                    f"Available providers: {', '.join(sorted(config.providers.keys()))}"
                )
            if config.providers:
                provider_name = list(config.providers.keys())[0]
                provider_cfg = config.providers[provider_name]
            else:
                raise ValueError(f"No LLM provider configured for {model}")

        # Use per-agent API key if set, otherwise fall back to provider config
        effective_api_key = conv.api_key or provider_cfg.api_key
        if not effective_api_key:
            # Phase B: providers.yaml is the canonical store for API keys.
            # Fall back to scanning the yaml file when neither conv.api_key nor
            # provider_cfg.api_key is set.
            try:
                from utils.providers_store import load_providers
                for p in load_providers():
                    if p.name == provider_name and p.api_key:
                        effective_api_key = p.api_key
                        break
            except Exception as e:
                logger.warning("Cannot load providers.yaml fallback for %s: %s", provider_name, e)
        # Use app_title as X-Title header for OpenRouter attribution
        x_title = conv.app_title or ""

        # Use streaming when on_text_delta is registered AND the provider supports it
        use_streaming = (
            self._on_text_delta is not None
            and (provider_cfg.supports_streaming if provider_cfg else True)
        )
        if use_streaming:
            logger.debug("[call-llm] sk=%s streaming=True provider=%s model=%s msg_count=%d",
                         session_key, provider_name, model, len(messages))
            caller_key = self._resolve_caller_key(provider_cfg, model)
            return self._call_llm_streaming(
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=effective_api_key,
                model=model,
                caller_key=caller_key,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )

        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"No caller for provider {provider_cfg.name if provider_cfg else provider_name} "
                f"(caller_key={caller_key!r}). "
                f"Set the 'caller' field in Settings → Providers."
            )

        return caller(
            base_url=provider_cfg.base_url,
            api_key=effective_api_key,
            model=model,
            messages=messages,
            tools=tools if tools else None,
            timeout=float(self._config.tool_timeout_seconds),
            x_title=x_title,
        )

    def _call_llm_streaming(
        self,
        session_key: str,
        base_url: str,
        api_key: str,
        model: str,
        caller_key: str,
        messages: list[dict],
        tools: list[dict] | None,
        timeout: float,
        x_title: str = "",
    ) -> dict:
        """
        Call the LLM with streaming. Fires on_text_delta as chunks arrive,
        on_tool_call_start when a tool call is complete, and returns the
        assembled response dict when done.

        Parameter contract: see StreamingCallKwargs — the fields there must
        match this method's parameters exactly. The regression test
        (TestStreamingSignature) derives expected_params from the TypedDict.

        Returns:
            Assembled response dict compatible with _extract_tool_calls / _extract_text_content.
        """
        # Phase CB-3: prepend pending stuck messages as transient prefixes.
        # (Same fix as _call_llm; streaming path needs it too.)
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        pending = self._pending_stuck_messages.pop(session_key, [])
        if pending:
            stuck_prefix = {
                "role": "user",
                "content": (
                    "[Stuck-detection intervention — please consider a different approach]\n\n"
                    + "\n\n---\n\n".join(pending)
                ),
            }
            messages = [stuck_prefix] + messages
            logger.debug("[stuck-injection] sk=%s (streaming): prepended %d stuck message(s)", session_key, len(pending))

        # PHASE-11: caller_key is resolved by _call_llm before calling this method
        # (explicit caller > default_model prefix > model prefix). Symmetric with
        # the non-streaming path.
        streamer = _PROVIDER_STREAMERS.get(caller_key)
        if streamer is None:
            raise ValueError(
                f"No streaming caller for caller_key={caller_key!r} "
                f"(model={model!r}). Check provider's 'caller' field in Settings → Providers."
            )

        full_content = ""
        # tool_call_index → {name, arguments, done}
        tool_calls_partial: dict[int, dict] = {}
        # Phase CB-3: usage captured from SSE "usage" event (BUG #3 fix).
        captured_usage: dict = {}

        for ev in streamer(base_url, api_key, model, messages, tools, timeout, x_title=x_title):
            if ev.type == "text_delta":
                text = ev.data.get("content") or ""
                full_content += text
                if self._on_text_delta:
                    self._dispatch(self._on_text_delta, session_key, text)

            elif ev.type == "tool_call_delta":
                # PHASE-11.5: default to 0 if streamer omits 'index' (e.g. Anthropic
                # single-tool responses). Without this, the runtime crashes mid-stream.
                idx = ev.data.get("index", 0)
                if idx not in tool_calls_partial:
                    tool_calls_partial[idx] = {"name": "", "arguments": ""}
                tc = tool_calls_partial[idx]
                if ev.data["name"]:
                    tc["name"] = ev.data["name"]
                if ev.data["arguments"]:
                    tc["arguments"] += ev.data["arguments"]

            elif ev.type == "usage":
                # Provider sent a usage chunk (e.g., OpenAI's "final" frame).
                # Capture the most recent one; the final response uses it.
                # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.2 (BUG #3 fix).
                usage_data = ev.data.get("usage", {})
                if isinstance(usage_data, dict) and usage_data:
                    captured_usage = usage_data

            elif ev.type == "done":
                # Build final tool_calls list from accumulated partials
                tool_calls = []
                for idx in sorted(tool_calls_partial.keys()):
                    tc = tool_calls_partial[idx]
                    if tc["name"]:
                        tool_calls.append({
                            "id": f"call_{idx}",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        })
                logger.debug("[stream] sk=%s done: text_len=%d tool_calls=%d usage_captured=%s",
                             session_key, len(full_content), len(tool_calls),
                             bool(captured_usage))
                return {
                    "choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}],
                    "usage": captured_usage,
                }

        # Fallback — stream ended without explicit done event (e.g. provider doesn't send [DONE])
        tool_calls = []
        for idx in sorted(tool_calls_partial.keys()):
            tc = tool_calls_partial[idx]
            if tc["name"]:
                tool_calls.append({
                    "id": f"call_{idx}",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"]
                    }
                })
        logger.debug("[stream-fallback] sk=%s text_len=%d tool_calls=%d (no done event)",
                     session_key, len(full_content), len(tool_calls))
        return {"choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}], "usage": captured_usage}

    def _check_stuck(self, session_key: str, tool_name: str, args: dict, iteration: int) -> str | None:
        """
        §E — Stuck detection.

        Monitor tool call history for signs the agent is looping:
        - Same tool + same args 3+ times in last 10 calls → intervention
        - 8+ write_file calls with no exec_command in last 8 → intervention

        Returns an intervention message string, or None if not stuck.
        """
        with self._tool_history_lock:
            history = self._tool_history.setdefault(session_key, [])
            args_str = str(sorted(args.items()))
            args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
            history.append({"tool": tool_name, "args_hash": args_hash, "iteration": iteration})

            # Keep only last 20 entries
            if len(history) > 20:
                history[:] = history[-20:]

            # Check 1: same tool + same args 3+ times in last 10
            recent = history[-10:]
            same_count = sum(
                1 for e in recent
                if e["tool"] == tool_name and e["args_hash"] == args_hash
            )
            if same_count >= 3:
                return (
                    f"[stuck-detection] You've called {tool_name} with the same arguments "
                    f"{same_count} times in recent iterations. You appear to be stuck. "
                    f"Consider: re-reading the file, checking the error message carefully, "
                    f"or trying a completely different approach. "
                    f"If you've tried 3+ approaches without progress, report as blocked."
                )

            # Check 2: 8+ write operations with no verification commands
            recent_tools = [e["tool"] for e in recent]
            write_ops = recent_tools.count("write_file") + recent_tools.count("edit_file")
            if write_ops >= 8 and "exec_command" not in recent_tools[-8:]:
                return (
                    "[stuck-detection] You've written files 8+ times without running any "
                    "commands to verify. Run tests or check syntax before continuing."
                )

            return None

    def _cleanup_tool_history(self, session_key: str) -> None:
        """Remove tool history and pending stuck messages for a session when conversation ends."""
        with self._tool_history_lock:
            self._tool_history.pop(session_key, None)
        # Phase CB-3: also clean up pending stuck messages
        self._pending_stuck_messages.pop(session_key, None)

    def _check_and_stop_on_limit(self, session_key: str, conv: Any) -> bool:
        """
        Check cost and step limits. Returns True if stopped.
        """
        stopped = False
        reason = None

        if self._config.cost_limit is not None and conv.total_cost > self._config.cost_limit:
            stopped = True
            reason = f"Cost limit exceeded: ${conv.total_cost:.4f} > ${self._config.cost_limit:.4f}"
        elif self._config.step_limit is not None and conv.step_count > self._config.step_limit:
            stopped = True
            reason = f"Step limit exceeded: {conv.step_count} > {self._config.step_limit}"

        if stopped:
            conv.add_assistant_message(f"[stopped: {reason}]", [])
            self._dispatch(self._on_error, session_key, reason)
            self._auto_save(session_key, conv)

        return stopped

    def _auto_save(self, session_key: str, conv: Any) -> None:
        """Save conversation if auto_save is enabled."""
        if self._config.auto_save_conversations:
            try:
                _save_conversation_to_disk(conv, session_key)
            except Exception:
                logger.exception("Failed to auto-save conversation %s", session_key)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save_conversation(self, session_key: str) -> str:
        """Save a conversation to disk. Returns the file path."""
        with self._lock:
            conv = self._conversations.get(session_key)
            if conv is None:
                raise ValueError(f"No conversation found for {session_key}")
            path = _save_conversation_to_disk(conv, session_key)
        return path

    def load_conversation(self, session_key: str) -> bool:
        """Load a conversation from disk into the runtime. Returns True if found."""
        result = _load_conversation_from_disk(session_key)
        if result is None:
            return False
        conv, _ = result
        with self._lock:
            self._conversations[session_key] = conv
        return True

    def list_conversations(self) -> list[tuple[str, str]]:
        """List all saved conversations: [(session_key, agent_name)]."""
        d = _conversations_dir()
        try:
            files = [f for f in os.listdir(d) if f.endswith(".json")]
        except OSError:
            return []

        result = []
        for fname in files:
            sk = fname[:-5]  # strip .json
            result2 = _load_conversation_from_disk(sk)
            if result2:
                _, meta = result2
                result.append((sk, meta.get("agent_name", "unknown")))
            else:
                result.append((sk, "unknown"))
        return result

    def approve_exec(self, session_key: str, tool_name: str, args: dict, approved: bool) -> None:
        """
        Resolve a pending approval when the PM clicks Approve or Deny.

        Called by AgentRuntimeHandler.approve_exec() via the feed UI.
        Sets result_ref so _dispatch_approval's waiting thread unblocks,
        then removes the entry from _pending_approvals.
        """
        with self._lock:
            for key, pending in list(self._pending_approvals.items()):
                if key.startswith(session_key):
                    pending["result_ref"][0] = approved
                    pending["event"].set()
                    self._pending_approvals.pop(key, None)
                    logger.info("Approval resolved for %s: %s", session_key, approved)
                    return
