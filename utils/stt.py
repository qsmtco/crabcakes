# utils/stt.py
# Speech-to-text via faster-whisper — push-to-talk with stop_async pattern.
#
# Architecture:
#   arecord (ALSA/PipeWire, 16kHz mono) → raw PCM in memory
#     → faster-whisper (Python API, model loaded once) → transcript via callback
#
# Environment:
#   STT_MODEL_SIZE  — faster-whisper model size, default "tiny.en".
#                    Values: "tiny.en", "base.en", "small.en", "medium.en", etc.

import os
#
# Security Manifest:
#   Reads: ALSA device ("default" via PipeWire ALSA plugin)
#   No files written; no network calls; no secrets

import io
import subprocess
import threading
import wave

# Default capture: 16kHz mono (whisper/faster-whisper native)
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


class STTEngine:
    """
    Push-to-talk STT using faster-whisper (CTranslate2 + int8 CPU).

    Lifecycle:
        stt = STTEngine(on_result=callback)
        stt.start()         → begin capturing audio
        stt.stop_async()   → stop capture, transcribe in background, callback(text)
        stt.stop()         → stop capture, transcribe, return text (blocking)

    Audio source: PipeWire ALSA plugin ("default" device).
    Much faster device open than direct hardware (~5ms vs ~230ms).
    """

    def __init__(
        self,
        model_size=None,
        device="default",
        on_result=None,
    ):
        """
        Args:
            model_size:   faster-whisper model — "tiny.en" for English-only (fastest CPU).
                          Respects STT_MODEL_SIZE env var as fallback. Values: "tiny.en",
                          "base.en", "small.en", "medium.en", etc. None → use env var or default.
            device:       ALSA device name for capture (arecord -D <device>).
                          "default" uses PipeWire ALSA plugin (~5ms open vs ~230ms direct HW).
            on_result:    Callback(text: str) — called with transcript on stop_async.
        """
        self._model_size = model_size or os.environ.get("STT_MODEL_SIZE", "tiny.en")
        self._device = device
        self._on_result = on_result

        self._model = None       # loaded lazily on first transcription
        self._recording = False
        self._capture_thread = None
        self._capture_proc = None
        self._frames = []       # raw PCM bytes captured during this session

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Begin capturing audio from the microphone into memory."""
        if self._recording:
            return
        self._recording = True
        self._frames.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop_async(self, on_done=None):
        """
        Stop capturing and transcribe asynchronously in a background thread.

        Calls on_done(text) when transcription finishes.
        Uses GLib.idle_add if available to dispatch to GTK main thread.

        Args:
            on_done: Optional callback(text: str) — overrides on_result from __init__.
        """
        if not self._recording:
            return
        self._recording = False
        if self._capture_thread is not None:
            self._capture_thread.join()

        frames = list(self._frames)  # copy before background thread reads
        callback = on_done or self._on_result

        def _worker():
            text = self._transcribe_frames(frames)
            if callback:
                try:
                    from gi.repository import GLib
                    GLib.idle_add(lambda: callback(text) if text else callback(""))
                except ImportError:
                    callback(text or "")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def stop(self) -> str:
        """
        Stop capturing and transcribe synchronously.
        Blocks until transcription is complete.
        """
        if not self._recording:
            return ""
        self._recording = False
        if self._capture_thread is not None:
            self._capture_thread.join()
        return self._transcribe_frames(self._frames)

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── Internal ───────────────────────────────────────────────────────────────

    def _capture_loop(self):
        """Background thread: runs arecord at 16kHz mono, buffers PCM frames."""
        self._capture_proc = subprocess.Popen(
            [
                "arecord",
                "-D", self._device,
                "-f", "S16_LE",   # 16-bit signed little-endian
                "-t", "wav",
                "-q",             # quiet
                "-r", str(SAMPLE_RATE),
                "-c", str(CHANNELS),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        while self._recording:
            stdout = self._capture_proc.stdout
            if stdout is None:
                break
            # Read in 1-second chunks
            chunk = stdout.read(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
            if not chunk:
                break
            self._frames.append(chunk)

        self._capture_proc.terminate()
        self._capture_proc.wait()

    def _load_model(self):
        """Load faster-whisper model lazily — cached for all subsequent calls."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )

    def _transcribe_frames(self, frames) -> str:
        """Convert captured frames to WAV in memory and transcribe with faster-whisper."""
        if not frames:
            return ""

        self._load_model()

        # Build WAV in memory
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(frames))

        buf.seek(0)
        segments, _ = self._model.transcribe(buf, language="en")
        text = "".join(seg.text for seg in segments).strip()
        return text
