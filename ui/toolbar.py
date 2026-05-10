# ui/toolbar.py
# Top toolbar — horizontal bar across the top of the window

import gi
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from ui.handlers.chat_handler import STREAMING_ENABLED

class Toolbar(Gtk.Box):
    """
    Top toolbar widget.
    A horizontal bar that will contain app-level actions.
    Currently: Connect button (right-justified) with status label.
    Extends Gtk.Box with horizontal orientation.
    """

    def __init__(self, on_connect_clicked=None):
        # Initialize as a horizontal box — children lay out left to right
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        # Fixed height of 40 pixels, width stretches to fill window (-1 = stretch)
        self.set_size_request(-1, 40)

        # Store the connect button callback
        self._on_connect_clicked = on_connect_clicked

        # Stream toggle — left side of toolbar
        self._stream_btn = Gtk.ToggleButton(label="Stream: OFF")
        self._stream_btn.set_size_request(100, -1)
        self._stream_btn.set_active(STREAMING_ENABLED)
        self._update_stream_label()
        self._stream_btn.connect("toggled", self._on_stream_toggled)

        # Spacer — expands to push everything after it to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)

        # Right-aligned box containing toolbar buttons
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Connection status label
        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.END)
        self._status_label.set_valign(Gtk.Align.CENTER)
        self._status_label.set_margin_end(8)
        self._status_label.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 10">● Not connected</span>')

        # Connect button
        self._connect_btn = Gtk.Button(label="Connect")
        self._connect_btn.add_css_class("suggested-action")
        self._connect_btn.set_size_request(90, -1)
        self._connect_btn.connect("clicked", self._on_connect_click)

        # Add spacing between buttons (if more are added later)
        right_box.set_spacing(6)
        right_box.append(self._status_label)
        right_box.append(self._connect_btn)

        # Assemble: stream btn | spacer | right content
        self.append(self._stream_btn)
        self.append(spacer)
        self.append(right_box)

    def _on_connect_click(self, *args):
        """Called when Connect button is clicked. Delegates to window's callback."""
        if self._on_connect_clicked is not None:
            self._on_connect_clicked()

    def _on_stream_toggled(self, button):
        """Toggle streaming on/off and update the button label."""
        import ui.handlers.chat_handler as chat_handler
        chat_handler.STREAMING_ENABLED = button.get_active()
        self._update_stream_label()

    def _update_stream_label(self):
        """Update stream button label to reflect current state."""
        import ui.handlers.chat_handler as chat_handler
        self._stream_btn.set_label(
            "Stream: ON" if chat_handler.STREAMING_ENABLED else "Stream: OFF"
        )

    # ── State update methods ─────────────────────────────────────────────────

    def update_connection_state(self, state):
        """
        Update button label and status label based on connection state.
        state: "disconnected" | "connecting" | "connected" | "offline"
        """
        if state == "connecting":
            self._connect_btn.set_label("Connecting…")
            self._status_label.set_markup(
                '<span foreground="#f59e0b" font_desc="Sans 10">● Connecting</span>')
        elif state == "connected":
            self._connect_btn.set_label("Disconnect")
            self._connect_btn.remove_css_class("suggested-action")
            self._connect_btn.add_css_class("destructive-action")
            self._status_label.set_markup(
                '<span foreground="#22c55e" font_desc="Sans 10">● Connected</span>')
        elif state == "offline":
            self._connect_btn.set_label("Connect")
            self._connect_btn.remove_css_class("destructive-action")
            self._connect_btn.add_css_class("suggested-action")
            self._status_label.set_markup(
                '<span foreground="#8b8ba0" font_desc="Sans 10">● Offline — local agents available</span>')
        elif state == "disconnected":
            self._connect_btn.set_label("Connect")
            self._connect_btn.remove_css_class("destructive-action")
            self._connect_btn.add_css_class("suggested-action")
            self._status_label.set_markup(
                '<span foreground="#6b6b7a" font_desc="Sans 10">● Not connected</span>')
