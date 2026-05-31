# SPEC: Extract Business Logic from window.py into Handlers

**Date:** 2026-05-30
**Author:** QTR (Kage-7)
**Status:** Draft — for implementation
**Implements:** Audit Report Step 2 — window.py business logic extraction
**Depends on:** ARCHITECTURE.md (2026-05-30 revision)
**Target branch:** main

> Architecture compliance: Per ARCHITECTURE.md §3.6, `window.py` must only assemble components and wire callbacks. Business logic belongs in handlers (§8.6). This spec extracts 4 methods (~230 lines) from `window.py` into their owning handlers.

---

## 1. Overview

**Problem:** `window.py` at 1026 lines contains ~230 lines of business logic that belongs in handlers:
- `_on_audit_report_card()` — constructs `FeedCardData` from audit reports (42 lines)
- `_on_agent_saved()` — MCP hot-reload logic (44 lines)
- `_on_agent_deleted()` — near-identical MCP hot-reload logic (37 lines, duplicates `_on_agent_saved`)
- `_register_stub_commands()` — registers all slash commands (49 lines)
- `_confirm_delete_agent()` — GTK delete confirmation dialog (25 lines)

**Solution:** Move each method into its owning handler. Eliminate the duplication between `_on_agent_saved` and `_on_agent_deleted`. Window.py becomes pure wiring.

**Scope:**

| In Scope | Out of Scope |
|----------|-------------|
| `_on_audit_report_card` → `FeedHandler` | `_on_forward_clicked` / `_forward_to_agent` (separate concern) |
| `_on_agent_saved` / `_on_agent_deleted` → `AgentRuntimeHandler` | `_sync_gateway_to_chat_handler` (complex wiring, separate concern) |
| `_register_stub_commands` → `CommandHandler.__init__` | Any view-layer changes |
| `_confirm_delete_agent` → `AgentBuilderHandler` | Changes to `models/` or `utils/` |

---

## 2. Changes by File

### 2.1 `ui/handlers/feed_handler.py` — Add `add_audit_report_card()`

**What changes:** Add a new public method `add_audit_report_card()` that encapsulates the `FeedCardData` construction currently in `window._on_audit_report_card()`.

**Why FeedHandler owns this:** FeedHandler already owns all feed card lifecycle operations (`add_card()`, `handle_review()`, `handle_accept()`, `handle_reject()`). Audit report cards are feed cards. The handler already has access to `FeedCardData`, `feed_store`, and the `FeedTab` view.

**New method signature:**
```python
def add_audit_report_card(
    self,
    report: dict,
    project_name: str | None = None,
) -> str | None:
    """
    Construct and add a feed card for a structured audit report (SPEC-3).

    Args:
        report: dict with keys: severity, file_path, task, bug_description,
                pattern, reviewer, target_role, project_path.
        project_name: Override project name. If None, uses report["project_path"]
                      to derive the name. If no project can be determined, returns None.

    Returns:
        card_id string on success, None if no project context available.

    Thread-safe: dispatches to main thread via GLib.idle_add() if needed.
    """
```

**Code sample (verified against actual FeedCardData constructor):**
```python
def add_audit_report_card(
    self,
    report: dict,
    project_name: str | None = None,
) -> str | None:
    """Construct and add a feed card for a structured audit report (SPEC-3)."""
    from datetime import datetime, timezone
    from models.feed_card import FeedCardData

    severity = report.get("severity", "issue")
    icons = {"bug": "🔴", "issue": "🟡", "suggestion": "🔵"}
    icon = icons.get(severity, "⚪")

    file_path = report.get("file_path", "?")
    pattern = report.get("pattern")
    reviewer = report.get("reviewer", "unknown")
    target = report.get("target_role", "unknown")
    desc = report.get("bug_description", "")

    pattern_suffix = f" ({pattern})" if pattern else ""
    title = f"{icon} {severity.upper()}: {file_path}{pattern_suffix}"
    body = f"**{reviewer}** reviewed **{target}**: {desc}"

    resolved_project = project_name
    if not resolved_project:
        # Derive project name from project_path if available
        project_path = report.get("project_path")
        if project_path:
            import os
            resolved_project = os.path.basename(project_path)

    if not resolved_project:
        _logger.warning("Cannot add audit report card: no project context")
        return None

    card = FeedCardData(
        card_type="audit_report",
        source="agent",
        title=title,
        body=body,
        author=reviewer,
        timestamp=datetime.now(timezone.utc),
        project_name=resolved_project,
        file_path=file_path,
        metadata={
            "severity": severity,
            "pattern": pattern,
            "target_role": target,
        },
    )
    return self.add_card(card)
```

