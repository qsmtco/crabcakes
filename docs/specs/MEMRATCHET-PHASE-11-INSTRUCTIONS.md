# MEMRATCHET Phase 11 — Allocator experiment + honest-gate re-measure

**Loop:** SPEC-MEMORY-WIDGET-RATCHET.md §5 step 6 + step 8, §6 secondary gate.
**Builder:** Coder. **No product code in this phase.** Evidence discipline per loop norm:
no count without its command; paste actual output.

## Context

P1–P10 are closed, committed, and pushed (`95a0675`). The widget-invariant work is done
and audited. What remains is the measurement question the spec forces us to answer
honestly: the widget ratchet accounted for only ~0.18 MB/min of the recorded 4.55 MB/min
slope (~4%). P11 measures the residual and tests whether glibc allocator tuning moves it.

## Phase A — Discovery + baseline (passive; do first)

1. Find the live app instance:
   `ps -eo pid,stat,etime,args | awk '$3=="python3" && $4=="main.py" && $2 !~ /T/ {print}'`
   (spec §5.1 command, extended with `etime` so eligibility is visible in one shot).
2. **Eligibility** — the instance must satisfy at least one:
   - runtime ≥ 60 minutes (from `etime`), or
   - already holding > `MAX_LIVE_CARD_WIDGETS` (120) widgets.
   If neither: STOP and report blocked-on-PM with exactly what is needed. Do not run a
   short-window probe and present it as a gate measurement (round-2 BUG #5).
3. If eligible, run the baseline probe:
   `/usr/bin/python3 scripts/crab_mem_probe.py --pid <pid> --duration 3600 --budget 0.5`
   Record: slope (MB/min), window length, VmRSS/VmData at start/end.
4. **Widget count evidence:** report the observed live-widget count at measurement time,
   and state HOW you observed it (probe output field, CRABCAKES_DEBUG eviction log line,
   or other instrument). §6 requires the count alongside the slope — an unsourced count
   is a non-finding.

## Phase B — Allocator arm (REQUIRES PM CONSENT — do not relaunch on your own)

The relaunch closes the PM's current app session. Ask the PM (via the Supervisor) before
doing this. If consented:

1. PM relaunches with:
   `MALLOC_MMAP_THRESHOLD_=131072 MALLOC_TRIM_THRESHOLD_=131072 MALLOC_ARENA_MAX=2`
   (exact values from spec §5 step 6 — do not improvise).
2. Re-measure with the same probe, same duration, same eligibility rules.
3. Record which setting moved the slope, if any. Attribution matters: if you cannot
   distinguish which of the three env vars mattered, say exactly that.

## Phase C — Verdict + records

1. **Honest gate (spec §6, verbatim intent):** if the residual slope is still above the
   0.5 MB/min budget after Phase B, that is the honest outcome — report
   "invariant fixed, churn unaddressed" and escalate to the WebKit proposal
   (docs/proposals/WEBKIT-RENDER-SURFACE_PROPOSAL.md). Do NOT re-scope the spec to chase
   the remainder, and do NOT declare the gate met.
2. If the allocator settings help: bake them into
   `~/.local/share/applications/com.crabcakes.app.desktop` (Exec line env prefix) and say
   so in the report. If they don't: say so and stop.
3. Append the results to `docs/post-mortems/2026-09-17-MEMRATCHET-POST-MORTEM.md` as a
   dated "P11 measurement" section: baseline, arm, verdict, widget counts, commands.
4. No source changes → no red-check requirement. The probe itself is already committed.

## Deliverable

A report in the loop channel with: eligibility evidence, baseline numbers, arm numbers
(or the PM-consent ask), honest-gate verdict, where the records were appended, and the
exact commands for every number claimed.
