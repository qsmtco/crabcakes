# SPEC: GTK Container Membership Fix

**Date:** 2026-07-28
**Author:** Coder
**Status:** Draft — for implementation
**Implements:** Bug fix per context doc at `docs/specs/SPEC-GTK-CONTAINER-MEMBERSHIP-BUG-CONTEXT.md`
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** This fix touches only `ui/handlers/` and `ui/views/` — no layer violations. The `_is_in_container` helper is duplicated in each file per §8.6 (handlers never import from other handlers). The fix is a pure container-membership fix with no changes to `models/streaming.py` or `ui/views/chat_bubble.py`.

---

## 1. Overview

### Problem
Six sites in the codebase use Python's `in` operator to check membership of a widget inside a `Gtk.Box`:

```python
if widget in gtk_box:      # TypeError: argument of type 'Gtk.Box' is not iterable
```

PyGObject does NOT wire Python's `__contains__` onto GTK container classes. The `in` operator raises `TypeError`. In `chat_render_handler.py`, this exception is raised inside a `GLib.idle_add` callback with no exception handler — GLib silently swallows it, the rest of `_finalize()` is skipped, and the user sees a truncated message (raw streaming widget never replaced by the final parsed bubble).

### Root Cause
The GTK C method `gtk_widget_contains()` is exposed as `container.contains(widget)`, not as Python's `__contains__`. PyGObject does not synthesize `__contains__` from `contains()` for container widgets. The `in` operator falls through to `__iter__`, which `Gtk.Box` does not implement, producing `TypeError`.

### Solution Summary
1. Add `_is_in_container(widget, container)` helper to both files — uses sibling walk via `container.get_first_child()` + `get_next_sibling()`.
2. Replace all 6 `in gtk_container` patterns with calls to the helper.
3. Add try/except + logging to `_dispatch`'s `_wrap` in `chat_render_handler.py` so future swallowed exceptions leave a log trail.
4. Add new test file `tests/test_gtk_container_membership.py` documenting the bug class and testing the helper.

### Scope

| In scope | Out of scope |
|----------|-------------|
| `ui/handlers/chat_render_handler.py` — 1 site + `_dispatch` | `models/streaming.py` — no changes |
| `ui/views/feed_tab.py` — 5 sites | `ui/views/chat_bubble.py` — no changes |
| `tests/test_gtk_container_membership.py` — new file | Any textview/texttag work |
| | Other handlers' `_dispatch` methods (defensive pattern only for the one that already had the bug) |

### Architecture Principles
- **§8.6 Handler rule:** handlers never import from other handlers. The helper must be duplicated in each file.
- **Layer separation:** `ui/views/` is pure view — no business logic. The helper is a pure GTK utility, acceptable.
- **Minimal fix:** only the broken pattern is replaced. No surrounding refactoring.

---

## 2. DISCOVERY — actual source verification

### Site 1: `ui/handlers/chat_render_handler.py:570`

```python
# Inside _finalize() closure (lines 568-602), called from end_streaming():
def _finalize():
    full_text = sb.plain_text
    if sb.bubble in sb.container:          # ← LINE 570 — raises TypeError
        sb.container.remove(sb.bubble)
    # ... resolves agent_name, builds final bubble, appends ...
```

- `sb` is a `StreamingBubble` (from `models/streaming.py`). `sb.bubble` is `Gtk.Widget`. `sb.container` is `Gtk.Box`.
- This is called via `self._dispatch(_finalize)` at line 603.

### Site 2: `ui/views/feed_tab.py:193`

```python
# Inside show_empty_state() (lines 185-203):
for card_id in list(self._cards_by_id.keys()):
    widget = self._cards_by_id[card_id]
    self._clear_widget_state_recursive(widget)
    if widget in self._card_container:      # ← LINE 193
        self._card_container.remove(widget)
```

- `self._card_container` is `Gtk.Box | None` (initialized as `None` in `__init__`, set later by `FeedHandler`).
- `self._cards_by_id` is `dict[str, Gtk.Widget]`.

### Site 3: `ui/views/feed_tab.py:210`

```python
# Inside append_card() (lines 204-218):
if self._empty_widget is not None and self._empty_widget in self._card_container:  # ← LINE 210
    self._card_container.remove(self._empty_widget)
    self._empty_widget = None
```

