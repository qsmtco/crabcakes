# Phase 5 — New tests per SPEC §2.5

**Spec:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §2.5

## Context

Phases 1–4 wired the agent builder, fixed `set_provider_options` types, populated the dropdown at construction, and removed dead Model/Manual/API-key widgets. The spec requires NEW tests covering:
1. The dialog's dropdown is populated at construction (not "(loading...)")
2. The dialog has no Model dropdown, no Manual entry, no API key field
3. Save button enables without an API key

Two new test files: `tests/test_agent_builder_dialog.py` and `tests/test_agent_builder_no_model_dropdown.py`.

## Files to change

1. `tests/test_agent_builder_dialog.py` (NEW — create)
2. `tests/test_agent_builder_no_model_dropdown.py` (NEW — create)
3. `tests/test_window_settings_wiring.py` (REVISED — add the spec test from §2.5 if not already present)

## Rules

- Use the steelFramedCodeWriter prompt at `prompts/steelFramedCodeWriter.md` exactly
- Follow existing test patterns in the repo — see `tests/test_agent_builder_no_provider_keys.py` and `tests/test_window_settings_wiring.py` for style
- Do NOT change any other file
- Do NOT add tests to `tests/test_agent_builder_handler.py` (the spec marks it as REVISED but the revision is just "ensure existing tests continue to pass" — they already do)

## File 1: `tests/test_agent_builder_dialog.py` (NEW)

Create a new test file that covers:
- The dropdown is populated from `handler.get_provider_options()` at construction
- The dropdown does NOT show "(loading...)" when providers exist
- The dropdown shows "(no providers — open Settings)" when handler returns empty list
- `get_values()` returns the selected provider name (and `model: ""`)

Use the existing `StubHandler` pattern from `tests/test_agent_builder_no_provider_keys.py` (lines 21-31) — a stub with `get_provider_options` returning a list of dicts.

The dialog needs a real `Gtk.Window` parent — use a `Gtk.ApplicationWindow(application=Gtk.Application())` like the smoke test in Phase 4.

```python
# tests/test_agent_builder_dialog.py
"""Tests for AgentBuilderDialog — provider dropdown population at construction.

Refs: docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md §2.5
"""

import gi
gi.require_version('Gtk', '4.0')

import pytest
from gi.repository import Gtk

from models.providers import ProviderConfig
import utils.providers_store as ps


class StubHandler:
    """Stub AgentBuilderHandler — returns canned provider options."""
    def __init__(self, providers):
        self._providers = providers
    def get_prompt_options(self):
        return []
    def get_tool_options(self):
        return []
    def get_provider_options(self):
        # Return list[dict] matching the shape get_provider_options() returns
        return [
            {"name": p.name, "base_url": p.base_url, "default_model": p.default_model,
             "enabled": p.enabled, "api_***ey": p.api_key}
            for p in self._providers
        ]
    def get_mcp_options(self):
        return []


@pytest.fixture
def gtk_parent():
    """A real Gtk.ApplicationWindow for use as a dialog parent."""
    app = Gtk.Application()
    win = Gtk.ApplicationWindow(application=app)
    return win


def _make_dlg(parent, providers, agent_def=None):
    handler = StubHandler(providers)
    from ui.views.agent_builder import AgentBuilderDialog
    return AgentBuilderDialog(parent=parent, handler=handler, agent_def=agent_def)


class TestProviderDropdownPopulation:
    """The dropdown is populated at construction from handler.get_provider_options()."""

    def test_dropdown_populated_with_provider_names(self, gtk_parent):
        """Two providers → dropdown has two entries with their names."""
        providers = [
            ProviderConfig("openai", "u", "k", "gpt-4o", True),
            ProviderConfig("anthropic", "u", "k", "c", True),
        ]
        dlg = _make_dlg(gtk_parent, providers)
        model = dlg._provider_dropdown.get_model()
        assert model.get_n_items() == 2
        assert model.get_string(0) == "openai"
        assert model.get_string(1) == "anthropic"

    def test_dropdown_does_not_show_loading_when_providers_exist(self, gtk_parent):
        """The first item is NOT '(loading...)' when providers exist."""
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        first = dlg._provider_dropdown.get_model().get_string(0)
        assert first != "(loading...)"

    def test_dropdown_shows_no_providers_message_when_empty(self, gtk_parent):
        """When handler returns empty, dropdown shows the 'no providers' hint."""
        dlg = _make_dlg(gtk_parent, [])
        model = dlg._provider_dropdown.get_model()
        assert model.get_n_items() == 1
        assert model.get_string(0) == "(no providers — open Settings)"

    def test_get_values_returns_selected_provider(self, gtk_parent):
        """get_values() returns the selected provider name as a string."""
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        dlg._name_entry.set_text("test-agent")
        values = dlg.get_values()
        assert values["provider"] == "openai"
        assert values["model"] == ""  # resolved at runtime
        assert "provider_keys" not in values
        assert "api_key" not in values
```

