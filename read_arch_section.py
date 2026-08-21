#!/usr/bin/env python3
with open('docs/ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find line with "Prompt library: load"
for i, line in enumerate(lines):
    if 'Prompt library: load' in line:
        # Print lines 35-60
        for j in range(max(0, i-5), min(len(lines), i+15)):
            print(f"{j+1:4d}: {lines[j]}", end='')
        break
