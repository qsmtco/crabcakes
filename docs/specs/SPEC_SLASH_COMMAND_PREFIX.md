---
status: DONE
---
# SPEC: Migrate Command Prefix from Backtick to Slash

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL_SLASH_COMMAND_PREFIX.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md §3.21a, §3.21e, §3.21j): `utils/config.py` owns `COMMAND_PREFIX`. `CommandHandler` reads from config and provides `set_prefix()`. `AgentCommandHandler` owns A2A scanning via standalone `_extract_quoted_commands()`. All prompts live in `prompts/system/`. No GTK in config or command parsing.

---

## DISCOVERY

- **`utils/config.py`:** `COMMAND_PREFIX = "\`"` at line 71. Single constant.
- **`ui/handlers/command_handler.py`:** `self._prefix = COMMAND_PREFIX` (line 65). `process_input()` checks `text.startswith(self._prefix)` (line 210). `set_prefix()` at line 96. `get_command_names()` at line 122 returns `set[str]`. Help strings: lines 106-115. Error messages: lines 283, 285, 295.
- **`ui/handlers/agent_command_handler.py`:** `_extract_quoted_commands(text)` is a standalone function (line 55). Regex at line 69: `r'\x60([^\x60]+)\x60'`. Called at line 266: `_extract_quoted_commands(clean_text)`. Has `self._command_handler` available via `set_command_handler()` (line 167).
- **`ui/handlers/task_handler.py`:** 17 backtick references — docstrings + usage strings.
- **`ui/handlers/collab_handler.py`:** 8 backtick references.
- **`ui/handlers/session_handler.py`:** 8 backtick references.
- **`ui/handlers/review_handler.py`:** 5 backtick references.
- **`ui/handlers/project_handler.py`:** 3 backtick references.
- **`ui/window.py`:** 5 backtick references in help_text kwargs.
- **`ui/handlers/chat_handler.py`:** 1 comment reference (line 62).
- **`prompts/system/crabcakes-commands.md`:** Full command reference. 15+ backtick references.
- **`prompts/system/collab.md`:** Agent collaboration protocol. 15+ backtick references.
- **`prompts/system/project-awareness.md`:** Line 28 references backtick.
- **`prompts/system/crabcakes-context.md`:** Line 16 references backtick.
- **`prompts/cc-task-planning.md`:** Lines 17, 76, 82, 101 reference backtick.
- **`docs/ARCHITECTURE.md`:** 10 backtick references.
- **`docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md`:** Backtick framing references.
- **`tests/test_command_handler.py`:** 34 backtick references.
- **`tests/test_agent_command_handler.py`:** 46 backtick references.
- **Regex verified:** New regex `r'(?:^|\s)/([^\s/\n][^/\n]*)'` + command name validation tested against 14 cases. All pass. File paths, URLs, double-slashes all correctly rejected.

---

## 1. Overview

### Problem
Backtick as command prefix collides with markdown's inline code delimiter. This causes delimiter collision bugs in the A2A scanner, requires extensive agent prompt teaching ("CRITICAL: include both opening AND closing backtick"), and goes against universal chat convention (Discord, Slack, IRC, Telegram all use `/`).

### Solution
Change `COMMAND_PREFIX` from `` ` `` to `/`. Update A2A scanner regex with command name validation. Rewrite agent teaching prompts. Update all help strings, error messages, and test assertions.

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| `COMMAND_PREFIX` constant | Markdown backtick rendering |
| A2A scanner regex + command validation | Fenced code block parsing |
| Handler help/error strings (7 files) | Syntax highlighting |
| Agent teaching prompts (5 files) | Crabcard format |
| Architecture docs (2 files) | Agent response formatting |
| Test assertions (2 files, ~80) | The quoted payload format (`"payload"`) |

---

## 2. Changes by File

### 2.1 `utils/config.py`

**Line 71 — one character:**

Current:
```python
COMMAND_PREFIX = "`"
```

New:
```python
COMMAND_PREFIX = "/"
```

**Verified:** Imported only by `ui/handlers/command_handler.py` line 31.

---

### 2.2 `ui/handlers/agent_command_handler.py`

**Change 1 — function signature (line 55):**

Current:
```python
def _extract_quoted_commands(text: str) -> list[ParsedCommand]:
```

New:
```python
def _extract_quoted_commands(text: str, command_names: set[str] | None = None) -> list[ParsedCommand]:
```

**Change 2 — regex (line 69):**

Current:
```python
    for m in re.finditer(r'`([^`]+)`', text):
        inner = m.group(1)
        tokens = inner.split()
        if not tokens:
            continue
        
        cmd = tokens[0]
        rest = tokens[1:]
