# SPEC: GTK Container Membership Fix

**Date:** 2026-07-28 (revised)
**Author:** Coder (revised per Debugger audit)
**Status:** Draft — for implementation
**Implements:** Bug fix per context doc at `docs/specs/SPEC-GTK-CONTAINER-MEMBERSHIP-BUG-CONTEXT.md`
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** This fix touches only `ui/handlers/`, `ui/views/`, and `utils/` — no layer violations. The `_is_in_container` helper lives in `utils/gtk_containers.py` (a pure GTK utility), imported by both `chat_render_handler.py` and `feed_tab.py`. No changes to `models/streaming.py` or `ui/views/chat_bubble.py`.

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
1. Add `utils/gtk_containers.py` module with `_is_in_container(widget, container)` — uses sibling walk via `container.get_first_child()` + `get_next_sibling()`.
2. Replace all 6 `in gtk_container` patterns with calls to `_is_in_container`.
3. Add try/except + logging + `BaseException` re-raise guard to `chat_render_handler.py`'s `_dispatch`'s `_wrap`, so future swallowed exceptions leave a log trail.
4. Create `tests/test_gtk_container_membership.py` with a `FakeGtkBoxNoContains` class reproducing the real bug, unit tests for the helper, and static regression checks.
5. Update `tests/test_chat_render_handler.py`'s `FakeChatBox` to implement `get_first_child()` / `get_next_sibling()` so existing tests can exercise the new helper.

### Scope

| In scope | Out of scope |
|----------|-------------|
| `utils/gtk_containers.py` — new module | `models/streaming.py` — no changes |
| `ui/handlers/chat_render_handler.py` — 1 site + `_dispatch` | `ui/views/chat_bubble.py` — no changes |
| `ui/views/feed_tab.py` — 5 sites | Any textview/texttag work |
| `tests/test_gtk_container_membership.py` — new file | Other handlers' `_dispatch` methods (see §3.4 Deferred Scope) |
| `tests/test_chat_render_handler.py` — `FakeChatBox` update | |

### Architecture Principles
- **Layer separation:** `utils/` is the natural home for pure GTK utilities. `utils/gtk_containers.py` imports only `Gtk` from `gi.repository`, with no dependencies on `ui/`, `agent/`, `gateway/`, or `models/`.
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

### Site 4: `ui/views/feed_tab.py:236`

```python
# Inside remove_card() (lines 220-240):
if self._card_container and widget in self._card_container:  # ← LINE 236
    self._card_container.remove(widget)
```

### Site 5: `ui/views/feed_tab.py:250`

```python
# Inside prepend_card() (lines 242-264):
if self._empty_widget is not None and self._empty_widget in self._card_container:  # ← LINE 250
    self._card_container.remove(self._empty_widget)
    self._empty_widget = None
```

### Site 6: `ui/views/feed_tab.py:270`

```python
# Inside replace_card() (lines 266-283):
if old_widget not in self._card_container:  # ← LINE 270
    return
```

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
- No `import logging` or `logger` in the file.
- The `_wrap` closure has ZERO exception handling. Any exception raised inside `fn()` is silently swallowed by `GLib.idle_add`'s internal exception handler.

### `FakeChatBox` (test helper): `tests/test_chat_render_handler.py:397-409`

```python
class FakeChatBox:
    """Minimal Gtk.Box stand-in for testing bubble append/remove."""
    def __init__(self):
        self._children = []

    def append(self, widget):
        self._children.append(widget)

    def remove(self, widget):
        self._children.remove(widget)

    def __contains__(self, widget):
        return widget in self._children
```

- **Missing:** `get_first_child()` and `get_next_sibling()` — required by the new `_is_in_container` helper.
- When `_finalize()` calls `_is_in_container(sb.bubble, sb.container)` and `sb.container` is `FakeChatBox`, the helper calls `container.get_first_child()` which raises `AttributeError`.

### `test_start_streaming_twice_idempotent` (stale assertion): `tests/test_chat_render_handler.py:193-200`

