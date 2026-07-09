"""Reproduce the user's reported warning."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Reconstruct the content the user saw
content = """./utils/gtk_safe_link.py:88: format_markdown). This helper:
./utils/gtk_safe_link.py:99: + format_markdown).
./utils/markdown.py:25:# format_markdown(text) -&gt; str — converts markdown to Pango Markup
./utils/markdown.py:80:def format_markdown(text: str) -&gt; str:
./docs/audits/2026-06-19-PHASE-6-ADVERSARIAL-AUDIT.md:131: formatted = format_markdown(escaped) # ← renders <a href="..."> tags
./docs/audits/2026-06-19-QTR-DELEGATIONS.md:14:Problem: blockquote path renders format_markdown() output (warn-but-render can include `<a href="javascript:...">`) onto raw Gtk.Label with NO activate-link guard. Clicking the link executes the JS.
./docs/audits/2026-06-19-PHASE-6.1-ADVERSARIAL-AUDIT.md:202:| 729 | `_build_terminal_segment` | Terminal output, `escape_for_pango` applied | ✅ Safe — escaped, no `format_markdown` |
./docs/audits/2026-06-19-PHASE-6.1-ADVERSARIAL-AUDIT.md:203:| 748 | `_build_heading_segment` | Heading text, `escape_for_pango` only | ✅ Safe — escaped, no `format_markdown` |"""

escaped = escape_for_pango(content)
formatted = format_markdown(escaped)

print("=== Counts ===")
print(f"<tt> open={formatted.count('<tt>')} close={formatted.count('</tt>')}")
print(f"<b>  open={formatted.count('<b>')}  close={formatted.count('</b>')}")
print(f"<i>  open={formatted.count('<i>')}  close={formatted.count('</i>')}")
print(f"<u>  open={formatted.count('<u>')}  close={formatted.count('</u>')}")
print(f"<s>  open={formatted.count('<s>')}  close={formatted.count('</s>')}")
print(f"<a   open={formatted.count('<a ')}")
print(f"</a> close={formatted.count('</a>')}")
print(f"<span open={formatted.count('<span')} close={formatted.count('</span>')}")
print()
print("=== Render test ===")
label = Gtk.Label()
label.set_markup(formatted)
print("Rendered successfully")

# Look for `<` or `>` that aren't part of valid markup
import re
# Strip valid Pango tags, what's left should have no bare < or >
tag_stripped = re.sub(r'</?[a-zA-Z]+(?:\s+[^>]*)?>', '', formatted)
bare_lt = tag_stripped.count('<')
bare_gt = tag_stripped.count('>')
print(f"\nAfter stripping tags: bare '<' = {bare_lt}, bare '>' = {bare_gt}")
if bare_lt or bare_gt:
    print("PROBLEM: unescaped < or > leaked through")
    # Find them
    for m in re.finditer(r'.{0,30}[<>].{0,30}', tag_stripped):
        print(f"  ... {m.group(0)!r}")