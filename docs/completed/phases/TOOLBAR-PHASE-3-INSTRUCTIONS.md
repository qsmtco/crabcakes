# PHASE 3 of 7 — Verify + Test `ui/views/chat_input_toolbar.py`

**Spec:** `/home/q/projects/crabcakes/docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` Section 2.3
**Target file:** `ui/views/chat_input_toolbar.py` (already exists — 549 lines)
**Test file to create:** `tests/test_chat_input_toolbar.py`

## Context

Phase 1 (spellcheck) and Phase 2 (handler) are complete and audited. All bugs fixed.
- `utils/spellcheck.py` — 24 tests passing
- `ui/handlers/input_toolbar_handler.py` — 23 tests passing, 0 warnings

The view file already exists. Your job is to:
1. **Read the existing file** and verify it matches the spec
2. **Read the spec** Section 2.3 to understand the full contract
3. **Write comprehensive tests**
4. **Fix any bugs** you find

## Architecture Rules (from ARCHITECTURE.md)

- `ui/views/` = **pure view** — displays widgets, handles NO business logic
- View may import Gtk widgets freely (this is the view layer)
- View receives callbacks from the window wiring — it does NOT create handlers
- All CSS classes must come from `ui/styles.py` via `add_css_class()`
- View must NOT import from `ui/handlers/` — handlers are wired by the window

## What the spec requires (Section 2.3)

The view is a horizontal toolbar below the chat input area containing:

### Left section — file buttons:
- Open file button (folder icon)
- Save file button (disk icon)

### Center section — editing controls:
- Find/Replace toggle button (magnifying glass icon)
- Spell check toggle button (ABC icon with underline)
- Find bar (expandable, contains: search entry, prev/next buttons, replace entry, replace/replace-all buttons, count label, close button)

### Right section — submit:
- Send button (arrow icon)

### Find bar behavior:
- Slides in when find toggle is activated
- Shows search entry with match count badge (e.g., "3/7")
- Previous/next navigation buttons
- Replace entry + replace button + replace-all button
- Close button clears find state

### Callbacks the view emits (set by window):
- `on_find_toggled(callback)` — find toggle clicked
- `on_spell_toggled(callback)` — spell toggle clicked
- `on_send_clicked(callback)` — send button clicked
- `on_open_file(callback)` — open file clicked
- `on_save_file(callback)` — save file clicked
- `on_find_search(callback)` — search text changed
- `on_find_next(callback)` — next button clicked
- `on_find_prev(callback)` — prev button clicked
- `on_replace_current(callback)` — replace button clicked
- `on_replace_all(callback)` — replace all button clicked
- `on_find_closed(callback)` — close find bar clicked
- `on_suggestion_selected(callback)` — spell suggestion right-click menu item selected

### Public methods the view exposes:
- `set_find_count(current, total)` — update the match count badge
- `set_spell_active(active: bool)` — toggle visual state of spell button
- `set_find_bar_visible(visible: bool)` — show/hide the find bar
- `get_search_text() -> str` — current search entry text
- `get_replace_text() -> str` — current replace entry text
- `show_suggestions_menu(suggestions: list[str], callback)` — popup right-click menu
- `get_input_buffer() -> Gtk.TextBuffer` — the input buffer for handler access

## Known Issues Already Found by Supervisor

During code review, the supervisor found these issues in the EXISTING view:

1. **`Gtk.ModelButton` does not exist in GTK4** — if used anywhere, it must be replaced with `Gtk.Button` or a `Gtk.PopoverMenu` with actions
2. **`set_keynav_wrapper` does not exist on `Gtk.Entry` in GTK4** — if called, it will crash
3. **The view may import from `ui/handlers/`** — this violates architecture. The view must only receive callbacks, not import handlers.

## Test Strategy for Views

Views are GTK widgets. Testing GTK4 views requires a display. Use this approach:

```python
import os
import sys

# GTK4 requires a display — use headless if no display available
if "GDK_BACKEND" not in os.environ:
    os.environ["GDK_BACKEND"] = "headless"

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
```

