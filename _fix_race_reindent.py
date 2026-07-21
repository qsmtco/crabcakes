#!/usr/bin/env python3
"""Fix the indentation of the _run_loop function body and add is_loop_active.

The current state has the marker + outer try + re-indented guard check,
but the `# BUG #21` comment at line 1185 is at 16 spaces (inside the
with block) instead of 12 spaces (inside the outer try).

This is because the first edit_file only replaced the function header
up to the first `# BUG #21` line, but the continuation lines were
not re-indented.

Fix: read the function, re-indent the body correctly, add is_loop_active.
"""

with open('agent/runtime.py', 'r') as f:
    lines = f.readlines()

# Find _run_loop
fn_start = None
fn_end = None
for i, line in enumerate(lines):
    stripped = line.strip()
    if fn_start is None and stripped.startswith('def _run_loop('):
        fn_start = i
    if fn_start is not None and i > fn_start + 1:
        if stripped.startswith('def ') and line.startswith('    '):
            fn_end = i
            break

if fn_end is None:
    fn_end = len(lines)

print(f"_run_loop: lines {fn_start+1} to {fn_end}")

# The current function structure:
# Line 0 (fn_start):     def _run_loop(...):  indent=4
# Line 1:                """..."""            indent=8
# Line 2:                # FIX-CLEAR-ASK-RACE  indent=8 -- marker
# Line 3:                # ...                 indent=8
# Line 4:                # ...                 indent=8
# Line 5:                with self._lock:     indent=8 -- marker add
# Line 6:                    self._active_loops.add  indent=12
# Line 7:                try:                 indent=8 -- outer try
# Line 8:                    with self._lock: indent=12 -- guard check
# Line 9:                        if not...   indent=16
# Line 10:                           return  indent=20
# Line 11:                       conv = ...  indent=16
# Line 12:                       if conv...  indent=16
# Line 13:                           self._dispatch... indent=20
# Line 14:                           return  indent=20
# Line 15: (blank)
# Line 16:                   # BUG #21: ...  indent=16 -- WRONG, should be 12
# Line 17:                    # This guarantees... indent=12 -- CORRECT
# ...body at indent=12 (correct)
# ...inner try/except at indent=12 (correct)
# Line N-1: ...dispatch(e)  indent=16 (inside the exception handler)
# Line N:   finally:       indent=8 -- from the partial script run
# Line N+1: # FIX-CLEAR-ASK-RACE... indent=12
# Line N+2: with self._lock: indent=12
# Line N+3:     self._active_loops.discard indent=16
# Line N+4: (blank)
# Line N+5: def _dispatch_approval...

# The issue: the `# BUG #21` line (line 16) is at 16 spaces (inside the with block)
# but should be at 12 spaces (inside the outer try, outside the with block).
# This is because the edit_file replaced the old `with self._lock:` block with
# the new marker + try + re-indented guard check, but the `# BUG #21` line at
# 8 spaces in the old file became 12 spaces in the new text (inside the outer try).
# However, the continuation lines were at 8 spaces in the original and were NOT
# part of the match, so they stayed at 8 spaces. Then... something moved them to 12.

# Let me look at the actual structure
print("=== Current function structure ===")
for i in range(fn_start, fn_end):
    indent = len(lines[i]) - len(lines[i].lstrip())
    print(f"{i+1:4d}: indent={indent:2d} | {lines[i].rstrip()}")

# The actual issue seems to be:
# 1. The `# BUG #21` line is at 16 spaces (inside the with block) 
# 2. It should be at 12 spaces (inside the outer try, after the with block)
# 
# This is because the old_text had `# BUG #21` at 8 spaces, and the new_text
# had it at 12 spaces. But the edit_file inserted it INSIDE the with block
# (after the `return` at 20 spaces, with the `# BUG #21` at 16 spaces).
# 
# Wait, no. The edit_file's new_text has:
#         try:
#             with self._lock:
#                 if not self._running:
#                     return
#                 conv = ...
#                 if conv is None:
#                     self._dispatch(...)
#                     return
# 
#         # BUG #21: ...
# 
# The `# BUG #21` line is at 12 spaces (inside the outer try, after the with block).
# But the sed output shows it at 16 spaces. That doesn't match.
# 
# Unless the edit_file's match didn't include the `return` at the end of the
# with block, and the `# BUG #21` line ended up inside the with block.

# I think the issue is clearer now. Let me just fix it by replacing the
# specific lines that are wrong.