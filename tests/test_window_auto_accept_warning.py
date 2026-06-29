# tests/test_window_auto_accept_warning.py
# Regression tests for MainWindow._show_auto_accept_warning.
#
# Coverage targets:
#   1. The bug: GTK4 MessageDialog secondary-text setter was named wrong
#      (`format_secondary_text` — GTK3 API). Pre-fix this threw AttributeError.
#   2. Confirm path: clicking "Turn On" invokes on_confirm.
#   3. Cancel path: clicking "Cancel" invokes on_cancel.
#   4. Default response is CANCEL (Phase 5-4 spec).
#   5. Dialog text fields are populated with the agent name.
#
# Strategy: instantiate a stub MainWindow subclass that skips the heavy
# widget tree but still creates a real Gtk.ApplicationWindow as `self`
# (Gtk.MessageDialog requires a real GTK windowing context for proper
# construction). Invoke _show_auto_accept_warning as an unbound function
# via MainWindow._show_auto_accept_warning(self, ...), exercising the
# actual production code path.

import os
import sys

import pytest

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.window import MainWindow


# Module-level application — created once, shared across all tests in
# the session. Constructing a Gtk.Application per-test triggers Gtk critical
# warnings ("New application windows must be added after the GApplication::
# startup signal has been emitted") that interfere with dialog lifetime.
_app = Gtk.Application(application_id="test.crabcakes.auto_accept_warning")


class _MainWindowTestHarness(Gtk.ApplicationWindow):
    """
    Real Gtk.ApplicationWindow that proxies `_show_auto_accept_warning` to
    the production MainWindow method. This avoids having to instantiate
    MainWindow's full UI tree (feed handler, chat handler, gateway handler,
    project handler, agent runtime, etc., all wired together) just to test
    a single dialog helper.
    """

    def __init__(self):
        super().__init__(application=_app)
        self.set_default_size(400, 300)
        # Bind the production method to this instance.
        self._show_auto_accept_warning = (
            lambda agent_name, on_confirm, on_cancel:
            MainWindow._show_auto_accept_warning(self, agent_name, on_confirm, on_cancel)
        )


@pytest.fixture
def harness():
    """Provide a fresh MainWindowTestHarness for each test."""
    return _MainWindowTestHarness()


def _find_dialog(window):
    """
    Find the most recently constructed Gtk.MessageDialog in the test process.

    GTK4 MessageDialog is a Gtk.Window (toplevel). It is registered in
    Gtk.Window.list_toplevels() as soon as it's constructed, even before
    dialog.show(). Return the most recent one.
    """
    matches = [w for w in Gtk.Window.list_toplevels()
               if isinstance(w, Gtk.MessageDialog)]
    if not matches:
        raise AssertionError(
            "No Gtk.MessageDialog found — did _show_auto_accept_warning run?"
        )
    # Return the most recent (last) — captures the latest created dialog
    return matches[-1]


class TestShowAutoAcceptWarningNoThrow:
    """Regression for the `format_secondary_text` AttributeError (Phase 5-4)."""

    def test_call_does_not_raise_attribute_error(self, harness):
        """
        Pre-fix this raised:
            AttributeError: 'MessageDialog' object has no attribute
            'format_secondary_text'
        at ui/window.py:945. Post-fix the method must construct the dialog
        cleanly using GTK4's `secondary_text=` constructor kwarg.
        """
        try:
            harness._show_auto_accept_warning(
                agent_name="coder",
                on_confirm=lambda: None,
                on_cancel=lambda: None,
            )
        except AttributeError as e:
            if "format_secondary_text" in str(e) or "secondary_text" in str(e):
                pytest.fail(
                    f"REGRESSION: GTK3 MessageDialog API still in code: {e}. "
                    "Fix is `secondary_text=` constructor kwarg on Gtk.MessageDialog."
                )
            raise

    def test_call_does_not_raise_any_exception(self, harness):
        """No unexpected exception types from dialog construction."""
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )

    @pytest.mark.parametrize("agent_name", [
        "coder",
        "SuperCoder-9000",
        "agent/with/slashes",
        "",  # edge case: empty agent name (sad path)
        "🦀 crab 🦀",  # unicode
    ])
    def test_call_robust_to_agent_name_variations(self, harness, agent_name):
        """Dialog construction must work for any agent_name string."""
        harness._show_auto_accept_warning(
            agent_name=agent_name,
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )


