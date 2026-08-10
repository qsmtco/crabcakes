# SPEC: Task System Full Redesign — Specs as Atomic Work Units

**Date:** 2026-07-31  
**Author:** Coder  
**Status:** Draft — for implementation  
**Implements:** `/tmp/spec-task-full-redesign.md`  
**Depends on:** `docs/specs/SPEC-SUPERVISOR-ONBOARDING-REFINEMENTS.md`, `prompts/implementationLoop.md`  
**Target branch:** `main`

> Architecture compliance: `models/` remains pure data; `utils/` remains pure Python/file I/O with no UI, gateway, or agent imports; task/work command behavior lives in a dedicated `ui/handlers/work_handler.py`; `ui/window.py` is the composition root; cross-handler communication is callback/dependency wiring only. `ARCHITECTURE.md` remains authoritative.

## DISCOVERY

- Read `models/task.py`: `Task` is a mutable dataclass with zero-padded sequential IDs, flat `title`/`description`/`assigned_to`/`status`/`priority` fields and timestamps; `TaskStore` is an in-memory dict with `create`, `get`, `update`, `list_all`, `list_by_agent`, and `delete`. `update()` stamps `updated_at`; `list_all()` sorts by `created_at`. There is no file persistence.
- Read `models/__init__.py`: the process-global singleton is `task_store = TaskStore()`, and `Task`, `TaskStore`, labels, and the singleton are re-exported. The redesign must introduce the Work Unit singleton without breaking legacy imports immediately.
- Read `ui/handlers/task_handler.py`: `TaskHandler` owns eight pure command methods (`cmd_task`, `cmd_done`, `cmd_start`, `cmd_blocked`, `cmd_cancel`, `cmd_tasks`, `cmd_assign`, `cmd_priority`), uses the global `task_store`, emits task response cards and optional feed cards, and has `_parse_task_id(cmd) -> str | None`. It has no project-path persistence dependency and no agent-runtime dependency.
- Read `ui/handlers/command_handler.py`: constructor accepts an optional task handler; when present it registers `task` (alias `t`), `done`, `start`, `blocked`, `cancel`, `tasks`, `assign`, and `priority` individually. Registration is via `register_command(name, handler, aliases, help_text, payload_free)`; command handlers return `CommandResult`.
- Read `utils/project_awareness.py`: `build_awareness_snapshot(project_path, task_store=None)` calls `_get_task_info(task_store)`; `_get_task_info(task_store)` currently calls `list_all()` and returns `total`, `in_progress`, `blocked`, `pending`, and `done`. `build_awareness_dict()` calls `build_awareness_snapshot(project_path)` without a store, so its current task counts are zero. Snapshot data is persisted separately by callers; this redesign changes the source passed to `_get_task_info` and the count schema.
- Read `utils/workflow_state.py`: `PHASES` currently is `onboarding`, `discovery`, `architecture`, `task-planning`, `implementation`, `testing`, `ship`; `PHASE_PROMPTS` maps `task-planning` to `prompts/cc-task-planning.md`. `init_workflow()` renders every phase; `advance_phase()` validates names, marks one row done, marks the next current, and writes the file. The redesign changes planning to `spec-planning` and maps it to `cc-spec-planning.md`; implementation remains the phase where `/work start` is used.
- Read `prompts/implementationLoop.md`: it is authoritative for the supervisor/builder/auditor loop, mandatory adversarial audits, phase instructions, implementation authority, and post-mortem format. It is not to be modified. `/work start` must hand off to the Supervisor rather than implement a second PICK→BUILD→TEST→REVIEW→RECORD engine.
- Read `prompts/cc-task-planning.md`: it currently asks for flat tasks, uses `/task`, writes `tasks.md`, and advances `task-planning`. It must be rewritten as spec planning or replaced by `cc-spec-planning.md`; the chosen filename must match `PHASE_PROMPTS` and all workflow references.
- Read `prompts/cc-workflow-guide.md`: it presents seven phases and currently calls phase 3 “Task Planning”, describes `cc-task-planning`, and says phase 4 is engine-run implementation. It must describe “Spec Planning”, Work Units, generated `tasks.md`, and manual `/work start` handoff.
- Read `prompts/system/crabcakes-commands.md`: it currently documents `/task`, `/tasks`, `/start`, `/done`, `/blocked`, `/cancel`, `/assign`, and `/priority` as separate commands. It must document `/work` and aliases, including `/work start` as the implementation-loop trigger.
- Read `docs/proposals/PROPOSAL-implementation-engine.md`: the old deterministic engine proposal is explicitly unimplemented and conflicts with the approved redesign if revived. It must remain reference-only; this spec does not implement `utils/engine.py` or an autonomous cycle.
- Read `ui/handlers/agent_runtime_handler.py`: the verified special-agent send entry point is `send_to_special_agent(session_key: str, text: str) -> None`; it rejects unregistered special agents, resolves project context, and starts the local runtime asynchronously. `/work start` uses this API for `special:supervisor` and must handle its no-return-value/asynchronous nature.
- Read `agent/runtime.py`: `AgentRuntime` owns LLM/tool-loop execution and callbacks; it is not the UI command dispatch API. The Work Handler must not call private runtime methods or construct a second send path.
- Read `ui/views/main_content.py`: project chat tabs are created through `create_chat_tab(session_key, agent_name)`; project session keys use `project:<name>`. This is relevant only for command-result display and is not a Work Unit persistence concern.
- Read `docs/specs/SPEC-SUPERVISOR-ONBOARDING-REFINEMENTS.md`: Supervisor is manually added (`auto_add_to_projects: false`), onboarding is role-gated, and its workflow references must be kept consistent with the new `spec-planning` phase and prompt.
- **Architecture owners:** `WorkUnit` owns work-unit data; `WorkUnitStore`/`utils/work_persistence.py` own `.crabcakes/work.json` persistence and generated `tasks.md`; `WorkHandler` owns command semantics and start handoff; `utils/project_awareness.py` owns awareness counts; `utils/workflow_state.py` owns phase names/prompt mapping; `ui/window.py` wires dependencies.
- **Existing patterns to copy:** dataclass serialization from `models/team.py`, explicit `save_*` file utilities in `utils/project_awareness.py`, command registration through `CommandHandler.register_command`, and special-agent dispatch through `AgentRuntimeHandler.send_to_special_agent`.