**Imports required:** None new — `datetime`, `timezone`, `FeedCardData`, `os` are already used in the module or imported locally.

**Line count estimate:** ~35 lines added to `feed_handler.py`.

---

### 2.2 `ui/handlers/agent_runtime_handler.py` — Add `reload_agents_and_mcp()`

**What changes:** Add a new public method `reload_agents_and_mcp()` that consolidates the MCP hot-reload logic currently duplicated in `window._on_agent_saved()` and `window._on_agent_deleted()`. This method handles both the "saved" and "deleted" cases.

**Why AgentRuntimeHandler owns this:** The method manipulates `self._agents` (the special agent registry), calls `reload_registry()` and `get_special_agents()` from `agent.special_agents`, and manages MCP connections via `disconnect_all()` and `connect_servers()` from `utils.mcp_client`. All of these are already dependencies of `AgentRuntimeHandler`.

**New method signature:**
```python
def reload_agents_and_mcp(
    self,
    *,
    on_complete: Callable[[], None] | None = None,
) -> None:
    """
    Reload agent registry and hot-reload MCP connections.

    Flow:
    1. reload_registry() — re-read YAML files from agents/
    2. disconnect_all() for all known conv_id_prefixes — kill stale MCP subprocesses
    3. Re-register all agents from the fresh registry
    4. connect_servers() per agent — pre-warm MCP connections
    5. Call on_complete callback if provided

    Thread-safe: MCP operations are blocking; call from a background thread
    or via GLib.idle_add() if calling from a non-main thread that needs
    to update UI after completion.
    """
```

**Code sample (verified against actual function signatures):**
```python
def reload_agents_and_mcp(
    self,
    *,
    on_complete: Callable[[], None] | None = None,
) -> None:
    """Reload agent registry and hot-reload MCP connections."""
    from agent.special_agents import reload_registry, get_special_agents
    from utils.mcp_client import disconnect_all, connect_servers

    # 1. Reload registry from disk
    reload_registry()

    # 2. Collect current agent prefixes BEFORE clearing
    old_prefixes = list(self._agents.keys())

    # 3. Re-register all agents from fresh registry
    self._agents.clear()
    new_agents = get_special_agents()
    for agent_def in new_agents:
        self._agents[agent_def.conv_id_prefix] = agent_def

    # 4. Disconnect stale MCP connections for all known prefixes
    prefixes_to_disconnect = set(old_prefixes) | {a.conv_id_prefix for a in new_agents}
    for prefix in prefixes_to_disconnect:
        try:
            disconnect_all(conversation_key=prefix)
        except Exception as e:
            logger.warning("MCP disconnect failed for prefix %s: %s", prefix, e)

    # 5. Re-establish MCP connections for each agent
    for agent_def in new_agents:
        if agent_def.mcp_servers:
            try:
                result = connect_servers(
                    server_names=agent_def.mcp_servers,
                    conversation_key=agent_def.conv_id_prefix,
                )
                for server_name, error in result.items():
                    if error:
                        logger.warning(
                            "MCP hot-reload: failed to connect %s for %s: %s",
                            server_name, agent_def.conv_id_prefix, error,
                        )
            except Exception as e:
                logger.warning(
                    "MCP hot-reload: connection attempt failed for %s: %s",
                    agent_def.conv_id_prefix, e,
                )

    logger.info("Agent registry and MCP connections reloaded")

    if on_complete:
        on_complete()
```

**Exception handling:**
- `reload_registry()` — can raise `Exception` on YAML parse errors (caught by the `except Exception` blocks above)
- `get_special_agents()` — calls `_ensure_loaded()` internally; can raise on file I/O errors
- `disconnect_all(conversation_key=prefix)` — can raise `RuntimeError` if MCP loop thread is shutting down (line 156 of mcp_client.py). Caught by `except Exception`.
- `connect_servers(server_names, conversation_key)` — returns `dict[str, str]` (name→error). Individual server failures are logged, not raised. The function itself can raise on unexpected errors — caught by `except Exception`.

