"""Test inline code containing <tt> tags."""
from utils.markdown import format_markdown

# Test: inline code with < known tag > inside
content = "Use `<tt>` for monospace."
formatted = format_markdown(content)
print('inline-code-with-tt:')
print(formatted)
print()

# Test: nested backticks
content2 = "Wrap code in `` `code` `` markers."
formatted2 = format_markdown(content2)
print('nested-backticks:')
print(formatted2)
print()

# Test: <tt> as plain text in code block
content3 = "Run:\n\n```\nprint('<tt>')\n```\n\nEnd"
formatted3 = format_markdown(content3)
print('fenced-with-literal-tt:')
print(formatted3)