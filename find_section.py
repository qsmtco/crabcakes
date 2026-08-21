#!/usr/bin/env python3
with open('docs/ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Find key sections
for marker in [
    "## 10. Environment Variables",
    "## 11. Gateway Protocol Reference",
    "## 12. Provider Resolution",
    "## 13. File Inventory",
    "## 14. Principles to Preserve",
]:
    idx = content.find(marker)
    if idx >= 0:
        print(f"'{marker}' at byte {idx}")
    else:
        print(f"'{marker}' NOT FOUND")

# Also find around the file index section
idx = content.find("## 13. File Inventory")
if idx >= 0:
    print(f"\nContext around ## 13:")
    print(content[idx-200:idx+500])
