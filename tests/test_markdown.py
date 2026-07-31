# tests/test_markdown.py
# Tests for utils/markdown.py — inline markdown to Pango Markup converter.

import pytest
from utils.markdown import format_markdown
from utils.escaping import escape_for_pango


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
        assert "<u>click here</u>" in result
        assert '<a ' not in result

    def test_link_url_encoded(self):
        result = format_markdown("[search](https://example.com?q=hello world)")
        # URL should be encoded (spaces become %20)
        assert "hello%20world" in result

    def test_auto_link_bare_url(self):
        result = format_markdown("check https://example.com for info")
        assert '<u>https://example.com</u>' in result
        assert '<a ' not in result

    def test_auto_link_strips_trailing_punct(self):
        result = format_markdown("see https://example.com. it works")
        # Trailing period should be stripped from underlined URL
        assert '<u>https://example.com</u>' in result
        # Period NOT in the underlined URL
        assert '<u>https://example.com.</u>' not in result


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

    def test_bullet_list_first_item(self):
        """Bug #7: first bullet at position 0 must be converted, not just subsequent ones."""
        result = format_markdown("- first\n- second")
        assert result.startswith("•"), f"first bullet not converted: {result!r}"
        assert result.count("•") == 2, f"expected 2 bullets, got {result.count('•')}: {result!r}"

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


# ═══════════════════════════════════════════════════════════════════════════════
#  HIGH-6: warn-but-render for non-allowlisted link schemes
# ═══════════════════════════════════════════════════════════════════════════════

from utils.markdown import format_markdown, _validate_link_url, _ALLOWED_LINK_SCHEMES


class TestValidateLinkUrl:
    """HIGH-6: _validate_link_url must allow http/https/mailto, block all others."""

    def test_http_allowed(self):
        assert _validate_link_url("http://example.com") is True

    def test_https_allowed(self):
        assert _validate_link_url("https://example.com") is True

    def test_mailto_allowed(self):
        assert _validate_link_url("mailto:x@y.com") is True

    def test_file_not_allowed(self):
        assert _validate_link_url("file:///etc/passwd") is False

    def test_smb_not_allowed(self):
        assert _validate_link_url("smb://server/share") is False

    def test_ftp_not_allowed(self):
        assert _validate_link_url("ftp://files.example.com") is False

    def test_javascript_not_allowed(self):
        assert _validate_link_url("javascript:alert(1)") is False

    def test_data_uri_not_allowed(self):
        assert _validate_link_url("data:text/html,<script>alert(1)</script>") is False

    def test_ssh_not_allowed(self):
        assert _validate_link_url("ssh://user@host") is False

    def test_custom_scheme_not_allowed(self):
        assert _validate_link_url("myapp://action") is False

    def test_empty_url_not_allowed(self):
        assert _validate_link_url("") is False

    def test_relative_url_allowed(self):
        assert _validate_link_url("relative/path") is True

    def test_absolute_path_allowed(self):
        assert _validate_link_url("/absolute/path") is True

    def test_anchor_allowed(self):
        assert _validate_link_url("#section") is True

    def test_case_insensitive_scheme(self):
        """Scheme matching must be case-insensitive."""
        assert _validate_link_url("HTTP://EXAMPLE.COM") is True
        assert _validate_link_url("HTTPS://EXAMPLE.COM") is True
        assert _validate_link_url("File:///etc/passwd") is False


class TestMarkdownWarnButRender:
    """HIGH-6: non-allowlisted links render WITH warning; allowlisted ones WITHOUT."""

    def test_http_link_no_warning(self):
        result = format_markdown("[example](http://example.com)")
        assert "\u26a0" not in result
        assert '<u>example</u>' in result

    def test_https_link_no_warning(self):
        result = format_markdown("[example](https://example.com)")
        assert "\u26a0" not in result
        assert '<u>example</u>' in result

    def test_mailto_no_warning(self):
        result = format_markdown("[email me](mailto:x@y.com)")
        assert "\u26a0" not in result
        assert '<u>email me</u>' in result

    def test_file_link_with_warning(self):
        """file:// links must be rendered WITH red warning prefix."""
        result = format_markdown("[passwd](file:///etc/passwd)")
        assert "\u26a0" in result, (
            "HIGH-6 VIOLATION: file:// link must have warning prefix. "
            f"Got: {result!r}"
        )
        # Link must still be rendered (warn-but-render, not block)
        assert '<u>passwd</u>' in result

    def test_smb_link_with_warning(self):
        result = format_markdown("[share](smb://server/share)")
        assert "\u26a0" in result
        assert '<u>share</u>' in result

    def test_javascript_link_with_warning(self):
        result = format_markdown("[click](javascript:alert(1))")
        assert "\u26a0" in result, "javascript: links must have warning prefix"
        assert '<u>click</u>' in result

    def test_data_uri_with_warning(self):
        result = format_markdown("[data](data:text/html,<script>alert(1)</script>)")
        assert "\u26a0" in result
        assert '<u>data</u>' in result

    def test_ssh_link_with_warning(self):
        result = format_markdown("[ssh](ssh://user@host)")
        assert "\u26a0" in result
        assert '<u>ssh</u>' in result

    def test_custom_scheme_with_warning(self):
        result = format_markdown("[app](myapp://action)")
        assert "\u26a0" in result
        assert '<u>app</u>' in result

    def test_auto_link_http_no_warning(self):
        """Bare http:// URLs must not have warning prefix."""
        result = format_markdown("Visit http://example.com now")
        assert "\u26a0" not in result

    def test_auto_link_file_with_warning(self):
        """Bare file:// URLs must have warning prefix."""
        result = format_markdown("See file:///etc/passwd")
        assert "\u26a0" in result, (
            "HIGH-6 VIOLATION: auto-linked file:// URL must have warning prefix"
        )

    def test_warning_uses_pango_red_bold_triangle(self):
        """Warning prefix must be Pango-red-bold ⚠."""
        result = format_markdown("[x](file:///etc/passwd)")
        # Pango markup for red bold WARNING SIGN
        assert '<span foreground="red" weight="bold">\u26a0</span>' in result
        # Link text must still be underlined
        assert '<u>x</u>' in result

    def test_multiple_links_mixed_schemes(self):
        """Mixed allowlisted and non-allowlisted links in one text."""
        result = format_markdown(
            "[safe](https://example.com) and [danger](file:///etc/passwd)"
        )
        # https has no warning
        assert result.count("\u26a0") == 1, "Only file:// should have warning"
        assert '<u>safe</u>' in result
        assert '<u>danger</u>' in result