```

New:
```python
    for m in re.finditer(r'(?:^|\s)/([^\s/\n][^/\n]*)', text):
        inner = m.group(1)
        tokens = inner.split()
        if not tokens:
            continue
        
        cmd = tokens[0].lower()  # commands are case-insensitive
        
        # Reject unknown command names (file paths, URLs, etc.)
        if command_names and cmd not in command_names:
            continue
        
        rest = tokens[1:]
```

**Key difference:** Backtick regex required matching open+close backticks. Slash regex only needs the prefix — no closing delimiter. This eliminates the "forgot the closing backtick" failure mode entirely.

Also added `cmd = tokens[0].lower()` — command names should be case-insensitive (already true in `CommandHandler` via registry lookup, but the old scanner was case-sensitive). If this introduces a behavior change, the implementer should verify existing tests account for case.

**Change 3 — call site (line 266):**

Current:
```python
        parsed_commands = _extract_quoted_commands(clean_text)
```

New:
```python
        command_names = self._command_handler.get_command_names() if self._command_handler else None
        parsed_commands = _extract_quoted_commands(clean_text, command_names)
```

**Regex safety analysis (14 test cases verified):**

| Input | Regex matches | cmd name valid? | @Agent? | Result |
|-------|:---:|:---:|:---:|--------|
| `/ask @Coder "hello"` | ✅ | ✅ ask | ✅ | **Parsed** |
| `text /ask @Coder "hi"` | ✅ | ✅ ask | ✅ | **Parsed** |
| `/home/q/file.py` | ✅ | ❌ home | — | **Rejected** |
| `use /etc/hosts` | ✅ | ❌ etc | — | **Rejected** |
| `Save /tmp/out.txt and @Coder` | ✅ | ❌ tmp, out.txt | — | **Rejected** |
| `/status` | ✅ | ✅ status | ❌ None | **Rejected** (no agent) |
| `/task @QTR do stuff` | ✅ | ✅ task | ✅ | **Parsed** |
| `path/home/q` | ❌ no space | — | — | **No match** |
| `/a @Coder "quick"` | ✅ | ✅ a (alias) | ✅ | **Parsed** |
| `the // comment` | ❌ no space+slash | — | — | **No match** |
| `/STOp @Coder` | ✅ | ✅ stop | ✅ | **Parsed** |
| `/usr/bin/env` | ✅ | ❌ usr | — | **Rejected** |
| `Run /ask @Debugger "x"` | ✅ | ✅ ask | ✅ | **Parsed** |
| `https://example.com` | ❌ no space | — | — | **No match** |

---

### 2.3 `ui/handlers/command_handler.py`

**Lines 106-115 — help strings:**

Current:
```python
                help_text = f"Unknown command: `{name}"
            else:
                help_text = f"`{name}` — {help_text}"
            return CommandResult(handled=True, response_text=help_text)
        lines = [" CrabCakes Commands", ""]
        for name in self._registry.list_commands():
            alias_list = [al for al, cn in self._registry.list_aliases().items() if cn == name]
            alias_str = f" (`{', `'.join(alias_list)}`)" if alias_list else ""
            lines.append(f"  `{name}`{alias_str}")
        lines.extend(["", f"Type `help <command> for details."])
