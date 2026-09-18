# PHASE 10 of 13 — ARCHITECTURE.md updates (spec §8)

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §8 — the four required
documentation items.
**Files to change:** exactly one: `docs/ARCHITECTURE.md`. No code, no tests.

## Where

`docs/ARCHITECTURE.md` (4,662 lines). The relevant module sections are §3.22c
(`ui/handlers/feed_handler.py` — starts ~`:2891`) and §3.35 (`ui/views/feed_tab.py` —
starts ~`:3475`). Anchor by section headers, not line numbers. Read both sections in
full before editing.

## Edits (spec §8's four items, placed per below)

1. **§3.22c (feed_handler):** add a paragraph documenting the bounded live-widget
   window: `MAX_LIVE_CARD_WIDGETS = 120` / `KEEP_NEWEST_CARDS = 40`, the invariant in
   bold — **card data is unbounded; card widgets are bounded** — and that eviction
   (`_evict_surplus_card_widgets`, spec-verbatim at ~`:1827`) releases only
   above-viewport victims chosen by `seq_num` across all projects, pushing data back to
   `_backlog` (newest-first, survivors-first merge on load) so nothing becomes
   unreachable. Note the GTK-never-returns-memory rationale: freed widget memory is
   never returned to the OS, which is why the bound exists at all.
2. **§3.22c:** document `_project_cards[project]` ordering: newest-first by `seq_num`
   at every insertion point (loader sorts; `add_card` inserts at 0); Accept All /
   batch-bar visibility depends on it.
3. **§3.35 (feed_tab):** extend the Public API block with the three geometry
   primitives (`get_vadjustment`, `is_near_bottom`, `is_above_viewport`) and document
   the fail-safe contract INCLUDING the trap: GTK 4.14 returns
   `compute_bounds -> (True, zero rect)` for a widget that has never been allocated,
   so "unknown" must be `ok is False` **or** a non-positive extent — and note the
   P3-audit finding that a non-ancestor target returns `ok=False` (also with a zero
   rect). Also add the P2-audit correction: `get_vadjustment` returns a real zeroed
   Adjustment for a constructed tab — None occurs only when `_feed_scroll` is absent,
   not "before first map".
4. **§3.22c:** one line on `_project_seq` concurrency: increments and the loader's
   max() rebuild are under `_lock` (P6), and the counter is per-project — cross-project
   eviction victim ordering ties are broken arbitrarily (documented accepted behavior,
   spec erratum #4).

## Style rules

- Match the file's existing documentation voice (see §3.22c's background-writer
  paragraph and §3.35's Public API block for the register).
- Reference the spec (`SPEC-MEMORY-WIDGET-RATCHET.md`) and the phase where a reader
  should look for detail — the architecture doc summarizes, it does not duplicate the
  spec.
- No code blocks longer than 10 lines; no speculative future work.

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Read-before-edit in full for both sections. Related inaccuracies found in adjacent
  text: flag, don't fix.

## Verification (run and paste verbatim)

```bash
grep -n "MAX_LIVE_CARD_WIDGETS\|KEEP_NEWEST_CARDS\|is_above_viewport\|never returned" docs/ARCHITECTURE.md
/usr/bin/python3 -m pytest tests/test_architecture.py -q 2>&1 | tail -1
git diff --stat docs/ARCHITECTURE.md
```

## Report back

Counts, the four inserted blocks (paste), grep output, test result, deviations, and
COMPLETENESS:

COMPLETENESS:
- [x/not done] Bounded-window paragraph + invariant + rationale — evidence
- [x/not done] newest-first ordering documented — evidence
- [x/not done] Geometry primitives + zero-rect trap + non-ancestor + get_vadjustment correction — evidence
- [x/not done] `_project_seq` concurrency + cross-project tie note — evidence
- [x/not done] test_architecture still green — evidence
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
