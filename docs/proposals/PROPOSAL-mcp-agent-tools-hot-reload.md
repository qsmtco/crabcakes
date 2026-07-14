# PROPOSAL: Hot-Reload MCP Server Config in Edit Agent Dialog

**Status:** ⚠️ PARTIALLY DONE — MCP Servers section in Edit Agent dialog shipped (`ui/views/agent_builder.py:534` `_build_mcp_section()`). Hot-reload on next message partially confirmed — MCP client supports runtime connect/disconnect via `utils/mcp_client.py` and `agent/runtime.py:955-959` cleanup. Full end-to-end hot-reload verification not confirmed. 
> **status:** `PARTIAL` — sortable tag for `ls | grep STATUS` The **MCP Servers section** in the Edit Agent dialog is shipped. See `ui/views/agent_builder.py:123-124` (`mcp_section = self._build_mcp_section()`) and `agent_builder.py:534` (`def _build_mcp_section(self)`). The visual UI is in place. However, the **hot-reload on next message** (no restart needed) part is **not verified** — the proposal's "no restart" claim requires confirming that MCP server changes take effect on the next agent invocation without a restart. The MCP client (`utils/mcp_client.py`) supports runtime connect/disconnect (per `agent/runtime.py:955-959` "BUG #22: Clean up existing MCP connections before replacing conversation"), which suggests hot-reload is at least partially in place. **Marked PARTIAL pending confirmation that the "no restart" claim holds end-to-end.**

---

## Implementation

### 1. UI — Add MCP Servers Section to AgentBuilderDialog

**File:** `ui/views/agent_builder.py`

**Location in form:** Between the Provider section and the Self-Improvement section.

**New method:** `_build_mcp_section()` — renders available MCP servers as checkbox list + "Add Server" button.

```
┌─ MCP Servers ────────────────────────────────────────┐
│  [+ Add Server]                                       │
│  ┌─ Installed ────────────────────────────────────┐   │
│  │  ☑ memory   (Knowledge graph — connected)       │   │
│  │  ☐ filesystem (Local file access)               │   │
│  │  ☐ github   (GitHub API — not configured)       │   │
│  └────────────────────────────────────────────────┘   │
│  ┌─ Custom server ──────────────────────────────┐    │
│  │ Label: [_______________]                       │    │
│  │ Command: [_______________]                    │    │
│  │ Args: [____________________]                  │    │
│  │                [+ Add] [Cancel]               │    │
│  └────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
```

**Data flow:**
- `get_mcp_servers()` from `utils/mcp_config.py` → list of available servers
- Checked = `mcp_servers: [server_name]` in the agent YAML
- Unchecked = omitted from `mcp_servers` list
- `_collect_values()` includes `mcp_servers` in the form dict

### 2. Handler — Persist MCP config changes

**File:** `ui/handlers/agent_builder_handler.py`

Add `get_mcp_server_configs()` and `save_mcp_server_config()` to support adding custom servers.

Or simpler: delegate to `utils/mcp_config.py` which already has `load_mcp_servers()` and `save_mcp_servers()`.

### 3. Runtime — Hot-Reconnect on Agent Save

**File:** `ui/window.py` — `_on_agent_saved()`

After `reload_registry()` and `add_special_agent()` calls, add MCP hot-reload:

```python
def _on_agent_saved(self, name: str) -> None:
    from agent.special_agents import reload_registry, get_special_agent
    from utils.mcp_client import connect_servers_for_agent

    reload_registry()

    # Re-register all agents
    self._agent_runtime_handler._agents.clear()
    for agent_def in get_special_agents():
        self._agent_runtime_handler.add_special_agent(agent_def)
        # Hot-reload MCP connections
        connect_servers_for_agent(
            session_key=agent_def.conv_id_prefix,
            mcp_servers=agent_def.mcp_servers,
        )

    self._left_panel.set_special_agents(self._agent_runtime_handler)
```

**New function in `utils/mcp_client.py`:**
```python
def connect_servers_for_agent(session_key: str, mcp_servers: list[str]) -> None:
    """Connect each named MCP server for a given session key.
    Disconnects any servers no longer in the list."""
    for server in mcp_servers:
        if not is_connected(session_key, server):
            connect(server, session_key)
```

### 4. Add MCP Servers Section to the Form

**File:** `ui/views/agent_builder.py`

In `__init__`, call `_build_mcp_section()` and add it to the form. In `_collect_values()`, include `mcp_servers` field.

In `_populate_from_agent_def()` (existing method), pre-check the servers that are already configured.

---

## What Already Works (No Code Needed)

- `window.py:_on_agent_saved()` already calls `reload_registry()` — agent YAML changes are picked up without restart
- `AgentBuilderDialog` already has checkbox patterns (`_build_tools_section()`) that can be cloned for MCP servers
- `utils/mcp_config.py` already has `load_mcp_servers()`, `save_mcp_servers()`

## What Needs to Be Built

| Component | File | Effort |
|-----------|------|--------|
| MCP section UI | `ui/views/agent_builder.py` | ~100 lines |
| MCP config in form dict | `ui/views/agent_builder.py` | ~15 lines |
| Populate existing servers | `ui/views/agent_builder.py` | ~15 lines |
| `connect_servers_for_agent()` | `utils/mcp_client.py` | ~20 lines |
| Wire hot-reconnect | `ui/window.py` | ~10 lines |

**Total:** ~160 lines across 4 files.

---

## UX Details

- **"Add Server" button** opens a small form inline: label + command + args. Saves to `~/.config/crabcakes/mcp-servers.json`.
- **"Not configured" state** — servers in `mcp-servers.json` that have no working command show `(not found)` badge.
- **"Connected" badge** — memory server shows green `(connected)` if the subprocess is running.
- **No save button** — changes take effect on dialog Save (the same Save that already triggers hot-reload).

---

## Status

- [x] Investigation complete
- [ ] UI mockup / approval
- [ ] Build `_build_mcp_section()`
- [ ] Wire `connect_servers_for_agent()`
- [ ] Test end-to-end (Edit Coder → add memory → send message → verify MCP tools)
- [ ] Push to GitHub