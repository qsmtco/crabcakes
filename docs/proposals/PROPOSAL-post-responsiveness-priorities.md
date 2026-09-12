# PROPOSAL: Post-Responsiveness Priorities — What To Fix After SPEC-UI-RESPONSIVENESS-2

**Date:** 2026-09-11
**Author:** Supervisor (read-only assessment; no code changed to produce this)
**Status:** Draft — for PM review
**Trigger:** PM request following the 2026-09-11 UI-responsiveness investigation and the writing of `docs/specs/SPEC-UI-RESPONSIVENESS-2.md`
**Depends on:** `docs/specs/SPEC-UI-RESPONSIVENESS-2.md` (Phases 1–8) landing first
**Related:** `docs/audits/2026-09-01-core-loop-performance.md`, `docs/proposals/PROPOSAL-ui-responsiveness-during-agent-runs.md`

> **Premise.** SPEC-UI-RESPONSIVENESS-2 fixes the measured freeze (feed read/write on the GTK main thread, ~0.62 s per tool result, 100 % of sampled main-thread cost). This document is explicitly about **what remains after that**. It is a prioritised remediation list, not a spec — each P0/P1 item should get its own work unit before implementation.

---

## 1. The through-line

This codebase's weakness is **not craftsmanship — it is verification**. There is no CI, no type checking, no performance gate, and a permanently-red test baseline. Every defect found during the 2026-09-11 investigation was found by a human reading code and attaching a profiler, not by a mechanism that catches regressions.

The consequence is concrete and measurable: a 0.62 s-per-tool-call stall, on the GTK main thread, sat unnoticed through an entire audit, a proposal, a six-phase spec, and a "performance quick wins" work unit — because nothing in the pipeline measured the running process.

**Therefore the first priority is detection, not features.** Close the detection gaps and the next bottleneck surfaces on its own.

---

## 2. P0 — Measurement infrastructure (do first; everything else depends on it)

### P0.1 — Performance regression gate

**Why:** the systemic failure was "nobody profiled the app". Fix the habit, not the single instance.

**What:** a test module (e.g. `tests/test_perf_feed.py`) that builds a realistic feed fixture and asserts hard bounds:

| Assertion | Bound | Rationale |
|---|---|---|
| `feed_handler.update_card()` with a 9,500-card feed | < 50 ms | was ~620 ms on 2026-09-11 |
| `feed_store.load_feed()` at `FEED_WINDOW_DEFAULT` | < 100 ms | measured 0.24 s pre-pruning |
| `append_card_update()` cost vs. an empty feed | within 3× | O(1) append invariant |
| Main-thread stall while a card update is enqueued | < 5 ms | the actual user-visible metric |

**Evidence:** the full 2026-09-11 investigation; §0 of SPEC-UI-RESPONSIVENESS-2 (29 stack dumps, 8,718-sample flamegraph).
**Effort:** 3–4 h. **Risk:** LOW.

### P0.2 — CI

**Why:** `ls .github/workflows/` returns nothing. All current rigour — worktree baseline diffs, byte-identical failure-set comparisons, red-first evidence — is a manual ritual performed by an agent that remembers to do it. Process rules enforced by willpower are not enforced.

**What:** workflows for pytest (chunked, or after P1.3 fixes the OOM), ruff, and pyright. At minimum, run on push and PR.

**Evidence:** no workflow files present; the AC3 post-mortem (§5, §11) documents manual verification runs.
**Effort:** 4–6 h. **Risk:** LOW (may surface the existing 40-failure baseline as failing CI — that is the point; see P1.3).

---

## 3. P1 — Debt that undermines the above

### P1.3 — Burn the 40-failure baseline; fix the OOM'ing test classes

**Why:** a permanently-red suite means a genuinely new failure is invisible against the noise. This directly negates the value of P0.2.

**What:** complete the already-started `SPEC-TEST-DEBT-1` burn-down (BUG-21 is the first item), and resolve the `TestEndStreaming*` classes that consume ~14 GB — currently worked around by "chunked runs".

**Evidence:** AC3 post-mortem §8 ("Pre-Existing Issues Flagged") — 2 BUG-21 failures root-cause-confirmed, 2 OOM classes baseline-proven since AC1.
**Effort:** 1–2 days. **Risk:** MEDIUM (touches the hottest guarded paths).

### P1.4 — Enforce static typing

**Why:** 52k production LOC across 129 files, dataclass-heavy, with **no mypy or ruff configuration** and a `pyrightconfig.json` that explicitly **excludes `ui/`** — the single largest surface. A recurring bug class found by adversarial audit (attribute drift, field/constructor mismatches, stale contracts after refactors) is what a type checker catches for free.

