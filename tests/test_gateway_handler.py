# tests/test_gateway_handler.py
# Tests for ui/handlers/gateway_handler.py — GatewayHandler.
#
# Principle: test the failure modes that would break callers.
# Mock GatewayClient, Toolbar, LeftPanel at the boundary.
# Mock GLib to verify idle_add is called for GTK operations.

import pytest
from unittest.mock import MagicMock, patch, call


# ── Fake GLib ─────────────────────────────────────────────────────────────────

class FakeGLib:
    """Simulates GLib.idle_add — stores callbacks but does NOT run them until dispatch() is called."""

    def __init__(self):
        self._pending = []  # list of (fn, args, kwargs)
        self._dispatched = []  # list of (fn, args, kwargs) that have been dispatched

    def idle_add(self, fn, *args, **kwargs):
        # Store for later — does NOT execute synchronously (mimics real GLib behavior)
        self._pending.append((fn, args, kwargs))
        return len(self._pending)  # return a source ID

    def dispatch_all(self):
        """Simulate GTK idle cycle — run all pending callbacks in order."""
        results = []
        while self._pending:
            fn, args, kwargs = self._pending.pop(0)
            self._dispatched.append((fn, args, kwargs))
            results.append(fn(*args, **kwargs))
        return results


# ── Fake Toolbar ───────────────────────────────────────────────────────────────

class FakeToolbar:
    """Tracks update_connection_state calls."""

    def __init__(self):
        self._state = "disconnected"
        self._calls = []

    def update_connection_state(self, state):
        self._state = state
        self._calls.append(state)


# ── Fake LeftPanel ────────────────────────────────────────────────────────────

class FakeLeftPanel:
    """Tracks set_agents calls."""

    def __init__(self):
        self._agents = {}
        self._callback = None
        self._calls = []

    def set_agents(self, agent_names_ref, on_agent_selected_callback):
        self._agents = dict(agent_names_ref) if agent_names_ref else {}
        self._callback = on_agent_selected_callback
        self._calls.append(("set_agents", dict(self._agents)))


# ── Fake AgentManager ─────────────────────────────────────────────────────────

class FakeAgentManager:
    """Fake AgentManager for gateway handler tests."""

    def __init__(self):
        self._sessions = {}

    def clear(self):
        self._sessions = {}

    def register(self, session_key, name):
        if name not in self._sessions:
            self._sessions[name] = []
        if session_key not in self._sessions[name]:
            self._sessions[name].append(session_key)

    def get_sessions(self, name):
        return self._sessions.get(name, [])

    def get_names_ref(self):
        """Returns a dict {name: [session_keys]}."""
        return self._sessions


# ── Fake GatewayClient ─────────────────────────────────────────────────────────

class FakeGatewayClient:
    """Fake GatewayClient — matches the real GatewayClient constructor signature."""

    def __init__(self, url="ws://localhost:18789", on_connect=None, on_error=None, on_event=None, on_tick=None):
        self.url = url
        self._on_connect = on_connect
        self._on_error = on_error
        self._on_event = on_event
        self._on_tick = on_tick if on_tick is not None else lambda: None
        self._connected = False
        self._snapshot = {"health": {"agents": []}}

    def start(self):
        self._connected = True

    def stop(self):
        self._connected = False

    def is_connected(self):
        return self._connected

    def get_snapshot(self):
        return self._snapshot

    def set_snapshot(self, snapshot):
        self._snapshot = snapshot

    # Simulate the gateway calling its own on_connect callback
    def simulate_connect(self):
        if self._on_connect:
            self._on_connect()

    def simulate_error(self, msg="connection refused"):
        if self._on_error:
            self._on_error(msg)

    def simulate_event(self, event, payload):
        if self._on_event:
            self._on_event(event, payload)


# ── Subject under test ─────────────────────────────────────────────────────────

def make_handler(
    toolbar=None,
    left_panel=None,
    on_agent_selected=None,
    on_event=None,
    GLib_module=None,
    gateway_client_class=None,
    agent_manager_class=None,
):
    """Create a GatewayHandler with injected fakes."""
    from ui.handlers.gateway_handler import GatewayHandler

    return GatewayHandler(
        toolbar=toolbar or FakeToolbar(),
        left_panel=left_panel or FakeLeftPanel(),
        on_agent_selected=on_agent_selected or MagicMock(),
        on_event=on_event or MagicMock(),
        GLib_module=GLib_module or FakeGLib(),
        gateway_client_class=gateway_client_class or FakeGatewayClient,
        agent_manager_class=agent_manager_class or FakeAgentManager,
    )


# ── Tests: connect() ──────────────────────────────────────────────────────────

class TestConnect:
    """connect() must create GatewayClient and AgentManager, start the client."""

    def test_creates_gateway_client(self):
        """connect() must create a GatewayClient instance."""
        handler = make_handler()
        handler.connect()

        assert handler._gw is not None
        assert handler._gw.is_connected()

    def test_creates_agent_manager(self):
        """connect() must create an AgentManager instance."""
        handler = make_handler()
        handler.connect()

        assert handler._agent_mgr is not None

    def test_sets_connecting_state_before_start(self):
        """Toolbar must show 'connecting' before client.start() is called."""
        toolbar = FakeToolbar()
        handler = make_handler(toolbar=toolbar)
        handler.connect()

        assert "connecting" in toolbar._calls

    def test_second_connect_stops_old_client(self):
        """Calling connect() twice must stop the old client first."""
        handler = make_handler()
        handler.connect()
        client1 = handler._gw

        handler.connect()
        client2 = handler._gw

        assert not client1.is_connected()  # old client stopped
        assert client2.is_connected()       # new client running
        assert client1 is not client2       # different instances

    def test_disconnect_before_first_connect_no_crash(self):
        """disconnect() called before connect() must not crash."""
        handler = make_handler()
        handler.disconnect()  # must not raise


