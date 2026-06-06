# tests/test_activity_drawer.py
# Tests for SPEC-activity-drawer — Phase 3.
#
# Architecture:
#   ActivityBubble.to_drawer_row() — pure-Python dict builder
#   ActivityDrawer — pure GTK view; receives dicts via append_event()
#   ActivityHandler.set_on_agent_lifecycle — fires (sk, agent_name, phase)
#
# These tests cover:
#   1. TestToDrawerRow — 5 tests on ActivityBubble.to_drawer_row()
#   2. TestActivityDrawer — 6 tests on drawer state mutation
#   3. TestActivityHandlerLifecycleCallback — 3 tests on lifecycle firing
#
# GTK initialization: the ActivityDrawer test class patches
# _build_header and _build_list to no-ops so the drawer can be
# constructed in a headless test environment without a display.

import gi
gi.require_version('Gtk', '4.0')

import re
from unittest.mock import MagicMock, patch

import pytest


# ── Class 1: TestToDrawerRow — pure-Python dataclass tests ────────


class TestToDrawerRow:
    """ActivityBubble.to_drawer_row() returns a flat dict the drawer consumes."""

    def test_basic_fields_present(self):
        """All 12 spec-required keys exist in the returned dict."""
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_start", session_key="sk-1", tool_name="web_search")
        row = b.to_drawer_row()
        required_keys = {
            "agent", "agent_name", "session_key", "activity_type", "icon",
            "type_label", "command", "file_path", "output", "exit_code",
            "duration", "duration_ms", "timestamp", "raw_text",
        }
        missing = required_keys - set(row.keys())
        assert not missing, f"missing required keys: {missing}"
        # Spot-check values for sanity
        assert row["session_key"] == "sk-1"
        assert row["activity_type"] == "tool_start"
        assert row["type_label"] == "tool"

    def test_agent_name_default_is_Agent(self):
        """When agent_name='', the dict's 'agent' key is 'Agent' (the fallback label)."""
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_start", session_key="sk-1", tool_name="search")
        row = b.to_drawer_row()
        assert row["agent_name"] == ""
        assert row["agent"] == "Agent"

    def test_agent_name_propagates(self):
        """When agent_name is set, the dict's 'agent' key matches."""
        from models.activity import ActivityBubble
        b = ActivityBubble(
            type="tool_start", session_key="sk-1", tool_name="search",
            agent_name="Coder",
        )
        row = b.to_drawer_row()
        assert row["agent_name"] == "Coder"
        assert row["agent"] == "Coder"

    def test_timestamp_format_is_hms(self):
        """The 'timestamp' field is HH:MM:SS — three 2-digit groups separated by colons."""
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_start", session_key="sk-1")
        row = b.to_drawer_row()
        ts = row["timestamp"]
        assert isinstance(ts, str)
        assert re.match(r"^\d{2}:\d{2}:\d{2}$", ts), f"timestamp {ts!r} is not HH:MM:SS"

    def test_duration_formatting(self):
        """_format_duration rules: <1000ms → Nms; <60_000ms → N.Ns; >=60_000ms → Nm Ns; <=0 → ''."""
        from models.activity import ActivityBubble
        # 1247ms → "1.2s"
        b1 = ActivityBubble(type="tool_end", session_key="sk-1", duration_ms=1247)
        assert b1.to_drawer_row()["duration"] == "1.2s"
        # 60000ms → "1m 0s"
        b2 = ActivityBubble(type="tool_end", session_key="sk-1", duration_ms=60000)
        assert b2.to_drawer_row()["duration"] == "1m 0s"
        # 0ms → "" (per models/activity.py: ms <= 0 returns "")
        b3 = ActivityBubble(type="tool_end", session_key="sk-1", duration_ms=0)
        assert b3.to_drawer_row()["duration"] == ""
        # 847ms → "847ms"
        b4 = ActivityBubble(type="tool_end", session_key="sk-1", duration_ms=847)
        assert b4.to_drawer_row()["duration"] == "847ms"

    def test_exit_code_only_for_command_output(self):
        """For non-command_output types, exit_code is None; for command_output, it's the bubble's value."""
        from models.activity import ActivityBubble
        # non-command_output → None
        b1 = ActivityBubble(type="tool_end", session_key="sk-1", exit_code=42)
        assert b1.to_drawer_row()["exit_code"] is None
        # command_output → preserves value (0 is kept, non-zero too)
        b2 = ActivityBubble(type="command_output", session_key="sk-1", exit_code=0)
        assert b2.to_drawer_row()["exit_code"] == 0
        b3 = ActivityBubble(type="command_output", session_key="sk-1", exit_code=127)
        assert b3.to_drawer_row()["exit_code"] == 127

    def test_type_label_mapping(self):
        """command_output → 'exec', lifecycle_start → 'lifecycle', plan → 'plan', etc."""
        from models.activity import ActivityBubble
        cases = [
            ("command_output", "exec"),
            ("lifecycle_start", "lifecycle"),
            ("plan", "plan"),
            ("approval_request", "approval"),
            ("patch", "patch"),
            ("tool_start", "tool"),
            ("tool_end", "tool"),
            ("tool_error", "tool"),
        ]
        for activity_type, expected_label in cases:
            b = ActivityBubble(type=activity_type, session_key="sk-1")
            assert b.to_drawer_row()["type_label"] == expected_label, \
                f"{activity_type} should map to {expected_label!r}"


