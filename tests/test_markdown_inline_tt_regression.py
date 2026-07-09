"""Regression tests for bug:
format_markdown misidentifies inline code spans (`` `<tt>` ``) as fenced code blocks
when followed by a triple-backtick block on the same input.

Symptoms:
- Inline `` `<tt>` `` should become `<tt>&lt;tt&gt;</tt>`.
- Before fix: format_markdown opens a `<tt>` tag (treating `` `` `` as a fence opener)
  and never closes it; Pango then emits "Failed to set text: ... Element "markup" was
  closed, but the currently open element is "tt"".

These tests pin the fix in utils/markdown.py:_collect_code_spans where the
fenced-block detection regex used to match single-backtick spans.
"""

import pytest
from utils.markdown import format_markdown
from utils.escaping import escape_for_pango


class TestFencedVsInlineBacktickRegression:
    """Inline-code-spans containing Pango tag names must not be mistaken for fenced blocks."""

    def test_inline_bt_followed_by_fenced_block_does_not_eat_block(self):
        """Inline `` `<tt>` `` followed by ```bash code block must both be handled correctly."""
        content = "Use `<tt>` for code:\n\n```bash\necho hi\n```\n\nEnd"
        escaped = escape_for_pango(content)
        result = format_markdown(escaped)

        # Inline <tt> literal becomes <tt>&lt;tt&gt;</tt>
        assert "<tt>&lt;tt&gt;</tt>" in result, f"inline `<tt>` was not properly escaped: {result!r}"
        # Code block preserved
        assert "echo hi" in result
        # No unbalanced <tt> tags
        assert result.count("<tt>") == result.count("</tt>"), (
            f"Unbalanced <tt> tags: {result.count('<tt>')} open, {result.count('</tt>')} close"
        )

    def test_inline_underscores_then_fenced_block(self):
        """`` `*` `` followed by fenced block — inline content must be wrapped, not eaten."""
        content = "Math: `x*y`\n\n```\nx*y\n```"
        result = format_markdown(content)
        assert result.count("<tt>") == result.count("</tt>")
        # Math content should be in inline code, not fenced block
        assert "<tt>x*y</tt>" in result

    def test_two_inline_bt_then_fenced_block(self):
        """Multiple inline backticks, then a fenced block — none should be eaten."""
        content = "Use `<b>` and `<tt>` then:\n\n```\nraw code\n```"
        result = format_markdown(content)
        assert result.count("<tt>") == result.count("</tt>"), (
            f"Got: open={result.count('<tt>')}, close={result.count('</tt>')}"
        )

    def test_exact_user_failure_content_renders(self):
        """The exact message that triggered Gtk-WARNING on the user's machine."""
        content = (
            "Specifically, `&quot;` is being preserved by strict unescape "
            "(it's in the allowlist and has a semicolon, so it decodes to `\"`, "
            "but then the code block formatting wraps it in `<tt>` tags and the `\"` "
            "characters inside code blocks interact badly with the attribute escaping).\n\n"
            "Run this:\n\n```bash\nrm ~/.config/file\n```\n\nEnd"
        )
        escaped = escape_for_pango(content)
        result = format_markdown(escaped)
        # Balanced tags
        assert result.count("<tt>") == result.count("</tt>"), (
            f"Unbalanced <tt>: {result.count('<tt>')}/{result.count('</tt>')}"
        )
        # Inline backticks around `<tt>` produce <tt>&lt;tt&gt;</tt>
        assert "<tt>&lt;tt&gt;</tt>" in result

    def test_marksup_is_balanced_pass_pango_validation(self):
        """Verifies the output markup has balanced tags for Pango XML parser."""
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        content = "Run `` `<tt>` `` literal markup here:\n\n```bash\necho hi\n```\n\nEnd"
        escaped = escape_for_pango(content)
        result = format_markdown(escaped)
        label = Gtk.Label()
        # Will raise / emit Gtk-WARNING if markup is unbalanced
        label.set_markup(result)  # should NOT produce "Failed to set text"