# PHASE 6 — Fall back to AgentManager for agent name resolution

**Date:** 2026-06-05
**Supervisor:** Qaster (using `implementationSupervisor` prompt exactly)
**Builder:** QTR (using `steelFramedCodeWriter` prompt exactly)
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.4 (the "TODO before implementation" note) + §5
**Bug report:** Captain observed `[Agent]` instead of real agent name in the drawer
**Root cause:** The gateway's `stream=item kind=tool` events do NOT carry `data.agentName`. The current code in `ActivityHandler.on_gateway_event` only reads from `data.agentName`, so all tool bubbles end up with `agent_name=""`, and the drawer's "agent" key defaults to `"Agent"`. This is the exact fallback case the spec warned about.

## Goal

When the gateway payload's `data.agentName` is empty/missing, fall back to `AgentManager.get_name(session_key)` to resolve the agent's display name. This is the spec's documented fallback path.

## Files to change (2 files, 1 sub-phase)

### 1. `ui/handlers/activity_handler.py` — extract agent name with fallback

#### Change 1a: Add `set_agent_manager` setter

Add a setter method on `ActivityHandler` (alongside `set_agent_routing`):

```python
def set_agent_manager(self, agent_mgr) -> None:
    """Inject AgentManager for session_key → agent_name fallback (SPEC-activity-drawer §2.4).
    
    Called by ConnectionSyncHandler.sync() after the gateway connects.
    Used to resolve agent_name when the gateway payload's data.agentName is empty.
    """
    self._agent_mgr = agent_mgr
```

Also initialize `self._agent_mgr = None` in `__init__`.

#### Change 1b: Extract a helper method

Currently there are TWO places that extract `_agent_name` from the payload:
- Line ~243: `if stream == "lifecycle": _agent_name = payload.get("data", {}).get("agentName", "") or ""`
- Line ~292: `_agent_name = data.get("agentName", "") or ""` (in the item branch)

Both should use a single helper that adds the AgentManager fallback. Replace both extraction sites with:

```python
_agent_name = self._resolve_agent_name(payload)
```

And add the helper method:

```python
def _resolve_agent_name(self, payload: dict) -> str:
    """Resolve the agent display name from a gateway payload.
    
    Resolution order (SPEC-activity-drawer §2.4 fallback chain):
    1. payload.data.agentName — gateway-supplied agent name (may be empty)
    2. AgentManager.get_name(payload.sessionKey) — local session_key → name lookup
    3. "" — drawer will display "[Agent]" as last-resort fallback
    
    Args:
        payload: The gateway event payload dict.
    
    Returns:
        The agent display name, or "" if unknown.
    """
    direct = payload.get("data", {}).get("agentName", "") or ""
    if direct:
        return direct
    session_key = payload.get("sessionKey", "") or ""
    if session_key and self._agent_mgr is not None:
        try:
            name = self._agent_mgr.get_name(session_key)
            if name:
                return name
        except Exception:
            pass  # AgentManager may not be ready; fall through
    return ""
```

QTR's discovery should confirm the exact line numbers and that both call sites can be replaced.

### 2. `ui/handlers/connection_sync_handler.py` — wire the AgentManager

In `sync()`, after the existing `self._main_content.set_agent_manager(...)` line (around line 114), add:

```python
# Inject AgentManager into ActivityHandler for agent_name fallback (SPEC-activity-drawer §2.4)
self._activity_handler.set_agent_manager(self._gateway_handler.agent_mgr)
```

This goes BEFORE the existing `set_on_activity_bubble` / `set_on_agent_lifecycle` wiring block so the AgentManager is available by the time activity events arrive.

## Rules for the builder

- **You MUST use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md` exactly as written — no deviation.** Begin your response with: "Starting Discovery Phase — reading all relevant files before writing any code."
- Discovery is mandatory: re-read `ui/handlers/activity_handler.py` (full file) and `ui/handlers/connection_sync_handler.py` (full file) before writing.
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT modify any other file. This phase is the 2 listed files ONLY.
- Do NOT change the `format_text` method or any other code path.
- Do NOT remove the existing `_agent_name` variable in the lifecycle branch — replace its initialization with the helper call.

## Verification (run yourself, paste output in your report)

```bash
# 1. set_agent_manager is defined and called
grep -n "set_agent_manager" ui/handlers/activity_handler.py ui/handlers/connection_sync_handler.py
# Expected: 2 matches (1 definition + 1 call site)

# 2. _resolve_agent_name helper exists
grep -n "_resolve_agent_name" ui/handlers/activity_handler.py
# Expected: 1+ matches (definition + 2 call sites replacing the old extraction)

# 3. Existing 52 tests still pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -q
# Expected: 52 passed

# 4. AST parse
python3 -c "import ast; ast.parse(open('ui/handlers/activity_handler.py').read()); print('activity_handler.py: PARSE OK')"
python3 -c "import ast; ast.parse(open('ui/handlers/connection_sync_handler.py').read()); print('connection_sync_handler.py: PARSE OK')"

# 5. App still starts
cd /home/q/projects/crabcakes && timeout 3 python3 main.py 2>&1 | head -5
# Expected: clean exit, no crash
```

## Optional bonus: add a test for the fallback

This is a real behavior change and is worth a regression test. Add to `tests/test_activity_bubbles.py` in `TestActivityHandlerActivityBubbles`:

```python
def test_tool_bubble_falls_back_to_agent_manager(self, fake_glib):
    """When data.agentName is empty, fall back to AgentManager.get_name(session_key)."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)
    
    # Mock AgentManager
    agent_mgr = MagicMock()
    agent_mgr.get_name = MagicMock(return_value="Coder")
    handler.set_agent_manager(agent_mgr)
    
    # Payload WITHOUT agentName
    handler.on_gateway_event("agent", {
        "stream": "item",
        "sessionKey": "agent:coder",
        "runId": "run-1",
        "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"},
        # NO "agentName" key
    })
    
    bubble = cb.call_args[0][0]
    assert bubble.agent_name == "Coder", f"expected AgentManager fallback, got {bubble.agent_name!r}"
    agent_mgr.get_name.assert_called_once_with("agent:coder")
```

OPTIONAL — QTR's call. If skipped, document why in the COMPLETENESS checklist.

## Report format

```
COMPLETENESS:
- [x/not done] Edit 1: added set_agent_manager setter on ActivityHandler — evidence (line number, grep)
- [x/not done] Edit 2: added _resolve_agent_name helper with AgentManager fallback — evidence (line number, grep)
- [x/not done] Edit 3: replaced 2 _agent_name extraction sites with helper call — evidence (grep, line numbers)
- [x/not done] Edit 4: wired set_agent_manager in connection_sync_handler.sync() — evidence (line number, grep)
- [x/not done] (Optional) Edit 5: added regression test — evidence OR "skipped"
- [x/not done] Test result: pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py — paste full output
- [x/not done] App still starts — paste output
- [x/not done] Manual test: simulated gateway event with missing agentName — agent_name now resolves to "Coder" via AgentManager — paste output
```

## After QTR reports done

Qaster will:
1. Re-verify with the same commands above
2. Run adversarialDebugger audit with mutation tests (e.g., set AgentManager to return wrong name, confirm test catches it)
3. Commit if clean (Qaster author per Captain's authorization)
4. Push to origin/main
5. Write post-mortem
