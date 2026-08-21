with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

targets = [
    'self._prompts_handler = PromptsHandler',
    'self._input_toolbar_handler = InputToolbarHandler',
    'set_active_project_path(p)',
    'clear_active_project_path()',
    'self._project_handler.set_on_project_opened(',
    'self._project_handler.set_on_project_closed(',
]

for i, line in enumerate(lines, 1):
    for target in targets:
        if target in line:
            print(f"{i:4d}: {line.rstrip()}")

print(f"\nTotal lines: {len(lines)}")