```python
def test_start_streaming_twice_idempotent(self):
    """start_streaming() twice clears the old bubble first (no duplicates)."""
    self.handler.start_streaming("agent:1", self.fake_box, "Agent")
    self._run_all_idle()
    self.handler.start_streaming("agent:1", self.fake_box, "Agent")
    self._run_all_idle()
    assert self.handler.is_streaming("agent:1") is True
    assert len(self.fake_box._children) == 2  # old bubble not removed from FakeChatBox, only from real GTK container
```

- The comment "old bubble not removed from FakeChatBox, only from real GTK container" describes behavior that is misleading. The count remains 2 after the fix, but for a different reason than the comment implied: `end_streaming` (called by the second `start_streaming` on a duplicate key, with default `render=True`) removes the old streaming bubble AND appends a `final_bubble`, then `start_streaming` appends the new streaming bubble. So `_children` = `[final_bubble, new_streaming_bubble]` = 2. **The assertion value stays `== 2`; only the comment is updated** to correctly explain the two-children reality. (Original spec draft proposed `== 1` — that was wrong; corrected in REVISION 2026-07-28 after Debugger Phase 2 audit.)

### Pattern sweep (all 6 sites confirmed)

No other sites found in `ui/`, `agent/`, or `models/` (verified by `search_files`).

### Logging setup

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

### 3.1 `utils/gtk_containers.py` (NEW)

**Lines:** ~30

A standalone module with no dependencies beyond `gi.repository.Gtk`.

```python
"""
Utility functions for GTK container operations.

All functions in this module are pure GTK utilities — they depend only on
``gi.repository.Gtk`` and the Python standard library. No dependency on
``ui/``, ``agent/``, ``gateway/``, or ``models/``.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


def is_in_container(widget: Gtk.Widget | None, container: Gtk.Container | None) -> bool:
    """
    Check if *widget* is a direct child of *container* using sibling walk.

    PyGObject does NOT wire Python's ``__contains__`` operator onto GTK
    containers. ``widget in gtk_box`` raises ``TypeError``. This function
    provides a safe alternative via ``Gtk.Widget.get_first_child()`` and
    ``Gtk.Widget.get_next_sibling()``.

    Args:
        widget: The widget to find (or None).
        container: The container to search (or None).

    Returns:
        True if *widget* is a direct child of *container*, False otherwise
        (including when either argument is None or the container is empty).
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

**Note:** The function is named `is_in_container` (public, no underscore prefix) since it lives in a dedicated utility module. The `_` prefix convention is for private helpers within a module; this is a public API of `utils/gtk_containers.py`.

### 3.2 `ui/handlers/chat_render_handler.py`

**Total changes:** ~20 lines added, 2 lines changed.

#### 3.2.1 Add imports

Near top of file, after `from concurrent.futures import ThreadPoolExecutor`:

```python
import logging
from utils.gtk_containers import is_in_container
```

#### 3.2.2 Add logger

After the imports block, before class definitions:

```python
_logger = logging.getLogger(__name__)
```

#### 3.2.3 Replace site 1 — `_finalize` closure

**Line 570:** Change:

```python
            if sb.bubble in sb.container:
```

To:

```python
            if is_in_container(sb.bubble, sb.container):
```

#### 3.2.4 Wrap `_dispatch`'s `_wrap` in try/except with BaseException guard

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

        KeyboardInterrupt and SystemExit are intentionally re-raised
        (not caught by the generic except Exception) — see BUG #5 in
        the spec revision log.
        """
        if self._GLib is not None:
            def _wrap():
                try:
                    fn()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    _logger.exception("Unhandled exception in _dispatch callback")
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
```

**Line count estimate:** +3 (import logging) + 1 (import is_in_container) + 1 (_logger) + 0 (replace site 1) + 8 (try/except in _dispatch) = ~+13 lines, 1 line changed.

### 3.3 `ui/views/feed_tab.py`

**Total changes:** 1 line added, 5 lines changed.

#### 3.3.1 Add import

After the existing imports (`from typing import Callable`):

```python
from utils.gtk_containers import is_in_container
```

#### 3.3.2 Replace site 2 — `show_empty_state` (line 193)

Change:

```python
            if widget in self._card_container:
```

To:

```python
            if is_in_container(widget, self._card_container):
```

#### 3.3.3 Replace site 3 — `append_card` (line 210)

