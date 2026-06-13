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
import os
import logging

from models.command import Command, CommandResult
from models import task_store
from utils.git_ops import init_repo, stage_all, commit
from utils.workflow_state import init_workflow

_logger = logging.getLogger(__name__)


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
        main_content:      DEPRECATED — no longer used (project view is in LeftPanel)
        left_panel:       LeftPanel instance — for refresh_agents_with_project()
        projects_module:  utils.projects module — for load_members() / save_members()
        agent_to_project: AgentRoutingTable — shared with ChatHandler (writes here, reads there)
        GLib_module:      gi.repository.GLib or None — for thread-safe GTK dispatch
    """

    def __init__(
        self,
        left_panel,
        projects_module,
        agent_to_project,  # AgentRoutingTable
        GLib_module=None,
        awareness_module=None,  # utils.project_awareness module (optional)
    ):
        self._lp = left_panel
        self._projects = projects_module
        self._GLib = GLib_module
        self._awareness = awareness_module  # utils.project_awareness for .crabcakes/ access

        # Shared routing table — AgentRoutingTable instance from window
        self._agent_to_project = agent_to_project
        self._agent_mgr = None  # injected via set_agent_manager() after gateway connect
        self._active_project_name: str | None = None
        self._active_project_path: str | None = None  # path for current project

        # ── Per-project solo DM target ────────────────────────────────────
        # Key: project_name, Value: member session_key or None (all = broadcast)
        self._solo_targets: dict[str, str | None] = {}

        # ── Cross-handler callbacks (set by window) ───────────────────────
        self._on_project_opened: list[Callable] = []   # window's callbacks
        self._on_project_closed: list[Callable] = []   # window's close callbacks
        self._on_members_changed: Callable | None = None   # window's callback

    # ── Public API — for window / other handlers ───────────────────────────

    def open_project(self, name: str, path: str):
        """
        Create a project chat tab and activate it.
        Called by LeftPanel when user double-clicks a project directory.

        Args:
            name:  Project display name
            path:  Project directory path
        """
        self._active_project_name = name
        self._active_project_path = path

        # Initialize .crabcakes/ directory (migrates legacy config if needed)
        if self._awareness:
            self._awareness.init_project_config(path, name)

        # Auto-add onboarding agents if not already members
        self._auto_add_onboarding_agents(path)

        # Initialize workflow.md (idempotent — skips if already exists)
        try:
            init_workflow(path)
        except Exception:
            pass  # non-fatal

        # Create the project tab in main content
        # NOTE: No chat tab creation here. Project view lives in LeftPanel's Projects tab.

        # Refresh the agents list to show +/− buttons
        self._dispatch(lambda: self._lp.refresh_agents_with_project(name))

        # Populate agent → project routing lookup
        members = self._load_members(name)
        for member_key in members:
            self._agent_to_project.add(member_key, name)

        # Notify window (for any external side-effects)
        for cb in self._on_project_opened:
            cb(name, path)

    def create_project(self, name: str, path: str | None = None, pm_name: str = "", pm_id: str = "") -> str | None:
        """
        Create a new project directory and open it.
        Called by FileTree when user fills out the New Project form.

        Args:
            name:  Project display name (must be non-empty)
            path:  Optional path override. Defaults to $CRABCAKES_PROJECTS_DIR/<name>
            pm_name: Project manager display name (e.g. "Captain")
            pm_id:   Project manager identifier (e.g. "cli")

        Returns:
            The project path on success, or None on failure.
        """
        # Validate name
        if not name or not name.strip():
            return None
        name = name.strip()

        # Resolve default path from projects module
        if not path:
            projects_dir = self._projects._PROJECTS_DIR_REF[0]
            path = os.path.join(projects_dir, name)

        # Check if directory already exists
        if os.path.exists(path):
            return None

        # Create the directory
        try:
            os.makedirs(path, exist_ok=False)
        except OSError:
            return None

        # Initialize .crabcakes/ with awareness artifacts
        if self._awareness:
            self._awareness.init_project_config(path, name, pm_name, pm_id)

        # Auto-add onboarding agents (Crabcakes 🦀) to new project team
        self._auto_add_onboarding_agents(path)

        # Initialize workflow.md (idempotent — creates with onboarding as current)
        try:
            init_workflow(path)
        except Exception:
            pass  # non-fatal

        # Auto-initialize git repo with initial commit
        result = init_repo(path)
        if result.success:
            stage_all(path)
            commit(path, f"project {name} created via CrabCakes")
        else:
            _logger.warning("git init failed for %s: %s", path, result.error)

        # Refresh awareness snapshot AFTER git init so git state is captured
        if self._awareness:
            snapshot = self._awareness.build_awareness_snapshot(path)
            self._awareness.save_awareness_snapshot(path, snapshot)

        # Open the project (creates tab, refreshes agents, fires callbacks)
        self.open_project(name, path)

        return path

    def toggle_agent(self, session_key: str):
        """
        Add or remove an agent from the active project.
        Called by LeftPanel when user clicks +/− on an agent row.

        Args:
            session_key: Agent session key to add or remove
        """
        if not self._active_project_name:
            return

        members = self._load_members(self._active_project_name)
        if session_key in members:
            members.remove(session_key)
        else:
            members.append(session_key)

        self._save_members(self._active_project_name, members)

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
            name:  Project display name
        """
        if self._active_project_name is None:
            return
        # Capture name BEFORE clearing state — callbacks need the project name
        closing_name = name
        self._active_project_name = None
        self._active_project_path = None
        # Clear routing entries for this project
        self._agent_to_project.remove_project(name)
        self._dispatch(lambda: self._lp.refresh_agents_with_project(None))
        for cb in self._on_project_closed:
            cb(closing_name)

    def get_project_for_session(self, session_key: str) -> str | None:
        """Resolve project name from a session key.

        For project tabs (session_key starts with "project:"), extracts
        the project name directly. For agent sessions, looks up the
        routing table to find which project the agent belongs to.

        Args:
            session_key: Session key to resolve.

        Returns:
            Project name, or None if not associated with any project.
        """
        if session_key.startswith("project:"):
            return session_key.split(":", 1)[1]
        return self._agent_to_project.get_project(session_key)

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
        return list(self._load_members(project_name))

    def get_agent_session_in_project(self, project_name: str, agent_name: str) -> str | None:
        """Return the session key that a named agent currently uses in a project.

        Cross-references project members with AgentManager sessions to find
        which of the agent's sessions is active in this project.

        Args:
            project_name:  Project to check.
            agent_name:    Display name of the agent.

        Returns:
            Session key, or None if the agent is not a member of this project.
        """
        members = self.get_project_members(project_name)
        if not self._agent_mgr:
            return None
        agent_sessions = self._agent_mgr.get_sessions(agent_name)
        for sk in members:
            if sk in agent_sessions:
                return sk
        return None

    def update_agent_session(self, project_name: str, old_session_key: str, new_session_key: str) -> None:
        """Replace an agent's session key within a project's member list.

        Updates members.json and the routing table atomically.

        Args:
            project_name:     Project to update.
            old_session_key:  Current session key for the agent.
            new_session_key:  New session key to switch to.
        """
        members = list(self._load_members(project_name))
        if old_session_key not in members:
            return  # Agent not in this project — nothing to do

        # Replace the old session key with the new one
        idx = members.index(old_session_key)
        members[idx] = new_session_key

        # Persist
        self._save_members(project_name, members)

        # Rebuild routing table for this project
        self._agent_to_project.remove_project(project_name)
        for m in members:
            self._agent_to_project.add(m, project_name)

        # Migrate solo target if it was pointing at the old session
        if self._solo_targets.get(project_name) == old_session_key:
            self._solo_targets[project_name] = new_session_key

    def get_active_project_name(self) -> str | None:
        """Return the currently active project name, or None."""
        return self._active_project_name

    # ── Solo DM target (Phase 5 — per-project direct message override) ─────

    @staticmethod
    def _extract_display_name(session_key: str) -> str:
        """Extract a human-readable name from a session key when AgentManager has no mapping.

        Examples:
          'special:auxilium' → 'auxilium'
          'special:tester'    → 'tester'
          'agent:qtr:telegram:direct:123' → 'qtr'
          'agent:qaster:telegram:direct:456' → 'Qaster'
        """
        parts = session_key.split(":")
        if parts[0] == "special" and len(parts) >= 2:
            return parts[1]
        if parts[0] == "agent" and len(parts) >= 2:
            return parts[1]
        return session_key

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

    def set_on_project_closed(self, cb: Callable):
        """Add a callback for when a project is closed. Supports multiple callbacks."""
        self._on_project_closed.append(cb)

    def set_on_members_changed(self, cb: Callable):
        """Window calls this to receive membership-change notifications."""
        self._on_members_changed = cb

    def set_agent_manager(self, agent_mgr) -> None:
        """Inject the live AgentManager after gateway connect. Called by window.py."""
        self._agent_mgr = agent_mgr

    # ── Phase 5: Project Onboarding ─────────────────────────────────────

    def _auto_add_onboarding_agents(self, project_path: str) -> None:
        """Auto-add agents with auto_add_to_projects=True to the project team.

        Called during project creation and first open. These agents serve as
        project onboarding guides — they receive the project-onboarding template
        via compose_system_prompt() when the project is not yet onboarded.
        """
        try:
            from agent.special_agents import get_project_onboarding_agents
            onboarding_agents = get_project_onboarding_agents()
        except Exception:
            return  # Non-fatal — special agents may not be loaded yet

        if not onboarding_agents or not self._awareness:
            return

        team = self._awareness.load_team(project_path)
        changed = False
        for agent_def in onboarding_agents:
            if not team.has_member(agent_def.conv_id_prefix):
                from models.team import TeamMember
                team.add_member(TeamMember(
                    session_key=agent_def.conv_id_prefix,
                    name=agent_def.display_name,
                    role="onboarding guide",
                    can_write=True,  # needs write_file for onboarding
                ))
                changed = True
                # Also add to routing table if project is active
                if self._active_project_name:
                    self._agent_to_project.add(agent_def.conv_id_prefix, self._active_project_name)

        if changed:
            self._awareness.save_team(project_path, team)
            _logger.info("Auto-added onboarding agents to project at %s", project_path)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load_members(self, project_name: str) -> list[str]:
        """Load member session keys. Uses awareness module if available, else legacy."""
        path = self._get_project_path(project_name)
        if path and self._awareness:
            team = self._awareness.load_team(path)
            return team.get_session_keys()
        # Fallback to legacy
        if self._projects:
            return list(self._projects.load_members(project_name))
        return []

    def _save_members(self, project_name: str, members: list[str]) -> None:
        """Save member session keys. Uses awareness module if available, else legacy."""
        path = self._get_project_path(project_name)
        if path and self._awareness:
            from models.team import TeamMember
            team = self._awareness.load_team(path)
            new_members = []
            for sk in members:
                existing = team.get_member(sk)
                if existing:
                    new_members.append(existing)
                else:
                    new_members.append(TeamMember(session_key=sk, name=""))
            team.members = new_members
            self._awareness.save_team(path, team)
            # Auto-commit team changes
            self._git_commit_if_available(path, "update team roster")
            return
        # Fallback to legacy
        if self._projects:
            self._projects.save_members(project_name, members)

    def _get_project_path(self, project_name: str) -> str | None:
        """Resolve project path from name. Uses cached active path or searches projects."""
        if self._active_project_name == project_name and self._active_project_path:
            return self._active_project_path
        # Search projects list
        if self._projects:
            for name, path in self._projects.load_projects():
                if name == project_name:
                    return path
        return None

    def get_active_project_path(self) -> str | None:
        """Return the currently active project path, or None."""
        return self._active_project_path

    # ── Command entry points (Phase 7) ────────────────────────────────────────


    def cmd_status(self, cmd: Command, session_key: str | None = None) -> CommandResult:
        """/status → project status summary"""
        sk = cmd.source_session_key
        if not sk.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to check status.")
        project_name = sk.split(":", 1)[1]
        members = self.get_project_members(project_name)
        solo_target = self.get_solo_target(project_name)
        all_tasks = task_store.list_all()
        project_tasks = [t for t in all_tasks if t.assigned_to in members]
        pending = sum(1 for t in project_tasks if t.status == "pending")
        in_progress = sum(1 for t in project_tasks if t.status == "in_progress")
        blocked = sum(1 for t in project_tasks if t.status == "blocked")
        done = sum(1 for t in project_tasks if t.status == "done")
        review_state = self._review_handler.get_state(project_name) if hasattr(self, '_review_handler') and self._review_handler else None
        review_status = "active" if (review_state and review_state.is_active()) else "not started"
        solo_str = f"@{((self._agent_mgr.get_name(solo_target) if self._agent_mgr else "") or self._extract_display_name(solo_target))}" if solo_target else "none"
        lines = [
            f"Project: {project_name}",
            f"Members: {len(members)}",
            f"Tasks: {pending} pending, {in_progress} in progress, {blocked} blocked, {done} done",
            f"Review: {review_status}",
            f"Solo DM: {solo_str}",
        ]
        return CommandResult(handled=True, response_text="\n".join(lines))

    def cmd_agents(self, cmd: Command, session_key: str | None = None) -> CommandResult:
        """/agents → list project agents and their state"""
        sk = cmd.source_session_key
        if not sk.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to list agents.")
        project_name = sk.split(":", 1)[1]
        members = self.get_project_members(project_name)
        solo_target = self.get_solo_target(project_name)
        lines = [f"Members in {project_name}:", ""]
        for m in members:
            name = (self._agent_mgr.get_name(m) if self._agent_mgr else "") or self._extract_display_name(m)
            solo_marker = " (solo DM target)" if m == solo_target else ""
            lines.append(f"• @{name} — {m}{solo_marker}")
        return CommandResult(handled=True, response_text="\n".join(lines))


    def cmd_cost(self, cmd: Command, session_key: str | None = None) -> CommandResult:
        """/cost — spending summary for current project"""
        sk = cmd.source_session_key
        if not sk.startswith("project:"):
            return CommandResult(handled=True, response_text="Open a project tab to check cost.")
        project_name = sk.split(":", 1)[1]
        members = self.get_project_members(project_name)
        if not members:
            return CommandResult(handled=True, response_text="No members in this project.")
        agent_names = [((self._agent_mgr.get_name(sk) if self._agent_mgr else "") or self._extract_display_name(sk)) for sk in members]
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


    def set_review_handler(self, review_handler) -> None:
        """"Inject ReviewHandler for review state queries in cmd_status."""
        self._review_handler = review_handler

    # ── Git commit helper ───────────────────────────────────────────────

    def _git_commit_if_available(self, path: str, message: str) -> None:
        """Stage all and commit if git is available. Non-fatal on failure."""
        try:
            stage_all(path)
            commit(path, message)
        except Exception:
            _logger.debug("git commit failed for %s: %s", path, message)

    def _dispatch(self, fn: Callable):
        """Call fn on the GTK main thread. Direct call if GLib not available."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
