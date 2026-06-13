# PHASE FOLLOWUP 2 of N — Audit 13 Pre-Existing Test Failures

**Task:** Audit the 13 pre-existing test failures that have been accumulating across PHASES 1-11. Categorize each failure, identify root causes, and file bugs or fix where possible.

**Reference:** PHASE-11 post-mortem, "Should do #2: Audit the 13 pre-existing test failures. The 5 in `test_agent_builder_handler.py` and 3 in `test_special_agents.py` are the biggest clusters."

## Files to change

This is an audit-only task. You may create/modify test files only if the fix is trivial (e.g. a missing import, a typo). For anything non-trivial, document the root cause in a bug report file at `docs/specs/PHASE0-BUGS.md`.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Run the full test suite first to get the current failure count and list
- For each failing test, determine:
  1. Which test file and test class/method
  2. What the error is (import error, assertion failure, fixture issue, etc.)
  3. Whether it's a pre-existing failure (existed before PHASE 10-11 work) or a regression
  4. Root cause
  5. Fixability (trivial / fixable with effort / deferred)
- Fix only **trivial** failures (missing import, typo, wrong path, etc.)
- For all others, document in `docs/specs/PHASE0-BUGS.md`
- Run: `cd /home/q/projects/crabcakes && python3 -m pytest tests/ -q --tb=no --no-header 2>&1 | tail -10` and paste output
- Run: `cd /home/q/projects/crabcakes && python3 -m pytest tests/ --tb=no --no-header 2>&1 | grep "FAILED" | head -20` and paste output
- At the end, include a completeness checklist

## Approach

**Step 1: Get the full failure list**
Run the full suite with no-traceback output to get the list of failing tests.

**Step 2: Run each failing test in isolation**
Run each failing test individually with full traceback to understand the error.

**Step 3: Categorize**
- **Type A — Trivial fix:** import error, typo, wrong path, missing mock — can fix in this phase
- **Type B — Non-trivial fix:** logic error, fixture issue, external dependency — document and defer
- **Type C — Pre-existing but now blocking:** was passable before but broke silently — investigate

**Step 4: Fix Type A only**
Fix only the trivial ones. Do NOT refactor non-trivial failures in this phase.

**Step 5: Document Type B/C**
Create `docs/specs/PHASE0-BUGS.md` with one section per failing test.

## Anti-patterns to avoid

- Do NOT run only the failing tests — run the full suite
- Do NOT assume a failure is pre-existing without checking git history
- Do NOT hide failures — if a test was passing before and now fails, flag it as a regression
- Do NOT spend more than 5 minutes on any single failure — if it's non-trivial, document and defer