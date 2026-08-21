#!/usr/bin/env python3
with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the init_workflow call in create_project and print surrounding lines
for i, line in enumerate(lines):
    if 'init_workflow(path)' in line:
        print(f"Found at line {i+1}")
        # Print 5 lines before and 5 lines after
        start = max(0, i-5)
        end = min(len(lines), i+6)
        for j in range(start, end):
            print(f"{j+1:4d}: {repr(lines[j])}")
        print("---")
