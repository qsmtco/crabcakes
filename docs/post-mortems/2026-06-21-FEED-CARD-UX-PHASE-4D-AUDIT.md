# Phase 4D Audit Report — Feed Scroll-on-Open + GtkBox Active-State

**Date:** 2026-06-21
**Auditor:** Qaster (implementation supervisor)
**Subject:** Phase 4 follow-up fixes (Bug A: scroll-to-top flake on reopen; Bug B: GtkBox active-state warning)
**Scope:** `ui/views/feed_tab.py`, `ui/handlers/feed_handler.py`, `tests/test_feed_handler.py`
**Commits reviewed:** `bd2576a`, `c1cad1d` (latest HEAD on `main`)

---

## Summary

The mechanism choice for the two bug fixes is **correct and well-defended**:

- **Bug A** fix: connect to vadjustment's `"changed"` signal with a 150ms timeout fallback. Verified empirically that `Gtk.Widget.size-allocate` is not a signal in GTK4 (the report's spec deviation claim holds), and that `Gtk.Adjustment.changed` is a real signal that `connect()` accepts.
- **Bug B** fix: recursive `unset_state_flags(PRELIGHT | ACTIVE | SELECTED)` before widget removal. Correct API; correct recursive walk; covers the parent box and all descendant widgets (buttons inside cards).

**However, three gaps remain that this audit flags for follow-up:**

1. **Zero test coverage of the new `schedule_scroll_to_bottom` mechanism.** The `MockFeedTab.schedule_scroll_to_bottom` is a one-line stub that calls `scroll_to_bottom()` directly, bypassing the new `vadjustment.connect("changed", ...)` and `GLib.timeout_add(...)` logic. The 146 passing tests include none that exercise the actual fix.
2. **Zero test coverage of `_clear_widget_state_recursive`.** The recursive walker is unverified.
3. **Cleanup race in `schedule_scroll_to_bottom`'s timeout fallback.** If the `changed` signal's success path's `disconnect()` raises (e.g., during widget teardown), the 150ms timeout fires later and silently re-scrolls the feed even if the user has scrolled away. The fix is to pass the timeout source ID into the success handler and disarm it there.

---

## Bugs Found During Audit

### BUG #1 — Mock bypasses real mechanism in `schedule_scroll_to_bottom`

**Severity:** issue (test coverage gap, not a code bug)
**File:** `tests/test_feed_handler.py:81-82`
**Assumption violated:** "If the test passes, the code path is exercised."
**Attack vector:** Builder adds a stub method to a mock to make existing tests compile, but the new logic is never run in CI.
**Reproduction:** `grep -n "schedule_scroll_to_bottom" tests/` shows two lines: the mock stub and a no-op assertion. The real `FeedTab.schedule_scroll_to_bottom` (with `vadj.connect("changed", ...)` and `GLib.timeout_add(150, ...)`) has no test.
**Root cause:** The mock was scoped to the minimum change needed to compile, not to test the new behavior.
**Fix:** Phase 4D-1 — replace the stub with a fake `Gtk.Adjustment` and assert the `changed` signal handler and timeout fallback actually fire.
**Pattern:** mock-truthiness

### BUG #2 — `_clear_widget_state_recursive` has no tests

