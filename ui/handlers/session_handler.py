# ui/handlers/session_handler.py
# Session switching command implementation — extracted from window.py Phase 7.
#
# Manifest:
#   reads:   models.command, models.agents (AgentManager)
#   writes:  ProjectHandler (via update_agent_session)
#   network: nothing
#   GTK:     nothing
#
# Owns: session command — session list/switch for agents in project tabs
# Does NOT own: GTK widgets, gateway client
#
# Architecture: pure Python. No imports from ui/, gateway/, or agent/.
#
# Dependencies injected via setters after construction:
#   set_agent_manager()    — AgentManager for session lookups
#   set_project_handler()  — ProjectHandler for session updates


from models.command import Command, CommandResult


class SessionHandler:
    """
    Handles `session list @agent | `session <ref> @agent command.

    Manages agent session switching within project tabs. Needs AgentManager
    (for session lookup by agent name) and ProjectHandler (for updating
    the active session mapping) — injected via setters after construction.

    Args:
        agent_manager:   AgentManager — set via set_agent_manager()
        project_handler: ProjectHandler — set via set_project_handler()
    """

    def __init__(self, agent_manager=None, project_handler=None):
        self._agent_mgr = agent_manager
        self._project_handler = project_handler

    def set_agent_manager(self, agent_mgr) -> None:
        """Inject the live AgentManager after gateway connect."""
        self._agent_mgr = agent_mgr

    def set_project_handler(self, project_handler) -> None:
        """Inject the live ProjectHandler after construction."""
        self._project_handler = project_handler

    def cmd_session(self, cmd: Command) -> CommandResult:
        """`session list @agent | `session <ref> @agent — switch agent session."""
        sk = cmd.source_session_key
        if not sk or not sk.startswith("project:"):
            return CommandResult(
                handled=True,
                response_text="Session switching is only available in project tabs.",
            )

        project_name = sk.split(":", 1)[1]

        if not cmd.target_session_key:
            return CommandResult(
                handled=True,
                response_text="Usage: `session list @agent | `session <ref> @agent",
            )

        if self._agent_mgr is None:
            return CommandResult(handled=True, response_text="Not connected to gateway.")

        agent_name = self._agent_mgr.get_name(cmd.target_session_key)
        if not agent_name:
            return CommandResult(handled=True, response_text=f"Unknown agent: {cmd.target_session_key}")

        # Verify agent is a member of this project
        current_sk = self._project_handler.get_agent_session_in_project(project_name, agent_name)
        if current_sk is None:
            return CommandResult(handled=True, response_text=f"@{agent_name} is not a member of this project.")

        if not cmd.args:
            return CommandResult(
                handled=True,
                response_text="Usage: `session list @agent | `session <ref> @agent",
            )

        subcmd = cmd.args[0].lower()
        if subcmd == "list":
            return self._session_list(agent_name, current_sk)
        else:
            return self._session_switch(agent_name, current_sk, subcmd, project_name)

    # ── Private helpers ───────────────────────────────────────────────────────────

    def _session_list(self, agent_name: str, current_sk: str) -> CommandResult:
        """Return numbered list of agent sessions."""
        sessions = self._agent_mgr.get_sessions(agent_name)
        if not sessions:
            return CommandResult(handled=True, response_text=f"No sessions found for @{agent_name}.")

        lines = [f"Sessions for {agent_name}:"]
        for i, s in enumerate(sessions, 1):
            display = self._short_session_key(s)
            marker = "  ✓ (current)" if s == current_sk else ""
            lines.append(f"  {i}. {display}{marker}")
        lines.append("")
        lines.append("Switch: `session <number> @" + agent_name)
        return CommandResult(handled=True, response_text="\n".join(lines))

    def _session_switch(
        self,
        agent_name: str,
        old_sk: str,
        session_ref: str,
        project_name: str,
    ) -> CommandResult:
        """Switch an agent to a different session in the project."""
        sessions = self._agent_mgr.get_sessions(agent_name)
        if not sessions:
            return CommandResult(handled=True, response_text=f"No sessions found for @{agent_name}.")

        new_sk = None

        # Try numeric index
        try:
            idx = int(session_ref)
            if 1 <= idx <= len(sessions):
                new_sk = sessions[idx - 1]
        except ValueError:
            pass

        # Try string match (exact then prefix)
        if new_sk is None:
            for s in sessions:
                if s == session_ref:
                    new_sk = s
                    break
            if new_sk is None:
                prefix = f"agent:{agent_name.lower()}:"
                matches = [s for s in sessions if s.lower().startswith(prefix + session_ref.lower())]
                if len(matches) == 1:
                    new_sk = matches[0]
                elif len(matches) > 1:
                    return CommandResult(
                        handled=True,
                        response_text=f"Ambiguous session ref '{session_ref}'. Use `session list @{agent_name} to see options.",
                    )

        if new_sk is None:
            return CommandResult(
                handled=True,
                response_text=f"No matching session '{session_ref}'. Use `session list @{agent_name} to see options.",
            )

        if new_sk == old_sk:
            display = self._short_session_key(new_sk)
            return CommandResult(handled=True, response_text=f"Already on session: {display}")

        self._project_handler.update_agent_session(project_name, old_sk, new_sk)
        display = self._short_session_key(new_sk)
        return CommandResult(handled=True, response_text=f"✓ Switched @{agent_name} to: {display}")

    def _short_session_key(self, key: str) -> str:
        """Strip 'agent:<name>:' prefix for display."""
        parts = key.split(":")
        if len(parts) >= 3 and parts[0] == "agent":
            return ":".join(parts[2:])
        return key
