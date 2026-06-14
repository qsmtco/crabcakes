# Command Reference

CrabCakes supports slash commands typed directly in the chat input. Commands are parsed by `CommandHandler` (in `ui/handlers/command_handler.py`) and dispatched to the appropriate handler. Commands only work when typed at the beginning of a message (must start with `/`).

## Command Syntax Rules

### Basic Format

```
/command @Agent "payload"
```

- **Commands start with `/`** at the beginning of the message.
- **Agent mentions use `@AgentName`** (case-insensitive, prefix matching supported with 2+ characters).
- **Payloads must be quoted** using double quotes: `"your message here"`.
- **Max one `@mention` per command**. Multiple mentions produce an error.
- **Payloads are capped at 4096 characters** (4K) per the A2A Quoted Payload Spec.
- **Unrecognized commands are passed through** as regular messages — they are not errors.

### Payload-Free Commands

Some commands do not require a quoted payload. These are: `stop`, `tasks`, `review`, `check`, `accept`, `reject`, `status`, `agents`, `cost`, `help`, `done`, `start`, `blocked`, `cancel`.

### Implicit Ask Shorthand

Typing `@Agent message` (without a `/` prefix) is automatically interpreted as `/ask @Agent "message"`. This is a convenience shortcut for the most common collaboration command.

### Quoted Payload Parsing

Payloads use the A2A Quoted Payload Spec:
- Payload starts after `@Agent ` and must begin with `"`.
- Escaped quotes inside payloads are supported (`\"`).
- Missing closing `"` produces: `Unclosed quote — missing closing "`.
- Empty payload (`""`) produces: `Empty payload — provide a message`.

### Flag Parsing

Flags use `--flag value` or `--flag` (boolean) syntax:
```
/command @Agent "payload" --verbose
/command @Agent "payload" --priority high
```

Duplicate flags overwrite the previous value (with a warning log).

### Email Safety

Tokens that look like email addresses (e.g. `user@example.com`) are never treated as `@mentions` — they are preserved as regular text.

---

## Help Command

### `/help` or `/?`

Lists all registered commands with their aliases.

```
/help
```

For specific command help:

```
/help ask
```

---

## Project Commands

These commands work inside project tabs (session keys starting with `project:`).

### `/status`

Shows a project status summary including member count, task counts (pending/in-progress/blocked/done), review state, and solo DM target.

```
/status
```

**Example output:**
```
Project: my-app
Members: 3
Tasks: 2 pending, 1 in progress, 0 blocked, 4 done
Review: active
Solo DM: none
```

### `/agents`

Lists all project members and their session keys. The current solo DM target is marked.

```
/agents
```

**Example output:**
```
Members in my-app:

• @Coder — special:coder
• @Debugger — special:debugger
• @Qaster — agent:qaster:telegram:direct:123 (solo DM target)
```

### `/cost`

Shows a spending summary for the current project's members. Note: detailed cost data requires OpenClaw usage tracking to be enabled on the gateway side.

```
/cost
```

### Solo DM

Solo DM is controlled per-project via the right-click context menu on the project tab, not via a slash command. Right-click the project tab to see a menu of project members. Select one to switch to solo DM mode (only that agent receives messages), or select "All" to return to broadcast mode.

The solo DM state is tracked in `ProjectHandler._solo_targets` as a per-project `dict[str, str | None]`.

---

## Collaboration Commands

These commands route messages between agents within project tabs. They are handled by `CollabHandler` (in `ui/handlers/collab_handler.py`).

### `/ask @Agent "question"`

Consult an agent for their expertise. The question is forwarded to the target agent.

```
/ask @Coder "How should I structure the database layer?"
```

**Broadcast variant:** Use `/ask @ "question"` to send to all project members.

**Shorthand:** `@Coder "question"` is automatically interpreted as `/ask`.

Aliases: `/a`

### `/delegate @Agent "task"`

Delegate a task to an agent. The task text is forwarded to the target agent.

```
/delegate @Debugger "Investigate the memory leak in parser.py"
```

Aliases: `/d`

### `/tell @Agent "information"`

Share information with an agent without expecting a response. The info is forwarded but no response is required.

```
/tell @Coder "The API endpoint changed to /v2/users"
```

### `/stop @Agent`

Send a stop signal to an agent. This tells the agent to stop the current collaboration.

```
/stop @Coder
```

**Payload rules:** This command is payload-free — no quoted payload required.

---

## Task Commands

Task commands are handled by `TaskHandler` (in `ui/handlers/task_handler.py`). Tasks are tracked in an in-memory `TaskStore` singleton (from `models/task.py`). Task IDs are sequential 8-character zero-padded strings (e.g. `00000001`).

