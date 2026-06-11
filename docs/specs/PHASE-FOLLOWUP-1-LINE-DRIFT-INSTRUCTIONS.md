# PHASE FOLLOWUP 1 of N — Fix Line-Number Drift in Specs

**Task:** Create a spec-writing convention document that prevents line-number drift, then retroactively fix the line-number references in PHASE-11 specs as a reference example.

**Reference:** PHASE-11 post-mortem, "Suggested follow-ups: Fix spec line-number drift — use symbol-based navigation going forward."

## Files to create

1. `docs/specs/SPEC-LINE-NUMBER-DRIFT.md` — new spec-writing convention document
2. `docs/specs/PHASE-11-P1-INSTRUCTIONS.md` — retroactively fixed
3. `docs/specs/PHASE-11-P2-INSTRUCTIONS.md` — retroactively fixed
4. `docs/specs/PHASE-11-P3-INSTRUCTIONS.md` — retroactively fixed

## The Problem

Every time code changes, line numbers shift. Specs that say "insert at line 1401" are wrong the moment the first edit lands. This has burned three consecutive phases:

- PHASE-10.5: spec said "line 1401" but actual was different
- PHASE-11 P1: spec said "insert after line 1400" but actual insertion point was ~1369
- PHASE-11 P2: spec said "4 patches at lines 631, 661, 689, 724" — there are actually 5 patches, and their positions shifted
- PHASE-11 P3: spec said "around line 690-745" but actual was different

## The Rule

**Never use line numbers for navigation in specs. Use symbols.**

Symbol-based anchors:
- "Find `def _call_llm(` in `agent/runtime.py` and insert the new method after it ends"
- "Find the `class TestStreaming:` block and add the helper after `_resp()`"
- "Find the line containing `assert complete[0] == \"Hello world!\"`"
- "Find the last method in `AgentRuntime` before `_check_stuck`"

When you MUST include line numbers (e.g. for verification commands that check file state):
1. Use them only for verification commands (`grep -n`, `sed -n Xp`)
2. Mark them as approximate: "around line X" not "at line X"
3. Include a "verify line numbers" step in the spec that re-checks them before the agent runs

## Rules

- Read all 3 PHASE-11 spec files completely before editing
- Create `SPEC-LINE-NUMBER-DRIFT.md` with the convention
- For each PHASE-11 spec, find every line-number reference and replace with symbol-based navigation
- Keep all other spec content unchanged (code samples, rules, verification commands)
- Run: `python3 -c "print('OK')"` to confirm no syntax issues in created files
- Run: `grep -n "line [0-9]" docs/specs/PHASE-11-*.md docs/specs/SPEC-LINE-NUMBER-DRIFT.md` to verify no bare line numbers remain (except in grep commands)
- At the end, include a completeness checklist

## Approach

**SPEC-LINE-NUMBER-DRIFT.md** should cover:
1. The problem statement (what happened, why it matters)
2. The rule (never use line numbers for navigation)
3. Approved symbol-based patterns with examples
4. When line numbers ARE acceptable (verification commands only)
5. Retroactive fix instructions for existing specs

**Retroactive fixes to PHASE-11 specs:**
- P1: Replace "after line 1400 (end of `_call_llm`)" with "after `def _call_llm(` ends" — keep the call site reference as a grep command, not a line number
- P2: Remove line-number annotations from patch locations — use "find the `with unittest.mock.patch.object(rt, \"_call_llm\", ...)` pattern inside `TestStreaming`"
- P3: Replace "around line 690-745" with "find `class TestStreamingSignature:` and insert before it" — use symbol-based anchor