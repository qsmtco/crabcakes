import sys, os, subprocess
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

raw = """$ python3 <<'PYEOF'
import sys
sys.path.insert(0, '.')
from utils.escaping import _strict_unescape
import re"""

escaped = escape_for_pango(raw)
formatted = format_markdown(escaped)
print('Formatted:', repr(formatted))
print('Length:', len(formatted))

# Write a test script that reads the markup from argv
with open('/tmp/test_label2.py', 'w') as f:
    f.write('''
import sys, os, gi
sys.path.insert(0, "/home/q/projects/crabcakes")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
# Read markup from argv[1] (saved as base64 to avoid shell quoting issues)
import base64
markup = base64.b64decode(sys.argv[1]).decode("utf-8")
print("Markup being tested:", repr(markup[:100]))
try:
    label.set_markup(markup)
    print("OK - markup accepted, no warnings")
except Exception as e:
    print(f"FAIL: {e}")
''')

import base64
b64 = base64.b64encode(formatted.encode('utf-8')).decode('ascii')
proc = subprocess.run(['python3', '/tmp/test_label2.py', b64],
                      capture_output=True, text=True,
                      env={**os.environ, 'LANG': 'C'}, timeout=15)
print('---')
print('stdout:', proc.stdout)
print('stderr:', proc.stderr[:1500])