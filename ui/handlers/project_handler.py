# ui/handlers/project_handler.py
# Project handler — extracted from window.py Phase 3.
#
# Owns: active project name, agent-to-project routing lookup.
# Does NOT own: MainContent, LeftPanel, ChatHandler.
#
# Architecture rule: does NOT import other handlers. Window wires cross-handler
# communication via callbacks.
#
# Thread safety: all GTK operations are dispatched via GLib.idle_add().
# This handler has no background threads of its own — all entry points
# (open_project, toggle_agent) are called from the GTK main thread.

from typing import Callable


class ProjectHandler:
    """
    Handles project tab lifecycle and membership routing.

    Owns:
      _active_project_name — currently open project name (or None)
      _agent_to_project   — AgentRoutingTable instance; shared with ChatHandler

    Does NOT own: MainContent, LeftPanel, ChatHandler — receives them as deps.

    Thread safety: all GTK calls dispatched via GLib.idle_add() when GLib_module
    is provided. Safe to call from GTK main thread without GLib.

    Args:
        main_content:      MainContent instance — for create_chat_tab()
        left_panel:       LeftPanel instance — for refresh_agents_with_project()
        projects_module:  utils.projects module — for load_members() / save_members()
        agent_to_project: AgentRoutingTable — shared with ChatHandler (writes here, reads there)
        GLib_module:      gi.repository.GLib or None — for thread-safe GTK dispatch
    """

    def __init__(
        self,
        main_content,
        left_panel,
        projects_module,
        agent_to_project,  # AgentRoutingTable
        GLib_module=None,
    ):
        self._mc = main_content
        self._lp = left_panel
        self._projects = projects_module
        self._GLib = GLib_module

        # Shared routing table — AgentRoutingTable instance from window
        self._agent_to_project = agent_to_project
        self._active_project_name: str | None = None

        # ── Per-project solo DM target ────────────────────────────────────
        # Key: project_name, Value: member session_key or None (all = broadcast)
        self._solo_targets: dict[str, str | None] = {}

        # ── Cross-handler callbacks (set by window) ───────────────────────
        self._on_project_opened: list[Callable] = []   # window's callbacks
        self._on_members_changed: Callable | None = None   # window's callback

    # ── Public API — for window / other handlers ───────────────────────────

    def open_project(self, name: str, path: str):
        """
        Create a project chat tab and activate it.
        Called by LeftPanel when user double-clicks a project directory.

        Args:
            name:  Project display name
            path:  Project directory path (unused here, kept for compatibility)
        """
        self._active_project_name = name

        # Create the project tab in main content
        self._dispatch(lambda: self._mc.create_chat_tab(f"project:{name}", f"Project: {name}"))

        # Refresh the agents list to show +/− buttons
        self._dispatch(lambda: self._lp.refresh_agents_with_project(name))

        # Populate agent → project routing lookup
        members = self._projects.load_members(name) if self._projects else []
        for member_key in members:
            self._agent_to_project.add(member_key, name)

        # Notify window (for any external side-effects)
        for cb in self._on_project_opened:
            cb(name, path)

    def toggle_agent(self, session_key: str):
        """
        Add or remove an agent from the active project.
        Called by LeftPanel when user clicks +/− on an agent row.

        Args:
            session_key: Agent session key to add or remove
        """
        if not self._active_project_name:
            return

        members = list(self._projects.load_members(self._active_project_name))
        if session_key in members:
            members.remove(session_key)
        else:
            members.append(session_key)

        self._projects.save_members(self._active_project_name, members)

        # Rebuild routing table for this project
        self._agent_to_project.remove_project(self._active_project_name)
        for m in members:
            self._agent_to_project.add(m, self._active_project_name)

        # Refresh agents list (+/− button state)
        self._dispatch(lambda: self._lp.refresh_agents_with_project(self._active_project_name))

        # Notify window
        if self._on_members_changed:
            self._on_members_changed(self._active_project_name, members)

    def close_project(self, name: str):
        """
        Close a project: navigate left_panel file_tree back to picker.
        Does NOT close the tab — caller handles that.

        Args:
            name:  Project display name (ignored, just clears state)
        """
        self._active_project_name = None
        # Clear routing entries for this project
        self._agent_to_project.remove_project(name)
        self._dispatch(lambda: self._lp.refresh_agents_with_project(None))
        for cb in self._on_project_opened:
            cb(None, None)

    def is_project_session(self, session_key: str) -> bool:
        """
        True if session_key belongs to any known project.
        Used by ChatHandler to detect project tabs.
        """
        return self._agent_to_project.is_routed(session_key)

    def get_project_for_agent(self, session_key: str) -> str | None:
        """
        Return the project name this agent belongs to, or None.
        Used by ChatHandler to route responses to the correct project tab.
        """
        return self._agent_to_project.get_project(session_key)

    def get_project_members(self, project_name: str) -> list[str]:
        """
        Return the member session keys for a project.
        Used by ChatHandler for fan-out in project tabs.
        """
        return list(self._projects.load_members(project_name)) if self._projects else []

    def get_active_project_name(self) -> str | None:
        """Return the currently active project name, or None."""
        return self._active_project_name

    # ── Solo DM target (Phase 5 — per-project direct message override) ─────

    def get_solo_target(self, project_name: str) -> str | None:
        """
        Return the solo DM target for a project, or None for group broadcast.

        Args:
            project_name: Name of the project.

        Returns:
            Member session_key if solo mode is active, None if all members receive messages.
        """
        return self._solo_targets.get(project_name)

    def set_solo_target(self, project_name: str, member_session_key: str | None):
        """
        Set or clear the solo DM target for a project.

        Args:
            project_name:          Name of the project.
            member_session_key:    Session key of the solo recipient, or None to
                                   restore group broadcast (All members).
        """
        self._solo_targets[project_name] = member_session_key

    # ── Setters for cross-handler callbacks ─────────────────────────────────

    def set_on_project_opened(self, cb: Callable):
        """Add a callback for when a project is opened. Supports multiple callbacks."""
        self._on_project_opened.append(cb)

    def set_on_members_changed(self, cb: Callable):
        """Window calls this to receive membership-change notifications."""
        self._on_members_changed = cb

    # ── Internal ─────────────────────────────────────────────────────────────

    def _dispatch(self, fn: Callable):
        """Call fn on the GTK main thread. Direct call if GLib not available."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