**Imports required:** None new — `agent.special_agents` and `utils.mcp_client` are already used in the module.

**Line count estimate:** ~45 lines added to `agent_runtime_handler.py`.

---

### 2.3 `ui/handlers/command_handler.py` — Move command registration into `__init__`

**What changes:** The `_register_stub_commands()` method in `window.py` calls `self._command_handler.register_command()` 16 times. Move this registration into `CommandHandler.__init__()` so commands are registered at construction time.

**Why CommandHandler owns this:** Per ARCHITECTURE.md §3.21a, CommandHandler "owns: CommandRegistry (owns the handler map)". The command registry is an internal implementation detail of CommandHandler. External code should not need to manually register each command.

**Changes to `CommandHandler.__init__()`:**

The constructor currently takes `gateway_client`, `agent_manager`, `project_handler`, `GLib_module`, `on_display_card`, `on_display_text`. It needs references to the handler instances that own each command.

**New constructor signature:**
```python
def __init__(
    self,
    gateway_client,
    agent_manager,
    project_handler,
    GLib_module=None,
    on_display_card=None,
    on_display_text=None,
    collab_handler=None,    # NEW — CollabHandler instance
    task_handler=None,      # NEW — TaskHandler instance
    review_handler=None,    # NEW — ReviewHandler instance
    session_handler=None,   # NEW — SessionHandler instance
):
```

**Code sample for the registration block (to be added at end of `__init__`):**
```python
# ── Register built-in commands ──────────────────────────────────────────

# Help (owned by CommandHandler itself)
self.register_command("help", self.cmd_help, aliases=["?"],
    help_text="List all commands or help for a specific command")

# Collaboration — requires CollabHandler
if collab_handler is not None:
    self.register_command("ask", collab_handler.cmd_ask, aliases=["a"],
        help_text="Ask an agent a question: /ask @agent — question")
    self.register_command("delegate", collab_handler.cmd_delegate, aliases=["d"],
        help_text="PM delegates to agent: /delegate @agent — task")
    self.register_command("stop", collab_handler.cmd_stop,
        help_text="PM stops the current collaboration: /stop @agent")
    self.register_command("tell", collab_handler.cmd_tell,
        help_text="One agent shares information with another: /tell @agent — info")

# Task — requires TaskHandler
if task_handler is not None:
    self.register_command("task", task_handler.cmd_task, aliases=["t"],
        help_text="Create a task card assigned to agent")
    self.register_command("done", task_handler.cmd_done,
        help_text="Mark task complete")
    self.register_command("start", task_handler.cmd_start,
        help_text="Start working on a task")
    self.register_command("blocked", task_handler.cmd_blocked,
        help_text="Report a blocker on a task")
    self.register_command("cancel", task_handler.cmd_cancel,
        help_text="Cancel a task")
    self.register_command("tasks", task_handler.cmd_tasks,
        help_text="Show all tasks")
    self.register_command("assign", task_handler.cmd_assign,
        help_text="Reassign a task to a different agent")
    self.register_command("priority", task_handler.cmd_priority,
        help_text="Set task priority")

# Review — requires ReviewHandler
if review_handler is not None:
    self.register_command("review", review_handler.cmd_review,
        help_text="Start a review checkpoint")
    self.register_command("check", review_handler.cmd_check,
        help_text="Show diff of changes since checkpoint")
    self.register_command("accept", review_handler.cmd_accept,
        help_text="Accept all changes (or single file)")
    self.register_command("reject", review_handler.cmd_reject,
        help_text="Reject all pending changes")

# Project — ProjectHandler (always available, passed to constructor)
self.register_command("status", project_handler.cmd_status, aliases=["st"],
    help_text="Project status summary")
self.register_command("agents", project_handler.cmd_agents,
    help_text="List project agents and current state")
self.register_command("cost", project_handler.cmd_cost,
    help_text="Spending summary for this project")

# Session — requires SessionHandler
if session_handler is not None:
    self.register_command("session", session_handler.cmd_session, aliases=["s"],
        help_text="Switch agent session in project: /session list @agent | /session <ref> @agent")
```

