# SPEC: Outstanding Cleanup — Items 1, 2, 3

**Date:** 2026-05-31
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** QTR architecture audit follow-up (2026-05-31)
**Target branch:** main

> Architecture compliance: All changes preserve ARCHITECTURE.md §3.6 (window.py is the composition root — wires components, holds no business logic) and §8.6 (no handler cross-imports).

---

## 1. Overview

### Problem
The original architecture audit (2026-05-30) found 20 issues. The 7-phase audit-fixes spec (2026-05-31) resolved 7 of the 13 fixable findings. Three remaining items are isolated, low-risk cleanup:

1. ~~`utils/workflow_state.py` has the same circular self-import pattern~~ **N/A — verified false by QTR 2026-05-31.** The only `from utils.workflow_state import` line in the file is inside the module docstring's `Usage:` example. The actual `advance_phase` function has no self-import. Item 1 is skipped.

2. **`tests/test_convergence.py` references deleted `converge/` code.** The `converge/` directory was removed, but the test file remained. The `.bak` and `.insert` files are also leftover from the deletion work. All three should be removed.

3. **`ui/window.py` still has two extractable methods** (`_sync_gateway_to_chat_handler` at 73 lines, `_forward_to_agent` at 57 lines) that violate ARCHITECTURE.md §3.6. The earlier extraction refactor (5 steps) was supposed to be a complete pass, but these two methods were not in scope. Extract them into a new `ConnectionSyncHandler` (Item 3a) and a new `ForwardHandler` (Item 3b).

### Solution Summary
- Item 1: One-line function body change in `utils/workflow_state.py`
- Item 2: Delete three stale test files
- Item 3: Extract two methods from `window.py` into dedicated handler classes following the established pattern (`ui/handlers/*_handler.py`)

### Scope (in / out)
| In | Out |
|---|---|
| `utils/workflow_state.py` — remove self-import | Refactoring `_sync_gateway_to_chat_handler`'s call chain |
| `tests/test_convergence.py` + `.bak` + `.insert` — delete | `converge/` directory (already gone) |
| New `ui/handlers/connection_sync_handler.py` | Changes to other handler constructors |
| New `ui/handlers/forward_handler.py` | Behavior changes to forwarding logic |
| `ui/window.py` — remove the two methods, wire in handlers | Adding new functionality to forwarded messages |
| New tests for both handlers | Touching any other handler file |

### Architecture principles
- **ARCH §3.6:** window.py is the composition root. After this spec, `_sync_gateway_to_chat_handler` and `_forward_to_agent` will not exist in `window.py`.
- **ARCH §8.6:** New handlers do not import from other handlers.
- **Supervisor prompt rules:** Granular phases (1 file/phase where possible), file-based delegation for complex instructions, per-phase independent verification.

---

## 2. Changes by File


### Item 2 — Test file deletion

**Files to delete:**
- `tests/test_convergence.py` — references `converge/` package code that was deleted; 303 lines of orphaned test logic
- `tests/test_convergence.py.bak` — leftover backup from the `converge/` deletion work
- `tests/test_convergence.py.insert` — leftover artifact from the deletion work

**Verified:** No file in the codebase imports from `converge/` (verified by `grep -rn "from converge\|import converge" . --include="*.py"` returning no results, with `converge/` directory confirmed absent via `ls converge/` returning exit 2). Deletion is safe.

**Line count estimate:** −303 lines (test_convergence.py) + 2 backup files

### Item 3a — `ui/handlers/connection_sync_handler.py` (NEW)

**What changes:** Create a new handler that owns the logic for syncing live gateway references into all dependent handlers after a successful gateway connect. Move the body of `window._sync_gateway_to_chat_handler()` here.

**Verified current code (read from source, window.py lines 613–685):**
```python
def _sync_gateway_to_chat_handler(self, gw):
    """Sync the live GatewayClient into ChatHandler after connect succeeds.

    Called by GatewayHandler via set_sync_callback() after on_connected() dispatches.
    GatewayClient is not available at window construction time (gateway isn't running yet),
    so we defer the reference injection until after the WebSocket handshake completes.
    This is the only place where ChatHandler._gw gets set — it's write-once after connect.
    """
    self._chat_handler.set_gateway_client(gw)
    self._main_content.set_agent_manager(self._gateway_handler.agent_mgr)
    # ... (73 lines of setter calls, see Source for full body)
```

