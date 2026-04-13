# Phase 4 Review — Special Event Cards

**Reviewer:** Qaster  
**Date:** 2026-04-12  
**Tests:** 284 pass (regression from 287 — 5 tests deleted)

---

## ✅ What's Correct

- **Widget factories** in `chat_bubble.py`: `create_file_card`, `create_edit_card`, `create_tool_card`, `create_error_bubble` — all properly structured
- **Handler routing** in `chat_handler.py`: `_handle_special_event()` dispatches to `render_event_card()` based on event type
- **`render_event_card()`** in `chat_render_handler.py`: clean factory dispatch with fallback for unknown types
- **CSS** in `styles.py`: colored left borders for each event type, error gets red background tint
- **Thread safety**: `render_event_card()` uses `self._dispatch()` for GTK calls
- **Views don't import handlers**: ✅
- **`window.py` not modified**: handler already has `ChatRenderHandler` reference, no new wiring needed ✅
- **Pango escaping**: all user content passed through `escape_for_pango()` ✅
- **Selectability**: event card content is selectable ✅
- **5 Phase 4 tests** pass: file_read, edit_proposal, tool_call, error, unknown type fallback

---

## ❌ Bugs

### BUG #1: `_handle_special_event` uses wrong chat box (MEDIUM)

**LOCATION:** `ui/handlers/chat_handler.py:237`

```python
chat_box = self._mc.get_chat_box()  # ← CURRENT tab, not target_tab's tab!
```

Same as Phase 3 Bug #3. If user is viewing Agent A's tab and Agent B sends a `tool_call` event, the card appears in Agent A's tab.

**FIX:**
```python
chat_box = self._mc.get_chat_box_for_session(target_tab)
```

---

### BUG #2: 5 tests deleted (REGRESSION)

**LOCATION:** `tests/test_chat_render_handler.py`

Deleted tests:
- `test_markdown_italic_converted` — Phase 1 formatting
- `test_markdown_inline_code_conported` — Phase 1 formatting
- `test_empty_text` — edge case
- `test_xss_prevention` — security
- `test_sync_allows_different_session_keys` — reentrancy

These should be restored. Net test count dropped from 287→284.

---

## ❌ Architecture Violations

### VIOLATION #1: ARCHITECTURE.md not updated (Section 0)

**LOCATION:** `docs/ARCHITECTURE.md` — no changes in diff

Section 0 requires every code change to update ARCHITECTURE.md. Phase 4 adds:
- New public methods: `render_event_card()` on `ChatRenderHandler`
- New widget factories: `create_file_card`, `create_edit_card`, `create_tool_card`, `create_error_bubble`
- New event routing: `_handle_special_event()` in `ChatHandler`
- New CSS classes: `.bubble-file-read`, `.bubble-edit-proposal`, `.bubble-tool-call`, `.bubble-error`, `.bubble-thinking`, `.bubble-streaming`
- New event types handled: `file_read`, `edit_proposal`, `tool_call`, `error`, `thinking`

None of these are documented in ARCHITECTURE.md.

---

## Summary

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | `_handle_special_event` uses current tab's chat box | MEDIUM | Bug |
| 2 | 5 tests deleted (287→284 regression) | MEDIUM | Regression |
| 3 | ARCHITECTURE.md not updated | HIGH | Architecture violation |

**The code itself is solid.** Event card factories are clean, properly escaped, thread-safe, and tested. The three issues above need fixing before commit.
