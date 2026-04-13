# ui/handlers/chat_render_handler.py
# Chat render handler — coordinates text processing and bubble widget creation.
#
# Ported from deadcode's formatters.py (Phase 1 of Chat Formatting Port).
# Security: No secrets, no file I/O, no network calls.
#
# Thread safety: all GTK calls dispatched via GLib.idle_add when GLib is set.
# If GLib is None (tests), GTK calls are made directly — only safe when
# the caller is already on the main thread.
#
# Reentrancy guard: _ReentrancySet prevents concurrent renders for the same
# session_key. If a render is already in-flight for a key, subsequent calls
# are skipped silently. This avoids visual glitches when multiple events
# arrive simultaneously for the same session.
#
# Public API:
#   render(role, text, session_key, on_bubble_ready, on_error=None)
#       Escape + markdown-convert text, build bubble, call on_bubble_ready(widget)
#       on the main thread (via GLib.idle_add when available).
#       session_key enables reentrancy guarding.
#
#   render_sync(role, text, session_key=None) -> Gtk.Widget
#       Synchronous version — only call from the main thread.

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
from ui.views.chat_bubble import build_role_bubble


class _ReentrancySet:
    """
    Tracks which session keys are currently being rendered.

    Prevents concurrent renders for the same session — if a render is
    already in-flight for a key, subsequent calls for that key are skipped.

    Mimics deadcode's _ReentrancySet (chat.py lines 19–33).
    """

    def __init__(self):
        self._keys: set[str] = set()

    def add(self, key: str) -> bool:
        """Add a key. Returns True if not already present (not in flight)."""
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def remove(self, key: str):
        """Remove a key when rendering is complete."""
        self._keys.discard(key)

    def __contains__(self, key: str) -> bool:
        return key in self._keys


