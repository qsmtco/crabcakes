# PHASE 3 of 13 — Test-double accessors (F5) + non-ancestor regression test

**Spec:** `docs/specs/SPEC-MEMORY-WIDGET-RATCHET.md` §2.6 "Test-double prerequisite" block.
**Files to change:** exactly one: `tests/test_feed_handler.py`. No product code this phase.

## Context

Phase 5's eviction pass calls FOUR methods on the tab: `is_near_bottom()`,
`is_above_viewport(widget)`, `get_vadjustment()`, and `get_card_container()` (via the
handler's `_card_container_spacing()`). `MockFeedTab` (`:59-131`) defines none of them —
it holds `self._vadjustment` as an attribute but has no accessors and no container stub.
Every inline tab double passed to `set_feed_tab(...)` needs the same four methods.
`MockGLib.idle_add` dispatches synchronously, so a missing accessor surfaces immediately
once Phase 5 lands — that is why this phase exists before it.

## Edit 1 — `MockFeedTab`

Add four accessors, backed by configurable attributes so Phase 5 tests can drive
per-case values:

```python
    # MEMRATCHET P3: eviction-pass surface (spec §2.6). Defaults chosen so the
    # eviction cases are permissive; individual tests override the attributes.
    self._near_bottom = True
    self._above_viewport = True
    self._card_spacing = 8   # real container's spacing (feed_tab.py:86)

    def is_near_bottom(self, slack: int = 80) -> bool:
        return self._near_bottom

    def is_above_viewport(self, widget) -> bool:
        return self._above_viewport

    def get_vadjustment(self):
        return self._vadjustment

    def get_card_container(self):
        # Minimal stub: eviction only reads get_spacing() through the handler's
        # _card_container_spacing() helper.
        return self   # or a tiny stub object exposing get_spacing()
```

If `MockFeedTab` cannot double as its own container cleanly (it has no `get_spacing`),
prefer a small dedicated stub class whose `get_spacing()` returns `self._card_spacing`.
Either way, `get_card_container().get_spacing()` must return **8** by default and the
value must be overridable.

## Edit 2 — inline doubles

Find every `set_feed_tab(` call site that constructs an **inline** double (a plain
object/class literal, not the shared `MockFeedTab` instance). Add the same four methods
to each. The spec says 13 `set_feed_tab(` occurrences total — count the inline doubles
you actually touch; if the live count differs from the spec's 13, report the real number
(drift disclosure, not a blocker). Do not touch doubles that are `MockFeedTab` instances.

## Edit 3 — non-ancestor regression test (P2 audit advisory)

In `TestScheduleScrollToBottom` (real-FeedTab Xvfb class), add
`test_is_above_viewport_false_for_non_ancestor`: append a `Gtk.Label` to a **foreign**
`Gtk.Box` (not the tab's `_card_container`), assert `is_above_viewport(label)` is False
— this pins the `not ok` half of the guard (`compute_bounds` returns ok=False for a
non-ancestor target; verified in the P2 audit probe `.debug/p2_geometry_probe.py`).

## Rules

- Use the steelFramedCodeWriter prompt at `.crabcakes/prompts/steelFramedCodeWriter.md`.
- Read the full test file sections you touch before editing. Identifier anchors, not line
  numbers.
- No product code changes. `ui/views/feed_tab.py` is closed this phase.
- Related bugs: flag, don't fix.

## Verification (run and paste verbatim)

```bash
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py -q 2>&1 | tail -3
grep -c "def is_above_viewport" tests/test_feed_handler.py
grep -n "def is_near_bottom\|def get_vadjustment\|def get_card_container" tests/test_feed_handler.py | head -20
```

Expected: suite green (198+ passed — 197 + the new non-ancestor test); the four accessor
names present in MockFeedTab AND in every inline double; `is_above_viewport` defined
1 + N_inline times.

## Report back

Files changed, counts (accessors added per double), verification output verbatim, drift
notes, and the mandatory COMPLETENESS checklist:

COMPLETENESS:
- [x/not done] MockFeedTab: four accessors, configurable defaults (True/True/8) — evidence
- [x/not done] Every inline double: four accessors — count + evidence
- [x/not done] Non-ancestor test added, False asserted — evidence
- [x/not done] Suite green under xvfb + /usr/bin/python3 — evidence (tail pasted)
- [x/not done] Related issues flagged, not fixed

Please write — that phrase is the marker.