**Architecture concern:** This method is pure setter injection — it does not contain any *new* business logic, only the choreographed wiring. The extraction's value is removing 73 lines of inline call sequencing from `window.py`. The method itself should remain essentially unchanged, just moved to its own handler with all dependent handlers passed in via constructor.

**Class signature (verified against existing handler patterns — e.g., `GatewayHandler.__init__(self, toolbar, left_panel, on_agent_selected, on_event, ...)`):**

```python
class ConnectionSyncHandler:
    """
    Coordinates the post-connect wiring of live references into all dependent handlers.

    Called once by GatewayHandler via set_sync_callback() after on_connected() dispatches.
    All other handlers are constructed with None/stub references at composition time;
    this handler injects the live GatewayClient and AgentManager after the WebSocket
    handshake completes.

    Thread safety: called on the gateway's background thread via GLib.idle_add() in
    GatewayHandler.on_connected(). All handler setters must be main-thread safe.

    Args:
        chat_handler:           ChatHandler instance — receives GatewayClient
        main_content:           MainContent instance — receives AgentManager
        agent_list_handler:     AgentListHandler instance — receives AgentManager
        gateway_handler:        GatewayHandler instance — source of AgentManager
        project_handler:        ProjectHandler instance — receives AgentManager + ReviewHandler
        command_handler:        CommandHandler instance — receives GatewayClient + AgentManager
        agent_command_handler:  AgentCommandHandler instance — receives many live refs
        session_handler:        SessionHandler instance — receives AgentManager
        feed_handler:           FeedHandler instance — receives audit report callback
        left_panel:             LeftPanel instance — receives refresh trigger
        project_path_provider:  Callable[[], str | None] — for project path lookup
        agent_defs_loader:      Callable[[], list] | None — for agent defs loading
    """
    def __init__(self, *, chat_handler, main_content, agent_list_handler,
                 gateway_handler, project_handler, command_handler,
                 agent_command_handler, session_handler, feed_handler,
                 left_panel, project_path_provider, agent_defs_loader=None):
        ...

    def sync(self, gw: "GatewayClient") -> None:
        """
        Inject the live GatewayClient and AgentManager into all dependent handlers.
        Called once after gateway connect succeeds.
        """
        # Body: the 73 lines from window._sync_gateway_to_chat_handler, with
        # self._chat_handler → self._chat_handler, etc. (no other changes)
```

**Constructor parameters are keyword-only** (using `*`), matching the style of `AgentCommandHandler.__init__(self, *, GLib_module=None)`, `AgentListHandler.__init__(self, *, agent_mgr=None, ...)`, and `FeedHandler.__init__(self, *, GLib, ...)`.

**Imports required (verified against the file references in the extracted body):**
```python
from utils.agent_defs import load_agent_defs  # inside try/except, already exists
```

**Line count estimate:** +110 lines for the new file, −73 lines from window.py = +37 net

### Item 3b — `ui/handlers/forward_handler.py` (NEW)

**What changes:** Create a new handler that owns the logic for forwarding messages between agents. Move the body of `window._forward_to_agent()` and the popover-construction portion of `window._on_forward_clicked()` (lines 733–833) here.

**Architecture decision (boundary):** Looked at the current `_on_forward_clicked` (lines 733–775) — it builds a `Gtk.Popover` and creates button widgets. Extracting that GTK widget code into a handler would move UI construction out of `window.py` (good per ARCH §3.6) but would create a handler that depends heavily on `Gtk.*` types, which is normal for handlers (see `agent_builder_handler.py`, `review_handler.py`). Both `_on_forward_clicked` and `_forward_to_agent` should move together as a unit because they share the `popover` variable.

**Verified current code (read from source, window.py lines 733–833):**
- `_on_forward_clicked(self, text, anchor_widget, source_session_key=None)` — builds a `Gtk.Popover` of available agents, wires button clicks to `_forward_to_agent`
- `_forward_to_agent(self, target_session_key, text, source_session_key, popover)` — routes the forwarded text to the target agent, creates/selects the target tab, appends a bubble

