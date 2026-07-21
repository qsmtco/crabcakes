#!/usr/bin/env python3
"""Transform _run_loop: add outer try/finally, re-indent body.

Original structure:
    def _run_loop(...):
        """..."""
        with self._lock:            # indent=8
            if not self._running:   # indent=12
                return
            conv = ...              # indent=12
            if conv is None:        # indent=12
                ...                 # indent=16
                return
                                    # blank
        # BUG #21: ...              # indent=8
        ...body...
        try:                        # indent=8
            ...body...
        except Exception as e:      # indent=8
            ...body...
        # last line: self._dispatch(...)  # indent=12

New structure:
    def _run_loop(...):
        """..."""
        # FIX-CLEAR-ASK-RACE: ...   # indent=8
        # ...
        # ...
        with self._lock:            # indent=8
            self._active_loops.add  # indent=12
        try:                        # indent=8
            with self._lock:        # indent=12 (was 8)
                if not...           # indent=16 (was 12)
                    return
                conv = ...          # indent=16 (was 12)
                if conv is None:    # indent=16 (was 12)
                    ...             # indent=20 (was 16)
                    return
                                    # blank
            # BUG #21: ...          # indent=12 (was 8)
            ...body...              # all +4
            try:                    # indent=12 (was 8)
                ...body...
            except Exception as e:  # indent=12 (was 8)
                ...body...
        finally:                    # indent=8
            with self._lock:        # indent=12
                self._active_loops  # indent=16
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

# Verify the original first 10 lines
print("=== Original first 8 lines of body ===")
for i in range(fn_start + 2, min(fn_start + 10, fn_end)):
    indent = len(lines[i]) - len(lines[i].lstrip())
    print(f"  line {i+1}: indent={indent:2d} | {lines[i].rstrip()}")

# The original `with self._lock:` block is lines fn_start+2 through fn_start+8
# This is the guard check. These 7 lines need to be replaced with:
#   3 lines of marker + 1 with + 1 add + 1 try + 7 re-indented lines

# The body to re-indent starts at fn_start+9 (blank line after the guard check)
# through fn_end-1 (last line of except block)

# Find the original `with self._lock:` block end (line fn_start+8 should be `return`)
# Let me verify
assert lines[fn_start + 2].strip() == 'with self._lock:', \
    f"Expected 'with self._lock:' at line {fn_start+3}, got {lines[fn_start+2].strip()}"

# The last line of the with block is the `return` at fn_start+8
# After that, fn_start+9 is blank, fn_start+10 is `# BUG #21`

# Build new lines
new_lines = []

# Part 1: Everything before the function
new_lines.extend(lines[:fn_start])

# Part 2: Function def and docstring (unchanged)
new_lines.append(lines[fn_start])
new_lines.append(lines[fn_start + 1])

# Part 3: FIX-CLEAR-ASK-RACE marker + new with block + outer try
new_lines.append("        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n")
new_lines.append("        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n")
new_lines.append("        # finally block at the end of this function.\n")
new_lines.append("        with self._lock:\n")
new_lines.append("            self._active_loops.add(session_key)\n")
new_lines.append("        try:\n")

# Part 4: Re-indented original guard check (lines fn_start+2 to fn_start+8)
# These were at indent 8/12/16, now need to be at indent 12/16/20
for i in range(fn_start + 2, fn_start + 9):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    new_indent = indent + 4
    new_lines.append(' ' * new_indent + line.lstrip() + ('\n' if not line.endswith('\n') else ''))

# Part 5: Re-indented body from fn_start+9 to fn_end-1
# fn_start+9 is the blank line (or the # BUG #21 line)
for i in range(fn_start + 9, fn_end - 1):
    line = lines[i]
    if line.strip():
        indent = len(line) - len(line.lstrip())
        new_indent = indent + 4
        new_lines.append(' ' * new_indent + line.lstrip() + ('\n' if not line.endswith('\n') else ''))
    else:
        # Blank line — keep as-is
        new_lines.append(line if line.endswith('\n') else line + '\n')

# Part 6: finally block
new_lines.append("        finally:\n")
new_lines.append("            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n")
new_lines.append("            # on exception or early return, so a crashed loop doesn't block\n")
new_lines.append("            # /clear for this session permanently.\n")
new_lines.append("            with self._lock:\n")
new_lines.append("                self._active_loops.discard(session_key)\n")

# Part 7: Blank line separator between functions
new_lines.append(lines[fn_end - 1] if lines[fn_end - 1].endswith('\n') else lines[fn_end - 1] + '\n')

# Part 8: Everything after the function
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
    import traceback
    traceback.print_exc()