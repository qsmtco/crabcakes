#!/usr/bin/env python3
"""
Comprehensive transformation for FIX-CLEAR-ASK-RACE.

Reads the clean baseline, applies all replacements via text operations.
No re-indentation needed — we build the new function from scratch.
"""
import ast

# ── Helper: read file ─────────────────────────────────────────────────────────

def readfile(path):
    with open(path, 'r') as f:
        return f.read()

def writefile(path, text):
    with open(path, 'w') as f:
        f.write(text)

def check_ast(text, label):
    try:
        ast.parse(text)
        print(f"  ✅ {label}: ast.parse OK")
    except SyntaxError as e:
        print(f"  ❌ {label}: {e}")
        lines = text.splitlines(True)
        if e.lineno:
            for i in range(max(0, e.lineno-3), min(len(lines), e.lineno+3)):
                marker = ' >>>' if i == e.lineno - 1 else '    '
                print(f'{marker} {i+1}: {lines[i].rstrip()}')

# ── 1. Agent/runtime.py ───────────────────────────────────────────────────────

text = readfile('agent/runtime.py')

# === Edit 1: Add _active_loops to __init__ ===
OLD = '        self._running = False\n\n        # §E: Stuck detection'
NEW = '''        self._running = False

        # FIX-CLEAR-ASK-RACE: sessions with an in-flight _run_loop. Used by
        # is_loop_active() and maintained by _run_loop's try/finally.
        self._active_loops: set[str] = set()

        # §E: Stuck detection'''
assert OLD in text, "Edit 1: old text not found"
text = text.replace(OLD, NEW, 1)
print("✅ Edit 1: _active_loops added to __init__")

# === Edit 2: Restructure _run_loop ===

# The original _run_loop body starts with:
#     def _run_loop(self, session_key: str, text: str) -> None:
#         """Background thread: run the full tool loop for one user message."""
#         with self._lock:
#             if not self._running:
#                 return
#             conv = self._conversations.get(session_key)
#             if conv is None:
#                 self._dispatch(self._on_error, session_key, "No conversation found")
#                 return
#         (blank)
#         # BUG #21: Fire a turn-start signal BEFORE any LLM call or tool processing.
#         ...

# Find the _run_loop function
FN_SENTINEL = '    def _run_loop(self, session_key: str, text: str) -> None:\n'
NEXT_DEF = '    def _dispatch_approval(self, session_key: str, tool_name: str, args: dict) -> bool | None:\n'

fn_start = text.index(FN_SENTINEL)
fn_end = text.index(NEXT_DEF, fn_start)

# Extract the full function body
fn_body = text[fn_start:fn_end]
lines = fn_body.splitlines(True)

# Original structure:
# line  0: def _run_loop(...)
# line  1: """..."""
# line  2: with self._lock:
# line  3:     if not self._running:
# line  4:         return
# line  5:     conv = ...
# line  6:     if conv is None:
# line  7:         self._dispatch(...)
# line  8:         return
# line  9: (blank)
# line 10: # BUG #21: ...
# line 11+ (body continues at indent 8)
# Last line: self._dispatch(self._on_error, session_key, e) (indent 12)
# Trailing blank

# Verify structure
assert lines[0] == FN_SENTINEL
assert lines[1].strip() == '"""Background thread: run the full tool loop for one user message."""'
assert lines[2].strip() == 'with self._lock:'
assert lines[8].strip() == 'return'

# Find last content line
last_content_idx = len(lines) - 1
while last_content_idx > 0 and not lines[last_content_idx].strip():
    last_content_idx -= 1

print(f"  Original _run_loop: {len(lines)} lines, last content at line {last_content_idx}")

# Build new function body
new_lines = []

# Line 0-1: def + docstring
new_lines.append(lines[0])  # def
new_lines.append(lines[1])  # docstring

# Marker + outer try
new_lines.append('        # FIX-CLEAR-ASK-RACE: mark this session as having an active loop so\n')
new_lines.append('        # clear_conversation() can refuse to wipe it mid-turn. Cleared in the\n')
new_lines.append('        # finally block at the end of this function.\n')
new_lines.append('        with self._lock:\n')
new_lines.append('            self._active_loops.add(session_key)\n')
new_lines.append('        try:\n')

# Re-indented guard check: lines 2-8 (+4 spaces)
for i in range(2, 9):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    new_lines.append(' ' * (indent + 4) + line.lstrip() + '\n')

# Re-indented body: lines 9 through last_content_idx (+4 spaces)
# Line 9 is typically blank
for i in range(9, last_content_idx + 1):
    line = lines[i]
    stripped = line.strip()
    if stripped:
        indent = len(line) - len(line.lstrip())
        new_lines.append(' ' * (indent + 4) + stripped + '\n')
    else:
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

new_fn_body = ''.join(new_lines)

# Replace in text
text = text[:fn_start] + new_fn_body + text[fn_end:]
check_ast(text, "After Edit 2 (runtime.py)")
print("✅ Edit 2: _run_loop restructured")

# === Edit 3: Add is_loop_active method ===

# Insert after _run_loop (before _dispatch_approval)
insert_pos = text.index(NEXT_DEF, text.index(FN_SENTINEL))

is_loop_active = '''    def is_loop_active(self, session_key: str) -> bool:
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

text = text[:insert_pos] + is_loop_active + text[insert_pos:]
check_ast(text, "After Edit 3 (runtime.py)")
print("✅ Edit 3: is_loop_active method added")

writefile('agent/runtime.py', text)
print("✅ agent/runtime.py written")

# ── 2. agent_runtime_handler.py ──────────────────────────────────────────────

text = readfile('ui/handlers/agent_runtime_handler.py')

# Find the guard check block in clear_conversation
# The line before conv = rt.get_conversation(session_key)
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

assert OLD in text, "Edit 4: pattern not found in agent_runtime_handler.py"
text = text.replace(OLD, NEW, 1)
check_ast(text, "After Edit 4 (handler)")
print("✅ Edit 4: guard added in clear_conversation")

writefile('ui/handlers/agent_runtime_handler.py', text)
print("✅ agent_runtime_handler.py written")

# ── 3. project_handler.py ────────────────────────────────────────────────────

text = readfile('ui/handlers/project_handler.py')

# Find the else branch in cmd_clear
# The current structure after the if ok: block:
#             return CommandResult(
#                 handled=True,
#                 response_text=f"Could not clear {agent_name}'s conversation.",
#             )
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

assert OLD in text, "Edit 5: pattern not found in project_handler.py"
text = text.replace(OLD, NEW, 1)
check_ast(text, "After Edit 5 (project_handler)")
print("✅ Edit 5: else branch added in cmd_clear")

writefile('ui/handlers/project_handler.py', text)
print("✅ project_handler.py written")

print("\n=== ALL 5 EDITS COMPLETE ===")