import re

attrs = ' href="https://example.com&gt"'
print(f'attrs: {attrs!r}')

# Test the regex
def _escape_attr_ampersands(m):
    print(f'  matched: {m.group(0)!r}')
    return m.group(0).replace('&', '&amp;')

result = re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, attrs)
print(f'result: {result!r}')