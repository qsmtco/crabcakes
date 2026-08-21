#!/usr/bin/env python3
with open('docs/ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'Prompt library: load' in line:
        print(f"Found at line {i+1}")
        print("="*60)
        for j in range(max(0, i-3), min(len(lines), i+12)):
            print(f"{j+1:4d}| {lines[j]}", end='')
        print("="*60)
        break