## Spec Sequencing

The task-system spec MUST be implemented before or in the same commit as the Supervisor spec's `utils/workflow_state.py` changes. The Supervisor spec's `spec-planning`/`cc-spec-planning.md` workflow references are conditional on this task spec landing; if the Supervisor spec is implemented standalone first, it must retain `task-planning` and `cc-task-planning.md` until this redesign is implemented.

## 1. Overview

### Problem

The current flat Task model is process-local, has no required spec, and cannot represent acceptance criteria, file scope, dependency ordering, supervisor/builder/auditor ownership, or an auditable implementation lifecycle. `tasks.md` is agent-written and not read back, while the authoritative implementation loop is manual and has no command trigger.

### Solution

Replace flat tasks with persisted Work Units whose required spec file is the atomic implementation contract. Store machine-readable state in `.crabcakes/work.json`, generate `.crabcakes/tasks.md` as a summary, and introduce `/work` commands with backward-compatible aliases. `/work start #N` validates the spec, status, and Supervisor membership, then sends the Supervisor a precise implementation-loop handoff. The existing `implementationLoop.md` remains unchanged and remains the execution authority.

### Scope

| In scope | Out of scope |
|---|---|
| `WorkUnit` model/store and JSON persistence | Implementing the autonomous PICK→BUILD→TEST→REVIEW→RECORD engine |
| Generated `tasks.md` summary and best-effort legacy migration | Changing `prompts/implementationLoop.md` or post-mortem format |
| `/work` commands and legacy aliases | Removing review-layer integration |
| `/work start` Supervisor handoff | Gateway response-correlation engine |
| Awareness/workflow/prompt/documentation updates | Parallel work-unit execution |
| Deprecated compatibility surface for `models.task` | Destructive deletion of existing task data |

### Approved decisions

1. Specs are the atomic work unit; flat tasks cease to be the primary model.
2. `.crabcakes/work.json` is the source of truth; `.crabcakes/tasks.md` is generated only.
3. `/work start #N` is a manual implementation-loop trigger.
4. Existing command names remain aliases.
5. Supervisor, builder, and auditor are separate assignment fields.
6. Legacy `tasks.md` migration is best-effort on first project open.
7. The implementation loop itself is unchanged.

## 2. Data Model and Invariants

### 2.1 `models/work_unit.py` — new

Define a pure dataclass:

```python
@dataclass
class WorkUnit:
    id: str = field(default_factory=_work_next_id)
    title: str = ""
    spec_path: str = ""
    status: str = "draft"
    assigned_supervisor: str = "special:supervisor"
    assigned_builder: str = "special:coder"
    assigned_auditor: str = "special:debugger"
    priority: str = "medium"
    depends_on: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    post_mortem_path: str = ""
    blocked_reason: str = ""
```

Serialization must use this explicit round-trip API, preserving all fields and defensively copying `depends_on`:

```python
def to_dict(self) -> dict:
    return {
        "id": self.id,
        "title": self.title,
        "spec_path": self.spec_path,
        "status": self.status,
        "assigned_supervisor": self.assigned_supervisor,
        "assigned_builder": self.assigned_builder,
        "assigned_auditor": self.assigned_auditor,
        "priority": self.priority,
        "depends_on": list(self.depends_on),
        "created_at": self.created_at,
        "updated_at": self.updated_at,
        "completed_at": self.completed_at,
        "post_mortem_path": self.post_mortem_path,
        "blocked_reason": self.blocked_reason,
    }

@classmethod
def from_dict(cls, data: dict) -> "WorkUnit":
    if not isinstance(data, dict):
        raise ValueError("Work Unit record must be an object")
    def string_field(name: str, default: str = "") -> str:
        value = data.get(name, default)
        if not isinstance(value, str):
            raise ValueError(f"Work Unit field {name!r} must be a string")
        return value
    depends_on = data.get("depends_on", [])
    if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
        raise ValueError("Work Unit field 'depends_on' must be a list of strings")
    return cls(
        id=string_field("id"),
        title=string_field("title"),
        spec_path=string_field("spec_path"),
        status=string_field("status", "draft"),
        assigned_supervisor=string_field("assigned_supervisor", "special:supervisor"),
        assigned_builder=string_field("assigned_builder", "special:coder"),
        assigned_auditor=string_field("assigned_auditor", "special:debugger"),
        priority=string_field("priority", "medium"),
        depends_on=list(depends_on),
        created_at=string_field("created_at"),
        updated_at=string_field("updated_at"),
        completed_at=string_field("completed_at"),
        post_mortem_path=string_field("post_mortem_path"),
        blocked_reason=string_field("blocked_reason"),
    )
```

`from_dict()` must validate types before accepting values and reject malformed dependency lists rather than iterating arbitrary strings. IDs are sequential, eight-character zero-padded strings, matching the current Task scheme. After loading units, call `_work_init_counter(loaded_units)` to avoid restart collisions:

```python
def _work_init_counter(work_units: Iterable[WorkUnit]) -> None:
    global _work_next_num
    maximum = 0
    for work in work_units:
        try:
            maximum = max(maximum, int(work.id))
        except (TypeError, ValueError):
            continue
    _work_next_num = maximum + 1
```

The loader must call `_work_init_counter(loaded_units)` after `load_work_units()`/migration returns, before the next create. `depends_on` must be acyclic and must not include the Work Unit's own ID; validate this on create and update. On update, every dependency ID must refer to an existing Work Unit; reject stale references with a clear validation error.

Allowed statuses are exactly: `draft`, `spec-pending`, `spec-ready`, `in-progress`, `auditing`, `done`, `cancelled`. Allowed priorities are `low`, `medium`, `high`, `critical`. Invalid status/priority transitions must return a documented failure or raise a documented validation error; command handlers must convert failures into `CommandResult.response_text`, not leak exceptions to the UI.

Lifecycle:

```text
draft → spec-pending → spec-ready → in-progress → auditing → done
                                           ↑          │
                                           └ bugs ────┘
Any status → cancelled
```

