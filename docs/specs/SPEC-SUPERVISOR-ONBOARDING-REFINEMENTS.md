# SPEC: Supervisor Onboarding Refinements

**Date:** 2026-07-31  
**Author:** Coder  
**Status:** Draft — for implementation  
**Implements:** `/tmp/delegate-context.md`  
**Depends on:** Current project-awareness, workflow-state, and special-agent registry implementations  
**Target branch:** `main`

> Architecture compliance: `utils/` remains pure Python; UI behavior is owned by handlers and wired from `ui/window.py`; no handler imports another handler. Structural changes must be reflected in `docs/ARCHITECTURE.md` in the implementation commit.

## DISCOVERY

- Read `agent/special_agents.py`: `SpecialAgentDef` fields are `conv_id_prefix`, `display_name`, `role`, `tools`, `can_write`, provider fields, `auto_open`, and `auto_add_to_projects`. `_load_registry()` derives `can_write` from `write_file`/`edit_file`; `get_project_onboarding_agents()` returns definitions whose registry flag is true; `get_special_agent(prefix)` resolves a special session key.
- Read `utils/agent_defs.py`: `_seed_defaults()` currently copies built-in YAML files from `prompts/default_agents/` only when the user agents directory has no definition files; existing user files are never overwritten. This all-or-nothing guard means an existing user with other agent files would not receive a missing Supervisor definition. The implementation must change seeding to copy each missing built-in file individually, never overwriting an existing same-name user file. Definitions require a non-empty `name`, `prompts`, `tools`, `llm_name`, and `fallback_provider`, and prompt files/tools are validated.
- Read `prompts/default_agents/auxilium.yaml`, `coder.yaml`, and `debugger.yaml`: YAML uses `name`, `emoji`, `role`, `prompts`, `tools`, provider fields, and auto flags. Auxilium currently has `auto_open: true` and `auto_add_to_projects: true`; Coder/Debugger do not opt into project auto-add.
- Read `prompts/system/project-onboarding.md`: it is a separate interview/setup template and instructs the agent to update manifest, team, context, and workflow. Its content is not to be folded into the Supervisor prompt; only the code-level manifest cleanup safety net is added around completion.
- Read `utils/prompt_loader.py`: `compose_system_prompt(...)` loads shared templates, then currently appends `project-onboarding.md` only when `agent_role == "coder"` and `is_project_onboarded(project_path)` is false. Agent-specific templates currently select coder/debugger/helper; Supervisor needs an explicit `supervisor` branch.
- Read `agent/context.py`: the fallback role derivation currently recognizes only coder/debugger from the agent name when no explicit role is supplied. The implementation must add Supervisor to this fallback (or prove every Supervisor conversation always passes an explicit `SpecialAgentDef.role`; the safer required change is to add the supervisor branch). Read the conversation-construction call chain before choosing the implementation.
- Read `ui/handlers/project_handler.py`: `create_project(name, path=None, pm_name="", pm_id="")` creates the directory, initializes awareness, auto-adds onboarding agents, initializes workflow, initializes git, refreshes awareness, calls `open_project(name, path)`, and returns the path or `None`. `open_project(name, path)` initializes config, auto-adds agents, initializes workflow, refreshes the UI/routing, and fires registered `set_on_project_opened` callbacks. `_auto_add_onboarding_agents()` currently hardcodes `role="onboarding guide"` and `can_write=True`. `_save_members()` currently preserves existing members, creates unknown members with only `name=""`, and auto-commits.
- Read `utils/project_awareness.py`: `init_project_config()` creates `.crabcakes/` skeleton files; `generate_project_skeleton()` emits HTML-comment-only section bodies; `is_project_onboarded()` strips comments and checks for real non-heading manifest lines or nonempty context; `build_awareness_snapshot(project_path, task_store=None)` computes live team size; `save_awareness_snapshot(project_path, snapshot)` writes `awareness.json`; `build_awareness_dict(project_path)` reads live manifest/team/state/context and caches the result.
- Read `utils/workflow_state.py`: `advance_phase(project_path, phase_name)` validates against `PHASES`, initializes/reads workflow, marks the phase done, marks the next phase current, and writes the file. The task-system redesign changes the planning phase from `task-planning` to `spec-planning` and maps it to `prompts/cc-spec-planning.md`; the onboarding completion hook remains `advance_phase(project_path, "onboarding")`. It currently has no completion callback.
- Read `models/team.py`: `TeamMember(session_key, name, role="", can_write=False)` is the persisted roster record; `ProjectTeam` preserves PM metadata and exposes `get_member()`/`get_session_keys()`.
- Read `ui/handlers/chat_render_handler.py`, `ui/views/chat_bubble.py`, `ui/views/main_content.py`, and `ui/window.py`: `ChatRenderHandler.render_sync(role, text, session_key=None, on_forward_click=None, forwarded_from=None, agent_name=None, tab_key=None)` returns a widget synchronously on the GTK main thread; `build_role_bubble()` handles `role == "System"` with the `chat-bubble-System` CSS class. `MainContent.get_chat_box_for_session(session_key)` resolves the chat box. Existing system messages use `render_sync("System", ..., session_key)` and append the returned widget, followed by `scroll_chat_to_bottom()`.
- **Architecture owner:** `ui/window.py` is the composition root for project-created UI side effects; `ProjectHandler` owns project lifecycle and persistence; `utils/project_awareness.py` owns manifest/awareness files; `utils/workflow_state.py` owns workflow transitions; `agent/special_agents.py` owns the special-agent registry.
- **Existing patterns to copy:** callback registration from `ProjectHandler.set_on_project_opened()`, synchronous System rendering through `ChatRenderHandler.render_sync()`, and snapshot persistence through `build_awareness_snapshot()` followed by `save_awareness_snapshot()`.

