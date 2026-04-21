# CrabCakes Command System — Specification

**Date:** 2026-04-19
**Status:** Pre-build spec
**Depends on:** `docs/ARCHITECTURE.md`
**Namespace:** `` ` `` (backtick) prefix — configurable

---

## Overview

CrabCakes commands are triggered by a prefix character (default: backtick `` ` ``) at the start of a message. Commands are intercepted by `CommandHandler` before the message reaches the gateway. Unknown commands are passed through as plain text.

The prefix character is configurable via `utils/config.py` so it can be changed if it conflicts with user workflows.

**Namespace collision avoidance:** OpenClaw gateway uses `/` for its commands (`/approve`, `/status`, `/reasoning`, `/elevated`, `/exec`). CrabCakes uses `` ` ``. Zero collision.

---

## Architecture Compliance

### Module Placement

```
crabcakes/
├── ui/
│   └── handlers/
│       └── command_handler.py    # NEW — command parsing, routing, execution
├── models/
│   └── command.py                # NEW — Command dataclass, CommandResult, command registry
└── utils/
    └── config.py                 # UPDATED — add COMMAND_PREFIX setting
```

### Layer Rules

| Module | Imports | Does NOT import |
|--------|---------|-----------------|
| `models/command.py` | Nothing | No `ui/`, no `gateway/`, no GTK |
| `ui/handlers/command_handler.py` | `models/command.py`, `gateway/client.py` interface | No other handlers directly |
| `utils/config.py` | Nothing | No `ui/`, no GTK |

### Handler Rules (per ARCHITECTURE.md)

- CommandHandler does NOT import other handlers. Window wires cross-handler communication via callbacks.
- CommandHandler does NOT own GTK widgets. It owns command parsing and routing logic.
- All GTK operations dispatched via `GLib.idle_add()` when GLib module is provided.

---

## Data Model — `models/command.py`

### `Command` Dataclass

```python
@dataclass
class Command:
    name: str                    # e.g. "ask", "task", "done"
    args: list[str]              # positional arguments
    flags: dict[str, str]        # --flag value pairs
    raw_text: str                # original input after prefix
    source_session_key: str      # who sent it (agent or PM)
    target_session_key: str | None  # resolved target (for @agent mentions)
```

### `CommandResult` Dataclass

```python
@dataclass
class CommandResult:
    handled: bool                # True = command consumed, don't send to gateway
    response_text: str | None    # Text to display in chat (None = silent)
    response_card: dict | None   # Card data for special rendering (task cards, etc.)
    forward_to: str | None       # Session key to send a message to (for routing)
    forward_text: str | None     # Text to forward (if forward_to is set)
```

### Command Registry

```python
class CommandRegistry:
    """Maps command names to handler functions. Extensible."""

    def __init__(self):
        self._commands: dict[str, Callable[[Command], CommandResult]] = {}
        self._aliases: dict[str, str] = {}  # e.g. "t" → "task"

    def register(self, name: str, handler: Callable, aliases: list[str] = None)
    def get(self, name: str) -> Callable | None
    def list_commands(self) -> list[str]
    def get_help(self, name: str) -> str | None
```

**Extensibility:** New commands are added by calling `registry.register(name, handler_fn)`. No modification to CommandHandler internals needed. This supports future commands (review layer, task layer, etc.) without touching the command parsing code.

---

## Handler — `ui/handlers/command_handler.py`

### Responsibilities

1. Detect command prefix in user/agent input
2. Parse command name, arguments, `@agent` mentions, `--flags`
3. Look up command in registry
4. Execute command handler → get `CommandResult`
5. Route result: display in chat, forward to agent, or pass through to gateway

### Public API

```python
class CommandHandler:
    def __init__(
        self,
        gateway_client,            # for send_message()
        agent_manager,             # for resolving @agent to session_key
        project_handler,           # for project membership lookups
        GLib_module=None,          # for thread-safe GTK dispatch
        on_display_card=None,      # callback to render card in chat
        on_display_text=None,      # callback to render text in chat
    ):
        ...

    def process_input(self, session_key: str, text: str) -> CommandResult:
        """
        Main entry point. Called by ChatHandler before gateway send.

        If text starts with command prefix, parse and execute.
        If not a command, return CommandResult(handled=False).
        If command not found, return CommandResult(handled=False) — pass through.
        """

    def register_command(self, name: str, handler: Callable, aliases: list[str] = None, help_text: str = ""):
        """Register a new command. Called by window during setup."""

    def set_prefix(self, char: str):
        """Change the command prefix character. Default: ` (backtick)."""
