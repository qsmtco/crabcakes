# ui/views/chat_control_bar.py
# Chat control bar — sits between the chat notebook and user input.
#
# UI ONLY — no business logic. Receives updates via update() callback.
#
# Public API:
#   bar = ChatControlBar()
#   bar.update(event_type, message)  # stubbed — wire later

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


class ChatControlBar(Gtk.Label):
    """
    Horizontal bar showing controls/info for the active chat tab.
    Placed between the notebook and the user input area.
    """

    def __init__(self):
        super().__init__()
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 10">'
            'Chat Control Bar</span>'
        )

    def update(self, event_type, message):
        """TODO: wire to real control logic."""
        pass