## Spec Sequencing

The task-system redesign in `docs/specs/SPEC-TASK-SYSTEM-FULL-REDESIGN.md` MUST be implemented before or in the same commit as this spec's `utils/workflow_state.py` changes. This spec's `spec-planning`/`cc-spec-planning.md` references are conditional on that redesign landing. If this Supervisor spec is implemented standalone first, retain `task-planning` and `prompts/cc-task-planning.md` until the task-system redesign is implemented; do not create a workflow pointing at a prompt that does not yet exist.

## 1. Overview

### Problem

Auxilium is currently auto-added to every project while the onboarding prompt is hardcoded to Coder. The project team therefore contains the wrong onboarding agent, the prompt gate and roster disagree, team metadata is discarded during toggles, awareness snapshots become stale, and project creation gives no explicit instruction for manually adding the Supervisor.

### Solution

Promote Supervisor to the built-in project-onboarding/orchestration agent, keep it manually added (`auto_add_to_projects: false`), remove Auxilium's project auto-add, gate the onboarding template on the explicit `supervisor` role, preserve registry metadata when writing teams, refresh awareness after membership changes, avoid implicit roster commits, and clean comment-only manifest sections when onboarding is completed. Project creation emits a System bubble explaining that the user must add Supervisor manually. The registry auto-add mechanism remains available for other/legacy onboarding definitions, but no current default agent opts into it.

### Scope

| In scope | Out of scope |
|---|---|
| New Supervisor YAML/system prompt; explicit Supervisor-role onboarding gate | Changing Coder or Debugger definitions |
| Auxilium auto-add flag | Auto-adding Supervisor during project creation |
| Project-created System bubble | Review layer/feed-card changes |
| Team metadata backfill and awareness refresh | Gateway-agent name resolution beyond retaining empty persisted names |
| Manifest comment-only section cleanup at onboarding completion | Folding onboarding content into `supervisor.md` |
| Tests and architecture documentation for these changes | Changes to the review layer |

### User-config migration decision

Built-in YAMLs are templates used to seed missing user files via `_seed_defaults()` (now per-file after §2.4). Once a user file exists, it is the sole source of truth — the built-in is never consulted again at load time. Users with an existing `~/.config/crabcakes/agents/supervisor.yaml` must manually update its `prompts:` list to include `system/supervisor.md` if they want the new prompt. Do not overwrite, migrate, or delete the existing user file.

## 2. Changes by File

### 2.1 `prompts/default_agents/supervisor.yaml` — new

Create a valid built-in definition with:

