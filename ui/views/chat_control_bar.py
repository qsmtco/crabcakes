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

    def update(self, event_type: str, message: str) -> None:
        """
        Update the control bar with current session/activity info.

        event_type: state name from ActivityHandler (idle/sending/reasoning/
                   streaming/tool_use/done) or 'text' for direct markup.
        message:   Pango markup string or fallback text.
        """
        if event_type == "text":
            # Direct markup passed via set_control_bar_text()
            self.set_markup(message)
        else:
            # State-based update — show colored state dot + message
            state_colors = {
                "idle": "#4ade80",      # green
                "sending": "#f59e0b",  # amber
                "reasoning": "#f59e0b",
                "streaming": "#f59e0b",
                "tool_use": "#a78bfa",  # purple
                "done": "#4ade80",
            }
            color = state_colors.get(event_type, "#6b6b7a")
            if message:
                markup = f'<span foreground="{color}" font_desc="Sans 10">{message}</span>'
            else:
                markup = f'<span foreground="{color}" font_desc="Sans 10">● {event_type.title()}</span>'
            self.set_markup(markup)
