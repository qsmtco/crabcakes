# Post-Mortem: Activity Drawer Bug Fix Sprint (BUGFIX-1 through BUGFIX-9)

**Date:** 2026-06-06
**Duration:** ~4 hours (09:50 PDT – 14:00 PDT + 23:00–23:10 PDT)
**Commits:** 8 commits on main (`e2b3908` through `5a03ffe`)
**Builder:** QTR ("Cutter") — steelFramedCodeWriter prompt
**Supervisor:** Qaster — implementationSupervisor + adversarialDebugger prompts
**Final test result:** 1242/1243 pass (1 pre-existing failure unchanged)

---

## Code Quality Grade: B+

**Justification:** The fixes are surgical, well-tested, and follow existing patterns. The two bugs found during adversarial audit (type confusion on exitCode, missing status check) reveal that QTR's first pass is solid but not perfect — the adversarial loop caught real issues. Comments are clear and reference the spec. No collateral edits.

---

## What's Good

1. **QTR follows patterns precisely.** Every branch mirrors the existing `patch` branch structure. Defensive `or ""` patterns, `_resolve_agent_name` resolution, phase gating — all consistent with the codebase's established style.

2. **Test quality is high.** Every fix has tests that can actually fail. The BUGFIX-1 audit tests (string exitCode, missing exitCode with failed status) are genuine edge cases. The BUGFIX-3 tests verify the subtle counter-collapse interaction. BUGFIX-4 has both vulnerability tests and regression guards.

3. **No collateral edits.** QTR obeyed Rule 8 (steelFramedCodeWriter) — no adjacent reformatting, no "improvements," no import reordering. Diffs are clean.

4. **Counter-collapse math is correct.** BUGFIX-3's interaction with `_mutate_counter_row` was the hardest part. The `setdefault` behavior when the key already exists (returns existing dict, doesn't overwrite) means the new-row initialization and the collapse mutation compose correctly. No double-counting.

5. **Documentation is honest.** BUGFIX-5/6 correctly identifies these as gateway limitations, not code bugs, and documents workaround options.

---

## What's Bad

1. **QTR missed the exitCode type confusion (BUG A in BUGFIX-1 audit).** The gateway sends `exitCode` as an int, but the code didn't defend against string serialization. The adversarial audit caught it. This is the kind of defensive coding that should be automatic when following the steelFramedCodeWriter's Rule 6 ("Validate All External Input").

2. **QTR missed the status="failed" with no exitCode case (BUG B in BUGFIX-1 audit).** The code only checked `exit_code != 0` and ignored the `status` field entirely. Again, Rule 6 should have caught this — the function accepts data from outside and didn't validate all the relevant fields.

3. **The implementationSupervisor (me) wasted the Captain's time.** I failed to remember how to use `/ask @QTR` and spawned a subagent instead, then fumbled the format multiple times. This is a process failure that added 15+ minutes of frustration. Lesson: know your tools before starting a delegation loop.

4. **Pre-existing test failure was not addressed.** `test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer` has been failing since before this sprint. It expects the old `_bubble_to_row` function signature but the code was refactored. Should be fixed in a future sprint.

---

## Bugs Found During Audit

| Bug | Found By | Phase | Severity | Description |
|-----|----------|-------|----------|-------------|
| exitCode type confusion | Qaster (adversarialDebugger) | BUGFIX-1 round 1 | bug | string "0" treated as error |
| Missing status check | Qaster (adversarialDebugger) | BUGFIX-1 round 1 | bug | status="failed" with exitCode=0 shows SUCCESS |
| None (BUGFIX-2) | — | — | — | Clean on first pass |
| None (BUGFIX-3) | — | — | — | Clean on first pass |
| None (BUGFIX-4) | — | — | — | Clean on first pass |
| None (BUGFIX-5/6) | — | — | — | Doc-only |
| None (BUGFIX-7/8/9) | — | — | — | Clean on first pass |

**Audit rounds per fix:**
- BUGFIX-1: 2 rounds (2 bugs found in round 1, clean in round 2)
- BUGFIX-2 through BUGFIX-9: 1 round each (clean)

---

## Process Metrics

| Metric | Value |
|--------|-------|
| Total bugs fixed | 9 |
| Production code changes | 4 files |
| Test code changes | 3 files |
| Documentation changes | 2 files |
| New tests added | 19 |
| Bugs found in audit | 2 (both in BUGFIX-1) |
| Audit rounds | 11 total (9 first-pass + 2 re-audit) |
| Pre-existing failures | 1 (unchanged) |
| Regressions introduced | 0 |

---

## Commits

```
5a03ffe fix: elif chain, redundant guard removal, type guards (BUGFIX-7/8/9)
4473ef7 docs: document gateway event limitations for patch, plan, approval (BUGFIX-5/6)
58abe40 fix: guard state machine transitions to lifecycle events only (BUGFIX-4)
eb3400d fix: initialize _agent_counters in new-row path for accurate on_agent_end stats (BUGFIX-3)
94fb3dc fix: clear _last_row_widget after row trim to prevent GTK crash (BUGFIX-2)
e2b3908 fix: add missing stream=command_output handler (BUGFIX-1)
4d11917 fix: PHASE 8 latent bug — add _agent_name resolution to plan/approval/patch branches
```

Note: QTR's commits for BUGFIX-7/8/9 went through the review layer (`Accept: Modified ...`), committed as `72d3aa8`, `70b3440`, `aff099a`. The final commit `5a03ffe` adds the test file and spec.

---

## Lessons Learned

1. **The adversarialDebugger catches real bugs.** The exitCode type confusion and missing status check are genuine production risks. Without the adversarial audit, BUGFIX-1 would have shipped with two latent bugs. The audit process paid for itself in the first phase.

2. **File-based delegation works.** Every phase used `docs/specs/BUGFIX-N-INSTRUCTIONS.md`. No truncation, no ambiguity. QTR read the file, followed it, reported against it. Zero miscommunication on scope.

3. **Know your communication channels before starting.** The `/ask @AgentName "quoted payload"` format is documented in the project manifest. I should have read it before the sprint instead of fumbling live.

4. **One file per phase, one change per phase.** Every phase touched 1-2 files with a focused change. First-try success rate was very high (7 of 9 phases clean on first audit). The two bugs in BUGFIX-1 were in the same file, same change — caught by the adversarialDebugger in one pass.

5. **Counter-collapse state machines need careful testing.** BUGFIX-3's interaction between `_agent_counters` initialization (new-row path) and `_mutate_counter_row` (collapse path) was the most subtle fix. The `setdefault` pattern means the two paths compose correctly, but this required careful tracing to verify. The mixed new-row + collapse test is the one that would catch a regression.

---

## Recommendations for Future Work

1. **Fix the pre-existing test failure** in `test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer`. It's been failing since at least PHASE 8.

2. **Add client-side patch detection.** Per BUGFIX-5's workaround option (A): treat `stream: "item" kind: "tool"` end events with `name in {write, edit, write_file, edit_file}` as patch-like events. This would give file-edit visibility for agents that don't use `apply_patch`.

3. **Add `durationMs` coercion.** Same risk as the exitCode type confusion — `durationMs` from the gateway could theoretically arrive as a string. Add `int(data.get("durationMs", 0) or 0)` in the command_output branch for consistency.

4. **Update ARCHITECTURE.md.** The command_output handler is a new event dispatch path. Section 3.8 (ActivityHandler) should be updated to reflect the complete stream catalog.
