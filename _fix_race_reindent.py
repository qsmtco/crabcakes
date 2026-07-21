#!/usr/bin/env python3
"""Replace _run_loop with outer try/finally and re-indent body.

Strategy:
1. Extract the original body (lines after the initial `with self._lock:` block)
2. Add 4 spaces to each line
3. Build the new function with marker, outer try, re-indented body, finally
4. Write back
"""

with open('agent/runtime.py', 'r') as f:
    lines = f.readlines()

# Find _run_loop boundaries
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

# The original function is:
# line fn_start:   def _run_loop(...
# line fn_start+1: """..."""
# line fn_start+2: with self._lock:    (8 spaces)
# line fn_start+3:     if not...       (12 spaces)
# line fn_start+4:         return      (16 spaces)
# line fn_start+5:     conv = ...      (12 spaces)
# line fn_start+6:     if conv is...   (12 spaces)
# line fn_start+7:         self._dispatch... (16 spaces)
# line fn_start+8:         return      (16 spaces)
# line fn_start+9: (blank)
# line fn_start+10: # BUG #21: ...     (8 spaces)
# ...
# line fn_end-1:    self._dispatch(...)  (12 spaces)
# line fn_end-1: (blank)
# line fn_end:     def _dispatch_approval(...

# The body to re-indent: everything from fn_start+2 (the original `with self._lock:`)
# to fn_end-1 (the last line of the function body, which is the except block's dispatch).
# We need to:
# 1. Replace fn_start+2 through fn_start+8 with the new marker + outer try + re-indented with block
# 2. Re-indent fn_start+9 through fn_end-1 by +4 spaces
# 3. Add finally block

# Find the original `with self._lock:` block boundaries
# The original with block starts at fn_start+2 and ends at fn_start+8 (the last return)
# Let me verify
print(f"fn_start+2: {lines[fn_start+2].rstrip()}")
print(f"fn_start+8: {lines[fn_start+8].rstrip()}")

# The original `with self._lock:` block (lines fn_start+2 through fn_start+8):
# This is the initial guard check. We need to replace it with the marker + outer try
# + re-indented guard check.

# The body to re-indent (lines fn_start+9 through fn_end-1):
# These are the lines after the initial guard check, at 8-space indent.
# We need to re-indent them to 12 spaces (inside the outer try).

# Build new function
new_lines = []

# Part 1: Everything before the function
new_lines.extend(lines[:fn_start])

# Part 2: Function def and docstring
new_lines.append(lines[fn_start])        # def _run_loop
new_lines.append(lines[fn_start + 1])    # docstring

# Part 3: Marker + outer try + re-indented guard check
new_lines.append("        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n")
new_lines.append("        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n")
new_lines.append("        # finally block at the end of this function.\n")
new_lines.append("        with self._lock:\n")
new_lines.append("            self._active_loops.add(session_key)\n")
new_lines.append("        try:\n")

# The original guard check was at lines fn_start+2 through fn_start+8.
# It was indented at 8/12/16 spaces. We need it at 12/16/20 spaces (inside outer try).
for i in range(fn_start + 2, fn_start + 9):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    new_indent = indent + 4
    new_lines.append(' ' * new_indent + line.lstrip())

# Part 4: Body after the guard check, re-indented by +4 spaces
# Lines fn_start+9 through fn_end-1
for i in range(fn_start + 9, fn_end - 1):
    line = lines[i]
    if line.strip():
        indent = len(line) - len(line.lstrip())
        new_indent = indent + 4
        new_lines.append(' ' * new_indent + line.lstrip())
    else:
        # Empty line — keep as-is (blank line separator)
        new_lines.append(line)

# Part 5: Finally block
new_lines.append("        finally:\n")
new_lines.append("            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n")
new_lines.append("            # on exception or early return, so a crashed loop doesn't block\n")
new_lines.append("            # /clear for this session permanently.\n")
new_lines.append("            with self._lock:\n")
new_lines.append("                self._active_loops.discard(session_key)\n")

# Part 6: Blank line separator
new_lines.append(lines[fn_end - 1])  # the blank line before next def

# Part 7: Everything after the function
new_lines.extend(lines[fn_end:])

# Write back
with open('agent/runtime.py', 'w') as f:
    f.writelines(new_lines)

print("Done writing.")

# Verify
import ast
try:
    ast.parse(open('agent/runtime.py').read())
    print("✅ ast.parse OK")
except SyntaxError as e:
    print(f"❌ SyntaxError: {e}")
    # Show the problematic area
    import traceback
    traceback.print_exc()