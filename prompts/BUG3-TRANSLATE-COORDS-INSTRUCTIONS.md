# Bug #3 Fix — Silent translate_coordinates Failure

## File to edit
- `ui/window.py` — the `_on_input_right_click` closure only (around line 369-372)

## Problem
When `text_view.translate_coordinates(self, x, y)` returns `ok=False`, the code silently returns with no log message. The comment says "shouldn't happen" but if it ever does (e.g., widget tree restructuring, detached TextView), debugging is impossible because there's zero diagnostic output.

## Fix
Add a `logger.warning(...)` call before the `return` so the silent failure becomes a visible diagnostic.

## Exact change required

### Change the silent return to a logged warning

Current code (around line 369-372):
```python
            ok, wx, wy = text_view.translate_coordinates(self, int(x), int(y))
            if not ok:
                return  # widgets not in the same toplevel (shouldn't happen)
```

Change to:
```python
            ok, wx, wy = text_view.translate_coordinates(self, int(x), int(y))
            if not ok:
                logger.warning(
                    "translate_coordinates failed for right-click at (%d, %d) — "
                    "text_view and window not in same toplevel",
                    int(x), int(y),
                )
                return
```

## Test required

Add a test that verifies the warning is logged when `translate_coordinates` fails. This test should:
1. Be added to `tests/test_chat_input_toolbar.py` in a new class `TestTranslateCoordinatesWarning`
2. OR be added to whichever test file covers `window.py` right-click behavior (check existing tests first)
3. Mock `translate_coordinates` to return `(False, 0, 0)`
4. Verify `logger.warning` was called with a message containing "translate_coordinates"

If no test file covers `window.py` right-click behavior, add the test to `tests/test_chat_input_toolbar.py` as a new class.

## Constraints
- Do NOT change the return behavior — it should still return early
- Do NOT change the coordinates or the pointing_to calculation
- Do NOT touch any other method
- The warning message must include the x, y coordinates for debugging
- Use `%`-style formatting in the logger call (not f-string) per logging best practices

## Verification
- `python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_main_content_tab_switch.py -q --tb=short` — all tests must pass (109 existing + new)
- The new test must FAIL when the `logger.warning` is removed (i.e., the production code reverts to silent return)
