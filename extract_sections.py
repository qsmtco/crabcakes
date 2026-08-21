#!/usr/bin/env python3
"""Extract key sections from ui/window.py."""

import sys

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = len(lines)
print(f"Total lines: {total}", file=sys.stderr)

# PromptsHandler creation (around line 278)
print("\n=== PROMPTS_HANDLER (lines 272-286) ===")
for i in range(271, min(287, total)):
    print(f"{i+1:4d}: {lines[i]}", end='')

# InputToolbarHandler creation (around line 314)
print("\n=== INPUT_TOOLBAR_HANDLER (lines 310-322) ===")
for i in range(309, min(323, total)):
    print(f"{i+1:4d}: {lines[i]}", end='')

# Project opened lambda (around line 561)
print("\n=== PROJECT_OPENED (lines 555-595) ===")
for i in range(554, min(596, total)):
    print(f"{i+1:4d}: {lines[i]}", end='')

# Project closed lambda (around line 579)
print("\n=== PROJECT_CLOSED (lines 575-600) ===")
for i in range(574, min(601, total)):
    print(f"{i+1:4d}: {lines[i]}", end='')
