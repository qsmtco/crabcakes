# SPEC: MCP Client Integration — Phase 1 (stdio transport)

**Date:** 2026-05-24
**Author:** QTR (based on PROPOSAL-mcp-client-integration.md by Qaster)
**Status:** Draft — for implementation
**Repository:** github.com/qsmtco/crabcakes
**Dependencies:** `mcp` Python package, `npx` or `uvx` (system binaries)
**Implements:** `docs/proposals/PROPOSAL-mcp-client-integration.md`
**Target branch:** main

> **⚠️ Architecture Compliance:**
> This spec adheres strictly to ARCHITECTURE.md patterns. Read ARCHITECTURE.md section 0.1 — "this document is the law." All code MUST follow the documented patterns, layers, and naming conventions. Deviation requires spec revision.

---

## 1. Overview

### 1.1 Purpose

Enable CrabCakes agents to connect to external MCP (Model Context Protocol) servers and use their tools alongside built-in tools. MCP is the industry standard adopted by Anthropic, OpenAI, Google, and Microsoft. Thousands of MCP servers exist — each is a potential tool library.

### 1.2 Scope

| Phase | Deliverable |
|-------|-------------|
| **Phase 1** | MCP client library (`utils/mcp_client.py`) + config loader (`utils/mcp_config.py`) + agent runtime integration (stdio only) |
| **Phase 2** | Runtime integration (tool merging, routing) — integrated in Phase 1 |
| **Phase 3** | UI integration (Edit Agent dialog MCP server selection) — deferred to future spec |
| **Phase 4** | Documentation, ARCHITECTURE.md updates |

**Transport:** stdio only for v1. 95% of MCP servers support stdio. It runs locally as subprocesses with zero network exposure. Streamable HTTP is deferred to v2.

### 1.3 Key Architecture Principles (per ARCHITECTURE.md §3)

- **Layer separation:** `utils/` is pure Python, no GTK, no network at import time
- **First-class tools:** MCP tools are identical to built-in tools from the LLM's perspective — unified tool list
- **Tool routing:** Transparent routing in runtime — `tool_name` contains `/` → MCP, otherwise → built-in
- **Thread safety:** All GTK callbacks via `GLib.idle_add()` / `_dispatch()`

---

## 2. Architecture

### 2.1 Data Flow (per ARCHITECTURE.md §4.15 flow patterns)

```
┌─────────────────────────────────────────────────────────────┐
│ Agent Runtime (agent/runtime.py)                            │
│                                                             │
│  Agent YAML: tools: [read_file, github:create_issue, ...]  │
│                                                             │
│  ┌─────────────────────┐  ┌────────────────────────────┐    │
│  │ Built-in Tools      │  │ MCP Client                 │    │
│  │ (agent/tools.py)   │  │ (utils/mcp_client.py)      │    │
│  │                    │  │                             │    │
│  │ read_file          │  │  ┌────────┐  ┌────────┐    │    │
│  │ write_file         │  │  │ GitHub │  │ Fetch  │    │    │
│  │ exec_command      │  │  │Server │  │Server │    │    │
│  │ ...               │  │  │(stdio)│  │(stdio)│    │    │
│  └─────────────────────┘  └────────────────────────────┘    │
│              │                         │                      │
│              └──────────┬─────────────┘                      │
│                          ▼                                   │
│              Unified Tool List → LLM API                    │
│                          │                                   │
│                          ▼                                   │
│              Tool Call Response                            │
│                          │                                   │
│                 ┌─────────┴─────────┐                       │
│                 ▼                  ▼                        │
│            Built-in?           MCP tool?                     │
│            → execute_tool()     → mcp_client.call_tool()       │
│                                   │                         │
│                                   ▼                         │
│                            MCP Server (stdio)                │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Module Responsibilities

**This section intentionally left blank — moved to §2.3 Async Bridge Design**

### 2.3 Async Bridge Design

> **Critical: The MCP Python SDK is entirely async.**
> This section addresses how async MCP calls integrate with CrabCakes' synchronous runtime.

#### 2.3.1 The Problem

The MCP SDK uses `asyncio` and `anyio`:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def use_mcp():
    params = StdioServerParameters(command="npx", args=["-y", "@mcp/server-github"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("tool_name", {"arg": "value"})
```

But CrabCakes' agent runtime runs in a **worker thread** (`threading.Thread`, see `agent/runtime.py` line ~883 `send_message` → `threading.Thread`). The tool loop is synchronous — calling the LLM, executing tools, returning results all block in that thread.


