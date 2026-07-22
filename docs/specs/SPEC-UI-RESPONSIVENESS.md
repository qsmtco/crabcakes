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

- **Read `agent/runtime.py`** (1995 lines): `AgentRuntime.__init__` takes `GLib, on_text_delta, on_tool_call_start, on_tool_call_result, on_response_complete, on_error` etc. `send_message()` (line 535) spawns a `threading.Thread(target=self._run_loop)` — runs on daemon thread. `create_conversation()` (line 435) calls `build_system_prompt()` synchronously at line 498 — file I/O + template composition, ~300ms on any caller thread (including main thread when called from `send_to_special_agent`). `_rebuild_conversation_context()` (line 1708) also calls `build_system_prompt()`. `_dispatch()` (line 387) wraps callback in `GLib.idle_add` or direct call. `_run_loop` (line 782) calls `self._dispatch(self._on_text_delta, session_key, text)` for every SSE text token. The `_lock` is `threading.Lock` (line 340, not RLock). `_conversations` dict is protected by `self._lock`. `_run_loop` raises `except Exception as e:` at line 1264 — outermost error handler. `force_llm_compact` (line 1851) reads/writes `conv.system_prompt` under `self._compaction_lock`.

- **Read `ui/handlers/agent_runtime_handler.py`** (1767 lines): `send_to_special_agent()` (line 733) runs ENTIRELY on main thread. It calls `_get_runtime()` (line inference ~675, lazy init), then `rt.load_conversation()` (disk I/O), then `rt._rebuild_conversation_context()` or `rt.create_conversation()` (both call `build_system_prompt()` synchronously, ~300ms blocking), then `rt.send_message()` (line 540 — spawns thread). `_on_text_delta` (line 962) dispatches to main thread via `GLib.idle_add`. `_do_text_delta` (line 972) accumulates text, calls `self._crh.update_streaming()`. `_do_error` (line 1719) calls `self._crh.end_streaming()` then renders error bubble. Callbacks: `_on_agent_start_cb` (line 80, set at line 156) and `_on_agent_end_cb` (line 81, set at line 160) are set by window.py — signature `cb(session_key)`. `self._streaming_text: dict[str, str]` at line 75. `self._crh` set at line 54. `self._agents` at line 64. `self._ended_sessions: set[str]` at line 100. `self._started_turn_sessions: set[str]` at line 104. `self._on_drawer_lifecycle` at line 94, set at line 198.

- **Read `ui/handlers/chat_render_handler.py`** (758 lines): `update_streaming()` (line 434) stores text, checks throttle (150ms via `_stream_throttle_sec` at line 192), then defines inner `_update()` (lines 465-471) which does `escape_for_pango` + `format_markdown` + `set_markup`. `_update()` is dispatched via `self._dispatch()` (line 750 — another `GLib.idle_add`). This is the SECOND idle_add — the first was in `_on_text_delta` → `_do_text_delta`. `_dispatch()` (line 750) wraps in `GLib.idle_add` returning `False` (one-shot). The throttle (150ms) is checked BEFORE `_dispatch`, so at most ~6.7 `_update` calls/sec per session. `start_streaming()` at line 373. `end_streaming()` at line 544. `is_streaming()` at line 405. `_streaming_bubbles` at line 179. `import time` at line 456 (inside function body).

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
| **Fix 1** | Move `build_system_prompt` off main thread into background thread via `defer_prompt_build` param on `create_conversation` | Eliminates 300-500ms initial freeze on Send |
| **Fix 2** | Eliminate double `GLib.idle_add` in `update_streaming` | Halves idle-queue entries during streaming |
| **Fix 3** | Move throttle check from `update_streaming` to `_do_text_delta` | Reduces per-token main-thread work by ~50% |
| **Fix 5** | Use `set_text()` instead of `set_markup()` during streaming | Eliminates expensive Pango layout + markdown formatting during streaming |

### 1.3 Scope

| Item | In scope (Phase 1) | Out of scope (Phase 2) |
|------|-------------------|----------------------|
| Fix 1: `defer_prompt_build` on `create_conversation`, wired in `send_to_special_agent` | ✅ | — |
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
`create_conversation()` (line 435) currently calls `build_system_prompt()` synchronously at line 498 and passes the result to `Conversation(system_prompt=...)` at line 517. The `send_message()` method (line 535) spawns a thread that calls `_run_loop`.

The system prompt build involves reading the project directory tree, parsing `.gitignore`, reading `.crabcakes/` docs, and template composition — all synchronous file I/O that blocks the caller's thread (which is the main thread when called from `send_to_special_agent`).

**Key insight:** `send_message()` already spawns a background thread (`threading.Thread(target=self._run_loop)` at line 540). The system prompt building happens BEFORE `send_message` is called (in `create_conversation` at line 498). The fix is to add a `defer_prompt_build` parameter to `create_conversation` that skips the build and passes `system_prompt=""`, then have `_run_loop` call `_ensure_system_prompt()` as its first step.

