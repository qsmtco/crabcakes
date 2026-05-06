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
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from models.conversation import Conversation

logger = logging.getLogger(__name__)

# ── Cost tables (USD per 1M tokens) ─────────────────────────────────────────

_OPENAI_COST = {"prompt": 2.5, "completion": 10.0}    # GPT-4o
_MINIMAX_COST = {"prompt": 0.5, "completion": 1.0}   # MiniMax-M2
_ANTHROPIC_COST = {"prompt": 3.0, "completion": 15.0} # Claude 3.5

_PROVIDER_COSTS: dict[str, dict[str, float]] = {
    "openai": _OPENAI_COST,
    "minimax": _MINIMAX_COST,
    "anthropic": _ANTHROPIC_COST,
}


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
) -> dict:
    """Call OpenAI Chat Completions API."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model.split("/")[-1],
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
) -> dict:
    """Call MiniMax ChatCompletion v2 API."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
    payload = {
        "model": model.split("/")[-1],
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
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
        "model": model.split("/")[-1],
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
}


# ── SSE Streaming (Phase 1.3b) ─────────────────────────────────────────────────

import re
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


def _stream_openai_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
):
    """Yield SSE events from OpenAI Chat Completions streaming API."""
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model.split("/")[-1],
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            # Text content delta
            if "content" in delta:
                yield SSEEvent(type="text_delta", data={"content": delta["content"]})
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


def _stream_minimax_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
):
    """Yield SSE events from MiniMax ChatCompletion streaming API (OpenAI-compatible)."""
    endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
    payload = {
        "model": model.split("/")[-1],
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            if "content" in delta:
                yield SSEEvent(type="text_delta", data={"content": delta["content"]})
            tc_delta = delta.get("tool_calls", [])
            for tcd in tc_delta:
                idx = tcd.get("index", 0)
                if "function" in tcd:
                    fname = tcd["function"].get("name") or ""
                    fargs = tcd["function"].get("arguments", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })


