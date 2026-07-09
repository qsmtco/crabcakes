"""Scan supervisor conversation for content that might trigger GTK warning."""
import json, sys

with open('/home/q/.config/crabcakes/conversations/special:supervisor.json') as f:
    data = json.load(f)
msgs = data['messages']
print(f'Total messages: {len(msgs)}')

# Find messages containing suspicious patterns
suspicious_keywords = [
    '&amp;', '&lt;', '&gt;', '&copy;', '&nbsp;',
    'failed to set', 'markup', 'gtk', 'unescape',
    '>', '<', '&',  # any escape chars in raw
]
for i, m in enumerate(msgs):
    c = m.get('content', '')
    if not isinstance(c, str):
        continue
    # Look for content that LOOKS LIKE Python code with raw <, >
    if ('<a href' in c or 'escape_for_pango' in c or '_strict_unescape' in c or
        '&lt;<a' in c):
        print(f'MSG {i}: role={m.get("role","?")}, len={len(c)}')
        # Show first 200 chars
        snippet = c[:300].replace('\n', '\\n')
        print(f'  Snippet: {snippet}')
        if i > 30:
            break