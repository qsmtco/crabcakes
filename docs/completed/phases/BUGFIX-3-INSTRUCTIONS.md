# BUGFIX 3 — Initialize `_agent_counters[agent]` in the new-row path of `append_event()`

## Problem

`ui/views/activity_drawer.py` — The `_agent_counters[agent]` dict is only initialized inside `_mutate_counter_row()` (the counter-collapse path). When a session has mixed event types (no counter-collapse happens because consecutive events have different `(agent, activity_type)` keys), `_agent_counters[agent]` is never populated. When `on_agent_end()` runs, `self._agent_counters.pop(agent_name, None)` returns `None`, and the separator shows "ended" instead of the actual event count and total duration.

## Context

- `_agent_counters` is keyed by agent name (string), valued as `{"count": N, "total_duration_ms": M, "last_command": "..."}`
- `_mutate_counter_row()` (line ~455) initializes via `setdefault(agent, {"count": 1, ...})` — but only runs on counter-collapse (same key back-to-back)
- `append_event()` new-row path (line ~207-212) does NOT initialize the counter
- `on_agent_end()` (line ~240) reads the counter for the summary separator
- The `setdefault` in `_mutate_counter_row` initializes count to 1 (representing the anchor event), then increments to 2. This means the math is correct for collapsed sequences: count = mutations + 1 = total events.
- For the new-row path, we need to ADD to the counter (not overwrite it), because the agent may have multiple non-collapsed events across different types

## What to implement

### File 1: `ui/views/activity_drawer.py` — method `append_event()`, new-row path

After `self._list.append(row_widget)` and `self._last_row_key = key` / `self._last_row_widget = row_widget` (around line 209-210), add counter initialization:

```python
# BUGFIX-3: Track this event in the agent's running counter so that
# on_agent_end() can produce an accurate summary even when no counter-
# collapse happens (mixed event types from the same agent).
agent_counter = self._agent_counters.setdefault(
    agent, {"count": 0, "total_duration_ms": 0, "last_command": ""}
)
agent_counter["count"] += 1
agent_counter["total_duration_ms"] += row.get("duration_ms", 0)
if row.get("command"):
    agent_counter["last_command"] = row["command"]
```

**Important:** Use `setdefault` with `count: 0` (NOT 1 — that was the anchor trick in `_mutate_counter_row`). Here we're incrementing from 0 because this is the actual event count, not an anchor. The `_mutate_counter_row` method's `setdefault(agent, {"count": 1, ...})` will still work correctly because `setdefault` only initializes if the key doesn't exist yet — and after BUGFIX-3, it will already exist, so `setdefault` returns the existing counter and the `count += 1` in `_mutate_counter_row` adds to the already-correct count.

**Wait — there's a subtle interaction.** Let me trace carefully:

Scenario: 3 tool_end events from Qaster, all counter-collapsed:
1. Event 1 (tool_end): NEW row (BUGFIX-3 path). Counter init: count=0+1=1, duration=0+200=200.
2. Event 2 (tool_end): Counter-collapse. `_mutate_counter_row` runs. `setdefault` finds existing counter (count=1). `count += 1` → 2. `total += 150` → 350.
3. Event 3 (tool_end): Counter-collapse. `setdefault` finds counter (count=2). `count += 1` → 3. `total += 168` → 518.

Result: count=3, total=518. ✅ Correct.

But wait — `_mutate_counter_row` ALSO initializes the counter with `setdefault(agent, {"count": 1, ...})`. If the counter already exists (from BUGFIX-3), `setdefault` returns the existing dict and doesn't overwrite. So `count += 1` adds to the existing count. ✅

Scenario: 1 tool_start + 1 tool_end + 1 plan from Qaster (no collapse):
1. Event 1 (tool_start): NEW row. Counter: count=0+1=1, duration=0.
2. Event 2 (tool_end): NEW row (different type). Counter: count=1+1=2, duration=0+200=200.
3. Event 3 (plan): NEW row (different type). Counter: count=2+1=3, duration=200+0=200.

Result: count=3, total=200. ✅ Correct. Previously showed "ended", now shows "3 events in 200ms".

### File 2: `tests/test_activity_drawer.py`

Add a test to `TestActivityDrawerAppend` or a new class:

1. Create a drawer
2. Append 3 events from the same agent but with DIFFERENT activity types (no counter-collapse)
3. Call `on_agent_end("sk-1", "Coder")`
4. Assert the separator shows "N events in Xms" (NOT "ended")

Also add a test for the mixed scenario:
1. 1 event of type A (new row)
2. 2 events of type A (counter-collapse)
3. 1 event of type B (new row)
4. `on_agent_end` → assert total count = 4

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "_agent_counters" ui/views/activity_drawer.py | head -15
python3 -m pytest tests/test_activity_drawer.py -q --tb=short
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Added agent_counter initialization in append_event() new-row path — evidence: grep line numbers
- [ ] Edit 2: Added test for mixed-type events producing accurate on_agent_end summary — evidence: test pass
- [ ] Edit 3: Added test for mixed new-row + counter-collapse scenario — evidence: test pass
- [ ] Edit 4: Full test suite passes — evidence: pytest output
```