#### 2.3.2 Solution: Dedicated Async Event Loop Thread

`utils/mcp_client.py` manages a **dedicated asyncio event loop in a background thread** that exposes synchronous wrappers to the agent runtime.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│ Agent Runtime (synchronous worker thread)              │
│                                                      │
│  execute_tool() → mcp_client.call_tool() [SYNC]      │
│                              ↓                       │
│              ┌─────────────────┴─────────┐           │
│              ▼                           ▼               │
│     Built-in tool?              MCP tool?              │
│     → agent/tools.py         → mcp_client.call_tool() │
│                                   ↓                 │
│                          [sync wrapper]               │
│                                   ↓                 │
│              ┌─────────────────────────────────────────┐     │
│              ▼ async event loop in Background Thread │     │
│              (asyncio.run() with queue-based API)    │
│              │                                       │     │
│              │ stdin/stdout ← subprocess (stdio)     │     │
│              │ MCP server process                    │     │
│              └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

**Implementation pattern:**

```python
# utils/mcp_client.py (excerpt showing async bridge)


import asyncio
import threading
from queue import Queue
from typing import Any, Callable

# Background thread that runs the asyncio event loop
_background_thread: threading.Thread | None = None
_event_loop: asyncio.AbstractEventLoop | None = None
_request_queue: Queue[tuple[Callable, Any, Any]] = Queue()
_result_queue: Queue[Any] = Queue()


def _run_async_loop():
    """Background thread: runs the asyncio event loop forever."""
    global _event_loop
    _event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_event_loop)
    _event_loop.run_forever()


def _ensure_async_loop_started():
    """Start the background async thread if not already running."""
    global _background_thread
    if _background_thread is None or not _background_thread.is_alive():
        _background_thread = threading.Thread(target=_run_async_loop, daemon=True)
        _background_thread.start()


def _submit_async(coro: Callable, *args) -> Any:
    """Submit an async coroutine to the background thread and wait for result.
    
    Uses futures to bridge between threads.
    """
    _ensure_async_loop_started()
    
    async def run_and_return():
        result = await coro(*args)
        return result
    
    # Schedule on the background event loop
    import concurrent.futures
    
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, run_and_return())
        return future.result(timeout=30)  # 30s timeout
```

**Simplified alternative — `asyncio.run()` per call:**

For lower complexity, we can use `asyncio.run()` to create and run a fresh event loop **per call**. This is less efficient (creates event loop each time) but much simpler and sufficient for our use case:

```python
# Simpler pattern — create fresh event loop per call
import asyncio

def call_tool_sync(server_name: str, tool_name: str, arguments: dict) -> MCPToolResult:
    """Synchronous wrapper around async MCP tool call."""
    async def _call():
        # Get or create connection for this server
        # ... (see §2.3.3)
        session = _get_or_create_session(server_name)
        result = await session.call_tool(tool_name, arguments)
        return _convert_result(result)
    
    # Each call gets its own fresh event loop
    return asyncio.run(_call())
```

This simpler pattern is **recommended for v1**. It avoids thread management complexity and is sufficient for the MCP use case (subprocess communication is fast, not I/O bound).

#### 2.3.3 Connection Lifecycle (Revised)


**Per-conversation connections (recommended):**

- **Connect:** When `send_message()` is called with an MCP-configured agent, `connect()` is called for each server in `mcp_servers` before the tool loop runs
- **Disconnect:** After the LLM returns (tool calls exhausted), `disconnect_all()` is called before returning
- **Persist across calls within same conversation:** Connections can reuse within same conversation (between tool calls), but closed at end

**Runtime integration points:**
```python
# agent/runtime.py — modified send_message (around line ~840)

def send_message(self, session_key, text):
    # ... existing initialization ...
    
    # NEW: Connect MCP servers for this conversation
    if conv.mcp_servers:
        from utils.mcp_client import connect_servers
        connect_servers(conv.mcp_servers)  # Connect all, failures non-fatal
    
    try:
        # ... existing tool loop ...
        pass
    finally:
        # NEW: Disconnect MCP servers
        if conv.mcp_servers:
            from utils.mcp_client import disconnect_all
            disconnect_all()
```

