# tests/test_window_settings_wiring.py
# Tests for ui/wiring.py — verifies that the SettingsHandler's callbacks
# are correctly wired to the toolbar and the settings dialog factory.
# No GTK widgets required — we use simple stubs.

import pytest

from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler

from models.providers import ProviderConfig


class StubToolbar:
    """Captures set_settings_status calls."""
    def __init__(self):
        self.status_calls: list[bool] = []
    def set_settings_status(self, has_verified: bool) -> None:
        self.status_calls.append(has_verified)


class StubDialog:
    """Captures refresh_providers calls."""
    def __init__(self):
        self.refresh_calls: list[list] = []
    def refresh_providers(self, providers: list) -> None:
        self.refresh_calls.append(list(providers))


def _make_provider(name: str = "test", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name,
        base_url=f"https://api.{name}.example.com/v1",
        api_key="test-key",
        default_model=f"{name}/model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestWireSettingsHandler:
    def test_returns_the_handler(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        result = wire_settings_handler(h, t)
        assert result is h

    def test_sets_initial_toolbar_status(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t)
        # No providers → status is False
        assert t.status_calls == [False]

    def test_initial_status_true_when_verified_provider_exists(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        from utils.provider_test import TestResult
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=1, error=None, model_used=kw["model"]))
        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        # Now test the provider to set last_verified_at
        import threading
        event = threading.Event()
        h.test_provider(p, lambda r: event.set())
        assert event.wait(timeout=2.0)
        t = StubToolbar()
        wire_settings_handler(h, t)
        assert t.status_calls == [True]


class TestOnStatusChanged:
    def test_add_fires_status_changed(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t)
        t.status_calls.clear()
        h.add_or_update(_make_provider("p"))
        # After add, status should be False (no verified yet)
        assert t.status_calls[-1] is False

    def test_remove_fires_status_changed(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))
        t = StubToolbar()
        wire_settings_handler(h, t)
        t.status_calls.clear()
        h.remove("p")
        assert t.status_calls[-1] is False


class TestOnProvidersChanged:
    def test_add_fires_providers_changed_with_factory(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        dlg = StubDialog()
        factory = lambda: dlg
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.add_or_update(_make_provider("p1"))
        # StubDialog should have received the new list
        assert len(dlg.refresh_calls) == 1
        assert len(dlg.refresh_calls[0]) == 1
        assert dlg.refresh_calls[0][0].name == "p1"

    def test_remove_fires_providers_changed_with_factory(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        t = StubToolbar()
        dlg = StubDialog()
        factory = lambda: dlg
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.remove("p1")
        assert len(dlg.refresh_calls) >= 1
        # Last refresh should have empty list
        assert dlg.refresh_calls[-1] == []

    def test_no_factory_is_safe(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t, settings_dialog_factory=None)
        # Adding a provider should not crash even with no dialog factory
        h.add_or_update(_make_provider("p"))
        # Status callback should still fire
        assert t.status_calls[-1] is False

    def test_factory_returning_none_is_safe(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        factory = lambda: None  # dialog not open
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.add_or_update(_make_provider("p"))
        # Should not crash; status callback should still fire
        assert t.status_calls[-1] is False


# ── GTK availability for lifecycle tests ──────────────────────────────
try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk as _Gtk
    _GTK_AVAILABLE = True
except (ImportError, ValueError):
    _GTK_AVAILABLE = False


@pytest.mark.skipif(not _GTK_AVAILABLE, reason="GTK not available")
class TestSettingsDialogHideLifecycle:
    """Regression: closing the dialog must invalidate the cache so the
    next open constructs a fresh dialog, not reuse a hidden one.

    In GTK4, close-request returning False hides the window (it does NOT
    destroy it). The hide signal is what we connect to for cache
    invalidation."""

    def test_close_then_reopen_constructs_fresh_dialog(
        self, tmp_config_dir
    ):
        """Open → close → reopen must construct a fresh SettingsDialog."""
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from ui.handlers.settings_handler import SettingsHandler
        from ui.views.settings_dialog import SettingsDialog

        # Build a minimal harness that mirrors window._open_settings
        class _Harness:
            def __init__(self):
                self._settings_dialog = None
                self._settings_handler = SettingsHandler()

            def _open_settings(self) -> None:
                if not hasattr(self, "_settings_dialog") or self._settings_dialog is None:
                    self._settings_dialog = SettingsDialog(
                        parent=None,
                        handler=self._settings_handler,
                        on_close=lambda: None,
                    )
                    # Lifecycle hook — same as window.py (hide signal)
                    self._settings_dialog._window.connect(
                        "hide",
                        lambda *_, ref=self: setattr(ref, "_settings_dialog", None),
                    )
                self._settings_dialog.show()

        win = _Harness()

        # First open
        win._open_settings()
        dlg1 = win._settings_dialog
        assert dlg1 is not None

        # Real close — hides the window (GTK4 default behavior)
        dlg1._window.close()
        assert not dlg1._window.get_visible(), "Window should be hidden after close"

        # In headless GTK4, close() hides but doesn't fire the hide
        # signal. In a real display it would. Emit it directly to
        # simulate the real behavior.
        dlg1._window.emit("hide")

        # Cache should now be cleared
        assert getattr(win, "_settings_dialog", None) is None, (
            "Cache was not cleared after hide — bug not fixed"
        )

        # Reopen — must construct fresh
        win._open_settings()
        dlg2 = win._settings_dialog
        assert dlg2 is not None
        assert dlg2 is not dlg1, "Reopen reused the hidden dialog"

        # Cleanup
        dlg2._window.close()
        dlg2._window.emit("hide")

    def test_no_gtk_warning_on_second_open(
        self, tmp_config_dir, capfd
    ):
        """Opening, closing, and reopening must not produce Gtk-WARNING."""
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from ui.handlers.settings_handler import SettingsHandler
        from ui.views.settings_dialog import SettingsDialog

        class _Harness:
            def __init__(self):
                self._settings_dialog = None
                self._settings_handler = SettingsHandler()

            def _open_settings(self) -> None:
                if not hasattr(self, "_settings_dialog") or self._settings_dialog is None:
                    self._settings_dialog = SettingsDialog(
                        parent=None,
                        handler=self._settings_handler,
                        on_close=lambda: None,
                    )
                    self._settings_dialog._window.connect(
                        "hide",
                        lambda *_, ref=self: setattr(ref, "_settings_dialog", None),
                    )
                self._settings_dialog.show()

        win = _Harness()

        # First open
        win._open_settings()
        dlg1 = win._settings_dialog

        # Close
        dlg1._window.close()
        dlg1._window.emit("hide")

        # Flush any pending output
        capfd.readouterr()

        # Reopen — should not produce Gtk-WARNING
        win._open_settings()
        dlg2 = win._settings_dialog

        captured = capfd.readouterr()
        assert "Gtk-WARNING" not in captured.err, (
            f"Gtk-WARNING on second open:\n{captured.err}"
        )

        # Cleanup
        dlg2._window.close()
        dlg2._window.emit("hide")
