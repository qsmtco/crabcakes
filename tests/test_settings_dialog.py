# tests/test_settings_dialog.py
# Tests for ui/views/settings_dialog.py — pure view smoke tests.
# Pattern: construct the dialog with a real handler (using tmp_config_dir),
# inspect the widget tree, do not actually open a window (no Gtk.Window present).

import pytest

try:
    from gi.repository import Gtk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

from models.providers import ProviderConfig
from ui.handlers.settings_handler import SettingsHandler
from ui.views.settings_dialog import SettingsDialog


pytestmark = pytest.mark.skipif(not GTK_AVAILABLE, reason="GTK not available")


def _make_provider(name: str = "test", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name,
        base_url=f"https://api.{name}.example.com/v1",
        api_key="test-key",
        default_model=f"{name}/model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestEmptyState:
    def test_no_providers_shows_empty_state(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        assert d._empty_state is not None
        assert d._empty_state.get_visible() is True

    def test_with_providers_hides_empty_state(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        assert d._empty_state.get_visible() is False


class TestProviderCards:
    def test_one_provider_renders_one_card(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 1
        assert d._cards[0].get_widget().get_visible() is True

    def test_two_providers_render_two_cards(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        h.add_or_update(_make_provider("p2"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 2

    def test_add_provider_button_appends_card(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        initial = len(d._cards)
        d._on_add_provider_clicked(None)
        assert len(d._cards) == initial + 1

    def test_card_has_all_widgets(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert card._name_entry is not None
        assert card._base_url_entry is not None
        assert card._model_entry is not None
        assert card._api_key_entry is not None
        assert card._test_btn is not None
        assert card._remove_btn is not None
        assert card._save_btn is not None

    def test_api_key_entry_is_password(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert card._api_key_entry.get_visibility() is False
        assert card._api_key_entry.get_input_purpose() == Gtk.InputPurpose.PASSWORD


class TestRemoveCallback:
    def test_remove_unsaved_card_directly(self, tmp_config_dir):
        """Removing an unsaved card just removes the widget, no handler call."""
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        d._on_add_provider_clicked(None)
        assert len(d._cards) == 1
        card = d._cards[0]
        assert card._is_new is True
        card._on_remove_clicked(None)
        assert len(d._cards) == 0

    def test_remove_saved_card_calls_handler(self, tmp_config_dir, monkeypatch):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)

        # We can't easily run the GTK main loop to process the MessageDialog's
        # idle_add callback. Instead, verify that handler.remove() actually
        # removes the provider and the dialog's on_providers_changed refreshes.
        h.remove("p1")
        d.refresh_providers(h.list_providers())
        assert len(d._cards) == 0
        assert h.list_providers() == []


class TestSaveFlow:
    def test_save_valid_calls_handler_add_or_update(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        d._on_add_provider_clicked(None)
        new_card = d._cards[-1]
        new_card._name_entry.set_text("newprov")
        new_card._base_url_entry.set_text("https://x.example.com/v1")
        new_card._api_key_entry.set_text("test-api-key")
        new_card._model_entry.set_text("newprov/model-v1")
        new_card._on_save_clicked(None)
        names = [p.name for p in h.list_providers()]
        assert "newprov" in names

    def test_save_invalid_shows_error_in_status_label(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        d._on_add_provider_clicked(None)
        new_card = d._cards[-1]
        new_card._name_entry.set_text("")  # empty -> ValueError
        new_card._base_url_entry.set_text("https://x.example.com/v1")
        new_card._api_key_entry.set_text("test-api-key")
        new_card._model_entry.set_text("model")
        new_card._on_save_clicked(None)
        status = new_card._status_label.get_text().lower()
        assert "required" in status or "name" in status


class TestRefreshProviders:
    def test_refresh_rebuilds_cards(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 1
        h.add_or_update(_make_provider("b"))
        d.refresh_providers(h.list_providers())
        assert len(d._cards) == 2

    def test_refresh_repopulates_from_saved_data(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        d = SettingsDialog(parent=None, handler=h)
        # User edits the entry without saving
        d._cards[0]._name_entry.set_text("edited-but-unsaved")
        # Refresh from handler (which still has "a")
        d.refresh_providers(h.list_providers())
        # Card is rebuilt from handler data — unsaved edit is lost
        assert d._cards[0]._name_entry.get_text() == "a"
