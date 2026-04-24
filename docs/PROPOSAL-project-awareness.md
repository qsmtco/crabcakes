# Project Awareness System — Formal Proposal

**Date:** 2026-04-24
**Author:** Qaster
**Status:** Implemented — Commit `2ce677d`
**Affects:** `utils/`, `models/`, `agent/`, `ui/handlers/`, `ui/views/`

---

## 1. Objective

When a project is opened via the Projects tab, inject project-awareness context into all agents working on that project. This includes the project's purpose, team roster, active tasks, git state, and persistent cross-session memory.

Replace the legacy `~/.config/crabcakes/projects/<name>/members.json` membership system with a richer, project-local `.crabcakes/` directory.

---

## 2. Design Principles

1. **Project-local config** — All project awareness data lives in `<project_root>/.crabcakes/`, not in `~/.config/`
2. **Auto-init on project open** — `.crabcakes/` is created automatically when a project is first opened
3. **Legacy migration** — Existing `crabcakes.md` at project root and `members.json` in `~/.config/` are auto-migrated
4. **Two delivery paths** — System prompt injection for special agents, message prefix for gateway agents
5. **Backwards compatible** — `load_members()`/`save_members()` in `utils/projects.py` delegate to new system
6. **Architecture compliance** — `models/` is pure data (no GTK, no network), `utils/` is pure Python, handlers follow Section 8.6

---

## 3. Directory Structure

```
<project_root>/
  .crabcakes/
    project.md              # Static project manifest (migrated from crabcakes.md)
    team.json               # Team roster with roles (replaces members.json)
    context.md              # Persistent cross-session memory — agents can read/write
    awareness.json          # Dynamic state (git, tasks, review mode) — auto-generated
```

### File Specifications

#### `project.md` — Static Manifest
Markdown file describing the project. Migrated from legacy `crabcakes.md` at project root. Skeleton generated on init if no legacy file exists.

Contains: purpose, stack, entry points, conventions, notes.

#### `team.json` — Team Roster
```json
{
  "members": [
    {
      "session_key": "special:coder",
      "name": "Coder",
      "role": "implementation",
      "can_write": true
    }
  ],
  "pm": {
    "name": "Captain JAQx",
    "id": "cli"
  }
}
```

Managed by: `+/−` buttons in Agents tab (auto), PM hand-edit (manual).

#### `context.md` — Cross-Session Memory
Free-form markdown. Agents can read/write (future: agent tool). 50KB cap with oldest-content-first truncation.

#### `awareness.json` — Dynamic State Snapshot
Auto-generated on project open. Includes git state, task summary, team size, tech stack, review mode.

---

## 4. New Modules

### `models/team.py` — Pure Data Model
- `TeamMember` dataclass: `session_key`, `name`, `role`, `can_write`
- `ProjectTeam` dataclass: `members` list, `pm_name`, `pm_id`
- Serialization: `to_dict()` / `from_dict()`
- Membership operations: `add_member()`, `remove_member()`, `has_member()`, `get_session_keys()`

**Architecture:** No GTK, no network, no file I/O. Pure data.

### `utils/project_awareness.py` — Awareness Builder
**Public API:**

| Function | Purpose |
|----------|---------|
| `get_crabcakes_dir(project_path)` | Return `.crabcakes/` path |
| `init_project_config(project_path, name, pm_name, pm_id)` | Initialize `.crabcakes/` with migration |
| `load_project_manifest(project_path)` | Read `project.md` |
| `load_team(project_path)` / `save_team(project_path, team)` | Team roster I/O |
| `load_project_context(project_path)` / `save_project_context(project_path, content)` | Context memory I/O |
| `append_project_context(project_path, entry)` | Append with separator |
| `build_awareness_snapshot(project_path, task_store)` | Build dynamic state dict |
| `build_awareness_block(project_path, task_store)` | Assemble full awareness text for injection |
| `detect_tech_stack(project_path)` | Detect from project files |

