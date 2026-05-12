# BUG: `forward_to` commands silently fail for special agents

**Status:** Open
**Discovered:** 2026-05-12
**Severity:** Medium — `ask`/`delegate`/`stop`/`tell` commands don't work when targeting local special agents (Coder, Debugger)
**Introduced:** Phase 1.4 (AgentRuntime) — `forward_to` path never updated for special agent routing

---

## Problem

`ChatHandler.on_send()` has two routing paths:

1. **Normal message path** (line ~385) — correctly checks `is_special` and routes through `AgentRuntimeHandler.send_to_special_agent()` for special agents, `gw.send_message()` for gateway agents. ✅

2. **Command `forward_to` path** (line ~248) — always sends via `self._gw.send_message(result.forward_to, result.forward_text)` regardless of whether the target is a special agent or gateway agent. ❌

When a user types `` `ask @Coder question` `` in a project tab:
- `CommandHandler` resolves `@Coder` → `special:coder`
- `CollabHandler.cmd_ask()` returns `CommandResult(forward_to="special:coder", forward_text="question")`
- `ChatHandler` sends `gw.send_message("special:coder", "question")`
- Gateway doesn't know what `special:coder` is → message silently lost

The same bug affects `delegate`, `stop`, and `tell` commands targeting any special agent.

## Root Cause

The `forward_to` routing block was written before Phase 1.4 (AgentRuntime) introduced local special agents. When special agent routing was added to the normal message path, the command `forward_to` path was never updated.

## Fix

Add the same `is_special` check to the `forward_to` path in `ChatHandler.on_send()` (around line 248):

```python
# Current (broken):
if result.forward_to and result.forward_text:
    agent_name = result.forward_to.split("/")[-1]
    echo_text = f"→ @{agent_name}: {result.forward_text}"
    def _show_echo_and_forward():
        # ... echo bubble rendering ...
        if self._gw is not None and self._gw.is_connected():
            self._gw.send_message(result.forward_to, result.forward_text)
    self._dispatch(_show_echo_and_forward)
```

```python
# Fixed:
if result.forward_to and result.forward_text:
    agent_name = result.forward_to.split("/")[-1]
    echo_text = f"→ @{agent_name}: {result.forward_text}"
    def _show_echo_and_forward():
        # ... echo bubble rendering ...
        # Route through AgentRuntime for special agents, gateway for others
        is_special = (self._agent_runtime_handler is not None
                      and result.forward_to in self._agent_runtime_handler.get_special_agents())
        if is_special:
            self._agent_runtime_handler.send_to_special_agent(result.forward_to, result.forward_text)
        elif self._gw is not None and self._gw.is_connected():
            self._gw.send_message(result.forward_to, result.forward_text)
    self._dispatch(_show_echo_and_forward)
```

The same pattern should also be applied to the `broadcast_targets` path (around line 250-275) which does a loop over targets — each target needs the same `is_special` check.

## Test Cases

1. `` `ask @Coder how do I parse this?` `` from a project tab → message reaches Coder via AgentRuntime
2. `` `ask @QTR status update` `` from a project tab → message reaches QTR via gateway (no regression)
3. `` `delegate @Coder implement auth` `` → same special/gateway split
4. `` `ask @all what do you think?` `` (broadcast) → special agents via AgentRuntime, gateway agents via gw

## Related Files

- `ui/handlers/chat_handler.py` — lines ~228-275 (forward_to and broadcast_targets routing)
- `ui/handlers/collab_handler.py` — returns CommandResult with forward_to
- `ui/handlers/agent_runtime_handler.py` — `send_to_special_agent()` (correct routing target)
