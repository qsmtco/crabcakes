# tests/test_escaping.py
# Tests for utils/escaping.py — Pango/XML escape utilities.

import pytest
from utils.escaping import escape_for_pango, xml_escape_text


class TestXmlEscapeText:
    """Simple XML escaping for plain text (no Pango markup)."""

    def test_plain_text_unchanged(self):
        assert xml_escape_text("Hello world") == "Hello world"

    def test_ampersand_escaped(self):
        assert xml_escape_text("Tom & Jerry") == "Tom & Jerry"
        assert xml_escape_text("A & B & C") == "A & B & C"

    def test_angle_brackets_escaped(self):
        assert xml_escape_text("<script>") == "<script>"
        assert xml_escape_text("a < b") == "a < b"
        assert xml_escape_text("a > b") == "a > b"

    def test_double_quotes_escaped(self):
        assert xml_escape_text('say "hi"') == 'say "hi"'

    def test_single_quote_apostrophe(self):
        assert xml_escape_text("it's") == "it's"

    def test_mixed(self):
        assert xml_escape_text('Tom & Jerry <script> "hi"') == (
            'Tom & Jerry <script> "hi"'
        )

    def test_empty_string(self):
        assert xml_escape_text("") == ""


class TestEscapeForPango:
    """Pango-aware escaping — preserves valid tags, escapes malformed ones."""

    # Plain text
    def test_plain_text_unchanged(self):
        assert escape_for_pango("Hello world") == "Hello world"

    def test_plain_text_ampersand_escaped(self):
        assert escape_for_pango("Tom & Jerry") == "Tom & Jerry"

    def test_plain_text_with_literal_brackets_escaped(self):
        assert escape_for_pango("a < b") == "a < b"
        assert escape_for_pango("a > b") == "a > b"

    def test_empty_string(self):
        assert escape_for_pango("") == ""

    # Valid Pango tags preserved
    def test_bold_tag_preserved(self):
        assert escape_for_pango("<b>bold text</b>") == "<b>bold text</b>"

    def test_italic_tag_preserved(self):
        assert escape_for_pango("<i>italic text</i>") == "<i>italic text</i>"

    def test_monospace_tag_preserved(self):
        assert escape_for_pango("<tt>code</tt>") == "<tt>code</tt>"

    def test_underline_tag_preserved(self):
        assert escape_for_pango("<u>underlined</u>") == "<u>underlined</u>"

    def test_strikethrough_tag_preserved(self):
        assert escape_for_pango("\u672cstrikethrough\u672c") == "\u672cstrikethrough\u672c"

    def test_span_tag_preserved(self):
        assert escape_for_pango('<span foreground="red">text</span>') == '<span foreground="red">text</span>'

    def test_anchor_tag_preserved(self):
        assert escape_for_pango('<a href="https://x.com">link</a>') == '<a href="https://x.com">link</a>'

    def test_nested_tags_preserved(self):
        assert escape_for_pango("<b><i>bold italic</i></b>") == "<b><i>bold italic</i></b>"

    def test_mixed_tags_with_ampersand_in_content(self):
        assert escape_for_pango("<b>Tom & Jerry</b>") == "<b>Tom & Jerry</b>"

    # Malformed tags escaped
    def test_unmatched_closing_tag_escaped(self):
        result = escape_for_pango("</b>")
        assert "</b>" in result

    def test_wrong_closing_tag_escaped(self):
        result = escape_for_pango("<b>text</i>")
        assert "</i>" in result or "</i>" not in result

    def test_double_closing_escaped(self):
        result = escape_for_pango("</b></b>")
        assert result.count("<") >= 2 or result.count("<") == 0

    def test_incomplete_open_tag_preserved(self):
        result = escape_for_pango("<b")
        assert result != "<b"

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
        assert "<" in result

    def test_multiple_ampersands(self):
        assert escape_for_pango("a & b & c") == "a & b & c"

    def test_trailing_lt_escaped(self):
        result = escape_for_pango("text <")
        assert result.endswith("<") or result.endswith("&lt")

    # Orphan tag sweep (NEW tests)
    def test_orphan_a_tag_escaped(self):
        result = escape_for_pango('renders <a href="..."> tags')
        assert '<a ' not in result
        assert '<a' in result or '<a href' in result

    def test_orphan_b_tag_escaped(self):
        result = escape_for_pango('<b>bold')
        assert '<b>' not in result
        assert '<b>' in result or '<b' in result

    def test_valid_tag_pair_preserved(self):
        assert escape_for_pango('<b>bold</b>') == '<b>bold</b>'

    def test_valid_a_tag_pair_preserved(self):
        result = escape_for_pango('<a href="https://x.com">link</a>')
        assert '<a href="https://x.com">link</a>' == result

    def test_nested_valid_tags_preserved(self):
        assert escape_for_pango('<b><i>nested</i></b>') == '<b><i>nested</i></b>'

    def test_grep_output_with_a_tag(self):
        result = escape_for_pango('# \u2190 renders <a href="..."> tags')
        assert '<a ' not in result
        assert '<a' in result or '<a href' in result

    def test_no_orphan_when_all_closed(self):
        result = escape_for_pango('<b>one</b> <i>two</i>')
        assert result == '<b>one</b> <i>two</i>'

    # Strict entity unescape
    def test_well_formed_amp(self):
        assert escape_for_pango("Tom & Jerry") == "Tom & Jerry"

    def test_well_formed_lt(self):
        assert escape_for_pango("a < b") == "a < b"

    def test_well_formed_gt(self):
        assert escape_for_pango("a > b") == "a > b"

    def test_malformed_gt_preserved(self):
        result = escape_for_pango("see &gt here")
        assert ">" not in result.replace(">", "").replace("&gt", "")

    def test_malformed_amp_preserved(self):
        result = escape_for_pango("see &amp here")
        assert "&amp" in result

    def test_buggy_autolink_output_robust(self):
        broken = '<<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
        result = escape_for_pango(broken)
        assert 'href="https://example.com>' not in result

    def test_numeric_decimal(self):
        assert escape_for_pango("&#42;") == "*"

    def test_numeric_hex(self):
        assert escape_for_pango("&#x2A;") == "*"

    def test_non_pango_entity_not_decoded(self):
        result = escape_for_pango("&copy; 2024")
        assert "\u00a9" not in result

    def test_double_encoded_no_double_decode(self):
        result = escape_for_pango("&")
        assert result == "&"

    def test_invalid_numeric_codepoint_preserved(self):
        result = escape_for_pango("&#999999999;")
        assert "999999999" in result