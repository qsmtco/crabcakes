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
from ui.handlers.project_handler import ProjectHandler


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
        # Chat render handler — owns text→bubble pipeline (Phase 2 refactor)
        # Created here and injected into both MainContent and ChatHandler so neither
        # instantiates it directly. window.py is the composition root.
        from gi.repository import GLib
        from ui.handlers.chat_render_handler import ChatRenderHandler
        self._chat_render_handler = ChatRenderHandler(GLib_module=GLib)

        # Create UI components
        toolbar = Toolbar(on_connect_clicked=self._on_connect_clicked)
        self._toolbar = toolbar

        self._main_content = MainContent()

        # Session switch menu needs AgentManager — set after gateway connects
        self._main_content.set_agent_manager(None)
        self._main_content.set_chat_render_handler(self._chat_render_handler)

        # Chat handler — gateway_client is a lambda to avoid stale None reference
        # (self._gw is None at construction, only set when Connect is clicked)
        self._chat_handler = ChatHandler(
            main_content=self._main_content,
            gateway_client=None,  # synced after connect via set_sync_callback
            agent_to_project=self._agent_to_project,
            projects_module=__import__("utils.projects", fromlist=["projects"]),
            GLib_module=GLib,
        )

        # Inject ChatRenderHandler into ChatHandler (window.py is composition root)
        self._chat_handler.set_chat_render_handler(self._chat_render_handler)

        # Wire Send button
        self._main_content.send_button.connect("clicked", self._chat_handler.on_send_clicked)

        # Left panel — created BEFORE GatewayHandler
        left_panel = LeftPanel(
            on_prompt_selected=self._on_prompt_selected,
            on_project_selected=self._on_project_selected,
        )
        self._left_panel = left_panel

        # Agent card handler — agent_mgr set in _sync_gateway_to_chat_handler after connect
        from ui.handlers.agent_list_handler import AgentListHandler
        self._agent_list_handler = AgentListHandler(
            agent_mgr=None,
            on_agent_chat=lambda sk, n: self._on_agent_selected(sk, n),
            on_agent_toggle=None,  # left_panel._on_agent_toggle_clicked handles membership directly
        )
        self._left_panel.set_agent_list_handler(self._agent_list_handler)

        # Prompts handler — wired to left_panel after both are created
        from ui.handlers.prompts_handler import PromptsHandler
        self._prompts_handler = PromptsHandler(
            on_refresh_ui=lambda: self._left_panel.refresh_prompts(),
            on_prompt_loaded=lambda fp, name, content: self._on_prompt_selected(content),
        )
        self._left_panel.set_prompts_handler(self._prompts_handler)

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

        # # Response Status bar (right side)
        self._response_status = FeedBar()

        # Media handler — owns STT (whisper.cpp push-to-talk) + improve (Phase 4)
        self._media_handler = MediaHandler(
            main_content=self._main_content,
            improve_module=__import__("utils.improve", fromlist=["improve"]),
            GLib_module=GLib,
        )

        # Project handler — owns active project state + agent-to-project routing (Phase 3)
        from ui.handlers.project_handler import ProjectHandler
        self._projects = __import__("utils.projects", fromlist=["projects"])
        self._project_handler = ProjectHandler(
            main_content=self._main_content,
            left_panel=self._left_panel,
            projects_module=self._projects,
            agent_to_project=self._agent_to_project,  # shared with ChatHandler — the ONE true dict
            GLib_module=GLib,
        )
        # Wire left_panel project events → ProjectHandler
        # Project list handler — provides project cards with colors and data
        from ui.handlers.project_list_handler import ProjectListHandler
        self._project_list_handler = ProjectListHandler(
            on_project_opened=self._project_handler.open_project,
        )
        left_panel._file_tree.set_project_list_handler(self._project_list_handler)
        left_panel._file_tree.set_on_navigate_back(self._on_file_tree_navigate_back)
        left_panel._file_tree.set_on_project_opened(self._project_handler.open_project)
        self._left_panel.set_toggle_agent_callback(self._project_handler.toggle_agent)

        # Wire feed bar — updates when project opens or members change
        self._main_content.set_on_project_tab_close(self._on_tab_close)
        self._main_content.set_on_project_settings_update(self._on_feed_bar_update)
        self._project_handler.set_on_project_opened(lambda n, p: self._on_feed_bar_update(n, len(self._projects.load_members(n)) if n else 0))
        self._project_handler.set_on_members_changed(lambda n, m: self._on_feed_bar_update(n, len(m)))

        # Wire STT + improve buttons
        self._main_content.set_on_stt_click(self._media_handler.on_stt_click)
        self._main_content.set_on_improve_click(self._media_handler.on_improve_click)

        # Right-side vertical stack: feedbar above main content
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_box.append(self._response_status)
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
        """Insert prompt content into the user input TextView at cursor position."""
        buffer = self._main_content.user_input.get_buffer()
        cursor_iter = buffer.get_iter_at_mark(buffer.get_insert())
        buffer.insert(cursor_iter, content)

    def _on_project_selected(self, path):
        """Handle file tree selection — no-op; project card clicks route via ProjectHandler."""
        pass

    # ── Gateway toggle ──────────────────────────────────────────────────────

    def _on_connect_clicked(self, *args):
        """Toggle gateway connection — delegates to GatewayHandler."""
        gh = self._gateway_handler
        if gh.is_connected():
            gh.disconnect()
            self._chat_handler.set_gateway_client(None)
            self._main_content.set_agent_manager(None)
        else:
            gh.connect()

    def _close_project_tab(self, name: str):
        """Close a project tab and reset all state. Called by both × and < paths.

        Does: close notebook tab, navigate file_tree back, reset agents +/-, clear feed bar.
        """
        # 1. Close the tab in the notebook
        session_key = f"project:{name}"
        page_idx = self._main_content._find_page_by_session(session_key)
        if page_idx is not None:
            self._main_content._close_tab(page_idx)
        # 2. Navigate back to the project card picker in left_panel
        self._left_panel._file_tree.navigate_back()
        # 3. Reset project state (clears _active_project_name, refreshes +/− buttons)
        self._project_handler.close_project(name)
        # 4. Clear the feed bar
        self._on_feed_bar_update(None, 0)

    def _on_file_tree_navigate_back(self, project_name):
        """← back button in FileTree — close project tab (delegates to shared method)."""
        if project_name:
            self._close_project_tab(project_name)

    def _on_tab_close(self, session_key: str):
        """× clicked on a project tab — close project tab."""
        project_name = session_key.replace("project:", "")
        self._close_project_tab(project_name)

    def _on_feed_bar_update(self, project_name: str, member_count: int):
        """Update the project settings bar with project name + member count."""
        self._main_content._update_project_settings_from_project(project_name, member_count)

    def _on_ws_event(self, event, payload):
        """Handle incoming gateway events — delegates to ChatHandler for chat events."""
        if event == "chat":
            self._chat_handler.on_chat_event(event, payload)

    def _sync_gateway_to_chat_handler(self, gw):
        """Called by GatewayHandler after connect succeeds — sync live GatewayClient to ChatHandler."""
        self._chat_handler.set_gateway_client(gw)
        self._main_content.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire AgentListHandler to the live AgentManager
        self._agent_list_handler.set_agent_mgr(self._gateway_handler.agent_mgr)

    # ── Agent selection callback ────────────────────────────────────────────

    def _on_agent_selected(self, session_key, agent_name):
        """Called when an agent row is clicked — create/open chat tab."""
        self._main_content.create_chat_tab(session_key, agent_name)
