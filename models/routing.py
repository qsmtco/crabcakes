# models/routing.py — Agent-to-project routing table
#
# Manifest: reads nothing, writes nothing, no network
# Pure in-memory lookup — maps session_key → project_name


class AgentRoutingTable:
    """Maps agent session keys to their active project.

    Shared between ProjectHandler (writes) and ChatHandler (reads).
    Replaces a raw dict with explicit methods and a clear contract.
    """

    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def add(self, session_key: str, project_name: str) -> None:
        """Register an agent as a member of a project."""
        self._map[session_key] = project_name

    def remove(self, session_key: str) -> None:
        """Remove an agent from routing. No-op if not present (safe to call on any key)."""
        self._map.pop(session_key, None)

    def remove_project(self, project_name: str) -> None:
        """Remove all agents belonging to a project."""
        stale = [k for k, v in self._map.items() if v == project_name]
        for k in stale:
            del self._map[k]

    def get_project(self, session_key: str) -> str | None:
        """Return project name for a session key, or None."""
        return self._map.get(session_key)

    def is_routed(self, session_key: str) -> bool:
        """True if session_key belongs to any known project."""
        return session_key in self._map

    def clear(self) -> None:
        """Remove all routing entries."""
        self._map.clear()
