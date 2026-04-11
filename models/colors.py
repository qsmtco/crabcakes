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
    """Reset the agent round-robin counter. Call on gateway reconnect."""
    global _agent_color_next
    _agent_color_next = 0
