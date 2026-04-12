# utils/escaping.py
# Pango/XML escape utilities — pure Python, no GTK imports.
#
# Ported from deadcode's formatters.py (Phase 1 of Chat Formatting Port).
# Security: No secrets, no file I/O, no network calls.
#
# Public API:
#   escape_for_pango(text) -> str    — escape XML specials, preserve known Pango tags
#   xml_escape_text(text) -> str     — simple & < > " escaping for plain text

import re
import html


# Pango markup tags known to Gtk.Label.set_markup().
# Only these tags are preserved; everything else is escaped.
# Ref: https://docs.gtk.org/Pango/pango_markup.html
_PANGO_KNOWN_TAGS: frozenset[str] = frozenset({
    # Text style tags
    "b", "i", "u", "s", "tt", "big", "small",
    # Span tag (generic container with attributes)
    "span",
    # Anchor tag
    "a",
    # Line breaks and separators
    "br", "hr", "wabr",
    # Sub/superscript
    "sub", "sup",
    # Overline
    "o",
})

# Void elements — HTML elements with no closing tag.
# These never push to the open-tags stack.
_PANGO_VOID_TAGS: frozenset[str] = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "param", "source", "track", "wbr",
})


def escape_for_pango(text: str) -> str:
    """
    Escape XML specials in text while preserving known Pango markup tags.

    Pango only understands a specific set of tags. Unknown tags (e.g., <script>,
    <div>) cause Gtk.Label.set_markup() to render the ENTIRE content as empty.
    To prevent this data loss, we maintain an explicit whitelist of known
    Pango tags and escape everything else.

    Tags like <b>, </b>, <i>, </i> are preserved intact.
    Malformed closing tags (e.g., </b> with no matching open) are escaped.
    Unknown tags (e.g., <script>, <div>) are escaped.

    Stack-based approach: tracks open tags so we can detect malformed closes.
    When a closing tag doesn't match what's on top of the stack, it's escaped
    as plain text.

    Args:
        text: Input string that may contain Pango markup

    Returns:
        Escaped string safe for use in Gtk.Label.set_markup()

    Examples:
        "Tom & Jerry"                      -> "Tom &amp; Jerry"
        "<b>bold</b>"                      -> "<b>bold</b>"  (preserved)
        "<b>bold"                          -> "<b>bold"  (unclosed, preserved)
        "<b>Tom & Jerry</b>"               -> "<b>Tom &amp; Jerry</b>"
        "<script>evil()</script>"          -> "&lt;script&gt;evil()&lt;/script&gt;"
        "</b>"                              -> "&lt;/b&gt;"    (malformed close)
    """
    if not text:
        return ""

    result: list[str] = []
    i = 0
    n = len(text)
    open_tags: list[str] = []

    while i < n:
        ch = text[i]

        if ch != "<":
            # Regular character — collect runs of plain text and escape them
            start = i
            while i < n and text[i] != "<":
                i += 1
            plain = text[start:i]
            result.append(html.escape(plain))
            continue

        # Found '<'. Determine if it's a Pango tag or a literal '<'.
        if i + 1 >= n:
            # Trailing '<' — escape as literal
            result.append("&lt;")
            i += 1
            continue

        next_ch = text[i + 1]

        if next_ch == "/":
            # Closing tag: </name>
            match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                if tag_name in _PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
                    # Correctly nested known tag — preserve the closing tag
                    result.append(match.group(0))
                    open_tags.pop()
                else:
                    # Unknown tag OR malformed close — escape it
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                # Malformed close pattern — escape the '<'
                result.append("&lt;")
                i += 1
        elif next_ch.isalpha() or next_ch == "!" or next_ch == "?":
            # Opening tag: <name ...> or <name>
            match = re.match(r"<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                attrs = match.group(2)
                # Self-closing tags (e.g., <br/>) are void
                is_self_closing = attrs.strip().endswith("/")
                is_void = is_self_closing or tag_name in _PANGO_VOID_TAGS

                if tag_name in _PANGO_KNOWN_TAGS or is_void:
                    # Known Pango tag OR void tag — preserve and track on stack.
                    # Also escape bare & in attribute values (e.g. URLs like
                    # href="http://example.com?a=1&b=2") to prevent XML parse
                    # errors in Gtk.Label.set_markup(). Only escape & not already
                    # part of an entity by checking for ; following &.
                    full_tag = match.group(0)
                    if attrs.strip():
                        # Escape bare ampersands in attributes only
                        def _escape_attr_ampersands(m):
                            amp = m.group(0)
                            return amp.replace("&", "&amp;")
                        # Only & not followed by valid entity (letter/digit/# then ;)
                        attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, attrs)
                        full_tag = f"<{tag_name}{attrs_escaped}>"
                    result.append(full_tag)
                    if not is_void:
                        open_tags.append(tag_name)
                else:
                    # Unknown tag — escape it entirely
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                # Malformed open — escape '<'
                result.append("&lt;")
                i += 1
        else:
            # '<#' or '<-' etc. — treat as literal
            result.append("&lt;")
            i += 1

    return "".join(result)


def xml_escape_text(text: str) -> str:
    """
    Simple XML/HTML escaping for plain text (no Pango markup).

    Escapes: & < > "

    Use this for content that is definitely plain text and should not
    contain any Pango markup tags.

    Args:
        text: Plain text to escape

    Returns:
        Escaped string safe for XML/Pango attribute or text content.

    Examples:
        "Tom & Jerry" -> "Tom &amp; Jerry"
        "<script>"    -> "&lt;script&gt;"
        'say "hi"'    -> "say &quot;hi&quot;"
    """
    return html.escape(text, quote=True)
