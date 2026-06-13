# MCP Client Integration — Proposal

**Date:** 2026-05-21
**Authors:** Qaster (with Captain JAQx)
**Status:** Draft — Awaiting approval

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — The MCP client infrastructure is **partially** built. `utils/mcp_client.py` exists (supports `mcp__connect`, `mcp__disconnect`, `mcp__tools` operations). `agent/runtime.py:955-959` cleans up existing MCP connections before replacing a conversation (BUG #22 fix). `agent/special_agents.py:50` has `mcp_servers: list[str]` field on `SpecialAgentDef`. `ui/views/agent_builder.py:534` has `_build_mcp_section()` for the agent builder UI. However, the **Phase B** features (MCP client library swap, multi-server orchestration, SSE transport, server-initiated notifications) described in this proposal are **not** confirmed as shipped. The MCP client appears to be a basic implementation sufficient for single-server tool calls, but the full Phase B capabilities (especially server-initiated notifications and multi-server orchestration) are not verified. **Marked PARTIAL; basic MCP works, full Phase B not confirmed.**
**Repository:** github.com/qsmtco/crabcakes
**Target:** CrabCakes local agent runtime (Coder, Debugger, user-defined agents)

---

## Problem Statement

CrabCakes agents currently have 8 hardcoded tools in `agent/tools.py`. Adding new capabilities (database access, cloud APIs, git hosting, etc.) requires writing Python code and modifying the source. This doesn't scale.

The **Model Context Protocol (MCP)** is now the industry standard for tool integration, adopted by Anthropic, OpenAI, Google, and Microsoft. There are thousands of MCP servers available — each one is a potential tool library for CrabCakes agents. But CrabCakes can't use any of them.

## Vision

Every CrabCakes agent can connect to external MCP servers and use their tools alongside the built-in tools. The Captain configures which servers each agent can access, and selects which tools (both built-in and MCP) each agent gets. MCP servers appear as another tool source in the Edit Agent dialog — no different from checking "read_file" or "write_file."

---

## Transport Decision: stdio Only (for now)

MCP defines two standard transports: **stdio** and **Streamable HTTP**.

### Why stdio first

| Factor | stdio | Streamable HTTP |
|--------|-------|-----------------|
| Setup | Zero config — just a command to run | Needs URL, auth headers, session management |
| Security | Local only, runs as subprocess | Exposed to network, needs auth |
| Latency | Subprocess stdin/stdout — instant | HTTP round-trip per call |
| Complexity | Trivial — launch process, pipe JSON | HTTP client, SSE parsing, session tokens, reconnect |
| Server availability | 95%+ of MCP servers support stdio | Growing but not universal |
| Multi-client | One client per instance | Multiple clients per server |
| Remote servers | Not supported | Supported |

**Recommendation: Ship stdio in v1. Add Streamable HTTP in v2.**

Rationale:
1. **95% of MCP servers run locally via stdio.** Filesystem, git, database, browser automation — they're all local tools. Streamable HTTP is for enterprise deployments where servers run in the cloud. CrabCakes is a desktop app running on the Captain's machine. stdio is the natural fit.
2. **Implementation simplicity.** stdio is subprocess + stdin/stdout. We can ship it in one spec. Streamable HTTP adds HTTP client code, session management, SSE parsing, auth token handling — easily a second spec's worth of work.
3. **Config format supports both.** The agent YAML config we design now will have a `transport` field. stdio gets `"command"` + `"args"`, Streamable HTTP gets `"url"` + `"headers"`. Adding HTTP later is additive — no redesign needed.
4. **The spec RECOMMENDS clients support stdio.** From the MCP spec: "Clients SHOULD support stdio whenever possible."

### When we'll want Streamable HTTP

- Connecting to shared team MCP servers (e.g., a company's internal tool server)
- Using hosted MCP services (e.g., paid API gateways)
- Remote database access
- Multi-user CrabCakes deployments

That's a v2 problem. stdio covers the v1 use case completely.

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ CrabCakes Agent Runtime (agent/runtime.py)                  │
│                                                             │
│  Agent YAML: tools: [read_file, github:create_issue, ...]   │
│                                                             │
│  ┌─────────────┐  ┌──────────────────────────────────┐     │
│  │ Built-in    │  │ MCP Client                       │     │
│  │ Tools       │  │ (utils/mcp_client.py)             │     │
│  │ (tools.py)  │  │                                  │     │
│  │             │  │  ┌────────┐  ┌────────┐          │     │
│  │ read_file   │  │  │ GitHub │  │ Fetch  │          │     │
│  │ write_file  │  │  │ Server │  │ Server │  ...     │     │
│  │ exec_command│  │  │(stdio) │  │(stdio) │          │     │
│  │ ...         │  │  └────────┘  └────────┘          │     │
│  └─────────────┘  └──────────────────────────────────┘     │
│         │                     │                             │
│         └─────┬───────────────┘                             │
│               ▼                                             │
│         Unified Tool List → LLM API                         │
│               │                                             │
│               ▼                                             │
│         Tool Call Response                                  │
│               │                                             │
│        ┌──────┴──────┐                                      │
│        ▼             ▼                                      │
│   Built-in?      MCP tool?                                 │
│   → tools.py     → mcp_client.py                           │
│                       │                                     │
│                       ▼                                     │
│               tools/call → MCP Server (stdio)               │
└─────────────────────────────────────────────────────────────┘
```

### Key Principle: MCP tools are first-class tools

The LLM doesn't know (or care) whether a tool is built-in or MCP. The tool list presented to the model is a single unified list. Tool routing happens transparently in the runtime.

---

## Available MCP Servers (Ecosystem Survey)

### Reference Servers (official, maintained by MCP steering group)

| Server | Description | Tools it provides | Stdio |
|--------|-------------|-------------------|-------|
| **filesystem** | Secure file operations with configurable access controls | read_file, write_file, create_directory, list_directory, move_file, search_files, get_file_info, list_allowed_directories | ✅ |
| **git** | Read, search, and manipulate Git repositories | git_status, git_log, git_diff, git_add, git_reset, git_log_blame, git_commit, git_create_branch, git_checkout, git_show, git_init | ✅ |
| **fetch** | Web content fetching and conversion for LLM usage | fetch (URL → markdown/text) | ✅ |
| **memory** | Knowledge graph-based persistent memory system | create_entities, create_relations, add_observations, delete_entities, delete_relations, delete_observations, read_graph, search_nodes, open_nodes | ✅ |
| **sequential-thinking** | Dynamic and reflective problem-solving through thought sequences | sequentialthinking (structured reasoning chain) | ✅ |
| **time** | Time and timezone conversion | get_current_time, convert_time | ✅ |

### Popular Community Servers

| Server | Description | Relevant for CrabCakes |
|--------|-------------|----------------------|
| **GitHub** (official) | Repository management, issues, PRs, code search | ✅ Issue tracking, PR management |
| **GitLab** | GitLab API integration | Similar to GitHub |
| **PostgreSQL** | Read-only database access with schema inspection | ✅ Database introspection |
| **SQLite** | Database interaction and business intelligence | ✅ Lightweight data analysis |
| **Brave Search** (official) | Web and local search using Brave's Search API | Supersedes our built-in web_search |
| **Puppeteer** | Browser automation and web scraping | ✅ UI testing, web scraping |
| **Slack** | Channel management and messaging | Team communication |
| **Sentry** | Issue retrieval and analysis from Sentry.io | ✅ Error monitoring |
| **Google Drive** | File access and search for Google Drive | Document access |
| **Google Maps** | Location services, directions, place details | Geospatial data |
| **Redis** | Interact with Redis key-value stores | Caching, state management |

### What This Means for CrabCakes

A Coder agent configured with the **git** MCP server gets `git_commit`, `git_branch`, `git_diff` etc. — operations our built-in tools can't do (our `exec_command` can run git, but the LLM has to construct the right command). MCP gives us structured, well-described tools with proper schemas.

A Debugger agent configured with **PostgreSQL** and **Sentry** MCP servers can query live databases and inspect production errors — capabilities we'd never build into `agent/tools.py`.

---

## Configuration Design

### 1. MCP Server Registry (global config)

**File:** `~/.config/crabcakes/mcp-servers.json`

Defines all available MCP servers. Shared across all agents — this is the catalog.

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
    "postgres": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
      "description": "PostgreSQL read-only access",
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
    }
  }
}
```

**Design decisions:**
- **Named servers** — agents reference servers by name (`"github"`) not by command. Makes it easy to swap implementations.
- **`${ENV_VAR}` syntax** — environment variable substitution in the `env` block. Keeps tokens out of config files.
- **`enabled` flag** — disable a server globally without deleting its config.
- **`transport` field** — currently always `"stdio"`, but positions us for `"streamable-http"` later:
  ```json
  "remote-ai": {
    "transport": "streamable-http",
    "url": "https://mcp.example.com/tools",
    "headers": {
      "Authorization": "Bearer ${MCP_API_TOKEN}"
    },
    "description": "Remote AI tool server"
  }
  ```
- **Global, not per-project** — MCP servers are system-level resources. A PostgreSQL server doesn't change per project. Per-project tool *selection* (which of the server's tools this agent gets for this project) happens in the agent YAML.

### 2. Per-Agent MCP Server Selection (agent YAML)

**File:** Agent YAML (e.g. `~/.config/crabcakes/agents/coder.yaml`)

```yaml
# Coder — Full-stack code writing agent
name: Coder
emoji: "🛠️"
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
mcp_servers:              # NEW — which MCP servers to connect to
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

**Key design decisions:**
- **`mcp_servers`** — list of server names from the global registry. When this agent starts, CrabCakes connects to these servers and discovers their tools.
- **`tools` list includes MCP tools** — MCP tools are namespaced as `server_name/tool_name`. This lets the Captain selectively enable individual MCP tools, just like built-in tools. An agent might connect to the GitHub server (which exposes 20+ tools) but only be allowed to use `create_issue` and `search_repositories`.
- **Backward compatible** — agents without `mcp_servers` work exactly as they do today. No changes to existing agents.

### 3. Edit Agent Dialog Modifications

The current Edit Agent dialog has:
- Name, Emoji, Role fields
- Provider dropdown
- Model entry
- System Prompts checklist
- Tools section (preset buttons + checkboxes)

**Changes needed:**

#### 3a. MCP Server Selection (new section)

Add an "MCP Servers" section between System Prompts and Tools:

```
┌─────────────────────────────────────────────────────┐
│  MCP Servers                                        │
│  ┌─────────────────────────────────────────────────┐│
│  │ ☑ GitHub — GitHub API, issues, PRs, repos       ││
│  │ ☑ Fetch — Web content fetching                  ││
│  │ ☐ Git — Git repository operations               ││
│  │ ☐ PostgreSQL — Read-only database access         ││
│  │ ☐ Memory — Persistent knowledge graph            ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

- Checkboxes populated from `mcp-servers.json` registry
- Shows server name + description
- Checking a server connects to it and discovers its tools (with a loading indicator)
- Saved as `mcp_servers` list in the agent YAML

#### 3b. Tool Selection Expanded

The existing Tools section now shows **built-in tools** AND **MCP tools from selected servers**:

```
┌─────────────────────────────────────────────────────┐
│  Tools                                              │
│  [Full Access] [Read Only] [Custom]                 │
│  ┌─────────────────────────────────────────────────┐│
│  │ ── Built-in ─────────────────────────────────── ││
│  │ ☑ read_file — Read file contents                ││
│  │ ☑ write_file — Write file to disk               ││
│  │ ☑ edit_file — Replace exact text in file        ││
│  │ ☑ exec_command — Run shell command               ││
│  │ ☑ list_files — List directory contents           ││
│  │ ☑ search_files — Search for pattern in files     ││
│  │ ── GitHub ───────────────────────────────────── ││
│  │ ☑ create_issue — Create a new GitHub issue       ││
│  │ ☑ search_repositories — Search GitHub repos      ││
│  │ ☑ get_file_contents — Get file from GitHub repo  ││
│  │ ☐ list_commits — List commits in a repository    ││
│  │ ☐ create_pull_request — Create a GitHub PR       ││
│  │ ... (15 more GitHub tools)                       ││
│  │ ── Fetch ────────────────────────────────────── ││
│  │ ☑ fetch — Fetch URL content as markdown          ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

- **Section headers** separate built-in tools from MCP server tools
- **Collapsible sections** — MCP server tool lists can be long. Each server's tools are in a collapsible group, defaulting to expanded.
- **Group-level checkboxes** — checking the server header toggles all its tools.
- **Tool names stored as namespaced** — `github/create_issue`, `fetch/fetch`, etc.
- **Lazy discovery** — tools are discovered when the server checkbox is checked. If the server isn't running, show an error inline.
- **Preset buttons updated** — "Full Access" checks everything (built-in + all MCP). "Read Only" checks built-in read-only tools + all MCP tools (since MCP tools are already access-controlled by the server).

---

## Implementation Plan

### Files to Create

| File | Purpose |
|------|---------|
| `utils/mcp_client.py` | MCP client — connects to servers via stdio, discovers tools, calls tools |
| `utils/mcp_config.py` | Load/validate/save `mcp-servers.json` registry |
| `tests/test_mcp_client.py` | Unit tests for MCP client |
| `tests/test_mcp_config.py` | Unit tests for config loading |

### Files to Modify

| File | Changes |
|------|---------|
| `agent/runtime.py` | Merge MCP tools into tool loop; route MCP tool calls to `mcp_client` |
| `agent/tools.py` | `get_tool_definitions_for_api()` accepts MCP tools; `execute_tool()` routes MCP namespaced tools |
| `agent/context.py` | Include MCP tool descriptions in system prompt context |
| `ui/views/agent_builder.py` | Add MCP server checkboxes; expand tool picker with MCP tools |
| `ui/handlers/agent_builder_handler.py` | Load MCP server options; discover tools from selected servers |
| `utils/agent_defs.py` | Parse `mcp_servers` field from agent YAML |
| `docs/ARCHITECTURE.md` | Document MCP client module and config format |

### Module: `utils/mcp_client.py`

```python
class MCPClient:
    """Manages connections to MCP servers and provides tool discovery/invocation."""

    def __init__(self):
        self._servers: dict[str, MCPServerConnection] = {}  # name → connection

    async def connect(self, server_name: str, config: dict) -> None:
        """Connect to an MCP server. Launches subprocess for stdio transport."""

    async def disconnect(self, server_name: str) -> None:
        """Disconnect from an MCP server. Terminates subprocess."""

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""

    async def discover_tools(self, server_name: str) -> list[MCPToolDef]:
        """Call tools/list on a connected server. Returns tool definitions."""

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> MCPToolResult:
        """Call tools/call on a connected server."""

    def get_all_tools(self) -> list[MCPToolDef]:
        """Return all discovered tools from all connected servers."""

    def is_connected(self, server_name: str) -> bool:
        """Check if a server is connected."""

@dataclass
class MCPToolDef:
    """Tool definition from an MCP server."""
    server_name: str           # e.g. "github"
    tool_name: str             # e.g. "create_issue"
    namespaced_name: str       # e.g. "github/create_issue"
    description: str
    input_schema: dict         # JSON Schema

@dataclass
class MCPToolResult:
    """Result from an MCP tool call."""
    content: list[dict]        # [{"type": "text", "text": "..."}, ...]
    is_error: bool = False
```

### Module: `utils/mcp_config.py`

```python
def load_mcp_servers_config() -> dict:
    """Load the MCP server registry from ~/.config/crabcakes/mcp-servers.json."""

def save_mcp_servers_config(config: dict) -> None:
    """Save the MCP server registry."""

def get_server_config(server_name: str) -> dict | None:
    """Get config for a specific server by name."""

def resolve_env_vars(value: str) -> str:
    """Replace ${VAR} patterns with environment variable values."""

def validate_server_config(name: str, config: dict) -> list[str]:
    """Validate a server config. Returns list of errors."""
```

### Runtime Integration: `agent/runtime.py`

The tool loop currently:
1. Build tool list from `get_tool_definitions_for_api()`
2. Send to LLM
3. LLM returns tool calls
4. Execute each via `execute_tool()`

With MCP:
1. Build tool list from `get_tool_definitions_for_api()` **+ MCP discovered tools**
2. Send to LLM (tools look identical — just more of them)
3. LLM returns tool calls
4. **Route:** if tool name contains `/` → MCP client, else → built-in `execute_tool()`
5. Result format is normalized — built-in returns `ToolResult`, MCP returns `MCPToolResult`, both converted to the same format for the LLM

### Agent Lifecycle

When an agent starts a conversation:
1. Read agent YAML → get `mcp_servers` list
2. For each server in the list:
   a. Load server config from `mcp-servers.json`
   b. `mcp_client.connect(server_name, config)` — launch subprocess
   c. `mcp_client.discover_tools(server_name)` — get tool definitions
3. Filter discovered tools by agent's `tools` list (namespace-prefixed)
4. Merge with built-in tools
5. Present unified list to LLM

When the agent stops or conversation ends:
1. `mcp_client.disconnect_all()` — terminate all server subprocesses

---

## Security Considerations

1. **MCP tool calls go through the same approval gate as exec_command.** If a tool is marked as requiring approval (or if the Captain configures it), the PM must approve before the call goes to the MCP server.

2. **Server subprocess isolation.** Each MCP server runs as a separate subprocess. If it crashes, it doesn't affect CrabCakes or other servers.

3. **Environment variable substitution for secrets.** API tokens go in environment variables, not in config files. The `${VAR}` syntax reads them at runtime.

4. **Sandboxing doesn't apply to MCP tools.** Built-in file tools sandbox to `project_path`. MCP tools are external — their sandboxing is the MCP server's responsibility. The agent prompt should make this clear.

5. **Tool descriptions from MCP servers are UNTRUSTED** (per MCP spec). We display them in the Edit Agent dialog for selection, but don't let them influence agent behavior beyond what the Captain explicitly enables.

---

## Effort Estimate

| Phase | Description | Effort |
|-------|-------------|--------|
| **Phase 1** | `mcp_config.py` + `mcp_client.py` (stdio only) + tests | ~4 hours |
| **Phase 2** | Runtime integration (tool merging, routing) | ~3 hours |
| **Phase 3** | Edit Agent dialog (MCP server selection + expanded tool picker) | ~3 hours |
| **Phase 4** | Documentation, architecture updates, integration testing | ~2 hours |
| **Total** | | **~12 hours** |

Could be broken into 2-3 specs:
- **SPEC-A:** MCP client library + config (Phase 1)
- **SPEC-B:** Runtime integration (Phase 2)
- **SPEC-C:** UI integration (Phase 3 + 4)

---

## Future Considerations (out of scope for v1)

1. **Streamable HTTP transport** — Add `"transport": "streamable-http"` support with URL + headers config. Same `mcp_client.py` interface, different transport layer.

2. **Per-project MCP servers** — A `.crabcakes/mcp-servers.json` in a project directory that adds project-specific servers (e.g., a project's database server).

3. **Dynamic tool discovery** — Listen for `notifications/tools/list_changed` from MCP servers and update the available tool list without restarting the agent.

4. **MCP server marketplace** — Browse and install MCP servers from a registry directly in CrabCakes UI (similar to VS Code extension marketplace).

5. **CrabCakes as MCP server** — Expose CrabCakes' built-in tools and review/feed system as an MCP server that other AI applications can connect to.

6. **Resource support** — MCP servers can also expose Resources (contextual data) and Prompts (templates). Initial scope is Tools only.

---

## Dependencies

- **`mcp` Python package** — Official MCP Python SDK. Provides client-side stdio transport, JSON-RPC message handling, and type definitions. `pip install mcp`.
- **`npx` or `uvx`** — MCP servers are typically distributed as npm packages or Python packages. The Captain needs `npx` (Node.js) or `uvx` (uv/Python) installed to run most servers. Most Linux systems will have one or both.
- No other new dependencies.
