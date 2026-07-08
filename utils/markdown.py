# utils/markdown.py
# Inline markdown to Pango Markup converter.
#
# Ported from deadcode's formatters.py (Phase 1 of Chat Formatting Port).
# Security: No secrets, no file I/O, no network calls.
#
# Handles ONLY inline formatting — block-level (code blocks, blockquotes)
# are handled by block_parser.py in Phase 2.
#
# Conversion rules:
#   **bold**   -> <b>bold</b>
#   *italic*   -> <i>italic</i>
#   `code`     -> <tt>code</tt>
#   ~~strike~~ -> <s>strike</s>
#   [text](url)-> <a href="url"><u>text</u></a>
#   bare URL   -> clickable link (auto-detect)
#   - item     -> bullet conversion at line start
#
# IMPORTANT: Inline code spans are protected FIRST using null-byte
# placeholders so that _ and * inside code are not treated as
# formatting markers. The placeholders are restored after all
# other conversions are applied.
#
# Public API:
#   format_markdown(text) -> str   — converts markdown to Pango Markup

import html
import re
import urllib.parse


_CODE_PLACEHOLDER_RE = re.compile(r'\x00CODE(\d+)\x00')
_ANCHOR_PLACEHOLDER_RE = re.compile(r'\x00ANCHOR(\d+)\x00')

# Regex for auto-linking bare URLs
_AUTO_LINK_RE = re.compile(
    r'(?<![a-zA-Z0-9/:])'  # not preceded by alphanum or ://
    r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()]+)'
    r'|'
    r'(?<!["\'])'
    r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()]+))'
    , re.IGNORECASE
)

# Trailing punctuation chars to strip from auto-detected URLs
_TRAILING_PUNCT = frozenset('.,;:!?')

# HIGH-6: Schemes that are safe to render as clickable links without warning.
# All other schemes (file://, smb://, ftp://, ssh://, javascript:, data:,
# custom URI schemes) render with a red warning prefix but stay clickable.
# Per CptJAQx 2026-06-18 — preserves user agency.
_ALLOWED_LINK_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})

# HIGH-6: Warning prefix shown in front of non-allowlisted links.
# U+26A0 = WARNING SIGN, rendered in red bold.
_WARNING_PREFIX: str = '<span foreground="red" weight="bold">\u26a0</span> '


def _validate_link_url(url: str) -> bool:
    """Return True if `url`'s scheme is in _ALLOWED_LINK_SCHEMES (or is relative).

    HIGH-6: relative URLs (no scheme) are allowed without warning.
    """
    if not url:
        return False
    # Allow relative URLs (no scheme)
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', url):
        return True
    scheme = url.split(":", 1)[0].lower()
    return scheme in _ALLOWED_LINK_SCHEMES


def _strip_trailing_punct(url: str) -> str:
    """Strip common trailing punctuation from a URL."""
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    return url


