# File Tree Concurrent-Expand Fix Post-Mortem

**Date:** 2026-08-14
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** 1 (pending at write time)
**Phases:** 3 (production fix → tests → vacuous-test repair)
**Total bugs found:** 3 (1 HIGH, 1 MEDIUM, 1 LOW — all in tests, all fixed)
**Process:** supervisor/builder/auditor loop per `prompts/implementationLoop.md`; spec-first, file-based delegation, adversarial audit every code-bearing turn, baseline FAIL→PASS proofs required

---

## 1. Code Quality Grade: A (93/100)

### Justification

The production fix is minimal (5 edit sites, +15/−12), spec-exact, and audited clean twice.
The test work needed one repair round — the first delivery included two tests that
passed vacuously on pre-fix code, which the adversarial audit caught and the fix round
resolved with genuinely discriminating scenarios. Nothing compounded: every bug was
caught within its own phase and fixed in a single round-trip.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | All scenarios traced + empirically verified; −1 for test 4's behavioral claim being mechanism-pinned rather than outcome-pinned |
| Architecture compliance | 10/10 | Single view file; no layer violations; no handler/view boundary crossed |
| Test coverage         | 9/10 | 6 targeted tests, 3 behaviorally discriminating, baseline FAIL→PASS proven; −1 for harness duplication across two files (flagged, deferred) |
| Documentation         | 9/10 | Spec + phase instructions + docstrings; −1 for the supervisor's own baseline-count overstatement (corrected in §6) |
| Maintainability       | 9/10 | Per-parent token dict is self-documenting; comments cite spec sections; −1 for two harness implementations |
| DX (Developer Exp.)   | 9/10 | Deterministic harness (no sleeps); grep-verifiable acceptance criteria; −1 for 120s sandbox cap forcing targeted runs |
| **Total**             | **93/100** | **A** |

