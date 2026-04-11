# tests/test_media_handler.py
"""Tests for MediaHandler — STT toggle + improve callback."""

import sys
import pytest
from unittest.mock import MagicMock


class FakeGLib:
    """Simulates GLib.idle_add — stores callbacks but does NOT run them until dispatch() is called."""

    def __init__(self):
        self._pending = []

    def idle_add(self, fn, *args, **kwargs):
        self._pending.append((fn, args, kwargs))
        return len(self._pending)

    def dispatch_all(self):
        """Simulate GTK idle cycle — run all pending callbacks in order."""
        results = []
        while self._pending:
            fn, args, kwargs = self._pending.pop(0)
            results.append(fn(*args, **kwargs))
        return results


class FakeTextIter:
    """Fake Gtk.TextIter — minimal stub."""

    def __init__(self):
        pass


class FakeTextBuffer:
    """Fake Gtk.TextBuffer — supports get_text/set_text and iter methods."""

    def __init__(self, initial=""):
        self._text = initial

    def get_text(self, start_iter, end_iter, include_hidden=True):
        return self._text

    def set_text(self, text):
        self._text = text

    def get_start_iter(self):
        return FakeTextIter()

    def get_end_iter(self):
        return FakeTextIter()


class FakeTextView:
    """Fake Gtk.TextView — has get_buffer() returning FakeTextBuffer."""

    def __init__(self, buffer):
        self._buffer = buffer

    def get_buffer(self):
        return self._buffer


class FakeMainContent:
    """Fake MainContent — mimics real MainContent interface."""

    def __init__(self, initial_input=""):
        self._stt_state = "idle"
        self._input_text = initial_input
        self._improved_button = MagicMock()
        self._append_calls = []
        self._input_buffer = FakeTextBuffer(initial_input)
        self._input_view = FakeTextView(self._input_buffer)

    def update_stt_state(self, state):
        self._stt_state = state

    def append_stt_text(self, text):
        self._append_calls.append(text)

    def replace_input_text(self, text):
        self._input_text = text
        self._input_buffer._text = text

    @property
    def user_input(self):
        """Fake Gtk.TextView — get_buffer() returns FakeTextBuffer."""
        return self._input_view

    def set_on_stt_click(self, cb):
        pass

    def set_on_improve_click(self, cb):
        pass


class FakeSTTEngine:
    """Fake STTEngine — matches new STTEngine stop_async API."""

    def __init__(self, on_result=None):
        self._on_result = on_result
        self._is_recording = False
        self._transcript_text = ""

    @property
    def is_recording(self):
        return self._is_recording

    def start(self):
        self._is_recording = True

    def stop_async(self, on_done=None):
        self._is_recording = False
        callback = on_done or self._on_result
        if callback:
            callback(self._transcript_text)

    def stop(self):
        self._is_recording = False
        return self._transcript_text


class FakeImprove:
    """Fake improve module — intercepts improve_prompt calls."""

    def __init__(self, result_text="", result_error=None):
        self._calls = []
        self._result_text = result_text
        self._result_error = result_error
        self._pending_callback = None

    def improve_prompt(self, text, callback, GLib=None):
        self._calls.append((text, callback, GLib))
        self._pending_callback = (callback,)
        if GLib is None:
            callback(self._result_text, self._result_error)


_UNSET = object()


def make_handler(
    main_content=None,
    improve_module=None,
    GLib_module=_UNSET,
    stt_engine_class=None,
):
    from ui.handlers.media_handler import MediaHandler

    return MediaHandler(
        main_content=main_content or FakeMainContent(),
        improve_module=improve_module or FakeImprove(),
        GLib_module=GLib_module if GLib_module is not _UNSET else FakeGLib(),
        stt_engine_class=stt_engine_class or FakeSTTEngine,
    )


# ── STT Tests ────────────────────────────────────────────────────────────────


class TestSTTStartStop:
    """STT starts recording when not already recording, stops when recording."""

    def test_click_stops_recording(self):
        """Clicking while recording stops it, appends transcript via callback."""
        mc = FakeMainContent()
        GLib = FakeGLib()
        handler = make_handler(main_content=mc, GLib_module=GLib)
        handler._stt_engine._transcript_text = "hello world"

        handler.on_stt_click()  # start
        handler.on_stt_click()  # stop_async → callback → idle_add

        assert not handler._stt_engine.is_recording
        assert mc._stt_state == "idle"
        GLib.dispatch_all()  # flush idle callbacks
        assert mc._append_calls == ["hello world"]

    def test_click_starts_recording(self):
        """Clicking while not recording starts recording."""
        mc = FakeMainContent()
        handler = make_handler(main_content=mc)

        handler.on_stt_click()

        assert handler._stt_engine.is_recording
        assert mc._stt_state == "recording"

    def test_stop_with_empty_transcript_no_append(self):
        """Empty transcript is not appended."""
        mc = FakeMainContent()
        GLib = FakeGLib()
        handler = make_handler(main_content=mc, GLib_module=GLib)
        handler._stt_engine._transcript_text = ""
        handler._stt_engine.start()

        handler.on_stt_click()
        GLib.dispatch_all()

        assert mc._append_calls == []


