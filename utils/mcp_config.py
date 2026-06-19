# utils/mcp_config.py
# MCP server configuration loader.
#
# Manifest: Loads MCP server configs from ~/.config/crabcakes/mcp-servers.json
# No network, no GTK, no state — pure functions.
#
# Architecture: utils/ is pure Python, no dependencies on UI or network.
# Follows patterns from agent/config.py for JSON loading.

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from utils.config import get_config_dir


logger = logging.getLogger(__name__)


# MED-12: Only forward these environment variables to MCP servers.
# All other vars are refused (log + skip) to prevent leaking sensitive config.
_MCP_FORWARDABLE_ENV_VARS: frozenset[str] = frozenset({
    "PATH", "HOME", "LANG", "VIRTUAL_ENV", "PYTHONPATH",
})


# ── Dataclasses ────────────────────────────────────────────────────────────────


class MCPConfigError(ValueError):
    """Raised when MCP config is invalid."""
    pass


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str                    # Server name (e.g., "github")
    transport: str = "stdio"     # "stdio" or "streamable-http"
    command: str = ""            # Command to run (e.g., "npx")
    args: list[str] = field(default_factory=list)  # Arguments
    env: dict[str, str] | None = None  # Environment variables
    description: str = ""      # Human-readable description
    enabled: bool = True        # Whether server is active

    def to_stdio_params(self) -> "StdioServerParameters":
        """Convert to MCP SDK StdioServerParameters.

        Handles env var substitution: ${VAR} → os.environ[VAR]

        Raises:
            MCPConfigError: If stdio transport but command is empty.
        """
        # Import here to avoid circular import at module level
        from mcp import StdioServerParameters

        if self.transport == "stdio" and not self.command.strip():
            raise MCPConfigError(f"Server '{self.name}': stdio transport requires non-empty command")

        # Substitute environment variables
        env: dict[str, str] | None = None
        if self.env:
            env = {}
            for key, value in self.env.items():
                # Match ${VAR} pattern
                match = re.match(r"^\$\{(\w+)}$", value)
                if match:
                    var_name = match.group(1)
                    # MED-12: Check allowlist before forwarding
                    if var_name not in _MCP_FORWARDABLE_ENV_VARS:
                        logger.warning(
                            "MED-12: Refusing to forward env var '%s' for server '%s' "
                            "— not in forwardable allowlist. Allowed: %s",
                            var_name, self.name, sorted(_MCP_FORWARDABLE_ENV_VARS),
                        )
                        continue
                    resolved = os.environ.get(var_name, "")
                    if not resolved:
                        logger.warning(
                            "MED-12: Environment variable '%s' is set for server '%s' "
                            "but is empty or not found in process environment",
                            var_name, self.name,
                        )
                    env[key] = resolved
                else:
                    env[key] = value

        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=env if env else None,
        )


# ── Config Loading ────────────────────────────────────────────────────────────────


# Simple cache to avoid repeated file reads
_config_cache: dict[str, MCPServerConfig] | None = None

# LOW-5: one-time legacy path warning flag
_LEGACY_MCP_JSON_WARNED: bool = False


def _check_legacy_mcp_json() -> None:
    """LOW-5: Warn once if legacy ~/.mcp.json exists."""
    global _LEGACY_MCP_JSON_WARNED
    if _LEGACY_MCP_JSON_WARNED:
        return
    _LEGACY_MCP_JSON_WARNED = True
    from pathlib import Path
    legacy = Path.home() / ".mcp.json"
    if legacy.is_file():
        logger.warning(
            "LOW-5: Legacy %s found. Migrate to %s and remove the old file.",
            legacy, get_mcp_servers_path(),
        )


def _clear_cache() -> None:
    """Clear the config cache. For testing."""
    global _config_cache
    _config_cache = None


def get_mcp_servers_path() -> str:
    """Return path to mcp-servers.json config file."""
    return os.path.join(get_config_dir(), "mcp-servers.json")