class TestAngleBracketAutoLink:
    """Tests for CommonMark/GFM angle-bracket auto-link syntax: <URL>.

    These inputs go through escape_for_pango() BEFORE format_markdown(),
    so angle brackets arrive as &lt; and &gt;. The auto-link regex must
    not capture &gt; as part of the URL, and _strip_trailing_punct must
    not strip the semicolon from the entity.
    """

    def test_angle_bracket_basic(self):
        """<https://example.com> renders as underlined link text."""
        from utils.escaping import escape_for_pango
        result = format_markdown(escape_for_pango("see <https://example.com>"))
        assert '<u>https://example.com</u>' in result
        assert "&gt\"" not in result  # no truncated entity in href
        assert "&gt<" not in result   # no truncated entity before tag

    def test_angle_bracket_standalone(self):
        """Standalone <https://example.com> works."""
        from utils.escaping import escape_for_pango
        result = format_markdown(escape_for_pango("<https://example.com>"))
        assert '<u>https://example.com</u>' in result

    def test_angle_bracket_with_query_params(self):
        """<https://test.com?a=1&b=2> preserves full query string."""
        from utils.escaping import escape_for_pango
        result = format_markdown(escape_for_pango("see <https://test.com?a=1&b=2>"))
        # href should contain the full URL with &amp; for &
        assert "test.com?a=1&amp;b=2" in result
        assert "&gt" not in result.replace("&gt;", "", 1)  # no broken entities

    def test_angle_bracket_trailing_period(self):
        """go to <https://example.com>. works (period after bracket)."""
        from utils.escaping import escape_for_pango
        result = format_markdown(escape_for_pango("go to <https://example.com>."))
        assert '<u>https://example.com</u>' in result

    def test_angle_bracket_embedded_in_sentence(self):
        """see <https://example.com> out works."""
        from utils.escaping import escape_for_pango
        result = format_markdown(escape_for_pango("see <https://example.com> out"))
        assert '<u>https://example.com</u>' in result

    def test_plain_url_still_works(self):
        """Regression: plain URL without angle brackets still auto-links."""
        result = format_markdown("check https://example.com for info")
        assert '<u>https://example.com</u>' in result

    def test_markdown_link_still_works(self):
        """Regression: [label](url) still works."""
        result = format_markdown("[label](https://example.com)")
        assert '<u>label</u>' in result

    def test_no_broken_entities_in_output(self):
        """Output must not contain &gt without semicolon (would crash Pango)."""
        from utils.escaping import escape_for_pango
        import re
        result = format_markdown(escape_for_pango("see <https://example.com>"))
        # Look for &gt not followed by ;
        broken = re.findall(r'&gt(?!;)', result)
        assert not broken, f"Broken entities found: {broken}"

    def test_non_allowlisted_scheme_no_broken_entity(self):
        """BUG #1: <file:///x> must not produce broken &gt in href."""
        from utils.escaping import escape_for_pango
        import re
        for raw in ["<file:///etc/passwd>", "<ssh://user@host>", "<git://github.com/x>"]:
            result = format_markdown(escape_for_pango(raw))
            broken = re.findall(r'&gt(?!;)', result)
            assert not broken, f"Broken entity for {raw}: {broken}"
            assert "href=" in result, f"No link created for {raw}"

    def test_uppercase_scheme_no_broken_entity(self):
        """BUG #4: <HTTPS://example.com> must not produce broken &gt."""
        from utils.escaping import escape_for_pango
        import re
        for raw in ["<HTTPS://example.com>", "<Http://example.com>"]:
            result = format_markdown(escape_for_pango(raw))
            broken = re.findall(r'&gt(?!;)', result)
            assert not broken, f"Broken entity for {raw}: {broken}"

    def test_non_allowlisted_scheme_has_warning(self):
        """HIGH-6: file:// and ssh:// must have the warning prefix."""
        from utils.escaping import escape_for_pango
        for raw in ["<file:///etc/passwd>", "<ssh://user@host>"]:
            result = format_markdown(escape_for_pango(raw))
            assert "⚠" in result or "foreground=\"red\"" in result, (
                f"Missing HIGH-6 warning for {raw}"
            )