# ── Tests: disconnect() ────────────────────────────────────────────────────────

class TestDisconnect:
    """disconnect() must stop client, clear state, update toolbar."""

    def test_stops_gateway_client(self):
        """disconnect() must stop the running GatewayClient."""
        handler = make_handler()
        handler.connect()
        client_before_disconnect = handler._gw
        handler.disconnect()

        assert not client_before_disconnect.is_connected()

    def test_clears_agent_manager(self):
        """disconnect() must clear the AgentManager."""
        handler = make_handler()
        handler.connect()
        am_before_disconnect = handler._agent_mgr
        handler.disconnect()

        # AgentManager is still there but cleared
        assert am_before_disconnect.get_sessions("any") == []

    def test_sets_disconnected_state(self):
        """Toolbar must show 'disconnected' after disconnect (dispatch idle callbacks first)."""
        toolbar = FakeToolbar()
        GLib = FakeGLib()
        handler = make_handler(toolbar=toolbar, GLib_module=GLib)
        handler.connect()
        handler.disconnect()

        # disconnect() queued its "disconnected" update via idle_add — dispatch it
        GLib.dispatch_all()

        assert "disconnected" in toolbar._calls

    def test_disconnect_when_not_connected_no_crash(self):
        """disconnect() when not connected must not crash."""
        handler = make_handler()
        handler.disconnect()  # must not raise


# ── Tests: on_connected() — GTK thread safety ─────────────────────────────────

class TestOnConnected:
    """on_connected() fires from gateway thread — GTK calls must use idle_add."""

    def test_connection_state_update_dispatched_to_main_thread(self):
        """Toolbar state update must be dispatched via GLib.idle_add."""
        toolbar = FakeToolbar()
        GLib = FakeGLib()
        handler = make_handler(toolbar=toolbar, GLib_module=GLib)
        handler.connect()
        # connect() already queued "connecting" synchronously
        GLib.dispatch_all()  # drain connect's idle callbacks first
        toolbar._calls.clear()  # reset to measure only on_connected effect

        handler._gw.simulate_connect()  # trigger on_connected callback

        # "connected" queued but not yet dispatched
        assert toolbar._state == "connecting"
        assert len(GLib._pending) >= 1

        # Dispatch idle callbacks
        GLib.dispatch_all()

        # Now toolbar updated to "connected"
        assert toolbar._state == "connected"

    def test_set_agents_dispatched_to_main_thread(self):
        """left_panel.set_agents must be dispatched via GLib.idle_add."""
        left_panel = FakeLeftPanel()
        GLib = FakeGLib()
        handler = make_handler(left_panel=left_panel, GLib_module=GLib)
        handler.connect()

        # Pre-populate agent manager with a snapshot
        handler._gw.set_snapshot({
            "health": {
                "agents": [
                    {"agentId": "qaster", "name": "Qaster",
                     "sessions": {"recent": [{"key": "agent:qaster:1"}]}}
                ]
            }
        })
        handler._gw.simulate_connect()

        # left_panel not updated yet
        assert left_panel._agents == {}
        assert len(GLib._pending) >= 1

        # Dispatch
        GLib.dispatch_all()

        # Now left_panel has agents
        assert "Qaster" in left_panel._agents

    def test_on_connected_calls_sync_callback(self):
        """on_connected() must call _sync_callback if set (for ChatHandler gateway sync)."""
        GLib = FakeGLib()
        sync_calls = []
        def sync_gw(gw):
            sync_calls.append(gw)
        handler = make_handler(GLib_module=GLib)
        handler.connect()
        handler.set_sync_callback(sync_gw)
        handler._gw.simulate_connect()
        GLib.dispatch_all()

        assert len(sync_calls) == 1
        assert sync_calls[0] is handler._gw


# ── Tests: on_error() — GTK thread safety ─────────────────────────────────────

class TestOnError:
    """on_error() fires from gateway thread — GTK calls must use idle_add."""

    def test_disconnected_state_dispatched_via_idle_add(self):
        """Toolbar 'disconnected' update must be via GLib.idle_add."""
        toolbar = FakeToolbar()
        GLib = FakeGLib()
        handler = make_handler(toolbar=toolbar, GLib_module=GLib)
        handler.connect()
        GLib.dispatch_all()  # drain connect's idle callbacks
        toolbar._calls.clear()  # reset

        handler._gw.simulate_error("server closed")

        # Error queued but not yet dispatched
        assert toolbar._state == "connecting"
        assert len(GLib._pending) >= 1

        GLib.dispatch_all()

        assert toolbar._state == "disconnected"


# ── Tests: is_connected() ─────────────────────────────────────────────────────

class TestIsConnected:
    """is_connected() is called by window to check before toggling Connect button."""

    def test_false_before_connect(self):
        handler = make_handler()
        assert handler.is_connected() is False

    def test_true_after_connect(self):
        handler = make_handler()
        handler.connect()
        assert handler.is_connected() is True

    def test_false_after_disconnect(self):
        handler = make_handler()
        handler.connect()
        handler.disconnect()
        assert handler.is_connected() is False


# ── Tests: agent_mgr property ─────────────────────────────────────────────────

class TestAgentMgrProperty:
    """Window needs read access to AgentManager for project membership building."""

    def test_returns_agent_manager_after_connect(self):
        handler = make_handler()
        handler.connect()
        assert handler.agent_mgr is handler._agent_mgr

    def test_returns_none_before_connect(self):
        handler = make_handler()
        assert handler.agent_mgr is None
