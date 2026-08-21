with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(1, 25):
    print(f"{i:4d}: {lines[i-1]}", end='')

print("\n=== create_project ===")
for i in range(141, min(200, len(lines))):
    print(f"{i:4d}: {lines[i-1]}", end='')
    if i > 141 and 'def ' in lines[i-1] and 'create_project' not in lines[i-1]:
        break
