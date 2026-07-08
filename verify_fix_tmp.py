"""Verify the spec's proposed fix works for all test cases mentioned in §4 + §5."""
import re
from utils.escaping import escape_for_pango

# Simulate the spec's proposed implementation
import urllib.parse

def _validate_link_url(url):
    """Mock — always returns True for valid URLs."""
    return True

_WARNING_PREFIX = ''

def format_markdown_fixed(text):
    """Mock of format_markdown with the spec's Step 3a applied."""
    # Step 3a: angle-bracket auto-links
    anchor_spans = []
    
    def _angle_link_replace(m):
        url = m.group(1)
        anchor_html = f'<a href="{url}"><u>{url}</u></a>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
    
    angle_link_re = re.compile(
        r'&lt;((?:https?|ftp|mailto)://(?:[^\s&]|&(?:amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)+)&gt;'
    )
    text = angle_link_re.sub(_angle_link_replace, text)
    
    # Step 6: restore anchors (simplified — no other markdown processing)
    for i, anchor in enumerate(anchor_spans):
        text = text.replace(f'\x00ANCHOR{i}\x00', anchor)
    
    return text


# Test cases from §4 Acceptance Criteria
test_cases = [
    # (input, expected substrings)
    ('see <https://example.com>', ['href="https://example.com"', '<u>https://example.com</u>']),
    ('<https://example.com>', ['href="https://example.com"']),
    ('go to <https://example.com>.', ['href="https://example.com"', '<u>https://example.com</u>']),
    ('check https://example.com for info', []),  # plain URL — should be unchanged (Step 4 not implemented in mock)
    ('[label](https://example.com)', []),  # markdown link — should be unchanged (Step 3 not implemented in mock)
    ('see <https://example.com> out', ['<u>https://example.com</u>']),
    ('see <https://test.com?a=1&b=2>', ['href="https://test.com?a=1&amp;b=2"', '<u>https://test.com?a=1&amp;b=2</u>']),
]

print('=== Verifying spec\'s proposed fix ===\n')
all_pass = True
for input_text, expected in test_cases:
    escaped = escape_for_pango(input_text)
    output = format_markdown_fixed(escaped)
    
    missing = [e for e in expected if e not in output]
    status = 'PASS' if not missing else 'FAIL'
    if missing:
        all_pass = False
    print(f'[{status}] input: {input_text!r}')
    print(f'  escaped: {escaped!r}')
    print(f'  output: {output!r}')
    if missing:
        print(f'  MISSING: {missing}')
    print()

# Now test with GTK for the key case
import subprocess, os
print('=== GTK validation ===\n')
key_cases = ['see <https://example.com>', 'see <https://test.com?a=1&b=2>', '<https://example.com>']
for case in key_cases:
    escaped = escape_for_pango(case)
    output = format_markdown_fixed(escaped)
    result = subprocess.run(['python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
label.set_markup({output!r})
print("OK")
'''], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
    warn = 'Failed to set text' in result.stderr
    print(f'[{"PASS" if not warn else "FAIL"}] {case!r}  -> GTK warning: {warn}')

print()
print('OVERALL:', 'ALL PASS' if all_pass else 'SOME FAILED')