**Graceful degradation:** If MCP connection fails (server not found, can't start), log warning and continue **without MCP tools**. Agent still functions with built-in tools only.


#### 2.3.4 Tool Discovery Logic (Where it belongs)


`get_mcp_tools_for_api()` belongs in `utils/mcp_client.py`, not `agent/tools.py`. The function:

1. **Ensures servers are connected** — calls `connect()` if not already
2. **Discovers tools** — calls `discover_tools()` for each server
3. **Converts to OpenAI format** — transforms `MCPToolDefinition` → function-calling dict

```python
# utils/mcp_client.py — added function

def get_tools_for_api(server_names: list[str]) -> list[dict]:
    """Get MCP tool definitions in OpenAI function-calling format.
    
    Used by agent runtime to merge with built-in tools.
    
    Args:
        server_names: List of server names configured for this agent
        
    Returns:
        List of tool definitions in OpenAI function-calling format.
    """
    tools = []
    for server_name in server_names:
        # Ensure connected (connect if not)
        if server_name not in get_connected_servers():
            config = get_server_config(server_name)
            if config:
                connect(server_name, config)
        
        # Discover tools
        server_tools = discover_tools(server_name)
        
        # Convert to namespaced OpenAI format
        for tool in server_tools:
            namespaced_name = f"{server_name}/{tool.name}"
            tools.append({
                "type": "function",
                "function": {
                    "name": namespaced_name,
                    "description": tool.description,  # NOTE: Untrusted per spec
                    "parameters": tool.parameters,
                },
            })
    
    return tools
```

#### 2.3.5 `MCPServerConfig` Construction

The spec references `StdioServerParameters` but doesn't show construction. Here's how:

```python
# utils/mcp_config.py — method extension

from mcp import StdioServerParameters

def MCPServerConfig.to_stdio_params(self) -> StdioServerParameters:
    """Convert to MCP SDK StdioServerParameters.

    Handles env var substitution: ${VAR} → os.environ[VAR]
    """
    # Substitute environment variables
    env = {}
    if self.env:
        for k, v in self.env.items():
            if v.startswith("${") and v.endswith("}"):
                var = v[2:-1]
                env[k] = os.environ.get(var, "")
            else:
                env[k] = v
    
    return StdioServerParameters(
        command=self.command,
        args=self.args,
        env=env if env else None,
    )
```

---

## 3. Configuration

#### A. `utils/mcp_config.py` — MCP Server Registry Loader

**FILE:** `~/.config/crabcakes/mcp-servers.json` (global config, per ARCHITECTURE.md §10 path resolution via `utils/config.py`)

**Responsibility:** Load and validate MCP server configurations from JSON. Support `${ENV_VAR}` substitution for secrets.

**Public API:**

```python
def load_mcp_servers() -> dict[str, MCPServerConfig]:
    """Load all MCP server configs from ~/.config/crabcakes/mcp-servers.json.
    
    Returns:
        Dict mapping server name → MCPServerConfig.
        
    Raises:
        FileNotFoundError: Config file doesn't exist.
        ValidationError: Config is invalid JSON or missing required fields.
    """

@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str                    # Server name (e.g., "github")
    transport: str               # "stdio" or "streamable-http"
    command: str                # Command to run (e.g., "npx", "uvx")
    args: list[str]             # Arguments (e.g., ["-y", "@modelcontextprotocol/server-github"])
    env: dict[str, str] | None = None  # Environment variables (optional)
    description: str = ""      # Human-readable description
    enabled: bool = True        # Whether server is active
    
    def to_stdio_params(self) -> StdioServerParameters:
        """Convert to MCP SDK StdioServerParameters for stdio transport."""
```

#### B. `utils/mcp_client.py` — MCP Client Library

**Responsibility:** Connect to MCP servers via stdio, discover tools, call tools, manage lifecycle.

**Public API:**

```python
from dataclasses import dataclass

@dataclass
class MCPToolDefinition:
    """Definition of an MCP tool (mirrors agent/tools.py ToolDefinition)."""
    name: str                  # Namespaced name: "server_name/tool_name"
    description: str            # From MCP server
    parameters: dict            # JSON Schema for LLM function-calling
    server_name: str           # Original server (e.g., "github")

@dataclass  
class MCPToolResult:
    """Result of executing an MCP tool."""
    success: bool
    output: str = ""
    error: str | None = None
    duration_ms: int = 0

def connect(server_name: str, config: MCPServerConfig) -> None:
    """Connect to an MCP server via stdio.
    
    Launches subprocess, performs MCP handshake (initialize).
    
    Raises:
        ConnectionError: Server failed to start or reject handshake.
        RuntimeError: Already connected to this server.
    """

def disconnect(server_name: str) -> None:
    """Disconnect from an MCP server.
    
    Terminates subprocess gracefully (sends JSON-RPC terminate).
    No-op if not connected.
    """

def disconnect_all() -> None:
    """Disconnect from all connected MCP servers.
    
    Called on agent shutdown.
    """

def discover_tools(server_name: str) -> list[MCPToolDefinition]:
    """Discover tools available from a connected MCP server.
    
    Sends tools/list request, returns tools.
    
    Raises:
        RuntimeError: Server not connected.
    """

def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict,
) -> MCPToolResult:
    """Call an MCP tool.
    
    Args:
        server_name: Server name (e.g., "github")
        tool_name: Tool name WITHOUT server prefix (e.g., "create_issue")
        arguments: Tool arguments dict
        
    Returns:
        MCPToolResult with output or error.
        
    Raises:
        RuntimeError: Server not connected or tool not found.
    """

def get_connected_servers() -> set[str]:
    """Return set of currently connected server names."""
```

#### C. `agent/tools.py` — Modified Tool Execution (EXTENSION, not modification of existing behavior)

**New function:** `is_mcp_tool(tool_name: str) -> bool`

```python
def is_mcp_tool(tool_name: str) -> bool:
    """Check if tool name is an MCP tool (contains '/' separator).
    
    Examples:
        "github/create_issue" → True
        "read_file" → False
    """
    return "/" in tool_name
```

**Modified function:** `execute_tool()` — Add MCP routing:

```python
def execute_tool(name, arguments, project_path, session_key) -> ToolResult:
    """Execute a tool.
    
    MODIFIED: Routes to MCP client if name contains '/'.
    """
    if "/" in name:
        # Route to MCP client
        server_name, _, tool_name = name.partition("/")
        from utils.mcp_client import call_tool
        mcp_result = call_tool(server_name, tool_name, arguments)
        # Convert MCPToolResult to ToolResult
        return ToolResult(
            success=mcp_result.success,
            output=mcp_result.output,
            error=mcp_result.error,
            duration_ms=mcp_result.duration_ms,
        )
    # ... existing built-in tool handling unchanged ...
```

**New function:** `get_mcp_tools_for_api(server_names: list[str]) -> list[dict]`

```python
def get_mcp_tools_for_api(server_names: list[str]) -> list[dict]:
    """Get MCP tool definitions for specified servers.
    
    Used by AgentRuntime to build unified tool list.
    
    Args:
        server_names: List of server names from agent YAML mcp_servers field
        
    Returns:
        List of tool definitions in OpenAI function-calling format.
    """
```

#### D. `agent/runtime.py` — Modified Tool Loop

**Section reference:** ARCHITECTURE.md §3.20 AgentRuntime API

**Modified section (around line 957-960):** Merge built-in + MCP tools:

```python
# Get tools for this agent (filtered by allowed_tools if set)
from agent.tools import get_tool_definitions_for_api

# MODIFIED: Also get MCP tools if mcp_servers is configured
mcp_tools = []
if conv.mcp_servers:
    from agent.tools import get_mcp_tools_for_api
    mcp_tools = get_mcp_tools_for_api(conv.mcp_servers)

tools = get_tool_definitions_for_api(conv.allowed_tools)
tools.extend(mcp_tools)  # Unified tool list
```

**NEW field** in `models/conversation.py` Conversation dataclass (line ~91, add after `step_count`):

```python
@dataclass
class Conversation:
    # ... existing fields ...
    step_count: int = 0
    mcp_servers: list[str] = field(default_factory=list)  # NEW: MCP servers
```

**Load flow:**
1. `agent_defs.py` parses agent YAML → extracts `mcp_servers` list
2. Passes to `runtime.create_conversation()` → stored in Conversation.mcp_servers
3. Tool loop accesses via `conv.mcp_servers`

#### E. `agent/config.py` — Where YAML `mcp_servers` field is loaded

**File:** `~/.config/crabcakes/agents/coder.yaml` (example)
```yaml
name: Coder
# ... existing fields ...
mcp_servers:          # MCP servers for this agent
  - github
  - fetch
  - git
```

**Load chain:**
1. **`agent/config.py`** (existing code) — `load_agent_yaml()` parses YAML
2. Add: Extract `mcp_servers` field during YAML parse
3. Pass to **`agent.runtime.create_conversation()`** as `mcp_servers` parameter
4. Stored in **`Conversation.mcp_servers`** (dataclass field)
5. Tool loop reads via `conv.mcp_servers`

---

## 3. Configuration

### 3.1 Global Server Registry

**File:** `~/.config/crabcakes/mcp-servers.json`

Created by the user (or by setup tooling). Format:

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      },
      "description": "GitHub API — issues, PRs, repositories",
      "enabled": true
    },
    "fetch": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-fetch"],
      "description": "Web content fetching and conversion",
      "enabled": true
    },
    "git": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-git"],
      "description": "Git repository operations",
      "enabled": true
    },
    "memory": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "description": "Persistent knowledge graph memory",
      "enabled": true
    },
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/q/projects"],
      "description": "Secure file operations",
      "enabled": true
    }
  }
}
```

**Design decisions (from proposal):**

1. **Named servers** — Agents reference servers by name, not by command
2. **`${ENV_VAR}` syntax** — Environment variable substitution, keeps tokens out of config
3. **`enabled` flag** — Disable server without deleting config
4. **`transport` field** — Positions for Streamable HTTP v2 (currently always "stdio")
5. **Global, not per-project** — Servers are system-level resources

### 3.2 Per-Agent MCP Server Selection

**File:** `~/.config/crabcakes/agents/coder.yaml` (example)

```yaml
name: Coder
emoji: 🛠️
role: coder
prompts:
  - system/coder.md
