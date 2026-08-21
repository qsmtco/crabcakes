#!/usr/bin/env python3
with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in [50, 576, 577, 578, 579, 580, 594, 595, 596, 597, 598, 314, 315]:
    print(f"{i:4d}: {lines[i-1].rstrip()}")