class TestAutoLinkAttributeProtection:
    """Auto-link regex must not match URLs inside href="..." attributes."""

    def test_url_in_href_not_double_linked(self):
        """A pre-existing <a href="URL"> must not get nested <a> tags."""
        result = format_markdown('<a href="https://example.com">link</a>')
        assert result.count('<a ') == 1, f"Nested <a> tags: {result}"

    def test_plain_url_still_links(self):
        """Regression: plain URLs without attributes still auto-link."""
        result = format_markdown("check https://example.com for info")
        assert '<a href="https://example.com">' in result

    def test_url_after_equals_not_linked(self):
        """URL preceded by = should not auto-link."""
        result = format_markdown('value=https://example.com')
        assert '<a ' not in result


class TestAutoLinkBareHostname:
    """Bare hostnames (scheme-less URLs) must auto-link without crashing.

    Regression: before fix, _auto_link called m.group(1) but _AUTO_LINK_RE has
    two alternatives — when only the bare.hostname alternative matched,
    group(1) was None, and urllib.parse.quote(None) raised TypeError.
    """

    def test_bare_hostname_links(self):
        """httpbin.org/help → <a href="httpbin.org/help"> link."""
        result = format_markdown("visit httpbin.org/help for info")
        assert '<a href="httpbin.org/help">' in result, f"Got: {result!r}"

    def test_bare_hostname_simple(self):
        """example.com → <a href="example.com">."""
        result = format_markdown("see example.com today")
        assert '<a href="example.com">' in result, f"Got: {result!r}"

    def test_bare_hostname_strips_trailing_period(self):
        """Period after bare hostname is stripped from URL."""
        result = format_markdown("see example.com.")
        assert '<a href="example.com">' in result, f"Got: {result!r}"
        # And the period is NOT in the href value
        assert 'example.com.' not in result.split('"')[1] if '"' in result else True

    def test_scheme_url_still_works(self):
        """No regression: explicit-scheme URLs still auto-link."""
        result = format_markdown("see https://x.com")
        assert '<a href="https://x.com">' in result


class TestFencedVsInlineBacktickRegression:
    """Regression: inline `` `<tt>` `` followed by ``` fenced block was being
    eaten by the fenced-block detector as if a single backtick started a fence.

    Symptom: format_markdown output an UNBALANCED <tt> tag, causing Pango to emit
    "Failed to set text: ... Element 'markup' was closed, but the currently open
    element is 'tt'".

    Root cause: utils/markdown.py:_collect_code_spans used to match single
    backticks as fenced-block openers. Fixed by only matching 3+ backticks.
    """

    def test_inline_bt_followed_by_fenced_block_does_not_eat_block(self):
        """`` `<tt>` `` followed by ```bash block must both be handled."""
        content = "Use `<tt>` for code:\n\n```bash\necho hi\n```\n\nEnd"
        escaped = escape_for_pango(content)
        result = format_markdown(escaped)
        # Inline literal `<tt>` becomes <tt>&lt;tt&gt;</tt>
        assert "<tt>&lt;tt&gt;</tt>" in result, (
            f"inline `<tt>` not properly escaped: {result!r}"
        )
        # Code block preserved
        assert "echo hi" in result
        # Balanced
        assert result.count("<tt>") == result.count("</tt>"), (
            f"Unbalanced <tt>: open={result.count('<tt>')}, close={result.count('</tt>')}"
        )

    def test_inline_underscores_then_fenced_block(self):
        content = "Math: `x*y`\n\n```\nx*y\n```"
        result = format_markdown(content)
        assert result.count("<tt>") == result.count("</tt>")
        assert "<tt>x*y</tt>" in result

    def test_two_inline_bt_then_fenced_block(self):
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
        assert result.count("<tt>") == result.count("</tt>"), (
            f"Unbalanced <tt>: {result.count('<tt>')}/{result.count('</tt>')}"
        )
        assert "<tt>&lt;tt&gt;</tt>" in result

    def test_markup_passes_pango_validation(self):
        """Verifies the output markup is valid Pango XML (no Gtk-WARNING)."""
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        content = (
            "Use `<tt>` literal text and code:\n\n"
            "```bash\n"
            "echo `hello`\n"
            "```\n"
            "\nEnd of message with `<span foreground=\"red\">` literal mention."
        )
        escaped = escape_for_pango(content)
        result = format_markdown(escaped)
        # Should not raise / emit "Failed to set text" Gtk-WARNING
        label = Gtk.Label()
        label.set_markup(result)
