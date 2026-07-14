# PROPOSAL: Migrate Command Prefix from Backtick to Slash

**Date:** 2026-05-28  
**Author:** Qaster  
**Status:** ✅ DONE — migration complete. `utils/config.py:71` sets `COMMAND_PREFIX = "/"`. All command prompt files use `/` syntax. Slash is the active command prefix.

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` The migration from backtick to slash is **complete**. `utils/config.py:71` sets `COMMAND_PREFIX = "/"`. `ui/handlers/command_handler.py:69` reads `self._prefix = COMMAND_PREFIX` (from config). `command_handler.py:173` says "Default: slash" in the `set_prefix()` docstring. All command prompt files use `/` syntax (e.g. `prompts/system/crabcakes-commands.md:22` shows `/ask`, `/a`, `/delegate` aliases). The proposal's estimated effort ("~2 hours") was accurate. **Marked DONE; slash is the active command prefix.**  
**Priority:** Medium  
**Effort:** ~2 hours (code + prompts + tests)

---

## Why

### The Problem

CrabCakes uses the backtick (`` ` ``) as its command prefix. This was a reasonable early choice — it's compact and distinctive. But as the system has grown, the backtick has become a liability:

1. **Delimiter collision.** Backtick is markdown's primary delimiter for inline code. AI agents use `` `code` `` and ``` ```code blocks ``` in virtually every response. The A2A command scanner (`r'\`([^\`]+)\`'`) must distinguish between agent code references and actual commands — a constant source of parsing bugs.

2. **Already caused real bugs.** The A2A spec (`docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md`) was written specifically because backtick-delimited parsing was truncating payloads when agents used code references like `` `match()` `` inside their responses. We patched around it, but the root cause — using backtick for two different things — remains.

3. **Every prompt must teach the backtick exception.** The `collab.md` prompt spends 30+ lines explaining opening/closing backticks, why they're required, and what happens when you forget them. That's a sign the abstraction is wrong. Slash commands are self-explanatory.

4. **Against convention.** Every major chat platform — Discord, Slack, IRC, Telegram, Matrix, Teams, Google Chat — uses `/` for commands. Users expect it. Agents trained on diverse data expect it. Backtick-as-command is a CrabCakes invention that must be taught from scratch.

5. **Gets worse over time.** The more prompts, tests, and agent training docs we write with backtick syntax, the more we have to migrate later. The cost only grows.

### Why Slash

| Criterion | `/` (slash) | Assessment |
|-----------|-------------|------------|
| Universal convention | ✅ Every chat app on earth | **Excellent** |
| Learning curve | ✅ Zero — `/help`, `/status` are universal | **Excellent** |
| Conflict with markdown | ❌ No conflict — slash is not a markdown delimiter | **Excellent** |
| Conflict with file paths | ⚠️ `/home/q/...` exists, but users don't start chat messages with file paths; unknown commands pass through | **Acceptable** |
| Conflict with code | ⚠️ `// comment` in code, but agents put code in fenced blocks, not bare text | **Acceptable** |
| Visual distinctiveness | ✅ `/command` is clearly a command at a glance | **Good** |
| Config already exists | ✅ `set_prefix()` method + `COMMAND_PREFIX` config already implemented | **No plumbing needed** |

### What This Is NOT

This proposal does **not** change:
- Markdown syntax — backticks for inline code and fenced blocks remain standard markdown
- How agents format code or responses — only the command prefix changes
- The A2A quoted payload format — `"payload"` quoting stays the same
- Any rendering, parsing, or display logic — only the command detection prefix

---

## What

### Before (current)
```
`ask @Coder "should I use a generator?"
`task @QTR — implement the spec
`help
`status
```

### After (proposed)
```
/ask @Coder "should I use a generator?"
/task @QTR — implement the spec
/help
/status
```

The only change is the first character. Everything after — command name, `@Agent`, `"payload"`, flags — stays identical.

