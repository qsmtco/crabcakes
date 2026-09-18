# PHASE 1 of 13 — Memory Probe (`scripts/crab_mem_probe.py`)

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.5 — read it before writing code.
**Files to change:** exactly one new file, `scripts/crab_mem_probe.py`. Nothing else.

## Context

This probe is the measurement instrument for the whole spec. Every later phase (eviction,
ticker de-dup) is judged by the slope this script reports, so its contract must exactly
mirror the existing perf probe.

## Requirements

1. **Read `scripts/crab_perf_probe.py` in full first.** Mirror its CLI contract exactly:
   - `--pid` **required**; `--duration` (default **1800** s); `--budget` (default **0.5**
     MB/min); optional `--feed-json PATH`.
   - Exit codes: **0** under budget, **1** over budget, **2** usage error, **3** process
     gone.
2. Sample `VmRSS` and `VmData` from `/proc/<pid>/status` every **10 s**; report the mean
   slope in **MB/min** for each.
3. **Card arrivals (`--feed-json`):** do NOT use feed.json file length or journal line
   count — compaction truncates the journal (`JOURNAL_COMPACT_THRESHOLD = 500`,
   `utils/feed_store.py:55`, truncated at `:700-701`), so it sawtooths 0..500.
   Use the delta of the **maximum `seq_num`** across cards (monotonic: `_apply_overlay`
   drops records for absent cards; pruning removes from the oldest end; `seq_num` is at
   `models/feed_card.py:108`, back-filled on load at `feed_handler.py:1608-1610`).
   If a second signal is wanted, sum `len(cards) + journal lines` per sample.
4. The script must be import-safe (no side effects on import) and runnable with
   `/usr/bin/python3` (stdlib only — no PyGObject, no third-party deps).

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Do NOT attempt to start the baseline measurement — the app instance that was targeted
  is no longer running. The supervisor coordinates measurement separately.
- Do NOT touch any other file. `scripts/crab_perf_probe.py` is read-only reference.

## Verification (run and paste output)

```bash
/usr/bin/python3 -m py_compile scripts/crab_mem_probe.py && echo COMPILE-OK
/usr/bin/python3 scripts/crab_mem_probe.py 2>&1; echo "exit=$?"          # expect usage, exit=2
/usr/bin/python3 scripts/crab_mem_probe.py --pid 999999 --duration 1 2>&1; echo "exit=$?"  # expect exit=3
/usr/bin/python3 scripts/crab_mem_probe.py --pid $$ --duration 2 --budget 100000 2>&1; echo "exit=$?"  # expect slope ~0.0, exit=0
```

## Report back

- Files changed with line counts (`wc -l`).
- All four verification command outputs pasted verbatim.
- COMPLETENESS checklist (mandatory — a delivery without it is returned):
  COMPLETENESS:
  - [x/not done] CLI contract mirrors crab_perf_probe.py (pid required, duration/budget/feed-json) — evidence
  - [x/not done] VmRSS + VmData sampled every 10s, slope MB/min reported — evidence
  - [x/not done] Arrival metric = max(seq_num) delta, not journal/file length — evidence
  - [x/not done] Exit codes 0/1/2/3 exercised — evidence
  - [x/not done] Related issues found but not fixed (flag, don't expand scope)

Please write per the instructions above — the word "please write" is the marker.
