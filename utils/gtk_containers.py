"""
Utility functions for GTK container operations.

All functions in this module are pure GTK utilities — they depend only on
``gi.repository.Gtk`` and the Python standard library. No dependency on
``ui/``, ``agent/``, ``gateway/``, or ``models/``.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


def is_in_container(widget: Gtk.Widget | None, container: Gtk.Container | None) -> bool:
    """
    Check if *widget* is a direct child of *container* using sibling walk.

    PyGObject does NOT wire Python's ``__contains__`` operator onto GTK
    containers. ``widget in gtk_box`` raises ``TypeError``. This function
    provides a safe alternative via ``Gtk.Widget.get_first_child()`` and
    ``Gtk.Widget.get_next_sibling()``.

    Args:
        widget: The widget to find (or None).
        container: The container to search (or None).

    Returns:
        True if *widget* is a direct child of *container*, False otherwise
        (including when either argument is None or the container is empty).
    """
    if widget is None or container is None:
        return False
    child = container.get_first_child()
    while child is not None:
        if child is widget:
            return True
        child = child.get_next_sibling()
    return False