# ── Class 2: TestActivityDrawer — drawer state mutation tests ────


class TestActivityDrawer:
    """ActivityDrawer state mutation: append_event, counter-collapse, filters, clear.

    GTK widget construction is patched to no-ops so the tests run
    headless. We test the data-state methods directly: append_event,
    on_agent_start, on_agent_end, clear_events, _passes_filter.
    """

    @pytest.fixture
    def drawer(self, monkeypatch):
        """Construct an ActivityDrawer with GTK widget builders patched to no-ops."""
        # Patch the GTK widget builders to no-ops before any drawer code runs
        # This avoids the need for an actual GTK display.
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._build_header",
            lambda self: None,
        )
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._build_list",
            lambda self: None,
        )
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._apply_expanded_state",
            lambda self: None,
        )
        # Patch the helper methods that touch GTK widgets
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._update_count_label",
            lambda self: None,
        )
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._trim_old_rows_if_needed",
            lambda self: None,
        )
        monkeypatch.setattr(
            "ui.views.activity_drawer.ActivityDrawer._auto_scroll_to_bottom",
            lambda self: None,
        )

        # Mock Gtk widgets: provide just enough surface for the drawer to track state
        fake_list = MagicMock()
        fake_list.get_row_at_index = MagicMock(return_value=None)
        fake_list.append = MagicMock()
        fake_list.remove = MagicMock()

        # Patch Gtk.Box to return a mock that the drawer's __init__ can super() into
        from gi.repository import Gtk
        monkeypatch.setattr(Gtk, "Box", MagicMock)

        from ui.views.activity_drawer import ActivityDrawer
        d = ActivityDrawer()
        # Inject the fake list — drawer reads self._list for append_event logic
        d._list = fake_list
        d._listbox = fake_list  # backward-compat alias in case
        return d

    def test_append_event_new_row(self, drawer):
        """Fresh drawer: append_event → 1 row, _last_row_key set, _total_count=1."""
        row = {
            "agent": "Coder",
            "activity_type": "tool_start",
            "type_label": "tool",
            "icon": "🔧",
        }
        drawer.append_event(row)
        assert drawer._total_count == 1
        assert drawer._last_row_key == ("Coder", "tool_start")
        assert drawer._list.append.called

    def test_append_event_counter_collapse(self, drawer):
        """Two same-(agent, type) events → counter collapsed, but only 1 list.append call."""
        row = {
            "agent": "Coder",
            "activity_type": "tool_start",
            "type_label": "tool",
            "icon": "🔧",
        }
        drawer.append_event(row)
        drawer.append_event(row)  # same key
        # First call appends; second call mutates in place (no new list.append)
        assert drawer._list.append.call_count == 1, \
            f"expected 1 list.append, got {drawer._list.append.call_count}"
        assert drawer._total_count == 2  # both events counted

    def test_append_event_different_type_new_row(self, drawer):
        """Same agent, different activity_type → 2 list.append calls (counter chain broken)."""
        row_tool = {
            "agent": "Coder", "activity_type": "tool_start", "type_label": "tool", "icon": "🔧",
        }
        row_plan = {
            "agent": "Coder", "activity_type": "plan", "type_label": "plan", "icon": "📋",
        }
        drawer.append_event(row_tool)
        drawer.append_event(row_plan)
        assert drawer._list.append.call_count == 2
        assert drawer._total_count == 2
        assert drawer._last_row_key == ("Coder", "plan")

    def test_filter_drop_unmatched(self, drawer):
        """When _visible_agents = {'Coder'}, an event with agent='Debugger' is dropped (not appended)."""
        drawer._visible_agents = {"Coder"}
        row = {
            "agent": "Debugger",
            "activity_type": "tool_start",
            "type_label": "tool",
            "icon": "🔧",
        }
        drawer.append_event(row)
        # Row was dropped, not appended
        assert drawer._list.append.call_count == 0
        # But total_count still increments
        assert drawer._total_count == 1

    def test_filter_pass_matched(self, drawer):
        """When _visible_agents = {'Coder'}, an event with agent='Coder' is appended."""
        drawer._visible_agents = {"Coder"}
        row = {
            "agent": "Coder",
            "activity_type": "tool_start",
            "type_label": "tool",
            "icon": "🔧",
        }
        drawer.append_event(row)
        assert drawer._list.append.call_count == 1
        assert drawer._total_count == 1

    def test_filter_type_set_blocks_non_matching(self, drawer):
        """Type filter is also AND — non-matching type drops the row even if agent matches."""
        drawer._visible_types = {"tool_start"}
        row = {
            "agent": "Coder",
            "activity_type": "plan",  # not in the filter set
            "type_label": "plan",
            "icon": "📋",
        }
        drawer.append_event(row)
        assert drawer._list.append.call_count == 0
        assert drawer._total_count == 1

    def test_clear_events_resets_state(self, drawer):
        """clear_events() empties _total_count, _last_row_key, _agent_counters."""
        row = {
            "agent": "Coder", "activity_type": "tool_start", "type_label": "tool", "icon": "🔧",
        }
        drawer.append_event(row)
        drawer.append_event(row)
        assert drawer._total_count == 2
        assert drawer._last_row_key is not None
        # Make get_row_at_index return None (no rows) so the while-loop exits
        drawer._list.get_row_at_index.return_value = None
        drawer.clear_events()
        assert drawer._total_count == 0
        assert drawer._last_row_key is None
        assert drawer._agent_counters == {}

    def test_passes_filter_empty_set_passes_all(self, drawer):
        """Empty filter sets pass everything (default behavior)."""
        assert drawer._visible_agents == set()
        assert drawer._visible_types == set()
        assert drawer._passes_filter("Coder", "tool_start") is True
        assert drawer._passes_filter("Anything", "any_type") is True

    def test_passes_filter_agent_filter_active(self, drawer):
        """Non-empty _visible_agents only passes rows in the set."""
        drawer._visible_agents = {"Coder", "Debugger"}
        assert drawer._passes_filter("Coder", "tool_start") is True
        assert drawer._passes_filter("Debugger", "plan") is True
        assert drawer._passes_filter("Crabcakes", "tool_start") is False


