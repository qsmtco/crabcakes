# FILTERFIX-1 Audit — Unnecessary rebuild on every event

## Bug

`ui/views/activity_drawer.py` — `_refresh_filter_popovers()` is called on every `append_event()` (line 221), even when `_known_agents` and `_known_types` have not changed. For a session with 100 events of the same agent, this destroys and recreates all checkboxes 100 times.

## Attack vector

A normal session with 50 tool events from the same agent would trigger 50 popover rebuilds, each destroying ~6 widgets (1 "All" checkbox + 5 agent checkboxes + 1 "All" types + 2 type checkboxes = 9 widgets per rebuild, × 2 popovers = 18 widgets destroyed and recreated per event).

## Reproduction

1. Run a long session (50+ events from the same agent)
2. Monitor the popover content — it's destroyed and recreated on every event
3. CPU usage spikes from widget allocation churn

## Fix

In `append_event()`, check if the known-sets actually changed before calling `_refresh_filter_popovers()`:

```python
# Before:
self._known_agents.add(agent)
self._known_types.add(activity_type)
self._refresh_filter_popovers()

# After:
new_agent = agent not in self._known_agents
new_type = activity_type not in self._known_types
self._known_agents.add(agent)
self._known_types.add(activity_type)
if new_agent or new_type:
    self._refresh_filter_popovers()
```

## Test

Add a test to `tests/test_activity_drawer.py`:

```python
def test_popovers_not_refreshed_when_known_sets_unchanged(self, drawer, monkeypatch):
    """FILTERFIX-1 audit: _refresh_filter_popovers must only be called when
    _known_agents or _known_types actually changes."""
    refresh_spy = MagicMock()
    monkeypatch.setattr(drawer, "_refresh_filter_popovers", refresh_spy)

    # First event — new agent/type, refresh expected
    drawer.append_event({"agent": "Coder", "activity_type": "tool_start", "type_label": "tool", "icon": "🔧"})
    assert refresh_spy.call_count == 1

    # Second event — same agent/type, no refresh expected
    drawer.append_event({"agent": "Coder", "activity_type": "tool_start", "type_label": "tool", "icon": "🔧"})
    assert refresh_spy.call_count == 1, "Should not refresh when agent/type unchanged"

    # Third event — new agent, refresh expected
    drawer.append_event({"agent": "Debugger", "activity_type": "plan", "type_label": "plan", "icon": "📋"})
    assert refresh_spy.call_count == 2
```

## Verification

```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_activity_drawer.py -q --tb=short
```