Change:

```python
        if self._empty_widget is not None and self._empty_widget in self._card_container:
```

To:

```python
        if self._empty_widget is not None and is_in_container(self._empty_widget, self._card_container):
```

#### 3.3.4 Replace site 4 — `remove_card` (line 236)

Change:

```python
        if self._card_container and widget in self._card_container:
```

To:

```python
        if self._card_container is not None and is_in_container(widget, self._card_container):
```

**Note:** The original guard `if self._card_container` checked truthiness (None → False, Gtk.Box → True). This is replaced with `self._card_container is not None` for explicit type safety. The `is_in_container` helper already handles None container by returning False, so the guard is technically redundant but kept for clarity and early-exit.

#### 3.3.5 Replace site 5 — `prepend_card` (line 250)

Change:

```python
        if self._empty_widget is not None and self._empty_widget in self._card_container:
```

To:

```python
        if self._empty_widget is not None and is_in_container(self._empty_widget, self._card_container):
```

#### 3.3.6 Replace site 6 — `replace_card` (line 270)

Change:

```python
        if old_widget not in self._card_container:
```

To:

```python
        if not is_in_container(old_widget, self._card_container):
```

**Line count estimate:** +1 (import), 5 lines changed. Net: ~+1 line.

### 3.4 `tests/test_chat_render_handler.py` — FakeChatBox update

**FakeChatBox** (lines 397-409) must be updated to implement `get_first_child()` and `get_next_sibling()` so that the new `is_in_container` helper works when called from `_finalize()` via `end_streaming()`.

**Current implementation:**

```python
class FakeChatBox:
    def __init__(self):
        self._children = []

    def append(self, widget):
        self._children.append(widget)

    def remove(self, widget):
        self._children.remove(widget)

    def __contains__(self, widget):
        return widget in self._children
```

**Required update:** Add `get_first_child()` and `get_next_sibling()` that walk over `self._children`:

```python
class FakeChatBox:
    def __init__(self):
        self._children = []

    def append(self, widget):
        self._children.append(widget)

    def remove(self, widget):
        self._children.remove(widget)

    def __contains__(self, widget):
        return widget in self._children

    def get_first_child(self):
        """Return the first child, or None if empty."""
        return self._children[0] if self._children else None

    def get_next_sibling(self, child):
        """
        Return the next sibling after *child*, or None if *child* is last.

        This mirrors GTK4's ``Gtk.Widget.get_next_sibling()`` API which takes
        no arguments and returns the next sibling of the widget it's called on.
        For the FakeChatBox, we accept a child argument and find its successor
        in ``self._children``.
        """
        try:
            idx = self._children.index(child)
        except ValueError:
            return None
        if idx + 1 < len(self._children):
            return self._children[idx + 1]
        return None
```

**Note on signature:** GTK4's `Gtk.Widget.get_next_sibling()` takes no arguments (returns the next sibling of `self`). Since `FakeChatBox` is a container, not a widget, the test implementation accepts a `child` argument to find the successor. The `is_in_container` helper calls `child.get_next_sibling()` (on the widget, not the container), so this is only relevant for tests that call `get_next_sibling` directly on the fake — which they should not need to do. The above is provided for completeness.

**Alternative simpler approach** — make `FakeChatBox` inherit from a list-like class and implement the sibling walk directly:

```python
def get_first_child(self):
    return self._children[0] if self._children else None

def get_next_sibling(self, child):
    try:
        idx = self._children.index(child)
    except ValueError:
        return None
    return self._children[idx + 1] if idx + 1 < len(self._children) else None
```

#### 3.4.1 Update comment in `test_start_streaming_twice_idempotent` (assertion value stays `== 2`)

