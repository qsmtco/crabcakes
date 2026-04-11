# ui/window.py
# Main application window — assembles toolbar, left panel, and main content.
#
# ── Handler Organization ────────────────────────────────────────────────────────
# All callback handlers are defined as private methods on this class.
# They are grouped by subsystem:
#   _setup_keyboard_shortcuts  — keyboard input
#   _on_prompt_selected        — prompt library
#   _on_stt_*                 — speech-to-text
#   _on_improve_*             — moved to MediaHandler (Phase 4)
#   _on_stt_*                 — moved to MediaHandler (Phase 4)
#   _on_project_*             — project tab management
#   GatewayHandler            — owns GatewayClient + AgentManager (Phase 2)
#   ChatHandler               — owns send/fan-out/routing (Phase 1)
#   MediaHandler              — owns STT + improve (Phase 4)
#
# Thread safety: GTK calls from background threads MUST go through GLib.idle_add().
# This applies to: _on_improve_result, _on_stt_partial, gateway callbacks.
# GatewayHandler.dispatch is used internally for its own thread safety.
#
# Project fan-out: _on_send checks if current tab is "project:<name>".
# If so, it calls load_members() and sends to each member independently.
# Responses from agents are routed back to the project tab via _agent_to_project lookup.

import gi
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

# Import UI components
from ui.toolbar import Toolbar
from ui.views.feedbar import FeedBar
from ui.views.left_panel import LeftPanel
from ui.views.main_content import MainContent
from ui.handlers.chat_handler import ChatHandler
from ui.handlers.gateway_handler import GatewayHandler
from ui.handlers.media_handler import MediaHandler


# Gateway URL — WebSocket endpoint for OpenClaw gateway
GATEWAY_URL = "ws://localhost:18789"