**Class signature:**
```python
class ForwardHandler:
    """
    Manages the agent-to-agent message forwarding flow.

    Owns: the popover widget construction, target agent resolution, and
          forwarded bubble rendering.

    Thread safety: called only on the main thread (button click handler).

    Args:
        main_content:           MainContent — for create_chat_tab, get_chat_box,
                                 _chat_notebook.set_current_page, scroll_chat_to_bottom
        chat_handler:           ChatHandler — for set_on_forward_message wiring target
        chat_render_handler:    ChatRenderHandler — for render_sync (forwarded bubble)
        agent_runtime_handler:  AgentRuntimeHandler — for get_special_agents(),
                                 send_to_special_agent() (special agent routing)
        gateway_handler:        GatewayHandler — for agent_mgr.get_name(), gw.send_message()
    """
    def __init__(self, *, main_content, chat_handler, chat_render_handler,
                 agent_runtime_handler, gateway_handler):
        ...

    def show_forward_popover(self, text: str, anchor_widget,
                              source_session_key: str | None) -> None:
        """Build and display the forward-to-agent popover."""
        # Body: lines 733–775 of window.py

    def forward_to_agent(self, target_session_key: str, text: str,
                          source_session_key: str | None, popover) -> None:
        """Route forwarded text to target agent and show it in their tab."""
        # Body: lines 777–831 of window.py
```

**Imports required:**
```python
from gi.repository import GLib, Gtk  # verified: window.py:789 imports these
from utils.agent_defs import load_agent_defs  # already used, no new import here
```

**Subtle bug to preserve (not fix):** Line 825 references `self._chat_render_handler._on_forward_message` directly, which is `None` until `chat_handler.set_on_forward_message()` propagates the callback. This is a latent issue but is *not* in scope for this spec. The extraction must preserve the exact same behavior, not fix it.

**Line count estimate:** +120 lines for the new file, −101 lines from window.py (733 → 833) = +19 net

### Item 3 — `ui/window.py` modifications

**What changes:** Remove the three methods (`_sync_gateway_to_chat_handler`, `_on_forward_clicked`, `_forward_to_agent`) and replace them with handler instantiation + callback wiring.

**Verified current code patterns (from `_build()`, lines 88–421):**
- Handlers are instantiated with keyword args
- `self._chat_handler.set_on_forward_message(self._on_forward_clicked)` is on line 664 — this wire-up must be updated to point at the new `ForwardHandler` method

**Change 1:** In `_build()`, after the existing `self._command_handler = ...` line, add:
```python
# Item 3a — Connection sync handler
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
    project_path_provider=lambda: self._project_handler.get_active_project_path() if self._project_handler else None,
    agent_defs_loader=load_agent_defs,  # imported at top of _build
)
```

**Change 2:** In `_build()`, after the ForwardHandler is needed, add:
```python
# Item 3b — Forward handler
from ui.handlers.forward_handler import ForwardHandler
self._forward_handler = ForwardHandler(
    main_content=self._main_content,
    chat_handler=self._chat_handler,
    chat_render_handler=self._chat_render_handler,
    agent_runtime_handler=self._agent_runtime_handler,
    gateway_handler=self._gateway_handler,
)
self._chat_handler.set_on_forward_message(self._forward_handler.show_forward_popover)
```

**Change 3:** Update `GatewayHandler.set_sync_callback` call to point at the new handler:
```python
# Verified: currently (window.py:421 area) this points at self._sync_gateway_to_chat_handler
self._gateway_handler.set_sync_callback(self._connection_sync_handler.sync)
```

**Change 4:** Delete the three methods from `window.py`:
- Lines 611–685 (`_sync_gateway_to_chat_handler`) — 75 lines including blank line
- Lines 731–833 (`_on_forward_clicked` and `_forward_to_agent`) — 103 lines including blank line

**Line count estimate:** −178 lines from window.py

---

## 3. Data Flow

### Item 1 — workflow_state self-import