def load_mcp_servers(use_cache: bool = True) -> dict[str, MCPServerConfig]:
    """Load all MCP server configs from ~/.config/crabcakes/mcp-servers.json.

    Args:
        use_cache: If True, cache loaded config (default). Clear with _clear_cache().

    Returns:
        Dict mapping server name → MCPServerConfig.
        
    Raises:
        FileNotFoundError: Config file doesn't exist.
        json.JSONDecodeError: Config is invalid JSON.
        MCPConfigError: Config is invalid (malformed types, bad names, etc.).
    """
    global _config_cache

    if use_cache and _config_cache is not None:
        return _config_cache

    _check_legacy_mcp_json()  # LOW-5

    config_path = get_mcp_servers_path()
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"MCP config not found: {config_path}")

    # MED-6: Check file ownership and permissions before reading
    try:
        from utils.file_security import assert_secure_file
        assert_secure_file(config_path)
    except (ImportError, FileNotFoundError):
        pass  # Allow read if security check is unavailable
    except PermissionError as e:
        logger.warning("MED-6: %s — proceeding with config read anyway", e)
    
    with open(config_path, "r", encoding="utf-8") as f:
        raw: Any = json.load(f)

    # BUG #5: Validate top-level JSON is a dict
    if not isinstance(raw, dict):
        raise MCPConfigError(f"Expected JSON object, got {type(raw).__name__}")

    # BUG #4: Validate servers key is a dict
    servers_data = raw.get("servers")
    if servers_data is None:
        servers_data = {}
    if not isinstance(servers_data, dict):
        raise MCPConfigError(f"'servers' must be an object, got {type(servers_data).__name__}")

    # Parse each server config
    servers: dict[str, MCPServerConfig] = {}
    
    for name, config in servers_data.items():
        # BUG #6: Validate server names (no /, no whitespace)
        if "/" in name or re.search(r"\s", name):
            raise MCPConfigError(f"Invalid server name '{name}': must not contain '/' or whitespace")

        # BUG #3: Validate each server config is a dict
        if not isinstance(config, dict):
            raise MCPConfigError(f"Server '{name}': expected object, got {type(config).__name__}")

        # Parse fields
        transport = config.get("transport", "stdio")
        command = config.get("command", "")
        desc = config.get("description", "")
        
        # BUG #1: Validate args is a list of strings
        args_raw = config.get("args", [])
        if args_raw is None:
            args = []
        elif not isinstance(args_raw, list):
            raise MCPConfigError(f"Server '{name}': 'args' must be array, got {type(args_raw).__name__}")
        else:
            args = []
            for i, arg in enumerate(args_raw):
                if not isinstance(arg, str):
                    raise MCPConfigError(
                        f"Server '{name}': args[{i}] must be string, got {type(arg).__name__}"
                    )
                args.append(arg)

        # BUG #7: Validate command for stdio transport
        if transport == "stdio" and not isinstance(command, str):
            raise MCPConfigError(f"Server '{name}': 'command' must be string, got {type(command).__name__}")

        # Env: validate if present
        env_raw = config.get("env")
        env: dict[str, str] | None = None
        if env_raw is not None:
            if not isinstance(env_raw, dict):
                raise MCPConfigError(f"Server '{name}': 'env' must be object, got {type(env_raw).__name__}")
            for k, v in env_raw.items():
                if not isinstance(v, str):
                    raise MCPConfigError(
                        f"Server '{name}': env.{k} must be string, got {type(v).__name__}"
                    )
            env = env_raw

        # BUG #9/#16 FIXED: enabled must be bool
        enabled_raw = config.get("enabled", True)
        if not isinstance(enabled_raw, bool):
            raise MCPConfigError(
                f"Server '{name}': 'enabled' must be boolean, got {type(enabled_raw).__name__}"
            )
        enabled = enabled_raw

        # Transport validation
        if transport not in ("stdio", "streamable-http"):
            raise MCPConfigError(f"Server '{name}': unknown transport '{transport}'")

        servers[name] = MCPServerConfig(
            name=name,
            transport=transport,
            command=command or "",
            args=args,
            env=env,
            description=desc or "",
            enabled=enabled,
        )

    if use_cache:
        _config_cache = servers

    return servers


def get_server_config(server_name: str) -> MCPServerConfig | None:
    """Get config for a specific MCP server.

    Args:
        server_name: Server name (e.g., "github")
        
    Returns:
        MCPServerConfig or None if not found.
    """
    servers = load_mcp_servers()
    return servers.get(server_name)


def is_server_enabled(server_name: str) -> bool:
    """Check if an MCP server is enabled.

    Args:
        server_name: Server name
        
    Returns:
        True if server exists and is enabled.
    """
    servers = load_mcp_servers()
    config = servers.get(server_name)
    return config is not None and config.enabled


def get_enabled_servers() -> list[str]:
    """Get list of enabled server names.

    Returns:
        List of enabled server names.
    """
    servers = load_mcp_servers()
    return [name for name, cfg in servers.items() if cfg.enabled]