`done` requires a non-empty `spec_path`, existing spec file at the project root, and a non-empty `post_mortem_path` only when the completion command is used as the final implementation-loop record. `/work done` is a controlled administrative transition; it must not silently invent a post-mortem path.

### 2.2 Store API

`WorkUnitStore` must provide pure in-memory operations over loaded/project-scoped records:

```python
class WorkUnitStore:
    def create(self, work: WorkUnit) -> WorkUnit: ...
    def get(self, work_id: str) -> WorkUnit | None: ...
    def update(self, work: WorkUnit) -> WorkUnit: ...
    def list_all(self) -> list[WorkUnit]: ...
    def list_by_status(self, status: str) -> list[WorkUnit]: ...
    def delete(self, work_id: str) -> bool: ...
    def replace_all(self, work_units: Iterable[WorkUnit]) -> None: ...
```

`WorkUnitStore` is pure in-memory. `utils/work_persistence.py` is the persistence layer. `WorkHandler` orchestrates: load on every `open_project`, save after every mutation. `replace_all` is internal and called only by the load path. `create`, `update`, and `delete` therefore do not perform file I/O themselves. `list_all()` sorts by `created_at` ascending (oldest first, matching current `TaskStore` behavior), with ID as tiebreaker; empty `created_at` values sort first because an empty string precedes timestamps lexicographically. Store updates must stamp `updated_at` using an ISO timestamp; creation stamps both created/updated if absent.

### 2.3 Singleton compatibility

Add a Work Unit singleton in `models/__init__.py` and expose `WorkUnit`, `WorkUnitStore`, and `work_store`. Keep importing `Task`, `TaskStore`, `task_store`, labels, and constants from `models.task` temporarily so existing callers/tests do not break during migration. Mark `models/task.py` deprecated in its module docstring; do not remove it in this redesign.

## 3. Persistence and Migration

### 3.1 `utils/work_persistence.py` — new

Own project-root persistence and generated summaries. Public API:

```python
def work_json_path(project_path: str) -> str: ...
def tasks_summary_path(project_path: str) -> str: ...
def load_work_units(project_path: str) -> list[WorkUnit]: ...
def save_work_units(project_path: str, work_units: Iterable[WorkUnit]) -> None: ...
def load_or_migrate_work_units(project_path: str) -> list[WorkUnit]: ...
def render_tasks_summary(work_units: Iterable[WorkUnit]) -> str: ...
def write_tasks_summary(project_path: str, work_units: Iterable[WorkUnit]) -> None: ...
```

`work_json_path()` returns `<project_path>/.crabcakes/work.json`; `tasks_summary_path()` returns `<project_path>/.crabcakes/tasks.md`. Use `get_crabcakes_dir(project_path)` rather than rebuilding path conventions. `save_work_units()` creates `.crabcakes/` if needed, writes valid JSON atomically where the repository’s file-writing conventions permit, and then writes the generated summary. A failed summary write must not corrupt or invalidate the JSON source of truth; log it and preserve `work.json`.

JSON format:

```json
{
  "version": 1,
  "work_units": [
    {
      "id": "00000001",
      "title": "...",
      "spec_path": "docs/specs/SPEC-example.md",
      "status": "spec-ready",
      "assigned_supervisor": "special:supervisor",
      "assigned_builder": "special:coder",
      "assigned_auditor": "special:debugger",
      "priority": "high",
      "depends_on": [],
      "created_at": "2026-07-31T...",
      "updated_at": "2026-07-31T...",
      "completed_at": "",
      "post_mortem_path": "",
      "blocked_reason": ""
    }
  ]
}
```

Missing file means an empty list. Invalid JSON, wrong top-level shape, or malformed records must be handled best-effort: log a warning, preserve a readable empty/valid state, and never crash project open. Do not treat generated `tasks.md` as input when valid `work.json` exists.

The generated summary must include every Work Unit, status, priority, spec indicator/path, and assignment fields in a stable human-readable format. It must be deterministic and contain a source-of-truth note: “Generated from `.crabcakes/work.json`; edit work units through `/work` commands.” No implementation path may parse this generated summary after it has been written.

### 3.2 Legacy migration

`load_or_migrate_work_units(project_path)` behavior:

1. If `work.json` exists and parses into the versioned shape, load it directly and regenerate `tasks.md` from it.
2. If `work.json` is absent, parse existing `tasks.md` best-effort, one Work Unit per recognizable task section/table row, with `spec_path=""`, title from the task title, priority when recognizable, and empty assignment fields replaced by defaults. Map statuses exactly: legacy `pending` → `draft` (not `spec-ready`, since no spec exists); legacy `in_progress` → `in-progress`; legacy `blocked` → `in-progress` plus `blocked_reason`; legacy `done` → `done`; legacy `cancelled` → `cancelled`.

Example legacy input:

```markdown
## Task 00000003: File watcher core — 🔄 in_progress
- **Priority:** high
- **Assigned:** special:coder

## Task 00000004: API integration — 🚫 blocked
- **Priority:** medium
- **Notes:** waiting for credentials
```

This yields Work Units `00000003` (`in-progress`) and `00000004` (`in-progress`, `blocked_reason="waiting for credentials"`), both with empty `spec_path`.
3. If no recognizable tasks exist, return an empty list.
4. Persist migrated Work Units to `work.json` and regenerate `tasks.md` exactly once after migration.
5. Never delete or overwrite the original information before the new JSON has been successfully written. Unparseable markdown is retained as legacy text only; it is not silently fabricated into completed work.

Migration is invoked on project open through the project lifecycle wiring, before awareness/task commands can read the store. Re-opening a project must not duplicate migrated units.

### 3.3 Project lifecycle

On every project switch/open, the composition root (`ui/window.py`) wires the load: its project-open callback calls `work_handler.load_for_project(path)`. `WorkHandler.load_for_project(path)` calls `load_or_migrate_work_units(path)` and then `store.replace_all(loaded)`. The Work Handler does not import `ProjectHandler`; it receives the project path through this explicit composition-root call or a provider callback. The store is project-scoped and must not retain units from the previous project. `close_project()` releases the active project binding without deleting persisted data.

