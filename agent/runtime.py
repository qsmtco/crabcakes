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
import re
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypedDict

if TYPE_CHECKING:
    from models.conversation import Conversation
    from agent.config import LLMProviderConfig

from agent.enforcement import check as _enforcement_check
from agent.tool_middleware import (
    EnforcementMiddleware,
    StuckDetectionMiddleware,
    ToolContext,
    ToolMiddlewareChain,
)

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
    "_is_retryable_ssl_error",
    "_stream_with_ssl_retry",
    "_friendly_error_message",
]

logger = logging.getLogger(__name__)

# ── Audit Log (A-4) ──────────────────────────────────────────────────────────

class AuditEntry:
    """Single audit log entry for a tool execution."""
    __slots__ = ("tool_name", "args_hash", "approved", "user", "timestamp", "result_hash", "exit_code")

    def __init__(self, tool_name: str, args_hash: str, approved: bool | None,
                 user: str, timestamp: float, result_hash: str = "", exit_code: int | None = None):
        self.tool_name = tool_name
        self.args_hash = args_hash
        self.approved = approved
        self.user = user
        self.timestamp = timestamp
        self.result_hash = result_hash
        self.exit_code = exit_code


class AuditLog:
    """In-memory audit log for tool executions (A-4).

    Defense-in-depth: records tool name, args hash (not raw args),
    approval decision, user identity, timestamp, and result hash.
    In-memory by default; flush to disk via flush_audit_log().
    """

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    def record(self, tool_name: str, args: dict, approved: bool | None,
               user: str, result: str = "", exit_code: int | None = None) -> None:
        """Record a tool execution in the audit log."""
        args_hash = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        result_hash = hashlib.sha256(result.encode()).hexdigest()[:16] if result else ""
        entry = AuditEntry(
            tool_name=tool_name,
            args_hash=args_hash,
            approved=approved,
            user=user,
            timestamp=time.time(),
            result_hash=result_hash,
            exit_code=exit_code,
        )
        with self._lock:
            self._entries.append(entry)

    def flush_audit_log(self, path: str | None = None) -> str | None:
        """Flush audit log to disk as JSON lines.

        Args:
            path: Output file path. Defaults to ~/.config/crabcakes/audit-log.jsonl.

        Returns:
            The file path written, or None if no entries.
        """
        from utils.config import get_config_dir
        if path is None:
            path = os.path.join(get_config_dir(), "audit-log.jsonl")
        with self._lock:
            if not self._entries:
                return None
            entries = list(self._entries)
            self._entries.clear()
        with open(path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps({
                    "tool_name": e.tool_name,
                    "args_hash": e.args_hash,
                    "approved": e.approved,
                    "user": e.user,
                    "timestamp": e.timestamp,
                    "result_hash": e.result_hash,
                    "exit_code": e.exit_code,
                }) + "\n")
        return path

    @property
    def entries(self) -> list[AuditEntry]:
        with self._lock:
            return list(self._entries)


# ── Cost tables + functions (extracted to agent/llm/cost.py, Phase B1) ──────
# Re-exported under legacy underscore names for backward compatibility.
from agent.llm.cost import cost_for_model

# ── Anthropic converters (extracted to agent/llm/convert.py, Phase B2) ──────
# Re-exported under legacy underscore names for backward compatibility.
from agent.llm.convert import (
    convert_messages_for_anthropic as _convert_messages_for_anthropic,
    convert_tools_for_anthropic as _convert_tools_for_anthropic,
)

# ── LLM providers (extracted to agent/llm/, Phase B4) ───────────────────────
# Re-exported under legacy names for backward compatibility.
from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider
from agent.llm.registry import get_provider as _get_provider

# Bound methods for test-patch compatibility (patch("agent.runtime._call_openai"))
_call_openai = OpenAIProvider("openai").call
_call_minimax = MiniMaxProvider().call
_call_anthropic = AnthropicProvider().call

# DEPRECATED: dispatch now uses get_provider(caller_key).call().
# This dict is retained for backward compatibility with test patches and
# get_valid_callers(). Do not add new dispatch logic here — use
# agent.llm.registry.get_provider().
_PROVIDER_CALLERS: dict[str, Any] = {
    "openai": _call_openai,
    "minimax": _call_minimax,
    "anthropic": _call_anthropic,
    "openrouter": OpenAIProvider("openrouter").call,
    "zai": OpenAIProvider("zai").call,
}


def get_valid_callers() -> frozenset[str]:
    """Return the frozenset of valid caller keys for ProviderConfig.caller.

    Single source of truth for the provider-caller taxonomy. The set is
    derived from _PROVIDER_CALLERS.keys() at module level — adding a new
    adapter to the dict automatically extends the valid set.

    Used by:
      - ui/handlers/settings_handler.py (save-time validation, Test Connection)
      - tests/test_settings_handler.py (regression coverage)
      - tests/test_providers_store.py (verify duplication invariant)

    Layer rule: utils/* cannot import from agent/*, so utils/providers_store.py
    DUPLICATES this set as a module-level constant. The duplication is enforced
    by a regression test in tests/test_providers_store.py
    (TestValidCallersDuplicationInvariant).

    Returns:
        frozenset of strings: {"anthropic", "minimax", "openai",
        "openrouter", "zai"} (alphabetically sorted; order is irrelevant).
    """
    return frozenset(_PROVIDER_CALLERS.keys())


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


# ── SSE streaming helpers (extracted to agent/llm/streaming.py, Phase B5) ──
# Re-exported under legacy underscore names for backward compatibility.
from agent.llm.streaming import (
    SSEEvent,
    sse_lines as _sse_lines,
    parse_sse_line as _parse_sse_line,
    parse_sse_delta as _parse_sse_delta,
    first_choice as _first_choice,
    urlopen_with_ssl_retry as _urlopen_with_ssl_retry,
    stream_with_ssl_retry as _stream_with_ssl_retry,
    is_retryable_ssl_error as _is_retryable_ssl_error,
    friendly_error_message as _friendly_error_message,
    RETRYABLE_SSL_ERRORS as _RETRYABLE_SSL_ERRORS,
    RETRYABLE_OSERROR_TYPES as _RETRYABLE_OSERROR_TYPES,
    MAX_SSL_RETRIES as _MAX_SSL_RETRIES,
    SSL_RETRY_BASE_MS as _SSL_RETRY_BASE_MS,
)

import urllib.error
import urllib.request


# ── Stream functions (moved to provider classes, Phase B6) ──────────────────
# Re-exported as bound methods for backward compatibility with test patches.
_stream_openai_events = OpenAIProvider("openai").stream
_stream_minimax_events = MiniMaxProvider().stream
_stream_anthropic_events = AnthropicProvider().stream

# DEPRECATED: dispatch now uses get_provider(caller_key).stream().
# This dict is retained for backward compatibility with test patches.
# Do not add new dispatch logic here — use agent.llm.registry.get_provider().
_PROVIDER_STREAMERS: dict[str, Any] = {
    "openai": _stream_openai_events,
    "minimax": _stream_minimax_events,
    "anthropic": _stream_anthropic_events,
    "openrouter": OpenAIProvider("openrouter").stream,  # OpenAI-compatible SSE
    "zai": OpenAIProvider("zai").stream,        # OpenAI-compatible SSE
}






