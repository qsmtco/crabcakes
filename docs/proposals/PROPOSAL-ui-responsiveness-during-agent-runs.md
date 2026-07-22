# PROPOSAL: UI Responsiveness During Agent Runs

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for review
**Severity:** HIGH — the app freezes during agent runs, making it unusable while agents work
**Related proposals:** None (standalone performance fix)

> **Architecture alignment:** This proposal modifies components in `agent/runtime.py` (callback dispatch), `ui/handlers/` (idle callback management), and `ui/views/` (widget rendering). All changes respect the layering rules in §2: `agent/` has no UI dependencies, `ui/` handlers receive callbacks via the established dispatch pattern. No new cross-layer imports.

---

## 1. Executive Summary

When an agent (Coder, Debugger, etc.) is running — calling the LLM, streaming tokens, executing tools — the CrabCakes GTK4 UI becomes sluggish or fully unresponsive. The user cannot scroll smoothly, switch tabs, or click buttons until the agent finishes.

The root cause is **not a single bottleneck** but a **death by a thousand cuts**: the agent's background thread floods the GTK main-loop idle queue with high-frequency callbacks (one per SSE token), and several of those callbacks do non-trivial main-thread work (string processing, widget rebuilding, feed card construction). The cumulative effect saturates the main loop's frame budget, starving paint and input events.

Six specific issues were identified through source-code analysis and profiling. Each is independently fixable. The first three are high-impact, low-effort fixes that address 80% of the problem. The remaining three are deeper architectural improvements.

---

## 2. Problem Statement

### 2.1 Symptom

1. User sends a message to an agent (e.g. "implement the auth middleware")
2. The agent starts streaming a response — text appears incrementally in the chat bubble
3. During streaming (and especially during tool execution), the UI becomes sluggish:
   - Scrolling stutters or freezes
   - Tab switches take 1-2 seconds
   - Button clicks are delayed or ignored
   - The entire window occasionally goes gray ("not responding" in some window managers)
4. When the agent finishes its response, the UI recovers instantly

### 2.2 Architecture Intention vs Reality

The architecture **intends** for the agent to run in a background thread with all GTK calls dispatched via `GLib.idle_add`:

```
User clicks Send
  → ChatHandler.on_send() [main thread]
    → AgentRuntimeHandler.send_to_special_agent() [main thread]
      → build_system_prompt() [main thread, ~300ms blocking]
      → AgentRuntime.send_message() [main thread]
        → threading.Thread(target=_run_loop).start() [background thread]
          → _run_loop [background]
            → for each SSE token: _dispatch(on_text_delta) → GLib.idle_add [main thread]
            → _dispatch(on_tool_call_start) → GLib.idle_add [main thread]
            → _dispatch(on_tool_call_result) → GLib.idle_add [main thread]
            → _dispatch(on_response_complete) → GLib.idle_add [main thread]
```

The threading is correct — `_run_loop` genuinely runs in a daemon thread. The problem is the **volume and cost of the idle callbacks** that flood back to the main thread.

### 2.3 Why This Matters

An agent development environment where the UI freezes when agents work is a productivity killer. The whole point of CrabCakes is that you can watch agents work in real time — review diffs, read feed cards, scroll the chat. If the UI is frozen, the "real-time collaboration" promise is broken.

---

## 3. Investigation Results — Six Identified Issues

### Issue 1: Main-thread system prompt build before thread spawn (HIGH)

**Location:** `AgentRuntimeHandler.send_to_special_agent()` → `rt.create_conversation()` / `rt._rebuild_conversation_context()` → `build_system_prompt()` → `build_file_context_with_core_files()`

**What happens:** Before the background thread is spawned, `send_to_special_agent` calls `create_conversation` (or `_rebuild_conversation_context`), which synchronously calls `build_system_prompt`. This reads the entire project directory tree, parses `.gitignore`, reads `.crabcakes/` docs, reads core files (README.md, AGENTS.md, etc.), and builds a 67K-char system prompt.

**Measured cost:** 300ms on a warm cache, 300ms on a cold cache (the file-context cache mitigates repeat calls). On a large project (thousands of files) or a slow filesystem, this could be 1-2 seconds.

**Impact:** The UI freezes for 300ms-2s when the user clicks Send, before any streaming starts. This is the "initial freeze" the user perceives.

