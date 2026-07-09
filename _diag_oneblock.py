from utils.markdown import format_markdown

# Just the markdown content (no escape_for_pango)
content = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
formatted = format_markdown(content)
print('No escape first:')
print(formatted)
print()
print('tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))