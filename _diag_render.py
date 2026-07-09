import sys, os, subprocess, base64
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# This is the EXACT text from the user's terminal output snippet
raw = """$ python3 <<'PYEOF'
import sys
sys.path.insert(0, '.')
from utils.escaping import _strict_unescape, _ENTITY_UNESCAPE_RE
import re

# ADVERSARIAL: Regex matching edge cases

# 1. Greedy vs non-greedy: the regex has no quantifier, so it's exact match.
# &amp;amp; — does the regex match &amp; first, or try &amp;amp; as a whole?
# The alternation is amp|lt|gt|quot|apos|nbsp|#[0-9]+|#x[0-9a-fA-F]+
# None of these match &quot;amp&quot;. So the regex tries the leftmost match.
# At position 0, the regex tries &amp; (since amp is in the alternation).
# &amp; matches the first 5 chars (&amp; + amp + ;). Match found.
#
# After the match, the regex continues from position 5: &quot;amp;&quot;
# At position 5, the regex tries to match &amp;name; — but the text is &quot;amp;&quot; (no &amp;).
# So no more matches.
#
# Result: &amp; → &amp; (decoded), amp; → amp; (preserved)
# Output: &quot;&amp;&quot; — correct.

text = &quot;&amp;amp;&quot;
result = _strict_unescape(text)
print(f&quot;&amp;amp; → {result!r}&quot;)
"""

escaped = escape_for_pango(raw)
formatted = format_markdown(escaped)
print('Formatted (first 500):', repr(formatted[:500]))
print('Formatted (last 200):', repr(formatted[-200:]))
print('Total length:', len(formatted))
print()

# Test with GTK
test_script = '''
import sys, os, gi, base64
sys.path.insert(0, "/home/q/projects/crabcakes")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import sys as _sys
markup = base64.b64decode(_sys.argv[1]).decode("utf-8")
label = Gtk.Label()
try:
    label.set_markup(markup)
    print("OK - markup accepted, no warnings")
except Exception as e:
    print(f"FAIL: {e}")
'''
with open('/tmp/test_label3.py', 'w') as f:
    f.write(test_script)

b64 = base64.b64encode(formatted.encode('utf-8')).decode('ascii')
proc = subprocess.run(['python3', '/tmp/test_label3.py', b64],
                      capture_output=True, text=True,
                      env={**os.environ, 'LANG': 'C'}, timeout=15)
print('stdout:', proc.stdout[:500])
print('stderr:', proc.stderr[:1500])