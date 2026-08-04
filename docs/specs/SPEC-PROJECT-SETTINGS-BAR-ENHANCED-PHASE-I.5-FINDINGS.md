# Phase I.5 Audit Findings — Tests

**Code under audit:** 3 test files (37 new tests)
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ✅ **PASS with recommendations**

## Summary

**Initial test run: 72/72 pass** (37 new + 35 regression).

**Mutation test results: 8/10 caught, 1 partial, 1 untestable.** The test suite catches real regressions — it is not a false-confidence suite.

**Bug count: 0 CRIT, 0 HIGH, 1 MED, 3 LOW, 4 INFO.**

## Mutation test results (the key evidence)

| # | Mutation | Caught? |
|---|----------|---------|
| 1 | Remove gear re-append | ✅ YES |
| 2 | Remove xml_escape on project name | ✅ YES |
| 2b | Remove xml_escape on branch | ✅ YES |
| 3 | Revert BUG #7 fix (empty-value fallback) | ✅ YES |
| 4 | Make on_cancel emit | ✅ YES |
| 5 | Remove default-arg capture | ❌ NO (untestable — defensive pattern, no manifestation path) |
| 6 | Remove refresh from off-path | ✅ YES |
| 7 | Remove token guard | ❌ **NO** (BUG #1 — test gap) |
| 8 | Remove active-project identity check | ✅ YES |
| 9 | Key cache by name instead of path | ⚠️ PARTIAL (write path caught, reuse path not) |
| 10 | Remove build-time fix | ✅ YES |

## Top 3 must-fix (coverage gaps, not code bugs)

1. **BUG #1 (MEDIUM)** — Add `test_branch_worker_not_stacked_when_already_running` for token guard (Round 2 BUG #1). The only missing test for a critical production invariant.
2. **BUG #2 (LOW)** — Add `test_a_to_b_to_a_cache_reuse` for path-keyed cache (Round 3 BUG #5).
3. **BUG #7 (LOW)** — Add `test_worker_returning_after_close_is_discarded` for full close-mid-refresh integration.

**Supervisor decision:** These are test-coverage improvements, not code bugs. The implementation is correct (audited in I.2/I.3/I.4). Documenting as deferred items in the post-mortem §9 (Evolution Suggestions) rather than blocking the loop.

## Coverage assessment

- **Phase I.2 (FeedHandler):** 10/11 invariants covered.
- **Phase I.3 (MainContent):** 14/16 invariants covered.
- **Phase I.4 (Window):** 12/15 invariants covered.

## Test quality observations

- **Assertion strength:** Strong — checks cache contents, markup payloads, callback invocations.
- **Fake/mock fidelity:** Good — `_FakeGtk.Box` supports sibling-walk; `MockGLib` runs idle_add synchronously.
- **GTK segfault avoidance:** Clean — `__new__()` bypass + fakes.
- **Test isolation:** Good — independent fixtures.

## Next step

Proceed to Phase I.6 (ARCHITECTURE.md update).