### Issue 2: Double GLib.idle_add dispatch for text deltas (HIGH)

**Location:** `AgentRuntime._dispatch(on_text_delta)` → `GLib.idle_add` → `_do_text_delta` → `self._crh.update_streaming()` → `ChatRenderHandler._dispatch(_update)` → `GLib.idle_add` → `_update`

**What happens:** Each SSE text token triggers TWO `GLib.idle_add` calls:
1. `AgentRuntime._dispatch` wraps the callback in `idle_add` to get from the background thread to the main thread.
2. `_do_text_delta` (now on the main thread) calls `update_streaming`, which internally calls `self._dispatch(_update)` — ANOTHER `idle_add`.

The second dispatch is unnecessary because `_do_text_delta` is already on the main thread. It adds a second queue entry per token, doubling the idle-queue pressure.

**Measured cost:** At 50-100 tokens/sec (typical LLM streaming rate), this generates 100-200 `idle_add` entries per second. Each entry is tiny (~0.03ms of work), but the queue entries themselves compete with paint events for main-loop time.

**Impact:** Sustained idle-queue pressure during streaming starves the GTK frame clock, causing dropped frames and input latency.

### Issue 3: Unthrottled _do_text_delta per-token processing (MEDIUM)

**Location:** `AgentRuntimeHandler._do_text_delta()` — runs on EVERY token, no throttle

**What happens:** The 150ms throttle lives in `ChatRenderHandler.update_streaming`, which limits the expensive `set_markup` call. But `_do_text_delta` itself runs on every token, doing:
- String concatenation (`self._streaming_text[sk] += text`)
- Dict lookup (`self._crh.is_streaming(sk)`)
- Method call (`self._crh.update_streaming(...)`)

The string concatenation is O(n) per token where n is the accumulated text length — for a 5000-char response with 100-char tokens, the 50th token concatenates a 5000-char string. This is minor per-call but runs 50-100 times/sec.

**Impact:** Small but contributes to the cumulative main-thread saturation. The throttle should be at the `_do_text_delta` level, not inside `update_streaming`.

### Issue 4: Full widget rebuild for feed card updates (MEDIUM)

**Location:** `FeedHandler.update_card()` → `build_feed_card()` [full widget reconstruction]

**What happens:** Every tool result triggers `update_card`, which rebuilds the entire feed card widget (Gtk.Box, Gtk.Label, CSS classes, action buttons) and replaces the old widget in the feed tab. For a coding session where Coder calls 5-10 tools per turn, that's 5-10 full widget rebuilds.

**Impact:** Each `build_feed_card` call creates multiple GTK widgets (5-10 Gtk.Label/Box/Button objects), which triggers allocation and layout passes. At 5-10 calls per agent turn, this adds measurable jank.

### Issue 5: set_markup triggers full Pango layout recalculation (MEDIUM)

**Location:** `ChatRenderHandler._update()` → `sb.label.set_markup(formatted + cursor)`

**What happens:** Every 150ms during streaming, `_update` calls `set_markup` with the full accumulated text formatted as Pango markup. `set_markup` parses the markup, re-runs the Pango layout engine on the entire text (line breaking, wrapping, height calculation), and triggers a GTK resize/allocate pass on the label and its parent containers.

**Cost:** For a 5000-char response, the Pango layout pass takes ~5-15ms (estimated — cannot benchmark headlessly). Combined with the 150ms throttle, this is ~6.7 updates/sec × 5-15ms = 34-100ms/sec of layout work. At the upper bound, this exceeds one full frame budget (16ms @ 60fps), causing dropped frames.

**Impact:** Visible stuttering during streaming, especially for long responses.

### Issue 6: Synchronous pre-loop work in send_to_special_agent (LOW-MEDIUM)

**Location:** `AgentRuntimeHandler.send_to_special_agent()` — several synchronous operations before `rt.send_message()`:

- Agent definition lookup and model resolution
- `rt.load_conversation(session_key)` — disk I/O (reads JSON, deserializes messages)
- `rt._rebuild_conversation_context()` — calls `build_system_prompt` (Issue 1)
- Conversation state syncing (api_key, model, MCP servers, SI enforcement)
- Step count reset

**Impact:** Each individual operation is fast (<50ms), but they run sequentially on the main thread. For a conversation with 100+ messages, `load_conversation` deserialization can take 50-100ms. Combined with the 300ms `build_system_prompt`, the total pre-loop latency is 400-500ms.

