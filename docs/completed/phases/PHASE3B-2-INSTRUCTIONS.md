# Phase 3b-2 Instructions — Wire ForwardHandler into window.py

**Date:** 2026-05-31
**Phase:** 3b-2 of 6
**File to change:** `ui/window.py` ONLY

## Context

Phase 3b-1 created `ui/handlers/forward_handler.py` (committed `27ac951`). This phase wires it into `window.py` and removes the old `_on_forward_clicked` and `_forward_to_agent` methods.

**This is an INTEGRATION phase.** Per supervisor rules, integration has a 1-attempt rule — if you fail once, I fix it. So read the instructions file carefully.

## Required Changes (in order)

### Edit 1: Add `self._forward_handler = None` placeholder

Find the placeholder block at the top of `_build()` (around lines 81-85, where `self._connection_sync_handler = None` was added in Phase 3a-2). Add a new line:

```python
# Forward handler — owns agent-to-agent message forwarding (Phase 3b extraction)
self._forward_handler = None
```

### Edit 2: Instantiate `ForwardHandler` BEFORE the ConnectionSyncHandler instantiation

The ConnectionSyncHandler (line 446-461) currently has:
```python
on_forward_clicked=self._on_forward_clicked,  # method still exists in window.py for now
```

We need to:
1. Add a `ForwardHandler` instantiation block BEFORE the ConnectionSyncHandler block
2. Update the ConnectionSyncHandler's `on_forward_clicked` arg to point to `self._forward_handler.show_forward_popover`
3. Remove the inline comment `# method still exists in window.py for now` since the method will be deleted in Edit 3

**Insert BEFORE the `from ui.handlers.connection_sync_handler import ConnectionSyncHandler` line:**

```python
# Forward handler — owns agent-to-agent message forwarding (Phase 3b extraction)
from ui.handlers.forward_handler import ForwardHandler
self._forward_handler = ForwardHandler(
    main_content=self._main_content,
    chat_handler=self._chat_handler,
    chat_render_handler=self._chat_render_handler,
    agent_runtime_handler=self._agent_runtime_handler,
    gateway_handler=self._gateway_handler,
)
```

**Then UPDATE the ConnectionSyncHandler block (line 461):**

```python
# OLD:
on_forward_clicked=self._on_forward_clicked,  # method still exists in window.py for now

# NEW:
on_forward_clicked=self._forward_handler.show_forward_popover,
```

### Edit 3: Delete the old `_on_forward_clicked` and `_forward_to_agent` methods

Delete from the `# ── Agent selection callback ──` section comment block boundary (around line 682) through the end of `forward_to_agent` (around line 784). The block to delete includes:

- The section comment header (something like `# ── Forward popover + routing ──` if present, otherwise just the methods)
- The `def _on_forward_clicked(...)` method (43 lines)
- The blank line(s) between methods
- The `def _forward_to_agent(...)` method (57 lines)

After deletion, the file should have `def _on_agent_selected(self, session_key, agent_name):` directly after the section above (the comment `# ── Agent selection callback ──` and its method).

**Note:** Line numbers will shift after deletion. Use `grep -n "_on_forward_clicked\|_forward_to_agent" ui/window.py` to find any remaining references before doing the next step.

### Edit 4: Verify no remaining references

Run: `grep -n "_on_forward_clicked\|_forward_to_agent" ui/window.py` — must return 0 matches. If any remain (e.g., in stale comments), update or remove them.

## Files NOT Changed

- `ui/handlers/forward_handler.py` — already created in Phase 3b-1
- `ui/handlers/connection_sync_handler.py` — only the on_forward_clicked call site in window.py is updated, not the handler
- Any test file
- ARCHITECTURE.md (will be updated in Phase 5)

## Verification Commands

Run these and paste output:

1. `grep -n "_on_forward_clicked" ui/window.py` — must return 0
2. `grep -n "_forward_to_agent" ui/window.py` — must return 0
3. `grep -n "ForwardHandler" ui/window.py` — must return 4+ (1 placeholder, 1 import, 1 instantiation, 1 set call)
4. `wc -l ui/window.py` — must be ≤ 695 (was 784; removing ~100 lines, adding ~12)
5. `python3 -c "from ui.window import MainWindow; print('OK')"` — must print OK
6. `python3 -m pytest tests/ -q --ignore=tests/test_agent_runtime.py 2>&1 | tail -3` — must show 25 failed, 1099 passed (no regressions)
7. `git diff --stat` — only ui/window.py modified

## Completeness Checklist

```
COMPLETENESS:
- [x] Edit 1: added self._forward_handler = None placeholder
- [x] Edit 2: instantiated ForwardHandler + updated ConnectionSyncHandler's on_forward_clicked
- [x] Edit 3: deleted both old methods
- [x] Edit 4: no remaining references
- [x] No collateral edits
- [x] No regressions
```
