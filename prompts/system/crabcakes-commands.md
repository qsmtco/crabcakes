# CrabCakes Commands Reference

You are working inside CrabCakes, a project management chat interface. These commands are typed in the **project feed** (the chat input). They are NOT shell/terminal commands — do not run them in a terminal.

All commands start with a slash (`/`).

---

## Syntax

- `` /command arguments `` — type in the project feed
- `@agent` — mention an agent by name (e.g. `@Coder`, `@QTR`)
- `#task` — reference a task by number (e.g. `#1`, `#3`)
- `— text` — freeform body text after the em-dash

---

## Collaboration

| Command | Args | Description |
|---------|------|-------------|
| `` /ask `` | `@agent — question` | Ask an agent a question. Response appears in feed. |
| `` /delegate `` | `@agent — message` | Delegate work to an agent (higher priority). |
| `` /tell `` | `@agent — info` | Share information with an agent. No response expected. |
| `` /stop `` | (none) | Stop current agent activity. |

Aliases: `` /ask `` = `` /a ``, `` /delegate `` = `` /d ``

## Tasks

| Command | Args | Description |
|---------|------|-------------|
| `` /task `` | `@agent — description` | Create a task assigned to an agent. |
| `` /start `` | `#task` | Start working on a task. |
| `` /done `` | `#task — notes` | Mark task complete. |
| `` /blocked `` | `#task — reason` | Report a blocker. |
| `` /cancel `` | `#task` | Cancel a task. |
| `` /tasks `` | (none) | Show all tasks. |
| `` /assign `` | `#task @agent` | Reassign a task. |
| `` /priority `` | `#task level` | Set priority (low/medium/high/critical). |

Aliases: `` /task `` = `` /t ``

## Review

| Command | Args | Description |
|---------|------|-------------|
| `` /review `` | (none) | Create a git checkpoint. |
| `` /check `` | (none) | Show diff since checkpoint. |
| `` /accept `` | `[--file path]` | Accept changes (all or one file). |
| `` /reject `` | `— reason` | Reject all pending changes. |

## Project

| Command | Args | Description |
|---------|------|-------------|
| `` /status `` | `[--verbose]` | Project status summary. |
| `` /agents `` | (none) | List project agents. |
| `` /cost `` | (none) | Spending summary. |

Aliases: `` /status `` = `` /s ``

## Utility

| Command | Args | Description |
|---------|------|-------------|
| `` /help `` | `[command]` | List commands or help for one. |

Aliases: `` /help `` = `` /? ``

---

## Important Reminders

- These are **CrabCakes slash commands**, not shell commands.
- To create tasks, use `` /task @agent — description `` in the project feed.
- Do NOT attempt /task add in a terminal — that command does not exist.
- `@mentions` in commands route to specific agents; they do NOT trigger @mention notifications.

---

## Crabcards — Project Feed Cards

When you modify project files, you MUST emit a crabcard so the PM can review your changes in the Project Feed.

### Format

The crabcard block must start on its own line:

    ```crabcard
    type: diff
    title: Short description of the change
    file: path/to/file.py
    additions: 5
    deletions: 2
    ---
    - old line removed
    + new line added
    + another new line
    ```

### Required fields
- `type` — always `diff` when changing files
- `title` — short description of the change

### Optional fields
- `file` — path relative to project root
- `additions` / `deletions` — line counts
- `commit_sha` — if committing
- /task_id` — if related to a task

### When to emit

| Action | Card type | Required |
|--------|-----------|----------|
| Write or modify a file | `diff` | **Yes** — include actual diff in body |
| Delete a file | `diff` | **Yes** — show removed lines |
| Start or complete a task | `agent_action` | Optional |
| Report a decision or finding | `agent_action` | Optional |

### When NOT to emit
- `file_created` / `file_modified` / `file_deleted` — CrabWatch detects these automatically
- `git_commit` — created automatically when PM accepts or rejects a card
- `system` — internal use only

### Diff body format
Use unified diff format with `+` and `-` prefixes. Each changed line must start with `+` (added) or `-` (removed). Context lines (unchanged) have no prefix:

    - def old_function():
    -     return None
    + def new_function():
    +     return True

### Example — new file

    ```crabcard
    type: diff
    title: Added auth middleware
    file: src/middleware.py
    additions: 15
    deletions: 0
    ---
    +from auth import verify_token
    +
    +def middleware(request):
    +    token = request.headers.get("Authorization")
    +    if not verify_token(token):
    +        raise PermissionError("Invalid token")
    +    return request
    ```

### Example — modify existing file

    ```crabcard
    type: diff
    title: Fixed null check in user lookup
    file: src/users.py
    additions: 3
    deletions: 1
    ---
        def get_user(user_id):
    -     return db.query(user_id)
    +     user = db.query(user_id)
    +     if user is None:
    +         raise ValueError(f"User {user_id} not found")
    +     return user
    ```
