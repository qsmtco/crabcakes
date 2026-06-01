# SPEC: Outstanding Audit Fixes (A–G)

**Date:** 2026-05-31
**Author:** Qaster (implementation supervisor)
**Scope:** 7 outstanding issues from QTR's architecture audit
**Aligned with:** `docs/ARCHITECTURE.md` (current as of commit 51f6e55)

---

## Overview

This spec addresses 7 issues identified in QTR's architecture audit dated 2026-05-31. Items are ordered by dependency — earlier items must be completed first because later items may depend on them.

---

## Phase 1 — ARCHITECTURE.md Update (Issue A)

**Severity:** Critical
**Estimated scope:** 1 file, ~200 lines changed
**Depends on:** Nothing (do this LAST — after all other changes are committed)

### Problem

ARCHITECTURE.md is stale in three ways:
1. **Section 2 (Directory Structure)** — lists files that don't exist, missing files that do exist
2. **Section 12 (File Inventory)** — window.py still listed as "~1026 lines" (now 833), some line counts stale
3. **Section 3.6** — lists extracted methods that no longer exist in window.py

### What to Change

**Section 2 — Directory Structure tree:**
- `ui/window.py` description: update from "~1026 lines — MainWindow + all handler wiring + business logic (audit, MCP hot-reload, forward)" to "~833 lines — MainWindow — assembles all components, wires callbacks. Business logic extracted to handlers (see Section 3.6)."
- `ui/handlers/command_handler.py` description: update from "~525 lines — slash-prefix command parser + @mention resolution (Phase 7)" to include note about auto-registration of 21 commands
- `ui/handlers/feed_handler.py` description: add note about `add_audit_report_card()` method
- `ui/handlers/agent_runtime_handler.py` description: add note about `reload_agents_and_mcp()` method
- `ui/handlers/agent_builder_handler.py` description: add note about `delete_agent_with_confirmation()` method
- Verify all files listed actually exist; remove any that don't
- Add any new files that exist but aren't listed (run `find` to compare)

**Section 3.6 — window.py:**
- Remove `_on_audit_report_card`, `_on_agent_saved`, `_on_agent_deleted`, `_confirm_delete_agent`, `_register_stub_commands` from any mention
- Update the "callback handlers not yet extracted" list to remove the 5 extracted methods
- Note that these methods now live in their respective handlers

**Section 12 — File Inventory:**
- Update `window.py` line count from ~1026 to ~833
- Update `command_handler.py` line count (now includes auto-registration)
- Update any other stale line counts (run `wc -l` on each file)

**Section 3 — Module Responsibilities:**
- Add public API entries for new handler methods:
  - `FeedHandler.add_audit_report_card(report, project_name)` — Section 3.x
  - `AgentRuntimeHandler.reload_agents_and_mcp(on_complete)` — Section 3.x
  - `AgentBuilderHandler.delete_agent_with_confirmation(name)` — Section 3.x
  - `CommandHandler.__init__(..., collab_handler, task_handler, review_handler, session_handler)` — update constructor params in Section 3.x

### Verification

```bash
# Every file listed in Section 2 exists
grep -oP '[\w/]+\.py' docs/ARCHITECTURE.md | sort -u | while read f; do
  [ -f "$f" ] || echo "MISSING: $f"
done

# Line counts in Section 12 match reality
wc -l ui/window.py ui/handlers/command_handler.py ui/handlers/feed_handler.py

# No extracted methods still listed as window.py methods
grep -c '_on_audit_report_card\|_register_stub_commands\|_on_agent_saved\|_on_agent_deleted\|_confirm_delete_agent' docs/ARCHITECTURE.md
```

---

## Phase 2 — models/__init__.py Exports (Issue B)

**Severity:** Critical
**Estimated scope:** 1 file, ~15 lines changed
**Depends on:** Nothing

### Problem

`models/__init__.py` exports 9 names but `models/` contains 13 modules. Used-but-not-exported symbols:
- `ActivityBubble` from `activity.py`
- `ConversationSnapshot`, `SnapshotMessage` from `conversation_snapshot.py`
- `TeamMember`, `ProjectTeam` from `team.py`
- `ReviewState` from `review_state.py`

These are imported directly (e.g., `from models.activity import ActivityBubble`) but should be accessible via `from models import ActivityBubble` per ARCHITECTURE.md Section 2 which says `models/__init__.py` exports are the canonical import path.

### What to Change

Add to `models/__init__.py`:

```python
from .activity import ActivityBubble
from .conversation_snapshot import ConversationSnapshot, SnapshotMessage
from .review_state import ReviewState
from .team import TeamMember, ProjectTeam
```

Update `__all__` to include all new names.

### Verification

```bash
# All exported names are importable
python3 -c "from models import ActivityBubble, ConversationSnapshot, SnapshotMessage, ReviewState, TeamMember, ProjectTeam; print('OK')"

# Existing imports still work
python3 -c "from models import AgentManager, Command, CommandResult, FeedCardData; print('OK')"
```

