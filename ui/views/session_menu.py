# ui/views/session_menu.py
# Right-click session switcher menu for any widget.
#
# Usage:
#   from ui.views.session_menu import show_session_menu
#   show_session_menu(parent_widget, agent_name, sessions, on_select)
#
#   sessions: list[str] of session keys
#   on_select: callable(session_key: str) — called with the selected session
#
# Can be attached to any visible GTK widget for positioning.
#
# GTK4 note: Gtk.ModelButton was removed in GTK4. We use Gtk.Popover
# with a Gtk.ListBox instead, which is the recommended pattern.

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


def show_session_menu(parent, agent_name, sessions, on_select):
    """
    Build and popup a right-click menu listing all sessions for an agent.
    Clicking a session item calls on_select(session_key).

    Args:
        parent:       Any visible GTK widget — used for positioning the popup.
        agent_name:   Display name for the agent (shown as menu header).
        sessions:     List of session key strings.
        on_select:    Callable(session_key: str) — called with the selected session.
    """
    popover = Gtk.Popover()

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    vbox.set_margin_top(6)
    vbox.set_margin_bottom(6)
    vbox.set_margin_start(6)
    vbox.set_margin_end(6)

    # Header — agent name, non-interactive
    header = Gtk.Label()
    header.set_markup(f"<b>{agent_name}</b>")
    header.set_sensitive(False)
    header.set_margin_bottom(4)
    vbox.append(header)

    # Separator
    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    sep.set_margin_bottom(4)
    vbox.append(sep)

    if not sessions:
        empty = Gtk.Label(label="No sessions available")
        empty.add_css_class("dim-label")
        vbox.append(empty)
    else:
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        for sk in sessions:
            row = Gtk.ListBoxRow()
            row.set_activatable(True)
            row.set_selectable(False)

            label = Gtk.Label(label=_shorten_session_key(sk), xalign=0)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(8)
            label.set_margin_end(8)
            row.set_child(label)
            row._session_key = sk
            list_box.append(row)
        list_box.connect("row-activated", lambda _lb, row: _on_selected(popover, row._session_key, on_select))
        vbox.append(list_box)

    popover.set_child(vbox)
    popover.set_parent(parent)
    popover.popup()


def _on_selected(popover, session_key, on_select):
    popover.popdown()
    popover.unparent()
    on_select(session_key)


def _shorten_session_key(key: str) -> str:
    """Shorten a session key for display in the menu.

    Examples:
        agent:qaster:main → main
        agent:qaster:telegram:direct:7478874934 → telegram:direct:7478874934
        agent:qaster:subagent:abc-123 → subagent:abc-123
    """
    parts = key.split(":")
    if len(parts) >= 3 and parts[0] == "agent":
        # Strip "agent:<name>:" prefix, show the rest
        return ":".join(parts[2:])
    return key
