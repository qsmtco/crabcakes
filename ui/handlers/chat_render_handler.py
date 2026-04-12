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
    Orchestrates text processing and bubble widget creation for chat messages.

    Processing pipeline per message:
      1. escape_for_pango(text)      — protect existing Pango markup tags
      2. format_markdown(text)       — convert markdown -> Pango inline markup
      3. build_role_bubble(role, text) — create styled GTK bubble widget

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

    # ── Async (thread-safe) ──────────────────────────────────────────────

    def render(self, role: str, text: str, session_key: str, on_bubble_ready, on_error=None):
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
                bubble = build_role_bubble(role, text)

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

    def render_sync(self, role: str, text: str, session_key: str = None):
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
        # Pass raw text — build_role_bubble() owns the full pipeline:
        # extract_blocks() on raw text, then per-segment escape+markdown/highlight.
        return build_role_bubble(role, text)

    # ── Internal ─────────────────────────────────────────────────────────

    def _dispatch(self, fn):
        """Call fn on the GTK main thread."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
