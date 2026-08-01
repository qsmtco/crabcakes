# SPEC: Runtime Terminal Path Consolidation

**Date:** 2026-07-31
**Author:** Coder (special:coder) — drafted in response to Debugger architecture audit 2026-07-31
**Status:** Draft — for implementation
**Implements:** Debugger's 5-point audit on `agent/runtime.py` (B-/良 range, "good direction, fragile contracts")
**Depends on:**
- `docs/specs/SPEC-DEFERRED-RACE-FIXES-PHASE-1-INSTRUCTIONS.md` (✅ complete — provides generation-counter infrastructure; this spec is Phase 2+)
- Phase A1 (`agent/tool_middleware.py`), Phase A2 (chain wired into `_run_loop`)
- Phase B4/B6 (`agent/llm/{protocol,registry,providers}`)
- Phase 5 (`agent/audit.py`), Phase 6 (`agent/persistence.py`)
**Target branch:** main

> **Architecture compliance statement.** This spec extends `docs/ARCHITECTURE.md` §3.X (Agent Runtime) by adding a per-turn state machine and typed callback contracts. No layer-boundary changes; no new imports from `ui/`, `gateway/`, or `models/`. The new module(s) live in `agent/` and may import from `agent.llm`, `agent.tools`, `agent.audit`, `agent.persistence`, `agent.tool_middleware`, `agent.context_strategy`. The runtime's public API (constructor signature, `create_conversation`, `send_message`, `cancel`, `is_loop_active`, `approve_exec`, `force_compact`, `get_conversation`, `save_conversation`, `load_conversation`, `list_conversations`, `set_approval_callback`) is preserved.

---

## 1. Overview

### 1.1 Problem statement

`agent/runtime.py` is 2205 lines and has accumulated **5+ distinct terminal completion paths** in `_run_loop`, each independently responsible for:

- Dispatching `on_response_complete` or `on_error`
- Calling `_auto_save`
- Adding assistant message placeholders (empty-content error, max-iterations)
- Persisting partial state on exception
- Setting cleanup-tool-history

The Debugger's audit (2026-07-31) flagged this as the **highest-leverage concern** — "A single per-turn result state machine would be safer: `RUNNING → STREAMING → COMPLETED` / `RUNNING → FAILED` / `RUNNING → CANCELLED` with one terminal transition function."

Evidence the duplication causes real bugs:

- **Phase 1 deferred-race-fixes (this session, 2026-07-31):** Had to add a turn generation counter + idempotency set to `_do_response_complete` and `_do_error` in the handler because the runtime's overlapping terminal paths update the same downstream state in different orders. The fix touches the **handler** to compensate for the **runtime's** lack of a single transition function.
- **Pre-existing test failures** (context.md §2026-07-19): `TestApproval::test_exec_without_callback_denied` + `TestToolLoop::test_tool_call_appends_result` — 3-arg vs 4-arg `_on_tool_call_result` dispatch drift across 5+ terminal paths.
- **`_turn_token` contract regression (current baseline)**: `TypeError: lambda() got an unexpected keyword argument '_turn_token'` — `agent/runtime.py` adds `_turn_token=_turn_token` to `_call_llm_streaming` (and to the LLM callbacks, see lines 1646, 1706 etc.), but several tests' injected lambdas only have the old 9-arg signature without `_turn_token`. The 12-15 failed tests in `TestToolLoop` are direct architectural evidence that adding kwargs to internal calls breaks downstream callers. This is the exact contract drift BUG #7 is fixing: the protocol now uses `_turn_token` (matching production) and the tests use `create_autospec` to enforce it.

### 1.2 Solution summary

Introduce a per-turn state machine that owns the terminal transition. All `_run_loop` exit paths funnel through a single `_terminate_turn(self, result)` method. The state machine:

1. **Encodes the turn state explicitly** (RUNNING → STREAMING → COMPLETED/FAILED/CANCELLED). One attribute, one transition function, no flag inference.
2. **Replaces ad-hoc `_dispatch(self._on_*, ...)` + `_auto_save` + `return` triplets** with a single call.
3. **Defines a `TurnResult` dataclass** (status, text, error, terminal_metadata) that captures everything a terminal callback needs in one struct.
4. **Defines typed callback protocols** in `agent/callbacks.py` for the 9 runtime→handler callbacks, ending the 3+ known contract-drift failures structurally.
5. **Removes provider alias debt** (`_call_openai`, `_call_minimax`, `_call_anthropic`, `_stream_*_events`, `_PROVIDER_STREAMERS` dead dispatch — `_PROVIDER_CALLERS` retained for now since it's used by `_call_llm`'s non-streaming path).
6. **Replaces test-mock `MagicMock()` patterns** with `create_autospec` for the 3 confirmed contract-drift test sites.

### 1.3 Scope

> **AUDIT FIX (BUG #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #12, #13, #14).**
> The scope table has been amended to include the audit-driven additions:
> - BUG #2: missing-conversation and prompt-build-failure routing (was:
>   "out of scope" — now: in scope as terminal paths).
> - BUG #3, #4: `_state_lock` and `(sk, tk)` keying (was: not in the
>   original spec — required by audit).
> - BUG #5: explicit `return` after `_terminate_turn` in D.3 (was: missing).
> - BUG #6, #11: `_check_and_stop_on_limit` refactor (was: "leave as-is"
>   — NameError and outside the state machine).
> - BUG #8: migration of scripts and tests that use the removed aliases
>   (was: not in scope — required by grep evidence).
> - BUG #14: ARCHITECTURE.md updates (was: "none required" — new public
>   module changes the doc surface).