- `name: Supervisor`
- `emoji` appropriate for orchestration
- `role: supervisor`
- `prompts: [system/supervisor.md]`
- onboarding/orchestration tools including at least `read_file`, `write_file`, `edit_file`, `exec_command`, `list_files`, and `search_files`; optional web tools must be justified by the implementation
- `llm_name: local-kb` and `fallback_provider: openrouter`, matching the built-in convention and validation requirements
- `auto_add_to_projects: false` — Supervisor is deliberately added by the user from the Agents tab; setting this true would make the creation bubble's “click +” instruction remove Supervisor.
- `auto_open: false` unless product explicitly elects an always-open Supervisor tab
- self-improvement settings appropriate to a write-capable orchestrator

The exact tool list must contain only names returned by `agent.tools.get_all_tools()`; verify before implementation. `can_write` is not a YAML field consumed by `_load_registry()`; it is derived from the write/edit tool list.

### 2.2 `prompts/system/supervisor.md` — new

Write the Supervisor role prompt. It must define Supervisor as:

1. the project onboarding agent that conducts the interview and completes only setup during onboarding;
2. the implementation orchestrator that plans/delegates work to Coder and Debugger after onboarding;
3. an agent that follows the project manifest, workflow, team roster, and project rules;
4. an agent that does not claim onboarding completion until manifest/context/team/workflow updates are complete.

Do **not** duplicate the full interview template. The loader appends `project-onboarding.md` separately while the project is not onboarded.

### 2.3 `prompts/default_agents/auxilium.yaml`

Change only `auto_add_to_projects: true` to `auto_add_to_projects: false`. Preserve `auto_open: true` and all existing help-agent settings.

### 2.4 `utils/agent_defs.py`

Change `_seed_defaults()` from an all-or-nothing directory guard to per-file seeding:

- enumerate built-in YAML/JSON files in `prompts/default_agents/`;
- for each built-in file, copy it only when the same destination filename is absent in the user agents directory;
- do not return early merely because unrelated user agent files exist;
- never overwrite an existing user file, including an existing customized `supervisor.yaml`.

Add a regression test with an existing unrelated user definition and no `supervisor.yaml`; the call must seed Supervisor while preserving the unrelated file.

### 2.5 `utils/prompt_loader.py`

Change the onboarding condition in `compose_system_prompt()` to the explicit Supervisor role required by the product decision:

- append `project-onboarding` only when `project_path` is active, `agent_role == "supervisor"`, and `is_project_onboarded(project_path)` is false;
- do **not** call `get_project_onboarding_agents()` for this prompt gate and do not derive the gate from `auto_add_to_projects`; Supervisor is manually added and intentionally has `auto_add_to_projects: false`;
- preserve the existing non-fatal onboarding-check behavior: if the project-state import/check fails, skip the optional onboarding template rather than breaking prompt composition;
- add an explicit `elif agent_role == "supervisor":` branch loading `supervisor.md`.

The implementation must also update `agent/context.py`'s fallback role derivation to recognize Supervisor when no explicit role is supplied. Verify the conversation-construction path: if a caller always passes the `SpecialAgentDef.role`, retain that explicit path and still add the fallback as defense-in-depth; otherwise the fallback change is required for Supervisor onboarding to work.

### 2.6 `ui/handlers/project_handler.py`

#### `_auto_add_onboarding_agents(project_path)`

Keep the existing `get_project_onboarding_agents()` lookup and membership/routing behavior. Construct the new member from the definition:

```python
TeamMember(
    session_key=agent_def.conv_id_prefix,
    name=agent_def.display_name,
    role=agent_def.role,
    can_write=agent_def.can_write,
)
```

Do not hardcode `"onboarding guide"` or `True`. Continue treating registry/load failures as non-fatal.

#### `_save_members(project_name, members)`

For an unknown session key, resolve local special-agent metadata before constructing `TeamMember`:

- call `get_special_agent(sk)` only for `special:*` keys (or safely call it for all keys and gate on a non-`None` result);
- if a definition exists, use `display_name`, `role`, and `can_write`;
- if no local definition exists, create a member with `name=""`, `role=""`, and `can_write=False` for gateway/unknown keys. Gateway names are intentionally resolved at display time and are not persisted here;
- preserve existing `TeamMember` records exactly as today when the key already exists;
- existing team members with `role="onboarding guide"` from the old `_auto_add_onboarding_agents` are preserved as-is (not migrated). New auto-additions use `agent_def.role`. This is a known migration artifact; users can manually edit `team.json` if they want to update the role;
- if `get_special_agent(sk)` returns `None` for a `special:*` key, log a warning (`special agent not in registry: {sk}`) and create a blank member. This handles stale team entries from deleted agent definitions;
- keep member ordering equal to the input `members` list.

After `save_team(path, team)`, refresh awareness with `build_awareness_snapshot(path)` and `save_awareness_snapshot(path, snapshot)`. These calls are non-GTK and should be guarded so a snapshot failure does not prevent the roster write (log the failure consistently with existing non-fatal project operations). Keep this explicit save as the membership-change refresh point.

The backfill branch must be behaviorally equivalent to:

```python
existing = team.get_member(sk)
if existing is not None:
    new_members.append(existing)
elif sk.startswith("special:"):
    agent_def = get_special_agent(sk)
    if agent_def is not None:
        new_members.append(TeamMember(
            session_key=sk,
            name=agent_def.display_name,
            role=agent_def.role,
            can_write=agent_def.can_write,
        ))
    else:
        new_members.append(TeamMember(session_key=sk, name="", role="", can_write=False))
else:
    # Gateway/unknown agents have no local registry definition.
    new_members.append(TeamMember(session_key=sk, name="", role="", can_write=False))
```

Import `get_special_agent` lazily with the other local registry imports, and preserve the existing-member branch before any backfill. Remove `_git_commit_if_available(path, "update team roster")` from this method. Explicit project-create and review-checkpoint commits remain unchanged.

If the handler's awareness dependency is absent, preserve the legacy `_projects.save_members(project_name, members)` fallback and do not invoke awareness-only APIs.

#### Project-created callback

Add a named callback API `set_on_project_created(cb: Callable[[str, str], None])` and a private `_on_project_created` callback slot. `create_project()` must notify `ui/window.py` **after** `self.open_project(name, path)` completes, by invoking the callback through the handler's `GLib.idle_add` dispatch so tab creation has completed before the callback body resolves the chat box. Do not auto-add Supervisor as part of this notification. The callback carries `(name, path)` and is registered/wired only for successful `create_project()`, not for opening an existing project. The implementation and tests must use this exact callback name so the declaration, wiring, and verification grep are unambiguous.

### 2.7 `ui/window.py`

Wire `ProjectHandler.set_on_project_created(self._on_project_created_system_bubble)` at composition time. The callback method must defer its widget work through `GLib.idle_add` (or the existing equivalent) for main-thread safety. Inside the deferred callback, execute this exact sequence:

1. derive `session_key = f"project:{name}"`;
2. call `chat_box = self._main_content.get_chat_box_for_session(session_key)`;
3. if `chat_box is None`, call `self._main_content.create_chat_tab(session_key, "System")` first, then call `get_chat_box_for_session(session_key)` again;
4. if the chat box is still unavailable, return without rendering;
5. call `self._chat_render_handler.render_sync("System", text, session_key, tab_key=session_key)` using the verified signature;
6. append the returned bubble only when it is not `None`;
7. call `self._main_content.scroll_chat_to_bottom()` after append.

`MainContent.create_chat_tab(session_key, agent_name)` is the verified tab-creation API; the callback must not assume `open_project()` or `refresh_agents_with_project()` created the project chat tab.

Use this exact user-facing message (with the actual project name substituted):

> `New project '<name>' created. Add the Supervisor agent from the Agents tab (click the +), then send it a message like 'I'm ready' to begin onboarding.`

No-op safely if the project chat box is unavailable. Because `open_project()` and downstream tab creation can be deferred through `GLib.idle_add`, the created callback must itself be deferred through `GLib.idle_add` (or an equivalent existing main-loop dispatch) and must resolve the chat box only inside that deferred callback. This ordering lets the project tab exist before `get_chat_box_for_session()` is called. The callback runs on the GTK main thread after dispatch; if the existing create path can run off-thread in a future change, dispatch before touching widgets.

### 2.8 `utils/project_awareness.py`

