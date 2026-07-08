import html
tests = [
    '&gt',
    '&gt;',
    '&gt"',
    '&gt<',
    '&amp',
    '&amp;',
    '&lt',
    '&lt;',
]
for t in tests:
    u = html.unescape(t)
    print(f'{t!r:15} -> {u!r}')