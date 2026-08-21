#!/usr/bin/env python3
with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find create_project method
start = None
for i, line in enumerate(lines):
    if 'def create_project' in line:
        start = i
        break

if start is not None:
    # Find end of method (next method at same indent or class end)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith('    def ') and not lines[j].startswith('        '):
            end = j
            break
    
    with open('create_project_dump.txt', 'w', encoding='utf-8') as out:
        for i in range(start, end):
            out.write(f"{i+1:4d}| {lines[i]}")
    print(f"Wrote lines {start+1}-{end} to create_project_dump.txt")
else:
    print("create_project not found")
