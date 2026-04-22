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

        # Register built-in special agents
        self._agent_runtime_handler.add_special_agent("Coder", "special/coder")

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
        self._project_handler = ProjectHandler(
            main_content=self._main_content,
            left_panel=self._left_panel,
            projects_module=self._projects,
            agent_to_project=self._agent_to_project,  # shared AgentRoutingTable — ProjectHandler writes, ChatHandler reads
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

        # Wire MainContent → ProjectHandler (for right-click project tab menu)
        self._main_content.set_project_handler(self._project_handler)
        self._chat_handler.set_project_handler(self._project_handler)

        # Wire feed bar — updates when project opens or members change
        # Note: set_on_project_tab_close is called here AND re-called below (Bug #13 fix)
        # Both callbacks fire: _on_tab_close (feed bar) + review_handler.on_project_closed
        self._main_content.set_on_project_settings_update(self._on_feed_bar_update)
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
        # Register all 20 commands (Phase 1-4 implementations)
        self._register_stub_commands()
        # Inject CommandHandler into ChatHandler (ChatHandler calls process_input before send)
        self._chat_handler.set_command_handler(self._command_handler)

        self._project_handler.set_on_project_opened(lambda n, p: self._on_feed_bar_update(n, len(self._projects.load_members(n)) if n else 0))
        self._project_handler.set_on_members_changed(lambda n, m: self._on_feed_bar_update(n, len(m)))

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
        self._main_content.set_on_project_tab_close(
            lambda sk: (self._on_tab_close(sk), self._review_handler.on_project_closed(sk.replace("project:", "", 1)))
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
        """Register all 16 commands as stubs that return 'not yet implemented'."""
        from models.command import CommandResult

        def stub(cmd):
            return CommandResult(handled=True, response_text="Not yet implemented.")

        # Collaboration — Phase 1 real implementations
        self._command_handler.register_command("ask", self._cmd_ask, aliases=["a"],
            help_text="Ask an agent a question: `ask @agent — question")
        self._command_handler.register_command("delegate", self._cmd_delegate, aliases=["d"],
            help_text="PM delegates to agent: `delegate @agent — task")
        self._command_handler.register_command("stop", self._cmd_stop,
            help_text="PM stops the current collaboration: `stop @agent")
        self._command_handler.register_command("tell", self._cmd_tell,
            help_text="One agent shares information with another: `tell @agent — info")
        # Task — Phase 2 real implementations
        self._command_handler.register_command("task", self._cmd_task, aliases=["t"],
            help_text="Create a task card assigned to agent")
        self._command_handler.register_command("done", self._cmd_done,
            help_text="Mark task complete")
        self._command_handler.register_command("start", self._cmd_start,
            help_text="Start working on a task")
        self._command_handler.register_command("blocked", self._cmd_blocked,
            help_text="Report a blocker on a task")
        self._command_handler.register_command("cancel", self._cmd_cancel,
            help_text="Cancel a task")
        self._command_handler.register_command("tasks", self._cmd_tasks,
            help_text="Show all tasks")
        self._command_handler.register_command("assign", self._cmd_assign,
            help_text="Reassign a task to a different agent")
        self._command_handler.register_command("priority", self._cmd_priority,
            help_text="Set task priority")
        # Review — Phase 3 real implementations
        self._command_handler.register_command("review", self._cmd_review,
            help_text="Start a review checkpoint")
        self._command_handler.register_command("check", self._cmd_check,
            help_text="Show diff of changes since checkpoint")
        self._command_handler.register_command("accept", self._cmd_accept,
            help_text="Accept all changes (or single file)")
        self._command_handler.register_command("reject", self._cmd_reject,
            help_text="Reject all pending changes")
        # Project
        self._command_handler.register_command("status", self._cmd_status, aliases=["s"],
            help_text="Project status summary")
        self._command_handler.register_command("agents", self._cmd_agents,
            help_text="List project agents and current state")
        self._command_handler.register_command("cost", self._cmd_cost,
            help_text="Spending summary for this project")
        # Utility
        self._command_handler.register_command("help", self._cmd_help, aliases=["?"],
            help_text="List all commands or help for a specific command")

    def _cmd_help(self, cmd: Command):
        """Handle `help [command] — returns command list card."""
        from models.command import CommandResult

        if cmd.args:
            # Help for specific command
            name = cmd.args[0].lstrip("@")
            help_text = self._command_handler.get_help(name)   # includes aliases via registry
            if help_text is None:
                help_text = f"Unknown command: `{name}"
            else:
                help_text = f"`{name}` — {help_text}"
            return CommandResult(handled=True, response_text=help_text)

        # Full list — dynamically read from registry so aliases are shown
        lines = [" CrabCakes Commands", ""]
        reg = self._command_handler._registry
        for name in reg.list_commands():
            alias_list = [al for al, cn in reg.list_aliases().items() if cn == name]
            alias_str = f" (`{', `'.join(alias_list)}`)" if alias_list else ""
            lines.append(f"  `{name}`{alias_str}")
        lines.extend(["", f"Type `help <command> for details."])
        return CommandResult(handled=True, response_text="\n".join(lines))

    def _cmd_ask(self, cmd: Command):
        """`ask @agent — question → forward question to agent (or all members if `@`)"""
        from models.command import CommandResult
        if cmd.is_broadcast:   # BUG #4 fix: fan-out to all project members
            return CommandResult(handled=True, broadcast_targets=cmd.broadcast_targets, forward_text=cmd.body)
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: `ask @agent — question")
        return CommandResult(handled=True, forward_to=cmd.target_session_key, forward_text=cmd.body)

    def _cmd_delegate(self, cmd: Command):
        """`delegate @agent — task → forward task to agent (or all members if `@`)"""
        from models.command import CommandResult
        if cmd.is_broadcast:   # BUG #4 fix: fan-out
            return CommandResult(handled=True, broadcast_targets=cmd.broadcast_targets, forward_text=cmd.body)
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: `delegate @agent — task")
        return CommandResult(handled=True, forward_to=cmd.target_session_key, forward_text=cmd.body)

    def _cmd_stop(self, cmd: Command):
        """`stop @agent → send stop signal to agent, show local echo."""
        from models.command import CommandResult
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: `stop @agent")
        return CommandResult(handled=True, forward_to=cmd.target_session_key, forward_text="stop")

    def _cmd_tell(self, cmd: Command):
        """`tell @agent — info → forward info to agent (or all members if `@`)"""
        from models.command import CommandResult
        if cmd.is_broadcast:   # BUG #4 fix: fan-out
            return CommandResult(handled=True, broadcast_targets=cmd.broadcast_targets, forward_text=cmd.body)
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: `tell @agent — info")
        return CommandResult(handled=True, forward_to=cmd.target_session_key, forward_text=cmd.body)

    def _cmd_task(self, cmd: Command):
        """`task @agent — description → create task, assign to agent, show card"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS, PRIORITY_LABELS
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: `task @agent — description")
        now = datetime.now().isoformat()
        task = task_store.create(Task(
            title=cmd.body,
            assigned_to=cmd.target_session_key,
            created_by=cmd.source_session_key,
            created_at=now,
            updated_at=now,
        ))
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        priority_label = PRIORITY_LABELS.get(task.priority, task.priority)
        # Resolve agent name for display
        agent_name = cmd.args[0] if cmd.args else ""
        card = {
            "type": "task",
            "action": "created",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": priority_label,
            "assigned_to": agent_name,
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_done(self, cmd: Command):
        """`done <id> → mark task complete"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        if not task_id:
            return CommandResult(handled=True, response_text="Usage: `done <task_id>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "done"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_start(self, cmd: Command):
        """`start <id> → start working on task"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS
        if not cmd.args:
            return CommandResult(handled=True, response_text="Usage: `start <task_id>")
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "in_progress"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_blocked(self, cmd: Command):
        """`blocked <id> — reason → mark task blocked"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        if not task_id:
            return CommandResult(handled=True, response_text="Usage: `blocked <task_id> — reason")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "blocked"
        task.blocked_reason = cmd.body   # BUG #17 fix: body text is the blocked reason
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_cancel(self, cmd: Command):
        """`cancel <id> → cancel task"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        if not task_id:
            return CommandResult(handled=True, response_text="Usage: `cancel <task_id>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "cancelled"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_tasks(self, cmd: Command):
        """`tasks → show all tasks"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS, PRIORITY_LABELS
        tasks = task_store.list_all()
        if not tasks:
            return CommandResult(handled=True, response_text="No tasks yet.")
        lines = ["📋 Tasks", ""]
        for t in tasks:
            status = TASK_STATUS_LABELS.get(t.status, t.status)
            priority = PRIORITY_LABELS.get(t.priority, t.priority)
            lines.append(f"[{t.id}] {t.title}")
            lines.append(f"    {status} | {priority}")
            lines.append("")
        return CommandResult(handled=True, response_text="\n".join(lines))

    def _cmd_assign(self, cmd: Command):
        """`assign <id> @agent → reassign task"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        if len(cmd.args) < 2:
            return CommandResult(handled=True, response_text="Usage: `assign <task_id> @agent")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        if cmd.target_session_key:
            task.assigned_to = cmd.target_session_key
        else:
            task.assigned_to = cmd.args[1]
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": cmd.args[1] if len(cmd.args) > 1 else "",
        }
        return CommandResult(handled=True, response_card=card)

    def _cmd_priority(self, cmd: Command):
        """`priority <id> <level> → set task priority"""
        from models.command import CommandResult
        from models.task import TASK_STATUS_LABELS, PRIORITY_LABELS
        valid = list(PRIORITY_LABELS.keys())
        if len(cmd.args) < 2:
            return CommandResult(handled=True, response_text=f"Usage: `priority <task_id> <{'|'.join(valid)}>")
        task_id = cmd.args[0].lstrip('#') if cmd.args else ''
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        level = cmd.args[1].lower()
        if level not in valid:
            return CommandResult(handled=True, response_text=f"Invalid priority. Use: {', '.join(valid)}")
        task.priority = level
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        priority_label = PRIORITY_LABELS.get(task.priority, task.priority)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": priority_label,
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    # ── Review commands (Phase 3) ────────────────────────────────────────────

    def _cmd_review(self, cmd: Command):
        """`review → start a review session"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab first.")
        project_name = session_key.split(":", 1)[1]
        self._review_handler.start_review(project_name, session_key)
        return CommandResult(handled=True, response_text="Starting review...")

    def _cmd_check(self, cmd: Command):
        """`check → check changes since checkpoint"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab first.")
        project_name = session_key.split(":", 1)[1]
        self._review_handler.check_changes(project_name, session_key)
        return CommandResult(handled=True, response_text="Checking changes...")

    def _cmd_accept(self, cmd: Command):
        """`accept → accept all changes"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab first.")
        project_name = session_key.split(":", 1)[1]
        body = " ".join(cmd.args) or "approved"
        self._review_handler.accept_changes(project_name, body, session_key)
        return CommandResult(handled=True, response_text="Accepting changes...")

    def _cmd_reject(self, cmd: Command):
        """`reject → reject all changes"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab first.")
        project_name = session_key.split(":", 1)[1]
        reason = cmd.body or "rejected"
        self._review_handler.reject_changes(project_name, reason, session_key)
        return CommandResult(handled=True, response_text="Rejecting changes...")

    def _cmd_status(self, cmd: Command):
        """`status → project status summary"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to check status.")
        project_name = session_key.split(":", 1)[1]

        # Get project info
        members = list(self._projects.load_members(project_name))
        solo_target = self._project_handler.get_solo_target(project_name) if self._project_handler else None

        # Get task summary
        all_tasks = task_store.list_all()

        # Filter tasks for this project's agents
        project_tasks = [t for t in all_tasks if t.assigned_to in members]
        pending = sum(1 for t in project_tasks if t.status == "pending")
        in_progress = sum(1 for t in project_tasks if t.status == "in_progress")
        blocked = sum(1 for t in project_tasks if t.status == "blocked")
        done = sum(1 for t in project_tasks if t.status == "done")

        # Review state
        review_state = None
        if hasattr(self, '_review_handler') and self._review_handler:
            review_state = self._review_handler.get_state(project_name)
        review_status = "active" if (review_state and review_state.is_active()) else "not started"

        solo_str = f"@{self._agent_list_handler.get_name(solo_target)}" if solo_target else "none"

        lines = [
            f"Project: {project_name}",
            f"Members: {len(members)}",
            f"Tasks: {pending} pending, {in_progress} in progress, {blocked} blocked, {done} done",
            f"Review: {review_status}",
            f"Solo DM: {solo_str}",
        ]
        return CommandResult(handled=True, response_text="\n".join(lines))

    def _cmd_agents(self, cmd: Command):
        """`agents → list project agents and their state"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to list agents.")
        project_name = session_key.split(":", 1)[1]

        members = list(self._projects.load_members(project_name))
        solo_target = self._project_handler.get_solo_target(project_name) if self._project_handler else None

        lines = [f"Members in {project_name}:", ""]
        for m in members:
            name = self._agent_list_handler.get_name(m) if hasattr(self, '_agent_list_handler') and self._agent_list_handler else m
            solo_marker = " (solo DM target)" if m == solo_target else ""
            lines.append(f"• @{name} — {m}{solo_marker}")

        return CommandResult(handled=True, response_text="\n".join(lines))

    def _cmd_cost(self, cmd: Command):
        """`cost — spending summary for current project"""
        from models.command import CommandResult
        session_key = self._main_content.get_current_session_key() or ""
        if not session_key.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to check cost.")
        project_name = session_key.split(":", 1)[1]
        members = list(self._projects.load_members(project_name))
        if not members:
            return CommandResult(handled=True, response_text="No members in this project.")
        # BUG #18 fix: use actual agent names from project members (not hardcoded)
        agent_names = [self._agent_mgr.get_name(sk) if self._agent_mgr else sk for sk in members]
        lines = [
            f"Spending summary for {project_name}:",
            "(last 7 days)",
            "",
            "Agent      Tokens   Cost",
            "────────────────────────",
        ]
        for name in agent_names:
            lines.append(f"  @{name}  (contact gateway for usage API)")
        lines.extend([
            "────────────────────────",
            "Note: Cost data requires OpenClaw usage tracking to be enabled.",
        ])
        return CommandResult(handled=True, response_text="\n".join(lines))

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
        # Wire CommandHandler with live references after connect
        self._command_handler.set_gateway_client(gw)
        self._command_handler.set_agent_manager(self._gateway_handler.agent_mgr)
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
