#!/usr/bin/env python3
"""Extract key sections from ui/window.py and write to a clean file."""

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = len(lines)
print(f"Total lines: {total}")

# Find all occurrences of key patterns and extract surrounding context
results = []

for i, line in enumerate(lines):
    # Find PromptsHandler creation
    if 'self._prompts_handler = PromptsHandler(' in line:
        start = max(0, i-2)
        end = min(total, i+8)
        results.append(("PROMPTS_HANDLER", start, end, i))
    
    # Find InputToolbarHandler creation  
    if 'self._input_toolbar_handler = InputToolbarHandler(' in line:
        start = max(0, i-2)
        end = min(total, i+8)
        results.append(("INPUT_TOOLBAR_HANDLER", start, end, i))
    
    # Find set_active_project_path(p)
    if 'set_active_project_path(p)' in line:
        # Find the lambda start
        for j in range(max(0, i-20), i+1):
            if 'lambda' in lines[j]:
                start = j
                break
        else:
            start = max(0, i-5)
        # Find the end of the tuple (next line with just )
        for j in range(i, min(total, i+20)):
            if lines[j].strip() == ')':
                end = j + 1
                break
        else:
            end = min(total, i+15)
        results.append(("PROJECT_OPENED", start, end, i))
    
    # Find clear_active_project_path()
    if 'clear_active_project_path()' in line:
        for j in range(max(0, i-20), i+1):
            if 'lambda' in lines[j]:
                start = j
                break
        else:
            start = max(0, i-5)
        for j in range(i, min(total, i+15)):
            if lines[j].strip() == ')':
                end = j + 1
                break
        else:
            end = min(total, i+10)
        results.append(("PROJECT_CLOSED", start, end, i))

# Write extracted sections to output file
with open('window_extract.txt', 'w', encoding='utf-8') as out:
    for name, start, end, target_line in results:
        out.write(f"\n{'='*60}\n")
        out.write(f"SECTION: {name} (target line {target_line+1})\n")
        out.write(f"{'='*60}\n")
        for j in range(start, end):
            marker = ">>> " if j == target_line else "    "
            out.write(f"{marker}{j+1:4d}: {lines[j]}")
        out.write("\n")

print("Extracted to window_extract.txt")
