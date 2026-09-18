# PHASE 8 of 13 — Seam extension: file-event + task bodies (§2.3) + the 3 feed_card §2.7 rows

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.3 (whole section) + §2.7 rows
1-3 (`feed_card.py` comment rewrites) + §2.6 last block (`tests/test_feed_card.py`).
**Files to change:** `ui/views/feed_card.py`, `tests/test_feed_card.py`.

## Edits — `ui/views/feed_card.py`

1. In `_render_file_event_body`, after the `_set_body_text(box, desc_label, …)` call
   (~`:340-343`), add `box._text_label = desc_label`.
2. In `_render_task_body`, after `_set_body_text(box, body_label, card_data.body)`
   (~`:375`), add `box._text_label = body_label`.
3. Rewrite the now-stale comments (§2.7 rows 1-3):
   - `:337-339` — currently says file-event cards have no single body seam; new text:
     the seam is exposed when a non-empty body exists at build time; an empty-body
     card still falls back to rebuild.
   - `:561-564` — the seam comment claiming `None for … file events, task cards`;
     correct it the same way.
   - `:871-873` — `update_card_in_place`'s docstring says the seam is "set by
     build_feed_card **for text bodies**"; correct: the body renderers set
     `_text_label` whenever a non-empty body exists at build time (status, chat,
     file-event, task); empty-body cards yield no seam → rebuild fallback.
4. No change to `build_feed_card` itself — the read side is
   `getattr(body_widget, "_text_label", None)` (~`:565`) and needs none.
5. Grep-verify no OTHER `_render_*_body` returns a body box without the seam when a
   non-empty body exists — if one does, flag it (do not fix; that would be a §2.3
   scope expansion beyond the spec's named two).

## Edits — `tests/test_feed_card.py`

Per §2.6: file-event card with a non-empty body and task card with a non-empty body
take the in-place path (`update_card_in_place` returns True, no rebuild — assert the
returned widget is the SAME object, and the label text updated); empty-body variants
still return False. Mirror the existing test patterns in that file.

## Rules

- steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Red-before-green via detached worktree (revert the two assignments → the new True-path
  tests must fail).
- Related bugs: flag, don't fix. Spec drift >10 lines → flag.

## Verification (run and paste verbatim, exact suite lists per count)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_card.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -2
grep -n "_text_label" ui/views/feed_card.py
```

## Report back

Files/counts, the two assignment hunks + three comment rewrites, test names + isolated
results, red-check, tails, the seam-coverage grep result, deviations, and COMPLETENESS:

COMPLETENESS:
- [x/not done] Both seam assignments placed after the named _set_body_text calls — evidence
- [x/not done] Three §2.7 comment rewrites — evidence (paste before/after)
- [x/not done] Tests: file-event True-path, task True-path, empty-body False-paths — evidence
- [x/not done] Red-before-green — evidence
- [x/not done] Suites green — evidence
- [x/not done] Seam-coverage grep + related issues flagged — evidence

Please write — that phrase is the marker.
