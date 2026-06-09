# ui/wiring.py
# Small wiring helpers for the Settings integration.
# Extracted from ui/window.py to make the SettingsHandler ↔ Toolbar ↔ SettingsDialog
# callback wiring testable in isolation (without constructing the full window).

from __future__ import annotations

from typing import Callable

from ui.handlers.settings_handler import SettingsHandler
from utils.providers_store import has_any_verified_provider, load_providers


def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable | None = None,
) -> SettingsHandler:
    """Wire the SettingsHandler's callbacks to the toolbar and (optionally) the dialog.

    - on_status_changed  → toolbar.set_settings_status(verified)
    - on_providers_changed → settings_dialog_factory().refresh_providers(providers)
      (no-op if no factory is provided — e.g. in tests where the dialog isn't open)
    - Sets initial toolbar status from the current state of providers.yaml.

    Returns the (now-wired) handler, so callers can keep a reference.
    """
    def _on_status_changed(verified: bool) -> None:
        toolbar.set_settings_status(verified)

    def _on_providers_changed(providers) -> None:
        if settings_dialog_factory is not None:
            try:
                dialog = settings_dialog_factory()
                if dialog is not None:
                    dialog.refresh_providers(providers)
            except Exception:
                pass  # dialog may not be open / already destroyed

    # Mutate the handler's private callback slots (per the handler's __init__ API)
    handler._on_status_changed = _on_status_changed
    handler._on_providers_changed = _on_providers_changed

    # Initial status — drives the red dot on the ⚙ button at startup.
    toolbar.set_settings_status(has_any_verified_provider(load_providers()))

    return handler
