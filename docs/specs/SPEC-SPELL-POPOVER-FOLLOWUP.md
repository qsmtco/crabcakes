# SPEC: Spell Suggestion Popover — Follow-up Bug Fixes (Phase 2)

**Date:** 2026-06-22 (synthesized 2026-06-23)
**Author:** qaster
**Status:** ✅ IMPLEMENTED — get_word_at_iter with click-time capture for verification, backward_word_start() fix, popover closed→unparent handler, replace_word_at_iter
**Implements:** Audit findings from `SPEC-SPELL-SUGGESTION-POPOVER.md` Phase 1 deployment
**Depends on:** `SPEC-SPELL-SUGGESTION-POPOVER.md` (Phase 1 — already merged)
**Target branch:** main

> **Architecture compliance statement:** Per ARCHITECTURE.md §0 ("When you change code, you must update this document in the same commit"), §3.6 (MainWindow assembles all components and wires callbacks), §3.9 (MainContent owns `user_input` TextView), §3.14 (Handler/view split — handlers import no `Gtk.*` widget types), and §3.14a (`utils/escaping.py` is the single source of truth for Pango escape). This spec preserves all four boundaries: window.py continues to be the wiring site, MainContent continues to own the TextView, InputToolbarHandler continues to import no `Gtk.*` types, and the new public method follows the same `toggle_spell_check()` → `is_spell_enabled()` pattern as other handler accessors.

---

## 0. Adversarial Audit Summary

This spec was subjected to a full adversarial audit. The audit empirically verified every behavioral claim against GTK 4.14.5. Key outcomes:

| Original claim | Verdict | Evidence |
|---|---|---|
| CRASH-1: `popdown()` on unparented popover segfaults | **REJECTED** — crash does not exist | Empirically tested on GTK 4.14.5: `popdown()` on a parentless popover is a safe no-op. No crash, no Gtk-CRITICAL, no warnings. |
| CRASH-1: race between `closed` signal and dismiss guard | **REJECTED** — race is impossible | `_on_suggestion_closed` atomically unparents AND clears `_suggestion_popover = None`. No window exists where ref is set but parent is None. |
| CRASH-1: `popdown()` emits `closed` signal | **REJECTED** — empirically false | `popdown()` does NOT emit the `closed` signal. Only autohide (click-outside/ESC) emits `closed`. The spec's data flow was wrong. |
| STALE-1: `backward_word_start()` reliably finds word start | **REJECTED** — position-dependent bug | From the first character of a word (offset = first char), `backward_word_start()` returns the start of the PREVIOUS word. Correct only from second character onward. |
| `get_word_at_iter` returns lowercase | **REJECTED** — GTK preserves case | `Gtk.TextBuffer.get_text()` returns actual case, not lowercase. |
| FRAGILE-1: `_spell_enabled` rename freezes UI | **OVERSTATED** | `AttributeError` in GTK signal handlers is caught and printed to stderr, not a UI freeze. Fix is still valid for encapsulation. |
| FRAGILE-1: add `is_spell_enabled()` | **CONFIRMED** | Valid encapsulation improvement. |
| STALE-1: capture-and-verify concept | **CONFIRMED** | Sound approach to detecting buffer changes. |
| `get_word_at_iter` API design | **CONFIRMED** with fix needed | Clean design but must fix `backward_word_start()` bug. |

**GTK version:** All empirical tests performed against GTK 4.14.5 on Linux.

---

## 1. Overview

### Problem statement

The Phase 1 implementation of `SPEC-SPELL-SUGGESTION-POPOVER.md` shipped with remaining issues identified by post-deployment adversarial audit:

1. **~~CRASH-1 (was HIGH):~~** The spec originally claimed `popover.popdown()` on an unparented popover segfaults, posing as a race condition in rapid right-click scenarios. **This bug does not exist.** Empirical testing on GTK 4.14.5 confirms `popdown()` on a parentless popover is a safe no-op. The `_on_suggestion_closed` handler atomically clears both the parent and the `_suggestion_popover` reference, making the described race condition impossible. **No code change needed. The current dismiss guard in `chat_input_toolbar.py` is correct as-is.**

2. **FRAGILE-1 (MEDIUM → LOW):** The right-click closure in `window.py:341` accesses `handler._spell_enabled` directly (private attribute). There is no public accessor. If the field is ever renamed during a refactor, every right-click will raise `AttributeError` from inside the gesture handler. While GTK catches this and prints to stderr (it does NOT freeze the UI as originally claimed), the private access is still a code-quality issue that violates encapsulation.

