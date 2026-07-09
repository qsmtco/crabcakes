import sys, os, subprocess, base64
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Various test inputs that might trigger "Failed to set text"
tests = [
    '<<script>alert</script>>',
    '<<a href=>><</a>>',
    'see &gt here &lt there',
    '<notag>',
    '</b>',
    '<b>bold',
    '<>',
    '< >',
    '\xc2\xa0',  # non-breaking space
]
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

for t in tests:
    escaped = escape_for_pango(t)
    formatted = format_markdown(escaped)
    label = Gtk.Label()
    try:
        label.set_markup(formatted)
        print(f'PASS: input={t!r} -> {formatted!r}')
    except Exception as e:
        print(f'FAIL: input={t!r}: {e}')