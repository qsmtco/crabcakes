from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# Full message body
content = """Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).

## The immediate fix

You need to clear Coder's persisted conversation so the broken content doesn't load on startup. Run this in a terminal:

```bash
rm ~/.config/crabcakes/conversations/special:coder.json
```

This deletes the saved conversation (304 messages, ~800KB)."""

escaped = escape_for_pango(content)
print('=== Escaped ===')
print(repr(escaped[-300:]))
print()

formatted = format_markdown(escaped)
print('=== Formatted (last 500) ===')
print(formatted[-500:])
print()
print('tt open:', formatted.count('<tt>'), 'tt close:', formatted.count('</tt>'))

# Try rendering
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
label = Gtk.Label()
try:
    label.set_markup(formatted)
    print('OK - renders')
except Exception as e:
    print(f'FAIL: {e}')