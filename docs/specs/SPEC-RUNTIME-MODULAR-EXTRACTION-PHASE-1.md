# SPEC: Runtime Modular Extraction — Phase 1

**Feature:** Extract Tool Middleware Chain (§3.1) and LLM Provider Adapter (§3.2) from `agent/runtime.py`
**Source proposal:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md`
**Spec writer:** Steel-Framed Code Writer (no deviations)
**Status:** Draft — awaiting captain approval
**Estimated effort:** 8–11 days (two tracks, sequential within each track)
**Last updated:** 2026-07-17 — refreshed line anchors and code samples against current source (commit pending, `wc -l` = 3,297 lines; spec originally written against `39432d2` at 2,495 lines)

---

## 0. Discovery

All line numbers verified against `agent/runtime.py` at the current HEAD (2026-07-17, `wc -l` = 3,297 lines).

### Files read during discovery

| File | Lines | What I learned |
|---|---|---|
| `agent/runtime.py` | 3,297 | Monolith containing: AuditLog/AuditEntry classes (lines 80–156), cost tables and helpers (lines 162–190), 15 module-level LLM functions (lines 195–1168), _PROVIDER_CALLERS (line 423), _RESPONSE_FORMAT (line 460), SSE streaming helpers (lines 476–1164), _PROVIDER_STREAMERS (line 1155), tool call extractors (lines 1170–1310), AgentRuntime class (line 1605) with _run_loop (lines 2101–2600), _dispatch_approval (line 2601), _call_llm (line 2655), _call_llm_streaming (line 2788), _check_stuck (line 2909), _check_and_stop_on_limit (line 2962) |
| `agent/tools.py` | 1,263 | Tool implementations + `ToolResult` dataclass (line 41), `execute_tool` function (line ~1161), `is_sensitive_path` (line ~141) |
| `agent/enforcement.py` | 942 | `check()` function at line 849 — single entry point called from `_run_loop` at lines 2530–2535. Returns `EnforcementResult` with `.appended_message` and `.checks` |
| `agent/context_strategy.py` | 874 | **The template.** Protocol → Default impl → wire via constructor → telemetry dataclass → no UI imports. This spec follows the same pattern. |
| `agent/config.py` | 319 | `AgentConfig` (line 74), `LLMProviderConfig` (line 29) with `caller` field, `EnforcementConfig` (line 46) |
| `tests/test_agent_runtime.py` | 4,217 | `TestStreamingSignature` (line 1841, was 1413), `TestApproval` (line 1125), `TestStuckDetection` (line 2047), `TestStreamingUsageCapture` (line 1915) |

### Architecture decisions

1. **New modules live in `agent/` layer.** They import only from `models/`, `utils/`, and stdlib. No UI imports. (ARCHITECTURE.md §2 layering rule, confirmed in `context_strategy.py`.)

2. **Composition over inheritance.** `AgentRuntime` *holds* a `ToolMiddlewareChain` instance and an `LLMProviderRegistry` instance. It does not subclass them. (Same pattern as `self._context_strategy` at runtime.py line 1709.)

3. **Backward compatibility via re-exports.** After extraction, `agent/runtime.py` re-exports the old names (`_call_openai`, `_PROVIDER_CALLERS`, etc.) via imports from the new modules. This keeps existing test patches working. Tests that `patch("agent.runtime._call_openai", ...)` continue to work.

4. **Two tracks, shipped sequentially.** Track A (Tool Middleware) ships first because it is lower risk and higher architectural leverage. Track B (LLM Provider) ships second because streaming is riskier and benefits from Track A's test isolation.

---

## Track A: Tool Middleware Chain

### A.1 Objective

Extract the three inline policy concerns from `_run_loop`'s tool-execution block (lines 2455–2581) into a composable middleware chain:

1. **Approval gating** (lines 2460–2490) — `exec_command` + sensitive `write_file`/`edit_file` → PM approval
2. **Enforcement check** (lines 2525–2551) — post-write syntax/test/lint verification
3. **Stuck detection** (lines 2553–2562) — loop detection on tool history

### A.2 New module: `agent/tool_middleware.py`

```
agent/tool_middleware.py
```

#### A.2.1 Protocol

```python
# agent/tool_middleware.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from agent.tools import ToolResult


class ToolMiddleware(Protocol):
    """Middleware that wraps tool execution.

    Each middleware receives the tool name, args, conversation context,
    and a `next` callable. It may:
    - Short-circuit (return a ToolResult without calling `next`)
    - Modify args before calling `next`
    - Modify the result after calling `next`
    - Raise on error

    Middlewares are composed in onion order: the first-registered wraps all others.
    """

    def __call__(
        self,
        tool_name: str,
        args: dict,
        context: "ToolContext",
        next: Callable[[], ToolResult],
    ) -> ToolResult: ...


@dataclass
class ToolContext:
    """Per-tool-call context shared across the middleware chain.

    Fields:
        session_key: Conversation session key (e.g. "special:coder").
        project_path: Absolute path to the project root (sandbox base).
        iteration: Current tool-loop iteration (0-indexed).
        bypass_approval: When True, the approval middleware skips PM dispatch
            (runtime already obtained approval before entering the chain).
        audit_log: Optional AuditLog instance for recording tool executions.
        user_id: User identity for audit trail (from AgentConfig.user_id).
        enforcement_config: The EnforcementConfig from AgentConfig, or None
            if enforcement is globally disabled.
        si_enforcement: Per-conversation self-improvement enforcement flag
            (None means default True).
    """
    session_key: str
    project_path: str
    iteration: int
    bypass_approval: bool = False
    audit_log: Any = None         # AuditLog instance or None
    user_id: str = ""
    enforcement_config: Any = None  # EnforcementConfig or None
    si_enforcement: bool | None = None
```

#### A.2.2 Concrete middleware classes

Three classes, each wrapping one existing concern:

```python
class ApprovalMiddleware:
    """Short-circuits execution when PM approval is required and not obtained.

    Triggers on:
    - exec_command (always)
    - write_file/edit_file when is_sensitive_path(args["path"]) returns True

    When bypass_approval is True in context, skips entirely (runtime already
    obtained approval via _dispatch_approval before entering the chain).

    When the approval callback returns False or None (timeout), returns a
    ToolResult with success=False, error="...denied...". Does NOT call `next`.
    """

    def __init__(
        self,
        approval_dispatcher: Callable[[str, str, dict], bool | None],
        is_sensitive_path_fn: Callable[[str], bool],
    ):
        """
        Args:
            approval_dispatcher: The runtime's _dispatch_approval method.
                Called as approval_dispatcher(session_key, tool_name, args).
                Returns True (approved), False (denied), or None (timeout).
            is_sensitive_path_fn: agent.tools.is_sensitive_path
        """
        self._dispatch = approval_dispatcher
        self._is_sensitive = is_sensitive_path_fn

    def __call__(self, tool_name, args, ctx, next):
        if ctx.bypass_approval:
            return next()

        needs_approval = False
        if tool_name == "exec_command":
            needs_approval = True
        elif tool_name in ("write_file", "edit_file"):
            path_arg = args.get("path", "")
            needs_approval = self._is_sensitive(path_arg)

        if not needs_approval:
            return next()

        approved = self._dispatch(ctx.session_key, tool_name, args)
        if approved is False or approved is None:
            msg = f"{tool_name} requires PM approval — request denied or timed out"
            if tool_name in ("write_file", "edit_file"):
                msg = (
                    f"{tool_name} blocked: {args.get('path', '')} is a sensitive path\n"
                    "PM approval denied or timed out."
                )
            return ToolResult(success=False, error=msg, output=msg)

        return next()


