# TOOLBAR-PHASE-5-INSTRUCTIONS.md — Wire InputToolbarHandler in window.py

## Context

Phase 4 complete: `main_content.py` now uses `ChatInputToolbar` instead of `ChatControlBar`. The toolbar widget exists but has no handler wired to it — the buttons do nothing.

This phase wires the `InputToolbarHandler` to the toolbar in `window.py`'s `_build()` method, following the MediaHandler pattern.

## Target File

`ui/window.py` — only this file

## What to Add

### 1. Add the handler attribute in `__init__()` (after line 72, near other handler declarations)

After `self._media_handler = None` (line 72), add:

```python
        # Input toolbar handler — owns find/replace, spell check, file I/O (Phase 5)
        self._input_toolbar_handler = None
```

### 2. Instantiate and wire the handler in `_build()` (after MediaHandler, around line 268)

After the MediaHandler block (lines 262-266), add:

```python
        # Input toolbar handler — owns find/replace, spell check, file I/O
        from ui.handlers.input_toolbar_handler import InputToolbarHandler
        self._input_toolbar_handler = InputToolbarHandler(
            main_content=self._main_content,
            GLib_module=GLib,
        )
```

### 3. Wire the toolbar callbacks (after the handler instantiation)

The toolbar is at `self._main_content._control_bar`. Wire the handler's methods to the toolbar's callback setters:

```python
        # Wire toolbar callbacks to handler
        toolbar = self._main_content._control_bar
        toolbar.set_on_find_toggled(self._input_toolbar_handler.toggle_spell_check)
        toolbar.set_on_spell_toggled(self._input_toolbar_handler.toggle_spell_check)
        toolbar.set_on_send_clicked(self._chat_handler.on_send_clicked)
        toolbar.set_on_open_file(self._input_toolbar_handler.load_file)
        toolbar.set_on_save_file(self._input_toolbar_handler.save_to_file)
        toolbar.set_on_find_next(self._input_toolbar_handler.find_next)
        toolbar.set_on_find_prev(self._input_toolbar_handler.find_prev)
        toolbar.set_on_replace(self._input_toolbar_handler.replace_current)
        toolbar.set_on_replace_all(self._input_toolbar_handler.replace_all)
        toolbar.set_on_find_closed(self._input_toolbar_handler.clear_find)
        toolbar.set_on_buffer_changed(self._input_toolbar_handler.on_buffer_changed)
```

IMPORTANT: Read the actual `ChatInputToolbar` callback setter methods and the `InputToolbarHandler` public methods before wiring. The mapping above is approximate — verify the exact method names match.

### 4. Wire the send button

The existing send button wiring at line ~167 is:
```python
self._main_content.send_button.connect("clicked", self._chat_handler.on_send_clicked)
```

The toolbar's send button should ALSO fire `on_send_clicked`. Wire it via the toolbar's `set_on_send_clicked` callback.

### 5. Wire the buffer changed signal

The `ChatInputToolbar` needs to know when the text buffer changes (for spell check, word count, char count). The `set_on_buffer_changed` callback should be wired to the handler's `on_buffer_changed` method.

Additionally, you may need to connect the buffer's `changed` signal to trigger the toolbar's callback. Check how the toolbar exposes this — if the toolbar connects the buffer's `changed` signal internally and fires the callback, this step is done. If not, you need to connect it here.

## What NOT to Change

- Do NOT modify `main_content.py` (done in Phase 4)
- Do NOT modify `input_toolbar_handler.py` (done in Phase 2)
- Do NOT modify `chat_input_toolbar.py` (done in Phase 3)
- Do NOT remove the existing send_button wiring (line ~167) — it's still used

## Architecture Rules

- `window.py` is the composition root — all wiring happens here
- Handler receives dependencies via constructor, not imports
- View receives callbacks via setters, not handler references
- Follow the MediaHandler pattern exactly

## Verification Commands

```bash
# Verify InputToolbarHandler import exists
cd /home/q/projects/crabcakes && grep -n "InputToolbarHandler" ui/window.py

# Verify _input_toolbar_handler attribute exists
cd /home/q/projects/crabcakes && grep -n "_input_toolbar_handler" ui/window.py

# Verify toolbar callbacks are wired
cd /home/q/projects/crabcakes && grep -n "set_on_" ui/window.py

# Verify app imports cleanly
cd /home/q/projects/crabcakes && xvfb-run -a python3 -c "from ui.window import MainWindow; print('OK')"

# Run full test suite
cd /home/q/projects/crabcakes && xvfb-run -a python3 -m pytest tests/ -q --tb=short

# Verify no handler imports in view
grep -n "from ui.handlers" ui/views/chat_input_toolbar.py
```

## COMPLETENESS Checklist

At the end of your response, you MUST include:

```
COMPLETENESS:
- [x/not done] _input_toolbar_handler attribute added to __init__ — evidence: grep
- [x/not done] InputToolbarHandler instantiated in _build() — evidence: grep
- [x/not done] Toolbar callbacks wired to handler methods — evidence: grep + read
- [x/not done] Send button wired — evidence: grep
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] Full test suite passes — evidence: pytest output
- [x/not done] No files modified other than window.py — evidence: git diff --stat
```

## Important Reminders

- Use the **steelFramedCodeWriter** prompt at `prompts/steelFramedCodeWriter.md`
- Start with discovery: read window.py, read the handler, read the toolbar view, THEN wire
- Verify exact method names match between handler and view before wiring
- Maximum 15 lines before verifying
- The word marker for this delegation is: **"please write"**
