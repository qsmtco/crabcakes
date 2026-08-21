#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('window_extracted.txt', 'w', encoding='utf-8') as out:
    for i in range(570, 585):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write("\n")
    for i in range(590, 603):
        out.write(f"{i+1:4d}: {lines[i]}")
