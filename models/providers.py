# models/providers.py
# Provider configuration dataclass — pure Python, no GTK, no network, no I/O.
#
# Manifest:
#   - Reads: nothing
#   - Writes: nothing
#   - Network: none
#   - Imports: only stdlib dataclasses

from dataclasses import dataclass


# Caller-specific default context windows. Used as a fallback when the
# configured max_tokens is missing/zero OR the /v1/models probe returns no
# context_window. Values verified against each provider's published docs:
#   - openai:      128_000 (gpt-4o, gpt-4-turbo)
#   - anthropic:   200_000 (claude-3+, claude-4)
#   - minimax:     1_048_576 (MiniMax-M2.7, MiniMax-M3 — per published docs)
#   - openrouter:  128_000 (most models; outliers discoverable via /v1/models probe)
#   - zai:         128_000 (GLM-4.5+, glm-5 series)
CALLER_DEFAULT_MAX_TOKENS: dict[str, int] = {
    "openai": 128_000,
    "anthropic": 200_000,
    "minimax": 1_048_576,
    "openrouter": 128_000,
    "zai": 128_000,
}


def caller_default_max_tokens(caller: str) -> int:
    """Return the default context window for a caller key, or 128_000 fallback.

    Used by agent/runtime._compute_model_max when provider_cfg.max_tokens is
    missing/zero AND by tests asserting the fallback behavior.
    """
    return CALLER_DEFAULT_MAX_TOKENS.get(caller.lower(), 128_000)


@dataclass
class ProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # API caller key (openai|minimax|anthropic|openrouter|zai)
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    default_max_tokens: int = 0
    last_verified_at: str | None = None
    last_error: str | None = None
