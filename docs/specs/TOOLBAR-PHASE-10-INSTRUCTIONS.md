# TOOLBAR-PHASE-10-INSTRUCTIONS.md

PHASE 10 — Rename `_control_bar` → `_toolbar` on `MainContent` and add a public `toolbar` property

This is a naming/cleanup phase. The attribute `self._control_bar` on `MainContent` was named in Phase 4, when the old `ChatControlBar` (a `Gtk.Label` stub) was being replaced. After Phases 1-8, the attribute holds a `ChatInputToolbar` — a much richer widget. The name `_control_bar` is now semantically misleading. The spec at `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` §2.4 calls for renaming it to `_toolbar` and adding a public `toolbar` property.

## Master Spec

`docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` §2.4 (the exact directive is reproduced below):

> Rename `_control_bar` → `_toolbar` and add a public `toolbar` property on `MainContent`.

## Why

- The current name `_control_bar` is a holdover from the `ChatControlBar` days. It now holds a `ChatInputToolbar`, which is not a "control bar" — it's a toolbar of editor actions (find/replace, spell check, file I/O, etc.).
- External consumers (`window.py:279`) reach in with `self._main_content._control_bar` — the leading underscore is a Python convention for "private." A public `toolbar` property is the right access pattern.
- Per the project's existing pattern, `MainContent` exposes `user_input` (a `Gtk.TextView`) as a public property. `toolbar` should follow the same pattern.

## Files to change (2)

- **`ui/views/main_content.py`** — rename attribute + add property
- **`ui/window.py`** — update the one reference to use the new property

## Edits (in order — read each block BEFORE editing)

### Edit 1: `ui/views/main_content.py` — rename `self._control_bar` → `self._toolbar` (3 occurrences)

**Read first:**
```bash
grep -n "_control_bar" ui/views/main_content.py
```

There should be exactly 3 occurrences:
- Line 72: `self._control_bar = ChatInputToolbar()` (in `__init__`)
- Line 78: `top_box.append(self._control_bar)` (in `__init__`)

Use the editor's find-and-replace feature, or three separate `edit` calls, to rename all occurrences in this file from `_control_bar` to `_toolbar`. **Do not change the type or the value** — only the name.

Verify with:
```bash
grep -n "_control_bar\|_toolbar" ui/views/main_content.py
```
Expected: only `_toolbar` references, zero `_control_bar`.

### Edit 2: `ui/views/main_content.py` — add a public `toolbar` property

**Read first:**
```bash
sed -n '25,35p' ui/views/main_content.py
```

There is already a `user_input` property at line 28. Add a `toolbar` property right after it. The property should be a simple getter:

```python
    @property
    def toolbar(self) -> "ChatInputToolbar":
        """Public accessor for the input toolbar view (find/replace, spell check, etc.)."""
        return self._toolbar
```

**Note:** the return type string `"ChatInputToolbar"` matches the pattern used for `user_input`'s return type (a forward reference, since the class is defined elsewhere in the same module's import order). If `user_input`'s property doesn't use a string-quoted return type, follow its actual pattern.

### Edit 3: `ui/window.py` — update the one reference (line 279)

**Read first:**
```bash
sed -n '275,285p' ui/window.py
```

The current line 279:
```python
        input_toolbar = self._main_content._control_bar
```

Replace with:
```python
        input_toolbar = self._main_content.toolbar
```

That's the only reference in `window.py`. The local variable `input_toolbar` (a name chosen in Phase 5 to avoid shadowing) keeps its name — no further changes needed.

### Edit 4: Verification — confirm no other references to `_control_bar` exist

```bash
grep -rn "_control_bar" --include="*.py" ui/ tests/ 2>&1
```

Expected output: **empty** (no matches). If any other file references `_control_bar`, you missed a call site — list it as a "Related issue found" but do NOT silently fix it.

## Verification Commands (run all of these)

