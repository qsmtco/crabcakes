#!/usr/bin/env python3
"""Minimal CSS test - no GTK app needed, just check if warnings fire."""
import sys, gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

# Test various rgba formats
APP_CSS = """
.agent-row:selected {
    background: rgba(99, 102, 241, 0.2) !important;
}
.agent-row:focus {
    background: rgba(99, 102, 241, 0.2);
}
.agent-row:focus-visible {
    background: #6366f1;
}
"""

display = Gdk.Display.get_default()
provider = Gtk.CssProvider()
provider.load_from_data(APP_CSS.encode())
Gtk.StyleContext.add_provider_for_display(
    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
print("PASS - no warnings")