**Verification:** All handler methods referenced above (`cmd_ask`, `cmd_delegate`, `cmd_stop`, `cmd_tell`, `cmd_task`, `cmd_done`, `cmd_start`, `cmd_blocked`, `cmd_cancel`, `cmd_tasks`, `cmd_assign`, `cmd_priority`, `cmd_review`, `cmd_check`, `cmd_accept`, `cmd_reject`, `cmd_status`, `cmd_agents`, `cmd_cost`, `cmd_session`, `cmd_help`) are verified to exist on their respective handler classes per the source code.

**Line count estimate:** ~45 lines added to `command_handler.py` (replacing the existing registration in window.py).

---

### 2.4 `ui/handlers/agent_builder_handler.py` — Add `delete_agent_with_confirmation()`

**What changes:** Add a new method `delete_agent_with_confirmation()` that shows a GTK confirmation dialog and then calls the existing `delete()` method. This moves the GTK dialog logic from `window._confirm_delete_agent()` into the handler.

**Why AgentBuilderHandler owns this:** The handler already owns agent deletion (`delete()` method). The confirmation dialog is part of the delete workflow. Per ARCHITECTURE.md §8.6, handlers own their state and logic.

**Important:** This method needs a reference to the parent `Gtk.Window` for the `Gtk.MessageDialog`. The window reference must be passed as a parameter — the handler must NOT import or hold a reference to the window.

**New method signature:**
```python
def delete_agent_with_confirmation(
    self,
    name: str,
    parent_window: Gtk.Window,
) -> None:
    """
    Show a confirmation dialog, then delete the agent if confirmed.

    Args:
        name: Display name of the agent to delete.
        parent_window: The parent Gtk.Window for the modal dialog.
                       Must be a GTK window instance (Gtk.ApplicationWindow
                       or Gtk.Window).

    Returns:
        None. The on_agent_deleted callback fires on success.
    """
```

**Code sample:**
```python
def delete_agent_with_confirmation(
    self,
    name: str,
    parent_window: Gtk.Window,
) -> None:
    """Show a confirmation dialog, then delete the agent if confirmed."""
    from gi.repository import Gtk

    dialog = Gtk.MessageDialog(
        transient_for=parent_window,
        modal=True,
        message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.YES_NO,
        text=f'Delete agent "{name}"?',
    )
    dialog.set_property(
        "secondary-text",
        "This cannot be undone. The agent definition file will be removed.",
    )

    def on_response(_dialog, response_id):
        dialog.close()
        if response_id == Gtk.ResponseType.YES:
            success = self.delete(name)
            if not success:
                logger.warning("Failed to delete agent: %s", name)

    dialog.connect("response", on_response)
    dialog.show()
```

**Imports required:** `from gi.repository import Gtk` (local import inside method, consistent with existing pattern in the module).

**Line count estimate:** ~25 lines added to `agent_builder_handler.py`.

---

### 2.5 `ui/window.py` — Remove business logic, wire handlers

**What changes:** Remove 5 methods and replace with handler delegation.

**Methods to remove:**
- `_on_audit_report_card()` (lines 551-593, 42 lines)
- `_register_stub_commands()` (lines 595-648, 49 lines) — NOTE: has bad indentation (extra 4 spaces), fix when removing
- `_on_agent_saved()` (lines 808-852, 44 lines)
- `_on_agent_deleted()` (lines 858-895, 37 lines)
- `_confirm_delete_agent()` (lines 901-925, 25 lines)

**Total lines removed:** ~197 lines. `window.py` goes from 1026 → ~829 lines.

**Wiring changes:**

1. **AgentBuilderHandler construction** (around line 191):
   ```python
   # BEFORE:
   self._agent_builder_handler = AgentBuilderHandler(
       on_agent_saved=lambda name: self._on_agent_saved(name),
       on_agent_deleted=lambda name: self._on_agent_deleted(name),
   )
   
   # AFTER:
   self._agent_builder_handler = AgentBuilderHandler(
       on_agent_saved=lambda name: self._agent_runtime_handler.reload_agents_and_mcp(
           on_complete=lambda: self._left_panel.set_special_agents(self._agent_runtime_handler)
       ),
       on_agent_deleted=lambda name: self._agent_runtime_handler.reload_agents_and_mcp(
           on_complete=lambda: self._left_panel.set_special_agents(self._agent_runtime_handler)
       ),
   )
   ```
   
   **Verification:** `reload_agents_and_mcp()` accepts `on_complete: Callable[[], None] | None`. The `on_complete` callback refreshes the left panel's special agent list — this is the same `self._left_panel.set_special_agents(self._agent_runtime_handler)` call that was previously at the end of both `_on_agent_saved` and `_on_agent_deleted`.