Add a pure helper, for example `clean_manifest_skeleton(project_path: str) -> bool`, that removes any manifest section whose body contains only whitespace and HTML comments. Requirements:

- operate only on `.crabcakes/project.md`;
- split the file into the top-level preamble/title plus sections using line boundaries matching `^## `; do not run a whole-file `re.sub(..., DOTALL)` that can let a comment containing `## ` swallow later sections;
- for each section independently, strip HTML comments from that section body, then remove the section only when the remaining body is whitespace; preserve the title, non-comment content, unrelated sections, and file newline structure as far as practical;
- do not remove the top-level `# Project` title; comments and `## ` text inside a comment must remain confined to that section's parsing;
- handle missing/unreadable files as a safe no-op returning `False` (or an explicitly documented non-raising result); do not raise into the onboarding flow;
- write only when content changed and return whether a change occurred.

Call this helper when onboarding completion is recorded, immediately before/within the `advance_phase(project_path, "onboarding")` completion path. The preferred implementation is a workflow-state completion hook that calls the helper for the onboarding phase, avoiding reliance on the LLM remembering a prompt instruction. Do not call it on every awareness read.

**Do not modify `build_awareness_dict()` to write snapshots.** It must remain read-only. Its mtime cache includes files in `.crabcakes/`, including `awareness.json`; writing `awareness.json` during an uncached build would invalidate the cache and can create a read → write → invalidate → recompute loop. It is also called during prompt construction on every turn. Keep explicit snapshot saves only in `create_project()` (already present) and `_save_members()` after membership changes.

### 2.9 `utils/workflow_state.py`

The task-system redesign changes `PHASES` from `task-planning` to `spec-planning` and changes the planning prompt mapping from `prompts/cc-task-planning.md` to `prompts/cc-spec-planning.md`. Implement the backward-compatible workflow-row migration described in `SPEC-TASK-SYSTEM-FULL-REDESIGN.md` §7.1, preserving status, dates, and notes. The onboarding completion trigger remains the literal `advance_phase(project_path, "onboarding")` path below.

Integrate the manifest cleanup at the onboarding completion trigger without introducing a UI import or circular dependency. A small lazy import inside `advance_phase()` is acceptable:

- after validating `phase_name` and before/after writing the completed onboarding row, call `clean_manifest_skeleton(project_path)` only when `phase_name == "onboarding"`;
- preserve `ValueError` for invalid phase names and current workflow write behavior;
- cleanup failures must be non-fatal and logged or safely absorbed according to the helper contract.

If implementation chooses a different exact ordering, it must still guarantee that a successful onboarding phase transition attempts cleanup exactly once and that a cleanup I/O failure does not block workflow completion.

### 2.10 Tests and documentation

Add/update focused tests in the named files:

