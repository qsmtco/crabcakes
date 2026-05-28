# SPEC: MCP Server Hot-Reload in Edit Agent Dialog

**Date:** 2026-05-27
**Author:** Qaster
**Status:** Draft — for implementation
**Repository:** github.com/qsmtco/crabcakes
**Implements:** `docs/proposals/PROPOSAL-mcp-agent-tools-hot-reload.md`
**Depends on:** `SPEC-MCP-client-integration.md` (already shipped)
**Target branch:** main

> **⚠️ Architecture Compliance:**
> This spec adheres strictly to ARCHITECTURE.md. All code follows documented patterns, layer separation, naming conventions, and handler pattern (§8.6). No deviations without spec revision.

---

## 1. Overview

### 1.1 Problem

Adding or removing an MCP server from a special agent's config currently requires:
1. Quit CrabCakes
2. Manually edit `~/.config/crabcakes/agents/{agent}.yaml`
3. Restart the app

This breaks the flow and makes MCP integration feel fragile.

### 1.2 Solution

Add an **MCP Servers section** to the Edit Agent dialog (`ui/views/agent_builder.py`). When the user saves the agent, the runtime hot-reloads the MCP config — no restart needed.

### 1.3 Scope

| In scope | Out of scope |
|----------|-------------|
| MCP server checkbox list in agent builder | Adding new MCP servers via inline form |
| Persisting `mcp_servers` in agent YAML | Streamable HTTP transport |
| Hot-reconnect on agent save | Per-project MCP servers |
| Disconnecting removed servers on save | Dynamic tool discovery (notifications/tools/list_changed) |
| Connection status badges in dialog | MCP server marketplace |

### 1.4 Key Architecture Principles

- **Layer separation:** `utils/mcp_config.py` and `utils/mcp_client.py` are pure Python — no GTK
- **Handler pattern:** All UI logic in handlers/views, not `window.py`
- **Callback wiring:** `window.py` connects handlers; handlers never import each other
- **Thread safety:** All GTK calls from MCP client bridged through `GLib.idle_add()`

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py` — MCP Servers Section (~80 lines)

**What:** Add `_build_mcp_section()` between Tools and the bottom of the form.

**Layout:**
```
┌─ MCP Servers ─────────────────────────────────────┐
│  ☑ memory   Knowledge graph memory server          │
│  ☐ fetch    Web content fetching and conversion    │
│  ☐ github   GitHub API — issues, PRs, repos        │
└────────────────────────────────────────────────────┘
```

**Implementation:**

1. Add instance variable `self._mcp_checks: dict[str, Gtk.CheckButton] = {}` in `__init__`

2. Add method `_build_mcp_section() -> Gtk.Box`:
   - Calls `utils/mcp_config.load_mcp_servers()` to get available servers
   - Creates a section label "MCP Servers"
   - Creates a `Gtk.ListBox` with one `Gtk.CheckButton` per enabled server
   - Each row shows: checkbox + server name + description (from config)
   - Stores each check button in `self._mcp_checks[server_name]`
   - If no servers configured, shows a dim label: "No MCP servers configured. Add servers to ~/.config/crabcakes/mcp-servers.json"
   - Returns the section box

3. Insert `self._add_labeled(form_box, "MCP Servers", mcp_section)` after the tools section and before the error label

4. Add `_get_selected_mcp_servers() -> list[str]`:
   ```python
   def _get_selected_mcp_servers(self) -> list[str]:
       return [name for name, check in self._mcp_checks.items() if check.get_active()]
   ```

5. Update `get_values()` to include `mcp_servers`:
   ```python
   def get_values(self) -> dict:
       # ... existing fields ...
       tools = self._get_selected_tools()
       return {
           "name": name,
           "emoji": emoji,
           "role": role,
           "prompts": prompts,
           "tools": tools,
           "provider": provider,
           "model": model,
           "mcp_servers": self._get_selected_mcp_servers(),
           "self_improvement": self._get_si_config(tools),
       }
   ```

6. Update `_fill_form()` to pre-check MCP servers when editing:
   ```python
   # In _fill_form(), after the tools check block:
   selected_mcp = set(agent_def.get("mcp_servers", []))
   for name, check in self._mcp_checks.items():
       check.set_active(name in selected_mcp)
   ```

**Import required:**
```python
from utils.mcp_config import load_mcp_servers
```

**CSS classes:**
- `"agent-builder-mcp-list"` on the `Gtk.ListBox`
- `"agent-builder-mcp-check"` on each `Gtk.CheckButton`

### 2.2 `ui/styles.py` — MCP Section CSS (~10 lines)

**What:** Add CSS rules for the MCP server list.

**Add to `APP_CSS`:**
```css
/* Agent Builder — MCP server list */
.agent-builder-mcp-list {
    background: @CLR_PANEL;
    border-radius: 6px;
}
.agent-builder-mcp-check {
    padding: 6px 8px;
}
```

**Location:** Add in the existing agent builder CSS block (after `.agent-builder-tool-list` rules).

### 2.3 `ui/window.py` — Hot-Reconnect on Save (~10 lines)

**What:** In `_on_agent_saved()`, disconnect stale MCP connections and reconnect for updated agent defs.

**Current code** (lines ~782–794):
```python
def _on_agent_saved(self, name: str) -> None:
    from agent.special_agents import reload_registry, get_special_agents
    reload_registry()
    self._agent_runtime_handler._agents.clear()
    for agent_def in get_special_agents():
        self._agent_runtime_handler.add_special_agent(agent_def)
    self._left_panel.set_special_agents(self._agent_runtime_handler)
    logger.info("Agent saved and UI refreshed: %s", name)
