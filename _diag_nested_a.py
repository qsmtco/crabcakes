"""Verify Debugger's nested <a> claim: does the auto-link regex match URLs inside
href=\"\" attributes, producing nested <a> tags?"""
import re
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')

from utils.escaping import escape_for_pango
from utils.markdown import format_markdown, _AUTO_LINK_RE

# ── Test 1: regex-level check ─────────────────────────────────────────────
# Does _AUTO_LINK_RE match a URL that lives inside href=""?
sample = '<a href="https://example.com">link</a>'
matches = list(_AUTO_LINK_RE.finditer(sample))
print(f"Test 1 — regex on existing <a> tag:")
print(f"  Input: {sample!r}")
print(f"  Matches: {[m.group(0) for m in matches]}")
print(f"  Spans: {[m.span() for m in matches]}")

# ── Test 2: full pipeline ────────────────────────────────────────────────
# Is the URL inside href="" wrapped in a NEW <a> by Step 4?
test_input = 'Click <a href="https://example.com">here</a> for info.'
escaped = escape_for_pango(test_input)
formatted = format_markdown(escaped)
print()
print(f"Test 2 — full pipeline on nested-URL scenario:")
print(f"  Input:   {test_input!r}")
print(f"  Escaped: {escaped!r}")
print(f"  Output:  {formatted!r}")
print(f"  <a  open: {formatted.count('<a ')}")
print(f"  </a> close: {formatted.count('</a>')}")

# ── Test 3: bare-text orphan (QTR's case) — for comparison ──────────────
orphan = 'See <a href="..."> for tags'
escaped2 = escape_for_pango(orphan)
formatted2 = format_markdown(escaped2)
print()
print(f"Test 3 — orphan <a> from plain text (QTR's case):")
print(f"  Input:   {orphan!r}")
print(f"  Output:  {formatted2!r}")
print(f"  <a  open: {formatted2.count('<a ')}")
print(f"  </a> close: {formatted2.count('</a>')}")