**Before:**
```
caller → advance_phase(project, name) → [line 11: from utils.workflow_state import ...] → resolve names
```

**After:**
```
caller → advance_phase(project, name) → resolve names from module scope
```

The function-level import was always redundant. `init_workflow`, `advance_phase`, and `get_current_phase` are all top-level functions in the same module, available at the time `advance_phase` is called. Removing the import shortens the function by one line with no behavior change.

### Item 2 — Test file deletion

No data flow change. Deletion of orphaned test files has no effect on production code.

### Item 3a — Connection sync

**Before:**
```
Gateway connect → GatewayHandler.on_connected() → idle_add(window._sync_gateway_to_chat_handler)
  → 73 lines of inline setter calls on 12+ handler instances
```

**After:**
```
Gateway connect → GatewayHandler.on_connected() → idle_add(window._connection_sync_handler.sync)
  → ConnectionSyncHandler.sync() runs the same 73 lines of setter calls
```

The flow is identical — only the method's home class changes. `set_sync_callback` already exists on `GatewayHandler` (verified at gateway_handler.py:117) and is designed exactly for this kind of deferred call.

### Item 3b — Forward flow

**Before:**
```
User clicks forward button → ChatRenderHandler renders bubble with on_forward_click callback
  → chat_handler._on_forward_message(text, anchor, source_session_key) → window._on_forward_clicked
  → builds Gtk.Popover → user clicks agent → window._forward_to_agent(target, text, source, popover)
  → routes to special/gateway agent, opens/selects target tab, renders bubble
```

**After:**
```
User clicks forward button → ChatRenderHandler renders bubble with on_forward_click callback
  → chat_handler._on_forward_message(text, anchor, source_session_key) → forward_handler.show_forward_popover
  → builds Gtk.Popover → user clicks agent → forward_handler.forward_to_agent(target, text, source, popover)
  → routes to special/gateway agent, opens/selects target tab, renders bubble
```

Same flow, one less hop through window.py. The callback wiring in `chat_handler.set_on_forward_message` is updated to point at the new handler method.

---

## 4. File Change Summary

| File | Change | Lines | Risk |
|---|---|---|---|
| `utils/workflow_state.py` | Remove line 11 self-import | −1 | **Trivial** (proven fix) |
| `tests/test_convergence.py` | Delete file | −303 | **Low** (dead test, no imports) |
| `tests/test_convergence.py.bak` | Delete file | −N | **Trivial** (backup) |
| `tests/test_convergence.py.insert` | Delete file | −N | **Trivial** (artifact) |
| `ui/handlers/connection_sync_handler.py` | New file | +110 | **Medium** (constructor wiring) |
| `ui/handlers/forward_handler.py` | New file | +120 | **Medium** (GTK widget construction) |
| `ui/window.py` | Remove 3 methods, add 2 handler instantiations, update 1 callback wire | −178 + ~20 | **Medium** (must preserve exact behavior) |
| `tests/test_connection_sync_handler.py` | New test file | +60 | **Low** |
| `tests/test_forward_handler.py` | New test file | +80 | **Low** |
| `docs/ARCHITECTURE.md` | Update §3.6 (window.py line count) and §8.2 (handler inventory) | +5 | **Low** |

**Net:** window.py goes from 833 → ~675 lines. Total handler count goes from 21 → 23.

---

## 5. Implementation Order

### Phase 1: ~~`utils/workflow_state.py` self-import~~ SKIPPED (verified N/A by QTR 2026-05-31)
- **Result:** Item 1 marked as not applicable. No code change to `utils/workflow_state.py`.
### Phase 2: Delete `test_convergence.py` and backups (Item 2)
- **Verify:** `ls tests/test_convergence*` returns "No such file or directory"
- **Verify:** `git ls-files tests/ | grep convergence` returns empty
- **Test:** `python3 -m pytest tests/ -q` — count decreases by however many tests `test_convergence.py` contributed (currently failing 0 of its tests, so count drops by total tests collected)
- **Estimated time:** 2 minutes