class EnforcementMiddleware:
    """Post-execution enforcement check for write tools.

    Calls agent.enforcement.check() after write_file/edit_file succeeds.
    Appends the enforcement result to the ToolResult output and dispatches
    per-check status callbacks.

    No-ops for non-write tools and failed writes.
    """

    def __init__(
        self,
        enforcement_check_fn: Callable,        # agent.enforcement.check
        on_status: Callable[[str, str, dict], None] | None = None,
    ):
        """
        Args:
            enforcement_check_fn: agent.enforcement.check
            on_status: Callback for each check result. Called as
                on_status(session_key, tool_name, {"tier":..., "file":..., "passed":..., "detail":...}).
                May be None (no status dispatch).
        """
        self._check = enforcement_check_fn
        self._on_status = on_status

    def __call__(self, tool_name, args, ctx, next):
        result = next()

        # Only run on successful writes
        if tool_name not in ("write_file", "edit_file"):
            return result
        if not result.success:
            return result

        # Check global + per-agent enforcement flags
        global_enabled = (
            ctx.enforcement_config is not None and ctx.enforcement_config.enabled
        )
        agent_enabled = ctx.si_enforcement if ctx.si_enforcement is not None else True
        if not (global_enabled and agent_enabled):
            return result

        import dataclasses as _dc
        enf_result = self._check(
            tool_name, args, result,
            ctx.project_path,
            ctx.enforcement_config,
        )
        if enf_result.appended_message:
            result = _dc.replace(
                result,
                output=(result.output or "") + "\n" + enf_result.appended_message,
            )
            if self._on_status:
                for check in enf_result.checks:
                    self._on_status(ctx.session_key, tool_name, {
                        "tier": check.tier,
                        "file": check.file,
                        "passed": check.passed,
                        "detail": check.detail,
                    })

        return result


class StuckDetectionMiddleware:
    """Records tool calls and detects loops.

    Delegates to the runtime's _check_stuck method (existing logic, no change).
    If a stuck message is produced, stores it in the provided pending-messages
    dict for the next LLM call to pick up.
    """

    def __init__(
        self,
        stuck_check_fn: Callable[[str, str, dict, int], str | None],
        pending_messages: dict[str, list[str]],
    ):
        """
        Args:
            stuck_check_fn: The runtime's _check_stuck method.
                Called as stuck_check_fn(session_key, tool_name, args, iteration).
                Returns an intervention message or None.
            pending_messages: The runtime's _pending_stuck_messages dict.
                Stuck messages are appended here for the next LLM call.
        """
        self._check_stuck = stuck_check_fn
        self._pending = pending_messages

    def __call__(self, tool_name, args, ctx, next):
        result = next()
        stuck_msg = self._check_stuck(ctx.session_key, tool_name, args, ctx.iteration)
        if stuck_msg:
            self._pending.setdefault(ctx.session_key, []).append(stuck_msg)
        return result


class ToolMiddlewareChain:
    """Composes middleware into a single callable.

    Order: ApprovalMiddleware → EnforcementMiddleware → StuckDetectionMiddleware

    The executor (innermost callable) is `execute_tool` from agent.tools.
    """

    def __init__(self, middlewares: list[ToolMiddleware]):
        self._middlewares = middlewares

    def run(
        self,
        tool_name: str,
        args: dict,
        ctx: ToolContext,
        executor: Callable[[], ToolResult],
    ) -> ToolResult:
        """Execute the middleware chain.

        Middlewares wrap each other in registration order:
        middlewares[0] wraps middlewares[1] wraps ... wraps executor.
        """
        def make_next(index: int) -> Callable[[], ToolResult]:
            if index >= len(self._middlewares):
                return executor
            mw = self._middlewares[index]
            return lambda: mw(tool_name, args, ctx, make_next(index + 1))

        return make_next(0)()
```

#### A.2.3 Wiring in `AgentRuntime.__init__`

Replace the inline approval + enforcement + stuck blocks in `_run_loop` with a chain constructed in `__init__` (currently lines 1635–1714 of runtime.py):

```python
# In AgentRuntime.__init__, after self._audit_log = AuditLog() (line 1703):
from agent.tool_middleware import (
    ApprovalMiddleware,
    EnforcementMiddleware,
    StuckDetectionMiddleware,
    ToolMiddlewareChain,
)
from agent.tools import is_sensitive_path
from agent.enforcement import check as _enf_check

self._tool_chain = ToolMiddlewareChain([
    ApprovalMiddleware(
        approval_dispatcher=self._dispatch_approval,
        is_sensitive_path_fn=is_sensitive_path,
    ),
    EnforcementMiddleware(
        enforcement_check_fn=_enf_check,
        on_status=self._dispatch_enforcement_status,
    ),
    StuckDetectionMiddleware(
        stuck_check_fn=self._check_stuck,
        pending_messages=self._pending_stuck_messages,
    ),
])
```

Where `_dispatch_enforcement_status` is a new thin method (pattern: current dispatch at line 2541–2549):

```python
def _dispatch_enforcement_status(self, session_key: str, tool_name: str, status: dict) -> None:
    """Dispatch enforcement status to the on_enforcement_status callback."""
    self._dispatch(self._on_enforcement_status, session_key, tool_name, status)
```

#### A.2.4 Call-site change in `_run_loop`

The entire tool-execution block (lines 2455–2581) is replaced with:

```python
# Determine bypass_approval BEFORE entering the chain.
# The runtime needs to call _dispatch_approval for exec_command and sensitive
# writes. If approved, bypass_approval=True so the ApprovalMiddleware skips.
# This preserves the current behavior: approval fires before tool_call_start
# dispatch, so the PM sees the approval card first.
bypass_approval = False
if tool_name == "exec_command":
    approved = self._dispatch_approval(session_key, tool_name, args)
    if approved is False or approved is None:
        tc.mark_failed("exec_command requires PM approval — request denied or timed out")
        conv.add_tool_result(call_id, tc.result or "denied")
        self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied", False)
        self._audit_log.record(tool_name, args, approved=False,
                               user=getattr(self._config, "user_id", ""),
                               result="denied")
        continue
    bypass_approval = True