```

New:
```python
                help_text = f"Unknown command: /{name}"
            else:
                help_text = f"/{name} — {help_text}"
            return CommandResult(handled=True, response_text=help_text)
        lines = [" CrabCakes Commands", ""]
        for name in self._registry.list_commands():
            alias_list = [al for al, cn in self._registry.list_aliases().items() if cn == name]
            alias_str = f" (/{', /'.join(alias_list)})" if alias_list else ""
            lines.append(f"  /{name}{alias_str}")
        lines.extend(["", f"Type /help <command> for details."])
```

**Lines 283, 285, 295 — error messages:**

Current:
```python
                    error_msg = 'Empty payload — provide a message: `' + cmd_name + ' @Agent "your message"`'
                    ...
                    error_msg = 'Unclosed quote — missing closing ": `' + cmd_name + ' @Agent "your message"`'
                    ...
            error_msg = 'Malformed command — payload must be quoted: `' + cmd_name + ' @Agent "your message"`'
```

New:
```python
                    error_msg = 'Empty payload — provide a message: /' + cmd_name + ' @Agent "your message"'
                    ...
                    error_msg = 'Unclosed quote — missing closing ": /' + cmd_name + ' @Agent "your message"'
                    ...
            error_msg = 'Malformed command — payload must be quoted: /' + cmd_name + ' @Agent "your message"'
```

---

### 2.4 `ui/handlers/task_handler.py`

All usage strings change `` `command `` → `/command`. 17 occurrences:

| Line | Current | New |
|------|---------|-----|
| 97 | `` ` ``task @agent — description | /task @agent — description |
| 99 | `` ` ``task @agent — description | /task @agent — description |
| 125 | `` ` ``done \<id\> → mark task complete | /done \<id\> → mark task complete |
| 128 | `` ` ``done \<task_id\> | /done \<task_id\> |
| 149 | `` ` ``start \<id\> → start working | /start \<id\> → start working |
| 152 | `` ` ``start \<task_id\> | /start \<task_id\> |
| 173 | `` ` ``blocked \<id\> — reason | /blocked \<id\> — reason |
| 176 | `` ` ``blocked \<task_id\> — reason | /blocked \<task_id\> — reason |
| 198 | `` ` ``cancel \<id\> → cancel task | /cancel \<id\> → cancel task |
| 201 | `` ` ``cancel \<task_id\> | /cancel \<task_id\> |
| 222 | `` ` ``tasks → show all tasks | /tasks → show all tasks |
| 236 | `` ` ``assign \<id\> @agent → reassign | /assign \<id\> @agent → reassign |
| 239 | `` ` ``assign \<task_id\> @agent | /assign \<task_id\> @agent |
| 241 | `` ` ``assign \<task_id\> @agent | /assign \<task_id\> @agent |
| 263 | `` ` ``priority \<id\> \<level\> | /priority \<id\> \<level\> |
| 266 | `` ` ``priority \<task_id\> \<level\> | /priority \<task_id\> \<level\> |
| 269 | `` ` ``priority \<task_id\> \<level\> | /priority \<task_id\> \<level\> |

---

### 2.5 `ui/handlers/collab_handler.py`

8 occurrences, same pattern `` `command `` → `/command`:

| Line | Current | New |
|------|---------|-----|
| 38 | `` ` ``ask @agent — question | /ask @agent — question |
| 42 | `` ` ``ask @agent — question | /ask @agent — question |
| 46 | `` ` ``delegate @agent — task | /delegate @agent — task |
| 50 | `` ` ``delegate @agent — task | /delegate @agent — task |
| 54 | `` ` ``stop @agent → send stop | /stop @agent → send stop |
| 56 | `` ` ``stop @agent | /stop @agent |
| 60 | `` ` ``tell @agent — info | /tell @agent — info |
| 64 | `` ` ``tell @agent — info | /tell @agent — info |

---

### 2.6 `ui/handlers/session_handler.py`

