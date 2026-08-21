with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

print('Total chars:', len(content))
idx = content.find('set_active_project_path(p)')
print('Found at index:', idx)
if idx > 0:
    print(content[idx-500:idx+500])
