#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

for pattern in [
    "# PHASE-5: seed per-project prompts",
    "# PHASE-5: reset handlers",
    "seed_project_prompts(p)",
    "set_project_path(p)",
    "set_project_path(None)",
]:
    idx = content.find(pattern)
    print(f"'{pattern}' at byte {idx}")
    if idx >= 0:
        # Print a few lines around it
        start = content.rfind('\n', 0, idx)
        if start < 0: start = 0
        end = content.find('\n', idx)
        if end < 0: end = len(content)
        print(f"  -> {content[start:end]}")