## 4. Work Commands and Handler

### 4.1 `ui/handlers/work_handler.py` — new, replaces `task_handler.py` in production wiring

The handler remains GTK-free and receives dependencies through its constructor:

```python
class WorkHandler:
    def __init__(
        self,
        project_handler,
        work_store,
        agent_runtime_handler=None,
        on_display_card=None,
        on_display_text=None,
        on_feed_card=None,
        GLib_module=None,
    ): ...
```

The handler must resolve the active project path/name through `project_handler`’s public APIs and must not read `ui.window` state directly. It may call the injected `agent_runtime_handler.send_to_special_agent(session_key, text)` for `/work start`; it must not import `agent_runtime_handler` or `agent.runtime` modules.

All command methods return `CommandResult`. Project-scoped commands must return a clear response when no project is active. Work-unit IDs accept the current eight-digit form and `#`-prefixed form; no ambiguous title matching is allowed.

### 4.2 Command grammar and aliases

Register one canonical `/work` command with alias `/task`. Preserve these aliases:

| Canonical | Legacy alias | Behavior |
|---|---|---|
| `/work` | `/task` | Create a draft Work Unit from the payload |
| `/work list` | `/tasks` | List Work Units |
| `/work start #N` | `/start #N` | Trigger the implementation loop |
| `/work done #N` | `/done #N` | Mark done, subject to authorization/validation |
| `/work blocked #N — reason` | `/blocked #N — reason` | Mark blocked (`in-progress` + reason) |
| `/work unblock #N` | — | Clear blocked reason and restore `spec-ready` |
| `/work cancel #N` | `/cancel #N` | Cancel |
| `/work assign #N @agent` | `/assign #N @agent` | Assign supervisor/builder/auditor according to target role |
| `/work priority #N level` | `/priority #N level` | Set priority |
| `/work spec-ready #N` | — | Validate the spec path and mark ready |
| `/work status #N <status>` | — | PM/Supervisor lifecycle transition (including `auditing`) |

The parser must not mutate the shared `Command.args` unexpectedly for later routing. Use a local subcommand/argument view or explicitly document and test mutation behavior. `/work` with no subcommand creates a draft. Both `/work` and `/task` route to the same `WorkHandler.cmd_work` method; `cmd_work` detects the legacy-vs-canonical form from `cmd.name`. The Work Handler derives the title from `cmd.body` if non-empty (quoted input such as `/work "My title"`), otherwise joins `cmd.args` with spaces (unquoted input such as `/work My title`). Both forms produce the same Work Unit. All `/work` subcommands and legacy commands use `cmd.args` for IDs and subcommand names, not `cmd.body`; for example `/work done #N` reads the ID from `cmd.args[1]`, while `/work blocked #N` reads the ID from `cmd.args[1]` and the reason from `cmd.body` or `cmd.args[2:]`. The legacy `/task` form uses the same title derivation.

`/work list` output must show ID, title, status, priority, spec indicator/path, supervisor, builder, and auditor. The spec indicator must distinguish missing spec (`⚠`) from present spec (`✓`). Empty list returns a stable “No work units yet.” message.

### 4.3 Create / spec lifecycle commands

Creation creates `WorkUnit(title=..., status="draft", spec_path="")`; it must not claim spec-ready. The Supervisor or PM may transition a unit to `spec-pending` while writing. Add `/work spec-ready #N`: it validates a non-empty relative `spec_path`, resolves it safely under the project root, verifies the file exists, and transitions only from `draft` or `spec-pending` to `spec-ready`. Reject absolute paths and paths escaping the project root (`..` traversal). If the assigned Supervisor is not in the project team, return a warning—not a hard refusal—after marking ready: `Spec marked ready, but Supervisor is not in the project team. Add Supervisor before /work start.` Persist and report validation errors.

Add `/work status #N <status>` for PM/Supervisor lifecycle transitions. Apply this explicit transition and authorization table:

| Requested status | Allowed source statuses | Authorized caller | Result |
|---|---|---|---|
| `draft` | Any non-`done` status | PM or assigned Supervisor | Set draft; clear readiness-only metadata as appropriate |
| `spec-pending` | `draft` | PM or assigned Supervisor | Mark spec writing in progress |
| `spec-ready` | — | — | **Rejected**; use `/work spec-ready #N` |
| `in-progress` | — | — | **Rejected**; use `/work start #N` |
| `auditing` | `in-progress` | Assigned Supervisor only | Mark adversarial audit phase |
| `done` | — | — | **Rejected**; use `/work done #N` |
| `cancelled` | Any non-`done` status | PM only | Cancel permanently |

The Supervisor may set `auditing`; `/work start` transitions directly from `spec-ready` to `in-progress`; `/work done` transitions from `in-progress` or `auditing` to `done`. Enforce the table and persist every accepted transition.

Add `/work unblock #N`: it is valid only when `status == "in-progress"` and `blocked_reason` is non-empty. Before restoring readiness, re-validate `spec_path` as non-empty and verify the spec file exists safely under the project root. If the spec is missing, clear the blocked reason, transition to `draft`, persist, and report exactly: `Spec file no longer exists. Work unit reverted to draft.` If the spec exists, clear `blocked_reason`, restore `status="spec-ready"`, persist, and report the transition. Other states return a clear refusal.

`/work done #N` may be invoked by PM or the assigned Supervisor only. It must validate the target, set `status="done"`, set `completed_at`, persist, regenerate the summary, and report the transition. It must refuse a missing unit and must not silently change a cancelled unit back to done.

`/work blocked #N — reason` requires a non-empty reason and, because the approved Work Unit status set does not include `blocked`, sets `status="in-progress"` plus `blocked_reason=reason`. Listing must render the blocked reason distinctly, and `/work start` must refuse a unit with a non-empty `blocked_reason` until the Supervisor/PM clears it through the approved lifecycle. Do not add a new `blocked` status without a separate PM-approved schema change.

### 4.4 `/work start #N` — implementation-loop trigger

This command is the key new behavior. It must execute synchronously through validation, then dispatch the special-agent send asynchronously through the injected runtime handler:

