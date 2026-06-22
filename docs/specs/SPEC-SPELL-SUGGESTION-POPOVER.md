# SPEC: Spell Check Suggestion Popover on Right-Click

**Date:** 2026-06-22
**Author:** qaster
**Status:** Draft — for implementation
**Depends on:** None (builds on existing spell check infrastructure shipped in Phase 5)
**Target branch:** main

> **Architecture compliance statement:** Per ARCHITECTURE.md §3.9, `MainContent` owns the `user_input` `Gtk.TextView`. All new GTK controller code (right-click `GestureClick`) is view-layer code and goes in `ui/views/main_content.py`. The suggestion popover UI lives in `ui/views/chat_input_toolbar.py` (already implemented: `show_suggestions_menu`). Word-replacement logic (buffer delete + insert) goes in `ui/handlers/input_toolbar_handler.py` (no GTK widget imports, uses `Gtk.TextBuffer` API via `main_content.user_input.get_buffer()` which is already the established pattern in that handler). No new files created. Architecture boundary preserved.

---

## 1. Overview

### Problem statement
Spell check highlights misspelled words with a red underline but there is no way to right-click a misspelled word and pick a correction from a suggestion list. The user can see the error but cannot act on it without manually deleting and retyping the word.

### Solution summary
Wire a `Gtk.GestureClick` (right-click / `BUTTON_SECONDARY`) controller onto the `user_input` `Gtk.TextView`. On right-click, if the clicked word has the `spell-error` tag, fetch suggestions via the existing `get_suggestions_at_iter()` → `get_suggestions()` → `enchant-2 -a` pipeline, then show the existing `show_suggestions_menu()` popover. When the user picks a suggestion, replace the misspelled word in the buffer via a new `replace_word_at_iter()` handler method.

### Scope

| In scope | Out of scope |
|---|---|
| Right-click GestureClick on `user_input` TextView | Replacing enchant-2 with a different spell checker |
| Showing suggestion popover when right-clicking a misspelled word | Adding "Add to dictionary" / "Ignore" actions |
| Replacing the misspelled word with the selected suggestion | Autocorrect / inline suggestions |
| Re-running spell check after replacement | Localized suggestion ordering |

### Architecture principles that apply
- **§3.9** — `MainContent` owns `user_input`. The `GestureClick` controller is added to `self._user_input` in `MainContent.__init__`.
- **Handler/view split** — All GTK widget construction stays in views (`main_content.py`, `chat_input_toolbar.py`). Buffer manipulation (delete/insert text) stays in `InputToolbarHandler`.
- **No GTK imports in handlers** — `input_toolbar_handler.py` imports no `Gtk.*` types. It accesses the buffer via `self._mc.user_input.get_buffer()`, which returns a `Gtk.TextBuffer` object — this is the same pattern used by `find()`, `replace_current()`, `_apply_spell_tags()`, and every other method in the handler.

---

## 2. Changes by File

### 2.1 `ui/views/main_content.py` — Add right-click GestureClick on TextView

**What changes:** Add a `Gtk.GestureClick` controller with `button=Gdk.BUTTON_SECONDARY` to `self._user_input` in `__init__`, wired to a new `_on_input_right_click` method. Also add a callback slot so window.py can inject the suggestion-fetch + popover-display logic (keeping MainContent a dumb view).

**New callback slot:**
```python
# In __init__, after the existing callback slots:
self._on_input_right_click: callable | None = None
```

**New setter:**
```python
def set_on_input_right_click(self, cb: callable) -> None:
    """Register callback for right-click on input TextView.

    cb(n_press, x, y) — called on right-click. The callback is responsible
    for checking if the word at (x, y) is misspelled and showing a popover.
    """
    self._on_input_right_click = cb
```

**GestureClick wiring** (in `__init__`, after `self._user_input.add_css_class("input-bubble")` at line 136, before `input_scroll.set_child(self._user_input)` at line 137):