elif tool_name in ("write_file", "edit_file"):
    path_arg = args.get("path", "")
    if agent_tools_module.is_sensitive_path(path_arg):
        approved = self._dispatch_approval(session_key, tool_name, args)
        if approved is False or approved is None:
            tc.mark_failed(
                f"{tool_name} blocked: {path_arg} is a sensitive path\n"
                "PM approval denied or timed out."
            )
            conv.add_tool_result(call_id, tc.result or "denied")
            self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied", False)
            self._audit_log.record(tool_name, args, approved=False,
                                   user=getattr(self._config, "user_id", ""),
                                   result="denied")
            continue
        bypass_approval = True

# Tool call start — fires AFTER approval
self._dispatch(self._on_tool_call_start, session_key, tool_name, args)
tc.mark_executing()

# Execute through middleware chain
from agent.tool_middleware import ToolContext
workspace = _resolve_session_workspace(conv.project_path, session_key)
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
        approval_callback=(lambda *a: True) if bypass_approval else None,
        allowed_tools=conv.allowed_tools,  # current code passes this at line 2519
    ),
)

# Record results (audit log already recorded inside chain if audit_log was provided)
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
```

**IMPORTANT UPDATE (2026-07-17):** The current `_on_tool_call_result` signature now takes **4 parameters**: `(session_key, tool_name, result_text, success_bool)`. The spec's sample above reflects this (`False` for denied, `result.success` for completed). See runtime.py lines 2466, 2486, 2567 for the current dispatch calls.

**Revised approach:** The approval logic stays OUTSIDE the chain (in `_run_loop`) because it must fire BEFORE `tool_call_start` dispatch, and the chain wraps the *execution* phase (which starts at `tool_call_start`). The chain handles enforcement and stuck detection (which fire AFTER execution). The approval check is a *pre-condition gate* that happens before the chain is entered.

**This is the correct decomposition:**

```
_run_loop per-tool-call flow:
  1. Pre-condition: approval gate (inline in _run_loop — unchanged)
  2. Dispatch: on_tool_call_start, tc.mark_executing()
  3. Execute through chain:
     a. EnforcementMiddleware (wraps executor, post-checks)
     b. StuckDetectionMiddleware (wraps executor, post-checks)
     c. executor = execute_tool(...)
  4. Post-condition: record results, audit log
```

So `ApprovalMiddleware` is **removed** from the chain. The approval logic stays inline in `_run_loop` because it has a temporal ordering constraint (must fire before `on_tool_call_start`). The chain wraps only the execution phase.

**Final chain order:** `[EnforcementMiddleware, StuckDetectionMiddleware]`

#### A.2.5 Audit log recording

The audit log recording currently happens in `_run_loop` at lines 2571–2578. **It stays in `_run_loop`** — not moved into the chain. The `ToolContext.audit_log` field is provided for middleware that *needs to read* audit state, but the primary record call stays in the loop. This avoids double-recording.

### A.3 Files modified

| File | Change |
|---|---|
| `agent/tool_middleware.py` | **NEW** — Protocol, ToolContext, EnforcementMiddleware, StuckDetectionMiddleware, ToolMiddlewareChain |
| `agent/runtime.py` | Import chain, construct in `__init__`, replace inline enforcement+stuck blocks in `_run_loop` with `self._tool_chain.run(...)` call, add `_dispatch_enforcement_status` method |

### A.4 Lines freed from runtime.py

~45 lines (the enforcement block at 2525–2551 + the stuck detection block at 2553–2562). The approval block stays inline (temporal ordering constraint).

### A.5 Tests

New file: `tests/test_tool_middleware.py`

Minimum test cases (30%+ sad path):

**EnforcementMiddleware tests:**
1. `test_enforcement_passes_through_non_write_tool` — `list_files` call, no enforcement check fired
2. `test_enforcement_passes_through_failed_write` — `write_file` returns `success=False`, no enforcement check
3. `test_enforcement_appends_message_on_success` — `write_file` succeeds, enforcement returns message, result.output includes it
4. `test_enforcement_skips_when_globally_disabled` — `enforcement_config.enabled=False`, no check
5. `test_enforcement_skips_when_agent_disabled` — `si_enforcement=False`, no check
6. `test_enforcement_dispatches_status_per_check` — verifies `on_status` called for each check
7. `test_enforcement_no_status_callback_is_safe` — `on_status=None`, no crash

**StuckDetectionMiddleware tests:**
8. `test_stuck_no_message_when_not_stuck` — `_check_stuck` returns None, no pending message
9. `test_stuck_appends_message_when_stuck` — `_check_stuck` returns message, message in pending dict
10. `test_stuck_uses_correct_session_key` — message keyed to correct session

**ToolMiddlewareChain tests:**
11. `test_chain_executes_in_order` — three middleware that wrap each other, verify call order via side-effect list
12. `test_chain_short_circuit_does_not_reach_executor` — middleware returns early, executor never called
13. `test_chain_executor_result_passes_through` — executor result returned unchanged when no middleware modifies it

**Integration tests (exercise the wired chain through _run_loop):**
14. `test_enforcement_fires_on_write_in_run_loop` — end-to-end: model calls `write_file`, enforcement check fires, result includes enforcement output
15. `test_stuck_detection_fires_in_run_loop` — end-to-end: model calls same tool 3x, stuck message injected

**Sad-path tests:**
16. `test_enforcement_check_raises_does_not_crash_loop` — enforcement.check raises, middleware must catch and log (not crash)
17. `test_stuck_check_raises_does_not_crash_loop` — stuck check raises, middleware must catch and log
18. `test_chain_with_empty_middleware_list` — empty chain, executor called directly

### A.6 Risk and mitigation

| Risk | Mitigation |
|---|---|
| Enforcement ordering change (was inline, now wrapped) | The chain preserves ordering: enforcement fires after `execute_tool` returns, same as before. Verified by test #14. |
| Stuck detection ordering change | Stuck detection fires after enforcement (it wraps outside enforcement in the chain). In the old code, stuck detection fired after enforcement too (line 2554 > line 2530). Same order. |
| Audit log double-recording | Audit log recording stays in `_run_loop`, not in middleware. No double-record. |
| `_dispatch_approval` temporal ordering | Approval stays inline in `_run_loop`, NOT in the chain. The chain starts after approval is resolved. |

### A.7 Backward compatibility

No re-exports needed — the middleware classes are new modules, and the old inline code is simply removed from `_run_loop`. No external code imported the inline blocks.

---

## Track B: LLM Provider Adapter

### B.1 Objective

Extract all 15 module-level LLM functions (lines 195–1168), the cost table (lines 162–164), `_model_id` (line 175), `_cost_for_model` (line 185), `_RESPONSE_FORMAT` (line 460), and all SSE/streaming/SSL helpers (lines 476–1164) into a new `agent/llm/` package.

### B.2 New package: `agent/llm/`

```
agent/llm/
    __init__.py          — public API: get_provider(), LLMResponse, SSEEvent
    protocol.py          — LLMProvider Protocol + LLMResponse dataclass
    registry.py          — provider registry: get_provider(id) -> LLMProvider
    openai_provider.py   — OpenAIProvider (handles openai, openrouter, zai)
    minimax_provider.py  — MiniMaxProvider (OpenAI-compatible wire protocol)
    anthropic_provider.py— AnthropicProvider
    streaming.py         — SSE helpers: sse_lines, parse_sse_line, parse_sse_delta, urlopen_with_ssl_retry
    extractors.py        — extract_tool_calls, extract_text_content, extract_usage
    convert.py           — convert_messages_for_anthropic, convert_tools_for_anthropic
    cost.py              — _model_id, _cost_for_model, PROVIDER_COSTS