```

### Processing Flow

```
User/Agent input text
       │
       ▼
CommandHandler.process_input(session_key, text)
       │
       ├─ text starts with prefix? ─── No ──→ check for plain @ mentions (see below)
       │                                         → ChatHandler sends to gateway normally
       │
       ├─ Plain @ mention routing (non-command messages):
       │   If text contains @ mentions but no command prefix:
       │     - Parse @ mentions from text
       │     - If mentions found (e.g. '@qtr hi') → route to those agents only
       │     - If no mentions found (e.g. 'hi') → route to all (existing default)
       │     - Note: '@' with no name is redundant — same as no @ (all members)
       │   This runs in ChatHandler.on_send() before fan-out decision
       │
       ├─ Parse: extract command name, args, @mentions, --flags
       │
       ├─ Lookup in registry ─── Not found ──→ return CommandResult(handled=False)
       │
       ├─ Resolve @agent mentions → session_keys via AgentManager
       │
       ├─ Execute command handler → CommandResult
       │
       └─ Return CommandResult
              │
              ├─ handled=True, forward_to set → send_message(forward_to, forward_text)
              ├─ handled=True, response_card set → on_display_card callback
              ├─ handled=True, response_text set → on_display_text callback
              └─ handled=False → pass through to gateway
```

### Wiring in `window.py`

CommandHandler is created and wired in `window.py` (the composition root), following the same pattern as all other handlers:

```python
# In window._build():
self._command_handler = CommandHandler(
    gateway_client=self._gw,
    agent_manager=self._agent_mgr,
    project_handler=self._project_handler,
    GLib_module=GLib,
    on_display_card=self._on_command_card,
    on_display_text=self._on_command_text,
)

# Register built-in commands
self._command_handler.register_command("ask", self._cmd_ask, aliases=["a"], help_text="Ask an agent a question")
self._command_handler.register_command("help", self._cmd_help, help_text="List available commands")
# ... etc.

# Wire into ChatHandler's on_send():
# ChatHandler calls self._command_handler.process_input(session_key, text)
# before self._gw.send_message()
```

### Integration with ChatHandler

`ChatHandler.on_send()` is modified to check CommandHandler before sending:

```python
# In ChatHandler.on_send(), before existing send logic:
result = self._command_handler.process_input(session_key, text)
if result.handled:
    if result.forward_to:
        self._gw.send_message(result.forward_to, result.forward_text)
    if result.response_card:
        self._on_display_card(result.response_card)
    if result.response_text:
        self._on_display_text(session_key, result.response_text)
    return  # don't send to gateway
