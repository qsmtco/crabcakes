#!/usr/bin/env python3
with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Write lines 170-210 (around create_project)
with open('create_project_extract.txt', 'w', encoding='utf-8') as out:
    for i in range(169, min(210, len(lines))):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write(f"\nTotal lines: {len(lines)}\n")

print("Done. See create_project_extract.txt")
