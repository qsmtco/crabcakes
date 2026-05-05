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
from ui.handlers.activity_handler import ActivityHandler
from ui.handlers.task_handler import TaskHandler
from ui.handlers.collab_handler import CollabHandler
from ui.handlers.session_handler import SessionHandler

from models.command import Command
from models.task import Task
from models import task_store
from datetime import datetime

from utils.config import get_gateway_url, COMMAND_PREFIX


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
        # AgentRuntime handler — owns special agent runtimes (Phase 1.4)
        self._agent_runtime_handler = None
        # Agent-to-project routing table — shared between ProjectHandler (writes) and ChatHandler (reads)
        from models import AgentRoutingTable
        self._agent_to_project = AgentRoutingTable()

        # Task handler — owns task command logic (Phase 7)
        self._task_handler = None
        # Collab handler — owns collaboration command logic (Phase 7)
        self._collab_handler = None
        # Session handler — owns session switching logic (Phase 7)
        self._session_handler = None

        self._build()
        self._setup_keyboard_shortcuts()

    def _build(self):
        """Composition root — all handler and view wiring lives here.

        This method is intentionally dense. It is the single place where
        all components are instantiated and connected. New handlers receive
        their dependencies here. See ARCHITECTURE.md §3.6 for the pattern.
        """
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
        self._chat_render_handler.set_main_content(self._main_content)

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
        self._left_panel.set_main_content(self._main_content)

        # Agent card handler — agent_mgr set in _sync_gateway_to_chat_handler after connect
        from ui.handlers.agent_list_handler import AgentListHandler
        self._agent_list_handler = AgentListHandler(
            agent_mgr=None,
            on_agent_chat=lambda sk, n: self._on_agent_selected(sk, n),
            on_agent_toggle=None,  # left_panel._on_agent_toggle_clicked handles membership directly
        )
        self._left_panel.set_agent_list_handler(self._agent_list_handler)

        # AgentRuntime handler — owns AgentRuntime instances for special agents (Phase 1.4)
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        self._agent_runtime_handler = AgentRuntimeHandler(
            main_content=self._main_content,
            chat_render_handler=self._chat_render_handler,
            GLib_module=GLib,
            review_handler=None,  # ReviewHandler created later in _build; Phase 1.5 will wire via setter
        )

        # Register built-in special agents from the registry
        from agent.special_agents import get_special_agents
        for agent_def in get_special_agents():
            self._agent_runtime_handler.add_special_agent(agent_def.display_name, agent_def.conv_id_prefix)

        # Inject into dependents after _agent_runtime_handler is assigned
        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        self._left_panel.set_special_agents(self._agent_runtime_handler)


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

        # Activity handler — owns the Response Status state machine (Phase 6)
        self._activity_handler = ActivityHandler(
            feedbar=self._response_status,
            main_content=self._main_content,
            GLib_module=GLib,
        )

        # Media handler — owns STT (whisper.cpp push-to-talk) + improve (Phase 4)
        self._media_handler = MediaHandler(
            main_content=self._main_content,
            improve_module=__import__("utils.improve", fromlist=["improve"]),
            GLib_module=GLib,
        )

        # Project handler — owns active project state + agent-to-project routing (Phase 3)
        from ui.handlers.project_handler import ProjectHandler
        self._projects = __import__("utils.projects", fromlist=["projects"])
        self._awareness = __import__("utils.project_awareness", fromlist=["project_awareness"])
        self._project_handler = ProjectHandler(
            left_panel=self._left_panel,
            projects_module=self._projects,
            agent_to_project=self._agent_to_project,  # shared AgentRoutingTable — ProjectHandler writes, ChatHandler reads
            GLib_module=GLib,
            awareness_module=self._awareness,
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
        left_panel._file_tree.set_on_create_project(
            lambda name: self._project_handler.create_project(name, pm_name="Captain", pm_id="cli")
        )
        self._left_panel.set_toggle_agent_callback(self._project_handler.toggle_agent)

        # Wire MainContent → ProjectHandler (for right-click project tab menu)
        self._main_content.set_project_handler(self._project_handler)
        self._chat_handler.set_project_handler(self._project_handler)

        # Wire feed bar — updates when project opens or members change
        self._main_content.set_on_project_settings_update(self._on_feed_bar_update)

        # ── Feed handler + feed tab (Phase 2) ────────────────────────────────
        # ── Feed handler + feed tab (Phase 2 — Project Feed) ─────────────────────
        #
        # Architecture: LeftPanel Projects tab owns the FeedTab view (created once).
        # FeedHandler manages card state. FeedHandler is told about FeedTab via set_feed_tab().
        # window wires project lifecycle → LeftPanel ↔ FeedHandler coordination.
        #
        # Order: FeedHandler → CrabWatch → FeedTab → wire callbacks

        from ui.handlers.feed_handler import FeedHandler

        def _on_populate_input(text: str):
            """Fill the user input box with review prompt text."""
            buf = self._main_content.user_input.get_buffer()
            buf.set_text("")
            buf.set_text(text)
            end_iter = buf.get_end_iter()
            buf.place_cursor(end_iter)
            self._main_content.user_input.grab_focus()

        def _on_send_to_agent(session_key: str, text: str):
            """Send a message to an agent tab (used for rejection notifications)."""
            self._chat_handler.send_raw_message(session_key, text)

        def _on_show_feed_subtab():
            """Switch Projects notebook to the Feed sub-tab."""
            self._left_panel.switch_to_feed_tab()

        # FeedHandler created before FeedTab — set_feed_tab() called after FeedTab exists
        self._feed_handler = FeedHandler(
            GLib=GLib,
            on_populate_input=_on_populate_input,
            on_send_to_agent=_on_send_to_agent,
            on_tab_switch=_on_show_feed_subtab,
            get_chat_box_for_session=self._main_content.get_chat_box_for_session,
        )

        # CrabWatch — filesystem watcher for project feed
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        self._crabwatch_handler = CrabWatchHandler(
            GLib_module=GLib,
            on_event=self._feed_handler.on_filesystem_event,
        )

        # FeedTab created here (once) — inject into LeftPanel's Projects "Feed" sub-tab
        from ui.views.feed_tab import FeedTab
        self._feed_tab = FeedTab()

        # Tell FeedHandler about the FeedTab (FeedHandler needs it to add/remove cards)
        self._feed_handler.set_feed_tab(self._feed_tab)

        # Inject FeedTab into LeftPanel's Projects notebook "Feed" sub-tab
        self._left_panel.set_feed_tab(self._feed_tab)

        # Wire ChatRenderHandler → FeedHandler (crabcard interception)
        def _on_crabcards_extracted(cards: list, session_key: str, tab_key: str = ""):
            from ui.views.chat_bubble import _set_crabcards_registry
            _set_crabcards_registry(cards, _on_show_feed_subtab)
            for card in cards:
                card.metadata["session_key"] = session_key  # agent's gateway key
                card.metadata["tab_key"] = tab_key or session_key  # chat box key (project:xxx or agent:xxx)
                self._feed_handler.add_card(card)

        self._chat_render_handler.set_on_crabcard_extracted(_on_crabcards_extracted)
        self._chat_render_handler.set_project_name("")  # set per-project when project opens

        # ── Wire project lifecycle → FeedHandler + CrabWatch ──────────────────────────
        #
        # When project OPENS:
        #   1. FeedHandler loads feed.json for the project
        #   2. CrabWatch starts watching the project directory
        #   3. ChatRenderHandler gets the project name for crabcard context
        #   4. Feed bar is updated
        #
        # When project CLOSES:
        #   1. FeedHandler clears its state for the project
        #   2. CrabWatch stops watching
        #   3. Feed bar is cleared

        self._project_handler.set_on_project_opened(
            lambda n, p: (
                self._main_content.create_chat_tab(f"project:{n}", f"Project: {n}"),
                self._left_panel.open_project_view(self._feed_tab),
                self._feed_handler.on_project_opened(n, p),
                self._crabwatch_handler.start_watching(p, n),
                self._chat_render_handler.set_project_name(n),
                self._on_feed_bar_update(n, len(self._project_handler.get_project_members(n)) if n else 0),
            )
        )
        self._project_handler.set_on_project_closed(
            lambda name: (
                self._feed_handler.on_project_closed(name),
                self._crabwatch_handler.stop_watching(),
                self._chat_render_handler.set_project_name(""),
                self._on_feed_bar_update(None, 0),
            )
        )
        self._project_handler.set_on_members_changed(
            lambda n, m: self._on_feed_bar_update(n, len(m))
        )
        # ── End Feed handler ──────────────────────────────────────────────
        # Task handler — task commands (Phase 7)
        self._task_handler = TaskHandler(
            on_display_card=self._on_command_card,
            on_display_text=self._on_command_text,
            on_feed_card=self._feed_handler.add_card,
        )
        # Collab handler — collaboration commands (Phase 7)
        self._collab_handler = CollabHandler()
        # Session handler — session switching (Phase 7)
        # Needs AgentManager and ProjectHandler injected via setters after connect
        self._session_handler = SessionHandler(
            agent_manager=None,   # synced in _sync_gateway_to_chat_handler
            project_handler=self._project_handler,
        )

        # Command handler — owns backtick command parsing + routing (Phase 0.2)
        # Created AFTER ProjectHandler is initialized so project_handler reference is valid.
        from ui.handlers.command_handler import CommandHandler
        self._command_handler = CommandHandler(
            gateway_client=None,   # synced after connect via _sync_gateway_to_chat_handler
            agent_manager=None,    # synced after connect via _sync_gateway_to_chat_handler
            project_handler=self._project_handler,
            GLib_module=GLib,
            on_display_card=self._on_command_card,
            on_display_text=self._on_command_text,
        )
        self._command_handler.set_prefix(COMMAND_PREFIX)   # BUG #9 fix: read prefix from config
        # Inject CommandHandler into ChatHandler (ChatHandler calls process_input before send)
        self._chat_handler.set_command_handler(self._command_handler)

        # Review handler — owns review session lifecycle (Phase 3)
        from ui.handlers.review_handler import ReviewHandler
        self._review_handler = ReviewHandler(
            GLib=GLib,
            main_content=self._main_content,
            project_handler=self._project_handler,
            on_review_started=self._on_review_started,
            on_review_ended=self._on_review_ended,
            on_display_card=self._on_command_card,
            on_display_text=self._on_command_text,
        )
        # Wire ReviewHandler into AgentRuntimeHandler (deferred to avoid circular dep in _build order)
        self._agent_runtime_handler.set_review_handler(self._review_handler)
        # Wire project lifecycle → ReviewHandler
        self._project_handler.set_on_project_opened(
            lambda n, p: (self._review_handler.on_project_opened(n, p))
        )
        self._project_handler.set_on_project_closed(
            lambda name: (self._review_handler.on_project_closed(name))
        )

        # Register all commands — must be after _review_handler is created (Phase 7)
        self._register_stub_commands()

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

    # ── Command handlers (Step 0.3) ────────────────────────────────────────

    def _on_command_text(self, session_key: str, text: str):
        """Display a command response text bubble in the current tab.

        Called by CommandHandler via on_display_text callback when a command
        returns response_text (e.g. error messages, help output).
        """
        chat_box = self._main_content.get_chat_box()
        if chat_box is None:
            return
        bubble = self._chat_render_handler.render_sync("CrabCakes", text, session_key)
        if bubble is not None:
            chat_box.append(bubble)
            self._main_content.scroll_chat_to_bottom()


    # ── Review callbacks (owned by ReviewHandler) ──────────────────────────────

    def _on_review_started(self, project_name: str, bar) -> None:
        """Called by ReviewHandler when a review session starts. Stub — no-op."""

    def _on_review_ended(self, project_name: str) -> None:
        """Called by ReviewHandler when a review session ends. Stub — no-op."""

    def _on_command_card(self, card: dict):
        """Render a command result card in the current tab.

        Called by CommandHandler via on_display_card callback when a command
        returns response_card (e.g. task card, status card).
        """
        # card = {type, ...fields} — rendered as a special bubble
        session_key = self._main_content.get_current_session_key() or ""
        chat_box = self._main_content.get_chat_box()
        if chat_box is None or self._chat_render_handler is None:
            return
        self._chat_render_handler.render_event_card(card["type"], chat_box, **card)
        self._main_content.scroll_chat_to_bottom()

    def _register_stub_commands(self):
            """Wire all commands to their handler methods (Phase 7)."""
            # Collaboration — CollabHandler
            ch = self._collab_handler
            self._command_handler.register_command("ask", ch.cmd_ask, aliases=["a"],
                help_text="Ask an agent a question: `ask @agent — question")
            self._command_handler.register_command("delegate", ch.cmd_delegate, aliases=["d"],
                help_text="PM delegates to agent: `delegate @agent — task")
            self._command_handler.register_command("stop", ch.cmd_stop,
                help_text="PM stops the current collaboration: `stop @agent")
            self._command_handler.register_command("tell", ch.cmd_tell,
                help_text="One agent shares information with another: `tell @agent — info")
            # Task — TaskHandler
            th = self._task_handler
            self._command_handler.register_command("task", th.cmd_task, aliases=["t"],
                help_text="Create a task card assigned to agent")
            self._command_handler.register_command("done", th.cmd_done,
                help_text="Mark task complete")
            self._command_handler.register_command("start", th.cmd_start,
                help_text="Start working on a task")
            self._command_handler.register_command("blocked", th.cmd_blocked,
                help_text="Report a blocker on a task")
            self._command_handler.register_command("cancel", th.cmd_cancel,
                help_text="Cancel a task")
            self._command_handler.register_command("tasks", th.cmd_tasks,
                help_text="Show all tasks")
            self._command_handler.register_command("assign", th.cmd_assign,
                help_text="Reassign a task to a different agent")
            self._command_handler.register_command("priority", th.cmd_priority,
                help_text="Set task priority")
            # Review — ReviewHandler
            rh = self._review_handler
            self._command_handler.register_command("review", rh.cmd_review,
                help_text="Start a review checkpoint")
            self._command_handler.register_command("check", rh.cmd_check,
                help_text="Show diff of changes since checkpoint")
            self._command_handler.register_command("accept", rh.cmd_accept,
                help_text="Accept all changes (or single file)")
            self._command_handler.register_command("reject", rh.cmd_reject,
                help_text="Reject all pending changes")
            # Project — ProjectHandler
            ph = self._project_handler
            self._command_handler.register_command("status", ph.cmd_status, aliases=["s"],
                help_text="Project status summary")
            self._command_handler.register_command("agents", ph.cmd_agents,
                help_text="List project agents and current state")
            self._command_handler.register_command("cost", ph.cmd_cost,
                help_text="Spending summary for this project")
            # Utility — SessionHandler + CommandHandler
            sh = self._session_handler
            self._command_handler.register_command("help", self._command_handler.cmd_help, aliases=["?"],
                help_text="List all commands or help for a specific command")
            self._command_handler.register_command("session", sh.cmd_session, aliases=["s"],
                help_text="Switch agent session in project: `session list @agent | `session <ref> @agent")
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
        """
        Close a project: return Projects tab in LeftPanel to picker view.

        Does: switch Projects tab back to picker, reset project state, clear feed bar.
        """
        # 1. Reset project state (clears _active_project_name, fires on_project_closed callbacks)
        self._project_handler.close_project(name)
        # 2. Reparent FileTree back to Stack picker, destroy nested Notebook
        self._left_panel.close_project_view()
        # 3. Clear the feed bar
        self._on_feed_bar_update(None, 0)

    def _on_file_tree_navigate_back(self, project_name):
        """← back button in FileTree — close project view in LeftPanel."""
        if project_name:
            self._close_project_tab(project_name)

    def _on_feed_bar_update(self, project_name: str, member_count: int):
        """Update the project settings bar with project name + member count."""
        self._main_content._update_project_settings_from_project(project_name, member_count)

    def _on_ws_event(self, event, payload):
        """Handle incoming gateway events — route to handlers.

        All events go to ActivityHandler for progress tracking. Chat events also
        go to ChatHandler for bubble rendering (separate responsibility).
        """
        self._activity_handler.on_gateway_event(event, payload)
        if event == "chat":
            self._chat_handler.on_chat_event(event, payload)

    def _sync_gateway_to_chat_handler(self, gw):
        """Sync the live GatewayClient into ChatHandler after connect succeeds.

        Called by GatewayHandler via set_sync_callback() after on_connected() dispatches.
        GatewayClient is not available at window construction time (gateway isn't running yet),
        so we defer the reference injection until after the WebSocket handshake completes.
        This is the only place where ChatHandler._gw gets set — it's write-once after connect.
        """
        self._chat_handler.set_gateway_client(gw)
        self._main_content.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire AgentListHandler to the live AgentManager
        self._agent_list_handler.set_agent_mgr(self._gateway_handler.agent_mgr)
        # Refresh agents list for the currently open project — fixes members not
        # appearing after gateway reconnect (session keys change on reconnect)
        if self._project_handler.get_active_project_name():
            self._left_panel.refresh_agents_with_project(
                self._project_handler.get_active_project_name()
            )
        # Wire CommandHandler with live references after connect
        self._command_handler.set_gateway_client(gw)
        self._command_handler.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire ProjectHandler with live AgentManager for session lookup
        self._project_handler.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire ProjectHandler → ReviewHandler for cmd_status review state queries
        self._project_handler.set_review_handler(self._review_handler)
        # Wire SessionHandler with live AgentManager for session lookups
        self._session_handler.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire ChatHandler with AgentManager for display name resolution
        self._chat_handler.set_agent_manager(self._gateway_handler.agent_mgr)
        # Wire forward button callback
        self._chat_handler.set_on_forward_message(self._on_forward_clicked)
        # Wire send-initiated → ActivityHandler pre-flight state
        self._chat_handler.set_on_send_initiated(self._activity_handler.on_send_initiated)
        # Wire res confirmation → ActivityHandler pre-flight end
        self._chat_handler.set_on_res_confirmed(self._activity_handler.on_res_confirmed)

    # ── Agent selection callback ────────────────────────────────────────────

    def _on_agent_selected(self, session_key, agent_name):
        """Called when an agent row is clicked — create/open chat tab."""
        self._main_content.create_chat_tab(session_key, agent_name)

    # ── Forward message ────────────────────────────────────────────────────

    def _on_forward_clicked(self, text, anchor_widget, source_session_key=None):
        """Show a popover listing all other agents to forward text to."""
        if self._gateway_handler is None:
            return
        agent_mgr = self._gateway_handler.agent_mgr
        if agent_mgr is None:
            return

        # Collect other agent sessions (exclude the source agent)
        source_name = agent_mgr.get_name(source_session_key) if source_session_key else None
        other_sessions = []
        for page_idx, sk in self._main_content._tab_sessions.items():
            name = agent_mgr.get_name(sk)
            if name and (source_session_key is None or sk != source_session_key):
                other_sessions.append((sk, name))

        popover = Gtk.Popover()
        popover.set_parent(anchor_widget)
        popover.set_position(Gtk.PositionType.TOP)

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_box.set_margin_start(8)
        menu_box.set_margin_end(8)
        menu_box.set_margin_top(4)
        menu_box.set_margin_bottom(4)

        for sk, name in other_sessions:
            btn = Gtk.Button(label=f"→ {name}")
            btn.add_css_class("flat")
            btn.set_has_frame(False)
            btn.connect("clicked", lambda _b, s=sk, t=text, ss=source_session_key, pop=popover: self._forward_to_agent(s, t, ss, pop))
            menu_box.append(btn)

        if not other_sessions:
            lbl = Gtk.Label(label="No other agents connected")
            lbl.add_css_class("dim-label")
            menu_box.append(lbl)

        popover.set_child(menu_box)
        popover.popup()

    def _forward_to_agent(self, target_session_key, text, source_session_key, popover):
        """Send forwarded text to target agent and show it in their tab."""
        popover.popdown()
        if not text:
            return
        gw = self._gateway_handler._gw if self._gateway_handler else None
        if gw is None or not gw.is_connected():
            return
        gw.send_message(target_session_key, text)

        # Look up source agent name for the forwarded-from header
        agent_mgr = self._gateway_handler.agent_mgr
        source_name = agent_mgr.get_name(source_session_key) if agent_mgr and source_session_key else None

        # Check if target agent already has an open tab
        target_tab_exists = None
        for page_idx, sk in self._main_content._tab_sessions.items():
            if sk == target_session_key:
                target_tab_exists = page_idx
                break

        if target_tab_exists is None:
            # No tab for target agent yet — create one
            target_name = agent_mgr.get_name(target_session_key) if agent_mgr else "Agent"
            target_tab_exists = self._main_content.create_chat_tab(target_session_key, target_name)
        else:
            self._main_content._chat_notebook.set_current_page(target_tab_exists)

        # Append forwarded bubble to the target tab
        chat_box = self._main_content.get_chat_box(target_tab_exists)
        if chat_box is not None and self._chat_render_handler is not None:
            bubble = self._chat_render_handler.render_sync(
                "You", text, target_session_key,
                on_forward_click=self._chat_render_handler._on_forward_message,
                forwarded_from=source_name,
                agent_name="You",
            )
            if bubble is not None:
                chat_box.append(bubble)
                # Defer scroll to ensure GTK has laid out the new bubble first
                from gi.repository import GLib
                GLib.timeout_add(16, lambda: (self._main_content.scroll_chat_to_bottom(target_tab_exists), False)[1])
