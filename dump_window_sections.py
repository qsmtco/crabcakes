#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('window_lines.txt', 'w', encoding='utf-8') as out:
    # Import section
    out.write("=== Import section (lines 48-52) ===\n")
    for i in range(48, 53):
        if i < len(lines):
            out.write(f"{i:4d}: {lines[i]}")
    
    # Around input_toolbar_handler construction
    out.write("\n=== InputToolbarHandler (lines 313-316) ===\n")
    for i in range(313, 317):
        if i < len(lines):
            out.write(f"{i:4d}: {lines[i]}")
    
    # Around project_opened lambda
    out.write("\n=== Project opened lambda (lines 570-584) ===\n")
    for i in range(570, 585):
        if i < len(lines):
            out.write(f"{i:4d}: {lines[i]}")
    
    # Around project_closed lambda
    out.write("\n=== Project closed lambda (lines 590-602) ===\n")
    for i in range(590, 603):
        if i < len(lines):
            out.write(f"{i:4d}: {lines[i]}")
    
    out.write(f"\n=== Total lines: {len(lines)} ===\n")
