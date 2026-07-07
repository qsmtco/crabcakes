# tests/test_streaming.py
# Tests for models/streaming.py — StreamingBubble dataclass.

import pytest
from models import StreamingBubble


class TestStreamingBubbleDefaults:
    def test_plain_text_defaults_to_empty_string(self):
        """plain_text must default to '' — streaming starts with no accumulated text."""
        sb = StreamingBubble(container="c", label="l", role="Agent")
        assert sb.plain_text == ""

    def test_bubble_defaults_to_none(self):
        """bubble must default to None — not set until bubble widget is created."""
        sb = StreamingBubble(container="c", label="l", role="Agent")
        assert sb.bubble is None


class TestStreamingBubbleFields:
    def test_all_fields_can_be_set(self):
        """Every field accepts a value without error."""
        sb = StreamingBubble(
            container="container_obj",
            label="label_obj",
            role="Agent",
            plain_text="hello",
            bubble="bubble_obj",
        )
        assert sb.container == "container_obj"
        assert sb.label == "label_obj"
        assert sb.role == "Agent"
        assert sb.plain_text == "hello"
        assert sb.bubble == "bubble_obj"

    def test_plain_text_can_be_mutated_in_place(self):
        """plain_text is mutable — used by update_streaming to track cumulative text."""
        sb = StreamingBubble(container="c", label="l", role="Agent")
        sb.plain_text = "partial response"
        assert sb.plain_text == "partial response"
        sb.plain_text = "full response"
        assert sb.plain_text == "full response"

    def test_role_accepts_you(self):
        """role field accepts "You" for outgoing streaming bubbles."""
        sb = StreamingBubble(container="c", label="l", role="You")
        assert sb.role == "You"


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