```python
# Right-click controller for spell-check suggestions.
# Pattern copied from left_panel.py:756-758 (prompt row right-click).
right_click = Gtk.GestureClick()
right_click.set_button(Gdk.BUTTON_SECONDARY)
right_click.connect("pressed", self._on_input_right_click_internal)
self._user_input.add_controller(right_click)
```

**Signal handler** (new method in MainContent):

```python
def _on_input_right_click_internal(self, gesture, n_press, x, y) -> None:
    """Internal: forward right-click to the registered callback.

    Args:
        gesture:  Gtk.GestureClick (the controller).
        n_press:  int — number of presses.
        x, y:     float — local coordinates relative to the TextView.
    """
    if n_press != 1:
        return
    if self._on_input_right_click is not None:
        self._on_input_right_click(n_press, x, y)
```

**Why the callback indirection:** MainContent is a pure view — it does not know about `InputToolbarHandler` or spell check. The callback lets `window.py` wire the handler without breaking the architecture boundary. This is the same pattern used for `set_on_buffer_changed` (line 221-223).

**Imports required:** `Gdk` is already imported in `main_content.py` (line 3: `from gi.repository import Gtk, Gdk, GLib`). `Gtk.GestureClick` is available via `Gtk.GestureClick` (used at lines 353, 359 in the same file). No new imports.

**Estimated lines:** ~25 lines added.

---

### 2.2 `ui/handlers/input_toolbar_handler.py` — Add `replace_word_at_iter` method

**What changes:** Add a new public method that replaces the word spanning `[word_start, word_end]` with a replacement string. This is called by the suggestion-popover callback when the user picks a suggestion.

**New method:**

```python
def replace_word_at_iter(self, text_iter, replacement: str) -> None:
    """Replace the word at *text_iter* with *replacement*.

    Finds word boundaries around text_iter, deletes the word, and inserts
    *replacement* in its place. After replacement, re-runs spell check if
    enabled so the underline is removed from the corrected word.

    Args:
        text_iter:  Gtk.TextIter — any iter inside the word to replace.
        replacement: str — the corrected word text.
    """
    word_start = text_iter.copy()
    word_end = text_iter.copy()
    if not word_start.inside_word():
        return
    word_start.backward_word_start()
    word_end.forward_word_end()
    buf = self._mc.user_input.get_buffer()
    buf.delete(word_start, word_end)
    buf.insert(word_start, replacement)
    # Re-run spell check to update tags (removes underline if word is now correct)
    if self._spell_enabled:
        self._run_spell_check()
```

**Verification of existing patterns this method mirrors:**
- `get_suggestions_at_iter` (line 77-98 of the same file) uses the same `backward_word_start()` / `forward_word_end()` / `inside_word()` pattern — verified at source.
- `replace_current` (line 214-226 of the same file) uses the same `buf.delete(start, end)` + `buf.insert(start, replacement)` pattern — verified at source.
- `self._run_spell_check()` is defined at line 102 and is the standard spell-check refresh entry point — verified at source.

**Imports required:** None. No new imports. All GTK types used (`TextIter` methods) are accessed through the existing `self._mc.user_input.get_buffer()` pattern.

**Estimated lines:** ~15 lines added.

---

### 2.3 `ui/views/chat_input_toolbar.py` — Fix `show_suggestions_menu` parent widget

**What changes:** The current `show_suggestions_menu` parents the popover to `self._spell_btn` (line 250). This is wrong for right-click context — the popover should appear near the clicked word, not near the spell-check toggle button. Accept a `parent_widget` parameter so the caller can pass the `TextView` as the parent.

**Current signature (line 243):**
```python
def show_suggestions_menu(self, suggestions: list[str], callback: callable):
```

**New signature:**
```python
def show_suggestions_menu(self, suggestions: list[str], callback: callable, parent_widget=None):
```

**Current parent line (250):**
```python
popover.set_parent(self._spell_btn)
```

**New parent logic:**
```python
if parent_widget is not None:
    popover.set_parent(parent_widget)
else:
    popover.set_parent(self._spell_btn)  # fallback: toolbar button
```

