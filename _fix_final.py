#!/usr/bin/env python3
"""
Comprehensive transformation for FIX-CLEAR-ASK-RACE.
Reads clean baseline, applies all edits via text operations.
"""
import ast

def readfile(path):
    with open(path, 'r') as f:
        return f.read()

def writefile(path, text):
    with open(path, 'w') as f:
        f.write(text)

def check_ast(text, label):
    try:
        ast.parse(text)
        print(f"  OK: {label}")
    except SyntaxError as e:
        print(f"  FAIL: {label}: {e}")
        raise

# ═══════════════════ 1. agent/runtime.py ═════════════════════════════════

text = readfile('agent/runtime.py')

# === Edit 1: Add _active_loops to __init__ ===
OLD1 = '        self._running = False\n\n        # §E: Stuck detection'
NEW1 = '''        self._running = False

        # FIX-CLEAR-ASK-RACE: sessions with an in-flight _run_loop. Used by
        # is_loop_active() and maintained by _run_loop's try/finally.
        self._active_loops: set[str] = set()

        # §E: Stuck detection'''
assert OLD1 in text, "Edit 1 text not found"
text = text.replace(OLD1, NEW1, 1)

# === Edit 2: Restructure _run_loop ===
FN_DEF = '    def _run_loop(self, session_key: str, text: str) -> None:\n'
NEXT_DEF = '    def _dispatch_approval(self, session_key: str, tool_name: str, args: dict) -> bool | None:\n'

fn_start = text.index(FN_DEF)
fn_end = text.index(NEXT_DEF, fn_start)
fn_body = text[fn_start:fn_end]
lines = fn_body.splitlines(True)

# Original structure:
#  0: def _run_loop(...)
#  1: """..."""
#  2: with self._lock:
#  3:     if not self._running:
#  4:         return
#  5:     conv = ...
#  6:     if conv is None:
#  7:         ...
#  8:         return
#  9: (blank)
# 10: # BUG #21: ...
# ...body...
# N: self._dispatch(self._on_error, session_key, e)
# N+1: (blank)

assert lines[0] == FN_DEF
assert lines[2].strip() == 'with self._lock:'

# Find last content line
last_idx = len(lines) - 1
while last_idx > 0 and not lines[last_idx].strip():
    last_idx -= 1

# Build new function
n = []
n.append(lines[0])  # def
n.append(lines[1])  # docstring
# Marker + outer try
n.append('        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n')
n.append('        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n')
n.append('        # finally block at the end of this function.\n')
n.append('        with self._lock:\n')
n.append('            self._active_loops.add(session_key)\n')
n.append('        try:\n')
# Re-indent guard check (lines 2-8): +4 spaces, preserve trailing newline via lstrip
for i in range(2, 9):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    n.append(' ' * (indent + 4) + line.lstrip())  # lstrip keeps \n
# Re-indent body (lines 9 to last_idx)
for i in range(9, last_idx + 1):
    line = lines[i]
    if line.strip():
        indent = len(line) - len(line.lstrip())
        n.append(' ' * (indent + 4) + line.lstrip())  # lstrip keeps \n
    else:
        # Empty or whitespace-only line
        n.append('\n')
# Finally
n.append('        finally:\n')
n.append('            # FIX-CLEAR-ASK-RACE: always release the active-loop marker, even\n')
n.append("            # on exception or early return, so a crashed loop doesn't block\n")
n.append('            # /clear for this session permanently.\n')
n.append('            with self._lock:\n')
n.append('                self._active_loops.discard(session_key)\n')
# Trailing blank line
n.append('\n')

new_fn = ''.join(n)
text = text[:fn_start] + new_fn + text[fn_end:]
check_ast(text, "After Edit 2")

# === Edit 3: Add is_loop_active ===
insert_pos = text.index(NEXT_DEF, text.index(FN_DEF))
is_loop = '''    def is_loop_active(self, session_key: str) -> bool:
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
text = text[:insert_pos] + is_loop + text[insert_pos:]
check_ast(text, "After Edit 3")
writefile('agent/runtime.py', text)
print("  Done: agent/runtime.py")

# ═══════════════════ 2. agent_runtime_handler.py ═════════════════════════

text = readfile('ui/handlers/agent_runtime_handler.py')
OLD = '        conv = rt.get_conversation(session_key)\n        if conv is not None:\n            try:\n                conv.messages = []'
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
assert OLD in text, "Edit 4 text not found"
text = text.replace(OLD, NEW, 1)
check_ast(text, "After Edit 4")
writefile('ui/handlers/agent_runtime_handler.py', text)
print("  Done: agent_runtime_handler.py")

# ═══════════════════ 3. project_handler.py ═════════════════════════════════

text = readfile('ui/handlers/project_handler.py')
OLD = '''            return CommandResult(
                handled=True,
                response_text=f"Could not clear {agent_name}'s conversation.",
            )'''
NEW = '''            else:
                return CommandResult(
                    handled=True,
                    response_text=(
                        f"Could not clear {agent_name}: a tool loop is currently running. "
                        f"Wait for it to finish, then run /clear again."
                    ),
                )'''
assert OLD in text, "Edit 5 text not found"
text = text.replace(OLD, NEW, 1)
check_ast(text, "After Edit 5")
writefile('ui/handlers/project_handler.py', text)
print("  Done: project_handler.py")

print("\n=== ALL 5 EDITS COMPLETE ===")