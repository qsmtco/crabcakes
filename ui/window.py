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

import logging

import gi

logger = logging.getLogger(__name__)
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

# Import UI components
from ui.toolbar import Toolbar
from ui.views.feedbar import FeedBar
from ui.views.left_panel import LeftPanel
from ui.views.main_content import MainContent
from ui.views.activity_drawer import ActivityDrawer
from ui.handlers.chat_handler import ChatHandler
from ui.handlers.gateway_handler import GatewayHandler
from ui.handlers.media_handler import MediaHandler
from ui.handlers.project_handler import ProjectHandler
from ui.handlers.activity_handler import ActivityHandler
from ui.handlers.task_handler import TaskHandler
from ui.handlers.collab_handler import CollabHandler
from ui.handlers.session_handler import SessionHandler


from models.task import Task
from models import task_store
from datetime import datetime

from utils.config import get_gateway_url, COMMAND_PREFIX


class MainWindow(Gtk.ApplicationWindow):
    """Main window for the Crabcakes application."""

    def __init__(self, application):
        super().__init__(application=application, title="Crabcakes")
        self.set_default_size(800, 600)

        # Connect realize signal — set_icon_list requires a valid surface
        self.connect("realize", self._on_realize)

        # Chat handler — owns message sending, fan-out, and response routing (Phase 1)
        self._chat_handler = None
        # Gateway handler — owns GatewayClient + AgentManager (Phase 2)
        self._gateway_handler = None
        # Media handler — owns STT + improve (Phase 4)
        self._media_handler = None
        # Input toolbar handler — owns find/replace, spell check, file I/O (Phase 5)
        self._input_toolbar_handler = None
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
        # Connection sync handler — owns post-connect wiring (Phase 3a extraction)
        self._connection_sync_handler = None
        # Forward handler — owns agent-to-agent message forwarding (Phase 3b extraction)
        self._forward_handler = None

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
        toolbar = Toolbar(
            on_connect_clicked=self._on_connect_clicked,
            on_settings_clicked=self._open_settings,
        )
        self._toolbar = toolbar
        self._toolbar.update_connection_state("offline")

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

        # Agent card handler — agent_mgr set in ConnectionSyncHandler.sync() after connect
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
        from agent.special_agents import get_special_agents, get_auto_open_agents
        for agent_def in get_special_agents():
            self._agent_runtime_handler.add_special_agent(agent_def)

        # Phase 4 — Auto-open Crabcakes tab on every launch.
        # Creates a tab for each agent with auto_open=True and sets a
        # synthetic project for agents with api_key_built_in=True so they
        # have a project context (file context, awareness, etc.).
        auto_open_agents = get_auto_open_agents()
        if auto_open_agents:
            from pathlib import Path
            app_path = str(Path(__file__).resolve().parent.parent)
            for agent_def in auto_open_agents:
                self._main_content.create_chat_tab(
                    agent_def.conv_id_prefix, agent_def.display_name
                )
                if agent_def.api_key_built_in:
                    self._agent_runtime_handler.set_active_project(
                        agent_def.display_name, app_path
                    )
                    break  # Only set synthetic project once
                logger.info(
                    "Auto-opened agent tab: %s (built_in=%s)",
                    agent_def.display_name, agent_def.api_key_built_in,
                )

        # Inject into dependents after _agent_runtime_handler is assigned
        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        self._left_panel.set_special_agents(self._agent_runtime_handler)
        self._main_content.set_agent_runtime_handler(self._agent_runtime_handler)

        # Agent builder handler — manages create/edit/delete for user-defined agents
        from ui.handlers.agent_builder_handler import AgentBuilderHandler
        self._agent_builder_handler = AgentBuilderHandler(
            GLib_module=GLib,
            parent_window=self,
            on_agent_saved=lambda name: self._agent_runtime_handler.reload_agents_and_mcp(
                on_complete=lambda: self._left_panel.set_special_agents(self._agent_runtime_handler)
            ),
            on_agent_deleted=lambda name: self._agent_runtime_handler.reload_agents_and_mcp(
                on_complete=lambda: self._left_panel.set_special_agents(self._agent_runtime_handler)
            ),
        )

        # Wire left panel agent builder callbacks
        self._left_panel.set_on_create_agent(lambda: self._open_agent_builder())
        self._left_panel.set_on_edit_agent(lambda name: self._open_agent_builder(name))
        self._left_panel.set_on_delete_agent(lambda name: self._agent_builder_handler.delete_agent_with_confirmation(name))

        # Settings handler — manages provider list, save/delete/test operations
        from ui.handlers.settings_handler import SettingsHandler
        self._settings_handler = SettingsHandler(
            GLib_module=GLib,
            parent_window=self,
            on_providers_changed=None,  # wired via wire_settings_handler below
            on_status_changed=None,
        )

        # Wire the SettingsHandler callbacks to the toolbar (and lazily to the settings dialog)
        from ui.wiring import wire_settings_handler
        self._settings_handler = wire_settings_handler(
            self._settings_handler,
            self._toolbar,
            settings_dialog_factory=lambda: None,
            agent_builder_factory=lambda: getattr(self, "_builder_dialog", None),
        )

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
        # # Response Status bar (right side)
        self._response_status = FeedBar()

        # Activity handler — owns the Response Status state machine (Phase 6)
        self._activity_handler = ActivityHandler(
            feedbar=self._response_status,
            main_content=self._main_content,
            GLib_module=GLib,
        )
        # Wire AgentRoutingTable so _is_ui_active can resolve project tabs for agent keys
        self._activity_handler.set_agent_routing(self._agent_to_project)

        # Media handler — owns STT (whisper.cpp push-to-talk) + improve (Phase 4)
        self._media_handler = MediaHandler(
            main_content=self._main_content,
            improve_module=__import__("utils.improve", fromlist=["improve"]),
            GLib_module=GLib,
        )

        # Input toolbar handler — owns find/replace, spell check, file I/O (Phase 5)
        from ui.handlers.input_toolbar_handler import InputToolbarHandler
        self._input_toolbar_handler = InputToolbarHandler(
            main_content=self._main_content,
            GLib_module=GLib,
        )

        # Wire input toolbar callbacks to handler — verified against actual setter names
        # NOTE: uses 'input_toolbar' to avoid shadowing the app-level 'toolbar' variable
        input_toolbar = self._main_content._control_bar
        input_toolbar.set_on_spell_toggle(self._input_toolbar_handler.toggle_spell_check)
        input_toolbar.set_on_open_file(self._input_toolbar_handler.load_file)
        input_toolbar.set_on_save_file(self._input_toolbar_handler.save_to_file)
        input_toolbar.set_on_find(self._input_toolbar_handler.find)
        input_toolbar.set_on_find_next(self._input_toolbar_handler.find_next)
        input_toolbar.set_on_find_prev(self._input_toolbar_handler.find_prev)
        input_toolbar.set_on_replace(self._input_toolbar_handler.replace_current)
        input_toolbar.set_on_replace_all(self._input_toolbar_handler.replace_all)
        # Wire input buffer's 'changed' signal to handler + count update.
        # The previous set_on_buffer_changed(...) was a no-op storage call
        # (chat_input_toolbar.set_on_buffer_changed just stores the cb).
        # Real wiring: main_content exposes its own buffer-changed signal
        # (added in Phase 8), and we bridge it to (a) handler.on_buffer_changed
        # for spell-check debounce and (b) toolbar.update_word_count for the
        # user-visible word/char count label.
        def _on_input_buffer_changed(_buf):
            self._input_toolbar_handler.on_buffer_changed()
            words, chars, tokens = self._input_toolbar_handler.compute_count()
            self._main_content._control_bar.update_word_count(words, chars, tokens)

        self._main_content.set_on_buffer_changed(_on_input_buffer_changed)

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
        self._main_content.set_on_project_tab_closed(
            lambda name: self._close_project_tab(name)
        )
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

        def _on_send_to_agent(session_key: str, text: str):
            """Send a message to an agent tab (used for rejection notifications)."""
            self._chat_handler.send_raw_message(session_key, text)

        def _on_show_feed_subtab():
            """Switch Projects notebook to the Feed sub-tab."""
            self._left_panel.switch_to_feed_tab()

        # FeedHandler created before FeedTab — set_feed_tab() called after FeedTab exists
        self._feed_handler = FeedHandler(
            GLib=GLib,
            on_send_to_agent=_on_send_to_agent,
            get_chat_box_for_session=self._main_content.get_chat_box_for_session,
            on_approve_exec=self._agent_runtime_handler.approve_exec,  # Phase E
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
                self._agent_runtime_handler.set_active_project(n, p),
                # SPEC-activity-drawer: clear stale events when switching projects
                self._activity_drawer.clear_events(),
                self._on_feed_bar_update(n, len(self._project_handler.get_project_members(n)) if n else 0),
            )
        )
        self._project_handler.set_on_project_closed(
            lambda name: (
                self._feed_handler.on_project_closed(name),
                self._crabwatch_handler.stop_watching(),
                self._chat_render_handler.set_project_name(""),
                self._agent_runtime_handler.clear_active_project(),
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
            agent_manager=None,   # synced in ConnectionSyncHandler.sync()
            project_handler=self._project_handler,
        )

        # Review handler — owns review session lifecycle (Phase 3)
        # Created BEFORE CommandHandler so it can be passed as a constructor param.
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

        # Command handler — owns backtick command parsing + routing (Phase 0.2)
        # Created AFTER ProjectHandler and ReviewHandler are initialized.
        from ui.handlers.command_handler import CommandHandler
        self._command_handler = CommandHandler(
            gateway_client=None,   # synced after connect via ConnectionSyncHandler.sync()
            agent_manager=None,    # synced after connect via ConnectionSyncHandler.sync()
            project_handler=self._project_handler,
            GLib_module=GLib,
            on_display_card=self._on_command_card,
            on_display_text=self._on_command_text,
            collab_handler=self._collab_handler,
            task_handler=self._task_handler,
            review_handler=self._review_handler,
            session_handler=self._session_handler,
        )
        self._command_handler.set_prefix(COMMAND_PREFIX)   # BUG #9 fix: read prefix from config
        # Inject CommandHandler into ChatHandler (ChatHandler calls process_input before send)
        self._chat_handler.set_command_handler(self._command_handler)
        # Populate CommandHandler with special agent names for @mention resolution in ask/delegate/stop/tell commands
        self._command_handler.set_special_agents(self._agent_runtime_handler.get_special_agents())
        # Wire ReviewHandler into AgentRuntimeHandler (deferred to avoid circular dep in _build order)
        self._agent_runtime_handler.set_review_handler(self._review_handler)
        # Wire FeedHandler into AgentRuntimeHandler (Phase D: tool call feed cards)
        self._agent_runtime_handler.set_feed_handler(self._feed_handler)
        # Wire AgentRoutingTable into AgentRuntimeHandler (solo DM response routing)
        self._agent_runtime_handler.set_agent_routing(self._agent_to_project)
        # Wire local agent lifecycle → ActivityHandler (offline mode progress bar)
        self._agent_runtime_handler.set_on_agent_start(
            lambda sk: self._activity_handler.on_agent_start(sk)
        )
        self._agent_runtime_handler.set_on_agent_end(
            lambda sk: self._activity_handler.on_agent_end(sk)
        )

        # ── Agent Command Handler (Phase 6.2) ─────────────────────────────────────
        # Scans agent responses for backtick commands, routes to target agents,
        # and relays answers back to the asking agent via pending-ask tracking.
        from ui.handlers.agent_command_handler import AgentCommandHandler
        self._agent_command_handler = AgentCommandHandler(GLib_module=GLib)
        self._agent_command_handler.set_command_handler(self._command_handler)
        self._agent_command_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        # Wire callbacks into both agent response pipelines
        self._chat_handler.set_on_agent_response(self._agent_command_handler.on_agent_response)
        self._agent_runtime_handler.set_on_agent_response(self._agent_command_handler.on_agent_response)

        # Forward handler — owns agent-to-agent message forwarding (Phase 3b extraction)
        from ui.handlers.forward_handler import ForwardHandler
        self._forward_handler = ForwardHandler(
            main_content=self._main_content,
            chat_handler=self._chat_handler,
            chat_render_handler=self._chat_render_handler,
            agent_runtime_handler=self._agent_runtime_handler,
            gateway_handler=self._gateway_handler,
        )

        # Connection sync handler — owns post-connect wiring (Phase 3a extraction)
        from ui.handlers.connection_sync_handler import ConnectionSyncHandler
        self._connection_sync_handler = ConnectionSyncHandler(
            chat_handler=self._chat_handler,
            main_content=self._main_content,
            agent_list_handler=self._agent_list_handler,
            gateway_handler=self._gateway_handler,
            project_handler=self._project_handler,
            command_handler=self._command_handler,
            agent_command_handler=self._agent_command_handler,
            session_handler=self._session_handler,
            feed_handler=self._feed_handler,
            left_panel=self._left_panel,
            review_handler=self._review_handler,
            activity_handler=self._activity_handler,
            agent_to_project=self._agent_to_project,
            on_forward_clicked=self._forward_handler.show_forward_popover,
            project_path_provider=lambda: self._project_handler.get_active_project_path() if self._project_handler else None,
        )
        # Wire the sync callback to fire on gateway connect
        self._gateway_handler.set_sync_callback(self._connection_sync_handler.sync)

        # SPEC-activity-drawer Phase 1: construct the ActivityDrawer BEFORE the
        # connection sync handler tries to wire it. The drawer widget itself is
        # lightweight (a Gtk.Box shell), so constructing it here is safe; the
        # actual re-parenting of main_content into the vertical Paned happens
        # in the drawer block at the end of _build().
        self._activity_drawer = ActivityDrawer()
        # The actual bubble + lifecycle wiring happens in sync() (after gateway
        # connect) so the drawer's append_event / on_agent_start /
        # on_agent_end are the targets from the first gateway event onward.
        # ChatHandler no longer renders activity.
        self._connection_sync_handler.set_activity_drawer(self._activity_drawer)

        # Wire project lifecycle → ReviewHandler
        self._project_handler.set_on_project_opened(
            lambda n, p: (self._review_handler.on_project_opened(n, p))
        )
        self._project_handler.set_on_project_closed(
            lambda name: (self._review_handler.on_project_closed(name))
        )



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

        # ── Activity Drawer (SPEC-activity-drawer Phase 1) ───────────────
        # Wrap main_content in a vertical Paned with the drawer below.
        # The drawer is global (one per window), not per-tab.
        # NOTE: self._activity_drawer is constructed earlier in _build() so
        # ConnectionSyncHandler can hold a reference to it. This block now
        # only handles the re-parenting of main_content into the Paned.
        self._activity_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self._activity_paned.set_end_child(self._activity_drawer)
        # Default: most space to chat (chat ~600px of ~800px window)
        self._activity_paned.set_position(600)
        self._activity_paned.set_shrink_end_child(True)
        self._activity_paned.set_resize_end_child(False)
        # Remove main_content from right_box BEFORE re-parenting it into the
        # new vertical Paned (GTK4 paned asserts child is unparented).
        right_box.remove(self._main_content)
        self._activity_paned.set_start_child(self._main_content)
        right_box.append(self._activity_paned)

    # ── Keyboard shortcuts ───────────────────────────────────────────────────

    def _set_window_icon(self):
        """Set the window icon from the PNG icon set (GTK4 via GdkSurface approach)."""
        from pathlib import Path
        icon_path = str(Path(__file__).resolve().parent.parent / "icons" / "256.png")
        surface = self.get_surface()
        if surface is None:
            return
        try:
            texture = Gdk.Texture.new_from_filename(icon_path)
            surface.set_icon_list([texture])
        except Exception as e:
            logger.warning(f"Could not load window icon: {e}")

    def _on_realize(self, widget):
        """Called when the widget surface is created. Set the window icon here."""
        self._set_window_icon()

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
        Close a project: return Projects tab in LeftPanel to picker view,
        close the project tab in main content, reset project state.
        """
        # 1. Reset project state (clears _active_project_name, fires on_project_closed callbacks)
        self._project_handler.close_project(name)
        # 2. Reparent FileTree back to Stack picker, destroy nested Notebook
        self._left_panel.close_project_view()
        # 3. Close the project tab in main content
        self._main_content.close_project_tab(name)
        # 4. Clear the feed bar
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

    # ── Agent selection callback ────────────────────────────────────────────

    def _on_agent_selected(self, session_key, agent_name):
        """Called when an agent row is clicked — create/open chat tab."""
        self._main_content.create_chat_tab(session_key, agent_name)

    # ── Agent Builder integration ──────────────────────────────────────────

    def _open_agent_builder(self, edit_name: str | None = None) -> None:
        """Open the Agent Builder dialog for creating or editing an agent."""
        from ui.views.agent_builder import AgentBuilderDialog

        if edit_name:
            agent_def = self._agent_builder_handler.load_for_edit(edit_name)
            if agent_def is None:
                logger.warning("Agent not found for editing: %s", edit_name)
                return
        else:
            # New agent — use template with sensible defaults
            agent_def = self._agent_builder_handler.create_new()

        self._builder_dialog = AgentBuilderDialog(
            self,
            handler=self._agent_builder_handler,
            agent_def=agent_def,
            on_save=lambda values: self._on_builder_save(values),
            on_cancel=lambda: self._on_builder_cancel(),
        )
        self._builder_dialog.show()

    def _on_builder_save(self, values: dict) -> None:
        """Called when the builder dialog fires save."""
        ok, errors = self._agent_builder_handler.save(values)
        if not ok:
            self._builder_dialog.show_errors(errors)
            return
        self._builder_dialog.close()

    def _on_builder_cancel(self) -> None:
        """Called when the builder dialog is cancelled."""
        pass  # dialog already closes itself

    # ── Settings integration ─────────────────────────────────────────────

    def _open_settings(self) -> None:
        """Open the Settings dialog (fresh instance each time)."""
        from ui.views.settings_dialog import SettingsDialog
        dialog = SettingsDialog(
            parent=self,
            handler=self._settings_handler,
            on_close=lambda: None,
        )
        dialog.show()







