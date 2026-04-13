# models/colors.py
# Agent color palette — round-robin assignment

AGENT_COLORS: list[str] = [
    "#6366f1",  # indigo
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#f43f5e",  # rose
    "#06b6d4",  # cyan
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#84cc16",  # lime
]

_agent_color_next: int = 0


def next_agent_color() -> str:
    """Return the next round-robin agent color and advance the counter."""
    global _agent_color_next
    color = AGENT_COLORS[_agent_color_next % len(AGENT_COLORS)]
    _agent_color_next += 1
    return color


def reset_color_indices() -> None:
    """Reset both agent and project round-robin counters. Call on gateway reconnect."""
    global _agent_color_next, _project_color_next
    _agent_color_next = 0
    _project_color_next = 0


# ── Project color palette (same colors, separate counter) ────────────────────
# NOTE: _agent_color_next and _project_color_next are global module-state.
# Agents keep their colors across reconnects (reset_color_indices() is called
# on reconnect to start fresh, but agents already registered retain their color
# via AgentManager._agent_colors which is a separate dict). This is intentional:
# reconnecting agents get the same color they had before.

_project_color_next: int = 0


def next_project_color() -> str:
    """Return the next round-robin project color and advance the counter."""
    global _project_color_next
    color = AGENT_COLORS[_project_color_next % len(AGENT_COLORS)]
    _project_color_next += 1
    return color