1. Resolve the current project path and load Work Unit `N`.
2. Reject missing ID/unit with a `CommandResult` error.
3. Verify `spec_path` is non-empty and relative. Resolve the full path with `os.path.realpath(os.path.join(project_path, spec_path))` and compare `os.path.normcase(resolved_path)` against `os.path.normcase(os.path.realpath(project_path))` plus a path separator; reject absolute paths, `..` traversal, and symlinks escaping the project root. Then require `os.path.isfile(resolved_path)`. Missing spec response: `Work unit #N has no spec. Write the spec first.`
3.5. For each ID in `work_unit.depends_on`, look it up in the store. Build one error list that distinguishes missing dependencies from unfinished ones: use `#B (not found)` when absent, and `#A (status: in-progress)` when present but not done. Return: `Work unit #N has unresolved dependencies: #A (status: in-progress), #B (not found). Resolve dependencies first.` Do not change state or send.
4. Verify `status == "spec-ready"` and `blocked_reason` is empty; otherwise return a message explaining the required status/recovery action.
5. Verify `assigned_supervisor` is present in `project_handler.get_project_members(project_name)`. If absent, return exactly: `Add the Supervisor agent to begin implementation.`
6. Set status to `in-progress`, stamp `updated_at`, persist JSON and generated summary before sending.
7. Construct this message, with the Work Unit’s relative path substituted:

```text
Load prompts/implementationLoop.md. This work unit's spec is at {spec_path}. Begin the implementation loop.
```

8. Call `agent_runtime_handler.send_to_special_agent(assigned_supervisor, message)` exactly once. This method returns `None` and starts the local runtime asynchronously; the command must not wait for the Supervisor response.
9. Wrap the `send_to_special_agent` call in `try/except`. On a synchronous exception from the call itself (for example, an unknown special session), log the exception, roll status back to `spec-ready`, persist, and return a failure `CommandResult`; the exception must not escape `process_input()`. On success (`None`), status stays `in-progress`. Asynchronous runtime failures are not catchable here; the Work Unit stays `in-progress`, and the user can use `/work blocked` or `/work cancel` to recover.
10. Return a response confirming the Work Unit ID and Supervisor handoff.

No autonomous engine, polling loop, gateway correlation, test execution, review automation, or second implementation cycle is created by this command.

### 4.5 Assignment semantics

`/work assign #N @agent` must identify whether the target is supervisor, builder, or auditor. Preserve the existing `Command` mention resolution; do not infer role only from display-name substrings when a session key is available. The command must update exactly one assignment field, or return a clear usage/error if the role is ambiguous. Defaults are `special:supervisor`, `special:coder`, and `special:debugger`.

### 4.6 Authorization and project scope

PM identity is `cmd.source_session_key` matching `project:<name>` (user typing in the project tab) or the project team's `pm_id`; the implementation must use the existing `ProjectTeam.pm_id` field rather than inventing a second identity store. `/work done` and `/work cancel` are authorized for PM identity or the assigned Supervisor. `/work status`, `/work spec-ready`, `/work unblock`, and lifecycle mutations follow the same PM/Supervisor authorization; unrelated gateway agents are denied. Tests must cover PM, assigned Supervisor, unrelated agent, missing project, and missing member cases.

## 5. Command Registration and Wiring

### 5.1 `ui/handlers/command_handler.py`

Do **not** use the `aliases=` parameter for any work command: `CommandRegistry.get()` checks canonical `_commands` before `_aliases`, so registering `/work` with `aliases=["task"]` would orphan the legacy command. Register `/work` and every legacy name as separate canonical commands, each with `payload_free=True`:

```python
self.register_command("work", work_handler.cmd_work,
    help_text="Work units: create, list, start, spec-ready, status, unblock, done, blocked, cancel, assign, priority",
    payload_free=True)
self.register_command("task", work_handler.cmd_work,
    help_text="Create a Work Unit (legacy alias)", payload_free=True)
self.register_command("tasks", work_handler.cmd_work_list,
    help_text="List Work Units (legacy alias)", payload_free=True)
self.register_command("start", work_handler.cmd_work_start,
    help_text="Start a Work Unit (legacy alias)", payload_free=True)
self.register_command("done", work_handler.cmd_work_done,
    help_text="Complete a Work Unit (legacy alias)", payload_free=True)
self.register_command("blocked", work_handler.cmd_work_blocked,
    help_text="Block a Work Unit (legacy alias)", payload_free=True)
self.register_command("cancel", work_handler.cmd_work_cancel,
    help_text="Cancel a Work Unit (legacy alias)", payload_free=True)
self.register_command("assign", work_handler.cmd_work_assign,
    help_text="Assign a Work Unit (legacy alias)", payload_free=True)
self.register_command("priority", work_handler.cmd_work_priority,
    help_text="Set Work Unit priority (legacy alias)", payload_free=True)
```

The canonical `/work` subcommands are `list`, `start`, `spec-ready`, `status`, `unblock`, `done`, `blocked`, `cancel`, `assign`, and `priority`. `/work` with no subcommand creates a draft. `/task` maps only to draft creation; the other legacy names map to their corresponding Work Handler methods. All registrations use `payload_free=True`: this permits command parsing without requiring a quoted payload while still allowing `/work` creation to consume `cmd.body`. `/work` must be canonical in help output.

### 5.2 `ui/window.py`

Replace `TaskHandler` construction with `WorkHandler`, inject the project handler, work store, and `AgentRuntimeHandler`, preserve existing card/text/feed callbacks, and register the Work Handler with Command Handler. Ensure the Work Handler receives the live project lifecycle/store binding before a project command can run. Existing non-task command wiring must remain unchanged.

### 5.3 Agent handoff

The only special-agent handoff path for `/work start` is the injected `AgentRuntimeHandler.send_to_special_agent()` method with its verified `(session_key: str, text: str) -> None` signature. The handler must not call `AgentRuntime._run_loop`, `_call_llm`, or private provider methods.

## 6. Awareness Integration

### 6.1 `_get_task_info` replacement

Change `utils/project_awareness.py::_get_task_info` to consume Work Units rather than `TaskStore`. Preserve `build_awareness_snapshot(project_path, task_store=None)` compatibility only if needed during transition; the implementation should rename the parameter/documentation to a Work Unit store or project-bound loader and update all callers.