# else: existing send logic (gateway, fan-out, etc.)
```

---

## Input Parsing Rules

### Command Syntax

```
<prefix><command> [@agent] [#task] [--flag value] [— text]
```

- **Prefix:** configurable, default `` ` `` (backtick)
- **Command:** alphanumeric word, case-insensitive
- **@agent:** optional agent mention, resolves to session_key
- **#task:** optional task number reference
- **--flag value:** optional flags
- **— text:** everything after ` — ` (em-dash with spaces) is the free-text body

### @ Mention Resolution

`@<agent_name>` or `@<partial_name>` or `@` (empty) resolves to session_key(s) via `AgentManager`.

- Empty: `@` → all project members (fan-out broadcast)
- Exact match: `@Debugger` → session key for agent named "Debugger"
- Partial match: `@debug` → session key for first agent whose name contains "debug" (case-insensitive)
- Multiple matches: return error text listing candidates
- No match: return error text "Unknown agent: @name"


`@` broadcast works for all collaboration commands (`ask`, `delegate`, `tell`) and task commands (`task`, `assign`).

### Parsing Examples

```
`ask @Debugger — what's causing the segfault?
→ Command(name="ask", target=Debugger, body="what's causing the segfault?")

`ask @ — what's the status on the rate limiter?
→ Command(name="ask", target=all_members, body="what's the status on the rate limiter?")

`delegate @Coder @Debugger — help with the memory leak
→ Command(name="delegate", targets=[Coder, Debugger], body="help with the memory leak")

`tell @Debugger — found the bug, fix is in auth_handler.py
→ Command(name="tell", target=Debugger, body="found the bug, fix is in auth_handler.py")

`task @Coder — implement JWT auth with refresh tokens
→ Command(name="task", target=Coder, body="implement JWT auth with refresh tokens")

`done #3 — tests passing
→ Command(name="done", task=3, body="tests passing")

`tasks
→ Command(name="tasks", no args)

`stop
→ Command(name="stop", no args

`status --verbose
→ Command(name="status", flags={"verbose": ""})
```

---

## Command Reference

### Collaboration Commands

| Command | Aliases | Args | Description |
|---------|---------|------|-------------|
| `` `ask `` | `` `a `` | `@agent — question` | Agent-to-agent question. Routes to target agent. Response appears in project feed. |
| `` `delegate `` | `` `d `` | `@agent — message` | PM delegates to agent. Higher priority than agent-initiated `/ask`. |
| `` `stop `` | | (none) | PM stops the current agent collaboration. |
| `` `tell `` | | `@agent — information` | One agent shares information with another. No response expected. Receiving agent incorporates the info into their context. |

### Task Commands

| Command | Aliases | Args | Description |
|---------|---------|------|-------------|
| `` `task `` | `` `t `` | `@agent — description` | Create a task card assigned to agent. |
| `` `done `` | | `#task — notes` | Mark task complete (transitions to Review). |
| `` `start `` | | `#task` | Start working on a task (transitions to In Progress). |
| `` `blocked `` | | `#task — reason` | Report a blocker. |
| `` `cancel `` | | `#task` | Cancel a task. |
| `` `tasks `` | | (none) | Render task summary card in project feed. |
| `` `assign `` | | `#task @agent` | Reassign a task to a different agent. |
| `` `priority `` | | `#task low\|medium\|high\|critical` | Set task priority. |

### Review Commands

| Command | Aliases | Args | Description |
|---------|---------|------|-------------|
| `` `review `` | | (none) | Start a review checkpoint. |
| `` `check `` | | (none) | Show diff of changes since checkpoint. |
| `` `accept `` | | [--file path] | Accept all changes (or single file). |
| `` `reject `` | | `— reason` | Reject all pending changes. |

### Project Commands

| Command | Aliases | Args | Description |
|---------|---------|------|-------------|
| `` `status `` | `` `s `` | [--verbose] | Project status summary card. |
| `` `agents `` | | (none) | List project agents and current state. |
| `` `cost `` | | (none) | Spending summary for this project. |

### Utility Commands

| Command | Aliases | Args | Description |
|---------|---------|------|-------------|
| `` `help `` | `` `? `` | [command] | List all commands or help for specific command. |

---

## Command Results in the Feed

### Text Results

Simple text responses rendered as normal chat bubbles from "CrabCakes":

```
CrabCakes: Unknown agent: @debugz. Did you mean @Debugger?
```

### Card Results

Structured responses rendered as special card widgets in the project feed:

**Task card:**
```
┌─────────────────────────────────────────────┐
│ 📋 Task #3 · @Coder · ○ Todo                │
│ Implement JWT auth with refresh tokens       │
│ [▶ Start] [↑ Priority] [✕ Cancel]           │
└─────────────────────────────────────────────┘
```

**Status card:**
```
┌─────────────────────────────────────────────┐
│ 📊 Project Status · kalshi-ata              │
│ Tasks: 12 total · 7 done · 3 in progress    │
│ Coder: ● Working on #11                      │
│ Debugger: ○ Idle                             │
│ [/tasks] [/agents] [/cost]                   │
└─────────────────────────────────────────────┘
```

**Help card:**
```
┌─────────────────────────────────────────────┐
│ ⌨ CrabCakes Commands                        │
│                                              │
│ `ask @agent — question   Ask an agent        │
│ `task @agent — desc      Create task         │
│ `done #task              Mark task done       │
│ `tasks                   Show all tasks       │
│ `status                  Project status       │
│ `help                    This list            │
│                                              │
│ 16 commands total. `help <cmd> for details.  │
└─────────────────────────────────────────────┘
```

Card CSS classes added to `ui/styles.py`:
```css
.cmd-card { /* base card style */ }
.cmd-card-header { /* title row */ }
.cmd-card-body { /* content area */ }
.cmd-card-actions { /* button row */ }
```

---

## Configuration — `utils/config.py` Addition

```python
# Command system configuration
COMMAND_PREFIX = "`"     # Default: backtick. Change to "/" or "." if preferred.
COMMAND_PARSE_EM_DASH = True  # Use " — " as body separator
```

---

## Error Handling

| Condition | Result |
|-----------|--------|
| Unknown command | `CommandResult(handled=False)` — passes through to gateway as plain text |
| Unknown `@agent` | `CommandResult(handled=True, response_text="Unknown agent: @name")` |
| Multiple `@agent` matches | `CommandResult(handled=True, response_text="Multiple agents match @name: Debugger, DebugPro")` |
| Command used outside project tab (collab/task commands) | `CommandResult(handled=True, response_text="This command only works in project tabs")` |
| Missing required args | `CommandResult(handled=True, response_text="Usage: `ask @agent — question")` |
| Command throws exception | `CommandResult(handled=True, response_text="Error: <message>")` |

---

## Thread Safety

- `process_input()` may be called from the GTK main thread (PM input) or from gateway thread (agent responses)
- All GTK operations (displaying cards/text) dispatched via `GLib.idle_add()`
- Command registry is read-only after initialization (no concurrent modification)
- `CommandResult` is a dataclass — immutable after creation

---

## Future Extensibility

The command registry pattern supports adding commands without modifying CommandHandler:

1. **Review layer** registers `` `review ``, `` `check ``, `` `accept ``, `` `reject ``
2. **Task layer** registers `` `task ``, `` `done ``, `` `tasks ``, etc.
3. **Agent collaboration** registers `` `ask ``, `` `stop ``, `` `delegate ``
4. **Plugins** could register custom commands in the future

Each layer's handler file registers its commands during window setup. No cross-handler imports needed.

---

## Phase Plan — Build Phase 0: Command System

This should be built first (before agent runtime, review layer, task layer) because all three depend on the `/` command system.

### Step 0.1 — Data Models

1. Create `models/command.py` — `Command`, `CommandResult`, `CommandRegistry`
2. Write `tests/test_command_models.py`
3. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Registry can register commands, parse `@mentions`, and return `CommandResult` dataclasses.

### Step 0.2 — Command Handler

1. Create `ui/handlers/command_handler.py`
2. Add `COMMAND_PREFIX` to `utils/config.py`
3. Wire into `ui/handlers/chat_handler.py` — call `process_input()` before `send_message()`
4. Wire into `ui/window.py` — create handler, register initial commands, connect callbacks
5. Write `tests/test_command_handler.py`
6. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Type `` `help `` in any chat tab → help card appears in feed. Type `` `ask @Debugger — test `` → message routed to Debugger. Unknown commands pass through to gateway.

### Step 0.3 — Help + Stub Commands

1. Implement `` `help `` command (full command list card)
2. Implement stub handlers for all 16 commands (return "not yet implemented" cards)
3. Add card CSS to `ui/styles.py`
4. Add card rendering to `ui/views/chat_bubble.py`
5. Update `docs/ARCHITECTURE.md`

**Checkpoint:** All 16 commands recognized and return a response. `` `help `` shows the full list. Unrecognized commands pass through. Gateway `/` commands unaffected.

---

*This spec covers the command parsing, routing, and registry system. Individual command implementations (task management, review, collaboration) are documented in their respective spec files.*