---

## Phase 3 — agent/__init__.py Exports (Issue C)

**Severity:** Critical
**Estimated scope:** 1 file, ~20 lines changed
**Depends on:** Nothing

### Problem

`agent/__init__.py` only exports `AgentRuntime`. Used-but-not-exported symbols:
- `SpecialAgentDef` from `special_agents.py`
- `get_special_agents()` from `special_agents.py`
- `build_system_prompt()` from `context.py`
- `check()` from `enforcement.py`
- `load_agent_config()` from `config.py`
- `get_api_key()` from `config.py`

### What to Change

Add to `agent/__init__.py`:

```python
from .config import load_agent_config, get_api_key
from .context import build_system_prompt
from .enforcement import check
from .special_agents import SpecialAgentDef, get_special_agents
```

Update `__all__`.

**Important:** `agent/special_agents.py` imports from `agent/context.py` which imports from `agent/config.py`. This is fine — the imports are already resolved at module level. Just ensure the `try/except ImportError` guard wraps the entire block (not each import individually) so the package degrades gracefully if dependencies are missing.

### Verification

```bash
python3 -c "from agent import AgentRuntime, SpecialAgentDef, get_special_agents, build_system_prompt, load_agent_config, get_api_key; print('OK')"
```

---

## Phase 4 — Test Fix: test_does_not_overwrite_existing (Issue D)

**Severity:** Bug
**Estimated scope:** 1 file, ~5 lines changed
**Depends on:** Nothing

### Problem

`tests/test_agent_defs.py::TestLoadAgentDefs::test_does_not_overwrite_existing` fails with:
```
AssertionError: assert 'Coder' not in ['Coder', 'Custom']
```

The test expects that when the agents directory is non-empty, `_seed_defaults()` should NOT seed any defaults. But the actual `_seed_defaults()` only checks if the *specific file* exists — it will still copy `coder.yaml` into a directory that already has `custom.yaml`.

### Analysis

Two possible fixes:

**Option A (fix the test):** The test's expectation is wrong. `_seed_defaults()` is designed to never overwrite existing files — it checks `if not os.path.isfile(dst)`. Seeding `coder.yaml` when only `custom.yaml` exists is correct behavior. The test should instead verify that `custom.yaml` was NOT overwritten, not that no seeding happened at all.

**Option B (fix the code):** Change `_seed_defaults()` to skip seeding entirely if the agents directory is non-empty (i.e., has at least one `.yaml`/`.yml`/`.json` file). This matches the test's intent: "if the user already has custom agents, don't interfere."

**Recommendation:** Option B. The test captures a reasonable design intent — if a user already has custom agents, the app shouldn't silently add built-in ones. The current behavior (add missing built-ins individually) could surprise users who intentionally removed a built-in agent.

### What to Change (Option B)

In `utils/agent_defs.py`, `_seed_defaults()`:

Add a check at the start:
```python
def _seed_defaults() -> None:
    agents_dir = _get_agents_dir()
    src_dir = _get_default_agents_src()

    if not os.path.isdir(src_dir):
        return

    # If user already has agents, don't seed defaults — they may have
    # intentionally removed built-in agents.
    try:
        os.makedirs(agents_dir, exist_ok=True)
    except OSError as e:
        logger.warning("Cannot create agents directory %s: %s", agents_dir, e)
        return

    existing = [f for f in os.listdir(agents_dir)
                if f.endswith((".yaml", ".yml", ".json"))]
    if existing:
        return  # user has agents — don't interfere
    # ... rest of seeding logic
```

### Verification

```bash
python3 -m pytest tests/test_agent_defs.py -v
```

---

## Phase 5 — Test Fix: TestUpdateAgentSession (Issue E)

**Severity:** Infrastructure
**Estimated scope:** 1 file, ~10 lines changed
**Depends on:** Nothing

### Problem

4 tests in `tests/test_project_handler.py::TestUpdateAgentSession` fail with:
```
TypeError: ProjectHandler.__init__() got an unexpected keyword argument 'main_content'
```

The test fixture passes `main_content` to `ProjectHandler.__init__()`, but the constructor signature was changed in an earlier phase — `main_content` is no longer a parameter.

### What to Change

In `tests/test_project_handler.py`, update the `handler` fixture to match the current `ProjectHandler.__init__()` signature:

```python
# Current signature (from ui/handlers/project_handler.py):
def __init__(self, left_panel, projects_module, agent_to_project,
             GLib_module=None, awareness_module=None)
```

