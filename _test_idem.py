"""Verify the idempotency test expectations."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')
import re
import html

_ENTITY_CODEPOINTS = {'amp': 0x26, 'lt': 0x3C, 'gt': 0x3E, 'quot': 0x22, 'apos': 0x27, 'nbsp': 0xA0}
_ENTITY_UNESCAPE_RE = re.compile(r'&(' + '|'.join(_ENTITY_CODEPOINTS.keys()) + r'|#[0-9]+|#x[0-9a-fA-F]+);')

def _strict_unescape(text):
    def replace(m):
        n = m.group(1)
        if n.startswith('#'):
            cp = int(n[2:], 16) if n[1] in 'xX' else int(n[1:], 10)
            try: return chr(cp)
            except: return m.group(0)
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


# Verify the idempotency test
for inp in ['&amp;amp;', '&amp;', '&amp;amp;amp;', '&amp;copy;']:
    out = escape_for_pango_fixed(inp)
    print(f'{inp!r:20} -> {out!r}')