**Severity:** issue (same as #1)
**File:** `ui/views/feed_tab.py:175-184` (and tests/)
**Assumption violated:** "Recursive walk via `get_first_child` / `get_next_sibling` is correct."
**Attack vector:** GTK4 widget tree walk has subtle gotchas (e.g., `get_first_child` may return the same node if the tree is being mutated during iteration). Untested.
**Reproduction:** `grep -rn "_clear_widget_state_recursive" tests/` → 0 matches.
**Root cause:** Tests scoped to handler, not view.
**Fix:** Phase 4D-2 — add 3 tests that build real `Gtk.Box` + `Gtk.Button` + `Gtk.Label` trees and assert state flags are cleared.
**Pattern:** mock-truthiness

### BUG #3 — Timeout-fallback cleanup race

**Severity:** issue (latent race; triggers in specific teardown scenarios)
**File:** `ui/views/feed_tab.py`, method `schedule_scroll_to_bottom` (~lines 210-260)
**Assumption violated:** "The `changed` signal's success path always cleans up `_scroll_handler_id`."
**Attack vector:** During `on_project_closed` → `clear_project` → `feed_tab.remove_card` for many cards in rapid succession, the scrolled window's vadjustment may be disposed by GTK before our `disconnect()` runs. `disconnect()` raises. `_scroll_handler_id` stays set. The 150ms timeout fires later, sees `is not None`, and silently re-scrolls the feed.
**Reproduction:** Hard to reproduce in a unit test without simulating adjustment disposal. The race is a real concern because project close iterates many `remove_card` calls in quick succession (potentially hundreds of cards).
**Root cause:** Two cleanup paths (signal handler + timeout) share a single state variable but are not bidirectionally synchronized.
**Fix:** Phase 4D-3 — capture the timeout source ID in an instance variable; the success path disarms the timeout before clearing itself.
**Pattern:** cleanup-not-idempotent

---

## What the Audit Confirmed

- **Failed Fix 1 (two `GLib.idle_add` callbacks) is genuinely reverted.** `grep -rn "_append_cards\|_scroll_after_layout" ui/` returns 0 matches.
- **Failed Fix 2 (`unrealize()` + `grab_focus()`) is genuinely reverted.** `grep -rn "unrealize\|grab_focus\|has_focus" ui/views/feed_tab.py` returns 0 matches.
- **`size-allocate` is not a GTK4 signal.** Verified empirically: `Gtk.Box().connect('size-allocate', ...)` raises `TypeError: unknown signal name: size-allocate`. The spec's recommendation was based on GTK3 conventions; the report's deviation is correct.
- **`Gtk.Adjustment.connect('changed', ...)` works.** Verified empirically: returns a valid handler ID.
- **`unset_state_flags` is the correct GTK4 API for clearing CSS state.** Documented in GTK4 reference; safe to call on widgets without the flags set.
- **Recursive walk via `get_first_child` / `get_next_sibling` is the canonical GTK4 widget tree traversal.** No alternative recommended.
- **All 146 feed-related tests pass.** 0 failures, 0 warnings. (Report stated 144; actual is 146 — minor discrepancy.)

---

## What Was NOT Audited

- The 150ms timeout value. Could be too long (user notices) or too short (changed signal doesn't fire yet on slow machines). 150ms is a reasonable starting point; no empirical tuning was done.
- Whether the `changed` signal fires for **every** `upper` change or only for some. GTK4 source is not introspected at runtime here; the test in 4D-1 will surface the answer.
- The "Broken accounting" warning's actual suppression. Without a live GTK runtime, the warning's occurrence rate post-fix is unknown. The unit test in 4D-2 verifies the recursive walk; the live test is a manual follow-up.
- Other call sites in `ui/handlers/feed_handler.py` that use `idle_add` (e.g., `_finalize_snapshot`, `_append`, `_remove`, `_clear`, `_render`). Not in scope for Phase 4D, but each follows the same "fire-and-forget on main thread" pattern; if any of them read vadjustment state, they have the same Bug A vulnerability.

---

## Recommendation

**Apply Phase 4D-1, 4D-2, 4D-3 as a single coherent unit.** The three fixes are interdependent:

- 4D-1 tests the `schedule_scroll_to_bottom` mechanism that exists in 4D-3's fix.
- 4D-2 tests the recursive walker that Bug B depends on.
- 4D-3 fixes the cleanup race that 4D-1's tests will surface.

Without 4D-1, 4D-3 has no regression test. Without 4D-3, 4D-1's `test_schedule_scroll_disarms_timeout_after_changed_fires` will fail. Order them: 4D-1 first (with a known-broken 4D-3 in place to confirm the test catches the race), then 4D-3, then re-run 4D-1 to confirm green.

Alternatively, write the test in 4D-1 against the **fixed** code (4D-3 already applied) and confirm green in one pass. Simpler.

**Live runtime verification remains a manual follow-up** (50 project open/close cycles for Bug A, 30 close events with terminal log scrape for Bug B). Cannot be automated without a GTK test harness.

---

**End of audit report.**