The fixture should pass:
- `left_panel` — a mock or fake LeftPanel
- `projects_module` — a mock or the real `utils.projects` module
- `agent_to_project` — a real `AgentRoutingTable()` instance
- `GLib_module` — None (tests don't need GLib dispatch)
- `awareness_module` — None (optional)

Remove `main_content` from the fixture.

### Verification

```bash
python3 -m pytest tests/test_project_handler.py::TestUpdateAgentSession -v
```

---

## Phase 6 — Circular Self-Import Fix (Issue F)

**Severity:** Fragile
**Estimated scope:** 1 file, ~5 lines changed
**Depends on:** Nothing

### Problem

`utils/projects.py` lines 63 and 78 have circular self-imports:
```python
from utils.projects import load_projects as _load_projects
```

This imports the module into itself. It works because Python caches module imports, but it's fragile and confusing. If the import order changes or the module is reloaded, it could break.

### What to Change

Replace the self-imports with direct calls to `load_projects()` (the function is already defined in the same file — just call it directly):

```python
# Before (line 63):
from utils.projects import load_projects as _load_projects
# ... later:
for name, path in _load_projects():

# After:
for name, path in load_projects():
```

Do the same for line 78.

**Note:** `load_projects()` is defined at module level before these functions. The function-level imports were presumably added to avoid circular imports at module load time, but since `load_projects` is defined before `load_members` and `save_members`, it's already available. Verify this doesn't introduce circular imports at load time by testing the import.

### Verification

```bash
python3 -c "from utils.projects import load_projects, load_members, save_members; print('OK')"
python3 -m pytest tests/ -q 2>&1 | tail -5
```

---

## Phase 7 — STT_MODEL_SIZE Env Var (Issue G)

**Severity:** Documentation
**Estimated scope:** 1 file, ~5 lines changed
**Depends on:** Nothing

### Problem

`utils/stt.py` hardcodes `model_size="tiny.en"` in the constructor. The `STT_MODEL_SIZE` environment variable is mentioned in ARCHITECTURE.md Section 10 but never actually read by the code.

### What to Change

In `utils/stt.py`, update the `__init__` method to read the env var:

```python
import os

class STTEngine:
    def __init__(self, model_size=None, ...):
        self._model_size = model_size or os.environ.get("STT_MODEL_SIZE", "tiny.en")
```

Also update the docstring to mention the env var fallback.

Update ARCHITECTURE.md Section 10 (Environment Variables) to confirm `STT_MODEL_SIZE` is now implemented:

```
| `STT_MODEL_SIZE` | `"tiny.en"` | faster-whisper model size — "tiny.en", "base.en", "small.en", etc. | No |
```

### Verification

```bash
# Default works
python3 -c "from utils.stt import STTEngine; e = STTEngine(); print(e._model_size)"
# Expected: tiny.en

# Env var works
STT_MODEL_SIZE=base.en python3 -c "from utils.stt import STTEngine; e = STTEngine(); print(e._model_size)"
# Expected: base.en

# Explicit param overrides env var
STT_MODEL_SIZE=base.en python3 -c "from utils.stt import STTEngine; e = STTEngine(model_size='small.en'); print(e._model_size)"
# Expected: small.en
```

---

## Execution Order

| Phase | Issue | Depends on | Estimated lines | Risk |
|-------|-------|-----------|----------------|------|
| 1 | A — ARCHITECTURE.md update | All other phases | ~200 | Low (docs only) |
| 2 | B — models/__init__.py exports | Nothing | ~15 | Low |
| 3 | C — agent/__init__.py exports | Nothing | ~20 | Low |
| 4 | D — test_does_not_overwrite_existing | Nothing | ~5 | Low |
| 5 | E — TestUpdateAgentSession fixture | Nothing | ~10 | Low |
| 6 | F — Circular self-import | Nothing | ~5 | Low |
| 7 | G — STT_MODEL_SIZE env var | Nothing | ~5 | Low |

**Phases 2–7 are independent and can be done in any order.** Phase 1 must be done last because it documents the final state of all other changes.

**Recommended execution:** Phases 2–7 in order (each takes 5–10 minutes), then Phase 1 to update docs.

---

## Acceptance Criteria

- [ ] `models/__init__.py` exports `ActivityBubble`, `ConversationSnapshot`, `SnapshotMessage`, `ReviewState`, `TeamMember`, `ProjectTeam`
- [ ] `agent/__init__.py` exports `SpecialAgentDef`, `get_special_agents`, `build_system_prompt`, `check`, `load_agent_config`, `get_api_key`
- [ ] `test_does_not_overwrite_existing` passes
- [ ] `TestUpdateAgentSession` (4 tests) pass
- [ ] No circular self-imports in `utils/projects.py`
- [ ] `STT_MODEL_SIZE` env var is read by `utils/stt.py`
- [ ] ARCHITECTURE.md Section 2, 3, and 12 reflect all changes
- [ ] Full test suite: no new failures beyond the 27 pre-existing ones
- [ ] `python3 -c "from ui.window import MainWindow; print('Import OK')"` passes