8 occurrences:

| Line | Current | New |
|------|---------|-----|
| 25 | `` ` ``session list @agent \| `` ` ``session \<ref\> @agent | /session list @agent \| /session \<ref\> @agent |
| 49 | `` ` ``session list @agent \| `` ` ``session \<ref\> @agent | /session list @agent \| /session \<ref\> @agent |
| 62 | `` ` ``session list @agent \| `` ` ``session \<ref\> @agent | /session list @agent \| /session \<ref\> @agent |
| 80 | `` ` ``session list @agent \| `` ` ``session \<ref\> @agent | /session list @agent \| /session \<ref\> @agent |
| 103 | `` ` ``session \<number\> @ | /session \<number\> @ |
| 142 | `` ` ``session list @ | /session list @ |
| 148 | `` ` ``session list @ | /session list @ |

---

### 2.7 `ui/handlers/review_handler.py`

5 occurrences:

| Line | Current | New |
|------|---------|-----|
| 170 | `` ` ``review | /review |
| 342 | `` ` ``review → start a review | /review → start a review |
| 353 | `` ` ``check → check changes | /check → check changes |
| 362 | `` ` ``accept → accept all | /accept → accept all |
| 373 | `` ` ``reject → reject all | /reject → reject all |

---

### 2.8 `ui/handlers/project_handler.py`

3 occurrences:

| Line | Current | New |
|------|---------|-----|
| 418 | `` ` ``status → project status | /status → project status |
| 444 | `` ` ``agents → list agents | /agents → list agents |
| 460 | `` ` ``cost — spending summary | /cost — spending summary |

---

### 2.9 `ui/window.py`

5 occurrences in help_text kwargs:

| Line | Current | New |
|------|---------|-----|
| 578 | `` ` ``ask @agent — question | /ask @agent — question |
| 580 | `` ` ``delegate @agent — task | /delegate @agent — task |
| 582 | `` ` ``stop @agent | /stop @agent |
| 584 | `` ` ``tell @agent — info | /tell @agent — info |
| 626 | `` ` ``session list @agent \| `` ` ``session \<ref\> @agent | /session list @agent \| /session \<ref\> @agent |

---

### 2.10 `ui/handlers/chat_handler.py`

1 comment reference:

| Line | Current | New |
|------|---------|-----|
| 62 | for backtick commands | for slash commands |

---

### 2.11 `prompts/system/crabcakes-commands.md` — FULL REWRITE

Replace all backtick references with slash. Key sections:

**Opening line:**
```markdown
All commands start with a slash (`/`).
```

**Syntax section:**
```markdown
- `/command arguments` — type in the project feed
- `@agent` — mention an agent by name (e.g. `@Coder`, `@QTR`)
```

**Every command table entry:**
```markdown
| `/ask` | `@agent — question` | Ask an agent a question. |
```

**Important reminders:**
```markdown
- These are **CrabCakes slash commands**, not shell commands.
- To create tasks, use `/task @agent — description` in the project feed.
- Do NOT attempt `task add` in a terminal — that command does not exist.
```

**Crabcard section:** No changes — fenced code blocks are markdown, not commands.

---

### 2.12 `prompts/system/collab.md` — SIGNIFICANT UPDATE

**Remove the entire "closing backtick" teaching section.** Slash commands don't need a closing delimiter.

Current opening:
```markdown
**CRITICAL: The command MUST have both an opening AND closing backtick.**

`ask @AgentName "your question"`

Anatomy: **opening backtick** → command → @Agent → **"quoted payload"** → **closing backtick**
```

New opening:
```markdown
Use the `ask` command to consult another agent. This is the **only**
mechanism for agent-to-agent consultation.

/ask @AgentName "your question"

