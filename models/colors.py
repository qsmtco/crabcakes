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
    """Reset both agent and project round-robin counters. Call on gateway reconnect.

    Does NOT reset _SPECIAL_AGENT_COLORS — special-agent role colors are
    stable for the process lifetime so that YAML reloads do not drift them.
    """
    global _agent_color_next, _project_color_next
    _agent_color_next = 0
    _project_color_next = 0


# ── Stable per-role colors for special agents ───────────────────────────────
# Unlike _agent_color_next, this cache is keyed by role and never advances
# past initial assignment. Survives reload_registry() and reset_color_indices()
# within a single process lifetime. The first call for a given role assigns
# from AGENT_COLORS in round-robin order (using the live-agent counter);
# subsequent calls return the cached color.
_SPECIAL_AGENT_COLORS: dict[str, str] = {}


def color_for_special_agent(role: str) -> str:
    """Return a stable hex color for a special agent role.

    First call for a given role assigns from AGENT_COLORS round-robin.
    Subsequent calls (including after reload_registry()) return the same
    color. Empty role returns the deterministic default "#6366f1".
    Unknown roles behave identically to known ones — the cache is created
    on first call and never invalidated.
    """
    global _agent_color_next
    if not role:
        return "#6366f1"
    if role in _SPECIAL_AGENT_COLORS:
        return _SPECIAL_AGENT_COLORS[role]
    color = AGENT_COLORS[_agent_color_next % len(AGENT_COLORS)]
    _agent_color_next += 1
    _SPECIAL_AGENT_COLORS[role] = color
    return color


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


# ── Agent color → CSS class mapping ─────────────────────────────────────────
# Maps a hex color (e.g. "#6366f1") to a CSS class name (e.g. "agent-bg-6366f1").
# Used by chat bubble rendering to apply per-agent tinted backgrounds.

def css_class_for_color(hex_color: str, prefix: str = "agent-bg") -> str:
    """Return a CSS class name for a hex color.

    Args:
        hex_color: Hex color string like "#6366f1" (with or without leading #).
        prefix:    "agent-bg" for bubble background classes, "agent-dot" for
                   header-dot background classes.

    Returns:
        CSS class name like "agent-bg-6366f1". Always lowercase, no '#'.
        Returns "agent-bg-default" if hex_color is falsy/invalid.
    """
    if not hex_color or not isinstance(hex_color, str):
        return f"{prefix}-default"
    cleaned = hex_color.lstrip("#").lower()
    if not cleaned:
        return f"{prefix}-default"
    return f"{prefix}-{cleaned}"


def all_palette_css_classes() -> list[tuple[str, str, str]]:
    """Return all (css_class, prefix, hex_color) tuples for the palette.

    Generates both "agent-bg-<hex>" and "agent-dot-<hex>" entries for every
    color in AGENT_COLORS. Used by ui/styles.py to generate CSS rules at startup.

    Returns:
        List of (css_class_name, prefix, hex_color) tuples.
    """
    result: list[tuple[str, str, str]] = []
    for hex_color in AGENT_COLORS:
        cleaned = hex_color.lstrip("#").lower()
        result.append((f"agent-bg-{cleaned}", "agent-bg", hex_color))
        result.append((f"agent-dot-{cleaned}", "agent-dot", hex_color))
    return result


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string to an (r, g, b) tuple (0-255 each).

    Handles "#rrggbb", "rrggbb", "#rgb", "rgb" formats.
    Returns (99, 102, 241) (indigo) as a safe fallback on parse failure.
    """
    if not hex_color or not isinstance(hex_color, str):
        return (99, 102, 241)
    cleaned = hex_color.lstrip("#").lower()
    try:
        if len(cleaned) == 3:
            r = int(cleaned[0] * 2, 16)
            g = int(cleaned[1] * 2, 16)
            b = int(cleaned[2] * 2, 16)
        elif len(cleaned) == 6:
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
        else:
            return (99, 102, 241)
        return (r, g, b)
    except (ValueError, IndexError):
        return (99, 102, 241)
