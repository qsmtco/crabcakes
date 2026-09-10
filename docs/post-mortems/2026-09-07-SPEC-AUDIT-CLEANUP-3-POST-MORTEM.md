# Audit Cleanup 3 — Perf Quick Wins (SPEC-AUDIT-CLEANUP-3) Post-Mortem

**Date:** 2026-09-07 (unit started) — closed 2026-09-08
**Supervisor:** special:supervisor
**Builder:** special:coder
**Auditor:** special:debugger
**Commits:** 4 (`bc56b50` Part A, `4568cb0` Part B, `5e2ebaf` Part C, `0426bb7` docstring correction)
**Phases:** 1 (single phase, 3 parts A/B/C per spec's design), each part audited as one Phase-1 audit
**Total bugs found:** 0 code defects; 1 doc-accuracy finding (fixed same-cycle); 5 process findings
**Process:** loop §3.1a audit on the full phase; supervisor-recovery commit for Part A after builder-session degradation (see §6.1 — the headline process event)

---

## 1. Code Quality Grade: A- (90/100)

### Justification

The three perf changes landed with all 6 spec invariants verified, 26 new tests (7 coalescing + 6 render + 13 activity) proven red-first, and the strongest possible regression evidence: the full-suite failure set (40 tests) byte-identical pre/post in an isolated worktree. The audit found zero code defects across all 11 sections — including genuinely adversarial probes (delta injection during inner execution, two-events-back-to-back sentinel behavior, stale-cursor poisoning). Deductions: the spec's core mental model was **wrong** (the "producer thread" claim — see §6.1) and propagated into two shipped docstrings before the audit caught it; Part A survived two builder-session degradations requiring a supervisor-recovery commit — process cost that a smaller phase-slicing might have avoided; and the pre-existing BUG-21 suppression test gap is now confirmed as a *real* incomplete fix (not just env noise), which this unit only flagged.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | 0 code defects; invariants 1-6 all test-covered and audit-verified; byte-identity of final text proven. −1: BUG-21 empty-return-vs-start-bubble gap confirmed real (pre-existing, flagged for its own spec). |
| Architecture compliance | 10/10 | 3 handler files only + their tests + conftest; no handler-to-handler imports; GLib dispatch pattern preserved; layering untouched. |
| Test coverage         | 9/10  | 26 red-first tests; 6/6 invariants each with a named test; existing suites all green. −1: the coalescer's cross-batch throttle behavior (batch-2 sits dirty until completion) is intended but has no direct test — the audit verified it by trace + probe, not by automated assert. |
| Documentation         | 8/10  | Docstring doc-lies introduced then fixed same-unit (0426bb7); the conftest upgrade and ticker-alias design are documented in-code. −2: two shipped commits carried wrong thread-model wording; caught only at audit. |
| Maintainability       | 9/10  | Single ticker replaces two; skip-cache + lazy resolution documented; aliases preserve public API. −1: the Part-A state (`_delta_dispatch_pending` + `_delta_dirty` + `_last_delta_dispatch`) is 3 parallel dicts — a future small dataclass would read better. |
| DX (Developer Exp.)   | 8/10  | The user-visible win (tab responsiveness during streaming) should be immediately noticeable. −2: Part A took two degraded sessions + a recovery; the incident cost more wall-time than the code. |
| **Total**             | **90/100** | **A-** — clean landing, strong evidence, one spec-model error caught late, unusual session instability absorbed. |

Deducted points:
- 1 Correctness: BUG-21 gap confirmed real-but-pre-existing
- 1 Test coverage: cross-batch throttle behavior untested-by-assert
- 2 Documentation: doc-lies shipped in 2 commits before audit catch
- 1 Maintainability: 3 parallel dicts where a small struct would read better
- 2 DX: session-degradation overhead (recovery commit, re-verification)

---

## 2. What's Good About the Code

1. **The coalescing design survived its own hard cases (bc56b50):** the empty-delta BUG-21 turn-start signal bypasses coalescing entirely (routed uncoalesced so the main-thread start-bubble path still fires); the dirty-flag trailing re-schedule lives in a `finally` so every return path preserves the "last batch always renders" guarantee; the dispatch carries the CURRENT turn token so mid-batch turn changes drop stale renders. Each of these is a case the naive implementation would have silently broken. `ui/handlers/agent_runtime_handler.py:1005-1160`.
2. **The unchanged-skip guard compares the right thing (4568cb0):** stored plain text, not the cursor'd display string — so a skipped update can never poison the next comparison or leave a stale cursor'd label. The skip sits AFTER the `sb.plain_text` assignment, preserving invariant 2 (completion always reads current text). `ui/handlers/chat_render_handler.py:519-545`.
3. **The single ticker's alias-preservation design (5e2ebaf):** `_live_update_timer`/`_idle_pulse_timer` kept as synced aliases so `_stop_live_update`/`_stop_idle_pulse` keep their public behavior with zero call-site changes — the refactor is invisible to every consumer. The skip-cache tuple `(state, phase, hops, elapsed@0.5s)` bounds label drift at 2/sec while state changes rebuild immediately. `ui/handlers/activity_handler.py:638-790`.
4. **`_agent_name_for_event` lazy sentinel (5e2ebaf):** resolution happens once per event only where a name is needed — per-delta assistant events pay ZERO resolution calls (the audit verified: 2 events → exactly 2 resolutions). The sentinel-reset-at-top pattern makes the cache safe across events without any invalidation bookkeeping. `ui/handlers/activity_handler.py:284-338`.
5. **The red-first evidence discipline held across all 26 tests:** every test class was run against the pre-change baseline (worktree at `bc56b50`/`361da0a`) with pasted failing output — throttle constant, dispatch-count bounds, skip-count spies, ticker interval — before any green claim. The pre-existing-failure pairs (BUG-21 ×2, OOM ×2) were worktree-proven at every step, never hand-waved.

---

## 3. What's Bad About the Code

1. **The spec's mental model was wrong and shipped into docstrings:** SPEC-AUDIT-CLEANUP-3 asserted "accumulate on the producer (runtime) thread — race-free." The audit proved the runtime's `_dispatch` wraps callbacks in `GLib.idle_add`, so `_on_text_delta` executes on the MAIN thread in production; there is no thread offload. The real win is the idle_add-queue flood reduction (N deltas once enqueued N render dispatches; now ≤~20/sec). My instructions repeated the wrong model; Coder's docstrings inherited it; two commits shipped the lie before §3.1a caught it.
   - Evolution: perf specs must include a one-paragraph **execution-context map** (which thread/callback-context each touched function actually runs in) before proposing thread-model fixes. The audit's probe (read `_dispatch`'s wrapper) is the checklist item.
