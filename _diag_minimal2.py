from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Specifically: the source line that broke
content = "Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `\"`, but then the code block formatting wraps it in `<tt>` tags and the `\"` characters inside code blocks interact badly with the attribute escaping)."
escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('=== Source ===')
print(content)
print()
print('=== Escaped ===')
print(escaped)
print()
print('=== Formatted ===')
print(formatted)
print()
print('<tt>:', formatted.count('<tt>'), '  </tt>:', formatted.count('</tt>'))

# Import for set_markup test
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
label = Gtk.Label()
try:
    label.set_markup(formatted)
    print('OK - renders')
except Exception as e:
    print(f'FAIL: {e}')