Return this schema:

```python
{
    "total": int,
    "spec_pending": int,
    "spec_ready": int,
    "in_progress": int,
    "done": int,
}
```

Counts come from Work Unit statuses. `draft` may be included in `spec_pending` for awareness purposes, but the mapping must be explicit and tested. `cancelled` and blocked compatibility states are not counted as active work. Update the state-line builder in `build_awareness_dict()` (the code that formats the `Tasks: N in progress, ...` line) to use `spec_pending`, `spec_ready`, `in_progress`, and `done`; remove references to `pending` and `blocked`. `build_awareness_block()` must likewise display the new names and must not emit stale authoritative task fields.

### 6.2 Persistence timing

Load Work Units on project open before the first awareness snapshot. Persist after every create/update/delete/transition and regenerate `tasks.md` from JSON. Awareness snapshot refresh remains the existing explicit caller responsibility; avoid writing snapshots from a read-only awareness builder if that would invalidate its cache.

## 7. Workflow and Prompt Changes

### 7.1 `utils/workflow_state.py`

Change `PHASES` from:

```text
onboarding, discovery, architecture, task-planning, implementation, testing, ship
```

to:

```text
onboarding, discovery, architecture, spec-planning, implementation, testing, ship
```

Change `PHASE_PROMPTS` so `spec-planning` maps to `prompts/cc-spec-planning.md`. `implementation` remains mapped to `prompts/implementationLoop.md`. Existing workflow files containing `task-planning` require a backward-compatible migration on read. In `_read_workflow_lines`, after the existing old-format migration, scan each parsed seven-column row and rewrite both the phase-name and prompt columns:

```python
migrated = False
for index, line in enumerate(lines):
    parsed = _parse_new_row(line)
    if parsed is None or parsed[1] != "task-planning":
        continue
    phase_idx, _name, _prompt, status, started, completed, notes = parsed
    lines[index] = _make_phase_row(
        phase_idx, "spec-planning", status, started, completed, notes
    )
    migrated = True
if migrated:
    _write_workflow_lines(project_path, lines)
```

The actual implementation must preserve status, started/completed dates, and notes while rewriting only the phase and prompt cells; use the existing row parser/emitter rather than relying on a broad string replacement if spacing differs. Persist the migrated rows once and do not reset status/dates/notes. After writing, re-read via `_read_workflow_lines()` and confirm all rows parse as valid seven-column rows; if any fail, log a warning. `advance_phase(project_path, "onboarding")` behavior remains unchanged except for the changed next phase.

### 7.2 `prompts/cc-spec-planning.md`

Create or rewrite the planning prompt so it:

- reads project manifest, requirements, and architecture;
- proposes Work Units, each with a title, required spec path, status, priority, dependency IDs, and supervisor/builder/auditor assignments;
- waits for PM approval before creation/readiness transitions;
- uses `/work` commands, not flat `/task` prose;
- writes/updates `.crabcakes/work.json` through the command system and treats `.crabcakes/tasks.md` as generated;
- marks `spec-planning` complete and appends context only after approved Work Units/spec stubs are recorded.

If the implementation keeps the filename `prompts/cc-task-planning.md` for compatibility, its content must be rewritten and `PHASE_PROMPTS["spec-planning"]` must point to that filename; do not leave two conflicting planning prompts. The preferred design is new `cc-spec-planning.md` plus a compatibility redirect/reference in the old file.

### 7.3 Other prompts/docs

Update `prompts/cc-workflow-guide.md`, `prompts/system/crabcakes-commands.md`, and any project-awareness workflow suggestion so they say Spec Planning, `cc-spec-planning`, Work Units, `/work start`, and generated `tasks.md`. Do not modify `prompts/implementationLoop.md`.

## 8. Migration and Compatibility

- Keep `models/task.py` importable and mark it deprecated; do not silently convert arbitrary `Task` objects at runtime.
- Keep old command names as aliases and preserve their user-facing intent by routing to Work Handler methods.
- On first project open, migrate recognizable legacy `tasks.md` entries once; write `work.json` and regenerate the summary. Existing task IDs should be retained where they fit the eight-digit Work Unit ID scheme; otherwise allocate new IDs and record the source ID in a migration note if the schema is extended.
- Existing `tasks.md` is never authoritative after successful migration. Manual edits are not read back and may be overwritten by the generated summary; the summary header must make that explicit.
- Existing `work.json` always wins over `tasks.md`, including when `tasks.md` is stale or malformed.
- Migration errors are logged and non-fatal; project open continues with an empty Work Unit list only when no valid source can be recovered.

## 9. Files by Change

### New files

- `models/work_unit.py` — WorkUnit, WorkUnitStore, statuses/priorities, serialization.
- `utils/work_persistence.py` — work.json source of truth, generated tasks.md, migration.
- `ui/handlers/work_handler.py` — canonical `/work` command implementation and Supervisor handoff.
- `prompts/cc-spec-planning.md` — spec-planning prompt, unless the existing filename is deliberately retained as a compatibility wrapper.

### Modified files

- `models/__init__.py` — exports and `work_store` singleton.
- `models/task.py` — deprecation documentation only unless compatibility adapters are required.
- `ui/handlers/command_handler.py` — canonical work registration plus aliases.
- `ui/window.py` — Work Handler construction/wiring and project lifecycle loading.
- `utils/project_awareness.py` — Work Unit awareness schema/counts and loader integration.
- `utils/workflow_state.py` — `spec-planning` phase, prompt mapping, legacy row migration.
- `prompts/cc-task-planning.md` — compatibility redirect or rewritten content, depending on chosen prompt filename.
- `prompts/cc-workflow-guide.md` — phase and output terminology.
- `prompts/cc-architecture-design.md` — update its next-step suggestion from `cc-task-planning` to `cc-spec-planning`.
- `prompts/system/crabcakes-commands.md` — `/work` reference and aliases.
- `prompts/system/project-awareness.md` — workflow suggestion if it names `cc-task-planning`.
- `docs/ARCHITECTURE.md` — model, persistence, handler, and workflow ownership.
- Focused tests listed in §10.

