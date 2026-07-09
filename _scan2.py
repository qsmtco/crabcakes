"""Find messages with content that might trigger Pango errors."""
import json, re

with open('/home/q/.config/crabcakes/conversations/special:supervisor.json') as f:
    data = json.load(f)
msgs = data['messages']

# Find messages that look like they contain problematic markup
# A bubble rendered message passes through escape_for_pango+format_markdown.
# If a message has raw < or > in code blocks (not pre-escaped), the format_markdown
# might emit something Pango can't parse.

candidates = []
for i, m in enumerate(msgs):
    c = m.get('content', '')
    if not isinstance(c, str):
        continue
    # Look for embedded code blocks (triple backticks)
    if '```' in c or '<' in c[:1000]:
        # Count unbalanced < or > in code
        candidates.append((i, m.get('role', '?'), c))

print(f'Candidates: {len(candidates)}')
# Inspect first non-tool messages
shown = 0
for i, role, c in candidates:
    if role == 'tool':
        continue
    # Show first 200 chars
    snippet = c.replace('\n', '\\n')[:300]
    print(f'\n=== MSG {i} ({role}, len={len(c)}) ===')
    print(snippet)
    shown += 1
    if shown >= 5:
        break