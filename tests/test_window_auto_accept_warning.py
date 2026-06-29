# tests/test_window_auto_accept_warning.py
# Regression tests for MainWindow._show_auto_accept_warning.
#
# Coverage targets:
#   1. The bug: GTK4 MessageDialog secondary-text setter was named wrong
#      (`format_secondary_text` — GTK3 API). Pre-fix this threw AttributeError.
#   2. Confirm path: clicking "Turn On" invokes on_confirm.
#   3. Cancel path: clicking "Cancel" (or closing dialog) invokes on_cancel.
#   4. Default response: Turn On is the default? No — Cancel is the default
#      (per Phase 5-4 spec: `set_default_response(Gtk.ResponseType.CANCEL)`).
#
# Strategy: stub out the parts of `self` that `_show_auto_accept_warning`
# touches (`self` is passed to `Gtk.MessageDialog(transient_for=self, ...)`).
# Reuse the real `_show_auto_accept_warning` function via a thin wrapping class
# so we exercise the actual production code path, not a re-implementation.

import sys
import os

import pytest

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.window import MainWindow


class _StubParentWindow(Gtk.ApplicationWindow):
    """
    Minimal real Gtk.ApplicationWindow parent for _show_auto_accept_warning.

    Real GTK is required: the function creates a Gtk.MessageDialog which is
    a Gtk.Window subclass and needs a real windowing context (the constructor
    will refuse transient_for=Non-uint64 values and may defer signal setup
    until a stable parent exists).
    """

    def __init__(self):
        # Use a bogus application_id — tests run headless; no display required
        # for construction, only for `.show()` / `.present()`. We never show
        # the dialog in these tests.
        app = Gtk.Application(application_id="test.crabcakes.auto_accept_warning")
        super().__init__(application=app)
        self.set_default_size(400, 300)


class TestShowAutoAcceptWarningNoThrow:
    """Regression for the `format_secondary_text` AttributeError (Phase 5-4)."""

    def test_call_does_not_raise_attribute_error(self):
        """
        Pre-fix this raised:
            AttributeError: 'MessageDialog' object has no attribute
            'format_secondary_text'
        at ui/window.py:945. Post-fix the method must construct the dialog
        cleanly using GTK4's `secondary_text=` constructor kwarg.
        """
        win = _StubParentWindow()
        try:
            win._show_auto_accept_warning(
                agent_name="coder",
                on_confirm=lambda: None,
                on_cancel=lambda: None,
            )
        except AttributeError as e:
            if "format_secondary_text" in str(e):
                pytest.fail(
                    f"REGRESSION: GTK3 API still in code: {e}. "
                    "Fix is `secondary_text=` constructor kwarg on Gtk.MessageDialog."
                )
            raise  # Re-raise any other AttributeError (real bug)

    def test_call_does_not_raise_any_exception(self):
        """No unexpected exception types from dialog construction."""
        win = _StubParentWindow()
        # If anything other than the expected dialog wiring raised, fail loudly.
        win._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )


class TestShowAutoAcceptWarningResponseRouting:
    """
    The dialog's response handler routes Gtk.ResponseType.OK to on_confirm
    and Gtk.ResponseType.CANCEL (and all other responses) to on_cancel.
    (Phase 5-4 spec: confirm enables auto-accept; cancel snaps toggle back.)
    """

    def test_ok_response_invokes_on_confirm(self):
        win = _StubParentWindow()
        confirm_calls = []
        cancel_calls = []
        win._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: confirm_calls.append(True),
            on_cancel=lambda: cancel_calls.append(True),
        )
        # Find the dialog that was shown via _show_auto_accept_warning
        dialog = self._extract_last_message_dialog(win)
        # Simulate user clicking "Turn On"
        dialog.response(Gtk.ResponseType.OK)
        assert confirm_calls == [True], (
            f"Expected on_confirm to be called once, got {confirm_calls}"
        )
        assert cancel_calls == [], (
            f"Expected on_cancel NOT to be called, got {cancel_calls}"
        )

    def test_cancel_response_invokes_on_cancel(self):
        win = _StubParentWindow()
        confirm_calls = []
        cancel_calls = []
        win._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: confirm_calls.append(True),
            on_cancel=lambda: cancel_calls.append(True),
        )
        dialog = self._extract_last_message_dialog(win)
        # Simulate user clicking "Cancel"
        dialog.response(Gtk.ResponseType.CANCEL)
        assert cancel_calls == [True], (
            f"Expected on_cancel to be called once, got {cancel_calls}"
        )
        assert confirm_calls == [], (
            f"Expected on_confirm NOT to be called, got {confirm_calls}"
        )

    def test_default_response_is_cancel(self):
        """
        Per Phase 5-4 spec: set_default_response(Gtk.ResponseType.CANCEL).
        Verify default is Cancel (safety: accidental Enter goes to Cancel,
        not Turn On).
        """
        win = _StubParentWindow()
        win._show_auto_accept_warning(
            agent_name="coder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = self._extract_last_message_dialog(win)
        assert dialog.get_default_response() == Gtk.ResponseType.CANCEL

    @staticmethod
    def _extract_last_message_dialog(window: Gtk.ApplicationWindow) -> Gtk.MessageDialog:
        """
        Walk the GTK child tree to find the MessageDialog created by
        _show_auto_accept_warning.
        """
        # MessageDialog.show() normally makes it a descendant of the
        # transient_for parent. The dialog itself is the last Window created.
        # GTK4 API: enumerate via Gtk.Window.list_toplevels() would list
        # application-level windows; but our dialog.show() makes it part of
        # the same application. We use the well-known pattern of retrieving
        # the most recent Gtk.MessageDialog from the transient_for's child
        # list.
        result = None
        for child in window.get_children():
            if isinstance(child, Gtk.MessageDialog):
                result = child
        if result is None:
            # Walk grandchildren too (defensive)
            stack = list(window.get_children())
            while stack and result is None:
                node = stack.pop()
                if isinstance(node, Gtk.MessageDialog):
                    result = node
                if hasattr(node, "get_children"):
                    stack.extend(node.get_children())
        if result is None:
            raise AssertionError(
                "No MessageDialog found under parent window — "
                "_show_auto_accept_warning may have failed to create it"
            )
        return result


class TestShowAutoAcceptWarningDialogContent:
    """Verify the dialog's primary and secondary text are populated."""

    def test_primary_text_mentions_agent_name(self):
        win = _StubParentWindow()
        win._show_auto_accept_warning(
            agent_name="SuperCoder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = self._extract_last_message_dialog_for_test(win)
        primary = dialog.get_property("text")
        assert "SuperCoder" in primary, (
            f"Primary text should mention agent name; got: {primary!r}"
        )

    def test_secondary_text_mentions_agent_name(self):
        win = _StubParentWindow()
        win._show_auto_accept_warning(
            agent_name="SuperCoder",
            on_confirm=lambda: None,
            on_cancel=lambda: None,
        )
        dialog = self._extract_last_message_dialog_for_test(win)
        secondary = dialog.get_property("secondary-text")
        assert "SuperCoder" in secondary, (
            f"Secondary text should mention agent name; got: {secondary!r}"
        )

    @staticmethod
    def _extract_last_message_dialog_for_test(window):
        return TestShowAutoAcceptWarningResponseRouting._extract_last_message_dialog(window)
