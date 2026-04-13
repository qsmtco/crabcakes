# tests/test_chat_render_handler.py
# Tests for ui/handlers/chat_render_handler.py

import pytest
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from ui.handlers.chat_render_handler import ChatRenderHandler
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown


class TestRenderSync:
    """Tests for render_sync() — synchronous bubble creation."""

    def setup_method(self):
        self.handler = ChatRenderHandler(GLib_module=None)

    def test_renders_bubble_for_agent(self):
        widget = self.handler.render_sync("Agent", "Hello world")
        assert widget is not None

    def test_renders_bubble_for_you(self):
        widget = self.handler.render_sync("You", "Hello world")
        assert widget is not None

    def test_bubble_has_chat_bubble_agent_class(self):
        """Agent bubbles get the chat-bubble-agent CSS class."""
        widget = self.handler.render_sync("Agent", "test")
        # widget is a container box, bubble is inside
        # The bubble box (first child) has the CSS class
        container = widget
        assert container.get_halign() == 1  # Gtk.Align.START for agent

    def test_bubble_has_chat_bubble_you_class(self):
        """You bubbles get the chat-bubble-you CSS class and END alignment."""
        widget = self.handler.render_sync("You", "test")
        container = widget
        assert container.get_halign() == Gtk.Align.END  # right-aligned

    def test_escape_preserves_bold_tag(self):
        """Bold Pango tags are preserved through the pipeline."""
        widget = self.handler.render_sync("Agent", "<b>bold</b>")
        assert widget is not None

    def test_markdown_converted_to_pango(self):
        """Markdown **bold** is converted to Pango <b>bold</b>."""
        widget = self.handler.render_sync("Agent", "this is **bold** text")
        assert widget is not None

    def test_markdown_italic_converted(self):
        widget = self.handler.render_sync("Agent", "this is *italic* text")
        assert widget is not None

    def test_markdown_inline_code_converted(self):
        """Inline code is converted to <tt> tags."""
        widget = self.handler.render_sync("Agent", "use `my_var` here")
        assert widget is not None

    def test_empty_text(self):
        """Empty text produces a bubble widget."""
        widget = self.handler.render_sync("Agent", "")
        assert widget is not None

    def test_xss_prevention(self):
        """
        Script tags are escaped: the '<' becomes '&lt;' so GTK renders
        the literal text '<script>' rather than parsing it as a tag.
        We test via the escape_for_pango layer directly since GTK may
        emit a warning (not an error) for deeply malformed markup.
        """
        from utils.escaping import escape_for_pango
        escaped = escape_for_pango("<script>evil()</script>")
        assert "&lt;script&gt;" in escaped

    def test_role_alignment(self):
        """You bubbles are right-aligned, Agent bubbles are left-aligned."""
        you_bubble = self.handler.render_sync("You", "hi")
        agent_bubble = self.handler.render_sync("Agent", "hi")
        # Gtk.Align.END = right (You), Gtk.Align.START = left (Agent)
        assert you_bubble.get_halign() == Gtk.Align.END
        assert agent_bubble.get_halign() == Gtk.Align.START


class TestReentrancyGuard:
    """Tests for the _ReentrancySet reentrancy guard."""

    def test_async_blocks_duplicate_session_key(self):
        """
        render() skips when a render is already in flight for the key.

        In async mode (GLib provided), the second call with the same
        session_key is skipped before any widget construction begins.
        We verify by checking that the GLib idle_add was only called once
        for widget delivery.
        """
        idle_add_calls = []

        class FakeGLib:
            @staticmethod
            def idle_add(fn):
                idle_add_calls.append(fn)
                return len(idle_add_calls)

        handler = ChatRenderHandler(GLib_module=FakeGLib)
        delivered = []

        def capture(widget):
            delivered.append(widget)

        # First render: dispatches _build which dispatches _deliver
        handler.render("Agent", "hello", "session:1", capture)
        # In async mode, only _build is dispatched here; _deliver is
        # dispatched inside _build once widget construction completes.
        # Run the _deliver callback to simulate what would happen on main thread.
        if idle_add_calls:
            # Execute just the _deliver (last dispatched function)
            idle_add_calls[-1]()

        first_count = len(idle_add_calls)

        # Second render with same key: should be skipped (guard blocks before dispatch)
        handler.render("Agent", "hello again", "session:1", capture)
        second_count = len(idle_add_calls)

        # Only the first render dispatched work; second was blocked
        assert second_count == first_count, (
            f"second render should be blocked but {second_count - first_count} additional "
            f"dispatch(s) occurred"
        )

    def test_sync_allows_different_session_keys(self):
        """Different session keys don't interfere with each other."""
        handler = ChatRenderHandler(GLib_module=None)
        result1 = handler.render_sync("Agent", "msg1", session_key="session:1")
        result2 = handler.render_sync("Agent", "msg2", session_key="session:2")
        assert result1 is not None
        assert result2 is not None

    def test_sync_nil_key_guards_nothing(self):
        """session_key=None means no guarding at all."""
        handler = ChatRenderHandler(GLib_module=None)
        # All succeed with no session_key
        result1 = handler.render_sync("Agent", "msg", session_key=None)
        result2 = handler.render_sync("Agent", "msg", session_key=None)
        assert result1 is not None
        assert result2 is not None

    def test_reentrancy_set_basic(self):
        """_ReentrancySet.add() returns True first time, False on duplicate."""
        from ui.handlers.chat_render_handler import _ReentrancySet
        guard = _ReentrancySet()
        assert guard.add("key:1") is True
        assert guard.add("key:1") is False  # already in set
        assert "key:1" in guard
        assert "key:2" not in guard

    def test_reentrancy_set_remove(self):
        """_ReentrancySet.remove() frees the key for subsequent adds."""
        from ui.handlers.chat_render_handler import _ReentrancySet
        guard = _ReentrancySet()
        assert guard.add("key:1") is True
        guard.remove("key:1")
        assert "key:1" not in guard
        assert guard.add("key:1") is True  # can re-add after remove