Anatomy: `/` → command → @Agent → "quoted payload"
```

**Remove from DO/DON'T lists:**
- "Always include the closing backtick"
- "Forget the closing backtick — `ask @Agent "question"` without the trailing backtick is invisible to the parser"

**Keep:**
- Quoted payload requirement
- 4,096 character limit
- Maximum 3 commands per response
- @Agent routing rules

**Command reference table:**
```markdown
| /ask @Agent "question" | Consult an agent, get their expertise | Response expected |
| /delegate @Agent "task" | Assign a task to an agent | Response expected |
| /tell @Agent "information" | Share information with an agent | No response expected |
| /stop @Agent | Stop collaboration with an agent | No payload needed |
```

---

### 2.13 `prompts/system/project-awareness.md`

Line 28 — replace backtick requirement:

Current:
```markdown
**The command must have both opening and closing backticks** — without the closing backtick, the parser will not detect the command.
```

New:
```markdown
Commands start with `/` (slash). Example: `/ask @Agent "question"`.
```

---

### 2.14 `prompts/system/crabcakes-context.md`

Line 16:

Current:
```markdown
Use backtick commands to query CrabCakes state: `status`, `agents`, `tasks`, `review`, `cost`
```

New:
```markdown
Use slash commands to query CrabCakes state: `/status`, `/agents`, `/tasks`, `/review`, `/cost`
```

---

### 2.15 `prompts/cc-task-planning.md`

Lines 17, 76, 82, 101 — replace backtick references with slash.

Line 17:
```markdown
5. Create each approved task using CrabCakes slash commands (typed in the project feed, NOT a shell CLI)
```

Line 76:
```markdown
/task @assignee — description
```

Line 82:
```markdown
**Important:** This is a CrabCakes slash command, NOT a shell/terminal command. Do not run `task add` in a terminal.
```

Line 101:
```markdown
3. Suggest: "All tasks created. Use `/tasks` to review, or tell the assigned agent to `/start #1`."
```

---

### 2.16 `docs/ARCHITECTURE.md`

10 references to update:

| Line | Current | New |
|------|---------|-----|
| 102 | backtick command parser (Phase 7) | command parser, slash prefix (Phase 7) |
| 923 | Backtick Command Parser (Phase 7) | Command Parser — Slash Prefix (Phase 7) |
| 925 | Parse backtick commands | Parse slash-prefixed commands |
| 1022 | Scan agent response text for backtick commands | Scan agent response text for slash commands |
| 1051 | parse backtick commands | parse slash commands |
| 1137 | `COMMAND_PREFIX = "\`"` # backtick command trigger | `COMMAND_PREFIX = "/"` # slash command trigger |
| 2057 | backtick command in their response text | slash command in their response text |
| 2058 | The backtick command is parsed by CommandHandler | The slash command is parsed by CommandHandler |
| 2558 | backtick command parser + @mention resolution | command parser (slash prefix) + @mention resolution |
| 2602 | Backtick command reference for project chats | Slash command reference for project chats |

---

### 2.17 `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md`

Update all backtick framing references. The spec's canonical format changes from:

```
`cmd @Agent "payload"
```

to:

```
/cmd @Agent "payload"
```

Update the anatomy description to remove backtick framing.

---

### 2.18 `tests/test_command_handler.py`

34 occurrences. Mechanical find-and-replace: every `` `command `` in `process_input()` calls becomes `/command`:

```python
# Before:
result = configured_handler.process_input("agent:1", "`echo @Debugger \"hello\"")

# After:
result = configured_handler.process_input("agent:1", "/echo @Debugger \"hello\"")
```

Edge cases to handle:
- Line 106: `process_input("agent:1", "\`")` → `process_input("agent:1", "/")` (prefix-only input)
- Line 110: `process_input("agent:1", "\`   ")` → `process_input("agent:1", "/   ")` (prefix + whitespace)

---

### 2.19 `tests/test_agent_command_handler.py`

46 occurrences. Two types of changes:

**Type 1 — embedded command strings in agent response text:**
```python
# Before:
handler.on_agent_response("special:coder", "`ask @Debugger hello`", "crabwatch")

