# utils/syntax_highlight.py
# Pygments → Pango Markup syntax highlighting — Phase 2 of Chat Formatting Port.
#
# Security: No secrets, no file I/O, no network calls.
# Pure Python, no GTK imports.
#
# Converts source code into Pango Markup with colored <span> tags.
# Pygments is an optional dependency — if not installed or no lexer found,
# the code is escaped as plain monospace text.
#
# Color scheme: dark theme (Tokyo Night-inspired).
# All colors are foreground only — background is set via CSS.
#
# Public API:
#   highlight(code, lang="") -> str
#       Returns Pango Markup string with syntax colors.

import html

# Try to import Pygments; if not available, highlighter degrades gracefully
try:
    from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
    from pygments.token import Token
    _PYGMENTS_AVAILABLE = True
except ImportError:
    _PYGMENTS_AVAILABLE = False


# Tokyo Night dark theme — foreground colors only (background via CSS)
_TOKEN_COLORS: dict = {
    # Keyword
    Token.Keyword:              '#c792ea',  # purple
    Token.Keyword.Constant:     '#f78c6c',  # orange
    Token.Keyword.Declaration:   '#c792ea',  # purple
    Token.Keyword.Namespace:     '#c792ea',  # purple
    Token.Keyword.Pseudo:       '#c792ea',  # purple
    Token.Keyword.Reserved:     '#c792ea',  # purple
    Token.Keyword.Type:         '#ffcb6b',  # yellow
    # Names
    Token.Name:                 '#82aaff',  # blue
    Token.Name.Class:            '#ffcb6b',  # yellow
    Token.Name.Exception:       '#ff5370',  # red
    Token.Name.Function:        '#82aaff',  # blue
    Token.Name.Decorator:       '#c792ea',  # purple
    Token.Name.Variable:         '#eeffff',  # white
    Token.Name.Builtin:          '#82aaff',  # blue
    Token.Name.Builtin.Pseudo:  '#82aaff',  # blue
    # Literals
    Token.Literal:              '#c3e88d',  # green
    Token.String:               '#c3e88d',  # green
    Token.String.Doc:           '#c3e88d',  # muted green
    Token.String.Affix:         '#c3e88d',  # green
    Token.String.Backtick:      '#c3e88d',  # green
    Token.String.Char:          '#c3e88d',  # green
    Token.String.Double:         '#c3e88d',  # green
    Token.String.Escape:        '#f78c6c',  # orange escape
    Token.String.Heredoc:        '#c3e88d',  # green
    Token.String.Interpol:       '#f78c6c',  # orange
    Token.String.Other:          '#c3e88d',  # green
    Token.String.Regex:         '#f78c6c',  # orange
    Token.String.Single:         '#c3e88d',  # green
    Token.String.Symbol:         '#c3e88d',  # green
    # Numbers
    Token.Number:               '#f78c6c',  # orange
    Token.Number.Bin:            '#f78c6c',  # orange
    Token.Number.Float:         '#f78c6c',  # orange
    Token.Number.Hex:            '#f78c6c',  # orange
    Token.Number.Integer:        '#f78c6c',  # orange
    Token.Number.Integer.Long:   '#f78c6c',  # orange
    Token.Number.Oct:            '#f78c6c',  # orange
    # Operators
    Token.Operator:             '#89ddff',  # cyan
    Token.Operator.Word:        '#c792ea',  # purple (e.g., and, or, not)
    # Punctuation
    Token.Punctuation:          '#89ddff',  # cyan
    # Comments
    Token.Comment:              '#676e95',  # muted
    Token.Comment.Multiline:     '#676e95',  # muted
    Token.Comment.Preproc:       '#ffcb6b',  # yellow
    Token.Comment.PreprocFile:  '#ffcb6b',  # yellow
    Token.Comment.Single:        '#676e95',  # muted
    Token.Comment.Special:       '#676e95',  # muted
    # Generic
    Token.Generic:              '#eeffff',  # white
    Token.Generic.Deleted:       '#ff5370',  # red
    Token.Generic.Emph:          '#eeffff',  # white/italic
    Token.Generic.Error:         '#ff5370',  # red
    Token.Generic.Heading:       '#82aaff',  # blue bold
    Token.Generic.Inserted:     '#c3e88d',  # green
    Token.Generic.Strong:        '#eeffff',  # white bold
    Token.Generic.Subheading:    '#82aaff',  # blue bold
    Token.Generic.Traceback:     '#ff5370',  # red
    # Other
    Token.Token:                '#eeffff',  # white
    Token.Text:                 '#eeffff',  # white
}

_DEFAULT_COLOR = '#eeffff'  # near-white fallback


def _token_color(ttype) -> str:
    """Walk the token type hierarchy upward to find a mapped color."""
    while ttype:
        if ttype in _TOKEN_COLORS:
            return _TOKEN_COLORS[ttype]
        ttype = ttype.parent
    return _DEFAULT_COLOR


def highlight(code: str, lang: str = "") -> str:
    """
    Convert source code to Pango Markup with syntax colors.

    Args:
        code: Source code string to highlight.
        lang: Language name (e.g., "python", "javascript", "bash").
              If empty and Pygments is available, tries to auto-detect.

    Returns:
        Pango Markup string. All special chars are HTML-escaped,
        token types are wrapped in <span foreground="..."> tags.
        If Pygments is not available or no lexer found, returns
        escaped monospace text: <tt>escaped_code</tt>.

    Examples:
        highlight("def foo(): pass", "python")
        # -> '<span foreground="#c792ea">def</span> <span foreground="#82aaff">foo</span>...'
    """
    if not code:
        return ""

    if not _PYGMENTS_AVAILABLE:
        escaped = html.escape(code)
        return f"<tt>{escaped}</tt>"

    # Get lexer for the language
    lexer = None
    lang_lower = lang.lower().strip()

    if lang_lower:
        try:
            lexer = get_lexer_by_name(lang_lower)
        except Exception:
            # Unknown language — fall through to plain escape
            escaped = html.escape(code)
            return f"<tt>{escaped}</tt>"

    if lexer is None:
        escaped = html.escape(code)
        return f"<tt>{escaped}</tt>"

    # Tokenize and emit colored spans
    result: list[str] = []
    for ttype, value in lexer.get_tokens(code):
        if not value:
            continue
        color = _token_color(ttype)
        escaped_val = html.escape(value)
        if color != _DEFAULT_COLOR:
            result.append(f'<span foreground="{color}">{escaped_val}</span>')
        else:
            result.append(escaped_val)

    return "".join(result)
