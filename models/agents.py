# models/agents.py
# Agent state management — tracks session keys, display names, colors, sessions

from .colors import next_agent_color


class AgentManager:
    """
    Manages agent state: session_key -> display name, colors, sessions.
    Single source of truth for agent data.
    """

    def __init__(self) -> None:
        self._agent_names: dict[str, str] = {}       # session_key -> display name
        self._agent_colors: dict[str, str] = {}     # name -> hex color
        self._agent_sessions: dict[str, list[str]] = {}  # name -> [session_keys]

    def register(self, session_key: str, agent_name: str) -> None:
        """Register a new agent session."""
        if session_key not in self._agent_names:
            self._agent_names[session_key] = agent_name
            self._assign_color(agent_name)
            self._agent_sessions.setdefault(agent_name, []).append(session_key)

    def get_name(self, session_key: str) -> str:
        """Get agent display name for a session key."""
        return self._agent_names.get(session_key, "")

    def _assign_color(self, agent_name: str) -> None:
        """Assign a round-robin color if not already assigned."""
        if agent_name not in self._agent_colors:
            self._agent_colors[agent_name] = next_agent_color()

    def get_names_ref(self) -> dict[str, str]:
        """Return reference to internal names dict (for UI panels)."""
        return self._agent_names

    def get_sessions(self, agent_name: str) -> list[str]:
        """Return list of session keys for an agent name."""
        return self._agent_sessions.get(agent_name, [])

    def get_color(self, agent_name: str) -> str | None:
        """Return the assigned hex color for an agent name, or None if not registered."""
        return self._agent_colors.get(agent_name)

    def clear(self) -> None:
        """Clear all session tracking. Preserves colors so agents keep them on reconnect."""
        self._agent_names.clear()
        self._agent_sessions.clear()