def format_markdown(text: str) -> str:
    """
    Convert inline markdown to Pango Markup.

    IMPORTANT: This function receives ALREADY-ESCAPED text.
    The caller (chat_render_handler) must call escape_for_pango() FIRST,
    then pass the escaped result here. Output is Pango Markup ready for
    Gtk.Label.set_markup().

    Order of operations:
      1. Protect inline code spans (backtick-delimited, GFM multi-backtick)
      2. Apply markdown -> Pango conversions (bold, italic, strike)
      3. Convert markdown links [text](url) -> <a href="url"><u>text</u></a>
         THEN immediately replace those <a> tags with placeholders
      4. Auto-link bare URLs (now safe — <a> tags are placeholders)
      5. Restore inline code spans (with <tt> wrapper)
      6. Restore <a> anchor tags
      7. Return Pango Markup

    Args:
        text: Markdown-formatted text, already escaped by escape_for_pango().

    Returns:
        Pango Markup string ready for Gtk.Label.set_markup().
    """
    if not text:
        return ""

    # ── Step 0: Cap input length to prevent ReDoS on adversarial input ──────
    # MED-10: Cap at 100 KB. Truncate and append a truncation marker.
    _MAX_INPUT_LEN = 100 * 1024  # 100 KB
    if len(text) > _MAX_INPUT_LEN:
        text = text[:_MAX_INPUT_LEN] + "\n[... input truncated at 100 KB ...]"

    # ── Step 0a: Isolate adjacent bold boundaries ────────────────────────────
    # The pattern **** (closing ** immediately followed by opening **) causes
    # the bold+italic regex (Step 2) to match across what should be two separate
    # bold blocks. Insert ZWSP between adjacent ** pairs to prevent cross-boundary
    # matching. ZWSP is invisible in rendered output. Removed after all substitutions.
    # MED-10: Replace quadratic while-loop with single non-overlapping regex pass.
    _ZWSP = '\u200b'
    text = re.sub(r'\*\*(?=\*\*)', f'**{_ZWSP}', text)

    # ── Step 1: Protect inline code spans ────────────────────────────────────
    code_spans: list[str] = []

    def _is_fenced_block(content: str) -> bool:
        """True if content starts a fenced code block — don't protect it."""
        if content.startswith('```'):
            return True
        if content.startswith('> '):
            return True
        return False

    # GFM multi-backtick code spans: ``` ``nested`code`` ``` → content = "`nested`code`"
    BACKTICK_RUN = re.compile(r'^`+')

    def _parse_code_span(text: str) -> tuple[str, int] | None:
        """Parse GFM backtick code span from start of text.
        Returns (content, num_backticks) or None if not a code span."""
        m = BACKTICK_RUN.match(text)
        if not m:
            return None
        num = len(m.group(0))
        rest = text[num:]
        # Closing run: same length, preceded and followed by non-backtick (or boundary)
        pattern = re.compile(r'(?<=[^`])`{%d}(?=[^`]|$)' % num)
        m2 = pattern.search(rest)
        if m2:
            return rest[:m2.start()], num
        return None

    def _collect_code_spans(t: str) -> str:
        """Scan text left-to-right; collect code spans, return text with placeholders."""
        result_parts: list[str] = []
        i = 0
        while i < len(t):
            chunk = t[i:]
            # Blockquote prefix — skip one character
            if chunk.startswith('> '):
                result_parts.append(t[i])
                i += 1
                continue
            # Fenced code block opener ( ``` lang or just ``` ) — protect the whole block.
            # Check for 3+ backticks followed by (newline or non-backtick char = fenced block opener).
            # If followed by another backtick = could be inline multi-backtick span, let parser handle.
            if (chunk.startswith('```') or chunk.startswith('``') or chunk.startswith('`')) \
                    and len(chunk) >= 4 and chunk[3] not in ('`', "'"):
                # This looks like a fenced block opener (``` or ```` etc).
                # Find the matching closing fence.
                num = len(chunk) - len(chunk.lstrip('`'))
                rest = chunk[num:]
                fence_char = '`' * num
                close_pos = rest.find('\n' + fence_char)
                if close_pos >= 0:
                    # Found closing fence after a newline — consume entire fenced block
                    block_end = num + close_pos + 1 + num  # past closing fence
                    # Include the block as-is (will be restored verbatim)
                    result_parts.append(t[i:i + block_end])
                    i += block_end
                    continue
            parsed = _parse_code_span(chunk)
            if parsed is not None:
                content, num = parsed
                if _is_fenced_block(content):
                    result_parts.append(t[i])
                    i += 1
                else:
                    code_spans.append(content)
                    result_parts.append(f'\x00CODE{len(code_spans) - 1}\x00')
                    i += num + len(content) + num
            else:
                result_parts.append(t[i])
                i += 1
        return ''.join(result_parts)

    protected = _collect_code_spans(text)

    # ── Step 2: Bold, italic, strikethrough ──────────────────────────────────

    # Bold+italic: ***text*** -> <b><i>text</i></b> (MUST run before bold/italic)
    protected = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', protected)

    # Bold: **text** -> <b>text</b>
    protected = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', protected)

    # Italic: *text* -> <i>text</i>  (non-greedy, avoid ** and isolated *)
    protected = re.sub(
        r'(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)',
        r'<i>\1</i>',
        protected
    )

    # Strikethrough: ~~text~~ -> <s>text</s>
    protected = re.sub(r'~~(.+?)~~', r'<s>\1</s>', protected)

    # Inline bullets at line start: "- " -> bullet (also match at position 0)
    protected = re.sub(r'(?m)^-( )', r'•\1', protected)

    # ── Step 3: Markdown links -> <a> tags, then immediately protect those <a> tags
    anchor_spans: list[str] = []

    def _link_replace_and_protect(m):
        label = m.group(1)
        url = m.group(2)
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
        # Produce <a> tag, then immediately protect it with a placeholder
        anchor_html = f'<a href="{safe_url}"><u>{label}</u></a>'
        # HIGH-6: prepend red warning prefix for non-allowlisted schemes
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'

    protected = re.sub(r'\[([^\]]+)\]\(((?:[^()]|\([^()]*\))+)\)', _link_replace_and_protect, protected)

    # ── Step 3a: Convert angle-bracket auto-links to anchor placeholders ────
    # CommonMark/GFM auto-link syntax: <https://example.com>
    # After escape_for_pango(), this is &lt;https://example.com&gt;
    # If we let Step 4's auto-link regex run, it would capture &gt; as part
    # of the URL, and _strip_trailing_punct would then strip the trailing
    # semicolon from &gt;, producing the invalid entity &gt (Gtk warning).
    # We pre-process here: extract the URL between the escaped brackets,
    # build an <a> tag, and protect it with the same \x00ANCHOR{N}\x00
    # placeholder that Step 3 uses for markdown links — so Step 6 restores
    # both kinds together.
    def _angle_link_replace(m):
        url = m.group(1)
        # Decode entities for visible text (so user sees & not &amp;),
        # then re-escape for safe Pango display.
        import html as _html
        display_url = _html.escape(_html.unescape(url))
        anchor_html = f'<a href="{url}"><u>{display_url}</u></a>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'

    # Broaden scheme to match any [a-zA-Z][a-zA-Z0-9+.-]*:// (same as Step 4).
    # Add re.IGNORECASE to match Step 4's case behavior.
    # This prevents non-allowlisted/uppercase schemes from bypassing Step 3a
    # and falling through to Step 4 where _strip_trailing_punct breaks &gt;.
    angle_link_re = re.compile(
        r'&lt;([a-zA-Z][a-zA-Z0-9+.-]*://(?:[^\s&]|&(?:amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)+)&gt;',
        re.IGNORECASE
    )
    protected = angle_link_re.sub(_angle_link_replace, protected)

    # ── Step 4: Auto-link bare URLs ──────────────────────────────────────────
    def _auto_link(m):
        url = m.group(1)
        url = _strip_trailing_punct(url)
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
        anchor_html = f'<a href="{safe_url}"><u>{url}</u></a>'
        # HIGH-6: prepend red warning prefix for non-allowlisted schemes
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        return anchor_html

    protected = _AUTO_LINK_RE.sub(_auto_link, protected)

    # ── Step 5: Restore inline code spans ────────────────────────────────────
    def _restore_code(m):
        idx = int(m.group(1))
        if idx < len(code_spans):
            content = code_spans[idx]
            # If the span contains HTML entities (&#xNN; or &name; or &quot;
            # etc.), it's already been through escape_for_pango() — don't
            # re-escape. After escape_for_pango(), '&' only appears as part
            # of entities (never bare), so checking for '&' is sufficient.
            # Otherwise escape for protection against raw HTML like <div>.
            if '&' in content:
                return f'<tt>{content}</tt>'
            escaped = html.escape(content)
            return f'<tt>{escaped}</tt>'
        return m.group(0)

    protected = _CODE_PLACEHOLDER_RE.sub(_restore_code, protected)

    # ── Step 6: Restore <a> anchor tags ──────────────────────────────────────
    def _restore_anchor(m):
        idx = int(m.group(1))
        if idx < len(anchor_spans):
            return anchor_spans[idx]
        return m.group(0)

    protected = _ANCHOR_PLACEHOLDER_RE.sub(_restore_anchor, protected)

    # ── Step 7: Remove zero-width spaces (added in Step 0) ────────────────────
    protected = protected.replace(_ZWSP, '')

    return protected
