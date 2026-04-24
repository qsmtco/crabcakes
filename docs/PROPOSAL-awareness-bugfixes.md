# Project Awareness Bug Fix Proposal

**Date:** 2026-04-24
**Author:** Qaster
**Status:** Proposed — Awaiting Captain JAQx Approval
**Source Audit:** `docs/ADVERSARIAL_AUDIT_PROJECT_AWARENESS.md` by QTR (Kage-7)
**Affects:** `utils/project_awareness.py`, `ui/handlers/project_handler.py`, `ui/handlers/chat_handler.py`

---

## 1. Objective

Fix all 9 bugs identified in QTR's adversarial audit of the Project Awareness System. This proposal addresses every finding — including the 3 pre-existing bugs not introduced by the awareness system — to bring the feature to production quality.

---

## 2. Architecture Compliance

All fixes adhere to ARCHITECTURE.md:

- **Section 8.6 (Handler Pattern):** Fixes in `project_handler.py` and `chat_handler.py` remain within handler boundaries. No cross-handler imports added.
- **Section 3.11 (utils/):** Fixes in `project_awareness.py` remain pure Python — no GTK, no network, no imports from `ui/` or `agent/`.
- **Section 3.3 (models/):** No models changes needed. `models/team.py` is untouched.
- **Section 5 (Callback Pattern):** No new callbacks. All fixes are internal to their owning module.
- **Section 7.6 (Thread Safety):** All GTK calls in handler fixes continue via `GLib.idle_add()`.
- **Section 8.5 (Testing):** Each fix includes a corresponding test.

---

## 3. Bug Fix Specifications

### Bug #1 — HIGH: `.crabcakes` as a file crashes the app

**File:** `utils/project_awareness.py` — `init_project_config()`
**Architecture home:** `utils/project_awareness.py` owns all `.crabcakes/` directory lifecycle.

**Fix:** Add a guard at the top of `init_project_config()` and `_ensure_crabcakes_dir()`:

```python
def _ensure_crabcakes_dir(project_path: str) -> str:
    d = get_crabcakes_dir(project_path)
    if os.path.isfile(d):
        raise RuntimeError(
            f"Cannot create .crabcakes/ directory: "
            f"a file named '.crabcakes' already exists at {project_path}"
        )
    os.makedirs(d, exist_ok=True)
    return d
```

**Wire-up check:** `_ensure_crabcakes_dir` is called by `init_project_config()`, `save_team()`, `save_project_context()`, `save_awareness_snapshot()`, `generate_project_skeleton()`, and `_migrate_or_create_manifest()`. All paths are covered by this single fix.

**Test:** Create a temp project, `touch .crabcakes`, call `init_project_config()`, assert `RuntimeError`.

---

### Bug #2 — MEDIUM: `close_project()` doesn't clear `_active_project_path`

**File:** `ui/handlers/project_handler.py` — `close_project()`
**Architecture home:** `ProjectHandler` owns `_active_project_name` and `_active_project_path` (Section 3.19).

**Fix:** Add one line to `close_project()`:

```python
def close_project(self, name: str):
    self._active_project_name = None
    self._active_project_path = None  # ← ADD THIS
    self._agent_to_project.remove_project(name)
    self._dispatch(lambda: self._lp.refresh_agents_with_project(None))
    for cb in self._on_project_opened:
        cb(None, None)
```

**Wire-up check:** `close_project()` is called from `window.py` line ~947 when a project tab is closed. The fix ensures both name and path are cleared atomically.

**Test:** Open project, close project, assert `get_active_project_path()` returns `None`.

---

### Bug #3 — MEDIUM: Empty `session_key` passed to `on_res_confirmed`

**File:** `ui/handlers/chat_handler.py` — `on_res_confirmed()`
**Architecture home:** `ChatHandler` owns all chat event processing (Section 3.14).

**Fix:** Guard against empty `session_key`:

```python
def on_res_confirmed(self, session_key: str):
    if not session_key:
        return
    if self._on_res_confirmed is not None:
        self._on_res_confirmed(session_key)
```

**Wire-up check:** `on_res_confirmed` is called from `window._on_ws_event()` when a `res` event arrives. The guard prevents downstream `ActivityHandler` state corruption.

**Test:** Call `on_res_confirmed("")` — assert no crash, no callback fired.

---

### Bug #4 — MEDIUM: Silent empty team when `.crabcakes/` doesn't exist at resolved path

**File:** `utils/project_awareness.py` — `load_team()`
**Architecture home:** `utils/project_awareness.py` owns team data loading.

**Fix:** Add a warning log when `.crabcakes/team.json` is expected but missing after a project has been opened:

```python
import logging
_logger = logging.getLogger(__name__)

def load_team(project_path: str) -> ProjectTeam:
    path = os.path.join(get_crabcakes_dir(project_path), TEAM_FILENAME)
    if not os.path.isfile(path):
        _logger.warning(
            "load_team: no team.json at %s — returning empty team. "
            "Was init_project_config() called for this project?",
            path
        )
        return ProjectTeam()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ProjectTeam.from_dict(data)
    except (json.JSONDecodeError, OSError):
        _logger.warning("load_team: corrupt or unreadable team.json at %s", path)
        return ProjectTeam()
```

