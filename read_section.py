#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Print around first PHASE-5 comment
idx1 = content.find("# PHASE-5: seed per-project prompts")
print(f"idx1 = {idx1}")
if idx1 >= 0:
    print(content[idx1:idx1+500])
    print("="*60)

# Print around second PHASE-5 comment
idx2 = content.find("# PHASE-5: reset handlers")
print(f"idx2 = {idx2}")
if idx2 >= 0:
    print(content[idx2:idx2+500])
