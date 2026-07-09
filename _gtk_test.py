import sys, os, subprocess
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

raw = """$ python3 <<'PYEOF'
import sys
sys.path.insert(0, '.')
from utils.escaping import _strict_unescape
import re

# ADVERSARIAL: Regex matching edge cases

# 1. Greedy vs non-greedy: the regex has no quantifier, so it's exact match."""

escaped = escape_for_pango(raw)
formatted = format_markdown(escaped)
print('Formatted length:', len(formatted))
print('Formatted:', repr(formatted))
print()
print('Testing with Gtk...')

# Write the test script to a file
test_script = '''
import sys, os
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
formatted = "<<<MARKUP>>>"
label.set_markup(formatted)
print("OK - markup accepted")
'''
test_script = test_script.replace("<<<MARKUP>>>", formatted)
with open('/tmp/test_label.py', 'w') as f:
    f.write(test_script)

proc = subprocess.run(['python3', '/tmp/test_label.py'],
                      capture_output=True, text=True,
                      env={**os.environ, 'LANG': 'C'}, timeout=15)
print('stdout:', proc.stdout[:500])
print('stderr:', proc.stderr[:1500])