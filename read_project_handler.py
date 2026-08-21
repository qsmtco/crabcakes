with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find create_project and init_workflow
for i, line in enumerate(lines):
    if 'def create_project' in line or 'init_workflow' in line or 'import' in line:
        print(f"{i+1:4d}: {line.rstrip()}")

print(f"\nTotal lines: {len(lines)}")

# Show lines 175-195 around init_workflow
print("\n=== Lines 175-200 ===")
for i in range(174, min(200, len(lines))):
    print(f"{i+1:4d}: {lines[i]}", end='')
