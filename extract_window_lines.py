#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Write lines 570-610 to a file for reading
with open('window_570_610.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total lines in window.py: {len(lines)}\n\n")
    for i in range(569, min(611, len(lines))):
        # Mark known lines
        marker = ""
        if i == 576: marker = " >>> line 577 (PHASE-5 open)"
        elif i == 594: marker = " >>> line 595 (PHASE-5 close)"
        out.write(f"{i+1:4d}: {lines[i].rstrip()}{marker}\n")

print("Wrote window_570_610.txt")
