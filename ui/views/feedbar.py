# ui/feedbar.py
# Activity feed bar — displays live agent activity between toolbar and main content.
#
# UI ONLY — no business logic here. This module owns the feedbar widget.
# Events and content updates come from callbacks passed at construction time.
#
# Public API:
#   feedbar = FeedBar(on_feed_event=None)
#   feedbar.update(event_type, message)  # called by window with feed events

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


class FeedBar(Gtk.Box):
    """
    Horizontal bar showing live agent/project activity.
    Sits between toolbar and main content area.
    """

    def __init__(self, on_feed_event=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_size_request(-1, 32)
        self.set_hexpand(True)

        self._on_feed_event = on_feed_event

        # Placeholder label — replace with real feed content
        self._feed_label = Gtk.Label()
        self._feed_label.set_halign(Gtk.Align.START)
        self._feed_label.set_valign(Gtk.Align.CENTER)
        self._feed_label.set_margin_start(12)
        self._feed_label.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 10">'
            'Response Status</span>'
        )
        self.append(self._feed_label)

    # ── Public API ─────────────────────────────────────────────────────────

    def update(self, event_type, message):
        """
        Update the feed bar with an activity event.
        Called by window._on_ws_event when feed events fire.
        """
        # TODO: wire to real feed event logic
        pass
