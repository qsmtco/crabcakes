"""Test which entities Pango's XML parser handles."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import subprocess, os, sys

entities = ['&amp;', '&lt;', '&gt;', '&quot;', '&apos;', '&copy;', '&reg;', '&nbsp;', '&#42;', '&#x2a;', '&amp', '&lt', '&gt', '&copy']

for ent in entities:
    # Wrap in <b>...</b> for context
    markup = f'X{ent}Y'
    result = subprocess.run([
        'python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
try:
    label.set_markup({markup!r})
    print("OK")
except Exception as e:
    print(f"ERR: {{e}}")
'''
    ], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
    warn = 'WARNING' in result.stderr
    err = 'Error on' in result.stderr
    status = 'OK' if not (warn or err) else f'WARN={warn} ERR={err}'
    print(f'{ent!r:15} -> {status}')