---

## How

### Tier 1: Core Code (3 files)

#### 1. `utils/config.py` — line 71
```python
# Before:
COMMAND_PREFIX = "`"

# After:
COMMAND_PREFIX = "/"
```
One character. The entire command system reads from this constant. `CommandHandler.__init__()` sets `self._prefix = COMMAND_PREFIX`. `process_input()` checks `text.startswith(self._prefix)`. All command routing flows from this single value.

#### 2. `ui/handlers/agent_command_handler.py` — line 69
```python
# Before:
for m in re.finditer(r'`([^`]+)`', text):

# After:
for m in re.finditer(r'/([^/\n]+)', text):
```
The A2A scanner that looks for commands in agent responses. Change the regex from backtick-delimited to slash-prefixed matching. The `[^\n]` ensures we don't match across line boundaries (a command must be on one line).

**Note:** This regex change actually **simplifies** the scanner. The current regex requires matching opening AND closing backticks, which is the root cause of the delimiter collision bugs. Slash commands only need a prefix — no closing delimiter required. This eliminates the "forgot the closing backtick" failure mode entirely.

#### 3. `ui/handlers/command_handler.py` — help text strings (~8 lines)
Lines 106-115 wrap command names in backticks for display. Change to wrap in a distinct format:
```python
# Before:
help_text = f"Unknown command: `{name}"
help_text = f"`{name}` — {help_text}"
lines.append(f"  `{name}`{alias_str}")
lines.extend(["", f"Type `help <command> for details."])

# After:
help_text = f"Unknown command: /{name}"
help_text = f"/{name} — {help_text}"
lines.append(f"  /{name}{alias_str}")
lines.extend(["", f"Type /help <command> for details."])
```

### Tier 2: Handler Help Strings (3 files)

#### 4. `ui/handlers/task_handler.py` — ~17 occurrences
All usage/help strings currently show backtick commands:
```python
# Before:
return CommandResult(handled=True, response_text="No target agent. Usage: `task @agent — description")

# After:
return CommandResult(handled=True, response_text="No target agent. Usage: /task @agent — description")
```

#### 5. `ui/handlers/collab_handler.py` — ~8 occurrences  
Same pattern — usage strings reference backtick commands.

#### 6. `ui/handlers/session_handler.py` — ~2 occurrences

#### 7. `ui/handlers/review_handler.py` — ~5 occurrences

### Tier 3: Agent Teaching Prompts (5 files)

This is the critical piece. These prompts teach agents how to use commands. They must be rewritten to teach slash syntax. **Without updating these, agents will keep generating backtick commands that won't work.**

#### 8. `prompts/system/crabcakes-commands.md` — FULL REWRITE
The complete command reference. Currently opens with "All commands start with a backtick." Must be rewritten to use `/` prefix. Every command example changes from `` `command `` to `/command`. The table of commands, examples, and reminders all update.

**Key improvement:** The prompt currently has an "Important Reminders" section explaining that "these are CrabCakes backtick commands, not shell commands." With slash, this gets simpler — "these are CrabCakes slash commands" requires less explanation because slash is already the universal command convention.

#### 9. `prompts/system/collab.md` — SIGNIFICANT UPDATE
The agent collaboration protocol. Currently has 30+ lines teaching agents about opening/closing backticks. This simplifies dramatically:

```markdown
# Before (current):
**CRITICAL: The command MUST have both an opening AND closing backtick.**

`ask @AgentName "your question"`

Anatomy: **opening backtick** → command → @Agent → **"quoted payload"** → **closing backtick**

The payload **must** be wrapped in double quotes. Unquoted payloads are not
accepted. Commands without a closing backtick are **silently ignored** — the
parser will not find them.

...

- **Closing backtick required:** The command must end with a backtick.
- **Always include the closing backtick** — the command does not work without it
- Forget the closing backtick — `ask @Agent "question"` without the trailing
  backtick is invisible to the parser

# After (proposed):
Commands start with `/` (slash). Use the `ask` command to consult another agent.

/ask @AgentName "your question"

Anatomy: `/` → command → @Agent → "quoted payload"

The payload must be wrapped in double quotes.
```

