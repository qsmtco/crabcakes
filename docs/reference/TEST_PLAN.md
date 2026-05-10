# CrabCakes Command System — Test Plan

> **Status: REFERENCE** — Test plan for the command system. Tests exist and pass.

**518 automated tests + manual GTK UI verification**

---

## Phase 0 — Foundation

### Automated tests (run first)
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_command_models.py tests/test_command_handler.py -v
```
**Expected:** 56+ tests pass — Command/CommandResult data models, prefix detection, @mention resolution, flag parsing, registry.

### Manual: Prefix detection
1. Open a project tab in CrabCakes
2. Type `hello world` (no prefix) → goes to gateway as normal text
3. Type `` `help `` → command intercepted, no gateway send
4. Type `` `ask @Debugger hello `` → command intercepted, `hello` goes to `@Debugger` as PM message

### Manual: Unknown command passthrough
1. Type `` `unknowncmd arg1 arg2 `` → `handled=False` → sent to gateway as plain text

---

## Phase 1 — Collaboration Commands

### Automated tests
```bash
python3 -m pytest tests/test_command_handler.py::TestMentionResolution -v
python3 -m pytest tests/test_command_handler.py::TestCommandExecution -v
```
**Expected:** All pass. `ask`, `delegate`, `stop`, `tell` registered and parsing correctly.

### Manual: `ask`
1. Open project tab with member `@Debugger`
2. Type `` `ask @Debugger — what's the current status? ``
3. **Expect:** Echo bubble shows "→ @Debugger: what's the current status?"
4. **Expect:** Agent `@Debugger` receives the question via gateway
5. **Expect:** Buffer cleared immediately

### Manual: `delegate`
1. Type `` `delegate @Coder — implement the feature ``
2. **Expect:** Echo bubble "Delegated to @Coder: implement the feature"
3. **Expect:** `@Coder` receives task via gateway

### Manual: `stop`
1. Type `` `stop @Debugger ``
2. **Expect:** Echo bubble "Stopped @Debugger"
3. **Expect:** `@Debugger` receives `stop` signal via gateway

### Manual: `tell`
1. Type `` `tell @Qat — found a bug in the parser ``
2. **Expect:** Echo bubble "→ @Qat: found a bug in the parser"
3. **Expect:** `@Qat` receives message via gateway

### Edge cases
- `` `ask @UnknownAgent — hello `` → Error: "Unknown agent: UnknownAgent"
- `` `ask `` (no args) → Error: "No target agent. Usage: `ask @agent — question"
- `` `ask @Debugger`` (no body) → Echo with empty forward_text, agent receives empty message
- Type from non-project tab → "No target agent" or similar error

---

## Phase 2 — Task Commands

### Automated tests
```bash
python3 -m pytest tests/test_tasks.py -v
```
**Expected:** 7 tests pass — Task dataclass, TaskStore CRUD, label dicts.

### Manual: `task` — create a task
1. Open project tab with member `@Debugger`
2. Type `` `task @Debugger — implement auth flow ``
3. **Expect:** Task card appears in chat (created action)
4. **Expect:** Task ID shown (8-char hex string)
5. **Expect:** Status = "⏳ Pending", Priority = "🟡 Medium", Assigned = "@Debugger"

### Manual: `start`
1. Run `python3 -c "from models.task import task_store; print([t.id for t in task_store.list_all()])"` to get a task ID
2. Type `` `start <task_id> `` (use the ID from step 1)
3. **Expect:** Task card with "updated" action
4. **Expect:** Status changes to "🔄 In Progress"

### Manual: `done`
1. Type `` `done <task_id> ``
2. **Expect:** Task card with "updated" action
3. **Expect:** Status = "✅ Done"

### Manual: `blocked`
1. Type `` `blocked <task_id> — reason: API key missing ``
2. **Expect:** Task card shows "🚫 Blocked"
3. **Expect:** Blocked reason preserved

### Manual: `cancel`
1. Type `` `cancel <task_id> ``
2. **Expect:** Task card shows "❌ Cancelled"

### Manual: `assign`
1. Type `` `assign <task_id> @Qat ``
2. **Expect:** Task card shows updated "assigned_to" to @Qat

### Manual: `priority`
1. Type `` `priority <task_id> critical ``
2. **Expect:** Task card shows "🆘 Critical" priority
3. Type `` `priority <task_id> low `` → "🟢 Low"

### Manual: `tasks` — list all
1. Type `` `tasks ``
2. **Expect:** Text list of all tasks with IDs, titles, status, priority
3. **Expect:** Empty message "No tasks yet." if no tasks exist

