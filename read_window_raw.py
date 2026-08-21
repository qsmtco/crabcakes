import sys

with open('ui/window.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Print exact indices around known line numbers
for idx in [50, 276, 277, 278, 279, 280, 312, 313, 314, 315, 316,
            559, 560, 561, 562, 563, 564, 565, 566, 567, 568, 569, 570,
            571, 572, 573, 574, 575, 576, 577, 578, 579, 580, 581, 582,
            583, 584, 585, 586, 587, 588, 589, 590]:
    if 0 <= idx-1 < len(lines):
        print(f"{idx:4d}: {lines[idx-1].rstrip()}")
    else:
        print(f"{idx:4d}: <out of range>")

print(f"\nTotal lines: {len(lines)}")
