# CrabCakes Commands Reference

These are **CrabCakes slash commands**, typed in the project feed chat input. They are NOT shell/terminal commands — do not run them in a terminal.

All commands start with `/`. Syntax: `/command args`, `@agent` mentions, `#task` refs, `— text` for freeform body.

## Quick reference

| Cmd | Args | What |
|-----|------|------|
| `/ask` | `@agent — q` | Ask agent a question. Alias `/a`. |
| `/delegate` | `@agent — task` | Assign work. Alias `/d`. |
| `/tell` | `@agent — info` | Share info, no response expected. |
| `/stop` | (none) | Stop current agent. |
| `/task` | `@agent — desc` | Create task. Alias `/t`. |
| `/start` | `#task` | Begin task. |
| `/done` | `#task — notes` | Complete. |
| `/blocked` | `#task — reason` | Report blocker. |
| `/cancel` | `#task` | Cancel. |
| `/tasks` | (none) | List all. |
| `/assign` | `#task @agent` | Reassign. |
| `/priority` | `#task level` | Set low/med/high/critical. |
| `/review` | (none) | Git checkpoint. |
| `/check` | (none) | Show diff since checkpoint. |
| `/accept` | `[--file path]` | Accept changes. |
| `/reject` | `— reason` | Reject all. |
| `/status` | `[--verbose]` | Project status. Alias `/s`. |
| `/agents` | (none) | List project agents. |
| `/cost` | (none) | Spending summary. |
| `/help` | `[command]` | Help. Alias `/?`. |

**Do NOT** attempt `/task add` in a terminal — that command does not exist. `@mentions` in commands route to specific agents; they do NOT trigger @mention notifications.

## Crabcards — Project Feed Cards

When you modify project files, emit a crabcard so the PM can review in the Project Feed.

### Format

    ```crabcard
    type: diff
    title: Short description
    file: path/to/file.py
    additions: 5
    deletions: 2
    ---
    - old line
    + new line
    ```

### Required
- `type` — always `diff` when changing files
- `title` — short description

### Optional
- `file` — relative path
- `additions` / `deletions` — line counts
- `commit_sha`, `task_id`

### When to emit

| Action | Card type | Required? |
|--------|-----------|-----------|
| Write/modify a file | `diff` | **Yes** — include actual diff |
| Delete a file | `diff` | **Yes** — show removed lines |
| Start/complete a task | `agent_action` | Optional |
| Decision or finding | `agent_action` | Optional |

Do NOT emit for `file_created/modified/deleted` (CrabWatch detects), `git_commit` (auto), `system` (internal).

### Diff body
Unified diff with `+`/`-` prefixes. Context lines have no prefix.

    - def old(): return None
    + def new(): return True