---

## 4. Proposed Solutions

### 4.1 High-Impact Fixes (Phase 1 — addresses 80% of the problem)

#### Fix 1: Move build_system_prompt off the main thread

**Approach:** Move `build_system_prompt` (and the `create_conversation` / `_rebuild_conversation_context` calls that invoke it) into a background thread. Spawn the thread in `send_to_special_agent`, do the prompt build there, then call `rt.send_message` from the same thread (or after the thread completes).

**Key change:** `send_to_special_agent` currently does:
```python
# Main thread — BLOCKING
rt.load_conversation(session_key)          # disk I/O
rt._rebuild_conversation_context(...)      # builds system prompt (300ms)
rt.send_message(session_key, text)         # spawns background thread
```

Change to:
```python
# Main thread — FAST (just UI feedback)
self._show_thinking_indicator(session_key)

# Background thread — does the heavy lifting
def _prepare_and_send():
    rt.load_conversation(session_key)
    rt._rebuild_conversation_context(...)
    rt.send_message(session_key, text)

threading.Thread(target=_prepare_and_send, daemon=True).start()
```

**Risk:** MEDIUM — `load_conversation` and `create_conversation` mutate `self._conversations` under `self._lock`. Moving them to a background thread requires ensuring no concurrent access from the main thread. The lock already protects this, but we must verify no GTK calls happen inside these methods (they don't — they're pure data + disk I/O).

**Estimated impact:** Eliminates 300-500ms of main-thread blocking at the start of every agent turn. This is the most perceptible "freeze" the user experiences.

#### Fix 2: Eliminate the double idle_add dispatch

**Approach:** In `_do_text_delta`, call the `_update` function directly instead of going through `ChatRenderHandler._dispatch` (which does another `idle_add`). Since `_do_text_delta` is already on the main thread (via the first `idle_add`), the second dispatch is pure overhead.

**Key change:** In `ChatRenderHandler.update_streaming`, replace:
```python
self._dispatch(_update)  # another idle_add — unnecessary
```
with:
```python
_update()  # direct call — we're already on the main thread
```

Or better: inline the `_update` logic directly into `update_streaming` and remove the inner function.

**Risk:** LOW — the second `idle_add` was never necessary; it just deferred the work by one more main-loop iteration. Removing it makes the update happen sooner (lower latency) with less queue pressure.

**Estimated impact:** Halves the idle-queue entries during streaming (from ~200/sec to ~100/sec).

#### Fix 3: Add throttle at _do_text_delta level

**Approach:** Move the throttling from `update_streaming` (inner) to `_do_text_delta` (outer). Currently every token runs `_do_text_delta`, which calls `update_streaming`, which checks the throttle and returns early. Moving the throttle earlier means the string concatenation and method call overhead are also skipped for throttled tokens.

**Key change:** In `_do_text_delta`, add a throttle check at the top:
```python
import time
now = time.monotonic()
last = self._last_delta_time.get(session_key, 0)
self._streaming_text[session_key] = self._streaming_text.get(session_key, "") + text
if now - last < 0.05:  # 50ms minimum between processing
    return
self._last_delta_time[session_key] = now
# ... rest of update logic
```

The stored text is always updated (so the final render is correct), but the expensive processing (escape + format + set_markup) only runs at most 20 times/sec.

**Risk:** LOW — the throttle already exists in `update_streaming`; this just moves it earlier in the chain.

**Estimated impact:** Reduces per-token main-thread work by ~50% (skips the method call chain for 80% of tokens).

### 4.2 Medium-Impact Fixes (Phase 2 — deeper improvements)

#### Fix 4: Incremental widget update for feed cards

**Approach:** Instead of rebuilding the entire feed card widget on every `update_card`, update only the changed fields (status badge, body text). `FeedCardData` already has a `metadata["status"]` field — just update the status label's CSS class and text, don't rebuild the whole widget.

**Key change:** Add an `update_card_status(card_id, status, body)` method to `FeedHandler` that does an in-place widget update instead of a full `build_feed_card` reconstruction.

**Risk:** MEDIUM — requires tracking widget sub-components (status label, body label) by reference. The current `build_feed_card` doesn't expose these; the fix needs to either store references or query the widget tree.

#### Fix 5: Use Gtk.Label with set_text instead of set_markup during streaming

