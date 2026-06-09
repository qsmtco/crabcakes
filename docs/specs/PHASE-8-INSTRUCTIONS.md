# PHASE 8 of 9 — Test gap fill + small `agent/config.py` behavior addition

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.10 (verify), §2.11 (verify), §2.14 (verify), §2.15 (fill test gap).

## State of the world entering Phase 8

After Phases 1-7, the spec is **mostly done**. What remains:

| Spec section | Status | Phase 8 action |
|--------------|--------|----------------|
| §2.10 `ui/views/agent_builder.py` REVISED (Phase C) | ⏸ Explicitly deferred to Phase C | **No work** — verified. |
| §2.11 `ui/handlers/agent_builder_handler.py` REVISED | ✅ No-op (verification only) | **No work** — verified. |
| §2.14 `utils/agent_defs.py` REVISED | ✅ Done (verified: `get_available_providers` reads from `providers.yaml`, `validate_agent_def` already has the comment "API keys are validated at config time") | **No work** — verified. |
| §2.15 Tests | ⚠️ 2 of 6 test files missing | **Fill the gap.** |
| §2.15 "writes empty providers.yaml when neither exists" | ❌ Behavior not implemented in `agent/config.py` | **Add it.** |
| §2.16 Files NOT changed | N/A | **Verify only.** |

## Files to change

1. `agent/config.py` — REVISED. Add a small `ensure_providers_yaml_exists()` helper that creates an empty `providers.yaml` if no providers config exists. Call it from `load_agent_config()` when `agent.json` has no `providers` section AND `providers.yaml` is missing. (~15 lines)
2. `tests/test_agent_config_yaml_fallback.py` — NEW. Tests the three paths of `_load_providers_from_yaml_or_fallback` + the new `ensure_providers_yaml_exists` behavior. (~100 lines, 4 classes, ~10 tests)
3. `tests/test_agent_builder_no_provider_keys.py` — NEW. Tests that `validate_agent_def` no longer requires `api_key`/`provider_keys`. Tests for `agent_builder_dialog.get_values()` are EXPECTED TO BE MARKED as `xfail` or `skip` because the `provider_keys` removal is **Phase C work** (out of scope for Phase 8). The Phase 8 deliverable is: the test file exists, the validation tests pass, and the `provider_keys` removal tests are marked as `xfail` with a clear comment pointing to Phase C. (~60 lines, 2 classes, ~6 tests)

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT modify `ui/views/agent_builder.py`** — that is Phase C work. You write tests that **document expected post-Phase-C behavior** with `xfail` markers.
- **Do NOT modify `ui/handlers/agent_builder_handler.py`** — §2.11 is a no-op.
- **Do NOT modify `utils/agent_defs.py`** — §2.14 is already done.
- **Do NOT modify `ui/window.py`, `ui/wiring.py`, `ui/handlers/settings_handler.py`, `ui/views/settings_dialog.py`, `ui/toolbar.py`, `ui/styles.py`** — Phases 4-7 are complete and audited.
- **The new helper `ensure_providers_yaml_exists()` in `agent/config.py`** must NOT overwrite an existing `providers.yaml` or `agent.json` `providers` section. It only creates `providers.yaml` if both sources are absent.
- **Use `tests/conftest.py:tmp_config_dir` fixture** for all tests.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.15 (the missing test requirements)
2. `agent/config.py` lines 140-225 (the existing `_load_providers_from_yaml_or_fallback` and `load_agent_config`)
3. `agent/config.py` lines 252-298 (`_create_default_config` — the pattern for safe file creation)
4. `utils/providers_store.py` (full file — especially `load_providers`, `save_providers`, and the file format)
5. `utils/agent_defs.py` lines 312-385 (`validate_agent_def` — verify the api_key/provider_keys check is gone)
6. `ui/views/agent_builder.py` lines 195-220 (`get_values()` — verify `provider_keys` is still there so you know to xfail that test)
7. `tests/conftest.py` (the `tmp_config_dir` fixture)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 8.1: `agent/config.py` — add `ensure_providers_yaml_exists()`

