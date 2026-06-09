# PHASE 9B — Item 1: Documentation fix (test result line)

## Master spec
`docs/specs/PHASE-9-COMPLETION-REPORT.md` line 6 (and the COMPLETENESS entry for item 9.7).

## Context
The completion report's "Test result" line says `1283 passed, 1 skipped, 2 xfailed, 0 failures in 9.04s`. This is wrong. The actual full test suite result (verified by the auditor via two independent runs) is:

```
1 failed, 1364 passed, 1 skipped, 2 xfailed, 4 warnings in 134.98s (0:02:14)
```

The 9.04s runtime is also impossible — every full run in this session took 2:14-2:15. The 1283 count is 81 short of 1364 (which matches the 1368 collected minus 1 failed + 1 skipped + 2 xfailed = 4 non-passing, leaving 1364 passing).

## Files to change

1. `docs/specs/PHASE-9-COMPLETION-REPORT.md` — REVISED. Two text corrections.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `proceed` is in this delegation.
- **Do NOT modify any code or test files.** This is a documentation fix only.
- **Do NOT modify any other line of the report** — only the two test-result references listed below.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## SUB-PHASE 9B.1: Fix line 6 (executive summary)

**Current (line 6):**
```
**Test result:** 1283 passed, 1 skipped, 2 xfailed, 0 failures in 9.04s
```

**Replace with:**
```
**Test result:** 1364 passed, 1 failed, 1 skipped, 2 xfailed, 4 warnings in 134.98s (0:02:14)
```

## SUB-PHASE 9B.2: Fix the COMPLETENESS evidence line (item 9.7)

Find the line that reads:
```
- [x] 9.7 full test suite run — evidence: `1283 passed, 1 skipped, 2 xfailed, 0 failures in 9.04s`
```

**Replace with:**
```
- [x] 9.7 full test suite run — evidence: `1 failed, 1364 passed, 1 skipped, 2 xfailed, 4 warnings in 134.98s (0:02:14)` (verified via two independent full-suite runs in the same session)
```

## SUB-PHASE 9B.3: Add a brief Note about the discrepancy

Add a short note (2-3 sentences) near the executive summary (or in a new "Note on test count correction" section after section 1) explaining that the original Phase 9 submission reported 1283 passed in 9.04s, which was the result of an accidentally filtered suite run; the auditor ran the full suite twice and the correct result is 1364 passed in 134.98s. Suggested wording:

> **Note on test count:** The original Phase 9 report listed 1283 passed in 9.04s, which was the result of a filtered run (heavy tests like `test_agent_runtime.py` were excluded to avoid a sandbox OOM). The auditor ran the full suite twice in the same session; the correct result is 1364 passed, 1 failed, 1 skipped, 2 xfailed in 134.98s. The single failure is the pre-existing `test_connection_sync_handler.py::TestActivityHandlerWiring` test, which has been failing since Phase 3 and is not a regression from this spec.

You may add this as a new section 1.1 or as a footnote in the executive summary. Your call — just make sure the discrepancy is documented so future readers don't get confused.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# Verify line 6 now has the correct number
sed -n '6p' docs/specs/PHASE-9-COMPLETION-REPORT.md
echo "---"

# Verify the COMPLETENESS evidence line is updated
grep "9.7 full test suite" docs/specs/PHASE-9-COMPLETION-REPORT.md
echo "---"

# Sanity: the report still has 340ish lines (no large accidental deletions)
wc -l docs/specs/PHASE-9-COMPLETION-REPORT.md
echo "---"

# Sanity: the 1283 / 9.04 strings are GONE from the report
if grep -q "1283" docs/specs/PHASE-9-COMPLETION-REPORT.md; then
    echo "FAIL: 1283 still in report"
else
    echo "OK: 1283 removed"
fi
if grep -q "9.04" docs/specs/PHASE-9-COMPLETION-REPORT.md; then
    echo "FAIL: 9.04 still in report"
else
    echo "OK: 9.04 removed"
fi
```

## Acceptance criteria for this phase

- [ ] Line 6 of `PHASE-9-COMPLETION-REPORT.md` reads `1364 passed, 1 failed, 1 skipped, 2 xfailed, 4 warnings in 134.98s (0:02:14)`
- [ ] The COMPLETENESS entry for 9.7 cites the correct test result
- [ ] A note documents the discrepancy between the original report and the corrected number
- [ ] The strings "1283" and "9.04" no longer appear anywhere in the report
- [ ] The report's line count is still 330-360 (no accidental deletions)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 9B (Item 1) — COMPLETE

Files changed:
- docs/specs/PHASE-9-COMPLETION-REPORT.md — REVISED, +N / -M lines (paste git diff --stat)

Verification (paste outputs of every command listed above):
- line 6 corrected: ...
- COMPLETENESS evidence updated: ...
- line count preserved: ...
- 1283 / 9.04 removed: ...

**COMPLETENESS:**
- [x] 9B.1 line 6 has 1364 passed — evidence: <sed output>
- [x] 9B.2 COMPLETENESS evidence corrected — evidence: <grep output>
- [x] 9B.3 discrepancy note added — evidence: <grep output>
- [x] 9B.x 1283 / 9.04 strings gone — evidence: <grep -v output>
- [x] 9B.x report line count preserved — evidence: <wc -l output>

When done, please write: `Item 1 complete — ready for Item 2.`
```

When done, please write: `Item 1 complete — ready for Item 2.`
