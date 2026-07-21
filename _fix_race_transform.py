#!/usr/bin/env python3
"""
Full transformation for FIX-CLEAR-ASK-RACE.

Reads all 3 files, transforms them, writes them back.
Handles the _run_loop re-indentation correctly.
"""
import ast

# ── 1. Read agent/runtime.py ──────────────────────────────────────────────────

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

# Original structure of the function body:
#   fn_start+0:  def _run_loop(...):        indent=4
#   fn_start+1:  """..."""                   indent=8
#   fn_start+2:  with self._lock:           indent=8  -- guard check
#   fn_start+3:      if not self._running:  indent=12
#   fn_start+4:          return             indent=16
#   fn_start+5:      conv = ...             indent=12
#   fn_start+6:      if conv is None:       indent=12
#   fn_start+7:          self._dispatch(...) indent=16
#   fn_start+8:          return             indent=16
#   fn_start+9:  (blank)                    indent=0
#   fn_start+10: # BUG #21: ...             indent=8  -- body starts
#   ...all body at indent=8 (8, 12, 16...)
#   fn_end-2:  body's last content line
#   fn_end-1:  (blank)

# Show the boundaries
print(f"  fn_start+2: {lines[fn_start+2].rstrip()}")
print(f"  fn_start+8: {lines[fn_start+8].rstrip()}")
print(f"  fn_start+9: {repr(lines[fn_start+9])}")
print(f"  fn_start+10: {lines[fn_start+10].rstrip()}")

# Find the last content line of the function
last_content = fn_end - 1
while last_content > fn_start:
    if lines[last_content].strip():
        break
    last_content -= 1

print(f"  last_content idx: {last_content}: {lines[last_content].rstrip()}")

# ── 2. Build new _run_loop ────────────────────────────────────────────────────

new_lines = []

# Before the function
new_lines.extend(lines[:fn_start])

# Def line + docstring (unchanged)
new_lines.append(lines[fn_start])
new_lines.append(lines[fn_start + 1])

# Marker block
new_lines.append('        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n')
new_lines.append('        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n')
new_lines.append('        # finally block at the end of this function.\n')
new_lines.append('        with self._lock:\n')
new_lines.append('            self._active_loops.add(session_key)\n')
new_lines.append('        try:\n')

# Re-indented guard check: lines fn_start+2 through fn_start+8
# These were at indent 8/12/16, now need to be at 12/16/20
for i in range(fn_start + 2, fn_start + 9):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    new_indent = indent + 4
    new_lines.append(' ' * new_indent + line.lstrip() + '\n')

# Re-indented body: lines fn_start+9 through last_content (inclusive)
# fn_start+9 is typically a blank line, keep it as-is
# Others get +4 spaces
for i in range(fn_start + 9, last_content + 1):
    line = lines[i]
    if line.strip():
        indent = len(line) - len(line.lstrip())
        new_indent = indent + 4
        new_lines.append(' ' * new_indent + line.lstrip() + '\n')
    else:
        # Empty line
        new_lines.append('\n')

# Finally block
new_lines.append('        finally:\n')
new_lines.append('            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n')
new_lines.append("            # on exception or early return, so a crashed loop doesn't block\n")
new_lines.append('            # /clear for this session permanently.\n')
new_lines.append('            with self._lock:\n')
new_lines.append('                self._active_loops.discard(session_key)\n')

# Trailing blank line
new_lines.append('\n')

# Everything after the function
new_lines.extend(lines[fn_end:])

# ── 3. Add is_loop_active() method ────────────────────────────────────────────

# Find the end of _dispatch_approval
# We need to find where to insert is_loop_active.
# It should go right after _run_loop ends (before _dispatch_approval).
# Let me find _dispatch_approval's start in the new text
new_text = ''.join(new_lines)

# The is_loop_active method should be inserted after the blank line that
# follows _run_loop's finally block, and before _dispatch_approval.
# Find _dispatch_approval
NEXT_SENTINEL = '    def _dispatch_approval(self, session_key: str, tool_name: str, args: dict) -> bool | None:\n'
insert_pos = new_text.index(NEXT_SENTINEL)

is_loop_active_code = '''    def is_loop_active(self, session_key: str) -> bool:
        """Return True if a _run_loop thread is currently active for this session.

        FIX-CLEAR-ASK-RACE: used by AgentRuntimeHandler.clear_conversation() to
        refuse wiping a conversation that an in-flight loop is still reading.
        Thread-safe via _lock. A session marked active stays active until the
        loop's finally block discards it — including through exceptions and
        early returns, so a crashed loop cannot permanently block /clear.
        """
        with self._lock:
            return session_key in self._active_loops


'''