### What to test:
1. **Construction** — view can be instantiated without crash
2. **Widget structure** — expected child widgets exist
3. **Callback wiring** — callbacks are stored and can be invoked
4. **Public methods** — set_find_count, set_spell_active, set_find_bar_visible, etc.
5. **No handler imports** — verify the view does not import from ui/handlers/

### What NOT to test:
- Visual rendering (colors, sizes, positions)
- CSS class application (that's styles.py domain)
- Actual GTK signal emission (too fragile)

## Required Tests

### Construction tests:
1. `test_construction` — view instantiates without error
2. `test_has_expected_widgets` — key widgets (find toggle, spell toggle, send button) exist
3. `test_no_handler_imports` — view module does not import from ui/handlers/

### Callback tests:
4. `test_on_find_toggled` — callback fires when find toggle clicked
5. `test_on_spell_toggled` — callback fires when spell toggle clicked
6. `test_on_send_clicked` — callback fires when send clicked
7. `test_on_open_file` — callback fires
8. `test_on_save_file` — callback fires
9. `test_on_find_closed` — callback fires

### Public method tests:
10. `test_set_find_count` — updates count label
11. `test_set_spell_active` — toggles spell button visual state
12. `test_set_find_bar_visible` — shows/hides find bar
13. `test_get_search_text` — returns search entry text
14. `test_get_replace_text` — returns replace entry text

### Edge case tests:
15. `test_set_find_count_no_matches` — (0, 0) displays "0/0" or similar
16. `test_set_find_count_with_matches` — (3, 7) displays "3/7"
17. `test_find_bar_initially_hidden` — find bar not visible at start
18. `test_callbacks_default_none` — no crash if callback not set

## Mocking Rules

- Mock the handler at construction if the view takes a handler parameter
- Use `GDK_BACKEND=headless` for all tests
- Do NOT mock Gtk widgets — use real GTK4 widgets in headless mode
- Mock only external dependencies (file system, network)

## Verification Commands

```bash
# Run the new tests
cd /home/q/projects/crabcakes && GDK_BACKEND=headless python3 -m pytest tests/test_chat_input_toolbar.py -v --tb=short

# Run the full suite
cd /home/q/projects/crabcakes && python3 -m pytest tests/ -q --tb=short

# Verify no handler imports
grep -n "from ui.handlers\|import ui.handlers" ui/views/chat_input_toolbar.py

# Check for GTK3-only APIs
grep -n "ModelButton\|set_keynav_wrapper" ui/views/chat_input_toolbar.py

# Verify line count
wc -l ui/views/chat_input_toolbar.py
```

## COMPLETENESS Checklist

At the end of your response, you MUST include:

```
COMPLETENESS:
- [x/not done] Read existing ui/views/chat_input_toolbar.py — verified against spec
- [x/not done] Read spec Section 2.3 — understood the contract
- [x/not done] Created tests/test_chat_input_toolbar.py — evidence: (test count, passing count)
- [x/not done] Construction tests (3 tests) — evidence: test names + results
- [x/not done] Callback tests (6 tests) — evidence: test names + results
- [x/not done] Public method tests (5 tests) — evidence: test names + results
- [x/not done] Edge case tests (4 tests) — evidence: test names + results
- [x/not done] All new tests pass — evidence: pytest output
- [x/not done] Full test suite passes — evidence: pytest output
- [x/not done] No handler imports in view — evidence: grep output
- [x/not done] No GTK3-only APIs (ModelButton, set_keynav_wrapper) — evidence: grep output
- [x/not done] Bugs found in existing code (if any) — description + fix
```

## Important Reminders

- Use the **steelFramedCodeWriter** prompt at `prompts/steelFramedCodeWriter.md`
- Start with discovery: read the file, read the spec section, then write
- Maximum 15 lines before verifying
- Every test must be able to fail (Rule 4)
- Report any bugs found in existing code — do not silently fix without reporting
- The word marker for this delegation is: **"please write"**