Add the following helper function near `_create_default_config` (around line 252). It must:
- Check if `providers.yaml` exists at `<config_dir>/providers.yaml`
- Check if `agent.json` has a `providers` section
- If neither exists: create an empty `providers.yaml` (just `[]` or `providers: []` — match the yaml format used by `utils/providers_store`)
- If either exists: do nothing
- Be safe to call multiple times (idempotent)
- Set file mode 0o600 (owner-only, matches `providers_store.py`'s convention)

```python
def ensure_providers_yaml_exists(config_path: str) -> str:
    """Ensure providers.yaml exists in the same directory as agent.json.
    
    Called on startup if neither providers.yaml nor agent.json's providers
    section has any provider entries. Creates an empty providers.yaml so
    the UI's Settings dialog has a file to write to.
    
    Returns the path to providers.yaml.
    """
    dir_path = os.path.dirname(config_path)
    yaml_path = os.path.join(dir_path, "providers.yaml")
    
    # Don't overwrite an existing providers.yaml
    if os.path.isfile(yaml_path):
        return yaml_path
    
    # Don't create providers.yaml if agent.json has a providers section —
    # that's the fallback path; user must explicitly migrate via Settings.
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if raw.get("providers"):
                return yaml_path
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Could not read agent.json: %s", e)
    
    # Create empty providers.yaml
    try:
        os.makedirs(dir_path, exist_ok=True)
        # Match the format used by utils/providers_store.save_providers
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("providers: []\n")
        os.chmod(yaml_path, 0o600)
        logger.info("Created empty providers.yaml at %s", yaml_path)
    except OSError as e:
        logger.warning("Could not create providers.yaml at %s: %s", yaml_path, e)
    
    return yaml_path
```

**Also modify `load_agent_config()` (line 187)** to call this helper at the end if the parsed config has no providers:

```python
def load_agent_config(config_path: str | None = None) -> AgentConfig:
    """... (existing docstring) ..."""
    # ... existing code through line 222 ...
    
    # Phase 8: if no providers were loaded from either source, ensure
    # providers.yaml exists so the Settings dialog has a place to write.
    if not providers:
        ensure_providers_yaml_exists(config_path)
    
    return AgentConfig(
        # ... existing code ...
    )
```

**Note on placement:** The call goes AFTER the providers dict is built, but BEFORE the `return AgentConfig(...)`. The simplest insertion is a single `if not providers: ensure_providers_yaml_exists(config_path)` line right before the `return`.

**Imports:** `os`, `json`, and `logger` are already imported at the top of `agent/config.py`. No new imports needed.

## SUB-PHASE 8.2: `tests/test_agent_config_yaml_fallback.py` (new test file)

Test the three loading paths of `_load_providers_from_yaml_or_fallback` plus the new `ensure_providers_yaml_exists` behavior.

```python
# tests/test_agent_config_yaml_fallback.py
# Tests for agent/config.py — verifies that load_agent_config uses providers.yaml
# (canonical) when present, falls back to agent.json providers section (with
# deprecation warning) when providers.yaml is empty, and creates an empty
# providers.yaml when neither source has providers.

import json
import os
import pytest

from agent.config import (
    _load_providers_from_yaml_or_fallback,
    ensure_providers_yaml_exists,
    load_agent_config,
    get_config_dir,
)
from utils.providers_store import save_providers, load_providers
from models.providers import ProviderConfig


def _make_provider(name="openai", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name, base_url=f"https://api.{name}.example.com/v1",
        api_key=*** default_model=f"{name}/default-model",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestProvidersYamlCanonical:
    def test_yaml_used_when_present(self, tmp_config_dir):
        """providers.yaml is the canonical source when it has providers."""
        save_providers([_make_provider("p1"), _make_provider("p2")])
        # Create a minimal agent.json
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({"providers": {"legacy": {}}}))
        # Load and check
        config = load_agent_config(str(agent_json))
        assert "p1" in config.providers
        assert "p2" in config.providers
        assert "legacy" not in config.providers  # agent.json ignored when yaml present

    def test_yaml_takes_precedence_over_agent_json(self, tmp_config_dir, caplog):
        """If both exist, yaml wins, agent.json is silently ignored (no warning)."""
        save_providers([_make_provider("yamlprov")])
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({
            "providers": {"jsonprov": {"base_url": "x", "api_key": "y"}}
        }))
        with caplog.at_level("WARNING"):
            config = load_agent_config(str(agent_json))
        # yaml wins
        assert "yamlprov" in config.providers
        assert "jsonprov" not in config.providers
        # No deprecation warning
        assert "deprecated" not in caplog.text


class TestAgentJsonFallback:
    def test_fallback_to_agent_json_when_yaml_empty(self, tmp_config_dir, caplog):
        """If providers.yaml is empty, fall back to agent.json providers."""
        # Empty providers.yaml
        providers_yaml = tmp_config_dir / "providers.yaml"
        providers_yaml.write_text("providers: []\n")
        # agent.json with a provider
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({
            "providers": {"legacyprov": {
                "base_url": "https://legacy.example.com/v1",
                "api_key": "key",
                "default_model": "legacy-model",
            }}
        }))
        with caplog.at_level("WARNING"):
            config = load_agent_config(str(agent_json))
        assert "legacyprov" in config.providers
        # Deprecation warning was logged
        assert "deprecated" in caplog.text

    def test_fallback_when_yaml_missing(self, tmp_config_dir, caplog):
        """If providers.yaml doesn't exist, fall back to agent.json."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({
            "providers": {"legacyprov": {
                "base_url": "https://x", "api_key": "k", "default_model": "m",
            }}
        }))
        with caplog.at_level("WARNING"):
            config = load_agent_config(str(agent_json))
        assert "legacyprov" in config.providers

    def test_empty_when_both_missing(self, tmp_config_dir):
        """If neither source has providers, return empty dict."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({}))
        config = load_agent_config(str(agent_json))
        assert config.providers == {}


class TestEnsureProvidersYamlExists:
    def test_creates_empty_yaml_when_neither_exists(self, tmp_config_dir):
        """First-run state: creates empty providers.yaml."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({}))
        yaml_path = ensure_providers_yaml_exists(str(agent_json))
        assert os.path.isfile(yaml_path)
        # Verify it's a valid empty list
        from utils.providers_store import load_providers
        assert load_providers() == []

    def test_does_not_overwrite_existing_yaml(self, tmp_config_dir):
        """If providers.yaml already exists, do not touch it."""
        save_providers([_make_provider("existing")])
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({}))
        yaml_path = ensure_providers_yaml_exists(str(agent_json))
        from utils.providers_store import load_providers
        assert len(load_providers()) == 1
        assert load_providers()[0].name == "existing"

    def test_does_not_create_when_agent_json_has_providers(self, tmp_config_dir):
        """If agent.json has providers, do not create providers.yaml."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({
            "providers": {"legacy": {
                "base_url": "https://x", "api_key": "k", "default_model": "m",
            }}
        }))
        yaml_path = ensure_providers_yaml_exists(str(agent_json))
        assert not os.path.isfile(yaml_path), "Should not create yaml when agent.json has providers"

    def test_yaml_permissions(self, tmp_config_dir):
        """Created providers.yaml has 0o600 permissions."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({}))
        yaml_path = ensure_providers_yaml_exists(str(agent_json))
        mode = os.stat(yaml_path).st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_idempotent(self, tmp_config_dir):
        """Calling twice is safe — does not overwrite or error."""
        agent_json = tmp_config_dir / "agent.json"
        agent_json.write_text(json.dumps({}))
        path1 = ensure_providers_yaml_exists(str(agent_json))
        path2 = ensure_providers_yaml_exists(str(agent_json))
        assert path1 == path2
        from utils.providers_store import load_providers
        assert load_providers() == []


class TestLoadAgentConfigIntegration:
    def test_creates_yaml_on_first_run(self, tmp_config_dir):
        """load_agent_config on a brand-new install creates empty providers.yaml."""
        # No agent.json, no providers.yaml
        config = load_agent_config()  # uses default path
        # agent.json should now exist (default config)
        # providers.yaml should now exist (empty)
        from utils.providers_store import load_providers
        assert load_providers() == []

    def test_load_returns_config_with_no_providers(self, tmp_config_dir):
        """After first-run, load_agent_config returns a valid config with empty providers."""
        config = load_agent_config()
        assert hasattr(config, "providers")
        assert config.providers == {}
```

**Note:** The integration test `test_creates_yaml_on_first_run` calls `load_agent_config()` with no args, which uses the default `get_config_dir()`. The `tmp_config_dir` fixture monkeypatches `HOME` to a temp dir, so this should work — but if the default config dir is not derived from `HOME` in this version, the test may need adjustment. **QTR: verify this works. If it doesn't, modify the test to explicitly pass a `config_path` to a temp file, and add a TODO comment.**

## SUB-PHASE 8.3: `tests/test_agent_builder_no_provider_keys.py` (new test file)

This file has two halves: tests that PASS now (for the `validate_agent_def` part, which is already done) and tests that are EXPECTED TO FAIL (`xfail` markers, for the `get_values()` part, which is Phase C work).

```python
# tests/test_agent_builder_no_provider_keys.py
# Tests that the agent builder no longer requires api_key/provider_keys.
#
# Phase 8 scope: validate_agent_def no longer requires api_key/provider_keys
# (verified — done in earlier phase).
#
# Phase C scope (deferred): agent_builder.get_values() should NOT include
# provider_keys in output, and the API key field should be removed from the
# form. These tests are marked xfail until Phase C.

import pytest
from utils.agent_defs import validate_agent_def


class TestValidateAgentDef:
    """validate_agent_def should NOT require api_key or provider_keys (Phase 8)."""

    def _valid_def(self, **overrides) -> dict:
        base = {
            "name": "test-agent",
            "provider": "openai",
            "model": "gpt-4o",
            "prompts": ["default"],
            "tools": ["read"],
        }
        base.update(overrides)
        return base

    def test_no_api_key_is_ok(self):
        """An agent def without api_key should validate successfully."""
        agent_def = self._valid_def()  # no api_key, no provider_keys
        errors = validate_agent_def(agent_def)
        # No 'API key required' error
        assert not any("api_key" in e.lower() for e in errors), \
            f"Unexpected api_key error: {errors}"

    def test_no_provider_keys_is_ok(self):
        """An agent def without provider_keys dict should validate successfully."""
        agent_def = self._valid_def()  # no provider_keys
        errors = validate_agent_def(agent_def)
        assert not any("provider_keys" in e.lower() for e in errors), \
            f"Unexpected provider_keys error: {errors}"

    def test_with_api_key_still_validates(self):
        """If api_key is present (legacy data), validation should still pass."""
        agent_def = self._valid_def(api_key="sk-test")
        errors = validate_agent_def(agent_def)
        # Should not error on api_key (it's just an unused field now)
        assert not any("api_key" in e.lower() and "required" in e.lower() for e in errors)

    def test_missing_provider_still_errors(self):
        """Provider is still required."""
        agent_def = self._valid_def(provider="")
        errors = validate_agent_def(agent_def)
        assert any("provider" in e.lower() for e in errors)

    def test_missing_name_still_errors(self):
        """Name is still required."""
        agent_def = self._valid_def(name="")
        errors = validate_agent_def(agent_def)
        assert any("name" in e.lower() for e in errors)


class TestAgentBuilderGetValuesPhaseC:
    """These tests are for Phase C work (ui/views/agent_builder.py revision).
    They are EXPECTED TO FAIL until Phase C is complete.
    Marked xfail with a clear reason pointing to spec §2.10.
    """

    @pytest.mark.xfail(
        reason="Phase C work — agent_builder.get_values() still includes provider_keys. See spec §2.10.",
        strict=True,  # If this accidentally passes, the test errors (catches the unexpected success)
    )
    def test_get_values_does_not_include_provider_keys(self):
        from ui.views.agent_builder import AgentBuilderDialog
        # Construct a dialog (we don't need to show it)
        dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
        values = dlg.get_values()
        assert "provider_keys" not in values, \
            f"Expected provider_keys removed, but got: {list(values.keys())}"

    @pytest.mark.xfail(
        reason="Phase C work — API key field is still in the form. See spec §2.10.",
        strict=True,
    )
    def test_api_key_field_removed(self):
        from ui.views.agent_builder import AgentBuilderDialog
        dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
        assert not hasattr(dlg, "_api_key_entry"), \
            "Expected _api_key_entry removed from form"
```

**Important:** The `strict=True` on `xfail` means if the test ACCIDENTALLY passes, pytest will error. This is intentional — it catches the case where Phase C work is done but the test file is not updated. When Phase C is complete, QTR (or a future maintainer) should remove the `xfail` markers and the tests will then PASS, confirming Phase C.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# 8.1: imports still ok after agent/config.py changes
python3 -c "from agent.config import load_agent_config, ensure_providers_yaml_exists, _load_providers_from_yaml_or_fallback; print('imports ok')"
echo "---"

# 8.1: helper exists with correct name
grep -n "def ensure_providers_yaml_exists" agent/config.py
echo "---"

# 8.1: helper called from load_agent_config
grep -B1 -A2 "ensure_providers_yaml_exists(config_path)" agent/config.py
echo "---"

# 8.2: new test file passes
python3 -m pytest tests/test_agent_config_yaml_fallback.py -v --tb=short 2>&1 | tail -30
echo "---"

# 8.3: new test file — most pass, two xfail
python3 -m pytest tests/test_agent_builder_no_provider_keys.py -v --tb=short 2>&1 | tail -20
echo "---"

# 8.2/8.3: test count progression
python3 -m pytest tests/test_agent_config_yaml_fallback.py tests/test_agent_builder_no_provider_keys.py --collect-only -q 2>&1 | tail -5
echo "---"

# 8.2/8.3: full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

## Acceptance criteria for this phase

- [ ] `agent/config.py` defines `ensure_providers_yaml_exists(config_path: str) -> str` (15 lines, idempotent, 0o600 perms)
- [ ] `load_agent_config()` calls `ensure_providers_yaml_exists(config_path)` when `providers` is empty
- [ ] `tests/test_agent_config_yaml_fallback.py` exists with 4 classes / 8+ tests
- [ ] `tests/test_agent_builder_no_provider_keys.py` exists with 2 classes / 5+ tests
- [ ] The Phase C tests in the second file are marked `xfail(strict=True)` with reasons
- [ ] All passing tests pass; xfail tests are reported as xfail (not error)
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 8 of 9 — COMPLETE

Files changed:
- agent/config.py — REVISED, +N / -M lines (paste git diff --stat)
- tests/test_agent_config_yaml_fallback.py — NEW, +N lines (paste wc -l)
- tests/test_agent_builder_no_provider_keys.py — NEW, +N lines (paste wc -l)

Verification (paste outputs of every command listed above):
- 8.1 imports ok: ...
- 8.1 helper exists: ...
- 8.1 helper called from load_agent_config: ...
- 8.2 test file passes: ...
- 8.3 test file passes (with xfail): ...
- 8.2/8.3 test counts: ...
- full test suite: ...

**COMPLETENESS:**
- [x] 8.1 ensure_providers_yaml_exists exists — evidence: <grep>
- [x] 8.1 load_agent_config calls it — evidence: <grep>
- [x] 8.2 test file has 4+ classes / 8+ tests — evidence: <pytest --collect-only>
- [x] 8.2 all tests pass — evidence: <pytest tail>
- [x] 8.3 test file has 2+ classes / 5+ tests — evidence: <pytest --collect-only>
- [x] 8.3 validation tests pass — evidence: <pytest tail>
- [x] 8.3 Phase C tests marked xfail(strict=True) — evidence: <grep -A1 xfail>
- [x] 8.3 xfail tests reported as xfail not error — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs)

**Implementation choices made:**
- (e.g. "created providers.yaml format as 'providers: []' to match providers_store.save_providers")
- (e.g. "Phase C tests use strict=True to catch accidental success")
- (list other choices)
```

When done, please write: `Phase 8 complete — ready for audit.`
