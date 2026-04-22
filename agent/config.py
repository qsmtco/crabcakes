# agent/config.py
# LLM provider configuration for the agent runtime.
#
# Manifest:
#   - Reads <config_dir>/agent.json on load
#   - Validates file permissions (warns if group/world-readable)
#   - No network, no GTK
#
# Architecture: agent/ specific config — API keys and model selection.
# Path resolution uses utils/config.get_config_dir() — never hardcoded paths.

from __future__ import annotations

import dataclasses
import json
import logging
import os
import stat
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000          # context window size


@dataclass
class AgentConfig:
    """Top-level agent runtime configuration."""
    providers: dict[str, LLMProviderConfig] = field(default_factory=dict)
    default_provider: str = "openai"
    default_model: str = "openai/gpt-4o"
    max_tool_iterations: int = 50
    tool_timeout_seconds: int = 120
    auto_save_conversations: bool = True
    cost_limit: float | None = None    # per-conversation USD limit
    step_limit: int | None = None      # per-conversation turn limit
    review_staging_dirname: str = ".crabcakes_review_staging"  # shadow dir for review-mode writes


# ── Config loading ─────────────────────────────────────────────────────────────


def _check_permissions(path: str) -> None:
    """
    Warn if config file is group/world-readable.

    Logs a warning but does NOT block startup.
    A group-readable agent.json means other users on the same machine
    can read the API keys. This is a security concern worth surfacing.
    """
    try:
        file_stat = os.stat(path)
        mode = file_stat.st_mode
        # Check group or other read bits
        concerning = (
            (mode & stat.S_IRGRP) or   # group readable
            (mode & stat.S_IWGRP) or    # group writable
            (mode & stat.S_IROTH) or   # others readable
            (mode & stat.S_IWOTH)       # others writable
        )
        if concerning:
            octal = oct(mode)[-4:]
            logger.warning(
                "agent.json is readable by other users (mode=%s). "
                "Run: chmod 600 %s",
                octal, path,
            )
    except OSError:
        pass  # File doesn't exist yet — not a permission problem


def load_agent_config(config_path: str | None = None) -> AgentConfig:
    """
    Load agent configuration from <config_dir>/agent.json.

    Uses utils/config.get_config_dir() for path resolution, which respects
    $XDG_CONFIG_HOME and falls back to ~/.config/crabcakes.

    Args:
        config_path: Optional override for testing. If None, uses <config_dir>/agent.json.

    Returns:
        AgentConfig with defaults for any missing fields.

    Creates agent.json with example content if it doesn't exist.
    Logs a warning if agent.json is group/world-readable.
    """
    if config_path is None:
        import importlib
        utils_config = importlib.import_module("utils.config")
        config_path = os.path.join(utils_config.get_config_dir(), "agent.json")

    # Check permissions before reading
    if os.path.isfile(config_path):
        _check_permissions(config_path)

    if not os.path.isfile(config_path):
        _create_default_config(config_path)
        return AgentConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        logger.error("agent.json is not valid JSON: %s — using defaults", e)
        return AgentConfig()

    # Parse providers
    providers: dict[str, LLMProviderConfig] = {}
    for name, prov in raw.get("providers", {}).items():
        if not isinstance(prov, dict):
            continue
        providers[name] = LLMProviderConfig(
            name=name,
            base_url=prov.get("base_url", ""),
            api_key=prov.get("api_key", ""),
            default_model=prov.get("default_model", ""),
            supports_tools=prov.get("supports_tools", True),
            supports_streaming=prov.get("supports_streaming", True),
            max_tokens=prov.get("max_tokens", 128_000),
        )

    return AgentConfig(
        providers=providers,
        default_provider=raw.get("default_provider", "openai"),
        default_model=raw.get("default_model", "openai/gpt-4o"),
        max_tool_iterations=raw.get("max_tool_iterations", 50),
        tool_timeout_seconds=raw.get("tool_timeout_seconds", 120),
        auto_save_conversations=raw.get("auto_save_conversations", True),
        cost_limit=raw.get("cost_limit"),
        step_limit=raw.get("step_limit"),
    )


def _create_default_config(path: str) -> None:
    """Create agent.json with example content and a warning comment."""
    example = {
        "_comment": "LLM provider configuration for Crabcakes agent runtime",
        "_security": "chmod 600 agent.json — this file contains API keys",
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-your-key-here",
                "default_model": "gpt-4o",
                "max_tokens": 128_000,
            },
            "minimax": {
                "base_url": "https://api.minimax.chat/v1",
                "api_key": "your-minimax-key",
                "default_model": "MiniMax-M2.5",
                "max_tokens": 1_048_576,
            },
        },
        "default_provider": "openai",
        "default_model": "openai/gpt-4o",
        "max_tool_iterations": 50,
        "tool_timeout_seconds": 120,
        "cost_limit": 5.0,
        "step_limit": 100,
    }

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(example, f, indent=4)
        os.chmod(path, 0o600)
        logger.info("Created example agent.json at %s — add your API keys", path)
    except OSError as e:
        logger.warning("Could not create example agent.json at %s: %s", path, e)


def get_api_key(provider_name: str) -> str | None:
    """
    Get the API key for a specific provider.

    Loads the config if not already loaded (lazy loading).
    """
    config = load_agent_config()
    provider = config.providers.get(provider_name)
    return provider.api_key if provider else None
