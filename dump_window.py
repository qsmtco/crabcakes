import sys

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = len(lines)

# Write to a clean temp file
with open('window_dump.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total lines: {total}\n\n")
    
    # Lines around 270-290 (prompts_handler creation)
    out.write("=== Lines 270-290 (PromptsHandler) ===\n")
    for i in range(269, min(291, total)):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write("\n")
    
    # Lines around 308-325 (input_toolbar_handler creation)
    out.write("=== Lines 308-325 (InputToolbarHandler) ===\n")
    for i in range(307, min(326, total)):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write("\n")
    
    # Lines around 560-595 (project opened lambda)
    out.write("=== Lines 560-595 (project opened lambda) ===\n")
    for i in range(559, min(596, total)):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write("\n")
    
    # Lines around 578-600 (project closed lambda)
    out.write("=== Lines 578-600 (project closed lambda) ===\n")
    for i in range(577, min(601, total)):
        out.write(f"{i+1:4d}: {lines[i]}")
    out.write("\n")

print("Done. Wrote to window_dump.txt")
