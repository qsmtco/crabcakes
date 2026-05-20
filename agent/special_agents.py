# agent/special_agents.py
# Special agent registry for the agent runtime.
#
# Loads agent definitions from ~/.config/crabcakes/agents/*.yaml (or .json).
# Built-in defaults (Coder, Debugger) are seeded from prompts/default_agents/
# on first launch.
#
# System prompts are loaded from prompts/system/{role}.md via prompt_loader.
#
# Adding a new special agent: create a YAML file in the agents config dir,
# or use the Agent Builder UI. No code changes needed.

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["SPECIAL_AGENTS", "SpecialAgentDef", "get_special_agents", "get_special_agent"]


@dataclass
class SpecialAgentDef:
    """Definition of a Crabcakes Special Agent.

    Can be loaded from YAML/JSON config files or created programmatically.
    Fields provider, model, and self_improvement are optional overrides —
    when None, the global agent config defaults apply.
    """
    conv_id_prefix: str           # e.g. "special:coder" — used as session_key
    display_name: str             # e.g. "Coder"
    role: str                     # e.g. "coder" — matches prompts/system/{role}.md
    emoji: str                    # e.g. "🛠️"
    color: str                    # hex color from AGENT_COLORS
    tools: list[str]              # tool names this agent can use
    can_write: bool               # whether write_file is in the default tool set
    provider: str | None = None   # per-agent provider override (None → global default)
    model: str | None = None      # per-agent model override (None → global default)
    self_improvement: dict = field(default_factory=dict)  # SI layer toggles

    def get_self_improvement_config(self) -> dict:
        """Return self_improvement config with defaults applied.

        Delegates to utils.agent_defs.get_default_si_config() for the
        canonical defaults. The YAML-level self_improvement overrides
        the defaults.
        """
        from utils.agent_defs import get_default_si_config
        defaults = get_default_si_config(can_write=self.can_write)
        return {**defaults, **self.self_improvement}


# ── Color assignment ─────────────────────────────────────────────────────────

# Round-robin color palette for agent avatars.
_AGENT_COLORS = [
    "#6366f1",  # indigo
    "#f43f5e",  # rose
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#ec4899",  # pink
    "#14b8a6",  # teal
    "#ef4444",  # red
    "#84cc16",  # lime
]
_color_index = 0


def _next_color() -> str:
    """Return the next color in the round-robin palette."""
    global _color_index
    color = _AGENT_COLORS[_color_index % len(_AGENT_COLORS)]
    _color_index += 1
    return color


# ── Agent registry ───────────────────────────────────────────────────────────

# Lazy-loaded from YAML/JSON config files. None means "not yet loaded".
SPECIAL_AGENTS: dict[str, SpecialAgentDef] | None = None


def _load_registry() -> dict[str, SpecialAgentDef]:
    """Load agent definitions from config files and build the registry."""
    from utils.agent_defs import load_agent_defs

    defs = load_agent_defs()
    registry: dict[str, SpecialAgentDef] = {}

    for agent_def in defs:
        role = agent_def.get("role", "")
        name = agent_def.get("name", "Agent")
        session_key = f"special:{role}"
        tools = agent_def.get("tools", [])
        color = _next_color()

        registry[session_key] = SpecialAgentDef(
            conv_id_prefix=session_key,
            display_name=name,
            role=role,
            emoji=agent_def.get("emoji", "🤖"),
            color=color,
            tools=tools,
            can_write="write_file" in tools or "edit_file" in tools,
            provider=agent_def.get("provider"),
            model=agent_def.get("model"),
            self_improvement=agent_def.get("self_improvement", {}),
        )

    return registry


def _ensure_loaded() -> dict[str, SpecialAgentDef]:
    """Ensure the registry is loaded, then return it."""
    global SPECIAL_AGENTS
    if SPECIAL_AGENTS is None:
        SPECIAL_AGENTS = _load_registry()
        logger.info("Loaded %d agent definitions", len(SPECIAL_AGENTS))
    return SPECIAL_AGENTS


def reload_registry() -> None:
    """Force reload the registry from config files.

    Call after creating/editing/deleting agent definitions.
    """
    global SPECIAL_AGENTS, _color_index
    SPECIAL_AGENTS = None
    _color_index = 0
    _ensure_loaded()


def get_special_agents() -> list[SpecialAgentDef]:
    """Return all special agent definitions, in display order."""
    return list(_ensure_loaded().values())


def get_special_agent(prefix: str) -> SpecialAgentDef | None:
    """Look up a special agent by its session key prefix."""
    return _ensure_loaded().get(prefix)
