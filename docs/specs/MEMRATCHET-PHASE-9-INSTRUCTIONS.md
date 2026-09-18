# PHASE 9 of 13 — Ticker churn: feedbar markup de-dup + elapsed bucket 1.0 s

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.4 + §2.7 row 6
(`activity_handler.py` `:812-813` comment).
**Files to change:** `ui/views/feedbar.py`, `ui/handlers/activity_handler.py`,
`tests/` (see below).

## Edits — `ui/views/feedbar.py`

1. In `__init__` (~`:28-35`): add `self._last_status_markup: str | None = None`.
2. In `set_status_text` (~`:67-69`): short-circuit identical writes — if the incoming
   markup equals `_last_status_markup`, return without calling `set_markup`; else store
   and render. The acceptance criterion calls `set_status_text` with *identical markup*
   reaching `set_markup` once — read it carefully: the FIRST write must reach
   `set_markup` (from None), only a REPEAT is skipped. Resetting (e.g. a new
   status family) must always render — dedupe is value-based, not family-based, so
   keep it simple: compare exact strings only.

## Edits — `ui/handlers/activity_handler.py`

3. Widen the elapsed bucket `0.5 → 1.0` in `_live_update`'s skip-when-unchanged
   signature (~`:812-814`): `int((time.monotonic() - ...) / 1.0)` — and update the
   adjacent comment (`:812-813`) which says "0.5s granularity — labels update at most
   twice per second": new text must say 1.0 s granularity, at most once per second.
4. Nothing else in the ticker. `_status_tick`'s state branches are untouched.

## Edits — `tests/`

5. **§6 criterion (F12) tests** — find where feedbar is tested (likely
   `tests/test_feedbar.py` or inside `test_activity_handler.py`; locate it). Add:
   - identical markup twice → `set_markup` called **once**;
   - different markup → called again;
   - with state/phase/hop constant, two ticks inside the same 1 s bucket → at most one
     markup build; ticks crossing a bucket boundary → re-render (drive `time.monotonic`
     or the bucket seam directly per the file's existing mocking pattern).
6. Run the existing activity-handler suite and note any test that depended on the 0.5 s
   bucket — update with justification if so (list under deviations).

## Rules

- steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Red-before-green via detached worktree (remove the short-circuit / revert the bucket →
  the new tests must fail).
- Related bugs: flag, don't fix.

## Verification (run and paste verbatim, exact suite lists per count)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_uirsp3_phase2.py -q 2>&1 | tail -2
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_bubble_batching.py -q 2>&1 | tail -2
grep -n "_last_status_markup\|/ 1.0" ui/views/feedbar.py ui/handlers/activity_handler.py
```

(Note: `tests/test_feedbar.py` does not exist — the feedbar/ticker suite is
`tests/test_uirsp3_phase2.py`; pytest given a nonexistent path silently collects
nothing rather than failing.)

(If either test file lives elsewhere, state the actual path and adjust the command.)

## Report back

Files/counts, hunks, test names + results, red-check, tails, deviations, COMPLETENESS:

COMPLETENESS:
- [x/not done] `_last_status_markup` init + short-circuit (first write renders) — evidence
- [x/not done] Bucket 0.5 → 1.0 + comment rewritten — evidence
- [x/not done] F12 tests (dedupe-once, change-renders, bucket-boundary) — names + results
- [x/not done] Red-before-green — evidence
- [x/not done] Existing suites green (exact lists) — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