## File 2: `tests/test_agent_builder_no_model_dropdown.py` (NEW)

Create a new test file that covers:
- The dialog has NO `_model_dropdown` attribute
- The dialog has NO `_manual_provider_entry` or `_manual_toggle` attribute
- The dialog has NO `_api_key_entry` attribute
- Save button enables when name + prompts + tools + provider are all set, WITHOUT an API key

```python
# tests/test_agent_builder_no_model_dropdown.py
"""Tests that the Agent Builder form has no Model dropdown, no Manual entry,
no API key field, and Save enables without an API key.

Refs: docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md §2.5
"""

import gi
gi.require_version('Gtk', '4.0')

import pytest
from gi.repository import Gtk

from models.providers import ProviderConfig


class StubHandler:
    def __init__(self, providers):
        self._providers = providers
    def get_prompt_options(self):
        return ["p1", "p2"]
    def get_tool_options(self):
        return ["read", "write"]
    def get_provider_options(self):
        return [
            {"name": p.name, "base_url": p.base_url, "default_model": p.default_model,
             "enabled": p.enabled, "api_***ey": p.api_key}
            for p in self._providers
        ]
    def get_mcp_options(self):
        return []


@pytest.fixture
def gtk_parent():
    app = Gtk.Application()
    win = Gtk.ApplicationWindow(application=app)
    return win


def _make_dlg(parent, providers):
    handler = StubHandler(providers)
    from ui.views.agent_builder import AgentBuilderDialog
    return AgentBuilderDialog(parent=parent, handler=handler)


class TestNoModelDropdown:
    """The form has no Model dropdown widget."""

    def test_no_model_dropdown_attribute(self, gtk_parent):
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        assert not hasattr(dlg, "_model_dropdown")
        assert not hasattr(dlg, "_model_labeled")
        assert not hasattr(dlg, "_build_model_dropdown")
        assert not hasattr(dlg, "_rebuild_model_dropdown")
        assert not hasattr(dlg, "_get_selected_model")


class TestNoManualEntry:
    """The form has no Manual provider/model entry widgets."""

    def test_no_manual_widgets(self, gtk_parent):
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        assert not hasattr(dlg, "_manual_provider_entry")
        assert not hasattr(dlg, "_manual_model_entry")
        assert not hasattr(dlg, "_manual_toggle")
        assert not hasattr(dlg, "_manual_mode")
        assert not hasattr(dlg, "_on_manual_toggled")


class TestNoApiKeyField:
    """The form has no API key entry."""

    def test_no_api_key_entry(self, gtk_parent):
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        assert not hasattr(dlg, "_api_key_entry")
        assert not hasattr(dlg, "_provider_keys")


class TestSaveButtonEnablesWithoutApiKey:
    """Save enables when name + prompts + tools + provider are set (no API key)."""

    def test_save_disabled_when_only_name_set(self, gtk_parent):
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        dlg._name_entry.set_text("agent")
        dlg._update_save_button()
        assert dlg._save_btn.get_sensitive() is False

    def test_save_enabled_when_all_required_fields_set(self, gtk_parent):
        """name + prompts + tools + provider → Save sensitive, no API key entered."""
        providers = [ProviderConfig("openai", "u", "k", "gpt-4o", True)]
        dlg = _make_dlg(gtk_parent, providers)
        dlg._name_entry.set_text("agent")
        # Simulate user checking a prompt
        if dlg._prompt_checks:
            first_prompt = list(dlg._prompt_checks.values())[0]
            first_prompt.set_active(True)
        # Simulate user checking a tool
        if dlg._tool_checks:
            first_tool = list(dlg._tool_checks.values())[0]
            first_tool.set_active(True)
        dlg._update_save_button()
        assert dlg._save_btn.get_sensitive() is True
```

