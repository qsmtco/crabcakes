# TOOLBAR-PHASE-8-INSTRUCTIONS.md

PHASE 8 — Wire the input buffer's `changed` signal to the handler + word count

This is a **bug-fix phase**, not a new feature. The toolbar's word/char count label has been broken since Phase 4 because the input buffer's `changed` signal is never connected. Phases 6 and 7 cleaned up the dead `ChatControlBar` code path; this phase makes the count actually update.

## Master Spec

`docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md`:

- **Section 2.4** (`ui/views/main_content.py` — MODIFIED) — explicitly says to add:
  > Add a buffer-changed signal emission so the handler can debounce spell checks:
  > ```python
  > buf = self._user_input.get_buffer()
  > buf.connect("changed", self._on_input_buffer_changed)
  > ```
  This was never implemented. Phase 4 added the toolbar and the handler but skipped the buffer-changed wiring.

## The bug

Symptom: the toolbar's word/char count label reads "0 words · 0 chars" regardless of what the user types.

Root cause: chain of three missing wires.

1. **`main_content.py` never connects `buf.connect("changed", ...)`** — the input buffer's `changed` signal has no listener in production code.
2. **`input_toolbar_handler.py::on_buffer_changed()` is never called** — and even if it were, it only handles spell check (early-returns if `_spell_enabled` is False), not word count.
3. **No production code calls `ChatInputToolbar.update_word_count()`** — the method exists in the view (`chat_input_toolbar.py:214`) and the handler has `get_word_count()` (`input_toolbar_handler.py:394`), but nothing bridges them.

## Architecture constraint (read this carefully)

**The handler must NOT get a reference to the toolbar view.** The handler file's docstring explicitly states: *"No GTK imports — all GTK dispatch via GLib.idle_add callbacks. Follows the same pattern as MediaHandler."* The handler is controller logic; the view is display logic. The wiring layer (`window.py`) is the bridge.

If you find yourself adding a `toolbar_view` parameter to `InputToolbarHandler.__init__`, **stop and re-read this section**. The fix shape below does not require it.

## Files to change (3)

1. **`ui/views/main_content.py`** — add the buffer-changed signal wiring (matches existing pattern in this file: project_settings, feed_bar, etc.)
2. **`ui/handlers/input_toolbar_handler.py`** — modify `on_buffer_changed()` to keep the spell-check debounce, plus add a separate public method for computing the count (handler returns the data; wiring layer pushes it to the view)
3. **`ui/window.py`** — replace the dead `set_on_buffer_changed` wiring (line 288) with a real bridge that subscribes to `main_content`'s buffer-changed signal and routes to both the handler (spell check) and the toolbar view (count label)

## Edits (in order — read each file BEFORE editing)

### Edit 1: `ui/views/main_content.py` — add buffer-changed signal wiring

**Where:** find the block where `self._user_input = Gtk.TextView()` is created (around line 120-126).

**Read first:**
```bash
sed -n '115,135p' ui/views/main_content.py
```

**Add immediately after the `self._user_input` setup block** (after `set_left_margin(8)` and any subsequent `self._user_input.*` calls in that block, before the next unrelated line):

```python
        # Buffer-changed signal — let subscribers react to typing/edits.
        # Mirrors the pattern used by project_settings / feed_bar in this class.
        buf = self._user_input.get_buffer()
        self._on_buffer_changed: callable | None = None
        buf.connect("changed", self._on_input_buffer_changed)
```

**Then add two new methods to the class** (anywhere reasonable — grouping with the existing `set_on_*` setters is fine):

```python
    def set_on_buffer_changed(self, cb: callable) -> None:
        """Register callback for input buffer 'changed' events. cb(buffer)."""
        self._on_buffer_changed = cb

    def _on_input_buffer_changed(self, buf) -> None:
        """Fire the registered callback (if any). The actual buffer.connect
        is in __init__; this is the indirection layer."""
        if self._on_buffer_changed is not None:
            self._on_buffer_changed(buf)
```

### Edit 2: `ui/handlers/input_toolbar_handler.py` — add a public `compute_count()` method

**Do NOT touch the existing `on_buffer_changed()` method** (lines 65-78). Its spell-check-only behavior is correct as-is. The new method is additive.

**Read first:**
```bash
sed -n '388,403p' ui/handlers/input_toolbar_handler.py
```

**Add immediately after the existing `get_word_count()` method (after line 403):**

```python
    def compute_count(self) -> tuple[int, int, int]:
        """Public alias for get_word_count() — used by the wiring layer
        (window.py) to push the count to the toolbar view on every
        buffer change. Kept separate from get_word_count() so the
        existing unit tests at tests/test_input_toolbar_handler.py
        keep passing without modification."""
        return self.get_word_count()
```