**Wire-up check:** `load_team()` is called from `_load_members()`, `build_awareness_block()`, `build_awareness_snapshot()`, and the `save_members()` legacy wrapper. All paths now emit diagnostic logs.

**Test:** Call `load_team()` on a path with no `.crabcakes/` — assert warning logged, empty team returned.

---

### Bug #5 — LOW: Inconsistent truncation between prefix injection and file reads

**File:** `utils/project_awareness.py` — `build_awareness_block()`
**Architecture home:** `utils/project_awareness.py` owns awareness content assembly.

**Fix:** Increase truncation limits and add a `[truncated — full content in .crabcakes/project.md]` marker so agents know the truncation boundary:

```python
# In build_awareness_block():
manifest = load_project_manifest(project_path)
if manifest:
    truncated = manifest[:4000]  # was 2000
    if len(manifest) > 4000:
        truncated += "\n[... truncated — full content in .crabcakes/project.md ...]"
    parts.append(f"## Project Manifest\n\n{truncated}")

# Similarly for context:
truncated = context[:6000]  # was 3000
if len(context) > 6000:
    truncated += "\n[... truncated — full content in .crabcakes/context.md ...]"
```

**Wire-up check:** `build_awareness_block()` is called from `chat_handler._build_awareness_prefix()` and `agent/context.py build_system_prompt()`. Both paths benefit.

**Test:** Create a project with a 5KB manifest — assert marker appears in awareness block.

---

### Bug #6 — LOW: Unbounded `_awareness_sent` set growth

**File:** `ui/handlers/chat_handler.py` — `_awareness_sent`
**Architecture home:** `ChatHandler` owns message sending and awareness state (Section 3.14).

**Fix:** Clear entries for removed agents when `toggle_agent` fires a membership change. Add a cleanup method called from `ProjectHandler.toggle_agent()` via the existing `set_on_members_changed` callback:

In `ui/handlers/chat_handler.py`:
```python
def cleanup_awareness_for_project(self, project_name: str, current_members: list[str]) -> None:
    """Remove _awareness_sent entries for agents no longer in this project."""
    current_keys = {f"{project_name}:{m}" for m in current_members}
    to_remove = [k for k in self._awareness_sent if k.startswith(f"{project_name}:") and k not in current_keys]
    for k in to_remove:
        self._awareness_sent.discard(k)
```

In `ui/window.py`, wire the callback:
```python
# In _build(), after chat_handler and project_handler are created:
self._project_handler.set_on_members_changed(
    lambda n, m: self._chat_handler.cleanup_awareness_for_project(n, m)
)
```

**Wire-up check:** The `set_on_members_changed` callback already fires from `ProjectHandler.toggle_agent()`. The new cleanup runs on the same callback chain.

**Architecture check:** This follows the callback pattern (Section 5) — `window.py` wires `ChatHandler` to `ProjectHandler` events. No cross-handler import.

**Test:** Add agent to project, send message (adds to `_awareness_sent`), remove agent, assert entry removed.

---

### Bug #7 — LOW: Unhandled `PermissionError` on team save

**File:** `utils/project_awareness.py` — `save_team()`, `save_project_context()`, `save_awareness_snapshot()`
**Architecture home:** `utils/project_awareness.py` owns all file writes to `.crabcakes/`.

**Fix:** Wrap all file writes in try/except with logging:

```python
import logging
_logger = logging.getLogger(__name__)

def save_team(project_path: str, team: ProjectTeam) -> None:
    try:
        _ensure_crabcakes_dir(project_path)
        path = os.path.join(get_crabcakes_dir(project_path), TEAM_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(team.to_dict(), f, indent=2)
    except OSError as e:
        _logger.error("save_team: failed to write %s: %s", project_path, e)
```

Same pattern for `save_project_context()` and `save_awareness_snapshot()`.

**Wire-up check:** These are called from `_save_members()` in `ProjectHandler`, which is called from `toggle_agent()`. The error is logged instead of crashing the UI.

**Test:** `chmod 000 .crabcakes/team.json`, call `save_team()`, assert no crash, assert error logged.

---

### Bug #8 — LOW: Hardcoded git branch `"main"`

**File:** `utils/project_awareness.py` — `_get_git_info()`
**Architecture home:** `utils/project_awareness.py` owns awareness state. `utils/git_ops.py` provides git access.

**Fix:** Implement branch detection in `git_ops.py` and use it:

In `utils/git_ops.py`, add:
```python
def get_branch(project_path: str) -> GitResult:
    """Return current git branch name."""
    return _run_git(project_path, ["branch", "--show-current"])
```

In `utils/project_awareness.py` `_get_git_info()`:
```python
from utils.git_ops import get_head_sha, log, status, get_branch

branch_result = get_branch(project_path)
branch = branch_result.stdout.strip() if branch_result.success else "unknown"
```

**Wire-up check:** `get_branch` follows the existing `get_head_sha()` pattern in `git_ops.py`. Used only in `_get_git_info()`.