class TestShowAutoAcceptWarningResponseRouting:
    """
    The dialog's response handler routes Gtk.ResponseType.OK to on_confirm
    and any other response (incl. CANCEL, CLOSE) to on_cancel.
    (Phase 5-4 spec: confirm enables auto-accept; cancel snaps toggle back.)
    """

    def test_ok_response_invokes_on_confirm(self, harness):
        confirm_calls = []
        cancel_calls = []
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: confirm_calls.append(True),
            on_cancel=lambda: cancel_calls.append(True),
        )
        dialog = _find_dialog(harness)
        # Emit the 'response' signal — simulates user clicking a button
        # (Gtk.MessageDialog.response() doesn't emit by itself in GTK4)
        dialog.emit("response", Gtk.ResponseType.OK)
        # Note: the production _on_response handler also calls
        # dialog.close() after dispatching, which may cascade additional
        # response emissions. We assert the *first* dispatch target:
        assert confirm_calls, (
            f"Expected on_confirm to be invoked when user clicks Turn On; "
            f"got confirm={confirm_calls}, cancel={cancel_calls}"
        )

    def test_cancel_response_invokes_on_cancel(self, harness):
        confirm_calls = []
        cancel_calls = []
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: confirm_calls.append(True),
            on_cancel=lambda: cancel_calls.append(True),
        )
        dialog = _find_dialog(harness)
        dialog.emit("response", Gtk.ResponseType.CANCEL)
        assert cancel_calls, (
            f"Expected on_cancel to be invoked when user clicks Cancel; "
            f"got confirm={confirm_calls}, cancel={cancel_calls}"
        )
        # Note: confirm_calls may be 0 here regardless.

    def test_close_response_invokes_on_cancel(self, harness):
        """
        Closing the dialog via the window manager (DELETE_EVENT) should
        route to on_cancel, not on_confirm.
        """
        confirm_calls = []
        cancel_calls = []
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: confirm_calls.append(True),
            on_cancel=lambda: cancel_calls.append(True),
        )
        dialog = _find_dialog(harness)
        dialog.emit("response", Gtk.ResponseType.DELETE_EVENT)
        assert cancel_calls, (
            f"Expected on_cancel to be called on DELETE_EVENT, got {cancel_calls}"
        )
        assert not confirm_calls, (
            f"on_confirm must NOT be invoked on DELETE_EVENT (closing "
            f"the dialog must not silently enable auto-accept), got "
            f"{confirm_calls}"
        )

    def test_default_response_is_cancel(self, harness):
        """
        Per Phase 5-4 spec: set_default_response(Gtk.ResponseType.CANCEL).
        Verify the Cancel button is the dialog's default action widget
        (safety: accidental Enter goes to Cancel, not Turn On).

        GTK4 has no `get_default_response()` — we read it back via the
        Cancel button's `has_default()` property, which `set_default_response`
        sets to True.
        """
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = _find_dialog(harness)
        cancel_widget = dialog.get_widget_for_response(Gtk.ResponseType.CANCEL)
        assert cancel_widget is not None, "Cancel button must exist"
        assert cancel_widget.has_default(), (
            "Cancel button must be the dialog's default action widget"
        )


class TestShowAutoAcceptWarningDialogContent:
    """Verify the dialog's primary and secondary text are populated."""

    def test_primary_text_mentions_agent_name(self, harness):
        harness._show_auto_accept_warning(
            agent_name="SuperCoder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = _find_dialog(harness)
        primary = dialog.get_property("text")
        assert "SuperCoder" in primary, (
            f"Primary text should mention agent name; got: {primary!r}"
        )

    def test_secondary_text_mentions_agent_name(self, harness):
        """
        This test specifically guards against the `format_secondary_text`
        bug — if secondary-text is empty, the constructor didn't accept the
        kwarg or the binding was lost. Pre-fix the dialog had NO secondary
        text because the call raised before it could execute.
        """
        harness._show_auto_accept_warning(
            agent_name="SuperCoder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = _find_dialog(harness)
        secondary = dialog.get_property("secondary-text")
        assert secondary is not None and "SuperCoder" in secondary, (
            f"Secondary text should mention agent name and be non-empty; "
            f"got: {secondary!r}"
        )

    def test_secondary_text_is_non_empty(self, harness):
        """
        Sad path / bug guard: if secondary_text was set via an invalid
        method (like the GTK3 format_secondary_text), this returns empty.
        With the correct GTK4 constructor kwarg, it returns the full body.
        """
        harness._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = _find_dialog(harness)
        secondary = dialog.get_property("secondary-text")
        assert secondary, f"Secondary text must be non-empty; got {secondary!r}"