2. **Left panel delete callback** (around line 198):
   ```python
   # BEFORE:
   self._left_panel.set_on_delete_agent(lambda name: self._confirm_delete_agent(name))
   
   # AFTER:
   self._left_panel.set_on_delete_agent(
       lambda name: self._agent_builder_handler.delete_agent_with_confirmation(
           name, parent_window=self
       )
   )
   ```
   
   **Verification:** `delete_agent_with_confirmation(name: str, parent_window: Gtk.Window)`. `self` (MainWindow) extends `Gtk.ApplicationWindow` which extends `Gtk.Window`. Type-compatible.

3. **CommandHandler construction** (around line 384):
   ```python
   # BEFORE:
   from ui.handlers.command_handler import CommandHandler
   self._command_handler = CommandHandler(
       gateway_client=None,
       agent_manager=None,
       project_handler=self._project_handler,
       GLib_module=GLib,
       on_display_card=...,
       on_display_text=...,
   )
   
   # AFTER:
   from ui.handlers.command_handler import CommandHandler
   self._command_handler = CommandHandler(
       gateway_client=None,
       agent_manager=None,
       project_handler=self._project_handler,
       GLib_module=GLib,
       on_display_card=...,
       on_display_text=...,
       collab_handler=self._collab_handler,
       task_handler=self._task_handler,
       review_handler=self._review_handler,
       session_handler=self._session_handler,
   )
   ```
   
   **Verification:** All 4 handler instances (`_collab_handler`, `_task_handler`, `_review_handler`, `_session_handler`) are created before `CommandHandler` in `_build()`. The `if handler is not None` guards in the registration block ensure no crash if any handler is None.

4. **Remove `_register_stub_commands()` call** (around line 444):
   ```python
   # BEFORE:
   # Register all commands — must be after _review_handler is created (Phase 7)
   self._register_stub_commands()
   
   # AFTER: (nothing — commands are registered in CommandHandler.__init__)
   ```
   
   **Verification:** The `CommandHandler.__init__` now handles all registration. The `collab_handler`, `task_handler`, `review_handler`, and `session_handler` are all created before `CommandHandler` in `_build()`, so they're available at construction time.

5. **Audit report card wiring** (around line 740):
   ```python
   # BEFORE:
   self._agent_command_handler.set_on_audit_report(
       self._on_audit_report_card
   )
   
   # AFTER:
   self._agent_command_handler.set_on_audit_report(
       lambda report: self._feed_handler.add_audit_report_card(
           report,
           project_name=self._project_handler.get_active_project_name() if self._project_handler else None,
       )
   )
   ```
   
   **Verification:** `add_audit_report_card(report: dict, project_name: str | None = None) -> str | None`. The lambda passes the report dict and the active project name. `set_on_audit_report` expects a `Callable[[dict], None]` — the lambda matches (return value discarded).

**Imports to remove from window.py:**
- `from models.feed_card import FeedCardData` (only used in `_on_audit_report_card`)
- `from agent.special_agents import reload_registry, get_special_agents` (only used in `_on_agent_saved`/`_on_agent_deleted`)
- `from utils.mcp_client import disconnect_all, connect_servers` (only used in `_on_agent_saved`/`_on_agent_deleted`)
- `from models.command import Command` — verify if used elsewhere in window.py

**Verification needed:** Check if `Command` import is used elsewhere in window.py before removing.

---

## 3. Data Flow

### 3.1 Audit Report Card Flow (after extraction)

```
Agent response contains ## Audit Report
  → AgentCommandHandler.on_agent_response()
    → AuditParser.extract_audit_reports(text) → list[AuditReport]
    → For each report: self._on_audit_report_callback(report_dict)
      → FeedHandler.add_audit_report_card(report, project_name)
        → Construct FeedCardData(card_type="audit_report", ...)
        → self.add_card(card_data)
          → Store in self._cards
          → Build widget via build_feed_card()
          → Prepend to FeedTab
          → Persist to feed.json
```