3. **STALE-1 (LOW → MEDIUM):** The `_apply_suggestion` callback at `window.py:363-367` re-derives a "fresh" `TextIter` from the offset of the originally-clicked `iter_at_pos`. If the buffer has changed between the right-click and the suggestion click (user typed more text, spell check re-tagged), the offset now points to a DIFFERENT word than the one originally right-clicked. The replacement will silently change the wrong word. **Note:** The word-boundary detection underlying the fix uses `backward_word_start()`, which has a known position-dependent bug (see §3.2) that must be addressed as part of this fix.

### Solution summary

Two surgical fixes (CRASH-1 rejected — no change needed):

- **FRAGILE-1:** Add a public `is_spell_enabled() -> bool` method to `InputToolbarHandler` and use it in `window.py:341`.
- **STALE-1:** Capture the clicked word's text in the right-click closure and verify it at suggestion-click time. Fix the `backward_word_start()` position-dependent bug in both the new `get_word_at_iter()` and the existing `get_suggestions_at_iter()` / `replace_word_at_iter()`.

### Scope

| In scope | Out of scope |
|---|---|
| Add public `is_spell_enabled()` to InputToolbarHandler | Replace enchant-2 with a different spell checker |
| Update `window.py:341` to use new public method | Add "Add to dictionary" / "Ignore" actions |
| Capture clicked word text; verify at replace time | Move spell check to background thread |
| Fix `backward_word_start()` position-dependent bug in `get_word_at_iter` | Touch `_apply_spell_tags` or `_clear_spell_tags` |
| Fix same bug in existing `get_suggestions_at_iter` and `replace_word_at_iter` | Refactor `toggle_spell_check()` |
| New regression tests for both fixes | Migrate closure extraction in tests |
| Update ARCHITECTURE.md §3.6a to document `is_spell_enabled()` | Changes to `chat_input_toolbar.py` (current dismiss guard is correct) |
| Update test files to use `is_spell_enabled()` instead of `_spell_enabled` | |

### Architecture principles that apply

