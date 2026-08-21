import sys

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines, 1):
    if 'set_active_project_path' in line or 'clear_active_project_path' in line:
        print(f"{i:4d}: {line.rstrip()}")

print("\n--- Around line 560 (project_opened) ---")
for i in range(555, min(590, len(lines))):
    print(f"{i+1:4d}: {lines[i].rstrip()}")

print("\n--- Around line 575 (project_closed) ---")
for i in range(572, min(600, len(lines))):
    print(f"{i+1:4d}: {lines[i].rstrip()}")

print("\n--- Around line 314 (input_toolbar_handler) ---")
for i in range(305, min(325, len(lines))):
    print(f"{i+1:4d}: {lines[i].rstrip()}")

print(f"\n--- Total lines: {len(lines)} ---")
