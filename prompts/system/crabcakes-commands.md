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
| `/work` | `subcommand …` | Work Unit commands (see below). |
| `/review` | (none) | Git checkpoint. |
| `/check` | (none) | Show diff since checkpoint. |
| `/accept` | `[--file path]` | Accept changes. |
| `/reject` | `— reason` | Reject all. |
| `/status` | `[--verbose]` | Project status. Alias `/s`. |
| `/agents` | (none) | List project agents. |
| `/cost` | (none) | Spending summary. |
| `/help` | `[command]` | Help. Alias `/?`. |

## Work Unit commands (`/work`)

Work Units live in `.crabcakes/work.json`; `.crabcakes/tasks.md` is a generated summary, not a source of truth.

| Command | What |
|---------|------|
| `/work "Title"` | Create a Work Unit (status `draft`). |
| `/work list` | List all Work Units. |
| `/work start #N` | Start a Work Unit — validates its spec file + deps, then hands off to the Supervisor (implementation loop). |
| `/work done #N — notes` | Complete a Work Unit. |
| `/work blocked #N — reason` | Block a Work Unit. |
| `/work unblock #N` | Clear a blocker; restore to spec-ready (PM/Supervisor only). |
| `/work cancel #N` | Cancel a Work Unit. |
| `/work assign #N @agent` | Assign supervisor/builder/auditor. |
| `/work priority #N level` | Set priority (low/med/high/critical). |
| `/work spec-ready #N <path>` | Validate the spec path and mark ready (PM/Supervisor only). |
| `/work status #N` | Show a Work Unit's status. |

**Do NOT use `/task add` in a terminal — that command does not exist.** `@mentions` in commands route to specific agents; they do NOT trigger @mention notifications.

### Legacy aliases

The old task-centric commands are still accepted and route to the Work Handler:

| Legacy command | Maps to |
|----------------|---------|
| `/task` | `/work` (create) |
| `/tasks` | `/work list` |
| `/start` | `/work start` |
| `/done` | `/work done` |
| `/blocked` | `/work blocked` |
| `/cancel` | `/work cancel` |
| `/assign` | `/work assign` |
| `/priority` | `/work priority` |

The legacy `/t` alias for `/task` is **gone** (SPEC-TASK-SYSTEM-FULL-REDESIGN §5.1) — use `/work`.

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
