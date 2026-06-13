# FILTERFIX 2 — Fix ordering: update `_known_agents`/`_known_types` BEFORE filter check

## Problem

`ui/views/activity_drawer.py:190-198` — In `append_event()`, the known-sets are only updated AFTER the filter check:

```python
# Filter check — drop the row if filtered out
if not self._passes_filter(agent, activity_type):
    self._total_count += 1
    self._update_count_label()
    return  # ← early return — _known_agents NOT updated

# Track known agents/types for the filter dropdowns
self._known_agents.add(agent)
self._known_types.add(activity_type)
```

**Impact:** If a filter is set to a specific agent (e.g., `_visible_agents = {"Coder"}`), a new event from "Debugger" arrives, the filter check returns False, the early return fires, and `_known_agents` is NEVER updated with "Debugger". The popover dropdown never shows "Debugger" as an option — the user can never re-enable it.

## Note: This bug is RELATED to FILTERFIX-1

After FILTERFIX-1, the popover content is refreshed only when `_known_agents`/`_known_types` change. If the filter blocks the `_known_agents.add()` call, the popover is also never refreshed. So the symptom only manifests when BOTH:
1. A filter is active
2. A new event from a non-matching agent/type arrives

## What to implement

### File: `ui/views/activity_drawer.py`

In `append_event()`, move the known-set updates ABOVE the filter check:

**Before:**
```python
# Filter check — drop the row if filtered out
if not self._passes_filter(agent, activity_type):
    self._total_count += 1
    self._update_count_label()
    return

# Track known agents/types for the filter dropdowns
self._known_agents.add(agent)
self._known_types.add(activity_type)
self._refresh_filter_popovers()  # FILTERFIX-1
```

**After:**
```python
# Track known agents/types for the filter dropdowns BEFORE the filter
# check, so agents/types that get filtered out are still discoverable
# in the dropdown (the user can re-enable them later).
# FILTERFIX-1 audit: capture whether the sets actually changed BEFORE
# the .add() calls — once added, we can't tell if it was new.
new_agent = agent not in self._known_agents
new_type = activity_type not in self._known_types
self._known_agents.add(agent)
self._known_types.add(activity_type)
if new_agent or new_type:
    self._refresh_filter_popovers()

# Filter check — drop the row if filtered out
if not self._passes_filter(agent, activity_type):
    self._total_count += 1
    self._update_count_label()
    return
```

The known-set update + refresh now happens for EVERY event, regardless of whether it passes the filter. The filter check still happens but only affects row visibility, not the known-set.

## Test

Add to `tests/test_activity_drawer.py`:

```python
def test_known_sets_updated_even_when_filter_blocks_event(self, drawer):
    """FILTERFIX-2: events that fail the filter check must still update
    _known_agents / _known_types so they appear in the dropdown."""
    # Set a filter that blocks all events
    drawer._visible_agents = {"Coder"}
    drawer._visible_types = {"tool_start"}

    # Send a Debugger/plan event — blocked by the filter
    drawer.append_event({
        "agent": "Debugger",
        "activity_type": "plan",
        "type_label": "plan",
        "icon": "📋",
    })

    # _known_agents / _known_types MUST include "Debugger" and "plan"
    assert "Debugger" in drawer._known_agents, (
        "Filtered-out events must still update _known_agents"
    )
    assert "plan" in drawer._known_types, (
        "Filtered-out events must still update _known_types"
    )
```

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "self._known_agents.add\|self._known_types.add\|_passes_filter" ui/views/activity_drawer.py | head -10
python3 -m pytest tests/test_activity_drawer.py -q --tb=short
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Moved known-set updates above filter check in append_event — evidence: grep showing new ordering
- [ ] Edit 2: Added test_known_sets_updated_even_when_filter_blocks_event — evidence: test pass
- [ ] Edit 3: Full test suite passes — evidence: pytest output
```
