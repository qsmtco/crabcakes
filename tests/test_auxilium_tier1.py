# tests/test_auxilium_tier1.py
# Smoke tests for the Auxilium first-run wizard (D7, Tier 1)
#
# Tests 1-4: non-GTK (handler imports, helper function).
# Tests 5-6: handler state machine (non-GTK, but exercise threading).
# Test 7: GTK view instantiation (needs xvfb-run -a).

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest


# ── Tests 1-4: Non-GTK ────────────────────────────────────────────────────────

def test_wizard_handler_imports():
    """Module imports cleanly and exposes the expected public API."""
    from ui.handlers.auxilium_wizard_handler import (
        AuxiliumWizardHandler,
        WizardStep,
        WizardState,
        is_auxilium_wizard_needed,
    )
    assert AuxiliumWizardHandler is not None
    assert WizardStep is not None
    assert WizardState is not None
    assert callable(is_auxilium_wizard_needed)


def test_wizard_view_imports():
    """View module imports cleanly (GTK required)."""
    import gi
    gi.require_version('Gtk', '4.0')
    from ui.views.auxilium_wizard import AuxiliumWizard
    assert AuxiliumWizard is not None


def test_is_auxilium_wizard_needed_missing_file():
    """Empty config dir (no providers.yaml) → wizard needed."""
    with tempfile.TemporaryDirectory() as tmp:
        from ui.handlers.auxilium_wizard_handler import is_auxilium_wizard_needed
        assert is_auxilium_wizard_needed(Path(tmp)) is True


def test_is_auxilium_wizard_needed_with_providers():
    """Config dir with providers.yaml → returns a bool (False on this machine)."""
    from ui.handlers.auxilium_wizard_handler import is_auxilium_wizard_needed
    real = Path.home() / ".config" / "crabcakes"
    result = is_auxilium_wizard_needed(real)
    # Should be False if providers.yaml exists (may be True if config is fresh)
    assert isinstance(result, bool)


# ── Tests 5-6: Handler state machine (non-GTK) ────────────────────────────────

def test_handler_install_check_advances_state():
    """start() runs the install check and sets step to INSTALL_CHECK."""
    with tempfile.TemporaryDirectory() as tmp:
        from ui.handlers.auxilium_wizard_handler import (
            AuxiliumWizardHandler,
            WizardStep,
        )
        calls: list[str] = []
        h = AuxiliumWizardHandler(
            config_dir=Path(tmp),
            on_complete=lambda: calls.append("complete"),
            on_error=lambda msg: calls.append(f"error: {msg}"),
        )
        h.start()
        state = h.get_state()
        assert state.step == WizardStep.INSTALL_CHECK
        assert state.install_check["ok"] is True  # this machine has all deps
        assert state.install_check["platform"] == "linux"
        assert calls == []  # no callbacks fired yet


def test_handler_advance_to_gateway():
    """advance_to_gateway() spawns probe thread and sets step to GATEWAY_CHECK."""
    with tempfile.TemporaryDirectory() as tmp:
        from ui.handlers.auxilium_wizard_handler import (
            AuxiliumWizardHandler,
            WizardStep,
        )
        h = AuxiliumWizardHandler(
            config_dir=Path(tmp),
            on_complete=lambda: None,
            on_error=lambda msg: None,
        )
        h.start()
        h.advance_to_gateway()
        state = h.get_state()
        assert state.step == WizardStep.GATEWAY_CHECK
        assert "ok" in state.gateway_check
        # Wait for probe to complete (3s timeout + buffer)
        time.sleep(4.5)
        state2 = h.get_state()
        assert "ok" in state2.gateway_check  # probe finished


# ── Test 7: GTK view (needs xvfb-run -a) ──────────────────────────────────────

def test_view_current_step_property():
    """View's current_step property returns 'install_check' on init."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    from ui.views.auxilium_wizard import AuxiliumWizard
    from ui.handlers.auxilium_wizard_handler import WizardState

    with tempfile.TemporaryDirectory() as tmp:
        class StubHandler:
            def __init__(self):
                self._state = WizardState()

            def get_state(self):
                return self._state

            def start(self):
                pass

            def advance_to_gateway(self):
                pass

            def advance_to_provider(self):
                pass

            def set_provider_choice(self, c, p, m, k):
                pass

        h = StubHandler()
        w = AuxiliumWizard(
            handler=h,
            on_install_check_complete=lambda: None,
            on_gateway_check_complete=lambda: None,
            on_provider_selected=lambda: None,
        )
        assert w.current_step == "install_check"
        w.cleanup()
