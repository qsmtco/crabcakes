# SPEC-MEMORY-WIDGET-RATCHET Post-Mortem

**Date:** 2026-09-17
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** 0 standalone (all work delivered into the pending review-layer diff; commit occurs on PM acceptance — see Sign-off)
**Phases:** 13 planned → 12 executed (P9's comment rows absorbed into P2/P7b/P8/P10; P11 measurement pending PM session)
**Total bugs found:** 13 auditor findings — 2 functional (LOW), 7 docs/comment (LOW), 2 process claims dismissed with receipts, 1 spec design gap, 1 instruction defect (supervisor-authored)
**Process:** supervisor phases → Coder builds per file-based instructions → Debugger adversarial 11-section audit per code-bearing turn → supervisor independent verification (own test runs, byte-identity extraction, greps) → small fixes applied by supervisor inline

---

## 1. Code Quality Grade: A (93/100)

### Justification

A seven-round pre-implementation adversarial audit made this the most over-determined spec the project has run, and the loop confirmed it: ten phases of eviction, ordering, locking, seam, and ticker work landed with **zero CRITICAL/HIGH/MEDIUM defects**, every verbatim block byte-identical (verified independently three ways), and every red-check reproduced mutant-for-mutant by the auditor. The two functional findings (a stale-snapshot overwrite of `_project_seq`, an unlocked read-modify-write) were both caught by the loop itself and fixed within two phases. The grade drops from A+ for: five spec errata discovered mid-loop (the spec's anchors and two of its premises were stale), a P11 measurement that remains open pending a PM session, and a trio of unverifiable-count report claims that cost audit cycles even though all three turned out to be correct.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | 2 LOW functional bugs, both caught in-phase and fixed |
| Architecture compliance | 10/10 | Boundaries kept (§3.22c/§3.35); arch guard tests green throughout |
| Test coverage         | 10/10 | +833 test lines, mutation-verified red-before-green per phase |
| Documentation         | 8/10 | 6 stale comments rewritten, ARCHITECTURE.md §8 done; 2 generalized seams docstrings needed a second pass |
| Maintainability       | 9/10 | Verbatim blocks anchored to spec; AST lock-audit test guards the invariants structurally |
| DX (Developer Exp.)   | 9/10 | Probe committed; F12 tests; geometry helpers reusable; clear eviction contract docs |
| **Total**             | **93/100** | **A** |

Deducted points:
- 1 correctness: the `_project_seq` bug existed in the shipped product and was found by this loop, not before it
- 2 documentation: two rounds of comment rewrites were themselves partially wrong and needed audit correction
- 4 process/other: P11 gate unresolved; spec errata count; three audit cycles spent on unverifiable counts

---

## 2. What's Good About the Code

1. **The eviction pass is contract-first and fail-safe by construction.** `ui/handlers/feed_handler.py:1921-2010` is the spec's 86-line block verbatim: victims by `seq_num` across all projects, `KEEP_NEWEST_CARDS` floor, above-viewport-only with break-on-first-visible, exclude-set for Load More's own page, data pushed to `_backlog` under lock so nothing becomes unreachable. Every TOCTOU Debugger mounted against the two-tier lock structure came back clean.
2. **The geometry guard documents its own trap.** `ui/views/feed_tab.py:444-465` encodes the GTK 4.14 `compute_bounds -> (True, zero rect)` behaviour for never-allocated widgets — "unknown is never above" — and is pinned by four discriminating tests including a synthetic-rect test that survives the mutation-equivalence the real-GTK tests cannot distinguish (`tests/test_feed_handler.py::test_is_above_viewport_false_when_ok_false_alone`).
3. **The `_backlog` merge makes card loss structurally impossible.** `feed_handler.py:1661-1665` merges survivors-first under lock; the no-loss failure mode is pinned by injecting the push *inside* the patched `feed_store.load_feed` — exactly where the race window lives (`TestBacklogDiscipline`).
4. **Structural AST guards protect what behaviour tests cannot.** `test_loader_builds_widgets_outside_the_lock` re-derives the lock inventory from the AST each run: widget construction outside `_lock`, map writes inside. It went red under the auditor's own lock-widening mutation — the lock-narrowing (round-3 BUG #8's fix) cannot silently regress.
5. **The invariant is documented where the next reader will look.** `docs/ARCHITECTURE.md:2907-2911, 3508-3512`: **card data is unbounded; card widgets are bounded**, the never-returned-to-OS rationale, the newest-first ordering contract, and the geometry fail-safe — with pointers into the spec rather than duplication.

---

## 3. What's Bad About the Code

1. **The churn component remains unaddressed — by design, and it is the larger half.** §6's honest gate: the widget bound can recover at most ~0.18 MB/min of the measured 4.55 MB/min (~4%). Until P11 measures and the WebKit proposal (docs/proposals/WEBKIT-RENDER-SURFACE_PROPOSAL.md) is decided, long sessions will still grow, just slower and bounded by the cap.
   - Evolution suggestion: run P11's probe + `MALLOC_*` experiment at the next PM session; escalate the WebKit decision with numbers in hand.
2. **The spec shipped with five errata and stale anchors** (get_vadjustment wording, "13 inline doubles" premise — reality: 1, feed_store anchor drift, cross-project `seq_num` tie ambiguity, §2.1/§2.3 anchor drift after edits). Code was written from fences (which were correct), so the errata cost verification effort, not correctness — but a future reader following §2 prose anchors will land in the wrong place.
   - Evolution suggestion: one erratum pass over SPEC-MEMORY-WIDGET-RATCHET.md before it becomes historical reference; specs should carry identifier anchors only.
3. **Cross-project victim ordering is arbitrary on ties** — `_project_seq` is per-project while eviction sorts a cross-project union. Accepted and documented (erratum #4, ARCHITECTURE.md:2911), but a background project's newest card can lose a tie to the active project's older card.
   - Evolution suggestion: a global monotonic counter for eviction keying, or per-project victim fairness, in a future tier.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | P1 | LOW | `_journal_lines` docstring falsely claimed the secondary signal monotonic | Debugger | Supervisor (docstring, in-place) |
| 2 | P2 | LOW (advisory) | `not ok` guard half had no committed test | Debugger | Supervisor via P3 (synthetic-rect test) |
| 3 | P3 | LOW | Non-ancestor test's non-vacuity claim false (GTK couples ok=False with zero rect) — *instruction defect, supervisor-authored* | Debugger | Supervisor (honest docstring + new test) |
| 4 | P3 | LOW | body-cap double prediction over-filed (≤120 gate precedes accessor calls) | Debugger | Disposition: hazard note; hygiene fix applied anyway |
| 5 | P4 | issue | `_project_seq` reset ignores parse-window arrivals → duplicate `seq_num` | Coder (flag) | Coder (P5 max() fix) |
| 6 | P5 | LOW | The max() fix is an unlocked RMW; residual collision window | Debugger | Coder (P6 lock wraps) |
| 7 | P5/P7a | LOW | Unlocked `len(_backlog)` label read; `_load_more` widget store; loader lock region | Debugger | Coder (P7a) |
| 8 | P6 | LOW | Cross-project `seq_num` ties → arbitrary victim order (spec-mandated shape) | Debugger | Documented (erratum #4, ARCHITECTURE.md) |
| 9 | P7a | LOW | Stale "rebinds" comment inside the eviction fence contradicted the merge | Debugger | Supervisor (comment, in-place) |
| 10 | P8 | LOW | Generalized seam comments overclaimed "empty body yields no seam" (text renderer yields a placeholder seam, refused at update) | Debugger | Supervisor (2 comments, in-place) |
| 11 | P9 | LOW | `set_status_text(None)` silently skipped (None doubles as cache sentinel) — latent trap | Debugger | Supervisor (contract docstring) |
| 12 | P6 | LOW (dismissed) | "76 passed" flagged unverifiable | Debugger | **Dismissed**: test_architecture(6)+test_feed_card(70)=76 reproduced |
| 13 | P7a | LOW (dismissed) | "53/99" flagged unverifiable | Debugger | **Dismissed**: 53=triple+arch, 99=exact command in builder report |

One paragraph: 13 findings, none CRITICAL/HIGH/MEDIUM; the two functional ones (#5, #6) were the product of a genuine pre-existing bug plus its first-fix's own race, both closed by P6. Nothing compounded across phases — the phase granularity and per-phase audits caught everything at birth. Three audit cycles were spent on unverifiable-count claims that were all actually correct; the auditor's combination list, not the builder's reporting, was the gap both times.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `stale-comment-post-refactor` | 3 | Comments describing superseded behaviour (#1, #9, #10) |
| `unverifiable-claim` | 2 | Reported counts the auditor couldn't derive — both were correct (#12, #13) |
| `unlocked-rmw` | 1 | Concurrent read-modify-write without `_lock` (#6) |
| `stale-snapshot-overwrite` | 1 | Loader clobbering live counter state (#5) |
| `false-nonvacuity-claim` | 1 | Test claimed to pin a branch it couldn't (#3) |
| `cross-project-key-collision` | 1 | Per-project key used for global ordering (#8) |
| `sentinel-overload` | 1 | None as both cache-empty and legal argument (#11) |

---

## 5. Process: What Worked

1. **Byte-identity extraction as a standing verification step.** The supervisor independently re-extracted every verbatim-mandatory block (eviction, spacing, merge, guard, instrument, sentinel) and diffed against the spec fence — catching two of the supervisor's own extraction bugs along the way (mid-line `find()` anchor, newline asymmetry) before they became false alarms. Builders never edited a fence; nothing drifted.
2. **Detached-worktree red-checks.** After the 2026-09-07 lesson (the review layer auto-commits any tree mutation), every red-before-green ran in `git worktree add --detach` scratch copies — including the auditor's. Zero review-layer incidents across ten phases despite heavy mutation testing.
3. **Exact-suite-list rule for every reported count.** Instituted after the P6 "76" dispute: no number without its command. It cost the P6 and P7a audits their two dismissals, but ended the pattern — P7b and P9 counts all derived first try.
4. **Stage-wise red-checks (one mutant per edit).** P6's four stages each failed exactly the test that pinned its edit — and stage 4 exposed a coverage gap (load-path eviction was unreachable below-cap) *before* delivery, turning a would-be audit finding into a better test.
5. **Auditor continuation passes.** Debugger's unprompted P9 continuation (set_markup never raises; two uncounted suites run green; mid-audit tree delta byte-verified benign) closed loose ends the phase audit legitimately left open.

---

## 6. Process: What Didn't Work

1. **The auditor's count-verification combinations missed small suites three times** (P6 "76", P7a "53/99" — the last partly the supervisor's own verification combo). Impact: two dismissals-with-receipts, ~three audit cycles.
   - Lesson: a reported count is falsified only by running its *stated command*; "no combination I tried yields it" is not evidence.
2. **Supervisor-authored instruction defects reached the builder twice** (P3's false non-vacuity claim; P9's nonexistent `tests/test_feedbar.py` path — pytest collects nothing on a missing path instead of failing loudly). Impact: one false claim propagated into a test docstring; one confusing verification block.
   - Lesson: instruction files are deliverables — verify paths with `ls` and empirical claims with a mutation before writing them.
3. **Spec errata accumulated to five instead of being triaged at entry.** Impact: recurring anchor-drift flags in every phase's COMPLETENESS.
   - Lesson: run an anchor-and-premise drift check as P0's deliverable (this loop did it for line counts but not for prose premises like "13 inline doubles").

---

## 7. What the Code Actually Does (End-User Impact)

1. **Memory stops ratcheting.** A long session no longer grows a widget per card forever: above 120 live widgets, cards scrolled off the top release their widgets (56 KB each) and re-render from data if Load More brings them back. Code path: `add_card`/`add_cards_batch`/load/`_load_more` → `_evict_surplus_card_widgets` (`feed_handler.py:829, 969, 1734, 1863`).
2. **Scrolling stays put.** When eviction removes content above the viewport while the user is scrolled up, the offset is compensated (`value − Σ(height + spacing)`); at the bottom, the view stays pinned. Code path: eviction's compensation arms (`feed_handler.py:1995-2008`).
3. **Reopening a project no longer duplicates or misorders cards.** Same-project reopen unparents stale widgets (no orphans), `_project_cards` is newest-first by `seq_num`, so the batch bar and Accept All see every actionable card. Code path: load-path remove-before-append (`:1726-1730`), ordering block (`:1719-1727`).
4. **Updated cards look updated — everywhere.** A card evicted then updated shows the post-update body when re-rendered (render-from-`_cards`), updates to file-event/task cards now refresh in place instead of rebuilding (seam :346/:382), and an update to an evicted card persists without re-appending an old card at the feed's bottom (guard `:1089-1093`).
5. **The status line stops twitching.** Identical status markup no longer re-lays-out the label, and elapsed-time drift re-renders at most once per second instead of twice. Code path: `feedbar.py:80-83`, `activity_handler.py:812-814`.
6. **Load More never eats its own page.** Each click renders its 15 cards and they survive the eviction pass that click triggers; the label always reports the true remaining count. Code path: `exclude=frozenset(ids_just_loaded)` (`:1863`), merged-count sentinel rebuilds (`:1670`, `:1990-1997`).

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **In-flight loader resurrection race** (`on_project_opened` clears `_backlog` while a previous project's loader thread is mid-parse; the merge can repopulate the old project's backlog). Pre-existing shape at `:1574-1575`; needs a load-generation token. Verified during P7a audit.
2. **GTK exit-time segfault** in GTK-touching suites under bare pytest runs (xvfb resolves it). Known environment issue; documented in `.crabcakes/context.md` since 2026-09-07.
3. **`docs/ARCHITECTURE.md` completeness gaps** (P10 flags 2-4): §3.35 Public API omits `prepend_card`/`replace_card`/`show_empty_state`; §3.22c "Owns:" omits `_backlog`/`_project_seq`/`_active_project_name`/`_loading`; `get_cards_for_project`'s contract noted only in the new paragraph. Pre-existing; not in scope.
4. **`tests/test_feed_body_cap.py` duplicated `MockFeedTab`** rather than importing — the underlying hygiene defect (symptoms fixed in P3's follow-up; deduplication left as the real cure).
5. **`handler` fixture `_is_ui_active` trap** in `test_uirsp3_phase2.py` (bare MagicMock sentinel for `get_current_session_key`); pre-existing fixture design, worked around by tests.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Load-generation token guarding `_backlog`/loader (flag #8.1) | ~2 h | Eliminates cross-project backlog resurrection on fast project switches |
| P11 measurement session (probe + `MALLOC_*` experiment + honest-gate verdict) | 1 h wall-clock | Turns the spec's §6 gate from pending into a verdict; decides the WebKit escalation |
| WebKit render-surface proposal decision | PM decision | Addresses the ~4 MB/min churn the widget bound cannot |
| Global eviction ordering key (or per-project fairness) | ~3 h | Makes cross-project victim selection deterministic |
| Spec erratum pass over SPEC-MEMORY-WIDGET-RATCHET.md | ~1 h | Aligns §2 prose/anchors with delivered reality before the doc becomes historical |
| ARCHITECTURE.md Public-API/Owns completeness pass | ~2 h | Closes flags #8.3; extend `test_all_documented_public_apis_exist` to FeedTab |
| Deduplicate test tab doubles into one importable module | ~2 h | Removes the drift class the body-cap double represented |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Byte-identity, verified by extraction, both directions.**
   - Trigger: any spec block marked verbatim-mandatory.
   - Action: supervisor extracts fence → file and diffs; line-by-line with indent normalization; beware mid-line `find()` anchors and trailing-newline asymmetry (both produced supervisor-side false "DIFFERS" results this loop).
2. **Red-checks only in detached worktrees.**
   - Trigger: any tree mutation for testing (mutants, baseline runs).
   - Action: `git worktree add --detach`, copy the files under test in, run, remove; never stash/checkout in-tree (review layer auto-commits mutations).
3. **No count without its command.**
   - Trigger: every verification number in a builder report or audit.
   - Action: state the exact suite list + command with every count; a count is dismissed only by running its stated command, never by failing to reproduce it from other combinations.
4. **Mutation-equivalence is real: some branches cannot be pinned by real objects.**
   - Trigger: a "this test pins guard half X" claim where GTK/library couples two conditions.
   - Action: demand a synthetic minimal double that isolates the branch, and mutation-verify the test kills the minimal deletion — not just the whole-guard removal.
5. **Instruction files are deliverables.**
   - Trigger: writing any PHASE-N-INSTRUCTIONS.md.
   - Action: `ls` every referenced path; empirically check premises ("13 inline doubles"); never assert a test's discriminating power without running the mutation yourself.
6. **A spec erratum is routed, not absorbed.**
   - Trigger: spec prose contradicts verified reality mid-loop.
   - Action: log erratum + source of proof, keep code on the fence's authority, surface the list to the PM at the post-mortem (this loop: 5 errata, none bent code).

---

## 11. Sign-off

- [ ] Code committed and pushed to main — **PENDING PM ACCEPTANCE** (all work sits in the review-layer diff: 7 files — `ui/handlers/feed_handler.py`, `ui/views/feed_tab.py`, `ui/views/feed_card.py`, `ui/views/feedbar.py`, `ui/handlers/activity_handler.py`, `scripts/crab_mem_probe.py`, `docs/ARCHITECTURE.md` — plus test files and this post-mortem; PM restarts/accepts to commit)
- [x] All post-loop verification commands run and pasted — final sweep 2026-09-17: 505 passed + 1 skipped across `test_feed_handler`(225) + `test_feed_card`(79) + `test_feed_body_cap`(23) + `test_feed_snapshot_off_thread`(8) + `test_review_handler_feed_card`(16) + `test_architecture`(6) + `test_uirsp3_phase2`(15+1skipped) + `test_activity_bubbles`(65) + `test_activity_bubble_batching`(8) + `test_connection_sync_handler`(29) + `test_missing_message_fix`(18) + `test_activity_wiring_handler`(13)
- [x] Captain notified with summary (this document's delivery message)
- [ ] Tier 2+ backlog updated — P11 measurement + items in §9 pending PM session

---

## 12. P11 — CLOSED WITHOUT MEASUREMENT (PM direction, 2026-09-18)

The allocator experiment + honest-gate re-measure (§5 steps 6/8, §6 secondary) was
**not run**. PM directed P11 closed and the loop moved to the DevelCakes fork
(2026-09-18 ~11:19). Record, honestly:

- **Primary gate (deterministic invariant): MET and verified** — P1-P10 closed, audited,
  505-pass final sweep. The widget cap, ordering, backlog discipline, and ticker dedup
  are in production shape.
- **Secondary gate (measured slope): NOT MEASURED — deferred, not met.** No baseline
  probe ever ran: three candidate instances died waiting for a 60-min window (PID
  1369351 pre-loop; PID 1732842 in the 2026-09-18 10:22 OOM session death; the
  10:32 relaunch was superseded by this closure before eligibility at 11:32:28).
  Per §6: absent measurement, the honest statement is "invariant fixed, churn
  unmeasured" — and the standing estimate stands: ratchet fixes ≈0.18 MB/min of a
  recorded 4.55 MB/min (≈4%); the residual churn was always beyond this spec's scope,
  with the WebKit proposal as the designated escalation.
- **Severity record (journal-sourced, Coder's enumeration):** ≥9 kernel OOM kills of
  12-13 GB python3 instances on this machine Sep 09-14, all in the Terminal vte scope;
  plus the 2026-09-18 session death (gnome-shell SIGSEGV under memory pressure +
  oomd sweep). The leak is a recurring operational hazard, not a lab curiosity.
- **What closed with this decision:** the allocator experiment (env-var relaunch arm)
  is NOT run in v1. If DevelCakes v2 still shows churn, re-open measurement there
  (probe is committed; scripts/crab_mem_probe.py).
- Tier-2 backlog: live-widget-count emitter (declared gap in P11 adjudication) stays
  logged for v2.
