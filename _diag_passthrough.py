"""Trace the auto-link pipeline for the problematic content."""
from utils.escaping import escape_for_pango

content = '<a href="..."> tags'
escaped = escape_for_pango(content)
print("Escaped:", repr(escaped))

# escape_for_pango preserves known tags literally
# Now run through format_markdown steps
import re
import html as _html

# Step 1: escape_for_pango already done
text = escaped
print("Step 1 (input):", repr(text))

# Step 2: code spans (now testing)
from utils.markdown import _parse_code_span, _collect_code_spans
# Actually the function is internal. Let me just call format_markdown and examine.

from utils.markdown import format_markdown
formatted = format_markdown(text)
print("Final formatted:", repr(formatted))