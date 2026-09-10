# Crabcakes Performance Analysis — Core Loop / UI Lag

**Date:** 2026-09-01
**Scope:** Read-only code analysis of `/path/to/projects/crabcakes` (~40k lines Python/GTK4)
**Focus:** UI unresponsiveness during agent implementation loops (tab switching nearly impossible while a loop runs)
**Files modified:** none

---

## Summary

Root cause of the lag is **GIL contention + main-thread saturation**, not slow I/O. The agent runtime, SSE streaming parser, tool execution, and all UI render preparation run as Python threads in the same process as the GTK main loop. During a hot tool loop, the token pipeline pushes hundreds of main-loop events per second, starving the GTK main thread.

Findings, worst first:

---

## 1. GIL starvation of the GTK main thread (root cause)

The agent runtime (`agent/runtime.py`, `_run_loop`), SSE streaming parser (`agent/llm/streaming.py`), tool execution, and all UI render prep run as Python threads **in the same process** as the GTK main loop. Python's GIL means every delta parse, JSON decode, and text-processing burst steals timeslices from the main thread. GTK4 in PyGObject is notoriously sensitive to this — the UI feels "next to impossible to click" exactly when the tool loop is hot. Threading exists everywhere (correctly via `GLib.idle_add`), but threads don't help when the work is pure-Python CPU-bound.

**Fix direction:** move the runtime loop to a **subprocess** (or separate process with IPC), or at minimum move SSE parsing into C-speed paths (see #3).

## 2. Per-delta `GLib.idle_add` flood

`agent_runtime_handler._on_text_delta` → `GLib.idle_add` for **every SSE delta**, then a second `idle_add`-equivalent inside the render handler. Each idle callback is a main-loop scheduling event; at hundreds of deltas/sec the main loop queue itself becomes the bottleneck even though rendering is throttled (50ms handler + 150ms `set_text`). Also each dispatch re-checks tokens/dicts on the main thread.

**Fix:** coalesce deltas in the runtime thread and dispatch at most one update per 100–150ms (timer-driven pull model instead of push-per-delta).

## 3. Full-cumulative-text set_text — O(n²) streaming

Gateway/runtime sends **full cumulative text in every delta** (documented in `chat_render_handler.update_streaming`). `sb.label.set_text(full_text)` every 150ms means Pango re-layouts a growing string — O(n²) total work on the main thread, brutal for long responses. Compounded by `self._streaming_text[session_key] = ... + text` string concatenation (O(n) copy per delta) in the handler.

**Fix:** stream incremental appends into a `Gtk.TextBuffer`/`GtkTextView`, or set text at ≥500ms intervals; accumulate with a list + join.

## 4. Runtime global lock during hot paths

`runtime.py` has ~50 uses of `self._lock`; `_run_loop` acquires it repeatedly per iteration, and `send_message`/`cancel`/`_dispatch` all contend. On a multi-tab multi-agent run, sessions serialize on this lock and the resulting callback bursts all land on the main thread at once.

**Fix:** shard locks per session_key; never hold `_lock` across callback dispatch.

## 5. FeedBar/activity timers (200ms × multiple)

`activity_handler.py` runs `_live_update` every 200ms, idle pulse every 200ms, plus done-flash and send-initiated timers — several `timeout_add` tickers rebuilding Pango markup strings (`_streaming_label()` builds new markup + does arithmetic every tick) during exactly the same window streaming is hammering the UI.

**Fix:** single 250ms ticker for all status UI; skip markup rebuild when values unchanged.

## 6. Final-render cost spike at `end_streaming`

When a turn completes, `end_streaming` replaces the plain streaming bubble with a fully formatted one (`process_segments`, markdown, syntax highlighting, crabcard parsing) — for a long implementation-loop response that's a single large main-thread stall, exactly when the user tries to switch tabs. The 2-worker `ThreadPoolExecutor` only covers part of it; widget assembly (`_assemble_from_processed`) still runs on the main thread.

**Fix:** keep the plain-text bubble and upgrade formatting lazily/incrementally; cap crabcard parsing cost.

## 7. Minor contributors

- `agent/tools.py:479` — `os.walk` over the project tree on the runtime thread; GIL load during tool loop. Consider `scandir` pruning or caching.
- `agent/llm/streaming.py` — retry `time.sleep(wait_s)` blocks a thread but not the UI; fine, just thread-pool waste.
- `ui/views/file_tree.py` (2391 lines) — spawns a thread per operation; fine individually, but combined `idle_add` bursts add up.
- `chat_render_handler` — render pool is `max_workers=2` **shared as a class attribute** across all tabs; one heavy render starves another tab's chat.

---

## Priority order (expected impact)

1. **Coalesce deltas → single throttled dispatch** (#2) — cheap, big win
2. **Incremental text append instead of cumulative `set_text`** (#3)
3. **Move runtime/SSE parsing out of the GTK process** or off pure-Python paths (#1)
4. **Single status ticker** (#5) + lazy final render (#6)
5. **Lock sharding** (#4)

---

## Bottom line

The lag is architectural — one process, one GIL, with the token pipeline pushing hundreds of main-loop events per second during agent runs. Items 1–2 are low-risk patches that should make tab switching usable immediately; item 3 is the real fix.