### Files NOT changed

- `prompts/implementationLoop.md` — authoritative loop; `/work start` only triggers it.
- `docs/proposals/PROPOSAL-implementation-engine.md` — historical unimplemented proposal; do not revive or rewrite as part of this redesign.
- Review-layer modules — the Work Handler hands off to the Supervisor and does not replace review behavior.
- `agent/runtime.py` — no private runtime changes are required for the send API.
- Gateway transport modules — no autonomous gateway correlation is in scope.

## 10. Tests and Verification

Add/update focused tests in these files (create missing files where needed):

- `tests/test_work_unit.py`: ID generation, defaults, serialization round-trip, status/priority validation, dependency defensive copy, store ordering and updates.
- `tests/test_work_persistence.py`: JSON round-trip, atomic/error behavior, deterministic summary, missing/invalid JSON, generated-summary non-readback, and legacy `tasks.md` migration/idempotence.
- `tests/test_work_handler.py`: all `/work` commands (`list`, `start`, `spec-ready`, `status`, `unblock`, `done`, `blocked`, `cancel`, `assign`, `priority`), separate legacy canonical commands, shared `/work`/`/task` create method, quoted/unquoted title derivation, project scope, authorization, the explicit status transition table, path/realpath/normcase traversal rejection, dependency checks with not-found vs not-done errors, spec existence checks, exact missing-spec/supervisor messages, persistence calls, and one-call Supervisor handoff.
- `tests/test_command_handler.py`: canonical `/work` registration, alias resolution, no collisions, help output, and legacy command behavior.
- `tests/test_project_awareness.py`: new Work Unit counts (`total`, `spec_pending`, `spec_ready`, `in_progress`, `done`) and absence of stale authoritative task fields.
- `tests/test_workflow_state.py`: new `PHASES`, `spec-planning` prompt mapping, migration of old `task-planning` rows, and unchanged onboarding transition.
- `tests/test_project_handler.py` or project lifecycle fixture tests: load/migrate Work Units on open and release binding on close.
- `tests/test_agent_runtime_handler.py`: `/work start` calls `send_to_special_agent("special:supervisor", message)` with the exact implementation-loop message and handles exceptions.
- Prompt/document static tests: `cc-spec-planning`, workflow guide, command reference, and project-awareness references contain no stale task-planning-only instructions where replacement is required.

Before implementation completion, run the full relevant suite, configured lint/type checks, and repository-wide searches:

```bash
grep -RIn "task-planning" utils/workflow_state.py prompts/cc-workflow-guide.md prompts/system/project-awareness.md docs/specs/SPEC-SUPERVISOR-ONBOARDING-REFINEMENTS.md
grep -RIn "build_awareness_dict.*save_awareness_snapshot\|save_awareness_snapshot.*build_awareness_dict" utils/project_awareness.py
 grep -RIn "class TaskStore\|task_store" models ui/handlers utils | head -100
 grep -RIn "def send_to_special_agent\|send_to_special_agent" ui/handlers/agent_runtime_handler.py ui/handlers/work_handler.py tests
```

The old phase name may remain only in explicit migration/compatibility tests and documentation explaining migration. The old in-memory singleton must not remain the runtime source for Work Handler or awareness.

## 11. Data Flow

### Work creation

1. User enters `/work @supervisor — Title` in a project session.
2. `CommandHandler.process_input()` resolves the command and invokes `WorkHandler.cmd_work()`.
3. Work Handler resolves the project, creates a draft `WorkUnit` with empty `spec_path`, persists `work.json`, regenerates `tasks.md`, and returns a response card/text.
4. Supervisor/captain writes the spec and marks the unit `spec-ready` only after the relative file exists.

### Start handoff

1. User enters `/work start #00000001`.
2. Work Handler loads the project-bound Work Unit and validates path, status, and Supervisor membership.
3. It persists `in-progress` before dispatching.
4. It calls `AgentRuntimeHandler.send_to_special_agent("special:supervisor", "Load prompts/implementationLoop.md. This work unit's spec is at ...")`.
5. The Supervisor loads the spec and authoritative loop, phases/delegates to Coder/Debugger, and reports through the existing collaboration/runtime channels. Work Handler does not poll or run the loop.
6. Supervisor/PM later uses `/work done`, or updates status through the approved lifecycle, after the required post-mortem/commit evidence exists.

### Awareness

On project open, `ui/window.py` invokes `work_handler.load_for_project(path)` from the project-open callback; that method calls `load_or_migrate_work_units(path)` and then `work_store.replace_all(loaded)`. This binding occurs before snapshots or commands. `build_awareness_snapshot()` calls the Work Unit-aware `_get_task_info()`, and explicit lifecycle writes refresh `awareness.json` through existing project callers. `build_awareness_dict()` remains a read/build operation and must not write snapshots as a side effect.

## 12. Acceptance Criteria

- [ ] Work Units, not flat Tasks, are the primary persisted atomic work units.
- [ ] Every Work Unit has a relative `spec_path`; creation starts with an empty path and cannot become `spec-ready` without an existing file.
- [ ] `work.json` is the source of truth and survives restart; generated `tasks.md` is deterministic and never read back after valid JSON exists.
- [ ] Existing `tasks.md` migrates best-effort exactly once without duplicate Work Units.
- [ ] `/work` and `/task` route to the same `WorkHandler.cmd_work` method, while each other legacy name is a separate canonical registration; no `aliases=` registration is used for work commands.
- [ ] All canonical work and legacy registrations use `payload_free=True` while `/work` creation still consumes `cmd.body`.
- [ ] `/work start #N` validates spec existence with realpath containment, dependency completion, `spec-ready` status, and Supervisor membership before changing state or sending.
- [ ] `/work spec-ready`, `/work status`, and `/work unblock` enforce their documented transitions and persist changes.
- [ ] `/work start` sends exactly one message through `send_to_special_agent(session_key, text)` and never calls private runtime APIs.
- [ ] Missing spec and missing Supervisor return the specified actionable messages.
- [ ] Work Unit lifecycle, dependencies, priority, assignments, blocked reason, completion, cancellation, and post-mortem fields persist losslessly.
- [ ] Awareness exposes `total`, `spec_pending`, `spec_ready`, `in_progress`, and `done` from live Work Units.
- [ ] Workflow uses `spec-planning`; old `task-planning` rows migrate without losing status/dates/notes.
- [ ] `cc-spec-planning` and command/workflow documentation describe Work Units and `/work start` consistently.
- [ ] `implementationLoop.md`, review integration, and post-mortem format remain unchanged.
- [ ] Tests, lint, type checks, and pattern sweeps pass with environmental GTK limitations explicitly reported.

