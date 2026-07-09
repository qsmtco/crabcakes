import sys, os, subprocess
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# This is the FULL chunk the user pasted. Reconstruct from their terminal output.
raw = """$ python3 <<'PYEOF'
import sys
sys.path.insert(0, '.')
from utils.escaping import _strict_unescape, _ENTITY_UNESCAPE_RE
import re

# ADVERSARIAL: Regex matching edge cases
text = "&amp;amp;"
result = _strict_unescape(text)
print(f"&amp;amp; -> {result!r}")

text = "&amp;amp&amp;"
result = _strict_unescape(text)
print(f"&amp;amp&amp; -> {result!r}")

text = "&amp; &amp;"
result = _strict_unescape(text)
print(f"&amp; &amp; -> {result!r}")
"""

escaped = escape_for_pango(raw)
formatted = format_markdown(escaped)
print('Formatted length:', len(formatted))
# Find any pre-formatted code block
if 'monospace' in formatted.lower():
    print('Contains <tt> tag (pre-formatted)')

import base64
b64 = base64.b64encode(formatted.encode('utf-8')).decode('ascii')
proc = subprocess.run(['python3', '/tmp/test_label2.py', b64],
                      capture_output=True, text=True,
                      env={**os.environ, 'LANG': 'C'}, timeout=15)
print('---')
print('stdout:', proc.stdout)
print('stderr:', proc.stderr[:1500])