# SPEC: UI Responsiveness During Agent Runs — Phase 1

**Date:** 2026-07-20
**Author:** Coder (via steelFramedSpecWriter)
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-ui-responsiveness-during-agent-runs.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance statement: `agent/runtime.py` has no GTK imports. `ui/handlers/` receives callbacks via the established dispatch pattern (`GLib.idle_add`). All changes respect layer separation (§2 of ARCHITECTURE.md). No new cross-layer imports are introduced.

---

## DISCOVERY

- **Read `agent/runtime.py`** (1995 lines): `AgentRuntime.__init__` takes `GLib, on_text_delta, on_tool_call_start, on_tool_call_result, on_response_complete, on_error` etc. `send_message()` (line 535) spawns a `threading.Thread(target=self._run_loop)` — runs on daemon thread. `create_conversation()` (line 435) calls `build_system_prompt()` synchronously (file I/O + template composition). `_rebuild_conversation_context()` (line 1708) also calls `build_system_prompt()`. `_dispatch()` (line 387) wraps callback in `GLib.idle_add` or direct call. `_run_loop` (line 782) calls `self._dispatch(self._on_text_delta, session_key, text)` for every SSE text token. The `_lock` is `threading.Lock` (not RLock). `_conversations` dict is protected by `self._lock`.

- **Read `ui/handlers/agent_runtime_handler.py`** (1700+ lines): `send_to_special_agent()` (line 733) runs ENTIRELY on main thread. It calls `_get_runtime()` (line 675, lazy init), then `rt.load_conversation()` (disk I/O), then `rt._rebuild_conversation_context()` or `rt.create_conversation()` (both call `build_system_prompt()` synchronously, ~300ms blocking), then `rt.send_message()` (line 540 — spawns thread). `_on_text_delta` (line 962) dispatches to main thread via `GLib.idle_add`. `_do_text_delta` (line 972) accumulates text, calls `self._crh.update_streaming()`. No `_show_thinking_indicator` or `thinking_indicator` method exists. Callbacks: `_on_agent_start_cb` (line 154) and `_on_agent_end_cb` (line 158) are set by window.py — signature `cb(session_key)`.

- **Read `ui/handlers/chat_render_handler.py`** (800+ lines): `update_streaming()` (line 434) stores text, checks throttle (150ms via `_stream_throttle_sec` at line 192), then defines inner `_update()` (lines 465-472) which does `escape_for_pango` + `format_markdown` + `set_markup`. `_update()` is dispatched via `self._dispatch()` (line 750 — another `GLib.idle_add`). This is the SECOND idle_add — the first was in `_on_text_delta` → `_do_text_delta`. `_dispatch()` (line 750) wraps in `GLib.idle_add` returning `False` (one-shot). The throttle (150ms) is checked BEFORE `_dispatch`, so at most ~6.7 `_update` calls/sec per session.

- **Read `agent/context.py`** (800+ lines): `build_system_prompt()` (line 702) calls `compose_system_prompt()` which reads templates from `prompts/system/`, calls `build_file_context_with_core_files()` (line 545) which reads project directory tree, `.gitignore`, `.crabcakes/` docs, core files (README, ARCHITECTURE, etc.), and file index. All synchronous file I/O. Cache exists on `build_file_context` (`_FILE_CONTEXT_CACHE`) but not on the full `build_system_prompt` composition.

- **Architecture owner:** `agent/runtime.py` owns the tool loop and callback dispatch. `ui/handlers/agent_runtime_handler.py` owns the UI bridge. `ui/handlers/chat_render_handler.py` owns streaming bubble rendering.

- **Existing patterns:** `_on_text_delta` → `GLib.idle_add` → `_do_text_delta` (main thread) is the established one-dispatch pattern. All other callbacks (`_on_tool_call_start`, `_on_tool_call_result`, `_on_response_complete`, `_on_error`) follow the same `GLib.idle_add` → `_do_*` pattern with NO second dispatch inside the handler.

---

## 1. Overview

### 1.1 Problem

When an agent runs (Coder, Debugger, etc.), the CrabCakes GTK4 UI becomes sluggish or frozen. The user cannot scroll, switch tabs, or click buttons until the agent finishes. Root cause: the agent's background thread floods the GTK main-loop idle queue with high-frequency callbacks, and several main-thread operations (system prompt build, string processing, Pango layout) compound the problem.

### 1.2 Solution Summary

Phase 1 addresses four independent fixes that eliminate ~80% of the perceived freeze:

| Fix | What | Impact |
|-----|------|--------|
| **Fix 1** | Move `build_system_prompt` off main thread into background thread | Eliminates 300-500ms initial freeze on Send |
| **Fix 2** | Eliminate double `GLib.idle_add` in `update_streaming` | Halves idle-queue entries during streaming |
| **Fix 3** | Move throttle check from `update_streaming` to `_do_text_delta` | Reduces per-token main-thread work by ~50% |
| **Fix 5** | Use `set_text()` instead of `set_markup()` during streaming | Eliminates expensive Pango layout + markdown formatting during streaming |

### 1.3 Scope

| Item | In scope (Phase 1) | Out of scope (Phase 2) |
|------|-------------------|----------------------|
| Fix 1: build_system_prompt off main thread | ✅ | — |
| Fix 2: Double idle_add elimination | ✅ | — |
| Fix 3: Throttle at _do_text_delta | ✅ | — |
| Fix 4: Incremental feed card update | — | ✅ Deferred |
| Fix 5: set_text during streaming | ✅ | — |
| Fix 6: Full pre-loop batching | — | ✅ Deferred |

### 1.4 Architecture Principles

