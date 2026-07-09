from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# The exact problematic content
content = """Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping)."""

escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('Just the prose with inline code (no fenced block):')
print(formatted)
print()
print('tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))
print()

# Add the code block
content2 = content + '\n\n```bash\nrm ~/.config/file\n```'

escaped2 = escape_for_pango(content2)
formatted2 = format_markdown(escaped2)
print('With code block:')
print(formatted2)
print()
print('tt open:', formatted2.count('<tt>'), 'close:', formatted2.count('</tt>'))

# Set_markup test
label = Gtk.Label()
try:
    label.set_markup(formatted2)
    print('OK - renders')
except Exception as e:
    print(f'FAIL: {e}')