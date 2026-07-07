# PHASE 10 (Audit Fixes) — 4 fixes from adversarial audit

**Spec:** `docs/specs/spec-markdown-header-fix.md` (Phases 2-9 audit follow-up)
**Files to change:** `ui/views/chat_bubble.py`, `tests/test_chat_terminal_segment.py` (new), `tests/test_streaming.py` (additions)

These are 4 small, surgical fixes from the Debugger's adversarial audit of Phases 2-9. Each is independent and verifiable on its own.

---

## FIX 1 — Type-robust content handling in heading/task segments (BUG #1)

**File:** `ui/views/chat_bubble.py`

**Problem:** `_build_heading_segment` and `_build_task_segment` call `seg.get("content", "")` then immediately `content.strip()`. If a caller passes `{"content": None}` or `{"content": 42}` (key present with a non-string value), `.get` returns the value as-is and `.strip()` raises `AttributeError`.

**Current code — `_build_heading_segment` (starts at line 763):**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size and inline markdown."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")
    if not content.strip():
        return Gtk.Box()  # empty spacer
```

**New code — add a type coercion line after the `.get` call:**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size and inline markdown."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")
    if not isinstance(content, str):
        content = ""
    if not content.strip():
        return Gtk.Box()  # empty spacer
```

**Current code — `_build_task_segment` (starts at line 781):**
```python
def _build_task_segment(seg: dict) -> Gtk.Widget:
    """Render a task list item with checkbox character and inline markdown."""
    content = seg.get("content", "")
    if not content.strip():
        return Gtk.Box()  # empty spacer
```

**New code — same type coercion:**
```python
def _build_task_segment(seg: dict) -> Gtk.Widget:
    """Render a task list item with checkbox character and inline markdown."""
    content = seg.get("content", "")
    if not isinstance(content, str):
        content = ""
    if not content.strip():
        return Gtk.Box()  # empty spacer
```

---

## FIX 2 — Empty-content guard for terminal segment (BUG #7)

**File:** `ui/views/chat_bubble.py`

**Problem:** `_build_terminal_segment` has no empty-content guard. An empty terminal block produces a full terminal widget (header, copy button, prompt, empty line) instead of an empty spacer.

**Current code — `_build_terminal_segment` (starts at line 707):**
```python
def _build_terminal_segment(seg: dict) -> Gtk.Widget:
    """
    Render a terminal block with amber left border and $ prefix on lines.
    ...
    """
    content = seg.get("content", "")

    block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
```

**New code — add empty-content guard after the `.get` call:**
```python
def _build_terminal_segment(seg: dict) -> Gtk.Widget:
    """
    Render a terminal block with amber left border and $ prefix on lines.
    ...
    """
    content = seg.get("content", "")
    if not isinstance(content, str):
        content = ""
    if not content.strip():
        return Gtk.Box()  # empty spacer

    block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
```

---

## FIX 3 — Create `tests/test_chat_terminal_segment.py` (BUG #4)

**File:** `tests/test_chat_terminal_segment.py` (NEW FILE)

**Spec reference:** spec §3.9. Create 5 tests covering inline markdown + HIGH-6 invariants for the terminal segment.

```python
# tests/test_chat_terminal_segment.py
# Tests for Bug #3 + #8: _build_terminal_segment renders inline markdown
# and blocks javascript: links via make_safe_label per-line.

import pytest


def _gtk_skip():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        return True
    return False


class TestTerminalSegment:

    def test_bold_in_terminal_line(self):
        """Terminal content with **bold** must render as <b>bold</b>, not literal **."""
        if _gtk_skip():
            pytest.skip("GTK not available in test environment")
        from ui.views.chat_bubble import _build_terminal_segment
        widget = _build_terminal_segment({"content": "error with **bold** message"})
        # Walk widget tree to find the content label (nested in row > make_safe_label)
        def find_label_with(w, needle):
            if hasattr(w, "get_label"):
                if needle in w.get_label():
                    return True
            child = w.get_first_child()
            while child:
                if find_label_with(child, needle):
                    return True
                child = child.get_next_sibling()
            return False
        assert find_label_with(widget, "<b>bold</b>"), "bold not rendered in terminal line"

    def test_https_link_in_terminal(self):
        """Terminal content with [docs](https://...) must render the href."""
        if _gtk_skip():
            pytest.skip("GTK not available in test environment")
        from ui.views.chat_bubble import _build_terminal_segment
        widget = _build_terminal_segment({"content": "see [docs](https://example.com)"})
        def find_label_with(w, needle):
            if hasattr(w, "get_label"):
                if needle in w.get_label():
                    return True
            child = w.get_first_child()
            while child:
                if find_label_with(child, needle):
                    return True
                child = child.get_next_sibling()
            return False
        assert find_label_with(widget, 'href="https://example.com"')

    def test_javascript_link_blocked(self):
        """HIGH-6: javascript: links in terminal must be blocked by activate-link."""
        if _gtk_skip():
            pytest.skip("GTK not available in test environment")
        from ui.views.chat_bubble import _build_terminal_segment
        widget = _build_terminal_segment({"content": "see [x](javascript:alert(1))"})
        # Find the label with the href and verify activate-link returns True
        def find_and_emit(w):
            if hasattr(w, "get_label") and "javascript" in w.get_label():
                return w.emit("activate-link", "javascript:alert(1)")
            child = w.get_first_child()
            while child:
                result = find_and_emit(child)
                if result is not None:
                    return result
                child = child.get_next_sibling()
            return None
        result = find_and_emit(widget)
        assert result is True, "javascript: link not blocked in terminal"

    def test_plain_text_unchanged(self):
        """Regression: plain terminal text must render without Pango conversion."""
        if _gtk_skip():
            pytest.skip("GTK not available in test environment")
        from ui.views.chat_bubble import _build_terminal_segment
        widget = _build_terminal_segment({"content": "plain text"})
        def find_label_with(w, needle):
            if hasattr(w, "get_label"):
                # Strip the Pango wrapper tags to check the visible text
                import re
                visible = re.sub(r'<[^>]+>', '', w.get_label())
                if needle in visible:
                    return True
            child = w.get_first_child()
            while child:
                if find_label_with(child, needle):
                    return True
                child = child.get_next_sibling()
            return False
        assert find_label_with(widget, "plain text")

    def test_empty_content_returns_box(self):
        """BUG #7: empty terminal content must return an empty spacer, not a full block."""
        if _gtk_skip():
            pytest.skip("GTK not available in test environment")
        from ui.views.chat_bubble import _build_terminal_segment
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        widget = _build_terminal_segment({"content": ""})
        # The empty spacer is a plain Gtk.Box with no children.
        # A full terminal block would have the terminal-block CSS class.
        assert "terminal-block" not in widget.get_css_classes(), (
            "empty terminal should return spacer, not full block"
        )
```

