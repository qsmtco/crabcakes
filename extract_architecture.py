#!/usr/bin/env python3
with open('docs/ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Find sections containing "prompt" or "file context"
for i, line in enumerate(lines):
    lower = line.lower()
    if 'prompt' in lower or 'file context' in lower:
        print(f"{i+1:4d}: {line.rstrip()}")
