# PHASE 4 — Add `agent_name=_agent_name` to tool bubbles

**Date:** 2026-06-05
**Supervisor:** Qaster (using `implementationSupervisor` prompt exactly)
**Builder:** QTR (using `steelFramedCodeWriter` prompt exactly)
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.4
**Audit context:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` P1 #4
**Predecessor:** PHASE 1+2+3+FIXES complete (4 commits, 49/49 tests pass, pushed to origin/main)

## Goal

The `_agent_name` variable is captured at the top of the `stream == "lifecycle"` branch in `ActivityHandler.on_gateway_event()` (around line 271), but it's NOT passed to the `ActivityBubble` constructor for `tool_start`/`tool_end`/`tool_error` events (lines 314-337). Spec §2.4 lists all 6 bubble construction sites as needing `agent_name`. 3 of 6 (lifecycle_start) already do; 3 (tool_start/tool_end/tool_error) don't.

## Files to change (1 file, 1 sub-phase)

### `ui/handlers/activity_handler.py` — add `agent_name=_agent_name` to 3 tool bubble constructors

Specifically the `ActivityBubble(...)` calls inside the `stream == "item"` branch, in the `kind == "tool"` sub-branch. There are 3 ActivityBubble constructions:
- `tool_start` (line ~314): currently no `agent_name`. Add `agent_name=_agent_name`.
- `tool_end` (line ~325): currently no `agent_name`. Add `agent_name=_agent_name`.
- `tool_error` (line ~336): currently no `agent_name`. Add `agent_name=_agent_name`.

After the change, the 3 tool bubble constructions should look like:
```python
bubble = ActivityBubble(
    type="tool_start",
    session_key=sk,
    tool_name=name,
    icon=icon,
    status=ToolStatus.RUNNING,
    agent_name=_agent_name,  # NEW
)
```

`_agent_name` is in scope at this point (set in the lifecycle branch above). The exact name of the local var in the tool branch may be different (e.g., `agent_name`) — QTR should use the steelFramedCodeWriter discovery phase to confirm the exact variable name in scope.

## Rules for the builder

- **You MUST use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md` exactly as written — no deviation.** Begin with: "Starting Discovery Phase — reading all relevant files before writing any code."
- Discovery is mandatory: re-read `ui/handlers/activity_handler.py` lines 207-340 to confirm the exact variable name in scope and the 3 constructor call sites.
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT modify any other file. This phase is `ui/handlers/activity_handler.py` ONLY.
- Do NOT change the `lifecycle_start` bubble — that already has `agent_name=_agent_name`. Don't break it.
- Do NOT change the `plan`, `approval_request`, or `patch` bubbles — they're not in scope (spec §2.4 lists "all 6 construction sites" but only 4 are in `lifecycle_start` + 3 tool sites; the other 3 bubble types are gateway-specific and not in this phase).

## Verification (run yourself, paste output in your report)

```bash
# 1. agent_name= is now passed in all 3 tool bubble sites
grep -nE 'bubble = ActivityBubble\(' ui/handlers/activity_handler.py
# Expected: 4 matches (lifecycle_start, tool_start, tool_end, tool_error)
# Each match should have `agent_name=_agent_name` (or whatever the local var is named)

# 2. Confirm no regression: existing 49 tests still pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -q
# Expected: 49 passed

# 3. AST parse
python3 -c "import ast; ast.parse(open('ui/handlers/activity_handler.py').read()); print('PARSE OK')"

# 4. App still starts
cd /home/q/projects/crabcakes && timeout 3 python3 main.py 2>&1 | head -5
# Expected: no crash, clean exit
```

## Optional bonus: add a test

The audit's P1 #4 fix is a 3-line code change. There's no test that asserts `agent_name` is set on tool bubbles. Spec §2.10 doesn't mandate a test for this, but adding one would catch a regression. If QTR wants to be thorough, add 1 test to `tests/test_activity_bubbles.py` in the `TestActivityHandlerActivityBubbles` class:

```python
def test_tool_start_bubble_has_agent_name(self, fake_glib):
    """Tool bubbles carry agent_name from the gateway payload (spec §2.4)."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)
    handler.on_gateway_event("agent", {
        "stream": "item",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running", "agentName": "Coder"},
    })
    bubble = cb.call_args[0][0]
    assert bubble.agent_name == "Coder"
```

This is OPTIONAL for PHASE 4 — QTR's call. If skipped, document why in the COMPLETENESS checklist.

## Report format

At the end, include the COMPLETENESS checklist:

```
COMPLETENESS:
- [x/not done] Edit 1: added agent_name=_agent_name to tool_start bubble — evidence (grep, line number)
- [x/not done] Edit 2: added agent_name=_agent_name to tool_end bubble — evidence (grep, line number)
- [x/not done] Edit 3: added agent_name=_agent_name to tool_error bubble — evidence (grep, line number)
- [x/not done] (Optional) Edit 4: added test_tool_start_bubble_has_agent_name — evidence OR "skipped"
- [x/not done] Test result: pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py — paste full output
- [x/not done] App still starts — paste output
```

## After QTR reports done

Qaster will:
1. Re-verify with the same commands above
2. Run adversarialDebugger audit (mutation test: remove the `agent_name=...` arg, confirm a test catches it — if QTR added the optional test, otherwise run a manual sanity check)
3. Commit if clean (Qaster author)
4. Push to origin/main
5. Write post-mortem and report