### Phase 3: Extract `ConnectionSyncHandler` (Item 3a)
- **Sub-phase 3a-1:** Create `ui/handlers/connection_sync_handler.py` with the class and `sync()` method
- **Sub-phase 3a-2:** Update `ui/window.py` — instantiate handler, update `set_sync_callback`, delete old method
- **Sub-phase 3a-3:** Create `tests/test_connection_sync_handler.py` covering all setter calls
- **Verify after each sub-phase:** `python3 -m pytest tests/test_connection_sync_handler.py -v` if applicable
- **Final verify:** `python3 -m pytest tests/ -q` — count must be ≥ 1601
- **Estimated time:** 20 minutes

### Phase 4: Extract `ForwardHandler` (Item 3b)
- **Sub-phase 4b-1:** Create `ui/handlers/forward_handler.py` with `show_forward_popover()` and `forward_to_agent()` methods
- **Sub-phase 4b-2:** Update `ui/window.py` — instantiate handler, update `set_on_forward_message` callback, delete old methods
- **Sub-phase 4b-3:** Create `tests/test_forward_handler.py` covering popover construction, special-agent routing, gateway-agent routing, tab creation
- **Verify after each sub-phase:** `python3 -m pytest tests/test_forward_handler.py -v`
- **Final verify:** `python3 -m pytest tests/ -q` — count must be ≥ 1601
- **Estimated time:** 30 minutes (GTK popover testing is tricky)

### Phase 5: Update `ARCHITECTURE.md`
- Update §3.6 example line count (was 833, now ~675)
- Update §8.2 handler inventory (add ConnectionSyncHandler, ForwardHandler — 21 → 23 handlers)
- Update §12 file inventory
- **Verify:** grep for old line counts returns 0; grep for new handler names returns 1 match
- **Estimated time:** 5 minutes

### Phase 6: Full adversarial audit
- Re-read the implementation, run adversarialDebugger methodology
- Check for regressions in adjacent functionality (gateway connect, special agents, tab creation)
- Verify no handler cross-imports
- **Estimated time:** 15 minutes

### Phase 7: Post-mortem
- Grade the implementation
- Document lessons learned
- Write to `docs/post-mortems/2026-06-XX-cleanup-spec.md`
- **Estimated time:** 10 minutes

---

## 6. Acceptance Criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | `utils/workflow_state.py` no longer has any self-import | `grep "from utils.workflow_state" utils/workflow_state.py` returns 0 |
| 2 | `utils/workflow_state.py` functions still work | `advance_phase`, `init_workflow`, `get_current_phase` importable and callable |
| 3 | `tests/test_convergence.py`, `.bak`, `.insert` deleted | `ls tests/test_convergence*` fails |
| 4 | `ui/handlers/connection_sync_handler.py` exists with `ConnectionSyncHandler` class | `python3 -c "from ui.handlers.connection_sync_handler import ConnectionSyncHandler; print('OK')"` |
| 5 | `ui/handlers/forward_handler.py` exists with `ForwardHandler` class | `python3 -c "from ui.handlers.forward_handler import ForwardHandler; print('OK')"` |
| 6 | `ui/window.py` no longer has `_sync_gateway_to_chat_handler` method | `grep "_sync_gateway_to_chat_handler" ui/window.py` returns 0 |
| 7 | `ui/window.py` no longer has `_forward_to_agent` method | `grep "_forward_to_agent" ui/window.py` returns 0 |
| 8 | `ui/window.py` no longer has `_on_forward_clicked` method | `grep "_on_forward_clicked" ui/window.py` returns 0 |
| 9 | `ui/window.py` line count is < 700 | `wc -l ui/window.py` |
| 10 | Full test suite passes with no new regressions | `python3 -m pytest tests/ -q` shows ≥ 1601 passed |
| 11 | New handler tests pass | `pytest tests/test_connection_sync_handler.py tests/test_forward_handler.py -v` shows 0 failures |
| 12 | ARCHITECTURE.md reflects the new handler count (23) | `grep "ConnectionSyncHandler\|ForwardHandler" docs/ARCHITECTURE.md` returns 2+ matches |
| 13 | No handler cross-imports | `grep -r "from ui.handlers" ui/handlers/` shows no handler→handler imports |
| 14 | Commits pushed to origin/main | `git log origin/main -1` shows the cleanup commit |

