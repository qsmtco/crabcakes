#!/usr/bin/env python3
"""Verify the window.py edits."""

with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

checks = [
    ("Import seed_project_prompts", "from utils.project_awareness import seed_project_prompts"),
    ("seed before set_project_path", "seed_project_prompts(p),"),
    ("prompts_handler set_project_path", "self._prompts_handler.set_project_path(p),"),
    ("input_toolbar_handler set_project_path", "self._input_toolbar_handler.set_project_path(p),"),
    ("prompts_handler load_prompts", "self._prompts_handler.load_prompts(),"),
    ("left_panel refresh on open", "self._left_panel.refresh_prompts(),"),
    ("prompts_handler reset on close", "self._prompts_handler.set_project_path(None),"),
    ("input_toolbar_handler reset on close", "self._input_toolbar_handler.set_project_path(None),"),
]

for name, pattern in checks:
    if pattern in content:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name} — missing '{pattern}'")

# Count occurrences of refresh_prompts() and load_prompts()
refresh_count = content.count("self._left_panel.refresh_prompts()")
load_count = content.count("self._prompts_handler.load_prompts()")
print(f"\nrefresh_prompts() occurrences: {refresh_count} (expected: 2)")
print(f"load_prompts() occurrences: {load_count} (expected: 2)")

# Verify no second set_on_project_opened/closed call
opened_calls = content.count("self._project_handler.set_on_project_opened(")
closed_calls = content.count("self._project_handler.set_on_project_closed(")
print(f"\nset_on_project_opened calls: {opened_calls} (expected: ≤6 — multiple existing callbacks)")
print(f"set_on_project_closed calls: {closed_calls} (expected: ≤5 — multiple existing callbacks)")

# Verify seed is before set_project_path in the tuple
seed_idx = content.find("seed_project_prompts(p),")
ph_set_idx = content.find("self._prompts_handler.set_project_path(p),")
if seed_idx < ph_set_idx:
    print("\nPASS: seed_project_prompts(p) comes BEFORE prompts_handler.set_project_path(p)")
else:
    print(f"\nFAIL: seed order wrong — seed@{seed_idx}, set@{ph_set_idx}")

print("\nDone.")