# After:
handler.on_agent_response("special:coder", "/ask @Debugger \"hello\"", "crabwatch")
```

**Note:** The old backtick format had the closing backtick as part of the delimiter. With slash, there's no closing delimiter — the command runs to end of logical segment. Agents must format commands as `/cmd @Agent "payload"` within their response text.

**Type 2 — helper function assertions:**
The test file has helper functions at lines 38-55 that parse backtick commands. These must be updated:

```python
# Before:
if text.startswith("`ask @"):
    ...
    msg = parts[1].rstrip("`") if len(parts) > 1 else ""

# After:
if text.startswith("/ask @"):
    ...
    msg = parts[1] if len(parts) > 1 else ""  # no trailing backtick to strip
```

**Type 3 — edge case tests for backtick collision:**
Tests like line 452 that specifically test backtick-vs-command disambiguation:

```python
# Before:
"Here's the fix:\n\n```python\nresult = `ask @Debugger`  # not a command\n```\n\nBut `ask @Debugger \"is this right?\"` ← IS a command"

# After: This test needs rewriting for the new world. With slash prefix, 
# backticks in code blocks are no longer a concern. Instead, test slash-in-prose:
"Here's the fix:\n\n```python\nresult = /ask @Debugger \"check\"  # not in prose\n```\n\nBut /ask @Debugger \"is this right?\" ← IS a command"
```

Actually, the test at line 452 tests that commands inside fenced code blocks are ignored (because `_strip_fenced_blocks` removes them first). This still applies — the slash command inside a fenced block gets stripped. The test still makes sense; just change backticks to slashes.

---

### 2.20 Comment in `ui/handlers/chat_handler.py`

Line 62:

```python
# Before:
self._command_handler = None     # injected via set_command_handler() — for backtick commands