# ── Class 3: TestActivityHandlerLifecycleCallback ────────────────


class TestActivityHandlerLifecycleCallback:
    """ActivityHandler fires set_on_agent_lifecycle on lifecycle events.

    Callback signature: cb(session_key, agent_name, phase) where phase
    is "start" or "end". agent_name comes from payload.data.agentName,
    defaulting to "" if the gateway doesn't supply it.
    """

    def test_lifecycle_start_fires_callback(self, fake_glib):
        """stream=lifecycle phase=start → cb(sk, agent_name, "start")."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(
            feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib,
        )
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "startedAt": 12345, "agentName": "Coder"},
        })

        cb.assert_called_once()
        args = cb.call_args[0]
        assert args == ("sk-1", "Coder", "start")

    def test_lifecycle_end_fires_callback(self, fake_glib):
        """stream=lifecycle phase=end → cb(sk, agent_name, "end")."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(
            feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib,
        )
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end", "agentName": "Debugger"},
        })

        cb.assert_called_once()
        args = cb.call_args[0]
        assert args == ("sk-1", "Debugger", "end")

    def test_lifecycle_end_without_agent_name(self, fake_glib):
        """When payload has no agentName, cb is called with empty string for agent_name."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(
            feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib,
        )
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end"},  # no agentName field
        })

        cb.assert_called_once()
        args = cb.call_args[0]
        # agent_name defaults to "" — drawer will show "[Agent]" for unknown agents
        assert args == ("sk-1", "", "end")

    def test_lifecycle_error_fires_end_callback(self, fake_glib):
        """stream=lifecycle phase=error → cb(sk, agent_name, "end") (error reuses end path)."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(
            feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib,
        )
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "error", "agentName": "Coder"},
        })

        cb.assert_called_once()
        args = cb.call_args[0]
        assert args == ("sk-1", "Coder", "end")

    def test_lifecycle_callback_not_set_does_not_crash(self, fake_glib):
        """If set_on_agent_lifecycle was never called, lifecycle events must not raise."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(
            feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib,
        )
        # No set_on_agent_lifecycle call
        try:
            handler.on_gateway_event("agent", {
                "stream": "lifecycle",
                "sessionKey": "sk-1",
                "runId": "run-1",
                "data": {"phase": "start", "agentName": "Coder"},
            })
        except Exception as e:
            pytest.fail(f"lifecycle event crashed when callback unset: {e}")
