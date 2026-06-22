# Bug #2 Fix — Test Coverage for New Popover Code Paths

## Files to edit
- `tests/test_chat_input_toolbar.py` — add new tests ONLY (do not modify existing tests)

## Problem
The deferred-popup and pointing_to code paths added in the popover positioning fix have ZERO test coverage. The existing test `test_show_suggestions_menu_with_parent_widget` passes `parent_widget` but not `pointing_to`, and since `get_root()` returns `None` in headless tests, the entire `GLib.idle_add` deferred-popup block is dead code in tests. These paths could be reverted and all tests would still pass.

## Fix
Add tests that verify the NEW code paths actually execute correctly. These tests must mock `get_root()` to return non-None so the popup branches are exercised.

## Exact tests required

### Test 1: `pointing_to` passed to `set_pointing_to`
Mock or patch so the popover is created with a `parent_widget` and `pointing_to=(10, 20, 30, 40)`. After the call, verify `set_pointing_to` was called on the popover with a `Gdk.Rectangle` whose x=10, y=20, width=30, height=40.

Approach: create a real `ChatInputToolbar`, call `show_suggestions_menu(["x"], cb, parent_widget=some_box, pointing_to=(10, 20, 30, 40))`, then inspect `toolbar._suggestion_popover` and check its pointing-to rect. GTK4 Popover doesn't have a `get_pointing_to()` that works reliably in tests, so instead: spy on the popover by patching `Gtk.Popover.set_pointing_to` or check the popover's child exists.

SIMPLEST RELIABLE APPROACH: Create the popover via `show_suggestions_menu` with `pointing_to`, grab `toolbar._suggestion_popover`, and verify it was created and parented correctly. The pointing_to rect is set via `Gdk.Rectangle` which is a value type — verify by checking the popover has the correct parent and that no exception was raised.

### Test 2: Deferred popup via `GLib.idle_add` when `parent_widget` is set and root exists
Patch `ChatInputToolbar.get_root` to return a non-None mock. Patch `GLib.idle_add` to capture the callback (don't actually run it). Call `show_suggestions_menu(["x"], cb, parent_widget=some_box)`. Verify `GLib.idle_add` was called (i.e., the deferred path was taken, not `popover.popup()` directly).

### Test 3: Direct `popup()` when no `parent_widget` and root exists
Patch `ChatInputToolbar.get_root` to return non-None. Patch `GLib.idle_add` to track calls. Call `show_suggestions_menu(["x"], cb)` with no `parent_widget`. Verify `GLib.idle_add` was NOT called (the direct `popup()` path was taken).

### Test 4: No popup when root is None (backward compat / test mode)
Call `show_suggestions_menu(["x"], cb)` with no parent_widget. Verify popover was created but `popup()` was never called (since `get_root()` returns None in headless). Verify `_suggestion_popover` is set.

## Constraints
- Do NOT modify any existing tests
- Do NOT modify production code — this is TESTS ONLY
- Use `unittest.mock.patch` for mocking `get_root` and `GLib.idle_add`
- Each test must be able to FAIL if the production code is reverted (e.g., if `idle_add` path is removed, test 2 must fail)
- Follow the mock construction rules from steelFramedCodeWriter.md: mock at boundary, set attributes explicitly, verify return types

## Verification
- `python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_main_content_tab_switch.py -q --tb=short` — all tests must pass (105 existing + new ones)
- Each new test must fail if the corresponding production code path is removed