# After:
self._command_handler = None     # injected via set_command_handler() — for slash commands
```

---

## 3. Data Flow

### User types `/ask @Coder "hello"`
1. User types text → `ChatHandler.on_send()` called
2. `ChatHandler` calls `self._command_handler.process_input(session_key, "/ask @Coder \"hello\"")`
3. `CommandHandler.process_input()` checks `text.startswith("/")` → True
4. Strips prefix: `raw = "ask @Coder \"hello\""`
5. Parses: command=`ask`, agent=`@Coder`, payload=`hello`
6. Dispatches to `CollabHandler.handle_ask()`
7. Returns `CommandResult(handled=True)`

### Agent response contains `/ask @Debugger "check this"`
1. Agent response arrives → `AgentCommandHandler.on_agent_response()` called
2. `_strip_fenced_blocks(text)` removes fenced code blocks
3. `_extract_quoted_commands(clean_text, command_names)` scans with regex `r'(?:^|\s)/([^\s/\n][^/\n]*)'`
4. Regex matches `ask @Debugger "check this"` after `/`
5. `cmd = 'ask'` → validated against `command_names` → ✅ registered
6. Finds `@Debugger` in rest → `agent = '@Debugger'`
7. Parses quoted payload → `"check this"`
8. Returns `ParsedCommand(command='ask', agent='@Debugger', payload='check this')`
9. `AgentCommandHandler` rebuilds as `/ask @Debugger "check this"` → passes to `process_input()`
10. Routes to target agent

### User types `/home/q/projects/file.py`
1. `process_input()` checks `text.startswith("/")` → True
2. Strips prefix: `raw = "home/q/projects/file.py"`
3. First token: `home/q/projects/file.py` (no spaces)
4. Looks up `home` in registry → not found
5. Returns `CommandResult(handled=False)` — passes through as normal text

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `utils/config.py` | Modified | 1 | None — single character |
| `ui/handlers/agent_command_handler.py` | Modified | ~5 | Medium — regex + validation logic |
| `ui/handlers/command_handler.py` | Modified | ~11 | Low — strings only |
| `ui/handlers/task_handler.py` | Modified | ~17 | Low — strings only |
| `ui/handlers/collab_handler.py` | Modified | ~8 | Low — strings only |
| `ui/handlers/session_handler.py` | Modified | ~8 | Low — strings only |
| `ui/handlers/review_handler.py` | Modified | ~5 | Low — strings only |
| `ui/handlers/project_handler.py` | Modified | ~3 | Low — strings only |
| `ui/window.py` | Modified | ~5 | Low — strings only |
| `ui/handlers/chat_handler.py` | Modified | 1 | None — comment only |
| `prompts/system/crabcakes-commands.md` | Full rewrite | ~120 | Medium — agent training |
| `prompts/system/collab.md` | Significant update | ~50 | Medium — agent training |
| `prompts/system/project-awareness.md` | Modified | ~3 | Low |
| `prompts/system/crabcakes-context.md` | Modified | ~2 | Low |
| `prompts/cc-task-planning.md` | Modified | ~6 | Low |
| `docs/ARCHITECTURE.md` | Modified | ~10 | Low — docs only |
| `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md` | Modified | ~15 | Low — docs only |
| `tests/test_command_handler.py` | Modified | ~34 | Low — mechanical replace |
| `tests/test_agent_command_handler.py` | Modified | ~46 | Medium — regex + edge cases |
| **Total** | | **~355 lines** | |

**Files NOT changed (already correct):**
- `utils/markdown.py` — inline code backticks are markdown spec, not commands
- `utils/block_parser.py` — fenced code blocks are markdown spec
- `utils/syntax_highlight.py` — unrelated
- `utils/crabcard_parser.py` — uses fenced blocks, not command prefix
- `ui/views/chat_bubble.py` — no command-specific code
- `agent/runtime.py` — sends text, doesn't parse commands
- `models/command.py` — no prefix references

---

## 5. Implementation Order

1. **Change `COMMAND_PREFIX`** in `utils/config.py` — one character
2. **Update A2A scanner** in `agent_command_handler.py` — regex + signature + call site + command validation
3. **Update handler strings** — `command_handler.py`, `task_handler.py`, `collab_handler.py`, `session_handler.py`, `review_handler.py`, `project_handler.py`, `window.py`, `chat_handler.py`
4. **Rewrite prompts** — `crabcakes-commands.md`, `collab.md`, `project-awareness.md`, `crabcakes-context.md`, `cc-task-planning.md`
5. **Update test assertions** — `test_command_handler.py`, `test_agent_command_handler.py`
6. **Update docs** — `ARCHITECTURE.md`, `A2A_QUOTED_PAYLOAD_SPEC.md`
7. **Run full test suite** — verify zero regressions
8. **Visual test** — type `/help`, `/status`, `/ask @Coder "hello"` in CrabCakes

**Verification at each step:**
1. `python3 -c "from utils.config import COMMAND_PREFIX; print(COMMAND_PREFIX)"` → `/`
2. `python3 -c "from ui.handlers.agent_command_handler import _extract_quoted_commands; print(_extract_quoted_commands('/ask @Coder \"hi\"', {'ask'}))"` → shows ParsedCommand
3. `grep -rn '\`' ui/handlers/ --include="*.py" | grep -v '#'` → zero non-comment backtick references
4. `grep -rn 'backtick' prompts/` → zero results
5. `python3 -m pytest tests/test_command_handler.py tests/test_agent_command_handler.py -q` → all pass
6. `/help` in CrabCakes shows slash commands

---

## 6. Acceptance Criteria

- [ ] `COMMAND_PREFIX = "/"` in `utils/config.py`
- [ ] A2A scanner detects `/command @Agent "payload"` in agent responses
- [ ] A2A scanner rejects file paths (`/home/q/...`), URLs, and unknown words after `/`
- [ ] A2A scanner validates command names against registered commands
- [ ] All help text shows `/command` format
- [ ] All error messages show `/command` format
- [ ] All agent prompts teach `/command` format
- [ ] `collab.md` no longer mentions "opening backtick" or "closing backtick"
- [ ] `crabcakes-commands.md` opens with "All commands start with a slash"
- [ ] All tests pass with `/command` inputs
- [ ] No references to backtick as command prefix in handler code
- [ ] Markdown backticks for code rendering work unchanged
- [ ] `/help` command displays correct output
- [ ] `/ask @Agent "payload"` routes correctly
- [ ] Unknown `/` inputs (e.g. `/home/q/...`) pass through as `handled=False`
- [ ] `ARCHITECTURE.md` updated with slash prefix references

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| User types `/home/q/file.py` | `process_input()` returns `handled=False` — passes through as text |
| Agent writes `use /etc/hosts` in response | Scanner rejects `etc` — not a registered command |
| Agent writes `/ask @Coder "hello"` in fenced code block | `_strip_fenced_blocks()` removes it — not detected |
| User types `// comment` | No space before second `/` → regex doesn't match → `handled=False` |
| User types `/HELP status` | Case-insensitive: `help` matched, `status` as arg |
| Agent writes `https://example.com/path` | No space before `/` in URL → regex doesn't match |
| User types `/` alone | `raw = ""` after strip → `handled=False` |
| User types `/   ` | `raw = ""` after strip → `handled=False` |
| `/status` typed by user | `process_input()` handles it — no `@Agent` needed |
| `/status` in agent response text | Scanner finds `status` (registered) but no `@Agent` → skipped |
| Agent writes `/STOp @Coder` | `cmd.lower() = 'stop'` → registered → parsed correctly |

