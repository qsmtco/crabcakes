import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
from ui.views.chat_bubble import _process_text_chunk, extract_blocks

# This is the EXACT content of my assistant message bubble
content = """I can't run commands right now — the exec approval gate is blocking me. But I can see the problem from the error output you pasted.

## What's happening

The persisted Coder conversation contains text with HTML entities like `&quot;`, `&amp;`, `&#x27;`, `&gt;`. When CrabCakes restores the conversation on project open, it runs this text through `escape_for_pango` → `format_markdown`. 

The **strict unescape fix** I just implemented changed how these entities are handled. The text in the persisted conversation was saved **before** the fix, with the old lenient `html.unescape` behavior. Now the strict unescape is preserving entities that the old code would have decoded, and this is producing output that Pango rejects.

Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).

## The immediate fix

You need to clear Coder's persisted conversation so the broken content doesn't load on startup. Run this in a terminal:

```bash
rm ~/.config/crabcakes/conversations/special:coder.json
```

This deletes the saved conversation (304 messages, ~800KB — the one we identified earlier as bloated). Coder will start fresh next time.

After deleting it, restart CrabCakes and try opening the project again.

I'm sorry this happened. The strict unescape fix is correct for new messages, but it created an incompatibility with old persisted conversations that were saved under the lenient regime. I need to investigate the exact failure mode and add backward compatibility once I can run commands again."""

print('Content length:', len(content))
print('Has markdown-formatted HTML entities:', '&amp;' in content or '&gt;' in content or '&quot;' in content)

# Now run through the actual chat bubble pipeline
processed = []
segments = extract_blocks(content)
print('Segments:', len(segments))

# Process it
_process_text_chunk(content, processed)
print()
print('Processed segments:', len(processed))
for p in processed:
    ptype = p.get('type')
    if ptype == 'code':
        markup = p.get('code_markup', '')
        print(f'  CODE: {markup[:500]!r}')
    else:
        markup = str(p.get('markup', p.get('content','')))
        print(f'  {ptype.upper()}: {markup[:500]!r}')

# Try to render the TEXT segments
print()
print('=== RENDERING TEST ===')
all_ok = True
for p in processed:
    if p.get('type') in ('text', 'code'):
        markup = p.get('markup', p.get('code_markup', ''))
        label = Gtk.Label()
        try:
            label.set_markup(markup)
        except Exception as e:
            print(f'FAIL on {p["type"]}: {e}')
            all_ok = False
if all_ok:
    print('ALL SEGMENTS RENDER OK')

print()
print('=== FULL PIPELINE TEST ===')
escaped = escape_for_pango(content)
formatted = format_markdown(escaped)
print('First 200 of formatted:', repr(formatted[:200]))
print('Last 200 of formatted:', repr(formatted[-200:]))
try:
    label = Gtk.Label()
    label.set_markup(formatted)
    print('OK - the pipeline output renders without warning')
except Exception as e:
    print(f'FAIL pipeline: {e}')