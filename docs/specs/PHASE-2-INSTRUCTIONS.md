# PHASE 2 — Wire `set_on_command_output` in `ConnectionSyncHandler`

**Date:** 2026-06-05
**Supervisor:** Qaster
**Builder:** QTR
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.5, §2.4
**Audit context:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` P0 #2
**Predecessor:** PHASE 1 complete (command_output branch removed, 24/24 tests pass, ARCHITECTURE.md §3.21 cleaned up)

## Goal

`AgentRuntimeHandler.set_on_command_output(cb)` is defined and fires the callback when a local `exec_command` tool completes — but `cb` is `None` because nothing in the system has called `set_on_command_output` yet. PHASE 2 closes the loop: when a local exec finishes, the drawer receives a `command_output` row with the actual `command` text and last-10-lines of `output`.

## Files to change (2 files, 1 sub-phase)

### 1. `ui/handlers/connection_sync_handler.py` — wire the callback in `sync()`

Add the wiring after the existing `set_on_activity_bubble` and `set_on_agent_lifecycle` block at the end of `sync()` (around line 198). Pseudocode of what to add:

```python
# Wire command_output from AgentRuntimeHandler → ActivityDrawer (SPEC-activity-drawer Phase 2)
# AgentRuntimeHandler fires (session_key, command, output) when a local exec_command completes.
# We construct an ActivityBubble (command_output type) and feed it to the drawer's append_event()
# via the same to_drawer_row() path as the gateway-driven bubbles. The drawer treats them identically.
if self._activity_drawer is not None:
    drawer = self._activity_drawer
    agent_runtime = self._chat_handler.get_agent_runtime_handler()  # or wherever it's reachable
    def _on_command_output(sk, command, output):
        from models.activity import ActivityBubble
        bubble = ActivityBubble(
            type="command_output",
            session_key=sk,
            tool_name=command,         # drawer reads this as the command text
            command=command,           # explicit field
            output=output,             # last 10 lines for click-to-expand
            icon="💻",
        )
        drawer.append_event(bubble.to_drawer_row())
    agent_runtime.set_on_command_output(_on_command_output)
```

**IMPORTANT — discovery step first.** Read `connection_sync_handler.py` to find:
- How to obtain a reference to the `AgentRuntimeHandler` instance (the constructor takes `chat_handler, main_content, agent_list_handler, ...` but not `agent_runtime_handler` directly — QTR must find the right path, e.g. via `self._chat_handler._agent_runtime_handler` or a new constructor parameter).
- The exact location of the existing `set_on_activity_bubble` / `set_on_agent_lifecycle` block at the end of `sync()` so the new wiring is consistent.
- The thread-safety expectations: `sync()` is called on the GTK main thread via `GLib.idle_add()` in `GatewayHandler.on_connected()`.

**Architectural rule (per ARCHITECTURE.md §3.6 — `connection_sync_handler` is the composition root for post-connect wiring):** the wiring goes in `sync()`, not in `window.py` or `__init__`. The `if self._activity_drawer is not None` guard mirrors the existing pattern.

**Architectural rule (per ARCHITECTURE.md §2 directory structure + §3.7b — `models/activity.py` is pure data):** the adapter constructs an `ActivityBubble` with the runtime's data and calls `to_drawer_row()`. Do NOT call `drawer.append_event` with a hand-rolled dict — always go through the dataclass so the field set stays consistent.

### 2. `ui/handlers/agent_runtime_handler.py` — make sure the callback is already firing (audit #2)

QTR's discovery step should confirm that the callback IS already firing at the right moment. Per the audit, the firing site is in `_do_tool_call_result` around lines 615-630, after an `exec_command` tool result returns. The signature is `cb(session_key, command, output)`. Do NOT change the signature — PHASE 2 is a pure consumer wiring, not a producer change.

If QTR finds that the callback is NOT firing (e.g. the call site is missing, or the `_pending_exec_commands` dict is empty when `_do_tool_call_result` runs), STOP and report. Do not invent a producer change in PHASE 2 — that's a separate phase.

### 3. (Optional) `tests/test_agent_runtime_handler.py` — add a test for the wiring

If a test file exists and has a `set_on_command_output` test, verify it still passes. If no such test exists, write a small one:

- Construct `AgentRuntimeHandler` with a `MagicMock` main_content + chat_render_handler + GLib
- Call `set_on_command_output(MagicMock())` — should store the callback
- Manually invoke the stored callback with `("sk-1", "ls -la", "file1\nfile2\n")`
- Assert: stored mock was called with the same args

This test is OPTIONAL for PHASE 2 — QTR's call. If the existing test suite covers it, skip. If not, add it.

## Rules for the builder

- **Use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`** — word for word, no deviation. Start with: "Starting Discovery Phase — reading all relevant files before writing any code."
- Maximum 15 lines of code per checkpoint, then verify.
- Discovery is mandatory: read `connection_sync_handler.py` and `agent_runtime_handler.py` COMPLETELY before writing any code.
- Do NOT add a new public setter on `ConnectionSyncHandler` — the wiring goes inside `sync()`.
- Do NOT modify `agent_runtime_handler.py` unless discovery shows the callback is not actually firing.
- Do NOT touch any other file in this phase.

## Verification (run yourself, paste output in your report)

```bash
# 1. Confirm set_on_command_output is called from inside sync()
grep -n "set_on_command_output" ui/handlers/connection_sync_handler.py
# Expected: at least 1 match (the call site)

# 2. Confirm the adapter constructs an ActivityBubble of type command_output
grep -n "ActivityBubble" ui/handlers/connection_sync_handler.py
# Expected: 1+ matches in the new wiring block

# 3. Confirm existing tests still pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py -q
# Expected: 24 passed

# 4. (If you added a new test) Confirm the new test passes
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime_handler.py -v
# Expected: 1+ passed (the new wiring test, plus any pre-existing tests)

# 5. Adversarial: simulate a local exec_command completion and confirm the drawer's append_event is called
python3 -c "
import sys
sys.path.insert(0, '.')
from unittest.mock import MagicMock
# (build a minimal ConnectionSyncHandler with mocks, then trigger sync())
# Assert: agent_runtime.set_on_command_output was called with a non-None callable
"
```

## Report format

At the end, include the COMPLETENESS checklist:

```
COMPLETENESS:
- [x/not done] Edit 1: wired set_on_command_output in connection_sync_handler.sync() — evidence (grep output, line number)
- [x/not done] Edit 2: confirmed AgentRuntimeHandler is firing the callback — evidence (line number of firing site, or note that no producer change was needed)
- [x/not done] (Optional) Edit 3: added wiring test in test_agent_runtime_handler.py — evidence (test output) OR "skipped because existing tests cover it"
- [x/not done] Test result: pytest tests/test_activity_bubbles.py — paste full output
- [x/not done] Adversarial: simulated exec completion → confirm drawer.append_event was invoked — paste output
```

If you cannot include this checklist, your response is INCOMPLETE. Do not expect acceptance.