That's it for the handler. No view reference. The handler stays pure logic.

### Edit 3: `ui/window.py` — replace the dead wiring at line 288

**Read first:**
```bash
sed -n '275,300p' ui/window.py
```

**The current line 288:**
```python
input_toolbar.set_on_buffer_changed(self._input_toolbar_handler.on_buffer_changed)
```

**Replace with this block** (delete the one line, add the new block in its place):

```python
        # Wire input buffer's 'changed' signal to handler + count update.
        # The previous set_on_buffer_changed(...) was a no-op storage call
        # (chat_input_toolbar.set_on_buffer_changed just stores the cb).
        # Real wiring: main_content exposes its own buffer-changed signal
        # (added in Phase 8), and we bridge it to (a) handler.on_buffer_changed
        # for spell-check debounce and (b) toolbar.update_word_count for the
        # user-visible word/char count label.
        def _on_input_buffer_changed(_buf):
            self._input_toolbar_handler.on_buffer_changed()
            words, chars, tokens = self._input_toolbar_handler.compute_count()
            self._main_content._control_bar.update_word_count(words, chars, tokens)

        self._main_content.set_on_buffer_changed(_on_input_buffer_changed)
```

## Tests

### Add a regression test (1 new test method)

**File:** `tests/test_chat_input_toolbar.py`

**Where:** add a new test method to the existing test class. Find the end of the class with:

```bash
grep -n "^class\|def test_" tests/test_chat_input_toolbar.py | tail -10
```

**Add this test method** (it does not need a real MainWindow — it exercises the view + handler + buffer wiring in isolation):

```python
    def test_word_count_label_updates_on_buffer_change(self):
        """Regression test for the Phase 8 bug: word/char label must update
        when the input buffer changes. See TOOLBAR-PHASE-8-INSTRUCTIONS.md."""
        from ui.handlers.input_toolbar_handler import InputToolbarHandler
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk, GLib

        # Build a real toolbar + handler + buffer, wire them as window.py does
        toolbar = ChatInputToolbar()
        # Use a stand-in main_content that exposes user_input.get_buffer()
        class _StubMC:
            def __init__(self):
                self._user_input = Gtk.TextView()
        mc = _StubMC()
        handler = InputToolbarHandler(main_content=mc, GLib_module=GLib)

        # Wire the count path the same way window.py does in Edit 3
        def _on_buf_changed(_buf):
            handler.on_buffer_changed()
            words, chars, tokens = handler.compute_count()
            toolbar.update_word_count(words, chars, tokens)
        buf = mc._user_input.get_buffer()
        buf.connect("changed", _on_buf_changed)

        # Type some text — the buffer's 'changed' signal should fire
        buf.set_text("hello world this is a test")

        # Drain the GLib main context so signal handlers run
        ctx = GLib.MainContext.default()
        while ctx.iteration(False):
            pass

        # The label should now reflect 5 words, not 0
        label = toolbar._count_label.get_label()
        assert "5 words" in label, f"expected '5 words' in label, got: {label!r}"
        assert "0 words" not in label, f"label still shows zero: {label!r}"
```

This test would have caught the Phase 8 bug. Without it, the existing unit tests at `test_update_word_count` and `test_get_word_count` pass, but the wiring is still broken — exactly the failure mode that landed the bug in the first place.

## Verification Commands (run all of these)

