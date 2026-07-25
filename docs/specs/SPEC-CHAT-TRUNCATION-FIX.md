# SPEC: Chat Display Truncation Fix — Missing Label Width Constraints

**Date:** 2026-07-21
**Author:** Supervisor
**Status:** Draft — for implementation
**Priority:** High
**Depends on:** ARCHITECTURE.md (handler pattern §3.16, CSS in styles.py §3.5)
**Target branch:** main

> Architecture compliance statement: This fix modifies `utils/gtk_safe_link.py` (pure utility) only. No handler logic changes. No CSS changes needed (existing chat bubble CSS is sufficient).

---

## 1. Overview

### 1.1 Problem
Long agent/supervisor responses (≥10k chars) are truncated in the chat UI. Terminal logs confirm full text was generated and sent (`text_len=32825`, `text_len=2011`), but only the first few lines are visible in the chat bubble.

**GTK Critical warning observed:**
```
GtkBox 0x1c1466a0 reports a minimum width of 186, but minimum width for height of 1048576 is 235. Expect overlapping widgets.
```

`1048576 = 1024 * 1024` — Pango's "unbounded" width indicator (1024 device units in Pango units). The label's natural width is unbounded, causing layout explosion.

### 1.2 Root Cause
The chat bubble's outer `container` uses `set_halign(Gtk.Align.START)` (agent) / `set_halign(Gtk.Align.END)` (user), causing it to shrink to children's natural width. The children include a `Gtk.Label` from `make_safe_label()` with:
- `set_wrap(True)`
- `set_wrap_mode(Pango.WrapMode.WORD_CHAR)`
- **NO `set_max_width_chars()` call**

The label's natural width becomes unbounded (Pango reports 1048576 Pango units = 1024 device units = "infinite"). Layout pass either renders off-screen or clips, causing visible truncation.

### 1.3 Solution
Add `set_max_width_chars(120)` to `make_safe_label()` in `utils/gtk_safe_link.py` after `set_wrap(True)`.

**Note:** Code block labels in `_build_code_from_markup()` (ui/views/chat_bubble.py:387) already have `set_max_width_chars(120)` — this fix only applies to the main chat text labels via `make_safe_label()`.

---

## 2. Discovery

### 2.1 Files Read

| File | Key Finding |
|------|-------------|
| `utils/gtk_safe_link.py` (lines 76-140) | `make_safe_label()` creates `Gtk.Label`, sets `wrap=True`, `wrap_mode=Pango.WrapMode.WORD_CHAR`, `use_markup=True`, `selectable=True`, `xalign=0`. **No `set_max_width_chars()`**. |
| `ui/views/chat_bubble.py` (lines 261-270) | `build_role_bubble()` creates `container` with `halign=START/END` (agent/user). Inner `bubble` box has no width constraint. |
| `ui/views/chat_bubble.py` (line 387) | `_build_code_from_markup()` **already has** `code_label.set_max_width_chars(120)` — already fixed for code blocks. |
| `ui/views/chat_bubble.py` (lines 626-640) | `_build_text_segment()` uses `make_safe_label()` — **affected by the bug**. |

### 2.2 Verification

```bash
# Confirm the bug exists
grep -n "set_max_width_chars" utils/gtk_safe_link.py
# Returns nothing — function doesn't call it

# Confirm code blocks already fixed
grep -n "set_max_width_chars" ui/views/chat_bubble.py
# Returns line 387: code_label.set_max_width_chars(120)
```

---

## 3. Changes by File

### 3.1 `utils/gtk_safe_link.py` — MODIFY

**Function:** `make_safe_label()`

**Change:** After `label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)`, add:

```python
# Bound the natural width — prevents Pango unbounded-width explosion
# which causes truncation of long messages in the chat viewport.
label.set_max_width_chars(120)
```

**Full modified block (lines ~110-120):**

```python
    if wrap:
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # Bound the natural width — prevents Pango unbounded-width explosion
        # which causes truncation of long messages in the chat viewport.
        label.set_max_width_chars(120)
```