Deducted points:
- 1 Correctness: `test_clear_state_discards_inflight_load`'s behavioral half can pass even without the staleness guard (store empty + parent gone); only the dict assertion pins the mechanism (Debugger OBSERVATION #3).
- 1 Test coverage: `TestStaleRequestGuard` duplicates the `TestConcurrentExpand` harness inline instead of sharing (Coder flag #2, deferred).
- 1 Documentation: supervisor's "4/5 fail pre-fix" was empirically right but conflated behavioral discrimination with mechanism-assertion failures (Debugger calibration finding).
- 1 Maintainability: same harness duplication as above.

## 2. What's Good About the Code

1. **Per-parent token design (the fix itself):** `ui/views/file_tree.py:455` — replacing one global counter with `dict[str, int]` keyed by directory path makes the staleness guard naturally scoped to the directory it guards. Concurrent expands, collapses, and project switches can no longer invalidate each other's loads. Minimal surface, maximal correctness.
2. **Deterministic async test harness:** `tests/test_file_tree_columnview.py` `tree_harness` — patches only the three I/O boundaries (`GLib.idle_add`, `threading.Thread`, `scan_directory`), so the real `_expand_directory`/`_on_directory_loaded`/`_collapse_directory` code paths execute unmodified with zero sleeps or timing dependence. Debugger confirmed the harness "exercises the real code paths" and has no fixture leakage.
3. **Baseline FAIL→PASS discipline:** every regression test was proven to fail on `git show HEAD:` code and pass on the fixed code, independently re-run by the supervisor. This is what turned "tests pass" into "tests catch the bug."
4. **Token non-mutation on collapse:** spec §3.4's decision to leave the dict untouched in `_collapse_directory` — relying on the `expanded` check plus mint-on-expand — provably prevents the duplicate-children interleaving (collapse→re-expand with stale first load), confirmed by test 3 and the Phase-1 audit's interleaving table.

## 3. What's Bad About the Code

1. **Two parallel harness implementations:** `TestStaleRequestGuard` (sort_filter) inlines its own `_SyncThread` + `fake_idle_add` instead of reusing `tree_harness` (which lives in the columnview file). ~25 duplicated lines, mild DRY violation.
   - Evolution: extract a shared `tests/helpers/file_tree_harness.py` fixture module.
2. **Test 4's outcome half is guard-independent:** after `_clear_all_state` the store is empty and the parent row is gone, so the "no children inserted" assertion would pass even with no staleness guard at all; only `assert tree._dir_load_requests == {}` carries the mechanism pin.
   - Evolution: if stricter, add a same-tick re-expand after clear and deliver the pre-clear load to prove rejection by token rather than by absent parent.

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 2 | HIGH | `test_collapse_reexpand_no_duplicate_children` passed on pre-fix code — vacuous as a regression guard | Debugger (§5 probe, vacuous-assertion) | Coder (added discriminating `test_collapse_reexpand_does_not_invalidate_other_dirs`) |
| 2 | 2 | MEDIUM | `test_clear_state_discards_inflight_load` passed on pre-fix code; no mechanism pin | Debugger (vacuous-assertion) | Coder (dict-cleared assertion + docstring note) |
| 3 | 2 | LOW | `TestStaleRequestGuard` relied on brittle `inspect.getsource` substring check; behavioral half vacuous | Debugger (brittle-string-assertion) | Coder (behavioral discriminating rewrite; `inspect` removed) |

All three were test-quality bugs caught by the adversarial audit in the same phase they
were introduced; none reached a downstream phase and none touched production code. The
Phase-1 production fix itself was audited clean on the first probe (16 attack vectors).

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `vacuous-assertion` | 2 | Tests asserted outcomes that pre-fix code already produced |
| `brittle-string-assertion` | 1 | Verbatim source-text match breaks on benign refactor |

## 5. Process: What Worked

1. **Spec-first with anti-interleaving rationale:** writing spec §3.4's "do NOT touch the dict on collapse" *with the duplicate-children argument* before any code existed meant Coder, Debugger, and the tests all reasoned from the same table of interleavings — zero design disputes.
2. **Baseline proof as a hard requirement:** mandating `git show HEAD:file > file` proofs (never stash/checkout, per the 2026-07-19 review-layer incident) produced the strongest artifact of the loop: empirical FAIL→FAIL→FAIL/FAIL→PASS chains run independently by both Coder and Supervisor.
3. **Mandatory adversarial audit earned its cost:** the Phase-2 audit's vacuous-test findings are exactly the class of defect that green-checkmark verification misses — tests passing on broken code. Two rounds of audit (Phase 1: clean; Phase 2: 3 bugs → repair → clean re-audit).
4. **Scope guards held:** Coder flagged (not fixed) both the 3 pre-existing failures and the harness duplication; no scope creep into diff_viewer or the widget tests.

## 6. Process: What Didn't Work

1. **Supervisor's baseline-count imprecision:** my re-audit handoff claimed "pre-fix 4/5 fail" without decomposing *why* they fail. Debugger's static analysis said 3/5; re-running with `-v` showed both were right — 4 fail (3 behaviorally + 1 via the new AttributeError assertion), 3 discriminate behaviorally. Wasted half a debate on a reconcilable ambiguity.
   - Lesson: when quoting test outcomes, decompose failure *mode* (behavioral vs. mechanism-assertion vs. error), not just count.
2. **Full-suite verification truncated by the 120s exec cap:** the 3,507-test suite can't complete in-sandbox; verification fell back to targeted files (121 tests across 5 files). Residual risk is low (single-file production change, no API change) but not zero.
   - Lesson: for single-file UI fixes, define an explicit adjacent-module test list in the spec instead of improvising the fallback mid-loop.
3. **`/clear` pairing failed twice:** both attempts to clear Coder/Debugger contexts were rejected ("a tool loop is currently running"). Context was retained instead — which turned out fine (mid bug-fix retention is the §9.9 exception anyway) but the failure mode was uncontrolled, not chosen.

## 7. What the Code Actually Does (End-User Impact)

1. **Expanding several folders quickly now shows all their contents.** Click `apps`, then `packages` before the first scan finishes: both receive children. Previously `apps` stayed expanded-but-empty until manually collapsed/re-expanded (the eagledispatch report). Code path: `ui/views/file_tree.py:1983` (per-parent token mint) → `:2037` (per-parent staleness check) — each directory's load is validated only against its own latest token.
2. **Collapse→re-expand races no longer duplicate children.** Expand A, collapse A, re-expand A before the first scan returns: exactly one set of children (re-expand mints token 2; stale load carrying token 1 is discarded). Code path: `_expand_directory` token bump + `_on_directory_loaded` mismatch return.
3. **Project switches stay clean.** Navigating back to the picker mid-scan clears all tokens (`_clear_all_state`, `:605`); any late-arriving scan finds no token and inserts nothing into the new project's tree.

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **3 failing widget tests** in `tests/test_file_tree_columnview.py` (`test_widget_has_children`, `test_set_label` — Gtk child-ordering assumptions; `test_setup_creates_widget` — `FileTreeFactory(None)` dereference). Verified failing on HEAD baseline before this work (supervisor `git stash` run, 2026-08-14). Not in scope.
2. **`DiffViewer._current_request_id`** in `ui/views/diff_viewer.py:98` — same global-counter pattern this loop removed from FileTree. Same class of race may exist there. Pre-existing on HEAD. Candidate for a future loop.
3. **Headless GTK segfault** in Debugger's sandbox (no display): `FileTree()` construction segfaults without `xvfb-run`. Environmental; the supervisor's runner used `xvfb-run -a` throughout.

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Extract shared `file_tree_harness` fixture module for the two test files | ~1h | Removes ~25 duplicated lines; single place to evolve async harness |
| Audit/port `DiffViewer._current_request_id` to per-parent tokens | ~2h | Closes the same race class in the diff drawer subsystem |
| Fix the 3 pre-existing widget tests (child-ordering + factory None) | ~2h | Green columnview suite; removes noise from every future loop in this file |
| CI/nightly full-suite run outside the 120s sandbox cap | ~3h | Restores true full-suite regression evidence for UI loops |

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Decompose failure modes when reporting test outcomes.**
   - Trigger: any baseline-vs-fix comparison quote in an audit handoff or report.
   - Action: state counts split by mode — behavioral failure / mechanism-assertion failure / error — so static and empirical reviewers reconcile on first pass.
2. **State the adjacent-module test list in the spec.**
   - Trigger: writing a spec whose verification will hit the sandbox time cap.
   - Action: spec §Test Plan names the explicit targeted file list (and its expected pass count) so the fallback is contract, not improvisation.
3. **Vacuous-test probe belongs in the standard audit ask.**
   - Trigger: any phase that delivers regression tests.
   - Action: the audit handoff must include "run the new tests against pre-fix code and report which fail" — this loop's highest-value finding came from exactly that question.

## 11. Sign-off

- [ ] Code committed and pushed to `main`
- [x] All post-loop verification commands run and pasted (targeted suites: 121 passed / 3 pre-existing failures; baseline discrimination: pre-fix 4 fail [3 behavioral + 1 mechanism-assert], post-fix 5/5 pass)
- [ ] Captain notified with summary
- [x] Tier 2+ backlog updated (§9 — 4 items)
