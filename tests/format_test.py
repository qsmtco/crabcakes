from utils.block_parser import extract_blocks

tests = [
    '```python\ndef greet(name):\n    return f"Hello, {name}!"\nprint(greet("World"))\n```',
    '```python\ndef test():\n    pass\n```',
    '$ echo hello',
    '> This is a quote',
]

for text in tests:
    print('Input:', repr(text[:50]))
    blocks = extract_blocks(text)
    print(' Blocks:', blocks)
    print()