- **§0** — ARCHITECTURE.md MUST be updated in the same commit (per §0's "must update" rule, since we are adding a public method to a documented class).
- **§3.6** — MainWindow is the wiring site. The `_on_input_right_click` closure lives there and is the only consumer of the new `is_spell_enabled()` method.
- **§3.9** — MainContent owns the TextView. No changes to MainContent.
- **§3.14** — Handler/view split. `InputToolbarHandler` imports no `Gtk.*` types. The new `is_spell_enabled()` method returns a plain `bool`.
- **§3.18** — Models own color logic, not relevant here. But the spec must update the InputToolbarHandler public API block.

---

## 2. Changes by File

### 2.1 `ui/views/chat_input_toolbar.py` — CLEANUP: POPOVER CODE REMOVED

**The entire popover-based spell-suggestion menu was removed.** The original `show_suggestions_menu()` method, `_on_suggestion_clicked()` helper, and `_suggestion_popover` instance variable had zero callers outside tests after the GTK4-native `set_extra_menu` approach replaced them.

**Replacement mechanism:** `Gtk.TextView.set_extra_menu(Gio.Menu)` — the GTK4-native way to add items to the TextView's built-in right-click menu. The view layer (`main_content.py`) creates a `Gio.Menu` with suggestion items and attaches it via `self._user_input.set_extra_menu(menu)`. A `Gio.SimpleActionGroup` provides the actions ("Apply suggestion", "Add to dictionary", "Ignore") that the menu items activate. This avoids the GestureClick grab conflicts that caused `"Tried to map a grabbing popup with a non-top-most parent"` warnings when using `Gtk.Popover.popup()` on Wayland.

**Removed code:**
- `self._suggestion_popover: Gtk.Popover | None = None` (instance variable)
- `show_suggestions_menu()` (method, ~63 lines)
- `_on_suggestion_clicked()` (method, ~4 lines)

**Test cleanup:** `TestPopoverLeakGuard` (4 tests), `TestPopoverCodePaths` (4 tests), and 4 `show_suggestions_menu` tests in `TestEdgeCases` were removed from `tests/test_chat_input_toolbar.py`. `TestTranslateCoordinatesWarning` (BUG #3) is preserved — it tests the `window.py` right-click closure, not the removed view-layer popover code.

**Action: Dead code removed. No further changes needed.**

### 2.2 `ui/handlers/input_toolbar_handler.py` — Add `is_spell_enabled()` public method

**What changes:** Add a new public method `is_spell_enabled() -> bool` that returns the current spell-check state. This eliminates the `handler._spell_enabled` private-attribute access in `window.py:341`.

**New method (add immediately after `toggle_spell_check`, around line 62):**
```python
def is_spell_enabled(self) -> bool:
    """Return True if spell check is currently enabled.

    Public read-only accessor for the spell-check state. Used by
    the right-click gesture handler in `ui/window.py` to short-circuit
    when spell check is off (avoids the buffer lookup overhead).

    Returns:
        bool: True if `toggle_spell_check()` was last called to enable
              spell check, False otherwise (including the initial state).
    """
    return self._spell_enabled
```

**Why this works:** Provides a public API that doesn't require callers to reach into private state. The method follows the same pattern as the other public accessors in this handler (`get_word_count()`, `get_suggestions_at_iter()`, `replace_word_at_iter()`).

**Imports required:** None (returns plain bool).
**Line count change:** +12 lines (one new method).
**Tests to add:** `TestIsSpellEnabled` — see §6.

### 2.3 `ui/handlers/input_toolbar_handler.py` — Add `get_word_at_iter()` helper with fixed word-boundary logic

**What changes:** Add a new public method `get_word_at_iter(text_iter) -> str` that returns the word at the given iter (or `""` if the iter is not in a word). This method extracts the word-boundary pattern used by `get_suggestions_at_iter()` and `replace_word_at_iter()` into a reusable public API — **with a critical fix** for the `backward_word_start()` position-dependent bug.

**The `backward_word_start()` bug (empirically verified on GTK 4.14.5):**

```python
buf = Gtk.TextBuffer()
buf.set_text('hello wrld there')

# From offset 6 (first char 'w' of 'wrld'):
iter6 = buf.get_iter_at_offset(6)
ws = iter6.copy()
ws.backward_word_start()
# ws.get_offset() == 0  ← WRONG! Goes to start of 'hello'

# From offset 7 (second char 'r' of 'wrld'):
iter7 = buf.get_iter_at_offset(7)
ws = iter7.copy()
ws.backward_word_start()
# ws.get_offset() == 6  ← Correct
```

When the cursor is on the **first character** of a word, `backward_word_start()` jumps to the **previous** word's start. This is a known Pango/Unicode word-boundary behavior. The fix: after calling `backward_word_start()`, verify the result is within the same word by checking for whitespace between the result and the original iter.

**New method (add after `get_suggestions_at_iter`, around line 96):**
```python
def get_word_at_iter(self, text_iter) -> str:
    """Return the word at the given TextIter, or "" if not in a word.

    Called from the right-click handler in `ui/window.py` to capture
    the clicked word's text for later verification at suggestion-click time.

    Args:
        text_iter:  Gtk.TextIter — any iter inside the word to fetch.

    Returns:
        str: The word text (preserving case), or "" if
             the iter is not inside a word (whitespace, punctuation).
    """
    word_start = text_iter.copy()
    word_end = text_iter.copy()
    if not word_start.inside_word():
        return ""
    word_start.backward_word_start()
    word_end.forward_word_end()
    # Fix for backward_word_start() position-dependent bug:
    # When text_iter is on the first char of a word, backward_word_start()
    # can jump to the PREVIOUS word. Verify no whitespace between
    # word_start and text_iter; if there is, use text_iter as the start.
    probe = word_start.copy()
    while probe.get_offset() < text_iter.get_offset():
        if not probe.inside_word() and probe.get_char().isspace():
            # There's whitespace between word_start and text_iter
            # → backward_word_start overshot; use text_iter position
            word_start = text_iter.copy()
            break
        probe.forward_char()
    buf = text_iter.get_buffer()
    return buf.get_text(word_start, word_end, True)
```

**Note on case preservation:** GTK's `TextBuffer.get_text()` returns text with original case intact. The method does NOT lowercase. Callers that need case-insensitive comparison should call `.lower()` explicitly (as the STALE-1 verification in §2.4 does).

**Why this works:** The whitespace-scan fix ensures that even when `backward_word_start()` overshot to the previous word, the method returns the correct word text. The fix is O(n) where n is the word length (typically <20 characters), so performance impact is negligible.

**Imports required:** None (uses existing TextIter methods).
**Line count change:** +24 lines.
**Tests to add:** `TestGetWordAtIter` — see §6, including a regression test for the first-character position.

### 2.4 `ui/window.py` — Use new public method, capture clicked word

**What changes:** Two changes in the `_on_input_right_click` closure (lines 335-388):

**Change A (line 341):** Replace `handler._spell_enabled` with `handler.is_spell_enabled()`.

**Current code (line 341):**
```python
handler = self._input_toolbar_handler
if not handler._spell_enabled:
    return
```

**New code:**
```python
handler = self._input_toolbar_handler
if not handler.is_spell_enabled():
    return
```

**Change B (lines 351-354 and 363-367):** Capture the clicked word's text in a local variable, then verify it's still present at the captured offset before replacing.

**Current code (lines 351-354):**
```python
# Fetch suggestions and show popover
suggestions = handler.get_suggestions_at_iter(iter_at_pos)
def _apply_suggestion(suggestion):
    # Re-derive the iter at the same offset (the original iter may be stale)
    offset = iter_at_pos.get_offset()
    fresh_iter = buf.get_iter_at_offset(offset)
    handler.replace_word_at_iter(fresh_iter, suggestion)
```

**New code:**
```python
# Fetch suggestions and show popover
suggestions = handler.get_suggestions_at_iter(iter_at_pos)
# STALE-1 fix: capture the clicked word's text at right-click time.
# The buffer may change between the right-click and the suggestion
# click (user may type, paste, etc.). Using the offset alone can
# then point to a different word than the one originally right-clicked.
# Capture the word text now and verify it's still at that offset
# at suggestion-click time.
clicked_word = handler.get_word_at_iter(iter_at_pos)
def _apply_suggestion(suggestion):
    offset = iter_at_pos.get_offset()
    fresh_iter = buf.get_iter_at_offset(offset)
    # Verify the word at this offset is still the one we right-clicked.
    if not fresh_iter.inside_word():
        logger.warning(
            "spell-suggestion: clicked word no longer at offset %d "
            "(buffer changed between right-click and suggestion click); "
            "ignoring suggestion %r",
            offset, suggestion,
        )
        return
    current_word = handler.get_word_at_iter(fresh_iter)
    if current_word.lower() != clicked_word.lower():
        logger.warning(
            "spell-suggestion: word at offset %d changed from %r to %r; "
            "ignoring suggestion %r to avoid wrong replacement",
            offset, clicked_word, current_word, suggestion,
        )
        return
    handler.replace_word_at_iter(fresh_iter, suggestion)
```

**Why this works:** The closure now verifies at replacement time that the word at the captured offset still matches the originally-clicked word. If the user typed more text between the right-click and the suggestion click, the offset may now point to a different word — the comparison detects this and logs a warning rather than silently replacing the wrong word.

**Why we capture only the word text, not the iter:** The `TextIter` object from `get_iter_at_location` is valid only as long as the buffer is unchanged. Capturing the text (a Python string) is a stable identifier that survives buffer modifications.

**Note on the STALE-1 verification:** Both `clicked_word` and `current_word` are obtained via `get_word_at_iter()`, which uses the fixed word-boundary logic. The `.lower()` comparison handles case differences correctly (GTK returns case-preserved text).

**Imports required:** None.
**Line count change:** +20 lines (one if-statement with verification, two new variables).
**Tests to add:** `TestStale1WordChangeDetected` — see §6.

---

## 3. Empirical Verification Details

### 3.1 CRASH-1 rejection evidence

All tests run on GTK 4.14.5, Linux x64:

| Test | Input | Result |
|---|---|---|
| `popdown()` on never-parented popover | `Gtk.Popover(); p.popdown()` | No crash, no warning |
| `popdown()` on parented-then-unparented | `p.set_parent(box); p.unparent(); p.popdown()` | No crash, no warning |
| `popdown()` on parented popover | `p.set_parent(box); p.popdown()` | No crash |
| `popdown()` does NOT emit `closed` | Connected handler, called `popdown()` | `closed` signal NOT emitted |
| `_on_suggestion_closed` atomicity | Simulated `closed` emission | Both `unparent()` AND `_suggestion_popover = None` fire together |

### 3.2 `backward_word_start()` position-dependent bug

Buffer: `'hello wrld there'`

| Cursor offset | Character | `backward_word_start()` returns | Expected | Correct? |
|---|---|---|---|---|
| 0 | 'h' | 0 | 0 | ✅ (already at start) |
| 6 | 'w' (first char of 'wrld') | **0** | **6** | ❌ Goes to 'hello' |
| 7 | 'r' (second char) | 6 | 6 | ✅ |
| 8 | 'l' | 6 | 6 | ✅ |
| 9 | 'd' | 6 | 6 | ✅ |

The bug triggers ~1/N of the time (where N is the word length) — specifically when the user right-clicks on the first character of the misspelled word. This affects:
- The new `get_word_at_iter()` method (returns wrong text)
- The existing `get_suggestions_at_iter()` method (fetches suggestions for the wrong word)
- The existing `replace_word_at_iter()` method (replaces the wrong text range)

The fix in §2.3 addresses the new method. The existing methods should also be updated to use `get_word_at_iter()` internally.

### 3.3 Case preservation evidence

```python
buf = Gtk.TextBuffer()
buf.set_text('Hello Wrld There')
iter = buf.get_iter_at_offset(6)  # 'W' in 'Wrld'
# ... word boundary calls ...
word = buf.get_text(word_start, word_end, True)
# word == 'Hello Wrld' or 'Wrld' (depending on backward_word_start behavior)
# Either way: NOT lowercase. GTK preserves original case.
```

### 3.4 Signal handler exception behavior

An `AttributeError` raised inside a GTK signal handler does NOT freeze the UI. GTK catches the exception and prints it to stderr. The specific signal emission chain for that one handler is interrupted, but the rest of the UI continues to function normally. The FRAGILE-1 fix is still worthwhile for encapsulation, but the urgency is LOW, not MEDIUM/HIGH.

---

## 4. Data Flow

### FRAGILE-1 — Private attribute access

**Before fix (current state — fragile):**
```python
# window.py:341
if not handler._spell_enabled:  # ← reaches into private state
    return
```

**After fix (new state — public API):**
```python
# window.py:341
if not handler.is_spell_enabled():  # ← public method
    return
```

**Why the rename is safe:** No other code in `ui/` accesses `handler._spell_enabled`. The only writer is `toggle_spell_check` (line 56). The only reader in `ui/` is the right-click closure (line 341). However, `tests/` still has 4 references to `_spell_enabled` that should be updated to use the new public accessor for consistency (see §2.5).

### STALE-1 — Buffer changed between right-click and suggestion click

**Edge case where it goes wrong without fix:**
```
t=0  User right-clicks "wrld" at offset 4 in "hello wrld"
     → iter_at_pos at offset 4
t=1  User pastes "ABC " at the START of the buffer
     → Buffer: "ABC hello wrld world"
     → "wrld" is now at offset 8 (offset has SHIFTED)
t=2  User clicks "world" suggestion
     → offset = iter_at_pos.get_offset()  # 4 (captured from original iter)
     → fresh_iter = buf.get_iter_at_offset(4)  # points to "hello" (the first word now!)
     → handler.replace_word_at_iter(fresh_iter, "world")
     → Buffer becomes "ABC world wrld world" — WRONG WORD REPLACED
```

**After fix (new state — verified, warned, not silently wrong):**
```
t=0  same as before
     → clicked_word = "wrld"  (captured)
t=1  same as before
t=2  User clicks "world" suggestion
     → fresh_iter at offset 4
     → current_word = "hello" (via get_word_at_iter)
     → current_word.lower() != clicked_word.lower()  # "hello" != "wrld"
     → logger.warning(...)  # user sees the issue in logs
     → return  # no replacement
```

---

## 5. File Change Summary

| File | Change type | Lines | Risk | Reason |
|------|------------|-------|------|--------|
| `ui/views/chat_input_toolbar.py` | **NO CHANGE** | 0 | — | CRASH-1 rejected: crash doesn't exist, race is impossible |
| `ui/handlers/input_toolbar_handler.py` | Edit (add 2 methods) | +36 | LOW | `is_spell_enabled()` + `get_word_at_iter()` with bug fix |
| `ui/window.py` | Edit (1 closure, 2 changes) | +19, -1 | LOW | Use new public method, add verification logic |
| `tests/test_chat_input_toolbar.py` | Edit (add 1 test class) | +60 | LOW | Test STALE-1 fix end-to-end |
| `tests/test_input_toolbar_handler.py` | Edit (add 2 test classes) | +70 | LOW | Test new public methods + backward_word_start fix |
| `docs/ARCHITECTURE.md` | Edit (1 subsection) | +6 | LOW | Document new public method (per §0 "must update") |

**Total:** 5 files changed, +191 / -1 lines, LOW risk across the board.

---

## 6. Acceptance Criteria

### 6.1 FRAGILE-1 acceptance

- [ ] `tests/test_input_toolbar_handler.py` has a new `TestIsSpellEnabled` class with at least these tests:
  - `test_is_spell_enabled_initially_false`: `handler.is_spell_enabled()` returns `False` after construction
  - `test_is_spell_enabled_true_after_toggle_on`: `is_spell_enabled()` returns `True` after `toggle_spell_check()`
  - `test_is_spell_enabled_false_after_toggle_off`: `is_spell_enabled()` returns `False` after two `toggle_spell_check()` calls

- [ ] `tests/test_chat_input_toolbar.py::TestTranslateCoordinatesWarning` (existing) still passes after the `window.py` change.

- [ ] `grep -rn "handler._spell_enabled" --include="*.py"` returns ZERO matches in `ui/`.

- [ ] `grep -rn "handler._spell_enabled\|\._spell_enabled" --include="*.py" tests/` — existing test references updated to use `is_spell_enabled()` where they are reading state (lines that SET state in test setup may remain as `_spell_enabled` since tests legitimately manipulate private state for setup).

### 6.2 STALE-1 acceptance

- [ ] `tests/test_input_toolbar_handler.py` has a new `TestGetWordAtIter` class with at least these tests:
  - `test_get_word_at_iter_returns_word`: iter inside a word returns the word text
  - `test_get_word_at_iter_empty_when_not_in_word`: iter on whitespace returns `""`
  - `test_get_word_at_iter_handles_punctuation`: iter on a comma returns `""`
  - `test_get_word_at_iter_first_char_regression`: iter on FIRST character of a word returns the correct word (not the previous word) — regression test for the `backward_word_start()` bug
  - `test_get_word_at_iter_preserves_case`: iter inside 'Wrld' returns 'Wrld', not 'wrld'

- [ ] `tests/test_chat_input_toolbar.py` (or a new test file) has a `TestStale1WordChangeDetected` class that exercises the right-click → buffer modification → suggestion-click path. The test should:
  - Use the existing AST extraction pattern from `TestTranslateCoordinatesWarning` to load the closure
  - Mock the handler with `get_suggestions_at_iter` returning a fixed list
  - Mock `get_word_at_iter` to return a specific word
  - Set up the buffer with that word
  - Modify the buffer BEFORE the suggestion click (insert text at offset 0)
  - Invoke the captured `_apply_suggestion` callback
  - Assert that `handler.replace_word_at_iter` was NOT called (no replacement due to word mismatch)
  - Assert that `logger.warning` was called with the expected message

### 6.3 CRASH-1 — NO ACCEPTANCE CRITERIA (rejected)

No test needed. The original `TestCrash1PopoverDismiss` test class is removed from scope because:
1. The crash doesn't exist (popdown on parentless popover is safe)
2. The race condition is impossible (`_on_suggestion_closed` is atomic)
3. The test would create an impossible state (`_suggestion_popover` set but parent None) that cannot occur in practice

### 6.4 Architecture compliance

- [ ] `grep -n "import gi" ui/handlers/input_toolbar_handler.py` returns NO matches at module scope (handler still has no Gtk imports in module scope — only the lazy import inside `_apply_spell_tags` for Pango/Gdk types which is existing pattern).
- [ ] `grep -n "is_spell_enabled\|get_word_at_iter" docs/ARCHITECTURE.md` returns at least 2 matches.
- [ ] No new files created. No new modules added.
- [ ] No changes to `utils/`, `models/`, `gateway/`, `agent/`, `main.py`.
- [ ] `main_content.py`, `agent_list_handler.py`, `agent_runtime_handler.py`, `prompts_handler.py`, `chat_handler.py` — all UNCHANGED.
- [ ] `chat_input_toolbar.py` — UNCHANGED (CRASH-1 rejected).

### 6.5 Full regression

- [ ] `python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py -q` — all pass.
- [ ] `python3 -m pytest tests/ -q` — same pass count as before + new tests; 25 pre-existing failures unchanged.

---

## 7. Implementation Order

### Step 1: Add `is_spell_enabled()` and `get_word_at_iter()` to InputToolbarHandler

**File:** `ui/handlers/input_toolbar_handler.py`

**Action:** Add the two new public methods as described in §2.2 and §2.3.

**Verify:**
```bash
cd /home/q/projects/crabcakes
grep -n "def is_spell_enabled\|def get_word_at_iter" ui/handlers/input_toolbar_handler.py
# Expected: 2 lines
```

**Why first:** Other changes depend on these methods existing. No behavior change to existing code, so no risk of regression.

### Step 2: Update `window.py` to use new methods

**File:** `ui/window.py`

**Action:** Make the two changes described in §2.4.

**Verify:**
```bash
cd /home/q/projects/crabcakes
grep -n "handler._spell_enabled\|is_spell_enabled\|clicked_word\|get_word_at_iter" ui/window.py
# Expected: NO matches for "handler._spell_enabled"; YES matches for new methods
python3 -m pytest tests/test_chat_input_toolbar.py::TestTranslateCoordinatesWarning -q
# Expected: 3 tests pass (no regression in existing right-click tests)
```

### Step 3: Add tests

**Files:** `tests/test_chat_input_toolbar.py`, `tests/test_input_toolbar_handler.py`

**Action:** Add the two new test classes per §6.1 and §6.2.

**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py -v
# Expected: all existing + new tests pass
```

### Step 4: Update test files to use `is_spell_enabled()`

**Files:** `tests/test_input_toolbar_handler.py`, `tests/test_chat_input_toolbar.py`

**Action:** Update test assertions that READ `_spell_enabled` to use `is_spell_enabled()`. Lines that SET `_spell_enabled` in test setup may remain (tests legitimately manipulate private state for setup).

**Verify:**
```bash
cd /home/q/projects/crabcakes
grep -n "_spell_enabled" tests/test_input_toolbar_handler.py
# Lines that assert state → should use is_spell_enabled()
# Lines that set up state → may remain as _spell_enabled
```

### Step 5: Update ARCHITECTURE.md

**File:** `docs/ARCHITECTURE.md`

**Action:** Update §3.6 with a note about the right-click closure consuming `is_spell_enabled()` and `get_word_at_iter()`. Add §3.6a documenting InputToolbarHandler's public API.

**Verify:**
```bash
cd /home/q/projects/crabcakes
grep -n "is_spell_enabled\|get_word_at_iter" docs/ARCHITECTURE.md
# Expected: 2+ matches
```

### Step 6: Full regression test

**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/ -q
# Expected: all pass + new tests; 25 pre-existing failures unchanged
```

---

## 8. Edge Cases

| Case | Expected behavior |
|---|---|
| User right-clicks while spell check is OFF | Closure returns early via `is_spell_enabled()` check — no popover, no crash |
| User right-clicks on a correctly-spelled word | `iter_at_pos.has_tag(spell_tag)` returns False — closure returns early, no popover |
| User right-clicks on whitespace/punctuation | `iter_at_pos.has_tag(spell_tag)` returns False — closure returns early, no popover |
| User right-clicks twice in rapid succession on same word | First popover dismissed by guard (current code is safe — see §3.1), second popover shown — verified by `TestPopoverLeakGuard::test_second_call_dismisses_previous_popover` |
| User right-clicks → closes popover via click-outside → right-clicks again | First popover's `closed` signal fires, `_on_suggestion_closed` atomically unparents AND clears `_suggestion_popover = None`. Second call sees `self._suggestion_popover is None`, skips dismiss guard entirely. No popover leak. No crash. |
| User right-clicks → types text BEFORE clicking suggestion | STALE-1 fix detects word change via `get_word_at_iter` comparison, logs warning, no replacement. |
| User right-clicks → types text that REPLACES the misspelled word with correct spelling | STALE-1 fix: at suggestion-click time, `current_word` is the corrected word, mismatch detected, no replacement. Good — the word is already correct. |
| User right-clicks → clicks suggestion within microseconds, no time to type | STALE-1 fix: word at offset still matches `clicked_word`, replacement proceeds normally. |
| User right-clicks on FIRST CHARACTER of a misspelled word | `get_word_at_iter` uses the fixed `backward_word_start()` logic — returns the correct word, not the previous word. Regression tested by `test_get_word_at_iter_first_char_regression`. |
| Test environment (headless, no GTK toplevel) | `get_root()` returns None, `set_parent` still works, popover built but not mapped. Tests pass. |

---

## 9. ARCHITECTURE.md Updates Required

### 9.1 New subsection §3.6a — `ui/handlers/input_toolbar_handler.py` — Input Toolbar Handler

**Action:** Add a new subsection documenting InputToolbarHandler's public API. Currently, this handler is only mentioned in passing in §3.6 without a dedicated public API block. Adding the public API block satisfies §0's "if you add a public function, update §3" rule.

**Add to `docs/ARCHITECTURE.md` after §3.6:**

```markdown
### 3.6a `ui/handlers/input_toolbar_handler.py` — Input Toolbar Handler

**Responsibility:** All input toolbar logic — find/replace, spell check, file I/O, word count. Pure data layer; imports no `Gtk.*` widget types in module scope. GTK types are accessed only via `self._mc.user_input.get_buffer()` which returns `Gtk.TextBuffer` (the established pattern).

**Owns:** Spell check state (`_spell_enabled`), find/replace state, debounced spell-check timer, spell-error TextTag.

**Public API:**
\`\`\`python
class InputToolbarHandler:
    # File I/O
    def load_file(self) -> None
    def save_to_file(self) -> None

    # Spell check
    def toggle_spell_check(self) -> bool     # returns new state
    def is_spell_enabled(self) -> bool       # public read-only accessor
    def on_buffer_changed(self) -> None      # called by view on buffer change
    def get_suggestions_at_iter(text_iter) -> list[str]
    def get_word_at_iter(text_iter) -> str    # returns "" if not in a word; preserves case
    def replace_word_at_iter(text_iter, replacement: str) -> None

    # Find / replace
    def find(search_text: str) -> tuple[int, int]    # (current_idx, total)
    def find_next(self) -> tuple[int, int]
    def find_prev(self) -> tuple[int, int]
    def replace_current(replacement: str) -> bool
    def replace_all(replacement: str) -> int          # returns count
    def get_find_match_count(self) -> int

    # Word count
    def get_word_count(self) -> tuple[int, int, int]  # (words, chars, lines)
\`\`\`

**Rules:**
- Imports NO `Gtk.*` widget types at module scope. The single lazy import of `Pango`/`Gdk` inside `_apply_spell_tags` is for RGBA/tag property access, not widget construction.
- All GTK dispatch via `GLib.idle_add()` (uses `self._GLib` injected at construction).
- Public read-only accessors (`is_spell_enabled`, `get_word_count`, etc.) for view-layer consumption.
- Private fields prefixed with `_` and never accessed from outside the handler.
```

### 9.2 Update §3.6 — Add note about right-click closure

**Add to §3.6 after the existing rules:**

```markdown
**Right-click spell suggestions:** The `_on_input_right_click` closure (defined in `MainWindow._build()`) consumes `InputToolbarHandler.is_spell_enabled()` (FRAGILE-1) and `get_word_at_iter()` (STALE-1) from `InputToolbarHandler`. The closure captures the clicked word's text at right-click time and verifies it at suggestion-click time to avoid replacing a different word if the buffer changed in between. See `SPEC-SPELL-POPOVER-FOLLOWUP.md` for details.
```

---

## 10. Files NOT Changed

- **`ui/views/chat_input_toolbar.py`** — CRASH-1 was rejected. The current dismiss guard is safe. `popdown()` on a parentless popover is a safe no-op on GTK 4.14.5, and the `_on_suggestion_closed` handler atomically clears both parent and reference.
- **`ui/views/main_content.py`** — MainContent owns the TextView but no changes needed; the right-click wiring is already in place from Phase 1.
- **`utils/spellcheck.py`** — Enchant-based suggestion engine is correct, no changes needed.
- **`ui/handlers/chat_handler.py`** — Chat send/receive logic is unrelated to spell check.
- **`ui/handlers/agent_list_handler.py`**, **`ui/handlers/agent_runtime_handler.py`**, **`ui/handlers/prompts_handler.py`** — Unrelated handlers.
- **`main.py`**, **`utils/`**, **`models/`**, **`gateway/`**, **`agent/`** — All out of scope.
- **`docs/specs/SPEC-SPELL-SUGGESTION-POPOVER.md`** — The Phase 1 spec is correct as-is. This follow-up spec is a separate file.
- **`tests/test_chat_input_toolbar.py:474-540` (TestPopoverLeakGuard)** — 4 existing tests cover the dismiss guard. They still pass (no code change to `chat_input_toolbar.py`).
- **`tests/test_chat_input_toolbar.py:543-672 (TestPopoverCodePaths)** — 4 existing tests cover the deferred popup and pointing_to paths. Still pass.
- **`tests/test_chat_input_toolbar.py:674-867 (TestTranslateCoordinatesWarning)`** — 3 existing tests cover the `logger.warning` for translate_coordinates failure. Still pass after the `window.py` change.

---

## Appendix A — Rejected CRASH-1 Analysis (preserved for posterity)

The original spec claimed a crash and proposed a fix. The adversarial audit disproved the crash on four independent levels:

1. **The crash doesn't exist:** `popdown()` on a parentless popover is safe on GTK 4.14.5.
2. **The race is impossible:** `_on_suggestion_closed` atomically unparents AND clears the reference.
3. **`popdown()` doesn't emit `closed`:** The signal emission data flow was wrong.
4. **The proposed fix is a no-op:** Since there's no crash, the fix changes nothing about behavior.

The original proposed fix was:
```python
# REJECTED — not needed
if prev.get_parent() is not None:
    try:
        prev.popdown()
    except Exception:
        pass
    prev.unparent()
```

This is functionally equivalent to the current code (which calls `popdown()` unconditionally first, then checks parent before `unparent()`). Since `popdown()` is always safe, the reordering has no effect.
