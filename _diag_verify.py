from utils.markdown import format_markdown
from utils.escaping import escape_for_pango

# Both inline code with <tt> and a fenced code block in the same content
content = """Specifically, `<tt>` tags and:

```bash
rm file
```

End"""
result = format_markdown(content)
print('Bare content tt open:', result.count('<tt>'), 'close:', result.count('</tt>'))

# Now with escape_for_pango (full pipeline)
escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('Full pipeline tt open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))
print()

# Try the FAILED content from the conversation
big = """Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).

## The immediate fix

You need to clear Coder's persisted conversation so the broken content doesn't load on startup. Run this in a terminal:

```bash
rm ~/.config/crabcakes/conversations/special:coder.json
```

This deletes the saved conversation."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

escaped2 = escape_for_pango(big)
formatted2 = format_markdown(escaped2)
print('Bug repro tt open:', formatted2.count('<tt>'), 'close:', formatted2.count('</tt>'))

label = Gtk.Label()
try:
    label.set_markup(formatted2)
    print('OK - the failing content now renders without warning')
except Exception as e:
    print(f'FAIL: {e}')