from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Just the fenced block alone
content = "Run this:\n\n```bash\nrm ~/.config/file\n```\n\nEnd."
escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('Format 1:')
print(repr(formatted))
print()
print('tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))

# With inline code too
content2 = "Test `&quot;` and:\n\n```bash\nrm file\n```\n\nEnd."
escaped2 = escape_for_pango(content2)
formatted2 = format_markdown(escaped2)
print()
print('Format 2:')
print(repr(formatted2))
print()
print('tt open:', formatted2.count('<tt>'), 'close:', formatted2.count('</tt>'))