## 13. Edge Cases

| Case | Expected behavior |
|---|---|
| Missing `work.json` and missing `tasks.md` | Start with an empty store; create files on first mutation. |
| Invalid `work.json` | Warn, attempt legacy migration only if the source is absent/usable by policy; never crash project open. |
| Valid `work.json` + stale `tasks.md` | Load JSON, regenerate summary; never parse stale markdown. |
| Duplicate migration/open | Detect existing JSON and do not duplicate units. |
| Absolute, escaping, or symlink-escaping `spec_path` | Reject using realpath containment; do not start or mark spec-ready. |
| Missing spec file | Return “Work unit #N has no spec. Write the spec first.” and leave status unchanged. |
| Unresolved dependency | Return the dependency IDs/statuses and leave state unchanged. |
| Non-`spec-ready` or blocked start | Refuse and report current/required status; use `/work unblock` after recovery. |
| Supervisor absent from team | Return “Add the Supervisor agent to begin implementation.”; do not send or set in-progress. |
| `/work unblock` on an unblocked/non-in-progress unit | Refuse without mutation. | |
| Supervisor send raises | Log, return a failure, and leave a recoverable status/error according to the explicit transaction policy. |
| Supervisor send returns `None` | Treat as successful dispatch; do not wait for response. |
| Unknown/ambiguous assignment target | Refuse rather than assigning the wrong role. |
| Unrelated agent mutates another project | Deny; no persistence write. |
| Cancelled unit | Cannot be restarted/done without an explicit future reactivation command. |
| Dependency missing/not done | `/work start` should reject with dependency IDs/statuses; no handoff. |
| Legacy status `pending`/`in_progress`/`blocked` | Map deterministically and record migration behavior; do not silently claim `spec-ready`. |
| Old workflow `task-planning` | Migrate to `spec-planning` preserving status, dates, notes, and prompt-column shape. |
| Generated summary manually edited | It is overwritten on next persistence; source-of-truth note explains why. |
| No project session | Return a project-required error and do not touch global state. |

## 14. ARCHITECTURE.md Updates Required

Update the architecture sections covering:

- pure model ownership: `WorkUnit`/`WorkUnitStore` replace Task as the primary model; `models/task.py` remains deprecated compatibility code;
- persistence ownership: `utils/work_persistence.py` owns `.crabcakes/work.json` and generated `tasks.md`;
- handler ownership: `WorkHandler` replaces `TaskHandler` in production wiring and owns `/work` semantics without importing other handlers;
- runtime boundary: `/work start` uses injected `AgentRuntimeHandler.send_to_special_agent()` and does not call runtime internals;
- awareness: `_get_task_info` reports Work Unit status counts;
- workflow: `spec-planning` replaces `task-planning`; implementation remains governed by `implementationLoop.md`;
- migration/source-of-truth rules and generated-summary behavior.

## 15. Rule 9 Self-Audit

- **Source verification:** Every referenced current API was read: `TaskStore` methods, `CommandHandler.register_command`, `AgentRuntimeHandler.send_to_special_agent(session_key, text)`, `build_awareness_snapshot`, `_get_task_info`, `PHASES`, `PHASE_PROMPTS`, `create_chat_tab`, and the implementation-loop prompt.
- **Key verification:** Work IDs remain eight-character strings; project persistence is under `.crabcakes/`; project session keys are `project:<name>`; special agents use `special:<role>`; assignments store session keys, not display names.
- **Return values:** `send_to_special_agent` returns `None` and is asynchronous; `create/update` return Work Units; `delete` returns bool; persistence loaders return lists and tolerate missing/invalid files; command methods always return `CommandResult`.
- **Exception coverage:** JSON decode, OSError, path validation, missing project/unit, invalid status/priority, authorization failure, and runtime-send exceptions are explicitly handled. The implementation must preserve exact exception classes from the current parser/store utilities when narrowing catches.
- **No autonomous-engine drift:** The spec deliberately does not add `utils/engine.py`, polling, gateway correlation, retries, test execution, or review automation. `/work start` only validates, persists, and sends one Supervisor message.
- **Cross-spec consistency:** Supervisor remains manually added; its spec's onboarding completion still calls `advance_phase(project_path, "onboarding")`; only the phase list/next-phase names and planning prompt references change to `spec-planning`.
- **Would an exact implementation work?** Yes, provided the implementer resolves the explicitly called-out command alias collision, blocked-status compatibility choice, and project-bound Work Unit store wiring before coding; each has required tests and no invented runtime API.

## 16. Rule 10 Completion Verification

Before reporting implementation complete, the implementer must provide:

1. **Scope checklist:** every new/modified file in §9 checked with line ranges, including both specs and all named prompts/tests/docs.
2. **Actual test output:** focused Work Unit/persistence/handler/awareness/workflow suites plus the full configured suite; paste pytest output and identify GTK/environmental skips.
3. **Pattern sweep:** verify no production Work Handler or awareness path imports/uses `TaskStore` as its source; verify no `task-planning` remains outside migration compatibility; verify `/work` and each separate legacy canonical registration (with no `aliases=` usage); verify `/work unblock`, `/work spec-ready`, and `/work status`; verify the exact `send_to_special_agent` call and implementation-loop message.
4. **Clarity-gap note:** the implementer should resolve remaining LOW clarity gaps (payload parsing details, generated-list formatting, injection timing, and the audit's BUGs #39, #43, #44, #47, #48, and #55) during implementation and document those decisions in the post-implementation report.
4. **Declaration:** report complete only after tests, lint/type checks, and pattern sweeps pass; otherwise report exact blockers and do not claim completion.
