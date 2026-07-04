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


# DUPLICATION INVARIANT: this set must match agent.runtime._PROVIDER_CALLERS.keys().
# Layer rule: utils/* cannot import from agent/*, so the set is duplicated here.
# Enforced by a regression test in tests/test_providers_store.py
# (TestValidCallersDuplicationInvariant). If you add a new adapter to
# agent.runtime._PROVIDER_CALLERS, you MUST also add the key here and update
# the regression test. See .crabcakes/task-specs/caller-validation.md.
_VALID_CALLERS: frozenset[str] = frozenset({
    "anthropic", "minimax", "openai", "openrouter", "zai",
})

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
        "default_max_tokens": p.default_max_tokens,
        "compaction_threshold": p.compaction_threshold,
        "last_verified_at": p.last_verified_at,
        "last_error": p.last_error,
    }


def _from_dict(d: dict[str, Any]) -> ProviderConfig:
    """Convert a plain dict to a ProviderConfig. Tolerates missing optional fields.

    Caller validation (caller-validation spec): if a non-empty caller field
    is present but is NOT in _VALID_CALLERS, log a warning and keep the value
    unchanged. Do NOT mutate — the load-time path is for surfacing legacy
    bad data, not for silent rewrites. Save-time validation in
    settings_handler.add_or_update prevents NEW bad data.
    """
    caller = d.get("caller", "")
    if caller and caller not in _VALID_CALLERS:
        _logger.warning(
            "providers.yaml: provider %r has invalid caller %r. "
            "Valid callers: %s. Auto-detect at save time will lower-case and "
            "validate, but load-time keeps the value unchanged. Fix the YAML "
            "or set caller explicitly via settings dialog.",
            d.get("name", "<unnamed>"), caller, sorted(_VALID_CALLERS),
        )
    return ProviderConfig(
        name=d.get("name", ""),
        base_url=d.get("base_url", ""),
        api_key=d.get("api_key", ""),
        default_model=d.get("default_model", ""),
        caller=caller,
        enabled=d.get("enabled", True),
        supports_tools=d.get("supports_tools", True),
        supports_streaming=d.get("supports_streaming", True),
        max_tokens=d.get("max_tokens", 128_000),
        default_max_tokens=d.get("default_max_tokens", 0),
        compaction_threshold=d.get("compaction_threshold", 0.80),
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


# ── KB provider auto-registration ─────────────────────────────────────────────


def remove_providers_from_agent_json() -> bool:
    """One-shot: remove legacy providers key from agent.json.

    Idempotent — returns True if removed, False if key was not present.
    Uses atomic .tmp + chmod 0o600 write, matching save_provider pattern.
    """
    from utils.config import get_config_dir
    agent_json_path = os.path.join(get_config_dir(), "agent.json")

    if not os.path.isfile(agent_json_path):
        return False

    try:
        with open(agent_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.debug("remove_providers_from_agent_json: cannot read agent.json: %s", e)
        return False

    if "providers" not in raw:
        return False

    del raw["providers"]

    # Atomic write: .tmp → rename → chmod 0o600
    tmp_path = agent_json_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=4, ensure_ascii=False)
        os.rename(tmp_path, agent_json_path)
        os.chmod(agent_json_path, 0o600)
        _logger.info("removed legacy providers key from agent.json")
        return True
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def migrate_from_agent_json() -> int:
    """One-time migration: copy agent.json providers → providers.yaml.

    Reads the legacy `providers` key from agent.json. For each entry,
    converts to a ProviderConfig and merges into providers.yaml. YAML wins
    on name conflict (it's the current source of truth). Safe to call
    multiple times — idempotent after first migration.

    After migrating, removes the `providers` key from agent.json so the
    legacy store is fully consolidated into providers.yaml.

    Returns the count of providers migrated.
    """
    from utils.config import get_config_dir
    agent_json_path = os.path.join(get_config_dir(), "agent.json")

    if not os.path.isfile(agent_json_path):
        return 0

    try:
        with open(agent_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.debug("migrate_from_agent_json: cannot read agent.json: %s", e)
        return 0

    providers_dict = raw.get("providers")
    has_providers_key = "providers" in raw
    if not providers_dict or not isinstance(providers_dict, dict) or len(providers_dict) == 0:
        # No providers to migrate, but strip the empty/missing key so agent.json is clean
        if has_providers_key:
            remove_providers_from_agent_json()
        return 0

    # Convert legacy agent.json entries to ProviderConfig
    migrated = []
    for name, cfg in providers_dict.items():
        if not isinstance(cfg, dict):
            continue
        try:
            migrated.append(ProviderConfig(
                name=name,
                base_url=cfg.get("base_url", ""),
                api_key=cfg.get("api_key", ""),
                default_model=cfg.get("default_model", ""),
                caller=cfg.get("caller", ""),
                supports_tools=cfg.get("supports_tools", True),
                supports_streaming=cfg.get("supports_streaming", True),
                max_tokens=cfg.get("max_tokens", 128_000),
            ))
        except (KeyError, TypeError) as e:
            _logger.warning("migrate_from_agent_json: skipping malformed entry %s: %s", name, e)
            continue

    if not migrated:
        return 0

    # Merge with existing YAML providers (YAML wins on name conflict)
    yaml_providers = load_providers()
    yaml_names = {p.name for p in yaml_providers}
    added_count = 0
    for p in migrated:
        if p.name not in yaml_names:
            yaml_providers.append(p)
            added_count += 1
            _logger.debug("migrate_from_agent_json: added %s from agent.json", p.name)

    save_providers(yaml_providers)
    # 1b: strip the providers key from agent.json after successful migration
    remove_providers_from_agent_json()
    _logger.info("migrated %d providers from agent.json to providers.yaml", added_count)
    return added_count


def ensure_kb_provider() -> None:
    """Seed the local-kb provider into providers.yaml if missing.

    Idempotent — safe to call on every startup. If a provider named
    'local-kb' already exists, this is a no-op for the provider.

    Also ensures the Auxilium (helper) agent is configured to use
    local-kb as its primary provider if it has no provider set.
    This enables a fresh-install user to get KB-backed help without
    any manual configuration.

    The local-kb provider wraps the KB HTTP server (agent/kb_server.py)
    and presents an OpenAI-compatible API on localhost:18790. It enables
    the Auxilium agent to answer questions from the local knowledge base
    without requiring an external LLM.
    """
    migrate_from_agent_json()
    _ensure_kb_provider_entry()
    _ensure_auxilium_uses_kb()


def _ensure_kb_provider_entry() -> None:
    """Seed or repair the local-kb provider in providers.yaml."""
    providers = load_providers()

    # Check if local-kb already exists
    existing = next((p for p in providers if p.name == "local-kb"), None)
    if existing is not None:
        # Repair: only fix the caller field if it's empty (the bug that caused runtime errors).
        # Don't touch other fields — respect user customizations (custom port, etc).
        if not existing.caller:
            existing.caller = "openai"
            save_providers(providers)
            _logger.info("ensure_kb_provider: repaired missing caller field on local-kb provider")
        return

    # Not found — create fresh
    kb_provider = ProviderConfig(
        name="local-kb",
        base_url="http://localhost:18790/v1",
        api_key="***",          # placeholder — KB server doesn't check auth
        default_model="local-kb",
        caller="openai",          # OpenAI-compatible API format
        supports_tools=False,     # KB server never calls tools
        supports_streaming=False, # blocking only
        max_tokens=4096,
    )
    providers.append(kb_provider)
    save_providers(providers)
    _logger.info("ensure_kb_provider: seeded local-kb provider into providers.yaml")


def _ensure_auxilium_uses_kb() -> None:
    """Ensure the Auxilium (helper) agent uses local-kb as its provider.

    On fresh install (no real providers configured), force the helper agent
    to use local-kb so it works out of the box.

    On existing installs where the user has configured real providers, only
    patch if the agent has no llm_name at all (respect user's explicit choice).
    """
    try:
        from utils.agent_defs import load_agent_def_by_role, save_agent_def

        agent_def = load_agent_def_by_role("helper")
        if agent_def is None:
            return  # No helper agent defined — nothing to patch

        llm_name = agent_def.get("llm_name", "")
        if llm_name == "local-kb":
            return  # Already correct

        # Check if user has real providers configured (beyond just local-kb)
        providers = load_providers()
        has_real_providers = any(p.name != "local-kb" for p in providers)

        if has_real_providers and llm_name:
            # User has real providers AND explicitly chose one for Auxilium — respect it
            return

        # No real providers (fresh install) or no llm_name set → use local-kb
        agent_def["llm_name"] = "local-kb"
        # Remove stale provider/model fields that conflict
        agent_def.pop("provider", None)
        agent_def.pop("model", None)
        # LOW-11: also ensure a fallback is set so validation passes. Prefer a
        # real cloud provider the user has configured; fall back to openrouter
        # as a sensible default for fresh installs.
        if not agent_def.get("fallback_provider"):
            real_fallbacks = [p.name for p in providers if p.name != "local-kb"]
            if real_fallbacks:
                agent_def["fallback_provider"] = real_fallbacks[0]
            else:
                agent_def["fallback_provider"] = "openrouter"
        save_agent_def(agent_def)
        _logger.info("ensure_kb_provider: set Auxilium agent to use local-kb provider")
    except Exception as e:
        _logger.warning("ensure_kb_provider: failed to patch Auxilium agent: %s", e)
