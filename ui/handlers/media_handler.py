# ui/handlers/media_handler.py
# MediaHandler — STT (push-to-talk) + prompt improvement.
#
# Thread safety: STTEngine callbacks fire from its background thread.
# All GTK operations are dispatched via GLib.idle_add() inside _on_stt_partial().
# improve_prompt() dispatches its callback via GLib.idle_add when GLib is provided.

from typing import Callable


class MediaHandler:
    """Handles STT (whisper.cpp push-to-talk) and prompt improvement."""

    def __init__(
        self,
        main_content,
        improve_module=None,
        GLib_module=None,
        stt_engine_class=None,
    ):
        from utils.stt import STTEngine

        self._mc = main_content
        self._improve = improve_module
        self._GLib = GLib_module
        self._stt_class = stt_engine_class or STTEngine
        self._sync_callback: Callable = None  # called after voice send, with text

        self._stt_engine = self._stt_class(on_partial=self._on_stt_partial)

    # ── STT — Public API ────────────────────────────────────────────────────

    def on_stt_click(self, _btn=None):
        """Toggle STT recording on Prompt button click."""
        if self._stt_engine.is_recording:
            text = self._stt_engine.stop()
            self._mc.update_stt_state("idle")
            if text:
                self._mc.append_stt_text(text)
                if self._sync_callback:
                    self._sync_callback(text)
        else:
            self._mc.update_stt_state("recording")
            self._stt_engine.start()

    def set_on_send_callback(self, cb: Callable):
        """Window calls this so MediaHandler can trigger ChatHandler.on_send() after voice input."""
        self._sync_callback = cb

    # ── STT — Internal ─────────────────────────────────────────────────────

    def _on_stt_partial(self, text):
        """
        Append a partial transcript to the input buffer.
        Fires from STT background thread — dispatch to GTK main thread.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._mc.append_stt_text, text)
        else:
            self._mc.append_stt_text(text)

    # ── Improve — Public API ────────────────────────────────────────────────

    def on_improve_click(self, _btn=None):
        """Get current input text, send to MiniMax API for improvement."""
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        if not text:
            return
        self._mc._improved_button.set_sensitive(False)
        improve_prompt = self._improve.improve_prompt if self._improve else None
        if improve_prompt is None:
            return
        improve_prompt(text, self._on_improve_result, GLib=self._GLib)

    # ── Improve — Internal ─────────────────────────────────────────────────

    def _on_improve_result(self, improved_text, error):
        """
        Handle improve API result — replace input with improved text.
        improve_prompt() already dispatched via GLib.idle_add when GLib was provided.
        """
        self._mc._improved_button.set_sensitive(True)
        if error:
            import logging
            logging.warning("[improve] error: %s", error)
            return
        if improved_text:
            self._mc.replace_input_text(improved_text)