# ── Tool call normalization ─────────────────────────────────────────────────────

# ── Response extractors (extracted to agent/llm/extractors.py, Phase B3) ────
# Re-exported under legacy underscore names for backward compatibility.
# _is_empty_content stays here (used at non-extractor sites).
from agent.llm.extractors import (
    extract_tool_calls as _extract_tool_calls,
    extract_text_content as _extract_text_content,
    extract_usage as _extract_usage,
)


def _is_empty_content(text) -> bool:
    """True if text_content is empty or whitespace-only.

    Used at write-side call sites to decide whether to substitute a placeholder
    before persisting. Matches the BUG #1 guard semantics so all empty-content
    paths produce consistent behavior.

    Covers:
    - None / missing
    - empty string ""
    - strings of only ASCII whitespace ("\\n", " \\t ", etc.)
    - strings of only Unicode whitespace (U+00A0 NBSP, U+2028 line sep, etc.)
    - strings of only "format" characters that some providers also reject
      (U+200B zero-width space, U+FEFF BOM, U+200C/200D ZWNJ/ZWJ)
    - empty list / dict (treated as falsy)

    Does NOT cover valid OpenAI responses with `content=None` and tool_calls
    present — that's the tool-call path which has its own guard at site 2391.
    """
    if not text:
        return True
    if isinstance(text, str):
        if text.strip() == "":
            return True
        # Zero-width / format chars: str.strip() doesn't remove these but some
        # strict providers treat them as effectively empty. Strip and re-check.
        _ZWS = "\u200b\u200c\u200d\ufeff"
        if text.translate(str.maketrans("", "", _ZWS)).strip() == "":
            return True
    return False


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
    """Return the conversations directory, creating it if needed.

    HIGH-3: parent dir is chmod 0o700 (owner only). Each conversation file
    is chmod 0o600 after write (in _save_conversation_to_disk).
    """
    from utils.config import get_config_dir
    d = os.path.join(get_config_dir(), "conversations")
    parent_existed = os.path.isdir(d)
    os.makedirs(d, exist_ok=True)
    if not parent_existed:
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return d


def _save_conversation_to_disk(conv: "Conversation", session_key: str) -> str:
    """Save a conversation to <conversations_dir>/<session_key>.json.

    HIGH-3: api_key is NOT serialized. The api_key is re-resolved on load
    from providers.yaml (atomic+0600) keyed by conv.model/conv.provider.
    Conversation files should never contain raw secrets.
    """
    path = os.path.join(_conversations_dir(), f"{session_key}.json")
    data = {
        "session_key": session_key,
        "agent_name": conv.agent_name,
        "project_path": conv.project_path,
        "model": conv.model,
        "provider": getattr(conv, "provider", None),  # HIGH-3: for api_key re-resolution on load
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
        # HIGH-3: api_key NOT serialized — re-resolved from providers.yaml on load
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
    # HIGH-3: chmod 0600 after write — conversation files contain model/provider
    # but must NOT contain raw api_key.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # non-POSIX filesystem
    return path


def _resolve_api_key_for_conversation(data: dict) -> str | None:
    """Resolve the api_key for a loaded conversation from providers.yaml.

    HIGH-3: never read api_key from the saved file. Re-resolve from the
    provider store keyed by `provider` field (or extracted from `model`).
    Returns None if no matching provider is configured.

    Args:
        data: The raw JSON data dict loaded from the conversation file.
              Expected to have a "model" key (e.g., "openai/gpt-4o") and
              optionally a "provider" key.
    """
    try:
        from utils.providers_store import load_providers
        providers = load_providers()
        if not providers:
            return None
        # Prefer explicit provider field
        provider_name = data.get("provider")
        if not provider_name:
            model = data.get("model", "")
            if "/" in model:
                provider_name = model.split("/")[0]
        if not provider_name:
            return None
        # Look up matching provider
        for p in providers:
            if p.name == provider_name:
                return p.api_key
        return None
    except Exception:
        logger.exception("[runtime] failed to resolve api_key for conversation")
        return None


def _load_conversation_from_disk(session_key: str) -> tuple["Conversation", dict] | None:
    """Load a conversation from disk. Returns (Conversation, metadata) or None.

    HIGH-3: api_key is re-resolved from providers.yaml (atomic+0600) keyed
    by conv.model. Saved api_key in old files is ignored (and stripped
    on next save by the one-time migration).
    """
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

    # HIGH-3: re-resolve api_key from providers.yaml, NOT from saved data
    api_key = _resolve_api_key_for_conversation(data)

    conv = Conversation(
        agent_name=data["agent_name"],
        # Option C+: project_path and system_prompt are NOT loaded from disk.
        # The persisted values may be stale (from a previous project the user
        # had open). They are re-applied by _rebuild_conversation_context
        # on first send, against the currently-active project. The persisted
        # values are still written on save so a manual audit can read them
        # back, but the runtime never trusts them.
        project_path=None,
        model=data.get("model", ""),
        provider=data.get("provider"),  # HIGH-3: stored so we can re-resolve api_key
        system_prompt="",
        messages=messages,
        total_tokens=data.get("total_tokens", 0),
        total_cost=data.get("total_cost", 0.0),
        step_count=data.get("step_count", 0),
        allowed_tools=data.get("allowed_tools"),
        api_key=api_key,  # HIGH-3: re-resolved from providers.yaml
        app_title=data.get("app_title", ""),
        mcp_servers=data.get("mcp_servers", []),
        si_enforcement=data.get("si_enforcement"),
        agent_role=data.get("agent_role", ""),
        fallback_provider=data.get("fallback_provider"),
        fallback_model=data.get("fallback_model"),
    )
    # allowed_tools fallback: if the persisted conversation has no
    # allowed_tools (pre-fix conversations or post-YAML-edit), fall back
    # to the live agent definition's tools list. Mirrors the HIGH-3
    # api_key re-resolution pattern: do not trust persisted state when
    # live config is available. Without this, the execute_tool gate is
    # a no-op for any conversation created before the gate shipped.
    if conv.allowed_tools is None:
        try:
            from agent.special_agents import get_special_agent
            agent_def = get_special_agent(session_key)
            if agent_def is not None and agent_def.tools:
                conv.allowed_tools = list(agent_def.tools)
        except Exception:
            pass  # Best-effort: leave None if lookup fails (gate skips)

    return conv, data


# ── HIGH-3: One-time migration ──────────────────────────────────────────────────

# Module-level flag — migration runs once per process
_CONVERSATION_MIGRATION_DONE: bool = False


def _migrate_conversation_files() -> int:
    """One-time sweep: remove api_key from existing conversation files.

    HIGH-3: scans ~/.config/crabcakes/conversations/*.json, removes the
    "api_key" field if present, writes back atomically with chmod 0600.
    New saves never include api_key. Idempotent — safe to call multiple times.

    Returns the number of files migrated.
    """
    global _CONVERSATION_MIGRATION_DONE
    if _CONVERSATION_MIGRATION_DONE:
        return 0
    _CONVERSATION_MIGRATION_DONE = True

    d = _conversations_dir()
    count = 0
    try:
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "api_key" in data:
                    del data["api_key"]
                    # Atomic write
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp, path)
                    # Ensure 0600
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                    count += 1
            except (OSError, json.JSONDecodeError):
                # Skip unreadable files — don't crash the migration
                continue
    except OSError:
        pass
    if count > 0:
        logger.info(
            "[runtime] HIGH-3 migration: removed api_key from %d conversation file(s)",
            count,
        )
    return count


