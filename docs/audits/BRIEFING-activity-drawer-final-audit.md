# Debugger Final Audit Briefing — Round 3 Bugfixes

## Context
This is the FOURTH and intended-final audit pass on the activity drawer feature. Round 3 fixed BUG #18, #17, #19, #20. Your job: verify the 4 fixes are correct AND do a final sweep for any surviving issues. If you find nothing new, say so explicitly — this is the ship gate.

## Files changed in Round 3
1. `ui/handlers/agent_runtime_handler.py` — 3 fixes (BUG #18 revert, BUG #17 1-liner, BUG #20 docstring).
2. `tests/test_agent_runtime.py` — 2 new regression tests (now 18 in the class).
3. `docs/ARCHITECTURE.md` — BUG #19 section move + renumber.

## Round 3 fixes (verify FIXED, do not re-report)
- **BUG #18**: reverted `_do_tool_call_start` (lines 1003–1011) to pure suppress-and-return (NO `_ended_sessions.discard` inside the suppression block). This restores the Round 1 behavior: ALL stale calls are suppressed; the flag is cleared only by `_do_text_delta` (line 973) when a new streaming turn begins. The two-set `_started_turn_sessions` design was PROPOSED in the spec but then CANCELLED mid-spec because it's fundamentally ambiguous (cannot distinguish stale calls from new-turn calls at the site). Confirmed: `grep _started_turn_sessions` returns zero matches.
- **BUG #17**: line 1136 `card_success = True` → `card_success = success`. The feed-card `else` branch now reads the runtime-dispatched param, so denied tools show "error" on the card (agreeing with the bubble's `tool_error`).
- **BUG #19**: ARCHITECTURE.md §3.21zc moved after §3.21zb and renumbered §3.21zd. Section order is now za → zb → zd.
- **BUG #20**: line 578 docstring `connection_sync_handler.py` → `activity_wiring_handler.py`.

## Known limitations / out of scope (do NOT re-report — these are accepted tradeoffs)
- **BUG #14 tradeoff:** a tool-only turn (no streaming text) whose first `_do_tool_call_start` arrives before any text delta will be suppressed. This is the documented, accepted tradeoff of the BUG #18 revert. We cannot distinguish "stale call from previous turn" from "first call of new tool-only turn" at the call site, and suppressing a legitimate first bubble is less harmful than emitting an orphan. The second-and-later tool_starts of a streaming turn fire normally after `_do_text_delta` clears the flag.
- **The two false-negative tests** from Round 1 (`test_denied_exec_command_emits_tool_error_bubble`, `test_sensitive_path_block_emits_tool_error_bubble`) still bypass the feed-card block. They're now redundant with the Round 2/3 card-primed tests but not harmful.

## Final-audit focus areas (hunt hard — this is the ship gate)

1. **BUG #18 revert completeness.** Confirm the suppression block at lines 1003–1011 contains NO `_ended_sessions.discard()`. Confirm line 973 (`_do_text_delta`) is the ONLY discard site. Confirm no `_started_turn_sessions` anywhere. Trace: single stale call → suppressed (correct); two stale calls → both suppressed (correct); streaming new turn → delta clears flag → tool_starts fire (correct).

2. **BUG #17 correctness across all result types.** Trace `card_success = success` for: (a) ToolResult success, (b) ToolResult failure, (c) string success ("OK..."), (d) string failure ("denied"). Does the card status agree with the bubble type in all four cases? Is there any result type where `success` (the param) disagrees with the actual outcome?

3. **The BUG #14 limitation — is it truly acceptable?** Think adversarially: is there a realistic agent workflow where the first tool_start of EVERY turn is suppressed (because the agent never streams text before calling tools)? If so, the drawer would show lifecycle separators with zero tool bubbles for that agent. How likely is this in practice? (Consider: does the runtime ALWAYS send a text delta before the first tool call, or can an LLM respond with a pure tool-call?)

4. **Test quality of the 2 new Round 3 tests.** Does `test_two_consecutive_stale_tool_starts_both_suppressed` actually fail if the BUG #18 revert is undone (i.e., if the discard is re-added)? Does `test_denied_exec_card_shows_error_status` fail if `card_success = success` is reverted to `card_success = True`? Mental-revert each and confirm the tests catch the regression.

5. **Whole-feature integrity sweep.** This is the ship gate. Step back and look at the complete data flow: runtime dispatch → handler → wiring handler → drawer. Are there any OTHER places where the card and bubble could disagree? Any other stale-state leaks? Any other paths where a cancelled/error turn could produce orphan bubbles? This is your last chance to catch anything before ship.

6. **ARCHITECTURE.md final accuracy.** Read the moved §3.21zd section. Does it accurately describe the current code? Are all references (constructor deps, public API, dedup invariant, extracted-from note) correct? Any remaining stale references to Round 0/1/2 behavior anywhere in the doc?

## Output
Use the BUG #[N] format from prompts/adversarialDebugger.md. **If you find NO new bugs, state explicitly: "No new bugs found. The 4 Round 3 fixes are correct and the feature is ship-ready."** Do not manufacture issues to justify the audit — if it's clean, say so. Be exhaustive on focus areas #2 and #5.
