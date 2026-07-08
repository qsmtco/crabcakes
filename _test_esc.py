"""Trace exactly what escape_for_pango does to the broken bug output."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango

# The literal broken output from the auto-link bug
broken_output = 'see &lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'

print('Input:')
print(repr(broken_output))
print()

escaped = escape_for_pango(broken_output)
print('After escape_for_pango:')
print(repr(escaped))
print()

# Now test what the GTK parser would see
# (without format_markdown running — we want to isolate escape_for_pango)
print('Try to set_markup the escaped result:')
import subprocess
import os
result = subprocess.run([
    'python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
label.set_markup({escaped!r})
print("OK")
'''
], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
print('stdout:', result.stdout.strip())
print('stderr:', result.stderr.strip()[:500])