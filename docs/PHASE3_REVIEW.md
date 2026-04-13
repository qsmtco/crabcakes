# Phase 3 Review — Streaming and Typing Indicators

**Reviewer:** Qaster  
**Date:** 2026-04-12  
**Tests:** 273/273 pass (but no new Phase 3 tests exist)

---

## ✅ What's Correct

- `chat_render_handler.py` — typing state, streaming state, all keyed by session_key
- `chat_bubble.py` — `build_typing_bubble()` and `build_streaming_bubble()` as widget factories
- `chat_handler.py` — event routing: typing → show_typing, delta → start/update_streaming, final → end_streaming
- CSS added to `styles.py` only (`.chat-bubble-pending`, `.typing-dots`)
- ARCHITECTURE.md updated with Phase 3 data flow (Section 4.5)
- `show_typing()` is idempotent (no-op if already showing)
- `start_streaming()` clears existing bubble before creating new one
- `clear_typing()` and `end_streaming()` are idempotent
- All GTK calls dispatched via `GLib.idle_add()` for thread safety
- `end_streaming()` replaces streaming bubble with properly rendered final bubble

---

## ❌ Bugs

### BUG #1: `update_streaming` builds markup from unescaped text (CRITICAL)

**TYPE:** Logic — XSS / Pango injection

**LOCATION:** `ui/handlers/chat_render_handler.py` — `update_streaming()`, inside `_update()`

**REPRODUCTION:**
```python
# If agent streams: "Use <div> for HTML"
# delta_text = "Use <div> for HTML"
# safe = escape_for_pango(delta_text)  → "Use &lt;div&gt; for HTML"
# new_plain = plain + delta_text       → "Use <div> for HTML" (RAW!)
# new_markup = new_plain + "<tt>▍</tt>" → BROKEN Pango markup!
# 'safe' is computed but NEVER USED
```

**ROOT CAUSE:** `safe = escape_for_pango(delta_text)` is computed but the code uses `new_plain` (raw accumulated text) for the Pango markup. If any streamed text contains `<`, `>`, `&`, or `"`, the `set_markup()` call will fail or produce broken rendering.

**FIX:**
```python
def _update():
    from utils.escaping import escape_for_pango
    new_plain = plain + delta_text
    self._streaming_bubbles[session_key] = (container, label, role, new_plain, _bubble)
    escaped = escape_for_pango(new_plain)
    label.set_markup(escaped + "<tt>▍</tt>")
```

**VERIFIED:** NO

---

### BUG #2: `start_streaming()` called on every delta — destroys and recreates bubble (CRITICAL)

**TYPE:** Logic

**LOCATION:** `ui/handlers/chat_handler.py:165-174` — `_handle_streaming_delta()`

**REPRODUCTION:**
```python
# _handle_streaming_delta calls start_streaming() on EVERY delta event:
def _handle_streaming_delta(self, session_key, delta_text):
    self._chat_render_handler.clear_typing(session_key)
    chat_box = self._mc.get_chat_box()
    if chat_box is not None:
        self._chat_render_handler.start_streaming(session_key, chat_box, "Agent")  # EVERY DELTA!
    self._chat_render_handler.update_streaming(session_key, delta_text)

# start_streaming() checks if bubble exists → calls end_streaming() → creates new bubble
# end_streaming() removes old bubble and renders it as FINAL
```

**ROOT CAUSE:** Every delta event:
1. Calls `start_streaming()`
2. `start_streaming()` sees existing bubble → calls `end_streaming()`
3. `end_streaming()` removes the streaming bubble and renders it as a final message
4. Creates a brand new streaming bubble
5. Appends just this one delta to the new bubble

**Expected:** One streaming bubble that grows incrementally with each delta.
**Actual:** A series of final-rendered single-word bubbles, each followed by a new streaming bubble with just the latest delta.

**FIX:**
```python
def _handle_streaming_delta(self, session_key, delta_text):
    if self._chat_render_handler is None:
        return
    self._chat_render_handler.clear_typing(session_key)
    # Only start streaming if not already streaming
    if session_key not in self._chat_render_handler._streaming_bubbles:
        chat_box = self._mc.get_chat_box()
        if chat_box is not None:
            self._chat_render_handler.start_streaming(session_key, chat_box, "Agent")
    self._chat_render_handler.update_streaming(session_key, delta_text)
```

Or better: add a public `is_streaming(session_key)` method to `ChatRenderHandler` instead of reaching into private state.

**VERIFIED:** NO

---

### BUG #3: Typing/streaming indicators appear in wrong tab (MEDIUM)

**TYPE:** Logic

**LOCATION:** `ui/handlers/chat_handler.py:157-163` (`_handle_typing`) and `ui/handlers/chat_handler.py:165-174` (`_handle_streaming_delta`)

**REPRODUCTION:**
```python
# User is viewing Agent A's tab
# Agent B starts typing
# _handle_typing("agent:B") calls self._mc.get_chat_box()
# get_chat_box() returns CURRENT page's chat box → Agent A's box!
# Typing indicator appears in Agent A's tab
```

**ROOT CAUSE:** Both `_handle_typing()` and `_handle_streaming_delta()` use `self._mc.get_chat_box()` which returns the **current** tab's chat box, not the session_key's tab. Multi-agent scenarios will show indicators in the wrong place.

**FIX:** Look up the correct chat box by session_key. `MainContent.get_chat_box()` already accepts a `page_index` parameter. Need a method like `get_chat_box_for_session(session_key)` that finds the right page.

**VERIFIED:** NO

---

### BUG #4: No Phase 3 tests (MEDIUM)

**TYPE:** Missing tests

**LOCATION:** `tests/test_chat_render_handler.py` — no new tests added

The plan specifies tests for:
- `show_typing()` → creates bubble, source_id tracked
- `clear_typing()` → removes bubble, source_id cancelled
- `start_streaming()` → creates streaming bubble
- `update_streaming()` → text appended correctly
- `end_streaming()` → cursor removed
- Double `start_streaming()` → idempotent

None of these exist. The Phase 3 code is entirely untested.

**VERIFIED:** NO

---

## ❌ Cleanup

### `fix_streaming.py` — Leftover patch script

**LOCATION:** `/home/q/projects/crabcakes/fix_streaming.py`

A one-off Python script used to patch `chat_render_handler.py`. Should be deleted and not committed.

---

## Summary

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | `update_streaming` uses unescaped text for Pango markup | **CRITICAL** | Bug |
| 2 | `start_streaming` called every delta, destroys bubble | **CRITICAL** | Bug |
| 3 | Typing/streaming in wrong tab for multi-agent | MEDIUM | Bug |
| 4 | No Phase 3 tests | MEDIUM | Missing tests |
| 5 | `fix_streaming.py` leftover | LOW | Cleanup |

**Bugs #1 and #2 are showstoppers.** Together they mean:
- Any streamed text with HTML chars will break Pango rendering (#1)
- Streaming creates a new bubble per delta instead of growing one bubble (#2)

Both need to be fixed before Phase 3 is functional.