def _stream_anthropic_events(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
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
        "model": model.split("/")[-1],
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            elif etype == "message_stop":
                yield SSEEvent(type="done", data={})
                return


_PROVIDER_STREAMERS: dict[str, Any] = {
    "openai": _stream_openai_events,
    "minimax": _stream_minimax_events,
    "anthropic": _stream_anthropic_events,
}


def _call_llm_streaming(
    runtime,  # AgentRuntime instance — for GLib dispatch
    session_key: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
) -> dict:
    """
    Call the LLM with streaming. Fires on_text_delta as chunks arrive,
    on_tool_call_start when a tool call is complete, and returns the
    assembled response dict when done.

    Returns:
        Assembled response dict compatible with _extract_tool_calls / _extract_text_content.
    """
    provider_name = model.split("/")[0] if "/" in model else model
    streamer = _PROVIDER_STREAMERS.get(provider_name)
    if streamer is None:
        raise ValueError(f"No streaming caller for provider {provider_name}")

    full_content = ""
    # tool_call_index → {name, arguments, done}
    tool_calls_partial: dict[int, dict] = {}

    for ev in streamer(base_url, api_key, model, messages, tools, timeout):
        if ev.type == "text_delta":
            text = ev.data["content"]
            full_content += text
            if runtime._on_text_delta:
                runtime._dispatch(runtime._on_text_delta, session_key, text)

        elif ev.type == "tool_call_delta":
            idx = ev.data["index"]
            if idx not in tool_calls_partial:
                tool_calls_partial[idx] = {"name": "", "arguments": ""}
            tc = tool_calls_partial[idx]
            if ev.data["name"]:
                tc["name"] = ev.data["name"]
            if ev.data["arguments"]:
                tc["arguments"] += ev.data["arguments"]

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
            return {
                "choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}],
                "usage": {},  # streaming responses omit usage; caller should use blocking call for accurate counts
            }

    # Should not reach here — done event should always fire
    return {"choices": [{"message": {"content": full_content, "tool_calls": []}}]}



# ── Tool call normalization ─────────────────────────────────────────────────────

def _extract_tool_calls(response: dict, provider: str) -> list[tuple[str, str, dict]]:
    """
    Extract tool calls from an API response dict.

    Returns [(call_id, tool_name, arguments)].

    Handles OpenAI, MiniMax, and Anthropic formats.
    """
    calls = []

    if provider in ("openai", "minimax"):
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

    elif provider == "anthropic":
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
    if provider in ("openai", "minimax"):
        choices = response.get("choices", [])
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        return msg.get("content", "") or ""

    elif provider == "anthropic":
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
    if provider == "anthropic":
        return (
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
    # OpenAI / MiniMax
    return (
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


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
        on_error: Callable | None = None,
    ):
        self._config = config
        self._GLib = GLib
        self._on_text_delta = on_text_delta
        self._on_tool_call_start = on_tool_call_start
        self._on_tool_call_result = on_tool_call_result
        self._on_tool_call_approval_needed = on_tool_call_approval_needed
        self._on_response_complete = on_response_complete
        self._on_token_usage = on_token_usage
        self._on_error = on_error

        # conversation_key → Conversation
        self._conversations: dict[str, Any] = {}
        # session_key → pending_approval {tool_name, args, result_event, result_ref}
        self._pending_approvals: dict[str, dict] = {}
        self._cancelled: set[str] = set()  # cancelled session keys
        self._cancel_requested: bool = False  # immediate cancel signal for running thread
        self._lock = threading.Lock()
        self._running = False

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
    ) -> str:
        """
        Create a new conversation for an agent.

        Returns the session_key (same as the argument).

        Args:
            allowed_tools: If provided, only these tool names are available to
                          the agent. If None, all tools are available.
        """
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
        system_prompt = build_system_prompt(agent_name, project_path, tool_names)

        conv = Conversation(
            agent_name=agent_name,
            project_path=project_path,
            allowed_tools=allowed_tools,
            model=model,
            system_prompt=system_prompt,
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

    # ── Tool loop ─────────────────────────────────────────────────────────────

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

            # Step 2: loop until no tool calls or limit hit
            iteration = 0
            max_iter = self._config.max_tool_iterations

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

                # Build API messages
                from models.conversation import MessageRole
                messages = conv.to_api_messages()

                # Get tools for this agent (filtered by allowed_tools if set)
                from agent.tools import get_tool_definitions_for_api
                tools = get_tool_definitions_for_api(conv.allowed_tools)

                # Call LLM
                response = self._call_llm(session_key, messages, tools)

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

                if not tool_calls_raw:
                    # Text-only response — done
                    conv.add_assistant_message(text_content, [])
                    self._dispatch(self._on_response_complete, session_key, text_content)
                    self._check_and_stop_on_limit(session_key, conv)
                    self._auto_save(session_key, conv)
                    return

                # Tool calls — execute each
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
                    self._dispatch(self._on_tool_call_start, session_key, tool_name, args)
                    tc.mark_executing()

                    # Approval gating for exec_command
                    if tool_name == "exec_command":
                        approved = self._dispatch_approval(session_key, tool_name, args)
                        if approved is False or approved is None:  # None = timeout = denial
                            tc.mark_failed("exec_command requires PM approval — request denied or timed out")
                            conv.add_tool_result(call_id, tc.result or "denied")
                            self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied")
                            continue

                    # Execute tool
                    import agent.tools as agent_tools_module
                    from agent.tools import execute_tool, set_approval_callback, _approval_callback
                    # Bypass exec_command's internal approval check — the runtime already
                    # confirmed PM approval via _dispatch_approval above (returned True).
                    prev_cb = _approval_callback
                    set_approval_callback(lambda *a: True)
                    try:
                        result = execute_tool(tool_name, args, conv.project_path or "/tmp", session_key)
                    finally:
                        set_approval_callback(prev_cb)
                    tc.mark_completed(result.output if result.success else result.error or "")
                    conv.add_tool_result(call_id, tc.result or "")
                    self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "")

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
        # Use self._config (already loaded once at startup) — Bug #12 fix
        config = self._config

        conv = self._conversations.get(session_key)
        if conv is None:
            raise ValueError("No conversation found")

        model = conv.model or config.default_model
        provider_name = model.split("/")[0] if "/" in model else model

        provider_cfg = config.providers.get(provider_name)
        if provider_cfg is None:
            # Fall back to first available provider
            if config.providers:
                provider_name = list(config.providers.keys())[0]
                provider_cfg = config.providers[provider_name]
            else:
                raise ValueError(f"No LLM provider configured for {model}")

        # Use streaming when on_text_delta callback is registered (Phase 1.3b)
        if self._on_text_delta is not None:
            return _call_llm_streaming(
                runtime=self,
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=provider_cfg.api_key,
                model=model,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
            )

        caller = _PROVIDER_CALLERS.get(provider_name)
        if caller is None:
            raise ValueError(f"No caller for provider {provider_name}")

        return caller(
            base_url=provider_cfg.base_url,
            api_key=provider_cfg.api_key,
            model=model,
            messages=messages,
            tools=tools if tools else None,
            timeout=float(self._config.tool_timeout_seconds),
        )

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
