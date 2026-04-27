# PROPOSAL: Extract Command Handlers from window.py

**Date:** 2026-04-27
**Author:** Qaster
**Status:** Proposed — Awaiting Captain JAQx Approval
**Severity:** Architecture violation — must fix before proceeding

---

## 1. The Problem

**window.py contains 518 lines of command handler logic that belongs in `ui/handlers/`.**

Per ARCHITECTURE.md Section 2:

> "The `ui/handlers/` directory contains self-contained logic modules extracted from `window.py`. This is not a suggestion — it is the architectural law. Every piece of new behavior must live in a handler, not in `window.py`."

Per ARCHITECTURE.md Section 3.21a:

> `ui/handlers/command_handler.py` — **Backtick Command Parser** — owns: CommandRegistry, command prefix, `@mention` resolution.

The command handler implementations (`_cmd_task`, `_cmd_done`, `_cmd_start`, `_cmd_blocked`, `_cmd_cancel`, `_cmd_tasks`, `_cmd_assign`, `_cmd_priority`, `_cmd_review`, `_cmd_check`, `_cmd_accept`, `_cmd_reject`, `_cmd_status`, `_cmd_agents`, `_cmd_cost`, `_cmd_help`, `_cmd_session`, plus helpers `_session_list`, `_session_switch`, `_short_session_key`) all live in `window.py` lines 403–920.

**window.py should only wire** (register commands with references to handler methods). It should not **implement** them.

### What's in window.py that shouldn't be:

| Lines | Content | Count |
|-------|---------|-------|
| 403–426 | `_cmd_help` | 24 lines |
| 427–561 | `_cmd_session` + `_session_list` + `_session_switch` + `_short_session_key` | 135 lines |
| 562–595 | `_cmd_ask`, `_cmd_delegate`, `_cmd_stop`, `_cmd_tell` | 34 lines |
| 596–721 | `_cmd_task`, `_cmd_done`, `_cmd_start` | 126 lines |
| 673–795 | `_cmd_blocked`, `_cmd_cancel`, `_cmd_tasks`, `_cmd_assign`, `_cmd_priority` | 123 lines |
| 796–837 | `_cmd_review`, `_cmd_check`, `_cmd_accept`, `_cmd_reject` | 42 lines |
| 838–920 | `_cmd_status`, `_cmd_agents`, `_cmd_cost` | 83 lines |
| **Total** | | **~518 lines** |

### Why it matters:

1. **window.py is 1096 lines** — it should be a thin wiring layer
2. **Command logic can't be tested independently** — it's tangled with GTK widget state
3. **Any new command requires editing window.py** — violates open/closed principle
4. **Architecture drift compounds** — the next agent will follow this bad pattern

---

## 2. The Fix

### New file: `ui/handlers/task_handler.py`

**Responsibility:** All task-related command logic.

**Public API:**
```python
class TaskHandler:
    def __init__(self, on_display_card, on_display_text):
        """
        Args:
            on_display_card: callback(card: dict) — display a card in project feed
            on_display_text: callback(text: str) — display text in project feed
        """
    
    def cmd_task(self, cmd: Command) -> CommandResult
    def cmd_done(self, cmd: Command) -> CommandResult
    def cmd_start(self, cmd: Command) -> CommandResult
    def cmd_blocked(self, cmd: Command) -> CommandResult
    def cmd_cancel(self, cmd: Command) -> CommandResult
    def cmd_tasks(self, cmd: Command) -> CommandResult
    def cmd_assign(self, cmd: Command) -> CommandResult
    def cmd_priority(self, cmd: Command) -> CommandResult
```

**Dependencies:** `models.task` (TaskStore, Task, labels), `models.command` (Command, CommandResult). No GTK. No window. No gateway.

