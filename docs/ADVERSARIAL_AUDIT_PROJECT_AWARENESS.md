# Adversarial Audit — Project Awareness System

**Auditor:** QTR (Kage-7)
**Date:** 2026-04-24
**Status:** READ-ONLY — Findings reported, no code changes made
**Files Audited:** `models/team.py`, `utils/project_awareness.py`, `utils/projects.py`, `ui/handlers/project_handler.py`, `ui/handlers/chat_handler.py`, `agent/context.py`, `ui/window.py`, `tests/test_project_awareness.py`, `tests/test_project_handler.py`, `tests/test_projects.py`, `models/command.py`, `ui/handlers/agent_runtime_handler.py`

---

## Methodology

Adversarial debugger mode. The goal: destroy every assumption the code makes about its own correctness. Slow, methodical, exhaustive. No verification that the code works — only proof that it can fail.

Assumptions challenged:
- Happy path vs. sad path
- Type and value validity at every boundary
- Race conditions and out-of-order calls
- Missing files, empty files, files as directories
- Silent failures vs. loud failures
- Unbounded growth and resource leaks
- External contract violations (git, filesystem, gateway)

---

## BUG #1
**Severity:** HIGH

**Assumption violated:** ".crabcakes/ is always a directory"

**Attack vector:** User creates a FILE named `.crabcakes` inside a project directory, then opens that project.

**Reproduction:**
1. `mkdir /tmp/testproject`
2. `touch /tmp/testproject/.crabcakes` — a file, not a directory
3. Open project "testproject" in crabcakes

**Root cause:** `init_project_config()` checks `os.path.isdir(crab_dir)` — this returns `True` for a file that exists, because the path technically exists. The code then falls through to `_ensure_crabcakes_dir()` which calls `os.makedirs(d, exist_ok=True)` on a path that is a FILE. This raises `FileExistsError`. Unhandled. Crashes `open_project()`, project tab never opens.

**Code location:** `utils/project_awareness.py` — `init_project_config()`

**Fix:** Add a guard before `_ensure_crabcakes_dir()`:
```python
if os.path.isfile(crab_dir):
    raise RuntimeError(f"Cannot create .crabcakes/: a file named .crabcakes already exists at {project_path}")
```

---

## BUG #2
**Severity:** MEDIUM

**Assumption violated:** "The active project name and active project path are always cleared together"

**Attack vector:**
1. User opens project "Alpha" (/path/to/alpha)
2. User closes project (`close_project("Alpha")`)
3. `get_active_project_path()` still returns `/path/to/alpha`
4. `get_active_project_name()` returns `None`
5. Any code relying on both being consistent will see a stale path with no project

**Root cause:** `close_project()` sets `_active_project_name = None` but does NOT clear `_active_project_path`. `open_project()` sets both, but `close_project()` only clears the name.

**Code location:** `ui/handlers/project_handler.py` — `close_project()`

**Fix:**
```python
def close_project(self, name: str):
    self._active_project_name = None
    self._active_project_path = None  # ← ADD THIS LINE
    self._agent_to_project.remove_project(name)
    ...
```

---

## BUG #3
**Severity:** MEDIUM

**Assumption violated:** "on_res_confirmed is always called with a valid, non-empty session_key"

**Attack vector:**
1. PM sends a message
2. Gateway sends res event with payload: `{"req_id": "...", "sessionKey": ""}`
3. `ChatHandler.on_res_confirmed("")` is called with empty string
4. `ActivityHandler.on_res_confirmed("")` transitions state for wrong/no session

**Root cause:** `ChatHandler.on_res_confirmed()` passes the `session_key` from the gateway payload directly without validation. `_on_res_stub` dispatches it to `self._on_event("res", {...})` which routes to `ChatHandler.on_res_confirmed()` without checking for empty string.

**Code location:** `ui/handlers/chat_handler.py` — `on_res_confirmed()`, `ui/handlers/gateway_handler.py` — `_on_res_stub`

**Fix:** Validate session_key before calling the callback:
```python
def on_res_confirmed(self, session_key: str):
    if not session_key:
        return
    if self._on_res_confirmed is not None:
        self._on_res_confirmed(session_key)
```

---

## BUG #4
**Severity:** MEDIUM

**Assumption violated:** "load_members always finds the project it was called for and that project has awareness state"

**Attack vector:**
1. User's `CRABCAKES_PROJECTS_DIR` points to a directory that gets updated externally (sync, rename, etc.)
2. A project gets a new path on disk
3. `ProjectHandler.open_project()` was never called for this project in this session
4. Code calls `load_members("projectname")` by name
5. `load_projects()` returns the new path
6. But `.crabcakes/` was created at the OLD path — new path has no `.crabcakes/`
7. `load_team()` returns empty `ProjectTeam` silently
8. PM thinks agents are in the project but they're not — empty team, no context

**Root cause:** `load_members()` in `utils/projects.py` resolves project name → path via `load_projects()`, but if the project was never opened in this session, the path could point to a directory without a `.crabcakes/` subdirectory. The silent fallback to empty team is misleading.

**Code location:** `utils/projects.py` — `load_members()`, `utils/project_awareness.py` — `load_team()`

**Fix:** Require that `open_project()` has been called first (enforce path is cached), or raise an error when `.crabcakes/` doesn't exist at the resolved path rather than returning a misleading empty team.

---

## BUG #5
**Severity:** LOW

**Assumption violated:** "The awareness block we show agents is consistent with what agents can read themselves"