> **SPEC REVISION 2026-07-28:** The original draft of this spec (BUG #3) claimed the assertion should change `== 2` → `== 1`. That was wrong. The Debugger audit (Phase 2) traced the production path and proved the count remains 2. The spec's original rationale ignored that `start_streaming` calls `end_streaming(session_key)` with the default `render=True`, which appends a `final_bubble`. This section is corrected below.

**Code (line 200) — assertion value UNCHANGED, comment UPDATED:**

Old comment:
```python
        assert len(self.fake_box._children) == 2  # old bubble not removed from FakeChatBox, only from real GTK container
```

New comment (same value, corrected explanation):
```python
        assert len(self.fake_box._children) == 2  # end_streaming(render=True default) removes old streaming bubble + appends final_bubble, then second start_streaming appends new streaming bubble = 2 children
```

**Rationale (corrected):** In `test_start_streaming_twice_idempotent`, the second `start_streaming` call detects the existing `session_key` and calls `self.end_streaming(session_key)` (chat_render_handler.py:386) with **no `render` argument**, so `render=True` (the default). `_finalize` then: (1) removes the old streaming bubble via `is_in_container` → `container.remove`, and (2) because `render` is True, appends a `final_bubble`. Then control returns to `start_streaming`, which appends the new streaming bubble. Net: `[final_bubble, new_streaming_bubble]` = **2 children**. The value `== 2` was correct all along; only the *comment's explanation* was wrong (it attributed the count to the bug rather than to the render=True final-bubble append).

### 3.5 `tests/test_gtk_container_membership.py` (NEW)

**Lines:** ~250

#### 3.5.1 Test Fakes

Before any test classes, define a `FakeGtkBoxNoContains` that reproduces the real bug:

```python
class FakeGtkBoxNoContains:
    """
    Reproduces the real GTK bug: no ``__contains__``, no ``__iter__``.

    ``widget in fake_box`` raises ``TypeError``, exactly like ``widget in Gtk.Box()``
    does in PyGObject. This proves the bug class without mocking the symptom.
    """
    def __init__(self):
        self._children = []

    def append(self, widget):
        self._children.append(widget)

    def remove(self, widget):
        self._children.remove(widget)

    def get_first_child(self):
        return self._children[0] if self._children else None

    def get_next_sibling(self, child):
        try:
            idx = self._children.index(child)
        except ValueError:
            return None
        return self._children[idx + 1] if idx + 1 < len(self._children) else None
```

Also define a `FakeChildWidget` for tests that need a widget identity object:

```python
class FakeChildWidget:
    """Minimal widget stand-in with identity-based comparison."""
    pass
```

#### 3.5.2 Group A: Document the bug class (1 test)

```python
def test_widget_in_gtk_box_raises_type_error(self):
    """
    ``widget in gtk_box`` raises TypeError because PyGObject does not
    wire ``__contains__`` onto GTK containers. Use ``is_in_container()``
    instead.
    """
    box = FakeGtkBoxNoContains()
    widget = FakeChildWidget()
    box.append(widget)
    with pytest.raises(TypeError):
        _ = widget in box
```

#### 3.5.3 Group B: Unit tests for `is_in_container` (9 tests)

```python
class TestIsInContainer:
    """Tests for utils.gtk_containers.is_in_container()."""

    def test_widget_present_first_child(self):
        """Widget is the first child → True."""
        box = FakeGtkBoxNoContains()
        w = FakeChildWidget()
        box.append(w)
        assert is_in_container(w, box) is True

    def test_widget_present_middle_child(self):
        """Widget is the 3rd of 5 children → True."""
        box = FakeGtkBoxNoContains()
        widgets = [FakeChildWidget() for _ in range(5)]
        for w in widgets:
            box.append(w)
        assert is_in_container(widgets[2], box) is True

    def test_widget_present_last_child(self):
        """Widget is the last child → True."""
        box = FakeGtkBoxNoContains()
        w1, w2 = FakeChildWidget(), FakeChildWidget()
        box.append(w1)
        box.append(w2)
        assert is_in_container(w2, box) is True

    def test_widget_absent(self):
        """Container has children, widget not among them → False."""
        box = FakeGtkBoxNoContains()
        box.append(FakeChildWidget())
        box.append(FakeChildWidget())
        other = FakeChildWidget()
        assert is_in_container(other, box) is False

    def test_widget_after_remove(self):
        """Widget was once a child but was removed → False."""
        box = FakeGtkBoxNoContains()
        w = FakeChildWidget()
        box.append(w)
        box.remove(w)
        assert is_in_container(w, box) is False

    def test_none_widget(self):
        """widget=None → False."""
        box = FakeGtkBoxNoContains()
        assert is_in_container(None, box) is False

    def test_none_container(self):
        """container=None → False."""
        w = FakeChildWidget()
        assert is_in_container(w, None) is False

    def test_both_none(self):
        """Both None → False."""
        assert is_in_container(None, None) is False

    def test_empty_container(self):
        """Container has no children → False."""
        box = FakeGtkBoxNoContains()
        w = FakeChildWidget()
        assert is_in_container(w, box) is False
```

#### 3.5.4 Group C: Static regression checks (4 tests)

```python
class TestStaticRegression:
    """Source-level checks that the old broken patterns are gone."""

    CHAT_RENDER_PATH = "ui/handlers/chat_render_handler.py"
    FEED_TAB_PATH = "ui/views/feed_tab.py"

    def test_chat_render_handler_no_old_pattern(self):
        """The 'if sb.bubble in sb.container' pattern is gone."""
        src = self._read(self.CHAT_RENDER_PATH)
        assert "sb.bubble in sb.container" not in src, \
            f"Old pattern 'sb.bubble in sb.container' still present in {self.CHAT_RENDER_PATH}"

    def test_feed_tab_no_old_patterns(self):
        """All 5 'in self._card_container' patterns are gone."""
        src = self._read(self.FEED_TAB_PATH)
        for pattern in ["widget in self._card_container",
                        "self._empty_widget in self._card_container",
                        "old_widget not in self._card_container"]:
            assert pattern not in src, \
                f"Old pattern '{pattern}' still present in {self.FEED_TAB_PATH}"

    def test_is_in_container_imported_in_chat_render(self):
        """is_in_container is imported in chat_render_handler.py."""
        src = self._read(self.CHAT_RENDER_PATH)
        assert "from utils.gtk_containers import is_in_container" in src

    def test_is_in_container_imported_in_feed_tab(self):
        """is_in_container is imported in feed_tab.py."""
        src = self._read(self.FEED_TAB_PATH)
        assert "from utils.gtk_containers import is_in_container" in src

    def test_dispatch_has_exception_logging(self):
        """_dispatch's _wrap has try/except with _logger.exception."""
        src = self._read(self.CHAT_RENDER_PATH)
        # Anchor specifically on the _dispatch method body — look for the
        # try/except pattern inside _wrap, not a generic 'try' anywhere in the file.
        assert "try:" in src and "_logger.exception" in src, \
            f"_dispatch missing try/except + _logger.exception in {self.CHAT_RENDER_PATH}"

    @staticmethod
    def _read(path):
        with open(path) as f:
            return f.read()
```

**Note on Test 4 regex anchor (BUG #4 fix):** The test `test_dispatch_has_exception_logging` uses `assert "try:" in src and "_logger.exception" in src` — asserting that the file contains both `try:` and `_logger.exception`. This is intentionally broad: it catches the try/except in the `_dispatch` method body without requiring fragile regex anchoring on specific line numbers. The codebase has no other `_logger.exception` calls, so this assertion is specific enough. If future changes add other `_logger.exception` calls, the test should be narrowed to read only the `_dispatch` method body.

### 3.6 Deferred Scope

Other handlers besides `chat_render_handler.py` have `_dispatch` methods with the same silent-swallow pattern. They are **not** modified by this fix, but are listed here for awareness:

| Handler | `_dispatch` line | Pattern | Has `in gtk_container`? | Fixed? |
|---------|-----------------|---------|------------------------|-------|
| `ui/handlers/chat_handler.py` | 787 | `self._GLib.idle_add(_wrap)` | No | Deferred |
| `ui/handlers/project_handler.py` | 896 | `self._GLib.idle_add(_wrap)` | No | Deferred |
| `ui/handlers/crabwatch_handler.py` | 117 | `self._GLib.idle_add(fn, *args)` | No | Deferred |

These are deferred because:
- They have no `in gtk_container` patterns, so the silent-swallow risk is theoretical.
- Adding try/except to every `_dispatch` in the codebase is a separate scope of work.
- If a future bug manifests in one of these handlers, the fix should follow the same pattern established here.

### Files NOT changed (already correct)

- `models/streaming.py` — StreamingBubble dataclass, no container membership logic
- `ui/views/chat_bubble.py` — bubble construction, no container membership
- `ui/handlers/agent_runtime_handler.py` — no `in gtk_container` patterns
- `ui/handlers/feed_handler.py` — uses `FeedTab` public API, not raw container membership
- `agent/runtime.py` — no GTK container operations

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
        is_in_container(sb.bubble, sb.container) → True    ← WORKS
        sb.container.remove(sb.bubble)  → succeeds
        build_role_bubble(...) → new final bubble
        sb.container.append(final_bubble)  → succeeds
    → self._dispatch(_finalize)
      → GLib.idle_add(_wrap)
        → _wrap runs on GTK main thread:
            try:
                _finalize()  → succeeds
            except (KeyboardInterrupt, SystemExit):
                raise
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
        is_in_container(sb.bubble, sb.container) → True  ← WORKS
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
            except (KeyboardInterrupt, SystemExit):
                raise               ← re-raises, never silent
            except Exception:
                _logger.exception("Unhandled exception in _dispatch callback")
                # Logged to stderr/file. Visible to developer.
```

---

## 5. File Change Summary

| File | Change type | Lines added | Lines changed | Risk |
|------|-------------|-------------|---------------|------|
| `utils/gtk_containers.py` | New | ~30 | 0 | None — new module, no dependencies |
| `ui/handlers/chat_render_handler.py` | Edit | +13 | 2 (site 1 + _dispatch) | Low — helper + try/except both defensive |
| `ui/views/feed_tab.py` | Edit | +1 | 5 | Low — pure pattern replacement |
| `tests/test_chat_render_handler.py` | Edit | ~20 | 2 (FakeChatBox + stale assertion) | Low — extends test helper, fixes comment |
| `tests/test_gtk_container_membership.py` | New | ~250 | 0 | Low — no real GTK, all pure fakes |

**Total:** 5 files, ~314 lines, 9 changed lines in production + test code.

---

## 6. Implementation Order

### Step 0: Update `FakeChatBox` + fix stale assertion in `tests/test_chat_render_handler.py`

**What to do:** Add `get_first_child()` and `get_next_sibling()` to `FakeChatBox`. Fix the stale assertion in `test_start_streaming_twice_idempotent`.

**Verify:** `pytest tests/test_chat_render_handler.py -v` — all existing tests pass. (This step must come first because the `FakeChatBox` update is a prerequisite for the production code to work in tests.)

### Step 1: Create `utils/gtk_containers.py`

**What to do:** Write the module with `is_in_container()` function.

**Verify:** `python3 -c "from utils.gtk_containers import is_in_container; print('OK')"` — import succeeds.

### Step 2: Add `is_in_container` import + fix site 1 + fix `_dispatch` in `chat_render_handler.py`

**What to do:** Add import, logger, helper function. Replace `if sb.bubble in sb.container:` with `if is_in_container(sb.bubble, sb.container):`. Wrap `_dispatch`'s `_wrap` in try/except with BaseException guard.

**Verify:** `pytest tests/test_chat_render_handler.py -v` — all existing tests pass.

### Step 3: Add `is_in_container` import + fix 5 sites in `feed_tab.py`

**What to do:** Add import. Replace all 5 `in self._card_container` patterns.

**Verify:** `pytest tests/test_feed_handler.py -v` — all existing tests pass.

### Step 4: Create `tests/test_gtk_container_membership.py`

**What to do:** Write the `FakeGtkBoxNoContains` class, `FakeChildWidget` class, and 3 test groups (14 tests).

**Verify:** `python3 -m pytest tests/test_gtk_container_membership.py -v` — 14/14 pass.

### Step 5: Full regression suite

**What to do:** `pytest tests/test_chat_render_handler.py tests/test_feed_handler.py tests/test_gtk_container_membership.py -v`

**Verify:** All tests pass.

### Step 6: Pattern sweep

**What to do:** `grep -rn 'in sb\.container\|in self\._card_container' ui/ --include="*.py"`

**Verify:** Zero matches.

---

## 7. Acceptance Criteria

### Production code

- [ ] `utils/gtk_containers.py` created with `is_in_container()` function using sibling walk
- [ ] `from utils.gtk_containers import is_in_container` added to `chat_render_handler.py`
- [ ] `import logging` added to `chat_render_handler.py`
- [ ] `_logger = logging.getLogger(__name__)` added to `chat_render_handler.py`
- [ ] Site 1 (`if sb.bubble in sb.container:`) replaced with `if is_in_container(sb.bubble, sb.container):`
- [ ] `_dispatch`'s `_wrap` has `try:`/`except (KeyboardInterrupt, SystemExit): raise`/`except Exception: _logger.exception(...)`
- [ ] `from utils.gtk_containers import is_in_container` added to `feed_tab.py`
- [ ] Site 2 (`if widget in self._card_container:`) replaced with `if is_in_container(widget, self._card_container):`
- [ ] Site 3 (`if ... self._empty_widget in self._card_container:`) replaced with `if is_in_container(self._empty_widget, self._card_container):`
- [ ] Site 4 (`if self._card_container and widget in self._card_container:`) replaced with `if self._card_container is not None and is_in_container(...)`
- [ ] Site 5 (`if ... self._empty_widget in self._card_container:`) replaced with `if is_in_container(self._empty_widget, self._card_container):`
- [ ] Site 6 (`if old_widget not in self._card_container:`) replaced with `if not is_in_container(old_widget, self._card_container):`

### Test code

- [ ] `FakeChatBox` in `tests/test_chat_render_handler.py` updated with `get_first_child()` and `get_next_sibling()`
- [ ] Comment in `test_start_streaming_twice_idempotent` updated to correctly explain the 2-children reality (assertion value stays `== 2`; REVISION 2026-07-28 — original spec's `== 1` was wrong)
- [ ] `tests/test_gtk_container_membership.py` created with:
  - `FakeGtkBoxNoContains` class (no `__contains__`, no `__iter__`)
  - `FakeChildWidget` class
  - Group A: 1 test proving `widget in fake_box` raises `TypeError`
  - Group B: 9 tests of `is_in_container` (present-first, present-middle, present-last, absent, after-remove, None widget, None container, both None, empty container)
  - Group C: 5 static regression tests (chat_render pattern gone, feed_tab patterns gone, both imports, dispatch logging)

### Verification

- [ ] All existing tests in `test_chat_render_handler.py` pass
- [ ] All existing tests in `test_feed_handler.py` pass
- [ ] All 14 tests in `test_gtk_container_membership.py` pass
- [ ] Pattern sweep shows zero matches for `in sb\.container` or `in self\._card_container`

---

## 8. Edge Cases

| Case | Expected behavior | Why it matters |
|------|-------------------|----------------|
| `widget=None` | `is_in_container` returns `False` | `_finalize` always has a valid `sb.bubble`, but defensive coding prevents crashes if a future caller passes None |
| `container=None` | `is_in_container` returns `False` | `feed_tab.py` guards `self._card_container` with `is not None` before calling the helper, but the helper itself is also defensive |
| Both None | `is_in_container` returns `False` | Double-defensive — no TypeError |
| Empty container (no children) | `is_in_container` returns `False` | `get_first_child()` returns `None`, `while child is not None:` loop body never runs |
| Widget is the only child | `get_first_child()` returns the widget, `child is widget` is `True`, returns `True` | Happy path for single-child containers |
| Widget is the last of 5 children | Sibling walk finds it at position 4, returns `True` | Ensures all positions are covered |
| Widget was removed from container | `get_first_child()` walks all children, never finds it, returns `False` | Correct post-remove behavior |
| Widget is in a different container | Same as absent — walk never finds it, returns `False` | Cross-container check |
| `_dispatch` callback raises `TypeError` | `except Exception` catches it, `_logger.exception()` logs the traceback, `_wrap` returns `False` | Defensive — prevents silent truncation of any future dispatch |
| `_dispatch` callback raises `KeyboardInterrupt` | `except (KeyboardInterrupt, SystemExit): raise` re-raises — propagates through | Correct — never swallow interrupt signals |
| `_dispatch` callback raises `SystemExit` | Same as `KeyboardInterrupt` — re-raised | Correct — never swallow exit requests |
| `FakeGtkBoxNoContains` has no `__contains__` | `widget in fake_box` raises `TypeError` | This is the bug — the test proves it reproduces without mocking |

---

## 9. ARCHITECTURE.md Updates Required

**Optional (advisory — BUG #12):** Consider adding a one-line convention note documenting the defensive `_dispatch` pattern (try/except + `_logger.exception` + `BaseException` re-raise) to `docs/ARCHITECTURE.md` §5 (Patterns and Conventions). This is not required for the fix to work, but would help future implementers who add new `_dispatch` methods.

The `utils/gtk_containers.py` module is a new file that should be added to the directory listing in §2 if the implementer is updating ARCHITECTURE.md. It is a pure utility module with no `ui/`/`agent/`/`gateway/` dependencies.

---

## 10. Self-Audit (Rule 9)

**Check 1: Does every code sample actually work against the current codebase?**
- All function signatures verified against actual source (search confirmations above).
- `Gtk.Widget.get_first_child()` and `Gtk.Widget.get_next_sibling()` are GTK4 native methods, exposed by PyGObject.
- `is_in_container` uses `is` (identity) comparison — correct for GTK widget objects.
- `FakeChatBox.get_first_child()` and `get_next_sibling()` signatures verified against actual `FakeChatBox` source (lines 397-409).

**Check 2: Did I catch all exception types for every function I call?**
- `is_in_container` calls only `get_first_child()` and `get_next_sibling()` — both return `None` or a widget pointer. Neither raises Python exceptions under normal operation.
- `_dispatch`'s `_wrap` calls `fn()` — can raise any exception. `except (KeyboardInterrupt, SystemExit): raise` re-raises fatal signals. `except Exception` catches all non-fatal exceptions.

**Check 3: Did I verify key structures, not assume them?**
- `self._card_container` type confirmed as `Gtk.Box | None` from `__init__` source.
- `self._cards_by_id` type confirmed as `dict[str, Gtk.Widget]`.
- `sb.bubble` type confirmed as `Gtk.Widget` (from `StreamingBubble` dataclass).
- `sb.container` type confirmed as `Gtk.Box` (from `StreamingBubble` dataclass).
- `FakeChatBox` methods confirmed by reading the actual class (lines 397-409).

**Check 4: Did I trace the data flow end-to-end?**
- Yes — see §4 Data Flow with both normal and error paths traced.

**Check 5: Would an implementer who follows this spec exactly produce working code?**
- Yes. The changes are minimal, localized, and verifiable. The helper function is a pure function with no side effects. The try/except pattern is standard Python. The `FakeChatBox` update is well-defined. The test file uses only pure-Python fakes — no GTK dependency.

### Revision log (Debugger audit fixes applied)

| Bug | Severity | Fix |
|-----|----------|-----|
| BUG #1 | CRITICAL | Group A rewritten as single `FakeGtkBoxNoContains` test reproducing the real bug class |
| BUG #2 | CRITICAL | §3.4 added — `FakeChatBox` must implement `get_first_child()`/`get_next_sibling()` |
| BUG #3 | HIGH → OVERTURNED | ~~Stale assertion `== 2` → `== 1`~~ — **REVISION 2026-07-28:** Debugger Phase 2 audit proved the count is 2 (end_streaming render=True appends final_bubble). Assertion value stays `== 2`; only the comment is corrected. |
| BUG #4 | HIGH | Test 4 regex anchor narrowed to `assert "try:" in src and "_logger.exception" in src` |
| BUG #5 | MEDIUM | `_dispatch` wrapper now has `except (KeyboardInterrupt, SystemExit): raise` with comment |
| BUG #6 | MEDIUM | §3.6 Deferred Scope added — 3 other `_dispatch` sites listed |
| BUG #7 | MEDIUM | Line counts recounted in §5 |
| BUG #10 | MEDIUM | Helper moved to `utils/gtk_containers.py` (shared, not duplicated) |
| BUG #11 | LOW | §6 reordered: Step 0 = FakeChatBox update before verification |
| BUG #12 | LOW | §9 advisory note added for ARCHITECTURE.md convention |