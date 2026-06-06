# PHASE 1 — Remove gateway `command_output` branch from ActivityHandler

**Date:** 2026-06-05
**Supervisor:** Qaster
**Builder:** QTR
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.4
**Audit context:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` P0 #1
   (Full path: `/home/q/projects/crabcakes/docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md`)

## Goal

Per SPEC-activity-drawer §2.4, the `stream == "command_output"` branch in
`ActivityHandler.on_gateway_event()` must be REMOVED. Going forward,
`AgentRuntimeHandler` is the sole source of `command_output` activity bubbles
(because only it has the `command` text and the captured `output`).

## Files to change (1 file, 1 sub-phase)

### 1. `ui/handlers/activity_handler.py` — delete the gateway command_output branch

Delete the entire `elif stream == "command_output":` block, which currently
sits around lines 332-343.

The block looks like this (find it with `grep -n 'elif stream == "command_output"'`):

```python
elif stream == "command_output":
    # ── Activity bubble: shell command output ──────────────────
    data = payload.get("data", {})
    if data.get("phase") == "end":
        name = data.get("name", "") or ""
        exit_code = data.get("exitCode", 0)
        duration_ms = data.get("durationMs", 0)
        sk = payload.get("sessionKey", "") or session_key
        if name and self._activity_bubble_callback:
            from models.activity import ActivityBubble, ToolStatus
            bubble = ActivityBubble(type="command_output", session_key=sk, tool_name=name, exit_code=exit_code, duration_ms=duration_ms, icon="💻")
            self._activity_bubble_callback(bubble)
```

Replace it with nothing — the branch is gone, the gateway-driven `command_output`
event is no longer handled here.

### 2. `tests/test_activity_bubbles.py` — remove the test that exercises the deleted branch

Delete the test `test_command_output_end_fires_callback` (around line 203).
This test is in `TestActivityHandlerActivityBubbles` and was kept only because
the branch existed. Per the audit, spec §2.10's list of "tests to keep" was
incomplete — the test must go alongside the branch it tests.

## Rules for the builder

- **Use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`** — word for word, no deviation. Start with: "Starting Discovery Phase — reading all relevant files before writing any code."
  (That is the project's own prompts directory. Do not search `/home/q/prompts/` — that path does not exist.)
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT touch any other lines, comments, or formatting in either file.
- Do NOT add new functionality — this is a strict removal.

## Verification (run yourself, paste output in your report)

```bash
# 1. Branch is gone
grep -n 'elif stream == "command_output"' ui/handlers/activity_handler.py
# Expected: 0 matches (or no output)

# 2. Verification cheat sheet grep from the spec
grep -n "command_output" ui/handlers/activity_handler.py | grep "data.get"
# Expected: 0 matches (or no output)

# 3. Test is gone
grep -n "def test_command_output_end_fires_callback" tests/test_activity_bubbles.py
# Expected: 0 matches

# 4. Full test suite passes
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py -v
# Expected: 24 passed (down from 25, since we removed 1 test)
```

## Report format

At the end, include the COMPLETENESS checklist:

```
COMPLETENESS:
- [x/not done] Edit 1: removed command_output branch in activity_handler.py — evidence (grep -c output)
- [x/not done] Edit 2: removed test_command_output_end_fires_callback — evidence (grep -c output)
- [x/not done] Test result: pytest tests/test_activity_bubbles.py — paste full output
```

If you cannot include this checklist, your response is INCOMPLETE. Do not expect acceptance.
