# PHASE 2 of 7 — Verify + Test `ui/handlers/input_toolbar_handler.py`

**Spec:** `/home/q/projects/crabcakes/docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` Section 2.2
**Target file:** `ui/handlers/input_toolbar_handler.py` (already exists — 395 lines)
**Test file to create:** `tests/test_input_toolbar_handler.py`

## Context

Phase 1 is complete. `utils/spellcheck.py` verified + tested (24 tests passing, supervisor fixed 2 type-guard bugs and added 6 extra tests).

The handler file already exists. Your job is to:
1. **Read the existing file** and verify it matches the spec
2. **Read the spec** to understand the full contract
3. **Write comprehensive tests** — but this is a HANDLER, so test strategy differs from utils
4. **Fix any bugs** you find

## Architecture Rules (from ARCHITECTURE.md)

- `ui/handlers/` = logic with NO `Gtk.*` widget imports. Pango/Gdk data types allowed.
- Handler receives `main_content` reference and `GLib_module` — test with mocks
- Handler dispatches all GTK calls via `GLib.idle_add` callbacks
- Follows the same pattern as `MediaHandler`

## What the spec requires (Section 2.2)

The handler owns: **find/replace**, **spell check**, **file I/O**

### Spell check methods:
- `toggle_spell_check() -> bool` — toggle on/off, returns new state
- `on_buffer_changed()` — debounced at 300ms, runs spell check
- `get_suggestions_at_iter(text_iter) -> list[str]` — right-click suggestions

### Find/replace methods:
- `find(search_text: str) -> tuple[int, int]` — returns (current_index, total_matches)
- `find_next() -> tuple[int, int]`
- `find_prev() -> tuple[int, int]`
- `replace_current(replacement: str) -> tuple[int, int]`
- `replace_all(replacement: str) -> int` — returns count
- `clear_find()` — clear all state and tags

### File I/O methods:
- `save_to_file(file_path: str) -> bool`
- `load_file(file_path: str) -> bool`
- `save_as_prompt(filename: str) -> str | None`
- `load_prompt(prompt_name: str) -> bool`

### Word count:
- `get_word_count() -> tuple[int, int, int]` — (words, chars, approx_tokens)

## Known Issues Already Found by Supervisor

During code review, the supervisor found these issues in the EXISTING handler:

1. **`_apply_spell_tags` and `_apply_find_tags` import `from gi.repository import Pango, Gdk` inside the method** — this is architecturally acceptable (Pango/Gdk are data types, not widgets). But the import is lazy, which means tests can't easily mock it. Consider this in your test design.

2. **`get_suggestions_at_iter` takes a `text_iter` (GTK TextIter)** — this is a GTK dependency. Your tests MUST mock the TextIter and buffer objects.

3. **`on_buffer_changed` creates a GLib timeout** — test with mock GLib.

## Test Strategy for Handlers

Since the handler depends on:
- `main_content` (has `user_input` property returning a Gtk.TextView)
- `GLib_module` (for `idle_add`, `timeout_add`, `source_remove`)

You MUST mock these. Create mock objects that simulate the interfaces:

```python
from unittest.mock import MagicMock, patch

def make_mock_main_content():
    """Create a mock main_content with a realistic user_input mock."""
    mc = MagicMock()
    buf = MagicMock()
    # Simulate get_text returning buffer contents
    buf.get_text.return_value = ""
    buf.get_start_iter.return_value = MagicMock()
    buf.get_end_iter.return_value = MagicMock()
    mc.user_input.get_buffer.return_value = buf
    return mc

def make_mock_glib():
    """Create a mock GLib with idle_add, timeout_add, source_remove."""
    glib = MagicMock()
    glib.idle_add.side_effect = lambda fn, *args: fn(*args)  # execute immediately
    glib.timeout_add.side_effect = lambda ms, fn: fn()  # execute immediately
    glib.source_remove = MagicMock()
    return glib
```

## Required Tests

### Spell check tests:
1. `test_toggle_spell_check_on` — first toggle returns True, enables spell check
2. `test_toggle_spell_check_off` — second toggle returns False
3. `test_on_buffer_changed_when_disabled` — does nothing when spell check off
4. `test_on_buffer_changed_when_enabled` — runs spell check with debounce
5. `test_get_suggestions_at_iter` — returns suggestions for misspelled word at iter

### Find/replace tests:
6. `test_find_no_match` — returns (-1, 0)
7. `test_find_one_match` — returns (0, 1)
8. `test_find_multiple_matches` — returns (0, N)
9. `test_find_next_wraps` — wraps from last to first match
10. `test_find_prev_wraps` — wraps from first to last match
11. `test_replace_current` — replaces current match
12. `test_replace_all` — replaces all matches, returns count
13. `test_clear_find` — clears all state

### File I/O tests (use real temp files):
14. `test_save_to_file` — saves buffer text to file
15. `test_save_to_file_permission_error` — returns False
16. `test_load_file` — loads file into buffer
17. `test_load_file_not_found` — returns False
18. `test_load_file_binary` — returns False (UnicodeDecodeError)

### Word count:
19. `test_get_word_count_empty` — returns (0, 0, 0)
20. `test_get_word_count_text` — returns correct counts

## Mocking Rules (steelFramedCodeWriter Rule 4)

- Mock `main_content` and `GLib` at construction — these are dependencies
- Mock `utils.spellcheck.check_words` and `utils.spellcheck.get_suggestions` for handler tests
- Do NOT mock the handler methods themselves
- For file I/O tests: use real temp files via `tmp_path` fixture (this tests real I/O)

## Verification Commands

```bash
# Run the new tests
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_input_toolbar_handler.py -v --tb=short

# Run the full suite to check for regressions
cd /home/q/projects/crabcakes && python3 -m pytest tests/ -q --tb=short

# Verify the file has no Gtk widget imports
grep -n "from gi.repository import Gtk\|import Gtk" ui/handlers/input_toolbar_handler.py

# Verify line count
wc -l ui/handlers/input_toolbar_handler.py
```

## COMPLETENESS Checklist

At the end of your response, you MUST include:

```
COMPLETENESS:
- [x/not done] Read existing ui/handlers/input_toolbar_handler.py — verified against spec
- [x/not done] Read spec Section 2.2 — understood the contract
- [x/not done] Created tests/test_input_toolbar_handler.py — evidence: (test count, passing count)
- [x/not done] Spell check tests (5 tests) — evidence: test names + results
- [x/not done] Find/replace tests (8 tests) — evidence: test names + results
- [x/not done] File I/O tests (5 tests) — evidence: test names + results
- [x/not done] Word count tests (2 tests) — evidence: test names + results
- [x/not done] All new tests pass — evidence: pytest output
- [x/not done] Full test suite passes — evidence: pytest output (1421+ passed)
- [x/not done] No Gtk widget imports in handler — evidence: grep output
- [x/not done] Bugs found in existing code (if any) — description + fix
```

## Important Reminders

- Use the **steelFramedCodeWriter** prompt at `prompts/steelFramedCodeWriter.md`
- Start with discovery: read the file, read the spec section, then write
- Maximum 15 lines before verifying
- Every test must be able to fail (Rule 4)
- Report any bugs found in existing code — do not silently fix without reporting
- The word marker for this delegation is: **"please write"**
