# Post-Mortem — Settings button moved to left of toolbar

**Date:** 2026-06-09
**Supervisor:** qaster (implementationSupervisor)
**Builder:** QTR (steelFramedCodeWriter)
**Scope:** 1 file, 1 focused change (move `⚙ Settings` from right cluster to left cluster, immediately right of Stream toggle).

## Outcome

✅ Complete. Tests pass. No bugs found in builder's code.

## What changed

| File | Lines | Purpose |
|------|-------|---------|
| `ui/toolbar.py` | +9 / -5 | Added `left_box` cluster for `[Stream | Settings]`, removed settings from `right_box`, updated assembly order. Also: refreshed stale class docstring (supervisor fix). |
| `docs/ARCHITECTURE.md` | +6 / -4 | §3.4 updated: new layout diagram, expanded public API to include `on_settings_clicked` and `set_settings_status`, "offline" added to the `update_connection_state` states list. |
| `docs/specs/SETTINGS-BTN-LEFT-INSTRUCTIONS.md` | +151 | New spec file (single-deliverable; pre-existed as a planning artifact, persisted for audit trail). |

## Verification evidence

- **Imports ok:** `python3 -c "from ui.toolbar import Toolbar; print('ok')"` → `ok`
- **Instance attributes preserved:** All five (`_stream_btn`, `_settings_btn`, `_status_dot`, `_connect_btn`, `_status_label`) still on constructed Toolbar.
- **Old pattern gone:** `grep -c "right_box.append(overlay)" ui/toolbar.py` → `0`
- **Public API unchanged:** Constructor `__init__(on_connect_clicked, *, on_settings_clicked)`, `update_connection_state(state)`, `set_settings_status(has_verified_provider)` all present with same signatures.
- **`tests/test_toolbar.py`:** 11/11 pass without modification.
- **Full suite:** 1372 passed, 1 failed (pre-existing — verified on unmodified `main` via `git stash`).

## Code quality grade

**A−.** Tight, surgical diff. QTR followed the spec exactly: built `left_box`, removed `right_box.append(overlay)`, swapped the three `self.append()` lines. No collateral edits, no reformatting, no renamed variables. The only nit was stale documentation, which the supervisor fixed in two `edit` calls.

## What's good

- One file, one focused change, no scope creep. Exactly the pattern the supervisor prompt §8 recommends.
- Diff is minimal (8+/4− before the doc fix): just the three lines that mattered plus a 4-line `left_box` block.
- Public API preserved. Tests untouched. No regressions.
- The red-dot overlay mechanism is unchanged, so `set_settings_status()` continues to work.

## What's bad

- The class docstring on `Toolbar` was already stale before this change (it didn't mention Stream either — Stream was added earlier without a doc update). The supervisor's audit caught it. This is a recurring pattern: widgets get added to the toolbar without touching its docstring. Future work on the toolbar should treat the docstring as part of the change.
- `ARCHITECTURE.md` §3.4 had drifted in the same way. Section 0 of that file literally says *"If you don't [update it], it becomes a lie"* — and the lie was there before this work. Not a new failure, but visible.

## Bugs found during audit

| # | Severity | Where | Who found | Status |
|---|----------|-------|-----------|--------|
| 1 | LOW (docs only) | `ui/toolbar.py` class docstring (line 14) — said "Currently: Connect button (right-justified) with status label", missing Stream and Settings | Supervisor (adversarialDebugger §10) | Fixed by supervisor — class docstring now describes the new layout |
| 2 | LOW (docs only) | `docs/ARCHITECTURE.md` §3.4 — same drift, also missing `on_settings_clicked` and `set_settings_status` from the documented public API, and missing `"offline"` from the `update_connection_state` states list | Supervisor (adversarialDebugger §10) | Fixed by supervisor — section now matches reality |

Per supervisor §6, these were fixed by the supervisor (1-2 line docstring/doc updates), not sent back to the builder.

## Pre-existing test failure (attribution)

`tests/test_connection_sync_handler.py::TestActivityHandlerWiring::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer` fails on this work's branch **and** on unmodified `main` (verified via `git stash`). The error is:

```
Expected: set_on_activity_bubble(<MagicMock ...>)
Actual: set_on_activity_bubble(<function ConnectionSyncHandler.sync.<locals>._bubble_to_row>)
```

A mock-truthiness / type-confusion issue in the wiring test — has nothing to do with the toolbar. Logged here per the supervisor verification checklist; not in scope for this work.

## Successes

- **Spec-first delegation.** Writing the spec to disk first (§9.6 of the supervisor prompt) let the `/ask` payload stay short (one line, no truncation risk) and let QTR see the full plan including verification commands and the **COMPLETENESS block requirement.
- **QTR followed the steelFramedCodeWriter prompt.** The diff shows the right shape: a hard-part-first implementation, no collateral edits, verification at the end.
- **Adversarial audit caught the doc drift** before commit. Without the audit, this would have shipped as a code change with a lying docstring — exactly the failure mode ARCHITECTURE.md §0 warns about.

## Failures in the process

- **First `/ask` was multi-line in the message body and got dropped.** QTR reported "your message got cut off" and asked for clarification. Fix: re-sent as a single physical line (the slashes, command, mention, and payload all on one line, with embedded `\n` if needed). The supervisor prompt's §9.3 and §9.4 hint at this — `/ask` is a single-line slash command. Lesson: paste the entire `/ask` line as one literal line; do not break it across paragraphs in the assistant's response.

## Lessons

1. **`/ask` is single-line.** The current channel renders multi-line content, but the CLI's `/ask` parser is line-based. The full command must be on one physical line.
2. **Spec files should be persisted alongside the work, not just used as the delegation payload.** The spec file `SETTINGS-BTN-LEFT-INSTRUCTIONS.md` is now in `docs/specs/`, which makes it discoverable to the next person who wonders "why is the settings button on the left?" — same rationale as the `PHASE-N-INSTRUCTIONS.md` files.
3. **The docstring audit is a cheap insurance policy.** Two `edit` calls caught two stale docs and cost less than a builder round-trip.
4. **Stale docs on `Toolbar` are a recurring pattern.** When the next widget gets added to the toolbar, treat the class docstring as a required edit (same commit, same diff).

## Commits

- `e660041` (already on `main`): the just-merged Phase C + phase 9 work. Unrelated.
- This work has not yet been committed. Plan: one commit with the toolbar layout change + the doc fixes + the spec file.