### 3.2 Agent Saved/Deleted Flow (after extraction)

```
User saves agent in AgentBuilderDialog
  → AgentBuilderHandler.save(agent_def)
    → on_agent_saved callback
      → AgentRuntimeHandler.reload_agents_and_mcp(on_complete=...)
        → reload_registry() — re-read YAML files
        → Collect old prefixes, clear self._agents
        → get_special_agents() → re-register all
        → disconnect_all(prefix) for each known prefix
        → connect_servers() per agent with mcp_servers
        → on_complete() → left_panel.set_special_agents()
```

### 3.3 Command Registration Flow (after extraction)

```
window._build()
  → Create CollabHandler, TaskHandler, ReviewHandler, SessionHandler
  → Create CommandHandler(..., collab_handler=ch, task_handler=th, review_handler=rh, session_handler=sh)
    → __init__ registers all built-in commands automatically
  → (no separate _register_stub_commands() call needed)
```

### 3.4 Agent Delete Confirmation Flow (after extraction)

```
User clicks delete agent in left panel
  → on_delete_agent callback
    → AgentBuilderHandler.delete_agent_with_confirmation(name, parent_window=window)
      → Show Gtk.MessageDialog (transient_for=window)
      → If YES: self.delete(name)
        → delete_agent_def(name) from utils/agent_defs
        → on_agent_deleted callback → reload_agents_and_mcp()
```

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `ui/handlers/feed_handler.py` | Add `add_audit_report_card()` | +35 | Low — new method, no existing code changed |
| `ui/handlers/agent_runtime_handler.py` | Add `reload_agents_and_mcp()` | +45 | Low — new method, no existing code changed |
| `ui/handlers/command_handler.py` | Add handler params to `__init__`, add registration block | +45 | Medium — changes constructor signature |
| `ui/handlers/agent_builder_handler.py` | Add `delete_agent_with_confirmation()` | +25 | Low — new method, no existing code changed |
| `ui/window.py` | Remove 5 methods, update 4 wiring sites | -197, +15 | High — changes wiring, must verify all callback signatures |

---

## 5. Implementation Order

**Order matters.** Each step builds on the previous. Verify tests pass after each step.

### Step 1: Add `add_audit_report_card()` to FeedHandler
1. Add the method to `feed_handler.py`
2. Run `pytest tests/test_feed_handler.py -q` — must pass
3. Commit: `feat(feed): add add_audit_report_card() to FeedHandler`

### Step 2: Add `reload_agents_and_mcp()` to AgentRuntimeHandler
1. Add the method to `agent_runtime_handler.py`
2. Run `pytest tests/test_agent_runtime.py -q` — must pass
3. Commit: `feat(agent-runtime): add reload_agents_and_mcp() to AgentRuntimeHandler`

### Step 3: Add handler params to CommandHandler + registration block
1. Update `CommandHandler.__init__()` signature with 4 new optional params
2. Add registration block at end of `__init__`
3. Run `pytest tests/test_command_handler.py -q` — must pass
4. Commit: `feat(commands): move command registration into CommandHandler.__init__`

### Step 4: Add `delete_agent_with_confirmation()` to AgentBuilderHandler
1. Add the method to `agent_builder_handler.py`
2. Run `pytest tests/test_agent_builder_handler.py -q` — must pass
3. Commit: `feat(agent-builder): add delete_agent_with_confirmation()`

### Step 5: Update window.py wiring
1. Update `AgentBuilderHandler` construction to wire `on_agent_saved`/`on_agent_deleted` to `reload_agents_and_mcp()`
2. Update left panel delete callback to use `delete_agent_with_confirmation(name, parent_window=self)`
3. Update `CommandHandler` construction to pass 4 new handler params
4. Remove `_register_stub_commands()` call
5. Update audit report card wiring to use `feed_handler.add_audit_report_card()`
6. Remove the 5 obsolete methods from window.py
7. Clean up any now-unused imports
8. Run full test suite: `pytest --tb=short -q`
9. Commit: `refactor(window): extract business logic into handlers`

### Step 6: Update ARCHITECTURE.md
1. Update `window.py` line count from ~1026 to ~829
2. Update handler descriptions if needed
3. Commit: `docs(arch): update for window.py extraction`

