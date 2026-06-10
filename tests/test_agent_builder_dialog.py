# tests/test_agent_builder_dialog.py
# Tests for AgentBuilderDialog — provider dropdown population at construction.
#
# Refs: docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md §2.5

import gi
gi.require_version('Gtk', '4.0')

import pytest
from gi.repository import Gtk

from models.providers import ProviderConfig


class StubHandler:
    """Stub AgentBuilderHandler — returns canned provider options."""
    def __init__(self, providers):
        self._providers = providers

    def get_prompt_options(self):
        return []

    def get_tool_options(self):
        return []

    def get_provider_options(self):
        return [
            {
                "name": p.name,
                "base_url": p.base_url,
                "default_model": p.default_model,
                "enabled": p.enabled,
                "api_key": p.api_key,
            }
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
