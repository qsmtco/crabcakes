# Post-Mortem: Tier 1.2 — Wire ReviewHandler to Feed (feed-card-wiring)

**Date:** 2026-06-12
**Supervisor:** Qaster (Implementation Supervisor)
**Builder:** QTR (via `/ask @QTR` delegation from authorized CLI channel)
**Commit:** `56a6cee`
**Spec:** `SPEC-FEED-CARD-WIRING-FIX.md`

---

## What was built

ReviewHandler now emits `git_commit` feed cards when the user runs `/accept` or `/reject` in a project review session. Cards surface in the project feed with commit SHA, body output, and "Accepted:" or "Rejected:" title.

**Files changed:**
- `ui/handlers/review_handler.py` — +35 lines (ctor param, `_emit_feed_card` helper, two call sites)
- `ui/window.py` — +1 line (wiring `on_feed_card=self._feed_handler.add_card`)
- `tests/test_review_handler_feed_card.py` — new file, 202 lines, 9 tests across 4 classes

---

## Code Quality Grade: **A-**

### Why not A+
The implementation is clean, correct, and well-tested. The A- is for the spec error (see Failures below) and the fact that QTR had to self-correct the test file path without being told to.

---

## What's Good

1. **Spec-first approach paid off.** The master spec existed on disk before the phase instructions were written. QTR read both before touching code. Zero misalignment between what was asked and what was delivered.

2. **File-based delegation avoided truncation.** The 4,875-char payload was too large for `/ask` (4,096 limit). Writing to `TIER-1-2-FEED-CARD-WIRING-INSTRUCTIONS.md` and sending a 624-char one-liner meant QTR received the full implementation checklist without truncation.

3. **QTR's COMPLETENESS checklist was complete.** All 12 items checked, all with line-number evidence. Exactly what §3 of the supervisor prompt requires. No format skipping.

4. **QTR flagged related issues without fixing them.** Four genuine findings (no `test_review_handler.py`, `reject_file()` gap, `_send_rejection_messages()` error swallowing, duplicate `git_commit` card paths) — all correctly flagged as out-of-scope. This is the right behavior.

5. **End-to-end trace was accurate.** QTR traced the path from `/accept` slash command through 12 steps to the card appearing in the feed. The trace matched what the code actually does.

6. **Pattern mirroring was precise.** The `_emit_feed_card` helper at `review_handler.py:70-87` mirrors `task_handler.py:58-69` exactly — same structure, same null-check guard, same `FeedCardData` field population.

---

## What's Bad

1. **The spec said `tests/test_review_handler.py` existed.** It doesn't. Verification Step 3 told QTR to run `pytest tests/test_review_handler.py tests/test_feed_handler.py -v` but the file doesn't exist. QTR correctly worked around this and ran the right tests, but the supervisor should have verified the file existence before writing the spec.

2. **The "no existing tests broken" claim was slightly misleading.** QTR reported "68 passed" for Verification 3, but the actual correct command (given the non-existent file) was `pytest tests/ -k "review or feed_card"` which returned 72 passed. The number difference doesn't change the outcome (all pass), but the supervisor independently re-ran the correct command and confirmed.

3. **The working tree had 100+ deleted spec files.** These were pre-existing (from a prior session's spec cleanup) and showed as noise in `git status`. They didn't affect the commit, but they risked being bundled into QTR's commit if the supervisor hadn't checked. QTR correctly staged only the 3 expected files.

---

## Bugs Found During Audit

| # | Bug | Found by | Severity | Status |
|---|---|---|---|---|
| 1 | `tests/test_review_handler.py` doesn't exist (spec error) | QTR (Related Issues) + Supervisor (audit) | Low (spec wrong, not code) | Fixed: QTR worked around it; spec post-mortem notes the error |
| 2 | Pre-existing failure: `test_connection_sync_handler.py::TestActivityHandlerWiring::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer` | Supervisor (audit) | Low (unrelated to Tier 1.2) | Pre-existing; separate follow-up |
| 3 | `reject_file()` doesn't emit a feed card | QTR (Related Issues) | Low (out of scope) | Deferred to Tier 3 |
| 4 | `_send_rejection_messages()` swallows errors silently | QTR (Related Issues) | Low (pre-existing) | Deferred to follow-up |

---

## Successes and Failures in the Process

**Successes:**
- Option A (11-line fix) was the right call strategically. The Captain's instinct to reject the 52-line handler merge was correct. Scope stayed controlled.
- The implementation-supervisor system prompt (§9.6) correctly triggered the file-based delegation when the payload exceeded 4,096 chars. This prevented a truncation failure.
- Independent verification caught the pre-existing test failure and the spec error before accepting QTR's work.
- All 9 new tests pass, 72 existing tests pass, no regressions introduced.

**Failures:**
- The supervisor wrote a spec with a non-existent test file path. Should have run `ls tests/test_review_handler.py` before committing the spec.
- The 100+ deleted spec files in the working tree created noise that required manual filtering before committing.

---

## Lessons Learned

1. **Always verify file existence before referencing a file path in a spec.** One `ls` command would have caught the `tests/test_review_handler.py` error before the spec was committed.

2. **File-based delegation is not optional when the payload is large.** The implementation-supervisor prompt says this clearly. The moment the payload was 4,875 chars, writing to disk and sending a one-liner was the correct call — and it worked perfectly.

3. **QTR's "flag, don't fix" discipline on related issues is correct.** Four genuine findings, zero attempted fixes. The supervisor can decide what to escalate; the builder should not decide for themselves.

4. **Pre-existing failures must be confirmed with `git stash` before attributing.** Running the failing test on unmodified main took 30 seconds and definitively established the failure was pre-existing. Always verify before attributing.

5. **The end-to-end trace in QTR's report was the most valuable part.** It confirmed the 12-step path from slash command to card-in-feed actually works as designed. Every builder should be required to provide this.

---

## Open Follow-ups (Tier 3 candidate)

- `reject_file()` should also emit a `git_commit` card for consistency
- `test_review_handler.py` — handler-level unit tests for `cmd_accept`, `cmd_reject`, `start_review`, etc.
- `_send_rejection_messages()` error swallowing — add logging or error feedback
- Full handler unification (`feed_handler` + `review_handler` shared helper) — deferred from Tier 1.2

---

**Commit history for this change:**
- `56a6cee` — feat(review-handler): emit git_commit feed cards on accept/reject (Tier 1.2)
- `6d15f59` — docs: PROPOSAL-feed-card-wiring status PARTIAL → DONE (Tier 1.2 complete)