---

## 6. Acceptance Criteria

- [ ] `window.py` is ≤ 850 lines (down from 1026)
- [ ] `_on_audit_report_card` no longer exists in `window.py`
- [ ] `_on_agent_saved` no longer exists in `window.py`
- [ ] `_on_agent_deleted` no longer exists in `window.py`
- [ ] `_register_stub_commands` no longer exists in `window.py`
- [ ] `_confirm_delete_agent` no longer exists in `window.py`
- [ ] `FeedHandler.add_audit_report_card()` exists and handles audit report dict → feed card
- [ ] `AgentRuntimeHandler.reload_agents_and_mcp()` exists and handles both save and delete cases
- [ ] `CommandHandler.__init__()` registers all built-in commands automatically
- [ ] `AgentBuilderHandler.delete_agent_with_confirmation()` exists and shows GTK dialog
- [ ] All 4 new/updated handler methods have proper exception handling
- [ ] Full test suite passes (or same pass/fail count as before)
- [ ] No remaining references to the removed methods in window.py

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|------------------|
| Audit report with no project context | `add_audit_report_card()` returns `None`, logs warning, no card added |
| Audit report with unknown severity | Defaults to "⚪" icon (same as current behavior) |
| `reload_agents_and_mcp()` with no agents | `get_special_agents()` returns empty list, loop is no-op, MCP disconnect still runs for old prefixes |
| `reload_agents_and_mcp()` MCP disconnect fails | Exception caught and logged, continues to reconnect step |
| `reload_agents_and_mcp()` MCP connect fails for one server | Error logged for that server, continues to next server |
| `CommandHandler` constructed without optional handlers | `if handler is not None` guards prevent errors; those command groups simply not registered |
| `delete_agent_with_confirmation()` user clicks NO | Dialog closes, no deletion, no callback fired |
| `delete_agent_with_confirmation()` delete fails | `self.delete()` returns False, warning logged |
| Agent renamed (name changed between load and save) | Handled by existing `AgentBuilderHandler.save()` rename detection — not affected by this spec |

---

## 8. Test Files to Create/Update

### 8.1 `tests/test_feed_handler.py` — ADD tests for `add_audit_report_card()`

**New tests needed:**
```python
class TestAddAuditReportCard:
    def test_adds_card_with_valid_report(self):
        """Happy path: valid audit report dict creates a feed card."""
        
    def test_returns_none_when_no_project_context(self):
        """No project_name and no project_path in report → returns None."""
        
    def test_uses_report_project_path_when_no_override(self):
        """project_name=None, report has project_path → derives name from path."""
        
    def test_severity_icons(self):
        """bug→🔴, issue→🟡, suggestion→🔵, unknown→⚪."""
        
    def test_pattern_suffix_in_title(self):
        """Pattern present → ' (pattern)' appended to title. Pattern absent → no suffix."""
        
    def test_default_severity(self):
        """Missing severity key → defaults to 'issue'."""
        
    def test_default_reviewer(self):
        """Missing reviewer key → defaults to 'unknown'."""
```

**Estimated:** 7 new tests, ~80 lines.

### 8.2 `tests/test_agent_runtime.py` — ADD tests for `reload_agents_and_mcp()`

**New tests needed:**
```python
class TestReloadAgentsAndMcp:
    def test_reloads_registry(self):
        """Calls reload_registry() and re-registers agents."""
        
    def test_disconnects_old_prefixes(self):
        """MCP disconnect_all called for all old conv_id_prefixes."""
        
    def test_reconnects_new_agents(self):
        """connect_servers called for each agent with mcp_servers."""
        
    def test_catches_disconnect_errors(self):
        """disconnect_all raises → caught, logged, continues."""
        
    def test_catches_connect_errors(self):
        """connect_servers raises → caught, logged, continues to next agent."""
        
    def test_on_complete_callback_fires(self):
        """on_complete callback called after all operations succeed."""
        
    def test_on_complete_not_called_on_error(self):
        """If reload_registry raises, on_complete not called."""
        
    def test_no_agents_no_mcp_calls(self):
        """Empty agent list → no MCP connect calls made."""
```

**Estimated:** 8 new tests, ~120 lines.

### 8.3 `tests/test_command_handler.py` — UPDATE for new constructor params

