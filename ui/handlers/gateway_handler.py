# ui/handlers/gateway_handler.py
# Gateway handler — extracted from window.py Phase 2.
#
# Owns: GatewayClient instance, AgentManager instance, connection lifecycle.
# Does NOT own: ChatHandler, MainContent, LeftPanel callbacks beyond set_agents.
#
# Thread safety: on_connected() and on_error() are called from the gateway's
# background thread. All GTK operations (toolbar state, left_panel.set_agents)
# are dispatched via GLib.idle_add(). Never call GTK directly from these callbacks.
#
# Gateway sync: After connect(), ChatHandler needs the live GatewayClient reference
# to send messages. Window calls set_sync_callback(fn) with a function that updates
# ChatHandler._gw. The handler calls this function from on_connected() via idle_add.

from typing import Callable


class GatewayHandler:
    """
    Handles gateway connection lifecycle and agent discovery.

    Owns: GatewayClient instance, AgentManager instance.
    Receives: Toolbar (for connection state), LeftPanel (for set_agents),
              on_agent_selected callback, GLib module (for thread-safe GTK dispatch).

    Thread safety: all GTK operations in on_connected() and on_error() are
    dispatched via GLib.idle_add().

    Args:
        toolbar:                Toolbar instance — for update_connection_state()
        left_panel:             LeftPanel instance — for set_agents() after connect
        on_agent_selected:      Callable — window's agent click handler
        GLib_module:            gi.repository.GLib or None — for thread-safe GTK calls
        gateway_client_class:   GatewayClient class — injectable for tests
        agent_manager_class:    AgentManager class — injectable for tests
    """

    def __init__(
        self,
        toolbar,
        left_panel,
        on_agent_selected: Callable,
        on_event: Callable[[str, dict], None],
        GLib_module=None,
        gateway_client_class=None,
        agent_manager_class=None,
    ):
        from gateway import GatewayClient
        from models import AgentManager

        self._toolbar = toolbar
        self._left_panel = left_panel
        self._on_agent_selected = on_agent_selected
        self._on_event = on_event  # window's event handler (e.g. ChatHandler routing)
        self._GLib = GLib_module

        self._gw_class = gateway_client_class or GatewayClient
        self._am_class = agent_manager_class or AgentManager

        self._gw: object = None
        self._agent_mgr: object = None
        self._sync_callback: Callable = None  # set by window to sync gw to ChatHandler

    # ── Public API ───────────────────────────────────────────────────────────

    def connect(self):
        """
        Create GatewayClient and AgentManager, connect to the gateway.
        Calls on_connected() via the gateway thread when connection succeeds.
        """
        # Stop any existing client first
        if self._gw is not None:
            self._gw.stop()

        self._agent_mgr = self._am_class()

        # Update toolbar to "connecting" immediately (this is from GTK thread, no idle_add needed)
        self._toolbar.update_connection_state("connecting")

        self._gw = self._gw_class(
            url="ws://localhost:18789",
            on_connect=self.on_connected,
            on_error=self.on_error,
            on_event=self._on_event_stub,
        )
        self._gw.start()

    def disconnect(self):
        """Stop the gateway client and reset state."""
        if self._gw is not None:
            self._gw.stop()
            self._gw = None

        if self._agent_mgr is not None:
            self._agent_mgr.clear()
            self._agent_mgr = None

        self._dispatch(lambda: self._toolbar.update_connection_state("disconnected"))

    def is_connected(self) -> bool:
        """Returns True if the gateway client is connected."""
        return self._gw is not None and self._gw.is_connected()

    @property
    def agent_mgr(self):
        """Read-only access to AgentManager — used by window for project membership."""
        return self._agent_mgr

    def set_sync_callback(self, fn: Callable):
        """
        Set a callback to sync the live GatewayClient to other handlers.
        Called after on_connected() dispatches, with the live gateway instance.
        Window uses this to keep ChatHandler._gw in sync.
        """
        self._sync_callback = fn

    # ── Gateway thread callbacks — MUST use idle_add for GTK ─────────────────

    def on_connected(self):
        """
        Handle successful gateway connection.
        ⚠️ Called from gateway background thread — all GTK calls need idle_add.
        """
        from models import reset_color_indices

        if self._agent_mgr is not None:
            self._agent_mgr.clear()
        reset_color_indices()

        # Dispatch GTK operations to main thread
        def _do_connect():
            self._toolbar.update_connection_state("connected")

            # Populate agent manager from snapshot
            snapshot = self._gw.get_snapshot() if self._gw else None
            agents = snapshot.get("health", {}).get("agents", []) if snapshot else []

            if self._agent_mgr is not None:
                for agent in agents:
                    agent_id = agent.get("agentId", "main")
                    name = agent.get("name") or agent_id
                    recent = agent.get("sessions", {}).get("recent", [])
                    for entry in recent:
                        session_key = entry.get("key", "")
                        if session_key:
                            self._agent_mgr.register(session_key, name)

            # Tell window to build the agents list in the sidebar
            self._left_panel.set_agents(
                self._agent_mgr.get_names_ref() if self._agent_mgr else {},
                self._on_agent_selected,
            )

            # Sync live gateway to ChatHandler (via window's callback)
            if self._sync_callback is not None:
                self._sync_callback(self._gw)

        self._dispatch(_do_connect)

    def on_error(self, err_msg: str):
        """
        Handle gateway connection error.
        ⚠️ Called from gateway background thread — all GTK calls need idle_add.
        """
        def _do_error():
            self._toolbar.update_connection_state("disconnected")

        self._dispatch(_do_error)

    def _on_event_stub(self, event: str, payload: dict):
        """
        Forward gateway events to the window's event handler.
        Chat events are routed via window._on_ws_event → ChatHandler.
        """
        if self._on_event is not None:
            self._on_event(event, payload)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _dispatch(self, fn: Callable):
        """Call fn on the GTK main thread. Direct call if GLib not available."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False  # remove idle source after one execution
            self._GLib.idle_add(_wrap)
        else:
            fn()