### Edge cases
- `` `done nonexistent-id `` → "Task not found: nonexistent-id"
- `` `priority <task_id> invalid `` → "Invalid priority. Use: low, medium, high, critical"
- `` `start `` (no args) → "Usage: `start <task_id>"

---

## Phase 3 — Review Layer

### Automated tests (run first)
```bash
python3 -m pytest tests/test_git_ops.py tests/test_diff_parser.py tests/test_review_state.py -v
```
**Expected:** 20+ tests pass — Git operations against temp repos, diff parsing, ReviewState dataclass.

### Manual: `review` — start review session
**Prerequisite:** Open project tab with a real git repository project (e.g. `~/projects/crabcakes` itself).

1. Open project tab for a git-backed project
2. Type `` `review ``
3. **Expect:** "Starting review..." text response
4. **Run in terminal:** `cd ~/projects/crabcakes && git log --oneline -1` — should show new "review checkpoint" commit
5. **Expect:** ReviewBar appears at top of chat area (mode dropdown shows "review", status shows "No active session" or similar)

### Manual: `check` — check changes
1. Make a change to any file in the project (e.g. add a comment to a .py file)
2. Type `` `check ``
3. **Expect:** "Checking changes..." text response
4. **Expect:** Diff summary card appears in chat showing changed files
5. **Expect:** Per-file diff cards with syntax-highlighted hunks (+ green, - red)
6. **Expect:** Accept All / Reject All buttons on summary card
7. **Expect:** Accept File / Reject File buttons on each file card

### Manual: `accept` — accept changes
1. After `check` shows diffs, type `` `accept `` or `` `accept approved by PM ``
2. **Expect:** "Accepting changes..." text response
3. **Run:** `git log --oneline -1` → new commit with "approved by PM" message (or "approved")
4. **Expect:** ReviewBar resets to idle state
5. **Expect:** ✅ success card in chat

### Manual: `reject` — reject changes
1. Make another change to a project file
2. Type `` `review `` to start new session
3. Type `` `check `` to see diffs
4. Type `` `reject needs tests ``
5. **Expect:** Files revert to checkpoint SHA
6. **Run:** `git status` → clean
7. **Expect:** Rejection message sent to project members via gateway
8. **Expect:** ❌ info card in chat

### Edge cases
- `` `check `` without active review → "No active review session" or ReviewHandler returns early
- `` `review `` in non-project tab → "Open a project tab first"
- Project is not a git repo → auto-initializes with `git init`, "Initialized git repo for review" message

---

## Phase 4 — Project Query Commands

### Automated tests
```bash
python3 -m pytest tests/test_tasks.py tests/test_projects.py -v
```

### Manual: `status`
1. Open project tab with members
2. Create a few tasks via `` `task ``
3. Type `` `status ``
4. **Expect:** Text response with:
   - Project name
   - Member count
   - Task breakdown (pending, in progress, blocked, done)
   - Review state (active or not started)
   - Solo DM target (none or agent name)

### Manual: `agents`
1. Type `` `agents `` in project tab
2. **Expect:** List of all members with session keys
3. **Expect:** (solo DM target) marker shown for whichever member is targeted

### Manual: `cost`
1. Type `` `cost `` in project tab
2. **Expect:** Table with placeholder agent names, token counts, costs
3. **Expect:** Note at bottom: "Cost data requires OpenClaw usage tracking to be enabled."

### Edge cases
- `` `status `` from non-project tab → "Open a project tab to check status"
- `` `agents `` from non-project tab → "Open a project tab to list agents"

---

## Full Test Suite

Run everything:
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/ -x -q
```
**Expected:** 518 passed in ~3s

Run without `-x` (full run even if one fails):
```bash
python3 -m pytest tests/ -q
```

---

## What to look for

### GTK UI checks
- All bubbles appear immediately (no lag after typing)
- Command prefix `` ` `` not shown in sent message
- Error messages appear as text bubbles (red/muted style)
- Task cards render with emoji status badges
- ReviewBar appears/disappears correctly based on review state
- Diff cards collapse on click, expand on second click

### Error handling
- `` `ask @Nobody `` → shows "Unknown agent" error bubble
- `` `done bad-id `` → shows "Task not found" error bubble
- `` `priority abc123 high `` → validates priority level
- Typing from non-project tab → appropriate error for status/agents/cost/review/check/accept/reject

### Wire integrity
- `gw.send_message()` is called for Phase 1 commands (ask/delegate/stop/tell) → check via mock or network inspection
- `` `help `` shows all 20 commands in formatted list
- `` `help ask `` → shows help text for `ask` command specifically