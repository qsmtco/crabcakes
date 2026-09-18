# PHASE 7a of 13 — `_backlog` discipline: locking, loader merge, narrowed loader lock

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.1 — "Also lock the other
`_backlog` writers", "The loader must merge, not rebind — survivors first" (verbatim
code block), "Narrow the loader's lock region", "One rule for `_card_widgets`, stated
once". Plus the two audit-deferred items: eviction's unlocked `len(self._backlog)`
label read, and `_load_more`'s unlocked widget store (`:1841` region) + unlocked
`_backlog` page-slice.
**Files to change:** `ui/handlers/feed_handler.py`, `tests/test_feed_handler.py`.

## Edits — `ui/handlers/feed_handler.py`

1. **`_load_and_render` rebind → merge (round-4 BUG #3 / round-5 BUG #2).** Replace
   `self._backlog = list(reversed(backlog))` with the spec's verbatim block:
   `new_backlog = list(reversed(backlog))`, dedupe on card_id, then **under `_lock`**:
   `pushed = [c for c in self._backlog if c.card_id not in seen]`;
   `self._backlog = pushed + new_backlog`. Survivors **first** (they are the newest —
   eviction pushed them; see the spec's order-matters paragraph). Include the spec's
   comment if present in the fence.
2. **Narrow the loader's lock region (round-3 BUG #8).** `build_feed_card(...)` moves
   **outside** `self._lock`; the lock holds only the dict writes (`_cards`,
   `_card_widgets`). Per "One rule for `_card_widgets`": the map assignment itself
   stays inside the lock — only the expensive construction leaves it.
3. **Lock the remaining `_backlog` writers:** the `_load_more` page-slice
   (`if not self._backlog: return` → read `page = self._backlog[:PAGE_SIZE]` and the
   reassign `self._backlog = self._backlog[PAGE_SIZE:]` — compute the new list under
   the lock; keep the empty-check + remaining count consistent with it), the two
   clears (`clear_project` ~`:1557`, `on_project_closed` ~`:1708`), and the eviction
   insert if not already (it is — verify).
4. **Eviction's label read under lock:** the `len(self._backlog)` read feeding
   `_build_load_more_widget(...)` (P5 audit finding — benign TOCTOU, close it while
   the region is being touched). Minimal: read the count inside the existing locked
   region where `_backlog.insert` happens, pass it to the rebuild.
5. **`_load_more`'s widget store under `_lock`** (`self._card_widgets[data.card_id] =
   widget` inside the build loop region — F8). Build stays outside; the store goes in.
6. Do NOT touch: `update_card` (P7b), any view file, the eviction method's verbatim
   body beyond the minimal label-read change in (4) — if (4) cannot be done without
   editing the verbatim 86 lines, STOP and report instead (spec-fence changes need my
   sign-off).

## Edits — `tests/test_feed_handler.py`

1. **Merge-order test:** seed `_backlog` with a pushed (newer, evicted) card; run the
   loader with a snapshot backlog of older cards; assert the merged list is
   `[pushed_newest..., older_backlog...]` (survivors first) and contains no
   duplicates.
2. **No-loss test (round-2 BUG #3's failure mode):** eviction insert happens during
   the loader's parse (simulate: mutate `_backlog` inside a patched `feed_store.load_feed`
   before it returns) → after the load completes, the pushed card is STILL in
   `_backlog` (a plain rebind would discard it).
3. **Load More label consistency after merge:** after (2), the rebuilt sentinel (if
   any) reports the merged count.
4. Existing suite must stay green — the merge and lock changes are behavior-preserving
   for single-threaded tests.

## Rules

- steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Red-before-green via detached worktree (neuter the merge → test 2 red; narrow the
  lock → all green, so no red claim needed for (2), state that explicitly).
- Related bugs: flag, don't fix. Spec drift >10 lines → flag.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -k "backlog or merge or loader" -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_body_cap.py tests/test_feed_snapshot_off_thread.py tests/test_review_handler_feed_card.py -q 2>&1 | tail -1
```

## Report back

Files/counts, verbatim-block identity output for the merge fence, each test + result,
red-check output, tails, deviations, and COMPLETENESS:

COMPLETENESS:
- [x/not done] Merge (survivors first, dedupe, under lock) — evidence + identity check
- [x/not done] Loader lock narrowed (build outside, map write inside) — evidence
- [x/not done] `_backlog` writers locked (slice, two clears, label read) — evidence
- [x/not done] `_load_more` widget store under lock — evidence
- [x/not done] Merge-order + no-loss + label tests — names + results
- [x/not done] Suites green — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