```

### B.3 Module specifications

#### B.3.1 `agent/llm/protocol.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider.

    Fields:
        text: The text content of the response (may be empty when tool_calls present).
        tool_calls: List of (call_id, tool_name, arguments_dict) tuples.
        usage: (prompt_tokens, completion_tokens) tuple.
        raw: The raw provider response dict (for debugging and provider-specific access).
    """
    text: str = ""
    tool_calls: list[tuple[str, str, dict]] = field(default_factory=list)
    usage: tuple[int, int] = (0, 0)
    raw: dict = field(default_factory=dict)


# Re-export SSEEvent for streaming consumers
from agent.runtime import SSEEvent


class LLMProvider(Protocol):
    """One class per provider wire protocol.

    A single class may serve multiple registry entries (e.g., OpenAIProvider
    serves "openai", "openrouter", "zai" — all OpenAI-compatible).
    """

    @property
    def provider_id(self) -> str:
        """Stable identifier (e.g., "openai", "minimax", "anthropic")."""
        ...

    @property
    def response_format(self) -> str:
        """Response format family: "openai" or "anthropic".
        Determines how extractors parse the response.
        """
        ...

    def call(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        timeout: float,
        x_title: str = "",
    ) -> dict:
        """Make a blocking (non-streaming) LLM API call.

        Returns the raw provider response dict. Raises RuntimeError on error.
        """
        ...

    def stream(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        timeout: float,
        x_title: str = "",
    ) -> Iterator:
        """Yield SSEEvent instances from a streaming LLM call.

        Events: text_delta, tool_call_delta, usage, done.
        """
        ...
```

**Important:** The `call` and `stream` method signatures are **identical** to the existing `_call_openai` / `_stream_openai_events` parameter lists. This is not a coincidence — the existing functions already have the right interface. The provider class wraps them as methods, passing `self` only for the provider_id/response_format properties.

#### B.3.2 `agent/llm/openai_provider.py`

```python
class OpenAIProvider:
    """Handles OpenAI, OpenRouter, and ZAI APIs (all OpenAI-compatible).

    The provider_id is set at construction so a single class serves multiple
    registry entries. The wire protocol is identical; only credentials and
    base_url differ (both passed by the caller).
    """

    def __init__(self, provider_id: str = "openai"):
        self._id = provider_id

    @property
    def provider_id(self) -> str:
        return self._id

    @property
    def response_format(self) -> str:
        return "openai"

    def call(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _call_openai function (runtime.py line 195), verbatim.
        ...

    def stream(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _stream_openai_events function (runtime.py line 863), verbatim.
        # Yields SSEEvent instances.
        ...
```

**MiniMax is NOT a separate class.** MiniMax uses the OpenAI wire protocol for streaming (`_parse_sse_delta` is shared) but has a different endpoint path (`/text/chatcompletion_v2` vs `/chat/completions`) and a body-level error check. So MiniMax gets its own class:

#### B.3.3 `agent/llm/minimax_provider.py`

```python
class MiniMaxProvider:
    """MiniMax ChatCompletion v2 API.

    Uses the OpenAI-compatible message format but has a different endpoint
    path (/text/chatcompletion_v2), body-level error envelopes, and a different
    finish-detection mechanism (finish_reason in-stream, not [DONE]).
    """

    @property
    def provider_id(self) -> str:
        return "minimax"

    @property
    def response_format(self) -> str:
        return "openai"  # response shape is OpenAI-compatible

    def call(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _call_minimax function (runtime.py line 238), verbatim.
        ...

    def stream(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _stream_minimax_events function (runtime.py line 941), verbatim.
        ...
```

#### B.3.4 `agent/llm/anthropic_provider.py`

```python
class AnthropicProvider:
    """Anthropic Messages API.

    Requires message/tool format conversion (system message extraction,
    content-block format). Uses x-api-key header, not Bearer auth.
    """

    @property
    def provider_id(self) -> str:
        return "anthropic"

    @property
    def response_format(self) -> str:
        return "anthropic"

    def call(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _call_anthropic function (runtime.py line 363), verbatim.
        # Includes system message extraction + _convert_messages_for_anthropic.
        ...

    def stream(self, base_url, api_key, model, messages, tools, timeout, x_title=""):
        # Body is the existing _stream_anthropic_events function (runtime.py line 1052), verbatim.
        ...
```

#### B.3.5 `agent/llm/streaming.py`

Moves these functions verbatim from `runtime.py`:

| Function | Current location (runtime.py) | New location |
|---|---|---|
| `SSEEvent` namedtuple | line 476 | `agent/llm/streaming.py` (also re-exported from `agent/llm/__init__.py`) |
| `_sse_lines` → `sse_lines` | line 480 | `agent/llm/streaming.py` |
| `_parse_sse_line` → `parse_sse_line` | line 487 | `agent/llm/streaming.py` |
| `_parse_sse_delta` → `parse_sse_delta` | line 511 | `agent/llm/streaming.py` |
| `_urlopen_with_ssl_retry` → `urlopen_with_ssl_retry` | line 703 | `agent/llm/streaming.py` |
| `_RETRYABLE_SSL_ERRORS` | line 557 | `agent/llm/streaming.py` |
| `_RETRYABLE_OSERROR_TYPES` | line 577 | `agent/llm/streaming.py` |
| `_MAX_SSL_RETRIES`, `_SSL_RETRY_BASE_MS` | lines 582–583 | `agent/llm/streaming.py` |
| `_is_retryable_ssl_error` | line 586 | `agent/llm/streaming.py` |
| `_friendly_error_message` | line 657 | `agent/llm/streaming.py` |
| `_stream_with_ssl_retry` | line 770 | `agent/llm/streaming.py` |

**Naming:** Leading underscores dropped since these are now public within the `agent.llm` package. The `agent/runtime.py` re-exports keep the old underscore-prefixed names as aliases for backward compatibility.

#### B.3.6 `agent/llm/extractors.py`

Moves these functions verbatim:

| Function | Current location (runtime.py) |
|---|---|
| `_extract_tool_calls` → `extract_tool_calls` | line 1170 |
| `_extract_text_content` → `extract_text_content` | line 1224 |
| `_extract_usage` → `extract_usage` | line 1277 |
| `_is_empty_content` | line 1245 (stays in runtime.py — used by text-content placeholder logic at lines 2386, 2423, not a pure extractor) |

The `_RESPONSE_FORMAT` dict (runtime.py line 460) is replaced by each provider's `.response_format` property. The extractors take an optional `response_format: str` parameter instead of looking up `_RESPONSE_FORMAT`:

```python
def extract_tool_calls(response: dict, response_format: str = "openai") -> list[tuple[str, str, dict]]:
    ...

def extract_text_content(response: dict, response_format: str = "openai") -> str:
    ...

def extract_usage(response: dict, response_format: str = "openai") -> tuple[int, int]:
    ...
```

**Migration:** Callers that currently pass `provider` (a string like `"minimax"`) now pass `response_format` (a string like `"openai"` or `"anthropic"`). The values change from provider names to format family names. The caller resolves this via `provider.response_format`.

#### B.3.7 `agent/llm/convert.py`

Moves these functions verbatim:

| Function | Current location (runtime.py) |
|---|---|
| `_convert_messages_for_anthropic` → `convert_messages_for_anthropic` | line 286 |
| `_convert_tools_for_anthropic` → `convert_tools_for_anthropic` | line 338 |

These are called only by `AnthropicProvider`, so they could live inside `anthropic_provider.py`. But keeping them in `convert.py` makes them testable in isolation and available to future Anthropic-compatible providers.

#### B.3.8 `agent/llm/cost.py`

Moves `_model_id`, `_cost_for_model`, and all cost tables verbatim:

| Symbol | Current location (runtime.py) |
|---|---|
| `_OPENAI_COST` | line 162 |
| `_MINIMAX_COST` | line 163 |
| `_ANTHROPIC_COST` | line 164 |
| `_PROVIDER_COSTS` | line 166 |
| `_model_id` → `model_id` | line 175 |
| `_cost_for_model` → `cost_for_model` | line 185 |

#### B.3.9 `agent/llm/registry.py`

```python
from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider

_REGISTRY: dict[str, object] = {
    "openai": OpenAIProvider("openai"),
    "openrouter": OpenAIProvider("openrouter"),
    "zai": OpenAIProvider("zai"),
    "minimax": MiniMaxProvider(),
    "anthropic": AnthropicProvider(),
}


def get_provider(provider_id: str):
    """Return the LLMProvider instance for the given provider ID.

    Raises KeyError if the provider is not registered.
    """
    if provider_id not in _REGISTRY:
        raise KeyError(
            f"Unknown LLM provider: {provider_id!r}. "
            f"Registered: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[provider_id]


def list_providers() -> list[str]:
    """Return sorted list of registered provider IDs."""
    return sorted(_REGISTRY.keys())
```

**Key insight:** The old `_PROVIDER_CALLERS` dispatch dict (line 423) mapped provider names to *functions*. The registry maps provider names to *objects* with both `.call()` and `.stream()` methods. This collapses two dispatch dicts (`_PROVIDER_CALLERS` + `_PROVIDER_STREAMERS` at line 1155) into one registry.

#### B.3.10 `agent/llm/__init__.py`

```python
"""LLM provider abstraction layer.

