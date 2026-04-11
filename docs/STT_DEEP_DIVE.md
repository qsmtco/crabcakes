# STT Deep Dive Report — Prompt Button Startup Delay

**Date:** 2026-04-11
**Author:** Qaster

## The Problem

User reports a ~4 second delay between clicking the Prompt (STT) button and being able to speak.

## Root Cause: faster-whisper `base` model transcription is 3.8 seconds for 2 seconds of audio

The delay is **NOT on the recording start side.** The actual culprit is on the **stop/transcribe side**, but it manifests as a perceived startup delay because:

1. User clicks Prompt → recording starts (fast, ~300ms to ALSA open)
2. User speaks for a few seconds
3. User clicks Prompt again to stop → **3.8 seconds of CPU grinding** while `base` model transcribes
4. During transcription, the UI appears frozen/unresponsive (compute happens on a background thread, but the result takes forever)

**If the user is perceiving 4 seconds *before* speaking**, it's because they're remembering the lag from the *previous* stop cycle, or the button state change feels delayed due to main thread blocking somewhere.

## Timing Breakdown

| Step | Duration | Notes |
|------|----------|-------|
| Button click → thread start | <1ms | Trivial |
| `Popen("arecord")` | ~1ms | Fork + exec |
| ALSA device open (`plughw:CARD=PCH,DEV=0`) | **230ms** | Hardware negotiation via ALSA plugin |
| WAV header written | <1ms | 44 bytes |
| First audio byte captured | ~350ms total | 230ms ALSA + ~125ms first ALSA period |
| `base` model load (cold) | **840ms** | Lazy — only loads on first transcription |
| `base` model load (warm) | **460ms** | Cached by faster-whisper internally |
| `base` model transcribe 2s audio | **3,833ms** | **This is the bottleneck** |
| `tiny` model load (cold) | **3,505ms** | First download |
| `tiny` model transcribe 2s audio | **484ms** | 8x faster |

## Architecture Trace: Click to Audio

```
User clicks "Prompt" button
  → MainContent._on_prompt_clicked()
    → self._on_stt_start_stop()  [callback set by window]
      → MediaHandler.on_stt_click()
        → self._mc.update_stt_state("recording")  [button shows "■ Stop"]
        → self._stt_engine.start()
          → threading.Thread(target=_capture_loop, daemon=True).start()
            → subprocess.Popen(["arecord", "-D", "plughw:CARD=PCH,DEV=0", ...])
              → 230ms: ALSA device opens, hardware negotiation
              → WAV header written (44 bytes to stdout)
              → read loop begins capturing PCM chunks (1-second reads)

User clicks "■ Stop" button
  → MainContent._on_prompt_clicked()
    → MediaHandler.on_stt_click()
      → self._mc.update_stt_state("idle")  [button shows "Prompt"]
      → self._stt_engine.stop_async(on_done=self._on_result)
        → self._recording = False
        → capture_thread.join()  [waits for arecord to drain]
        → spawn worker thread:
          → _transcribe_frames(frames)
            → _load_model()  [840ms first time, 460ms after]
            → build WAV in memory
            → model.transcribe(buf, language="en")  [3,833ms for 2s audio]
          → GLib.idle_add(callback, text)
        → MediaHandler._on_result(text)
          → GLib.idle_add(_append_and_send, text)
            → MainContent.append_stt_text(text)
              → buf.insert_at_cursor(text)
```

## Key Findings

### 1. The `base` model is too slow for real-time use

**3.8 seconds to transcribe 2 seconds of audio** on CPU (int8). That's ~1.9x realtime, meaning:
- 5 seconds of speech → ~9.5 seconds of transcription
- User waits nearly 10 seconds after clicking Stop before seeing text

The `tiny` model does the same 2 seconds in **0.48 seconds** (0.24x realtime) — usable.

### 2. ALSA device open is 230ms on `plughw:CARD=PCH,DEV=0`

This is a direct hardware ALSA device. Using PipeWire's ALSA plugin instead:
- `default`: **22ms** (10x faster)
- `sysdefault:CARD=PCH`: **5ms** (46x faster)

The `plughw:` path bypasses PipeWire and talks to hardware directly, incurring the full ALSA negotiation cost.

### 3. Model is loaded lazily on first transcription

First call to `_transcribe_frames()` triggers `_load_model()` which takes 840ms. Subsequent calls skip this. But the model is per-`STTEngine` instance — `MediaHandler` creates one instance at startup, so the cold load only happens once per app launch.

### 4. `transcribe()` returns a lazy generator

The `model.transcribe()` call itself is nearly instant (~28ms). The actual compute happens when iterating the generator (`for seg in segments`). This is a common gotcha — profiling just the `transcribe()` call shows misleadingly fast results.

## Recommendations

### Quick Win: Switch to `tiny` model (saves ~3.4s per transcription)

Change default `model_size` from `"base"` to `"tiny"` in `STTEngine.__init__()` or set `STT_MODEL_SIZE=tiny` env var. Accuracy drops slightly but for voice-to-text prompts it's fine.

### Quick Win: Use PipeWire ALSA device (saves ~220ms on recording start)

Change `device` default from `"plughw:CARD=PCH,DEV=0"` to `"default"` in `STTEngine.__init__()`. Uses PipeWire's ALSA plugin which opens in 22ms instead of 230ms.

### Medium Effort: Preload model at app startup

Call `_load_model()` in `MediaHandler.__init__()` or in a background thread shortly after app launch. Eliminates the 840ms cold load on first transcription.

### Future: Streaming transcription

Instead of record-all-then-transcribe, stream audio to the model in chunks for real-time partial results. This would require switching from faster-whisper's batch API to its streaming API or a different engine entirely.

## File Reference

| File | Role |
|------|------|
| `ui/views/main_content.py` L363-390 | Prompt button, STT state machine, `append_stt_text()` |
| `ui/handlers/media_handler.py` L30-60 | `on_stt_click()`, `_on_result()`, `_append_and_send()` |
| `utils/stt.py` | `STTEngine`: `start()`, `stop_async()`, `_capture_loop()`, `_load_model()`, `_transcribe_frames()` |
| `ui/window.py` L164-166 | Wires `set_on_stt_click` → `media_handler.on_stt_click` |
