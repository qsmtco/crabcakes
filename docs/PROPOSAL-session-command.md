# Change Proposal: `session` Backtick Command for Project Tabs

**Date:** 2026-04-23
**Status:** Proposal — not yet implemented
**Author:** Qaster
**Scope:** CommandHandler, ProjectHandler, ChatHandler, models/command.py

---

## 1. Problem Statement

In multi-agent project tabs, individual agents do not have their own chat tabs. The right-click session menu (`session_menu.py`) that exists on agent tabs cannot be used because there is no agent tab to right-click on. There is currently **no way** — graphical or command-line — to change which session an agent uses within a project context.

Users working across platforms (Telegram, Discord, webchat) need to switch an agent's session so that subsequent project messages route to the correct conversation thread on the correct platform.

## 2. Proposed Solution

Add a new `session` backtick command with two sub-commands:

### 2.1 `session list @<agent>`

Lists all available sessions for the named agent within the current project context. Returns a formatted text response displayed in the project tab chat.

**Example:**
```
`session list @qaster
```

**Output (displayed as text in chat):**
```
Sessions for Qaster:
  1. main  ✓ (current)
  2. telegram:direct:7478874934
  3. discord:thread:123456
```

### 2.2 `session <session_ref> @<agent>`

Switches the named agent to use the specified session within the project. From that point on, messages directed to that agent (whether via fan-out or solo DM) route to the chosen session.

**Examples:**
```
`session 2 @qaster
`session telegram:direct:7478874934 @qaster
```

The `session_ref` argument accepts either:
- A **numeric index** (1-based, matching the `list` output)
- A **full or partial session key** (matched against the agent's sessions)

---

## 3. Architecture Alignment

### 3.1 Where Commands Live

Per `ARCHITECTURE.md` Section 8.6 (Handler Pattern) and the existing command registration in `window.py` (lines 351–383), commands are:

1. **Registered** in `window.py` via `self._command_handler.register_command(name, handler)`
2. **Handler methods** live in `window.py` as `_cmd_<name>(self, cmd: Command) -> CommandResult`
3. **Parsing** is owned by `CommandHandler` — `@mentions` are resolved before the handler receives the `Command`
4. **Result routing** is handled by `CommandHandler._dispatch_result()` and `ChatHandler`'s forward logic

This proposal follows the same pattern exactly.

### 3.2 Data Ownership

| Data | Owner | API Used |
|------|-------|----------|
| Agent sessions list | `AgentManager` | `get_sessions(agent_name) -> list[str]` |
| Agent name from session key | `AgentManager` | `get_name(session_key) -> str` |
| Project members | `ProjectHandler` | `get_project_members(project_name) -> list[str]` |
| Active project name | `ProjectHandler` | `get_active_project_name() -> str \| None` |
| Solo DM target | `ProjectHandler` | `get_solo_target() / set_solo_target()` |
| Session-to-project routing | `AgentRoutingTable` | `add() / remove()` |

**No new data structures are created.** All data is accessed through existing APIs.

### 3.3 Layer Separation

| Layer | Change? | Notes |
|-------|---------|-------|
| `models/` | No | Uses existing `Command`, `CommandResult` dataclasses |
| `gateway/` | No | No network changes |
| `utils/` | No | No utility changes |
| `ui/handlers/command_handler.py` | No | Already handles `@mention` resolution before handler receives `Command` |
| `ui/handlers/project_handler.py` | **Yes — minor** | Add `update_agent_session()` method |
| `ui/window.py` | **Yes** | Register the `session` command, add `_cmd_session()` handler |
| `ui/handlers/chat_handler.py` | **No** | Fan-out logic reads from `load_members()` — changing the session key in `members.json` automatically changes routing |

### 3.4 Thread Safety

All GTK calls dispatched via `GLib.idle_add()` where needed. The command handler runs on the GTK main thread (triggered by user input). `ProjectHandler` methods are main-thread-safe per architecture.

---

## 4. Detailed Design

### 4.1 New Method on `ProjectHandler`: `update_agent_session()`

```python
def update_agent_session(self, project_name: str, old_session_key: str, new_session_key: str) -> None:
    """Replace an agent's session key within a project's member list.

    Updates members.json and the routing table atomically.

    Args:
        project_name:     Project to update.
        old_session_key:  Current session key for the agent.
        new_session_key:  New session key to switch to.

    Raises:
        ValueError:       If old_session_key is not a member of the project.
    """
```

**Logic:**
1. Load current members via `load_members(project_name)`
2. Verify `old_session_key` is in the list (raise ValueError if not)
3. Replace `old_session_key` with `new_session_key` in the list
4. Save via `save_members(project_name, members)`
5. Rebuild routing table for this project (remove old, add new)
6. If solo target was the old key, update it to the new key

**Why on ProjectHandler:** Per architecture, ProjectHandler owns project membership and routing. This is its data.

### 4.2 New Method on `ProjectHandler`: `get_agent_session_in_project()`

```python
def get_agent_session_in_project(self, project_name: str, agent_name: str) -> str | None:
    """Return the session key that a named agent currently uses in a project.

    Cross-references project members with AgentManager sessions to find
    which of the agent's sessions is active in this project.

    Args:
        project_name:  Project to check.
        agent_name:    Display name of the agent.

    Returns:
        Session key, or None if the agent is not a member of this project.
    """
```

**Logic:**
1. Load project members via `load_members(project_name)`
2. Get agent's sessions via `AgentManager.get_sessions(agent_name)`
3. Return the intersection (the one member key that belongs to this agent)

### 4.3 Command Handler in `window.py`: `_cmd_session()`

```python
def _cmd_session(self, cmd: Command) -> CommandResult:
    """`session list @agent — list sessions | `session <ref> @agent — switch session"""