tools:
  - read_file
  - write_file
  - edit_file
  - exec_command
  - list_files
  - search_files
  # MCP tools — namespaced as "server_name/tool_name"
  - github/create_issue
  - github/search_repositories
  - github/get_file_contents
  - github/list_commits
  - fetch/fetch
  - git/git_diff
  - git/git_log
provider: minimax
model: MiniMax-M2.7
mcp_servers:          # NEW — which MCP servers to connect to
  - github
  - fetch
  - git
self_improvement:
  bug_journal: true
  project_rules: true
  enforcement: true
  structured_feedback: true
  dream_consolidation: true
```

**Design decisions:**

1. **`mcp_servers`** — List of server names from global registry
2. **`tools` list includes MCP tools** — Namespaced as `server_name/tool_name`
3. **Per-tool selection** — Agent can use subset of server's exposed tools

---

## 4. Files to Create and Modify

### 4.1 New Files

| File | Description |
|------|-------------|
| `utils/mcp_config.py` | MCP server registry loader |
| `utils/mcp_client.py` | MCP stdio client library |
| `tests/test_mcp_config.py` | Tests for config loader |
| `tests/test_mcp_client.py` | Tests for MCP client |
| `tests/__init__.py` (in tests/ if missing) | Test package marker |

### 4.2 Modified Files

| File | Modification |
|------|-------------|
| `agent/tools.py` | Add MCP routing in `execute_tool()`, add `get_mcp_tools_for_api()`, add helper predicates |
| `agent/runtime.py` | Merge tools (built-in + MCP) before LLM call |
| `agent/config.py` | Load `mcp_servers` from YAML, add to AgentConfig dataclass |
| `docs/ARCHITECTURE.md` | Add §3.21n (mcp_config.py), §3.21o (mcp_client.py), update data flow |
| `docs/ARCHITECTURE.md` §11 | Add protocol for MCP initialization and tool calls |

---

## 5. Security Considerations

### 5.1 Per ARCHITECTURE.md Patterns

1. **Approval gate** — MCP tool calls go through `set_approval_callback()` same as exec_command. If tool requires approval (configured per tool), PM must approve before call to MCP server.

2. **Server subprocess isolation** — Each MCP server runs as separate subprocess. Crash isolation: if server crashes, doesn't affect CrabCakes or other servers.

3. **Environment variable substitution** — API tokens go in environment variables, not in config files. `${VAR}` syntax reads at runtime from process environment.

4. **Sandboxing** — Does NOT apply to MCP tools. Built-in tools (read_file, write_file) sandbox to `project_path`. MCP tools are external — their sandboxing is the MCP server's responsibility. Prompt should make this clear.

5. **Tool descriptions are UNTRUSTED** — Per MCP spec, tool descriptions from servers are not trusted. Displayed for selection convenience only.

---

## 6. Testing Strategy

### 6.1 Unit Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_mcp_config.py` | Valid config parsing, missing file, env var substitution, validation |
| `tests/test_mcp_client.py` | connect, disconnect, discover_tools, call_tool, error handling |

