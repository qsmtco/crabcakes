# ui/views/feedbar.py
# Activity feed bar — displays live agent activity between toolbar and main content.
#
# UI ONLY — no business logic here. This module owns the feedbar widget.
# Events and content updates come from ActivityHandler via the public API below.
#
# Public API (used by ActivityHandler):
#   feedbar.set_status_text(markup)          — update the state label (Pango markup)
#   feedbar.set_progress_fraction(fraction)    — set 0.0..1.0 bar fill; stops any active pulse
#   feedbar.set_progress_hidden(hidden)       — show/hide the progress bar (opacity 0 or 1)
#   feedbar.set_progress_pulse(enable)       — start/stop GTK pulse animation
#   feedbar.pulse_progress()                  — advance the pulse by one step (call every ~100ms)
#   feedbar.set_progress_opacity(opacity)     — set bar opacity 0.0..1.0 (for subtle idle pulse)

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


class FeedBar(Gtk.Box):
    """
    Horizontal bar showing live agent/project activity.
    Sits between toolbar and main content area.

    Contains a vertical box: status label on top, progress bar below.
    """

    def __init__(self, on_feed_event=None):
        # Top-level is HORIZONTAL (original layout), inner content is VERTICAL
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_size_request(-1, 40)  # slightly taller to accommodate progress bar
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)

        self._on_feed_event = on_feed_event

        # Inner vertical box: label above, progress bar below
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        inner.set_hexpand(True)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        inner.set_margin_top(6)
        inner.set_margin_bottom(4)

        # Status label — shows state text (reasoning, streaming, done, etc.)
        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_valign(Gtk.Align.END)
        self._status_label.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 10">'
            'Response Status</span>'
        )

        # Progress bar — driven by ActivityHandler
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class("response-progress")
        self._progress_bar.set_show_text(False)
        self._progress_bar.set_opacity(0)  # hidden by default

        inner.append(self._status_label)
        inner.append(self._progress_bar)

        self.append(inner)

    # ── Public API (called by ActivityHandler) ───────────────────────────

    def set_status_text(self, markup):
        """Update the status label with Pango markup."""
        self._status_label.set_markup(markup)

    def set_progress_fraction(self, fraction):
        """Set progress bar fraction (0.0..1.0). Removes pulse, shows bar."""
        self._progress_bar.set_fraction(fraction)
        self._progress_bar.set_opacity(1)

    def set_progress_hidden(self, hidden):
        """Show or hide the progress bar (opacity 0 or 1)."""
        self._progress_bar.set_opacity(0 if hidden else 1)

    def set_progress_opacity(self, opacity):
        """Set the progress bar opacity (0.0..1.0). Used for subtle idle pulse."""
        self._progress_bar.set_opacity(opacity)

    def set_progress_pulse(self, enable):
        """Start or stop the pulse animation on the progress bar."""
        if enable:
            self._progress_bar.set_opacity(1)
            self._progress_bar.pulse()
        else:
            # Stop pulsing — ActivityHandler will call set_progress_fraction next
            # with a concrete value, which will override the pulse fill.
            pass  # no-op; set_fraction in set_progress_fraction stops pulse

    def pulse_progress(self):
        """Advance the progress bar by one pulse step."""
        self._progress_bar.pulse()

    # ── Legacy API (not used by ActivityHandler, kept for compatibility) ──

    def update(self, event_type: str, message: str) -> None:
        """
        Legacy compatibility method — delegates to the direct FeedBar API.

        ActivityHandler calls the direct API (set_status_text, set_progress_*).
        This method exists for any external callers that expect a generic
        update(event_type, message) interface.
        """
        # Map event_type to a colored status label the same way
        # ActivityHandler._update_feedbar() does.
        state_colors = {
            "idle": "#4ade80",
            "sending": "#f59e0b",
            "reasoning": "#f59e0b",
            "streaming": "#f59e0b",
            "tool_use": "#a855f7",
            "done": "#4ade80",
        }
        color = state_colors.get(event_type, "#6b6b7a")
        if message:
            markup = f'<span foreground="{color}">{message}</span>'
        else:
            markup = f'<span foreground="{color}">● {event_type.title()}</span>'
        self.set_status_text(markup)
        self.set_progress_hidden(event_type == "idle")
