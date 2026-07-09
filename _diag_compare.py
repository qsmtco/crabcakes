from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# The simplest test that triggers
content = """Test `&quot;` and:

```bash
rm file
```

End of message."""

escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('Full body:')
print(formatted)
print()
print('tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))

# Test just simple inline
content2 = "Test `code` and end."
escaped2 = escape_for_pango(content2)
formatted2 = format_markdown(escaped2)
print()
print('Inline only:')
print(formatted2)
print('tt open:', formatted2.count('<tt>'), 'close:', formatted2.count('</tt>'))

# Test just code block
content3 = "Test:\n\n```bash\nrm file\n```\n\nEnd."
escaped3 = escape_for_pango(content3)
formatted3 = format_markdown(escaped3)
print()
print('Code block only:')
print(formatted3)
print('tt open:', formatted3.count('<tt>'), 'close:', formatted3.count('</tt>'))

# Test both combined but different formatting
content4 = "Test `code`\n\n```bash\nrm file\n```\n\nEnd."
escaped4 = escape_for_pango(content4)
formatted4 = format_markdown(escaped4)
print()
print('Both:')
print(formatted4)
print('tt open:', formatted4.count('<tt>'), 'close:', formatted4.count('</tt>'))