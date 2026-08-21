#!/usr/bin/env python3
with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find create_project method and write it to a file
start = None
end = None
for i, line in enumerate(lines):
    if 'def create_project' in line:
        start = i
    if start is not None and i > start:
        # Check if we hit another method at the same indent
        if line.startswith('    def ') and 'create_project' not in line:
            end = i
            break

if start is not None:
    with open('create_project_method.txt', 'w', encoding='utf-8') as out:
        for i in range(start, end if end else min(start + 80, len(lines))):
            out.write(lines[i])
    print(f"Wrote lines {start+1} to {end if end else start+80}")
else:
    print("create_project not found")
