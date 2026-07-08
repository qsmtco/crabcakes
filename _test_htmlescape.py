import html
tests = [
    '&gt',
    '&gt;',
    '&amp',
    '&amp;',
    '<div>',
    '"hi"',
]
for t in tests:
    e = html.escape(t)
    print(f'{t!r:15} -> {e!r}')