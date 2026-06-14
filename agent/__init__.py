# agent/__init__.py
# Agent runtime package.
#
# Exports:
#   AgentRuntime — main agent runtime, Phase 1.3a
#   LLMProviderConfig, EnforcementConfig, AgentConfig, load_agent_config, get_api_key
#   SpecialAgentDef, SPECIAL_AGENTS, get_special_agents, reload_registry
#   ToolDefinition, ToolResult
#   build_system_prompt, build_file_context
#   kb_lookup, is_index_available — KB lookup (Auxilium Tier 1)
#   check (enforcement)
#
# Files in this package:
#   __init__.py       — this file
#   config.py         — LLM provider configuration
#   tools.py          — tool definitions and execution
#   context.py        — system prompt + file context builder
#   kb_lookup.py      — KB lookup (Auxilium Tier 1)
#   runtime.py        — AgentRuntime (Phase 1.3a)
#   special_agents.py — Coder + Debugger definitions
#   enforcement.py    — policy enforcement checks

from .config import LLMProviderConfig, EnforcementConfig, AgentConfig, load_agent_config, get_api_key
from .special_agents import (
    SpecialAgentDef,
    SPECIAL_AGENTS,
    get_special_agents,
    reload_registry,
)
from .tools import ToolDefinition, ToolResult
from .context import build_system_prompt, build_file_context
# Note: kb_lookup and is_index_available are NOT re-exported here because
# the function name would shadow the submodule name. Import them directly:
#   from agent.kb_lookup import kb_lookup, is_index_available
from .enforcement import check

try:
    from .runtime import AgentRuntime
    __all__ = [
        "AgentRuntime",
        "AgentConfig",
        "EnforcementConfig",
        "LLMProviderConfig",
        "SpecialAgentDef",
        "SPECIAL_AGENTS",
        "ToolDefinition",
        "ToolResult",
        "build_file_context",
        "build_system_prompt",
        "check",
        "get_api_key",
        "get_special_agents",
        "is_index_available",
        "kb_lookup",
        "load_agent_config",
        "reload_registry",
    ]
except ImportError:
    __all__ = [
        "AgentConfig",
        "EnforcementConfig",
        "LLMProviderConfig",
        "SpecialAgentDef",
        "SPECIAL_AGENTS",
        "ToolDefinition",
        "ToolResult",
        "build_file_context",
        "build_system_prompt",
        "check",
        "get_api_key",
        "get_special_agents",
        "is_index_available",
        "kb_lookup",
        "load_agent_config",
        "reload_registry",
    ]
