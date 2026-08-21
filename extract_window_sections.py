#!/usr/bin/env python3
"""Extract key sections from ui/window.py for analysis."""

import sys

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = len(lines)
print(f"Total lines: {total}")

# Find exact line numbers for key patterns
patterns = [
    'self._prompts_handler = PromptsHandler',
    'self._input_toolbar_handler = InputToolbarHandler',
    'set_active_project_path(p)',
    'clear_active_project_path()',
]

for pattern in patterns:
    for i, line in enumerate(lines):
        if pattern in line:
            print(f"\n=== '{pattern}' at line {i+1} ===")
            start = max(0, i-3)
            end = min(total, i+8)
            for j in range(start, end):
                marker = " >>>" if j == i else ""
                print(f"  {j+1:4d}: {lines[j].rstrip()}{marker}")

# Also find the set_on_project_opened and set_on_project_closed lambdas
for i, line in enumerate(lines):
    if 'self._project_handler.set_on_project_opened(' in line and 'lambda' in lines[min(total-1, i+1)]:
        print(f"\n=== set_on_project_opened lambda at line {i+1} ===")
        start = i
        end = min(total, i+25)
        for j in range(start, end):
            print(f"  {j+1:4d}: {lines[j].rstrip()}")
    
    if 'self._project_handler.set_on_project_closed(' in line and 'lambda' in lines[min(total-1, i+1)]:
        print(f"\n=== set_on_project_closed lambda at line {i+1} ===")
        start = i
        end = min(total, i+20)
        for j in range(start, end):
            print(f"  {j+1:4d}: {lines[j].rstrip()}")