**The entire "closing backtick" teaching section goes away.** Slash commands don't need a closing delimiter — the command runs to end of line. This eliminates the #1 failure mode for agent command generation.

#### 10. `prompts/system/project-awareness.md` — UPDATE A2A SECTION
Lines 28: Currently says "The command must have both opening and closing backticks." Simplifies to just showing `/ask @Agent "question"` format.

#### 11. `prompts/system/crabcakes-context.md` — UPDATE BACKTICK SECTION
Line 16: Currently "Use backtick commands to query CrabCakes state." Changes to "Use slash commands to query CrabCakes state."

#### 12. `prompts/cc-task-planning.md` — UPDATE REFERENCES
Lines 17, 76, 82: References to "backtick commands" become "slash commands." Example commands change from `` `task @agent — description `` to `/task @agent — description`.

### Tier 4: Architecture Documentation (1 file)

#### 13. `docs/ARCHITECTURE.md` — UPDATE COMMAND SECTIONS
- §3.21a title: "Backtick Command Parser" → "Command Parser (Slash Prefix)"
- §3.21a description: "Parse backtick commands" → "Parse slash-prefixed commands"
- §3.21e description: "Scan agent response text for backtick commands" → "Scan agent response text for slash commands"
- File tree comment (line 102): "backtick command parser" → "command parser (slash prefix)"
- Any other backtick references in command-related sections

### Tier 5: Tests (2 files)

#### 14. `tests/test_command_handler.py` — ~34 assertions
All test inputs use `` `command `` format. Change to `/command`:
```python
# Before:
result = configured_handler.process_input("agent:1", "`echo @Debugger \"hello\"")

# After:
result = configured_handler.process_input("agent:1", "/echo @Debugger \"hello\"")
```

#### 15. `tests/test_agent_command_handler.py` — ~46 assertions
A2A scanner tests that feed backtick-wrapped commands to the parser. Change to slash prefix.

### Tier 6: Investigation & Spec Docs (reference only, optional)

#### 16. `docs/INVESTIGATION_COMMAND_PREFIX.md` — update or archive
This investigation doc becomes historical context.

#### 17. `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md` — update references
The spec references backtick framing. Update to slash.

---

## File Change Summary

| File | Change | Lines | Tier |
|------|--------|-------|------|
| `utils/config.py` | `COMMAND_PREFIX = "/"` | 1 | Core |
| `ui/handlers/agent_command_handler.py` | A2A scanner regex | 1 | Core |
| `ui/handlers/command_handler.py` | Help text strings | ~8 | Core |
| `ui/handlers/task_handler.py` | Usage strings | ~17 | Handlers |
| `ui/handlers/collab_handler.py` | Usage strings | ~8 | Handlers |
| `ui/handlers/session_handler.py` | Usage strings | ~2 | Handlers |
| `ui/handlers/review_handler.py` | Usage strings | ~5 | Handlers |
| `prompts/system/crabcakes-commands.md` | Full rewrite | ~120 | Prompts |
| `prompts/system/collab.md` | Significant update | ~50 | Prompts |
| `prompts/system/project-awareness.md` | A2A section | ~5 | Prompts |
| `prompts/system/crabcakes-context.md` | Backtick section | ~2 | Prompts |
| `prompts/cc-task-planning.md` | References | ~6 | Prompts |
| `docs/ARCHITECTURE.md` | Section titles/descriptions | ~10 | Docs |
| `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md` | Format references | ~15 | Docs |
| `tests/test_command_handler.py` | Test inputs | ~34 | Tests |
| `tests/test_agent_command_handler.py` | Test inputs | ~46 | Tests |
| **Total** | | **~330 lines** | |

---

## What Does NOT Change

These files/areas are **not affected** by this migration:

- **Markdown parsing** (`utils/markdown.py`) — backticks for inline code are markdown spec, not our command system
- **Fenced code blocks** (`utils/block_parser.py`) — triple backticks are markdown spec
- **Syntax highlighting** (`utils/syntax_highlight.py`) — unrelated
- **Crabcard parsing** (`utils/crabcard_parser.py`) — uses fenced blocks (```crabcard), not command prefix
- **Chat rendering** (`ui/views/chat_bubble.py`) — no command-specific code
- **Agent runtime** (`agent/runtime.py`) — sends text, doesn't parse commands
- **Any agent response formatting** — agents still use markdown with backticks for code. Only command invocations change.
- **The quoted payload format** — `"payload"` stays the same. Only the prefix before `command` changes.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| File paths starting with `/` trigger command parsing | Low | Low — unknown commands pass through as `handled=False` | Already handled: `process_input()` returns `handled=False` for unknown commands |
| Agents trained on old prompts generate backtick commands | Medium | Medium — commands silently ignored until re-prompted | Deploy prompt updates simultaneously with code. Old agents get new prompts on next session. |
| Users accustomed to backtick | Low | Low — slash is more intuitive, faster to learn | Mention in release notes |
| `/` in agent response text matches A2A scanner | Low | Low — scanner checks for registered command names after match | Already filtered: scanner checks `cmd in self._command_names` |

