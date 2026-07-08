"""Simulate the proposed strict-unescape fix and verify it works on the audit-bug input."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')

import re
import html

# The proposed new code from the spec
_ENTITY_CODEPOINTS: dict[str, int] = {
    "amp": 0x26,
    "lt":  0x3C,
    "gt":  0x3E,
    "quot": 0x22,
    "apos": 0x27,
    "nbsp": 0xA0,
}

_ENTITY_UNESCAPE_RE = re.compile(
    r"&(" + "|".join(_ENTITY_CODEPOINTS.keys()) + r"|#[0-9]+|#x[0-9a-fA-F]+);"
)

def _safe_chr(cp):
    try:
        return chr(cp)
    except (ValueError, OverflowError):
        return None  # signal failure

def _strict_unescape(text):
    def replace(m):
        name_or_num = m.group(1)
        if name_or_num.startswith('#'):
            # Numeric reference
            if name_or_num[1] in 'xX':
                cp = int(name_or_num[2:], 16)
            else:
                cp = int(name_or_num[1:], 10)
            ch = _safe_chr(cp)
            if ch is None:
                return m.group(0)  # leave malformed
            return ch
        else:
            # Named entity
            return chr(_ENTITY_CODEPOINTS[name_or_num])
    return _ENTITY_UNESCAPE_RE.sub(replace, text)


# Now monkey-patch the escape_for_pango to use strict unescape
import utils.escaping as esc_mod

# Save the original
original_unescape_call_source = open('utils/escaping.py').read()

# Build a fixed version
def escape_for_pango_fixed(text):
    if not text:
        return ""
    text = _strict_unescape(text)  # WAS: html.unescape(text)

    result = []
    i = 0
    n = len(text)
    open_tags = []

    while i < n:
        ch = text[i]
        if ch != "<":
            start = i
            while i < n and text[i] != "<":
                i += 1
            plain = text[start:i]
            result.append(html.escape(plain))
            continue

        if i + 1 >= n:
            result.append("&lt;")
            i += 1
            continue

        next_ch = text[i + 1]
        if next_ch == "/":
            match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                if tag_name in esc_mod._PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
                    result.append(match.group(0))
                    open_tags.pop()
                else:
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                result.append("&lt;")
                i += 1
        elif next_ch.isalpha() or next_ch == "!" or next_ch == "?":
            match = re.match(r"<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                attrs = match.group(2)
                is_self_closing = attrs.strip().endswith("/")
                is_void = is_self_closing or tag_name in esc_mod._PANGO_VOID_TAGS
                if tag_name in esc_mod._PANGO_KNOWN_TAGS or is_void:
                    full_tag = match.group(0)
                    if attrs.strip():
                        def _esc(m):
                            return m.group(0).replace("&", "&amp;")
                        attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', _esc, attrs)
                        full_tag = f"<{tag_name}{attrs_escaped}>"
                    result.append(full_tag)
                    if not is_void:
                        open_tags.append(tag_name)
                else:
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                result.append("&lt;")
                i += 1
        else:
            result.append("&lt;")
            i += 1

    return "".join(result)


# ── Run verification ─────────────────────────────────────────────────────

# 1. The audit-bug input
print('=== Test 1: audit-bug input (the regression) ===')
audit_input = '&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
out = escape_for_pango_fixed(audit_input)
print(f'INPUT:  {audit_input!r}')
print(f'OUTPUT: {out!r}')

import subprocess, os
result = subprocess.run([
    'python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
label.set_markup({out!r})
print("OK")
'''
], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
warn = 'Failed to set text' in result.stderr
print(f'GTK warning: {warn}')
print(f'stderr: {result.stderr.strip()[:300]}')
print(f'stdout: {result.stdout.strip()}')
print()

# 2. Well-formed entities (regression check)
print('=== Test 2: well-formed entities (regression check) ===')
for inp in ['Tom &amp; Jerry', 'a &lt; b', 'a &gt; b', 'say &quot;hi&quot;', "it&apos;s"]:
    out = escape_for_pango_fixed(inp)
    print(f'  {inp!r:30} -> {out!r}')

print()

# 3. Malformed entities (NEW behavior — preserved as literal)
print('=== Test 3: malformed entities (preserved as literal) ===')
for inp in ['&amp', '&lt', '&gt', '&amp;amp;', '&amp Jerry']:
    out = escape_for_pango_fixed(inp)
    print(f'  {inp!r:30} -> {out!r}')

print()

# 4. Numeric refs
print('=== Test 4: numeric refs (regression check) ===')
for inp in ['&#42;', '&#x2A;', '&#x2a;']:
    out = escape_for_pango_fixed(inp)
    print(f'  {inp!r:30} -> {out!r}')

print()

# 5. Non-Pango entity
print('=== Test 5: non-Pango entity (preserved, not decoded) ===')
out = escape_for_pango_fixed('&copy; 2024')
print(f'  {"&copy; 2024"!r:30} -> {out!r}')

print()

# 6. Full pipeline: escape_for_pango → format_markdown
print('=== Test 6: full pipeline (the actual fix scenario) ===')
from utils.markdown import format_markdown
raw = 'see <https://example.com>'  # auto-link input
out = format_markdown(escape_for_pango_fixed(raw))
print(f'INPUT:  {raw!r}')
print(f'OUTPUT: {out!r}')
result = subprocess.run([
    'python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
label.set_markup({out!r})
print("OK")
'''
], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
warn = 'Failed to set text' in result.stderr
print(f'GTK warning: {warn}')
print(f'stderr: {result.stderr.strip()[:300]}')
print()

# 7. Verify no regression on existing test cases
print('=== Test 7: existing test cases from test_escaping.py ===')
test_cases = [
    ("plain text", "Hello world", "Hello world"),
    ("ampersand", "Tom & Jerry", "Tom &amp; Jerry"),
    ("angle brackets", "a < b", "a &lt; b"),
    ("bold tag", "<b>bold text</b>", "<b>bold text</b>"),
    ("link tag", '<a href="http://example.com"><u>link</u></a>',
     '<a href="http://example.com"><u>link</u></a>'),
    ("unmatched close", "</b>", "&lt;/b&gt;"),
    ("br tag", "line1<br/>line2", "line1<br/>line2"),
]
for desc, inp, expected in test_cases:
    out = escape_for_pango_fixed(inp)
    status = 'PASS' if out == expected else 'FAIL'
    print(f'  [{status}] {desc}: {inp!r:50} -> {out!r} (expected {expected!r})')