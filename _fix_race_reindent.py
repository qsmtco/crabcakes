#!/usr/bin/env python3
"""Re-indent the body of _run_loop inside a new outer try/finally.

Reads agent/runtime.py, finds _run_loop, re-indents the body
(except the function def line, docstring, and the already-correct
top marker block), adds the outer try/finally, writes back.
"""

with open('agent/runtime.py', 'r') as f:
    lines = f.readlines()

# Find _run_loop boundaries
fn_start = None
fn_end = None
for i, line in enumerate(lines):
    if line.strip().startswith('def _run_loop('):
        fn_start = i
    if fn_start is not None and i > fn_start:
        # Next function definition at same indentation level (8 spaces for class method)
        if line.strip().startswith('def ') and line[:8] == '        ' and i > fn_start + 1:
            fn_end = i
            break
        # Also check for top-level def (not a method)
        if line.strip().startswith('def ') and not line.startswith(' ' * 8) and i > fn_start + 1:
            fn_end = i
            break

if fn_end is None:
    fn_end = len(lines)  # Last function in file

print(f"Function _run_loop: lines {fn_start+1} to {fn_end}")

# The function currently looks like:
# line fn_start:     def _run_loop(...):
# line fn_start+1:   """..."""
# line fn_start+2..fn_start+5:  # FIX-CLEAR-ASK-RACE marker + with self._lock + try:
# lines fn_start+6..fn_start+12:  with self._lock (check) — already inside outer try
# line fn_start+13:  # BUG #21 — NOT re-indented, needs 4 spaces

# Identify the "body start" — first line after the outer try's `with self._lock:` block
# that needs re-indentation. This is the # BUG #21 comment line.
body_start = None
for i in range(fn_start + 1, fn_end):
    stripped = lines[i]
    # After the new outer try's `with self._lock:` block, the next line
    # that's NOT at the re-indented level is the body to re-indent.
    # The re-indented block is: 16 spaces (8 class + 4 try + 4 with)
    # The body to re-indent is at: 8 spaces (class level)
    # After re-indent it should be: 12 spaces (8 class + 4 try)
    
    # The first line inside the outer try AFTER the `with self._lock:` block
    # (which is at 16 spaces) — look for lines at 8 spaces that are not docstring/marker
    if i > fn_start + 12:  # After the marker + try + with blocks
        if stripped.startswith('        ') and not stripped.startswith('            '):
            if stripped.strip() and not stripped.strip().startswith('#'):
                body_start = i
                break
        elif stripped.startswith('        #') and i > fn_start + 12:
            body_start = i
            break

# More reliable: find the first line after the outer with block that is at 8-space indent
# The outer try structure is:
# line fn_start+2:         with self._lock:  (12 spaces)
# line fn_start+3:             self._active_loops...  (16 spaces)
# line fn_start+4:     try:  (12 spaces)
# line fn_start+5:         with self._lock:  (16 spaces)
# line fn_start+6:             if not self._running:  (20 spaces)
# ... 
# line fn_start+12:        return  (16 spaces)
# Next line is at 8 spaces: needs re-indentation

# Actually let me just find the line after the return in the with block
# The return is at 16 spaces (20 would be inside the if)
# After it, we have:
# line:             # BUG #21: Fire a turn-start... (8 spaces)
# line:         if self._on_text_delta:  (8 spaces)

# Let me just find the first line at 8 spaces after the function def
# that is NOT the docstring or the marker block
body_start = None
for i in range(fn_start + 1, fn_end):
    stripped = lines[i]
    # Skip docstring
    if i == fn_start + 1 and stripped.strip().startswith('"""'):
        continue
    if i == fn_start + 2 and stripped.strip().endswith('"""'):
        continue
    # Skip the FIX-CLEAR-ASK-RACE marker block (lines with 8 spaces)
    # These are:
    #         # FIX-CLEAR-ASK-RACE: ... (8 spaces)
    #         with self._lock: (8 spaces)
    #             self._active_loops... (12 spaces)
    #     try: (4 spaces)
    #         with self._lock: (8 spaces)
    #             if not self._running... (12 spaces)
    #                 return (16 spaces)
    #             conv = self._conversations... (12 spaces)
    #             if conv is None: (12 spaces)
    #                 self._dispatch... (16 spaces)
    #                 return (16 spaces)
    
    # The body to re-indent starts at the first line after this block
    # that is at 8-space indent and is NOT part of the marker setup.
    # Let me detect the end of the marker+try+with block by finding
    # the last line with 12+ spaces that's part of the setup.
    
    if body_start is None and i > fn_start + 3:
        # At this point we've passed the docstring
        # Look for the transition: we're at 8 spaces but the PREVIOUS line ended the with block
        prev = lines[i-1].rstrip()
        if stripped.startswith('        ') and not stripped.startswith('            '):
            if prev.strip() == 'return' and prev.startswith('                '):
                body_start = i
                break

print(f"Body start: line {body_start+1 if body_start else 'not found'}")
print(f"Lines around body_start: {repr(lines[body_start] if body_start else 'N/A')}")

# Actually, let me just take a different approach - find the exact lines
# Let me look at what the file looks like now
print("\n--- Current state of _run_loop ---")
for i in range(fn_start, min(fn_start + 20, fn_end)):
    print(f"{i+1:4d}: {lines[i].rstrip()}")