### 6.2 Integration Tests

| Test | Description |
|------|-------------|
| Tool discovery | Connect to filesystem MCP server, verify tools discovered |
| Tool execution | Call filesystem read_file, verify file content returned |
| Multiple servers | Connect to multiple servers, verify isolation |
| Disconnect | Connect then disconnect, verify subprocess terminated |
| Tool routing | Route MCP tool through execute_tool(), verify correct server called |

---

## 7. Error Handling

| Error | Handling |
|-------|----------|
| MCP server config file not found | Log warning, return empty dict, continue without MCP |
| MCP server fails to start | Raise ConnectionError with stderr |
| MCP handshake rejected | Raise ConnectionError with rejection reason |
| Server not connected when calling tool | Raise RuntimeError |
| Tool call timeout | Raise MCPToolResult with success=False, error message |
| Server process crash | Detect on next call, attempt reconnect, fail gracefully |

---

## 8. Dependencies

| Dependency | Purpose | Installation |
|-------------|---------|--------------|
| `mcp` | Official MCP Python SDK | Already installed (v1.26.0) — no action needed |
| `npx` | Run npm-packaged MCP servers | Node.js (typically pre-installed) |
| `uvx` | Run Python-packaged MCP servers | `uv` (typically pre-installed) |

> **Note:** The `mcp` package (v1.26.0) is already installed in this environment. Verify with `pip show mcp`.

