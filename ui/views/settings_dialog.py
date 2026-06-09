# ui/views/settings_dialog.py
# GTK4 dialog for managing LLM provider settings.
#
# Pure view — receives data from SettingsHandler, emits user actions
# back through handler methods. No direct file I/O or network calls.
#
# Architecture rule (ARCHITECTURE.md Section 9):
#   - Uses add_css_class() only, no inline CssProvider
#   - No business logic — delegates to handler for validation/persistence
#   - CSS classes: settings-*

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from models.providers import ProviderConfig
from ui.handlers.settings_handler import SettingsHandler

if TYPE_CHECKING:
    from utils.provider_test import TestResult

logger = logging.getLogger(__name__)


class _ProviderCard:
    """A single provider's edit form. Pure view — delegates to handler."""

    def __init__(self, dialog: SettingsDialog, provider: ProviderConfig | None):
        """If provider is None, this is a new (unsaved) card with empty fields."""
        self._dialog = dialog
        self._is_new = provider is None
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key="", default_model="",
        )
        self._build_widgets()
        if provider is not None:
            self._populate_from_provider()

    def _build_widgets(self) -> None:
        self._frame = Gtk.Frame()
        self._frame.add_css_class("settings-provider-card")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)

        # Name
        self._name_entry = Gtk.Entry()
        self._name_entry.set_placeholder_text("Provider name")
        self._name_entry.set_hexpand(True)
        name_row = self._labeled("Name", self._name_entry)
        vbox.append(name_row)

        # Base URL
        self._base_url_entry = Gtk.Entry()
        self._base_url_entry.set_placeholder_text("https://api.example.com/v1")
        self._base_url_entry.set_hexpand(True)
        url_row = self._labeled("Base URL", self._base_url_entry)
        vbox.append(url_row)

        # Default model
        self._model_entry = Gtk.Entry()
        self._model_entry.set_placeholder_text("model-id")
        self._model_entry.set_hexpand(True)
        model_row = self._labeled("Default Model", self._model_entry)
        vbox.append(model_row)

        # API key (password + reveal toggle)
        self._api_key_entry = Gtk.Entry()
        self._api_key_entry.set_placeholder_text("API key")
        self._api_key_entry.set_hexpand(True)
        self._api_key_entry.set_visibility(False)
        self._api_key_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)

        self._reveal_btn = Gtk.Button(label="👁")
        self._reveal_btn.add_css_class("flat")
        self._reveal_btn.set_size_request(36, -1)
        self._reveal_btn.connect("clicked", self._on_reveal_clicked)

        api_key_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        api_key_box.append(self._api_key_entry)
        api_key_box.append(self._reveal_btn)
        api_key_row = self._labeled("API Key", api_key_box)
        vbox.append(api_key_row)

        # Status label
        self._status_label = Gtk.Label(label="Untested")
        self._status_label.add_css_class("settings-status-untested")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_wrap(True)
        vbox.append(self._status_label)

        # Button row: Test | Save | Remove
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self._test_btn = Gtk.Button(label="Test Connection")
        self._test_btn.add_css_class("settings-test-btn")
        self._test_btn.connect("clicked", self._on_test_clicked)
        btn_row.append(self._test_btn)

        self._save_btn = Gtk.Button(label="Save")
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.connect("clicked", self._on_save_clicked)
        btn_row.append(self._save_btn)

        self._remove_btn = Gtk.Button(label="Remove")
        self._remove_btn.add_css_class("settings-remove-btn")
        self._remove_btn.connect("clicked", self._on_remove_clicked)
        btn_row.append(self._remove_btn)

        vbox.append(btn_row)
        self._frame.set_child(vbox)

    def _labeled(self, text: str, widget: Gtk.Widget) -> Gtk.Box:
        """Create a label + widget row."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=text)
        label.set_size_request(100, -1)
        label.set_halign(Gtk.Align.START)
        label.set_valign(Gtk.Align.CENTER)
        row.append(label)
        row.append(widget)
        return row

    def _populate_from_provider(self) -> None:
        p = self._provider
        self._name_entry.set_text(p.name or "")
        self._base_url_entry.set_text(p.base_url or "")
        self._model_entry.set_text(p.default_model or "")
        self._api_key_entry.set_text(p.api_key or "")

        # Show verification status if available
        if p.last_verified_at:
            self._status_label.set_text("✅ Verified")
            self._status_label.remove_css_class("settings-status-untested")
            self._status_label.remove_css_class("settings-status-fail")
            self._status_label.add_css_class("settings-status-ok")
        elif p.last_error:
            self._status_label.set_text(f"❌ {p.last_error}")
            self._status_label.remove_css_class("settings-status-untested")
            self._status_label.remove_css_class("settings-status-ok")
            self._status_label.add_css_class("settings-status-fail")

    def _collect_from_form(self) -> ProviderConfig:
        """Collect current form values into a ProviderConfig."""
        existing = self._provider
        return ProviderConfig(
            name=self._name_entry.get_text().strip(),
            base_url=self._base_url_entry.get_text().strip(),
            api_key=self._api_key_entry.get_text().strip(),
            default_model=self._model_entry.get_text().strip(),
            enabled=existing.enabled if existing else True,
            supports_tools=existing.supports_tools if existing else True,
            supports_streaming=existing.supports_streaming if existing else True,
            max_tokens=existing.max_tokens if existing else 128_000,
            last_verified_at=existing.last_verified_at if existing else None,
            last_error=existing.last_error if existing else None,
        )

    def _on_reveal_clicked(self, *args) -> None:
        """Toggle API key visibility."""
        current = self._api_key_entry.get_visibility()
        self._api_key_entry.set_visibility(not current)

    def _on_save_clicked(self, *args) -> None:
        """Save the card's current form values via handler."""
        provider = self._collect_from_form()
        try:
            self._dialog._handler.add_or_update(provider)
        except ValueError as e:
            self._set_status(str(e), fail=True)

    def _on_test_clicked(self, *args) -> None:
        """Run Test Connection via handler. Does not block."""
        provider = self._collect_from_form()
        self._status_label.set_text("Testing...")
        self._status_label.remove_css_class("settings-status-ok")
        self._status_label.remove_css_class("settings-status-fail")
        self._status_label.add_css_class("settings-status-untested")
        self._dialog._handler.test_provider(provider, self._on_test_result)

    def _on_remove_clicked(self, *args) -> None:
        """Remove this provider. Shows confirmation first."""
        if self._is_new:
            # Unsaved card — just remove from the dialog
            self._dialog._remove_card(self)
            return

        name = self._provider.name
        dialog = Gtk.MessageDialog(
            transient_for=self._dialog._window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f'Remove provider "{name}"?',
        )
        dialog.set_property(
            "secondary-text",
            "This cannot be undone.",
        )

        def on_response(_dlg, response_id):
            _dlg.close()
            if response_id == Gtk.ResponseType.YES:
                self._dialog._handler.remove(name)

        dialog.connect("response", on_response)
        dialog.show()

    def _on_test_result(self, result: TestResult) -> None:
        """Called on the GTK main thread with the test result."""
        if result.ok:
            self._set_status(f"✅ {result.latency_ms}ms", ok=True)
        else:
            error_msg = result.error or "unknown error"
            self._set_status(f"❌ {error_msg}", fail=True)

    def _set_status(self, text: str, *, ok: bool = False, fail: bool = False) -> None:
        self._status_label.set_text(text)
        self._status_label.remove_css_class("settings-status-ok")
        self._status_label.remove_css_class("settings-status-fail")
        self._status_label.remove_css_class("settings-status-untested")
        if ok:
            self._status_label.add_css_class("settings-status-ok")
        elif fail:
            self._status_label.add_css_class("settings-status-fail")
        else:
            self._status_label.add_css_class("settings-status-untested")

    def get_widget(self) -> Gtk.Frame:
        return self._frame


