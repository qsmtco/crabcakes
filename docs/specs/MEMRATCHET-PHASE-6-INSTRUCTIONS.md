# PHASE 6 of 13 — Load path + Load More: call sites, sentinel cleanup, orphans, render source

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.1 (call-site table rows 3-4,
"Load-path sentinel cleanup", "Why the project-open path needs its own removal",
"Evicted cards must re-render from authoritative data") + §2.6 tests 8, 9, 11 + the
Xvfb mirror assertion and the orphan check (§6).
**Files to change:** `ui/handlers/feed_handler.py`, `tests/test_feed_handler.py`.

## Edits — `ui/handlers/feed_handler.py`

1. **Load path render loop** (`_load_and_render` / `_append_and_schedule_scroll`
   region): immediately before each `append_card` in the per-card render loop, add
   `self._feed_tab.remove_card(card_id)` (same-project reopen orphan de-dupe,
   round-7 BUG #2 — FeedTab.append_card overwrites the map but leaves the old widget
   parented). After all appends: `self._evict_surplus_card_widgets()`.
2. **`_load_more`**: eviction as the **FINAL statement of `_render`**, after the
   Load More re-add/clear block — NOT after the page-prepend loop (round-6 BUG #4:
   mid-render eviction would rebuild the sentinel from the post-push backlog, then the
   tail would build a second one from the stale `remaining`):
   `self._evict_surplus_card_widgets(exclude=frozenset(ids_just_loaded))` where
   `ids_just_loaded` is the set of `card_id`s built in this call. The exclusion is
   mandatory (round-3 BUG #1).
3. **Sentinel cleanup** (`_append_and_schedule_scroll`): hoist
   `self._feed_tab.remove_card("__load_more__")` out of the `if` unconditionally;
   `if load_more_widget is not None:` prepend; `else:` `self._load_more_widget = None`
   (round-6 BUG #3 — switching to a project with no backlog must clear the previous
   project's bar).
4. **Render from `_cards`** (`_load_more`, the `for card in page:` build loop):
   `data = self._cards.get(card.card_id, card)` and `build_feed_card(data, ...)`
   (round-4 BUG #1 — evicted cards re-render post-update). NOTE: deliberately NOT the
   redundant `_backlog` rewrite — spec §2.1 explicitly forbids adding it.
5. **`_project_seq` lock wraps (P5 audit BUG #1):** take `self._lock` around the
   `add_card` increment (~`:767-770`) and around the loader's
   `max(max_seq, get(project_name, 0))` read-modify-write assignment. Keep regions
   minimal (the dict write, not surrounding work).
6. Do NOT touch: the loader's widget-build lock region (P7), `_backlog` writers/merge
   (P7), `update_card` (P7b), any view file.

## Edits — `tests/test_feed_handler.py`

1. **Test 8 (page identity, §2.6):** ≥121 live widgets, then one `_load_more()` click
   with the guard permissive → every id in `ids_just_loaded` still in `_card_widgets`
   AND in the tab's card list; non-vacuity: ≥1 non-page card released.
2. **Test 9 (drained backlog):** backlog empty, `_load_more_widget is None`; an
   eviction that pushes cards back also rebuilds the Load More widget (assert the
   sentinel reappears in the tab).
3. **Test 11 (cross-project bound, §6):** cards added while a different project is
   `_active_project_name` are still eviction candidates.
4. **Sentinel tests (§6 rows):** (a) same-project reopen below the cap → exactly one
   `__load_more__` parented; (b) switch from a backlogged project to one with
   ≤ PAGE_SIZE cards → no `__load_more__` widget remains.
5. **Orphan check (§6, round-7 BUG #2):** reopen the same project twice; count the
   tab's non-card-container children excluding the empty-state and sentinel widgets →
   equals the number of distinct card ids in the tab map.
6. **Mirror assertion (§6, Xvfb class):** for every id in
   `_project_cards[active]` (excluding `__load_more__`), membership in
   `FeedTab._cards_by_id` equals membership in `_card_widgets` — run in the
   real-FeedTab class, **asserting non-vacuity first** (≥1 id left both maps in the
   same pass; drive the eviction with a fake widget whose compute_bounds succeeds, per
   the spec's warning that the unallocated-harness case is trivially vacuous).
7. **Lock-wrap regression:** the P5 `_project_seq` test still passes (no behavioral
   change expected); add none — the wraps are observationally equivalent, note that in
   your report.

## Rules

- steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Red-before-green via detached worktree as in P4/P5. For the exclusion specifically:
  show the no-op-Load-More failure mode (without `exclude` the page is re-evicted).
- Related bugs: flag, don't fix. Spec drift >10 lines → flag.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -k "load_more or sentinel or orphan or mirror or cross_project or reopen" -q 2>&1 | tail -4
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_body_cap.py tests/test_feed_snapshot_off_thread.py tests/test_review_handler_feed_card.py -q 2>&1 | tail -2
```

## Report back

Files/counts, each new test + isolated result, red-check output, full tails, deviations,
and COMPLETENESS:

COMPLETENESS:
- [x/not done] Load-path remove_card-before-append + eviction call — evidence
- [x/not done] `_load_more` final-statement eviction with exclude — evidence (paste)
- [x/not done] Unconditional sentinel removal + else-null — evidence
- [x/not done] Render-from-`_cards` (no _backlog rewrite) — evidence
- [x/not done] Both `_project_seq` lock wraps — evidence
- [x/not done] Tests 8, 9, 11 + sentinel pair + orphan + mirror (non-vacuity) — names + results
- [x/not done] Suites green — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