```bash
cd /home/q/projects/crabcakes

# 1. main_content.py: _control_bar gone, _toolbar present
echo "=== _control_bar in main_content.py (should be 0) ==="
grep -c "_control_bar" ui/views/main_content.py
echo "=== _toolbar in main_content.py (should be 3) ==="
grep -c "_toolbar" ui/views/main_content.py

# 2. main_content.py: toolbar property present
echo "=== toolbar property (should be 1) ==="
grep -n "def toolbar" ui/views/main_content.py

# 3. window.py: uses the new property, not the old private attr
echo "=== window.py uses _main_content.toolbar (should be 1) ==="
grep -n "_main_content\.toolbar" ui/window.py
echo "=== window.py uses _main_content._control_bar (should be 0) ==="
grep -c "_main_content\._control_bar" ui/window.py

# 4. Zero _control_bar anywhere in ui/ or tests/
echo "=== _control_bar in ui/ tests/ (should be 0) ==="
grep -rn "_control_bar" --include="*.py" ui/ tests/ 2>&1 | wc -l

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

# 7. Targeted toolbar tests still pass (no new test needed — this is a rename)
xvfb-run -a python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_spellcheck.py -q --tb=short 2>&1 | tail -8

# 8. Behavioral repro: the new property returns the same toolbar the old one did
xvfb-run -a timeout 10 python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from ui.window import MainWindow
m = MainWindow(application=None); m.present()
ctx = GLib.MainContext.default()
while ctx.iteration(False): pass
# Old style would have been: m._main_content._control_bar
# New style: m._main_content.toolbar
assert hasattr(m._main_content, 'toolbar'), 'public toolbar property missing'
assert not hasattr(m._main_content, '_control_bar') or True  # _toolbar may exist; just check property works
# The toolbar should be functional
ibuf = m._main_content.user_input.get_buffer()
ibuf.set_text('Hello world')
while ctx.iteration(False): pass
toolbar = m._main_content.toolbar
assert '2 words' in toolbar._count_label.get_label(), f'expected 2 words, got: {toolbar._count_label.get_label()!r}'
print('BEHAVIORAL CHECK PASSED — public property works, word count still updates')
" 2>&1 | tail -5
```

## Rules

- **Use the [steelFramedCodeWriter](../../prompts/steelFramedCodeWriter.md) prompt at `prompts/steelFramedCodeWriter.md`**
- Read each block BEFORE editing
- Maximum 15 lines edited before re-reading
- Do NOT change the type, value, or lifecycle of the toolbar — only the name
- Do NOT add a setter for the `toolbar` property (it's a read-only view)
- Do NOT remove the local variable `input_toolbar = ...` in `window.py` — it's a deliberate shadowing-avoidance pattern from Phase 5

## What to report back

- The diff for `ui/views/main_content.py` and `ui/window.py`
- The output of all 8 verification commands
- The COMPLETENESS checklist (see below)
- Any related issues found (do NOT silently fix them)

## Related-Bug Scan (per steelFramedCodeWriter Step 6.6)

After completing the 4 edits, scan for:
- Other `self._control_bar` references anywhere (should be 0)
- Other `MainContent` attributes that are still using the old "underscore-prefixed + accessed from outside" pattern (these are the same naming-debt class)
- Any other `ChatControlBar` references in production code (should be 0)

Report these as "Related issue found, not fixed in this phase" — do NOT fix them.

## COMPLETENESS Checklist (mandatory)

```
COMPLETENESS:
- [x/not done] Edit 1: renamed _control_bar → _toolbar in main_content.py (3 occurrences) — evidence: grep + diff
- [x/not done] Edit 2: added public @property toolbar on MainContent — evidence: grep + diff
- [x/not done] Edit 3: updated window.py:279 to use _main_content.toolbar — evidence: grep + diff
- [x/not done] main_content.py: _control_bar = 0 — evidence: grep -c
- [x/not done] main_content.py: _toolbar = 3 — evidence: grep -c
- [x/not done] main_content.py: toolbar property present — evidence: grep -n
- [x/not done] window.py: uses _main_content.toolbar (not _control_bar) — evidence: grep -n
- [x/not done] ui/ + tests/: _control_bar references = 0 — evidence: grep -r
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] App launches with no Gtk-CRITICAL — evidence: G_DEBUG output
- [x/not done] Targeted toolbar tests pass (116/116) — evidence: pytest output
- [x/not done] Behavioral check: public property returns the toolbar, word count still updates — evidence: python3 output
- [x/not done] No files modified other than the 2 listed — evidence: git diff --stat
- [x/not done] Related issues scanned and reported — evidence: yes/no
```

## Important Reminders

- The word marker for this delegation is: **"please write"**
- You are operating from the authorized crabcakes CLI channel
- This is a RENAME phase — no new functionality
- Maximum 15 lines edited before re-reading
- Do not commit or push — only edit and report. I will audit and commit.
