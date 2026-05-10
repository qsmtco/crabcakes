# BUG INVESTIGATION: Project Members Not Persisting on Reopen

> **Status: PARTIALLY FIXED** — Verified in code as of 2026-05-09
> - ✅ Fix 1 (session key matching via `get_all_sessions_for_agent`) — implemented
> - ✅ Fix 2 (refresh on gateway connect) — implemented
> - ❌ Bug #1 (MEDIUM): Still saves ephemeral session keys in team.json, not agent names — can re-break on reconnect cycles
> - ✅ Bug #2 (LOW): FIXED — now uses public `self._agent_mgr.get_sessions(name)` instead of accessing private `_agent_names`
> - ❌ Bug #3 (LOW): Refresh may fire before async agent discovery completes
> - ❌ Bug #4 (LOW): Stale key on orphaned widget after list rebuild

**Date:** 2026-04-27
**Investigator:** Qaster
**Status:** Root cause identified, initial fix applied, adversarial review complete

---

## Symptom

When a project is closed and reopened, agents that were previously added to the project do not appear in the agents list. They seem to have been removed, even though they were added in a prior session.

## Investigation

### Data Layer — ✅ Working Correctly

- `team.json` saves correctly when agents are added/removed
- `load_members('crabwatch')` correctly returns saved session keys
- `init_project_config()` does NOT overwrite existing `team.json` (has early return guard)
- `save_members()` → `save_team()` writes to `.crabcakes/team.json` properly

Verified:
```
load_members('crabwatch') → ['agent:qtr:telegram:direct:7478874934']
```

### UI Rendering Layer — ❌ Bug Located (Original)

**File:** `ui/views/left_panel.py`
**Method:** `_refresh_agents_list()` (line 160)

```python
# Line 182
if self._agent_list_handler and self._agent_list_handler.has_agent_mgr():
    sorted_agents = self._agent_list_handler.get_sorted_agents(project_members)
else:
    # Fallback: only shows agents in _agent_names dict
```

**Problem 1: Gateway timing**
If the project opens before the gateway connects and discovers agents, `has_agent_mgr()` returns False. The fallback path only shows agents from `_agent_names` (populated by gateway events). No gateway = no agents shown = members appear missing.

**Problem 2: Session key mismatch**
In `agent_list_handler.py` line 96:
```python
in_project = bool(project_members) and sk in project_members
```
`sk` comes from AgentManager's current live sessions. `project_members` comes from `team.json`. If an agent reconnects with a different session key, the saved key won't match the new one, so `in_project` is False.

**Problem 3: No refresh on gateway connect**
When the gateway connects and agents are discovered, there's no callback to refresh the agents list for the currently open project. The members are on disk but the UI never re-reads them after agents appear.

### Root Causes (Original)

| # | Cause | Impact |
|---|-------|--------|
| 1 | Gateway not connected when project opens | Agent list empty, members can't be matched |
| 2 | Session keys can change on reconnect | Saved keys don't match live keys |
| 3 | No refresh callback when agents are discovered | UI never updates after gateway connects |

---

## Qrusher's Fix

### Fix 1 — Session key matching (`agent_list_handler.py`)

```python
# Before:
in_project = bool(project_members) and sk in project_members

# After:
in_project = bool(project_members) and (
    sk in project_members or
    any(s in project_members for s in self.get_all_sessions_for_agent(name))
)
```

New method added:
```python
def get_all_sessions_for_agent(self, name: str) -> list[str]:
    """Return all session_keys for a given agent name."""
    if self._agent_mgr is None:
        return []
    return [
        sk for sk, n in self._agent_mgr._agent_names.items()
        if n == name
    ]
```

### Fix 2 — Refresh on gateway connect (`window.py`)

```python
# Added in _sync_gateway_to_chat_handler:
if self._project_handler.get_active_project_name():
    self._left_panel.refresh_agents_with_project(
        self._project_handler.get_active_project_name()
    )
```

---

## Adversarial Review Results (2026-04-27)

### BUG #1 — MEDIUM (Remaining issue)
**Assumption violated:** The fix matches by name across sessions but still **saves the primary session key**, which is ephemeral.

**Attack vector:**
1. Agent QTR connects with `agent:qtr:telegram:direct:7478874934`
2. User clicks + → saves `agent:qtr:telegram:direct:7478874934` ✅
3. Gateway reconnects. QTR gets two sessions: `agent:qtr:telegram:direct:7478874934` and `agent:qtr:project:main`
4. `get_sorted_agents` picks `agent:qtr:project:main` as primary (`:main` wins)
5. User clicks − → saves `agent:qtr:project:main` to team.json
6. Gateway reconnects AGAIN. QTR only gets `agent:qtr:telegram:direct:7478874934` (no `:main`)
7. Saved key `agent:qtr:project:main` doesn't match any live session
8. `get_all_sessions_for_agent("qtr")` returns only the direct key → no match
9. **QTR appears as not added** — bug recurs

**Root cause:** The fix improves matching but doesn't solve the fundamental problem: session keys are ephemeral identifiers, not stable agent identities.

**Fix:** Persist agent **name** (not session key) in team.json, or normalize session keys to a canonical form on save.

### BUG #2 — LOW
**Assumption violated:** `get_all_sessions_for_agent` accesses `_agent_mgr._agent_names` (private attribute).
**Root cause:** Cross-boundary private state access.
**Fix:** Add public `get_sessions_for_name(name)` to AgentManager.

### BUG #3 — LOW
**Assumption violated:** Refresh in `_sync_gateway_to_chat_handler` fires immediately after `set_agent_mgr()`, but agent discovery is async (WebSocket events arrive later).
**Attack vector:** Gateway connects → sync runs → agent_mgr is empty → refresh shows nothing. Agents arrive moments later but no second refresh fires.
**Fix:** Hook into agent discovery events to trigger a second refresh.

### BUG #4 — LOW
**Assumption violated:** `_on_agent_toggle_clicked` uses `button._agent_session_key` stored at row-build time. If a list rebuild happens between build and click, the key may be stale.
**Attack vector:** Unlikely GTK4 race — orphaned widget fires handler with outdated key.
**Fix:** Look up agent's current sessions at toggle time.

---

## Summary

| # | Severity | Status | Issue |
|---|----------|--------|-------|
| 1 | **MEDIUM** | Open | Primary key saved is ephemeral — can re-break on reconnect |
| 2 | LOW | Open | Private attribute access across handler boundary |
| 3 | LOW | Open | Refresh may fire before async agent discovery completes |
| 4 | LOW | Open | Stale key on orphaned widget after list rebuild |

**Recommendation:** Fix Bug #1 by normalizing to agent name on save. Bugs 2-4 are low priority.

---

## Files Involved

| File | Role |
|------|------|
| `ui/views/left_panel.py` | Agent list rendering, `load_members()` call |
| `ui/handlers/agent_list_handler.py` | `get_sorted_agents()`, `in_project` matching |
| `ui/handlers/project_handler.py` | `_load_members()`, `_save_members()`, `open_project()` |
| `ui/window.py` | `_sync_gateway_to_chat_handler()` — gateway connect wiring |
| `utils/projects.py` | `load_members()` — deprecated wrapper |
| `utils/project_awareness.py` | `load_team()` / `save_team()` — actual team.json I/O |
| `models/team.py` | `ProjectTeam`, `get_session_keys()` |