**Also add a "closed" signal handler** to unparent the popover on dismiss (same fix pattern as the Tier-3 left_panel popover-leak fix):

```python
popover.connect("closed", lambda *_: popover.unparent())
```

This goes after the `popover.set_child(vbox)` line (currently line 270, before the `if self.get_root() is not None:` popup guard).

**Why:** Prevents popover widget leak on ESC/click-outside dismiss — the exact same bug class fixed in the Tier-3 Phase 1 left_panel work.

**Backward compatibility:** Existing tests at `tests/test_chat_input_toolbar.py:399-432` call `show_suggestions_menu(["world", ...], callback)` without a `parent_widget` arg. With `parent_widget=None` default, these tests continue to pass unchanged.

**Estimated lines:** ~6 lines changed.

---

### 2.4 `ui/window.py` — Wire the right-click callback

**What changes:** Add a right-click handler function in the input toolbar wiring section (after the existing `_on_input_buffer_changed` closure at line ~334) that:
1. Converts TextView-local (x, y) coordinates to a buffer offset via `get_iter_at_location`.
2. Checks if the iter has the `spell-error` tag.
3. If yes, calls `handler.get_suggestions_at_iter()` and `toolbar.show_suggestions_menu()`.
4. Wires it via `self._main_content.set_on_input_right_click(...)`.

**New wiring code** (added after the `_on_input_buffer_changed` closure definition, ~line 334):

```python
def _on_input_right_click(n_press, x, y):
    """Right-click on input TextView — show spell suggestions if word is misspelled."""
    handler = self._input_toolbar_handler
    if not handler._spell_enabled:
        return
    text_view = self._main_content.user_input
    # Convert (x, y) to a TextIter
    result, iter_at_pos = text_view.get_iter_at_location(int(x), int(y))
    # GTK4 TextView.get_iter_at_location returns (bool success, TextIter)
    if not result:
        return
    # Check if the iter has the spell-error tag
    buf = text_view.get_buffer()
    tag_table = buf.get_tag_table()
    spell_tag = tag_table.lookup("spell-error")
    if spell_tag is None:
        return  # spell check never ran (no tag created yet)
    if not iter_at_pos.has_tag(spell_tag):
        return  # word is not misspelled — no popover
    # Fetch suggestions and show popover
    suggestions = handler.get_suggestions_at_iter(iter_at_pos)
    def _apply_suggestion(suggestion):
        # Re-derive the iter at the same offset (the original iter may be stale)
        offset = iter_at_pos.get_offset()
        fresh_iter = buf.get_iter_at_offset(offset)
        handler.replace_word_at_iter(fresh_iter, suggestion)
    self._main_content.toolbar.show_suggestions_menu(
        suggestions, _apply_suggestion, parent_widget=text_view
    )

self._main_content.set_on_input_right_click(_on_input_right_click)
```

**API verification:**

- `Gtk.TextView.get_iter_at_location(x, y)` — GTK4 returns `(bool, TextIter)`. Verified: this is the documented GTK4 API (GTK3 returned `None` and modified an iter in-place; GTK4 changed to a tuple return).
- `Gtk.TextIter.has_tag(tag)` — returns bool. Verified standard TextIter API.
- `Gtk.TextBuffer.get_tag_table().lookup("spell-error")` — the tag is created in `InputToolbarHandler._apply_spell_tags` (line 137: `tag = buf.create_tag("spell-error")`). Verified at source.
- `Gtk.TextIter.get_offset()` — returns int offset. Standard API.
- `Gtk.TextBuffer.get_iter_at_offset(offset)` — returns TextIter. Standard API.

**Why a closure inside `__init__`:** This matches the existing `_on_input_buffer_changed` pattern (defined as a local closure at line ~327-330 in `window.py`). Both closures capture `self` (the MainWindow) to access `_main_content` and `_input_toolbar_handler`.

**Estimated lines:** ~30 lines added.

