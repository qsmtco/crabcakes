#!/usr/bin/env python3
with open('agent/context.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('context_extract.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total lines: {len(lines)}\n\n")
    
    # DOC_NAMES section
    out.write("=== DOC_NAMES (around line 162) ===\n")
    for i in range(155, min(195, len(lines))):
        out.write(f"{i+1:4d}: {lines[i]}")
    
    # build_file_context function
    out.write("\n=== build_file_context (line 269) ===\n")
    for i in range(265, min(380, len(lines))):
        out.write(f"{i+1:4d}: {lines[i]}")

print("Wrote context_extract.txt")
