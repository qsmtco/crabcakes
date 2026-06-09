# models/providers.py
# Provider configuration dataclass — pure Python, no GTK, no network, no I/O.
#
# Manifest:
#   - Reads: nothing
#   - Writes: nothing
#   - Network: none
#   - Imports: only stdlib dataclasses

from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    last_verified_at: str | None = None
    last_error: str | None = None
