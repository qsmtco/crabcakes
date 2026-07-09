"""Investigate: is <a href='...'> being mis-detected as auto-link?"""
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Single problematic line
content = '<a href="..."> tags'
print("Input:", repr(content))
escaped = escape_for_pango(content)
print("Escaped:", repr(escaped))
formatted = format_markdown(escaped)
print("Formatted:", repr(formatted))
print(f"<a count: open={formatted.count('<a ')} close={formatted.count('</a>')}")
print()

# Check what's in the raw content from the user's grep
content2 = "131: formatted = format_markdown(escaped) # ← renders <a href=\"...\"> tags"
print("Input2:", repr(content2))
escaped2 = escape_for_pango(content2)
print("Escaped2:", repr(escaped2))
formatted2 = format_markdown(escaped2)
print("Formatted2:", repr(formatted2))
print(f"<a count: open={formatted2.count('<a ')} close={formatted2.count('</a>')}")