new_text = new_text[:insert_pos] + is_loop_active_code + new_text[insert_pos:]

# ── 4. Add _active_loops to __init__ ─────────────────────────────────────────

# Find the __init__ where _running = False
RUNNING_SENTINEL = '        self._running = False\n'
running_pos = new_text.index(RUNNING_SENTINEL)
running_end = running_pos + len(RUNNING_SENTINEL)

active_loops_init = '''        # FIX-CLEAR-ASK-RACE: sessions with an in-flight _run_loop. Used by
        # is_loop_active() and maintained by _run_loop's try/finally.
        self._active_loops: set[str] = set()

'''
new_text = new_text[:running_end] + active_loops_init + new_text[running_end:]

# ── 5. Write agent/runtime.py ─────────────────────────────────────────────────

# Verify ast.parse
try:
    ast.parse(new_text)
    print("✅ runtime.py: ast.parse OK")
except SyntaxError as e:
    print(f"❌ runtime.py: {e}")
    # Show problematic area
    test_lines = new_text.splitlines(True)
    if e.lineno:
        for i in range(max(0, e.lineno-3), min(len(test_lines), e.lineno+3)):
            marker = ' >>>' if i == e.lineno - 1 else '    '
            print(f'{marker} {i+1}: {test_lines[i].rstrip()}')
    # Don't write, let's debug
    raise

with open('agent/runtime.py', 'w') as f:
    f.write(new_text)
print("✅ agent/runtime.py written")

# ── 6. Read and transform agent_runtime_handler.py ────────────────────────────

with open('ui/handlers/agent_runtime_handler.py', 'r') as f:
    text = f.read()

# Find the guard check block in clear_conversation
# The line before conv = rt.get_conversation(session_key) is blank
# We need to insert the guard before it
OLD = '        conv = rt.get_conversation(session_key)\n        if conv is not None:\n            try:\n                conv.messages = []'

if OLD in text:
    NEW = '''        # FIX-CLEAR-ASK-RACE: refuse to wipe a conversation that an in-flight
        # _run_loop is actively reading. The /clear + /ask pairing rule can
        # fire /clear while the /ask thread is between add_user_message and
        # to_api_messages; wiping conv.messages at that instant produces a
        # system-only payload that MiniMax rejects (status_code=2013). Refuse
        # instead; the user can retry /clear once the loop finishes.
        if rt.is_loop_active(session_key):
            logger.warning(
                "clear_conversation: refusing reset for %s — tool loop is active; retry after it completes",
                session_key,
            )
            return False

        conv = rt.get_conversation(session_key)
        if conv is not None:
            try:
                conv.messages = []'''
    text = text.replace(OLD, NEW, 1)
    print("✅ agent_runtime_handler.py: guard added")
else:
    print("❌ agent_runtime_handler.py: pattern not found")

with open('ui/handlers/agent_runtime_handler.py', 'w') as f:
    f.write(text)

# Verify ast.parse
try:
    ast.parse(text)
    print("✅ agent_runtime_handler.py: ast.parse OK")
except SyntaxError as e:
    print(f"❌ agent_runtime_handler.py: {e}")

# ── 7. Read and transform project_handler.py ──────────────────────────────────

with open('ui/handlers/project_handler.py', 'r') as f:
    text = f.read()

# Find the cmd_clear's if ok: block
# The current structure:
#             if ok:
#                 # UI side effect...
#                 ...
#                 return CommandResult(...)
#             return CommandResult(
#                 handled=True,
#                 response_text=f"Could not clear {agent_name}'s conversation.",
#             )

# We need to replace the else branch with a specific message
OLD = '''            return CommandResult(
                handled=True,
                response_text=f"Could not clear {agent_name}'s conversation.",
            )'''

if OLD in text:
    NEW = '''            else:
                return CommandResult(
                    handled=True,
                    response_text=(
                        f"Could not clear {agent_name}: a tool loop is currently running. "
                        f"Wait for it to finish, then run /clear again."
                    ),
                )'''
    text = text.replace(OLD, NEW, 1)
    print("✅ project_handler.py: else branch added with refusal message")
else:
    print("❌ project_handler.py: old pattern not found, trying to find alternatives")
    # Search for what's actually there
    idx = text.find('return CommandResult(')
    if idx >= 0:
        snippet = text[idx:idx+200]
        print(f"  Found: {repr(snippet[:100])}")

with open('ui/handlers/project_handler.py', 'w') as f:
    f.write(text)

# Verify ast.parse
try:
    ast.parse(text)
    print("✅ project_handler.py: ast.parse OK")
except SyntaxError as e:
    print(f"❌ project_handler.py: {e}")

print("\n=== ALL DONE ===")