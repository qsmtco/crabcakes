# CrabCakes Commands Reference

You are working inside CrabCakes, a project management chat interface. These commands are typed in the **project feed** (the chat input). They are NOT shell/terminal commands — do not run them in a terminal.

All commands start with a backtick (`` ` ``).

---

## Syntax

- `` `command arguments `` — type in the project feed
- `@agent` — mention an agent by name (e.g. `@Coder`, `@QTR`)
- `#task` — reference a task by number (e.g. `#1`, `#3`)
- `— text` — freeform body text after the em-dash

---

## Collaboration

| Command | Args | Description |
|---------|------|-------------|
| `` `ask `` | `@agent — question` | Ask an agent a question. Response appears in feed. |
| `` `delegate `` | `@agent — message` | Delegate work to an agent (higher priority). |
| `` `tell `` | `@agent — info` | Share information with an agent. No response expected. |
| `` `stop `` | (none) | Stop current agent activity. |

Aliases: `` `ask `` = `` `a ``, `` `delegate `` = `` `d ``

## Tasks

| Command | Args | Description |
|---------|------|-------------|
| `` `task `` | `@agent — description` | Create a task assigned to an agent. |
| `` `start `` | `#task` | Start working on a task. |
| `` `done `` | `#task — notes` | Mark task complete. |
| `` `blocked `` | `#task — reason` | Report a blocker. |
| `` `cancel `` | `#task` | Cancel a task. |
| `` `tasks `` | (none) | Show all tasks. |
| `` `assign `` | `#task @agent` | Reassign a task. |
| `` `priority `` | `#task level` | Set priority (low/medium/high/critical). |

Aliases: `` `task `` = `` `t ``

## Review

| Command | Args | Description |
|---------|------|-------------|
| `` `review `` | (none) | Create a git checkpoint. |
| `` `check `` | (none) | Show diff since checkpoint. |
| `` `accept `` | `[--file path]` | Accept changes (all or one file). |
| `` `reject `` | `— reason` | Reject all pending changes. |

## Project

| Command | Args | Description |
|---------|------|-------------|
| `` `status `` | `[--verbose]` | Project status summary. |
| `` `agents `` | (none) | List project agents. |
| `` `cost `` | (none) | Spending summary. |

Aliases: `` `status `` = `` `s ``

## Utility

| Command | Args | Description |
|---------|------|-------------|
| `` `help `` | `[command]` | List commands or help for one. |

Aliases: `` `help `` = `` `? ``

---

## Important Reminders

- These are **CrabCakes backtick commands**, not shell commands.
- To create tasks, use `` `task @agent — description `` in the project feed.
- Do NOT attempt `task add` in a terminal — that command does not exist.
- `@mentions` in commands route to specific agents; they do NOT trigger @mention notifications.