**Architecture:** Pure Python. No GTK, no network, no imports from `ui/`, `agent/`, `gateway/`.

---

## 5. Delivery Mechanisms

### Path A: System Prompt Injection (Special Agents)
`agent/context.py` → `build_system_prompt()` now calls `build_awareness_block()` and includes it in the `file_context_block` template variable.

Injected on every special agent turn (Coder, Debugger).

### Path B: Message Prefix (Gateway Agents)
`ui/handlers/chat_handler.py` tracks `_awareness_sent: set[str]` — keyed by `"{project_name}:{session_key}"`.

On first message to each agent in a project, prepends:
```
[Project Context]
<awareness block>

[User Message]
<original text>
```

Subsequent messages to the same agent in the same project are sent without prefix.

---

## 6. Modified Modules

### `utils/projects.py`
- `load_members()` / `save_members()` → backwards-compatible wrappers delegating to `project_awareness`
- Marked as DEPRECATED; new code should use `project_awareness.load_team()` / `save_team()`

### `ui/handlers/project_handler.py`
- Constructor: new `awareness_module` parameter (injected by `window.py`)
- Stores `_active_project_path` alongside `_active_project_name`
- `open_project()`: calls `init_project_config(path, name)` to create/migrate `.crabcakes/`
- Internal `_load_members()` / `_save_members()`: use awareness module when available, legacy fallback
- `_get_project_path()`: resolves project name → path via cached active path or `load_projects()`

### `ui/handlers/chat_handler.py`
- New `_awareness_sent: set[str]` — tracks which project+agent pairs received awareness
- `_build_awareness_prefix()`: builds context block for injection
- Fan-out logic: injects prefix on first message, tracks in set

### `ui/window.py`
- Imports `utils.project_awareness` as `self._awareness`
- Passes to `ProjectHandler` constructor
- All `self._projects.load_members()` calls replaced with `self._project_handler.get_project_members()`

### `ui/views/left_panel.py`
- Removed unused `save_members` import

### `agent/context.py`
- `build_system_prompt()` includes awareness block in special agent prompts

---

## 7. Migration Path

When a project is opened for the first time after this update:

1. `init_project_config()` checks for `.crabcakes/` → not found
2. Checks for `crabcakes.md` at project root → copies to `.crabcakes/project.md`
3. Checks for `~/.config/crabcakes/projects/<name>/members.json` → migrates session keys to `.crabcakes/team.json`
4. Creates empty `.crabcakes/context.md`
5. Creates initial `.crabcakes/awareness.json`

Legacy config files are NOT deleted — they remain in place as backup.

---

## 8. Tests

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_project_awareness.py` | 26 | All awareness functions |
| `tests/test_projects.py` | 16 | Legacy wrappers + migration |
| `tests/test_project_handler.py` | 22 | Handler integration |

**Total: 582 tests passing, 0 new failures.**

---

## 9. Future Work

| Feature | Priority | Notes |
|---------|----------|-------|
| UI for editing `project.md` | Medium | Could use a popover or external editor launch |
| UI for editing team roles | Medium | Enhance +/− button flow with role dropdown |
| Agent write-back to `context.md` | High | Tool/function for agents to persist learnings |
| Review mode toggle → `awareness.json` | Low | `review_mode` field exists, needs ReviewHandler wiring |
| Periodic awareness snapshot refresh | Low | For long sessions, refresh git state periodically |
| Awareness for new agents joining mid-session | Medium | Reset `_awareness_sent` entry when new agent added |

---

## 10. Architecture Compliance Checklist

- [x] `models/team.py` — pure data, no GTK, no network
- [x] `utils/project_awareness.py` — pure Python, no imports from ui/agent/gateway
- [x] Handlers do NOT import other handlers (Section 8.6)
- [x] Window wires cross-handler communication via callbacks
- [x] GTK calls use `GLib.idle_add()` from background threads
- [x] Config paths via `utils/config.py` — no hardcoded paths
- [x] No secrets in project-awareness files
- [x] Existing tests preserved and passing
