# agent/special_agents.py
# Special agent registry for the agent runtime.
#
# Defines the built-in Crabcake Special Agents (Coder, Debugger) that run
# locally without a gateway connection. Each agent has a stable session key,
# display name, emoji, color, tool set, and system prompt template.
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
    emoji: str                    # e.g. "🛠️"
    color: str                    # hex color from AGENT_COLORS
    tools: list[str]              # tool names this agent can use
    system_prompt_template: str   # template with {project_name}, {file_context}, etc.
    can_write: bool               # whether write_file is in the default tool set


# ── System prompt templates ──────────────────────────────────────────────────

CODER_PROMPT_TEMPLATE = """\
You are Coder, an expert software developer working on the project: {project_name}.

You have access to the following tools: {tools}.

## Your Role
- Implement features, refactor code, write tests, build infrastructure
- Read files before modifying them to understand context
- Write clear, well-structured code with comments for non-obvious decisions
- Run tests after making changes to verify correctness

## Working Directory
{project_path}

## File Context
{file_context}

## Guidelines
- Always read existing code before modifying it
- Make small, focused changes
- Explain your reasoning before writing code
- Run relevant tests after changes
- Follow existing code style and conventions
{review_mode_block}\
"""

DEBUGGER_PROMPT_TEMPLATE = """\
You are Debugger, an expert at diagnosing bugs, tracing errors, and analyzing logs. \
You investigate and report — you do NOT write files by default.

You have access to the following tools: {tools}.

## Your Role
- Diagnose bugs by reading code, logs, and stack traces
- Trace error paths through the codebase
- Analyze test failures and identify root causes
- Suggest fixes but do NOT implement them (read-only by default)
- If the PM explicitly asks you to fix something, you may write files

## Working Directory
{project_path}

## File Context
{file_context}

## Guidelines
- Start by reading relevant files and understanding the error
- Build a hypothesis before diving deep
- Present findings clearly with file paths and line numbers
- Suggest specific fixes with code snippets
- Never make assumptions — verify by reading the actual code
{review_mode_block}\
"""


# ── Agent registry ───────────────────────────────────────────────────────────

SPECIAL_AGENTS: dict[str, SpecialAgentDef] = {
    "special:coder": SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        emoji="🛠️",
        color="#6366f1",
        tools=[
            "read_file", "write_file", "exec_command",
            "list_files", "search_files", "web_search", "web_fetch",
        ],
        system_prompt_template=CODER_PROMPT_TEMPLATE,
        can_write=True,
    ),
    "special:debugger": SpecialAgentDef(
        conv_id_prefix="special:debugger",
        display_name="Debugger",
        emoji="🐛",
        color="#f43f5e",
        tools=[
            "read_file", "exec_command",
            "list_files", "search_files", "web_search", "web_fetch",
        ],
        system_prompt_template=DEBUGGER_PROMPT_TEMPLATE,
        can_write=False,
    ),
}


def get_special_agents() -> list[SpecialAgentDef]:
    """Return all special agent definitions, in display order."""
    return list(SPECIAL_AGENTS.values())


def get_special_agent(prefix: str) -> SpecialAgentDef | None:
    """Look up a special agent by its session key prefix."""
    return SPECIAL_AGENTS.get(prefix)
