# TOOLBAR-PHASE-9-INSTRUCTIONS.md

PHASE 9 — Remove the dead `set_on_buffer_changed` on the toolbar view

This is a small dead-code cleanup phase. The toolbar view (`ui/views/chat_input_toolbar.py`) has a `set_on_buffer_changed(cb)` setter that stores a callback in `self._on_buffer_changed`, but the only place that callback is invoked is from `_on_find_entry_changed` (the find bar's search entry's `changed` signal — not the input buffer). After Phase 8, no production code calls `input_toolbar.set_on_buffer_changed` anymore. The setter, the stored field, and the conditional in `_on_find_entry_changed` are all dead code.

## Master Spec

`docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` §3.34 (toolbar view module description).

The Phase 8 work moved the buffer-changed wiring to `main_content.set_on_buffer_changed`, leaving the toolbar's setter orphaned. The setter must be removed to eliminate the latent TypeError trap (see §Why below).

## Why (the latent TypeError)

`chat_input_toolbar.set_on_buffer_changed(cb)` (line 176) stores the callback with no signature check. Phase 8 introduced `_on_input_buffer_changed(buf)` in `main_content.py` — this method **requires a `buf` argument**. The toolbar's `_on_find_entry_changed` (line 582) invokes `self._on_buffer_changed()` with **no arguments** at line 584.

If a future developer ever re-wires `input_toolbar.set_on_buffer_changed(self._on_input_buffer_changed)` (the new Phase 8 callback), the find bar's typeahead will crash on every keystroke with `TypeError: _on_input_buffer_changed() missing 1 required positional argument: 'buf'`.

The setter's only purpose was to let the find entry's `changed` signal call back into the controller. Since the controller no longer cares about find-entry changes (it only cares about input buffer changes, now wired through `main_content`), the setter is dead.

## Files to change (1)

