# Debugger Re-Audit Briefing — Activity Drawer Bugfixes

## Context
Coder applied fixes for the 5 bugs + 2 known gaps you found in your first audit. This is a RE-AUDIT — verify the fixes are correct AND look for any new bugs introduced by the fixes themselves.

## Files changed in this round
1. `agent/runtime.py` — lines 2456, 2476, 2557 now pass `success: bool` as 4th arg to `_on_tool_call_result`.
2. `ui/handlers/agent_runtime_handler.py` — `_on_tool_call_result`/`_do_tool_call_result` signatures gained `success: bool = True`; `is_error = not success`; `_ended_sessions` set; `_pending_tool_args.pop` made unconditional; write_file tool_end suppressed (patch only); bubble emissions moved outside the project guard.
3. `tests/test_agent_runtime.py` — new `TestLocalAgentDrawerEmissions` class, 14 tests.

## Original bugs (verify FIXED, don't re-report)
- BUG #1: is_error always False → now `not success`
- BUG #2: orphan tool_start after cancel → `_ended_sessions` guard
- BUG #5: _pending_tool_args leak → unconditional pop
- BUG #4: empty-project lifecycle-without-events → bubbles outside project guard
- BUG #12: write_file double-count → tool_end suppressed for write_file success

## Known gap (do NOT re-report)
- ARCHITECTURE.md not yet updated (PM has this queued as separate follow-up).

## Re-audit focus areas (NEW — look hard here)

1. **`_ended_sessions` lifecycle correctness.** It's `discard`ed in `_do_text_delta` (agent-start) and `add`ed in both end sites. What if an agent does multiple turns without a cancel? Trace: turn1 start (discard) → tools → turn1 end (add) → turn2 start (discard) → tools → turn2 end (add). Does the discard at turn2-start correctly clear the turn1-end flag so turn2's tools fire? What if `_do_text_delta` is never called (no streaming, e.g. a tool-only turn)? Could `_ended_sessions` retain a stale entry that suppresses a legitimate next-turn tool?

2. **`success` param backward-compat.** The signature default is `success: bool = True`. The feed-card block at line ~1113 still has its OWN `success = result.success` / `success = True` reassignment that SHADOWS the param. Does the feed-card path's shadowing clobber the param for the bubble path? Trace the variable scope: the feed-card block reassigns `success`, then the bubble block at ~1158 reads `success`. Is it reading the param or the shadowed value? THIS IS A SUSPECTED REGRESSION.

3. **write_file failure path.** BUG #12 fix suppresses tool_end only for `write_file and not is_error`. For a FAILED write_file: tool_error fires (good) BUT does the patch bubble also fire? Trace: `write_file_success` guard at ~1199 checks `result.startswith("OK")`. A failed write_file result won't start with "OK" → patch skipped. Confirm no patch-on-failure. But also: does the failed write_file's tool_error bubble carry the right `tool_name`?

4. **`_pending_exec_commands` interaction.** The exec_command command capture (`_pending_exec_commands[session_key] = cmd`) is INSIDE the project guard (line ~1031). After BUG #4 moved bubbles outside the guard, does the command_output callback in `_do_tool_call_result` still find its command? If no project is open, `_pending_exec_commands` is never populated → `cmd = ""` → the empty-row bug (your original BUG #11) may now be MORE frequent since exec_command works without a project but command capture doesn't.

5. **Test quality of the 14 new tests.** Do they use real `AgentRuntimeHandler` instances or heavy mocking? Do they actually invoke `_do_tool_call_result` with a realistic `success=False` to prove BUG #1 is fixed, or do they mock the bubble callback and assert it was called (which proves wiring, not correctness)?

6. **The `success` shadowing in the feed-card block — trace this very carefully.** This is the highest-risk regression. If the feed-card block runs and reassigns `success`, the bubble block reads the wrong value.