**What:** staged adoption —
1. `models/` + `utils/` (already inside pyright's include list) → enforce in CI.
2. `agent/` → enforce.
3. `ui/` → remove the exclusion, fix in waves.

**Evidence:** `pyproject.toml` dev deps list ruff but configure nothing; `pyrightconfig.json` include = gateway/models/utils, exclude = ui.
**Effort:** 1–2 days for (1) and (2); `ui/` is a multi-day burn-down. **Risk:** LOW for (1)–(2), MEDIUM for (3).

---

## 4. P2 — Architecture

### P2.5 — Decide the Phase 8 architectural question with data

**Why:** the 2026-09-01 audit named GIL contention / single-process runtime as the root cause and called the subprocess split "the real fix". The 2026-09-11 profiler found **zero** main-thread samples in that path. One of those two claims is wrong, and leaving it unresolved means the item sits forever as a vague "someday" fix.

**What:** run the Phase 8 spike in SPEC-UI-RESPONSIVENESS-2 — scope the subprocess/IPC option against the measurements — then formally either schedule it or close it with the evidence recorded.

**Evidence:** audit #1 vs. §0 of SPEC-UI-RESPONSIVENESS-2 (100 % of main-thread samples were in the feed path).
**Effort:** 2 h to write; ~half a day to spike. **Risk:** LOW.

### P2.6 — Decompose the god objects

**Why:** four files now carry most of the risk surface, and their size is the reason a "small, low-risk fix" is hard to land safely.

`agent/runtime.py` 2,734 · `ui/views/file_tree.py` 2,391 · `ui/handlers/agent_runtime_handler.py` 1,986 · `ui/handlers/feed_handler.py` 1,897

**What:** incremental extraction along seams already identified by prior refactors. The technique is proven here — SPEC-52/53 extracted `runTransition`/`authAndRole` successfully, and AC2/AC3 removed dead code safely.

**Evidence:** file sizes above; the extraction precedent in the git log.
**Effort:** multi-day, incremental. **Risk:** MEDIUM (behaviour-preserving refactor of hot code).

### P2.7 — Cap the chat tab's widget accumulation

**Why:** the same class of bug as the feed — unbounded growth that only manifests later. No cap exists anywhere (no `MAX_BUBBLES`, no per-tab pruning, no eviction).

**What:** bound the rendered bubbles per chat tab and drop the oldest (or virtualise), mirroring the feed's `PAGE_SIZE` + backlog pattern (`feed_handler.py:89`, `:1149-1151`).

**Evidence:** grep for `MAX_*BUBBLE|bubble_limit|max_children` finds only unrelated GTK flow-box and menu calls; process RSS was 1.5–1.7 GB after ~12 h of use.
**Effort:** 2–3 h. **Risk:** LOW–MEDIUM (scroll-position behaviour).

---

## 5. P3 — Design, not performance

### P3.8 — Re-examine the feed/CrabWatch emission design

**Why:** per-file-event `git diff` snapshots and one feed card per file change is a questionable *structure*, not merely a slow one. One agent turn touching 30 files produces 30 cards, 30 debounce timers, and up to 30 `git diff` subprocesses (`feed_handler.py:1619`, `crabwatch_handler.py:109`, `git_ops.py:353`).

**What:** discuss coalescing at the emission point — per turn, or per prompt — instead of the per-file firehose. Likely cheaper, faster to render, and more useful to read (one card per logical change rather than one per file touched).

**Evidence:** card source distribution in the live feed — 7,045 `agent`, 2,357 `system`/crabwatch, 98 `git` — with a 13.9 MB file and no pruning.
**Effort:** design discussion first, then a spec. **Risk:** MEDIUM (changes user-visible feed semantics; needs PM sign-off).

### P3.9 — Documentation hygiene

**Why:** 765 markdown files with demonstrated rot. Three separate "doc-lie" incidents are already logged in post-mortems, and this assessment found more (the Eagle Dispatch build-plan page contradicts the code; invoice/status drift). At this volume, unpoliced docs are a net negative — they consume review attention and mislead.

**What:** either a CI staleness check (e.g. verify that referenced file:line anchors still resolve) or an archival pass that moves completed specs/post-mortems into `docs/completed/` and out of the active tree.

**Evidence:** `find docs -name '*.md' | wc -l` = 765; doc-lie rule triggered three times per the AC3 post-mortem §5.4.
**Effort:** 1 day for the archival pass; 1–2 days for a checker. **Risk:** LOW.

---

## 6. What NOT to do

**Do not continue micro-optimising the streaming path.** AC3 (coalescing, 500 ms throttle, single 250 ms ticker, `set_text`) plus Phases 1–3 of SPEC-UI-RESPONSIVENESS-2 take the measured cost to near zero, and the profiler shows the remaining main-thread samples are idle. Further work on `set_text` variants, ticker intervals, or markup paths is optimising a solved problem while the unmeasured risks (no CI, no typing, unbounded growth) stay unmeasured.

---

## 7. Summary table

| Rank | Item | Effort | Risk | Why it sits here |
|---|---|---|---|---|
| P0.1 | Performance regression gate | 3–4 h | LOW | Fixes the habit that let a 0.62 s stall live for 2 months |
| P0.2 | CI (pytest/ruff/pyright) | 4–6 h | LOW | All existing rigour is currently manual |
| P1.3 | Burn the 40-failure baseline + OOM classes | 1–2 d | MED | A red suite hides the next regression; prerequisite for P0.2's value |
| P1.4 | Enforce static typing (staged) | 1–2 d + | LOW→MED | 52k lines, no config, `ui/` excluded |
| P2.5 | Decide the Phase 8 architecture question | 0.5–1 d | LOW | Resolve audit #1 vs. the profiler with evidence |
| P2.6 | Decompose the god objects | multi-day | MED | 2.7k/2.4k/2.0k/1.9k-line files carry most risk |
| P2.7 | Cap chat-tab widget growth | 2–3 h | LOW–MED | Same unbounded-growth class as the feed |
| P3.8 | Re-examine feed/CrabWatch emission design | design first | MED | Structural, not just slow; needs PM sign-off |
| P3.9 | Documentation hygiene | 1–2 d | LOW | 765 docs with demonstrated rot |

---

## 8. Sign-off

- [ ] PM reviews ranking and approves P0 + P1 for scheduling
- [ ] Each approved item gets its own spec before implementation
- [ ] P0.1 + P0.2 land before any further performance work begins