class SettingsDialog:
    """GTK4 dialog for managing LLM provider settings.

    Pure view — delegates all persistence to SettingsHandler.
    Called from the toolbar ⚙ button (wired in Phase 7).

    Args:
        parent: Parent Gtk.Window for transient setting.
        handler: SettingsHandler — the data gateway.
        on_close: Optional callback when the dialog is closed.
    """

    def __init__(
        self,
        parent: Gtk.Window | None,
        *,
        handler: SettingsHandler,
        on_close=None,
    ):
        self._handler = handler
        self._on_close = on_close
        self._cards: list[_ProviderCard] = []

        # ── Window setup ──────────────────────────────────────────────
        self._window = Gtk.Window(title="Settings")
        if parent is not None:
            self._window.set_transient_for(parent)
        self._window.set_modal(True)
        self._window.set_default_size(560, 480)
        self._window.add_css_class("settings-dialog")
        self._window.connect("close-request", self._on_close_request)

        # ── Build layout ──────────────────────────────────────────────
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Gtk.HeaderBar()
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda *_: self.close())
        header.pack_end(close_btn)
        content.append(header)

        # Scrollable body
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_vexpand(True)
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        self._list_box.set_margin_top(12)
        self._list_box.set_margin_bottom(12)

        # Empty state
        self._empty_state = Gtk.Label(
            label="No providers configured.\nAdd your first provider below."
        )
        self._empty_state.add_css_class("settings-empty-state")
        self._empty_state.set_justify(Gtk.Justification.CENTER)
        self._list_box.append(self._empty_state)

        self._scrolled.set_child(self._list_box)
        content.append(self._scrolled)

        # + Add Provider button (bottom)
        add_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_btn_box.set_margin_start(16)
        add_btn_box.set_margin_end(16)
        add_btn_box.set_margin_top(4)
        add_btn_box.set_margin_bottom(8)
        self._add_btn = Gtk.Button(label="+ Add Provider")
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.set_hexpand(True)
        self._add_btn.connect("clicked", self._on_add_provider_clicked)
        add_btn_box.append(self._add_btn)
        content.append(add_btn_box)

        self._window.set_child(content)

        # Populate from current handler state
        self.refresh_providers(handler.list_providers())

    # ── Public API ────────────────────────────────────────────────────

    def show(self) -> None:
        """Present the settings dialog."""
        self._window.present()

    def close(self) -> None:
        """Close the settings dialog."""
        self._window.close()

    def refresh_providers(self, providers: list[ProviderConfig]) -> None:
        """Rebuild the card list from the given provider list.

        Strategy: remove all existing cards, then rebuild from scratch.
        This is simpler and avoids stale-widget bugs from partial updates.
        The trade-off is that unsaved edits are lost on refresh — but
        refresh only fires after a successful save/remove/test, so the
        user's edits have already been committed.
        """
        # Remove existing cards
        for card in self._cards:
            self._list_box.remove(card.get_widget())
        self._cards.clear()

        # Rebuild cards
        for provider in providers:
            card = _ProviderCard(self, provider)
            self._cards.append(card)
            self._list_box.append(card.get_widget())

        # Toggle empty state
        self._empty_state.set_visible(len(providers) == 0)

    # ── Internal ──────────────────────────────────────────────────────

    def _on_add_provider_clicked(self, *args) -> None:
        """Append a new empty card for the user to fill in."""
        card = _ProviderCard(self, None)
        self._cards.append(card)
        self._list_box.append(card.get_widget())
        # Hide empty state
        self._empty_state.set_visible(False)

    def _remove_card(self, card: _ProviderCard) -> None:
        """Remove a card from the list (for unsaved new cards)."""
        if card in self._cards:
            self._cards.remove(card)
            self._list_box.remove(card.get_widget())
        self._empty_state.set_visible(len(self._cards) == 0)

    def _on_close_request(self, *args) -> bool:
        """Handle window close-request signal."""
        if self._on_close is not None:
            self._on_close()
        return False  # allow close
