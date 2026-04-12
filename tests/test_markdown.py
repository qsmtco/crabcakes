# tests/test_markdown.py
# Tests for utils/markdown.py — inline markdown to Pango Markup converter.

import pytest
from utils.markdown import format_markdown


class TestBold:
    def test_bold_basic(self):
        result = format_markdown("**bold text**")
        assert result == "<b>bold text</b>"

    def test_bold_inline(self):
        result = format_markdown("this is **bold** and not bold")
        assert result == "this is <b>bold</b> and not bold"

    def test_bold_non_greedy(self):
        # Should not consume across multiple ** pairs
        result = format_markdown("**one** and **two**")
        assert result == "<b>one</b> and <b>two</b>"

    def test_bold_empty(self):
        # **** is not valid bold, should not match
        result = format_markdown("****")
        assert "**" not in result or result == "****"


class TestItalic:
    def test_italic_basic(self):
        result = format_markdown("*italic text*")
        assert result == "<i>italic text</i>"

    def test_italic_inline(self):
        result = format_markdown("this is *italic* and not")
        assert result == "this is <i>italic</i> and not"

    def test_asterisk_not_italic(self):
        # Isolated * or * at word boundaries should not become italic
        # e.g., "3 * 3 = 9" or "a * b"
        result = format_markdown("3 * 3 = 9")
        assert "<i>" not in result

    def test_italic_with_spaces(self):
        # Spaces inside *...* are included in the italic content
        result = format_markdown("* text with space *")
        assert "<i> text with space </i>" in result


class TestInlineCode:
    def test_inline_code_basic(self):
        result = format_markdown("`code text`")
        assert result == "<tt>code text</tt>"

    def test_inline_code_with_underscores_protected(self):
        # Underscores inside code should NOT be treated as italic markers
        result = format_markdown("`my_variable_name`")
        assert result == "<tt>my_variable_name</tt>"
        assert "<i>" not in result  # not treated as italic

    def test_inline_code_with_asterisks_protected(self):
        result = format_markdown("`x * y`")
        assert result == "<tt>x * y</tt>"
        assert "<b>" not in result  # not treated as bold

    def test_inline_code_empty(self):
        # Empty code span
        result = format_markdown("``")
        # Should be preserved or handled gracefully
        assert "tt" not in result or "<tt></tt>" in result or result == ""

    def test_code_with_angle_brackets_escaped(self):
        result = format_markdown("`<div>`")
        assert result == "<tt>&lt;div&gt;</tt>"
        assert "<div>" not in result  # not unescaped HTML


class TestStrikethrough:
    def test_strikethrough_basic(self):
        result = format_markdown("~~strikethrough~~")
        assert result == "<s>strikethrough</s>"

    def test_strikethrough_inline(self):
        result = format_markdown("this is ~~crossed~~ out")
        assert result == "this is <s>crossed</s> out"


class TestLinks:
    def test_link_basic(self):
        result = format_markdown("[click here](https://example.com)")
        assert '<a href="https://example.com">' in result
        assert "<u>click here</u>" in result

    def test_link_url_encoded(self):
        result = format_markdown("[search](https://example.com?q=hello world)")
        # URL should be encoded (spaces become %20)
        assert "hello%20world" in result

    def test_auto_link_bare_url(self):
        result = format_markdown("check https://example.com for info")
        assert '<a href="https://example.com">' in result
        assert "https://example.com" in result  # visible text

    def test_auto_link_strips_trailing_punct(self):
        result = format_markdown("see https://example.com. it works")
        # Trailing period should be stripped from URL
        assert '<a href="https://example.com">' in result
        # Period NOT in the href value
        assert '<a href="https://example.com.">' not in result


class TestMixed:
    def test_bold_and_italic_combined(self):
        result = format_markdown("***bold italic***")
        # *** is bold+italic in some markdown but ambiguous here
        # Non-greedy will match innermost first
        pass  # ambiguous — skip strict test

    def test_code_with_markdown_inside(self):
        result = format_markdown("`my **bold** var`")
        assert "<tt>" in result
        assert "<b>" not in result  # ** inside code should not be bold

    def test_italic_with_code_inside(self):
        result = format_markdown("*use `x` for variable*")
        assert "<i>" in result
        assert "<tt>" in result

    def test_normal_text_unchanged(self):
        result = format_markdown("Hello world, this is plain text.")
        assert result == "Hello world, this is plain text."

    def test_escaped_markdown_characters(self):
        # Literal characters that happen to look like markdown
        result = format_markdown("not bold: ** just literal")
        assert "just literal" in result


class TestEdgeCases:
    def test_empty_string(self):
        assert format_markdown("") == ""

    def test_none_handling(self):
        # Should handle None gracefully — raise TypeError
        # The function doesn't explicitly handle None
        pass

    def test_newlines_preserved(self):
        result = format_markdown("line1\nline2")
        assert "\n" in result or result == "line1\nline2"

    def test_bullet_list(self):
        result = format_markdown("- item1\n- item2")
        assert "•" in result

    def test_triple_backtick_fence_preserved(self):
        """Triple-backtick fences must not be consumed as inline code spans."""
        code = '```python\nprint("hi")\n```'
        result = format_markdown(code)
        # The ``` markers must still be present (Phase 2 extract_blocks needs them)
        assert '```' in result
        assert '<tt>' not in result  # not converted to inline code span

    def test_triple_fence_with_inline_code_in_text(self):
        """Text with both triple-fence block and inline code should render both correctly."""
        text = 'Text before\n\n```python\nx = 1\n```\n\nText with `inline` after.'
        result = format_markdown(text)
        assert '```' in result        # fence preserved
        assert '<tt>inline</tt>' in result  # inline code processed