2. **Part A took two builder-session degradations:** first a shell-output corruption loop, then a model repetition-loop collapse at report time. The work was functionally complete both times — the sessions failed, not the code — but the recovery consumed a supervisor verification pass + commit and left the phase's delivery narrative fragmented.
   - Evolution: for phases touching the hottest, most-guarded code paths (the delta pipeline), consider slicing even finer (A1: producer-side accumulation only; A2: coalescing+trailing) so a session collapse loses less narrative continuity and the recovery verification is smaller.
3. **The BUG-21 suppression tests now PROVE the fix is incomplete (pre-existing, confirmed):** the test calls `_do_text_delta(sk, "")` expecting the start-bubble path to clear `_ended_sessions`, but the empty-return fires first. Baseline-identical failure — but this unit's Part-A work touched exactly this code and had to route around the gap (the new `if not text and not streaming_text: return` preserves the old ordering). The fix/test pair needs its own spec.
   - Evolution: promote from "pre-existing failure" flag to a proper work-unit (the drawer-emission suppression path); the 40-failure baseline burn-down unit should sequence it early since two of the failures are this one root cause.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 1 | suggestion | Docstring doc-lies: `_on_text_delta` "Runs on the runtime thread" and `_do_text_delta` "accumulated on the PRODUCER thread" — both run on the main thread in production via the runtime's GLib.idle_add wrapper | Debugger (§10) | Supervisor directly (`0426bb7`) |
| 2 | 1 | process | 1-line Part-B test cleanup rode in the Part C commit (unrelated change in a feature commit) | Coder (self-flagged) | Accepted; rule logged (§10.3) |
| 3 | 1 | process | Coder's "self-caught recursion fix" claim was inaccurate — the memoization sentinel was never a recursion bug; description drifted | Debugger (§10) | Noted for report-accuracy; final state correct |
| 4 | 1 | flagged | BUG-21 suppression tests fail because `_do_text_delta`'s empty-return precedes the start-bubble path — the original fix is genuinely incomplete, not env noise | Debugger (§11) | Deferred — needs its own spec (pre-existing) |
| 5 | 1 | flagged | `ActivityHandler.__init__` never initializes `_agent_to_project` — bare `_set_state` without `set_agent_routing()` raises AttributeError (prod-safe: window.py always wires it) | Coder (red-run discovery) | Deferred — init-order hardening for a future sweep |
| 6 | 1 | process | Builder session degradations (shell corruption; repetition-loop collapse) — work unaffected, delivery narrative fragmented | Supervisor (incident) | Recovery commit `bc56b50` + fresh session for B/C |