```bash
cd /home/q/projects/crabcakes

# 1. main_content has the new wiring
echo "=== main_content: set_on_buffer_changed method present (should be 1) ==="
grep -n "def set_on_buffer_changed" ui/views/main_content.py
echo "=== main_content: _on_input_buffer_changed method present (should be 1) ==="
grep -n "def _on_input_buffer_changed" ui/views/main_content.py
echo "=== main_content: buf.connect('changed', ...) present (should be 1) ==="
grep -n 'buf\.connect."changed"' ui/views/main_content.py

# 2. handler has the new public method
echo "=== handler: compute_count method present (should be 1) ==="
grep -n "def compute_count" ui/handlers/input_toolbar_handler.py
echo "=== handler: get_word_count still present (should be 1) ==="
grep -n "def get_word_count" ui/handlers/input_toolbar_handler.py

# 3. window.py has the new wiring and the dead one is gone
echo "=== window.py: set_on_buffer_changed on the toolbar still present (still 1, but now it's a real call) ==="
grep -n "set_on_buffer_changed" ui/window.py
echo "=== window.py: compute_count() called (should be 1) ==="
grep -n "compute_count" ui/window.py
echo "=== window.py: update_word_count() called (should be 1) ==="
grep -n "update_word_count" ui/window.py

# 4. App imports cleanly
xvfb-run -a python3 -c "from ui.window import MainWindow; print('imports OK')"

# 5. App launches with no Gtk-CRITICAL
G_DEBUG=fatal-criticals xvfb-run -a python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
from ui.window import MainWindow
m = MainWindow(application=None)
m.present()
import time; time.sleep(2)
print('launch OK')
"

# 6. Run the targeted toolbar tests (existing 115 + new 1 = 116)
xvfb-run -a python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_spellcheck.py -q --tb=short 2>&1 | tail -10

# 7. Behavioral repro: type text, check the label updates
xvfb-run -a timeout 10 python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from ui.window import MainWindow
m = MainWindow(application=None); m.present()
ctx = GLib.MainContext.default()
while ctx.iteration(False): pass
buf = m._main_content.user_input.get_buffer()
buf.set_text('Hello world this is a test of the word count feature')
while ctx.iteration(False): pass
toolbar = m._main_content._control_bar
label = toolbar._count_label.get_label()
print(f'Label after typing 9 words: {label!r}')
assert '0 words' not in label, f'BUG: label still shows 0 words: {label!r}'
assert '9 words' in label, f'expected 9 words in label, got: {label!r}'
print('BEHAVIORAL CHECK PASSED')
"

# 8. Full git diff stat: only the 3 listed source files + 1 test file should change
git diff --stat
```

## Rules

- **Use the [steelFramedCodeWriter](../../prompts/steelFramedCodeWriter.md) prompt at `prompts/steelFramedCodeWriter.md`**
- Read each file BEFORE editing to confirm the exact text
- Maximum 15 lines edited before re-reading
- Do NOT add a view reference to the handler — that violates the architecture pattern
- Do NOT change the signature of `on_buffer_changed()` — the new `compute_count()` is additive
- Do NOT remove or rename `get_word_count()` — existing unit tests depend on it
- The new regression test must be added (without it, the bug could regress)

## What to report back

- The diff for each of the 3 source files + 1 test file
- The output of all 8 verification commands
- The COMPLETENESS checklist (see below)
- Any related issues found (do NOT silently fix them)

## Related-Bug Scan (per steelFramedCodeWriter Step 6.6)

After completing the 4 edits, scan adjacent code for the same dead-wiring pattern. Specifically:

- Search for other `set_on_*` methods on `ChatInputToolbar` that store a callback but never invoke it. List any that exist.
- Search for any other `Gtk.TextBuffer` or `Gtk.TextView` in the codebase that has no `'changed'`/`'insert-text'`/`'delete-range'` signal handler. List them.

Report these as "Related issue found, not fixed in this phase" — do NOT fix them.

## COMPLETENESS Checklist (mandatory)

```
COMPLETENESS:
- [x/not done] Edit 1: added buf.connect('changed',...) + set_on_buffer_changed + _on_input_buffer_changed to main_content.py — evidence: grep + diff
- [x/not done] Edit 2: added compute_count() to input_toolbar_handler.py — evidence: grep + diff
- [x/not done] Edit 3: replaced dead set_on_buffer_changed wiring in window.py with real bridge to handler.on_buffer_changed + toolbar.update_word_count — evidence: grep + diff
- [x/not done] Test: added test_word_count_label_updates_on_buffer_change to tests/test_chat_input_toolbar.py — evidence: pytest output
- [x/not done] main_content: set_on_buffer_changed method present — evidence: grep -c
- [x/not done] main_content: _on_input_buffer_changed method present — evidence: grep -c
- [x/not done] main_content: buf.connect('changed',...) present — evidence: grep -c
- [x/not done] handler: compute_count method present — evidence: grep -c
- [x/not done] handler: get_word_count still present — evidence: grep -c
- [x/not done] window.py: compute_count() called — evidence: grep -c
- [x/not done] window.py: update_word_count() called — evidence: grep -c
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] App launches with no Gtk-CRITICAL — evidence: G_DEBUG output
- [x/not done] Targeted toolbar tests pass (116/116) — evidence: pytest output
- [x/not done] Behavioral repro: label shows '9 words' after typing 9 words — evidence: python3 output
- [x/not done] No files modified other than the 3 source + 1 test listed — evidence: git diff --stat
- [x/not done] Related issues scanned and reported — evidence: yes/no
```

## Important Reminders

- The word marker for this delegation is: **"please write"**
- You are operating from the authorized crabcakes CLI channel
- This is a BUG FIX — the count label is a user-visible feature that's been broken
- Maximum 15 lines edited before re-reading
- Do not commit or push — only edit and report. I will audit and commit.