```

**Logic:**

1. Validate context: `cmd.source_session_key` must start with `"project:"` — session switching only makes sense in project tabs. If not, return error.

2. Extract project name from `cmd.source_session_key`.

3. Resolve `@mention` — already done by `CommandHandler` before handler receives `cmd`. The agent name is derived from `cmd.target_session_key` via `AgentManager.get_name()`.

4. If no `@mention` resolved → return error with usage text.

5. **Sub-command dispatch:**
   - First arg is `"list"` → call `_session_list()`
   - First arg is a session reference (number or string) → call `_session_switch()`
   - No args → return usage text

### 4.4 `_session_list()` Helper

```python
def _session_list(self, project_name: str, agent_name: str) -> CommandResult:
```

**Logic:**
1. Get all sessions for the agent: `self._agent_mgr.get_sessions(agent_name)`
2. Get the current session in the project: `self._project_handler.get_agent_session_in_project(project_name, agent_name)`
3. Format as numbered list with `✓` on the current session
4. Return `CommandResult(handled=True, response_text=formatted_list)`

### 4.5 `_session_switch()` Helper

```python
def _session_switch(self, project_name: str, agent_name: str, session_ref: str) -> CommandResult:
```

**Logic:**
1. Get all sessions for the agent: `self._agent_mgr.get_sessions(agent_name)`
2. Resolve `session_ref`:
   - If numeric → index into sessions list (1-based)
   - If string → find matching session key (exact match, or prefix match if unique)
3. If no match → return error listing available sessions
4. Get current session: `self._project_handler.get_agent_session_in_project(project_name, agent_name)`
5. If already on that session → return info message
6. Call `self._project_handler.update_agent_session(project_name, old_key, new_key)`
7. Return `CommandResult(handled=True, response_text=confirmation_message)`

### 4.6 Command Registration in `window.py`

```python
self._command_handler.register_command(
    "session",
    self._cmd_session,
    aliases=["s"],
    help_text="Switch agent session in project: `session list @agent | `session <ref> @agent",
)
```

---

## 5. Files Changed

| File | Change | Lines |
|------|--------|-------|
| `ui/handlers/project_handler.py` | Add `update_agent_session()` + `get_agent_session_in_project()` | ~40 lines |
| `ui/window.py` | Register `session` command + add `_cmd_session()`, `_session_list()`, `_session_switch()` | ~80 lines |
| `docs/ARCHITECTURE.md` | Document `session` command in command system section, update ProjectHandler public API | ~15 lines |
| `tests/test_command_handler.py` | Add tests for `session list` and `session switch` commands | ~60 lines |
| `tests/test_project_handler.py` | Add tests for `update_agent_session()` and `get_agent_session_in_project()` | ~40 lines |

**Total estimate:** ~235 lines across 5 files.

**Note:** The `help` command (`window.py:_cmd_help`) dynamically lists all registered commands from the `CommandRegistry`. Since the `session` command is registered via `register_command()` with `help_text`, it will **automatically appear** in the `` `help `` popup and `` `help session `` will show its description. No additional help-related code changes needed.

---

## 6. Files NOT Changed

| File | Why Not |
|------|---------|
| `models/command.py` | `Command` and `CommandResult` dataclasses already support everything needed |
| `ui/handlers/command_handler.py` | `@mention` resolution and command routing already work — no changes needed |
| `ui/handlers/chat_handler.py` | Fan-out reads from `load_members()` — changing the member key in `members.json` automatically changes routing |
| `ui/views/session_menu.py` | Right-click menus continue to work as-is |
| `ui/views/feedbar.py` | No visual changes |
| `gateway/client.py` | No network changes |
| `models/routing.py` | Used through existing `ProjectHandler` methods |
| `utils/projects.py` | `load_members()` / `save_members()` already support the use case |

---

## 7. Edge Cases

| Case | Behavior |
|------|----------|
| Command used in agent tab (not project tab) | Error: "Session switching is only available in project tabs" |
| Agent not a member of the project | Error: "@agent is not a member of this project" |
| Agent has only one session | `session list` shows one session; `session switch` works but is a no-op (already on that session) |
| Numeric index out of range | Error: "Invalid session index. Use `session list @agent` to see available sessions." |
| Partial session key matches multiple | Error: "Ambiguous session key. Matches: X, Y" |
| Partial session key matches zero | Error: "No matching session. Use `session list @agent` to see available sessions." |
| Switching to the already-active session | Info: "Already on session X" (no-op, not an error) |
| Project has solo DM target on the old session | `update_agent_session()` migrates solo target to new session |
| Gateway not connected | No special case — we're editing local routing, not sending messages |

---

## 8. What Does NOT Change

- Right-click on **agent tabs** (existing `session_menu.py`) continues to work unchanged
- Right-click on **project tabs** for agent targeting (broadcast vs. solo DM) continues to work unchanged
- `@mention` in input field for one-shot DMs continues to work unchanged
- Fan-out architecture — all project members still receive messages; only the session key for one agent changes
- `members.json` format — still a flat list of session keys; no schema change

---

## 9. Future Work (Out of Scope)

- **GUI for session switching in project tabs** — A dropdown or popover per agent in the project tab, similar to `session_menu.py`. The backtick command is the foundation; the GUI can reuse the same `ProjectHandler.update_agent_session()` method.
- **Session switching for agent tabs via command** — Currently out of scope since the right-click menu already handles this. Could be added later if desired.

---

*This proposal adheres to ARCHITECTURE.md: handler pattern (Section 8.6), callback-based composition, layer separation (models/ never imports ui/), existing APIs as single source of truth, and documentation updates required with any code change.*
