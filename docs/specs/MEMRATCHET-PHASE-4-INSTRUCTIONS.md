# PHASE 4 of 13 — Ordering invariant: `_project_cards` newest-first by `seq_num`

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.1 "Prerequisite — restore the
ordering invariant (F1)" — the replacement code block there is **verbatim-mandatory**.
**Files to change:** exactly two: `ui/handlers/feed_handler.py`,
`tests/test_feed_handler.py`.

## Context

Today the load path indexes cards by **chronological append** (the loop in
`_load_and_render`, ~`:1636-1640`) while `add_card` inserts at index 0 (`:784`). After
any project open, `_project_cards[proj]` is therefore oldest-first — contradicting
`get_cards_for_project`'s documented "newest first" contract (`~:1504-1508`) and making
the batch bar / Accept All miss cards placed last (they `break` at the first
non-actionable card). `seq_num` (back-filled on load, `:1600-1612`) is the only correct
ordering key.

`prev` can hold ids from two sources — (1) live arrivals during the parse window
(NEWER than the snapshot) and (2) ids the feed pruned at compaction (OLDER) — the spec's
comment block (verbatim in the replacement) explains why concatenating leftovers in
front promotes pruned ids to "newest", which Accept All would then act on.

## Edit 1 — `ui/handlers/feed_handler.py`

Replace the indexing block in `_load_and_render` with the spec §2.1 replacement code
**verbatim**, including the full comment block. It: indexes all cards into `_cards`,
merges `prev + new_ids` via `dict.fromkeys`, filters `cid in self._cards`, and sorts by
`self._cards[cid].seq_num or 0` descending. Do not "simplify" the comment; it documents
the round-7 premise correction for future readers.

Scope guard: do NOT touch `_backlog` writes, locking, widget construction, or anything
else in the loader this phase. Ordering only.

## Edit 2 — regression tests (`tests/test_feed_handler.py`)

Follow the existing load-path test patterns (search for tests driving `on_project_opened`
/ `_load_and_render` with the MockGLib + background-thread pattern; mirror their setup).
Three new tests:

1. `test_get_cards_for_project_newest_first_after_reopen` — load a project with several
   cards (distinct `seq_num`), then reopen the same project (second `on_project_opened`
   through the same path). Assert `get_cards_for_project` returns each id **exactly
   once**, newest-first by `seq_num` (spec §6 test-10; `dict.fromkeys` dedupe).
2. `test_load_live_arrival_lands_at_index_zero` — a card arriving (via `add_card`)
   between the snapshot parse and the merge has a higher `seq_num` than everything in
   the snapshot → after the load completes it sits at **index 0** (round-6 BUG #2).
3. `test_compacted_pruned_ids_stay_at_tail` — load a project; simulate compaction by
   removing the oldest cards' ids from `_cards` while they remain listed in
   `_project_cards` (`prev`); reopen with a fresh snapshot. Assert the list is still
   newest-first and the pruned (older) ids sort to the **tail**, never index 0
   (round-7 BUG #1: a pruned card must not become the first entry Accept All commits).

**Heads-up:** if any *existing* test asserts chronological (oldest-first) order after a
project open, that test encodes the bug being fixed — update it, and list every such
update under a "justified deviations" heading in your report with one-line rationale.

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Read the full `_load_and_render`, `get_cards_for_project`, `add_card`, and the
  existing load-path tests before editing. Identifier anchors.
- Related bugs: flag, don't fix. Spec drift >10 lines → flag in COMPLETENESS.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -k "cards_for_project or reopen or compacted_pruned or live_arrival" -q 2>&1 | tail -3
/usr/bin/python3 -m py_compile ui/handlers/feed_handler.py && echo COMPILE-OK
```

## Report back

Files changed with counts, the three test names + isolated runs, full-suite output,
deviations, and the mandatory COMPLETENESS checklist:

COMPLETENESS:
- [x/not done] Load-site block replaced verbatim (incl. comment) — evidence (paste diff hunk)
- [x/not done] Three regression tests, names + isolated results — evidence
- [x/not done] Existing-order assertions handled (updated + justified, or none found — state which search you ran)
- [x/not done] Scope guard respected (no _backlog/locking/eviction changes) — evidence
- [x/not done] Suite green under xvfb + /usr/bin/python3 — evidence (tail pasted)
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