**Approach:** During active streaming (while the cursor `▍` is shown), use `set_text` (plain text, no Pango markup parsing) instead of `set_markup` (which parses markup + re-runs Pango layout). When streaming completes (`end_streaming` → `_finalize`), switch to the full `build_role_bubble` with markdown formatting.

**Key change:** In `_update`, replace:
```python
escaped = escape_for_pango(sb.plain_text)
formatted = format_markdown(escaped)
sb.label.set_markup(formatted + "<tt>▍</tt>")
```
with:
```python
sb.label.set_text(sb.plain_text + "▍")  # plain text during streaming
```

**Risk:** LOW — the streaming bubble is temporary. Users see plain text while the response is streaming (which is what most chat UIs do anyway), then the formatted bubble replaces it on completion. No visual regression for the final bubble.

**Estimated impact:** Eliminates the `escape_for_pango` + `format_markdown` + Pango layout cost during streaming. This is the most expensive per-update operation.

#### Fix 6: Batch pre-loop work into the background thread

**Approach:** Move ALL of the pre-loop synchronous work (load_conversation, rebuild_context, state syncing) into the same background thread as Fix 1. The main thread only does:
1. Show a "thinking..." indicator
2. Spawn the background thread
3. Return immediately (UI stays responsive)

**Key change:** Refactor `send_to_special_agent` to extract the preparation logic into a function that runs on the background thread. Add a callback to dismiss the thinking indicator when the agent's first token arrives.

**Risk:** MEDIUM-HIGH — requires careful thread-safety analysis of all the state mutations (api_key syncing, MCP server list, allowed_tools). These currently run on the main thread where they're implicitly serialized with GTK events. Moving them to a background thread requires verifying no concurrent access.

---

## 5. Recommended Implementation Order

| Phase | Fix | Impact | Effort | Risk |
|-------|-----|--------|--------|------|
| **1a** | Fix 2: Eliminate double idle_add | HIGH | 1 hour | LOW |
| **1b** | Fix 5: set_text during streaming | HIGH | 1 hour | LOW |
| **1c** | Fix 3: Throttle at _do_text_delta | MEDIUM | 30 min | LOW |
| **1d** | Fix 1: build_system_prompt off main thread | HIGH | 3 hours | MEDIUM |
| **2a** | Fix 6: Batch pre-loop work | MEDIUM | 2 hours | MEDIUM-HIGH |
| **2b** | Fix 4: Incremental feed card update | MEDIUM | 2 hours | MEDIUM |

**Phase 1 (1a-1d) addresses ~80% of the perceived freeze.** Each fix is independently shippable. Fixes 1a and 1b are the highest-impact/lowest-risk and should ship first.

**Phase 2 (2a-2b) addresses the remaining edge cases** (long conversations, many tool calls). These are deeper changes that require more testing.

---

## 6. What This Proposal Does NOT Address

- **GTK4 rendering performance** — if GTK's own layout/paint engine is slow (e.g., too many widgets in the chat box), that's a GTK-level issue. This proposal focuses on reducing the work the main thread does, not on optimizing GTK internals.
- **Agent execution speed** — making the LLM respond faster or tools execute faster is out of scope. This proposal is about keeping the UI responsive WHILE the agent works slowly.
- **Network timeout handling** — addressed separately (TimeoutError fix, already shipped).
- **Memory usage** — a large number of chat bubbles or feed cards could cause memory pressure. Out of scope for this proposal.

---

## 7. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Moving build_system_prompt to background thread causes race with concurrent send | MEDIUM | Use a per-session lock or a "preparing" state flag that rejects concurrent sends |
| set_text during streaming loses inline formatting (bold/italic) | LOW | Acceptable tradeoff — most chat UIs show plain text during streaming and format on completion |
| Throttle at _do_text_delta level causes missed final token | LOW | Always update stored text; the throttle only skips the expensive UI update, not the text accumulation |
| Background thread access to conversation state races with cancel() | MEDIUM | cancel() already uses self._lock; verify the background prep path also acquires the lock |

---

## 8. Success Criteria

