"""LLM provider registry."""

from __future__ import annotations

from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider

_REGISTRY: dict[str, object] = {
    "openai": OpenAIProvider("openai"),
    "openrouter": OpenAIProvider("openrouter"),
    "zai": OpenAIProvider("zai"),
    "minimax": MiniMaxProvider(),
    "anthropic": AnthropicProvider(),
}


def get_provider(provider_id: str):
    """Return the LLMProvider instance for the given provider ID.

    Raises KeyError if the provider is not registered.
    """
    if provider_id not in _REGISTRY:
        raise KeyError(
            f"Unknown LLM provider: {provider_id!r}. "
            f"Registered: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[provider_id]


def list_providers() -> list[str]:
    """Return sorted list of registered provider IDs."""
    return sorted(_REGISTRY.keys())