**Methods extracted from window.py:**
- `_cmd_task` → `TaskHandler.cmd_task`
- `_cmd_done` → `TaskHandler.cmd_done`
- `_cmd_start` → `TaskHandler.cmd_start`
- `_cmd_blocked` → `TaskHandler.cmd_blocked`
- `_cmd_cancel` → `TaskHandler.cmd_cancel`
- `_cmd_tasks` → `TaskHandler.cmd_tasks`
- `_cmd_assign` → `TaskHandler.cmd_assign`
- `_cmd_priority` → `TaskHandler.cmd_priority`

**Lines freed from window.py:** ~246

---

### New file: `ui/handlers/collab_handler.py`

**Responsibility:** Collaboration command logic (ask, delegate, stop, tell).

**Public API:**
```python
class CollabHandler:
    def cmd_ask(self, cmd: Command) -> CommandResult
    def cmd_delegate(self, cmd: Command) -> CommandResult
    def cmd_stop(self, cmd: Command) -> CommandResult
    def cmd_tell(self, cmd: Command) -> CommandResult
```

**Dependencies:** `models.command` only. No GTK. No window.

**Lines freed from window.py:** ~34

---

### New file: `ui/handlers/session_handler.py`

**Responsibility:** Session switching command logic.

**Public API:**
```python
class SessionHandler:
    def __init__(self, agent_manager=None, project_handler=None):
        """
        Args:
            agent_manager: AgentManager for session lookups
            project_handler: ProjectHandler for session updates
        """
    
    def set_agent_manager(self, agent_mgr) -> None
    def set_project_handler(self, project_handler) -> None
    def cmd_session(self, cmd: Command) -> CommandResult
```

**Dependencies:** `models.command`, `models.agents` (AgentManager). No GTK. No window.

**Methods extracted from window.py:**
- `_cmd_session` → `SessionHandler.cmd_session`
- `_session_list` → `SessionHandler._session_list` (private)
- `_session_switch` → `SessionHandler._session_switch` (private)
- `_short_session_key` → `SessionHandler._short_session_key` (private)

**Lines freed from window.py:** ~135

---

### Extend: `ui/handlers/review_handler.py`

Review commands (`_cmd_review`, `_cmd_check`, `_cmd_accept`, `_cmd_reject`) currently in window.py just resolve the project name from session key and delegate to `ReviewHandler`. Move these thin wrappers into `ReviewHandler` itself as command methods.

**New methods on ReviewHandler:**
```python
def cmd_review(self, cmd: Command, session_key: str) -> CommandResult
def cmd_check(self, cmd: Command, session_key: str) -> CommandResult
def cmd_accept(self, cmd: Command, session_key: str) -> CommandResult
def cmd_reject(self, cmd: Command, session_key: str) -> CommandResult
```

**Lines freed from window.py:** ~42

---

### Extend: `ui/handlers/project_handler.py`

Project commands (`_cmd_status`, `_cmd_agents`, `_cmd_cost`) need project awareness that already lives in `ProjectHandler`. Move these there.

**New methods on ProjectHandler:**
```python
def cmd_status(self, cmd: Command, session_key: str) -> CommandResult
def cmd_agents(self, cmd: Command, session_key: str) -> CommandResult
def cmd_cost(self, cmd: Command, session_key: str) -> CommandResult
```

**Lines freed from window.py:** ~83

---

### Move: `_cmd_help` into `command_handler.py`

`_cmd_help` queries the CommandRegistry which is already owned by `CommandHandler`. It belongs there.

**New method on CommandHandler:**
```python
def cmd_help(self, cmd: Command) -> CommandResult
```

**Lines freed from window.py:** ~24

---

## 3. What window.py Looks Like After

The `_register_commands` method becomes pure wiring:

```python
def _register_commands(self):
    # Collaboration
    ch = self._collab_handler
    self._command_handler.register_command("ask", ch.cmd_ask, aliases=["a"],
        help_text="Ask an agent a question")
    self._command_handler.register_command("delegate", ch.cmd_delegate, aliases=["d"],
        help_text="PM delegates to agent")
    self._command_handler.register_command("stop", ch.cmd_stop,
        help_text="Stop current collaboration")
    self._command_handler.register_command("tell", ch.cmd_tell,
        help_text="Share information with an agent")
    
    # Tasks
    th = self._task_handler
    self._command_handler.register_command("task", th.cmd_task, aliases=["t"],
        help_text="Create a task")
    self._command_handler.register_command("done", th.cmd_done,
        help_text="Mark task complete")
    self._command_handler.register_command("start", th.cmd_start,
        help_text="Start working on a task")
    # ... etc
    
    # Review
    rh = self._review_handler
    self._command_handler.register_command("review", rh.cmd_review,
        help_text="Start review checkpoint")
    # ... etc
    
    # Project
    ph = self._project_handler
    self._command_handler.register_command("status", ph.cmd_status, aliases=["s"],
        help_text="Project status")
    # ... etc
    
    # Utility
    self._command_handler.register_command("help", self._command_handler.cmd_help,
        aliases=["?"], help_text="List commands")
    self._command_handler.register_command("session", self._session_handler.cmd_session,
        help_text="Switch agent session")
```

**window.py shrinks from ~1096 lines to ~578 lines.** That's a 47% reduction.

---

## 4. Dependency Flow

```
window.py (wiring only)
  ├── creates → TaskHandler(on_display_card, on_display_text)
  ├── creates → CollabHandler()
  ├── creates → SessionHandler(agent_manager, project_handler)
  ├── wires   → ReviewHandler.cmd_review/check/accept/reject
  ├── wires   → ProjectHandler.cmd_status/agents/cost
  └── wires   → CommandHandler.cmd_help
```

All handlers depend only on models/ and utils/. No handler imports from window.py or ui/views/.

---

## 5. Execution Plan

### Step 1: Create `task_handler.py`
- Move 8 command methods from window.py → TaskHandler class
- TaskStore accessed via module-level import (same as current `task_store` global)
- Pure functions, no GTK

### Step 2: Create `collab_handler.py`
- Move 4 command methods from window.py → CollabHandler class
- Trivial — each is 5-10 lines, returns CommandResult

### Step 3: Create `session_handler.py`
- Move session switching logic + helpers from window.py → SessionHandler
- Needs AgentManager + ProjectHandler references (injected via setters, same pattern as existing handlers)

### Step 4: Extend `review_handler.py`
- Add 4 `cmd_*` methods that wrap existing `start_review()` etc.
- Each resolves project_name from session_key, then delegates

### Step 5: Extend `project_handler.py`
- Add 3 `cmd_*` methods for status/agents/cost
- Needs references to AgentListHandler (for name resolution) and TaskStore (for task counts)
- Inject via setters

### Step 6: Move `_cmd_help` to `command_handler.py`
- Already has access to the registry

### Step 7: Update `window.py`
- Replace all `_cmd_*` methods with handler references in `_register_commands()`
- Instantiate new handlers in `__init__`
- Wire dependencies via setters after gateway connect

### Step 8: Update `ARCHITECTURE.md`
- Add new handler sections (3.21e TaskHandler, 3.21f CollabHandler, 3.21g SessionHandler)
- Update handler list in directory structure
- Update window.py description to reflect reduced scope
- Update file inventory

---

## 6. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Commands break during extraction | Each handler is pure Python with CommandResult returns — testable without GTK |
| Session handler needs live references | Use setter injection, same as existing handlers |
| TaskStore is a global singleton | Keep it global — handlers import it directly |
| Review commands need project_name resolution | Pass session_key, handler resolves internally |

---

## 7. Acceptance Criteria

- [ ] window.py contains NO `_cmd_*` methods
- [ ] window.py is under 600 lines
- [ ] All commands work identically to before
- [ ] New handlers have no imports from `ui/views/` or `window.py`
- [ ] ARCHITECTURE.md updated with new handler sections
- [ ] `git grep "_cmd_" ui/window.py` returns zero results