**Attack vector:**
1. Project has a large README.md (40KB) migrated to `.crabcakes/project.md`
2. PM opens project, sends message to gateway agent
3. Agent receives: `[Project Context]` + manifest (first 2000 chars truncated) + context (first 3000 chars truncated)
4. Agent reads `.crabcakes/project.md` and `.crabcakes/context.md` directly via their tools — FULL content
5. Agent's context is inconsistent: truncated in the prefix, full in file reads

**Root cause:** The awareness block sent as a message prefix is truncated independently from what agents can read from `.crabcakes/` files directly. This is a design inconsistency with no visible indicator.

**Code location:** `utils/project_awareness.py` — `build_awareness_block()`

**Fix:** Document this inconsistency prominently, or increase truncation limits to reduce the gap (e.g., 10KB for manifest, 15KB for context).

---

## BUG #6
**Severity:** LOW

**Assumption violated:** "The _awareness_sent set grows and shrinks with project membership changes"

**Attack vector:**
1. User repeatedly toggles agents in and out of projects (adds/removes from team.json)
2. Each toggle rebuilds the routing table but NEVER clears `_awareness_sent`
3. `_awareness_sent` accumulates `"project:agent"` entries forever
4. At 10,000 entries × ~50 bytes ≈ 500KB. Not large, but unbounded

**Root cause:** `_awareness_sent` is only added to, never cleaned up. No size limit, no LRU eviction, no removal when agents leave projects.

**Code location:** `ui/handlers/chat_handler.py` — `_awareness_sent`

**Fix:** Remove entries when an agent is toggled out of a project, or cap the set size with LRU eviction.

---

## BUG #7
**Severity:** LOW

**Assumption violated:** "save_team always succeeds or the caller handles the failure gracefully"

**Attack vector:**
1. Project directory exists and is found via `load_projects()`
2. User has no write permission in `.crabcakes/`
3. `save_members()` → `_save_members()` → `awareness.save_team()` → JSON write
4. Raises `PermissionError` — unhandled, propagates to `toggle_agent()` caller
5. Toggle fails with an exception the PM sees as a crash

**Root cause:** `save_team()` uses `open(path, "w")` with no error handling. If the file exists but is not writable, or the directory is read-only, it crashes.

**Code location:** `utils/project_awareness.py` — `save_team()`

**Fix:** Wrap the file write in try/except, log error, return gracefully to caller:
```python
def save_team(project_path: str, team: ProjectTeam) -> None:
    try:
        _ensure_crabcakes_dir(project_path)
        path = os.path.join(get_crabcakes_dir(project_path), TEAM_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(team.to_dict(), f, indent=2)
    except OSError as e:
        import logging
        logging.error("Failed to save team: %s", e)
```

---

## BUG #8
**Severity:** LOW

**Assumption violated:** "Git branch is always 'main' for awareness snapshot"

**Attack vector:** Any project using a non-main git branch (e.g., "develop", "feature/auth", "main").

**Reproduction:**
1. Open a project on git branch "feature/new-ui"
2. `build_awareness_snapshot` returns `"branch": "main"` — always hardcoded
3. Agent sees wrong branch name in project context

**Root cause:** `_get_git_info()` does not call any git_ops function that returns the actual branch name. The field is hardcoded to `"main"` in the return dict.

**Code location:** `utils/project_awareness.py` — `_get_git_info()`

**Fix:** Either implement branch detection via `git branch --show-current` or `git symbolic-ref --short HEAD` in git_ops, or remove the `branch` field from the snapshot until it is properly implemented.

---

## BUG #9
**Severity:** LOW

**Assumption violated:** "The awareness prefix is injected for all project member messages including forwarded messages"

**Attack vector:**
1. PM opens project "Alpha" with agents A and B
2. PM sends message to project → A and B receive awareness prefix (tracked in `_awareness_sent`)
3. PM uses `` `ask @A — question` `` command (forward_to path)
4. Command handler's forward_to path renders the echo and calls `gw.send_message(result.forward_to, result.forward_text)` directly
5. This bypasses `_build_awareness_prefix()` entirely
6. Agent A receives the forwarded message WITHOUT the project context prefix
7. Agent A doesn't know which project this is about

**Root cause:** The forward-to commands in `ChatHandler` render the echo and call `gw.send_message()` directly, bypassing the awareness injection path. Documented as a known limitation in the proposal, but the UX impact is real.

**Code location:** `ui/handlers/chat_handler.py` — `_show_echo_and_forward`, `_show_broadcast_and_forward`

**Fix:** Thread project context through the command result so that `forward_to` also gets the prefix, or document prominently that commands with forwarding do not inject project awareness.

---

## Summary

| Bug # | Severity | Category | File(s) |
|-------|----------|----------|---------|
| 1 | HIGH | Filesystem edge case | `utils/project_awareness.py` |
| 2 | MEDIUM | State inconsistency | `ui/handlers/project_handler.py` |
| 3 | MEDIUM | Missing validation | `ui/handlers/chat_handler.py`, `ui/handlers/gateway_handler.py` |
| 4 | MEDIUM | Silent failure | `utils/projects.py`, `utils/project_awareness.py` |
| 5 | LOW | Inconsistent truncation | `utils/project_awareness.py` |
| 6 | LOW | Unbounded growth | `ui/handlers/chat_handler.py` |
| 7 | LOW | Missing error handling | `utils/project_awareness.py` |
| 8 | LOW | Hardcoded value | `utils/project_awareness.py` |
| 9 | LOW | Forward path bypass | `ui/handlers/chat_handler.py` |

**Total: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 5 LOW**

**Most likely to bite first:** Bug #1. If a user has any stray file named `.crabcakes` inside a project directory (or creates one), opening that project crashes the entire app with an unhandled `FileExistsError`.

---

*This report is READ-ONLY. No code was modified.*
