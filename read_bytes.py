#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the PHASE-5 comment and print surrounding bytes
idx = content.find("PHASE-5: seed per-project prompts")
if idx >= 0:
    start = max(0, idx - 500)
    end = min(len(content), idx + 600)
    print(content[start:end])
else:
    print("PHASE-5 comment not found")

# Also find the second PHASE-5 comment
idx2 = content.find("PHASE-5: reset handlers")
if idx2 >= 0:
    start2 = max(0, idx2 - 500)
    end2 = min(len(content), idx2 + 600)
    print("\n" + "="*60 + "\n")
    print(content[start2:end2])
else:
    print("Second PHASE-5 comment not found")
