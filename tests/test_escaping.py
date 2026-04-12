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
        assert escape_for_pango('<span foreground="red">red</span>') == (
            '<span foreground="red">red</span>'
        )

    def test_nested_tags_preserved(self):
        assert escape_for_pango("<b><i>bold italic</i></b>") == (
            "<b><i>bold italic</i></b>"
        )

    def test_mixed_tags_with_ampersand_in_content(self):
        result = escape_for_pango("<b>Tom & Jerry</b>")
        assert result == "<b>Tom &amp; Jerry</b>"

    # ── Malformed closing tags ────────────────────────────────────────────────

    def test_unmatched_closing_tag_escaped(self):
        # No matching open tag → closing tag is escaped
        assert escape_for_pango("</b>") == "&lt;/b&gt;"

    def test_wrong_closing_tag_escaped(self):
        # <i> opened, </b> closed — </b> should be escaped
        assert escape_for_pango("<i>text</b>") == "<i>text&lt;/b&gt;"

    def test_double_closing_escaped(self):
        # Second </i> has no matching open → escaped
        assert escape_for_pango("<b>text</b></i>") == "<b>text</b>&lt;/i&gt;"

    # ── Incomplete / malformed opening tags ─────────────────────────────────

    def test_incomplete_open_tag_preserved(self):
        # Open tag with no close: the <b> IS preserved (valid Pango tag)
        # Pango will render 'not closed' in bold until end-of-text.
        # Our escape function preserves valid-looking tags.
        assert escape_for_pango("<b>not closed") == "<b>not closed"

    # ── Void / self-closing tags ────────────────────────────────────────────

    def test_br_tag_preserved(self):
        assert escape_for_pango("line1<br/>line2") == "line1<br/>line2"

    def test_hr_tag_preserved(self):
        assert escape_for_pango("<hr/>") == "<hr/>"

    # ── Attribute handling ─────────────────────────────────────────────────

    def test_tag_with_attributes_preserved(self):
        result = escape_for_pango('<span foreground="#ff0000" weight="bold">red bold</span>')
        assert result == '<span foreground="#ff0000" weight="bold">red bold</span>'

    def test_link_tag_with_url(self):
        result = escape_for_pango('<a href="http://example.com"><u>link</u></a>')
        assert result == '<a href="http://example.com"><u>link</u></a>'

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_only_tag_characters(self):
        assert escape_for_pango("<>>") == "&lt;&gt;&gt;"

    def test_multiple_ampersands(self):
        assert escape_for_pango("A & B & C") == "A &amp; B &amp; C"

    def test_trailing_lt_escaped(self):
        assert escape_for_pango("text < at end") == "text &lt; at end"