- **`ui/views/chat_input_toolbar.py`** — remove 3 things:
  1. The `set_on_buffer_changed` setter (line 176-177)
  2. The `self._on_buffer_changed` attribute initialization (find where it's set in `__init__`)
  3. The `if self._on_buffer_changed: self._on_buffer_changed()` block in `_on_find_entry_changed` (lines 583-584)

Do NOT remove `_on_find_entry_changed` itself — it still needs to call `self._on_find(text)` for the find logic. Just remove the buffer-changed callback invocation within it.

## Edits (in order — read each block BEFORE editing)

### Edit 1: `ui/views/chat_input_toolbar.py` — remove the setter

**Read first:**
```bash
sed -n '170,185p' ui/views/chat_input_toolbar.py
```

Find the `set_on_buffer_changed` method (it should be near line 176, just after `set_on_spell_toggle`). Delete the entire method (2 lines + the docstring if present).

### Edit 2: `ui/views/chat_input_toolbar.py` — remove the attribute initialization

**Read first:**
```bash
grep -n "_on_buffer_changed" ui/views/chat_input_toolbar.py
```

There should be exactly one remaining line (in `__init__`) after Edit 1. Find and delete it. If the attribute is set in a list of other `_on_*` initializations, just delete the one line.

### Edit 3: `ui/views/chat_input_toolbar.py` — remove the callback invocation in `_on_find_entry_changed`

**Read first:**
```bash
sed -n '580,595p' ui/views/chat_input_toolbar.py
```

Find the block:
```python
    def _on_find_entry_changed(self, entry):
        text = entry.get_text()
        if self._on_buffer_changed:
            self._on_buffer_changed()
        if self._on_find:
            self._on_find(text)
```

Delete the `if self._on_buffer_changed: self._on_buffer_changed()` block (3 lines, including the blank line if present). The function should look like:

```python
    def _on_find_entry_changed(self, entry):
        text = entry.get_text()
        if self._on_find:
            self._on_find(text)
```

## Verification Commands (run all of these)

```bash
cd /home/q/projects/crabcakes

# 1. set_on_buffer_changed is gone
echo "=== set_on_buffer_changed in chat_input_toolbar.py (should be 0) ==="
grep -c "set_on_buffer_changed" ui/views/chat_input_toolbar.py

# 2. _on_buffer_changed attribute is gone
echo "=== _on_buffer_changed in chat_input_toolbar.py (should be 0) ==="
grep -c "_on_buffer_changed" ui/views/chat_input_toolbar.py

# 3. No production code anywhere calls the dead setter
echo "=== set_on_buffer_changed anywhere in ui/ (should be 0) ==="
grep -rn "set_on_buffer_changed" --include="*.py" ui/ 2>&1 | wc -l

# 4. _on_find_entry_changed still calls _on_find
echo "=== _on_find_entry_changed still calls _on_find (should be 1) ==="
grep -c "self\._on_find" ui/views/chat_input_toolbar.py

# 5. App imports cleanly
xvfb-run -a python3 -c "from ui.window import MainWindow; print('imports OK')"

# 6. App launches with no Gtk-CRITICAL
G_DEBUG=fatal-criticals xvfb-run -a python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
from ui.window import MainWindow
m = MainWindow(application=None)
m.present()
import time; time.sleep(2)
print('launch OK')
"

# 7. Targeted toolbar tests still pass (no new test needed — this is a deletion)
xvfb-run -a python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_spellcheck.py -q --tb=short 2>&1 | tail -8

# 8. Behavioral repro: find bar still works (type in find entry → match count updates)
xvfb-run -a timeout 10 python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from ui.window import MainWindow
m = MainWindow(application=None); m.present()
ctx = GLib.MainContext.default()
while ctx.iteration(False): pass
# Type into the input, then into the find bar
ibuf = m._main_content.user_input.get_buffer()
ibuf.set_text('hello world this is a test for the find bar')
while ctx.iteration(False): pass
toolbar = m._main_content._control_bar
# Show the find bar
toolbar.show_find_bar()
# Type into the find entry
fbuf = toolbar._find_entry.get_buffer()
fbuf.set_text('hello')
while ctx.iteration(False): pass
# The find logic should have run (we can't easily check match count here,
# but the absence of TypeError is the test)
print('FIND BAR WORKS — no TypeError on find entry changed')
" 2>&1 | tail -5
```

## Rules

- **Use the [steelFramedCodeWriter](../../prompts/steelFramedCodeWriter.md) prompt at `prompts/steelFramedCodeWriter.md`**
- Read each block BEFORE editing
- Maximum 15 lines edited before re-reading
- Do NOT remove `_on_find_entry_changed` itself — only the dead callback invocation inside it
- Do NOT remove `_on_find` (the find logic is still wired)
- Do NOT add tests — this is pure deletion, the existing 116 tests are the regression suite

## What to report back

- The diff for `ui/views/chat_input_toolbar.py`
- The output of all 8 verification commands
- The COMPLETENESS checklist (see below)
- Any related issues found (do NOT silently fix them)

## Related-Bug Scan (per steelFramedCodeWriter Step 6.6)

After completing the 3 edits, scan `ui/views/chat_input_toolbar.py` for other `set_on_*` setters that store a callback in `self._on_*` and check whether the stored callback is actually invoked. List any that are storage-only (set but never called) — these are the same bug class.

Report these as "Related issue found, not fixed in this phase" — do NOT fix them.

## COMPLETENESS Checklist (mandatory)

```
COMPLETENESS:
- [x/not done] Edit 1: removed set_on_buffer_changed setter from chat_input_toolbar.py — evidence: grep + diff
- [x/not done] Edit 2: removed _on_buffer_changed attribute initialization from __init__ — evidence: grep + diff
- [x/not done] Edit 3: removed the if self._on_buffer_changed block from _on_find_entry_changed — evidence: grep + diff
- [x/not done] set_on_buffer_changed references in chat_input_toolbar.py = 0 — evidence: grep -c
- [x/not done] _on_buffer_changed references in chat_input_toolbar.py = 0 — evidence: grep -c
- [x/not done] set_on_buffer_changed in ui/ = 0 — evidence: grep -r
- [x/not done] _on_find still called from _on_find_entry_changed (find logic intact) — evidence: grep -c
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] App launches with no Gtk-CRITICAL — evidence: G_DEBUG output
- [x/not done] Targeted toolbar tests pass (116/116) — evidence: pytest output
- [x/not done] Find bar still works (no TypeError on find entry changed) — evidence: python3 output
- [x/not done] No files modified other than the 1 listed — evidence: git diff --stat
- [x/not done] Related issues scanned and reported — evidence: yes/no
```

## Important Reminders

- The word marker for this delegation is: **"please write"**
- You are operating from the authorized crabcakes CLI channel
- This is a DEAD-CODE REMOVAL phase — no new functionality
- Maximum 15 lines edited before re-reading
- Do not commit or push — only edit and report. I will audit and commit.
