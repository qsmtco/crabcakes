"""Find messages with potential triple-backtick code blocks containing < and > chars."""
import json

with open('/home/q/.config/crabcakes/conversations/special:supervisor.json') as f:
    data = json.load(f)
msgs = data['messages']

# Find messages that contain ```python or ``` blocks with < or > symbols
# These, when rendered, might have problems
print(f'Total messages: {len(msgs)}')
print()

# Look at last 200 messages (recent ones)
for i, m in enumerate(msgs[-200:]):
    actual_i = len(msgs) - 200 + i
    c = m.get('content', '')
    if not isinstance(c, str):
        continue
    role = m.get('role', '?')
    # Look for ```python blocks with < or > chars
    if '```python' in c or '```py' in c or '```bash' in c:
        snippet = c.replace('\n', '\\n')
        if '<' in c[-2000:] or '>' in c[-2000:]:  # raw arrows in last 2k
            print(f'\n=== MSG {actual_i} ({role}, len={len(c)}) ===')
            print(snippet[:500])
            if i > 5:
                break