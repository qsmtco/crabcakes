"""Verify both bugs produce Gtk-WARNING at set_markup() time."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
import sys, os
sys.path.insert(0, '/home/q/projects/crabcakes')
os.environ['GDK_BACKEND'] = 'x11'

from utils.markdown import format_markdown
from utils.escaping import escape_for_pango

cases = {
    "Debugger (nested <a>)": 'Click <a href="https://example.com">here</a> for info.',
    "QTR (orphan <a>)":      'See <a href="..."> for tags',
}

for name, content in cases.items():
    print(f"\n=== {name} ===")
    formatted = format_markdown(escape_for_pango(content))
    print(f"  Output:\n{formatted}")
    try:
        label = Gtk.Label()
        label.set_markup(formatted)
        print(f"  Render OK")
    except Exception as e:
        print(f"  Render failed: {e}")