```

**Updated code:**
```python
def _on_agent_saved(self, name: str) -> None:
    from agent.special_agents import reload_registry, get_special_agents
    from utils.mcp_client import disconnect_all as mcp_disconnect_all, connect_servers

    reload_registry()

    # Disconnect stale MCP connections before re-registering
    mcp_disconnect_all()

    self._agent_runtime_handler._agents.clear()
    for agent_def in get_special_agents():
        self._agent_runtime_handler.add_special_agent(agent_def)

        # Hot-reload MCP connections for each agent's active conversations
        if agent_def.mcp_servers:
            # Reconnect for the agent's conversation prefix
            # The next message will trigger full connect if needed
            connect_servers(agent_def.mcp_servers, agent_def.conv_id_prefix)

    self._left_panel.set_special_agents(self._agent_runtime_handler)
    logger.info("Agent saved, UI refreshed, MCP reconnected: %s", name)
```

**Why `disconnect_all()` then `connect_servers()`:** This ensures servers removed from an agent's config are cleaned up. `disconnect_all()` kills all MCP subprocesses; `connect_servers()` re-establishes only what's needed. The tool cache is invalidated on new connect (existing behavior in `mcp_client.py`).

**Same pattern applies to `_on_agent_deleted()`:**
```python
def _on_agent_deleted(self, name: str) -> None:
    from agent.special_agents import reload_registry, get_special_agents
    from utils.mcp_client import disconnect_all as mcp_disconnect_all, connect_servers

    reload_registry()

    mcp_disconnect_all()

    self._agent_runtime_handler._agents.clear()
    for agent_def in get_special_agents():
        self._agent_runtime_handler.add_special_agent(agent_def)
        if agent_def.mcp_servers:
            connect_servers(agent_def.mcp_servers, agent_def.conv_id_prefix)

    self._left_panel.set_special_agents(self._agent_runtime_handler)
    logger.info("Agent deleted, UI refreshed, MCP reconnected: %s", name)
```

### 2.4 `agent/special_agents.py` — Already Handles `mcp_servers`

**No changes needed.** The `SpecialAgentDef` dataclass already has `mcp_servers: list[str]` (line 41), and `_load_registry()` already coerces and validates the field (lines 101–106).

### 2.5 `utils/agent_defs.py` — Already Validates `mcp_servers`

**No changes needed.** `validate_agent_def()` already checks `mcp_servers` is a list of strings without `/` or whitespace (lines 404–413).

### 2.6 `utils/mcp_config.py` — Already Loads Server Config

**No changes needed.** `load_mcp_servers()` returns `dict[str, MCPServerConfig]` which provides name, description, and enabled status. `get_server_config(server_name)` returns a single config.

### 2.7 `utils/mcp_client.py` — Already Has `connect_servers()`

**No changes needed.** `connect_servers(server_names, conversation_key)` connects to multiple servers and returns a `name→error` dict. `disconnect_all()` cleans up all connections.

### 2.8 `agent/runtime.py` — Already Wires MCP

**No changes needed.** `create_conversation()` already accepts `mcp_servers` and passes it through to tool merging.

### 2.9 `ui/handlers/agent_runtime_handler.py` — Already Passes `mcp_servers`

**No changes needed.** Line 342 passes `mcp_servers=agent_def.mcp_servers` to `create_conversation()`.

---

## 3. Data Flow

### 3.1 Opening the Edit Agent Dialog

```
User right-clicks agent → Edit Agent
    → AgentBuilderDialog(parent, handler=handler, agent_def=agent_def)
        → _build_mcp_section()
            → load_mcp_servers() → gets all servers from mcp-servers.json
            → creates checkboxes for each enabled server
        → _fill_form(agent_def)
            → reads agent_def["mcp_servers"]
            → pre-checks matching servers
