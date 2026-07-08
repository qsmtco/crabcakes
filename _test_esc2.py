"""Debug escape_for_pango step by step."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')

import html
import re
from utils.escaping import _PANGO_KNOWN_TAGS, _PANGO_VOID_TAGS

# The input that escape_for_pango receives
text = 'see &lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
print(f'INPUT: {text!r}')
print()

# Step 1: html.unescape
text = html.unescape(text)
print(f'After html.unescape: {text!r}')
print()

# Manual loop
result = []
i = 0
n = len(text)
open_tags = []

while i < n:
    ch = text[i]
    if ch != '<':
        start = i
        while i < n and text[i] != '<':
            i += 1
        plain = text[start:i]
        result.append(html.escape(plain))
        continue

    if i + 1 >= n:
        result.append('&lt;')
        i += 1
        continue

    next_ch = text[i + 1]
    print(f'  pos {i}: char={ch!r}, next={next_ch!r}')

    if next_ch == '/':
        match = re.match(r'</([a-zA-Z][a-zA-Z0-9._-]*)\s*>', text[i:], re.ASCII)
        if match:
            tag_name = match.group(1).lower()
            print(f'    CLOSING tag: {tag_name!r}')
            if tag_name in _PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
                result.append(match.group(0))
                open_tags.pop()
                print(f'    -> preserved, stack now: {open_tags}')
            else:
                result.append(html.escape(match.group(0)))
                print(f'    -> escaped')
            i += match.end()
        else:
            result.append('&lt;')
            i += 1
    elif next_ch.isalpha() or next_ch == '!' or next_ch == '?':
        match = re.match(r'<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>', text[i:], re.ASCII)
        if match:
            tag_name = match.group(1).lower()
            attrs = match.group(2)
            print(f'    OPENING tag: name={tag_name!r}, attrs={attrs!r}')
            print(f'    match.group(0)={match.group(0)!r}')

            is_self_closing = attrs.strip().endswith('/')
            is_void = is_self_closing or tag_name in _PANGO_VOID_TAGS

            if tag_name in _PANGO_KNOWN_TAGS or is_void:
                full_tag = match.group(0)
                if attrs.strip():
                    def _escape_attr_ampersands(m):
                        return m.group(0).replace('&', '&amp;')
                    attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, attrs)
                    print(f'    attrs_escaped: {attrs_escaped!r}')
                    full_tag = f'<{tag_name}{attrs_escaped}>'
                    print(f'    full_tag: {full_tag!r}')
                result.append(full_tag)
                if not is_void:
                    open_tags.append(tag_name)
                    print(f'    -> preserved, stack now: {open_tags}')
            else:
                result.append(html.escape(match.group(0)))
                print(f'    -> escaped')
            i += match.end()
        else:
            result.append('&lt;')
            i += 1
    else:
        result.append('&lt;')
        i += 1

print()
print(f'FINAL: {"".join(result)!r}')