## File 3: `tests/test_window_settings_wiring.py` (REVISED)

The spec asks for a test `test_on_providers_changed_updates_agent_builder`. Check if this test already exists in the file. If not, add it.

Looking at the current file (lines 93-127), the `TestOnProvidersChanged` class has 4 tests:
- `test_add_fires_providers_changed_with_factory`
- `test_remove_fires_providers_changed_with_factory`
- `test_no_factory_is_safe`
- `test_factory_returning_none_is_safe`

If none of them assert that the agent builder's `set_provider_options` was called with the providers list when the agent builder factory returns a builder object, ADD this test:

```python
def test_on_providers_changed_updates_agent_builder(self, tmp_config_dir, monkeypatch):
    """When providers change and the agent builder is open, set_provider_options is called."""
    from unittest.mock import MagicMock
    from ui.handlers.settings_handler import SettingsHandler
    from ui.wiring import wire_settings_handler

    builder = MagicMock()
    handler = SettingsHandler()
    handler = wire_settings_handler(
        handler, MagicMock(),
        settings_dialog_factory=lambda: None,
        agent_builder_factory=lambda: builder,
    )

    providers = [{"name": "openai", "base_url": "u", "default_model": "gpt-4o"}]
    handler._on_providers_changed(providers)

    builder.set_provider_options.assert_called_once()
    args, _ = builder.set_provider_options.call_args
    assert len(args) == 1
    # First arg is the providers list — could be normalized to ProviderConfig or stay as dict
    assert len(args[0]) == 1
    assert args[0][0].name == "openai"
```

If the test already exists (or its coverage is already provided by the 4 existing tests), SKIP this change. Just verify the file passes tests.

## Verification

After the changes:

```bash
cd /home/q/projects/crabcakes

# New tests pass
python3 -m pytest tests/test_agent_builder_dialog.py tests/test_agent_builder_no_model_dropdown.py -v --tb=short 2>&1 | tail -20
# Expected: ~9 tests pass

# Existing wiring tests still pass
python3 -m pytest tests/test_window_settings_wiring.py -v --tb=short 2>&1 | tail -5
# Expected: 10 (or 11) passed

# Existing no_provider_keys tests still pass
python3 -m pytest tests/test_agent_builder_no_provider_keys.py -v --tb=short 2>&1 | tail -5
# Expected: 12 passed

# Full agent builder test suite passes
python3 -m pytest tests/ -k "agent_builder or window_settings_wiring" -v --tb=short 2>&1 | tail -30
# Expected: 30+ passed, 5 pre-existing failures (test_agent_builder_handler.py)
```

## COMPLETENESS Checklist

- [ ] File 1 created: `tests/test_agent_builder_dialog.py` — evidence: `ls tests/test_agent_builder_dialog.py`
- [ ] File 1 has 4 tests (TestProviderDropdownPopulation) — evidence: pytest count
- [ ] File 2 created: `tests/test_agent_builder_no_model_dropdown.py` — evidence: `ls tests/test_agent_builder_no_model_dropdown.py`
- [ ] File 2 has 4 test classes (TestNoModelDropdown, TestNoManualEntry, TestNoApiKeyField, TestSaveButtonEnablesWithoutApiKey) — evidence: pytest count
- [ ] File 3 (if needed): test added/verified in `tests/test_window_settings_wiring.py` — evidence: pytest count
- [ ] New tests pass — evidence: pytest tail
- [ ] Existing tests still pass — evidence: pytest tail
- [ ] Total: ~9 new tests added, all green — evidence: pytest summary
