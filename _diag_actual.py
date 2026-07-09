"""Diagnostic — show ACTUAL output for each failing test, so we can fix the expectations."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango, xml_escape_text

print("=== TestXmlEscapeText ===")
cases = [
    ("plain_text_unchanged", xml_escape_text("Hello world")),
    ("ampersand_escaped_1", xml_escape_text("Tom & Jerry")),
    ("ampersand_escaped_2", xml_escape_text("A & B & C")),
    ("angle_brackets_script", xml_escape_text("<script>")),
    ("angle_brackets_lt", xml_escape_text("a < b")),
    ("angle_brackets_gt", xml_escape_text("a > b")),
    ("double_quotes", xml_escape_text('say "hi"')),
    ("single_quote", xml_escape_text("it's")),
    ("mixed", xml_escape_text('Tom & Jerry <script> "hi"')),
    ("empty", xml_escape_text("")),
]
for n, out in cases:
    print(f'  {n}: {out!r}')

print()
print("=== TestEscapeForPango ===")
cases = [
    ("plain_text_unchanged", escape_for_pango("Hello world")),
    ("plain_text_ampersand", escape_for_pango("Tom & Jerry")),
    ("literal_brackets_lt", escape_for_pango("a < b")),
    ("literal_brackets_gt", escape_for_pango("a > b")),
    ("empty", escape_for_pango("")),
    ("bold", escape_for_pango("<b>bold text</b>")),
    ("italic", escape_for_pango("<i>italic text</i>")),
    ("monospace", escape_for_pango("<tt>code</tt>")),
    ("underline", escape_for_pango("<u>underlined</u>")),
    ("strikethrough", escape_for_pango("\u34e2strikethrough\u34e2")),
    ("span_colored", escape_for_pango('<span foreground="red">red</span>')),
    ("nested", escape_for_pango("<b><i>bold italic</i></b>")),
    ("mixed_amp_content", escape_for_pango("<b>Tom & Jerry</b>")),
    ("unmatched_closing", escape_for_pango("</b>")),
    ("wrong_closing", escape_for_pango("<i>text</b>")),
    ("double_closing", escape_for_pango("<b>text</b></i>")),
    ("incomplete_open", escape_for_pango("<b>not closed")),
    ("br_self_close", escape_for_pango("line1<br/>line2")),
    ("hr_self_close", escape_for_pango("<hr/>")),
    ("tag_with_attrs", escape_for_pango('<span foreground="#ff0000" weight="bold">red bold</span>')),
    ("link_with_url", escape_for_pango('<a href="http://example.com"><u>link</u></a>')),
    ("only_tag_chars", escape_for_pango("<>>")),
    ("multiple_amps", escape_for_pango("A & B & C")),
    ("trailing_lt", escape_for_pango("text < at end")),
]
for n, out in cases:
    print(f'  {n}: {out!r}')

print()
print("=== TestStrictEntityUnescape (existing wrong tests) ===")
cases = [
    ("well_formed_amp", escape_for_pango("Tom & Jerry")),
    ("well_formed_lt", escape_for_pango("a < b")),
    ("well_formed_gt", escape_for_pango("a > b")),
]
for n, out in cases:
    print(f'  {n}: {out!r}')