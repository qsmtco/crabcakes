from utils.escaping import escape_for_pango
from ui.views.chat_bubble import _process_text_chunk, extract_blocks

# Test what extract_blocks does
content = """Specifically, `&quot;` is being preserved.

```bash
rm ~/.config/file
```

This deletes the saved conversation."""

escaped = escape_for_pango(content)
print('Escaped:')
print(repr(escaped))
print()

segments = extract_blocks(content)
print('Segments:', len(segments))
for i, seg in enumerate(segments):
    print(f'  [{i}] type={seg.get("type")}, content={seg.get("content", "")[:80]!r}')
print()

# Run through _process_text_chunk
processed = []
_process_text_chunk(escaped, processed)
print('Processed:', len(processed))
for p in processed:
    ptype = p.get('type')
    if ptype == 'code':
        markup = p.get('code_markup', '')
        print(f'  CODE: {markup!r}')
    else:
        markup = str(p.get('markup', p.get('content','')))
        print(f'  {ptype.upper()}: {markup!r}')