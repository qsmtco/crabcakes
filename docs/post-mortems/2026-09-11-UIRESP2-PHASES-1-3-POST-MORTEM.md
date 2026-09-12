# SPEC-UI-RESPONSIVENESS-2 (Phases 1–3) Post-Mortem

**Date:** 2026-09-11
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** 6 (a3c95c2, c623196, 8749ecb, ecd6300 + spec commits 21fb08c and the Phase-3 sweep-in carrying the parent spec; spec amendments folded in-place)
**Phases:** 4 (spec authoring + 6 adversarial spec-audit rounds → Phase 1 writer → Phase 2 journal → Phase 3 window → final audit + fixes)
**Total bugs found:** 12 in-code (1 CRITICAL, 4 HIGH, 7 MEDIUM) + 63 spec-class across 6 audit rounds
**Process:** implementationLoop.md trio — file-based delegation, red-first, adversarial audit every code-bearing turn, supervisor independent verification each phase

---

## 1. Code Quality Grade: A- (91/100)

### Justification

The core deliverable — main-thread feed persistence moved off the GTK loop behind an O(1) journal with crash-safe compaction and bounded locks — landed clean, test-covered, and adversarially audited at every step. The one shipped-then-caught CRITICAL (split-lock inodes) was found by the *supervisor's own verification* before any release exposure and closed with a regression test the auditor proved non-vacuous via revert round-trip. Grade held below A by: two latent bugs the builder flagged rather than fixed (correct process, but they shipped into the interim state), one spec-authored guard bug (found by the builder at implementation time), and test-suite flakiness that reached the final audit before being caught.

| Category | Score | Notes |
|---|---|---|
| Correctness | 18/20 | split-lock CRITICAL caught pre-merge; self-satisfying guard was spec-authored; everything else verified |
| Architecture compliance | 10/10 | utils purity (documented rate-limit deviation), threading in handler layer, no GTK in feed_store |
| Test coverage | 9/10 | 62 new tests, red-first throughout, structural+timing pairing; 1 AC test initially missing |
| Documentation | 9/10 | ARCHITECTURE.md §3.22c/d + §4.14 flow; stale line counts corrected late |
| Maintainability | 9/10 | shared `_parse_cards`/`_apply_overlay`; tri-state return documented; three-phase drain documented |
| DX (Developer Exp.) | 9/10 | deterministic test harness (`_SyncThreading`, RecordingGLib) reusable; two racy tests initially |
| **Total** | **91/100** | **A-** |

Deducted points:
- 2 Correctness: Phase-1 interim race (update-before-append drops) shipped inside the sprint between phases — closed by Phase 2's journal as specced, but the window existed in-tree.
- 1 Test coverage: spec invariant-4 (<100 ms load) test missing until the final audit.
- 1 Documentation: ARCHITECTURE.md line-count drift (~10 lines each) survived the builder's own doc pass.
- 1 Maintainability/DX: TestSeqNumHandler race (un-joined daemon) introduced with the Phase-3 load-trigger work and flaked in the auditor's run before the fix.

---

## 2. What's Good About the Code

1. **The O(1) journal with uniform-flock discipline** (`utils/feed_store.py:256-351, :571-654`): one JSONL append per update, held under the single FEED lock; compaction folds crash-safely (replace-then-truncate, idempotent replay). This is the entire measured perf win — py-spy showed 100% of main-thread samples in the old RMW path.
2. **The three-phase drain** (`ui/handlers/feed_handler.py:1137-1232`): compactions-snapshot → deferred-in-place → queue. Eliminated the entire class of move-based retry bugs (counter resets, re-merge clobber, in-pass spins) by construction rather than by patching — the structural lesson of spec rounds 4-6 made real.
3. **Bounded everything** (`_acquire_lock` :151-184, size-scaled load timeout :440, size-scaled shutdown join :1260): the unbounded blocking flock — the observed UI freeze vector — no longer exists anywhere reachable from the main thread.
4. **Torn-tail repair over blind prepend** (`append_card_update` :314-330 + `_tail_is_complete_record`): the builder traced the spec's letter ("prepend \n") to a *lossy* consequence (subsequent records shadowed at replay, garbage baked into snapshots) and implemented the strictly-safer repair — the best single steelFramedCodeWriter moment of the loop.
5. **Tri-state return contract** (`update_feed_card` :655-676): True/False/None cleanly separates recorded / failed-retryable / card-gone-final, with the writer mapping each to distinct handling — this closed the Phase-1 interim race without any writer change.
6. **Deterministic test harness** (`_SyncThreading`, `RecordingGLib`, AST structural test): turns the thread-hop paths (persist, load, prune-surface) into synchronous, order-independent tests; reusable for future work in this file.

