# utils/providers_store.py
# Provider YAML persistence — load/save/add/remove/update for providers.yaml.
# Pure functions — no GTK, no state, no network.
#
# Manifest:
#   - Reads: <config_dir>/providers.yaml (or .json fallback)
#   - Writes: <config_dir>/providers.yaml (atomic, chmod 0o600)
#   - Network: none
#   - Imports: stdlib only (yaml if available, else json); models.providers
#
# Architecture: mirrors utils/feed_store.py and utils/agent_defs.py patterns.
# Path resolution uses utils.config.get_config_dir() — never hardcoded paths.

from __future__ import annotations

import json
import logging
import os
from typing import Any

from models.providers import ProviderConfig

_logger = logging.getLogger(__name__)

_FILENAME = "providers.yaml"


def get_providers_path() -> str:
    """Return absolute path to providers.yaml under config dir.
    Does NOT create the file."""
    from utils.config import get_config_dir
    return os.path.join(get_config_dir(), _FILENAME)


def _to_dict(p: ProviderConfig) -> dict[str, Any]:
    """Convert a ProviderConfig to a plain dict for serialization."""
    return {
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,
        "default_model": p.default_model,
        "caller": p.caller,
        "enabled": p.enabled,
        "supports_tools": p.supports_tools,
        "supports_streaming": p.supports_streaming,
        "max_tokens": p.max_tokens,
        "last_verified_at": p.last_verified_at,
        "last_error": p.last_error,
    }


def _from_dict(d: dict[str, Any]) -> ProviderConfig:
    """Convert a plain dict to a ProviderConfig. Tolerates missing optional fields."""
    return ProviderConfig(
        name=d.get("name", ""),
        base_url=d.get("base_url", ""),
        api_key=d.get("api_key", ""),
        default_model=d.get("default_model", ""),
        caller=d.get("caller", ""),
        enabled=d.get("enabled", True),
        supports_tools=d.get("supports_tools", True),
        supports_streaming=d.get("supports_streaming", True),
        max_tokens=d.get("max_tokens", 128_000),
        last_verified_at=d.get("last_verified_at"),
        last_error=d.get("last_error"),
    )


def _serialize(providers: list[ProviderConfig]) -> str:
    """Serialize providers list to YAML or JSON string."""
    items = [_to_dict(p) for p in providers]
    try:
        import yaml
        return yaml.dump(items, default_flow_style=False, allow_unicode=True)
    except ImportError:
        return json.dumps(items, indent=2, ensure_ascii=False)


def _parse(text: str) -> list[ProviderConfig]:
    """Parse YAML or JSON text into a list of ProviderConfig.
    Tolerates malformed content — returns [] with a warning."""
    raw: Any = None
    try:
        import yaml
        raw = yaml.safe_load(text)
    except ImportError:
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            _logger.warning("providers_store: failed to parse: %s", e)
            return []
    except Exception as e:
        _logger.warning("providers_store: YAML parse error: %s", e)
        return []

    if raw is None:
        return []
    if not isinstance(raw, list):
        _logger.warning("providers_store: expected list, got %s", type(raw).__name__)
        return []

    providers: list[ProviderConfig] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            _logger.warning("providers_store: skipping non-dict entry %d", i)
            continue
        try:
            providers.append(_from_dict(item))
        except (KeyError, TypeError) as e:
            _logger.warning("providers_store: skipping malformed entry %d: %s", i, e)
    return providers


def load_providers() -> list[ProviderConfig]:
    """Read providers.yaml → list[ProviderConfig]. Empty list if missing.
    Tolerates malformed lines (logs warning, skips)."""
    path = get_providers_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        _logger.warning("providers_store: failed to read %s: %s", path, e)
        return []
    return _parse(text)


def save_providers(providers: list[ProviderConfig]) -> None:
    """Write list[ProviderConfig] → providers.yaml. Creates parent dir.
    File is written with mode 0o600 (owner-only — contains API keys).
    Parent dir is chmod 0o700 if created.
    Atomic: writes to .tmp then renames."""
    path = get_providers_path()
    parent = os.path.dirname(path)

    # Create parent dir with restricted permissions if it doesn't exist
    parent_existed = os.path.isdir(parent)
    if not parent_existed:
        os.makedirs(parent, exist_ok=True)

    # Atomic write: .tmp → rename
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(_serialize(providers))
        os.rename(tmp_path, path)
    except Exception:
        # Clean up tmp on failure
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise

    # Set file permissions — owner only (contains API keys)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # non-POSIX filesystem

    # Set parent dir permissions if we just created it
    if not parent_existed:
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass


def add_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None:
    """Append-and-save. Replaces existing entry with the same name."""
    # Remove existing with same name, then append
    filtered = [x for x in providers if x.name != p.name]
    filtered.append(p)
    save_providers(filtered)


def remove_provider(providers: list[ProviderConfig], name: str) -> None:
    """Remove-by-name-and-save. No-op if not found."""
    filtered = [x for x in providers if x.name != name]
    save_providers(filtered)


def update_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None:
    """Replace existing entry with same name. Adds if new."""
    add_provider(providers, p)


def has_any_verified_provider(providers: list[ProviderConfig]) -> bool:
    """True if at least one provider has last_verified_at set. Drives the red dot."""
    return any(p.last_verified_at is not None for p in providers)
