# Post-Mortem: Tier 1.3 — Agent-Role Gating for Project Onboarding

**Date:** 2026-06-13
**Supervisor:** Qaster (Implementation Supervisor)
**Builder:** QTR (via `/ask @QTR` delegation from authorized CLI channel)
**Commit:** `7a3d8c9`
**Spec:** `docs/specs/SPEC-AGENT-ROLE-GATING-FIX.md`

---

## What was built

A single-line gate added to `utils/prompt_loader.py:184` so the `project-onboarding.md` template only loads for `agent_role == "coder"` agents. Previously, every agent with `project_path` set got the 3.3K onboarding interview injected into their first message — gateway and debugger agents included.

**Files changed:**
- `utils/prompt_loader.py` — 1 line changed (line 184)
- `tests/test_prompt_loader.py` — 34 lines added (1 new test with 3 sub-assertions for Coder, Debugger, Gateway)

---

## Code Quality Grade: **A**

This is the cleanest Tier 1 fix so far:
- 1 line in production code, 1 test, 1 bug fixed
- Zero scope creep
- Zero regressions
- QTR caught a real test-coupling issue and tightened the marker without being asked

---

## What's Good

1. **The right fix, minimal surface.** A `BUG_REPORT-identity-override.md` Bug #2 has been sitting open since the bug was filed. The fix is one comparison. No need to redesign anything, no need to add an allowlist, no need to touch callers. The `agent_role` parameter was already there.

2. **Test exercises the actual user-facing behavior.** Three sub-assertions confirm Coder gets onboarding, Debugger does not, Gateway does not. Not just a test of the helper method — a test of the gate's effect on the composed prompt.

3. **QTR caught a false-positive in the test marker.** The spec said to use `"Onboarding" in prompt or "onboard" in prompt.lower()`. QTR found that `project-awareness.md` contains "Onboarding complete → suggest loading cc-workflow-guide" — which would have made the test pass for the wrong reason (catching the wrong template). QTR tightened the marker to `"ONBOARDING phase"` and documented the coupling risk. This is exactly the kind of adversarial check the implementation-supervisor prompt asks for (§3 "Tests exercise the user-facing behavior, not just helper methods").

4. **QTR's "flag, don't fix" discipline held.** Four genuine findings flagged without attempt at silent fix: broad `onboard` marker coupling, no unit tests for `is_project_onboarded`, `crabcakes-commands.md` loaded unconditionally for gateway agents, and the bare `except Exception: pass` around the onboarding check. All out of scope; all real follow-up items.

5. **The end-to-end trace in QTR's report was precise.** Three cases (Coder, Debugger, Gateway) traced line-by-line through `compose_system_prompt`, confirming the short-circuit behavior at each branch. This catches the kind of "did it actually gate" question that helper-level tests miss.

6. **No working tree contamination.** The repo has 100+ pre-existing deleted/modified spec files in the working tree (from prior session cleanup). QTR staged exactly the 2 expected files. The Tier 1.2 commit had to manually filter the same noise; the pattern held here.

---

## What's Bad

1. **The spec's test marker was too broad.** I wrote `"Onboarding" in prompt or "onboard" in prompt.lower()` in the SPEC. QTR caught that `project-awareness.md` contains "Onboarding complete" — which would have made the test pass for the wrong reason. Lesson: when writing a test, check the other templates that load in the same code path for marker collisions.

2. **The pre-existing working tree noise (100+ D/M files) is still there.** This is the third Tier 1 commit where I've had to filter it out. It would be worth a Tier 2.5 sweep to clean it up: either `git clean` the deleted files or commit the moves. Deferring to follow-up.

---

## Bugs Found During Audit

| # | Bug | Found by | Severity | Status |
|---|---|---|---|---|
| 1 | Spec test marker would false-positive on `project-awareness.md` | QTR (Related Issues #1) | Low (test would pass for wrong reason) | Fixed by QTR: tightened to `"ONBOARDING phase"` |
| 2 | No unit tests for `is_project_onboarded()` | QTR (Related Issues #2) | Low | Deferred to follow-up |
| 3 | `crabcakes-commands.md` loads for gateway agents unnecessarily | QTR (Related Issues #3) | Low (separate scope) | Deferred to follow-up |
| 4 | Bare `except Exception: pass` around onboarding check | QTR (Related Issues #4) | Low (pre-existing) | Deferred to follow-up |

No new bugs introduced by the fix. No regressions in the 31 context tests or 35 prompt_loader tests.

---

## Successes and Failures in the Process

**Successes:**
- File-based delegation pattern held for a second time. Tier 1.2's lesson transferred cleanly.
- Independent verification ran all 6 commands myself, confirmed the diff is exactly 1 line, confirmed the test passes, confirmed no regressions in 66 related tests.
- The 1-line change was small enough that the audit took 3 minutes. The supervisor prompt's "one file per phase, one change per phase" mantra paid off.
- QTR's Related Issues were higher-quality than expected — the false-positive marker catch is the kind of thing a less careful builder would have missed.

**Failures:**
- The spec's test marker was a false-positive trap. The supervisor should have checked the other templates loaded in `compose_system_prompt` for marker collisions before writing the assertion.
- The pre-existing working tree noise is now 3 commits deep. Time to clean it up.

---

## Lessons Learned

1. **QTR caught a test marker collision the supervisor missed.** This validates the "flag, don't fix" rule: QTR's Related Issues #1 was a higher-quality observation than the spec's test design. The builder's adversarial check (Step 6.6 of steelFramedCodeWriter) found a bug in the spec, not the code.

2. **File-based delegation is now a confirmed pattern.** Two Tier 1 fixes in a row, zero truncation issues. The 4,096-char `/ask` limit and the 7,975-char phase-instructions file is a clean separation.

3. **The Tier 1 items are all small enough to verify in under 5 minutes.** 1 line in production, 1 test, 6 verification commands. The roadmap's "estimated effort" of "1 line + 1 test" was accurate for both Tier 1.2 and Tier 1.3. If a Tier 1 item ever balloons past 1 file in production or 50 lines of test, it's a sign it's actually a Tier 2 item disguised as Tier 1.

4. **The 100+ pre-existing working tree files are accumulating.** After 3 Tier 1 commits, the noise is real. The next session should either clean it up or document why it's there.

---

## Open Follow-ups (Tier 2/3 candidates)

- Tighten `is_project_onboarded()` marker check in test (or add a template-content-mocking helper for future tests)
- Add unit tests for `is_project_onboarded()` itself
- `crabcakes-commands.md` should not load for gateway agents (separate Tier 1 fix?)
- Bare `except Exception: pass` should at least log
- 100+ pre-existing working tree files: clean up or document

---

## Commit history for Tier 1.3

- `32c7f26` — docs: spec + phase instructions for Tier 1.3 (agent-role gating fix, 1-line)
- `7a3d8c9` — fix(prompt-loader): gate project-onboarding template to coder agents only (Tier 1.3)
- `0e0449a` — docs: PROPOSAL-project-onboarding status PARTIAL → DONE (Tier 1.3 complete)
- (this commit) — docs: post-mortem for Tier 1.3
