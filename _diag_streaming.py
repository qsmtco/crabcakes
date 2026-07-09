from utils.escaping import escape_for_pango
from utils.markdown import format_markdown

# The streaming path: escape_for_pango -> format_markdown -> set_markup
content = """Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).

## The immediate fix

You need to clear Coder's persisted conversation so the broken content doesn't load on startup. Run this in a terminal:

```bash
rm ~/.config/crabcakes/conversations/special:coder.json
```

This deletes the saved conversation."""

escaped = escape_for_pango(content)
print('Escaped last 200:', repr(escaped[-200:]))

formatted = format_markdown(escaped)
print('Formatted:')
print(formatted)
print()
print('<tt> open:', formatted.count('<tt>'), 'close:', formatted.count('</tt>'))

# Now also try _restore_code in format_markdown — there might be a protection issue
print()
print('=== Trying with full inline code sequence ===')
# The issue is `_parse_code_span` looks for backticks
# Both inline (`&quot;`) and fenced (```bash) coexist
# Let me check what _collect_code_spans does
import utils.markdown as M
code_spans = []
def collect_test(t):
    # monkey-patch to capture
    pass

# Run format_markdown manually and trace
result = M._collect_code_spans(escaped)
print('After protect:', repr(result[:300]))
print('Code spans captured:', len(M._format_markdown.__globals__))

# Hmm, code_spans is local. Let me check the function:
import inspect
src = inspect.getsource(M.format_markdown)
print('format_markdown first 500 chars:')
print(src[:500])