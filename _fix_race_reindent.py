#!/usr/bin/env python3
"""Transform _run_loop: add outer try/finally, re-indent body.

Reads the current function, builds the new version, replaces it.
"""

with open('agent/runtime.py', 'r') as f:
    text = f.read()

# Find _run_loop boundaries
FN_SENTINEL = '    def _run_loop(self, session_key: str, text: str) -> None:\n'
NEXT_FN_SENTINEL = '    def _dispatch_approval('

fn_start = text.index(FN_SENTINEL)
fn_end = text.index(NEXT_FN_SENTINEL, fn_start)

print(f"_run_loop: chars {fn_start} to {fn_end}")

# Extract the function body (the part after the def line + docstring)
fn_body = text[fn_start:fn_end]

# The old function structure:
# line 0:  def _run_loop(...):
# line 1:  """..."""
# line 2:  with self._lock:
# ...
# line 8:  return
# line 9:  (blank)
# line 10: # BUG #21: ...
# ...
# line N:  self._dispatch(self._on_error, session_key, e)
# line N+1: (blank, trailing newline)

lines = fn_body.splitlines(True)

# Verify structure
assert lines[0] == FN_SENTINEL, f'Expected function def, got {lines[0]!r}'
assert lines[1].strip().startswith('"""'), f'Expected docstring, got {lines[1]!r}'
assert lines[2].strip() == 'with self._lock:', f'Expected with self._lock at line 2, got {lines[2]!r}'

# The original `with self._lock:` block is lines 2-8
# Line 2:         with self._lock:
# Line 3:             if not self._running:
# Line 4:                 return
# Line 5:             conv = ...
# Line 6:             if conv is None:
# Line 7:                 self._dispatch(...)
# Line 8:                 return
# Line 9: blank

# Build new function
new_lines = []

# Line 0: function def (unchanged)
new_lines.append(lines[0])

# Line 1: docstring (unchanged)
new_lines.append(lines[1])

# FIX-CLEAR-ASK-RACE marker block
new_lines.append('        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n')
new_lines.append('        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n')
new_lines.append('        # finally block at the end of this function.\n')
new_lines.append('        with self._lock:\n')
new_lines.append('            self._active_loops.add(session_key)\n')
new_lines.append('        try:\n')

# Re-indented original guard check (lines 2-8): add 4 spaces
for i in range(2, 9):
    old = lines[i]
    indent = len(old) - len(old.lstrip())
    stripped = old.lstrip()
    new_lines.append(' ' * (indent + 4) + stripped)

# Re-indented body: lines 9 through N-1 (the blank line is the last)
# N is the last line index (fn_end - fn_start - 1 is the trailing newline/blank)
# The last content line is N-1 or N-2
# Let me find the last line before the trailing blank
last_content_idx = len(lines) - 1
while last_content_idx >= 0:
    if lines[last_content_idx].strip():
        break
    last_content_idx -= 1

print(f'Last content line index: {last_content_idx}')
print(f'Last content: {lines[last_content_idx].rstrip()}')

# Body is lines 9 through last_content_idx (inclusive)
for i in range(9, last_content_idx + 1):
    old = lines[i]
    if old.strip():
        indent = len(old) - len(old.lstrip())
        stripped = old.lstrip()
        new_lines.append(' ' * (indent + 4) + stripped)
    else:
        # Blank line — keep as-is but ensure it ends with newline
        stripped = old.rstrip('\n')
        new_lines.append(stripped + '\n')

# Finally block
new_lines.append('        finally:\n')
new_lines.append('            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n')
new_lines.append('            # on exception or early return, so a crashed loop doesn\'t block\n')
new_lines.append('            # /clear for this session permanently.\n')
new_lines.append('            with self._lock:\n')
new_lines.append('                self._active_loops.discard(session_key)\n')

# Trailing blank line (the one between functions)
# The original trailing blank line was at the end of the function body
# We need to add it back
new_lines.append('\n')

new_fn_body = ''.join(new_lines)

# Replace in text
new_text = text[:fn_start] + new_fn_body + text[fn_end:]

with open('agent/runtime.py', 'w') as f:
    f.write(new_text)

print('Done writing.')

# Verify
import ast
try:
    ast.parse(new_text)
    print('OK: ast.parse passes')
except SyntaxError as e:
    print(f'FAIL: {e}')
    # Show the problematic area
    lines = new_text.splitlines(True)
    lineno = e.lineno
    if lineno:
        for i in range(max(0, lineno-5), min(len(lines), lineno+5)):
            marker = ' >>>' if i == lineno - 1 else '    '
            print(f'{marker} {i+1}: {lines[i].rstrip()}')