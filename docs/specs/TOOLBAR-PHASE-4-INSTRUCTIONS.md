# TOOLBAR-PHASE-4-INSTRUCTIONS.md — Swap ChatControlBar → ChatInputToolbar in main_content.py

## Context

Phases 1-3 complete: spellcheck (24 tests), handler (23 tests), view (68 tests). All audited.

Now we integrate. This phase swaps the old `ChatControlBar` (a `Gtk.Label` stub) with the new `ChatInputToolbar` in `main_content.py`.

## Target File

`ui/views/main_content.py` — 872 lines

## What to Change

### 1. Replace the import (line 16)

**OLD:**
```python
from ui.views.chat_control_bar import ChatControlBar
```

**NEW:**
```python
from ui.views.chat_input_toolbar import ChatInputToolbar
```

### 2. Replace the construction (line 72)

**OLD:**
```python
self._control_bar = ChatControlBar()
```

**NEW:**
```python
self._control_bar = ChatInputToolbar()
```

### 3. Update the type annotation for `_on_control_bar_update` (line 75)

The old control bar used `update(event_type, message)`. The new toolbar doesn't use this callback pattern — the toolbar gets updated directly by the handler. BUT keep `set_on_control_bar_update` and `update_control_bar` for now because `activity_handler.py` line 603 still calls `self._mc.update_control_bar(state, plain)`. We'll remove that in Phase 6. For now, make `update_control_bar` a no-op or log a deprecation warning.

**Change `update_control_bar` (lines 205-208) to:**

```python
def update_control_bar(self, event_type: str, message: str) -> None:
    """Legacy — ActivityHandler still calls this. No-op until Phase 6 removes it."""
    # Phase 4: ChatInputToolbar replaces ChatControlBar. The toolbar is now
    # managed by InputToolbarHandler, not by activity state updates.
    pass
```

### 4. DO NOT change anything else

Do NOT:
- Change the `user_input` property
- Change the notebook handling
- Change any chat rendering code
- Change the project settings bar
- Touch any other file

## Architecture Rules

- `main_content.py` is a VIEW — it assembles widgets, no business logic
- The `_control_bar` attribute name stays the same — only the class changes
- `top_box.append(self._control_bar)` at line 81 stays the same — `ChatInputToolbar` is also a `Gtk.Box`, so it's API-compatible

## Verification Commands

```bash
# Verify the import changed
cd /home/q/projects/crabcakes && grep -n "chat_control_bar\|ChatControlBar" ui/views/main_content.py

# Verify the new import exists
cd /home/q/projects/crabcakes && grep -n "ChatInputToolbar" ui/views/main_content.py

# Verify no other files still import ChatControlBar (except the file itself and activity_handler comment)
cd /home/q/projects/crabcakes && grep -rn "ChatControlBar" ui/ --include="*.py" | grep -v "chat_control_bar.py"

# Run the full test suite
cd /home/q/projects/crabcakes && xvfb-run -a python3 -m pytest tests/ -q --tb=short

# Verify the app still imports cleanly
cd /home/q/projects/crabcakes && xvfb-run -a python3 -c "from ui.views.main_content import MainContent; print('OK')"
```

## COMPLETENESS Checklist

At the end of your response, you MUST include:

```
COMPLETENESS:
- [x/not done] Import changed: ChatControlBar → ChatInputToolbar — evidence: grep output
- [x/not done] Construction changed: ChatControlBar() → ChatInputToolbar() — evidence: grep output
- [x/not done] update_control_bar made into no-op — evidence: grep/read output
- [x/not done] No other changes made — evidence: git diff output
- [x/not done] App imports cleanly — evidence: python3 -c output
- [x/not done] Full test suite passes — evidence: pytest output
```

## Important Reminders

- Use the **steelFramedCodeWriter** prompt at `prompts/steelFramedCodeWriter.md`
- Start with discovery: read main_content.py, then make the changes
- Maximum 15 lines before verifying
- Do NOT touch any file other than `ui/views/main_content.py`
- The word marker for this delegation is: **"please write"**