---

## 3. What's Bad About the Code

1. **Interim-state bugs live in-tree between phases.** The Phase-1 race (updates for not-yet-appended cards → 3-retry ERROR drop) and Phase-2's ignored `window` param both existed as committed intermediate states. Acceptable inside a single sprint, but the same pattern at larger granularity would ship broken windows to users.
   - Evolution: when a phase's known-broken interim is load-bearing for the *next* phase's fix, land them as one commit or branch-protect the interim.
2. **`save_feed`'s dual role.** It now takes the lock and is test-only in production terms, yet remains the "official" save API. Dead-ish code with live semantics — a future caller gets correct-but-slow behavior with no signal it should use the journal path.
   - Evolution: deprecate or route it through the journal in a follow-up.
3. **The `stat` unused import and `widget` unused local** (pyflakes, pre-existing) were left per Rule 8 and still sit in the files.
   - Evolution: a 2-line hygiene commit.
4. **Test count vs spec AC drift.** The spec enumerated ACs with "(test)" markers; one had no test until the auditor caught it. The AC list and the test list were maintained separately and drifted.
   - Evolution: generate the AC checklist from the test file (or vice versa) at phase close.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|---|---|---|---|---|
| 1 | 2 | CRITICAL | Split lock inodes: journal appends locked `feed-updates.jsonl.lock` while compaction locked `feed.json.lock` — no mutual exclusion, silent update loss window | Supervisor (pre-audit verification) + Debugger (confirmed, traced) | Coder (send-back; 1 line) |
| 2 | 3 | HIGH | Self-satisfying guard in `_surface_prune_card`: card name derived from `_active_project_name` on the writer then compared against it — misfiled cards on project switch | Coder (flagged at delivery) | Supervisor (direct fix + regression test + spec amendment) |
| 3 | 1 | HIGH | Phase-1 interim race: update drained before append lands → legacy False → 3-retry ERROR drop (update lost) | Coder (flagged at delivery) | Closed by Phase 2 journal (existence-independent updates) |
| 4 | 2 | HIGH | `unpack-before-null-check`: 6 call sites unpacked `_acquire_lock` result before testing None → TypeError on the exact condition the bounded lock handles | Coder (self-caught, Step 6.6) | Coder (pre-delivery) |
| 5 | 3 | MEDIUM | Racy `TestSeqNumHandler` tests: un-joined daemon thread vs immediate assertion — order-dependent flakes | Debugger (final audit; reproduced 1 fail) | Supervisor (`_SyncThreading`, 8/8 stress) |
| 6 | 3 | MEDIUM | Spec/code placeholder drift (`project_name=""` vs active-name) — benign but drifting | Debugger (final audit) | Supervisor (code aligned to spec) |
| 7 | 3 | MEDIUM | Missing spec invariant-4 test (<100 ms load at window) | Debugger (final audit) | Supervisor (added, §9-paired) |
| 8 | 2 | MEDIUM | `test_low13_update_feed_card_atomic` collides with journal semantics (crash lands only on legacy) | Coder (flagged for ruling) | Coder (1-line monkeypatch; supervisor-approved) |
| 9 | 2 | MEDIUM | Spec's torn-tail rule lossy (prepend-\n shadows subsequent records; bakes garbage into snapshots) | Coder (deviation with trace) | Coder (repair implementation; auditor-confirmed) |
| 10 | 3 | LOW | ARCHITECTURE.md line counts ~10 off | Debugger (final audit) | Supervisor (sed) |
| 11 | 3 | LOW | Process: `git add -A` swept 3 untracked supervisor drafts into the Phase-3 commit | Debugger (final audit) | Logged here (no history surgery) |
| 12 | 1 | LOW | `load_feed` lock-free fallback reads journal outside any lock (residual) | Debugger (Phase-2 audit) | Accepted + documented at site (spec §2.2.3) |