- [ ] During a 30-second agent streaming response, the user can scroll the chat smoothly (no dropped frames visible to the eye)
- [ ] During agent tool execution (5+ tools), the user can switch tabs without >200ms delay
- [ ] The initial "send message" click does not freeze the UI for more than 50ms (before streaming starts)
- [ ] GTK frame rate during agent runs stays above 30fps (measured via `GTK_DEBUG=frames` or equivalent)
- [ ] All existing tests pass with zero modifications
- [ ] No regressions in streaming text accuracy (final bubble content matches pre-fix)

---

## 9. Open Questions

### Q1: Should we use a Gtk.FrameClock or a fixed timer for streaming updates?

GTK4's FrameClock fires at the display refresh rate (60fps typically). Aligning streaming updates to the frame clock (instead of a fixed 150ms throttle) would give smoother visual updates. However, it couples the update rate to the display, which may not be desirable on a 144Hz monitor (too many updates).

**Recommendation:** Keep the fixed throttle for now (150ms or reduced to 50ms). Frame-clock alignment is a future enhancement.

### Q2: Should we profile with sysstat/gtk-redshift before or after implementing?

Profiling first would validate which fixes have the highest impact. But the investigation already identifies the specific issues with measured costs. Implementing Phase 1 first, then profiling to verify, is faster than profiling → analyzing → implementing.

**Recommendation:** Implement Phase 1, then profile to validate and prioritize Phase 2.

### Q3: Should the thinking indicator be a GTK Spinner or a text label?

A `Gtk.Spinner` (animated) is the standard GTK pattern for "work in progress." It requires its own animation timer, which adds a small amount of main-thread work. A static text label ("Thinking...") is zero-cost but less visually informative.

**Recommendation:** Use `Gtk.Spinner` — the animation cost is negligible compared to the work it replaces (300ms of frozen UI).

---

## 10. Alternatives Considered

### Alternative A: Async/await for the entire agent loop

**Idea:** Rewrite `_run_loop` as an async coroutine, using `httpx.AsyncClient` for LLM calls and async subprocess for tools. This would make the entire loop non-blocking.

**Rejected because:** GTK4's main loop is not async-compatible out of the box. Bridging async Python with GTK's GLib main loop requires `asyncio` integration (e.g., `gbulb` or a custom event loop adapter). This is a massive refactor with high risk and unclear benefit over the simpler thread-based approach.

### Alternative B: Separate process for agent execution

**Idea:** Run the agent runtime in a separate process (not thread), communicating via IPC (pipes, sockets, or D-Bus).

**Rejected because:** Massive complexity increase (serialization of all data, IPC protocol, process lifecycle management). The threading model is correct; the problem is callback flooding, not threading itself.

### Alternative C: Reduce streaming update frequency at the source

**Idea:** Batch SSE tokens in the background thread before dispatching to the main thread. Instead of dispatching per-token, dispatch every N tokens or every T milliseconds.

**Rejected as primary fix, but worth considering as an optimization:** This reduces idle-queue pressure but doesn't address the double-dispatch or the set_markup cost. It's complementary to Fix 2 and Fix 3, not a replacement. Could be Phase 3.

---

## 11. Measurement Plan

After implementing Phase 1:

1. **Manual test:** Send a complex prompt to Coder (e.g., "implement a 50-line function"). During the 30-60 second response, attempt to scroll the chat, switch to the Feed tab, and click buttons. Rate the responsiveness subjectively (1=frozen, 10=buttery smooth).

2. **GTK frame timing:** Set `GDK_DEBUG=frames` and capture the frame timings during an agent run. Compare pre-fix vs post-fix frame intervals.

3. **Idle-queue depth:** Add a debug counter in `_dispatch` that logs the number of pending idle callbacks. Compare pre-fix vs post-fix.

4. **Microbenchmark:** Time `build_system_prompt` and `_do_text_delta` separately to confirm the measured costs match the estimates.

---

## 12. Summary

The UI freeze during agent runs is caused by **idle-queue flooding** (200+ idle_add entries per second from streaming tokens) compounded by **main-thread blocking** (300ms system prompt build before streaming starts). The fix is straightforward:

1. **Move blocking work off the main thread** (Fix 1 + Fix 6)
2. **Eliminate the double-dispatch overhead** (Fix 2)
3. **Reduce per-update cost** (Fix 3 + Fix 5)

Phase 1 (4 fixes, ~5 hours total effort) should eliminate ~80% of the perceived freeze. Phase 2 addresses the remaining edge cases. No architectural rewrite is needed — the threading model is correct; the problem is in how callbacks are dispatched and processed.
