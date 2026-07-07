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