---

## 8. ARCHITECTURE.md Updates Required

- §3.21a title: "Backtick Command Parser" → "Command Parser — Slash Prefix"
- §3.21a description: update command format references
- §3.21e description: update scanner description
- §3.21j config section: update `COMMAND_PREFIX` value and comment
- Architecture rules section (line 2057-2058): update command reference
- File tree section (lines 102, 2558): update comments
- Prompt file tree (line 2602): update description

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `COMMAND_PREFIX` at `utils/config.py:71` — verified ✅
   - `_extract_quoted_commands` signature at line 55 — verified ✅
   - A2A regex at line 69 — verified ✅
   - Call site at line 266 — verified ✅
   - `self._command_handler.get_command_names()` at line 122 of command_handler.py — verified ✅
   - All handler string line numbers verified via grep ✅
   - Test file backtick counts verified ✅

2. **Did I catch all exception types?**
   - `get_command_names()` returns `set[str]` — no exceptions possible
   - `_extract_quoted_commands()` returns `list[ParsedCommand]` — no exceptions
   - `process_input()` returns `CommandResult` — no exceptions
   - No new exception paths introduced ✅

3. **Did I verify key structures?**
   - `command_names` is `set[str]` — O(1) membership check ✅
   - `ParsedCommand` is a namedtuple with `(command, agent, payload, raw_start, raw_end)` — verified ✅
   - Regex capture group is `str` — `tokens = inner.split()` returns `list[str]` ✅

4. **Did I trace the data flow end-to-end?**
   - User input → `ChatHandler.on_send()` → `CommandHandler.process_input()` → prefix check → parse → dispatch. ✅
   - Agent response → `AgentCommandHandler.on_agent_response()` → `_strip_fenced_blocks()` → `_extract_quoted_commands(text, command_names)` → regex → cmd validation → @Agent lookup → ParsedCommand → `process_input()`. ✅

5. **Would an implementer produce working code?**
   - Yes. All changes are mechanical find-and-replace except the A2A scanner regex, which is fully specified and tested against 14 cases.

6. **Architecture compliance verified?**
   - `utils/config.py` owns `COMMAND_PREFIX` ✅
   - `CommandHandler` owns prefix enforcement, no GTK ✅
   - `AgentCommandHandler` owns A2A scanning, no GTK ✅
   - Prompt files in `prompts/system/` ✅
   - No cross-layer violations ✅