class TestSTTPartialTranscript:
    """_on_result dispatches transcript to GTK main thread via GLib.idle_add."""

    def test_result_callback_dispatched_via_glib(self):
        """_on_result queues append_stt_text via GLib.idle_add."""
        mc = FakeMainContent()
        GLib = FakeGLib()
        handler = make_handler(main_content=mc, GLib_module=GLib)

        handler._on_result("spoken words")

        assert mc._append_calls == []
        assert len(GLib._pending) == 1

        GLib.dispatch_all()

        assert mc._append_calls == ["spoken words"]

    def test_result_callback_direct_without_glib(self):
        """Without GLib, _on_result calls append_stt_text synchronously."""
        mc = FakeMainContent()
        handler = make_handler(main_content=mc, GLib_module=None)

        handler._on_result("direct call")

        assert mc._append_calls == ["direct call"]


class TestSTTVoiceSend:
    """Voice send: after stopping with transcript, calls sync callback via callback chain."""

    def test_stop_with_transcript_calls_sync_callback(self):
        """When STT stops with non-empty transcript, calls _sync_callback with text."""
        mc = FakeMainContent()
        GLib = FakeGLib()
        sync = MagicMock()
        handler = make_handler(main_content=mc, GLib_module=GLib)
        handler._sync_callback = sync
        handler._stt_engine._transcript_text = "spoken words"
        handler._stt_engine.start()

        handler.on_stt_click()  # stop_async → callback → idle_add → _append_and_send → sync_callback

        GLib.dispatch_all()  # flush idle callbacks
        sync.assert_called_once_with("spoken words")

    def test_stop_with_empty_transcript_no_callback(self):
        """Empty transcript does not trigger sync callback."""
        mc = FakeMainContent()
        GLib = FakeGLib()
        sync = MagicMock()
        handler = make_handler(main_content=mc, GLib_module=GLib)
        handler._sync_callback = sync
        handler._stt_engine._transcript_text = ""
        handler._stt_engine.start()

        handler.on_stt_click()
        GLib.dispatch_all()

        sync.assert_not_called()


# ── Improve Tests ─────────────────────────────────────────────────────────────


class TestImproveClick:
    """Improve button sends current input text to MiniMax API."""

    def test_noop_when_input_empty(self):
        """on_improve_click returns early if input is empty."""
        mc = FakeMainContent(initial_input="")
        handler = make_handler(main_content=mc)

        handler.on_improve_click()

        mc._improved_button.set_sensitive.assert_not_called()

    def test_disables_button_before_api_call(self):
        """Button is disabled before improve API is called."""
        mc = FakeMainContent(initial_input="original text")
        improve = FakeImprove()
        handler = make_handler(main_content=mc, improve_module=improve)

        handler.on_improve_click()

        mc._improved_button.set_sensitive.assert_called_once_with(False)

    def test_sends_input_text_to_api(self):
        """on_improve_click extracts and sends current input text."""
        mc = FakeMainContent(initial_input="raw input text")
        improve = FakeImprove()
        handler = make_handler(main_content=mc, improve_module=improve)

        handler.on_improve_click()

        assert improve._calls[0][0] == "raw input text"


class TestImproveResult:
    """Improve result replaces input text or re-enables button on error."""

    def test_result_replaces_input_text(self):
        """Successful improve result replaces input with improved text."""
        mc = FakeMainContent()
        handler = make_handler(main_content=mc)
        handler._mc._improved_button = MagicMock()

        handler._on_improve_result("Better prompt text", None)

        assert mc._input_text == "Better prompt text"
        mc._improved_button.set_sensitive.assert_called_once_with(True)

    def test_result_reenables_button_on_error(self):
        """Error message re-enables the button."""
        mc = FakeMainContent()
        handler = make_handler(main_content=mc)
        handler._mc._improved_button = MagicMock()

        handler._on_improve_result(None, "API error")

        mc._improved_button.set_sensitive.assert_called_once_with(True)

    def test_empty_result_no_change(self):
        """Empty improved text does not change input."""
        mc = FakeMainContent(initial_input="original")
        handler = make_handler(main_content=mc)
        handler._mc._improved_button = MagicMock()

        handler._on_improve_result("", None)

        assert mc._input_text == "original"
        mc._improved_button.set_sensitive.assert_called_once_with(True)