### `/task @Agent "title"`

Create a new task assigned to the specified agent. The task appears as a card in the project tab and in the project feed.

```
/task @Coder "Implement user authentication"
```

Aliases: `/t`

### `/done <task_id>`

Mark a task as complete (status → `done`).

```
/done 00000001
```

Task IDs can be specified with or without a leading `#` (e.g. `#1` or `00000001`).

### `/start <task_id>`

Start working on a task (status → `in_progress`).

```
/start 00000002
```

### `/blocked <task_id> — "reason"`

Report a blocker on a task (status → `blocked`). The blocked reason is stored in the task's `blocked_reason` field.

```
/blocked 00000003 "Waiting on API documentation from backend team"
```

### `/cancel <task_id>`

Cancel a task (status → `cancelled`).

```
/cancel 00000004
```

### `/tasks`

List all tasks in the current session.

```
/tasks
```

**Example output:**
```
📋 Tasks

[00000001] Implement user authentication
    ✅ Done | ▬ Medium

[00000002] Fix navigation bug
    🔄 In Progress | ▬ High
```

### `/assign <task_id> @Agent`

Reassign a task to a different agent.

```
/assign 00000001 @Debugger
```

### `/priority <task_id> <level>`

Set a task's priority. Valid levels: `low`, `medium`, `high`, `critical`.

```
/priority 00000002 high
```

**Invalid priority values produce an error** listing the valid options.

---

## Review Commands

Review commands are handled by `ReviewHandler` (in `ui/handlers/review_handler.py`). They manage git-backed code review sessions for project tabs.

### `/review`

Start a review checkpoint. Creates a git checkpoint (auto-commits current state) so changes can be diffed.

```
/review
```

### `/review stop`

End the current review session. Switches review mode off and removes the ReviewBar widget.

### `/check`

Show the diff of all changes since the last checkpoint. Displays file-by-file diffs in the chat.

```
/check
```

### `/accept`

Accept all pending changes since the checkpoint. The changes are kept (committed).

```
/accept
```

To accept a single file: `/accept <filename>`.

### `/reject`

Reject all pending changes. The changes are reverted to the checkpoint state (git checkout). A rejection message is sent to all project member agents so they know their changes were rolled back.

```
/reject
```

---

## Session Commands

### `/session list @Agent` or `/session <ref> @Agent`

Switch an agent's active session within a project tab. Only works in project tabs.

```
/session list @Coder
```

Lists all sessions for the agent with a numbered list:

```
Sessions for Coder:
  1. special:coder  ✓ (current)
  2. special:coder:debug

Switch: /session <number> @Coder
```

Switch to a different session:

```
/session 2 @Coder
```

Aliases: `/s`

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in message input |
| `Ctrl+Space` | Push-to-talk voice input (start/stop recording) |
| `Ctrl+,` | Open Settings |

---

## Audit Report Format

When agents review code (especially the Debugger agent), they produce structured audit reports embedded in their chat messages. The format uses `## Audit Report` sections with `**Field:**` value lines.

### Structure

```
## Audit Report

**Task:** What the agent was asked to do
**File:** path/to/file.py:42
**Severity:** bug
**Bug:** Description of the mistake
**Expected:** What should have happened
**Actual:** What actually happened
**Root Cause:** Why the bug occurred
**Fix:** How to fix it
**Pattern:** Categorical pattern tag for the bug type
**Tests:** Test changes needed
```

### Severity Levels

| Severity | Description |
|----------|-------------|
| `bug` | A confirmed mistake that causes incorrect behavior |
| `issue` | A problem or concern that may cause issues |
| `suggestion` | An improvement recommendation (not a bug) |

### Pattern Tags

Pattern tags are free-text categorical labels (e.g. "off-by-one", "null-reference", "missing-error-handling"). They are used by the self-improvement system to identify recurring mistake types.

### Processing

Audit reports are parsed by `utils/audit_parser.py:extract_audit_reports()` into `AuditReport` dataclass instances. Reports with severity `bug` are automatically appended to the agent's bug journal at `.crabcakes/{role}-bugs.md`. The structured feedback processor (`utils/feedback_processor.py`) handles the full pipeline: extract → classify → append to journal.

---

## Command Registration

Commands are registered in `CommandHandler.__init__()` (see `ui/handlers/command_handler.py`). The `CommandRegistry` (from `models/command.py`) maps command names to handler callables with optional aliases and help text.

If a handler dependency is `None` (e.g. `collab_handler` not provided), the corresponding commands are not registered. This is used in test fixtures.
