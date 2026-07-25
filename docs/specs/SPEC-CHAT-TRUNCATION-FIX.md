# SPEC: Chat Display Truncation Fix — Missing Label Width Constraints

**Date:** 2026-07-21
**Author:** Supervisor
**Status:** Draft — for implementation
**Priority:** High
**Depends on:** ARCHITECTURE.md (handler pattern §3.16, CSS in styles.py §3.5)
**Target branch:** main

> Architecture compliance statement: This fix modifies `utils/gtk_safe_link.py` (pure utility) and `ui/views/chat_bubble.py` (pure view). No handler logic changes. CSS in `ui/styles.py` via `add_css_class()` only.

---

## 1. Overview

### 1.1 Problem
Long agent/supervisor responses (≥10k chars) are truncated in the chat UI. The terminal logs confirm full text was generated and sent (`text_len=32825`, `text_len=2011`), but only the first few lines are visible in the chat bubble.

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

The label's natural width becomes unbounded (Pango reports 1048576 Pango units = infinite). The layout pass either renders the label off-screen or clips it, causing visible truncation.

### 1.3 Solution
Add width constraints to bounding labels:
1. **`make_safe_label()`** — add `label.set_max_width_chars(120)` after `set_wrap()`
2. **`_build_code_from_markup()`** — add `code_label.set_max_width_chars(120)` after `set_wrap()`

This bounds the label's natural width, enabling proper wrapping within the chat viewport.

---

## 2. Discovery

### 2.1 Files Read

| File | What I Learned |
|------|----------------|
| `utils/gtk_safe_link.py` (lines 76-140) | `make_safe_label()` creates `Gtk.Label`, sets `wrap=True`, `wrap_mode=Pango.WrapMode.WORD_CHAR`, `use_markup=True`, `selectable=True`, `xalign=0`. **No `set_max_width_chars()`**. Returns the label. |
| `ui/views/chat_bubble.py` (lines 261-270) | `build_role_bubble()` creates `container = Gtk.Box()`, sets `halign=START/END` based on role. `bubble = Gtk.Box(orientation=VERTICAL)` inside. No width constraint on either. |
| `ui/views/chat_bubble.py` (lines 384-388) | `_build_code_from_markup()` creates `code_label = Gtk.Label()`, sets `wrap=True`, `wrap_mode=WORD_CHAR`, `monospace`. **No `set_max_width_chars()`**. |
| `ui/views/chat_bubble.py` (lines 626-640) | `_build_text_segment()` calls `make_safe_link.make_safe_label()` for text segments. |
| `ui/handlers/chat_render_handler.py` (line 122) | `_assemble_from_processed()` uses `make_safe_label()` for the full message. |

### 2.2 Existing Pattern (Verified)
The codebase uses `set_max_width_chars` elsewhere:
- `ui/views/file_tree.py:152` — `self._label.set_max_width_chars(0)` (unbounded but explicit)
- `ui/views/diff_viewer.py` — labels with explicit max width
- `ui/views/feed_card.py` — labels with explicit max width

**Missing only in chat bubble labels.**

### 2.3 Verification Commands
```bash
grep -rn "set_max_width_chars" ui/views/chat_bubble.py utils/gtk_safe_link.py
# Expected: 0 matches (currently missing)

grep -rn "set_max_width_chars" ui/views/
# Expected: matches in file_tree.py, diff_viewer.py, feed_card.py (pattern exists)
```

---

## 3. Changes by File

### 3.1 `utils/gtk_safe_link.py` — **MODIFY**

**Function:** `make_safe_label()` (lines 76-140)

**Change:** Add `label.set_max_width_chars(120)` after `set_wrap_mode()`.

```python
def make_safe_label(
    text: str = "",
    selectable: bool = True,
    wrap: bool = True,
    wrap_mode: Pango.WrapMode = Pango.WrapMode.WORD_CHAR,
    xalign: float = 0.0,
    max_width_chars: int = 120,  # NEW PARAMETER
) -> Gtk.Label:
    """Create a Gtk.Label with safe defaults for chat rendering.
    
    Args:
        text: Initial text (Pango markup allowed).
        selectable: Allow text selection.
        wrap: Enable line wrapping.
        wrap_mode: Pango wrap mode for wrapping.
        xalign: Horizontal alignment (0.0 = left, 1.0 = right).
        max_width_chars: Maximum width in characters for wrapping. 
                         Set to 0 for unlimited (use with caution).
    """
    label = Gtk.Label()
    label.set_use_markup(True)
    label.set_selectable(selectable)
    label.set_ellipsize(0)  # no ellipsis
    if wrap:
        label.set_wrap(True)
        label.set_wrap_mode(wrap_mode)
        # BOUND THE NATURAL WIDTH — prevents Pango unbounded width explosion
        if max_width_chars > 0:
            label.set_max_width_chars(max_width_chars)
    label.set_xalign(xalign)
    if text:
        label.set_markup(text)
    return label
```

**Key decisions:**
- Default `max_width_chars=120` — reasonable for chat viewport (fits in typical 800px window with padding)
- Parameter allows callers to override (0 = unlimited, though not recommended for chat)
- Placed after `set_wrap_mode()` so it only applies when wrapping is enabled