Zero bug-severity code defects. 1 doc-accuracy issue (fixed same-cycle), 3 process findings, 2 pre-existing flags promoted to backlog.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `spec-model-error-thread-context` | 1 | Spec asserted a thread model without reading the dispatch wrapper; wrong model shipped into docstrings |
| `unrelated-cleanup-in-feature-commit` | 1 | Trivial fix riding a feature commit |
| `report-accuracy-drift` | 1 | Self-report described memoization as a "recursion fix" |
| `builder-session-degradation` | 2 | Model/shell failure modes (corruption loop; repetition collapse) requiring supervisor recovery |
| `incomplete-fix-test-pair` | 1 | BUG-21: fix and test disagree on mechanism; both shipped failing |

---

## 5. Process: What Worked

1. **Supervisor recovery-commit protocol (new, first use):** when Coder's session collapsed AFTER the work was verifiably done, I assessed the tree independently (7/7 new tests green, structural shape verified, baseline failures worktree-proven), committed the completed work with the spec'd message, and routed B/C to a fresh session. No work was lost, no re-implementation happened, and the degraded session was never asked to re-report. This is now a documented recovery pattern.
2. **The 6-invariant probe set as audit contract:** writing the invariants into the instructions file (with "each gets a test") made the audit concrete — Debugger verified each by name with evidence, and the one subtle case (trailing guarantee "bounded" behavior) got an honest nuance note rather than a rubber stamp.
3. **Worktree-baseline discipline at every step:** red-first evidence ran against worktrees at `8db8f7c`/`bc56b50`/`361da0a`; the pre-existing pairs (BUG-21 ×2, OOM ×2) were re-proven at each phase boundary; the unit-close gate ran the full 40-failure-set comparison. Zero regressions were asserted without a baseline diff somewhere in the chain.
4. **Doc-lie rule enforced at audit again:** the thread-context docstrings were caught by §10 of the adversarial probe and fixed same-cycle by the supervisor — the third time this rule has paid for itself (AC2 ARCHITECTURE.md entries, AC2 tree listings, AC3 docstrings).

---

## 6. Process: What Didn't Work

1. **I wrote the wrong thread model into the spec (highest-impact failure this unit):** "producer-side, runtime thread, race-free" — I derived it from the perf audit's framing and my own earlier read of `_on_text_delta`, but never re-read `agent/runtime.py:_dispatch`'s wrapper before speccing. The result: the code was correct (the coalescing works regardless of thread), but the documentation lied and the spec sold the wrong win. The audit caught it; the post-mortem records it.
   - Lesson: **perf specs include an execution-context map** — for every function the spec proposes to change, cite the actual dispatch chain (who calls it, from which thread/context, through what wrapper). Added to the spec-authoring checklist.
