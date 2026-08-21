#!/usr/bin/env python3
with open('docs/ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the file inventory section
idx = content.find("## 13. File Inventory")
if idx >= 0:
    print(f"Found at byte {idx}")
    print(content[idx:idx+800])
else:
    print("NOT FOUND")
