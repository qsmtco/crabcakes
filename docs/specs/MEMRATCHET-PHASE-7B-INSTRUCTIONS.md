# PHASE 7b of 13 — Evicted-card guard + debug instrument + the `_backlog` comment

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.1 ("Evicted-card guard",
"Debug instrument") + §2.6 test 6 + §2.7 (the `:122-124` comment row).
**Files to change:** `ui/handlers/feed_handler.py`, `tests/test_feed_handler.py`.

## Edits — `ui/handlers/feed_handler.py`

1. **Evicted-card guard** in `update_card`, immediately after the persistence block
   (~`:1045-1065`), **reusing the `old_widget` already bound at ~`:1032`** — the spec
   gives the code verbatim:

   ```python
        if old_widget is None:
            # Evicted (§2.1). Data was updated and persisted above; the widget is
            # rebuilt from data if the card is rendered again. Rebuilding here
            # would re-append an old card at the bottom of the feed.
            return
   ```

   After adding it, the `old_widget is None` branch of `_rebuild_and_replace_card`
   becomes unreachable — per spec, the `else: append_card` branch inside `_replace`
   may be deleted and the function docstring updated. Keep the deletion minimal and
   note it in your report.
2. **Debug instrument** after the new widget is stored at ~`:1126-1127` (i.e. in
   `_rebuild_and_replace_card`'s replace path), exactly:

   ```python
        if os.environ.get("CRABCAKES_DEBUG"):
            _logger.info("feed card rebuilt (no seam): %s", card_id)
   ```

   (`os` is imported at `:12`; `_logger` exists at `:1025`/`:1060` — verify both
   anchors, flag if drifted.)
3. **§2.7 comment row** (~`:122-124`): rewrite the `_backlog` comment — it currently
   says "Populated by on_project_opened() … Loaded in pages by `_load_more()`".
   New text must say: populated by `on_project_opened` (loader merge, survivors
   first), drained by `_load_more` (one page per click), and re-populated by eviction
   (evicted cards are pushed back newest-first so nothing becomes unreachable).
4. Do NOT touch: any view file, the seam (P8), `_load_more`/loader internals.

## Edits — `tests/test_feed_handler.py`

**§2.6 test 6:** `update_card` on an evicted card → no rebuild, no re-append, data
persisted. Setup: add a card (widget exists), over the cap with the guard permissive so
it evicts, then `update_card` with new body data. Assert: data + persisted payload
updated; the tab's card list does NOT grow; no `replace_card` call recorded;
`update_card` returns without touching widgets. If `update_card`'s persist path needs a
mock seam, mirror the existing test patterns for persist (search for how other
`update_card` tests stub the persist writer).

## Rules

- steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Red-before-green via detached worktree (neuter the guard → the test must show the
  rebuild/re-append happening).
- Related bugs: flag, don't fix.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -k "evicted or update" -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_body_cap.py tests/test_feed_snapshot_off_thread.py tests/test_review_handler_feed_card.py tests/test_architecture.py -q 2>&1 | tail -1
```

(Include exact suite lists with every count you report — the auditor probes
underivable counts.)

## Report back

Files/counts, the guard diff hunk, test name + isolated result, red-check output,
tails, deviations, and COMPLETENESS:

COMPLETENESS:
- [x/not done] Guard verbatim, after persistence, reusing old_widget — evidence
- [x/not done] Unreachable `_replace` branch deleted + docstring updated — evidence
- [x/not done] Debug instrument exact — evidence
- [x/not done] §2.7 comment rewritten (three populate/drain paths) — evidence (paste)
- [x/not done] Test 6 red-before-green — evidence
- [x/not done] Suites green — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
