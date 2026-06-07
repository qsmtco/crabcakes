# BUGFIX 7, 8, 9 — Low-severity fixes

## BUGFIX 7 — Fix inconsistent if/elif chain in activity_handler.py

### Problem

The first `if event == "agent":` block has an inconsistent dispatch structure:
- Line ~280: `if stream == "assistant":` — an `if` (not `elif`)
- Line ~288: `if stream == "lifecycle":` — an `if` (not `elif`)
- Line ~343: `elif stream == "item":` — an `elif` attached to the `lifecycle` `if`

This means `stream == "assistant"` is checked first, then `stream == "lifecycle"` is checked INDEPENDENTLY (always runs), then the `elif` chain (`item`, `plan`, `approval`, `patch`, `command_output`) is attached to the `lifecycle` `if`.

### What to do

Convert the `lifecycle` `if` to `elif` so the entire dispatch is mutually exclusive:

```python
if event == "agent":
    stream = payload.get("stream", "")
    if stream == "assistant":
        ...
    elif stream == "lifecycle":
        ...
    elif stream == "item":
        ...
    elif stream == "plan":
        ...
    elif stream == "approval":
        ...
    elif stream == "patch":
        ...
    elif stream == "command_output":
        ...
```

This is semantically identical because the gateway never sends two streams in one event, but makes the mutual exclusion explicit and prevents future bugs from inserting a new `if` between the lifecycle and item branches.

### Test

No new test needed — the existing tests already verify each branch fires independently. Just run the existing test suite to confirm no regression.

---

## BUGFIX 8 — Remove redundant guard in connection_sync_handler.py

### Problem

`ui/handlers/connection_sync_handler.py` — the `_on_command_output` closure has `if agent_runtime is not None:` inside it, but the closure is only created inside a `if agent_runtime is not None:` check at line ~198. The inner guard is always True.

### What to do

Remove the inner `if agent_runtime is not None:` guard and dedent the code inside it. The variable is guaranteed non-None by the outer scope.

### Verification

```bash
cd /home/q/projects/crabcakes
grep -n "agent_runtime is not None" ui/handlers/connection_sync_handler.py
# Should show only ONE match (the outer scope check)
```

---

## BUGFIX 9 — Add type guards to `_passes_filter()`

### Problem

`ui/views/activity_drawer.py` — `_passes_filter(agent, activity_type)` assumes both arguments are strings. If a malformed dict passes through (or a test mock provides non-string values), the `not in self._visible_agents` check may throw TypeError.

### What to do

Add a guard at the top of `_passes_filter`:

```python
if not isinstance(agent, str):
    agent = str(agent) if agent is not None else "Agent"
if not isinstance(activity_type, str):
    activity_type = str(activity_type) if activity_type is not None else ""
```

### Test

Add a test to `TestActivityDrawer`:
```python
def test_passes_filter_handles_non_string_agent(self, drawer):
    """BUGFIX-9: _passes_filter should not crash on non-string agent."""
    drawer._visible_agents = {"Coder"}
    # Non-string agent — should not crash
    assert drawer._passes_filter("Coder", "tool") is True
    assert drawer._passes_filter(None, "tool") is False  # coerced to "Agent"
```

---

## Verification Commands

```bash
cd /home/q/projects/crabcakes
# BUGFIX 7: verify elif chain
grep -n "if stream ==" ui/handlers/activity_handler.py | head -10

# BUGFIX 8: verify only one guard remains
grep -n "agent_runtime is not None" ui/handlers/connection_sync_handler.py

# BUGFIX 9: verify type guard
grep -n "isinstance.*agent.*str\|isinstance.*activity_type.*str" ui/views/activity_drawer.py

# Full suite
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1 (BUGFIX-7): Converted lifecycle `if` to `elif` in activity_handler.py — evidence: grep showing elif chain
- [ ] Edit 2 (BUGFIX-8): Removed redundant inner guard in connection_sync_handler.py — evidence: grep showing single match
- [ ] Edit 3 (BUGFIX-9): Added type guards to _passes_filter() — evidence: grep showing isinstance checks
- [ ] Edit 4 (BUGFIX-9): Added test for non-string agent — evidence: test pass
- [ ] Edit 5: Full test suite passes — evidence: pytest output
```
