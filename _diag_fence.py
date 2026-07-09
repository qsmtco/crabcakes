"""Trace _collect_code_spans to find the bug."""
import sys
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.markdown import _collect_code_spans, _parse_code_span, BACKTICK_RUN
import re

# The exact problematic content
escaped = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
print('Input (escaped):')
print(repr(escaped))
print()

result = _collect_code_spans(escaped)
print('After _collect_code_spans:')
print(repr(result))
print()

# Manual trace
print('=== Manual trace ===')
text = escaped
i = 0
while i < len(text):
    chunk = text[i:]
    print(f'i={i}, chunk[0:30]={chunk[:30]!r}')
    if chunk.startswith('> '):
        print('  -> blockquote prefix, skip 1 char')
        i += 1
        continue
    if (chunk.startswith('```') or chunk.startswith('``') or chunk.startswith('`')) \
            and len(chunk) >= 4 and chunk[3] not in ('`', "'"):
        num = len(chunk) - len(chunk.lstrip('`'))
        rest = chunk[num:]
        fence_char = '`' * num
        close_pos = rest.find('\n' + fence_char)
        print(f'  FENCE BLOCK: num={num}, fence={fence_char!r}, close_pos={close_pos}')
        if close_pos >= 0:
            block_end = num + close_pos + 1 + num
            print(f'  Consuming {block_end} chars from position {i}')
            print(f'  Block content: {text[i:i+block_end]!r}')
            i += block_end
            continue
    parsed = _parse_code_span(chunk)
    if parsed is not None:
        content, num = parsed
        print(f'  INLINE CODE: content={content!r}, num={num}')
        i += num + len(content) + num
        continue
    i += 1
    print('  Skip 1 char')