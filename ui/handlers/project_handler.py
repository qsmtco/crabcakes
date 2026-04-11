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
      _agent_to_project   — {session_key: project_name} for fan-out routing

    Does NOT own: MainContent, LeftPanel, ChatHandler — receives them as deps.

    Thread safety: all GTK calls dispatched via GLib.idle_add() when GLib_module
    is provided. Safe to call from GTK main thread without GLib.

    Args:
        main_content:      MainContent instance — for create_chat_tab()
        left_panel:       LeftPanel instance — for refresh_agents_with_project()
        projects_module:  utils.projects module — for load_members() / save_members()
        GLib_module:      gi.repository.GLib or None — for thread-safe GTK dispatch
    """

    def __init__(
        self,
        main_content,
        left_panel,
        projects_module,
        agent_to_project: dict,
        GLib_module=None,
    ):
        self._mc = main_content
        self._lp = left_panel
        self._projects = projects_module
        self._GLib = GLib_module

        # Owned state (delegated to shared dict from window)
        self._agent_to_project = agent_to_project  # shared ref — window passes same dict to ChatHandler
        self._active_project_name: str | None = None

        # ── Cross-handler callbacks (set by window) ───────────────────────
        self._on_project_opened: Callable | None = None   # window's callback
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
            self._agent_to_project[member_key] = name

        # Notify window (for any external side-effects)
        if self._on_project_opened:
            self._on_project_opened(name, path)

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

        # Rebuild routing dict for this project
        stale = [k for k, v in self._agent_to_project.items() if v == self._active_project_name]
        for k in stale:
            del self._agent_to_project[k]
        for m in members:
            self._agent_to_project[m] = self._active_project_name

        # Refresh agents list (+/− button state)
        self._dispatch(lambda: self._lp.refresh_agents_with_project(self._active_project_name))

        # Notify window
        if self._on_members_changed:
            self._on_members_changed(self._active_project_name, members)

    def is_project_session(self, session_key: str) -> bool:
        """
        True if session_key belongs to any known project.
        Used by ChatHandler to detect project tabs.
        """
        return session_key in self._agent_to_project

    def get_project_for_agent(self, session_key: str) -> str | None:
        """
        Return the project name this agent belongs to, or None.
        Used by ChatHandler to route responses to the correct project tab.
        """
        return self._agent_to_project.get(session_key)

    def get_project_members(self, project_name: str) -> list[str]:
        """
        Return the member session keys for a project.
        Used by ChatHandler for fan-out in project tabs.
        """
        return list(self._projects.load_members(project_name)) if self._projects else []

    def get_active_project_name(self) -> str | None:
        """Return the currently active project name, or None."""
        return self._active_project_name

    # ── Setters for cross-handler callbacks ─────────────────────────────────

    def set_on_project_opened(self, cb: Callable):
        """Window calls this to receive project-opened notifications."""
        self._on_project_opened = cb

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