**Parameters:** No new parameters needed. The `max_width_chars` value is hardcoded to 120 to match the code block implementation (line 387 of chat_bubble.py).

**Verification:**
```bash
python3 -c "
from utils.gtk_safe_link import make_safe_label
label = make_safe_label('Test')
print('max_width_chars:', label.get_max_width_chars())
"
# Expected output: max_width_chars: 120
```

---

### 3.2 Files NOT Changed

| File | Reason |
|------|--------|
| `ui/views/chat_bubble.py` | Code blocks already fixed (line 387). Chat bubble container alignment is intentional for visual design. |
| `ui/handlers/chat_render_handler.py` | Uses `make_safe_label()` — will automatically get the fix. |
| `ui/styles.py` | Existing chat bubble CSS is sufficient; no width constraints needed in CSS. |
| `ui/handlers/chat_handler.py` | No changes needed — sends full text, rendering handles layout. |

---

## 4. Data Flow

```
Agent Response (32k chars)
    → chat_handler.on_send() / chat_runtime_handler
    → chat_render_handler.render_async()
    → _assemble_from_processed()
    → make_safe_label(text)  ← FIX APPLIED HERE
    → Gtk.Label with max_width_chars=120
    → chat_bubble.build_role_bubble()
    → chat_box.append(bubble)
    → UI renders full wrapped text within viewport
```

---

## 5. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `utils/gtk_safe_link.py` | Modified | +3 | Low |
| **Total** | | **+3 net** | |

---

## 6. Implementation Order

### Phase 1 — Core Fix (15 mins)
1. Edit `utils/gtk_safe_link.py` `make_safe_label()` to add `label.set_max_width_chars(120)` after `set_wrap_mode()`

**Verification:**
```bash
# Test the function directly
python3 -c "
from utils.gtk_safe_link import make_safe_label
label = make_safe_label('Test')
print('max_width_chars:', label.get_max_width_chars())
assert label.get_max_width_chars() == 120
"

# Test with very long text (no GTK display needed)
python3 -c "
from utils.gtk_safe_link import make_safe_label
long_text = 'x' * 50000
label = make_safe_label(long_text)
print('max_width_chars:', label.get_max_width_chars())
"
```

### Phase 2 — Integration Test (15 mins)
1. Run `python3 main.py`
2. Open a project, start a conversation
2. Send a message that triggers a long agent response (≥10k chars)
3. Verify:
   - No `Gtk-CRITICAL` warning about `minimum width for height of 1048576`
   - Full text is visible and wrapped in the bubble
   - Bubble fits within chat viewport (no horizontal overflow)
   - Scroll works vertically if needed

---

## 7. Acceptance Criteria

- [ ] No `Gtk-CRITICAL` warning about `minimum width for height of 1048576`
- [ ] 32k-char agent response fully visible in chat bubble (wrapped)
- [ ] 2k-char supervisor response fully visible
- [ ] Bubble fits within chat viewport width (no horizontal scroll)
- [ ] Vertical scroll works for long messages
- [ ] Code blocks still render correctly (already fixed)
- [ ] No regression in existing tests

---

## 8. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Empty string | Label renders empty, no crash |
| Single very long word (no spaces) | `WORD_CHAR` wrap breaks at character boundaries |
| Markdown with very long URLs | Wraps at character boundary within URL |
| Mixed short/long paragraphs | Each paragraph wraps independently |
| Unicode (CJK, emoji) | Character count approximates visual width reasonably |

---

## 9. ARCHITECTURE.md Updates Required

None — this is a pure utility fix in `utils/` layer, no architectural changes.

---

## 10. Verification Commands

```bash
# Unit test
python3 -c "
from utils.gtk_safe_link import make_safe_label
label = make_safe_label('Test')
assert label.get_max_width_chars() == 120, f'Expected 120, got {label.get_max_width_chars()}'
print('OK: max_width_chars = 120')
"

# Integration test (manual)
python3 main.py
# 1. Open project
# 2. Ask agent for long response
# 3. Verify full text visible, no GTK critical warnings
```

---

**End of Spec**