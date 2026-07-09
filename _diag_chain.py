from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Full pipeline
content = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
escaped = escape_for_pango(content)
print('Escaped:')
print(repr(escaped))
print()
formatted = format_markdown(escaped)
print('Formatted:')
print(formatted)
print()
print('tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))
print('< open:', formatted.count('<'))
print('> close:', formatted.count('>'))