class MainWindow(Gtk.ApplicationWindow):
    """Main window for the Crabcakes application."""

    def __init__(self, application):
        super().__init__(application=application, title="Crabcakes")
        self.set_default_size(800, 600)

        # Chat handler — owns message sending, fan-out, and response routing (Phase 1)
        self._chat_handler = None
        # Gateway handler — owns GatewayClient + AgentManager (Phase 2)
        self._gateway_handler = None
        # Media handler — owns STT + improve (Phase 4)
        self._media_handler = None
        # Project fan-out lookup — {session_key: project_name} — initialized early (referenced in _build)
        self._agent_to_project = {}

        self._build()
        self._setup_keyboard_shortcuts()

    def _build(self):
        # Create UI components
        toolbar = Toolbar(on_connect_clicked=self._on_connect_clicked)
        self._toolbar = toolbar

        self._main_content = MainContent()

        # Session switch menu needs AgentManager — set after gateway connects
        self._main_content.set_agent_manager(None)

        # Chat handler — gateway_client is a lambda to avoid stale None reference
        # (self._gw is None at construction, only set when Connect is clicked)
        from gi.repository import GLib
        self._chat_handler = ChatHandler(
            main_content=self._main_content,
            gateway_client=None,  # synced after connect via set_sync_callback
            agent_to_project=self._agent_to_project,
            projects_module=__import__("utils.projects", fromlist=["projects"]),
            GLib_module=GLib,
        )

        # Wire Send button
        self._main_content.send_button.connect("clicked", self._chat_handler.on_send_clicked)

        # Left panel — created BEFORE GatewayHandler
        left_panel = LeftPanel(
            on_prompt_selected=self._on_prompt_selected,
            on_project_selected=self._on_project_selected,
        )
        self._left_panel = left_panel

        # Gateway handler — owns GatewayClient + AgentManager (Phase 2)
        # Note: connect button is wired via Toolbar(on_connect_clicked=...) — not here
        self._gateway_handler = GatewayHandler(
            toolbar=self._toolbar,
            left_panel=left_panel,
            on_agent_selected=self._on_agent_selected,
            on_event=self._on_ws_event,
            GLib_module=GLib,
        )
        # Sync the live GatewayClient reference into ChatHandler after connect
        self._gateway_handler.set_sync_callback(self._sync_gateway_to_chat_handler)
        self._left_panel.set_on_project_opened(self._on_project_opened)
        self._left_panel._file_tree.set_on_project_opened(self._on_project_opened)
        self._left_panel.set_on_project_members_changed(self._on_project_members_changed)
        self._active_project_name = None  # set when a project tab is opened
        self._agent_to_project = {}  # {agent_session_key: project_name} — for routing
        self._projects_module = __import__("utils.projects", fromlist=["projects"])

        # FeedBar — right-side activity strip
        self._feedbar = FeedBar()

        # Media handler — owns STT (whisper.cpp push-to-talk) + improve (Phase 4)
        self._media_handler = MediaHandler(
            main_content=self._main_content,
            improve_module=__import__("utils.improve", fromlist=["improve"]),
            GLib_module=GLib,
        )
        # Voice input: after transcript captured, send it automatically
        self._media_handler.set_on_send_callback(self._chat_handler.on_send)

        # Wire STT + improve buttons
        self._main_content.set_on_stt_click(self._media_handler.on_stt_click)
        self._main_content.set_on_improve_click(self._media_handler.on_improve_click)

        # Right-side vertical stack: feedbar above main content
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_box.append(self._feedbar)
        right_box.append(self._main_content)

        # Horizontal paned split: left panel | right content
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(left_panel)
        paned.set_end_child(right_box)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(True)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_position(250)

        # Vertical layout: toolbar → paned
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(toolbar)
        main_box.append(paned)

        self.set_child(main_box)

    # ── Keyboard shortcuts ───────────────────────────────────────────────────

    def _setup_keyboard_shortcuts(self):
        """Bind Shift+Enter in the input box to send."""
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_input_key_press)
        self._main_content.user_input.add_controller(controller)

    def _on_input_key_press(self, controller, keyval, keycode, state):
        """Shift+Enter sends the message."""
        if keyval == Gdk.KEY_Return and (state & Gdk.ModifierType.SHIFT_MASK):
            self._chat_handler.on_send()
            return True
        return False

    # ── Prompt callback ─────────────────────────────────────────────────────

    def _on_prompt_selected(self, content):
        """Load prompt content into the user input TextView."""
        buffer = self._main_content.user_input.get_buffer()
        buffer.set_text(content)

    # ── STT callbacks ──────────────────────────────────────────────────────

    # ── Project callbacks ───────────────────────────────────────────────────

    def _on_project_selected(self, path):
        """A project file was clicked — placeholder for future file action."""
        pass

    def _on_project_opened(self, name, path):
        """A project was opened — create a chat tab and set active project."""
        self._active_project_name = name
        self._main_content.create_chat_tab(f"project:{name}", f"Project: {name}")
        self._left_panel.refresh_agents_with_project(name)
        # Build agent → project lookup
        for member_key in self._projects_module.load_members(name):
            self._agent_to_project[member_key] = name

    def _on_project_members_changed(self, project_name, members):
        """Membership changed — rebuild the agent → project lookup for this project."""
        # Remove stale entries for this project
        stale = [k for k, v in self._agent_to_project.items() if v == project_name]
        for k in stale:
            del self._agent_to_project[k]
        # Add current members
        for member_key in members:
            self._agent_to_project[member_key] = project_name

    # ── Send button ────────────────────────────────────────────────────────

    # ── Connect button ─────────────────────────────────────────────────────

    # ── Gateway toggle ──────────────────────────────────────────────────────

    def _on_connect_clicked(self, *args):
        """Toggle gateway connection — delegates to GatewayHandler."""
        gh = self._gateway_handler
        if gh.is_connected():
            gh.disconnect()
            self._chat_handler._gw = None
            self._main_content.set_agent_manager(None)
        else:
            gh.connect()

    def _on_ws_event(self, event, payload):
        """Handle incoming gateway events — delegates to ChatHandler for chat events."""
        if event == "chat":
            self._chat_handler.on_chat_event(event, payload)

    def _sync_gateway_to_chat_handler(self, gw):
        """Called by GatewayHandler after connect succeeds — sync live GatewayClient to ChatHandler."""
        self._chat_handler._gw = gw
        self._main_content.set_agent_manager(self._gateway_handler.agent_mgr)

    # ── Agent selection callback ────────────────────────────────────────────

    def _on_agent_selected(self, session_key, agent_name):
        """Called when an agent row is clicked — create/open chat tab."""
        self._main_content.create_chat_tab(session_key, agent_name)