---

## Implementation Order

1. **Change `COMMAND_PREFIX` in config** — one character, instant effect
2. **Update A2A scanner regex** — one line in `agent_command_handler.py`
3. **Update handler help strings** — `command_handler.py`, `task_handler.py`, `collab_handler.py`, `session_handler.py`, `review_handler.py`
4. **Rewrite agent prompts** — `crabcakes-commands.md`, `collab.md`, `project-awareness.md`, `crabcakes-context.md`, `cc-task-planning.md`
5. **Update test assertions** — `test_command_handler.py`, `test_agent_command_handler.py`
6. **Update architecture docs** — `ARCHITECTURE.md`, `A2A_QUOTED_PAYLOAD_SPEC.md`
7. **Run full test suite** — verify zero regressions
8. **Visual test** — type `/help`, `/status`, `/ask @Coder "hello"` in CrabCakes
9. **Commit and push**

---

## Acceptance Criteria

- [ ] `COMMAND_PREFIX = "/"` in `utils/config.py`
- [ ] A2A scanner detects `/command @Agent "payload"` in agent responses
- [ ] A2A scanner no longer requires closing delimiter
- [ ] All help text shows `/command` format
- [ ] All agent prompts teach `/command` format
- [ ] `collab.md` no longer mentions "opening/closing backtick"
- [ ] `crabcakes-commands.md` opens with "All commands start with a slash"
- [ ] All tests pass with `/command` inputs
- [ ] No references to backtick as command prefix in code (comments/docs除外)
- [ ] Markdown backticks for code rendering work unchanged
- [ ] `/help` command displays correct output
- [ ] `/ask @Agent "payload"` routes correctly
- [ ] Unknown `/` inputs (e.g. `/home/q/...`) pass through as `handled=False`
- [ ] `ARCHITECTURE.md` updated with slash prefix references

---

## Why Now

1. **The cost only grows.** Every prompt, test, and doc written with backtick syntax is another line to migrate later.
2. **The plumbing already exists.** `set_prefix()` and `COMMAND_PREFIX` were built for exactly this scenario.
3. **The prompts are about to be deployed.** If we migrate before agents are trained on the command system, we teach the right syntax from day one.
4. **The table spec is next.** Tables in chat will make backtick-heavy markdown more common, increasing the collision surface.

The migration is mechanical, the architecture supports it, and the benefit is permanent. No reason to wait.
