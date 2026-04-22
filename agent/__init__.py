# agent/__init__.py
# Agent runtime package.
#
# Exports:
#   AgentRuntime — imported lazily in Phase 1.3a
#
# Files in this package:
#   __init__.py       — this file
#   config.py         — LLM provider configuration
#   tools.py          — tool definitions and execution
#   context.py        — system prompt + file context builder
#   runtime.py        — AgentRuntime (Phase 1.3a)
#   special_agents.py — Coder + Debugger definitions

try:
    from agent.runtime import AgentRuntime
    __all__ = ["AgentRuntime"]
except ImportError:
    __all__ = []