Public API:
    get_provider(id) -> LLMProvider
    SSEEvent — namedtuple for streaming events
    LLMResponse — normalized response dataclass
"""
from agent.llm.protocol import LLMProvider, LLMResponse
from agent.llm.registry import get_provider, list_providers
from agent.llm.streaming import SSEEvent

__all__ = [
    "get_provider",
    "list_providers",
    "LLMProvider",
    "LLMResponse",
    "SSEEvent",
]
```

### B.4 Wiring in `AgentRuntime`

#### B.4.1 `_call_llm` method changes (runtime.py line 2655)

The `_call_llm` method currently resolves the caller via `_PROVIDER_CALLERS[caller_key]` at line 2762:

```python
# Before (runtime.py lines 2762–2765):
caller = _PROVIDER_CALLERS.get(caller_key)
if caller is None:
    raise ValueError(...)
return caller(
    base_url=provider_cfg.base_url,
    api_key=effective_api_key,
    model=model,
    messages=messages,
    tools=tools if tools else None,
    timeout=float(self._config.tool_timeout_seconds),
    x_title=x_title,
)

# After:
from agent.llm.registry import get_provider

provider = get_provider(caller_key)
return provider.call(
    base_url=provider_cfg.base_url,
    api_key=effective_api_key,
    model=model,
    messages=messages,
    tools=tools if tools else None,
    timeout=float(self._config.tool_timeout_seconds),
    x_title=x_title,
)
```

#### B.4.2 `_call_llm_streaming` method changes (runtime.py line 2788)

```python
# Before (runtime.py lines 2815–2820):
streamer = _PROVIDER_STREAMERS.get(caller_key)
if streamer is None:
    raise ValueError(
        f"No streaming caller for caller_key={caller_key!r} "
        f"(model={model!r}). Check provider's 'caller' field in Settings → Providers."
    )

for ev in _stream_with_ssl_retry(streamer, ...):
    ...

# After:
provider = get_provider(caller_key)
for ev in _stream_with_ssl_retry(provider.stream, ...):
    ...
```

#### B.4.3 Extractor call-site changes

The three extractor functions are called in `_run_loop` at runtime.py lines 2252–2256:

```python
# Before:
loop_provider = model.split("/")[0] if "/" in model else model
text_content = _extract_text_content(response, loop_provider)
tool_calls_raw = _extract_tool_calls(response, loop_provider)
prompt_tok, comp_tok = _extract_usage(response, loop_provider)
cost = _cost_for_model(conv.model, prompt_tok, comp_tok)

# After:
from agent.llm.extractors import extract_tool_calls, extract_text_content, extract_usage
from agent.llm.registry import get_provider
from agent.llm.cost import cost_for_model

loop_provider = model.split("/")[0] if "/" in model else model
provider = get_provider(loop_provider)
fmt = provider.response_format
text_content = extract_text_content(response, fmt)
tool_calls_raw = extract_tool_calls(response, fmt)
prompt_tok, comp_tok = extract_usage(response, fmt)
cost = cost_for_model(conv.model, prompt_tok, comp_tok)
```

#### B.4.4 Cost function call-site changes

The `_call_for_summary` method (runtime.py line 3229) also uses `_extract_text_content` — this must be updated from the re-exports:

```python
# Before (runtime.py line 3295):
from agent.runtime import _extract_text_content
text = _extract_text_content(response_dict, provider_name)

# After:
from agent.llm.extractors import extract_text_content
text = extract_text_content(response_dict, fmt)
```

### B.5 Backward compatibility re-exports in `agent/runtime.py`

After extraction, add these re-exports near the top of `runtime.py` (after existing imports, before line 42):

```python
# ── Backward-compatibility re-exports (provider extraction) ────────────────────
# These symbols were moved to agent/llm/ but tests patch them via agent.runtime.
# Re-export so existing test patches (patch("agent.runtime._call_openai", ...)) still work.
from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider
from agent.llm.streaming import (
    SSEEvent,
    sse_lines as _sse_lines,
    parse_sse_line as _parse_sse_line,
    parse_sse_delta as _parse_sse_delta,
    urlopen_with_ssl_retry as _urlopen_with_ssl_retry,
    stream_with_ssl_retry as _stream_with_ssl_retry,
    is_retryable_ssl_error as _is_retryable_ssl_error,
    friendly_error_message as _friendly_error_message,
    RETRYABLE_SSL_ERRORS as _RETRYABLE_SSL_ERRORS,
    RETRYABLE_OSERROR_TYPES as _RETRYABLE_OSERROR_TYPES,
    MAX_SSL_RETRIES as _MAX_SSL_RETRIES,
    SSL_RETRY_BASE_MS as _SSL_RETRY_BASE_MS,
)
from agent.llm.extractors import (
    extract_tool_calls as _extract_tool_calls,
    extract_text_content as _extract_text_content,
    extract_usage as _extract_usage,
)
from agent.llm.convert import (
    convert_messages_for_anthropic as _convert_messages_for_anthropic,
    convert_tools_for_anthropic as _convert_tools_for_anthropic,
)
from agent.llm.cost import (
    model_id as _model_id,
    cost_for_model as _cost_for_model,
    PROVIDER_COSTS as _PROVIDER_COSTS,
    OPENAI_COST as _OPENAI_COST,
    MINIMAX_COST as _MINIMAX_COST,
    ANTHROPIC_COST as _ANTHROPIC_COST,
)

# Provider call/stream functions — wrapped as module-level functions for patch compatibility
_call_openai = OpenAIProvider("openai").call
_call_minimax = MiniMaxProvider().call
_call_anthropic = AnthropicProvider().call
_stream_openai_events = OpenAIProvider("openai").stream
_stream_minimax_events = MiniMaxProvider().stream
_stream_anthropic_events = AnthropicProvider().stream

# Dispatch dicts (for code that references them directly)
_PROVIDER_CALLERS = {
    "openai": _call_openai,
    "minimax": _call_minimax,
    "anthropic": _call_anthropic,
    "openrouter": OpenAIProvider("openrouter").call,
    "zai": OpenAIProvider("zai").call,
}
_PROVIDER_STREAMERS = {
    "openai": _stream_openai_events,
    "minimax": _stream_minimax_events,
    "anthropic": _stream_anthropic_events,
    "openrouter": OpenAIProvider("openrouter").stream,
    "zai": OpenAIProvider("zai").stream,
}
```

**Note:** The `_RESPONSE_FORMAT` dict (line 460) is NOT re-exported — it is replaced by `provider.response_format`. Any code that referenced `_RESPONSE_FORMAT` must be updated to use `get_provider(provider_name).response_format`. This is verified by `grep -rn "_RESPONSE_FORMAT" agent/runtime.py` returning zero matches after migration.

### B.6 StreamingCallKwargs and TestStreamingSignature

The `StreamingCallKwargs` TypedDict (runtime.py line 42) and `TestStreamingSignature` regression test (test_agent_runtime.py line 1841, previously 1413) must continue to pass unchanged.

**What changes:** The `_call_llm_streaming` method signature does NOT change. It still takes the same parameters. The method body changes to use `get_provider(caller_key).stream(...)` instead of `_PROVIDER_STREAMERS[caller_key](...)`.

**What stays:** `TestStreamingSignature` checks that the method signature matches the TypedDict. Since the signature is unchanged, the test passes without modification.

### B.7 Files modified

| File | Change |
|---|---|
| `agent/llm/__init__.py` | **NEW** — public API exports |
| `agent/llm/protocol.py` | **NEW** — LLMProvider Protocol, LLMResponse dataclass |
| `agent/llm/registry.py` | **NEW** — provider registry |
| `agent/llm/openai_provider.py` | **NEW** — OpenAIProvider (call + stream) |
| `agent/llm/minimax_provider.py` | **NEW** — MiniMaxProvider (call + stream) |
| `agent/llm/anthropic_provider.py` | **NEW** — AnthropicProvider (call + stream) |
| `agent/llm/streaming.py` | **NEW** — SSE helpers + SSL retry |
| `agent/llm/extractors.py` | **NEW** — response extractors |
| `agent/llm/convert.py` | **NEW** — Anthropic message/tool converters |
| `agent/llm/cost.py` | **NEW** — cost table + model_id + cost_for_model |
| `agent/runtime.py` | Delete ~970 lines of module-level functions (lines 162–1168 cost + LLM callers + SSE + streaming + extractors + converters). Add re-exports. Update `_call_llm` (line 2655), `_call_llm_streaming` (line 2788), `_call_for_summary` (line 3229), and extractor call sites at lines 2252–2256. |

### B.8 Lines freed from runtime.py

~970 lines (all module-level LLM functions: cost tables at 162–190, callers at 195–422, SSE helpers at 476–1164, streaming at 863–1168, extractors at 1170–1310, converters at 286–362, _RESPONSE_FORMAT at 460).

After Track A + Track B: `runtime.py` shrinks from 3,297 → ~2,280 lines (a 31% reduction, back below the 2,500-line threshold).

### B.9 Tests

New files:

- `tests/test_llm_providers.py` — unit tests for each provider class
- `tests/test_llm_streaming.py` — SSE parsing tests (moved from test_agent_runtime.py patterns)
- `tests/test_llm_extractors.py` — response extraction tests
- `tests/test_llm_cost.py` — cost calculation tests
- `tests/test_llm_registry.py` — registry lookup tests

Minimum test cases:

**OpenAIProvider tests:**
1. `test_openai_call_builds_correct_request` — verify endpoint, headers, payload
2. `test_openai_call_includes_tools_when_provided` — tool_choice=auto set
3. `test_openai_call_omits_tools_when_none` — no tools key in payload
4. `test_openai_call_raises_on_http_error` — HTTPError → RuntimeError
5. `test_openai_call_with_x_title_sets_headers` — X-Title and HTTP-Referer headers
6. `test_openai_stream_yields_text_delta` — SSE text content forwarded
7. `test_openai_stream_yields_tool_call_delta` — SSE tool call fragments forwarded
8. `test_openai_stream_yields_usage_at_end` — usage chunk captured
9. `test_openai_stream_yields_done_on_bracket_done` — [DONE] → done event
10. `test_openai_stream_handles_empty_response` — no choices, no crash

**MiniMaxProvider tests:**
11. `test_minimax_call_detects_body_level_error` — HTTP 200 with base_resp.status_code != 0 → RuntimeError
12. `test_minimax_call_success_returns_response` — normal response returned
13. `test_minimax_stream_detects_body_level_error_first_line` — non-SSE JSON error on first line → RuntimeError
14. `test_minimax_stream_finish_reason_signals_done` — finish_reason="stop" → done event
15. `test_minimax_stream_usage_captured_before_done` — usage event before done event

**AnthropicProvider tests:**
16. `test_anthropic_call_extracts_system_message` — system message moved to payload["system"]
17. `test_anthropic_call_strips_duplicate_system` — only first system message extracted
18. `test_anthropic_call_converts_tools` — tools use name/description/input_schema
19. `test_anthropic_stream_content_block_start_tool_use` — tool_use id forwarded
20. `test_anthropic_stream_text_delta_forwarded` — text_delta events forwarded
21. `test_anthropic_stream_message_delta_usage` — usage in message_delta captured
22. `test_anthropic_stream_message_stop_signals_done` — message_stop → done event

**Extractor tests:**
23. `test_extract_tool_calls_openai_format` — choices[0].message.tool_calls parsed
24. `test_extract_tool_calls_anthropic_format` — content blocks with tool_use parsed
25. `test_extract_tool_calls_empty_choices` — no choices → empty list
26. `test_extract_text_content_openai` — message.content returned
27. `test_extract_text_content_anthropic` — text blocks joined
28. `test_extract_usage_openai` — prompt_tokens/completion_tokens
29. `test_extract_usage_anthropic` — input_tokens/output_tokens
30. `test_extract_usage_missing` — no usage key → (0, 0)

**Cost tests:**
31. `test_model_id_strips_provider_prefix` — "minimax/MiniMax-M2.7" → "MiniMax-M2.7"
32. `test_model_id_no_prefix_returns_input` — "gpt-4o" → "gpt-4o"
33. `test_cost_for_model_openai` — known cost calculation
34. `test_cost_for_model_unknown_provider_defaults_openai` — fallback behavior
35. `test_cost_for_model_zero_tokens` — zero cost

**Registry tests:**
36. `test_get_provider_openai` — returns OpenAIProvider
37. `test_get_provider_minimax` — returns MiniMaxProvider
38. `test_get_provider_anthropic` — returns AnthropicProvider
39. `test_get_provider_openrouter` — returns OpenAIProvider (alias)
40. `test_get_provider_unknown_raises_keyerror` — clear error message

**Streaming tests (moved patterns from test_agent_runtime.py):**
41. `test_sse_lines_strips_whitespace` — line.strip() applied
42. `test_parse_sse_line_data_prefix` — "data: {...}" → SSEEvent
43. `test_parse_sse_line_done` — "data: [DONE]" → done event
44. `test_parse_sse_line_comment` — ":comment" → None
45. `test_parse_sse_delta_text_content` — delta.content → text_delta
46. `test_parse_sse_delta_tool_call` — delta.tool_calls → tool_call_delta

**Sad-path tests:**
47. `test_parse_sse_line_malformed_json` — bad JSON → None (not crash)
48. `test_urlopen_ssl_retry_transient_error` — retryable SSL error retried
49. `test_urlopen_ssl_retry_non_retryable_raises` — non-retryable error raised immediately
50. `test_urlopen_ssl_retry_max_attempts` — exhausts retries then raises

### B.10 Risk and mitigation

| Risk | Mitigation |
|---|---|
| Streaming regression (SSE ordering, tool-call delta accumulation) | All 6 stream functions moved verbatim. `TestStreamingSignature` passes unchanged (line 1841). New `test_llm_streaming.py` provides isolated SSE tests. |
| `_RESPONSE_FORMAT` removal breaks callers | All callers updated in the same PR. Verified by `grep -rn "_RESPONSE_FORMAT" agent/` returning zero. |
| Test patches break (`patch("agent.runtime._call_openai", ...)`) | Re-exports keep old names alive. Tests patched via `_PROVIDER_CALLERS` dict still work because the dict is re-exported. |
| `SSEEvent` import from `agent.runtime` breaks | `SSEEvent` re-exported from `agent.runtime` via `from agent.llm.streaming import SSEEvent`. |
| Provider body-level error (MiniMax HTTP 200) silently swallowed | Test #11 reproduces the exact payload from production. |

---

## C. Implementation Order

### Phase 1: Track A — Tool Middleware (3–4 days)

1. **Day 1:** Create `agent/tool_middleware.py` with Protocol, ToolContext, and all middleware classes. Write unit tests (test cases 1–13). Run tests in isolation.
2. **Day 2:** Wire `ToolMiddlewareChain` into `AgentRuntime.__init__`. Replace enforcement + stuck detection inline blocks in `_run_loop` with chain call. Run integration tests (14–15).
3. **Day 3:** Sad-path tests (16–18). Run full test suite for relevant test files: `test_agent_runtime.py` (TestApproval at line 1125, TestStuckDetection at line 2047, TestPerProjectEnforcement), `test_tool_middleware.py`. Fix regressions.
4. **Day 4:** Buffer for regression fixing. Commit.

### Phase 2: Track B — LLM Provider (5–7 days, two sub-phases)

**Phase 2a: Non-streaming extraction (3 days)**

5. **Day 5:** Create `agent/llm/` package. Move cost functions to `agent/llm/cost.py`. Move converters to `agent/llm/convert.py`. Move extractors to `agent/llm/extractors.py`. Write cost/extractor/convert unit tests (23–35). Run tests.
6. **Day 6:** Move `_call_openai` (line 195), `_call_minimax` (line 238), `_call_anthropic` (line 363) into provider classes. Create registry. Write provider `call()` tests (1–4, 11–12, 16–18). Re-export from runtime.py.
7. **Day 7:** Update `_call_llm` method (line 2655) to use registry. Update extractor call sites at lines 2252–2256 in `_run_loop`. Run `test_agent_runtime.py` TestApproval (uses `_call_llm` mock). Fix regressions. Commit Phase 2a.

**Phase 2b: Streaming extraction (3 days)**

8. **Day 8:** Move SSE helpers to `agent/llm/streaming.py` (lines 476–864). Move stream functions into provider classes: `_stream_openai_events` (line 863), `_stream_minimax_events` (line 941), `_stream_anthropic_events` (line 1052). Write streaming unit tests (5–10, 13–15, 19–22, 41–50).
9. **Day 9:** Update `_call_llm_streaming` (line 2788) to use registry. Verify `TestStreamingSignature` passes unchanged (line 1841). Run `TestStreaming`, `TestStreamingUsageCapture` (line 1915), `TestStreamAnthropicEvents`. Fix regressions.
10. **Day 10:** Delete old module-level functions from `runtime.py` (keep re-exports). Run full test suite for relevant test files. Fix regressions. Commit Phase 2b.

### Phase 3: Verification

11. **Day 11:** Final verification:
    - `wc -l agent/runtime.py` — verify under 2,400 lines
    - `grep -rn "_RESPONSE_FORMAT" agent/` — verify zero matches
    - `grep -rn "def _call_openai\|def _call_minimax\|def _call_anthropic" agent/runtime.py` — verify zero matches (moved to provider classes)
    - `grep -rn "def _stream_openai\|def _stream_minimax\|def _stream_anthropic" agent/runtime.py` — verify zero matches
    - `python3 -m pytest tests/test_agent_runtime.py tests/test_tool_middleware.py tests/test_llm_providers.py tests/test_llm_streaming.py tests/test_llm_extractors.py tests/test_llm_cost.py tests/test_llm_registry.py -q --tb=short` — all pass
    - `python3 -c "from agent.runtime import AgentRuntime, SSEEvent, StreamingCallKwargs"` — imports work

---

## D. Verification Commands

Every factual claim in this spec is verifiable. Run these commands before and after implementation:

```bash
# Line count (before / after)
wc -l agent/runtime.py
# Before: 3297. After Track A+B: ~2280

# Provider functions exist at current locations (before extraction)
grep -n "^def _call_openai\|^def _call_minimax\|^def _call_anthropic" agent/runtime.py
# Before: lines 195, 238, 363. After: zero matches.

grep -n "^def _stream_openai\|^def _stream_minimax\|^def _stream_anthropic" agent/runtime.py
# Before: lines 863, 941, 1052. After: zero matches.

# Dispatch dicts (before extraction)
grep -n "^_PROVIDER_CALLERS\|^_PROVIDER_STREAMERS\|^_RESPONSE_FORMAT" agent/runtime.py
# Before: lines 423, 1155, 460. After: only re-export lines.

# TestStreamingSignature regression test location
grep -n "class TestStreamingSignature" tests/test_agent_runtime.py
# Line 1841 (was 1413). Must pass unchanged after extraction.

# Enforcement check call site
grep -n "_enforcement_check" agent/runtime.py
# Before: line 31 (import), line 2530 (call). After: import only (call moves to middleware).

# Stuck detection call site
grep -n "_check_stuck" agent/runtime.py
# Before: line 2554 (call), line 2909 (def). After: def stays (method on AgentRuntime),
#   call moves into StuckDetectionMiddleware via function reference.

# New modules exist
ls agent/tool_middleware.py agent/llm/__init__.py agent/llm/protocol.py agent/llm/registry.py
ls agent/llm/openai_provider.py agent/llm/minimax_provider.py agent/llm/anthropic_provider.py
ls agent/llm/streaming.py agent/llm/extractors.py agent/llm/convert.py agent/llm/cost.py

# New test files exist
ls tests/test_tool_middleware.py tests/test_llm_providers.py tests/test_llm_streaming.py
ls tests/test_llm_extractors.py tests/test_llm_cost.py tests/test_llm_registry.py

# No _RESPONSE_FORMAT references remain
grep -rn "_RESPONSE_FORMAT" agent/
# After: zero matches

# Imports work
python3 -c "from agent.tool_middleware import ToolMiddlewareChain, ToolContext"
python3 -c "from agent.llm import get_provider, SSEEvent, LLMResponse"
python3 -c "from agent.llm.registry import get_provider; p = get_provider('openai'); print(p.provider_id, p.response_format)"
```

---

## E. Constraints

1. **Do NOT modify `agent/context_strategy.py`** — it is the template, not a target.
2. **Do NOT modify `agent/enforcement.py`** — it is called as-is by the middleware. Its internal structure is a separate audit.
3. **Do NOT modify `agent/tools.py`** — `ToolResult`, `execute_tool`, and `is_sensitive_path` are consumed, not changed.
4. **Do NOT modify `tests/test_agent_runtime.py`** — existing tests must pass unchanged (they use `_call_llm` mock pattern, `TestStreamingSignature` at line 1841 checks signature compatibility). If a test cannot pass without modification, STOP and flag it.
5. **Do NOT change `_call_llm_streaming`'s method signature** — `StreamingCallKwargs` TypedDict (line 42) and `TestStreamingSignature` (line 1841) enforce this.
6. **Do NOT rename `_dispatch_approval`** — it is called from inline approval logic that stays in `_run_loop`.
7. **Re-exports in `runtime.py` must keep ALL existing test patches working.** Verify with `grep -rn "patch.*agent.runtime._call\|patch.*agent.runtime._stream\|patch.*agent.runtime._PROVIDER" tests/`.
8. **Each track ships in its own commit.** Track A is one commit. Track B is two commits (2a non-streaming, 2b streaming). This enables independent revert.
9. **Approval gating stays inline in `_run_loop`.** It has a temporal ordering constraint (must fire before `on_tool_call_start` dispatch). The middleware chain starts AFTER approval is resolved. Do NOT move it into the chain.

---

## F. Completeness Checklist

When implementation is done, the builder MUST produce this block:

```
COMPLETENESS:
- [x] Track A: agent/tool_middleware.py created — evidence: ls + import check
- [x] Track A: ToolMiddlewareChain wired into AgentRuntime.__init__ — evidence: grep
- [x] Track A: Enforcement + stuck inline blocks removed from _run_loop — evidence: grep (zero matches for _enforcement_check call in _run_loop, _check_stuck call in _run_loop)
- [x] Track A: test_tool_middleware.py with 18+ test cases — evidence: pytest pass
- [x] Track A: All existing tests pass unchanged — evidence: pytest test_agent_runtime.py
- [x] Track B Phase 2a: agent/llm/ package created with 10 modules — evidence: ls
- [x] Track B Phase 2a: Non-streaming functions moved to provider classes — evidence: grep (zero matches for "def _call_openai/minimax/anthropic" in runtime.py)
- [x] Track B Phase 2a: _call_llm updated to use registry — evidence: grep "get_provider" in _call_llm body
- [x] Track B Phase 2a: Re-exports added to runtime.py — evidence: grep "from agent.llm"
- [x] Track B Phase 2a: Cost/extractor/convert/provider unit tests pass — evidence: pytest
- [x] Track B Phase 2b: Streaming functions moved to provider classes — evidence: grep (zero matches for "def _stream_openai/minimax/anthropic" in runtime.py)
- [x] Track B Phase 2b: _call_llm_streaming updated to use registry — evidence: grep "get_provider" in _call_llm_streaming body
- [x] Track B Phase 2b: TestStreamingSignature passes unchanged — evidence: pytest test_agent_runtime.py::TestStreamingSignature
- [x] Track B Phase 2b: Streaming unit tests pass — evidence: pytest test_llm_streaming.py
- [x] Phase 3: runtime.py under 2,400 lines — evidence: wc -l
- [x] Phase 3: No _RESPONSE_FORMAT references — evidence: grep -rn "_RESPONSE_FORMAT" agent/ returns zero
```

---

## G. Open Questions (resolved during implementation, not now)

1. **Should `ToolContext` carry the `Conversation` object?** Currently it carries only primitives (session_key, project_path, iteration). The conversation is accessible in `_run_loop` via `self._conversations[session_key]`. If middleware needs conv access, add it later. For now, middleware works with primitives only.
2. **Should the registry be configurable at runtime (register/unregister)?** Not needed for Phase 1. The registry is a module-level dict. If hot-registration is needed later, add `register_provider(id, provider)` to `registry.py`.
3. **Should the `LLMResponse` dataclass replace the raw dict returned by `call()`?** Not in Phase 1. The raw dict is consumed by extractors that have well-tested OpenAI/Anthropic format handling. Replacing the dict with a dataclass is a separate refactor.
4. **Should MiniMax get its own response_format value?** No — `response_format = "openai"` is correct. MiniMax returns OpenAI-format responses (`choices[0].message.tool_calls`, `usage.prompt_tokens`). The extractor logic is identical.

---

**End of specification.**