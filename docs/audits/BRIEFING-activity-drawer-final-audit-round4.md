# Debugger Final Audit (Fifth Pass) — Round 4 Turn-Start Signal

## Context
This is the FIFTH audit pass and the intended-final ship gate. Round 4 fixed BUG #21 (the ship blocker you found last round) by dispatching `_on_text_delta(session_key, "")` at the top of `_run_loop`, guaranteeing a turn-start signal for every turn regardless of event types. Your job: verify the fix is correct and do the final whole-feature integrity sweep. If clean, say so explicitly — this is the ship gate.

## File changed in Round 4
1. `agent/runtime.py` — 1 dispatch line + comment block in `_run_loop` (line ~2118), after the `conv` null-check, before the `try:` block.
2. `tests/test_agent_runtime.py` — 1 new regression test (now 19 in the class).

## Round 4 fix (verify FIXED, do not re-report)
- **BUG #21**: `_run_loop` now dispatches `_on_text_delta(session_key, "")` before any LLM call or tool processing, gated on `if self._on_text_delta:`. For a tool-only turn (zero text_delta events), this empty delta reaches `_do_text_delta` → clears `_ended_sessions` (line 973) → subsequent `_do_tool_call_start` calls see a clear flag → tool_starts fire. Test `test_tool_only_turn_tool_starts_not_suppressed` exercises this at the handler level.

## Accepted tradeoffs / out of scope (do NOT re-report)
- **BUG #14 limitation still stands:** the first tool_start of a tool-only turn is no longer suppressed (BUG #21 fix resolves that), but the underlying design — `_do_text_delta` is the flag-clear site — is unchanged. This is now correct because `_run_loop` guarantees the empty delta fires for every turn.
- The two false-negative tests from Round 1 (no-card path) remain; they're redundant but harmless.

## Final-ship-gate focus areas (be exhaustive — this is the last pass)

1. **BUG #21 fix correctness across all turn types.** Trace the empty-delta dispatch for: (a) normal text turn (empty delta then real deltas — does the empty one cause any visual artifact like an empty bubble that persists?), (b) tool-only turn (the fix case — does the empty streaming bubble started by the empty delta get correctly finalized at turn end?), (c) cancelled-before-LLM turn (empty delta fires, then cancel — is the flag state correct?), (d) non-streaming mode (`_on_text_delta is None` — dispatch skipped, correct?).

2. **Empty-streaming-bubble lifecycle.** The empty delta starts a streaming bubble (via `_crh.start_streaming`). For a tool-only turn, this bubble never receives content. Trace what happens at `_do_response_complete`: does `end_streaming` finalize an empty bubble cleanly? Is there any visual artifact (an empty agent bubble in the chat)? Is `was_streaming` True (because the empty delta started it) and does the crabcard-extraction path (line 1402 `full_text = ... or ""`) handle the empty string?

3. **Thread safety.** The empty-delta dispatch fires from `_run_loop` (background thread) via `_dispatch` → `GLib.idle_add`. The handler's `_do_text_delta` runs on the main thread. Is there any race where the empty delta's flag-clear and a concurrent cancel's flag-set could interleave incorrectly? (Note: both go through idle_add, so they're serialized on the main loop — but verify.)

4. **Does the fix work for BOTH streaming and non-streaming providers?** `_on_text_delta` is only set when streaming is enabled (runtime `__init__`). For a non-streaming provider, `_on_text_delta is None`, so the dispatch is skipped. Does the drawer still work for non-streaming local agents? Or does the flag never clear in non-streaming mode? (This may be a pre-existing limitation, not a Round 4 regression — but flag it either way.)

5. **Whole-feature integrity — the complete state machine.** You've now audited this state machine across 5 rounds. Step back and trace the COMPLETE lifecycle of `_ended_sessions` from cold start through multiple turns: cold start → turn 1 (text) → turn 1 end → turn 2 (tool-only) → turn 2 end → turn 3 (text) → cancel mid-turn-3 → turn 4. At every step, is the flag in the correct state? Are there any residual orphans, leaks, or suppressions?

6. **Test quality.** Does `test_tool_only_turn_tool_starts_not_suppressed` actually fail if the Round 4 dispatch line is removed? Mental-revert: without the dispatch, `_do_text_delta` is never called, the flag stays set, the tool_start is suppressed → assertion fails. Confirm the test catches the regression.

## Output
Use the BUG #[N] format from prompts/adversarialDebugger.md. **This is the ship gate. If you find NO new bugs, state explicitly: "No new bugs found. BUG #21 is fixed and the activity drawer feature is ship-ready."** Do not manufacture issues. But also do not rubber-stamp — if there's a real concern (especially focus #2 empty-bubble lifecycle and #4 non-streaming mode), report it.
