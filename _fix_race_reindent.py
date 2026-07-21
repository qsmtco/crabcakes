#!/usr/bin/env python3
"""Transform _run_loop in agent/runtime.py to add outer try/finally.

1. Find _run_loop function boundaries
2. Replace the top: add marker + outer try, re-indent body
3. Replace the bottom: add finally
4. Write back
"""

with open('agent/runtime.py', 'r') as f:
    content = f.read()
    lines = content.splitlines(keepends=True)

# Find _run_loop
fn_start = None
fn_end = None
for i, line in enumerate(lines):
    stripped = line.strip()
    if fn_start is None and stripped.startswith('def _run_loop('):
        fn_start = i
        continue
    if fn_start is not None and i > fn_start + 1:
        # Next method definition at class level (8 spaces)
        if stripped.startswith('def ') and line.startswith('    '):
            fn_end = i
            break

if fn_end is None:
    fn_end = len(lines)

print(f"_run_loop: lines {fn_start+1} to {fn_end}")

# The function currently starts like:
# line fn_start:     def _run_loop(self, session_key: str, text: str) -> None:
# line fn_start+1:   """Background thread: ..."""
# line fn_start+2:   with self._lock:
# ...
# line fn_start+6:   return
# line fn_start+7:   # BUG #21: Fire a turn-start signal...
# ...
# line fn_end-1:     self._dispatch(self._on_error, session_key, e)
# line fn_end:       (next def or end of file)

# The function body is everything from fn_start+1 (docstring) to fn_end-1.
# The current structure:
#   def _run_loop(...):
#       """..."""
#       with self._lock:           # 8-space indent
#           if not self._running:  # 12-space
#               return
#           conv = ...
#           if conv is None:
#               ...
#               return
#       
#       # BUG #21: ...              # 8-space
#       if self._on_text_delta:     # 8-space
#           ...
#       
#       try:                         # 8-space
#           ...
#       except Exception as e:      # 8-space
#           ...
#       (no finally)

# New structure:
#   def _run_loop(...):
#       """..."""
#       with self._lock:             # 8-space
#           self._active_loops.add(session_key)  # 12-space
#       try:                         # 8-space
#           with self._lock:         # 12-space
#               if not self._running:  # 16-space
#                   return
#               conv = ...
#               if conv is None:
#                   ...
#                   return
#           
#           # BUG #21: ...            # 12-space
#           if self._on_text_delta:   # 12-space
#               ...
#           
#           try:                     # 12-space
#               ...
#           except Exception as e:  # 12-space
#               ...
#       finally:                     # 8-space
#           with self._lock:         # 12-space
#               self._active_loops.discard(session_key)  # 16-space

# The tricky part: the original body is at 8-space indent (class method level).
# After the new structure, the body (except the first `with self._lock:` block)
# must be at 12-space indent (inside the outer try).

# Let me identify the transition point:
# The first `with self._lock:` block (lines fn_start+2 to fn_start+6) stays at
# 8-space indent but gets a new body (self._active_loops.add instead of the old checks).
# Everything from line fn_start+7 onward needs +4 spaces.

# Show the current function
print("=== Current function (first 15 lines) ===")
for i in range(fn_start, min(fn_start + 15, fn_end)):
    print(f"{i:4d}: {lines[i].rstrip()}")
print("=== Current function (last 10 lines) ===")
for i in range(max(fn_start, fn_end - 10), fn_end):
    print(f"{i:4d}: {lines[i].rstrip()}")

# Build new lines
new_lines = lines[:fn_start]  # Everything before _run_loop

# Line 1: function def
new_lines.append(lines[fn_start])

# Line 2: docstring (unchanged)
new_lines.append(lines[fn_start + 1])

# Line 3-5: FIX-CLEAR-ASK-RACE marker + with self._lock + add
# The old line fn_start+2 was: "        with self._lock:"
# We keep that pattern but change what's inside
new_lines.append("        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n")
new_lines.append("        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n")
new_lines.append("        # finally block at the end of this function.\n")
new_lines.append("        with self._lock:\n")
new_lines.append("            self._active_loops.add(session_key)\n")
new_lines.append("        try:\n")

# Now re-indent the original body (everything from fn_start+2 to fn_end)
# The original body starts at 8-space indent. We need to add 4 spaces to each line.
# But we skip the first `with self._lock:` block (lines fn_start+2 to fn_start+6)
# because we've already replaced it with the marker + new with block.

# Find where the original body starts after the first `with self._lock:` block.
# The original body is: lines[fn_start+2] to lines[fn_end-1] (inclusive)
# But we've already replaced lines fn_start+2 through fn_start+6 with the marker.
# So we need to re-indent lines fn_start+7 through fn_end-1 (the original body after the lock check).

# Actually, let me re-think. The original function body is:
# fn_start+2:         with self._lock:          (8 spaces)
# fn_start+3:             if not self._running: (12 spaces)
# fn_start+4:                 return            (16 spaces)
# fn_start+5:             conv = ...            (12 spaces)
# fn_start+6:             if conv is None:      (12 spaces)
# fn_start+7:                 self._dispatch... (16 spaces)
# fn_start+8:                 return            (16 spaces)
# fn_start+9:                                   (blank)
# fn_start+10:        # BUG #21: ...            (8 spaces)
# ...

# After our edit:
# fn_start+2:         # FIX-CLEAR-ASK-RACE: ... (8)
# fn_start+3:         # ...                      (8)
# fn_start+4:         # ...                      (8)
# fn_start+5:         with self._lock:           (8)
# fn_start+6:             self._active_loops...  (12)
# fn_start+7:         try:                       (8)
# fn_start+8:             with self._lock:       (12)
# fn_start+9:                 if not...          (16)
# fn_start+10:                return            (16)
# fn_start+11:            conv = ...             (12)
# fn_start+12:            if conv is None:       (12)
# fn_start+13:                self._dispatch... (16)
# fn_start+14:                return            (16)
# fn_start+15:                                   (blank)
# fn_start+16:        # BUG #21: ...            (8) -- needs +4 to 12

# Wait, the original fn_start+2 through fn_start+8 is the old `with self._lock:` block.
# fn_start+9 is a blank line, and fn_start+10 is the # BUG #21 comment at 8 spaces.
# So the body to re-indent starts at fn_start+9 (the blank line) or fn_start+10.

# Let me get the actual line numbers
print("\n=== Detailed line analysis ===")
for i in range(fn_start, min(fn_start + 15, fn_end)):
    indent = len(lines[i]) - len(lines[i].lstrip())
    print(f"{i:4d}: indent={indent} | {lines[i].rstrip()}")