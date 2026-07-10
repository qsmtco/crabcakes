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


# Entity references accepted by the strict unescape. Names match exactly
# what Pango's XML parser accepts plus the standard XML named entities
# for content (so LLM-emitted " etc. decodes correctly to the char).
_ENTITY_CODEPOINTS: dict[str, int] = {
    "amp": 0x26,    # &
    "lt":  0x3C,    # <
    "gt":  0x3E,    # >
    "quot": 0x22,   # "
    "apos": 0x27,   # '
    "nbsp": 0xA0,   # non-breaking space
}

# Strict entity reference pattern: must have a trailing semicolon.
# Matches named entities in _ENTITY_CODEPOINTS or numeric refs (decimal
# or hex). Does NOT match &name (no ;) — those are left as literal text.
_ENTITY_UNESCAPE_RE: re.Pattern[str] = re.compile(
    r"&("
    + "|".join(_ENTITY_CODEPOINTS.keys())
    + r"|#[0-9]+|#x[0-9a-fA-F]+);"
)


def _strict_unescape(text: str) -> str:
    """Decode entity references that have a trailing semicolon.

    Unlike html.unescape (which is HTML5-lenient and decodes &gt, &amp etc.
    even without the trailing ;), this function ONLY decodes well-formed
    entity references. Malformed entities are preserved as literal text
    and handled by the downstream html.escape / attribute-escape logic.
    """
    def _replace(m):
        name = m.group(1)
        if name.startswith("#"):
            try:
                if name.startswith("#x") or name.startswith("#X"):
                    return chr(int(name[2:], 16))
                return chr(int(name[1:]))
            except (ValueError, OverflowError):
                return m.group(0)  # invalid codepoint — preserve literal
        return chr(_ENTITY_CODEPOINTS[name])

    return _ENTITY_UNESCAPE_RE.sub(_replace, text)


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
        "Tom & Jerry"                      -> "Tom & Jerry"
        "<b>bold</b>"                      -> "<b>bold</b>"  (preserved)
        "<b>bold"                          -> "<b>bold"  (unclosed, preserved)
        "<b>Tom & Jerry</b>"               -> "<b>Tom & Jerry</b>"
        "<script>evil()</script>"          -> "<script>evil()</script>"
        "</b>"                              -> "</b>"    (malformed close)
    """
    if not text:
        return ""

    # Decode HTML entities that LLMs sometimes emit (", &, <, etc.)
    # before processing. Without this, html.escape() below would double-encode
    # them (e.g. " → ") and they'd appear as raw text in bubbles.
    text = _strict_unescape(text)

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
            result.append("<")
            i += 1
            continue

        next_ch = text[i + 1]

        if next_ch == "/":
            # Closing tag: </name>
            match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
            if match:
                tag_name = match.group(1).lower()
                if tag_name in _PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
                    # Correctly nested known tag — emit lowercased closing tag.
                    result.append(f"</{tag_name}>")
                    open_tags.pop()
                else:
                    # Unknown tag OR malformed close — escape it
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                # Malformed close pattern — escape the '<'
                result.append("<")
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
                    # Lowercase attribute NAMES (Pango is case-sensitive on attrs too).
                    # Preserve attribute VALUES exactly.
                    if attrs.strip():
                        # Lowercase attribute NAMES (Pango is case-sensitive on attrs too).
                        # Preserve attribute VALUES exactly.
                        def _lower_attr_names(m):
                            return m.group(1).lower() + m.group(2) + m.group(3)
                        lowered_attrs = re.sub(
                            r'(\s+[a-zA-Z][a-zA-Z0-9_.-]*)(=)("[^"]*"|\'[^\']*\'|[^\s>]*)',
                            _lower_attr_names,
                            attrs,
                        )
                        # Escape bare ampersands in attribute values
                        def _escape_attr_ampersands(m):
                            amp = m.group(0)
                            return amp.replace("&", "&")
                        attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, lowered_attrs)
                        full_tag = f"<{tag_name}{attrs_escaped}>"
                    else:
                        full_tag = f"<{tag_name}>"
                    result.append(full_tag)
                    if not is_void:
                        open_tags.append(tag_name)
                else:
                    # Unknown tag — escape it entirely
                    result.append(html.escape(match.group(0)))
                i += match.end()
            else:
                # Malformed open — escape '<'
                result.append("<")
                i += 1
        else:
            # '<#' or '<-' etc. — treat as literal
            result.append("<")
            i += 1

    # ── Orphan tag sweep ───────────────────────────────────────────────────
    # After the main loop, any tags still on the open_tags stack were opened
    # but never closed. These are orphan tags — plain text that looked like a
    # Pango tag (e.g. grep output containing <a href="...">). Pango would
    # reject an unclosed opening tag, so we escape orphan tags back to literal
    # text.
    output = "".join(result)
    for tag_name in reversed(open_tags):
        tag_pattern = re.compile(
            r'<' + re.escape(tag_name) + r'(?:\s[^>]*)?>',
            re.IGNORECASE
        )
        matches = list(tag_pattern.finditer(output))
        if matches:
            last_match = matches[-1]
            original = last_match.group(0)
            escaped = html.escape(original)
            output = output[:last_match.start()] + escaped + output[last_match.end():]

    return output


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
        "Tom & Jerry" -> "Tom & Jerry"
        "<script>"    -> "<script>"
        'say "hi"'    -> "say "hi""
    """
    return html.escape(text, quote=True)


def xml_template(template: str, **kwargs: str) -> str:
    """
    Substitute keyword arguments into a hardcoded Pango template, applying
    xml_escape_text() to each value. Use for any set_markup() call that
    interpolates dynamic values into a template containing literal Pango tags.

    This prevents presentation injection: escape_for_pango() preserves known
    Pango tags (<b>, <i>, etc.), so a file_path of "<b>fake</b>" would render
    as bold inside "<b>{escape_for_pango(file_path)}</b>". xml_template uses
    xml_escape_text() instead, which escapes all markup.

    Example:
        label.set_markup(xml_template(
            "<b>Task {action}:</b> {task_id}",
            action=action,
            task_id=task_id,
        ))

    Args:
        template: A format string containing literal Pango tags and {key}
            placeholders. The literal tags are preserved; only the kwarg
            values are escaped.
        **kwargs: Values to substitute. Each is passed through
            xml_escape_text() before formatting.

    Returns:
        A Pango markup string safe for set_markup().
    """
    escaped = {k: xml_escape_text(v) for k, v in kwargs.items()}
    return template.format(**escaped)