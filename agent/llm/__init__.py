"""LLM provider abstraction layer.

Public API:
    get_provider(id) -> LLMProvider
    list_providers() -> list[str]
    LLMProvider — Protocol
    LLMResponse — normalized response dataclass
"""
from agent.llm.protocol import LLMProvider, LLMResponse
from agent.llm.registry import get_provider, list_providers

__all__ = [
    "get_provider",
    "list_providers",
    "LLMProvider",
    "LLMResponse",
]