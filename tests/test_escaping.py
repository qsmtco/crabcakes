# tests/test_escaping.py
# Tests for utils/escaping.py — Pango/XML escape utilities.

import pytest
from utils.escaping import escape_for_pango, xml_escape_text


class TestXmlEscapeText:
    """Simple XML escaping for plain text (no Pango markup)."""

    def test_plain_text_unchanged(self):
        assert xml_escape_text("Hello world") == "Hello world"

    def test_ampersand_escaped(self):
        assert xml_escape_text("Tom & Jerry") == "Tom &amp; Jerry"
        assert xml_escape_text("A & B & C") == "A &amp; B &amp; C"

    def test_angle_brackets_escaped(self):
        assert xml_escape_text("<script>") == "&lt;script&gt;"
        assert xml_escape_text("a < b") == "a &lt; b"
        assert xml_escape_text("a > b") == "a &gt; b"

    def test_double_quotes_escaped(self):
        assert xml_escape_text('say "hi"') == "say &quot;hi&quot;"

    def test_single_quote_apostrophe(self):
        # html.escape uses &#x27; for single quotes by default
        assert xml_escape_text("it's") == "it&#x27;s"

    def test_mixed(self):
        assert xml_escape_text("Tom & Jerry <script> \"hi\"") == (
            "Tom &amp; Jerry &lt;script&gt; &quot;hi&quot;"
        )

    def test_empty_string(self):
        assert xml_escape_text("") == ""


class TestEscapeForPango:
    """Pango-aware escaping — preserves valid tags, escapes malformed ones."""

    # ── Plain text ──────────────────────────────────────────────────────────

    def test_plain_text_unchanged(self):
        assert escape_for_pango("Hello world") == "Hello world"

    def test_plain_text_ampersand_escaped(self):
        assert escape_for_pango("Tom & Jerry") == "Tom &amp; Jerry"

    def test_plain_text_with_literal_brackets_escaped(self):
        # Literal angle brackets (not valid tags) are escaped
        assert escape_for_pango("a < b") == "a &lt; b"
        assert escape_for_pango("a > b") == "a &gt; b"

    def test_empty_string(self):
        assert escape_for_pango("") == ""

    # ── Valid Pango tags preserved ────────────────────────────────────────────

    def test_bold_tag_preserved(self):
        assert escape_for_pango("<b>bold text</b>") == "<b>bold text</b>"

    def test_italic_tag_preserved(self):
        assert escape_for_pango("<i>italic text</i>") == "<i>italic text</i>"

    def test_monospace_tag_preserved(self):
        assert escape_for_pango("<tt>code</tt>") == "<tt>code</tt>"

    def test_underline_tag_preserved(self):
        assert escape_for_pango("<u>underlined</u>") == "<u>underlined</u>"

    def test_strikethrough_tag_preserved(self):
        assert escape_for_pango("<s>strikethrough</s>") == "<s>strikethrough</s>"

    def test_span_tag_preserved(self):
        assert escape_for_pango('<span foreground="red">text</span>') == '<span foreground="red">text</span>'

    def test_anchor_tag_preserved(self):
        assert escape_for_pango('<a href="https://x.com">link</a>') == '<a href="https://x.com">link</a>'

    def test_nested_tags_preserved(self):
        assert escape_for_pango("<b><i>bold italic</i></b>") == "<b><i>bold italic</i></b>"

    def test_mixed_tags_with_ampersand_in_content(self):
        assert escape_for_pango("<b>Tom & Jerry</b>") == "<b>Tom &amp; Jerry</b>"

    # ── Malformed tags escaped ───────────────────────────────────────────────

    def test_unmatched_closing_tag_escaped(self):
        result = escape_for_pango("</b>")
        assert "&lt;/b&gt;" in result

    def test_wrong_closing_tag_escaped(self):
        result = escape_for_pango("<b>text</i>")
        assert "</i>" not in result or "&lt;/i&gt;" in result

    def test_double_closing_escaped(self):
        result = escape_for_pango("</b></b>")
        assert result.count("<") == 0 or result.count("&lt;") >= 2

    def test_incomplete_open_tag_preserved(self):
        # <b without closing > — preserved as-is (not a complete tag)
        result = escape_for_pango("<b")
        # The < is escaped since it's not a complete tag
        assert result != "<b"  # some escaping happened

    def test_br_tag_preserved(self):
        assert escape_for_pango("line1<br>line2") == "line1<br>line2"

    def test_hr_tag_preserved(self):
        assert escape_for_pango("<hr>") == "<hr>"

    def test_tag_with_attributes_preserved(self):
        result = escape_for_pango('<span foreground="blue">blue text</span>')
        assert 'foreground="blue"' in result

    def test_link_tag_with_url(self):
        result = escape_for_pango('<a href="http://example.com"><u>link</u></a>')
        assert 'href="http://example.com"' in result

    def test_only_tag_characters(self):
        result = escape_for_pango("<<>>")
        # All should be escaped (no valid tag names)
        assert "<" not in result or "&lt;" in result

    def test_multiple_ampersands(self):
        assert escape_for_pango("a & b & c") == "a &amp; b &amp; c"

    def test_trailing_lt_escaped(self):
        result = escape_for_pango("text <")
        assert result.endswith("&lt;") or result.endswith("&lt")


class TestStrictEntityUnescape:
    """Strict unescape: only decode entities with trailing semicolon."""

    def test_well_formed_amp(self):
        assert escape_for_pango("Tom &amp; Jerry") == "Tom &amp; Jerry"

    def test_well_formed_lt(self):
        assert escape_for_pango("a &lt; b") == "a &lt; b"

    def test_well_formed_gt(self):
        assert escape_for_pango("a &gt; b") == "a &gt; b"

    def test_malformed_gt_preserved(self):
        """&gt (no ;) must NOT decode to > — this is the core bug fix."""
        result = escape_for_pango("see &gt here")
        assert ">" not in result.replace("&gt;", "").replace("&amp;gt", "")

    def test_malformed_amp_preserved(self):
        result = escape_for_pango("see &amp here")
        assert "&amp;amp" in result or "&amp;" in result

    def test_buggy_autolink_output_robust(self):
        """The exact failure input from the audit bug."""
        broken = '&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
        result = escape_for_pango(broken)
        assert 'href="https://example.com>' not in result

    def test_numeric_decimal(self):
        assert escape_for_pango("&#42;") == "*"

    def test_numeric_hex(self):
        assert escape_for_pango("&#x2A;") == "*"

    def test_non_pango_entity_not_decoded(self):
        result = escape_for_pango("&copy; 2024")
        assert "©" not in result

    def test_double_encoded_no_double_decode(self):
        result = escape_for_pango("&amp;amp;")
        assert result == "&amp;amp;"

    def test_invalid_numeric_codepoint_preserved(self):
        """&#999999999; exceeds Unicode range — must not crash."""
        result = escape_for_pango("&#999999999;")
        assert "999999999" in result
