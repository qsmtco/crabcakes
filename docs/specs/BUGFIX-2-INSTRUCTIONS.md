# BUGFIX 2 — Clear `_last_row_widget` after row trim

## Problem

`ui/views/activity_drawer.py` method `_trim_old_rows_if_needed()` removes the oldest rows when total exceeds `MAX_ROWS=100`, but does NOT check whether `_last_row_widget` references one of the removed widgets. After removal, `_last_row_widget` points at a destroyed/detached GTK widget. The next counter-collapse call (`_mutate_counter_row(self._last_row_widget, row)`) operates on a dead widget — potential GTK crash (segfault in PyGObject).

## Context

- `_last_row_widget` is set when a new row is appended (line ~209-210)
- `_last_row_key` tracks the (agent, activity_type) tuple for counter-collapse
- The trim removes 25 oldest non-separator rows when count > 100
- The removed widgets are detached from the ListBox via `self._list.remove(r)`
- In GTK4, removed widgets are NOT automatically destroyed — but they ARE unparented, and calling methods on them may cause issues depending on GTK internal state

## What to implement

### File 1: `ui/views/activity_drawer.py` — method `_trim_old_rows_if_needed()`

After the `for r in to_remove: self._list.remove(r)` loop, add a check:

1. Check if `self._last_row_widget` is among the removed rows. The simplest approach: check if the widget is still parented (has a parent in the listbox). If `self._last_row_widget` was removed, clear both `_last_row_key` and `_last_row_widget`.

2. The fix should be:
```python
for r in to_remove:
    self._list.remove(r)
# If the last counter-collapsed row was trimmed, clear the references
# to prevent _mutate_counter_row from operating on a detached widget.
if self._last_row_widget is not None:
    # Check if the widget is still in the listbox
    parent = self._last_row_widget.get_parent()
    if parent is None:
        self._last_row_key = None
        self._last_row_widget = None
```

**Important:** Use `get_parent()` to check — do NOT iterate the listbox to search for it (O(n) for large lists). `get_parent()` returns the Gtk.ListBoxRow wrapper, or `None` if the widget is unparented. Actually — `_last_row_widget` is a `Gtk.Box` (the child of a `Gtk.ListBoxRow`). When `self._list.remove(r)` is called with a `Gtk.ListBoxRow`, the ListBoxRow is unparented. The `Gtk.Box` child (`_last_row_widget`) would still have `get_parent()` return the unparented ListBoxRow. So we need to check differently.

**Better approach:** Build a set of the removed ListBoxRow widgets, then check if `_last_row_widget`'s parent is in that set:

```python
removed_rows = set()
for r in to_remove:
    self._list.remove(r)
    removed_rows.add(r)
# If the last counter-collapsed row was trimmed, clear the references.
if self._last_row_widget is not None and self._last_row_widget.get_parent() in removed_rows:
    self._last_row_key = None
    self._last_row_widget = None
```

Actually, the simplest and most reliable approach: after removing, check if `_last_row_widget` can still be found in the listbox. But that's O(n).

**Simplest reliable approach:** Track whether the widget was removed by checking directly. The `_list.remove(r)` call removes a `Gtk.ListBoxRow`. The `_last_row_widget` is a `Gtk.Box` that is the *child* of a ListBoxRow. So:

```python
removed_set: set[Gtk.ListBoxRow] = set(to_remove)
for r in to_remove:
    self._list.remove(r)
# Check if _last_row_widget's parent row was among the removed rows
if self._last_row_widget is not None:
    parent_row = self._last_row_widget.get_parent()
    if parent_row in removed_set:
        self._last_row_key = None
        self._last_row_widget = None
```

Wait — `to_remove` contains `Gtk.ListBoxRow` objects. `self._last_row_widget` is the *child* (Gtk.Box) of a ListBoxRow. `get_parent()` on the child returns the ListBoxRow. So `parent_row in removed_set` is the correct check.

### File 2: `tests/test_activity_drawer.py` (NEW or existing — check if tests for ActivityDrawer exist)

Add a test that:
1. Creates an ActivityDrawer
2. Appends > 100 events of the same (agent, type) to trigger a trim
3. After the trim, appends one more event with the same key
4. Asserts no crash (the counter-collapse should NOT try to mutate the dead widget)

If no test file for ActivityDrawer exists, create `tests/test_activity_drawer.py`. Check first.

**Test approach (since ActivityDrawer requires GTK):**
- The drawer needs a Gtk.ListBox, Gtk.Label, etc. — these require a display.
- Look at how existing tests handle this. Check if there's a `fake_glib` fixture or a GTK display setup in existing test files.
- If GTK can't be initialized in tests, write the test as a manual verification command that can be run with `CRABCAKES_DEBUG=1 python3 crabcakes.py`.

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "_last_row_widget\|_trim_old_rows" ui/views/activity_drawer.py
python3 -m pytest tests/ -q --tb=short -k "activity_drawer or trim" 2>&1 || echo "No matching tests found"
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Added removed-row tracking and _last_row_widget cleanup in _trim_old_rows_if_needed — evidence: grep line numbers
- [ ] Edit 2: Added test for trim-then-append-no-crash — evidence: test file exists and passes
- [ ] Edit 3: Full test suite passes — evidence: pytest output
```
