#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find byte offsets of key markers
markers = [
    "PHASE-5: seed per-project prompts",
    "PHASE-5: reset handlers",
    "seed_project_prompts(p)",
    "self._prompts_handler.set_project_path(p)",
    "self._input_toolbar_handler.set_project_path(p)",
    "self._prompts_handler.load_prompts()",
    "self._left_panel.refresh_prompts()",
    "self._prompts_handler.set_project_path(None)",
    "self._input_toolbar_handler.set_project_path(None)",
]

for m in markers:
    idx = content.find(m)
    if idx >= 0:
        print(f"Found '{m}' at byte {idx}")
        # Print surrounding context
        start = max(0, idx - 200)
        end = min(len(content), idx + len(m) + 200)
        context = content[start:end]
        print(f"Context:\n{context}\n{'='*60}")
    else:
        print(f"NOT FOUND: '{m}'")
    print()