- `tests/test_special_agents.py`: Supervisor YAML/registry loading, `auto_add_to_projects=False`, derived `can_write`, Auxilium `auto_open=True` + `auto_add_to_projects=False`, and per-file default seeding when another user agent already exists;
- `tests/test_prompt_loader.py`: explicit Supervisor onboarding gate, non-Supervisor/gateway exclusion, and Supervisor template selection;
- `tests/test_agent_context.py` (or the repository's existing context test file): fallback role derivation recognizes Supervisor when no explicit role is supplied;
- `tests/test_project_handler.py`: `_auto_add_onboarding_agents()` metadata behavior, `_save_members()` special/gateway backfill, no implicit roster commit, awareness snapshot refresh, created-only callback registration, deferred System-bubble behavior, exact `project:<name>` key/text, and unavailable-chat no-op;
- `tests/test_workflow_state.py`: onboarding completion invokes manifest cleanup without blocking workflow transition;
- `tests/test_project_awareness.py`: section-aware cleanup for comment-only, mixed, empty, malformed, missing, and already-clean manifests, including `## ` text inside comments; confirm `build_awareness_dict()` remains read-only;
- update/add any repository-specific GTK test fixture only where needed for the deferred callback; do not make tests depend on a live GTK display.

Update `docs/ARCHITECTURE.md` with the Supervisor role, explicit role-based onboarding gate, project-created System bubble ownership, manifest-cleanup ownership, and the Work Unit/spec-planning ownership required by `SPEC-TASK-SYSTEM-FULL-REDESIGN.md`.

The task-system redesign also updates `prompts/cc-task-planning.md` or replaces it with `prompts/cc-spec-planning.md`; this Supervisor spec must not continue to describe `task-planning` as the active phase or the old prompt as the active planning prompt.

## Files NOT Changed

- `prompts/default_agents/coder.yaml` — explicitly out of scope; Coder remains non-auto-added.
- `prompts/default_agents/debugger.yaml` — explicitly out of scope; Debugger remains non-auto-added.
- `prompts/system/project-onboarding.md` — do not rewrite its onboarding content; the code-level cleanup is separate.
- `ui/handlers/chat_handler.py`, `ui/handlers/feed_handler.py`, and feed-card modules — existing System rendering is sufficient; the new bubble is wired through the composition root and does not require a new feed card.
- Review-layer modules — explicit scope exclusion.

## 3. Data Flow

### New project

1. File-tree/UI calls `ProjectHandler.create_project(name, path, pm_name, pm_id)`.
2. `create_project()` validates and creates the directory; `init_project_config()` creates the skeleton; no current default agent is auto-added because Supervisor has `auto_add_to_projects=False`; `init_workflow()` creates workflow state; git initialization/initial commit runs; awareness is refreshed.
3. `open_project(name, path)` repeats idempotent initialization, runs the registry-driven auto-add hook (a no-op for current defaults), refreshes UI/routing, and fires normal opened callbacks.
4. The deferred created-only callback in the composition root derives `project:<name>`, checks `MainContent.get_chat_box_for_session()`, calls `MainContent.create_chat_tab(session_key, "System")` when no tab exists, resolves the chat box again, then creates/appends the System bubble via `ChatRenderHandler.render_sync()` and scrolls.
5. The user manually adds Supervisor from Agents and sends a message. Supervisor's explicit/fallback role resolves to `supervisor`; `compose_system_prompt()` sees that role and an un-onboarded project, then appends `project-onboarding.md` plus `supervisor.md`.

### Membership toggle

1. `ProjectHandler.toggle_agent()` loads session keys, adds/removes one key, and calls `_save_members()`.
2. `_save_members()` preserves existing records; for new `special:*`, `get_special_agent()` supplies display name/role/write capability; gateway keys remain blank in persisted metadata.
3. `save_team()` writes `team.json`; best-effort snapshot refresh writes `awareness.json` with current `team_size`; no git commit occurs.
4. Toggle rebuilds routing and refreshes the agent list as before.

### Onboarding completion

1. Supervisor follows the separate onboarding template and calls/causes the existing workflow completion operation.
2. `advance_phase(project_path, "onboarding")` invokes `clean_manifest_skeleton()` at the completion boundary, then writes the workflow transition.
3. Subsequent `is_project_onboarded()` and prompt composition see real manifest/context content; comment-only placeholders no longer remain in the completed manifest.

## 4. File Change Summary

| File | Change type | Estimate | Risk |
|---|---|---:|---|
| `prompts/default_agents/supervisor.yaml` | New | 20–35 lines | Medium — validation/provider/tool names |
| `prompts/system/supervisor.md` | New | 40–80 lines | Medium — prompt behavior |
| `prompts/default_agents/auxilium.yaml` | Edit | 1 line | Low |
| `utils/agent_defs.py` | Edit | 10–25 lines | Medium — per-file default seeding |
| `utils/prompt_loader.py` | Edit | 15–30 lines | High — prompt selection/gating |
| `agent/context.py` | Edit | 5–10 lines | Medium — role fallback |
| `ui/handlers/project_handler.py` | Edit | 45–80 lines | High — persistence and lifecycle |
| `ui/window.py` | Edit | 20–35 lines | Medium — deferred GTK callback wiring |
| `utils/project_awareness.py` | Edit | 60–100 lines | High — section-aware manifest cleanup |
| `utils/workflow_state.py` | Edit | 10–20 lines | Medium — completion trigger/circular imports |
| `tests/*` | New/edit | focused suites | Medium |
| `docs/ARCHITECTURE.md` | Edit | focused section | Low |

## 5. Implementation Order

1. Add Supervisor system prompt and YAML; verify YAML parses, its prompt exists, and every tool is registered.
2. Flip Auxilium's auto-add flag; add registry/definition tests.
3. Change prompt-loader onboarding and Supervisor template selection; test Supervisor/non-Supervisor/gateway cases.
4. Implement manifest cleanup helper and workflow completion hook; test all parser edge cases before wiring awareness changes.
5. Update awareness snapshot behavior and `_save_members()` metadata/commit behavior; run project-awareness and project-handler tests.
6. Add created-only callback and wire the System bubble in `ui/window.py`; test callback arguments, exact wording, and `None` chat-box behavior.
7. Update architecture documentation and run the full relevant test suite plus lint/type checks configured by the repository.
8. Perform the self-audit below and a repository-wide search for the removed hardcoded patterns.

## 6. Acceptance Criteria

- [ ] A fresh/default registry contains Supervisor with role `supervisor`, `auto_add_to_projects=False`, and write capability derived from its tools.
- [ ] Auxilium remains auto-open but is not auto-added to project teams.
- [ ] Onboarding-template selection is controlled by `agent_role == "supervisor"` plus onboarding state; it does not call `get_project_onboarding_agents()` for the gate and does not use the old Coder condition.
- [ ] Supervisor receives both its role prompt and the separate onboarding template for an un-onboarded project.
- [ ] Built-in YAMLs seed only missing user files; once `~/.config/crabcakes/agents/supervisor.yaml` exists, that user file is the sole load-time source of truth and is not migrated/deleted.
- [ ] Creating a project emits exactly one System bubble in `project:<name>` with the specified instruction, without auto-adding Supervisor.
- [ ] Any legacy/opt-in auto-added team records use registry display name/role/can-write values.
- [ ] Toggling a new local special agent backfills registry metadata; gateway metadata remains blank for display-time resolution.
- [ ] Team changes via `_save_members()` explicitly refresh `awareness.json` after team save.
- [ ] `build_awareness_dict()` remains read-only and does not write `awareness.json`.
- [ ] Successful onboarding completion strips only comment-only manifest sections.
- [ ] Existing project open does not emit the new-project bubble.
- [ ] Relevant tests, full test suite, and configured lint/type checks pass, with GTK-only environmental skips explicitly reported.

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| User Supervisor YAML already exists | It shadows the built-in; never overwrite/delete it. |
| Supervisor definition missing/invalid | Registry lookup fails safely; no onboarding agent is auto-added and prompt composition skips the optional onboarding template. |
| Auxilium only in registry | It opens automatically but does not enter new project teams. |
| Existing project already has Auxilium | Do not remove it as part of this change; only future auto-add behavior changes. |
| User manually adds Supervisor | `_save_members()` resolves its registry metadata. |
| Gateway member `agent:...` | Persist session key with empty name/role and false write flag; display layer resolves the name. |
| Existing team member record | Preserve its stored metadata; do not unexpectedly overwrite user edits. |
| Duplicate member keys in input | Preserve current input/order semantics; do not add duplicates beyond the existing team assignment behavior. |
| Awareness write fails | Log/ignore the snapshot failure; team save and returned awareness dict still succeed where their own writes permit. |
| Manifest has comments plus real text | Preserve the section; remove only sections with no real body text. |
| Manifest missing, unreadable, or malformed | Cleanup is a safe no-op; workflow transition still completes. |
| `advance_phase()` receives unknown phase | Preserve existing `ValueError`. |
| Project chat box unavailable after create | Do not raise; skip bubble and leave project creation successful. |
| GTK bubble renderer returns `None` | Do not append; do not call append on `None`. |
| Existing project opened rather than created | No creation System bubble. |

## 8. ARCHITECTURE.md Updates Required

Update the relevant project-awareness/agent-registry/UI-handler sections to state:

- Supervisor is the built-in onboarding/orchestration special agent; user definitions override built-ins without destructive migration.
- `auto_add_to_projects` controls project auto-membership only; the onboarding-template gate is explicitly `agent_role == "supervisor"`, so manual Supervisor addition and onboarding cannot contradict each other.
- Project-created System bubbles are rendered by the composition root using the existing ChatRenderHandler path, while ProjectHandler exposes only lifecycle callbacks.
- Team persistence refreshes awareness snapshots without implicit git commits.
- Manifest skeleton cleanup is a pure `utils.project_awareness` responsibility invoked at onboarding workflow completion.

## 9. Spec Self-Audit (Rule 9)

- **Code samples traced:** The constructor/backfill sample preserves existing members, resolves only local `special:*` definitions, and leaves gateway metadata blank. The renderer sample uses the verified `render_sync` signature and `project:<name>` session-key convention; its deferred dispatch is required because tab creation is asynchronous.
- **Signatures checked:** `create_project`, `open_project`, `render_sync`, `get_chat_box_for_session`, `build_awareness_snapshot`, `save_awareness_snapshot`, `build_awareness_dict`, `advance_phase`, `get_special_agent`, and `get_project_onboarding_agents` were read from source or verified by supplied discovery facts. `build_awareness_dict` is intentionally not called for persistence.
- **Contradiction check:** Supervisor is `auto_add_to_projects: false`, while the creation bubble instructs manual `+` addition; the auto-add hook is a no-op for current defaults, so clicking `+` cannot remove a pre-existing Supervisor.
- **Seed-order check:** default seeding is explicitly changed to per-file missing checks, so an existing unrelated user agent cannot suppress a missing built-in Supervisor.
- **Exceptions enumerated:** Registry loading, project initialization, workflow I/O, team loading/saving, awareness snapshot I/O, manifest reads/writes, and GTK/chat-box availability are all treated as non-fatal where existing code is non-fatal. `advance_phase` retains `ValueError` for invalid phase names. The implementation must inspect exact `OSError`/JSON/YAML failure behavior before narrowing catches.
- **Keys verified:** special keys are `special:<role>` from `_load_registry`; project chat keys are `project:<name>`; gateway keys remain `agent:...`; team persistence is a list of `TeamMember` objects in `ProjectTeam`.
- **Return values handled:** `create_project` returns path/`None`; `render_sync` may return `None`; `save_awareness_snapshot` returns `None`; cleanup returns a documented changed/no-op boolean; `advance_phase` returns `None` or raises `ValueError`.
- **Data flow traced:** create → initialize → open → deferred callback bubble; toggle → team save → explicit snapshot; Supervisor prompt composition → explicit role gate + separate onboarding template; workflow completion → section-aware manifest cleanup.
- **Cache safety check:** `build_awareness_dict()` remains read-only; no awareness snapshot write is permitted from the prompt-build path.
- **No unsupported scope expansion:** Coder/Debugger, feed/review systems, onboarding-template prose, and review layer are explicitly excluded.

## 10. Completion Verification Plan (Rule 10)

Before declaring implementation complete, the implementer must:

1. **Scope checklist:** check every file in §2 and the tests/docs listed in §2.9, recording changed line ranges.
2. **Tests:** run the relevant focused suites and the full configured suite; paste actual pytest output including pass/fail/skip counts. If GTK tests cannot run in the sandbox, list those exact tests and run all non-GTK tests.
3. **Pattern sweep:** run searches over the entire repository for removed patterns, at minimum:
   - `agent_role == "coder" and not is_project_onboarded`
   - `get_project_onboarding_agents()` used in the prompt-loader gate (it must not be)
   - `role="onboarding guide"`
   - `can_write=True` in `_auto_add_onboarding_agents`
   - `_git_commit_if_available(path, "update team roster")`
   - `auto_add_to_projects: true` in `auxilium.yaml`
   - `grep -A 80 "def build_awareness_dict" utils/project_awareness.py | grep "save_awareness_snapshot"`
     — must return zero matches inside the function body.
   - `clean_manifest_skeleton` (must be present in the new utility and workflow hook)
   - `supervisor.yaml` (must be present and contain `auto_add_to_projects: false`)
   - `grep -rn "set_on_project_created" --include="*.py" .`
   - `grep -rn "_on_project_created_system_bubble" --include="*.py" .`
     — each callback grep must return exactly one declaration, one wiring reference, and test references as applicable.
4. **Declaration:** report complete only when the scope checklist, actual test output, and zero-remnant/new-pattern verification are all present. Otherwise report the exact blocker.
