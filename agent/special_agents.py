# agent/special_agents.py
# Special agent registry for the agent runtime.
#
# Defines the built-in Crabcake Special Agents (Coder, Debugger) that run
# locally without a gateway connection. Each agent has a stable session key,
# display name, emoji, color, and tool set.
#
# System prompts are loaded from prompts/system/{role}.md via prompt_loader.
# See CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md for the full design.
#
# Adding a new special agent: create a SpecialAgentDef, add it to
# SPECIAL_AGENTS, and it automatically appears on next launch.

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["SPECIAL_AGENTS", "SpecialAgentDef", "get_special_agents", "get_special_agent"]


@dataclass
class SpecialAgentDef:
    """Definition of a built-in Crabcake Special Agent."""
    conv_id_prefix: str           # e.g. "special:coder" — used as session_key
    display_name: str             # e.g. "Coder"
    role: str                     # e.g. "coder" — matches prompts/system/{role}.md
    emoji: str                    # e.g. "🛠️"
    color: str                    # hex color from AGENT_COLORS
    tools: list[str]              # tool names this agent can use
    can_write: bool               # whether write_file is in the default tool set


# ── Agent registry ───────────────────────────────────────────────────────────

SPECIAL_AGENTS: dict[str, SpecialAgentDef] = {
    "special:coder": SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        color="#6366f1",
        tools=[
            "read_file", "write_file", "edit_file", "exec_command",
            "list_files", "search_files", "web_search", "web_fetch",
        ],
        can_write=True,
    ),
    "special:debugger": SpecialAgentDef(
        conv_id_prefix="special:debugger",
        display_name="Debugger",
        role="debugger",
        emoji="🐛",
        color="#f43f5e",
        tools=[
            "read_file", "exec_command",
            "list_files", "search_files", "web_search", "web_fetch",
        ],
        can_write=False,
    ),
}


def get_special_agents() -> list[SpecialAgentDef]:
    """Return all special agent definitions, in display order."""
    return list(SPECIAL_AGENTS.values())


def get_special_agent(prefix: str) -> SpecialAgentDef | None:
    """Look up a special agent by its session key prefix."""
    return SPECIAL_AGENTS.get(prefix)
