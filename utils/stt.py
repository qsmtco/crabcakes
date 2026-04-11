# utils/stt.py
# Speech-to-text via whisper.cpp — push-to-talk with streaming partial results.
#
# Architecture:
#   arecord (ALSA/PipeWire) → raw PCM in memory → WAV assembled in Python
#     → whisper-cli subprocess → partial transcript via callback
#
# Security Manifest:
#   Reads: /dev/null, ALSA device (plughw:CARD=PCH,DEV=0 via arecord subprocess)
#   Writes: /tmp/crabcakes_stt_*.wav (temp chunks, deleted after use)
#   External: whisper.cpp CLI binary ($WHISPER_CLI or default path)
#   Env vars: WHISPER_CLI, WHISPER_MODEL (optional overrides)

import subprocess
import threading
import wave
import os
import tempfile

import numpy as np
import scipy.signal

# Default paths
DEFAULT_WHISPER_CLI = os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli")
DEFAULT_MODEL = os.path.expanduser("~/whisper.cpp/models/ggml-large-v3-turbo.bin")

# Audio capture parameters (whisper-native: 16kHz mono)
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit


class STTEngine:
    """
    Push-to-talk streaming STT using whisper.cpp CLI.

    Lifecycle:
        stt = STTEngine(on_partial=callback)
        stt.start()       # begins capturing audio
        stt.stop()       # stops capture, returns final transcript
        stt.cancel()     # stops capture, discards audio

    The callback `on_partial(text)` is called for each transcribed chunk
    as audio is processed. It may be called multiple times with
    incremental results.

    Audio source: ALSA device (plughw:CARD=PCH,DEV=0 via arecord).
    Works with PipeWire's ALSA plugin.
    """

    def __init__(
        self,
        whisper_cli=None,
        model=None,
        device="plughw:CARD=PCH,DEV=0",
        chunk_duration=3.0,
        on_partial=None,
    ):
        """
        Args:
            whisper_cli:  Path to whisper-cli binary.
            model:        Path to GGML model file.
            device:       ALSA device name for capture.
            chunk_duration: Seconds of audio per transcription chunk.
            on_partial:   Callback(text: str) — called with each partial result.
        """
        self._cli = whisper_cli or os.environ.get("WHISPER_CLI", DEFAULT_WHISPER_CLI)
        self._model = model or os.environ.get("WHISPER_MODEL", DEFAULT_MODEL)
        self._device = device
        self._chunk_duration = chunk_duration
        self._on_partial = on_partial

        self._recording = False
        self._cancelled = False
        self._capture_thread = None
        self._capture_proc = None
        # Ring buffer: list of raw PCM frames (bytes)
        self._frames = []
        self._frames_lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Begin capturing audio from the microphone."""
        if self._recording:
            return
        self._recording = True
        self._cancelled = False
        self._frames.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop(self) -> str:
        """
        Stop capturing and return the final transcript.
        Blocks until the last chunk is transcribed.
        """
        if not self._recording:
            return ""
        self._recording = False
        if self._capture_thread is not None:
            self._capture_thread.join()
        # Transcribe any remaining audio
        text = self._transcribe_frames()
        return text

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── Internal ───────────────────────────────────────────────────────────────

    def _capture_loop(self):
        """
        Background thread: runs arecord, reads stdout, accumulates PCM frames.
        Every chunk_duration seconds, spawns whisper-cli to transcribe the chunk.
        """
        self._capture_proc = subprocess.Popen(
            [
                "arecord",
                "-D", self._device,
                "-f", "cd",          # 16-bit little-endian, 44100Hz, stereo
                "-t", "wav",
                "-q",                # quiet
                "-r", "44100",       # explicit sample rate
                "-c", "2",           # stereo
                "-f", "S16_LE",      # signed 16-bit little-endian
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        target_frames = int(SAMPLE_RATE * self._chunk_duration)
        # CD audio: 44100Hz * 2 channels * 2 bytes = 176400 bytes/second
        cd_bytes_per_frame = 4  # 2 channels * 2 bytes
        frames_buf = []
        bytes_per_chunk = target_frames * cd_bytes_per_frame

        while self._recording:
            # Read a chunk of audio from arecord's stdout
            stdout = self._capture_proc.stdout
            if stdout is None:
                break
            data = stdout.read(bytes_per_chunk)
            if not data:
                break
            frames_buf.append(data)
            accumulated = b"".join(frames_buf)
            # Check if we have enough for one full chunk
            if len(accumulated) >= bytes_per_chunk:
                chunk = accumulated[:bytes_per_chunk]
                frames_buf = [accumulated[bytes_per_chunk:]]
                if not self._cancelled:
                    self._transcribe_chunk_async(chunk)

        # Stop arecord
        self._capture_proc.terminate()
        self._capture_proc.wait()

    def _transcribe_chunk_async(self, pcm_data):
        """Transcribe a PCM chunk in a background thread and call on_partial."""
        def worker():
            text = self._transcribe_pcm(pcm_data)
            if text and self._on_partial and not self._cancelled:
                self._on_partial(text)
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _transcribe_pcm(self, pcm_data: bytes) -> str:
        """Convert raw PCM to WAV and run whisper-cli, return transcript text.

        Pipeline: 44.1kHz stereo (from arecord) → resample to 16kHz mono
        → write WAV → whisper-cli.

        Resampling uses scipy.signal.resample_poly (rational polyphase filter,
        high quality, efficient). Ratio: 44100→16000 = 441/160."""
        import math

        # Source: 44.1kHz stereo S16_LE → int16 numpy array
        samples_stereo = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        stereo = samples_stereo.reshape(-1, 2)  # (N, 2) — (left, right)

        # Convert to mono (average channels)
        mono = stereo.mean(axis=1)

        # Rational resample: 44100 → 16000 = 160/441
        # gcd(44100, 16000) = 100, so up=160, down=441
        up = 160
        down = 441
        mono_16k = scipy.signal.resample_poly(mono, up, down)

        # Convert back to int16
        mono_16k_int = np.clip(mono_16k * 32768.0, -32768, 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir="/tmp") as f:
            wav_path = f.name

        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)   # mono
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(16000)
                wf.writeframes(mono_16k_int.tobytes())

            result = subprocess.run(
                [
                    self._cli,
                    "-m", self._model,
                    "-f", wav_path,
                    "--no-timestamps",
                    "-otxt",
                    "-np",
                    "-t", "4",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout.strip()
        except Exception:
            return ""
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def _transcribe_frames(self) -> str:
        """Transcribe all accumulated frames and return combined text."""
        if not self._frames:
            return ""
        all_pcm = b"".join(self._frames)
        if not all_pcm:
            return ""
        return self._transcribe_pcm(all_pcm)
