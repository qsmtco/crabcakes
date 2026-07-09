"""Trace the bug by reading the format_markdown source and parsing it manually."""
from utils.markdown import format_markdown

escaped = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
formatted = format_markdown(escaped)
print('Input (escaped):')
print(repr(escaped))
print()
print('Output:')
print(repr(formatted))
print()

# Hex dump to see what's getting matched
print('Escaped (visualized):')
print(escaped)
print()
print('=========================')

# Let's manually do what _collect_code_spans does
text = escaped
i = 0
result_parts = []
code_spans = []
iteration = 0
while i < len(text):
    iteration += 1
    chunk = text[i:]
    if iteration > 20:
        print('Breaking - too many iterations')
        break

    if chunk.startswith('> '):
        result_parts.append(text[i])
        i += 1
        continue

    if (chunk.startswith('```') or chunk.startswith('``') or chunk.startswith('`')) \
            and len(chunk) >= 4 and chunk[3] not in ('`', "'"):
        num = len(chunk) - len(chunk.lstrip('`'))
        rest = chunk[num:]
        fence_char = '`' * num
        close_pos = rest.find('\n' + fence_char)
        if close_pos >= 0:
            block_end = num + close_pos + 1 + num
            block = text[i:i + block_end]
            result_parts.append(f'[FENCED_BLOCK len={len(block)}: {block[:30]!r}...]')
            i += block_end
            continue

    # _parse_code_span
    import re
    BACKTICK_RUN = re.compile(r'^`+')
    m = BACKTICK_RUN.match(chunk)
    if m:
        num = len(m.group(0))
        rest = chunk[num:]
        pattern = re.compile(r'(?<=[^`])`{%d}(?=[^`]|$)' % num)
        m2 = pattern.search(rest)
        if m2:
            content = rest[:m2.start()]
            result_parts.append(f'[INLINE_CODE num={num}, content={content!r}]')
            code_spans.append(content)
            i += num + len(content) + num
            continue

    result_parts.append(text[i])
    i += 1

print('Trace:')
for r in result_parts:
    print(' ', r)