**Architecture check:** `utils/git_ops.py` is the single source of truth for git operations (Section 3.21f). New function follows existing `GitResult` return pattern.

**Test:** Create a git repo, checkout a branch, call `get_branch()`, assert correct name.

---

### Bug #9 — LOW: Forward-to commands bypass awareness injection

**File:** `ui/handlers/chat_handler.py` — `_show_echo_and_forward`, `_show_broadcast_and_forward`
**Architecture home:** `ChatHandler` owns all message sending (Section 3.14).

**Fix:** Thread awareness injection through the command result's `forward_text`. Add a helper that wraps forward text with the awareness prefix when a project is active:

```python
def _maybe_inject_awareness(self, session_key: str, text: str) -> str:
    """Inject awareness prefix if session is in a project and awareness not yet sent."""
    project_name = self._agent_to_project.get_project(session_key)
    if not project_name:
        return text
    key = f"{project_name}:{session_key}"
    if key in self._awareness_sent:
        return text
    project_path = self._project_handler.get_active_project_path() if self._project_handler else None
    if not project_path:
        return text
    try:
        from utils.project_awareness import build_awareness_block
        block = build_awareness_block(project_path)
        if block.strip():
            self._awareness_sent.add(key)
            return f"[Project Context]\n{block}\n\n[Message]\n{text}"
    except Exception:
        pass
    return text
```

Then call it in the forward paths:
```python
# In _show_echo_and_forward / _show_broadcast_and_forward:
self._gw.send_message(
    result.forward_to,
    self._maybe_inject_awareness(result.forward_to, result.forward_text)
)
```

**Wire-up check:** Forward paths call `gw.send_message()` — the wrapper is inserted right before that call.

**Architecture check:** No new imports between handlers. Uses existing `ChatHandler._agent_to_project` and `ProjectHandler.get_active_project_path()` (via injected `_project_handler`).

**Test:** Open project, use `ask @Agent` command, assert awareness prefix present in forwarded message.

---

## 4. Implementation Order

| Order | Bug | Severity | Risk | Files Changed |
|-------|-----|----------|------|---------------|
| 1 | #1 | HIGH | App crash on edge case | `utils/project_awareness.py` |
| 2 | #2 | MEDIUM | Stale state after close | `ui/handlers/project_handler.py` |
| 3 | #3 | MEDIUM | State machine corruption | `ui/handlers/chat_handler.py` |
| 4 | #4 | MEDIUM | Silent data loss | `utils/project_awareness.py` |
| 5 | #7 | LOW | Crash on permission error | `utils/project_awareness.py` |
| 6 | #8 | LOW | Wrong data shown | `utils/git_ops.py`, `utils/project_awareness.py` |
| 7 | #5 | LOW | Inconsistent truncation | `utils/project_awareness.py` |
| 8 | #9 | LOW | Missing context | `ui/handlers/chat_handler.py` |
| 9 | #6 | LOW | Unbounded growth | `ui/handlers/chat_handler.py`, `ui/window.py` |

---

## 5. Files Changed Summary

| File | Bugs Fixed | Nature of Change |
|------|-----------|-----------------|
| `utils/project_awareness.py` | #1, #4, #5, #7, #8 | Guards, logging, error handling, truncation limits |
| `ui/handlers/project_handler.py` | #2 | One-line state cleanup |
| `ui/handlers/chat_handler.py` | #3, #6, #9 | Validation, cleanup, awareness for forwards |
| `ui/window.py` | #6 | Wire cleanup callback |
| `utils/git_ops.py` | #8 | New `get_branch()` function |
| `tests/test_project_awareness.py` | #1, #4, #5, #7 | New test cases |
| `tests/test_project_handler.py` | #2 | New test case |
| `tests/test_chat_handler.py` | #3, #6, #9 | New test cases |
| `tests/test_git_ops.py` | #8 | New test case |

---

## 6. ARCHITECTURE.md Updates Required

Per Section 0, the following updates are needed in the same commit:

| Section | Update |
|---------|--------|
| 3.21f `utils/git_ops.py` Public API | Add `get_branch(project_path) -> GitResult` |
| 3.19 `ProjectHandler` Public API | No change — fix is internal |
| 3.14 `ChatHandler` | Document `cleanup_awareness_for_project()` and `_maybe_inject_awareness()` |
| 11 File Inventory | Update line counts for changed files |

---

## 7. Verification Plan

After each fix:
1. Run `python3 -c "from <module> import ..."` — import check
2. Run `pytest tests/test_<relevant>.py -x` — targeted tests
3. Run `pytest tests/ --ignore=tests/test_chat_handler.py --ignore=tests/test_convergence.py --ignore=tests/test_command_models.py -q` — full suite

After all fixes:
1. Full test suite green
2. Manual test: open project, send message, toggle agent, close project — no crashes
3. Manual test: `touch .crabcakes` in a project dir, open project — graceful error, no crash

---

*This proposal is the implementation plan. Upon approval, fixes will be applied in the specified order with checkpoint verification after each.*
