# BUGFIX 4 — Add `stream == "lifecycle"` guard to second `if event == "agent"` block

## Problem

`ui/handlers/activity_handler.py` has TWO `if event == "agent":` blocks in `on_gateway_event()`:

1. **First block** (line ~280): handles `stream == "assistant"`, `stream == "lifecycle"`, `stream == "item"`, `stream == "plan"`, `stream == "approval"`, `stream == "patch"`, and now `stream == "command_output"`. This block fires ActivityBubbles and lifecycle callbacks.

2. **Second block** (line ~449): handles state machine transitions (`on_agent_start`, `on_agent_end`, `on_agent_error`). This block reads `phase` from the payload and calls the corresponding state transition.

The bug: the second block reads `phase` for ALL `event == "agent"` events, not just lifecycle ones. For a `stream == "lifecycle"` event with `data.phase == "end"`, the second block correctly reads phase from `data.phase` (via the `if stream == "lifecycle":` branch). But for any OTHER stream type, it falls to the `else` branch and reads `payload.get("phase", "")` — a top-level field that most gateway events don't have.

If the gateway ever sends a `stream == "item"` event with `payload.phase == "end"` at the top level, the second block would call `self.on_agent_end()`, transitioning the state machine to "done" prematurely. This is currently not triggered by the running gateway, but it's a latent trap.

## What to implement

### File 1: `ui/handlers/activity_handler.py` — second `if event == "agent":` block

The second block currently reads phase for ALL stream types. Add a guard so it ONLY processes lifecycle events. The simplest fix: wrap the entire phase-reading and state-transition logic inside `if stream == "lifecycle":`.

Current code (line ~449):
```python
if event == "agent":
    stream = payload.get("stream", "")
    if stream == "lifecycle":
        phase = self._safe_data(payload).get("phase", "")
    else:
        phase = payload.get("phase", "")
    if phase == "start":
        self.on_agent_start(session_key, payload)
    elif phase == "end":
        self.on_agent_end(session_key, payload)
    elif phase == "error":
        self.on_agent_error(session_key)
```

New code:
```python
if event == "agent":
    # State machine transitions only apply to lifecycle events.
    # Other stream types (item, plan, approval, patch, command_output)
    # should NOT trigger on_agent_start/end/error.
    stream = payload.get("stream", "")
    if stream == "lifecycle":
        phase = self._safe_data(payload).get("phase", "")
        if phase == "start":
            self.on_agent_start(session_key, payload)
        elif phase == "end":
            self.on_agent_end(session_key, payload)
        elif phase == "error":
            self.on_agent_error(session_key)
```

This removes the `else: phase = payload.get("phase", "")` branch entirely. Non-lifecycle events no longer trigger state machine transitions.

### File 2: `tests/test_activity_bubbles.py`

Add a test that verifies a `stream == "item"` event with `phase == "end"` does NOT trigger `on_agent_end`:

```python
def test_item_end_does_not_trigger_state_machine(self, fake_glib):
    """stream=item phase=end must NOT trigger on_agent_end state transition."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    # Start a session first
    handler.on_gateway_event("agent", {
        "stream": "lifecycle",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {"phase": "start"}
    })
    assert handler._state == "reasoning"

    # Send a stream=item event with phase=end
    handler.on_gateway_event("agent", {
        "stream": "item",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {"phase": "end", "kind": "tool", "name": "exec", "status": "completed"}
    })

    # State should still be "reasoning" — on_agent_end must NOT have fired
    assert handler._state == "reasoning", (
        "stream=item phase=end must not trigger on_agent_end state transition"
    )
```

Also add a test that `stream == "lifecycle"` events STILL trigger state transitions (regression guard):

```python
def test_lifecycle_end_triggers_state_machine(self, fake_glib):
    """stream=lifecycle phase=end MUST trigger on_agent_end state transition."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    handler.on_gateway_event("agent", {
        "stream": "lifecycle",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {"phase": "start"}
    })
    assert handler._state == "reasoning"

    handler.on_gateway_event("agent", {
        "stream": "lifecycle",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {"phase": "end"}
    })
    assert handler._state == "done"
```

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "if event == \"agent\":" ui/handlers/activity_handler.py
python3 -m pytest tests/test_activity_bubbles.py -q --tb=short
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Wrapped state transitions in `if stream == "lifecycle":` guard — evidence: grep line numbers
- [ ] Edit 2: Added test_item_end_does_not_trigger_state_machine — evidence: test pass
- [ ] Edit 3: Added test_lifecycle_end_triggers_state_machine (regression guard) — evidence: test pass
- [ ] Edit 4: Full test suite passes — evidence: pytest output
```