---

## 9. Future Considerations (Out of Scope for v1)

1. **Streamable HTTP transport** — Add `transport: streamable-http` config option with URL + headers
2. **Per-project MCP servers** — `.crabcakes/mcp-servers.json` in project directory
3. **Dynamic tool discovery** — Listen for `notifications/tools/list_changed`
4. **MCP server marketplace** — Browse and install MCP servers from registry
5. **CrabCakes as MCP server** — Expose built-in tools as MCP server
6. **Resources/Prompts** — Beyond tools, MCP can also expose Resources and Prompts

---

## 10. Implementation Checklist

### PHASE A — MCP Client Library (standalone, no integration)

- [ ] Create `utils/mcp_config.py` — Load and validate MCP server configs
- [ ] Create `utils/mcp_client.py` — stdio client with connect/disconnect/call_tool
- [ ] Create `tests/test_mcp_config.py` — Test config loader
- [ ] Create `tests/test_mcp_client.py` — Test MCP client
- [ ] **Verify:** Script-based test: connect → discover → call → disconnect

**Exit criteria:** Can call `fetch` MCP server and get markdown from a URL.

---

### PHASE B — Runtime Integration

- [ ] Modify `agent/tools.py` — Add MCP routing in execute_tool()
- [ ] Add `get_mcp_tools_for_api()` in utils/mcp_client.py (move from spec)
- [ ] Modify `agent/config.py` — Load and validate mcp_servers YAML field
- [ ] Modify `agent/runtime.py` — Merge built-in + MCP tools before LLM call
- [ ] Add `mcp_servers` field to Conversation dataclass

**Exit criteria:** Agent with MCP servers produces tool list with namespaced MCP tools.

---

### PHASE C — Verification + Cleanup

- [ ] Update `docs/ARCHITECTURE.md` — Add new module documentation, update data flow
- [ ] Integration test — Full flow: agent message → MCP tool call → result
- [ ] Verify no regression: built-in agent tools still work

---

## 11. Effort Estimate (by Phase)

| Phase | Description | Effort |
|-------|-------------|--------|
| **A** | MCP client library (`mcp_config.py`, `mcp_client.py`) + unit tests | ~3 hours |
| **B** | Runtime integration (tools.py, runtime.py, config) | ~2 hours |
| **C** | Documentation + full integration test | ~1 hour |
| **Total** | | **~6 hours** |

**Note:** Phases can be done in separate sessions. Phase A is independently verifiable.

Could be tightened to 2-3 spec files if desired, but the modules are tightly coupled — better as one cohesive implementation.

---

## 12. Open Questions for Architect

1. **MCP SDK versioning** — Which `mcp` package version should we target? Need to pin in requirements.
2. **Connection pooling** — Should MCP connections persist across agent conversations, or reconnect per conversation? Current spec assumes per-conversation (clean init/cleanup).
3. **Tool filtering** — If agent YAML specifies MCP tools list, do we still load all tools from discovered server and filter, or only request server-side filter? Current spec loads all, filters client-side.
4. **Error recovery** — Should we attempt automatic reconnect on failed tool call, or fail immediately? Current spec fails immediately.