### 3.2 `ui/views/chat_bubble.py` — **MODIFY**

**Function:** `_build_code_from_markup()` (lines 384-388)

**Change:** Add `code_label.set_max_width_chars(120)` after `set_wrap_mode()`.

```python
def _build_code_from_markup(self, markup: str) -> Gtk.Widget:
    """Build a code block widget from Pango markup."""
    code_label = Gtk.Label()
    code_label.set_use_markup(True)
    code_label.set_selectable(True)
    code_label.set_wrap(True)
    code_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    code_label.set_max_width_chars(120)  # BOUND WIDTH — matches make_safe_label
    code_label.add_css_class("code-block-content")
    code_label.set_markup(markup)
    return code_label
```

**No changes to `build_role_bubble()` or `bubble` alignment** — the width constraint on the label is sufficient. The label's bounded natural width will allow the bubble to lay out correctly within the chat viewport.

---

## 4. Data Flow

```
Agent response (32k chars)
    → ChatRenderHandler._assemble_from_processed()
    → make_safe_label(text, wrap=True, wrap_mode=WORD_CHAR, max_width_chars=120)
    → Gtk.Label with set_max_width_chars(120)
    → build_role_bubble() → container (halign=START) → bubble (VERTICAL)
    → chat_box (ScrolledWindow child, halign=FILL)
    → Layout pass: label natural width bounded by 120 chars
    → bubble fits within viewport, text wraps correctly
```

---

## 5. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `utils/gtk_safe_link.py` | Modified (+1 param + 3 lines) | +5 | Low |
| `ui/views/chat_bubble.py` | Modified (+1 line) | +1 | Low |
| **Total** | | **~6 net** | **Low** |

---

## 6. Implementation Order

### Phase 1 — Core Fix (5 min)
1. Edit `utils/gtk_safe_link.py` — add `max_width_chars` parameter and `set_max_width_chars()` call
2. Edit `ui/views/chat_bubble.py` — add `set_max_width_chars(120)` to `_build_code_from_markup()`

### Phase 2 — Verification (5 min)
```bash
# 1. Verify the changes
grep -n "set_max_width_chars" utils/gtk_safe_link.py ui/views/chat_bubble.py

# 2. Run the app
python3 main.py

# 3. Test with a long response
# - Send a 32k-char message to any agent
# - Verify: no GTK-CRITICAL warning about "minimum width for height of 1048576"
# - Verify: text wraps at ~120 chars
# - Verify: bubble fits within chat viewport
# - Verify: full text is visible (scrollable in ScrolledWindow)
```

---

## 7. Acceptance Criteria

- [ ] No `Gtk-CRITICAL` warning about "minimum width for height of 1048576" when rendering long messages
- [ ] Chat bubble text wraps at approximately 120 characters (reasonable for chat UI)
- [ ] Bubble fits within chat viewport (no horizontal overflow)
- [ ] Full text of long responses is visible (vertically scrollable in ScrolledWindow)
- [ ] Code blocks also wrap correctly at ~120 characters
- [ ] Existing tests pass (no regressions)

---

## 8. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Very long single word (e.g., 500-char URL) | `WORD_CHAR` wrap mode breaks at character level; fits within 120-char bound |
| Code block with long lines | `code_label` wraps at 120 chars; horizontal scroll if needed |
| Very narrow window | Label wraps at window width (max_width_chars is a max, not min) |
| Empty message | Renders as empty bubble (no crash) |
| Mixed markdown (text + code) | Both `make_safe_label` and `_build_code_from_markup` labels bounded |

---

## 9. ARCHITECTURE.md Updates Required

None — this is a pure view fix using existing patterns. The `set_max_width_chars` pattern is already documented in ARCHITECTURE.md §3.5 as standard practice for labels in views.

---

## 10. Spec Self-Audit (Rule 9)

1. **Does every code sample work against current codebase?** ✅ — `make_safe_label` signature matches existing; `set_max_width_chars` is standard GTK4 method.
2. **Exception types caught?** ✅ — No exceptions raised by `set_max_width_chars`. `Gtk.Label` creation can fail OOM (not handled elsewhere either).
3. **Key structures verified?** ✅ — `make_safe_label` returns `Gtk.Label`; `chat_bubble` uses it directly.
4. **Data flow traced?** ✅ — Agent response → render handler → label → bubble → chat box → viewport.
5. **Implementer following this spec produces working code?** ✅ — 2 files, 6 lines changed, straightforward.

---

## 11. Completion Verification (Rule 10)

**1. Scope checklist:**
- [ ] `utils/gtk_safe_link.py` — `make_safe_label()` modified
- [ ] `ui/views/chat_bubble.py` — `_build_code_from_markup()` modified

**2. Test suite:** Run `python3 main.py`, test with long message.

**3. Pattern sweep:** 
```bash
grep -rn "make_safe_label" utils/gtk_safe_link.py ui/views/chat_bubble.py
# Verify all calls pass max_width_chars (or default works)
```

**4. Declaration:** Complete when all acceptance criteria met.

---

**End of Spec**