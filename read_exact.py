with open('ui/handlers/project_handler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find create_project and extract method body
start = content.find('def create_project')
if start >= 0:
    # Find next method at same indent level (4 spaces + def)
    method_start = start
    # Skip to end of method - find next occurrence of "\n    def " after method body
    rest = content[method_start+1:]
    next_def = rest.find('\n    def ')
    if next_def >= 0:
        end = method_start + 1 + next_def
    else:
        end = len(content)
    method_body = content[method_start:end]
    print(method_body)
else:
    print("NOT FOUND")