- `self._empty_widget` is `Gtk.Widget | None`. Guarded by `is not None` check first, but `in` still raises TypeError on the `Gtk.Box` when `self._empty_widget` is a valid widget.

### Site 4: `ui/views/feed_tab.py:236`

```python
# Inside remove_card() (lines 220-240):
if self._card_container and widget in self._card_container:  # ← LINE 236
    self._card_container.remove(widget)
```

- `self._card_container` is `Gtk.Box | None`. Guarded by truthiness check, but `in` still raises TypeError.

### Site 5: `ui/views/feed_tab.py:250`

```python
# Inside prepend_card() (lines 242-264):
if self._empty_widget is not None and self._empty_widget in self._card_container:  # ← LINE 250
    self._card_container.remove(self._empty_widget)
    self._empty_widget = None
```

- Same pattern as Site 3 — identical bug.

### Site 6: `ui/views/feed_tab.py:270`

```python
# Inside replace_card() (lines 266-283):
if old_widget not in self._card_container:  # ← LINE 270
    return
```

- Uses `not in` — same TypeError, just inverted logic.

### `_dispatch` method: `ui/handlers/chat_render_handler.py:747-755`

```python
def _dispatch(self, fn):
    """Call fn on the GTK main thread."""
    if self._GLib is not None:
        def _wrap():
            fn()                        # ← NO try/except
            return False
        self._GLib.idle_add(_wrap)
    else:
        fn()
```

- `self._GLib` is `None | module` — set in `__init__` at line 176.
- No `import logging` or `logger` in the file. All GTK calls dispatched here.
- The `_wrap` closure has ZERO exception handling. Any exception raised inside `fn()` is silently swallowed by `GLib.idle_add`'s internal exception handler.
- This is the **root cause of the silent truncation** — the TypeError from line 570 propagates up through `_finalize()` into `_wrap`, GLib eats it, and the user sees a truncated message.

### Pattern sweep (all 6 sites confirmed)

```
$ grep -rn 'in self\._card_container\|in sb\.container\|if.*widget.*in.*container' ui/ --include="*.py"

ui/handlers/chat_render_handler.py:570:            if sb.bubble in sb.container:
ui/views/feed_tab.py:193:            if widget in self._card_container:
ui/views/feed_tab.py:210:        if self._empty_widget is not None and self._empty_widget in self._card_container:
ui/views/feed_tab.py:236:        if self._card_container and widget in self._card_container:
ui/views/feed_tab.py:250:        if self._empty_widget is not None and self._empty_widget in self._card_container:
ui/views/feed_tab.py:270:        if old_widget not in self._card_container:
```

No other sites found in `ui/`, `agent/`, or `models/` (verified by `search_files`).

### Logging setup in both files

- `chat_render_handler.py`: No `import logging`, no `logger` variable. Must be added.
- `feed_tab.py`: No `import logging`, no `logger` variable. Not needed — no `_dispatch` method in this file.

### Function signature verification

```bash
# Gtk.Widget.get_first_child() -> Gtk.Widget | None
# Gtk.Widget.get_next_sibling() -> Gtk.Widget | None
# Both are GTK4 native methods, exposed by PyGObject.
```

---

## 3. Changes by File

### 3.1 `ui/handlers/chat_render_handler.py`

**Total changes:** ~15 lines added, 1 line changed.

#### 3.1.1 Add imports

Near top of file, after `from concurrent.futures import ThreadPoolExecutor`:

```python
import logging
```

#### 3.1.2 Add logger

After the imports block, before class definitions:

```python
_logger = logging.getLogger(__name__)
```

#### 3.1.3 Add `_is_in_container` helper