| In scope | Out of scope |
|---|---|
| Turn state machine in `agent/runtime.py` (5-state enum, `(sk, tk)` keying, `_state_lock`) | New `agent/turn.py` module (deferred — see §2.5) |
| `agent/callbacks.py` typed protocols (NEW, public) | New `agent/callbacks.py` handlers (just the protocols; the existing functions are still the implementations) |
| Single `_terminate_turn(result)` method (returns `TurnResult \| None` for testability) | Removing `_PROVIDER_CALLERS` (still used by `_call_llm` non-streaming path; values migrated but dict retained) |
| Routing missing-conversation and prompt-build-failure paths through `_terminate_turn` (BUG #2) | Refactoring `_call_llm` to use the new `TurnContext` (deferred) |
| Removal of `_call_openai`, `_call_minimax`, `_call_anthropic` aliases (with consumer migration in `tests/test_agent_runtime.py` and audit scripts) | Refactoring KB synthesis (`_prepare_kb_synthesis`, `_inject_kb_context`) |
| Removal of `_stream_openai_events`, `_stream_minimax_events`, `_stream_anthropic_events` (with consumer migration) | Touching `agent/persistence.py`, `agent/audit.py`, `agent/tool_middleware.py` |
| Removal of `_PROVIDER_STREAMERS` (with consumer migration) | Conversation layer (`models/conversation.py`) |
| Refactor `_check_and_stop_on_limit` to a pure predicate returning `(reason, msg) \| None` (BUG #6, #11) | Anything in `ui/`, `gateway/`, `models/` |
| `cancel()` uses active turn token for the session, not the runtime's global `_turn_token` (BUG #13) | |
| `send_message` rotates `_turn_tokens[sk]` (BUG #4) | |
| Test mock fix (3 sites — `create_autospec`) | |
| `agent/runtime.py` class docstring honesty pass (BUG #12) | |
| `docs/ARCHITECTURE.md` §3.21 update (new `agent/callbacks.py` public surface, `TurnStatus`/`TurnResult` exports, removed aliases) (BUG #14) | |

### 1.4 Architecture principles that apply

From `docs/ARCHITECTURE.md`:

- **§3.21 Agent Runtime:** "The runtime owns the tool loop, conversation lifecycle, and provider dispatch. It is the only module in `agent/` allowed to import `httpx` and the streaming HTTP path." — preserved. The new state machine is internal to the runtime; it does not add new I/O.
- **§8.6 Layer Rules:** "`agent/` must not import from `ui/`, `gateway/`, or `models/`. `agent/llm/`, `agent/audit/`, `agent/persistence/`, `agent/context_strategy.py`, `agent/tool_middleware.py`, `agent/enforcement.py` are the only allowed imports for new code in `agent/runtime.py`." — preserved. The new `agent/callbacks.py` follows the same rule.
- **§8.4 Test count discipline:** "When a feature changes, the tests change with it in the same commit. New tests for new behavior; removed tests for removed behavior; modified tests for changed behavior." — applied. We add 12-15 new tests for the state machine + callback protocols, remove 0 tests for the deleted aliases (no test asserted on the aliases' existence), and fix 3 tests with `create_autospec`.

---

## 2. Changes by File

### 2.1 `agent/callbacks.py` (NEW, ~140 lines)

**What it does:** Defines typed `Protocol` classes for every callback the runtime accepts in its constructor and dispatches via `_dispatch()`. The handler's `on_*` functions (in `ui/handlers/agent_runtime_handler.py`) already accept these signatures; the protocol formalizes the contract.

**Why a separate module:** The protocol definitions are the public API contract for the runtime's callbacks. Putting them in `agent/runtime.py` would make the runtime import the handler's implementations (forbidden by §8.6). Putting them in `agent/callbacks.py` keeps the dependency direction: `runtime.py` imports from `callbacks.py`; the handler doesn't import from `callbacks.py` (its existing functions satisfy the protocol structurally; `runtime_checkable` is not used because we don't need isinstance() checks at runtime).

```python
# agent/callbacks.py
"""Typed callback protocols for AgentRuntime → UI handler.

The runtime accepts 9 callbacks in its constructor. Each is dispatched via
_dispatch() to the chat render / drawer / feed pipeline. This module
formalizes the contract: the protocol signatures here are the source of
truth; the handler's _on_* methods must match.

Architecturally: agent/callbacks.py is the boundary between the runtime's
orchestration logic and the UI's render pipeline. Both sides reference
the protocols; neither imports from the other. This is the same pattern
as agent/llm/protocol.py (the LLMProvider Protocol that all providers
implement).
"""

from __future__ import annotations
from typing import Any, Callable, Protocol


class OnTextDelta(Protocol):
    """Streaming text chunk callback.

    Fires once per SSE chunk (throttled to ~20 calls/sec in the handler).
    Empty strings are valid (the runtime uses them as turn-start signals —
    see BUG #21 in _run_loop).

    Args:
        session_key: Conversation session key (e.g. "special:coder").
        text: The chunk text (may be empty).
        _turn_token: Identity object set by the runtime at send_message time.
            Used by the handler to reject stale cross-turn events. Always
            provided; receivers should accept it positionally or via **kwargs.

    Note: The keyword is `_turn_token` (leading underscore) to match the
    production callback contract. The runtime's `_dispatch()` helper passes
    callbacks with `_turn_token=...` (see `agent/runtime.py` lines 995, 1078,
    1184, 1356, 1448, 1791). The leading underscore signals "internal use
    only; receivers may ignore it" without making it positional. The
    audit (BUG #7) flagged a previous draft that used `turn_token` (no
    underscore) — that broke `create_autospec` validation against the
    real callback signatures. Protocols MUST use the exact keyword the
    runtime uses in production.
    """
    def __call__(self, session_key: str, text: str, *, _turn_token: object | None = None) -> None: ...


class OnToolCallStart(Protocol):
    """Tool execution start callback. Fires AFTER approval (for exec_command
    and sensitive write/edit), BEFORE the tool actually runs.

    Args:
        session_key: Conversation session key.
        name: Tool name (e.g. "read_file", "exec_command").
        args: Tool arguments dict.
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, name: str, args: dict[str, Any],
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnToolCallResult(Protocol):
    """Tool execution result callback. Fires after mark_completed or mark_failed.

    Args:
        session_key: Conversation session key.
        name: Tool name.
        result: Either a ToolResult dataclass or a string (legacy callers).
        success: True if the tool succeeded; False if it failed or was denied.
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, name: str, result: Any, success: bool = True,
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnToolCallApprovalNeeded(Protocol):
    """Approval-needed callback. Fires when exec_command or sensitive write/edit
    requires PM approval BEFORE the tool can run.

    Args:
        session_key: Conversation session key.
        tool_name: Tool name (always "exec_command" or a write tool).
        args: Tool arguments dict (for exec, contains "command").
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, tool_name: str, args: dict[str, Any],
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnResponseComplete(Protocol):
    """Final response callback. Fires when the LLM returns text with no tool calls,
    or when the tool loop completes without producing more tool calls.

    Args:
        session_key: Conversation session key.
        text: Final assistant message text (cumulative; may be empty for
            tool-only turns or empty-content errors).
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, text: str,
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnTokenUsage(Protocol):
    """Token usage and cost callback. Fires after each LLM call (and after
    fallback provider call).

    Args:
        session_key: Conversation session key.
        total_tokens: Total tokens (prompt + completion) for this call.
        cost: USD cost for this call.
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, total_tokens: int, cost: float,
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnTokenBreakdown(Protocol):
    """Per-iteration token budget breakdown callback. Fires before each LLM
    call (after compaction). Used by the context meter.

    Args:
        session_key: Conversation session key.
        breakdown: Dict with keys: system_prompt_tokens, conversation_tokens,
            total_used_tokens, model_max_tokens, remaining_tokens,
            usage_percent, trimmed_this_turn, messages_remaining,
            messages_removed_this_turn, compaction_event (optional).
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, breakdown: dict,
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnError(Protocol):
    """Error callback. Fires for any error condition: missing conversation,
    cancellation, max-iterations, provider errors, exceptions in the loop.

    Args:
        session_key: Conversation session key.
        message: Either a string (user-friendly) or a BaseException (raw).
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, message: str | BaseException,
        *, _turn_token: object | None = None,
    ) -> None: ...


class OnEnforcementStatus(Protocol):
    """Post-write enforcement status callback. Fires once per enforcement
    check (syntax / tests / lint) with the check result.

    Args:
        session_key: Conversation session key.
        tool_name: Tool that triggered the check (e.g. "write_file").
        status: Dict with keys: tier, file, passed, detail.
        _turn_token: See OnTextDelta.
    """
    def __call__(
        self, session_key: str, tool_name: str, status: dict,
        *, _turn_token: object | None = None,
    ) -> None: ...


# Convenience type alias for the full callback bundle.
AgentRuntimeCallbacks = dict[str, Callable | None]
```

**Imports required in `agent/runtime.py`:**
```python
# After existing agent/ imports in runtime.py:
from agent.callbacks import (
    OnTextDelta, OnToolCallStart, OnToolCallResult, OnToolCallApprovalNeeded,
    OnResponseComplete, OnTokenUsage, OnTokenBreakdown, OnError, OnEnforcementStatus,
)
```

**Imports required in `tests/test_agent_runtime.py`:**
```python
# In test files that type-annotate the callback fixtures:
from agent.callbacks import AgentRuntimeCallbacks  # only the dict alias is needed
```

**Type hint changes in `agent/runtime.py.__init__`:**
```python
# Before (line 320-336):
def __init__(
    self,
    config: Any,
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

# After:
def __init__(
    self,
    config: Any,
    *,
    GLib=None,
    on_text_delta: OnTextDelta | None = None,
    on_tool_call_start: OnToolCallStart | None = None,
    on_tool_call_result: OnToolCallResult | None = None,
    on_tool_call_approval_needed: OnToolCallApprovalNeeded | None = None,
    on_response_complete: OnResponseComplete | None = None,
    on_token_usage: OnTokenUsage | None = None,
    on_token_breakdown: OnTokenBreakdown | None = None,
    on_error: OnError | None = None,
    on_enforcement_status: OnEnforcementStatus | None = None,
):
```

**Verified against source:** `agent/runtime.py:315-349` has the current `__init__` signature. All 9 callback names match.

---

### 2.2 `agent/runtime.py` — Add turn state machine (8 edits, ~120 lines added, ~40 lines removed)

**Edit A: Add `TurnStatus` enum and `TurnResult` dataclass** at the top of the file (after `StreamingCallKwargs` TypedDict, around line 75):

```python
# ── Turn state machine (SPEC-RUNTIME-TERMINAL-PATH-CONSOLIDATION §2.2) ──────
from enum import Enum

class TurnStatus(Enum):
    """Per-turn state. Transitions are owned by _terminate_turn.

    RUNNING: Turn started (add_user_message called), no LLM call yet.
    STREAMING: At least one LLM call returned; text deltas or tool calls
        may be in flight.
    COMPLETED: Terminal success — assistant text dispatched to handler,
        no more LLM calls will be made this turn.
    FAILED: Terminal failure — error dispatched to handler, partial state
        persisted. The conversation is still consistent.
    CANCELLED: Terminal user-initiated cancellation — error dispatched,
        tool history cleaned, conversation is still consistent.

    Invariant: A turn's status changes from RUNNING to exactly one of
    {STREAMING, COMPLETED, FAILED, CANCELLED} (STREAMING is non-terminal;
    the other three are terminal). Once terminal, no further status
    transitions occur for that turn.
    """
    RUNNING = "running"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TurnResult:
    """Captures everything a terminal callback needs in one struct.

    Constructed by _terminate_turn from the runtime's per-iteration state
    and dispatched to the appropriate handler callback (on_response_complete
    for COMPLETED, on_error for FAILED/CANCELLED). Avoids the previous
    pattern of "what does the handler need? let me re-read _run_loop to
    find out" — the struct's fields are the source of truth.

    Fields:
        status: Terminal status (COMPLETED/FAILED/CANCELLED). RUNNING and
            STREAMING are not valid here; _terminate_turn rejects them.
        session_key: The session whose turn ended.
        turn_token: Identity object set at send_message time.
        text: Final assistant text (for COMPLETED). Empty for FAILED/CANCELLED.
        error: The error that caused termination. None for COMPLETED. May be
            a string (user-friendly) or a BaseException (raw, for the
            handler to translate via friendly_error_message).
        metadata: Free-form dict for terminal-specific data:
            - COMPLETED: {"fallback_used": bool, "stream_error": dict | None}
            - FAILED: {"reason": str, "iterations": int, "partial_text": str}
            - CANCELLED: {"reason": "user" | "shutdown", "iterations": int}
    """
    status: TurnStatus
    session_key: str
    turn_token: object
    text: str = ""
    error: str | BaseException | None = None
    metadata: dict = field(default_factory=dict)
```

**Imports required in `agent/runtime.py`** (add to existing stdlib imports):
```python
# Existing imports include dataclasses, enum, threading, etc.
# Add:
from enum import Enum  # if not already imported
# dataclass and field are already imported (dataclass used at line 75 for StreamingCallKwargs fields).
```

**Verified against source:** `agent/runtime.py:30-50` has the existing import block. `dataclass` is imported (used in `StreamingCallKwargs`). `Enum` may or may not be; check with `grep -n "from enum\|^import enum" agent/runtime.py` and add if missing.

**Edit B: Add `_turn_state: dict[tuple[str, object], TurnStatus]`, `_turn_tokens: dict[str, object]`, `_turn_results: dict[tuple[str, object], TurnResult]`, and `_state_lock` to `__init__`** (after `_active_loops` declaration at line 369):

> **AUDIT FIX (BUG #3, #4).** The previous draft used
> `dict[str, TurnStatus]` keyed only by `session_key`. The audit
> correctly identified two structural problems:
> 1. **BUG #3 — GIL is not enough.** The compound "read previous
>    state → decide → write terminal state" operation is NOT atomic
>    under the GIL. Two terminal calls can both observe a non-terminal
>    state and dispatch twice. The fix is a dedicated `_state_lock`
>    acquired around ALL reads and writes of `_turn_state` /
>    `_turn_results` / `_turn_tokens`. The class docstring's
>    "synchronized under `self._lock`" claim is now literally true
>    for state-machine fields (under `_state_lock`).
> 2. **BUG #4 — Cancellation races the new turn.** With state keyed
>    only by `session_key`, a stale `cancel()` from the previous turn
>    can terminate the new turn's state. The fix is to key by
>    `(session_key, turn_token)` (a tuple) so a new turn with a fresh
>    token is observationally distinct from the prior turn. The
>    active token for a session is stored in `_turn_tokens[sk]`; a
>    terminal result whose `turn_token` does not match
>    `_turn_tokens[sk]` is a stale result and is rejected (logged,
>    ignored).

```python
        # FIX-CLEAR-ASK-RACE: sessions with an in-flight _run_loop. Used by
        # is_loop_active() and maintained by _run_loop's try/finally.
        self._active_loops: set[str] = set()

        # Turn state machine (SPEC-RUNTIME-TERMINAL-PATH-CONSOLIDATION §2.2).
        # _turn_tokens: session_key → active turn_token (object() identity).
        #   A new send_message() rotates this, so any terminal result
        #   carrying a stale token is rejected (BUG #4).
        # _turn_state: (session_key, turn_token) → current TurnStatus.
        #   Keyed by the tuple (NOT just session_key) so two turns for
        #   the same session can coexist briefly during the cancel race
        #   without overwriting each other.
        # _turn_results: (session_key, turn_token) → most recent terminal
        #   TurnResult. The handler queries via get_last_turn_result(sk)
        #   which returns the result for the currently active token.
        # _state_lock: dedicated lock for all state-machine mutations and
        #   reads. GIL does NOT make the compound operation atomic; this
        #   lock does. (BUG #3)
        self._state_lock = threading.Lock()
        self._turn_tokens: dict[str, object] = {}
        self._turn_state: dict[tuple[str, object], TurnStatus] = {}
        self._turn_results: dict[tuple[str, object], TurnResult] = {}
```

**Edit C: Add `_terminate_turn` method** (insert after `_dispatch_enforcement_status` at line 457):

> **AUDIT FIX (BUG #3, #4).** The previous draft read/wrote
> `_turn_state` and `_turn_results` without holding a lock, and
> deduplicated by `session_key` alone. The corrected version:
> 1. Acquires `_state_lock` for the read-prev / write-terminal
>    compound operation (BUG #3).
> 2. Keys state by `(session_key, turn_token)` (BUG #4).
> 3. Rejects terminal results whose `turn_token` does not match
>    `_turn_tokens[sk]` (stale-result rejection).
> 4. Returns the rejected `TurnResult` (or None) for testability
>    — the audit's BUG #9 deduplication test was impossible to
>    write without a way to know whether a call was "accepted"
>    or "rejected".

```python
    def _terminate_turn(self, result: TurnResult) -> TurnResult | None:
        """Single terminal transition function for all turn endings.

        Replaces the 5+ ad-hoc patterns of:
            self._dispatch(self._on_response_complete, ..., _turn_token=...)
            self._auto_save(...)
            return
        scattered across _run_loop. All terminal paths funnel through here.

        This is the only function that:
            - Sets the terminal TurnStatus
            - Dispatches the appropriate handler callback
            - Calls _auto_save (for FAILED and COMPLETED; CANCELLED
              requires explicit opt-in via metadata to avoid persisting
              half-finished work after /cancel)
            - Cleans up _tool_history
            - Records the result in _turn_results

        Threading: this method runs on the background thread (_run_loop's
        thread) and may also run on the main thread (from `cancel()`).
        All state-mutation paths acquire `self._state_lock`. All callback
        dispatches go through `_dispatch` which schedules
        `GLib.idle_add` for the main thread.

        Returns:
            The result if the transition was accepted; None if the result
            was rejected (invalid status, stale token, or duplicate
            terminal). Callers can use the return value for tests and
            for cancellation dedup (cancel() and the background thread
            may both call _terminate_turn for the same turn; only the
            first wins).

        Invariant: At most ONE accepted terminal transition per
        (session_key, turn_token) tuple. The function is the only
        writer of terminal state.
        """
        if result.status not in (TurnStatus.COMPLETED, TurnStatus.FAILED, TurnStatus.CANCELLED):
            logger.error(
                "_terminate_turn: invalid status %r (must be terminal); ignoring",
                result.status,
            )
            return None

        sk = result.session_key
        tk = result.turn_token
        state_key = (sk, tk)

        with self._state_lock:
            # Stale-token check (BUG #4): if a new send_message() rotated
            # the active token for this session, this result is from an
            # old turn. Reject it.
            active_token = self._turn_tokens.get(sk)
            if active_token is not None and active_token is not tk:
                logger.error(
                    "_terminate_turn: stale turn_token for %s "
                    "(active=%r, result=%r); result rejected",
                    sk, active_token, tk,
                )
                return None

            # Duplicate terminal check (BUG #3, #4): if a terminal state
            # already exists for this (sk, tk), this is a duplicate
            # transition. Reject it.
            prev = self._turn_state.get(state_key)
            if prev in (TurnStatus.COMPLETED, TurnStatus.FAILED, TurnStatus.CANCELLED):
                logger.error(
                    "_terminate_turn: duplicate terminal transition for %s "
                    "(prev=%s, new=%s); second call ignored",
                    sk, prev, result.status,
                )
                return None

            # Accepted transition — record state + result under the lock.
            self._turn_state[state_key] = result.status
            self._turn_results[state_key] = result

        # Dispatch the appropriate callback. This happens OUTSIDE the
        # state lock so a slow handler doesn't block other state
        # transitions on the same session.
        # For COMPLETED: on_response_complete with the text.
        # For FAILED/CANCELLED: on_error with the error message.
        if result.status == TurnStatus.COMPLETED:
            self._dispatch(
                self._on_response_complete, sk, result.text,
                _turn_token=result.turn_token,
            )
        else:  # FAILED or CANCELLED
            err_msg = result.error
            if err_msg is None:
                err_msg = "Turn ended without error message"
            self._dispatch(
                self._on_error, sk, err_msg,
                _turn_token=result.turn_token,
            )

        # Persist (except for CANCELLED unless explicitly requested).
        # FAILED always persists (partial state is better than lost state).
        # COMPLETED always persists (next turn must see the assistant message).
        # CANCELLED persists only if metadata["persist"] is True (caller decides
        # whether the user wants the partial assistant message on disk).
        should_persist = (
            result.status in (TurnStatus.COMPLETED, TurnStatus.FAILED)
            or result.metadata.get("persist", False)
        )
        if should_persist:
            try:
                conv = self._conversations.get(sk)
                if conv is not None:
                    self._auto_save(sk, conv)
            except Exception:
                logger.exception(
                    "_terminate_turn: auto_save failed for %s (status=%s)",
                    sk, result.status,
                )

        # Clean up stuck-detection history on terminal transitions.
        # Previously only `cancel()` did this; moved here so FAILED and
        # COMPLETED also reset the detector for the next turn.
        if result.status in (TurnStatus.FAILED, TurnStatus.CANCELLED):
            self._cleanup_tool_history(sk)

        logger.debug(
            "_terminate_turn: sk=%s tk=%r status=%s text_len=%d has_error=%s",
            sk, tk, result.status.value, len(result.text or ""),
            result.error is not None,
        )
        return result
```

**Edit D: Refactor `_run_loop` to use `_terminate_turn`** — replace the 5+ ad-hoc terminal blocks. Each replacement is targeted; the loop's body is preserved verbatim except for the terminal-call site.

> **AUDIT FIX (BUG #5).** Edit D.3 (mid-stream error with content) MUST
> include an explicit `return` after `_terminate_turn`. The previous
> draft did not, and the audit correctly observed that the code fell
> through into the text-success path (`conv.add_assistant_message(...)`
> + `_dispatch(on_response_complete, ...)`), dispatching both an error
> AND a success for the same turn.

**D.1: Cancellation paths (lines 932-940):**

```python
                    # Before:
                    if self._cancel_requested:
                        self._cancel_requested = False
                        self._dispatch(self._on_error, session_key, "Cancelled", _turn_token=turn_token)
                        return
                    # Check cancellation before each iteration
                    with self._lock:
                        if session_key in self._cancelled:
                            self._cancelled.discard(session_key)
                            self._dispatch(self._on_error, session_key, "Cancelled", _turn_token=turn_token)
                            return

                    # After:
                    if self._cancel_requested:
                        self._cancel_requested = False
                        accepted = self._terminate_turn(TurnResult(
                            status=TurnStatus.CANCELLED,
                            session_key=session_key,
                            turn_token=turn_token,
                            error="Cancelled",
                            metadata={"reason": "shutdown", "iteration": iteration},
                        ))
                        # If rejected (stale token), the loop should still
                        # exit — the new turn owns the session now.
                        return
                    # Check cancellation before each iteration
                    with self._lock:
                        if session_key in self._cancelled:
                            self._cancelled.discard(session_key)
                            self._terminate_turn(TurnResult(
                                status=TurnStatus.CANCELLED,
                                session_key=session_key,
                                turn_token=turn_token,
                                error="Cancelled",
                                metadata={"reason": "user", "iteration": iteration},
                            ))
                            return
```

**D.2: Empty/missing content error (lines 1141-1173):**

```python
                    # Before:
                            conv.add_assistant_message(
                                "[LLM returned no content — provider error or malformed response]",
                                [],
                            )
                            try:
                                self._dispatch(self._on_error, session_key, error_text, _turn_token=turn_token)
                            except Exception as _e:
                                logger.error(...)
                            self._auto_save(session_key, conv)
                            return

                    # After:
                            conv.add_assistant_message(
                                "[LLM returned no content — provider error or malformed response]",
                                [],
                            )
                            self._terminate_turn(TurnResult(
                                status=TurnStatus.FAILED,
                                session_key=session_key,
                                turn_token=turn_token,
                                error=error_text,
                                metadata={"reason": "empty_content", "iteration": iteration},
                            ))
                            return
```

Note: the `try/except` around the `_dispatch` call is **subsumed** by `_terminate_turn` — the handler exceptions are now caught at the dispatcher level (existing `_dispatch` already does `except Exception: logger.exception(...)`). The `try/except` was a belt-and-suspenders measure that becomes redundant.

**D.3: Mid-stream error with non-empty content (lines 1249-1259):**

```python
                    # Before:
                            try:
                                self._dispatch(self._on_error, session_key, error_text, _turn_token=turn_token)
                            except Exception as _e:
                                logger.error(...)

                    # After:
                            # AUDIT FIX (BUG #5): the previous code did not
                            # `return` here, falling through into the
                            # text-success path (conv.add_assistant_message +
                            # on_response_complete dispatch) below. Both an
                            # error AND a success were dispatched for the
                            # same turn. The corrected code returns
                            # unconditionally after _terminate_turn.
                            self._terminate_turn(TurnResult(
                                status=TurnStatus.FAILED,
                                session_key=session_key,
                                turn_token=turn_token,
                                error=error_text,
                                metadata={"reason": "stream_error_with_content",
                                          "iteration": iteration},
                            ))
                            return
```

Note: this path **previously did not return** — it fell through to the text-only response dispatch (line 1265). The refactor changes behavior: a mid-stream error with non-empty content now terminates the turn instead of falling through. **This is intentional and correct** — the previous behavior was a bug (the error warning got dispatched but the turn continued to dispatch a "successful" response after). The Debugger's audit specifically flagged this as "Error and completion paths are duplicated."

**D.4: Text-only response success (lines 1263-1269):**

```python
                    # Before:
                        logger.debug("[tool-loop] sk=%s text-only response, dispatching on_response_complete len=%d",
                                     session_key, len(text_content or ""))
                        conv.add_assistant_message(text_content, [])
                        self._dispatch(self._on_response_complete, session_key, text_content, _turn_token=turn_token)
                        self._check_and_stop_on_limit(session_key, conv)
                        self._auto_save(session_key, conv)
                        return

                    # After:
                        logger.debug("[tool-loop] sk=%s text-only response, dispatching on_response_complete len=%d",
                                     session_key, len(text_content or ""))
                        conv.add_assistant_message(text_content, [])
                        # AUDIT FIX (BUG #6, #11): _check_and_stop_on_limit
                        # is now a pure predicate that returns (stopped,
                        # reason) or None; it does NOT dispatch or save.
                        # If the limit is hit, build the FAILED TurnResult
                        # here and route through _terminate_turn.
                        limit_result = self._check_and_stop_on_limit(session_key, conv)
                        if limit_result is not None:
                            stopped, reason = limit_result
                            self._terminate_turn(TurnResult(
                                status=TurnStatus.FAILED,
                                session_key=session_key,
                                turn_token=turn_token,
                                error=reason,
                                metadata={"reason": stopped, "iteration": iteration},
                            ))
                            return
                        self._terminate_turn(TurnResult(
                            status=TurnStatus.COMPLETED,
                            session_key=session_key,
                            turn_token=turn_token,
                            text=text_content,
                            metadata={
                                "fallback_used": getattr(conv, "_fallback_attempted", False),
                                "stream_error": response.get("_stream_error"),
                            },
                        ))
                        return
```

> **AUDIT FIX (BUG #6, #11).** The previous draft kept
> `_check_and_stop_on_limit(session_key, conv)` at this call site
> unchanged. The audit caught two problems:
> 1. **BUG #6 — NameError.** The existing helper
>    `_check_and_stop_on_limit` (agent/runtime.py:1868) references an
>    undefined local `turn_token` in its `_dispatch(...)` call. This
>    would raise `NameError` the moment a limit is hit. The helper
>    also has no `turn_token` parameter.
> 2. **BUG #11 — Outside the state machine.** The helper dispatches
>    `on_error` and calls `_auto_save` directly, bypassing
>    `_terminate_turn`. That means a limit hit is a 6th ad-hoc
>    terminal path.
>
> The corrected plan replaces the helper with a pure predicate
> returning `(stopped, reason) | None`, and `_run_loop` builds the
> `TurnResult` itself. See Edit Q for the helper signature change.

**D.5: Max iterations (lines 1419-1423):**

```python
                    # Before:
                # Max iterations reached
                conv.add_assistant_message("[max tool iterations reached]", [])
                self._dispatch(self._on_error, session_key, "Max tool iterations reached", _turn_token=turn_token)
                self._auto_save(session_key, conv)

                    # After:
                # Max iterations reached
                conv.add_assistant_message("[max tool iterations reached]", [])
                self._terminate_turn(TurnResult(
                    status=TurnStatus.FAILED,
                    session_key=session_key,
                    turn_token=turn_token,
                    error="Max tool iterations reached",
                    metadata={"reason": "max_iterations", "iterations": max_iter},
                ))
```

Note: no explicit `return` needed — `_terminate_turn` doesn't `return`, and the loop's `while iteration < max_iter:` condition has been exhausted. Control falls out of the `while` loop into the same `finally` block. The original code's structure (no `return` after `_auto_save`) is preserved.

**D.6: Top-level exception (lines 1424-1435):**

```python
                    # Before:
            except Exception as e:
                logger.exception("Error in tool loop for %s", session_key)
                try:
                    self._auto_save(session_key, conv)
                except Exception:
                    logger.exception("Failed to auto_save after tool-loop error for %s", session_key)
                self._dispatch(self._on_error, session_key, e, _turn_token=turn_token)

                    # After:
            except Exception as e:
                logger.exception("Error in tool loop for %s", session_key)
                self._terminate_turn(TurnResult(
                    status=TurnStatus.FAILED,
                    session_key=session_key,
                    turn_token=turn_token,
                    error=e,
                    metadata={"reason": "exception", "exception_type": type(e).__name__},
                ))
```

Note: `_terminate_turn` internally calls `_auto_save` and the existing `_dispatch` already catches `Exception` from the handler. The `try/except` around `_auto_save` is preserved **inside** `_terminate_turn` (Edit C). The behavior change: handler exceptions are now caught by `_dispatch`'s `try/except`, not by the caller — same effect, less duplication.

**D.7: External cancellation in `cancel()` method (lines 661-678):**

> **AUDIT FIX (BUG #13).** The previous draft used
> `_turn_token=self._turn_token` (the runtime's single global token).
> The audit caught that if a previous `send_message()` rotated
> `_turn_token`, the cancellation dispatch carries the WRONG token,
> and the handler's stale-event filter rejects the cancellation
> event or associates it with the wrong turn. The corrected plan
> uses the active token for the session from `_turn_tokens[sk]`.

```python
                    # Before:
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
            self._dispatch(self._on_error, session_key, "Cancelled by user", _turn_token=self._turn_token)
            logger.info("Cancelled session %s", session_key)
        # §E: Clean up stuck-detection history when conversation ends
        self._cleanup_tool_history(session_key)

                    # After:
    def cancel(self, session_key: str) -> None:
        """Cancel an in-progress conversation.

        Signals the running thread to break out of the loop and dispatches
        a user-facing cancellation message. The background thread's
        `_run_loop` per-iteration cancellation check will see the signal
        and call `_terminate_turn(CANCELLED)`.

        The dispatch here uses the active turn token from
        `_turn_tokens[sk]` (not the runtime's single `_turn_token`
        attribute, which may have been rotated by a fresh
        `send_message()`). The dispatch is a UX path only — the
        authoritative state transition is the one made by
        `_terminate_turn` from the background thread.
        """
        with self._lock:
            self._cancelled.add(session_key)
            self._cancel_requested = True
            for sk in list(self._pending_approvals):
                if sk.startswith(session_key):
                    ev = self._pending_approvals[sk]["event"]
                    self._pending_approvals[sk]["result"] = None
                    ev.set()
        # §E: Clean up stuck-detection history. _terminate_turn will also
        # call _cleanup_tool_history, but doing it here too is idempotent
        # and ensures cleanup even if the background thread is wedged.
        self._cleanup_tool_history(session_key)
        # Dispatch the user-facing cancellation message. We do NOT call
        # _terminate_turn here directly because the background thread will
        # call it from its cancellation check (D.1) — and the prev-state
        # dedup in _terminate_turn ensures only one terminal transition.
        # We DO need the main-thread dispatch so the user sees the message
        # immediately rather than waiting for the loop to wake up.
        # AUDIT FIX (BUG #13): use the active token for this session,
        # not the runtime's single _turn_token attribute.
        with self._state_lock:
            active_tk = self._turn_tokens.get(session_key, self._turn_token)
        self._dispatch(
            self._on_error, session_key, "Cancelled by user",
            _turn_token=active_tk,
        )
        logger.info("Cancelled session %s", session_key)
```

Note: this **retains** the immediate `self._dispatch(self._on_error, ...)` from the main thread for UX (the user sees the cancellation message immediately). The background thread's `_terminate_turn` call from the cancellation check (D.1) is deduplicated by `_terminate_turn`'s prev-state check. This is intentional and correct — both dispatches happen, but only one `TurnResult` is recorded in `_turn_results`. The handler's existing idempotency (added in Phase 1 deferred-race-fixes: `_completed_turns: set[tuple[str, int]]`) catches the duplicate render.

**Verified against source:** All 5+ sites verified at the line numbers cited. The line numbers will drift by ~30-50 after Edit A-C are applied; the implementer must use the function/block anchors, not line numbers (per `prompts/steelFramedCodeWriter.md` Step 6.8 — Spec Drift Verification).

**Edit Q: Refactor `_check_and_stop_on_limit` to be a pure predicate** (replaces Edit D.4's helper at line 1868):

> **AUDIT FIX (BUG #6, #11).** The helper has two structural defects:
> 1. References an undefined `turn_token` local in its `_dispatch` call
>    (BUG #6 — NameError when limit is hit).
> 2. Dispatches `on_error` and saves, bypassing `_terminate_turn`
>    (BUG #11 — outside the state machine).
>
> The corrected version is a pure predicate. It does NOT dispatch,
> save, or modify any state beyond `conv.step_count` / `conv.total_cost`
> accounting. It returns `(stopped_reason, error_message) | None` so
> `_run_loop` can build the `TurnResult` and route through
> `_terminate_turn`.

```python
    def _check_and_stop_on_limit(
        self, session_key: str, conv: Any,
    ) -> tuple[str, str] | None:
        """Check cost and step limits. Returns (stopped_reason, error_message)
        if a limit is exceeded; None if the turn should continue.

        This is a PURE predicate: it does NOT dispatch callbacks, does NOT
        call `_auto_save`, and does NOT mutate `_turn_state` /
        `_turn_results`. The caller (`_run_loop`) is responsible for
        building a `TurnResult` and calling `_terminate_turn` if this
        returns non-None.

        Audit fixes (BUG #6, #11):
          - Removed the `_dispatch(self._on_error, ...)` call (was:
            NameError because `turn_token` was undefined in this scope).
          - Removed the `_auto_save(...)` call (was: a 6th ad-hoc
            terminal path that bypassed the state machine).
          - Removed the `conv.add_assistant_message(...)` call (was:
            a side effect that mutated conversation state from a
            "predicate" function — confusing for tests).

        Returns:
            None if the turn should continue.
            (stopped_reason, error_message) if a limit is hit, where
            stopped_reason is one of {"cost_limit", "step_limit"} for
            use as the TurnResult.metadata["reason"] value.
        """
        if self._config.cost_limit is not None and conv.total_cost > self._config.cost_limit:
            reason = (
                f"Cost limit exceeded: ${conv.total_cost:.4f} "
                f"> ${self._config.cost_limit:.4f}"
            )
            return ("cost_limit", reason)
        if self._config.step_limit is not None and conv.step_count > self._config.step_limit:
            reason = (
                f"Step limit exceeded: {conv.step_count} "
                f"> {self._config.step_limit}"
            )
            return ("step_limit", reason)
        return None
```

> **Note on `add_assistant_message` for limit placeholder.** The previous
> helper added a `[stopped: {reason}]` placeholder to the conversation.
> That mutation is now `_run_loop`'s responsibility, immediately before
> building the `TurnResult`. See Edit R.

**Edit R: Add limit placeholder mutation in `_run_loop`** (D.4's `if limit_result is not None` branch and the post-tool-execution limit check at line 1416):

```python
                    # At the post-tool-execution limit check (line 1416):
                    # Before:
                    if self._check_and_stop_on_limit(session_key, conv):
                        return
                    # After:
                    limit_result = self._check_and_stop_on_limit(session_key, conv)
                    if limit_result is not None:
                        stopped, reason = limit_result
                        conv.add_assistant_message(f"[stopped: {reason}]", [])
                        self._terminate_turn(TurnResult(
                            status=TurnStatus.FAILED,
                            session_key=session_key,
                            turn_token=turn_token,
                            error=reason,
                            metadata={"reason": stopped, "iteration": iteration},
                        ))
                        return
```

**Edit E: Add `get_last_turn_result` and `get_turn_state` public methods** (insert after `is_loop_active` at line 1444):

> **AUDIT FIX (BUG #3, #4).** The accessors must read under
> `_state_lock` (BUG #3 — GIL is not enough) and return the
> result for the *active* token, not any token (BUG #4 — a stale
> token from a prior turn must not be observable as the "current"
> state).

```python
    def get_last_turn_result(self, session_key: str) -> TurnResult | None:
        """Return the most recent terminal TurnResult for ``session_key``.

        Returns the TurnResult for the session's currently active
        turn token. If no terminal transition has occurred for the
        active token (turn is still RUNNING or STREAMING, or no turn
        has been attempted), returns None.

        Used by the handler for observability and by tests to assert
        on terminal state. Thread-safe via `_state_lock`.

        Note: results for stale tokens (a prior turn that has since
        been superseded by a new send_message) are NOT returned.
        Use `get_turn_state(session_key)` to inspect the active
        token's status; use `get_turn_result_for_token(sk, tk)` (if
        you need it) to inspect a specific token.
        """
        with self._state_lock:
            tk = self._turn_tokens.get(session_key)
            if tk is None:
                return None
            return self._turn_results.get((session_key, tk))

    def get_turn_state(self, session_key: str) -> TurnStatus | None:
        """Return the current TurnStatus for ``session_key``'s active
        turn token, or None if no turn is active.

        Thread-safe via `_state_lock`. Returns the status of the
        session's currently active token only.
        """
        with self._state_lock:
            tk = self._turn_tokens.get(session_key)
            if tk is None:
                return None
            return self._turn_state.get((session_key, tk))
```

**Edit F: Initialize `TurnStatus.RUNNING` at turn start** (insert at the top of `_run_loop`, BEFORE the missing-conversation check):

> **AUDIT FIX (BUG #2).** The previous draft initialized `RUNNING` AFTER
> the `if conv is None: return` early-exit and after the prompt-build
> try/except. That left `RUNNING` undefined for those two terminal paths
> and made the state machine observation order depend on which path was
> taken. The corrected plan initializes `RUNNING` as the first action in
> `_run_loop`, then routes BOTH early-exit paths through `_terminate_turn`.

```python
    def _run_loop(self, session_key: str, text: str, turn_token: object = None) -> None:
        """Background thread: run the full tool loop for one user message."""
        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so
        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the
        # finally block at the end of this function.
        with self._lock:
            self._active_loops.add(session_key)
        # Turn state machine: register the active token and initialize
        # RUNNING. _terminate_turn is the only function that transitions
        # to a terminal state. Initialization is BEFORE the conv-is-None
        # and prompt-build-failure checks so those paths also have a
        # well-defined starting state.
        with self._state_lock:
            self._turn_tokens[session_key] = turn_token
            self._turn_state[(session_key, turn_token)] = TurnStatus.RUNNING
        try:
            with self._lock:
                if not self._running:
                    return
                conv = self._conversations.get(session_key)
                if conv is None:
                    # AUDIT FIX (BUG #2): route through _terminate_turn
                    # rather than ad-hoc dispatch + return.
                    self._terminate_turn(TurnResult(
                        status=TurnStatus.FAILED,
                        session_key=session_key,
                        turn_token=turn_token,
                        error="No conversation found",
                        metadata={"reason": "no_conversation"},
                    ))
                    return

            # BUG #13 — Deferred prompt build. If create_conversation was called
            # with defer_prompt_build=True (system_prompt == ""), build it now on
            # the background thread. This eliminates ~300ms of main-thread blocking
            # on every new agent conversation.
            try:
                self._ensure_system_prompt(session_key)
            except Exception as e:
                # AUDIT FIX (BUG #2): route through _terminate_turn.
                self._terminate_turn(TurnResult(
                    status=TurnStatus.FAILED,
                    session_key=session_key,
                    turn_token=turn_token,
                    error=e,
                    metadata={"reason": "prompt_build_failed",
                              "exception_type": type(e).__name__},
                ))
                return
            ...
```

**Edit G: Transition to `STREAMING` on first LLM call** (insert just before the first `self._call_llm(...)` call, around line 1037):

```python
                    # First LLM call this turn — transition to STREAMING.
                    # STREAMING is a non-terminal state; _terminate_turn
                    # does the final transition to COMPLETED/FAILED/CANCELLED.
                    # AUDIT FIX (BUG #3, #4): access state under _state_lock
                    # and key by (session_key, turn_token).
                    with self._state_lock:
                        tk = self._turn_tokens.get(session_key)
                        if tk == turn_token and \
                                self._turn_state.get((session_key, turn_token)) == TurnStatus.RUNNING:
                            self._turn_state[(session_key, turn_token)] = TurnStatus.STREAMING

                    response = self._call_llm(session_key, messages_for_call, tools, _turn_token=turn_token)
```

**Edit H: Class docstring honesty pass** (replace the existing class docstring at the top of `agent/runtime.py`):

> **AUDIT FIX (BUG #12).** The previous draft claimed `_turn_state`
> and `_turn_results` were "protected under `self._lock`" — but the
> prescribed implementation did NOT use `self._lock` (or any lock) for
> those fields. The docstring was misleading: it described a property
> the implementation did not have. The corrected docstring matches
> the actual implementation: a dedicated `_state_lock` protects the
> state-machine fields, separately from `self._lock` which protects
> the existing conversation / cancellation / approval state.

```python
"""AgentRuntime: the core agent loop.

Threading model (SPEC-RUNTIME-TERMINAL-PATH-CONSOLIDATION §2.2 Edit H):

  The runtime operates on TWO threads:
    1. Main thread (UI / GTK): calls create_conversation, send_message,
       cancel, approve_exec, get_turn_state, get_last_turn_result.
    2. Background thread per turn: runs _run_loop, _call_llm,
       _call_llm_streaming, tool execution, persistence.

  Synchronized state (under self._lock):
    - _conversations (read in many places, written in create_conversation)
    - _cancelled, _cancel_requested (cancellation signals)
    - _active_loops (per-session in-flight marker)
    - _pending_approvals (read in _dispatch_approval, written in cancel/approve_exec)
    - _running (lifecycle flag)

  Synchronized state (under self._state_lock, a SEPARATE lock):
    - _turn_tokens: session_key → active turn_token. Written by
      _run_loop at start; read by _terminate_turn and cancel().
    - _turn_state: (session_key, turn_token) → current TurnStatus.
      Written only by _terminate_turn; read by _terminate_turn, the
      STREAMING transition in _run_loop, and the public accessors
      get_turn_state() / get_last_turn_result().
    - _turn_results: (session_key, turn_token) → most recent
      TurnResult. Same access pattern as _turn_state.

  Why a separate _state_lock: the GIL does NOT make the compound
  "read previous state → decide → write terminal state" operation
  atomic. Two threads calling _terminate_turn for the same session
  could both observe a non-terminal state and both dispatch. The
  state lock serializes the compound operation. The lock is NOT
  held during the dispatch callback (which is slow and may invoke
  GLib.idle_add); the lock is only held for the state mutation.

  Per-instance locks (separate from self._lock and _state_lock):
    - _tool_history_lock: protects _tool_history (stuck detection).
    - _compaction_lock: protects _compaction_events (telemetry).

  NOT synchronized (read-mostly, written once at init):
    - _runtimes, _agents, _config, _GLib
    - All callback references (on_text_delta etc.)
    - _pending_stuck_messages: per-session dict; written by _check_stuck
      (background), read by _call_llm (same thread, sequential).
      Cross-turn races are possible if the user hits /clear mid-turn;
      see FIX-CLEAR-ASK-RACE for the active-loop guard that mitigates.

  Known race: a result for a stale turn_token (one that has been
  rotated by a new send_message()) is rejected by _terminate_turn.
  The rejection is logged but the dispatch is NOT made. The handler
  must be prepared for: a turn may dispatch on_error / on_response_complete
  for the OLD token, then a NEW turn's RUNNING state begins, then the
  OLD token's stale result is dropped. This is the desired behavior
  (a previous turn must not abort a current turn), but it is observable
  in tests as: "the dispatched callback for the old turn fires, but
  no TurnResult is recorded for the new turn."

  Not actually thread-safe (concurrent access is a latent bug):
    - _pending_stuck_messages (see above).
    - The streaming text accumulator lives in the HANDLER
      (`ui/handlers/agent_runtime_handler.py`); the runtime's
      _call_llm_streaming is single-threaded per call.
"""
```

---

### 2.3 `agent/runtime.py` — Remove provider alias debt (6 edits, ~7 lines removed + 12 test/script lines updated)

> **AUDIT FIX (BUG #1, #8).** A previous draft of this section asserted
> that no tests or scripts used the aliases and that a grep sweep before
> commit would confirm 0 external matches. **This was false.** A repository-
> wide grep against the current tree (`git rev-parse HEAD`) returns these
> live external consumers:
>
> - `agent/llm/streaming.py:77,370-371` — docstring references to
>   `_stream_openai_events` / `_stream_minimax_events` / `_stream_anthropic_events`.
> - `utils/provider_test.py:96` — docstring references `_call_minimax`.
> - `scripts/audit_streaming_scenarios.py` lines 43, 70, 92, 118, 143, 191,
>   222, 242, 262 — `patch("agent.runtime._PROVIDER_STREAMERS", ...)`.
> - `scripts/audit_attack_scenarios.py:6,118,119,122,123,124,125` —
>   imports `_PROVIDER_STREAMERS` directly; `get_provider("").get("")` smoke
>   tests use the dict.
> - `tests/test_llm_providers.py:735` — references `_PROVIDER_STREAMERS`
>   in a docstring.
> - `tests/test_agent_runtime.py` lines 1362, 1541-1593, 1650-1697, 2336-
>   2379, 2479-2724, 3679-3703 — 9 test methods that `from agent.runtime
>   import _stream_openai_events / _stream_anthropic_events /
>   _stream_minimax_events / _call_minimax / _call_anthropic`.
> - `tests/generate_synthetic_conversations.py:56,126` — a *local* function
>   named `_call_minimax` (NOT the runtime alias; name collision only — no
>   runtime import, but grep will match).
>
> The corrected plan below divides the symbols into two groups based on
> whether they have **active** external consumers (which must be migrated
> in the same commit) or only **inert** consumers (docstrings, comments).
>
> **Two-tier removal:**
> - **Tier 1 — Safe to remove (docstring-only references):**
>   `_stream_openai_events` / `_stream_minimax_events` / `_stream_anthropic_events`
>   references in `agent/llm/streaming.py` and `utils/provider_test.py`
>   docstrings. These are inert — `streaming.py` re-uses the
>   `stream_with_ssl_retry` callable shape, not the runtime alias. The
>   docstrings will be updated to refer to `OpenAIProvider("openai").stream`
>   etc. by name. **No test breaks.**
> - **Tier 2 — Migration of active consumers:** the test and script
>   consumers listed above. They must be rewritten to use
>   `agent.llm.registry.get_provider(caller_key).stream(...)` /
>   `.call(...)` instead of importing the removed aliases. This is 12+
>   line changes across 4 files.

**Background:** During the Phase B4/B6 extraction, the following aliases were preserved "for test-patch compatibility":

- `_call_openai = OpenAIProvider("openai").call` (line 103)
- `_call_minimax = MiniMaxProvider().call` (line 104)
- `_call_anthropic = AnthropicProvider().call` (line 105)
- `_stream_openai_events = OpenAIProvider("openai").stream` (line 179)
- `_stream_minimax_events = MiniMaxProvider().stream` (line 180)
- `_stream_anthropic_events = AnthropicProvider().stream` (line 181)
- `_PROVIDER_STREAMERS: dict[str, Any]` (line 186) — used by `scripts/audit_*`
  and `tests/test_agent_runtime.py`; not used by production runtime code
  (production dispatch is via `_get_provider(caller_key).stream`).

**Edit I: Delete `_call_openai`, `_call_minimax`, `_call_anthropic` aliases** (lines 102-105):

> **AUDIT FIX (BUG #1).** The previous draft deleted these aliases while
> keeping `_PROVIDER_CALLERS` and `_RESPONSE_FORMAT`, which depend on them
> for their `.get()` calls and the `if _caller is _call_anthropic:` check.
> That left undefined names during module import. The corrected plan keeps
> `_PROVIDER_CALLERS` (used by `_call_llm` non-streaming dispatch and by
> `get_valid_callers()` for the provider-caller taxonomy) but migrates its
> values from the bound-method aliases to direct provider lookups.

```python
# Before (lines 102-105):
# Bound methods for test-patch compatibility (patch("agent.runtime._call_openai"))
_call_openai = OpenAIProvider("openai").call
_call_minimax = MiniMaxProvider().call
_call_anthropic = AnthropicProvider().call

# After:
# Provider dispatch is via agent.llm.registry._get_provider() (Phase B4).
# _call_llm's non-streaming path uses _get_provider(caller_key).call(...).
# _call_llm_streaming uses _get_provider(caller_key).stream.
# The previous bound-method aliases _call_openai / _call_minimax /
# _call_anthropic were preserved for test-patch compatibility but have
# been migrated to use the registry (see _PROVIDER_CALLERS below).
# Tests in tests/test_agent_runtime.py that `from agent.runtime import
# _call_minimax` / `_call_anthropic` have been rewritten to call
# MiniMaxProvider().call(...) / AnthropicProvider().call(...) directly
# (Edit O).
```

**Edit J: Delete `_stream_*_events` aliases and `_PROVIDER_STREAMERS` dict** (lines 179-189):

> **AUDIT FIX (BUG #8).** The previous draft asserted no external consumers
> exist; this is false (see the grep evidence in the section header). The
> corrected plan migrates the consumers in the same commit.

```python
# Before (lines 179-189):
_stream_openai_events = OpenAIProvider("openai").stream
_stream_minimax_events = MiniMaxProvider().stream
_stream_anthropic_events = AnthropicProvider().stream

# Original _PROVIDER_STREAMERS dict (now dead — _call_llm_streaming
# uses _get_provider(caller_key).stream instead):
_PROVIDER_STREAMERS: dict[str, Any] = {
    "openai": _stream_openai_events,
    "minimax": _stream_minimax_events,
    "anthropic": _stream_anthropic_events,
    "openrouter": OpenAIProvider("openrouter").stream,
    "zai": OpenAIProvider("zai").stream,
}

# After:
# _PROVIDER_STREAMERS and the _stream_*_events aliases were dispatch
# infrastructure superseded by _get_provider(caller_key).stream in
# Phase B6. Removed in SPEC-RUNTIME-TERMINAL-PATH-CONSOLIDATION §2.3.
# Tests in tests/test_agent_runtime.py and audit scripts that imported
# them have been migrated to OpenAIProvider("openai").stream(...) /
# MiniMaxProvider().stream(...) / AnthropicProvider().stream(...)
# (Edits N, O).
```

**Edit K: Update `__all__` and `_PROVIDER_CALLERS` to remove alias dependencies** (lines 82, 112-118):

```python
# Before (line 82):
__all__ = [
    "AgentRuntime",
    "SSEEvent",
    "StreamingCallKwargs",
    "_PROVIDER_CALLERS",
    "_PROVIDER_STREAMERS",
]

# After (line 82):
__all__ = [
    "AgentRuntime",
    "SSEEvent",
    "StreamingCallKwargs",
    # _PROVIDER_CALLERS retained: used by _call_llm's non-streaming
    # dispatch (line ~1618) and by get_valid_callers() for the
    # provider-caller taxonomy. _PROVIDER_STREAMERS removed: dead
    # since Phase B6 (Edit J).
    "_PROVIDER_CALLERS",
    "TurnStatus",
    "TurnResult",
]

# Before (lines 110-118):
_PROVIDER_CALLERS: dict[str, Any] = {
    "openai": _call_openai,
    "minimax": _call_minimax,
    "anthropic": _call_anthropic,
    "openrouter": OpenAIProvider("openrouter").call,
    "zai": OpenAIProvider("zai").call,
}

# After (lines 110-118):
# _PROVIDER_CALLERS values are now direct lookups into the provider
# registry rather than bound-method aliases. _RESPONSE_FORMAT
# (derived from this dict) and get_valid_callers() (returns
# _PROVIDER_CALLERS.keys()) work unchanged.
_PROVIDER_CALLERS: dict[str, Any] = {
    "openai": OpenAIProvider("openai").call,
    "minimax": MiniMaxProvider().call,
    "anthropic": AnthropicProvider().call,
    "openrouter": OpenAIProvider("openrouter").call,
    "zai": OpenAIProvider("zai").call,
}
```

> **Note on `_RESPONSE_FORMAT`:** The derivation loop
> `for _pk, _caller in _PROVIDER_CALLERS.items(): if _caller is _call_anthropic`
> depends on **identity comparison** with `_call_anthropic`. After Edit I
> deletes `_call_anthropic`, the comparison must be rewritten to compare
> with the new dict value (e.g. `_caller is _PROVIDER_CALLERS["anthropic"]`)
> or, preferably, to use the caller key directly:
>
> ```python
> # After (replacement for lines 145-152):
> # Response format families — derived from caller key (was: identity
> # comparison against _call_anthropic; deleted in Edit I). Any provider
> # not in {"anthropic"} uses OpenAI-format responses.
> _RESPONSE_FORMAT: dict[str, str] = {
>     pk: "anthropic" if pk == "anthropic" else "openai"
>     for pk in _PROVIDER_CALLERS
> }
> ```
>
> This avoids the identity-comparison trap and is clearer.

**Edit L: Verify no production code uses the removed symbols after the migration in Edits N, O, P** (grep sweep before commit):

```bash
grep -rn "_PROVIDER_STREAMERS\|_stream_openai_events\|_stream_minimax_events\|_stream_anthropic_events" \
    --include="*.py" /home/q/projects/crabcakes/ | \
    grep -v "tests/generate_synthetic_conversations.py\|_call_minimax"
```

Expected output: 0 matches. The only inert match is
`tests/generate_synthetic_conversations.py:56` which defines a **local**
function named `_call_minimax` (not an import of the runtime alias).
`grep -v` filters it.

> **If any matches remain after Edits N, O, P**, do not commit. The
> remaining consumers must be migrated in the same commit or the
> aliases must be kept as compat shims (deferred to a follow-up spec).

**Edit M: Verify no production code uses the removed `_call_*` aliases** (grep sweep):

```bash
grep -rn "from agent.runtime import.*\(_call_openai\|_call_minimax\|_call_anthropic\)\|agent\.runtime\._call_openai\|agent\.runtime\._call_minimax\|agent\.runtime\._call_anthropic" \
    --include="*.py" /home/q/projects/crabcakes/ | \
    grep -v "tests/generate_synthetic_conversations.py"
```

Expected output: 0 matches outside `agent/runtime.py` (where the symbols
are being removed). The local `_call_minimax` in
`tests/generate_synthetic_conversations.py` is a name collision only —
no import of the runtime alias, so it does not break.

**Edit N: Migrate `scripts/audit_streaming_scenarios.py` and `scripts/audit_attack_scenarios.py`** (12 sites).

The 9 `patch("agent.runtime._PROVIDER_STREAMERS", {"openai": streamer})`
sites in `scripts/audit_streaming_scenarios.py` and the 5
`from agent.runtime import _PROVIDER_STREAMERS` / `_PROVIDER_STREAMERS.get(...)`
sites in `scripts/audit_attack_scenarios.py` must be rewritten to patch
the provider class method instead:

```python
# scripts/audit_streaming_scenarios.py — replace each:
# Before:
with patch("agent.runtime._PROVIDER_STREAMERS", {"openai": bad_streamer}):
    ...

# After (one canonical pattern; the streamer key "openai" selects OpenAIProvider):
with patch("agent.llm.registry.get_provider",
           return_value=_FakeProvider(stream=bad_streamer)) as mock_get:
    ...

# Or, more directly for tests that don't need registry mocking:
with patch.object(OpenAIProvider, "stream", bad_streamer):
    ...
```

The implementer should choose the simpler `patch.object(OpenAIProvider,
"stream", ...)` form unless the test specifically exercises registry
routing. For `audit_attack_scenarios.py`, the imports
(`from agent.runtime import _PROVIDER_STREAMERS`) become
`from agent.llm.registry import get_provider` and the `.get("")` calls
become `get_provider("") is None` style direct calls.

**Edit O: Migrate `tests/test_agent_runtime.py` `_stream_*_events` and `_call_*` imports** (9 test methods, lines 1362, 1541-1593, 1650-1697, 2336-2379, 2479-2724, 3679-3703).

For each test that does `from agent.runtime import _stream_openai_events`
(or `_stream_anthropic_events`, `_stream_minimax_events`, `_call_minimax`,
`_call_anthropic`), rewrite the call to use the provider class directly:

```python
# Before:
from agent.runtime import _stream_openai_events
with patch.object(rt, "_call_llm_streaming", return_value=...) as mock_stream:
    events = list(_stream_openai_events(...))

# After:
from agent.llm.openai_provider import OpenAIProvider
with patch.object(rt, "_call_llm_streaming", return_value=...) as mock_stream:
    events = list(OpenAIProvider("openai").stream(...))
```

The 9 sites in §2.3's header can be migrated mechanically. The test
behavior is unchanged because the bound-method aliases were direct
wrappers around `OpenAIProvider("openai").stream` etc.

**Edit P: Update docstring/comment references in `agent/llm/streaming.py` and `utils/provider_test.py`** (3 sites, lines 77, 370-371, 96).

Replace the runtime-alias names with provider class method names in
docstrings and comments. These are inert but should not lie about
the current shape.

---

### 2.4 `tests/test_agent_runtime.py` — Replace `MagicMock()` with `create_autospec` at 3 sites (3 edits)

**Background:** The Debugger's audit identified `MagicMock()` patterns where the test mock's signature doesn't track the real method. When the real method gains a parameter (e.g. `turn_token`), the test still passes because `MagicMock()` accepts any kwargs. The fix is `unittest.mock.create_autospec(real_fn)` which makes the mock raise `TypeError` on bad signatures, catching the drift at test time.

**Verified against source:** `grep -n "MagicMock()" tests/test_agent_runtime.py | head -10` shows the patterns. The 3 sites below are the ones confirmed to be the source of the `turn_token` contract regression.

**Edit N: Test for `test_user_plus_assistant_in_conversation` (the regression site):**

The test is in `TestToolLoop` class, `test_user_plus_assistant_in_conversation` method. The current implementation uses `MagicMock()` for the `_call_llm` replacement:

```python
# Before (around line 3630-3650, exact lines drift — use function anchor):
def test_user_plus_assistant_in_conversation(self):
    """... [test docstring]"""
    # The runtime now adds turn_token to _call_llm; mock must accept it.
    rt = AgentRuntime(config=mock_config, GLib=None)
    # ...
    # Old pattern (broken after turn_token was added):
    with patch.object(rt, "_call_llm", return_value=mock_response) as mock_call:
        rt._run_loop("test:session", "user message")
    # ...

# After:
def test_user_plus_assistant_in_conversation(self):
    """... [test docstring]"""
    from unittest.mock import create_autospec, patch
    rt = AgentRuntime(config=mock_config, GLib=None)
    # autospec enforces the real _call_llm signature, including turn_token.
    mock_call = create_autospec(rt._call_llm, return_value=mock_response)
    with patch.object(rt, "_call_llm", side_effect=mock_call):
        rt._run_loop("test:session", "user message")
    # Verify call was made with turn_token (the parameter the test was missing).
    mock_call.assert_called()
    _, kwargs = mock_call.call_args
    assert "turn_token" in kwargs, (
        "Regression: turn_token kwarg was lost between _run_loop and _call_llm"
    )
```

**Edit O: Test for `test_exec_without_callback_denied` (TestApproval class):**

The current pattern uses a 3-arg `lambda` for `_on_tool_call_result` that doesn't accept the 4th `success` arg:

```python
# Before:
on_tool_call_result=lambda sk, name, result: None,  # 3 args, fails on 4-arg call

# After:
from unittest.mock import MagicMock
on_tool_call_result=MagicMock(),  # autospec'd to ToolCallResult callback signature
```

Concretely:

```python
# Before (around line 3500-3530 in TestApproval::test_exec_without_callback_denied):
rt = AgentRuntime(
    config=mock_config,
    GLib=None,
    on_tool_call_result=lambda sk, name, result: None,  # BUG: missing success arg
    on_error=lambda sk, msg: None,
)

# After:
from agent.callbacks import OnToolCallResult
rt = AgentRuntime(
    config=mock_config,
    GLib=None,
    on_tool_call_result=create_autospec(OnToolCallResult, return_value=None),
    on_error=create_autospec(lambda sk, msg: None, return_value=None),
)
```

**Edit P: Test for `test_tool_call_appends_result` (TestToolLoop class):**

Same pattern — the test injects a 3-arg lambda for a 4-arg callback. Replace with `create_autospec`.

```python
# Before:
on_tool_call_result=lambda sk, name, result: None,

# After:
on_tool_call_result=create_autospec(OnToolCallResult, return_value=None),
```

**Verified against source:** `grep -n "lambda sk, name, result" tests/test_agent_runtime.py` should find these 2 sites + any others. The implementer must grep the entire test file, not just the 3 sites named in this spec — there may be more.

---

### 2.5 Deferred: `agent/turn.py` extraction

**Status:** DEFERRED to a follow-up spec. The Debugger's recommendation #1 was "Introduce a `TurnContext` / `TurnState` object containing session key, cancellation state, token, iteration, accumulated text, and terminal status."

This spec implements the state machine **as internal state in `AgentRuntime`** (Edit B). Moving it to a separate `agent/turn.py` module is a follow-up because:

- The `TurnContext` shape needs the state machine to settle first (the current iteration is one full commit cycle; a follow-up commit cycle can extract once the API is proven)
- The state machine touches `_active_loops`, `_conversations`, `_auto_save`, `_cleanup_tool_history`, `_dispatch` — all internal to `AgentRuntime`. Extracting to a separate module would require passing all of these as dependencies to `TurnContext`, which is the same complexity the current structure has, just moved
- The Deferred work would be: extract `TurnStatus` + `TurnResult` + `_terminate_turn` to `agent/turn.py`, leaving `AgentRuntime` with a thin wrapper that delegates. Estimated: 1 week. Lower priority than this spec's terminal-path consolidation.

**Files NOT changed in this spec:**
- `agent/persistence.py` — already extracted (Phase 6); the `save_conversation_to_disk` and `auto_save` functions used by `_terminate_turn` are already there.
- `agent/audit.py` — already extracted (Phase 5); the `AuditLog` is wired in `__init__`.
- `agent/tool_middleware.py` — already extracted (Phase A1); `EnforcementMiddleware` + `StuckDetectionMiddleware` + `ToolMiddlewareChain` are used in `_run_loop` tool execution.
- `agent/llm/{protocol,registry,providers}.py` — already extracted (Phase B4/B6); `_call_llm` uses `_get_provider` exclusively after this spec.
- `agent/context_strategy.py` — already extracted (Phase 0); `_context_strategy.compact()` is used in `_run_loop`.
- `ui/handlers/agent_runtime_handler.py` — the handler's `_on_*` methods already satisfy the new `On*` Protocols structurally; no changes needed.
- `models/conversation.py` — the `Conversation` object used by `_run_loop` is unchanged.
- `tests/test_agent_runtime.py` — only the 3 sites in Edit N/O/P change. New tests for `_terminate_turn` are added (see §2.6).

---

### 2.6 New tests in `tests/test_agent_runtime.py` (18 tests, up from 15)

> **AUDIT FIX (BUG #9, #10).** The previous draft of this section had
> two unworkable tests:
> 1. **BUG #9.** `test_terminate_turn_persists_for_completed_and_failed_not_cancelled`
>    called `_terminate_turn` four times for the same `"test:sk"`. The
>    first call transitions to a terminal state; the remaining three
>    are deduped and return without persisting. The expected save
>    counts of 2 and 3 are impossible. The corrected test uses four
>    separate session keys, one per terminal status.
> 2. **BUG #10.** The 4 tests in "Test group 3" called
>    `rt._run_loop("test:sk", "hello")` without first creating a
>    conversation. The loop's `self._conversations.get("test:sk")`
>    returns `None`, so the loop takes the missing-conversation path
>    (which is now itself a `_terminate_turn(FAILED, no_conversation)`
>    call) instead of reaching the LLM. The tests would silently
>    validate the wrong path. The corrected tests use `_uniq()` to
>    generate unique session keys and call `create_conversation` first.

**Test group 1: `TurnStatus` and `TurnResult` (3 tests)**

```python
def test_turn_status_enum_values():
    """TurnStatus has 5 values, 2 non-terminal (RUNNING, STREAMING) and
    3 terminal (COMPLETED, FAILED, CANCELLED)."""
    from agent.runtime import TurnStatus
    assert {s.value for s in TurnStatus} == {
        "running", "streaming", "completed", "failed", "cancelled",
    }
    non_terminal = {TurnStatus.RUNNING, TurnStatus.STREAMING}
    terminal = {TurnStatus.COMPLETED, TurnStatus.FAILED, TurnStatus.CANCELLED}
    assert non_terminal.isdisjoint(terminal)

def test_turn_result_required_fields():
    """TurnResult requires status, session_key, turn_token. text defaults
    to empty, error to None, metadata to empty dict."""
    from agent.runtime import TurnResult, TurnStatus
    tr = TurnResult(
        status=TurnStatus.COMPLETED,
        session_key="test:sk",
        turn_token=object(),
    )
    assert tr.text == ""
    assert tr.error is None
    assert tr.metadata == {}

def test_turn_result_metadata_isolation():
    """Two TurnResult instances must not share metadata dict (mutable
    default arg trap)."""
    from agent.runtime import TurnResult, TurnStatus
    tr1 = TurnResult(
        status=TurnStatus.FAILED,
        session_key="test:sk",
        turn_token=object(),
        metadata={"reason": "x"},
    )
    tr2 = TurnResult(
        status=TurnStatus.FAILED,
        session_key="test:sk",
        turn_token=object(),
    )
    tr1.metadata["leak"] = "value"
    assert "leak" not in tr2.metadata
```

**Test group 2: `_terminate_turn` behavior (8 tests, was 6)**

```python
def test_terminate_turn_dispatches_on_response_complete_for_completed():
    """_terminate_turn(COMPLETED) calls on_response_complete with text."""
    from agent.runtime import TurnResult, TurnStatus
    mock_complete = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_response_complete=mock_complete)
    sk = _uniq()
    tk = object()
    rt._turn_tokens[sk] = tk
    rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
    accepted = rt._terminate_turn(TurnResult(
        status=TurnStatus.COMPLETED,
        session_key=sk, turn_token=tk, text="Hello",
    ))
    assert accepted is not None
    mock_complete.assert_called_once()
    args, kwargs = mock_complete.call_args
    assert args[1] == "Hello"  # session_key, text
    assert kwargs.get("_turn_token") is tk

def test_terminate_turn_dispatches_on_error_for_failed():
    """_terminate_turn(FAILED) calls on_error with the error."""
    from agent.runtime import TurnResult, TurnStatus
    mock_error = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_error=mock_error)
    sk = _uniq(); tk = object()
    rt._turn_tokens[sk] = tk
    rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
    rt._terminate_turn(TurnResult(
        status=TurnStatus.FAILED, session_key=sk, turn_token=tk,
        error="Something went wrong",
    ))
    mock_error.assert_called_once()

def test_terminate_turn_dispatches_on_error_for_cancelled():
    """_terminate_turn(CANCELLED) calls on_error with the error."""
    from agent.runtime import TurnResult, TurnStatus
    mock_error = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_error=mock_error)
    sk = _uniq(); tk = object()
    rt._turn_tokens[sk] = tk
    rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
    rt._terminate_turn(TurnResult(
        status=TurnStatus.CANCELLED, session_key=sk, turn_token=tk,
        error="Cancelled by user",
    ))
    mock_error.assert_called_once()

def test_terminate_turn_rejects_non_terminal_status():
    """_terminate_turn with RUNNING or STREAMING is invalid; returns None,
    does not dispatch, does not transition state."""
    from agent.runtime import TurnResult, TurnStatus
    mock_complete = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_response_complete=mock_complete)
    sk = _uniq(); tk = object()
    rt._turn_tokens[sk] = tk
    accepted = rt._terminate_turn(TurnResult(
        status=TurnStatus.RUNNING, session_key=sk, turn_token=tk,
    ))
    assert accepted is None
    mock_complete.assert_not_called()
    assert rt.get_turn_state(sk) is None

def test_terminate_turn_dedups_duplicate_terminal_transitions():
    """Calling _terminate_turn twice for the same (sk, tk) returns None
    on the second call; only one transition is recorded."""
    from agent.runtime import TurnResult, TurnStatus
    mock_complete = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_response_complete=mock_complete)
    sk = _uniq(); tk = object()
    rt._turn_tokens[sk] = tk
    rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
    first = rt._terminate_turn(TurnResult(
        status=TurnStatus.COMPLETED, session_key=sk, turn_token=tk, text="x",
    ))
    second = rt._terminate_turn(TurnResult(
        status=TurnStatus.FAILED, session_key=sk, turn_token=tk, error="y",
    ))
    assert first is not None
    assert second is None
    assert mock_complete.call_count == 1

def test_terminate_turn_rejects_stale_token():
    """AUDIT FIX (BUG #4). If the active token for sk has been rotated
    (new send_message), a result with the old token is rejected."""
    from agent.runtime import TurnResult, TurnStatus
    mock_complete = MagicMock()
    rt = AgentRuntime(config=_make_cfg(), GLib=None,
                      on_response_complete=mock_complete)
    sk = _uniq()
    old_tk, new_tk = object(), object()
    rt._turn_tokens[sk] = new_tk  # active token is the new one
    rt._turn_state[(sk, new_tk)] = TurnStatus.RUNNING
    # Result for the OLD token — should be rejected.
    accepted = rt._terminate_turn(TurnResult(
        status=TurnStatus.COMPLETED, session_key=sk,
        turn_token=old_tk, text="stale",
    ))
    assert accepted is None
    mock_complete.assert_not_called()
    # Active token's state was not disturbed.
    assert rt.get_turn_state(sk) == TurnStatus.RUNNING

def test_terminate_turn_persistence_uses_separate_session_keys():
    """AUDIT FIX (BUG #9). COMPLETED, FAILED, and CANCELLED each
    auto-save. Use separate session keys because _terminate_turn
    dedups terminal transitions for the same (sk, tk)."""
    from agent.runtime import TurnResult, TurnStatus
    rt = AgentRuntime(config=_make_cfg(), GLib=None)
    with patch.object(rt, "_auto_save") as mock_save:
        # Three separate session keys, each with its own token.
        for status, error, text, should_persist in [
            (TurnStatus.COMPLETED, None, "x", True),
            (TurnStatus.FAILED, "oops", "", True),
            (TurnStatus.CANCELLED, "cancelled", "", False),
        ]:
            sk = _uniq(); tk = object()
            rt._turn_tokens[sk] = tk
            rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
            rt._conversations[sk] = MagicMock()  # so _auto_save has a conv
            rt._terminate_turn(TurnResult(
                status=status, session_key=sk, turn_token=tk,
                text=text, error=error,
            ))
        # COMPLETED and FAILED persisted (counts 1 and 2);
        # CANCELLED without persist flag did NOT (count stays 2).
        assert mock_save.call_count == 2

def test_terminate_turn_cancelled_with_persist_metadata_saves():
    """CANCELLED with metadata={'persist': True} saves."""
    from agent.runtime import TurnResult, TurnStatus
    rt = AgentRuntime(config=_make_cfg(), GLib=None)
    with patch.object(rt, "_auto_save") as mock_save:
        sk = _uniq(); tk = object()
        rt._turn_tokens[sk] = tk
        rt._turn_state[(sk, tk)] = TurnStatus.RUNNING
        rt._conversations[sk] = MagicMock()
        rt._terminate_turn(TurnResult(
            status=TurnStatus.CANCELLED, session_key=sk, turn_token=tk,
            error="cancelled", metadata={"persist": True},
        ))
        assert mock_save.call_count == 1
```

**Test group 3: turn state transitions in `_run_loop` (4 tests)**

> **AUDIT FIX (BUG #10).** Every test in this group MUST
> `create_conversation` before invoking `_run_loop` and MUST use a
> unique session key (via `_uniq()`) so tests don't share state.
> The previous draft used the hardcoded literal `"test:sk"` and did
> not call `create_conversation`; both are corrected here.

```python
def test_run_loop_starts_in_running_state():
    """At the top of _run_loop, _turn_state[(sk, tk)] == RUNNING.
    After the loop completes, the state is COMPLETED."""
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    with patch.object(rt, "_call_llm", return_value=_resp("Hello, human.")):
        rt._run_loop(sk, "hello")
    assert rt.get_turn_state(sk) == TurnStatus.COMPLETED
    rt.stop()

def test_run_loop_transitions_to_streaming_before_first_llm_call():
    """After _call_llm is called once, state is STREAMING; after the
    loop ends, state is COMPLETED."""
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    states_seen = []
    def tracking_call(*args, **kwargs):
        states_seen.append(rt.get_turn_state(sk))
        return _resp("Hello.")
    with patch.object(rt, "_call_llm", side_effect=tracking_call):
        rt._run_loop(sk, "hello")
    assert TurnStatus.STREAMING in states_seen
    assert rt.get_turn_state(sk) == TurnStatus.COMPLETED
    rt.stop()

def test_run_loop_terminates_with_failed_on_max_iterations():
    """When max_tool_iterations is reached without a text response,
    terminal status is FAILED with reason 'max_iterations'."""
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    # Mock _call_llm to always return tool calls (never text)
    tool_resp = _resp(tool_calls=[{
        "id": "call_1", "function": {"name": "list_files",
                                      "arguments": '{"path": "."}'},
    }])
    with patch.object(rt, "_call_llm", return_value=tool_resp), \
         patch.object(rt, "execute_tool", return_value=("ok", True, None)):
        rt._run_loop(sk, "hello")
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.FAILED
    assert result.metadata.get("reason") == "max_iterations"
    rt.stop()

def test_run_loop_terminates_with_cancelled_on_cancel_signal():
    """When _cancel_requested is set during the loop, terminal status
    is CANCELLED with reason 'shutdown'."""
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    def trigger_cancel(*args, **kwargs):
        rt._cancel_requested = True
        return _resp("Cancelled mid-call.")
    with patch.object(rt, "_call_llm", side_effect=trigger_cancel):
        rt._run_loop(sk, "hello")
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.CANCELLED
    rt.stop()
```

**Test group 3a: AUDIT FIX (BUG #2) — missing-conversation and prompt-build-failure paths (2 tests)**

> The previous draft's "edge-case table" mentioned these paths but
> the proposed test list did not include tests for them. Without
> tests, the "all terminal paths use the chokepoint" claim is
> unfalsifiable. These two tests pin the behavior.

```python
def test_run_loop_terminates_with_failed_on_no_conversation():
    """AUDIT FIX (BUG #2). _run_loop with a session_key that has no
    Conversation must route through _terminate_turn(FAILED,
    no_conversation) — not the ad-hoc dispatch + return."""
    from agent.runtime import TurnResult, TurnStatus
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    # Deliberately do NOT call create_conversation.
    mock_error = MagicMock()
    rt._on_error = mock_error
    rt._run_loop(sk, "hello")
    # _terminate_turn dispatched on_error exactly once with the
    # "no conversation" message.
    mock_error.assert_called_once()
    args, kwargs = mock_error.call_args
    assert "no conversation" in str(args[1]).lower() or \
           "no conversation" in str(kwargs.get("message", "")).lower()
    rt.stop()

def test_run_loop_terminates_with_failed_on_prompt_build_failure():
    """AUDIT FIX (BUG #2). _run_loop where _ensure_system_prompt
    raises must route through _terminate_turn(FAILED,
    prompt_build_failed)."""
    from agent.runtime import TurnStatus
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    mock_error = MagicMock()
    rt._on_error = mock_error
    with patch.object(rt, "_ensure_system_prompt",
                      side_effect=RuntimeError("prompt build failed")):
        rt._run_loop(sk, "hello")
    mock_error.assert_called_once()
    # The result's metadata should mark this as a prompt-build failure.
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.FAILED
    assert result.metadata.get("reason") == "prompt_build_failed"
    rt.stop()
```

**Test group 3b: AUDIT FIX (BUG #5) — mid-stream error with content terminates (1 test)**

> The previous draft described this behavior change but did not
> include a regression test. Without a test, the fall-through
> regression (D.3 dispatching on_error and then continuing to
> dispatch on_response_complete) can silently return.

```python
def test_run_loop_terminates_with_failed_on_stream_error_with_content():
    """AUDIT FIX (BUG #5). A response with non-empty text_content AND
    _stream_error must terminate the turn with FAILED; the previous
    fall-through to on_response_complete must NOT happen."""
    from agent.runtime import TurnStatus
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    response = {
        "choices": [{"message": {
            "content": "partial response that was streamed",
            "tool_calls": [],
        }}],
        "_stream_error": {"code": 500, "message": "stream failed"},
    }
    mock_response_complete = MagicMock()
    mock_error = MagicMock()
    rt._on_response_complete = mock_response_complete
    rt._on_error = mock_error
    with patch.object(rt, "_call_llm", return_value=response):
        rt._run_loop(sk, "hello")
    # on_error was called once; on_response_complete was NOT called
    # (no fall-through).
    mock_error.assert_called_once()
    mock_response_complete.assert_not_called()
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.FAILED
    assert result.metadata.get("reason") == "stream_error_with_content"
    rt.stop()
```

**Test group 3c: AUDIT FIX (BUG #6) — limit handling terminates (2 tests)**

> The previous draft's "edge-case table" mentioned cost-limit and
> step-limit paths but the proposed test list did not include
> them. These tests pin the limit-then-terminate behavior.

```python
def test_run_loop_terminates_with_failed_on_cost_limit():
    """AUDIT FIX (BUG #6). When conv.total_cost > cost_limit, the
    turn terminates with FAILED reason='cost_limit'."""
    from agent.runtime import TurnStatus
    cfg = _make_cfg()
    cfg.cost_limit = 0.0  # any cost > 0 will trip
    rt = AgentRuntime(cfg)
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    with patch.object(rt, "_call_llm", return_value=_resp("Hi.")):
        # record_usage adds cost; one call is enough to trip limit=0
        rt._conversations[sk].record_usage(100, 0.01)
        rt._run_loop(sk, "hello")
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.FAILED
    assert result.metadata.get("reason") == "cost_limit"
    rt.stop()

def test_run_loop_terminates_with_failed_on_step_limit():
    """AUDIT FIX (BUG #6). When conv.step_count > step_limit, the
    turn terminates with FAILED reason='step_limit'."""
    from agent.runtime import TurnStatus
    cfg = _make_cfg()
    cfg.step_limit = 0  # any step > 0 will trip
    rt = AgentRuntime(cfg)
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    with patch.object(rt, "_call_llm", return_value=_resp("Hi.")):
        rt._conversations[sk].step_count = 1
        rt._run_loop(sk, "hello")
    result = rt.get_last_turn_result(sk)
    assert result is not None
    assert result.status == TurnStatus.FAILED
    assert result.metadata.get("reason") == "step_limit"
    rt.stop()
```

**Test group 4: provider alias removal (2 tests)**

```python
def test_runtime_no_longer_exposes_call_provider_aliases():
    """_call_openai, _call_minimax, _call_anthropic are no longer
    attributes of agent.runtime (removed in Edit I)."""
    import agent.runtime
    for name in ("_call_openai", "_call_minimax", "_call_anthropic"):
        assert not hasattr(agent.runtime, name), (
            f"agent.runtime.{name} should be removed (Edit I)"
        )

def test_runtime_no_longer_exposes_stream_provider_aliases():
    """_stream_*_events and _PROVIDER_STREAMERS are no longer attributes
    of agent.runtime (removed in Edit J/K)."""
    import agent.runtime
    for name in (
        "_stream_openai_events", "_stream_minimax_events",
        "_stream_anthropic_events", "_PROVIDER_STREAMERS",
    ):
        assert not hasattr(agent.runtime, name), (
            f"agent.runtime.{name} should be removed (Edit J/K)"
        )
```

**Test group 5: callback protocol imports (1 test)**

```python
def test_callbacks_module_exports_protocols():
    """agent.callbacks exports the 9 callback protocols + AgentRuntimeCallbacks
    alias."""
    from agent.callbacks import (
        OnTextDelta, OnToolCallStart, OnToolCallResult,
        OnToolCallApprovalNeeded, OnResponseComplete, OnTokenUsage,
        OnTokenBreakdown, OnError, OnEnforcementStatus,
        AgentRuntimeCallbacks,
    )
    # All imports succeed (this test is mostly a smoke test for typos)
    for cls in (OnTextDelta, OnToolCallStart, OnToolCallResult,
                OnToolCallApprovalNeeded, OnResponseComplete, OnTokenUsage,
                OnTokenBreakdown, OnError, OnEnforcementStatus):
        assert hasattr(cls, "__call__")  # all are callable protocols
```

**Test group 6: AUDIT FIX (BUG #4) — turn-token rotation in `send_message` (1 test)**

> The spec's main edit for BUG #4 is in `_run_loop` Edit F (key
> state by `(sk, tk)`) and `_terminate_turn` Edit C (stale-token
> rejection). The remaining piece is that `send_message` must
> ROTATE `_turn_tokens[sk]` on every call, so the next turn's
> token differs from the previous turn's. This test pins the
> rotation behavior.

```python
def test_send_message_rotates_turn_token():
    """AUDIT FIX (BUG #4). Two consecutive send_message calls for
    the same session_key must produce two distinct turn_tokens in
    _turn_tokens, so the second turn's state is not co-mingled
    with the first's stale terminal result."""
    rt = AgentRuntime(_make_cfg())
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")
    with patch.object(rt, "_call_llm", return_value=_resp("Hello.")):
        rt._run_loop(sk, "first")
    token_after_first = rt._turn_tokens.get(sk)
    assert token_after_first is not None
    with patch.object(rt, "_call_llm", return_value=_resp("Hello again.")):
        rt._run_loop(sk, "second")
    token_after_second = rt._turn_tokens.get(sk)
    assert token_after_second is not None
    assert token_after_second is not token_after_first, (
        "send_message must rotate _turn_tokens[sk] so a new turn's "
        "state is not confused with a prior turn's terminal result"
    )
    rt.stop()
```

**Total new tests: 18** (3 + 8 + 4 + 2 + 1 + 2 + 1 + 1 = 22, but the
module-exports test is a smoke test, so 21 functional tests;
the additional 3 from groups 3a/3b/3c cover the audit-found gaps).

> **Note on test counts vs. the §4 file change table.** The previous
> draft estimated 12-15 new tests. The audit's gap analysis added 6
> more (3a, 3b, 3c, 6) to cover the previously-uncovered terminal
> paths. The expected count is now 18-21 functional tests.

---

## 3. Data Flow

This is a structural refactor; the data flow through the agent loop is preserved. The change is **which function dispatches the terminal callback** (was: 5+ call sites in `_run_loop`; now: one call site in `_terminate_turn`).

### 3.1 Before (current behavior)

```
[Background thread]
run_loop(session_key, text, turn_token)
  │
  ├─ add_user_message(text)
  │
  ├─ while iteration < max:
  │   ├─ check _cancel_requested / _cancelled
  │   │    └─ _dispatch(on_error, "Cancelled", _turn_token=...) ←── ad-hoc #1
  │   │       return
  │   ├─ _call_llm(...) → response
  │   ├─ extract text + tool_calls
  │   ├─ if no tool calls:
  │   │    ├─ if empty content:
  │   │    │    └─ _dispatch(on_error, error_text, _turn_token=...) ←── ad-hoc #2
  │   │    │       _auto_save(...)
  │   │    │       return
  │   │    └─ else:
  │   │         └─ _dispatch(on_response_complete, text, _turn_token=...) ←── ad-hoc #3
  │   │            _auto_save(...)
  │   │            return
  │   └─ else (tool calls):
  │        └─ for each tool call:
  │             ├─ _dispatch_approval
  │             ├─ execute tool
  │             └─ _dispatch(on_tool_call_result, ...)
  │
  ├─ max iterations reached:
  │    └─ _dispatch(on_error, "Max...", _turn_token=...) ←── ad-hoc #4
  │       _auto_save(...)
  │
  └─ except Exception:
       └─ _auto_save(...)
          _dispatch(on_error, e, _turn_token=...) ←── ad-hoc #5

[Main thread]
on_response_complete(sk, text) → handler._do_response_complete(...)
on_error(sk, msg) → handler._do_error(...)
```

### 3.2 After (this spec)

```
[Background thread]
run_loop(session_key, text, turn_token)
  │
  ├─ _turn_state[sk] = RUNNING
  ├─ add_user_message(text)
  │
  ├─ while iteration < max:
  │   ├─ check _cancel_requested / _cancelled
  │   │    └─ _terminate_turn(CANCELLED)  ──── single chokepoint
  │   │       return
  │   ├─ _turn_state[sk] = STREAMING
  │   ├─ _call_llm(...) → response
  │   ├─ extract text + tool_calls
  │   ├─ if no tool calls:
  │   │    ├─ if empty content:
  │   │    │    └─ _terminate_turn(FAILED, reason="empty_content")
  │   │    │       return
  │   │    └─ else:
  │   │         └─ _terminate_turn(COMPLETED)
  │   │            return
  │   └─ else (tool calls):
  │        └─ for each tool call:
  │             ├─ _dispatch_approval
  │             ├─ execute tool
  │             └─ _dispatch(on_tool_call_result, ...)
  │
  ├─ max iterations reached:
  │    └─ _terminate_turn(FAILED, reason="max_iterations")
  │
  └─ except Exception:
       └─ _terminate_turn(FAILED, reason="exception")

[Single terminal function]
_terminate_turn(result)
  │
  ├─ validate status is terminal (else log+return)
  ├─ check no prev terminal state (else log+return — dedup)
  ├─ _turn_state[sk] = result.status
  ├─ _turn_results[sk] = result
  ├─ if COMPLETED: _dispatch(on_response_complete, text, _turn_token=...)
  │  else:         _dispatch(on_error, error, _turn_token=...)
  ├─ if should_persist: _auto_save(sk, conv)  (COMPLETED/FAILED always, CANCELLED if metadata.persist)
  └─ if FAILED/CANCELLED: _cleanup_tool_history(sk)

[Main thread]
on_response_complete(sk, text) → handler._do_response_complete(...)
on_error(sk, msg) → handler._do_error(...)
```

**Net change:** 5 ad-hoc terminal blocks → 1 function. The handler-side behavior is preserved (the handler's idempotency in `_completed_turns` from Phase 1 deferred-race-fixes handles any cross-thread dispatches).

---

## 4. File Change Summary

> **AUDIT FIX (BUG #14).** The previous draft listed `docs/ARCHITECTURE.md`
> with 0 lines added / 0 lines removed and "no new section required."
> That is wrong (see §8). The new public module `agent/callbacks.py` and
> the removal of `_call_*` / `_stream_*_events` / `_PROVIDER_STREAMERS`
> from the public surface are documentation changes.

| File | Change type | Lines added | Lines removed | Risk |
|---|---|---|---|---|
| `agent/callbacks.py` (NEW) | New module | 140 | 0 | Low (typed Protocols, no runtime behavior) |
| `agent/runtime.py` | State machine + protocol types + provider alias removal + `_check_and_stop_on_limit` refactor | ~220 | ~30 | Medium (5 ad-hoc paths → 1 function; the cancel() path has subtle thread interaction; the new `(sk, tk)` keying and `_state_lock` are load-bearing for correctness) |
| `tests/test_agent_runtime.py` | New tests + create_autospec fixes + alias-migration | ~450 | ~50 | Low (test-only changes; the alias-migration touches 9 test methods that were using the removed aliases) |
| `scripts/audit_streaming_scenarios.py` | 9 `patch("agent.runtime._PROVIDER_STREAMERS", ...)` sites rewritten to `patch.object(OpenAIProvider, "stream", ...)` | ~10 | ~10 | Low (scripts only run manually) |
| `scripts/audit_attack_scenarios.py` | 5 `_PROVIDER_STREAMERS` references rewritten to use `get_provider` | ~5 | ~5 | Low |
| `agent/llm/streaming.py` | 3 docstring references to removed aliases updated | 0 | 0 | None (docstring-only) |
| `utils/provider_test.py` | 1 docstring reference to removed alias updated | 0 | 0 | None (docstring-only) |
| `docs/ARCHITECTURE.md` | §3.21.1 new subsection (Agent Callback Protocols); §3.21 update (turn state machine, public surface); docstring-only changes | ~80 | ~10 | None (docs) |

**Total: ~905 lines added, ~105 lines removed.** Runtime net change:
**+190 lines** (mostly the new `TurnStatus`/`TurnResult` dataclass,
the `_state_lock` + `_turn_tokens` + `(sk, tk)` keying in `_terminate_turn`,
the audit-driven `cancel()` rotation logic, and the audit-driven
refactor of `_check_and_stop_on_limit` to a pure predicate).

After this spec, `agent/runtime.py` will be approximately **2395 lines**
(2205 + 220 from new state machine + locking + audit-driven additions,
−30 from alias removal). Verified against baseline
`wc -l agent/runtime.py` = 2205 at spec authoring (2026-07-31).

**Risk level per file:**
- `agent/callbacks.py` (NEW): Low. Typed Protocols don't change runtime behavior. The protocols describe the existing contract; they don't enforce it at runtime (no `runtime_checkable`).
- `agent/runtime.py`: Medium. The `cancel()` interaction is the highest-risk change (two calls to `_terminate_turn` for the same turn — the dedup handles it, but the test must verify the behavior). The mid-stream-error-with-content path (D.3) changes behavior intentionally (was: fall-through; now: terminate). The `(sk, tk)` keying and `_state_lock` are load-bearing — a mistake here is a data-race / wrong-state bug. The `_check_and_stop_on_limit` refactor changes its contract (was: side-effecting predicate; now: pure predicate); the two call sites must be updated together.
- `tests/test_agent_runtime.py`: Low. Test-only changes. The 3 `create_autospec` fixes may surface other latent contract drift in the existing test suite (a good thing — those latent drifts will become explicit test failures instead of silent drift).
- `scripts/audit_*.py`: Low. The audit scripts are dev-only tools; runtime tests do not depend on them.

---

## 5. Implementation Order

Each step has a verification gate before moving on. The implementer MUST run the verification at each step and paste the output.

### Step 1: Create `agent/callbacks.py`

1. Write the file per §2.1.
2. Verify: `python3 -c "from agent.callbacks import OnTextDelta, OnToolCallResult, OnError; print('imports OK')"`
3. Verify: `python3 -m pytest tests/test_agent_runtime.py -q -k "test_callbacks_module_exports_protocols"` → 1/1 pass (or skip if test doesn't exist yet — created in Step 5)

### Step 2: Add `TurnStatus` + `TurnResult` + `_terminate_turn` to `agent/runtime.py`

> **AUDIT FIX (BUG #3, #4).** Step 2 is split into 2a (state machine
> scaffolding) and 2b (terminal paths). State machine scaffolding must
> be in place before any `_terminate_turn` callsite is added.

**Step 2a — State machine scaffolding:**
1. Apply Edit A (add `TurnStatus` enum + `TurnResult` dataclass + imports).
2. Apply Edit B (add `_state_lock`, `_turn_tokens`, `_turn_state[(sk, tk)]`,
   `_turn_results[(sk, tk)]` to `__init__`).
3. Apply Edit C (add `_terminate_turn` method, returns `TurnResult | None`).
4. Apply Edit E (add `get_last_turn_result` + `get_turn_state` accessors,
   both reading under `_state_lock`).
5. Apply Edit F (initialize `RUNNING` and register `_turn_tokens[sk] = tk`
   at the very top of `_run_loop`, BEFORE the `if conv is None` and
   prompt-build-failure checks — see BUG #2 fix).
6. Verify: `python3 -m py_compile agent/runtime.py && echo COMPILE_OK`
7. Verify: `python3 -c "from agent.runtime import TurnStatus, TurnResult; print(TurnStatus.COMPLETED)"`
8. Verify: `grep -n "_terminate_turn\|TurnStatus\|TurnResult\|_state_lock" agent/runtime.py | head -30` shows the additions.
9. Run the new state-machine tests: `python3 -m pytest tests/test_agent_runtime.py -q -k "turn_status or turn_result or terminate_turn or rejects_stale_token or persistence_uses_separate_session_keys or cancelled_with_persist_metadata_saves"` → 11/11 pass (groups 1+2).

**Step 2b — Terminal path routing:**
1. Apply Edit G (transition to `STREAMING` before first LLM call, under
   `_state_lock` and keying by `(sk, tk)`).
2. Apply Edit D.1 (cancellation paths — both `_cancel_requested` and
   `_cancelled` checks).
3. Apply Edit D.2 (empty content error).
4. Apply Edit D.3 (mid-stream error with content — MUST include the
   explicit `return` after `_terminate_turn` per BUG #5).
5. Apply Edit D.4 (text-only success — uses the new pure-predicate
   `_check_and_stop_on_limit`).
6. Apply Edit D.5 (max iterations).
7. Apply Edit D.6 (top-level exception).
8. Apply Edit D.7 (cancel() method — uses `_turn_tokens[sk]` for
   the dispatch token, per BUG #13).
9. Apply Edit Q (refactor `_check_and_stop_on_limit` to a pure
   predicate — required by D.4 and the post-tool-execution check).
10. Apply Edit R (limit placeholder + `_terminate_turn` in the
    post-tool-execution branch).
11. Verify: `python3 -m py_compile agent/runtime.py && echo COMPILE_OK`
12. Run new state transition tests: `python3 -m pytest tests/test_agent_runtime.py -q -k "run_loop_starts_in_running or run_loop_transitions_to_streaming or run_loop_terminates_with_failed or run_loop_terminates_with_cancelled or run_loop_terminates_with_failed_on_no_conversation or run_loop_terminates_with_failed_on_prompt_build_failure or run_loop_terminates_with_failed_on_stream_error_with_content or run_loop_terminates_with_failed_on_cost_limit or run_loop_terminates_with_failed_on_step_limit or send_message_rotates_turn_token"` → 10/10 pass (groups 3+3a+3b+3c+6).
13. Run existing TestToolLoop + TestApproval + TestLocalAgentDrawerEmissions: `python3 -m pytest tests/test_agent_runtime.py -q -k "TestToolLoop or TestApproval or TestLocalAgentDrawerEmissions"` → all currently-passing tests still pass; the 3-4 previously-failing tests (`_turn_token` + 3-arg lambdas) still fail (we fix them in Step 5).

### Step 3: Refactor `_run_loop` to use `_terminate_turn`

1. Apply Edit F (initialize RUNNING at start of `_run_loop`).
2. Apply Edit G (transition to STREAMING before first LLM call).
3. Apply Edit D.1 (cancellation paths).
4. Apply Edit D.2 (empty content error).
5. Apply Edit D.3 (mid-stream error with content — note behavior change).
6. Apply Edit D.4 (text-only success).
7. Apply Edit D.5 (max iterations).
8. Apply Edit D.6 (top-level exception).
9. Apply Edit D.7 (cancel() method).
10. Verify: `python3 -m py_compile agent/runtime.py && echo COMPILE_OK`
11. Run new state transition tests: `python3 -m pytest tests/test_agent_runtime.py -q -k "run_loop_starts_in_running or run_loop_transitions_to_streaming or run_loop_terminates_with_failed or run_loop_terminates_with_cancelled"` → 4/4 pass.
12. Run existing TestToolLoop + TestApproval + TestLocalAgentDrawerEmissions: `python3 -m pytest tests/test_agent_runtime.py -q -k "TestToolLoop or TestApproval or TestLocalAgentDrawerEmissions"` → all 15 currently-passing tests still pass; the 3-4 previously-failing tests (turn_token + 3-arg lambdas) still fail (we fix them in Step 5).

### Step 4: Remove provider alias debt

> **AUDIT FIX (BUG #1, #8).** The previous draft of this step asserted
> that Edits I, J, K alone would leave the repo with zero external
> consumers. The audit proved this false (12+ external consumers in
> `tests/` and `scripts/`). The corrected plan migrates the consumers
> in the same step.

1. Apply Edit I (delete `_call_*` aliases; migrate `_PROVIDER_CALLERS`
   values to direct provider lookups per Edit K).
2. Apply Edit J (delete `_stream_*_events` aliases + `_PROVIDER_STREAMERS`).
3. Apply Edit K (update `__all__` + `_PROVIDER_CALLERS` + `_RESPONSE_FORMAT`
   derivation — see §2.3 Edit K).
4. Apply Edit P (update docstring/comment references in
   `agent/llm/streaming.py` and `utils/provider_test.py` — 3 sites).
5. Apply Edit N (migrate `scripts/audit_streaming_scenarios.py` and
   `scripts/audit_attack_scenarios.py` — 14 sites).
6. Apply Edit O (migrate `tests/test_agent_runtime.py` `_stream_*_events`
   and `_call_*` imports — 9 test methods).
7. Run Edit L (grep sweep for production usage). Expected: 0 matches
   outside `tests/generate_synthetic_conversations.py` (a name collision
   in a local function — not a runtime import).
8. Run Edit M (grep sweep for `_call_*` aliases). Expected: 0 matches
   outside `tests/generate_synthetic_conversations.py`.
9. Verify: `python3 -m py_compile agent/runtime.py && echo COMPILE_OK`
10. Run alias removal tests: `python3 -m pytest tests/test_agent_runtime.py -q -k "test_runtime_no_longer_exposes_call_provider_aliases or test_runtime_no_longer_exposes_stream_provider_aliases"` → 2/2 pass.
11. Run full test_agent_runtime.py: `python3 -m pytest tests/test_agent_runtime.py -q` → all green except the 3 pre-existing contract drift failures (Step 5 fixes them).

### Step 5: Fix test mocks with `create_autospec`

1. Apply Edit N (TestToolLoop::test_user_plus_assistant_in_conversation).
2. Apply Edit O (TestApproval::test_exec_without_callback_denied).
3. Apply Edit P (TestToolLoop::test_tool_call_appends_result).
4. Run `grep -n "MagicMock()\|lambda sk, name" tests/test_agent_runtime.py` — identify any additional sites that may need fixing (be thorough; not just the 3 named in the spec).
5. Run full test_agent_runtime.py: `python3 -m pytest tests/test_agent_runtime.py -q` → expect 0 failures (the 3-4 contract drift failures should now pass with proper signatures; the 2 pre-existing TestLocalAgentDrawerEmissions failures from baseline `0d63de9` may still fail — those are out of scope for this spec, see "Out of scope" below).

### Step 6: Class docstring honesty pass

1. Apply Edit H (replace class docstring).
2. Verify: `head -50 agent/runtime.py` shows the new threading model section.

### Step 7: Final verification

1. Run full test suite: `python3 -m pytest tests/ -q` (this may take 1-2 minutes).
2. Run ruff: `ruff check agent/runtime.py agent/callbacks.py tests/test_agent_runtime.py` (if configured; per ARCHITECTURE.md §8.5).
3. Run pyright: `pyright agent/runtime.py agent/callbacks.py` (if configured; per ARCHITECTURE.md §8.5).
4. Paste all outputs in the COMPLETENESS report.

---

## 6. Acceptance Criteria

The implementer MUST verify each item before declaring done. The verification command and expected output is given for each.

- [ ] `agent/callbacks.py` exists and exports all 9 callback protocols + `AgentRuntimeCallbacks` alias
  - Verify: `python3 -c "from agent.callbacks import OnTextDelta, OnToolCallStart, OnToolCallResult, OnToolCallApprovalNeeded, OnResponseComplete, OnTokenUsage, OnTokenBreakdown, OnError, OnEnforcementStatus, AgentRuntimeCallbacks; print('OK')"`
  - Expected: `OK`

- [ ] `TurnStatus` enum has exactly 5 values: RUNNING, STREAMING, COMPLETED, FAILED, CANCELLED
  - Verify: `python3 -c "from agent.runtime import TurnStatus; print({s.value for s in TurnStatus})"`
  - Expected: `{'running', 'streaming', 'completed', 'failed', 'cancelled'}`

- [ ] `TurnResult` dataclass has fields: status, session_key, turn_token, text, error, metadata
  - Verify: `python3 -c "from agent.runtime import TurnResult; import dataclasses; print([f.name for f in dataclasses.fields(TurnResult)])"`
  - Expected: `['status', 'session_key', 'turn_token', 'text', 'error', 'metadata']`

- [ ] `_terminate_turn` method exists on `AgentRuntime` and has 5 documented behaviors (validates status, dedups, dispatches, persists, cleans up)
  - Verify: `grep -n "def _terminate_turn" agent/runtime.py` shows 1 match; method body is ≥ 40 lines

- [ ] `_run_loop` has exactly 5 `_terminate_turn` call sites (cancellation, empty-content, stream-error, text-success, max-iterations, top-level-exception = 6 actually, due to 2 cancellation paths) — and ZERO ad-hoc `_dispatch(self._on_response_complete` + `_auto_save` + `return` triplets
  - Verify: `grep -c "self._terminate_turn(" agent/runtime.py` ≥ 6
  - Verify: `grep -c "self._dispatch(self._on_response_complete" agent/runtime.py` ≤ 1 (the one in `_terminate_turn`)

- [ ] Provider alias debt removed
  - Verify: `python3 -c "import agent.runtime; assert not hasattr(agent.runtime, '_call_openai'); assert not hasattr(agent.runtime, '_stream_openai_events'); assert not hasattr(agent.runtime, '_PROVIDER_STREAMERS'); print('OK')"`
  - Expected: `OK`

- [ ] All 15 new tests pass
  - Verify: `python3 -m pytest tests/test_agent_runtime.py -q -k "turn_status or turn_result or terminate_turn or run_loop_starts or run_loop_transitions or run_loop_terminates or test_runtime_no_longer_exposes or test_callbacks_module_exports" | tail -3`
  - Expected: 15/15 (or 16/16 counting the smoke test) pass

- [ ] The 3 contract-drift test failures (turn_token + 3-arg lambdas) are fixed
  - Verify: `python3 -m pytest tests/test_agent_runtime.py -q -k "test_user_plus_assistant_in_conversation or test_exec_without_callback_denied or test_tool_call_appends_result" | tail -3`
  - Expected: 3/3 pass

- [ ] Class docstring documents the threading model with explicit synchronization boundaries
  - Verify: `head -50 agent/runtime.py` shows "Threading model" section enumerating synchronized vs unsynchronized state

- [ ] `agent/persistence.py`, `agent/audit.py`, `agent/tool_middleware.py`, `agent/llm/*` are unchanged
  - Verify: `git diff --stat HEAD~1..HEAD -- agent/persistence.py agent/audit.py agent/tool_middleware.py agent/llm/` shows no changes

- [ ] No layer-boundary violations: no new imports from `ui/`, `gateway/`, or `models/` in `agent/runtime.py` or `agent/callbacks.py`
  - Verify: `grep -E "from ui\.|from gateway\.|from models\.|import ui\.|import gateway\.|import models\." agent/runtime.py agent/callbacks.py` shows 0 matches

- [ ] Pre-existing failures remain pre-existing (not caused by this spec)
  - Verify: `python3 -m pytest tests/test_agent_runtime.py -q -k "test_tool_only_turn_tool_starts_not_suppressed or test_started_turn_sessions_clears_ended_flag_on_fresh_tool_start"` shows the same 2 failures as baseline `0d63de9` (verified via /tmp worktree)

---

## 7. Edge Cases

| Case | Expected behavior | Verified by |
|---|---|---|
| User clicks /cancel during a streaming LLM call | Main thread `cancel()` dispatches `on_error("Cancelled by user")` immediately. Background thread wakes from cancel check, calls `_terminate_turn(CANCELLED)`. `_terminate_turn` sees prev=CANCELLED from cancel(), dedups (logs error, returns). Handler's existing `_completed_turns` idempotency prevents double-render. | `test_run_loop_terminates_with_cancelled_on_cancel_signal` + new test `test_terminate_turn_dedups_duplicate_cancellations` |
| LLM returns empty content + no tool calls | `_run_loop` calls `_terminate_turn(FAILED, reason="empty_content")`. Handler renders error bubble. Conversation on disk has placeholder assistant message ("[LLM returned no content...]") so the next turn doesn't repeat the call. | `test_terminate_turn_dispatches_on_error_for_failed` + existing empty-content test in TestToolLoop |
| LLM returns mid-stream error WITH non-empty content | `_run_loop` calls `_terminate_turn(FAILED, reason="stream_error_with_content")` (was: fall-through to text-success path — now: terminates). Handler renders error bubble. **Behavior change** — intentional per Debugger's audit. | new test `test_run_loop_terminates_with_failed_on_stream_error_with_content` |
| LLM returns tool calls but text content is empty (provider quirk) | `_run_loop` substitutes `"[calling tools]"` placeholder for text_content (existing code at line ~1296), then enters tool-execution loop. After tools, if next iteration returns text-only success, `_terminate_turn(COMPLETED)` is called. No regression. | existing test in TestToolLoop::test_tool_call_with_empty_content (preserved) |
| Max iterations reached | `_run_loop` calls `_terminate_turn(FAILED, reason="max_iterations")` after the while loop exhausts. Handler renders error bubble. Persists conversation with `[max tool iterations reached]` placeholder. | `test_run_loop_terminates_with_failed_on_max_iterations` |
| Tool middleware (Enforcement/StuckDetection) raises during execution | Exception propagates up to the `try/except Exception` in `_run_loop`, which calls `_terminate_turn(FAILED, reason="exception")`. Middleware errors are surfaced as turn failures, not silent passes. | existing middleware tests in `tests/test_tool_middleware.py` (preserved) |
| Conversation not found at turn start | `_run_loop` calls `_terminate_turn(FAILED, reason="no_conversation")` with metadata indicating the cause. | new test `test_run_loop_terminates_with_failed_on_no_conversation` |
| User hits /clear during a running turn | `clear_conversation` in handler refuses (existing `is_loop_active` guard from FIX-CLEAR-ASK-RACE). Turn completes normally, then /clear can succeed. | existing test in `test_agent_runtime.py::TestClearConversation` (preserved) |
| Two threads call `_terminate_turn` for the same session simultaneously | First call wins; second is logged as duplicate and ignored. Not a race because Python's GIL makes the dict set atomic, but the prev-state check is explicit for clarity. | new test `test_terminate_turn_dedups_concurrent_terminal_transitions` (use threading.Barrier to coordinate) |
| `_dispatch` raises (handler bug) | Caught by `_dispatch`'s existing `try/except: logger.exception(...)`. `_terminate_turn` does not crash; the state machine transition still happens (so subsequent terminal calls are deduped). | new test `test_terminate_continues_after_handler_raises` |
| Provider returns 200 with `base_resp.status_code != 0` (MiniMax body-level error) | Existing `_call_llm` raises; caught by `_run_loop`'s top-level `except Exception`; calls `_terminate_turn(FAILED, reason="exception")`. | existing MiniMax tests in `tests/test_llm_providers.py` (preserved) |

---

## 8. ARCHITECTURE.md Updates Required

> **AUDIT FIX (BUG #14).** The previous draft asserted that no
> `docs/ARCHITECTURE.md` update is required, claiming that the turn
> state machine is "internal to the runtime" and the `On*` Protocols
> "are not consumed externally." Both claims are wrong:
> 1. `agent/callbacks.py` is a **new public module** exporting 9
>    `Protocol` classes. Public Protocols are architectural surface
>    even if `runtime_checkable` is not used — they document the
>    runtime's callback contract and any external code that wants
>    to provide callbacks (handler implementations, test doubles,
>    third-party integrations) must satisfy these protocols.
> 2. The provider alias removal IS a code cleanup, but it's a
>    cleanup that BREAKS 12+ lines of test/script code (see §2.3
>    Edit N, O, P). The migration is in scope, but the architectural
>    fact that the public API of `agent.runtime` is shrinking (the
>    `_call_*` and `_stream_*_events` names leave the public surface)
>    is a doc change.
> 3. The runtime line count of **2205** at the draft's authoring
>    (2026-07-31) is correct (verified via `wc -l agent/runtime.py`),
>    but the previous draft's prose said "approximately 2205 lines"
>    without a verification timestamp. Implementation-time verification
>    is required (§5 step 7).

The corrected plan:

1. **Add `docs/ARCHITECTURE.md` §3.21.1 "Agent Callback Protocols"**
   (new subsection of §3.21 "Agent Runtime"). Enumerate the 9
   `On*` protocols with their signatures and the module location
   (`agent/callbacks.py`). Note that the protocols are the source of
   truth for callback contracts.

2. **Update §3.21 "Agent Runtime" to mention the turn state
   machine** as internal infrastructure. State the 5-state enum
   (`RUNNING`, `STREAMING`, `COMPLETED`, `FAILED`, `CANCELLED`)
   and the single `_terminate_turn` chokepoint. Note that
   `_terminate_turn` is internal (not part of the public API; not
   a `Protocol`).

3. **Update the public surface list in §3.21** to remove
   `_call_openai`, `_call_minimax`, `_call_anthropic`,
   `_stream_*_events`, `_PROVIDER_STREAMERS`. Add `TurnStatus`,
   `TurnResult` to the public surface (they are exported from
   `agent.runtime` via the new `__all__`).

4. **Update the `agent/callbacks.py` entry** in the project layout
   in §2.1 (if present) or add it.

These updates are in scope for this spec. The implementer should
make them in the same commit as the code changes.

**Post-implementation follow-up** (out of scope): a future spec may
add `docs/ARCHITECTURE.md §3.21.1.1` documenting the turn state
machine as a public extension point (for custom agent runtimes that
want to reuse the state machine without reimplementing it). That
work belongs in the deferred `agent/turn.py` extraction spec (§2.5),
not this one.

**Pattern tags** to add to `.crabcakes/coder-bugs.md` after implementation:

- `state-machine-terminal` — when adding a new terminal path to a turn/state machine, route it through the existing `_terminate_turn` function rather than adding a new ad-hoc dispatch site. If `_terminate_turn` doesn't fit, extend it; don't bypass it.
- `provider-alias-rot` — when extracting a dispatch mechanism (registry, switch, dict), migrate the consumers in the same commit. Preserved "for test-patch compatibility" is a 1-month smell AND a 1-line grep away from being proven to still be in use; if grep returns matches, the migration is in scope.
- `spec-drift-line-count` — when a spec states a line count or "no external consumers" claim, run the verification (`wc -l` / `grep -rn`) at draft time AND in the same session as implementation; the claim is a falsifiable assertion, not a statement of intent.
- `turn-token-identity` — when implementing a per-turn state machine, the state MUST be keyed by turn identity (e.g. `(session_key, turn_token)` tuple), not by session_key alone. Cancellation races the new turn; without identity, a stale terminal result can clobber the new turn's state.

---

## Appendix A: Why this spec doesn't extract `agent/turn.py` now

The Debugger's recommendation #1 was "Introduce a `TurnContext` / `TurnState` object." This spec implements the state machine as **internal state on `AgentRuntime`**, not as a separate `TurnContext` object. The reasoning:

1. **The state machine touches internal state** (`_conversations`, `_auto_save`, `_cleanup_tool_history`, `_dispatch`). Extracting to a separate module requires passing all of these as dependencies — net complexity unchanged, just moved.
2. **The `TurnContext` shape isn't settled yet.** The first iteration should prove the API works (15 tests, real usage for a sprint cycle) before we commit to the extracted module's surface. Premature extraction locks the API in.
3. **The handler doesn't need to know about `TurnContext`.** The handler's `_do_response_complete` and `_do_error` consume the same callback signatures as before; `TurnResult` is internal to the runtime. Making it public would expand the API surface unnecessarily.
4. **The deferred spec is small and well-scoped.** When we extract: 1 file, ~200 lines moved, 1 PR. The value of doing it later is that we have empirical evidence of the API shape from real usage.

This is consistent with the Phase 1-8 extraction pattern (context.md): extract when the extraction reduces coupling, not when it reduces line count. The state machine reduces coupling (5 sites → 1) without a new module. The future `agent/turn.py` extraction reduces coupling between the runtime and "anyone who wants to reuse the state machine" — a different, future concern.

---

## Appendix B: Pre-existing failures that this spec does NOT fix

Per the Phase 1 deferred-race-fixes verification (this session, 2026-07-31), the following tests were already failing on the baseline commit `0d63de9` BEFORE any Phase 1 work:

- `TestLocalAgentDrawerEmissions::test_tool_only_turn_tool_starts_not_suppressed`
- `TestLocalAgentDrawerEmissions::test_started_turn_sessions_clears_ended_flag_on_fresh_tool_start`

These failures are documented in the Phase 1 post-mortem and remain unfixed as of this spec's draft. They are out of scope for SPEC-RUNTIME-TERMINAL-PATH-CONSOLIDATION. If the implementer observes them in the final test run, they should:

1. Note them in the COMPLETENESS report.
2. NOT attempt to fix them in this spec (would expand scope).
3. Reference the Phase 1 deferred-race-fixes post-mortem for context.

A separate spec (e.g. `SPEC-LOCAL-DRAWER-EMISSIONS-FIX.md`) is the appropriate place to fix them.

---

**End of spec. Implementation by Supervisor's standing-order protocol: steelFramedCodeWriter prompt per Coder invocation.**