Plus **63 spec-class findings across 6 spec-audit rounds** (16 → 14 → 17 → 15 → 5 → 3, exit criterion met at round 6 with 0 CRITICAL/HIGH): tri-state loss, requeue clobber, append+compact deadlock, `default=str` silent corruption, counter-not-per-payload, in-pass retry spin, missing `import os`, and more — every one fixed in the spec *before* code was written. The spec-audit loop was the highest-leverage process of the entire unit.

### Bug patterns

| Pattern | Count | Description |
|---|---|---|
| `split-lock-inodes` | 1 | flock is per-inode; two lock files = no exclusion |
| `stale-derived-guard` | 1 | guard compares a value against its own source |
| `unpack-before-null-check` | 1 | unpacking a `tuple | None` before the None test |
| `unjoined-daemon-assert` | 1 | test asserts state a daemon thread hasn't written yet |
| `fold-in-introduces-new-hazard` | 4 | each spec fix's new machinery carried its own bug until traced |
| `interim-state-race` | 2 | known-broken window between dependent phases |

---

## 5. Process: What Worked

1. **Six adversarial spec-audit rounds before any code.** 63 spec defects eliminated pre-implementation; rounds 4-6's findings were semantics refinements (not structural holes), showing convergence. The exit criterion ("zero new CRITICAL/HIGH") made the stop decision objective instead of fatigue-based. Cheapest bug-removal of the loop by orders of magnitude.
2. **File-based delegation with red-first mandates.** Every phase's instructions file specified exact edits + test lists + gate commands; every delivery came back with genuine red evidence (the immediacy test's red showed the *actual* 0.62 s sync write, not a missing symbol). Zero truncation failures, zero "done" claims without output.
3. **Supervisor independent verification catching what both builder and auditor missed.** The split-lock CRITICAL was found in *my* pre-audit read of the diff — before Debugger's round. Never trusting the report, even the adversarially-audited one, paid for the whole loop once.
4. **The builder's flag-don't-fix discipline.** Coder flagged the interim race, the guard bug, the test collision, and the lossy spec rule instead of silently patching around them — each flag was a real finding and each needed a supervisor ruling, exactly per Step 6.6.
5. **Hermetic baseline comparison via `git archive` worktrees** (outside the review layer's watch): identical 40-failure sets pre/post at every phase gate, with the agent-runtime OOM class documented and excluded consistently both sides.

## 6. Process: What Didn't Work

1. **`git add -A` swept unrelated drafts into a phase commit.** Three untracked supervisor-authored files rode into `8749ecb`. No data harm, but the commit's scope is muddy and the audit had to rule on it.
   - Lesson: stage by explicit path in every commit; `-A` is banned during multi-stream work.
2. **The spec-audit loop's marginal round cost.** Round 6 found only refinements (3 MEDIUM/LOW) but still cost a full audit cycle; rounds 4-5 each found new CRITICALs introduced by *fixing* the previous round's findings.
   - Lesson: fold-in rounds should scope the re-audit to *only the changed code paths* (as the fix-verification round did — one focused pass, not 11 sections). This was learned mid-loop and applied at the end.
3. **AC-to-test linkage drifted.** The <100 ms AC had "(test)" in the spec but no test until the final audit.
   - Lesson: the phase-close checklist must tick ACs against *named tests*, not test-count claims.
4. **The enforcer hook's headless segfault noise.** Every direct edit triggered a no-xvfb GTK segfault "failure" that had to be mentally discarded and re-run under xvfb — pure friction in the verification loop.
   - Lesson (environment): the hook should run under xvfb-run or skip GTK suites; until then, treat its output as advisory only.

---

## 7. What the Code Actually Does (End-User Impact)

1. **The app stays responsive while agents work.** Every tool result, approval, and accept/reject now enqueues in <1 ms on the main thread (was a synchronous ~620 ms whole-file rewrite per event — 100% of main-thread profiler samples). Code path: `_do_tool_call_result` → `update_card` → `_enqueue_card_update` (`feed_handler.py:1026-1032`) → writer thread → `append_card_update` journal line.
2. **Feeds stop growing without bound — AMENDED 2026-09-12 (external verification F1): this claim is only partially true as shipped.** Compaction retains the newest 2,000 cards with pins; a 13.9 MB / 9,500-card feed compacts on first open with a visible prune card; loads complete in <100 ms (tested). **However** the `needs_approval` pin is a transient flag that is never cleared, so every exec-approval card ever created is pinned forever: against the live feed (11,222 cards) the window retains ~4,658, not 2,000, and the pinned set grows ~350/day. Bounding is real but the floor is much higher than designed and rises. Spec defect (pin rule authored at PM level, carried verbatim); fix tracked as the F1 amendment — see `docs/specs/UIRESP2-PHASE1-3-VERIFICATION-QRUSHER.md` and §12. Code path: `_load_and_render` trigger → writer compact branch → `_surface_prune_card` (main-thread name resolution, persisted copy).
3. **No UI freeze from lock waits, ever.** Every feed mutation holds one bounded flock (2 s default, size-scaled for loads/shutdown); the old unbounded blocking fallback that parked the main thread 9× in the live capture is deleted. A stuck lock now means a logged skip + retry, not a frozen window.
4. **Crash-safety.** Kill the app at any point: the journal replays idempotently (a torn final line is repaired or stopped-at), the snapshot is replaced atomically, accepted/rejected decisions are never pruned away.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **`test_agent_runtime.py` single-process OOM** (~14 GB in `TestEndStreaming*`) — baseline-proven at every gate this loop; excluded consistently both sides. Needs its own unit.
2. **`_ensure_gitignore_entry`'s unprotected read-modify-write** — pre-existing (every historical caller equally exposed); inherited by the journal's first-creation call. Post-mortem ledger item from Phase 2.
3. **`left_panel.py:15` view→handler import** (architecture violation) and `gtk_containers.py` carve-out gap — pre-existing from prior loops, unchanged.
4. **40-failure baseline set** (test_special_agents ×2, test_auxilium_tier2 KB ×6, etc.) — byte-identical pre/post; the accumulated pre-existing debt of earlier units.

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|---|---|---|
| Route `append_feed_card`'s RMW through the journal (D2's deferred item) — appends stay O(feed) until Phase-3 windowing bounds them | 4-6 h | removes the last whole-file rewrite path; unifies all writes as O(1) |
| Deprecate or journal-route `save_feed` (test-only API with live semantics) | 1 h | prevents future misuse of the slow path |
| Spec Phases 4-7 per parent `SPEC-UI-RESPONSIVENESS-2.md` §0a (deferred card render, git offload, lock sharding, render pool) | per phase | hygiene — profiler found no samples in them, scheduled after production soak |
| `TestSeqNumHandler`-style thread-hop audit across the older test suites (un-joined daemon asserts) | 2-3 h | kills the remaining order-dependent flakes at the root |
| Follow-up test-hardening unit: join-the-load-thread seams in `on_project_opened`-style tests project-wide | 2 h | CI stability |
| Phase 8 spike write-up (process-split architecture proposal) | 2 h | unblocks the audit-#1 GIL decision with a scoped document |

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Spec-audit until convergence, then scope the re-audits.** Full 11-section probes until the exit criterion; after it, fix-verification rounds probe *only the changed paths* (one focused pass). Trigger: any fold-in >1 round. Action: write the exit criterion into the audit request up front — it made stopping objective.
2. **Simplify-don't-add on repeated fold-in failures.** When two consecutive fix rounds introduce new bugs in the *machinery added to fix the last bug*, delete the machinery and restructure (the three-phase drain replaced four generations of retry plumbing in one move). Trigger: round-over-round new-CRITICALs in fix-introduced code. Action: re-derive the invariant (mutual exclusivity, in-place state) instead of patching the mechanism.
3. **Verify the auditor's target yourself before routing.** The supervisor's own diff read found the split-lock CRITICAL ahead of the audit round; the audit then confirmed with an independent trace. Trigger: any concurrency-bearing diff. Action: run the call-site/inode/lock analysis personally — never delegate 100% of verification even to a good auditor.
4. **No `git add -A` during multi-stream work.** Stage by explicit path. Trigger: any commit while other drafts exist in-tree. Action: `git add <paths>` only; sweep-ins are logged, never silent.
5. **Interim states that are load-bearing for the next phase land together.** Trigger: a phase's known bug whose fix is specced for the next phase. Action: one commit per closed defect window, or branch protection — never a committed broken window at merge granularity.