**BUG #13 — Why `defer_prompt_build` must go on `create_conversation`, not `send_message`:**
`send_message` (line 535) already starts a background thread. The blocking `build_system_prompt` call happens inside `create_conversation` (line 498), before `send_message` is even called. A `_defer_prompt` flag on `send_message` does not help because the main-thread freeze has already happened. The defer must occur at the `create_conversation` level — if we pass `defer_prompt_build=True`, it skips the build and creates the conversation with `system_prompt=""`. Then `_run_loop` (called from `send_message`'s background thread) calls `_ensure_system_prompt` to build it on the background thread.

**Detailed change:**

Add `defer_prompt_build` parameter to `create_conversation`:

```python
def create_conversation(
    self,
    agent_name: str,
    session_key: str,
    project_path: str | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: list[str] = None,
    agent_role: str = "",
    si_enforcement: bool | None = None,
    api_key: str | None = None,
    app_title: str = "",
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    defer_prompt_build: bool = False,       # NEW
) -> str:
```

When `defer_prompt_build=True`, wrap the `build_system_prompt` call in a conditional:

```python
        if defer_prompt_build:
            system_prompt = ""
        else:
            system_prompt = build_system_prompt(
                agent_name, project_path, tool_names,
                agent_role=agent_role,
                model_max_tokens=model_max_for_budget,
                context_mode=getattr(default_provider_cfg, "context_mode", "auto") or "auto",
            )
```

The `Conversation(system_prompt=system_prompt, ...)` call at line 517 is unchanged — it gets `""` when deferred.

Add method `_ensure_system_prompt`:

```python
def _ensure_system_prompt(self, session_key: str) -> None:
    """Ensure the conversation has a system prompt built.

    Called from _run_loop at the start, before any LLM call.
    If the conversation already has a system prompt, this is a no-op.

    Thread safety (BUG #1 audit, BUG #19 fix): uses double-checked-locking
    with an identity check on the conv object.

    BUG #19 — DCL pitfall: conv is fetched without the lock (fast path).
    Between the fast-path fetch and the slow-path lock, another thread
    (e.g., clear_conversation or load_conversation) could replace the
    conversation in self._conversations. The identity check ('conv_now is conv')
    inside the lock ensures we only write to the SAME object we checked.
    If the conversation was replaced, we skip the write — the new conversation
    will either have its own prompt or trigger a new build on its next _run_loop.
    """
    # Fast path: check without lock (common case — prompt already built
    # or deferred-build not enabled)
    conv = self._conversations.get(session_key)
    if conv is None or conv.system_prompt:
        return

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

    # Slow path: acquire lock, re-fetch conv, identity check, write
    with self._lock:
        conv_now = self._conversations.get(session_key)
        if conv_now is conv and not conv_now.system_prompt:
            conv_now.system_prompt = new_prompt
            logger.info("System prompt built for %s in background thread (len=%d)",
                        session_key, len(new_prompt))
```

Modify `_run_loop` to call `_ensure_system_prompt` as its first step after the lock/nil checks:

```python
def _run_loop(self, session_key: str, text: str) -> None:
    """Background thread: run the full tool loop for one user message."""
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

        # BUG #13 — Deferred prompt build. If create_conversation was called
        # with defer_prompt_build=True (system_prompt == ""), build it now on
        # the background thread. This eliminates ~300ms of main-thread blocking
        # on every new agent conversation.
        self._ensure_system_prompt(session_key)

        # BUG #21: Fire a turn-start signal...
```

**Verification of thread safety (BUG #14 updated narrative):**
- `build_system_prompt()` in `agent/context.py` is a pure function — no state, no GTK calls, only file I/O
- `conv.system_prompt` assignment in `_ensure_system_prompt` uses double-checked-locking: fast-path check without lock, slow-path write under `self._lock` with identity check. The first check is the common case (prompt already built or deferred-build not enabled).
- The identity check (`conv_now is conv`) ensures we don't write to a stale object if `self._conversations[session_key]` was replaced between the fast-path and slow-path.
- Concurrent writer `force_llm_compact` (line 1851, main thread via `/compact`) writes `conv.system_prompt` under `self._compaction_lock` — a DIFFERENT lock than `self._lock`. The double-check inside `self._lock` handles this: `_ensure_system_prompt` only writes when `conv_now.system_prompt` is still falsy, so if `force_llm_compact` already wrote it, the double-check skips the write.

**Exception handling:** `build_system_prompt` can raise if project path is invalid or templates are missing. `_ensure_system_prompt` has no try/except — let the exception propagate to `_run_loop`'s existing outer `except Exception` handler (line 1264), which dispatches `_on_error`. This is correct: a failed prompt build is a fatal error for the turn.

**Imports required:** None new — `build_system_prompt` and `get_all_tools` are already imported inside `create_conversation()`.

**Line count estimate:** +45 lines (new method + defer conditional in create_conversation + _run_loop call)

### 2.2 `ui/handlers/agent_runtime_handler.py` — Fix 1 wiring

**What changes:**
`send_to_special_agent()` (line 733) currently creates the conversation synchronously before calling `send_message()`. With Fix 1, the prompt build is deferred to the background thread.

**Approach:**
When creating a new conversation (line ~806 `rt.get_conversation(session_key) is None` and line ~818 `rt.create_conversation(...)`), pass `defer_prompt_build=True`. The actual `build_system_prompt` runs in the background thread via `_ensure_system_prompt`.

When loading a persisted conversation that needs rebuilding (`_rebuild_conversation_context` path, line ~813), the rebuild still calls `build_system_prompt` synchronously — this is a rare operation (project switch) that happens at most once per conversation lifetime. Not a performance concern.

**Detailed change in `send_to_special_agent`:**

In the "new conversation" path (~line 818):

```python
        if rt.get_conversation(session_key) is None:
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
                defer_prompt_build=True,        # NEW — prompt built in background
            )
```

The existing `if loaded: ... _rebuild_conversation_context` path (line ~810-815) is unchanged — it calls `create_conversation` only when no persisted conversation exists. When it does exist, `_rebuild_conversation_context` fires synchronously but rarely (once per conversation lifetime on project switch).

No need to modify `rt.send_message` — the defer is entirely handled by `create_conversation`/`_ensure_system_prompt`.

**Risk:** LOW — the `defer_prompt_build` parameter is a straightforward boolean flag. It is never set for the `_rebuild_conversation_context` path because that path loads a persisted conversation (which has a non-empty `system_prompt` after rebuild), then `_ensure_system_prompt` is a no-op.

**Line count estimate:** +1 line (`defer_prompt_build=True`)

### 2.3 `ui/handlers/chat_render_handler.py` — Fix 2: Eliminate double idle_add

**What changes:**
`update_streaming()` (line 434) currently defines `_update()` (lines 465-471) and dispatches it via `self._dispatch(_update)` (line 473). This is the SECOND `GLib.idle_add` — the first was in `_on_text_delta` → `GLib.idle_add` → `_do_text_delta`.

**Fix:** Call the update logic directly instead of going through `self._dispatch()`. Since `update_streaming` is called from `_do_text_delta` (which is already on the main thread via the first `GLib.idle_add`), the second dispatch is redundant.

**Verify call sites:**
- `agent_runtime_handler.py:998` — `self._crh.update_streaming(session_key, self._streaming_text[session_key])` — called from `_do_text_delta`, which IS on the main thread.
- `chat_handler.py:575` — `self._chat_render_handler.update_streaming(session_key, delta_text)` — called from `_handle_streaming_delta`. Gateway events arrive on the gateway thread and are dispatched via `GLib.idle_add` to the main thread. So YES, `_handle_streaming_delta` is also on the main thread.

Both callers are on the main thread. Safe to inline.

**Detailed change (post-Fix-5 state — Fix 5 runs first, replacing set_markup with set_text):**

Replace (lines 465-473, after Fix 5 has replaced set_markup with set_text):
```python
        def _update():
            from utils.escaping import escape_for_pango
            from utils.markdown import format_markdown
            escaped = escape_for_pango(sb.plain_text)
            formatted = format_markdown(escaped)
            sb.label.set_markup(formatted + "<tt>▍</tt>")

        self._dispatch(_update)
```

With (inline the update logic, remove `_dispatch`):
```python
        # Direct update — we're already on the main thread (caller dispatched
        # via GLib.idle_add). Inlining avoids double idle_add overhead.
        sb.label.set_text(sb.plain_text + " ▍")
```

**Risk:** LOW — the logic is identical, just removing the redundant `_dispatch` wrapper. The imports (`escape_for_pango`, `format_markdown`) were already inside `_update()`, now they're removed entirely since we use `set_text`.

**Line count:** −7 lines (remove `def _update():`, its body, and `self._dispatch(_update)` including dedented set_text line)

### 2.4 `ui/handlers/agent_runtime_handler.py` — Fix 3: Throttle at _do_text_delta level

**What changes:**
`_do_text_delta()` (line 972) does string concatenation, dict lookups, and method calls for EVERY token — including tokens that will be immediately throttled in `update_streaming()`.

**Fix:** Add a throttle check at the top of `_do_text_delta` that skips expensive processing for tokens that arrive too close together. The stored text is ALWAYS updated (so final output is complete), but the `update_streaming()` call (which triggers escape + format + set_text) is throttled to at most 20 calls/sec (50ms throttle).

**New instance variables (in `__init__`, near line ~75 where `_streaming_text` is set):**
```python
# UI responsiveness throttle: session_key → last monotonic time we dispatched
# _do_text_delta's expensive path (string concat is always done, but the
# rendering dispatch is throttled to at most 20/sec).
self._last_delta_dispatch: dict[str, float] = {}
self._delta_throttle_sec = 0.05  # 50ms — at most 20 throttle-pass updates/sec
```

**Modified `_do_text_delta` (line 972):**

```python
def _do_text_delta(self, session_key: str, text: str) -> None:
    """Main-thread portion of _on_text_delta.

    AgentRuntime sends incremental SSE chunks. ChatRenderHandler expects
    cumulative text (same contract as gateway). Accumulate here.

    Throttled: the stored text is ALWAYS updated (final render is correct),
    but the expensive rendering pipeline is limited to ~20 calls/sec per session.
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

**Import required:** Add `import time` at the top of `agent_runtime_handler.py` (at line ~17 alongside the existing `import logging`, `import os`, etc.).

**Risk:** LOW — the throttle already exists in `update_streaming` (150ms). This moves it earlier, to 50ms. The final render includes ALL accumulated text because `sb.plain_text` is always updated inside `update_streaming` regardless of throttle state. Adding 50ms throttle on top of 150ms means we dispatch at most every 50ms to `update_streaming`, which then throttles internally to 150ms for `set_text`. The 50ms outer throttle saves the method call chain for 80% of tokens without increasing visual latency (the 150ms inner throttle was already the bottleneck).

**Line count estimate:** +10 lines (import, throttle vars, throttle check)

### 2.5 `ui/handlers/chat_render_handler.py` — Fix 5: Use set_text during streaming

**What changes:**
The `_update` block (now inlined after Fix 2) does `escape_for_pango(sb.plain_text)`, `format_markdown(escaped)`, and `sb.label.set_markup(formatted + "<tt>▍</tt>")`. The `set_markup` call triggers Pango markup parsing, line breaking, wrapping, height calculation — expensive operations that contribute to dropped frames.

**Fix:** During active streaming, use `set_text()` with plain text instead of `set_markup()` with formatted markup. When streaming ends (`end_streaming`), the final bubble is built by `build_role_bubble` which applies full markdown formatting. Users see plain text during streaming (which is standard for chat UIs) and formatted text on completion.

**Detailed change in `update_streaming` (after Fix 2 inlining, the `_update` block is replaced):**

```python
        # During streaming: use plain text to avoid expensive Pango layout
        # recalculation. Full formatting (markdown, syntax highlighting) is
        # applied in end_streaming → build_role_bubble.
        sb.label.set_text(sb.plain_text + " ▍")
```

**BUG #18 — Cursor visual change:** This changes the cursor rendering from `<tt>▍</tt>` (Pango monospace tag, no leading space) to ` ▍` (plain text with a leading space). The space provides visual separation between text and cursor. This is a minor visual change — the cursor is slightly larger (no longer monospace-constrained) and has one space of padding. No behavioral impact.

**Why this is safe:**
- `end_streaming()` (line 544) creates the final bubble via `build_role_bubble(sb.role, full_text, ...)` which applies full markdown formatting, escape, syntax highlight, etc.
- The streaming bubble is temporary — it gets replaced by the final bubble on completion.
- The cursor `▍` is still shown as plain text (no need for `<tt>` Pango markup).
- Users see exactly the text the agent has typed so far, unformatted — same as ChatGPT, Claude, and every major chat UI.

**Exception handling:** `set_text` cannot raise. No exception path needed.

**Risk:** VERY LOW — `Gtk.Label.set_text` is the cheapest way to update label content (no markup parsing, no layout recalculation if width unchanged).

**Line count:** −4 lines (removes 2 import lines + 2 formatting lines, adds 1 line)

### 2.6 Test Impact of Fix 5 (set_text during streaming)

Fix 5 (using `set_text` instead of `set_markup` during streaming) changes what the streaming label contains. This affects existing tests that assert on Pango-escaped markup content in the streaming bubble, because `set_text` stores literal text while `set_markup` stored Pango-escaped text.

**Affected test (identified by Debugger spec audit, BUG #2):**

`tests/test_chat_render_handler.py:211 — `test_update_streaming_escapes_html_chars`

**Current assertion:** Asserts `"&lt;div&gt;" in markup` — the Pango-escaped form.
**Post-Fix 5 behavior:** The label contains `"Use <div> ▍"` — literal `<div>`, no escaping.

**Resolution:** Update this test to assert plain-text behavior during streaming:

```python
def test_update_streaming_shows_plain_text(self):
    """During streaming, label shows plain text (no markup escaping).
    Escaping is applied in end_streaming → build_role_bubble."""
    self.handler.start_streaming("agent:1", self.fake_box, "Agent")
    self._run_all_idle()
    self.handler.update_streaming("agent:1", "<div>hello</div>")
    self._run_all_idle()
    label = self.handler._streaming_bubbles["agent:1"].label.get_label()
    assert "<div>hello</div>" in label  # literal, not escaped
    assert "&lt;" not in label  # no markup escaping during streaming
```

**BUG #17 — Add XSS test for end_streaming (escapes HTML):**
Add a second test that verifies escaping is applied on the final render (not during streaming):

```python
def test_end_streaming_escapes_html_in_final_bubble(self):
    """end_streaming → build_role_bubble escapes < > & in the final bubble.
    Streaming shows plain text; escaping is applied on completion."""
    self.handler.start_streaming("agent:1", self.fake_box, "Agent")
    self._run_all_idle()
    self.handler.update_streaming("agent:1", "Use <div> & <script>")
    self._run_all_idle()
    self.handler.end_streaming("agent:1")
    self._run_all_idle()
    # The final bubble should have escaped the HTML chars.
    # The exact assertion depends on build_role_bubble's label content
    # structure. Intent: verify that < > & are escaped in the final
    # rendered bubble, not during streaming.
```

Note: the exact assertion may need to be adjusted during implementation based on how `build_role_bubble` exposes its label content. The spec documents the intent: verify escaping happens on final render, not during streaming.

### 2.7 Files NOT changed (already correct)

- `ui/handlers/feed_handler.py` — Fix 4 (incremental feed card update) is deferred to Phase 2. No changes needed.
- `agent/tools.py` — No tool logic changes. Correct as-is.
- `agent/context.py` — `build_system_prompt` is a pure function, correct as-is.
- `ui/views/chat_bubble.py` — `build_role_bubble` is used in `end_streaming`, correct as-is.
- `tests/*` — All existing tests must pass with zero modifications (acceptance criteria), EXCEPT `test_update_streaming_escapes_html_chars` which is updated to assert plain-text behavior (§2.6).
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
    → create_conversation(defer_prompt_build=True) [main, ~5ms] (NO build_system_prompt call)
    → send_message(session_key, text) [main, μs]
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
              → throttle check: skip if <150ms since last set_text [μs]
              → (if passes):
                → set_text(sb.plain_text + " ▍") [<1ms]
```

**Per-token total:** 1 idle_add entry (halved), <1ms main-thread work (dominated by set_text).

**Worst-case per-token latency:** With the outer 50ms throttle (Fix 3) and the inner 150ms throttle (update_streaming), a token can be delayed up to 200ms before the bubble visually updates. In practice, the inner 150ms throttle dominates (it's the longer interval), so worst-case is ~150ms for a token that arrives just after a throttle window opens. This matches the **pre-fix** behavior — the 150ms throttle already existed in `update_streaming`. Fix 3's 50ms outer throttle does NOT increase latency — it reduces throughput to `update_streaming`, which the inner throttle was already doing. **Net effect on user-perceived visual latency:** unchanged from pre-fix (still ~150ms worst-case). The improvement is in main-thread CPU usage (less work per token), not in visual latency.

**At 50 tokens/sec:** 50 idle_add/sec, <50ms/sec of main-thread work. Frame budget at 60fps is 16ms — uses ~3 of 16ms. **Dropped frames due to streaming should be eliminated.**

**BUG #16 — Throttle narrative correct:** The 150ms throttle applies to `set_text` (not `set_markup`). The throttle is a property of `update_streaming`'s time check, not the specific label-update method. Regardless of whether `set_text` or `set_markup` is called, `update_streaming` checks `time.monotonic()` against `self._last_stream_update[session_key]`. The same throttle mechanism works for both methods.

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
            → # [FIX 2] call update DIRECTLY (no _dispatch)
            → # [FIX 5] sb.label.set_text(sb.plain_text + " ▍")
```

---

## 4. File Change Summary

| File | Change type | Lines changed | Risk | Fix |
|------|------------|---------------|------|-----|
| `agent/runtime.py` | Add `_ensure_system_prompt()`, modify `create_conversation()` parameter, add call in `_run_loop()` | ~+45 | MEDIUM | Fix 1 |
| `ui/handlers/agent_runtime_handler.py` | Add throttle vars to `__init__`, modify `_do_text_delta()`, add `defer_prompt_build=True` in `create_conversation()` call | ~+11 | LOW-MEDIUM | Fix 1, Fix 3 |
| `ui/handlers/chat_render_handler.py` | Inline `_update()` (no `_dispatch`), use `set_text` instead of `set_markup` | ~-7 | LOW | Fix 2, Fix 5 |
| `tests/test_chat_render_handler.py` | Update `test_update_streaming_escapes_html_chars` → `test_update_streaming_shows_plain_text`; add `test_end_streaming_escapes_html_in_final_bubble` | ~+15 | LOW | Fix 5, BUG #17 |

---

## 5. Implementation Order

### Step 1: Fix 5 — set_text during streaming (chat_render_handler.py)

**What:** Replace `set_markup` with `set_text` in `update_streaming`. Remove the `_update` closure entirely (the body is now a single `set_text` line).

**Verification:** Run `python3 -m pytest tests/test_chat_render_handler.py -v`. Tests must pass.
- `test_update_streaming_escapes_html_chars` is updated to assert plain-text behavior during streaming (§2.6).
- `test_end_streaming_escapes_html_in_final_bubble` is added (§2.6, BUG #17).
- All other test assertions pass unchanged.

```
Expected: All tests pass. The one updated test reflects the new behavior.
```

### Step 2: Fix 2 — Eliminate double idle_add (chat_render_handler.py)

**What:** Remove the `_dispatch(_update)` call. The single `set_text` line remains inline in `update_streaming`.

**Note:** Step 1 already removed the `_update` closure. Step 2 is a no-op if Step 1 was done first. If implementing in a different order, ensure the `_dispatch` call is removed.

**Verification:** Run `python3 -m pytest tests/test_chat_render_handler.py tests/test_agent_runtime_handler.py -v`.

```
Expected: All passed
```

### Step 3: Fix 3 — Throttle at _do_text_delta level (agent_runtime_handler.py)

**What:** Add `_last_delta_dispatch` dict and `_delta_throttle_sec` to `__init__`. Add throttle check in `_do_text_delta`. Add `import time` at module top.

**Verification:** Run `python3 -m pytest tests/test_agent_runtime_handler.py -v`. If a test asserts on exact count of `update_streaming` calls, update the test to reflect throttled calls (or mock time.monotonic).

```
Expected: All passed
```

### Step 4: Fix 1 — build_system_prompt off main thread (runtime.py + agent_runtime_handler.py)

**What:** 
1. Add `defer_prompt_build: bool = False` parameter to `create_conversation()` (runtime.py:435)
2. Wrap the `build_system_prompt` call (runtime.py:498) in `if not defer_prompt_build:`
3. Add `_ensure_system_prompt()` method to `AgentRuntime` (including BUG #19 identity-check pattern)
4. Call `self._ensure_system_prompt(session_key)` in `_run_loop` (runtime.py:782) after the lock/nil checks
5. Pass `defer_prompt_build=True` in `send_to_special_agent`'s `create_conversation` call (agent_runtime_handler.py:818)

**Verification:**
1. `python3 -m pytest tests/test_agent_runtime.py -v` — all existing tests pass
2. `python3 -m pytest tests/test_agent_runtime_handler.py -v` — all existing tests pass
3. Manual verification: add `logging.info` to `_ensure_system_prompt` and verify the log appears from the background thread, not the main thread

```
Expected: All affected tests pass
```

### Step 5: Full test suite

```bash
python3 -m pytest -x -q  # stop on first failure
```

Expected: 0 unexpected failures. Two tests have changed assertions (both documented in §2.6). All other 1,200+ tests pass unchanged.

### Step 6: Pattern sweep

```bash
grep -rn 'self\._dispatch(_update)' ui/handlers/
grep -rn 'set_markup' ui/handlers/chat_render_handler.py | grep streaming
grep -n '_defer_prompt' agent/runtime.py agent/tools.py ui/handlers/agent_runtime_handler.py
```

Expected:
- `self._dispatch(_update)` — 0 matches (Fix 2 removed the only occurrence)
- `set_markup` in streaming path — 0 matches (only in `end_streaming`'s `build_role_bubble` which is correct)
- `_defer_prompt` — 0 matches across all files (Fix 1 uses `defer_prompt_build`, not `_defer_prompt`)

---

## 6. Acceptance Criteria

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | During a 30-second agent streaming response, the user can scroll the chat smoothly | Manual: send complex prompt to Coder, attempt to scroll during response. No visible jank. |
| 2 | During agent tool execution (5+ tools), tab switches complete in <200ms | Manual: send prompt that triggers 5+ tool calls, switch tabs during execution. |
| 3 | Initial "send message" click does not freeze UI for >50ms | Manual: click Send, observe no perceptible freeze before streaming starts. |
| 4 | Streaming text content is correct and complete | Automated: verify final bubble text matches full response (tests in test_streaming.py) |
| 5 | All existing tests pass EXCEPT `test_update_streaming_escapes_html_chars`, which is updated to assert plain-text behavior during streaming (see §2.6). New test `test_end_streaming_escapes_html_in_final_bubble` added. | `pytest -q` — 0 unexpected failures. Two tests' assertion bodies are intentionally changed/added. |
| 6 | No regressions in final bubble formatting | Manual: response with bold/italic/code blocks → final formatted bubble matches pre-fix |
| 7 | Gateway streaming agents also benefit from Fixes 2, 3, 5 | Automated: existing test_streaming tests pass. Fix 2/3/5 changes are internal to update_streaming/_do_text_delta. |

---

## 7. Edge Cases

| Case | Expected behavior | Notes |
|------|------------------|-------|
| **Empty streaming text** (tool-only turn, BUG #21) | Streaming bubble created with empty text, no final bubble rendered | `end_streaming(render=False)` suppresses final bubble. `_do_text_delta` with empty string still calls `update_streaming` — Fix 5's `set_text(" ▍")` works fine with empty text. |
| **Very fast streaming** (>50 tokens/sec) | Throttled to ~20 renders/sec via Fix 3 (50ms outer throttle) + Fix 5's cheap set_text | No dropped frames from excessive rendering. |
| **Very slow streaming** (<5 tokens/sec) | Every token renders (passes 50ms throttle), no visual latency | Final render is always correct — text accumulates before throttle check. |
| **Conversation creation on first send** | `create_conversation(defer_prompt_build=True)` skips the prompt build. `_ensure_system_prompt` runs in background thread via `_run_loop`. The first `on_text_delta` dispatch fires AFTER `_ensure_system_prompt` returns. | Verified against source: `_ensure_system_prompt` call at `_run_loop` line ~795, turn-start signal at line ~800. |
| **Stale project path on loaded conversation** | `_rebuild_conversation_context` still fires synchronously in `send_to_special_agent` (line ~813). This is correct — it fires ONCE per conversation lifetime (when loading from disk with different project path). Not a performance concern. | If the user switches projects frequently, the 300ms rebuild penalty applies each time. Acceptable. |
| **build_system_prompt raises in background thread** | Exception propagates to `_run_loop`'s outer `except Exception` handler (line 1264), which dispatches `_on_error` with the exception message. User sees error bubble. | Handled by existing infrastructure. |
| **Multiple concurrent send_to_special_agent** (user clicks Send twice) | First call creates conversation with `defer_prompt_build=True` + starts `_run_loop`. Second call gets existing conv, `create_conversation` is not called (exists). `_ensure_system_prompt` is a no-op (system_prompt already set). Both `_run_loop` instances run — the first one does the work. The second one's `_run_loop` is a pre-existing issue. | Not new to this fix. Out of scope. |
| **Error during streaming** (LLM timeout after partial text) | `_do_error` (line 1719) calls `end_streaming(session_key)` which finalizes the bubble with whatever text was accumulated. The final bubble is built via `build_role_bubble` with the partial text + the error message formatted as `[Error] ...`. The user sees the partial text plus the error. | Verified: `_do_error` at agent_runtime_handler.py:1719 calls `self._crh.end_streaming()` before rendering the error bubble. |
| **Token bursts** (10+ tokens within 50ms) | Only the first token in the burst triggers `update_streaming`. The remaining tokens' text is accumulated in `_streaming_text` and rendered on the next throttle pass (within 50ms). Visually, the bubble updates in small chunks rather than per-token — standard for chat UIs. | The 50ms outer throttle (Fix 3) coalesces the burst into a single dispatch. The text is always accumulated before the throttle check, so no text is lost. |
| **Fix 3 50ms throttle + Fix 5 set_text interaction** | No conflict. Fix 3 limits outer dispatch to ~20/sec. Fix 5 makes each dispatch cheap (<1ms). The 150ms throttle in `update_streaming` is still respected as well. | Both throttles together: at most ~6.7 `set_text` calls/sec (150ms inner) with the outer 50ms check filtering tokens earlier. |
| **Gateway streaming agents (chat_handler.py path)** | `chat_handler.py:575` calls `update_streaming` directly (already on main thread). Fix 2's inlining and Fix 5's set_text apply transparently — no changes needed to gateway path. | Fix 3's throttle is in `_do_text_delta` (agent_runtime_handler only), which the gateway path doesn't use. Gateway agents won't get Fix 3's pre-filtering but will get Fix 2 and Fix 5 benefits. |
| **force_llm_compact concurrent with _ensure_system_prompt** | `_ensure_system_prompt` holds `self._lock`; `force_llm_compact` holds `self._compaction_lock` (different lock). Both can write `conv.system_prompt` concurrently. The double-check in `_ensure_system_prompt` handles this: it re-reads `conv_now.system_prompt` inside `self._lock` and skips if already set. If `force_llm_compact` writes first, `_ensure_system_prompt` does nothing. If `_ensure_system_prompt` writes first, `force_llm_compact` temporarily augments the prompt (its own write pattern). | Two threads writing the same attribute on the same object is a pre-existing concern. The double-check prevents a partial-write state where both threads interleave. |

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
conversations. This requires passing `defer_prompt_build=True` to
`create_conversation()` — the conversation is registered with an
empty system prompt, and `_ensure_system_prompt` (called from
`_run_loop`) builds it on the background thread. This eliminates
300-500ms of main-thread blocking at the start of each agent turn.
```

### §3 — Component inventory

Update `agent/runtime.py` function list to include `_ensure_system_prompt`.

### §8.6 — Handler pattern

No changes needed — the handler dispatch pattern is unchanged (callbacks still use `GLib.idle_add` for main-thread dispatch).

---

## 9. Spec Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - YES. All function names verified by grep:
     - `create_conversation` → `agent/runtime.py:435`
     - `send_message` → `agent/runtime.py:535`
     - `_run_loop` → `agent/runtime.py:782`
     - `_dispatch` → `agent/runtime.py:387`
     - `_ensure_system_prompt` → new method (verified no existing symbol by that name)
     - `update_streaming` → `chat_render_handler.py:434`
     - `_do_text_delta` → `agent_runtime_handler.py:972`
     - `_do_error` → `agent_runtime_handler.py:1719`
     - `send_to_special_agent` → `agent_runtime_handler.py:733`
     - `build_system_prompt` → `context.py:702`
     - `force_llm_compact` → `runtime.py:1851`
   - `defer_prompt_build` is a new parameter — verified no existing caller of `create_conversation` passes it (all callers use positional args or the existing keyword set).
   - `GLib.idle_add` returns `False` pattern verified in chat_render_handler._dispatch (line 750).

2. **Did I catch all exception types for every function I call?**
   - `build_system_prompt` can raise `OSError`, `json.JSONDecodeError`, `ImportError` (from try/except blocks). The `_ensure_system_prompt` method lets exceptions propagate — they're caught by `_run_loop`'s outer `except Exception` (line 1264). **Correct.**
   - `escape_for_pango` and `format_markdown` are pure string functions — no exceptions (verified in utils/escaping.py and utils/markdown.py).
   - `set_text` on `Gtk.Label` cannot raise.
   - `sb.label.set_text` — `sb` is from `self._streaming_bubbles.get(session_key)`, which could be None. **Mitigation:** `update_streaming` already checks `if session_key not in self._streaming_bubbles: return` at line 448. Safe.

3. **Did I verify key structures, not assume them?**
   - YES. `self._streaming_text` dict structure verified (agent_runtime_handler.py:75: `_streaming_text: dict[str, str] = {}`).
   - `self._streaming_bubbles` dict structure verified (chat_render_handler.py:179: `_streaming_bubbles: dict = {}` — keys are session_key, values are StreamingBubble dataclass).
   - `self._on_agent_start_cb` signature verified (line 80: `Callable[[str], None]` — single arg session_key).
   - `self._lock` is `threading.Lock` (not RLock) — verified at runtime.py line 340.
   - `self._compaction_lock` is separate from `self._lock` — verified at runtime.py (used in `force_llm_compact`).

4. **Did I trace the data flow end-to-end?**
   - YES. See §3 Data Flow above. Traced from `send_to_special_agent` through `_run_loop` → `_dispatch` → `_do_text_delta` → `update_streaming` → label update. Both pre-fix and post-fix flows diagrammed.

5. **Would an implementer who follows this spec exactly produce working code?**
   - YES. Every change is scoped to known line numbers. Code samples are complete (not "pseudo-code"). The implementer only needs to:
     1. Add `defer_prompt_build` parameter to `create_conversation` (runtime.py:435) and conditionalize the `build_system_prompt` call
     2. Add `_ensure_system_prompt` method to AgentRuntime (with BUG #19 identity-check DCL)
     3. Call `self._ensure_system_prompt(session_key)` in `_run_loop` (runtime.py:782) after lock/nil checks
     4. Modify `_do_text_delta` (agent_runtime_handler.py:972) — add throttle check + `import time`
     5. Modify `update_streaming` (chat_render_handler.py:434) — inline `_update`, use `set_text`
     6. Add `defer_prompt_build=True` to `create_conversation` call (agent_runtime_handler.py:~818)
     7. Update test in test_chat_render_handler.py:211 (plain-text assertion)
     8. Add XSS test `test_end_streaming_escapes_html_in_final_bubble`
   - No ambiguous instructions. No "should work" assumptions.

---

## 10. Completion Verification (Rule 10)

### 10.1 Scope Checklist

```
[x] agent/runtime.py — changed (add _ensure_system_prompt + defer_prompt_build param on create_conversation + call in _run_loop)
[x] ui/handlers/agent_runtime_handler.py — changed (add throttle vars, modify _do_text_delta, add defer_prompt_build=True)
[x] ui/handlers/chat_render_handler.py — changed (inline _update, set_text, remove dead _dispatch + closure)
[x] tests/test_chat_render_handler.py — changed (update escaping test, add end_streaming XSS test)
[ ] ui/handlers/feed_handler.py — NOT changed (Fix 4 deferred to Phase 2)
```

### 10.2 Test Suite

After implementation, run:

```bash
python3 -m pytest tests/test_chat_render_handler.py tests/test_agent_runtime_handler.py -v
python3 -m pytest tests/test_agent_runtime.py -v
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

# BUG #13: verify NO _defer_prompt remnants remain
grep -rn '_defer_prompt' agent/ ui/handlers/ tests/
```

Expected:
- `self._dispatch(_update)` — 0 matches
- `set_markup` in streaming path — 0 matches (only in `end_streaming`'s `build_role_bubble` which is correct)
- `set_text` in `update_streaming` — 1 match
- `_defer_prompt` — 0 matches (defensive check: `_defer_prompt` was considered in an earlier draft but never introduced; the final approach uses `defer_prompt_build`)

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
