# BUGFIX-1 Audit — Issues Found

## BUG A: exit_code type confusion — string "0" treated as error

**Severity:** bug
**File:** `ui/handlers/activity_handler.py:424` (the `exit_code = data.get("exitCode", 0)` line)
**Bug:** `exitCode` from the gateway could arrive as a string (e.g. `"0"` or `"1"`) due to JSON serialization edge cases. The check `exit_code != 0` uses Python equality, where `"0" != 0` is `True`. This means a string `"0"` exit code would be treated as an error.
**Expected:** `exit_code = 0` (int) → `ToolStatus.SUCCESS`
**Actual:** `exit_code = "0"` (string) → `ToolStatus.ERROR`
**Root cause:** No type coercion on `exitCode` field.
**Fix:** Change line to: `exit_code = int(data.get("exitCode", 0) or 0)`
**Pattern:** type-confusion
**Tests:** Add a test case with `"exitCode": "0"` (string) and assert `bubble.status == ToolStatus.SUCCESS`. Add a test case with `"exitCode": "1"` (string) and assert `bubble.status == ToolStatus.ERROR`.

## BUG B: status="failed" with exitCode=0 shows SUCCESS

**Severity:** bug
**File:** `ui/handlers/activity_handler.py:432` (the `ToolStatus.ERROR if exit_code != 0 else ToolStatus.SUCCESS` line)
**Bug:** The error determination only checks `exit_code != 0`. If the gateway sends `status: "failed"` but `exitCode` is absent (defaults to 0), the bubble gets `ToolStatus.SUCCESS` — wrong.
**Expected:** `status: "failed"` with missing/zero exitCode → `ToolStatus.ERROR`
**Actual:** `status: "failed"` with missing/zero exitCode → `ToolStatus.SUCCESS`
**Root cause:** Error determination ignores the `status` field.
**Fix:** Change the status line to: `status=ToolStatus.ERROR if (exit_code != 0 or data.get("status") == "failed") else ToolStatus.SUCCESS`
**Pattern:** missing-field-check
**Tests:** Add a test case with `"status": "failed"` and no `exitCode` field, assert `bubble.status == ToolStatus.ERROR`.

## What to do

1. Fix both bugs in `ui/handlers/activity_handler.py`
2. Add the 2 edge-case tests to `tests/test_activity_bubbles.py`
3. Run full suite and report COMPLETENESS checklist
