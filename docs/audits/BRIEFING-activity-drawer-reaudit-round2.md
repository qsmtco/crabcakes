# Debugger Re-Re-Audit Briefing — Round 2 Bugfixes

## Context
This is the THIRD audit pass on the activity drawer feature. Round 1 found 5 bugs. Round 1 fixes introduced 3 regressions (BUG #13/#14/#15). Round 2 just fixed those 3 regressions. Your job: verify the 3 fixes are correct AND hunt for any NEW regressions or surviving issues.

## Files changed in Round 2
1. `ui/handlers/agent_runtime_handler.py` — 3 surgical fixes.
2. `tests/test_agent_runtime.py` — 2 new regression tests (now 16 in the class).
3. `docs/ARCHITECTURE.md` — doc update (5 edits).

## Round 2 fixes (verify FIXED, do not re-report)
- **BUG #13**: `success` param shadowing — renamed the feed-card locals to `card_success` (lines ~1122, 1127, 1136). The bubble path at line 1176 (`is_error = not success`) now reads the untouched param. Added 2 regression tests that prime `_tool_card_ids` + `_fh.get_card` so the feed-card block actually runs.
- **BUG #14**: `_ended_sessions` discard added inside the suppression `if` block at line ~1007, so tool-only turns clear the flag on their first (stale) call and subsequent calls fire.
- **BUG #15**: `_pending_exec_commands` capture moved from inside the project guard (old line 1027) to the unconditional block at line 1067.

## Already known / out of scope (do NOT re-report)
- The 2 false-negative tests from Round 1 (`test_denied_exec_command_emits_tool_error_bubble`, `test_sensitive_path_block_emits_tool_error_bubble`) — they still bypass the feed-card block, but the 2 NEW Round 2 tests now cover that path. Not a blocker.
- `_ended_sessions` design tradeoff: the first tool_start of a tool-only new turn is suppressed (treated as potentially stale). This is an acceptable ambiguity, documented in the spec. Don't report it as a bug.

## Re-re-audit focus areas (NEW — hunt hard here)

1. **The `card_success` rename — is it complete?** Grep the ENTIRE `_do_tool_call_result` function body for any remaining reference to `success` that should be `card_success`. Specifically check: the `card.metadata["status"]` line, and any other downstream read. Is there any place the feed-card block's `card_success` leaks where it shouldn't, or any place `success` (the param) is read by the feed-card block (which would now read the wrong thing)?

2. **The `card_success` rename — semantic correctness.** Before the rename, the feed-card block computed `success` from `result.success` (ToolResult) or defaulted to `True` (string). After the rename, `card_success` is computed identically. BUT: the `card.metadata["status"]` now uses `card_success`. Is that semantically right? For a denied exec_command (runtime passes `success=False`, result is a string), the feed-card block's `else` branch sets `card_success = True`, so the CARD shows "complete" even though the tool was denied. Is that a pre-existing issue or a new one? Trace whether the card status was correct before Round 1 (when `success` was computed from the result only, no param existed).

3. **BUG #14 discard placement.** The discard now lives INSIDE the suppression `if` block — meaning the stale call is suppressed AND the flag cleared. What if TWO stale calls are queued on the idle queue (e.g., two `_on_tool_call_start` dispatched before cancel)? Call 1: flag set → suppress + clear. Call 2: flag clear → proceeds → emits a tool_start bubble. Is that the desired behavior, or does call 2 produce an orphan? Trace the GLib.idle_add FIFO ordering with two queued starts + one cancel.

4. **BUG #15 unconditional capture — interaction with `_pending_exec_commands.pop`.** The capture now fires for EVERY exec_command (no project guard). The pop in `_do_tool_call_result` (line ~1148) also fires unconditionally. Is there any path where the capture fires but the pop doesn't (or vice versa), causing a stale entry or a KeyError? What if `_do_tool_call_start` runs for exec_command but `_do_tool_call_result` never runs (cancel mid-tool)?

5. **ARCHITECTURE.md accuracy.** Read the new §3.21zc section (or whatever slot Coder used). Does it accurately describe the handler? Does it match the actual code? Are the constructor deps, public API, and dedup invariant correctly documented? Any stale references to Round 0/1 behavior?

6. **Test quality of the 2 new regression tests.** Do they actually fail if the BUG #13 fix is reverted? (Mental test: if you rename `card_success` back to `success`, do these 2 tests fail?) If they'd still pass with the bug present, they're false negatives. Also: do they assert the RIGHT things (icon ❌, type tool_error, no patch)?

7. **Cross-cutting: any other variable in `_do_tool_call_result` that suffers the same shadowing pattern?** The function has `duration`, `output_text`, `error_text` locals in the feed-card block. Do any of those leak to downstream code that reads them outside the block? Specifically `duration_ms_bubble` in the bubble block — does it read a leaked local or compute fresh?

8. **The `write_file_success` guard at line ~1196.** It checks `isinstance(result, str) and result.startswith("OK")`. After BUG #13 fix, for a failed write_file (`success=False`), `is_error=True`, so `skip_tool_end=False`, so tool_error fires. But does the patch path also fire? `write_file_success` is False (result doesn't start with "OK"), so patch is skipped. Confirm no double-emit and no silent failure.

## Output
Use the BUG #[N] format from prompts/adversarialDebugger.md. If you find NO new bugs, say so explicitly with a summary of what you verified. Be exhaustive on focus areas #1, #3, and #6 — those are the highest-risk.
