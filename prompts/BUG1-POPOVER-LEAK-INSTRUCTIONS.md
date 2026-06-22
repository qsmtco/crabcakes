# Bug #1 Fix — Popover Leak Guard in show_suggestions_menu

## File to edit
- `ui/views/chat_input_toolbar.py` — method `show_suggestions_menu` only

## Problem
Every call to `show_suggestions_menu` creates a new `Gtk.Popover` with no tracking of a previous one. Two rapid right-clicks (or right-click → spell-button click) parent two popovers simultaneously. The first popover's `closed` → `unparent()` only fires when it's dismissed, so popovers stack/leak.

## Fix
Track the current suggestion popover in an instance attribute `_suggestion_popover`. Before creating a new popover, dismiss and clean up the existing one.

## Exact changes required

### 1. Add instance attribute in `__init__`
In `__init__`, after the callback attribute block (after `self._on_spell_toggle: callable | None = None`), add:
```python
# Track active suggestion popover to prevent leaks on repeated calls
self._suggestion_popover: Gtk.Popover | None = None
```

### 2. Add cleanup guard at top of `show_suggestions_menu`
At the very start of `show_suggestions_menu` (before `popover = Gtk.Popover()`), add:
```python
# Dismiss any existing suggestion popover before creating a new one
if self._suggestion_popover is not None:
    prev = self._suggestion_popover
    self._suggestion_popover = None
    try:
        prev.popdown()
    except Exception:
        pass
    if prev.get_parent() is not None:
        prev.unparent()
```

### 3. Store reference after creating the popover
After the line `popover = Gtk.Popover()` (or after `popover.set_autohide(True)`), add:
```python
self._suggestion_popover = popover
```

### 4. Clear reference on close
Modify the existing `closed` handler. Change:
```python
popover.connect("closed", lambda *_: popover.unparent())
```
to:
```python
def _on_suggestion_closed(p, *_):
    if p.get_parent() is not None:
        p.unparent()
    if self._suggestion_popover is p:
        self._suggestion_popover = None
popover.connect("closed", _on_suggestion_closed)
```

## Constraints
- Do NOT change the popover positioning logic (parent_widget, pointing_to, set_pointing_to)
- Do NOT change the deferred popup logic (GLib.idle_add)
- Do NOT touch any other method
- Do NOT reformat or reorder existing code
- Keep the `try/except` around `popdown()` — it can warn if the popover was never mapped

## Verification
- `grep -n "_suggestion_popover" ui/views/chat_input_toolbar.py` — should show 5+ hits
- `python3 -m pytest tests/ -q --tb=short` — all 101 tests must pass