---

## FIX 4 — Add streaming HIGH-6 tests (BUG #5)

**File:** `tests/test_streaming.py` (ADD tests to the existing file)

**Spec reference:** spec §3.11. Add 3 tests verifying the streaming bubble's activate-link guard.

Read the existing `tests/test_streaming.py` first to match its import style and test class structure. Then append this new class:

```python
class TestStreamingBubbleHigh6:
    """Bug #10: streaming label must have activate-link guard connected."""

    def test_streaming_javascript_blocked(self):
        """HIGH-6: build_streaming_bubble's label must block javascript: links."""
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            pytest.skip("GTK not available in test environment")

        from ui.views.chat_bubble import build_streaming_bubble
        _container, label = build_streaming_bubble("Agent")
        retval = label.emit("activate-link", "javascript:alert(1)")
        assert retval is True, "javascript: link not blocked in streaming label"

    def test_streaming_https_allowed(self):
        """HIGH-6: build_streaming_bubble's label must allow https: links."""
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            pytest.skip("GTK not available in test environment")

        from ui.views.chat_bubble import build_streaming_bubble
        _container, label = build_streaming_bubble("Agent")
        retval = label.emit("activate-link", "https://example.com/")
        assert retval is False, "https: link blocked in streaming label"

    def test_streaming_label_has_handler_connected(self):
        """The streaming label must have the activate-link handler connected."""
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            pytest.skip("GTK not available in test environment")

        from ui.views.chat_bubble import build_streaming_bubble
        _container, label = build_streaming_bubble("Agent")
        # If no handler is connected, emit returns False for ALL URIs.
        # Verify that javascript: specifically returns True (handler is active).
        assert label.emit("activate-link", "javascript:alert(1)") is True
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Make ONLY the changes described above. Do not refactor, rename, or reformat anything else.
- For Fix 4, read the existing `tests/test_streaming.py` first and match its style. Append the new class at the end.
- Do NOT touch any file other than the 3 listed.

## Verification commands (run these, paste the output)

```bash
cd /home/q/projects/crabcakes

# 1. Confirm type guards are in place (BUG #1)
xvfb-run -a python3 -c "
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from ui.views.chat_bubble import _build_heading_segment, _build_task_segment
# None content must NOT crash
h = _build_heading_segment({'level': 2, 'content': None})
t = _build_task_segment({'content': 42})
print('OK: type guards prevent crash on None/int content')
"

# 2. Confirm terminal empty-content guard (BUG #7)
xvfb-run -a python3 -c "
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from ui.views.chat_bubble import _build_terminal_segment
w = _build_terminal_segment({'content': ''})
classes = w.get_css_classes()
assert 'terminal-block' not in classes, f'empty terminal should be spacer, got: {classes}'
print('OK: empty terminal returns spacer (no terminal-block class)')
"

# 3. Run the new terminal tests (BUG #4)
xvfb-run -a python3 -m pytest tests/test_chat_terminal_segment.py -v

# 4. Run the streaming HIGH-6 tests (BUG #5)
xvfb-run -a python3 -m pytest tests/test_streaming.py -v

# 5. Full regression — no breakage
xvfb-run -a python3 -m pytest tests/test_chat_heading.py tests/test_chat_task_segment.py tests/test_chat_terminal_segment.py tests/test_streaming.py tests/test_presentation_injection.py tests/test_gtk_safe_link.py tests/test_markdown.py tests/test_block_parser.py tests/test_escaping.py tests/test_chat_render_handler.py -q
```

## Deliverables (COMPLETENESS checklist required)

When done, report:
1. Files changed with line numbers
2. Full output of all 5 verification commands above
3. `git diff ui/views/chat_bubble.py` output (showing only the type-guard additions)
4. COMPLETENESS checklist:
```
COMPLETENESS:
- [x/not done] Fix 1: heading/task type coercion (isinstance check) — evidence: (command 1 output)
- [x/not done] Fix 2: terminal empty-content guard — evidence: (command 2 output)
- [x/not done] Fix 3: test_chat_terminal_segment.py created with 5 tests — evidence: (command 3 output)
- [x/not done] Fix 4: streaming HIGH-6 tests added (3 tests) — evidence: (command 4 output)
- [x/not done] Full regression passes — evidence: (command 5 output)
```