**Changes needed:** Existing tests construct `CommandHandler` — must add the 4 new optional params (can be `None` in tests that don't need commands registered).

**New tests needed:**
```python
class TestCommandHandlerRegistration:
    def test_builtin_commands_registered_with_handlers(self):
        """When handlers provided, all expected commands are registered."""
        
    def test_commands_not_registered_without_handlers(self):
        """When handler=None, that handler's commands are not registered."""
        
    def test_help_always_registered(self):
        """Help command registered regardless of handlers."""
        
    def test_project_commands_always_registered(self):
        """Project commands (status, agents, cost) always registered — ProjectHandler is required."""
```

**Estimated:** Update ~5 existing test constructors (add `None` for new params), add 4 new tests (~60 lines).

### 8.4 `tests/test_agent_builder_handler.py` — ADD tests for `delete_agent_with_confirmation()`

**New tests needed:**
```python
class TestDeleteAgentWithConfirmation:
    def test_calls_delete_on_yes(self):
        """Simulate YES response → delete() called."""
        
    def test_does_not_call_delete_on_no(self):
        """Simulate NO response → delete() not called."""
        
    def test_delete_failure_logs_warning(self):
        """delete() returns False → warning logged."""
        
    def test_dialog_is_modal_with_correct_text(self):
        """Dialog has correct title and secondary text."""
```

**Estimated:** 4 new tests, ~80 lines. Note: GTK dialog testing requires `Gtk.Application` in test fixture or mocking.

---

## 9. ARCHITECTURE.md Updates Required

After implementation, update:

1. **`window.py` entry in §2 directory structure**:
   - Remove: `# window.py — ...`
   - Update to: `# window.py — component assembly and callback wiring only (no business logic)`

2. **`ui/window.py` line count in §12 File Inventory**:
   - From: `# ~1026 lines — MainWindow + all handler wiring + business logic`
   - To: `# ~829 lines — MainWindow + callback wiring only`

3. **Handler descriptions in §3** — add a note to each:
   - `FeedHandler`: "Also owns audit report card creation (`add_audit_report_card()`)"
   - `AgentRuntimeHandler`: "Also owns agent registry + MCP hot-reload (`reload_agents_and_mcp()`)"
   - `CommandHandler`: "Registers all built-in commands automatically at construction time"
   - `AgentBuilderHandler`: "Also owns delete confirmation dialog (`delete_agent_with_confirmation()`)"

---

## 10. Self-Audit

- [x] Every code sample traced against actual source code
- [x] `FeedCardData` constructor verified: accepts `card_type`, `source`, `title`, `body`, `author`, `timestamp`, `project_name`, `file_path`, `metadata` — all present in the spec's code sample
- [x] `reload_registry()` and `get_special_agents()` signatures verified — both take no required args
- [x] `disconnect_all(conversation_key=prefix)` verified — uses `str | None` param, matches `_make_conversation_key(conversation_key, server_name)` which expects `(str | None, str)`
- [x] `connect_servers(server_names, conversation_key)` verified — returns `dict[str, str]`
- [x] `agent_runtime_handler._agents` verified — `dict[str, Any]`, keyed by `conv_id_prefix`
- [x] `agent_builder_handler.delete(name)` verified — returns `bool`
- [x] `CommandHandler.register_command(name, handler, *, aliases, help_text)` verified — all kwargs
- [x] All 16 command handler methods (`cmd_ask`, `cmd_delegate`, etc.) verified to exist on their respective handlers
- [x] `Gtk.MessageDialog` constructor args verified against actual GTK4 API
- [x] `parent_window=self` type-compatible: `MainWindow(Gtk.ApplicationWindow(Gtk.Window))`
- [x] Exception types enumerated: `RuntimeError` (MCP thread shutting down), `FileNotFoundError` (server not found), `MCPConfigError` (disabled server), `TimeoutError` (loop not ready), generic `Exception` (YAML parse, I/O)
- [x] `Command` import in window.py — verified: imported at line 48 but never used as type/value (only CommandHandler/AgentCommandHandler are referenced). Safe to remove during Step 5.
- [x] Implementation order respects dependency chain: handlers first, window.py last
- [x] Files NOT changed listed: `models/`, `utils/`, `agent/`, `ui/views/`, test fixtures
