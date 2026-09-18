# PHASE 5 of 13 — Eviction core: constants + `_evict_surplus_card_widgets` + two call sites

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.1 (constants, the eviction
method, `_card_container_spacing`, call-site table) + §2.6 tests. The two verbatim code
blocks (eviction method, spacing helper) are **byte-identical-mandatory** — extract them
from the spec fence as in P4; supervisor re-verifies byte identity.
**Files to change:** `ui/handlers/feed_handler.py`, `tests/test_feed_handler.py`.

## Scope — this phase ONLY the two live append paths

Call sites wired here: `add_card`'s `_append` idle callback (after
`_schedule_smart_scroll()`, ~`:814-817`) and `add_cards_batch`'s `_append_all` (after
its single `_schedule_smart_scroll()`, ~`:946-952`). The **load path and `_load_more`
call sites are Phase 6** — do not touch them, even though the table lists four.

## Edits — `ui/handlers/feed_handler.py`

1. Module constants (module level, near the top; bare names — the method reads them at
   call time so tests can monkeypatch):
   `MAX_LIVE_CARD_WIDGETS = 120`, `KEEP_NEWEST_CARDS = 40`.
2. `_evict_surplus_card_widgets(self, exclude: frozenset[str] = frozenset())` — spec
   §2.1 verbatim, docstring included. `exclude` is unused until P6; keep it.
3. `_card_container_spacing()` — spec §2.1 verbatim.
4. The two call-site one-liners, per the table.
5. **`_project_seq` fix (routed from P4 audit, REQUIRED):** in `_load_and_render`
   (~`:1612-1614`), replace the unconditional
   `self._project_seq[project_name] = max_seq` with
   `self._project_seq[project_name] = max(max_seq, self._project_seq.get(project_name, 0))`
   so a live arrival's sequence number from the parse window is not clobbered by the
   disk snapshot. One line + a comment noting why (live arrivals during the parse
   window already advanced the counter).

## Edits — `tests/test_feed_handler.py`

New cases (spec §2.6 numbering) in a new class `TestEvictionSurplus` (or the most
consistent existing pattern):

1. **Test 1:** 500 `add_card` calls, viewport guard permissive →
   `len(handler._card_widgets) <= MAX_LIVE_CARD_WIDGETS` and the newest
   `KEEP_NEWEST_CARDS` (by `seq_num`) survive.
2. **Test 2 (bounded-but-over-cap):** over the cap with `_above_viewport = False` →
   nothing evicted, map unchanged.
3. **Test 3:** an evicted card's data remains in `_cards` AND sits at the **front** of
   `_backlog`; then `_load_more()` re-renders a widget for it (mock path fine).
4. **Test 4 (guard stops the loop):** make `is_above_viewport` permissive for the first
   victim then refusing (override the accessor with a stateful callable/list — keep the
   attribute contract intact for other tests) → the loop breaks; no widget beyond the
   first is destroyed.
5. **Test 5 (compensation):** near-bottom → `schedule_scroll_to_bottom` called;
   scrolled-up (`_near_bottom = False`, `MockVadjustment` with a nonzero value) →
   `vadj.set_value` called with `value - (height + spacing)`. If MockFeedTab /
   MockVadjustment don't record these calls yet, add recording (same file, in scope).
   Use a widget stub with a known `get_height()` so the spacing term (8) is asserted
   explicitly.
6. **Test 7:** `add_cards_batch` burst (e.g. 200 cards) → eviction runs; batch path
   covered.
7. **Zeroed-adjustment discriminator (from P2 audit):** over the cap with
   `_near_bottom = True` and a zeroed MockVadjustment (upper=page=value=0 — the
   "layout never ran" state indistinguishable from "no container") → eviction
   *attempts* but destroys nothing, because `is_above_viewport` is False for
   unmeasurable widgets. Pins that the fail-safe direction survives the
   indistinguishability.
8. **`_project_seq` regression:** seed `_project_seq[name] = 3`; snapshot seq 1..3; a
   live arrival during the load gets seq 4; the next `add_card` must get **5**, not 4.

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Byte-identity discipline as in P4 (no edits to the verbatim blocks).
- Do not touch: the loader's lock region, `_backlog` writers, `_load_more`, the load
  path's render loop, or any view file. Those are P6/P7.
- Related bugs: flag, don't fix. Spec drift >10 lines → flag.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -k "eviction or evict or project_seq" -q 2>&1 | tail -3
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_body_cap.py tests/test_feed_snapshot_off_thread.py -q 2>&1 | tail -2
```

## Report back

Files changed + counts, byte-identity check output for the two verbatim blocks, each new
test name + isolated result, full-suite tails, deviations, and COMPLETENESS:

COMPLETENESS:
- [x/not done] Constants at module level (120/40) — evidence
- [x/not done] Eviction method + spacing helper byte-identical to spec — evidence
- [x/not done] Two call sites (add_card, add_cards_batch) — evidence
- [x/not done] `_project_seq` max() fix + comment — evidence
- [x/not done] Tests 1,2,3,4,5,7 + zeroed-adjustment + _project_seq — names + results
- [x/not done] Full suite + adjacent suites green — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
