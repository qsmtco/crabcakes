import html
s = 'say "hi"'
print('input:', repr(s))
print('escape default:', repr(html.escape(s)))
print('escape quote=True:', repr(html.escape(s, quote=True)))