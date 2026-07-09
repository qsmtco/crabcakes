from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Minimal reproduction case
content = "wrap it in `<tt>` tags"
escaped = escape_for_pango(content)
print('Escaped:', repr(escaped))
formatted = format_markdown(escaped)
print('Formatted:', repr(formatted))
print()
print('<tt> count:', formatted.count('<tt>'))
print('</tt> count:', formatted.count('</tt>'))