# tests/test_render_error_callbacks.py
# Regression tests for A4/A5 (SPEC-AUDIT-CLEANUP-1 Class A):
# ChatRenderHandler deferred error callbacks closed over the bare
# except-variable `exc`, which Python deletes at except-block exit.

from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: F401 — import must precede handler import

from ui.handlers.chat_render_handler import ChatRenderHandler


class DeferredGLib:
    """GLib double that RECORDS idle_add callbacks without running them.

    Mirrors production timing: callbacks scheduled from inside an except
    block run on the main loop AFTER the block exits — at which point
    Python has deleted the bare except-variable. Running the recorded
    callbacks in the test body reproduces that timing.
    """

    def __init__(self):
        self.pending = []

    def idle_add(self, fn, *args, **kwargs):
        self.pending.append((fn, args, kwargs))
        return 0


def _wait_until(cond, timeout=5.0, poll=0.01):
    """Poll cond() until truthy or timeout. Returns True on success."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(poll)
    return cond()


class TestDeferredErrorCallbacks:
    """A4/A5 (SPEC-AUDIT-CLEANUP-1): on_error is dispatched via a lambda
    that closes over the bare except-variable `exc`. Python deletes `exc`
    at except-block exit, so the deferred callback raised NameError instead
    of reporting the error.

    Test design (two timing traps avoided):
    1. Callbacks are run INSIDE the patch context so the patched builder
       is still active when the deferred callback executes — otherwise the
       real builder runs and segfaults without a display server.
    2. render_async runs on a ThreadPoolExecutor; the test polls until the
       worker has scheduled the callback before running it.
    """

    def test_render_async_process_error_reaches_on_error(self):
        """A4: process_segments() raising must deliver the error via the
        deferred on_error callback, not NameError."""
        glib = DeferredGLib()
        handler = ChatRenderHandler(GLib_module=glib)
        errors = []
        with patch("ui.handlers.chat_render_handler.process_segments",
                   side_effect=Exception("render exploded")):
            handler.render_async("Agent", "text", "sk-async",
                                 on_bubble_ready=lambda w: None,
                                 on_error=lambda msg: errors.append(msg))
            assert _wait_until(lambda: len(glib.pending) >= 1), (
                "render_async worker never scheduled the error callback"
            )
            for fn, args, kwargs in glib.pending:
                fn(*args, **kwargs)  # was: NameError: name 'exc' is not defined
        assert errors == ["render exploded"], (
            f"A4 NameError masked by _dispatch: expected error text, got {errors}"
        )

    def test_render_build_error_reaches_on_error(self):
        """A5: build_role_bubble() raising must deliver the error via the
        deferred on_error callback, not NameError."""
        glib = DeferredGLib()
        handler = ChatRenderHandler(GLib_module=glib)
        errors = []
        with patch("ui.handlers.chat_render_handler.build_role_bubble",
                   side_effect=Exception("bubble exploded")):
            handler.render("Agent", "text", "sk-sync",
                           on_bubble_ready=lambda w: None,
                           on_error=lambda msg: errors.append(msg))
            for fn, args, kwargs in glib.pending:
                fn(*args, **kwargs)  # was: NameError: name 'exc' is not defined
        assert errors == ["bubble exploded"], (
            f"A5 NameError masked by _dispatch: expected error text, got {errors}"
        )
