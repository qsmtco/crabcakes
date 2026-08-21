#!/usr/bin/env python3
"""Extract create_project and imports from project_handler.py."""

with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('project_handler_extract.txt', 'w', encoding='utf-8') as out:
    # Imports (lines 1-22)
    out.write("=== IMPORTS ===\n")
    for i in range(22):
        out.write(f"{i+1:4d}: {lines[i]}")
    
    # create_project method
    out.write("\n=== create_project ===\n")
    in_method = False
    for i in range(len(lines)):
        if 'def create_project' in lines[i]:
            in_method = True
        if in_method:
            out.write(f"{i+1:4d}: {lines[i]}")
            # Stop when we hit next method definition at same indent level
            if i > 141 and lines[i].startswith('    def ') and 'create_project' not in lines[i]:
                break
    
    out.write(f"\nTotal lines: {len(lines)}\n")

print("Done. Wrote project_handler_extract.txt")
