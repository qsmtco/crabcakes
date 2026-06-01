# Post-Mortem: Fix GTK4 Overlay.remove() Crash on Tab Switch

**Date:** 2026-06-01
**Bug:** `AttributeError: 'Overlay' object has no attribute 'remove'` on tab switch
**Files changed:** `ui/views/main_content.py` (1 line), `tests/test_main_content_tab_switch.py` (new, 167 lines)
**Commit:** pending

---

## What Happened

When switching between chat tabs in CrabCakes, the application crashed with:

```
AttributeError: 'Overlay' object has no attribute 'remove'
  File "ui/views/main_content.py", line 368, in _on_notebook_switch_page
    old_parent.remove(widget)
```

## Root Cause

Commit `51f6e55` ("fix: GTK4 overlay reparent warning on multi-tab creation") introduced code to detach singleton overlay widgets (`_project_settings`, `_scroll_btn_box`) from their previous parent before re-adding them to a new tab's overlay. The detachment used `old_parent.remove(widget)`.

In GTK3, `Gtk.Container.remove()` was universal — every container had it. In GTK4, `Gtk.Overlay` is NOT a `Gtk.Container` and does not have `remove()`. Children added via `add_overlay()` must be removed via `remove_overlay()`, or more generally, via `widget.unparent()`.

The code worked on the first tab (no previous parent to remove from) but crashed on every subsequent tab switch.

## The Fix

Replaced:
```python
old_parent = widget.get_parent()
if old_parent is not None:
    old_parent.remove(widget)
```

With:
```python
if widget.get_parent() is not None:
    widget.unparent()
```

`Gtk.Widget.unparent()` is GTK4-idiomatic, works regardless of parent type, and is already the established pattern elsewhere in the codebase (session_menu.py:96,204; left_panel.py:206,256,295; main_content.py:842).

## Supervisor Assessment

**Approach deviation:** The supervisor initially suggested `old_parent.remove_overlay(widget)`. The builder (QTR) used `widget.unparent()` instead, which is a superior fix — it's parent-type-agnostic and matches existing codebase patterns. This deviation was accepted as an improvement.

## Code Quality Grade: A

**What's good:**
- Minimal, surgical fix — eliminated the `old_parent` variable entirely since it was no longer needed
- Comment explains the "why" and references the prior commit that introduced the bug
- 6 thorough tests covering: regression, ordering invariant, first-tab path, no-overlay path, multi-tab lifecycle
- Zero collateral edits

**What could be better:**
- Nothing worth flagging for a single-line fix

## Bugs Found During Audit

None. The adversarial debugger confirmed:
- `unparent()` works correctly for overlay children (tested with real GTK4 objects)
- `unparent()` on an unparented widget is a safe no-op (defensive guard is harmless)
- The fix is parent-type-agnostic — handles both overlay and non-overlay parents correctly

## Test Results

| Metric | Before Fix | After Fix | Delta |
|--------|-----------|-----------|-------|
| Failed | 30 | 26 | -4 |
| Passed | 1165 | 1169 | +4 |
| New tests | 0 | 6 | +6 (all passing) |

The fix also resolved 4 pre-existing test failures that were caused by the same `remove()` crash.

## Lessons Learned

1. **GTK3→GTK4 migration trap:** `Gtk.Container.remove()` was universal in GTK3. In GTK4, different widget types have different removal APIs. Always verify the specific widget type's API, not just the general GTK pattern.
2. **`unparent()` over parent-type-specific methods:** When detaching a widget from an unknown parent type, `widget.unparent()` is always safe. Type-specific methods like `remove_overlay()` only work when you know the parent is that specific type.
3. **Builder judgment over strict delegation:** The builder deviated from the supervisor's exact suggestion to use a better pattern. This is the kind of judgment worth encouraging — the spec/delegation is guidance, not a straightjacket.

## Implementation Team

- **Supervisor:** Qaster (implementation supervisor)
- **Builder:** QTR (code + tests)
- **Audit:** Qaster (adversarial debugger)