---

### 2.5 Files NOT changed

- **`utils/spellcheck.py`** — already has `get_suggestions()` (line 59) using `enchant-2 -a`. No changes needed.
- **`ui/views/left_panel.py`** — unrelated to input spell check. No changes.
- **`docs/ARCHITECTURE.md`** — §3.9 already describes `MainContent.user_input`. The new GestureClick controller is a minor addition that doesn't warrant a new section. (If desired, a one-line note can be added under §3.9 mentioning right-click spell suggestions, but this is optional and not blocking.)

---

## 3. Data Flow

```
User right-clicks misspelled word in TextView
    ↓
MainContent._on_input_right_click_internal(gesture, n_press, x, y)
    ↓
    (forwards to callback)
    ↓
window.py: _on_input_right_click(n_press, x, y)
    ↓
    TextView.get_iter_at_location(x, y) → (success, TextIter)
    ↓
    TextBuffer.get_tag_table().lookup("spell-error") → tag
    ↓
    TextIter.has_tag(spell_tag) → True/False
    ↓ (True)
InputToolbarHandler.get_suggestions_at_iter(iter)
    ↓
    iter.backward_word_start() / iter.forward_word_end()
    ↓
    buf.get_text(start, end) → "misspeled"
    ↓
utils.spellcheck.get_suggestions("misspeled")
    ↓
    subprocess: enchant-2 -a <<< "misspeled"
    ↓
    ["misspelled", "misspend", "misspent"] (up to 8)
    ↓
ChatInputToolbar.show_suggestions_menu(suggestions, callback, parent_widget=TextView)
    ↓
    Builds Gtk.Popover with suggestion buttons
    ↓
    User clicks "misspelled"
    ↓
    _on_suggestion_clicked(btn, "misspelled", callback, popover)
    ↓
    popover.popdown()
    ↓
    callback("misspelled")
    ↓
window.py: _apply_suggestion("misspelled")
    ↓
    buf.get_iter_at_offset(original_offset) → fresh_iter
    ↓
InputToolbarHandler.replace_word_at_iter(fresh_iter, "misspelled")
    ↓
    fresh_iter.backward_word_start() / forward_word_end()
    ↓
    buf.delete(word_start, word_end)
    ↓
    buf.insert(word_start, "misspelled")
    ↓
    _run_spell_check() (re-runs to update tags)
    ↓
    Red underline removed (word is now correctly spelled)
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `ui/views/main_content.py` | New: callback slot + setter + GestureClick + signal handler | +25 | Low — follows existing GestureClick pattern from same file (tab right-click at line 359) |
| `ui/handlers/input_toolbar_handler.py` | New: `replace_word_at_iter` method | +15 | Low — mirrors `get_suggestions_at_iter` + `replace_current` patterns in same file |
| `ui/views/chat_input_toolbar.py` | Modified: `show_suggestions_menu` signature + popover parent + closed handler | +6 changed | Low — backward-compatible (new param has default); fixes latent popover-leak bug |
| `ui/window.py` | New: right-click wiring closure | +30 | Medium — new wiring code, needs testing |
| **Tests** | | | |
| `tests/test_chat_input_toolbar.py` | New: test for `parent_widget` param | +15 | Low |
| `tests/test_input_toolbar_handler.py` | New: test for `replace_word_at_iter` | +20 | Low |
| `tests/test_window.py` or new `tests/test_spell_suggestion_wiring.py` | New: integration test for right-click → suggestion → replace flow | +30 | Medium |

**Total:** ~140 lines across 5 files (4 product + 1-2 test files).

---

## 5. Implementation Order

### Step 1: `replace_word_at_iter` in handler (no dependencies)
Add `replace_word_at_iter` to `input_toolbar_handler.py`.
**Verify:** Run existing tests in `tests/test_input_toolbar_handler.py` — all must still pass. Add unit test for `replace_word_at_iter`.

### Step 2: `show_suggestions_menu` parent fix in toolbar view (no dependencies)
Modify `show_suggestions_menu` in `chat_input_toolbar.py` to accept `parent_widget=None`.
**Verify:** Run `tests/test_chat_input_toolbar.py` — all existing suggestion tests must still pass.

### Step 3: Right-click GestureClick in MainContent (depends on nothing new)
Add callback slot, setter, GestureClick controller, and internal signal handler to `main_content.py`.
**Verify:** Run `tests/test_main_content.py` (if exists) or smoke-test that app still starts.

### Step 4: Wire in window.py (depends on Steps 1-3)
Add the `_on_input_right_click` closure and wire it via `set_on_input_right_click`.
**Verify:** Run `tests/test_window*.py`. Manual test: right-click a misspelled word → popover appears → click suggestion → word replaced.

### Step 5: Tests
Write and run all tests. Run full selective test suite.

---

## 6. Acceptance Criteria

- [ ] Right-clicking a misspelled word (with spell check ON) shows a popover with up to 8 suggestions
- [ ] Right-clicking a correctly-spelled word shows nothing
- [ ] Right-clicking when spell check is OFF shows nothing
- [ ] Clicking a suggestion replaces the misspelled word with the selected suggestion
- [ ] After replacement, the red underline is removed (spell check re-runs)
- [ ] Popover dismisses on ESC / click-outside without leaking widgets (closed → unparent)
- [ ] All existing tests pass (zero regressions)
- [ ] New unit tests pass: `replace_word_at_iter`, `show_suggestions_menu` with `parent_widget`
- [ ] `input_toolbar_handler.py` has zero `Gtk.*` imports (architecture boundary preserved)

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Right-click on empty TextView | Nothing happens (no word at iter, `get_iter_at_location` returns false) |
| Right-click between words | `inside_word()` returns False → no popover |
| Right-click on a word with no `spell-error` tag | `has_tag(spell_tag)` returns False → no popover |
| Spell check is OFF | Early return at top of `_on_input_right_click` → no popover |
| `enchant-2` not installed | `get_suggestions` returns `[]` → popover shows "(no suggestions)" |
| Misspelled word has zero suggestions | Popover shows "(no suggestions)" label |
| User clicks suggestion after buffer changed (iter stale) | `_apply_suggestion` re-derives iter via `get_iter_at_offset` — safe |
| Right-click fires twice (n_press=2) | `n_press != 1` guard in `_on_input_right_click_internal` → ignored |
| Spell tag not yet created (spell check enabled but no text typed yet) | `tag_table.lookup("spell-error")` returns None → early return |
| Popover already open, user right-clicks another word | Old popover auto-hides (`set_autohide(True)` at line 246); new popover appears |
| Replacement word is still misspelled | `_run_spell_check` re-runs → new underline applied |

---

## 8. ARCHITECTURE.md Updates Required

Optional: Add a one-line note under §3.9 (`MainContent`) mentioning that the input TextView supports right-click spell suggestions via a `GestureClick` controller and callback indirection.

Not blocking. The existing §3.9 description ("`content.user_input` → `Gtk.TextView`") already covers the widget ownership.

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** Yes — verified every function signature, tag name ("spell-error"), method name, and line number against source files read during discovery.

2. **Did I catch all exception types?** The only external call is `get_suggestions()` which already handles `FileNotFoundError`, `TimeoutExpired`, and generic `Exception`. `get_iter_at_location` does not raise. `has_tag` does not raise. No new exception paths.

3. **Did I verify key structures?** Tag name "spell-error" verified in `_apply_spell_tags` (line 137: `buf.create_tag("spell-error")`). `get_iter_at_location` return type verified as GTK4 `(bool, TextIter)` tuple. `_spell_enabled` flag verified at line 37.

4. **Did I trace the data flow end-to-end?** Yes — Section 3 traces from user click through to final tag update, naming every function and its source location.

5. **Would an implementer following this spec exactly produce working code?** Yes — all API references verified, all line numbers current, all patterns traced to existing code in the same files.