```

### 3.2 Saving the Agent

```
User clicks Save in agent builder
    → AgentBuilderDialog._do_save()
        → get_values() → includes mcp_servers list
        → on_save callback → AgentBuilderHandler.save()
            → save_agent_def() → writes YAML with mcp_servers field
        → on_agent_saved callback → window._on_agent_saved(name)
            → reload_registry() → re-reads YAML files
            → mcp_disconnect_all() → kill stale subprocesses
            → for each agent_def: add_special_agent() + connect_servers()
            → left_panel refresh
```

### 3.3 Agent Sends Message After Hot-Reload

```
User sends message to Coder
    → AgentRuntimeHandler.send_to_special_agent()
        → create_conversation(mcp_servers=agent_def.mcp_servers)
            → If MCP already connected (from hot-reload): reuses connection
            → If not: connect_servers() on-demand (existing fallback behavior)
        → get_tool_definitions_for_api()
            → Built-in tools + MCP discovered tools → unified list
        → LLM sees: [read_file, write_file, ..., memory/search_nodes, memory/read_graph]
```

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|------------|-------|------|
| `ui/views/agent_builder.py` | New section + methods | ~80 | Low — follows existing patterns |
| `ui/styles.py` | New CSS rules | ~10 | Minimal — cosmetic only |
| `ui/window.py` | Update 2 methods | ~20 | Medium — touches lifecycle |

**Total:** ~110 lines across 3 files. No new files. No new dependencies.

**Files NOT changed** (already correct):
- `agent/special_agents.py` — already handles `mcp_servers`
- `utils/agent_defs.py` — already validates `mcp_servers`
- `utils/mcp_config.py` — already loads server configs
- `utils/mcp_client.py` — already has `connect_servers()` and `disconnect_all()`
- `agent/runtime.py` — already wires MCP into conversations
- `ui/handlers/agent_runtime_handler.py` — already passes `mcp_servers`

---

## 5. Implementation Order

### Step 1: Add MCP section to `ui/views/agent_builder.py`

1. Add `self._mcp_checks = {}` in `__init__`
2. Implement `_build_mcp_section()`
3. Insert after tools section in form layout
4. Add `_get_selected_mcp_servers()`
5. Update `get_values()` to include `mcp_servers`
6. Update `_fill_form()` to pre-check MCP servers

### Step 2: Add CSS to `ui/styles.py`

Add `.agent-builder-mcp-list` and `.agent-builder-mcp-check` rules.

### Step 3: Wire hot-reconnect in `ui/window.py`

Update `_on_agent_saved()` and `_on_agent_deleted()` to call `mcp_disconnect_all()` then `connect_servers()` for each agent.

### Step 4: Test end-to-end

1. Open CrabCakes
2. Edit Coder agent → see memory server checkbox (pre-checked)
3. Uncheck memory → Save
4. Send message to Coder → verify no MCP tools in tool list
5. Edit Coder agent → check memory → Save
6. Send message to Coder → verify MCP tools restored
7. Verify no app restart needed at any point

---

## 6. Acceptance Criteria

- [ ] Edit Agent dialog shows MCP Servers section with checkboxes for all enabled servers in `mcp-servers.json`
- [ ] Pre-existing `mcp_servers` in agent YAML are pre-checked when editing
- [ ] Saving the agent persists `mcp_servers` to the YAML file
- [ ] No app restart needed — saving immediately reconnects MCP servers
- [ ] Removing a server from an agent disconnects it on save
- [ ] Adding a server to an agent connects it on save
- [ ] Other agents' MCP connections are not disrupted (disconnect_all + reconnect all)
- [ ] No MCP servers configured → shows "No MCP servers configured" message
- [ ] CSS matches existing agent builder styling

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| No `mcp-servers.json` file | `load_mcp_servers()` raises `FileNotFoundError` — catch and show "No MCP servers configured" |
| Server in YAML but not in `mcp-servers.json` | Not shown in checkbox list; silently ignored on save |
| Server fails to connect on hot-reload | `connect_servers()` returns error dict — log warning, don't crash |
| Agent has no `mcp_servers` key in YAML | Defaults to empty list — no checkboxes pre-checked |
| `mcp-servers.json` has no servers | Empty section with "No MCP servers configured" message |
| Multiple agents share the same server | Each gets its own connection (keyed by conversation_key + server_name) |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update:

1. **Section 3.21s** (`ui/views/agent_builder.py`) — document MCP section methods in Public API
2. **Section 12** (File Inventory) — update line counts for `agent_builder.py` and `window.py`
3. **Section 4.12** (MCP Tool Execution Flow) — add hot-reload step after agent save

---

*End of spec.*
