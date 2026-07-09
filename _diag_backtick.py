from utils.escaping import escape_for_pango

# Test 1: backticks alone
content = "```bash"
result = escape_for_pango(content)
print('TEST 1 (just ```):', repr(result))

# Test 2: triple backticks within multi-line
content = """Run this:

```bash
rm file
```

end"""
result = escape_for_pango(content)
print('TEST 2 multi-line:')
print(repr(result))
print()

# Now try the actual full content
content = '''Specifically, `&quot;` is being preserved by strict unescape (it's in the allowlist and has a semicolon, so it decodes to `"`, but then the code block formatting wraps it in `<tt>` tags and the `"` characters inside code blocks interact badly with the attribute escaping).'''
print('SOURCE:', repr(content[:100]))
result = escape_for_pango(content)
print('ESCAPED:')
print(result)
print()
print('Count <:', result.count('<'), '> :', result.count('>'), '` :', result.count('`'))