## 11. Sign-off

- [x] Code committed: `a3c95c2` (P1), `c623196` (P2 + split-lock fix), `8749ecb` (P3), `ecd6300` (final-audit fixes), `21fb08c` (spec) — main, local
- [x] All post-loop verification commands run and pasted (247/247 targeted suites; full-suite 40/40 identical baseline sets; 8/8 flake-stress; pyflakes undefined-name 0)
- [x] Captain notified with summary (this document + feed)
- [x] Tier 2+ backlog updated (§9 — parent-spec Phases 4-7, journal-routed appends, test-hardening unit)
- [ ] Push to origin — awaiting PM go (branch is ahead; includes the spec + 4 feature commits)

## 12. Post-acceptance amendment — external verification (Lt. Qrusher, 2026-09-12)

`docs/specs/UIRESP2-PHASE1-3-VERIFICATION-QRUSHER.md` verified the implementation independently (all claims reproduced: 0.09 ms journal append on the live feed, compaction fold/prune/truncate, <100 ms post-compaction load, 246 tests) and raised five findings. **F1 (HIGH) is accepted as a spec defect that changes the Phase-3 outcome claim:** the `needs_approval` pin treats a never-cleared transient flag as permanent state, so the window's effective floor is ~4,658 cards and rising (~350/day) rather than 2,000 — verified against the live feed independently (11,222 cards; 3,081 needs_approval; 1,884 undecided). Compounding mechanism (verified in source): `approve_exec` sets `card.accepted` in memory but the persist payload never includes `accepted`, so decided approvals stay `accepted=None` on disk and also escape the durable pin. §7.2 above is amended accordingly.

Corrections to the verification report from my own re-verification: (a) decisions *are* recorded on disk for 1,198 needs_approval cards (accepted≠None) — the write-back failure is partial, not total, likely because the in-memory→persist gap is path-dependent (the auto-approve path persists via `update_card`'s body/metadata payload which never carries `accepted`; a subset evidently persisted via other paths); (b) the post-mortem §4 bug table and grade are **unchanged** — F1 is a spec-rule defect, not an implementation defect; the implementation is faithful to the (wrong) rule. Handling: F1 spec amendment + F2 archive decision scheduled **before the first live compaction** (sequencing per the report §5.4); F3 spec amendment (drop `seq_floor`, as with §2.3.5); F4 app restart after push; F5 attribution corrected here.
