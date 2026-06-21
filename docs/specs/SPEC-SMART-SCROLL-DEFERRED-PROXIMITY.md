# SPEC: Deferred Smart Scroll with Proximity Check

**Date:** 2026-06-21
**Supervisor:** Qaster
**Builder:** QTR
**Priority:** HIGH
**Scope:** 3 files, 1 new method, 1 line swap, 1 new test class

---

## Problem

`smart_scroll_to_bottom()` in `ui/views/feed_tab.py` runs synchronously. When called from `feed_handler.py:add_card()` in the same idle callback as `append_card()`, GTK hasn't updated `vadjustment.upper` yet. The proximity check uses a stale upper, and the scroll either snaps to the wrong position or doesn't fire at all.

## Solution

Add a new method `schedule_smart_scroll_to_bottom()` that combines:
1. The proximity check from `smart_scroll_to_bottom()` (user near bottom?)
2. The deferred-signal approach from `schedule_scroll_to_bottom()` (wait for layout)

Then swap the call site in `feed_handler.py` to use the new method.

## Acceptance Criteria

1. `schedule_smart_scroll_to_bottom()` exists on `FeedTab` with correct proximity + deferral logic
2. `feed_handler.py` calls `schedule_smart_scroll_to_bottom()` instead of `smart_scroll_to_bottom()`
3. 3 new tests in `tests/test_feed_handler.py` covering: near-bottom scrolls, scrolled-up preserves position, stale-upper-is-correct behavior
4. All existing tests still pass
5. `smart_scroll_to_bottom()` is NOT modified (preserves contract for other callers)
6. `schedule_scroll_to_bottom()` is NOT modified (unconditional behavior preserved)

## Files

| File | Change |
|------|--------|
| `ui/views/feed_tab.py` | Add `schedule_smart_scroll_to_bottom()` after `schedule_scroll_to_bottom()` |
| `ui/handlers/feed_handler.py` | Line ~188: swap `smart_scroll_to_bottom()` → `schedule_smart_scroll_to_bottom()` |
| `tests/test_feed_handler.py` | Add `TestScheduleSmartScrollToBottom` class with 3 tests |

## Architecture Notes

- `FeedTab` is a pure view — adding a scroll method is consistent
- No new imports needed
- The proximity check uses stale upper intentionally (measures user position, not content height)
- 80px threshold preserved from existing `smart_scroll_to_bottom()`
