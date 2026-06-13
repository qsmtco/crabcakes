# Phase 3a-2 Instructions — Wire ConnectionSyncHandler into window.py

**Date:** 2026-05-31
**Phase:** 3a-2 of 6
**File to change:** `ui/window.py` ONLY

## Context

Phase 3a-1 created `ui/handlers/connection_sync_handler.py` (committed `8425a9d`). This phase wires it into `window.py` and removes the old `_sync_gateway_to_chat_handler` method.

## Required Changes (in order)

### Edit 1: Add placeholder for the new handler attribute (line 67 area)

Find the `self._<name> = None` block near the top of `_build()` (lines 67-83). Add a placeholder for the new handler alongside the other `None` initializations:

```python
self._connection_sync_handler = None
```

Pick any spot in that block. Do not reorder existing lines.

### Edit 2: Move the `set_sync_callback` call

Currently at line 224:
```python
self._gateway_handler.set_sync_callback(self._sync_gateway_to_chat_handler)
```

**Delete** this line. It will be re-added after the `ConnectionSyncHandler` is instantiated (Edit 3 below).

### Edit 3: Instantiate `ConnectionSyncHandler` and wire the callback

After the line that creates `_agent_command_handler` (line 439, the `self._agent_command_handler = AgentCommandHandler(GLib_module=GLib)` line), and after the four `set_on_agent_response` / `set_command_handler` / `set_agent_runtime_handler` lines that follow, add a new block:

```python
# Connection sync handler — owns post-connect wiring (Phase 3a extraction)
from ui.handlers.connection_sync_handler import ConnectionSyncHandler
self._connection_sync_handler = ConnectionSyncHandler(
    chat_handler=self._chat_handler,
    main_content=self._main_content,
    agent_list_handler=self._agent_list_handler,
    gateway_handler=self._gateway_handler,
    project_handler=self._project_handler,
    command_handler=self._command_handler,
    agent_command_handler=self._agent_command_handler,
    session_handler=self._session_handler,
    feed_handler=self._feed_handler,
    left_panel=self._left_panel,
    review_handler=self._review_handler,
    activity_handler=self._activity_handler,
    agent_to_project=self._agent_to_project,
    on_forward_clicked=self._on_forward_clicked,  # method still exists in window.py for now
    project_path_provider=lambda: self._project_handler.get_active_project_path() if self._project_handler else None,
)
# Wire the sync callback to fire on gateway connect
self._gateway_handler.set_sync_callback(self._connection_sync_handler.sync)
```

**Note about `on_forward_clicked`:** Use `self._on_forward_clicked` (the existing window method, lines 733-775). Phase 3b will replace this with the ForwardHandler; for now pass the existing method. This is intentional and will be updated in Phase 3b-2.

### Edit 4: Delete the old `_sync_gateway_to_chat_handler` method

Delete the entire method from line 611 (the `# ── Gateway sync ──` comment) through line 685 (the last `self._activity_handler.set_on_activity_bubble(...)` call). That's lines 611-685 — 75 lines including the section comment.

### Edit 5: Update stale comments that reference the old method

There are 4 stale comments referencing `_sync_gateway_to_chat_handler` that need updating:

- **Line 138:** `# Agent card handler — agent_mgr set in _sync_gateway_to_chat_handler after connect`
  → Change to: `# Agent card handler — agent_mgr set in ConnectionSyncHandler.sync() after connect`

- **Line 384:** `agent_manager=None,   # synced in _sync_gateway_to_chat_handler`
  → Change to: `agent_manager=None,   # synced in ConnectionSyncHandler.sync()`

- **Line 405:** `gateway_client=None,   # synced after connect via _sync_gateway_to_chat_handler`
  → Change to: `gateway_client=None,   # synced after connect via ConnectionSyncHandler.sync()`

- **Line 406:** `agent_manager=None,    # synced after connect via _sync_gateway_to_chat_handler`
  → Change to: `agent_manager=None,    # synced after connect via ConnectionSyncHandler.sync()`

**Note:** Line numbers may shift slightly after each edit. Use `grep -n "_sync_gateway_to_chat_handler" ui/window.py` to find all remaining references before doing the comment edits. There should be exactly 4 (the comments) plus possibly the line that wires `set_sync_callback` (which is being moved).

## Files NOT Changed

- `ui/handlers/connection_sync_handler.py` — already created in Phase 3a-1, do not modify
- Any other handler file
- Any test file (Phase 3a-3)

## Verification Commands

Run these and paste output:

1. `grep -n "_sync_gateway_to_chat_handler" ui/window.py` — must return 0 matches
2. `grep -n "ConnectionSyncHandler" ui/window.py` — must return 3+ matches (1 import, 1 instantiation, 1 callback wire)
3. `wc -l ui/window.py` — must be ≤ 770 lines (was 833, removing 75 lines + adding ~25)
4. `python3 -c "from ui.window import App; print('OK')"` — must print OK (basic import check)
5. `python3 -m pytest tests/ -q --ignore=tests/test_agent_runtime.py 2>&1 | tail -3` — must show 25 failed, 1071 passed (same as baseline)
6. `git diff --stat ui/window.py` — must show this is the ONLY file changed (no collateral)

## Completeness Checklist

```
COMPLETENESS:
- [x] Edit 1: added self._connection_sync_handler = None placeholder
- [x] Edit 2: moved/deleted old set_sync_callback line
- [x] Edit 3: instantiated ConnectionSyncHandler with 16 args + rewired set_sync_callback
- [x] Edit 4: deleted old _sync_gateway_to_chat_handler method (75 lines)
- [x] Edit 5: updated 4 stale comments
- [x] No collateral edits — only ui/window.py changed
- [x] No regressions — pytest output matches baseline
```