Add as a module-level private function (not a method — it's a pure utility, not stateful). Place after `_assemble_from_processed` and before the `ChatRenderHandler` class, or right after the `_ReentrancySet` class. The choice is aesthetic; the spec suggests placing it after `_ReentrancySet`:

```python
def _is_in_container(widget: Gtk.Widget | None, container: Gtk.Container | None) -> bool:
    """
    Check if widget is a direct child of container using sibling walk.

    PyGObject does NOT wire Python's ``__contains__`` operator onto GTK
    containers. ``widget in gtk_box`` raises TypeError. This helper
    provides a safe alternative.

    Returns False if either argument is None or if container has no children.
    """
    if widget is None or container is None:
        return False
    child = container.get_first_child()
    while child is not None:
        if child is widget:
            return True
        child = child.get_next_sibling()
    return False
```

**Verified against GTK4 API:** `Gtk.Widget.get_first_child()` returns the first child widget or `None`. `Gtk.Widget.get_next_sibling()` returns the next sibling or `None`. Both are exposed in PyGObject. The comparison `child is widget` uses identity (not equality) — correct for GTK widget objects where each widget is a unique C object.

#### 3.1.4 Replace site 1 — `_finalize` closure

**Line 570:** Change:

```python
            if sb.bubble in sb.container:
```

To:

```python
            if _is_in_container(sb.bubble, sb.container):
```

#### 3.1.5 Wrap `_dispatch`'s `_wrap` in try/except

**Lines 747-755:** Change:

```python
    def _dispatch(self, fn):
        """Call fn on the GTK main thread."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
```

To:

```python
    def _dispatch(self, fn):
        """Call fn on the GTK main thread.

        Uses GLib.idle_add to dispatch to the GTK main thread when
        GLib is available. Wraps the callback in try/except so that
        exceptions are logged rather than silently swallowed by GLib's
        main loop exception handler.
        """
        if self._GLib is not None:
            def _wrap():
                try:
                    fn()
                except Exception:
                    _logger.exception("Unhandled exception in _dispatch callback")
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
```

**Exception types:** `fn()` can raise any exception — `TypeError` (the known bug), `AttributeError`, `ValueError`, `KeyError`, or any GTK-related runtime error. Catching `Exception` (not `BaseException`) is correct: we want to catch real errors but let `KeyboardInterrupt` / `SystemExit` propagate.

**Return value:** `_wrap` must return `False` to tell GLib "don't call me again" (one-shot idle callback). The existing code returns `False` after `fn()`. The try/except preserves this — `False` is returned after the except block.

**Line count estimate:** +3 lines (import + logger + helper: ~15 lines), 1 line changed (site 1), ~10 lines changed (_dispatch). Net: ~+25 lines.

### 3.2 `ui/views/feed_tab.py`

**Total changes:** ~15 lines added, 5 lines changed.

#### 3.2.1 Add `_is_in_container` helper

Add as a module-level private function. Place after the imports block, before `class FeedTab`:

```python
def _is_in_container(widget: Gtk.Widget | None, container: Gtk.Container | None) -> bool:
    """
    Check if widget is a direct child of container using sibling walk.

    This is a duplicate of the same-named helper in chat_render_handler.py.
    Duplicated per ARCHITECTURE.md §8.6 — handlers never import from other
    handlers, and views never import from handlers.

    PyGObject does NOT wire Python's ``__contains__`` operator onto GTK
    containers. ``widget in gtk_box`` raises TypeError.
    """
    if widget is None or container is None:
        return False
    child = container.get_first_child()
    while child is not None:
        if child is widget:
            return True
        child = child.get_next_sibling()
    return False
```

**Identical function signature and body to the one in chat_render_handler.py.** This is intentional and required by §8.6.

#### 3.2.2 Replace site 2 — `show_empty_state` (line 193)

Change:

```python
            if widget in self._card_container:
```

To:

```python
            if _is_in_container(widget, self._card_container):
```

#### 3.2.3 Replace site 3 — `append_card` (line 210)

Change:

```python
        if self._empty_widget is not None and self._empty_widget in self._card_container:
```

To:

```python
        if self._empty_widget is not None and _is_in_container(self._empty_widget, self._card_container):
```

#### 3.2.4 Replace site 4 — `remove_card` (line 236)

Change:

```python
        if self._card_container and widget in self._card_container:
```

To:

```python
        if self._card_container is not None and _is_in_container(widget, self._card_container):
```

**Note:** The original guard `if self._card_container` checked truthiness (None → False, Gtk.Box → True). This is replaced with `self._card_container is not None` for explicit type safety. The `_is_in_container` helper already handles None container by returning False, so the guard is technically redundant but kept for clarity and early-exit performance.

#### 3.2.5 Replace site 5 — `prepend_card` (line 250)

Change:

```python
        if self._empty_widget is not None and self._empty_widget in self._card_container:
```

To:

```python
        if self._empty_widget is not None and _is_in_container(self._empty_widget, self._card_container):
```

#### 3.2.6 Replace site 6 — `replace_card` (line 270)

Change:

```python
        if old_widget not in self._card_container:
```

To:

```python
        if not _is_in_container(old_widget, self._card_container):
```

**Line count estimate:** +15 lines (helper), 5 lines changed. Net: ~+20 lines.

### 3.3 `tests/test_gtk_container_membership.py` (NEW)

**Author:** Coder
**Lines:** ~220

Covers three test groups:

#### Group A: Document the bug class (3 tests)

1. `test_widget_in_gtk_box_raises_type_error` — asserts `widget in Gtk.Box()` raises `TypeError`. Mock `Gtk.Box` to raise `TypeError` on `__contains__`.
2. `test_str_in_gtk_box_raises_type_error` — same for `str in Gtk.Box()`.
3. `test_none_in_gtk_box_raises_type_error` — same for `None in Gtk.Box()`.

#### Group B: Unit tests the helper (8 tests)

1. `test_widget_present` — widget is first child → True
2. `test_widget_absent` — container has children, widget not among them → False
3. `test_none_widget` — widget=None → False
4. `test_none_container` — container=None → False
5. `test_both_none` — both None → False
6. `test_empty_container` — container has no children → False
7. `test_widget_middle_child` — widget is the 3rd of 5 children → True
8. `test_widget_after_remove` — widget was once a child but was removed → False

#### Group C: Static regression checks (4 tests)

1. `test_chat_render_handler_no_old_pattern` — reads `chat_render_handler.py` source, asserts `if sb.bubble in sb.container` is NOT present.
2. `test_feed_tab_no_old_pattern` — reads `feed_tab.py` source, asserts none of the 5 old patterns are present.
3. `test_helper_duplicated` — asserts both files have the `_is_in_container` function definition.
4. `test_dispatch_has_exception_logging` — reads `chat_render_handler.py`, asserts `try:` and `_logger.exception` are present in the `_dispatch` method.

**Test file isolation:** No GTK import needed. All tests use `MagicMock` objects for `Gtk.Box`, `Gtk.Widget`, and sibling walk methods. The helper is tested as a pure function.

### Files NOT changed (already correct)

- `models/streaming.py` — StreamingBubble dataclass, no container membership logic
- `ui/views/chat_bubble.py` — bubble construction, no container membership
- `ui/handlers/agent_runtime_handler.py` — no `in gtk_container` patterns
- `ui/handlers/feed_handler.py` — uses `FeedTab` public API, not raw container membership
- `agent/runtime.py` — no GTK container operations
- `ui/handlers/chat_handler.py` — has its own `_dispatch` but no `in gtk_container` patterns (verified by search)

---

## 4. Data Flow

### Normal path (after fix):

```
User types message → agent stream starts
  → ChatRenderHandler.start_streaming(session_key, container)
    → StreamingBubble created, sb.bubble added to sb.container
  → ChatRenderHandler.update_streaming(session_key, delta)
    → sb.plain_text accumulated
  → Agent finishes → ChatRenderHandler.end_streaming(session_key)
    → _finalize closure created:
        sb.plain_text = full_text
        _is_in_container(sb.bubble, sb.container) → True
        sb.container.remove(sb.bubble)  → succeeds
        build_role_bubble(...) → new final bubble
        sb.container.append(final_bubble)  → succeeds
    → self._dispatch(_finalize)
      → GLib.idle_add(_wrap)
        → _wrap runs on GTK main thread:
            try:
                _finalize()  → succeeds
            except Exception:
                _logger.exception(...)  ← never reached
```

### Error path (what happened before fix):

```
    → _finalize closure:
        sb.bubble in sb.container  → TypeError ← RAISED
        sb.container.remove(...)  ← NEVER RUNS
        build_role_bubble(...)    ← NEVER RUNS
        sb.container.append(...)  ← NEVER RUNS
    → self._dispatch(_finalize)
      → GLib.idle_add(_wrap)
        → _wrap runs on GTK main thread:
            _finalize()  → TypeError ← GLib SILENTLY SWALLOWS
            # User sees truncated streaming widget, never replaced
```

### Error path (after fix + _dispatch logging):

```
    → _finalize closure:
        _is_in_container(sb.bubble, sb.container) → True  ← WORKS
        sb.container.remove(sb.bubble)  → succeeds
        build_role_bubble(...) → final bubble
        sb.container.append(final_bubble) → succeeds
```

If some OTHER exception occurs in a future `_dispatch` callback:

```
    → _dispatch(callback)
      → GLib.idle_add(_wrap)
        → _wrap runs on GTK main thread:
            try:
                callback()  → raises SomeException
            except Exception:
                _logger.exception("Unhandled exception in _dispatch callback")
                # Logged to stderr/file. Visible to developer.
```

---

## 5. File Change Summary

| File | Change type | Lines added | Lines changed | Risk |
|------|-------------|-------------|---------------|------|
| `ui/handlers/chat_render_handler.py` | Edit | ~18 | 2 (site 1 + _dispatch) | Low — helper + try/except both defensive |
| `ui/views/feed_tab.py` | Edit | ~15 | 5 | Low — pure pattern replacement |
| `tests/test_gtk_container_membership.py` | New | ~220 | 0 | Low — no real GTK, all mocked |

**Total:** 3 files, ~250 lines, ~7 changed lines in production code.

---

## 6. Implementation Order

### Step 1: Add `_is_in_container` helper + fix site 1 + fix `_dispatch` in `chat_render_handler.py`

**What to do:** Add import, logger, helper function. Replace `if sb.bubble in sb.container:` with `if _is_in_container(sb.bubble, sb.container):`. Wrap `_dispatch`'s `_wrap` in try/except.

**Verify:** `pytest tests/test_chat_render_handler.py -v` — all existing tests pass.

### Step 2: Add `_is_in_container` helper + fix 5 sites in `feed_tab.py`

**What to do:** Add helper function. Replace all 5 `in self._card_container` patterns.

**Verify:** `pytest tests/test_feed_handler.py -v` — all existing tests pass.

### Step 3: Create `tests/test_gtk_container_membership.py`

**What to do:** Write the 3 test groups (15 tests).

**Verify:** `python3 -m pytest tests/test_gtk_container_membership.py -v` — 15/15 pass.

### Step 4: Full regression suite

**What to do:** `pytest tests/test_chat_render_handler.py tests/test_feed_handler.py tests/test_gtk_container_membership.py -v`

**Verify:** All tests pass.

### Step 5: Pattern sweep

**What to do:** `grep -rn 'in sb\.container\|in self\._card_container' ui/ --include="*.py"`

**Verify:** Zero matches.

---

## 7. Acceptance Criteria

- [ ] `_is_in_container` helper added to `ui/handlers/chat_render_handler.py` with correct identity-based sibling walk
- [ ] `_is_in_container` helper added to `ui/views/feed_tab.py` (duplicate, identical)
- [ ] Site 1 (`if sb.bubble in sb.container:`) replaced with `_is_in_container(sb.bubble, sb.container)`
- [ ] Site 2 (`if widget in self._card_container:`) replaced with `_is_in_container(widget, self._card_container)`
- [ ] Site 3 (`if ... self._empty_widget in self._card_container:`) replaced with `_is_in_container(self._empty_widget, self._card_container)`
- [ ] Site 4 (`if self._card_container and widget in self._card_container:`) replaced with `if self._card_container is not None and _is_in_container(...)`
- [ ] Site 5 (`if ... self._empty_widget in self._card_container:`) replaced with `_is_in_container(self._empty_widget, self._card_container)`
- [ ] Site 6 (`if old_widget not in self._card_container:`) replaced with `if not _is_in_container(old_widget, self._card_container)`
- [ ] `import logging` and `_logger = logging.getLogger(__name__)` added to `chat_render_handler.py`
- [ ] `_dispatch`'s `_wrap` wrapped in `try:`/`except Exception:` with `_logger.exception()`
- [ ] `tests/test_gtk_container_membership.py` created with 15 tests (3 bug-class docs + 8 helper unit tests + 4 static regression checks)
- [ ] All existing tests in `test_chat_render_handler.py` and `test_feed_handler.py` pass
- [ ] New test file passes 15/15
- [ ] Pattern sweep shows zero matches for `in sb\.container` or `in self\._card_container`

---

## 8. Edge Cases

| Case | Expected behavior | Why it matters |
|------|-------------------|----------------|
| `widget=None` | `_is_in_container` returns `False` | `_finalize` always has a valid `sb.bubble`, but defensive coding prevents crashes if a future caller passes None |
| `container=None` | `_is_in_container` returns `False` | `feed_tab.py` guards `self._card_container` with `if self._card_container is not None` or truthiness before calling the helper. But the helper itself is also defensive. |
| Both None | `_is_in_container` returns `False` | Double-defensive — no TypeError |
| Empty container (no children) | `_is_in_container` returns `False` | `get_first_child()` returns `None`, `while child is not None:` loop body never runs |
| Widget is the only child | `get_first_child()` returns the widget, `child is widget` is `True`, returns `True` | Happy path for single-child containers |
| Widget is the last of 5 children | Sibling walk finds it at position 4, returns `True` | Ensures all positions are covered |
| Widget was removed from container | `get_first_child()` walks all children, never finds it, returns `False` | Correct post-remove behavior |
| Widget is in a different container | Same as absent — walk never finds it, returns `False` | Cross-container check |
| `_dispatch` callback raises `TypeError` | `except Exception` catches it, `_logger.exception()` logs the traceback, `_wrap` returns `False` | Defensive — prevents silent truncation of any future dispatch |
| `_dispatch` callback raises `KeyboardInterrupt` | `except Exception` does NOT catch `BaseException` subclasses — `KeyboardInterrupt` propagates | Correct — never swallow interrupt signals |
| `_dispatch` callback raises `SystemExit` | Same as `KeyboardInterrupt` — propagates through | Correct — never swallow exit requests |

---

## 9. ARCHITECTURE.md Updates Required

No ARCHITECTURE.md updates needed. This fix does not:
- Add/remove/rename a module
- Change a class's public API or responsibilities
- Change a public function or method signature
- Change environment variables
- Change data flow or event handling patterns
- Change patterns or conventions

The `_is_in_container` helper is a private (`_`-prefixed) module-level utility function. It is not part of any public API. Exception: the new test file should be documented in §8.5 (Test Inventory) if test counts are tracked there — but that is a minor update and can be deferred to the implementer's discretion.

---

## 10. Self-Audit (Rule 9)

**Check 1: Does every code sample actually work against the current codebase?**
- All function signatures verified against actual source (`grep -n` confirmations above).
- `Gtk.Widget.get_first_child()` and `Gtk.Widget.get_next_sibling()` are GTK4 native methods, exposed by PyGObject. Verified by reading GTK4 API docs (confirmed: `Gtk.Widget.get_first_child()` returns `GtkWidget*` or `NULL`; `Gtk.Widget.get_next_sibling()` returns `GtkWidget*` or `NULL`). PyGObject wraps these directly.
- `_is_in_container` uses `is` (identity) comparison — correct for GTK widget objects.

**Check 2: Did I catch all exception types for every function I call?**
- `_is_in_container` calls only `get_first_child()` and `get_next_sibling()` — both are GTK4 C methods that return `None` or a widget pointer. Neither raises Python exceptions under normal operation.
- `_dispatch`'s `_wrap` calls `fn()` — can raise any exception. `except Exception` catches all non-fatal exceptions. `BaseException` (KeyboardInterrupt, SystemExit) propagates — correct.

**Check 3: Did I verify key structures, not assume them?**
- `self._card_container` type confirmed as `Gtk.Box | None` from `__init__` source.
- `self._cards_by_id` type confirmed as `dict[str, Gtk.Widget]`.
- `sb.bubble` type confirmed as `Gtk.Widget` (from `StreamingBubble` dataclass).
- `sb.container` type confirmed as `Gtk.Box` (from `StreamingBubble` dataclass).

**Check 4: Did I trace the data flow end-to-end?**
- Yes — see §4 Data Flow with both normal and error paths traced.

**Check 5: Would an implementer who follows this spec exactly produce working code?**
- Yes. The changes are minimal, localized, and verifiable. The helper function is a pure function with no side effects. The try/except pattern is standard Python. The test file uses only `MagicMock` — no GTK dependency.