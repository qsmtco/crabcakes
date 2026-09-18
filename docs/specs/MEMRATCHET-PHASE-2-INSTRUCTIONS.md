# PHASE 2 of 13 — FeedTab geometry primitives

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.2 (code is given verbatim there — use it as written) + §2.6 (fail-safe test).
**Files to change:** exactly two: `ui/views/feed_tab.py`, `tests/test_feed_handler.py`.

## Context

These three accessors are the geometry primitives the eviction pass (Phase 5) will call.
`is_above_viewport` carries the load-bearing GTK 4.14 trap: `compute_bounds` returns
`(True, zero rect)` for a never-allocated widget, so a non-positive extent must mean
"unknown", never "above". Phase 5's correctness depends on this exact shape — do not
"simplify" the guard away.

## Edit 1 — `ui/views/feed_tab.py`

1. Add the three methods from spec §2.2 **verbatim**: `get_vadjustment`,
   `is_near_bottom(slack: int = 80)`, `is_above_viewport(widget)`. Place them near the
   other scroll-related methods (after `schedule_smart_scroll_to_bottom` / before
   `update_batch_bar` — anchor by identifier, not line number).
2. Update the module docstring's "Public API" list (top of file, `:5-11`) to include the
   three new primitives. This is spec §2.7's feed_tab row, done here while the file is
   open.
3. Nothing else. No signature changes to existing methods.

## Edit 2 — `tests/test_feed_handler.py`

Add to the **existing real-GTK Xvfb harness class** (the one at `:1284-1297` that builds
a real `FeedTab`) — do NOT touch `MockFeedTab` (Phase 3 owns it):

1. `test_is_near_bottom_true_when_no_vadjustment` — a FeedTab whose `_feed_scroll` is
   None (freshly constructed, never mapped) → `is_near_bottom()` is True, and
   `get_vadjustment()` is None.
2. `test_is_above_viewport_false_for_unallocated_widget` — append a real
   `Gtk.Label` to the card container but never realize/map the tab (drive with the
   harness's existing setup, do not call show). Assert `is_above_viewport(label)` is
   **False** — this is the zero-rect trap: GTK returns ok=True with height 0.0, and the
   `rect.size.height <= 0` guard must classify it "unknown".
3. `test_is_above_viewport_false_for_mock_widget` — an object with no `compute_bounds`
   → False (the AttributeError branch).

Mark the class so it only runs under Xvfb the same way the existing harness class does
(follow whatever skip/guard pattern the file already uses — mirror it exactly).

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Read `ui/views/feed_tab.py` and the relevant test file sections in full before editing.
- Anchor edits to identifiers. Spec drift >10 lines → flag it in COMPLETENESS.
- Related bugs: flag, don't fix.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -5
/usr/bin/python3 -m py_compile ui/views/feed_tab.py && echo COMPILE-OK
grep -n "def get_vadjustment\|def is_near_bottom\|def is_above_viewport" ui/views/feed_tab.py
```

Note: `/usr/bin/python3` is mandatory (PATH `python3` is a venv without `gi`).

## Report back

Files changed with line counts, all verification output verbatim, and the mandatory
COMPLETENESS checklist (delivery without it is returned):

COMPLETENESS:
- [x/not done] Three methods match spec §2.2 verbatim — evidence (paste the method bodies)
- [x/not done] Module Public-API docstring lists the three primitives — evidence
- [x/not done] Three new tests in the real-FeedTab Xvfb class, MockFeedTab untouched — evidence
- [x/not done] Full test_feed_handler.py suite green under xvfb — evidence (tail -5 pasted)
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
