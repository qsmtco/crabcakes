# Debugger Final Audit (Sixth Pass) — BUG #22 Empty Bubble Fix

## Context
This is the sixth audit pass. BUG #22 (the last finding from the fifth pass — a cosmetic empty chat bubble on tool-only turns) has been fixed. This should be the final pass. If clean, the entire activity drawer feature (6 rounds of fixes) ships.

## File changed in this round
1. `ui/handlers/chat_render_handler.py` — `end_streaming` gained `render: bool = True` param; the `build_role_bubble` + append block inside `_finalize` is guarded by `if render:`.
2. `ui/handlers/agent_runtime_handler.py` — `_do_response_complete` reads `get_streaming_text` and passes `render=bool(streaming_text.strip())` to `end_streaming`.
3. `tests/test_agent_runtime.py` — 1 new regression test (now 20 in the class).

## BUG #22 fix (verify FIXED, do not re-report)
- `end_streaming(session_key, agent_name=None, render=True)`: when `render=False`, the method still cleans up (pops `_streaming_bubbles`, removes the streaming widget) but skips `build_role_bubble` + `sb.container.append`. Backward-compatible default `True`.
- `_do_response_complete` computes `streaming_text = get_streaming_text(sk) or ""` then calls `end_streaming(sk, agent_name=resolved_name, render=bool(streaming_text.strip()))`. Empty/whitespace text → `render=False` → no empty bubble.

## Final-ship-gate focus areas

1. **Backward compatibility of the `render` param.** Grep for ALL callers of `end_streaming` across the codebase. Do any of them break with the new param? Every existing caller that doesn't pass `render` gets the default `True` — confirm no caller relies on `end_streaming` NOT having a third positional arg (e.g., a test that asserts the exact call signature).

2. **The `render=False` cleanup path.** When `render=False`, does `end_streaming` still correctly: (a) pop the `_streaming_bubbles` entry, (b) remove the streaming widget from the container, (c) reset `_last_message_key`? Trace through `_finalize` with `render=False` — the cleanup lines are BEFORE the `if render:` guard, so they should run unconditionally. Confirm.

3. **Whitespace-only text suppression.** The fix uses `bool(streaming_text.strip())`. Is suppressing a whitespace-only bubble correct? Could a legitimate response be whitespace-only (e.g., a markdown-only response that renders to nothing in plain text but has formatting)? If so, this would suppress a real bubble. Assess likelihood.

4. **Interaction with the crabcard extraction path.** In `_do_response_complete`, the crabcard block (Phase C, before the `end_streaming` call) reads `get_streaming_text` and may call `set_streaming_text` with cleaned text. If the original text had crabcards but the cleaned text is empty, does `render=False` suppress a bubble that SHOULD show the non-crabcard content? Trace this edge case.

5. **Test quality.** Does `test_tool_only_turn_no_empty_chat_bubble` actually fail if the fix is reverted (Edit C removed so `end_streaming` is called without `render=`)? Mental-revert: without Edit C, `end_streaming` gets default `render=True` → `call_kwargs.get("render")` is `True` → assertion fails. Confirm.

6. **Whole-feature final sweep.** This is the last pass on a 6-round feature. Step back: is there ANY remaining defect in the activity drawer pipeline (runtime → handler → wiring handler → drawer)? Any orphan bubbles, stale state, card/bubble disagreements, empty artifacts? If the feature is clean, say so explicitly.

## Output
Use the BUG #[N] format from prompts/adversarialDebugger.md. **This is the final ship gate. If you find NO new bugs, state explicitly: "No new bugs found. BUG #22 is fixed and the activity drawer feature is ship-ready after 6 audit rounds."** Do not manufacture issues. But verify thoroughly — especially focus #1 (all callers of `end_streaming`) and #4 (crabcard interaction).