# ── LOW-2: Per-session secure workspace ─────────────────────────────────────


def _resolve_session_workspace(project_path: str | None, session_key: str) -> str:
    """Return a per-session secure workspace under the project's .crabcakes/ dir.

    LOW-2: never fall back to /tmp — raise if project_path is empty.
    The workspace dir is created with 0o700 permissions (owner-only).

    Args:
        project_path: The project directory (must not be empty).
        session_key: Must be non-empty, whitespace-free, and contain only
            [a-zA-Z0-9._:-]. Path separators and ".." are rejected.
            Colons (e.g. "special:coder") are allowed and sanitized for
            filesystem safety.

    Returns:
        Absolute path to the session's scratch workspace directory.
    """
    if not project_path:
        raise ValueError(
            f"LOW-2: project_path is empty for session {session_key!r}; "
            "refusing to use a world-writable default"
        )
    # session_key validation — prevent empty keys, path escapes, and traversal
    if not session_key or not session_key.strip():
        raise ValueError(f"LOW-2: session_key must be non-empty and contain no whitespace: {session_key!r}")
    if ".." in session_key:
        raise ValueError(f"LOW-2: session_key must not contain '..': {session_key!r}")
    if not re.fullmatch(r"[a-zA-Z0-9._:-]+", session_key):
        raise ValueError(f"LOW-2: session_key must match [a-zA-Z0-9._:-]+, got: {session_key!r}")
    # Sanitize colon for filesystem safety (e.g. "special:coder" → "special-coder")
    fs_safe_key = session_key.replace(":", "-")
    workspace = os.path.join(project_path, ".crabcakes", "tmp", fs_safe_key)
    os.makedirs(workspace, mode=0o700, exist_ok=True)
    return workspace


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
              - trimmed_this_turn (bool): True if compaction removed messages this iteration.
                False on no-op iterations (where compact() was called but freed nothing).
                When True, "compaction_event" dict is also included with details.
              - messages_remaining (int): post-trim message count
              - messages_removed_this_turn (int): number of messages removed (0 if none)
        on_error: (session_key, error_message) — error occurred.
    """

    _RESPONSE_RESERVE_TOKENS = 4096  # reserve for model output tokens

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
        # §2.8: Telemetry — rolling CompactionEvent history (capped at 100) +
        # per-iteration flag for breakdown callbacks. Replaces the old scalar
        # _last_trim_removed field. The _last_trim_removed property below reads
        # the most recent layer==2 event from this history.
        self._compaction_events: list = []
        self._compaction_this_iteration: bool = False
        # Audit-Fix-26 (Bug #3): tracks the session_key of the most recent
        # breakdown dispatch so _last_trim_removed can filter _compaction_events
        # by session. Read+written only inside _run_loop's breakdown block.
        self._last_breakdown_session: str = ""
        self._on_error = on_error
        self._on_enforcement_status = on_enforcement_status

        # Phase CB-3: per-session list of pending stuck messages to send as
        # transient prefixes on the next LLM call.
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        self._pending_stuck_messages: dict[str, list[str]] = {}

        # HIGH-3: one-time migration on startup — removes api_key from existing files
        try:
            _migrate_conversation_files()
        except Exception:
            logger.exception("[runtime] conversation migration failed (non-fatal)")

        # conversation_key → Conversation
        self._conversations: dict[str, Any] = {}
        # session_key → pending_approval {tool_name, args, result_event, result_ref}
        self._pending_approvals: dict[str, dict] = {}
        self._cancelled: set[str] = set()  # cancelled session keys
        self._cancel_requested: bool = False  # immediate cancel signal for running thread
        self._lock = threading.Lock()
        self._running = False

        # FIX-CLEAR-ASK-RACE: sessions with an in-flight _run_loop. Used by
        # is_loop_active() and maintained by _run_loop's try/finally.
        self._active_loops: set[str] = set()

        # §E: Stuck detection — per-session tool call history for detecting loops
        # session_key → list[dict{"tool", "args_hash", "iteration"}]
        self._tool_history: dict[str, list[dict]] = {}
        self._tool_history_lock = threading.Lock()
        # Audit-Fix-8: Guard _compaction_events against concurrent append+truncate.
        self._compaction_lock = threading.Lock()

        # MED-1: Per-instance approval callback (takes precedence over global)
        self._approval_callback: Callable[[str, str, dict], bool] | None = None

        # A-4: Audit log for tool executions
        self._audit_log = AuditLog()

        # Track-A: Tool middleware chain (enforcement + stuck detection).
        # Approval gating stays inline in _run_loop (temporal ordering:
        # must fire before on_tool_call_start). The chain wraps only the
        # execution phase. See spec §A.2.3-§A.2.4.
        self._tool_chain = ToolMiddlewareChain([
            EnforcementMiddleware(
                enforcement_check_fn=_enforcement_check,
                on_status=self._dispatch_enforcement_status,
            ),
            StuckDetectionMiddleware(
                stuck_check_fn=self._check_stuck,
                pending_messages=self._pending_stuck_messages,
            ),
        ])

        # §0: Pluggable context management strategy.
        # DefaultContextStrategy is the extracted trim_to_token_limit algorithm
        # (Phase 1). Future: configurable via AgentConfig.context_strategy.
        from agent.context_strategy import DefaultContextStrategy
        self._context_strategy = DefaultContextStrategy()

    # ── Dispatch helpers ───────────────────────────────────────────────────────

    def set_approval_callback(self, cb: Callable[[str, str, dict], bool] | None) -> None:
        """Set per-instance approval callback (MED-1). Takes precedence over global."""
        self._approval_callback = cb

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

    def _dispatch_enforcement_status(
        self, session_key: str, tool_name: str, status: dict
    ) -> None:
        """Dispatch a per-check enforcement status to the callback.

        Called by EnforcementMiddleware for each EnforcementCheck result.
        Wraps the existing _dispatch(self._on_enforcement_status, ...) pattern
        that was inline in _run_loop (spec §A.2.3).
        """
        self._dispatch(self._on_enforcement_status, session_key, tool_name, status)

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
            except Exception as e:
                # Phase 9: log instead of silently passing. MCP cleanup is
                # best-effort during conversation replacement, but a failure
                # may indicate resource leaks that warrant investigation.
                logger.debug("MCP best-effort cleanup failed for %s: %s", session_key, e)

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
            context_mode=getattr(default_provider_cfg, "context_mode", "auto") or "auto",
        )
        # TODO: P10.8 — mid-session re-escalation. Currently the system prompt
        # is built once here and never reassigned. P10.8 will add a
        # _maybe_rebuild_system_prompt() check in the tool loop that calls
        # resolve_context_mode(turn_count, token_estimate) before each LLM call
        # and rebuilds if the effective mode changes.

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

        Option C+ lazy reconciliation: the runtime does not know the active
        project. The handler (AgentRuntimeHandler.send_to_special_agent)
        calls _rebuild_conversation_context BEFORE this method, so by the
        time we get here the in-memory conversation is already in sync.
        If the handler is bypassed (tests, future callers), the conversation
        may have a stale project_path. In that case the FIRST call from a
        cold context fires _rebuild_conversation_context here — the
        short-circuit in that method makes this O(1) when already in sync.
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
          2. caller_default_max_tokens(provider.caller) — per-caller static fallback
             (e.g. MiniMax = 1_048_576, Anthropic = 200_000)
          3. 128_000 global fallback (matches the §4.15 default)

        Returns 128_000 when:
          - conv.model is None and self._config.default_provider is not configured
          - the resolved provider config has max_tokens <= 0 or None AND the
            caller is not in CALLER_DEFAULT_MAX_TOKENS
          - any exception during provider lookup
        """
        from models.providers import caller_default_max_tokens
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
            max_tokens = getattr(provider_cfg, "max_tokens", None)
            if max_tokens and int(max_tokens) > 0:
                return int(max_tokens)
            # BUG #3 fix: use caller-specific default before falling back to 128K.
            # The provider config exists but its max_tokens is unset — use the
            # per-caller static table to avoid wasting 87% of MiniMax-M3's
            # 1M context window (or 50% of Claude's 200K).
            return caller_default_max_tokens(getattr(provider_cfg, "caller", ""))
        except Exception:
            logger.exception("[model-max] failed to resolve provider max_tokens; using fallback")
            return FALLBACK

    def _compute_compaction_threshold(self, conv: "Conversation") -> tuple[int, int]:
        """Return (soft_ceiling, hard_ceiling) tuple for the conversation's provider.

        Resolution order for the threshold fraction:
          1. conv.model's provider's compaction_threshold (when set and in (0, 1])
          2. 0.80 default

        Returns:
            tuple[int, int]: (soft_ceiling, hard_ceiling) where:
                - soft_ceiling = int(hard_ceiling * threshold) — compaction trigger point
                - hard_ceiling = _compute_model_max(conv) — provider's max_tokens or 128_000 fallback

        Fallback: (102_400, 128_000) when provider resolution fails.
        """
        DEFAULT_THRESHOLD = 0.80
        try:
            provider_name = (
                conv.model.split("/")[0]
                if conv.model and "/" in conv.model
                else self._config.default_provider
            )
            threshold = DEFAULT_THRESHOLD
            if provider_name:
                provider_cfg = self._config.providers.get(provider_name)
                if provider_cfg is not None:
                    cfg_threshold = getattr(provider_cfg, "compaction_threshold", None)
                    if cfg_threshold is not None and 0 < cfg_threshold <= 1:
                        threshold = float(cfg_threshold)
        except Exception as e:
            # Defensive coding should not hide programming errors. The default
            # 0.80 is used as fallback. Operators can enable DEBUG logging to
            # see the underlying cause. A misconfigured provider shouldn't
            # crash compaction, but it shouldn't be silently invisible either.
            logger.debug(
                "_compute_compaction_threshold: failed to resolve per-provider "
                "threshold, using default %s. Error: %s",
                DEFAULT_THRESHOLD,
                e,
            )
        hard_ceiling = self._compute_model_max(conv)
        soft_ceiling = int(hard_ceiling * threshold)
        return (soft_ceiling, hard_ceiling)

    @property
    def _last_trim_removed(self) -> int:
        """Backward-compat accessor: count from latest trim-layer event.

        Derived from _compaction_events so existing read sites (breakdown
        callback) keep working without modification. Returns 0 when no
        layer==2 (trim) events have been recorded.

        Audit-Fix-24: Acquire _compaction_lock before iterating to guard against
        concurrent rebind via the append+truncate critical section.

        Audit-Fix-26 (Bug #3): _compaction_events is shared across sessions on
        a single runtime. Without per-session filtering, session A's trim
        count bleeds into session B's breakdown. Use the breakdown session
        context (passed via the breakdown callback) to filter.
        """
        # The breakdown caller knows the session_key; we read it via the
        # _last_breakdown_session helper set by the dispatch in _run_loop.
        target_session = self._last_breakdown_session
        with self._compaction_lock:
            for ev in reversed(self._compaction_events):
                if ev.layer != 2:
                    continue
                # Empty session_key on event = unscoped (back-compat with
                # pre-Audit-Fix-26 events). Match against either empty or
                # matching session_key.
                if not ev.session_key or ev.session_key == target_session:
                    return ev.messages_removed
        return 0

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
        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so
        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the
        # finally block at the end of this function.
        with self._lock:
            self._active_loops.add(session_key)
        try:
            with self._lock:
                if not self._running:
                    return
                conv = self._conversations.get(session_key)
                if conv is None:
                    self._dispatch(self._on_error, session_key, "No conversation found")
                    return

            # BUG #21: Fire a turn-start signal BEFORE any LLM call or tool processing.
            # This guarantees the handler clears _ended_sessions and emits the drawer
            # lifecycle-start separator for EVERY turn — including tool-only turns
            # (LLM streams zero text_delta events). Reuses _on_text_delta with an
            # empty string: the handler's _do_text_delta clears the flag on the first
            # delta of a turn (is_streaming is False), and the empty content is a
            # harmless no-op for text accumulation.
            if self._on_text_delta:
                self._dispatch(self._on_text_delta, session_key, "")

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

                    # §0: Pluggable context strategy — compaction before each LLM call.
                    # The strategy lives in agent/context_strategy.py and replaces the
                    # old conv.trim_to_token_limit() call. The delegation shim on
                    # Conversation remains for backward compat with tests.
                    #
                    # _compute_compaction_threshold returns (soft_ceiling, hard_ceiling)
                    # where soft_ceiling = int(hard_ceiling * threshold) and
                    # threshold defaults to 0.80 (configurable per-provider).
                    soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)
                    model_max = hard_ceiling  # preserve for breakdown dispatch below
                    self._context_strategy.compact(conv, soft_ceiling)
                    # §2.8: Telemetry — read strategy.last_result, append to history.
                    # Audit-Fix-7: Patch hard_ceiling — strategy doesn't know the real value
                    # (computed by _compute_compaction_threshold at the runtime level).
                    # Audit-Fix-8: Guard append+truncate with _compaction_lock.
                    # Audit-Fix-19: Only mark iteration as having compacted when messages or
                    # tokens were actually freed (filter out no-op compact() calls).
                    # Audit-Fix-26 (Bug #1): capture the result into a LOCAL variable.
                    # Reading self._compaction_this_iteration in the breakdown block
                    # below was a TOCTOU race: another session's thread could overwrite
                    # the flag between compact() and the breakdown dispatch.
                    # Audit-Fix-26 (Bug #3): tag the event with session_key so
                    # _last_trim_removed can filter per-session when called from
                    # the breakdown block (events from other sessions on the same
                    # runtime are no longer mixed into this session's breakdown).
                    ev = self._context_strategy.last_result
                    _compaction_happened = False
                    _ev_for_breakdown = None
                    if ev is not None and (ev.messages_removed > 0 or ev.tokens_freed > 0):
                        if ev.hard_ceiling is None:
                            ev.hard_ceiling = hard_ceiling
                        # Tag the event with the originating session_key. Reuse the
                        # event object directly (it's a fresh per-call dataclass).
                        if not ev.session_key:
                            ev.session_key = session_key
                        _compaction_happened = True
                        _ev_for_breakdown = ev
                        with self._compaction_lock:
                            self._compaction_events.append(ev)
                            # Cap history at 100 events (prevents unbounded growth).
                            if len(self._compaction_events) > 100:
                                self._compaction_events = self._compaction_events[-100:]
                    # NOTE: self._compaction_this_iteration is intentionally NO LONGER
                    # written here. Bug #1 was caused by treating a per-runtime flag as
                    # if it were per-session/per-iteration; the breakdown block now
                    # uses the local _compaction_happened instead. The attribute is
                    # retained on the instance for backward-compat reads (e.g. tests)
                    # but no longer carries meaningful state. See tests for the
                    # deprecation notice.

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

                    # Build API messages AFTER compact so the wire payload reflects
                    # the trimmed conversation. Bug fix: was captured before compact().
                    from models.conversation import MessageRole

                    # Pre-call budget guard: if the conversation still exceeds
                    # the model's context window after compaction, raise a clear
                    # error before serializing or sending. This prevents mid-stream
                    # HTTP 400 rejections (which corrupt conversation state because
                    # the assistant message is already added by the time the error
                    # surfaces). Response reserve accounts for output tokens.
                    RESPONSE_RESERVE_TOKENS = self._RESPONSE_RESERVE_TOKENS
                    post_trim_estimate = conv.get_token_estimate()
                    effective_budget = model_max - RESPONSE_RESERVE_TOKENS
                    if post_trim_estimate >= effective_budget:
                        usage_pct = int((post_trim_estimate / model_max) * 100) if model_max > 0 else 0
                        raise RuntimeError(
                            f"Conversation is at {post_trim_estimate:,}/{model_max:,} tokens "
                            f"({usage_pct}%) after compaction — exceeds model context window. "
                            f"Use /clear to reset or /compact to summarize the conversation."
                        )
                    messages = conv.to_api_messages()

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
                    loop_fmt = _RESPONSE_FORMAT.get(loop_provider, "openai")
                    text_content = _extract_text_content(response, response_format=loop_fmt)
                    tool_calls_raw = _extract_tool_calls(response, response_format=loop_fmt)

                    # Record usage
                    prompt_tok, comp_tok = _extract_usage(response, response_format=loop_fmt)
                    cost = cost_for_model(conv.model, prompt_tok, comp_tok)
                    conv.record_usage(prompt_tok + comp_tok, cost)
                    self._dispatch(self._on_token_usage, session_key, prompt_tok + comp_tok, cost)

                    # §4.15 — Token budget breakdown for observability.
                    # Reuses the model_max that the trim call above already computed.
                    # Audit-Fix-26 (Bugs #1, #2, #3): use LOCAL variables
                    # (_compaction_happened, _ev_for_breakdown) instead of re-reading
                    # the shared _compaction_this_iteration flag or
                    # self._context_strategy.last_result. The shared state could be
                    # mutated by another session's thread between the gate and the
                    # breakdown dispatch, causing this session to report the wrong
                    # compaction state.
                    if self._on_token_breakdown is not None:
                        breakdown = conv.get_token_breakdown(model_max)
                        breakdown["trimmed_this_turn"] = _compaction_happened
                        breakdown["messages_remaining"] = len(conv.messages)
                        # Tag the most recent breakdown so _last_trim_removed knows
                        # which session_key to filter on. _last_trim_removed reads
                        # this attribute, so this must happen BEFORE the dispatch.
                        # Bug #3 fix: filter _compaction_events by session_key to
                        # avoid cross-session contamination.
                        self._last_breakdown_session = session_key
                        breakdown["messages_removed_this_turn"] = (
                            self._last_trim_removed if _compaction_happened else 0
                        )
                        # §0.4 + §2.8: Compaction telemetry from the strategy.
                        # Audit-Fix-20: Only include compaction_event when actual compaction
                        # occurred. Bug #2 fix: use the LOCAL _ev_for_breakdown instead
                        # of re-reading self._context_strategy.last_result, which could
                        # have been overwritten by another session's compact() call.
                        if _compaction_happened and _ev_for_breakdown is not None:
                            breakdown["compaction_event"] = {
                                "trigger": _ev_for_breakdown.trigger,
                                "layer": _ev_for_breakdown.layer,
                                "tokens_before": _ev_for_breakdown.tokens_before,
                                "tokens_after": _ev_for_breakdown.tokens_after,
                                "tokens_freed": _ev_for_breakdown.tokens_freed,
                                "soft_ceiling": _ev_for_breakdown.soft_ceiling,
                                "hard_ceiling": _ev_for_breakdown.hard_ceiling,
                                "summary_tokens_injected": _ev_for_breakdown.summary_tokens_injected,
                            }
                        self._dispatch(self._on_token_breakdown, session_key, breakdown)
                        # Bug #1 fix: no longer reset self._compaction_this_iteration
                        # here — the breakdown used the local _compaction_happened,
                        # so there's no shared flag to reset. The attribute is kept
                        # for backward-compat (read by tests) but is no longer the
                        # source of truth for breakdown state.

                    logger.debug("[tool-loop] sk=%s llm response: text_len=%d tool_calls=%d tokens=%d cost=%.4f",
                                 session_key, len(text_content or ""), len(tool_calls_raw),
                                 prompt_tok + comp_tok, cost)

                    if not tool_calls_raw:
                        # Text-only response — but check for empty/missing content
                        # which may indicate a provider error that wasn't raised (e.g. body-level
                        # error that slipped through, or malformed response with no choices)
                        # Whitespace-only counts as empty: some strict providers (Cohere,
                        # Anthropic strict mode) treat blank assistant content as a 400
                        # the same as a missing/empty payload. _is_empty_content covers
                        # falsy values (None, ""), empty lists, and strings that strip to
                        # nothing (e.g. " \n\u200b"). Same predicate used at the
                        # tool-call path below for consistency.
                        if _is_empty_content(text_content):
                            logger.warning("[tool-loop] sk=%s LLM returned no content (with tool_calls=%d, choices=%d) — treating as error",
                                           session_key, len(tool_calls_raw), len(response.get("choices") or []))
                            # Defense in depth: instead of persisting a corrupt empty
                            # assistant message that downstream providers (Cohere,
                            # strict OpenAI tool-loop, Anthropic strict mode) reject
                            # with HTTP 400 "must have non-empty content or tool calls",
                            # record a descriptive placeholder. The on_error dispatch
                            # below still fires so the user sees the error; this just
                            # prevents the corrupt entry from being saved and re-sent
                            # on subsequent calls.
                            # Trigger covers: missing choices, empty choices,
                            # choices-present-but-empty-content (e.g. nemotron-3-ultra
                            # returning finish_reason="stop" with empty content after
                            # a tool execution completes), and whitespace-only content
                            # (single newline, zero-width space, etc.) that strict
                            # providers also reject.
                            conv.add_assistant_message(
                                "[LLM returned no content — provider error or malformed response]",
                                [],
                            )
                            # BUG #2 fix: _on_error is a user-registered callback and may
                            # throw (e.g. UI broken, dispatcher bug). If it raises, we still
                            # need to: (a) persist the placeholder via _auto_save, and
                            # (b) return so the caller's loop exits instead of iterating
                            # with another empty response (which would add duplicate
                            # placeholders until max_iterations_enforced trips).
                            try:
                                self._dispatch(self._on_error, session_key,
                                               "Agent returned no content. This may indicate a configuration error "
                                               "or an issue with the LLM provider.")
                            except Exception as _e:
                                logger.error("[tool-loop] sk=%s _on_error handler raised %s: %s — continuing with save+return",
                                             session_key, type(_e).__name__, _e)
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
                                fb_fmt = _RESPONSE_FORMAT.get(fb_provider, "openai")
                                fb_text = _extract_text_content(fb_response, response_format=fb_fmt)
                                fb_tool_calls = _extract_tool_calls(fb_response, response_format=fb_fmt)
                                # Use fallback response as the text content
                                text_content = fb_text
                                tool_calls_raw = fb_tool_calls
                                # Record fallback usage
                                fb_prompt, fb_comp = _extract_usage(fb_response, response_format=fb_fmt)
                                fb_cost = cost_for_model(fallback_model, fb_prompt, fb_comp)
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
                    from models.conversation import ToolCall
                    from agent.tools import execute_tool

                    # Create assistant message once, attach all tool calls — fixes data corruption
                    # (was: conv.messages[-1].tool_calls.append(tc) — appended to USER message)
                    tool_call_objects = [
                        ToolCall(call_id=call_id, tool_name=tool_name, arguments=args)
                        for call_id, tool_name, args in tool_calls_raw
                    ]

                    # BUG #3 sweep: tool-call response with empty/whitespace text_content.
                    # OpenAI spec allows content=null with tool_calls, but strict providers
                    # (Cohere, Anthropic strict mode) require non-empty content even when
                    # tool_calls are present. If a model returns tool_calls with empty
                    # content (e.g. provider bug, malformed streaming response), substitute
                    # a meaningful placeholder so the next LLM call doesn't 400.
                    # The read-side filter at models/conversation.py:262 already handles
                    # the no-content-no-tool_calls case; this fills the gap for the
                    # tool_calls-present-but-content-empty case.
                    if _is_empty_content(text_content):
                        logger.warning(
                            "[tool-loop] sk=%s tool-call response has empty content "
                            "(tool_calls=%d) — substituting placeholder for strict-provider safety",
                            session_key, len(tool_call_objects),
                        )
                        text_content = "[calling tools]"

                    conv.add_assistant_message(text_content, tool_call_objects)

                    # Import once per loop iteration (avoid repeated import overhead)
                    import agent.tools as agent_tools_module

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
                                self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied", False)
                                self._audit_log.record(tool_name, args, approved=False,
                                                        user=getattr(self._config, "user_id", ""),
                                                        result="denied")  # A-4
                                continue

                        # HIGH-1: Sensitive-path write/edit also requires PM approval.
                        # Fires before tool_call_start so the PM sees the card.
                        if tool_name in ("write_file", "edit_file"):
                            path_arg = args.get("path", "")
                            if agent_tools_module.is_sensitive_path(path_arg):
                                approved = self._dispatch_approval(session_key, tool_name, args)
                                logger.debug("[tool-loop] sk=%s %s sensitive approval: %s",
                                             session_key, tool_name, approved)
                                if approved is False or approved is None:
                                    tc.mark_failed(
                                        f"{tool_name} blocked: {path_arg} is a sensitive path\n"
                                        "PM approval denied or timed out."
                                    )
                                    conv.add_tool_result(call_id, tc.result or "denied")
                                    self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied", False)
                                    self._audit_log.record(tool_name, args, approved=False,
                                                            user=getattr(self._config, "user_id", ""),
                                                            result="denied")  # A-4
                                    continue

                        # Tool call start — fires AFTER approval (for exec_command and sensitive write/edit)
                        # so the "running" card is truthful: the tool is actually about to run.
                        self._dispatch(self._on_tool_call_start, session_key, tool_name, args)
                        tc.mark_executing()

                        # Execute tool
                        logger.debug("[tool-loop] sk=%s executing tool: %s args_keys=%s",
                                     session_key, tool_name, list(args.keys()))
                        # Bypass exec_command's internal approval check — the runtime already
                        # confirmed PM approval via _dispatch_approval above (returned True).
                        # HIGH-1: write_file/edit_file with sensitive paths — runtime already
                        # dispatched to PM above, so bypass the tool's internal check.
                        # MED-1: Use per-call approval_callback (bypass = lambda True, normal = None).
                        bypass_approval = (tool_name == "exec_command" or
                                           (tool_name in ("write_file", "edit_file") and
                                            agent_tools_module.is_sensitive_path(args.get("path", ""))))
                        per_call_cb = (lambda *a: True) if bypass_approval else None
                        # LOW-2: resolve workspace before use; raises ValueError if project_path is empty
                        workspace = _resolve_session_workspace(conv.project_path, session_key)
                        # project_path is the sandbox base for all tools AND exec_command cwd.
                        # scratch_dir (workspace) is resolved for future use but no longer
                        # overrides exec_command CWD — see exec-cwd-fix spec.
                        # Allowed-tools enforcement gate (§3.21n).
                        # Forward conv.allowed_tools so execute_tool can deny tools the agent
                        # was configured without. conv.allowed_tools is the single source of
                        # truth — set in create_conversation() from agent_def["tools"] and
                        # persisted on the conversation object.
                        #
                        # Execute through the tool middleware chain.
                        # The chain wraps execute_tool with EnforcementMiddleware
                        # (post-write verification) and StuckDetectionMiddleware
                        # (loop detection). Approval was already resolved inline
                        # above (before on_tool_call_start) per spec §A.2.4.
                        ctx = ToolContext(
                            session_key=session_key,
                            project_path=conv.project_path,
                            iteration=iteration,
                            bypass_approval=bypass_approval,
                            audit_log=self._audit_log,
                            user_id=getattr(self._config, "user_id", ""),
                            enforcement_config=self._config.enforcement,
                            si_enforcement=conv.si_enforcement,
                        )
                        result = self._tool_chain.run(
                            tool_name=tool_name,
                            args=args,
                            ctx=ctx,
                            executor=lambda: execute_tool(
                                tool_name, args, conv.project_path, session_key,
                                approval_callback=per_call_cb,
                                allowed_tools=conv.allowed_tools,
                            ),
                        )
                        logger.debug("[tool-loop] sk=%s tool %s result: success=%s output_len=%d",
                                     session_key, tool_name, result.success, len(result.output or ""))

                        # Record tool result — ToolResult dataclass stays clean
                        tc.mark_completed(result.output if result.success else result.error or "")
                        tool_result_text = tc.result or ""

                        conv.add_tool_result(call_id, tool_result_text)
                        self._dispatch(self._on_tool_call_result, session_key, tool_name, tool_result_text, result.success)

                        # A-4: Record in audit log
                        _audit_user = getattr(self._config, "user_id", "")
                        self._audit_log.record(
                            tool_name=tool_name,
                            args=args,
                            approved=True if bypass_approval else None,
                            user=_audit_user,
                            result=tool_result_text,
                            exit_code=result.exit_code,
                        )

                    # Check cost/step limits after tool execution
                    if self._check_and_stop_on_limit(session_key, conv):
                        return

                # Max iterations reached
                conv.add_assistant_message("[max tool iterations reached]", [])
                self._dispatch(self._on_error, session_key, "Max tool iterations reached")
                self._auto_save(session_key, conv)

            except Exception as e:
                logger.exception("Error in tool loop for %s", session_key)
                # QTR-FIX: persist whatever partial progress was made before the
                # exception so the next /resume / restart can recover it instead of
                # silently dropping the in-memory conversation. conv is in scope
                # from the surrounding `with self._lock` block above.
                try:
                    self._auto_save(session_key, conv)
                except Exception:
                    logger.exception("Failed to auto_save after tool-loop error for %s", session_key)
                self._dispatch(self._on_error, session_key, e)
        finally:
            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even
            # on exception or early return, so a crashed loop doesn't block
            # /clear for this session permanently.
            with self._lock:
                self._active_loops.discard(session_key)

    def is_loop_active(self, session_key: str) -> bool:
        """Return True if a _run_loop thread is currently active for this session.

        FIX-CLEAR-ASK-RACE: used by AgentRuntimeHandler.clear_conversation() to
        refuse wiping a conversation that an in-flight loop is still reading.
        Thread-safe via _lock. A session marked active stays active until the
        loop's finally block discards it — including through exceptions and
        early returns, so a crashed loop cannot permanently block /clear.
        """
        with self._lock:
            return session_key in self._active_loops


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
            # QTR-FIX: inject the stuck prefix AFTER the system prompt, not
            # before it. `to_api_messages()` puts the system message at index 0
            # when `conv.system_prompt` is set; prepending the stuck message at
            # index 0 caused role:user to appear before role:system, which some
            # providers reject and which always loses the system's priority.
            if messages and messages[0].get("role") == "system":
                messages = [messages[0], stuck_prefix] + messages[1:]
            else:
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
            try:
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
            except (IndexError, KeyError, TypeError, ValueError) as e:
                e._crabcakes_context = {
                    "provider": caller_key,
                    "model": model,
                    "exception_type": type(e).__name__,
                }
                raise

        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"No caller for provider {provider_cfg.name if provider_cfg else provider_name} "
                f"(caller_key={caller_key!r}). "
                f"Set the 'caller' field in Settings → Providers."
            )

        try:
            provider = _get_provider(caller_key)
            return provider.call(
                base_url=provider_cfg.base_url,
                api_key=effective_api_key,
                model=model,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )
        except (IndexError, KeyError, TypeError, ValueError) as e:
            e._crabcakes_context = {
                "provider": caller_key,
                "model": model,
                "exception_type": type(e).__name__,
            }
            raise

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
        # PHASE-11: caller_key is resolved by _call_llm before calling this method
        # (explicit caller > default_model prefix > model prefix). Symmetric with
        # the non-streaming path.
        provider = _get_provider(caller_key)
        streamer = provider.stream
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

        for ev in _stream_with_ssl_retry(
            streamer,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=tools,
            timeout=timeout,
            x_title=x_title,
        ):
            if ev.type == "text_delta":
                text = ev.data.get("content") or ""
                full_content += text
                if self._on_text_delta:
                    self._dispatch(self._on_text_delta, session_key, text)

            elif ev.type == "tool_call_delta":
                # PHASE-11.5: default to 0 if streamer omits 'index' (e.g. Anthropic
                # single-tool responses). Without this, the runtime crashes mid-stream.
                # STREAM-ID-PRES: capture provider-assigned id from first delta;
                # subsequent deltas (which carry argument fragments) do not overwrite.
                idx = ev.data.get("index", 0)
                if idx not in tool_calls_partial:
                    tool_calls_partial[idx] = {"name": "", "arguments": "", "id": ""}
                tc = tool_calls_partial[idx]
                if ev.data.get("name"):
                    tc["name"] = ev.data["name"]
                if ev.data.get("arguments"):
                    tc["arguments"] += ev.data["arguments"]
                incoming_id = ev.data.get("id") or ""
                if incoming_id and not tc["id"]:
                    tc["id"] = incoming_id

            elif ev.type == "usage":
                # Provider sent a usage chunk (e.g., OpenAI's "final" frame).
                # Capture the most recent one; the final response uses it.
                # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.2 (BUG #3 fix).
                usage_data = ev.data.get("usage", {})
                if isinstance(usage_data, dict) and usage_data:
                    captured_usage = usage_data

            elif ev.type == "done":
                # Build final tool_calls list from accumulated partials.
                # STREAM-ID-PRES: use the provider-assigned id captured during
                # SSE assembly; fall back to synthetic only if absent.
                tool_calls = []
                for idx in sorted(tool_calls_partial.keys()):
                    tc = tool_calls_partial[idx]
                    if tc["name"]:
                        tool_calls.append({
                            "id": tc["id"] or f"call_{idx}",
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
        # STREAM-ID-PRES: same id-preservation logic as the done-event path.
        tool_calls = []
        for idx in sorted(tool_calls_partial.keys()):
            tc = tool_calls_partial[idx]
            if tc["name"]:
                tool_calls.append({
                    "id": tc["id"] or f"call_{idx}",
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

    def _rebuild_conversation_context(
        self,
        session_key: str,
        project_path: str | None,
        agent_role: str = "",
    ) -> None:
        """Re-apply the active project to a loaded conversation and rebuild its system prompt.

        Fix for the stale-project-context bug: conversations persisted to disk
        carry a `project_path` and `system_prompt` snapshot from the session
        that last wrote them. If the user switched projects between sessions,
        those persisted values are stale — the agent would see the wrong
        project's docs and tools would be sandboxed to the wrong directory.

        This method is idempotent and cheap (one build_system_prompt call +
        one attribute write). It is called from:
          - load_conversation: after restoring from disk, before any send
          - send_message: lazy reconciliation on first send after a project switch
          - AgentRuntimeHandler.set_active_project: eager reconciliation for
            all agents when the user opens a project

        Args:
            session_key: The conversation to reconcile.
            project_path: The currently-active project path. If None, the
                conversation's project_path is cleared and the system prompt
                is rebuilt without project context.
            agent_role: Role identifier (e.g. "coder", "debugger", "helper").
                Used to select the right per-role template in build_system_prompt.

        Concurrency contract (BUG #2 audit, 2026-07-02): `self._lock` is a
        `threading.Lock`, not an RLock — it is NOT re-entrant. The locked
        block below is intentionally narrow (a single dict.get on
        `self._conversations`). Do NOT widen it: do not call other
        AgentRuntime methods from inside the block, do not write to
        `self._conversations[session_key]` here, and do not invoke any
        callback that might re-enter the runtime. If you need to mutate
        `_conversations` under the lock, do the lookup here and the
        mutation outside (the existing pattern in `get_conversation`,
        `load_conversation`, `send_message`, etc.). Changing `self._lock`
        to `threading.RLock` would require auditing every lock site for
        correctness — out of scope for this fix.
        """
        with self._lock:
            conv = self._conversations.get(session_key)
        if conv is None:
            return  # Nothing to rebuild; load_conversation not called yet.

        if conv.project_path == project_path and conv.system_prompt:
            return  # Already in sync; skip the rebuild (cheap short-circuit).

        # Resolve model context window for the system prompt budget.
        # Mirrors the logic in create_conversation() — keep these in sync
        # so create and rebuild produce equivalent prompts.
        default_provider_name = self._config.default_provider
        default_provider_cfg = self._config.providers.get(default_provider_name) if default_provider_name else None
        if default_provider_cfg and getattr(default_provider_cfg, "max_tokens", None):
            model_max_for_budget = int(default_provider_cfg.max_tokens)
        else:
            model_max_for_budget = 128_000  # fallback per CB-1
        context_mode = getattr(default_provider_cfg, "context_mode", "auto") or "auto"

        try:
            from agent.context import build_system_prompt
            new_prompt = build_system_prompt(
                conv.agent_name,
                project_path,
                conv.allowed_tools or [],
                agent_role=agent_role or conv.agent_role or "",
                model_max_tokens=model_max_for_budget,
                context_mode=context_mode,
            )
        except Exception:
            # build_system_prompt is non-critical — fall back to whatever
            # was persisted, with a logged warning. The agent still works
            # (just with a potentially stale prompt) instead of crashing.
            logger.exception(
                "Failed to rebuild system prompt for %s; keeping persisted prompt",
                session_key,
            )
            new_prompt = conv.system_prompt

        conv.project_path = project_path
        conv.system_prompt = new_prompt
        logger.info(
            "Reconciled conversation context for %s: project_path=%r",
            session_key, project_path,
        )

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
            # W13: lightweight read — only extract agent_name, skip full
            # Conversation/Message deserialization + api_key re-resolution.
            agent_name = "unknown"
            try:
                path = os.path.join(d, fname)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                agent_name = data.get("agent_name", "unknown")
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass
            result.append((sk, agent_name))
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

    def force_compact(self, conv: "Conversation", token_budget: int) -> None:
        """Public wrapper around self._context_strategy.compact().

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.
        Allows external callers (like compact_conversation in
        agent_runtime_handler) to invoke compaction without poking at
        the private _context_strategy attribute.

        token_budget <= 0 is silently ignored (matches the strategy's
        own defensive behavior — see context_strategy.py:130).
        """
        with self._compaction_lock:
            self._context_strategy.compact(conv, token_budget)

    def force_llm_compact(
        self,
        conv: "Conversation",
        token_budget: int,
        focus_text: str = "",
        agent_def: Any = None,
    ) -> dict:
        """Force an LLM-summarization compact on ``conv``.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.3.2.

        FIX-BUG-3: swap self._context_strategy to the LLM strategy for
        the duration of the call, run compact, then swap back. This
        ensures self._context_strategy.last_result reflects the LLM
        compaction, which the runtime's breakdown dispatcher (line 2116)
        reads into self._compaction_events.
        """
        from agent.context_strategy import LLMSummarizeStrategy

        with self._compaction_lock:
            original_strategy = self._context_strategy

            # Resolve model_id with precedence: agent_def.llm_name > conv.model > global default.
            resolved_model = None
            if agent_def is not None:
                llm_name = getattr(agent_def, "llm_name", None)
                if llm_name:
                    prov_cfg = self._config.providers.get(llm_name)
                    if prov_cfg and prov_cfg.default_model:
                        if "/" in prov_cfg.default_model:
                            resolved_model = prov_cfg.default_model
                        else:
                            resolved_model = f"{llm_name}/{prov_cfg.default_model}"
            if not resolved_model:
                resolved_model = conv.model

            strat = LLMSummarizeStrategy(
                llm_provider=lambda sys_p, user_p, model_id=None:
                    self._call_for_summary(
                        system_prompt=sys_p,
                        user_prompt=user_p,
                        model_id=model_id or resolved_model,
                        conv=conv,
                    ),
            )
            self._context_strategy = strat

            original_sp = conv.system_prompt
            if focus_text:
                conv.system_prompt = (
                    f"{original_sp}\n\n## Focus for compaction\n{focus_text}"
                )
            try:
                strat.compact(conv, token_budget)
            finally:
                self._context_strategy = original_strategy
                conv.system_prompt = original_sp

        ev = strat.last_result
        tokens_after = conv.get_token_estimate()
        if ev is None:
            return {
                "messages_removed": 0,
                "tokens_freed": 0,
                "summary_chars": 0,
                "layer": 0,
            }
        return {
            "messages_removed": ev.messages_removed,
            "tokens_freed": ev.tokens_freed,
            "summary_chars": ev.summary_tokens_injected,
            "layer": ev.layer,
        }

    def _call_for_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
        conv: "Conversation | None" = None,
    ) -> str:
        """Single non-streaming chat completion for LLMSummarizeStrategy.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.3.2.
        FIX-BUG-2: reuses agent/runtime.py's real provider caller
        dispatch (_PROVIDER_CALLERS, _resolve_caller_key) — does NOT
        create a new sync_chat_completion helper that does not exist.

        Returns the assistant text. Raises any provider error.
        """
        if not model_id and self._config.default_provider:
            model_id = f"{self._config.default_provider}/{self._config.default_model}"
        if not model_id:
            raise RuntimeError(
                "_call_for_summary: no model_id and no default configured"
            )
        if "/" not in model_id:
            raise RuntimeError(
                f"_call_for_summary: model_id must be 'provider/model', "
                f"got {model_id!r}"
            )
        provider_name, model = model_id.split("/", 1)
        provider_cfg = self._config.providers.get(provider_name)
        if provider_cfg is None:
            raise RuntimeError(
                f"_call_for_summary: provider {provider_name!r} not configured"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"_call_for_summary: no caller for {caller_key!r}"
            )

        api_key = ""
        if conv is not None and getattr(conv, "api_key", None):
            api_key = conv.api_key
        if not api_key:
            api_key = getattr(provider_cfg, "api_key", "") or ""
        if not api_key:
            logger.warning(
                "_call_for_summary: empty api_key for %s; check Settings",
                provider_name,
            )

        provider = _get_provider(caller_key)
        response_dict = provider.call(
            base_url=provider_cfg.base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=None,
            timeout=float(self._config.tool_timeout_seconds),
            x_title="crabcakes-summary",
        )
        from agent.runtime import _extract_text_content, _RESPONSE_FORMAT
        fmt = _RESPONSE_FORMAT.get(provider_name, "openai")
        text = _extract_text_content(response_dict, response_format=fmt)
        return text
