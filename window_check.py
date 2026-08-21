#!/usr/bin/env python3
"""Read window.py and write relevant section to a file for inspection."""
with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('window_section.txt', 'w', encoding='utf-8') as out:
    for i, line in enumerate(lines, 1):
        if 'seed_project_prompts' in line or 'PHASE-5' in line or 'set_project_path' in line:
            out.write(f"{i:4d}: {line}")

print("Done. See window_section.txt")