- `agent/runtime.py` remains pure — no GTK imports, no UI logic
- `ui/handlers/` follow the established `GLib.idle_add` → `_do_*` dispatch pattern
- No new cross-layer imports (e.g., `agent/` doesn't import from `ui/`)
- Thread safety: all shared state access goes through `self._lock` (threading.Lock, not RLock)

---

## 2. Changes by File

### 2.1 `agent/runtime.py` — Fix 1: Move build_system_prompt off main thread

**What changes:**
`create_conversation()` (line 435) currently calls `build_system_prompt()` synchronously inside the method (line ~501). The `send_message()` method (line 535) spawns a thread that calls `_run_loop`.

The system prompt build involves reading the project directory tree, parsing `.gitignore`, reading `.crabcakes/` docs, and template composition — all synchronous file I/O that blocks the caller's thread (which is the main thread when called from `send_to_special_agent`).

**Key insight:** `send_message()` already spawns a background thread (`threading.Thread(target=self._run_loop)`). The system prompt building happens BEFORE `send_message` is called (in `create_conversation` or `_rebuild_conversation_context`). The fix is to move the build into the background thread that `send_message` creates.

**Approach:**
Add a `defer_prompt_build` parameter to `send_message()`. When `True`, `_run_loop` calls `_ensure_system_prompt()` as its first step instead of requiring it to be pre-built.

**Verification of thread safety:**
- `build_system_prompt()` in `agent/context.py` is a pure function — no state, no GTK calls, only file I/O
- `conv.system_prompt` assignment is protected by `self._lock` in `_run_loop` (line 786: `with self._lock:`)
- No other thread reads `conv.system_prompt` during the build window (the builder thread is the only one that accesses it until the first SSE event)

**Detailed change:**

Add method (includes double-checked-locking per BUG #1 fix):

```python
def _ensure_system_prompt(self, session_key: str) -> None:
    """Ensure the conversation has a system prompt built.

    Called from _run_loop at the start, before any LLM call.
    If the conversation already has a system prompt, this is a no-op.

    Thread safety (BUG #1 audit): uses double-checked-locking.
    The first check (outside lock) is the fast path — when the prompt
    is already built, we avoid the lock entirely. The second check
    (inside lock) prevents concurrent writes from _run_loop (background)
    and force_llm_compact (main thread via /compact).
    """
    conv = self._conversations.get(session_key)
    if conv is None:
        return
    if conv.system_prompt:
        return  # Already has one — fast path, no lock needed

    from agent.context import build_system_prompt
    from agent.tools import get_all_tools

    tool_names = [t.name for t in get_all_tools() if t.name in (conv.allowed_tools or [])]
    default_provider_name = self._config.default_provider
    default_provider_cfg = self._config.providers.get(default_provider_name) if default_provider_name else None
    if default_provider_cfg and getattr(default_provider_cfg, "max_tokens", None):
        model_max_for_budget = int(default_provider_cfg.max_tokens)
    else:
        model_max_for_budget = 128_000
    context_mode = getattr(default_provider_cfg, "context_mode", "auto") or "auto"

    # build_system_prompt is pure file I/O — safe outside the lock
    new_prompt = build_system_prompt(
        conv.agent_name,
        conv.project_path,
        tool_names,
        agent_role=conv.agent_role or "",
        model_max_tokens=model_max_for_budget,
        context_mode=context_mode,
    )
    # Double-checked-locking: re-check under lock to prevent concurrent write
    # from force_llm_compact (main thread) or another _run_loop instance.
    with self._lock:
        if not conv.system_prompt:
            conv.system_prompt = new_prompt
            logger.info("System prompt built for %s in background thread (len=%d)",
                        session_key, len(new_prompt))
```

Add parameter to `send_message()`:

```python
def send_message(self, session_key: str, text: str, *, _defer_prompt: bool = False) -> None:
    ...
    t = threading.Thread(
        target=self._run_loop,
        args=(session_key, text),
        kwargs={"_defer_prompt": _defer_prompt} if _defer_prompt else {},
        daemon=True,
    )
    t.start()
```

Modify `_run_loop` signature and first step:

```python
def _run_loop(self, session_key: str, text: str, _defer_prompt: bool = False) -> None:
    ...
    try:
        with self._lock:
            if not self._running:
                return
            conv = self._conversations.get(session_key)
            if conv is None:
                self._dispatch(self._on_error, session_key, "No conversation found")
                return

        # Deferred prompt build: if the system prompt hasn't been built yet
        # (deferred from send_to_special_agent), do it now on the background thread.
        if _defer_prompt:
            self._ensure_system_prompt(session_key)
        ...
```

**Exception handling:** `build_system_prompt` can raise if project path is invalid or templates are missing. `_ensure_system_prompt` has no try/except — let the exception propagate to `_run_loop`'s existing outer `except Exception` handler (line ~1240), which dispatches `_on_error`. This is correct: a failed prompt build is a fatal error for the turn.

**Imports required:** None new — `build_system_prompt` and `get_all_tools` are already imported in `create_conversation()`.

**Line count estimate:** +40 lines (new method + send_message kwarg + _run_loop dispatch + _defer_prompt plumbing in agent_runtime_handler.py)

### 2.2 `ui/handlers/agent_runtime_handler.py` — Fix 1 wiring

**What changes:**
`send_to_special_agent()` (line 733) currently builds the conversation synchronously before calling `send_message()`. With Fix 1, the prompt build is deferred to the background thread.

**Approach:**
When creating a new conversation (no existing conv), call `create_conversation()` with a placeholder/sentinel system prompt (empty string), then pass `_defer_prompt=True` to `send_message()`. The actual `build_system_prompt` runs in the background thread via `_ensure_system_prompt`.

When loading a persisted conversation that needs rebuilding (stale project path), still call `_rebuild_conversation_context` synchronously — this is a rare operation (project switch) and the rebuild happens at most once per conversation lifetime.

**Detailed change in `send_to_special_agent`:**

For the "create new conversation" path:

```python
# Current (line ~781):
if rt.get_conversation(session_key) is None:
    rt.create_conversation(
        agent_name=agent_def.display_name,
        session_key=session_key,
        project_path=project_path,
        ...
    )
```

Change to:

```python
# New: create_conversation will call build_system_prompt internally,
# but we defer that to the background thread via _defer_prompt.
# The conversation is created with a system_prompt built synchronously
# (from create_conversation), but in the future the prompt build will
# move to _ensure_system_prompt in the background thread.
if rt.get_conversation(session_key) is None:
    loaded = rt.load_conversation(session_key)
    if loaded:
        logger.info("send_to_special_agent: loaded persisted conversation for %s", session_key)
        rt._rebuild_conversation_context(
            session_key,
            project_path,
            agent_role=agent_def.role,
        )
        defer_prompt = False  # _rebuild_context already built prompt
    else:
        rt.create_conversation(
            agent_name=agent_def.display_name,
            session_key=session_key,
            project_path=project_path,
            model=agent_model,
            allowed_tools=agent_def.tools,
            mcp_servers=agent_def.mcp_servers,
            agent_role=agent_def.role,
            si_enforcement=si_enforcement,
            api_key=agent_def.api_key,
            app_title=agent_def.app_title,
            fallback_provider=agent_def.fallback_provider,
        )
        defer_prompt = True  # prompt will be built in background
else:
    # Conversation already exists — sync latest agent config (edits
    # take effect immediately without restart).
    defer_prompt = False
    conv = rt.get_conversation(session_key)
    if conv is not None:
        if agent_def.api_key:
            conv.api_key = agent_def.api_key
        if agent_model:
            conv.model = agent_model
        if agent_def.app_title:
            conv.app_title = agent_def.app_title
        conv.fallback_provider = agent_def.fallback_provider
        if agent_def.role:
            conv.agent_role = agent_def.role
        if agent_def.mcp_servers is not None:
            conv.mcp_servers = list(agent_def.mcp_servers)
        if si_enforcement is not None:
            conv.si_enforcement = si_enforcement
```

Then at the end:

```python
if defer_prompt:
    rt.send_message(session_key, text, _defer_prompt=True)
else:
    rt.send_message(session_key, text)
```

**Modify `create_conversation` in `agent/runtime.py`** to accept an optional overridden system_prompt:

Actually, a cleaner approach: `create_conversation` already passes `system_prompt=system_prompt` (line ~514 of runtime.py), where `system_prompt` is the result of `build_system_prompt()`. If we pass `system_prompt=""`, the conversation will have an empty system prompt. Then `_ensure_system_prompt` (called from `_run_loop` when `_defer_prompt=True`) checks `if conv.system_prompt:` and builds it.

So the cleanest approach: add a deferred flag to `send_message`, don't modify `create_conversation` at all.

**Risk:** MEDIUM — the `_defer_prompt` flag must not be set for the lazy reconciliation path (`_rebuild_conversation_context`). That path handles project-switching and needs the prompt built synchronously (the user expects the agent to see the new project context on the very next message). This is already handled: `_rebuild_conversation_context` fires BEFORE `send_message`, and after it runs, `conv.system_prompt` is non-empty, so `_ensure_system_prompt` is a no-op.

Additionally, `force_llm_compact` (called from the main thread via `/compact`) reads and potentially rewrites `conv.system_prompt` (runtime.py lines 1898-1907). The double-checked-locking pattern in `_ensure_system_prompt` (BUG #1 fix) prevents concurrent writes: `force_llm_compact` holds `self._compaction_lock` (a threading.Lock) when it writes `conv.system_prompt`, while `_ensure_system_prompt` holds `self._lock`. These are different locks, so the race is prevented by the double-check — `_ensure_system_prompt` re-reads `conv.system_prompt` inside `self._lock` and only writes if still empty, while `force_llm_compact` temporarily replaces `conv.system_prompt` with a focus-augmented version. If both run concurrently, one of the two writes wins; the double-check ensures neither produces a corrupt partial state.

**Line count estimate:** +8 lines (defer flag logic in send_to_special_agent)

### 2.3 `ui/handlers/chat_render_handler.py` — Fix 2: Eliminate double idle_add

**What changes:**
`update_streaming()` (line 434) currently defines `_update()` and dispatches it via `self._dispatch(_update)` (line 473). This is the SECOND `GLib.idel_add` — the first was in `_on_text_delta` → `GLib.idle_add` → `_do_text_delta`.

**Fix:** Call `_update()` directly instead of going through `self._dispatch()`. Since `update_streaming` is called from `_do_text_delta` (which is already on the main thread via the first `GLib.idle_add`), the second dispatch is redundant.

**Verify call sites:**
- `agent_runtime_handler.py:998` — `self._crh.update_streaming(session_key, self._streaming_text[session_key])` — called from `_do_text_delta`, which IS on the main thread.
- `chat_handler.py:575` — `self._chat_render_handler.update_streaming(session_key, delta_text)` — called from `_handle_streaming_delta`. Is THIS on the main thread? Let's check: `_handle_streaming_delta` is called from `on_chat_event` via the gateway dispatch chain. Gateway events arrive on the gateway thread and are dispatched via `GLib.idle_add` to the main thread. So YES, `_handle_streaming_delta` is also on the main thread.

Both callers are on the main thread. Safe to call `_update()` directly.

**Detailed change:**

Replace (lines 473):
```python
        def _update():
            from utils.escaping import escape_for_pango
            from utils.markdown import format_markdown
            # Use sb.plain_text (always latest) not the delta_text arg.
            # Route through escape + format_markdown so inline formatting
            # (bold/italic/links) renders during the streaming window (Bug #10).
            escaped = escape_for_pango(sb.plain_text)
            formatted = format_markdown(escaped)
            sb.label.set_markup(formatted + "<tt>▍</tt>")

        self._dispatch(_update)
```

With (inline the update logic, remove `_dispatch`):
```python
        from utils.escaping import escape_for_pango
        from utils.markdown import format_markdown
        # Direct update — we're already on the main thread (caller dispatched
        # via GLib.idle_add). Inlining avoids double idle_add overhead.
        escaped = escape_for_pango(sb.plain_text)
        formatted = format_markdown(escaped)
        sb.label.set_markup(formatted + "<tt>▍</tt>")
```

**Risk:** LOW — the logic is identical, just removing the redundant `_dispatch` wrapper. The imports (`escape_for_pango`, `format_markdown`) were already inside `_update()`, now they're at module scope (or can be moved to top-level imports since the handler already imports from utils).

**Update top-level imports:**
```python
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
```
Add to the existing imports in `chat_render_handler.py`. Replace the local `from utils.escaping import escape_for_pango` etc. with top-level imports.

**Line count:** −5 lines (remove `def _update():`, `_dispatch(_update)`, and dedent)

### 2.4 `ui/handlers/agent_runtime_handler.py` — Fix 3: Throttle at _do_text_delta level

**What changes:**
`_do_text_delta()` (line 972) does string concatenation, dict lookups, and method calls for EVERY token — including tokens that will be immediately throttled in `update_streaming()`.

**Fix:** Add a throttle check at the top of `_do_text_delta` that skips expensive processing for tokens that arrive too close together. The stored text is ALWAYS updated (so final output is complete), but the `update_streaming()` call (which triggers escape + format + set_markup) is throttled to at most 20 calls/sec (50ms throttle).

**New instance variables (in `__init__`, after line ~140 where `_pending_exec_commands` is set):**
```python
# UI responsiveness throttle: session_key → last monotonic time we dispatched
# _do_text_delta's expensive path (string concat is always done, but the
# rendering dispatch is throttled to at most 20/sec).
self._last_delta_dispatch: dict[str, float] = {}
self._delta_throttle_sec = 0.05  # 50ms — at most 20 throttle-pass updates/sec
```

**Modified `_do_text_delta`:**

```python
def _do_text_delta(self, session_key: str, text: str) -> None:
    """Main-thread portion of _on_text_delta.

    AgentRuntime sends incremental SSE chunks. ChatRenderHandler expects
    cumulative text (same contract as gateway). Accumulate here.

    Throttled: the stored text is ALWAYS updated (final render is correct),
    but the expensive rendering pipeline (escape + format + set_markup) is
    limited to at most ~20 calls/sec per session.
    """
    if self._crh is None:
        return
    # Always accumulate text — ensures final output is complete
    self._streaming_text[session_key] = self._streaming_text.get(session_key, "") + text

    if not self._crh.is_streaming(session_key):
        chat_box = self._resolve_chat_box(session_key)
        if chat_box is not None:
            self._crh.start_streaming(session_key, chat_box, "Agent")
            # Fire lifecycle: agent started → ActivityHandler progress bar
            if self._on_agent_start_cb:
                self._on_agent_start_cb(session_key)
            # BUG #2: Clear ended flag on new turn
            self._ended_sessions.discard(session_key)
            self._started_turn_sessions.discard(session_key)
            # NEW: drawer-lifecycle start → drawer separator
            if self._on_drawer_lifecycle is not None:
                agent_def_dl = self._agents.get(session_key)
                agent_name_dl = agent_def_dl.display_name if agent_def_dl else "Agent"
                self._on_drawer_lifecycle(session_key, agent_name_dl, "start")

    # Throttle check: skip expensive rendering if we recently dispatched.
    # The text has already been accumulated above, so the final render
    # will be correct. This reduces per-token main-thread work by ~80%.
    now = time.monotonic()
    last = self._last_delta_dispatch.get(session_key, 0.0)
    if now - last >= self._delta_throttle_sec:
        self._last_delta_dispatch[session_key] = now
        self._crh.update_streaming(session_key, self._streaming_text[session_key])
```

**Thread safety:** `_do_text_delta` is always called on the main thread (dispatched by `_on_text_delta` via `GLib.idle_add`). No concurrent access to `self._last_delta_dispatch` — streaming is single-threaded on the main thread.

**Risk:** LOW — the throttle already exists in `update_streaming` (150ms). This moves it earlier, to 50ms. The final render includes ALL accumulated text because `sb.plain_text` is always updated inside `update_streaming` regardless of throttle state. Adding 50ms throttle on top of 150ms means we dispatch at most every 50ms to `update_streaming`, which then throttles internally to 150ms for `set_markup`. This is a tighter outer throttle that costs less per token (skips the method call chain).

**Line count estimate:** +10 lines (import, throttle vars, throttle check)

### 2.5 `ui/handlers/chat_render_handler.py` — Fix 5: Use set_text during streaming

**What changes:**
The `_update` block (now inlined after Fix 2) does `escape_for_pango(sb.plain_text)`, `format_markdown(escaped)`, and `sb.label.set_markup(formatted + "<tt>▍</tt>")`. The `set_markup` call triggers Pango markup parsing, line breaking, wrapping, height calculation — expensive operations that contribute to dropped frames.

**Fix:** During active streaming, use `set_text()` with plain text instead of `set_markup()` with formatted markup. When streaming ends (`end_streaming`), the final bubble is built by `build_role_bubble` which applies full markdown formatting. Users see plain text during streaming (which is standard for chat UIs) and formatted text on completion.

**Detailed change in `update_streaming`:**

Replace:
```python
        from utils.escaping import escape_for_pango
        from utils.markdown import format_markdown
        escaped = escape_for_pango(sb.plain_text)
        formatted = format_markdown(escaped)
        sb.label.set_markup(formatted + "<tt>▍</tt>")
```

With:
```python
        # During streaming: use plain text to avoid expensive Pango layout
        # recalculation. Full formatting (markdown, syntax highlighting) is
        # applied in end_streaming → build_role_bubble.
        sb.label.set_text(sb.plain_text + " ▍")
```

**Why this is safe:**
- `end_streaming()` (line 544) creates the final bubble via `build_role_bubble(sb.role, full_text, ...)` which applies full markdown formatting, escape, syntax highlight, etc.
- The streaming bubble is temporary — it gets replaced by the final bubble on completion.
- The cursor `▍` is still shown as plain text (no need for `<tt>` Pango markup).
- Users see exactly the text the agent has typed so far, unformatted — same as ChatGPT, Claude, and every major chat UI.

**Exception handling:** `set_text` cannot raise. No exception path needed.

**Risk:** VERY LOW — `Gtk.Label.set_text` is the cheapest way to update label content (no markup parsing, no layout recalculation if width unchanged).

**Line count:** −4 lines (removes 2 import lines + 2 formatting lines, adds 1 line)

### 2.6 Files NOT changed (already correct)

- `ui/handlers/feed_handler.py` — Fix 4 (incremental feed card update) is deferred to Phase 2. No changes needed.
- `agent/tools.py` — No tool logic changes. Correct as-is.
- `agent/context.py` — `build_system_prompt` is a pure function, correct as-is.
- `ui/views/chat_bubble.py` — `build_role_bubble` is used in `end_streaming`, correct as-is.
- `tests/*` — All existing tests must pass with zero modifications (acceptance criteria).
- `window.py` — Wiring is correct; no new callbacks or dependencies needed.

---

## 3. Data Flow

### 3.1 Current (pre-fix) Main-Thread Work for One SSE Token

```
User clicks Send
  → send_to_special_agent [main]
    → load_conversation [main, disk I/O, ~50ms]
    → create_conversation / _rebuild_conversation_context [main, ~300ms]
      → build_system_prompt [main]
        → compose_system_prompt [~300ms]
    → send_message [main]
      → threading.Thread(target=_run_loop).start()

  → _run_loop [background]
    → LLM call → SSE token arrives
    → _dispatch(on_text_delta, text) [background]
      → GLib.idle_add [main queue entry #1]
        → _do_text_delta [main]
          → string concat: streaming_text[session_key] += text [~O(n), μs]
          → is_streaming check [μs]
          → update_streaming(sk, text) [main]
            → sb.plain_text = text [μs]
            → throttle check [μs]
            → (if passes):
              → _dispatch(_update) [main queue entry #2]
                → _update() [main]
                  → escape_for_pango(sb.plain_text) [~50μs]
                  → format_markdown(escaped) [~100μs]
                  → set_markup(formatted + "<tt>▍</tt>") [~5-15ms]
```

**Per-token total:** 2 idle_add entries, ~5-15ms of main-thread work (dominated by set_markup).

**At 50 tokens/sec:** 100 idle_add/sec, ~250-750ms/sec of main-thread work. Frame budget at 60fps is 16ms — this saturates it 15-47× over.

### 3.2 Post-Fix Main-Thread Work for One SSE Token

```
User clicks Send
  → send_to_special_agent [main, ~5μs]
    → _get_runtime [μs]
    → create_conversation [main, ~5ms] (NO build_system_prompt call)
    → send_message(_defer_prompt=True) [main, μs]
      → threading.Thread(target=_run_loop).start()

  → _run_loop [background]
    → _ensure_system_prompt [background, ~300ms] (non-blocking for UI!)
    → LLM call → SSE token arrives
    → _dispatch(on_text_delta, text) [background]
      → GLib.idle_add [main queue entry #1]
        → _do_text_delta [main]
          → string concat: streaming_text[session_key] += text [~O(n), μs]
          → throttle check: skip if <50ms since last dispatch [μs]
          → (if passes throttle):
            → update_streaming(sk, text) [main, NO idle_add]
              → sb.plain_text = text [μs]
              → throttle check: skip if <150ms since last set_markup [μs]
              → (if passes):
                → set_text(sb.plain_text + " ▍") [<1ms]
```

**Per-token total:** 1 idle_add entry (halved), <1ms main-thread work (dominated by set_text).

**Worst-case per-token latency:** With the outer 50ms throttle (Fix 3) and the inner 150ms throttle (update_streaming), a token can be delayed up to 200ms before the bubble visually updates. In practice, the inner 150ms throttle dominates (it's the longer interval), so worst-case is ~150ms for a token that arrives just after a throttle window opens. This matches the **pre-fix** behavior — the 150ms throttle already existed in `update_streaming`. Fix 3's 50ms outer throttle does NOT increase latency — it reduces throughput to `update_streaming`, which the inner throttle was already doing. **Net effect on user-perceived visual latency:** unchanged from pre-fix (still ~150ms worst-case). The improvement is in main-thread CPU usage (less work per token), not in visual latency.

**At 50 tokens/sec:** 50 idle_add/sec, <50ms/sec of main-thread work. Frame budget at 60fps is 16ms — uses ~3 of 16ms. **Dropped frames due to streaming should be eliminated.**

### 3.3 Key Structures

```
AgentRuntime._dispatch(on_text_delta, text)
  → callback = self._on_text_delta
  → self._GLib.idle_add(lambda: callback(text))
    → AgentRuntimeHandler._on_text_delta(sk, text)  # on main thread
      → self._GLib.idle_add(self._do_text_delta, sk, text)
        → AgentRuntimeHandler._do_text_delta(sk, text)  # on main thread
          → # [FIX 3] 50ms throttle: skip rendering if too soon
          → ChatRenderHandler.update_streaming(sk, text)
            → sb.plain_text = text  # always stored
            → # [FIX 3] throttle was already checked, but keep 150ms throttle
            → # [FIX 2] call _update() DIRECTLY (no _dispatch)
            → # [FIX 5] sb.label.set_text(sb.plain_text + " ▍")
```

---

## 4. File Change Summary

| File | Change type | Lines changed | Risk | Fix |
|------|------------|---------------|------|-----|
| `agent/runtime.py` | Add `_ensure_system_prompt()`, modify `send_message()` and `_run_loop()` signatures | ~+50 | MEDIUM | Fix 1 |
| `ui/handlers/agent_runtime_handler.py` | Add throttle vars to `__init__`, modify `_do_text_delta()`, modify `send_to_special_agent()` for defer flag | ~+25 | LOW-MEDIUM | Fix 1, Fix 3 |
| `ui/handlers/chat_render_handler.py` | Inline `_update()` (no `_dispatch`), use `set_text` instead of `set_markup`, add top-level imports | ~-5 | LOW | Fix 2, Fix 5 |
| `ui/handlers/feed_handler.py` | — | 0 | — | Deferred (Phase 2) |

---

## 5. Implementation Order

### Step 1: Fix 5 — set_text during streaming (chat_render_handler.py)

**What:** Replace `set_markup` with `set_text` in `update_streaming`. Add `escape_for_pango` + `format_markdown` to top-level imports (they'll be removed later; kept for back-compat).

**Verification:** Run `python3 -m pytest tests/test_chat_render_handler.py -v`. All tests must pass (test_update_streaming* may need adjustment if they assert on markup content). If tests assert on formatted output, update assertions to match plain text.

```
Expected: 12/12 passed (or adjusted assertions)
```

### Step 2: Fix 2 — Eliminate double idle_add (chat_render_handler.py)

**What:** Inline `_update()` logic directly into `update_streaming`, remove `self._dispatch(_update)`.

**Verification:** Run `python3 -m pytest tests/test_chat_render_handler.py tests/test_agent_runtime_handler.py -v`.

```
Expected: All passed
```

### Step 3: Fix 3 — Throttle at _do_text_delta level (agent_runtime_handler.py)

**What:** Add `_last_delta_dispatch` dict and `_delta_throttle_sec` to `__init__`. Add throttle check in `_do_text_delta`.

**Verification:** Run `python3 -m pytest tests/test_agent_runtime_handler.py -v`. If a test asserts on exact count of `update_streaming` calls, update the test to reflect throttled calls (or mock time.monotonic).

```
Expected: All passed
```

### Step 4: Fix 1 — build_system_prompt off main thread (runtime.py + agent_runtime_handler.py)

**What:** Add `_ensure_system_prompt()` to runtime.py. Add `_defer_prompt` parameter to `send_message()` and `_run_loop()`. Modify `send_to_special_agent` to pass `_defer_prompt=True` for new conversations.

**Verification:**
1. `python3 -m pytest tests/test_runtime.py -v` — all existing tests pass
2. `python3 -m pytest tests/test_agent_runtime_handler.py -v` — all existing tests pass
3. Manual verification: add `logging.info` to `_ensure_system_prompt` and verify the log appears from background thread, not main thread

```
Expected: All 112+ affected tests pass
```

### Step 5: Full test suite

```bash
python3 -m pytest -x -q  # stop on first failure
```

Expected: 0 failures. All 1,200+ tests pass.

### Step 6: Pattern sweep

```bash
grep -rn 'self\._dispatch(_update)' ui/handlers/chat_render_handler.py
```

Expected: 0 matches (Fix 2 removed the only occurrence).

---

## 6. Acceptance Criteria

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | During a 30-second agent streaming response, the user can scroll the chat smoothly | Manual: send complex prompt to Coder, attempt to scroll during response. No visible jank. |
| 2 | During agent tool execution (5+ tools), tab switches complete in <200ms | Manual: send prompt that triggers 5+ tool calls, switch tabs during execution. |
| 3 | Initial "send message" click does not freeze UI for >50ms | Manual: click Send, observe no perceptible freeze before streaming starts. |
| 4 | Streaming text content is correct and complete | Automated: verify final bubble text matches full response (tests in test_streaming.py) |
| 5 | All existing tests pass | `pytest -q` — 0 failures |
| 6 | No regressions in final bubble formatting | Manual: response with bold/italic/code blocks → final formatted bubble matches pre-fix |
| 7 | Gateway streaming agents also benefit from Fixes 2, 3, 5 | Automated: existing test_streaming tests pass. Fix 2/3/5 changes are internal to update_streaming/_do_text_delta. |

---

## 7. Edge Cases

| Case | Expected behavior | Notes |
|------|------------------|-------|
| **Empty streaming text** (tool-only turn, BUG #21) | Streaming bubble created with empty text, no final bubble rendered | `end_streaming(render=False)` suppresses final bubble. `_do_text_delta` with empty string still calls `update_streaming` — Fix 5's `set_text(" ▍")` works fine with empty text. |
| **Very fast streaming** (>50 tokens/sec) | Throttled to ~20 renders/sec via Fix 3 (50ms outer throttle) + Fix 5's cheap set_text | No dropped frames from excessive rendering. |
| **Very slow streaming** (<5 tokens/sec) | Every token renders (passes 50ms throttle), no visual latency | Final render is always correct — text accumulates before throttle check. |
| **Conversation creation on first send** | `_ensure_system_prompt` runs in background thread. The first `on_text_delta` dispatch is the BUG #21 empty-string turn-start signal, which fires AFTER `_ensure_system_prompt` returns. The BUG #21 signal provides the activity indicator via `_do_text_delta` → `_on_agent_start_cb`. **No additional mitigation needed** — the turn-start signal at `_run_loop` line 805 already handles this. | Verified against source: runtime.py:803-806 dispatches `self._dispatch(self._on_text_delta, session_key, "")` before the LLM call. |
| **Stale project path on loaded conversation** | `_rebuild_conversation_context` still fires synchronously in `send_to_special_agent` (line ~777). This is correct — it fires ONCE per conversation lifetime (when loading from disk with different project path). Not a performance concern. | If the user switches projects frequently, the 300ms rebuild penalty applies each time. Acceptable. |
| **build_system_prompt raises** | Exception propagates to `_run_loop`'s outer `except Exception` handler, which dispatches `_on_error` with the exception message. User sees error bubble. | Handled by existing infrastructure. |
| **Multiple concurrent send_to_special_agent** (user clicks Send twice) | First call creates conversation + starts `_run_loop`. Second call gets existing conv, `_ensure_system_prompt` is a no-op (system_prompt is already set). Both `_run_loop` instances run — the first one does the work, the second one's `_run_loop`... Actually, `send_message` doesn't prevent concurrent loops. This is a pre-existing issue. | Not new to this fix. Out of scope. |
| **Error during streaming** (LLM timeout after partial text) | `_do_error` calls `end_streaming(session_key)` which finalizes the bubble with whatever text was accumulated. The final bubble is built via `build_role_bubble` with the partial text + the error message formatted as `[Error] ...`. The user sees the partial text plus the error. | Verified: `_do_error` (agent_runtime_handler.py ~1294) calls `self._crh.end_streaming(session_key)` before rendering the error bubble. |
| **Token bursts** (10+ tokens within 50ms) | Only the first token in the burst triggers `update_streaming`. The remaining tokens' text is accumulated in `_streaming_text` and rendered on the next throttle pass (within 50ms). Visually, the bubble updates in small chunks rather than per-token — standard for chat UIs. | The 50ms outer throttle (Fix 3) coalesces the burst into a single dispatch. The text is always accumulated before the throttle check, so no text is lost. |
| **Fix 3 50ms throttle + Fix 5 set_text interaction** | No conflict. Fix 3 limits outer dispatch to ~20/sec. Fix 5 makes each dispatch cheap (<1ms). The 150ms throttle in `update_streaming` is still respected as well. | Both throttles together: at most ~6.7 `set_text` calls/sec (150ms inner) with the outer 50ms check filtering tokens earlier. |
| **Gateway streaming agents (chat_handler.py path)** | `chat_handler.py:575` calls `update_streaming` directly (already on main thread). Fix 2's inlining and Fix 5's set_text apply transparently — no changes needed to gateway path. | Fix 3's throttle is in `_do_text_delta` (agent_runtime_handler only), which the gateway path doesn't use. The gateway path already has its own throttling in `update_streaming` (the 150ms throttle). Gateway agents won't get Fix 3's pre-filtering but will get Fix 2 and Fix 5 benefits. |

---

## 8. ARCHITECTURE.md Updates Required

### §8.7 — UI Responsiveness

Add a new subsection documenting the throttle architecture:

```
### §8.7 — UI Responsiveness Throttle Architecture

During agent runs, streaming text updates are throttled at two levels
to prevent main-thread saturation:

1. **Outer throttle** (agent_runtime_handler.py `_do_text_delta`): 50ms
   — limits dispatch to `update_streaming` to ~20 calls/sec. Skips
   expensive method call chain for 80% of tokens. Text is always
   accumulated; rendering is throttled.

2. **Inner throttle** (chat_render_handler.py `update_streaming`): 150ms
   — limits `set_text` calls to ~6.7 calls/sec during streaming. This
   matches the pre-existing throttle that limited `set_markup`.

During streaming, `Gtk.Label.set_text()` is used instead of
`set_markup()` to avoid expensive Pango markup parsing and layout
recalculation. Full markdown formatting is applied in
`end_streaming()` → `build_role_bubble()` on completion.

System prompt building (`build_system_prompt`) is deferred to the
agent's background thread via `_ensure_system_prompt()` for new
conversations. This eliminates 300-500ms of main-thread blocking
at the start of each agent turn.
```

### §3 — Component inventory

Update `agent/runtime.py` function list to include `_ensure_system_prompt`.

### §8.6 — Handler pattern

No changes needed — the handler dispatch pattern is unchanged (callbacks still use `GLib.idle_add` for main-thread dispatch).

---

## 9. Spec Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - YES. All function names verified by grep: `send_message` (runtime.py:535), `_run_loop` (782), `_dispatch` (387), `update_streaming` (chat_render_handler.py:434), `_do_text_delta` (agent_runtime_handler.py:972), `send_to_special_agent` (733), `build_system_prompt` (context.py:702), `_ensure_system_prompt` (new), `set_text` (Gtk.Label standard), `set_markup` (Gtk.Label standard).
   - `_defer_prompt` is a new parameter — verified that no existing callers of `send_message` pass kwargs (test patches use `Mock` or direct calls).
   - `GLib.idle_add` returns `False` pattern verified in chat_render_handler._dispatch (line 750).

2. **Did I catch all exception types for every function I call?**
   - `build_system_prompt` can raise `OSError`, `json.JSONDecodeError`, `ImportError` (from try/except blocks). The `_ensure_system_prompt` method lets exceptions propagate — they're caught by `_run_loop`'s outer `except Exception` (line ~1240). **Correct.**
   - `escape_for_pango` and `format_markdown` are pure string functions — no exceptions (verified in utils/escaping.py and utils/markdown.py).
   - `set_text` on `Gtk.Label` cannot raise.
   - `sb.label.set_text` — `sb` is from `self._streaming_bubbles.get(session_key)`, which could be None. **Mitigation:** `update_streaming` already checks `if session_key not in self._streaming_bubbles: return` at line 448. Safe.

3. **Did I verify key structures, not assume them?**
   - YES. `self._streaming_text` dict structure verified (agent_runtime_handler.py:81: `_streaming_text: dict[str, str] = {}`).
   - `self._streaming_bubbles` dict structure verified (chat_render_handler.py:179: `_streaming_bubbles: dict = {}` — keys are session_key, values are StreamingBubble dataclass).
   - `self._on_agent_start_cb` signature verified (line 154: `Callable[[str], None]` — single arg session_key).
   - `self._lock` is `threading.Lock` (not RLock) — verified at runtime.py line ~310.

4. **Did I trace the data flow end-to-end?**
   - YES. See §3 Data Flow above. Traced from `send_to_special_agent` through `_run_loop` → `_dispatch` → `_do_text_delta` → `update_streaming` → label update. Both pre-fix and post-fix flows diagrammed.

5. **Would an implementer who follows this spec exactly produce working code?**
   - YES. Every change is scoped to known line numbers. Code samples are complete (not "pseudo-code"). The implementer only needs to:
     1. Add `_ensure_system_prompt` method to AgentRuntime
     2. Modify `send_message` and `_run_loop` signatures (add _defer_prompt)
     3. Modify `_do_text_delta` (add throttle + remove second dispatch)
     4. Modify `update_streaming` (inline _update, use set_text)
     5. Update imports in chat_render_handler.py
     6. Update `send_to_special_agent` (pass _defer_prompt)
   - No ambiguous instructions. No "should work" assumptions.

---

## 10. Completion Verification (Rule 10)

### 10.1 Scope Checklist

```
[x] agent/runtime.py — changed (add _ensure_system_prompt, modify send_message + _run_loop)
[x] ui/handlers/agent_runtime_handler.py — changed (add throttle vars, modify _do_text_delta, modify send_to_special_agent)
[x] ui/handlers/chat_render_handler.py — changed (inline _update, set_text, add top-level imports)
[ ] ui/handlers/feed_handler.py — NOT changed (Fix 4 deferred to Phase 2)
```

### 10.2 Test Suite

After implementation, run:

```bash
python3 -m pytest tests/test_chat_render_handler.py tests/test_agent_runtime_handler.py -v
python3 -m pytest tests/test_runtime.py -v
python3 -m pytest -q  # full suite (1,200+ tests)
```

Paste actual output in implementation report.

### 10.3 Pattern Sweep

```bash
# No old patterns to sweep — Fix 2 replaces self._dispatch(_update)
# with direct call. Verify zero remaining:
grep -rn 'self\._dispatch(_update)' ui/handlers/
grep -rn 'set_markup' ui/handlers/chat_render_handler.py | grep streaming

# Fix 5 replaces set_markup in streaming path. Verify set_text is used:
grep -n 'set_text\|set_markup' ui/handlers/chat_render_handler.py | grep -v 'test'
```

Expected:
- `self._dispatch(_update)` — 0 matches
- `set_markup` in streaming path — 0 matches (only in `end_streaming`'s `build_role_bubble` which is correct)
- `set_text` in `update_streaming` — 1 match

### 10.4 Declaration

Phase 1 complete when all four fixes are implemented, test suite passes, and pattern sweep is clean.

---

## 11. Out-of-Scope / Deferred (Phase 2)

### Fix 4 — Incremental feed card update

**Status:** Deferred — Phase 2.

**What it does:** Instead of rebuilding the entire feed card widget on every `update_card`, update only the changed fields (status badge, body text).

**Why deferred:** `update_card` is called during tool execution (5-10 times per agent turn). Each full rebuild creates 5-10 GTK widgets, triggering allocation and layout passes. However, this is a lower-impact fix than the streaming path (which fires 50-100 times/sec).

**Relevant code:** `FeedHandler.update_card()` in `ui/handlers/feed_handler.py`. Current code calls `build_feed_card()` which creates a new widget tree. Fix would add an in-place update method that modifies existing widget properties.

### Fix 6 — Batch pre-loop work into background thread

**Status:** Deferred — Phase 2.

**What it does:** Move ALL pre-loop work (`load_conversation`, `_rebuild_conversation_context`, state syncing, MCP server list resolution, api_key syncing, step_count reset) into the same background thread as Fix 1.

**Why deferred:** Fix 1 already moves the most expensive pre-loop operation (build_system_prompt, ~300ms). The remaining operations are each <50ms. The risk of race conditions (concurrent api_key syncing, MCP connection state) outweighs the benefit for Phase 1.

**Relevant code:** `send_to_special_agent()` lines 770-840. The entire block from `_get_runtime` through `send_message` would move to a background thread, with only the project guard and error checking on the main thread.