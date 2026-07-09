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
        assert xml_escape_text('say "hi"') == "say \"hi\""

    def test_single_quote_apostrophe(self):
        # html.escape uses ' for single quotes by default
        assert xml_escape_text("it's") == "it's"

    def test_mixed(self):
        assert xml_escape_text("Tom & Jerry <script> \"hi\"") == (
            "Tom & Jerry <script> \"hi\""
        )

    def test_empty_string(self):
        assert xml_escape_text("") == ""


class TestEscapeForPango:
    """Pango-aware escaping — preserves valid tags, escapes malformed ones."""

    # ── Plain text ──────────────────────────────────────────────────────────

    def test_plain_text_unchanged(self):
        assert escape_for_pango("Hello world") == "Hello world"

    def test_plain_text_ampersand_escaped(self):
        assert escape_for_pango("Tom & Jerry") == "Tom & Jerry"

    def test_plain_text_with_literal_brackets_escaped(self):
        # Literal angle brackets (not valid tags) are escaped
        assert escape_for_pango("a < b") == "a < b"
        assert escape_for_pango("a > b") == "a > b"

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
        assert escape_for_pango("<s>strikethrough