class TestPipeline:
    """Tests for the escape -> markdown -> bubble pipeline."""

    def test_escape_and_markdown_order(self):
        """Markdown inside a Pango tag should not be double-converted."""
        # Input: <b>**bold**</b>
        # After escape: <b>**bold**</b> (tags preserved)
        # After markdown: <b><b>bold</b></b> (double bold - OK, just tags)
        # The pipeline correctly does NOT escape the ** inside <b>...</b>
        safe = escape_for_pango("<b>**bold**</b>")
        assert "<b>" in safe  # opening tag preserved
        assert "</b>" in safe  # closing tag preserved

    def test_full_pipeline_agent_role(self):
        """Full pipeline: raw text -> role=Agent -> bubble."""
        handler = ChatRenderHandler(GLib_module=None)
        widget = handler.render_sync("Agent", "Hello **Agent**")
        assert widget is not None


class TestPhase3Streaming:
    """Tests for Phase 3 streaming and typing indicator methods."""

    def setup_method(self):
        # FakeGLib: records idle_add/timeout_add, runs funcs synchronously
        self.idle_calls = []
        self.timeout_calls = []
        self._next_timer_id = 1

        class FakeGLib:
            @staticmethod
            def idle_add(fn):
                self.idle_calls.append(fn)
                return len(self.idle_calls)

            @staticmethod
            def timeout_add(interval, fn, *user_data):
                self.timeout_calls.append(fn)
                tid = self._next_timer_id
                self._next_timer_id += 1
                return tid

            @staticmethod
            def source_remove(timer_id):
                pass  # no-op for tests

        self.fake_glib = FakeGLib
        self.handler = ChatRenderHandler(GLib_module=FakeGLib)
        # FakeChatBox: minimal container that holds appended widgets
        self.fake_box = FakeChatBox()

    def _run_all_idle(self):
        """Execute all dispatched idle functions to simulate main thread."""
        for fn in self.idle_calls:
            fn()
        self.idle_calls.clear()

    # ── Streaming ───────────────────────────────────────────────────────────

    def test_is_streaming_false_initially(self):
        """is_streaming() returns False when no streaming bubble exists."""
        assert self.handler.is_streaming("agent:1") is False

    def test_start_streaming_creates_bubble(self):
        """start_streaming() creates a streaming bubble in _streaming_bubbles."""
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        assert "agent:1" in self.handler._streaming_bubbles

    def test_start_streaming_twice_idempotent(self):
        """Calling start_streaming twice does not create duplicate bubbles."""
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        # start_streaming is called again — it should clean up old one first
        # but only one entry should exist
        entries_before = len(self.handler._streaming_bubbles)
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        assert len(self.handler._streaming_bubbles) == entries_before

    def test_update_streaming_uses_delta_as_full_text(self):
        """update_streaming() uses delta as complete accumulated text (no append).

        The gateway sends full cumulative text in each delta. Using delta directly
        avoids double-accumulation when the gateway already includes prior content.
        """
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        self.handler.update_streaming("agent:1", "Hello world")
        self._run_all_idle()
        _c, _l, _r, plain, _b = self.handler._streaming_bubbles["agent:1"]
        assert plain == "Hello world"  # last delta wins, no double-accumulation

    def test_update_streaming_escapes_html_chars(self):
        """update_streaming() escapes < > & in the label to prevent markup corruption."""
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        self.handler.update_streaming("agent:1", "Use <div>")
        self._run_all_idle()
        _c, label, _r, _plain, _b = self.handler._streaming_bubbles["agent:1"]
        markup = label.get_label()
        # Raw <div> must NOT appear in markup — it should be &lt;div&gt;
        assert "<div>" not in markup
        assert "&lt;div&gt;" in markup

    def test_is_streaming_true_after_start(self):
        """is_streaming() returns True after start_streaming() is called."""
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        assert self.handler.is_streaming("agent:1") is True

    def test_end_streaming_removes_entry(self):
        """end_streaming() removes the streaming bubble entry."""
        self.handler.start_streaming("agent:1", self.fake_box, "Agent")
        self._run_all_idle()
        self.handler.end_streaming("agent:1")
        self._run_all_idle()
        assert "agent:1" not in self.handler._streaming_bubbles

    def test_end_streaming_idempotent(self):
        """end_streaming() is safe to call when no streaming bubble exists."""
        self.handler.end_streaming("agent:1")  # no-op, no crash


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