2. **Builder session instability consumed significant wall-time:** two degradations (shell corruption mid-verification; repetition-loop collapse at report time). The recovery worked, but the phase that should have been one clean delivery became: delivery → collapse → supervisor verification → recovery commit → re-delegation → delivery. Part A's true cost was ~2× its code size.
   - Lesson: **slice hot-path phases finer** (A1/A2) so a collapse loses less; and when a session shows output corruption, stop it immediately rather than letting it run to report time (the repetition collapse was the corruption's second act).
3. **The 1-line cleanup rode the Part C commit:** trivial, self-flagged, but it's the exact pattern AC2's Rule-8 discipline exists to prevent — unrelated changes in feature commits make bisects lie.
   - Lesson: builder instruction already says flag-don't-fix; add "and don't ride even trivial cleanups — commit them separately or hand them to the supervisor."

---

## 7. What the Code Actually Does (End-User Impact)

1. **Streaming a long agent response no longer floods the UI event queue:** each SSE delta previously enqueued its own main-loop render dispatch (hundreds per second during a hot loop); now at most ~20 dispatches/sec per session reach the queue, with a guaranteed trailing render so the final text is never dropped. Combined with the 500ms label throttle (was 150ms) and the unchanged-text skip, a long response renders the same complete text with a fraction of the main-thread work. Code path: `agent/runtime.py:_dispatch` → `agent_runtime_handler.py:_on_text_delta` (accumulate + coalesce) → `_do_text_delta` (single render) → `chat_render_handler.py:update_streaming` (throttle + skip) → `set_text`.
2. **The status bar rebuilds less during streaming:** the FeedBar/activity ticker consolidated from two 200ms timers to one 250ms timer, and each tick now skips the Pango markup rebuild when nothing observable changed (same state, phase, hop count, elapsed bucket) — the progress label still tracks elapsed time at 0.5s resolution. Agent-name resolution for gateway events dropped from up to 6 call sites per event to exactly 1 (and zero for per-delta assistant events). Code path: `activity_handler.py:on_gateway_event` → `_agent_name_for_event` (lazy) → `_set_state` → `_status_tick` (branch + skip-cache).
3. **Users see the same final content, just rendered leaner:** every invariant test asserts it — accumulation completeness (100 deltas → byte-identical concatenation), completion ordering (trailing render precedes completion's authoritative overwrite), final-text byte-identity. The changes are pure overhead reduction; no user-visible content behavior changed.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **BUG-21 suppression test pair (2 failures, now root-cause-confirmed):** `_do_text_delta`'s empty-return precedes the start-bubble path that would clear `_ended_sessions`; the fix and its test disagree on mechanism. Baseline-identical since before AC1; promoted from "env noise" to "real incomplete fix" by this unit's audit. Needs its own spec.
2. **`TestEndStreaming*` OOM (2 classes, ~14GB):** baseline-proven since AC1; chunked runs remain the workaround.
3. **`ActivityHandler.__init__` missing `_agent_to_project` init:** AttributeError on bare `_set_state` without routing setup; prod-safe (window.py wires it) but a latent trap for tests/new callers.
4. **10 repo-wide pyflakes `pytest` shadow-import warnings** (test_gtk_safe_link/test_architecture): byte-identical at baseline; TYPE_CHECKING-shadowed, cosmetic.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| BUG-21 fix-spec: make `_do_text_delta`'s empty-delta path reach the start-bubble logic (or fix the test's mechanism) — closes 2 of the 40 baseline failures | 2-3 hours | Drawer-emission suppression tests green; the test-debt unit shrinks by 2 |
| Execution-context map as a spec-template section (which thread/context each touched function runs in, with the dispatch-chain citation) | 30 min (template) | Prevents the spec-model-error class permanently |
| ActivityHandler `_agent_to_project` init hardening (default None in `__init__`) | 15 min | Removes a latent AttributeError trap |
| Coalescer state consolidation: `_delta_dispatch_pending`/`_delta_dirty`/`_last_delta_dispatch` → one small per-session dataclass | 1-2 hours | Readability of the hottest path; no behavior change |
| Cross-batch throttle-behavior test (batch-2-sits-dirty-until-completion is intended — assert it) | 30 min | Converts an audit-trace-verified behavior into an automated guard |
| Test-debt unit (carried from AC2 post-mortem): burn the 40-failure baseline; BUG-21 spec above is the natural first item | 1-2 days | Green full-suite; removes the pre-existing asterisk from every future gate |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Execution-context map in every perf spec:** before proposing thread-model changes, the spec cites the actual dispatch chain for each touched function (caller → wrapper → thread). The AC3 spec's "producer thread" claim was derived from the audit doc's framing, not the code — and shipped a lie.
   - Trigger: any spec touching callbacks, timers, or dispatch paths.
   - Action: a "who calls this, from where" paragraph with file:line citations; auditor probes it first.
2. **Supervisor recovery-commit protocol (formalized):** when a builder session degrades after work is verifiably complete, the supervisor (a) assesses the tree independently (tests, structure, baseline-failure identity), (b) commits the completed work with the spec'd message, (c) logs the incident, (d) routes remaining work to a fresh session. Never ask a degraded session to re-report.
   - Trigger: session collapse with substantial uncommitted-but-complete work.
   - Action: verify → commit → log → re-delegate. First use this unit; worked end-to-end.
3. **No unrelated cleanups riding feature commits — even trivial ones:** Coder's 1-line test cleanup in the Part C commit was harmless but is the bisect-lie pattern. Flag to the supervisor or commit separately.
   - Trigger: any edit not required by the current phase's spec.
   - Action: separate commit or supervisor handoff.
4. **Stop degraded sessions at first corruption:** the shell-output corruption was Part A's first degradation; letting it run to report time produced the repetition-collapse second act and cost the recovery a full verification pass.
   - Trigger: garbled/echoing tool output.
   - Action: builder stops, reports best-state; supervisor takes over assessment immediately.
5. **The invariant-probe contract works — keep using it:** writing "each invariant gets a named test" into instructions made the audit concrete and the delivery verifiable part-by-part. This is the third unit where explicit gates (pyflakes count, baseline-diff, invariant tests) converted audit from opinion into evidence.
   - Trigger: every spec with correctness invariants.
   - Action: invariants → named tests → audit probes by invariant number.

---

## 11. Sign-off

- [x] Code committed at `0426bb7` (4 commits: 3 perf + 1 docstring correction); push pending PM go
- [x] All post-loop verification run and pasted: full-suite worktree comparison 40=40 IDENTICAL failure sets at `361da0a`; directly-touched suites 175/175 + 26 new red-first tests; pyflakes undefined-name 0 on target files; all 6 invariants audit-verified with named tests
- [x] PM notified with summary (next message)
- [x] Tier 2+ backlog updated: §9 (6 items — BUG-21 fix-spec and the test-debt unit are the headline pair)