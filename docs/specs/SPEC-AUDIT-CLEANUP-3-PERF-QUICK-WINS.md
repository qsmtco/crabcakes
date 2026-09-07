# SPEC-AUDIT-CLEANUP-3 — Core-Loop Perf Quick Wins (delta coalescing, render throttle, ticker)

**Loop authority:** `prompts/implementationLoop.md` + `prompts/implementationSupervisor.md`
**Builder playbook:** `prompts/steelFramedCodeWriter.md` — load fresh, follow every rule.
**Source:** `docs/audits/2026-09-01-core-loop-performance.md` findings #2, #3, #5 — **verified against the live tree on 2026-09-07.** Line numbers are current.
**Precondition:** tree clean at `d55b656`. Independent of SPEC-1/2 but land after them (all three touch the same files; keep the diffs separable).
**Position:** This is the cheap, low-risk slice of the perf backlog. The architectural fixes (subprocess isolation #1, lock sharding #4, `end_streaming` spike #6, TextBuffer rework) are deliberately OUT of scope — later units.

---

## Verified current behavior (2026-09-07)

- `ui/handlers/agent_runtime_handler.py:995-1002` — `_on_text_delta` does `GLib.idle_add(self._do_text_delta, ...)` for **every SSE delta**, unconditionally. The 50ms throttle (`_delta_throttle_sec`, :78) only gates the render call *inside* the main-thread callback (:1070-1076). At hundreds of deltas/sec the main loop queue itself floods.
- `:1047` — `self._streaming_text[sk] = self._streaming_text.get(sk, "") + text` runs **on the main thread per delta** — O(n) copy per delta.
- `ui/handlers/chat_render_handler.py` `update_streaming` — `sb.label.set_text(sb.plain_text + " ▍")` with full cumulative text, throttled at 150ms (`_stream_throttle_sec`). Pango relayouts a growing string → O(n²) total main-thread work.
- `update_streaming` also contains a stray debug `print(f"[STREAM] update_streaming: SKIP ...")` on the not-streaming path.
- `ui/handlers/activity_handler.py` — `_live_update` on a 200ms timer (:604), `_idle_pulse` on a second 200ms timer (:699), plus done-flash and send-initiated timers; `_update_feedbar`/`_streaming_label` rebuild Pango markup strings every tick even when nothing changed. `on_gateway_event` calls `_resolve_agent_name(payload)` 6× with the same payload (~:333-470).

**Correctness invariants the refactor must preserve (all verified in current code):**
1. `_streaming_text` accumulation is ALWAYS complete — final render and crabcard extraction depend on it (`_do_response_complete` :1500-1546 reads via CRH `get_streaming_text`).
2. `sb.plain_text` is updated BEFORE the throttle check in `update_streaming` — it is always current even when `set_text` is skipped. Any new design must keep `sb.plain_text` current for the last delta before completion runs.
3. Stale/ended guards: `_ended_sessions` check and `_turn_tokens` mismatch check in `_do_text_delta` must keep working against deferred dispatches.
4. Empty-delta skip (`if not text: return`) must be preserved.
5. Idle callback ordering: delta dispatches scheduled before the completion dispatch must run before it (they do today; preserve producer→idle→completion ordering).

---

## Phase 1 — Producer-side delta coalescing (audit #2)

Rework `_on_text_delta` / `_do_text_delta` in `agent_runtime_handler.py`:

1. **Accumulate on the producer (runtime) thread:** move the string accumulation from `_do_text_delta` (:1047) into `_on_text_delta`. Keep `self._streaming_text` as the cumulative dict; producer does the concat (atomic str assignment under GIL; per-session single producer thread makes this race-free).
2. **Coalesced dispatch:** add `self._delta_dispatch_pending: dict[str, bool]` (or set). In `_on_text_delta` (after the empty-text skip): schedule `idle_add` only when no dispatch is pending AND `now - self._last_delta_dispatch.get(sk, 0.0) >= self._delta_throttle_sec`. Record the pending flag; pass the **current** `_turn_token` through.
3. **Trailing guarantee:** clear the pending flag at the END of `_do_text_delta` (after processing), so any delta that arrived during processing re-schedules. This guarantees the last delta batch always reaches `update_streaming` before the completion dispatch runs (invariant 2).
4. `_do_text_delta` becomes: guards (`_ended_sessions`, token mismatch) → start-bubble-if-needed logic (unchanged) → throttle bookkeeping → `update_streaming(sk, self._streaming_text[sk])`. It no longer receives/appends delta text.
5. Keep `_delta_throttle_sec = 0.05` (dispatch coalescing rate unchanged; the win is per-delta idle_add → ≤20/sec).

**Test (new, in the existing agent-runtime test file):** simulate ≥100 rapid deltas via `_on_text_delta` with a stubbed GLib (existing tests already stub GLib; reuse the pattern from tests around `test_agent_runtime.py:1417`). Assert: (a) number of `_do_text_delta` invocations ≤ ~number-of-deltas/20 + 2, (b) the final accumulated text contains every delta exactly once (no loss, no duplication), (c) a pending dispatch exists for the last delta (trailing guarantee).

## Phase 2 — Render throttle + unchanged guard (audit #3, label-level)

In `chat_render_handler.py update_streaming`:
1. Raise `_stream_throttle_sec` from 0.150 to **0.5** (audit: "set text at ≥500ms intervals" — Pango relayout of a growing string is the dominant main-thread cost).
2. Add an unchanged guard: skip `set_text` entirely when `sb.plain_text` is identical to the last value passed to `set_text` (track per-session last-rendered text). `sb.plain_text` assignment stays unthrottled (invariant 2).
3. Delete the debug `print` on the not-streaming path; replace with `_logger.debug` (module already has `_logger`).

**Tests:** throttle still bounds set_text calls (time-mocked or stubbed monotonic); unchanged text produces zero additional `set_text` calls; `sb.plain_text` updates even when `set_text` is skipped.

**Explicitly OUT of scope:** Gtk.TextBuffer/TextView incremental append — that is the chat-render unit's job (bubble unification changes these widgets).

## Phase 3 — Single status ticker (audit #5)

In `activity_handler.py`:
1. Consolidate `_live_update` (200ms) and `_idle_pulse` (200ms) into **one 250ms ticker** driven by the existing state machine (`_set_state` starts/stops it; both old entry points become internal branches of the single tick based on `self._state`).
2. **Skip-when-unchanged:** cache the last-rendered `(state, phase, hop_bucket, elapsed_bucket)` tuple; if unchanged since the last tick, skip the `_update_feedbar` markup rebuild and `_streaming_label()` string construction entirely.
3. Hoist `_resolve_agent_name(payload)` in `on_gateway_event` to a single call at the top of the handler; pass the resolved name down (currently 6× same payload).
4. Preserve all timer lifecycle semantics: `_stop_live_update`, `_stop_idle_pulse`, done-flash, send-initiated timers keep their public behavior (they now stop the single ticker). Update their docstrings, not their call sites.

**Tests:** existing activity tests must stay green; add: (a) two consecutive ticks with unchanged state produce no markup rebuild (spy on `_streaming_label`/`_update_feedbar`), (b) state transition restarts the single ticker correctly, (c) `_resolve_agent_name` called at most once per event.

---

## Acceptance criteria
1. Full suite green: `pytest tests/ -B` (stale-.pyc rule).
2. New tests from Phases 1-3 pass and would FAIL on the pre-change code (that's the point of each).
3. Invariant checks: a streaming session's final rendered text (post-`end_streaming`) is byte-identical to the full delta concatenation — covered by the Phase 1 test.
4. No behavior change visible to the user other than: streaming label updates at most 2×/sec (was ~6.7×/sec), status bar ticks at 250ms (was 200ms).
5. `git diff` touches only: `ui/handlers/agent_runtime_handler.py`, `ui/handlers/chat_render_handler.py`, `ui/handlers/activity_handler.py`, plus the test files. Anything else = out of scope, explain in the summary.

## Audit checklist (Debugger)
- **Attack the coalescer:** interleavings — delta arriving during `_do_text_delta` execution; delta after completion (must be dropped by `_ended_sessions`, never resurrect a bubble); two sessions streaming concurrently; token mismatch mid-batch; empty deltas; first-delta-of-turn while a stale dispatch is pending.
- Prove the trailing guarantee: deltas with NO further activity must still produce one final `update_streaming` before completion's crabcard extraction reads `plain_text`. Write or demand a test for this exact race.
- Verify invariant 2 survived: grep that `sb.plain_text = delta_text` still precedes every throttle return path.
- Confirm the unchanged-guard doesn't break the cursor: label shows `text + " ▍"` — a skipped set_text must not leave a stale shorter text with cursor mismatch (guard compares stored rendered text, including cursor handling).
- Run the full suite yourself; paste real output; `git status` clean of strays.