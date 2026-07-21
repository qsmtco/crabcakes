#!/usr/bin/env python3
"""Re-indent _run_loop body and add finally block.

The file currently has:
- _active_loops in __init__ (line 732) ✓
- marker + outer try at top of _run_loop (lines 1170-1175) ✓
- BUT the body from line 1183 onward is NOT re-indented (still at 8 spaces)
- The existing inner try/except at bottom lacks a finally

This script re-indents lines 1183-1660 (the body after the outer with block)
by adding 4 spaces to each line, then adds the finally block.
"""

with open('agent/runtime.py', 'r') as f:
    content = f.read()
    lines = content.splitlines(keepends=True)

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

# The function currently has:
# Line fn_start:     def _run_loop(...):  (indent=4)
# Line fn_start+1:   """..."""            (indent=8)
# Line fn_start+2:   # FIX-CLEAR-ASK-RACE (indent=8)  -- marker
# Line fn_start+3:   # ...                (indent=8)
# Line fn_start+4:   # ...                (indent=8)
# Line fn_start+5:   with self._lock:    (indent=8)  -- new add marker
# Line fn_start+6:       self._active_loops... (indent=12)
# Line fn_start+7:   try:                (indent=8)  -- outer try
# Line fn_start+8:       with self._lock: (indent=12) -- outer with check
# Line fn_start+9:           if not...   (indent=16)
# Line fn_start+10:              return  (indent=20)
# Line fn_start+11:          conv = ...  (indent=16)
# Line fn_start+12:          if conv...  (indent=16)
# Line fn_start+13:              self._dispatch... (indent=20)
# Line fn_start+14:              return  (indent=20)
# Line fn_start+15:                     (blank, indent=8 or 0)
# Line fn_start+16:  # BUG #21: ...      (indent=8)  -- NEEDS +4
# ...all subsequent lines at indent=8 -- NEED +4

# The "body start" is the first line after the outer `with self._lock:` block
# that closes. The last line of the outer with block is the `return` at line fn_start+14
# (indent=20, inside `if conv is None:`). After that, line fn_start+15 is blank,
# and line fn_start+16 is `# BUG #21` at indent=8 -- this needs +4.

# Let me find the exact body start
behind_outer_with = False
body_start = None
for i in range(fn_start + 2, fn_end):
    indent = len(lines[i]) - len(lines[i].lstrip())
    # We're looking for the first line at 8-space indent that comes AFTER
    # the outer with self._lock: and its inner return
    if indent < 8 and i > fn_start + 2:
        # This is a blank line or comment at 0 spaces
        pass
    if lines[i].strip() == 'return' and indent == 20:
        # This is the last line of the `if conv is None:` block
        behind_outer_with = True
        continue
    if behind_outer_with and i > fn_start + 14:
        # After the last return of the outer with block
        if indent <= 8 or lines[i].strip() == '':
            body_start = i
            break

# If we didn't find it, just use fn_start + 14 as approximate
if body_start is None:
    body_start = fn_start + 15
    print(f"WARNING: using estimated body_start at line {body_start+1}")

print(f"Body start: line {body_start+1}")
print(f"  content: {lines[body_start].rstrip()}")

# NEW LINES: build from parts
new_lines = []

# Part 1: Before body start (lines 0 to body_start-1, unchanged)
new_lines.extend(lines[:body_start])

# Part 2: Body re-indented (+4 spaces)
# This is lines[body_start] to lines[fn_end-1] (excluding the final blank line)
# The last line of _run_loop is self._dispatch(self._on_error, session_key, e)
# The blank line after it is part of the function

# Find the last line of the existing except block
# It's: "            self._dispatch(self._on_error, session_key, e)" (indent=12)
# This is the last line before fn_end (which is the next def)

# Actually, the existing except block is at indent=8 (class method level)
# After re-indent it should be at indent=12 (inside outer try)
# Then we add finally at indent=8 (outer try level)

# Find the last non-blank line of the function
last_content = None
for i in range(fn_end - 1, body_start - 1, -1):
    if lines[i].strip():
        last_content = i
        break

print(f"Last content line: {last_content+1}")

# The existing except block ends at line last_content.
# The blank line at fn_end-1 is the function separator.
# We need to re-indent everything from body_start to last_content (inclusive)
# by adding 4 spaces to each non-empty line (empty lines stay empty).

for i in range(body_start, last_content + 1):
    line = lines[i]
    if line.strip():
        # Add 4 spaces. But we need to handle the case where the line
        # already has some indentation (it's at 8 spaces for the body,
        # 12 for the with block, 16 for inner if, etc.)
        # Actually, the original body was at 8-space indent for class method level.
        # After re-indent, it should be at 12-space (inside outer try).
        # Lines that were at 8 spaces move to 12.
        # Lines that were at 12 spaces move to 16.
        # Lines that were at 16 spaces move to 20.
        # etc.
        indent = len(line) - len(line.lstrip())
        new_indent = indent + 4
        new_lines.append(' ' * new_indent + line.lstrip())
    else:
        # Empty line - keep as is
        new_lines.append(line)

# Now add the finally block
new_lines.append("        finally:\n")
new_lines.append("            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n")
new_lines.append("            # on exception or early return, so a crashed loop doesn't block\n")
new_lines.append("            # /clear for this session permanently.\n")
new_lines.append("            with self._lock:\n")
new_lines.append("                self._active_loops.discard(session_key)\n")

# Add the blank line separator that was between _run_loop and _dispatch_approval
# (it was at fn_end - 1, which we already included in the re-indented block)
# The blank line at the end of the function is the last line of the re-indented block
# We need to add it back if it was consumed
# Actually, the blank line separator is between the old except block and the next def.
# Our re-indented block goes up to last_content (the old except's last line).
# The blank line separator was at fn_end - 1 (a blank line before the next def).
# Let me check if we already included it.

# The blank line between functions:
# lines[fn_end - 1] is the blank line before the next def
# We should NOT re-indent this blank line (it should stay as-is)
# It's already part of the unmodified lines before the next def.

# Actually, let me look at what's after the function:
# The next def starts at fn_end. fn_end - 1 is the blank line.
# Since our loop goes from body_start to last_content (inclusive),
# and last_content is the last line of the except block,
# the blank line at fn_end-1 is NOT included in the re-indented block.
# But wait, we need to make sure it's there.

# After the new_lines, we need to add:
# Part 3: The blank line separator (if any)
# Part 4: Everything from fn_end to end of file

# The blank line at fn_end - 1 was NOT included in our re-indent (since we
# only went up to last_content, and last_content is before fn_end - 1).
# But we also need to handle the case where fn_end - 1 == last_content + 1
# (i.e., there's a blank line between the except block and the next def).

# Let me check: is fn_end - 1 a blank line?
if fn_end - 1 > last_content:
    print(f"Blank line at {fn_end}: {repr(lines[fn_end - 1])}")
    # The blank line is between last_content and fn_end
    # It was NOT included in our re-indent, so we need to add it
    new_lines.append(lines[fn_end - 1])

# Part 3: Everything from fn_end to end of file
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