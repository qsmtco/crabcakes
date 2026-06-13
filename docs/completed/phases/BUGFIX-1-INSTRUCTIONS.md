# BUGFIX 1 — Add missing `stream: "command_output"` handler branch

## Problem

`ui/handlers/activity_handler.py` has no `elif stream == "command_output":` branch in the first `if event == "agent":` block (around line 408). Every `stream: "command_output"` event from the gateway is silently dropped. This means gateway agents (like Qaster) never see `command_output` rows in the activity drawer.

## Context

- The existing `elif` chain inside the first `if event == "agent":` block handles: `lifecycle`, `item`, `plan`, `approval`, `patch`.
- `command_output` is the only gateway event type with NO handler.
- The `command_output` ActivityType already exists in `models/activity.py` and has `format_text()` and `to_drawer_row()` support.
- The only code path that currently produces `command_output` bubbles is the local exec adapter in `ui/handlers/connection_sync_handler.py:225` — which only fires for local special agents, NOT gateway agents.

## Gateway Payload (verified from running gateway `openclaw 2026.5.18`)

For `stream: "command_output" phase: "end"` (the only phase we handle — same design as the `patch` branch):

```js
{
    itemId: "...",
    phase: "end",
    title: "exec <command>",      // human-readable title built by buildCommandItemTitle()
    toolCallId: "...",
    name: "exec" | "bash",        // tool name
    output: "last N lines...",    // may be absent if no output
    status: "completed" | "failed",
    exitCode: 0,                  // only present if execDetails has exitCode
    durationMs: 1234,             // only present if execDetails has durationMs
    cwd: "/some/path"             // only present if execDetails has cwd
}
```

For `stream: "command_output" phase: "delta"` (streaming output chunks):
```js
{
    itemId: "...",
    phase: "delta",
    title: "exec <command>",
    toolCallId: "...",
    name: "exec" | "bash",
    output: "chunk...",
    status: "running"
}
```

## What to implement

### File 1: `ui/handlers/activity_handler.py`

Add a new `elif stream == "command_output":` branch inside the first `if event == "agent":` block. Place it AFTER the `elif stream == "patch":` block (which ends around line 408) and BEFORE the closing of the `if event == "agent":` block.

The new branch must:

1. Read `data = self._safe_data(payload)`
2. Only handle `phase == "end"` — ignore `"delta"` (same design as the `patch` branch)
3. Extract fields:
   - `name = data.get("name", "") or ""` — tool name (e.g. "exec")
   - `output = data.get("output", "") or ""` — stdout/stderr tail
   - `exit_code = data.get("exitCode", 0)` — default 0 if absent
   - `duration_ms = data.get("durationMs", 0)` — default 0 if absent
   - `command = data.get("title", "") or ""` — the human-readable command string (title field contains the command text)
   - `sk = payload.get("sessionKey", "") or session_key`
4. Resolve agent name: `_agent_name = self._resolve_agent_name(payload)` (same as all other branches)
5. Create the bubble:
   ```python
   bubble = ActivityBubble(
       type="command_output",
       session_key=sk,
       tool_name=name,
       icon="💻",
       command=command,
       output=output,
       exit_code=exit_code,
       duration_ms=duration_ms,
       status=ToolStatus.ERROR if exit_code != 0 else ToolStatus.SUCCESS,
       agent_name=_agent_name,
   )
   ```
6. Fire `self._activity_bubble_callback(bubble)` if both `name` and callback are present.

Follow the EXACT pattern of the `elif stream == "patch":` branch above it. Mirror the structure, the defensive `or ""` patterns, and the `_agent_name` resolution.

### File 2: `tests/test_activity_bubbles.py`

Add a test method to the `TestActivityHandlerActivityBubbles` class:

```python
def test_command_output_end_fires_callback(self, fake_glib):
    """stream=command_output phase=end fires a command_output ActivityBubble."""
    from ui.handlers.activity_handler import ActivityHandler
    from models.activity import ActivityBubble
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)

    handler.on_gateway_event("agent", {
        "stream": "command_output",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {
            "phase": "end",
            "name": "exec",
            "title": "exec ls -la",
            "output": "total 42\ndrwxr-xr-x",
            "exitCode": 0,
            "durationMs": 2345,
            "status": "completed",
        }
    })

    cb.assert_called_once()
    bubble = cb.call_args[0][0]
    assert isinstance(bubble, ActivityBubble)
    assert bubble.type == "command_output"
    assert bubble.tool_name == "exec"
    assert bubble.command == "exec ls -la"
    assert bubble.output == "total 42\ndrwxr-xr-x"
    assert bubble.exit_code == 0
    assert bubble.duration_ms == 2345
    assert bubble.icon == "💻"
    assert bubble.agent_name == ""  # no agentName in payload, no AgentManager resolution
```

Also add a test for the `exit_code != 0` path (error case):

```python
def test_command_output_end_error_fires_callback(self, fake_glib):
    """stream=command_output phase=end with non-zero exit_code fires error bubble."""
    from ui.handlers.activity_handler import ActivityHandler
    from models.activity import ActivityBubble, ToolStatus
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)

    handler.on_gateway_event("agent", {
        "stream": "command_output",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {
            "phase": "end",
            "name": "exec",
            "title": "exec rm -rf /",
            "exitCode": 1,
            "durationMs": 100,
            "status": "failed",
        }
    })

    cb.assert_called_once()
    bubble = cb.call_args[0][0]
    assert isinstance(bubble, ActivityBubble)
    assert bubble.type == "command_output"
    assert bubble.exit_code == 1
    assert bubble.status == ToolStatus.ERROR
```

Also add a test that `phase: "delta"` does NOT fire a bubble:

```python
def test_command_output_delta_does_not_fire(self, fake_glib):
    """stream=command_output phase=delta should NOT fire a bubble (ignored, same as spec)."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)

    handler.on_gateway_event("agent", {
        "stream": "command_output",
        "sessionKey": "sk-1",
        "runId": "run-1",
        "data": {
            "phase": "delta",
            "name": "exec",
            "output": "streaming...",
            "status": "running",
        }
    })

    cb.assert_not_called()
```

## Verification Commands

After implementation, run and paste the FULL output of:

```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_activity_bubbles.py -q --tb=short
```

Also run and paste:

```bash
cd /home/q/projects/crabcakes
grep -n "command_output" ui/handlers/activity_handler.py
```

Also run and paste:

```bash
cd /home/q/projects/crabcakes
grep -n "command_output" tests/test_activity_bubbles.py
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Added `elif stream == "command_output":` branch in activity_handler.py after the `patch` branch — evidence: grep line numbers
- [ ] Edit 2: Added test_command_output_end_fires_callback test — evidence: grep line numbers + test pass
- [ ] Edit 3: Added test_command_output_end_error_fires_callback test — evidence: grep line numbers + test pass
- [ ] Edit 4: Added test_command_output_delta_does_not_fire test — evidence: grep line numbers + test pass
- [ ] Edit 5: Full test suite passes — evidence: pytest output
```