---

## 7. Edge Cases

| Case | Expected Behavior |
|---|---|
| `workflow_state.py` called at module import time | `advance_phase` still resolves `init_workflow` from module scope — must be verified that import order is correct |
| `workflow_state.py` is itself imported by another module that triggers `advance_phase` at import time | No change — the self-import was a no-op for name resolution, just slower |
| `ConnectionSyncHandler.sync()` called before gateway connects | Should not happen — `set_sync_callback` only fires from `on_connected`. Defensive: if `gw` is None, log error and return. (Match current behavior — the current method assumes gw is not None.) |
| `ForwardHandler.show_forward_popover()` called when no other agents exist | Build empty popover? Or return early? — current behavior returns early at `if not other_sessions: return`. Preserve this. |
| `ForwardHandler.forward_to_agent()` called when target tab exists | Selects existing tab via `_chat_notebook.set_current_page(target_tab_exists)` — preserve |
| `ForwardHandler.forward_to_agent()` called when gateway is not connected | Returns early at `if gw is None or not gw.is_connected(): return` — preserve |
| `ForwardHandler.forward_to_agent()` called for a special agent | Routes to `agent_runtime_handler.send_to_special_agent` — preserve |
| Tests for `ConnectionSyncHandler` — what if a setter changes? | Tests should verify the *intent* (e.g., "chat_handler receives gw") not the implementation (e.g., "set_gateway_client was called with gw") |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update the following sections:

### §3.6 (window.py as composition root)
- Update line count from 833 → ~675
- Note that `_sync_gateway_to_chat_handler`, `_on_forward_clicked`, and `_forward_to_agent` were extracted to `ConnectionSyncHandler` and `ForwardHandler`

### §8.2 (Handler inventory)
- Add `ConnectionSyncHandler` to the list: "Coordinates post-connect wiring of live references into all dependent handlers"
- Add `ForwardHandler` to the list: "Manages agent-to-agent message forwarding popover and routing"
- Update total count from 21 → 23

### §12 (File inventory)
- Add `ui/handlers/connection_sync_handler.py` to the handlers list
- Add `ui/handlers/forward_handler.py` to the handlers list
- Add `tests/test_connection_sync_handler.py` to the tests list
- Add `tests/test_forward_handler.py` to the tests list
- Note removal of `tests/test_convergence.py` and backups

### Quick Reference tree (§2)
- Add the two new handler files to the directory tree
- Remove `test_convergence.py` and friends

---

## Spec Self-Audit (Rule 9)

1. **Does every code sample actually work against the current codebase?** — Yes, all signatures verified via `inspect.signature()` against the live modules. The `ConnectionSyncHandler.__init__` follows the same kwargs-only pattern as `AgentCommandHandler`, `AgentListHandler`, and `FeedHandler`. The `ForwardHandler.__init__` follows the same pattern.

2. **Did I catch all exception types for every function I call?** — The only exception handler in the extracted methods is the bare `except: pass` around `from utils.agent_defs import load_agent_defs` (line 670 of window.py). This is preserved as-is (not fixing in this spec).

3. **Did I verify key structures, not assume them?** — `_tab_sessions.items()` iteration in `_forward_to_agent` verified at line 813. The key is `page_idx` (int) → `session_key` (str), not the reverse. Preserved.

4. **Did I trace the data flow end-to-end?** — Yes, see §3.

5. **Would an implementer who follows this spec exactly produce working code?** — Yes, with the caveat that the GTK popover construction in `_on_forward_clicked` requires GTK available at test time. Tests should mock the `Gtk.Popover` and `Gtk.Button` interactions.

**Known limitations:**
- The line 825 reference to `self._chat_render_handler._on_forward_message` is preserved as a latent issue, not fixed. Out of scope.
- The bare `except: pass` is preserved as a latent issue, not fixed. Out of scope.
- The `ConnectionSyncHandler` has 12 constructor parameters — this is high. Could be reduced by passing a `handlers` dict or a facade, but that's a separate refactor.
