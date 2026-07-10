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
        assert xml_escape_text("it's") == "it&#x27;s"

    def test_mixed(self):
        assert xml_escape_text('Tom & Jerry <script> "hi"') == (
            "Tom &amp; Jerry &lt;script&gt; &quot;hi&quot;"
        )

    def test_empty_string(self):
        assert xml_escape_text("") == ""


class TestEscapeForPango:
    """Pango-aware escaping — preserves valid tags, escapes malformed ones."""

    # Plain text
    def test_plain_text_unchanged(self):
        assert escape_for_pango("Hello world") == "Hello world"

    def test_plain_text_ampersand_escaped(self):
        assert escape_for_pango("Tom & Jerry") == "Tom &amp; Jerry"

    def test_plain_text_with_literal_brackets_escaped(self):
        assert escape_for_pango("a < b") == "a &lt; b"
        assert escape_for_pango("a > b") == "a &gt; b"

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
        assert escape_for_pango("<b>Tom & Jerry</b>") == "<b>Tom &amp; Jerry</b>"

    # Malformed tags escaped
    def test_unmatched_closing_tag_escaped(self):
        result = escape_for_pango("</b>")
        assert "&lt;/b&gt;" in result

    def test_wrong_closing_tag_escaped(self):
        result = escape_for_pango("<b>text</i>")
        assert "&lt;/i&gt;" in result

    def test_double_closing_escaped(self):
        result = escape_for_pango("</b></b>")
        assert result == "&lt;/b&gt;&lt;/b&gt;"

    def test_incomplete_open_tag_preserved(self):
        result = escape_for_pango("<b")
        assert result == "&lt;b"

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
        # <<>> - trailing > becomes &gt;, trailing < is kept as literal
        assert "&gt;" in result

    def test_multiple_ampersands(self):
        assert escape_for_pango("a & b & c") == "a &amp; b &amp; c"

    def test_trailing_lt_escaped(self):
        result = escape_for_pango("text <")
        assert result.endswith("&lt;")

    # Strict entity unescape
    def test_well_formed_amp(self):
        assert escape_for_pango("Tom & Jerry") == "Tom &amp; Jerry"

    def test_well_formed_lt(self):
        assert escape_for_pango("a < b") == "a < b"

    def test_well_formed_gt(self):
        assert escape_for_pango("a > b") == "a &gt; b"

    def test_malformed_gt_preserved(self):
        result = escape_for_pango("see &gt here")
        # &gt; without semicolon - & is escaped to &amp;, gt is literal
        assert "amp;gt" in result

    def test_malformed_amp_preserved(self):
        result = escape_for_pango("see &amp here")
        # &amp; without semicolon - & is escaped, amp is literal
        assert "amp;" in result

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
        # &copy; is well-formed (has semicolon), but &copy is not in our entity allowlist
        # So the & is escaped to &amp; before entity decode, resulting in &amp;copy;
        assert "&amp;copy;" in result

    def test_double_encoded_no_double_decode(self):
        result = escape_for_pango("&")
        assert result == "&amp;"

    def test_invalid_numeric_codepoint_preserved(self):
        result = escape_for_pango("&#999999999;")
        assert "999999999" in result or "&amp;#999999999;" in result


class TestOrphanTagSweep:
    """Orphan opening tags (no matching close) must be escaped."""

    def test_orphan_a_tag_escaped(self):
        result = escape_for_pango('renders <a href="..."> tags')
        assert '<a ' not in result  # not preserved as valid tag
        assert '<a' not in result     # fully escaped

    def test_orphan_b_tag_escaped(self):
        result = escape_for_pango('<b>bold')
        assert '<b>' not in result  # not preserved as valid tag
        assert '<b>' not in result  # fully escaped

    def test_valid_tag_pair_preserved(self):
        assert escape_for_pango('<b>bold</b>') == '<b>bold</b>'

    def test_valid_a_tag_pair_preserved(self):
        result = escape_for_pango('<a href="https://x.com">link</a>')
        assert '<a href="https://x.com">link</a>' == result

    def test_nested_valid_tags_preserved(self):
        assert escape_for_pango('<b><i>nested</i></b>') == '<b><i>nested</i></b>'

    def test_grep_output_with_a_tag(self):
        """The exact crash trigger: plain text containing <a href="...">."""
        result = escape_for_pango('# \u2190 renders <a href="..."> tags')
        assert '<a ' not in result  # not preserved as valid tag
        assert '<a' not in result     # fully escaped

    def test_no_orphan_when_all_closed(self):
        """When all tags are properly closed, sweep does nothing."""
        result = escape_for_pango('<b>one</b> <i>two</i>')
        assert result == '<b>one</b> <i>two</i>'


class TestPangoCaseSensitivity:
    """Pango is CASE-SENSITIVE on tag names and attribute names."""

    def test_uppercase_tag_pair_normalized(self):
        """Pango is CASE-SENSITIVE on tag names. Uppercase must be lowercased."""
        assert escape_for_pango("<B>orphan</B>") == "<b>orphan</b>"

    def test_mixed_case_tag_normalized(self):
        """Mixed case input must normalize to all-lowercase output."""
        assert escape_for_pango("<B>x</b>") == "<b>x</b>"
        assert escape_for_pango("<b>x</B>") == "<b>x</b>"
        assert escape_for_pango("<Span>x</span>") == "<span>x</span>"

    def test_uppercase_closing_tag_normalized(self):
        """Closing tag with uppercase name must be lowered to match opening."""
        assert escape_for_pango("<b>x</B>") == "<b>x</b>"

    def test_uppercase_attribute_name_normalized(self):
        """Pango is case-sensitive on attribute names. Uppercase must be lowered."""
        result = escape_for_pango('<span FOREGROUND="red">x</span>')
        assert 'foreground="red"' in result, f"Got: {result!r}"
        assert 'FOREGROUND="red"' not in result, f"Got: {result!r}"

    def test_mixed_case_attribute_name_normalized(self):
        """Mixed-case attribute name normalizes to lowercase."""
        result = escape_for_pango('<span Foreground="red">x</span>')
        assert 'foreground="red"' in result, f"Got: {result!r}"

    def test_attribute_value_case_preserved(self):
        """Attribute values are preserved exactly (case-sensitive user data)."""
        result = escape_for_pango('<span foreground="RED">x</span>')
        assert '<span foreground="RED">x</span>' == result

    def test_nested_uppercase_tags_normalized(self):
        """All Pango tags in nested structure must be lowercased."""
        assert escape_for_pango("<B><I>nested</I></B>") == "<b><i>nested</i></b>"
        assert escape_for_pango("<B><B>double</B></B>") == "<b><b>double</b></b>"

    def test_uppercase_self_closing_normalized(self):
        """Self-closing void tags with uppercase name normalized."""
        assert escape_for_pango("<BR/>") == "<br/>"
        assert escape_for_pango("<HR/>") == "<hr/>"

    def test_uppercase_orphan_tag_still_escaped(self):
        """Orphan tags are escaped regardless of input case."""
        # Uppercase orphan tags become lowercase, then are fully HTML-escaped
        # so they appear as literal text in the output
        assert escape_for_pango('<B>no close') == '&lt;b&gt;no close'
        assert escape_for_pango('<B attr="val">no close') == '&lt;b attr=&quot;val&quot;&gt;no close'