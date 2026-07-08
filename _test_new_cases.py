"""Test the new test cases from spec §6 acceptance criteria."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')

import re
import html

_ENTITY_CODEPOINTS = {
    "amp": 0x26, "lt": 0x3C, "gt": 0x3E, "quot": 0x22, "apos": 0x27, "nbsp": 0xA0,
}
_ENTITY_UNESCAPE_RE = re.compile(
    r"&(" + "|".join(_ENTITY_CODEPOINTS.keys()) + r"|#[0-9]+|#x[0-9a-fA-F]+);"
)

def _safe_chr(cp):
    try: return chr(cp)
    except (ValueError, OverflowError): return None

def _strict_unescape(text):
    def replace(m):
        n = m.group(1)
        if n.startswith('#'):
            cp = int(n[2:], 16) if n[1] in 'xX' else int(n[1:], 10)
            ch = _safe_chr(cp)
            return ch if ch is not None else m.group(0)
        return chr(_ENTITY_CODEPOINTS[n])
    return _ENTITY_UNESCAPE_RE.sub(replace, text)


import utils.escaping as esc_mod

def escape_for_pango_fixed(text):
    if not text: return ""
    text = _strict_unescape(text)
    result = []
    i = 0
    n = len(text)
    open_tags = []
    while i < n:
        ch = text[i]
        if ch != "<":
            start = i
            while i < n and text[i] != "<": i += 1
            result.append(html.escape(text[start:i]))
            continue
        if i + 1 >= n:
            result.append("&lt;"); i += 1; continue
        next_ch = text[i + 1]
        if next_ch == "/":
            match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                if tag_name in esc_mod._PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
                    result.append(match.group(0)); open_tags.pop()
                else:
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                result.append("&lt;"); i += 1
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
                        attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', lambda m: m.group(0).replace('&', '&amp;'), attrs)
                        full_tag = f"<{tag_name}{attrs_escaped}>"
                    result.append(full_tag)
                    if not is_void: open_tags.append(tag_name)
                else:
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                result.append("&lt;"); i += 1
        else:
            result.append("&lt;"); i += 1
    return "".join(result)


# ── Spec §6 acceptance criteria ──────────────────────────────────────
print('=== Spec §6 acceptance criteria ===\n')

# [ ] escape_for_pango("Tom &amp; Jerry") → "Tom &amp; Jerry"
out = escape_for_pango_fixed("Tom &amp; Jerry")
print(f'1. {"Tom &amp; Jerry":25} -> {out!r}')
print(f'   PASS' if out == "Tom &amp; Jerry" else '   FAIL')

# [ ] escape_for_pango("&gt") (no ;) → result does NOT contain a literal >
out = escape_for_pango_fixed("&gt")
print(f'2. {"&gt":25} -> {out!r}')
print(f'   PASS' if ">" not in out else '   FAIL')

# [ ] escape_for_pango('&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>') produces a string that does NOT contain <a href="https://example.com>
out = escape_for_pango_fixed('&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>')
print(f'3. audit-bug input -> {out!r}')
print(f'   PASS' if '<a href="https://example.com>' not in out else '   FAIL')

# [ ] Gtk.Label.set_markup(escape_for_pango(...)) produces NO Gtk-WARNING
import subprocess, os
out = escape_for_pango_fixed('&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>')
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
print(f'4. Gtk warning: {("Failed to set text" in result.stderr)}')
print(f'   PASS' if "Failed to set text" not in result.stderr else '   FAIL')
print(f'   stdout: {result.stdout.strip()}')
print(f'   stderr: {result.stderr.strip()[:200]}')

# [ ] escape_for_pango("&copy; 2024") does NOT decode &copy; to ©
out = escape_for_pango_fixed("&copy; 2024")
print(f'5. {"&copy; 2024":25} -> {out!r}')
print(f'   PASS' if "©" not in out else '   FAIL')

# [ ] escape_for_pango("&#42;") → "*"
out = escape_for_pango_fixed("&#42;")
print(f'6. {"&#42;":25} -> {out!r}')
print(f'   PASS' if out == "*" else '   FAIL')

# [ ] escape_for_pango("&#x2A;") → "*"
out = escape_for_pango_fixed("&#x2A;")
print(f'7. {"&#x2A;":25} -> {out!r}')
print(f'   PASS' if out == "*" else '   FAIL')