import re
with open('/home/q/projects/crabcakes/docs/specs/spec-strict-entity-unescape.md') as f:
    content = f.read()
# Count code fences (should be even)
fences = re.findall(r'^```', content, re.MULTILINE)
print(f'Total code fences: {len(fences)} (should be even for balanced code blocks)')
print(f'Words: {len(content.split())}')
print(f'Lines: {content.count(chr(10)) + 1}')

# Count section headers
headers = re.findall(r'^#+\s+', content, re.MULTILINE)
print(f'Section headers: {len(headers)}')