class ChatRenderHandler:
    """
    Orchestrates bubble widget creation for chat messages.

    Pipeline (owned by build_role_bubble()):
      1. extract_blocks(raw_text)          — split into typed segments
      2. Per segment:
         - text   → escape_for_pango() + format_markdown()
         - code   → syntax_highlight() (HTML-escapes internally)
         - quote  → escape_for_pango() + format_markdown()
         - heading/task/terminal → escape_for_pango()
      3. Wrap each segment in GTK widgets per CSS classes

    Phase 3 addition: streaming bubbles — text updates live as the agent types.

    Thread safety: render() dispatches GTK calls via GLib.idle_add.
    Use render_sync() only when already on the GTK main thread.

    Reentrancy guard: concurrent renders for the same session_key are skipped.
    This prevents visual glitches when multiple events arrive simultaneously.

    Args:
        GLib_module: gi.repository.GLib or None — for thread-safe GTK calls
    """

    def __init__(self, GLib_module=None):
        self._GLib = GLib_module
        self._reentrancy = _ReentrancySet()
        # Phase 3: streaming bubbles — session_key → (container, label, role, plain_text)
        self._streaming_bubbles: dict = {}
        # Phase 5b: message grouping — tracks last role+session_key for tight spacing
        self._last_message_key: str = None
        self._on_forward_message = None   # set via set_on_forward_message()
        # Phase 5: MainContent reference for self-contained scroll operations
        self._main_content = None

    # ── Async (thread-safe) ──────────────────────────────────────────────

    def render(self, role: str, text: str, session_key: str, on_bubble_ready, on_forward_click=None, on_error=None):
        """
        Process text and produce a bubble widget asynchronously.

        Args:
            role:           "You" or "Agent"
            text:           Raw message text (no markup assumed)
            session_key:    Session key for reentrancy guarding — if a render is
                           already in-flight for this key, this call is skipped.
            on_bubble_ready: callback(widget) — called on main thread with bubble
            on_error:       optional callback(error_msg) — called on main thread
                           if an exception occurs during processing
        """
        if not self._reentrancy.add(session_key):
            return  # render already in flight for this session_key

        def _build():
            try:
                # Pass raw text — build_role_bubble() owns the full pipeline.
                bubble = build_role_bubble(role, text, on_forward_click=on_forward_click)

                def _deliver():
                    self._reentrancy.remove(session_key)
                    on_bubble_ready(bubble)

                self._dispatch(_deliver)
            except Exception as exc:
                self._reentrancy.remove(session_key)
                if on_error:
                    self._dispatch(lambda: on_error(str(exc)))

        self._dispatch(_build)

    # ── Sync (main thread only) ──────────────────────────────────────────

    def set_on_forward_message(self, cb):
        """Set callback for forward button: cb(text, anchor_widget)."""
        self._on_forward_message = cb

    def set_main_content(self, main_content):
        """Set MainContent reference for self-contained scroll operations."""
        self._main_content = main_content

    def render_sync(self, role: str, text: str, session_key: str = None, on_forward_click=None, forwarded_from: str = None):
        """
        Process text and return a bubble widget synchronously.

        WARNING: Only call this when already on the GTK main thread.
        For use in signal handlers and idle callbacks.

        Args:
            role:  "You" or "Agent"
            text:  Raw message text
            session_key: Optional session key for reentrancy guarding.
                       If a render is in-flight for this key, returns None.

        Returns:
            Gtk.Widget (a bubble container box), or None if re-entrant.
        """
        if session_key is not None and session_key in self._reentrancy:
            return None
        current_key = f"{role}:{session_key}" if session_key else None
        tight = (current_key == self._last_message_key) and self._last_message_key is not None
        bubble = build_role_bubble(role, text, on_forward_click=on_forward_click, tight=tight, session_key=session_key, forwarded_from=forwarded_from)
        self._last_message_key = current_key
        return bubble


    # ── Streaming bubbles (Phase 3) ────────────────────────────────────

    def start_streaming(self, session_key: str, container: Gtk.Box, role: str = "Agent"):
        """
        Start a streaming response bubble in container.

        Creates a pending bubble with a cursor (▍) that text will be appended to.
        If a streaming bubble already exists for session_key, clears it first.

        Args:
            session_key: Session key for this streaming bubble.
            container:   The chat box Gtk.Box to append the bubble to.
            role:        "Agent" or "You" — determines bubble alignment.
        """
        # Clear any existing streaming bubble for this session
        if session_key in self._streaming_bubbles:
            self.end_streaming(session_key)

        from ui.views.chat_bubble import build_streaming_bubble
        bubble, label = build_streaming_bubble(role)

        # Store synchronously so end_streaming can access bubble even before
        # _show runs on the main thread (important when end_streaming is called
        # immediately after start_streaming from the same dispatch chain).
        self._streaming_bubbles[session_key] = (container, label, role, "", bubble)

        def _show():
            container.append(bubble)

        self._dispatch(_show)

    def is_streaming(self, session_key: str) -> bool:
        """Return True if a streaming bubble exists for session_key."""
        return session_key in self._streaming_bubbles

    def update_streaming(self, session_key: str, delta_text: str):
        """
        Update the streaming bubble label for session_key.

        The gateway sends FULL cumulative text in each delta (each delta contains
        all text accumulated so far). Use delta_text directly — do NOT append
        to the stored plain text, as that would double-accumulate.

        Safe to call from any thread.
        """
        if session_key not in self._streaming_bubbles:
            print(f"[STREAM] update_streaming: SKIP sk={session_key!r} not in _streaming_bubbles")
            return

        container, label, role, _old_plain, _bubble = self._streaming_bubbles[session_key]

        def _update():
            from utils.escaping import escape_for_pango
            # delta_text is already the complete accumulated text — use it directly
            self._streaming_bubbles[session_key] = (container, label, role, delta_text, _bubble)
            escaped = escape_for_pango(delta_text)
            label.set_markup(escaped + "<tt>▍</tt>")

        self._dispatch(_update)

    def end_streaming(self, session_key: str):
        """
        End streaming for session_key: remove cursor and replace with final bubble.

        The streaming bubble is replaced with a proper rendered final bubble.
        """
        if session_key not in self._streaming_bubbles:
            return

        container, label, role, plain, streaming_bubble = self._streaming_bubbles.pop(session_key)

        def _finalize():
            # Use tracked plain text directly (cursor already absent after pop)
            full_text = plain

            # Remove streaming bubble widget
            if streaming_bubble in container:
                container.remove(streaming_bubble)

            # Build and append final bubble
            final_bubble = build_role_bubble(role, full_text, on_forward_click=self._on_forward_message)
            container.append(final_bubble)
            if self._main_content is not None:
                self._main_content.scroll_chat_to_bottom()

        self._dispatch(_finalize)
        # Reset message grouping key so next message starts fresh
        self._last_message_key = None

    def render_event_card(self, event_type: str, container: Gtk.Box, **kwargs):
        """
        Render a special event card into container.

        Args:
            event_type: "file_read" | "edit_proposal" | "tool_call" | "error"
            container: Parent box to append the card widget to.
            kwargs: Per-event-type fields:
                file_read:   file_path, snippet="", line_range=""
                edit_proposal: file_path, diff=""
                tool_call:   tool_name, detail=""
                error:       error_msg
                thinking:    thought_text
        """
        from ui.views.chat_bubble import (
            create_file_card,
            create_edit_card,
            create_tool_card,
            create_error_bubble,
        )

        if event_type == "file_read":
            card = create_file_card(kwargs.get("file_path", ""),
                                   kwargs.get("snippet", ""),
                                   kwargs.get("line_range", ""))
        elif event_type == "edit_proposal":
            card = create_edit_card(kwargs.get("file_path", ""),
                                    kwargs.get("diff", ""))
        elif event_type == "tool_call":
            card = create_tool_card(kwargs.get("tool_name", ""),
                                    kwargs.get("detail", ""))
        elif event_type == "error":
            card = create_error_bubble(kwargs.get("error_msg", ""))
        elif event_type == "thinking":
            # Fall back to plain text bubble for thoughts
            text = kwargs.get("thought_text", "")
            card = build_role_bubble("Agent", text)
        else:
            # Unknown event type — ignore silently
            return

        def _append():
            container.append(card)
            if self._main_content is not None:
                self._main_content.scroll_chat_to_bottom()

        self._dispatch(_append)


    def _dispatch(self, fn):
        """Call fn on the GTK main thread."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
