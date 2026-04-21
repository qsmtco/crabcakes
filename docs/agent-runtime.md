# Agent Runtime — Specification (v0.2)

**Last updated:** 2026-04-18
**Changelog:** v0.1 → v0.2 — Added Crabcake Special Agents (always-present local agents in Agents tab), dual-section Agents tab layout, special agent definitions (Coder + Debugger).
**Status:** Not implemented — ready for build
**Depends on:** Existing CrabCakes architecture (see `docs/ARCHITECTURE.md`)
**New dependencies:** `httpx` (async HTTP client for LLM API calls), `gitpython` (shared with review-layer-simple)

---

## Overview

CrabCakes includes a built-in agent runtime that allows it to function as a standalone project development environment. Each agent tab runs an independent conversation loop with an LLM that has access to local tools (read files, write files, run commands, search the web). The human acts as project manager — assigning tasks, reviewing diffs, and accepting or rejecting changes.

**Key design:** CrabCakes is not a gateway client. It is the runtime. Each agent is a system prompt + a working directory + a tool loop. No WebSocket, no device auth, no external daemon.

**Why this instead of the OpenClaw gateway:** The gateway is designed for general-purpose agent assistance across multiple surfaces (Telegram, web, desktop). CrabCakes is a project development environment where the human manages agents writing code. That use case benefits from owning the entire stack — direct file access, direct tool execution, no permission negotiation, no multi-surface routing overhead.

**Relationship to existing gateway code:** The gateway code (`gateway/client.py`) remains in the codebase and works as before. Special agents run locally and gateway agents connect through the OpenClaw gateway. Both coexist simultaneously — no mode toggle needed. Both share the same UI (chat tabs, project tabs, review layer).

---

## What We're Building

CrabCakes as a project development environment where:

1. **The human is the PM.** They open projects, assign tasks to agents, review work, accept or reject changes.
2. **Crabcake Special Agents are always available.** Two built-in agents — Coder and Debugger — are present from first launch. They appear in the Agents tab with their own avatars and are always ready to work. No gateway connection required.
3. **Special agents are local.** Their conversations go directly from CrabCakes to the LLM provider via the agent runtime. They never touch the OpenClaw gateway.
4. **Gateway agents coexist.** When connected to an OpenClaw gateway, discovered agents appear in a separate section above the special agents. Both sections are visible simultaneously. Gateway agents route through the gateway; special agents route through the local runtime.
5. **Agents work on project files.** They read, write, and execute commands in the project directory. The review layer gates their changes (see `docs/review-layer-simple.md`).
6. **Everything is local for special agents.** LLM API calls go directly from CrabCakes to the provider. No WebSocket, no device auth, no external daemon.

---

## Architecture

### How It Fits Into CrabCakes

The agent runtime is a new layer between the UI (handlers/views) and the LLM provider. It powers the Crabcake Special Agents — always-present local agents that never touch the gateway.

```
Gateway agents (when connected):
  UI handlers → gateway/client.py → OpenClaw gateway → LLM provider

Crabcake Special Agents (always available):
  UI handlers → agent/runtime.py → LLM provider (direct)
```

Both paths share the same UI: same chat tabs, same streaming, same tool cards, same review layer. The Agents tab shows both sections:

```
Agents Tab
├── Connected Agents              (gateway — only when connected)
│   ├── Qaster ●
│   └── Qrusher ●
│
└── Crabcake Special Agents       (always present, local)
    ├── 🛠️ Coder
    └── 🐛 Debugger
```

The handlers don't change. `ChatHandler.on_send()` still sends a message. The difference is *where* that message goes: to a gateway WebSocket for gateway agents, or to the local agent runtime for special agents.

### New Packages and Modules

| Module | Package | Responsibility |
|--------|---------|---------------|
| `agent/__init__.py` | `agent/` | Exports: AgentRuntime |
| `agent/special_agents.py` | `agent/` | Special agent definitions — Coder, Debugger. Registry of always-present local agents. |
| `agent/runtime.py` | `agent/` | AgentRuntime — owns the tool loop, manages conversations, calls LLM API |
| `agent/tools.py` | `agent/` | Tool definitions and execution — read_file, write_file, exec, web_search, etc. |
| `agent/config.py` | `agent/` | LLM provider configuration — API keys, base URLs, model selection |
| `agent/context.py` | `agent/` | Context builder — assembles system prompt + project files + conversation history |
| `models/conversation.py` | `models/` | Conversation and Message dataclasses — per-agent conversation state |
| `ui/handlers/agent_runtime_handler.py` | `ui/handlers/` | Bridge between UI and AgentRuntime — handles local special agent conversations alongside GatewayHandler |

### Directory Impact

```
crabcakes/
├── agent/                          # NEW PACKAGE — agent runtime
│   ├── __init__.py                 # Exports: AgentRuntime, SPECIAL_AGENTS
│   ├── runtime.py                  # AgentRuntime — tool loop + conversation management
│   ├── tools.py                    # Tool definitions + execution
│   ├── config.py                   # LLM provider config (API keys, models)
│   ├── context.py                  # System prompt + file context builder
│   └── special_agents.py           # Special agent definitions (Coder, Debugger) + registry
│
├── models/
│   ├── ... (existing)
│   └── conversation.py             # NEW — Conversation + Message dataclasses
│
├── ui/
│   ├── handlers/
│   │   ├── ... (existing)
│   │   └── agent_runtime_handler.py  # NEW — bridge between UI and runtime
│   └── views/
│       ├── ... (existing)
│       └── (review_bar.py, diff_card.py from review-layer-simple)
│
├── gateway/                        # EXISTING — unchanged, used in gateway mode
├── utils/                          # EXISTING — tools.py uses git_ops.py, projects.py
└── docs/
    ├── ARCHITECTURE.md             # UPDATE — add agent/ to directory tree
    ├── review-layer-simple.md      # EXISTS — review layer spec
    └── agent-runtime.md            # THIS FILE
```

### Layer Dependency Rules (per ARCHITECTURE.md)

```
gateway/           → no ui/ imports (unchanged)
agent/             → no ui/ imports (new rule, same pattern as gateway/)
models/            → no ui/ imports, no agent/ imports, no gateway/ imports (unchanged)
ui/handlers/       → imports agent/, models/ (new)
ui/views/          → no agent/ imports (views receive data, not runtime references)
utils/             → no ui/ imports, no agent/ imports (unchanged)
```

---

## Crabcake Special Agents

Special agents are predefined local agents that are always available from the moment CrabCakes launches. They require no gateway connection, no setup, no configuration beyond the LLM API key in `~/.config/crabcakes/agent.json`.

### What Makes Them Special

- **Always present** — their cards appear in the Agents tab immediately on app launch
- **Always local** — conversations go directly to the LLM provider, never through the gateway
- **Predefined roles** — each has a purpose-built system prompt and tool set
- **Persistent state** — conversation history is saved to disk and restored on restart
- **Project-aware** — when a project tab is open, special agents automatically operate on that project

### Agent Definitions

#### 🛠️ Coder

**Role:** Implements features, refactors code, writes tests, builds infrastructure.

| Property | Value |
|----------|-------|
| Display name | Coder |
| Avatar | 🛠️ (or rendered icon with hammer + wrench) |
| Color | `#6366f1` (indigo — first from AGENT_COLORS) |
| Conv ID prefix | `special:coder` |
| Default model | From config `default_model` |

**Tools:** read_file, write_file, exec_command, list_files, search_files, web_search, web_fetch

**System prompt (built by `agent/context.py`):**
```
You are Coder, a software development agent built into the CrabCakes project development environment.
Your job is to write clean, correct, well-tested code.

Project: {project_name}
Working directory: {project_path}

{file_context}

Tools available: read_file, write_file, exec_command, list_files, search_files, web_search, web_fetch

Rules:
- Always read a file before modifying it
- Write tests for new functionality when practical
- Use exec_command to run tests after making changes
- If you're unsure about something, use search_files or web_search before guessing
- Report what you did and what still needs to be done
{review_mode_instructions}
{custom_prompt}
```

#### 🐛 Debugger

**Role:** Diagnoses bugs, traces errors, analyzes logs, identifies root causes. Suggests fixes but defaults to investigating rather than editing.

| Property | Value |
|----------|-------|
| Display name | Debugger |
| Avatar | 🐛 (or rendered icon with magnifying glass + bug) |
| Color | `#f43f5e` (rose — third from AGENT_COLORS) |
| Conv ID prefix | `special:debugger` |
| Default model | From config `default_model` |

**Tools:** read_file, exec_command, list_files, search_files, web_search, web_fetch

Note: Debugger does **not** get write_file by default. It investigates and reports. If the PM wants the Debugger to also fix issues, write_file can be enabled per-conversation via a toggle in the agent's chat tab.

**System prompt (built by `agent/context.py`):**
```
You are Debugger, a diagnostic agent built into the CrabCakes project development environment.
Your job is to investigate bugs, trace errors, analyze logs, and identify root causes.

Project: {project_name}
Working directory: {project_path}

{file_context}

Tools available: read_file, exec_command, list_files, search_files, web_search, web_fetch

Rules:
- Start by understanding the error or symptom described by the PM
- Read relevant files to trace the code path
- Use exec_command to run the code and reproduce the issue
- Use search_files to find related code and error handling
- Report your findings clearly: what's wrong, where it is, and what a fix would look like
- You do NOT write files by default — you diagnose. If asked to fix, proceed carefully.
{review_mode_instructions}
{custom_prompt}
```

### Agent Registry

Special agents are defined in code, not in config files. They're registered in a module-level constant:

```python
# agent/special_agents.py

from dataclasses import dataclass

@dataclass
class SpecialAgentDef:
    """Definition of a Crabcake Special Agent."""
    conv_id_prefix: str       # e.g. "special:coder"
    display_name: str         # e.g. "Coder"
    emoji: str                # e.g. "🛠️"
    color: str                # hex color from AGENT_COLORS
    tools: list[str]          # tool names this agent can use
    system_prompt_template: str  # template with {project_name}, {file_context}, etc.
    can_write: bool           # whether write_file is in the default tool set

SPECIAL_AGENTS: dict[str, SpecialAgentDef] = {
    "special:coder": SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        emoji="🛠️",
        color="#6366f1",
        tools=["read_file", "write_file", "exec_command", "list_files", "search_files", "web_search", "web_fetch"],
        system_prompt_template=CODER_PROMPT_TEMPLATE,
        can_write=True,
    ),
    "special:debugger": SpecialAgentDef(
        conv_id_prefix="special:debugger",
        display_name="Debugger",
        emoji="🐛",
        color="#f43f5e",
        tools=["read_file", "exec_command", "list_files", "search_files", "web_search", "web_fetch"],
        system_prompt_template=DEBUGGER_PROMPT_TEMPLATE,
        can_write=False,
    ),
}

def get_special_agents() -> list[SpecialAgentDef]:
    """Return all special agent definitions, in display order."""
    return list(SPECIAL_AGENTS.values())

def get_special_agent(prefix: str) -> SpecialAgentDef | None:
    """Get a special agent definition by its conv_id_prefix."""
    return SPECIAL_AGENTS.get(prefix)
```

**Adding a new special agent:** Create a new `SpecialAgentDef`, add it to the `SPECIAL_AGENTS` dict, and it automatically appears in the Agents tab on next launch. No other code changes needed.

### Agents Tab Layout

The left panel Agents tab (`ui/views/left_panel.py`) renders two sections:

```
┌─────────────────────────────┐
│  AGENTS                     │
│                             │
│  Connected Agents           │  ← section header, only shown when gateway connected
│  ┌───────────────────────┐  │
│  │ ● Qaster        [💬]  │  │  ← gateway agent, from AgentListHandler
│  │ ● Qrusher       [💬]  │  │
│  └───────────────────────┘  │
│                             │
│  Crabcake Special Agents    │  ← section header, always shown
│  ┌───────────────────────┐  │
│  │ 🛠️ Coder        [💬]  │  │  ← always present, from SpecialAgentDef registry
│  │ 🐛 Debugger      [💬]  │  │
│  └───────────────────────┘  │
│                             │
└─────────────────────────────┘
```

**Implementation:**
- The Agents tab's `Gtk.ListBox` is split into two groups with `Gtk.ListBoxRow` separators
- Gateway agents section: populated by existing `AgentListHandler` (unchanged). Hidden when not connected.
- Special agents section: populated from `SPECIAL_AGENTS` registry. Always visible. Each row shows emoji avatar + name + 💬 chat button.
- Clicking a special agent row opens its chat tab (or switches to existing one if already open)
- Special agent avatars use `utils/icons.py` — rendered as colored circles with the emoji or initials, same style as gateway agent avatars

### Special Agent Conversation Lifecycle

```
App launches
  → AgentRuntimeHandler.start()
    → AgentRuntime.start()
    → For each special agent in SPECIAL_AGENTS:
      → runtime.create_conversation(
            agent_name=def.display_name,
            conv_id=f"{def.conv_id_prefix}",  # stable ID, not UUID
            project_path=None,  # no project yet
        )
      → Load saved conversation from ~/.config/crabcakes/conversations/special:coder.json
      → If found: restore history. If not: fresh conversation.

PM clicks Coder in Agents tab
  → main_content.create_chat_tab("special:coder", "Coder")
  → Chat tab opens with restored conversation history (or empty if new)

PM types "Implement JWT auth"
  → ChatHandler.on_send()
    → Detects session_key starts with "special:" → routes to AgentRuntimeHandler
    → AgentRuntimeHandler.send_message("special:coder", text)
      → runtime.send_message("special:coder", text)
        → Build context (system prompt from Coder template + project files if project open)
        → Call LLM API → tool loop → stream response

PM opens project tab
  → AgentRuntimeHandler.on_project_opened(name, path)
    → For each special agent conversation:
      → conversation.project_path = path
      → Rebuild system prompt with project file context
      → (agent is now project-aware for subsequent messages)

PM closes project tab
  → AgentRuntimeHandler.on_project_closed(name)
    → For each special agent conversation:
      → conversation.project_path = None
      → System prompt reverts to generic (no project context)
```

---

## Module Specifications

### `models/conversation.py`

**Responsibility:** Data classes for conversation state. Pure data — no GTK, no network, no LLM calls.

**Why models/:** Per ARCHITECTURE.md: "Models are pure data. They contain no GTK code. They are the single source of truth."

**Public API:**
```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool"

class ToolCallStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ToolCall:
    """A single tool call from an assistant message."""
    call_id: str                    # unique identifier (e.g. "call_abc123")
    tool_name: str                  # e.g. "read_file", "exec"
    arguments: dict                 # parsed JSON arguments
    result: str | None = None       # tool execution result (text)
    status: ToolCallStatus = ToolCallStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None

@dataclass
class Message:
    """A single message in a conversation."""
    role: MessageRole
    content: str                    # text content (empty for tool calls)
    tool_calls: list[ToolCall] = field(default_factory=list)  # non-empty only for assistant messages
    tool_call_id: str | None = None # non-None only for tool result messages
    timestamp: datetime = field(default_factory=datetime.now)
    tokens_used: int = 0            # running token count for this message

@dataclass
class Conversation:
    """Full conversation state for a single agent tab."""
    agent_name: str                 # display name for the agent
    project_path: str | None = None # working directory for tools
    system_prompt: str = ""         # injected at start of every LLM call
    messages: list[Message] = field(default_factory=list)
    model: str = ""                 # e.g. "openai/gpt-4o", "minimax/MiniMax-M2.5"
    created_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0           # cumulative token usage

    def add_user_message(self, content: str) -> Message:
        """Add a user (PM) message and return it."""
        msg = Message(role=MessageRole.USER, content=content)
        self.messages.append(msg)
        return msg

    def add_assistant_message(self, content: str, tool_calls: list[ToolCall] | None = None) -> Message:
        """Add an assistant message and return it."""
        msg = Message(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls or [])
        self.messages.append(msg)
        return msg

    def add_tool_result(self, call_id: str, result: str) -> Message:
        """Add a tool result message."""
        msg = Message(role=MessageRole.TOOL_RESULT, content=result, tool_call_id=call_id)
        self.messages.append(msg)
        return msg

    def to_api_messages(self) -> list[dict]:
        """
        Convert conversation to the format expected by LLM APIs.

        Returns:
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, ...]

        Tool calls are formatted as:
            {"role": "assistant", "content": null, "tool_calls": [...]}
        Tool results as:
            {"role": "tool", "tool_call_id": "...", "content": "..."}
        """
        ...

    def get_token_estimate(self) -> int:
        """Rough token count estimate (~4 chars per token). Used for context window management."""
        total = len(self.system_prompt)
        for msg in self.messages:
            total += len(msg.content)
            for tc in msg.tool_calls:
                total += len(str(tc.arguments)) + len(tc.result or "")
        return total // 4

    def trim_to_token_limit(self, max_tokens: int) -> None:
        """
        Trim oldest messages (keeping system prompt) to stay under token limit.
        Never removes the system prompt or the most recent user message.
        """
        ...
```

**Rules:**
- No imports from `ui/`, `agent/`, `gateway/`, `subprocess`
- Pure data classes with helper methods only
- `to_api_messages()` is the serialization layer — it converts internal state to whatever the LLM API expects

---

### `agent/config.py`

**Responsibility:** LLM provider configuration. Reads from config file, provides provider instances.

**Why agent/:** This is agent-specific configuration (API keys, model selection), not general app config.

**Public API:**
```python
from dataclasses import dataclass

@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""
    name: str                       # e.g. "openai", "minimax", "anthropic"
    base_url: str                   # API endpoint
    api_key: str                    # API key (from config file)
    default_model: str              # e.g. "gpt-4o", "MiniMax-M2.5"
    supports_tools: bool = True     # whether the provider supports tool/function calling
    supports_streaming: bool = True
    max_tokens: int = 128000        # context window size

@dataclass
class AgentConfig:
    """Top-level agent runtime configuration."""
    providers: dict[str, LLMProviderConfig]   # keyed by provider name
    default_provider: str                      # e.g. "openai"
    default_model: str                         # e.g. "gpt-4o"
    max_tool_iterations: int = 50              # safety limit on tool loop
    tool_timeout_seconds: int = 120            # max time for a single tool execution
    auto_save_conversations: bool = True       # save conversation history to disk

def load_agent_config() -> AgentConfig:
    """
    Load agent configuration from ~/.config/crabcakes/agent.json.

    Example agent.json:
    {
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-...",
                "default_model": "gpt-4o",
                "max_tokens": 128000
            },
            "minimax": {
                "base_url": "https://api.minimax.chat/v1",
                "api_key": "...",
                "default_model": "MiniMax-M2.5",
                "max_tokens": 1048576
            }
        },
        "default_provider": "openai",
        "default_model": "gpt-4o",
        "max_tool_iterations": 50,
        "tool_timeout_seconds": 120
    }

    Returns AgentConfig with defaults for any missing fields.
    """
    ...

def get_api_key(provider_name: str) -> str | None:
    """Get API key for a specific provider. Returns None if not configured."""
    ...
```

**Security:** API keys are stored in `~/.config/crabcakes/agent.json`. This file should be `chmod 600`. Same pattern as existing `config.json` for MiniMax improve.

---

### `agent/tools.py`

**Responsibility:** Tool definitions and execution. Defines what tools agents have access to and runs them locally.

**Why agent/:** Tool definitions are specific to the agent runtime. They define the agent's capabilities.

**Public API:**
```python
from dataclasses import dataclass

@dataclass
class ToolDefinition:
    """Definition of a tool that an agent can use."""
    name: str                       # e.g. "read_file"
    description: str                # description sent to LLM
    parameters: dict                # JSON Schema for parameters
    dangerous: bool = False         # if True, requires PM approval in strict review mode

@dataclass
class ToolResult:
    """Result of executing a tool."""
    success: bool
    output: str                     # text output (file contents, command output, etc.)
    error: str | None = None        # error message if failed
    duration_ms: int = 0

# ── Tool Registry ──────────────────────────────────────────────────────

def get_all_tools() -> list[ToolDefinition]:
    """Return all available tool definitions (for LLM function calling)."""

def get_tool_definitions_for_api() -> list[dict]:
    """
    Return tools in the format expected by LLM APIs:
    [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
    """

def execute_tool(name: str, arguments: dict, project_path: str) -> ToolResult:
    """
    Execute a tool by name with the given arguments.

    Args:
        name: Tool name (e.g. "read_file")
        arguments: Parsed arguments dict (e.g. {"path": "src/main.py"})
        project_path: Absolute path to the project working directory

    Returns:
        ToolResult with output or error.

    All file paths are relative to project_path (sandboxed).
    Absolute paths in arguments are rejected unless they match project_path prefix.
    """

# ── Available Tools ────────────────────────────────────────────────────

# Each tool has a definition (sent to LLM) and an executor (runs locally).
# Tools are registered in a module-level dict: _TOOLS = {name: (definition, executor)}

# read_file
#   Reads a file relative to project_path.
#   Parameters: {"path": str, ["offset": int, "limit": int]}
#   Returns: file contents as text (truncated at 50KB)
#   Errors: file not found, permission denied, binary file

# write_file
#   Writes content to a file relative to project_path.
#   Parameters: {"path": str, "content": str}
#   Returns: "OK — wrote N bytes to <path>"
#   Errors: path outside project, permission denied, disk full
#   ⚠️ Dangerous: in review mode, writes go to staging (see review-layer-simple.md)

# exec_command
#   Runs a shell command in the project directory.
#   Parameters: {"command": str, ["timeout": int]}
#   Returns: stdout + stderr (truncated at 100KB)
#   Errors: timeout, non-zero exit code, command not found
#   ⚠️ Dangerous: can run any command. In strict review mode, blocked.
#   Safety: commands run with the same user permissions as CrabCakes.
#   Blocked commands: "rm -rf /", "mkfs", "dd if=/dev/zero" — hardcoded blocklist.

# list_files
#   Lists files in a directory relative to project_path.
#   Parameters: {"path": str, ["recursive": bool]}
#   Returns: file listing with sizes
#   Errors: directory not found

# search_files
#   Searches file contents using grep/ripgrep.
#   Parameters: {"pattern": str, ["path": str, "file_type": str]}
#   Returns: matching lines with file paths and line numbers
#   Errors: pattern not found, invalid regex

# web_search (optional — requires API key)
#   Searches the web via Brave Search API.
#   Parameters: {"query": str, ["count": int]}
#   Returns: search results (title, URL, snippet)
#   Note: uses same Brave API key as OpenClaw if configured, or a separate key in agent.json

# web_fetch (optional — no API key needed)
#   Fetches and extracts readable content from a URL.
#   Parameters: {"url": str, ["max_chars": int]}
#   Returns: page content as text/markdown
#   Errors: HTTP errors, timeout, invalid URL
```

**Implementation details:**

- **File sandboxing:** All file operations resolve paths relative to `project_path`. If a resolved path escapes the project directory (`os.path.realpath(result) != os.path.commonpath([result, project_path])`), the operation is rejected. This prevents agents from reading `~/.ssh/id_rsa` or writing to `/etc/passwd`.
- **Exec safety:** Commands run via `subprocess.run(command, shell=True, cwd=project_path, capture_output=True, timeout=timeout)`. A hardcoded blocklist prevents destructive commands. The blocklist is conservative — better to block a legitimate command than allow a destructive one.
- **Output truncation:** All tool results are truncated to fit within reasonable token limits. File reads at 50KB, exec output at 100KB. Truncation is noted in the output.
- **No GTK:** `tools.py` is pure Python. It imports `subprocess`, `os`, `pathlib` only. All results are data (strings), not widgets.

---

### `agent/context.py`

**Responsibility:** Build the system prompt and context for an LLM call. Assembles project info, file listing, and relevant file contents into a coherent prompt.

**Why agent/:** Context building is specific to the agent runtime's needs.

**Public API:**
```python
def build_system_prompt(
    agent_name: str,
    project_path: str | None,
    task_description: str | None = None,
) -> str:
    """
    Build the system prompt for an agent.

    Includes:
    - Agent identity ("You are <agent_name>, a software development agent...")
    - Project context (project name, directory structure, key files)
    - Tool usage instructions (what tools are available, how to use them)
    - Review mode awareness (if review is active, instructions to commit to branches)
    - Output format guidelines

    Args:
        agent_name: Display name for this agent
        project_path: Path to the project directory (None for non-project agents)
        task_description: Optional task override (if None, generic instructions)

    Returns:
        Complete system prompt string.
    """

def build_file_context(project_path: str, query: str | None = None) -> str:
    """
    Build a file context block listing project files and their contents.

    Strategy:
    - If query is provided: include files relevant to the query (by name match)
    - If no query: include directory tree + contents of key files
      (README, ARCHITECTURE, package.json, pyproject.toml, Makefile, etc.)
    - Respects .gitignore (skips node_modules, __pycache__, .git, etc.)
    - Total context capped at ~50K characters to leave room for conversation

    Returns:
        Formatted text block with file contents.
    """

def load_custom_system_prompt(project_path: str) -> str | None:
    """
    Load a custom system prompt from the project directory.

    Looks for (in order):
    1. .crabcakes/agent-system-prompt.md
    2. AGENTS.md (if exists in project root)
    3. None

    Returns:
        Custom prompt text, or None if no custom prompt found.
    """
```

---

### `agent/runtime.py`

**Responsibility:** The core agent loop. Manages conversations, calls LLM API, executes tools, streams responses. The brain of the agent runtime.

**Why agent/:** This is the agent runtime's central orchestrator. Same layering role as `gateway/client.py` — it's the connection to the outside world (LLM provider instead of WebSocket server).

**Public API:**
```python
class AgentRuntime:
    """
    Manages one or more agent conversations. Each agent tab in CrabCakes
    corresponds to one conversation managed by this runtime.

    Lifecycle:
        runtime = AgentRuntime(config)
        runtime.start()                          # starts background event loop

        # Create a conversation (one per agent tab)
        conv_id = runtime.create_conversation(
            agent_name="Worker-1",
            project_path="/home/q/projects/my-app",
            model="gpt-4o",
        )

        # Send a message (from PM to agent)
        runtime.send_message(conv_id, "Refactor the auth module")

        # Stream responses back via callbacks
        # (delta text, tool calls, final response, errors)

        runtime.stop()                           # clean shutdown

    Thread safety:
        - send_message() is thread-safe (can be called from GTK main thread)
        - All callbacks are dispatched via GLib.idle_add() for GTK safety
        - LLM API calls and tool execution run in background threads
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        GLib=None,                                       # for GTK thread dispatch
        on_text_delta: Callable | None = None,           # (conv_id, delta_text)
        on_tool_call_start: Callable | None = None,      # (conv_id, tool_name, args)
        on_tool_call_result: Callable | None = None,     # (conv_id, tool_name, result)
        on_response_complete: Callable | None = None,    # (conv_id, full_text)
        on_error: Callable | None = None,                # (conv_id, error_message)
        on_token_usage: Callable | None = None,          # (conv_id, tokens_used)
    ): ...

    def start(self) -> None:
        """Start the runtime. Initializes any resources needed."""

    def stop(self) -> None:
        """Stop the runtime. Cancels any in-progress LLM calls."""

    def create_conversation(
        self,
        agent_name: str,
        project_path: str | None = None,
        model: str | None = None,
        system_prompt_override: str | None = None,
    ) -> str:
        """
        Create a new conversation and return its ID.

        Args:
            agent_name: Display name for this agent.
            project_path: Working directory for tool execution.
            model: LLM model to use (e.g. "gpt-4o"). Uses default if None.
            system_prompt_override: Custom system prompt. Built from context if None.

        Returns:
            Conversation ID (UUID string).
        """

    def delete_conversation(self, conv_id: str) -> None:
        """Delete a conversation and free resources."""

    def send_message(self, conv_id: str, text: str) -> None:
        """
        Send a user message and run the agent loop.

        The loop:
        1. Append user message to conversation
        2. Build API messages (system + history)
        3. Call LLM API
        4. If response contains tool calls:
           a. Execute each tool (in sequence, not parallel)
           b. Append tool results to conversation
           c. Call LLM API again (go to step 3)
        5. If response is text only (no tool calls):
           a. Append assistant message to conversation
           b. Fire on_response_complete callback
           c. Done

        Streaming:
        - If the provider supports streaming, text deltas are sent via on_text_delta
        - Tool calls are reported as they appear in the stream
        - on_response_complete fires once with the full accumulated text

        Safety:
        - Loop terminates after max_tool_iterations (default 50)
        - Each tool execution has a timeout (default 120s)
        - On timeout or error, the error is reported and the loop stops
        """

    def cancel(self, conv_id: str) -> None:
        """Cancel an in-progress agent loop for a conversation."""

    def get_conversation(self, conv_id: str) -> Conversation | None:
        """Get the conversation state (for saving/loading)."""

    def save_conversation(self, conv_id: str) -> str:
        """
        Save conversation to disk as JSON.
        Location: ~/.config/crabcakes/conversations/<conv_id>.json
        Returns the file path.
        """

    def load_conversation(self, conv_id: str) -> bool:
        """Load conversation from disk. Returns True if found and loaded."""

    def list_conversations(self) -> list[tuple[str, str]]:
        """List saved conversations. Returns [(conv_id, agent_name), ...]"""

    def get_active_conversation_ids(self) -> list[str]:
        """Return IDs of conversations currently in an active agent loop."""

    # ── Internal ────────────────────────────────────────────────────────

    def _call_llm(self, conversation: Conversation) -> None:
        """
        Make an LLM API call for the given conversation.

        Determines provider from conversation.model string:
        - "openai/gpt-4o" → OpenAI API
        - "minimax/MiniMax-M2.5" → MiniMax API
        - "anthropic/claude-sonnet-4-20250514" → Anthropic API

        Uses httpx for HTTP requests (supports streaming via SSE).
        Handles provider-specific message formatting differences.
        """

    def _execute_tool_call(self, conv_id: str, tool_call: ToolCall) -> str:
        """
        Execute a single tool call and return the result string.

        Resolves project_path from the conversation.
        Calls tools.execute_tool(name, args, project_path).
        Updates tool_call status and result.
        """
```

**LLM API calling strategy:**

The runtime supports multiple providers. Provider selection is determined by the model string prefix:

| Model string | Provider | API format |
|-------------|----------|------------|
| `openai/*` | OpenAI | Chat Completions API (with tool_calls) |
| `minimax/*` | MiniMax | ChatCompletion v2 |
| `anthropic/*` | Anthropic | Messages API (with tool_use) |

Each provider has slightly different tool calling formats. The runtime normalizes them:

```python
# Internal: normalize tool calls from different providers
def _normalize_tool_calls(self, raw_response: dict, provider: str) -> list[ToolCall]:
    """
    Extract tool calls from provider-specific response format.

    OpenAI: response.choices[0].message.tool_calls
    Anthropic: response.content blocks with type="tool_use"
    MiniMax: response.choices[0].message.tool_calls (similar to OpenAI)
    """
```

**Streaming:**
- Uses SSE (Server-Sent Events) for providers that support it
- Text deltas fire `on_text_delta` callback immediately
- Tool calls are buffered until the complete call is received, then fired
- If provider doesn't support streaming, the full response is delivered at once

**Conversation persistence:**
- Conversations are saved as JSON to `~/.config/crabcakes/conversations/<conv_id>.json`
- Saved automatically when `auto_save_conversations=True` (default)
- Loaded on app startup to restore agent tab state
- JSON format is the `Conversation` dataclass serialized (messages, tool calls, metadata)

---

### `ui/handlers/agent_runtime_handler.py`

**Responsibility:** Bridge between the CrabCakes UI and the AgentRuntime. Creates conversations, routes user messages to the runtime, receives streamed responses and renders them in chat tabs. All GTK via `GLib.idle_add()`.

**Handler pattern compliance (per ARCHITECTURE.md Section 8.6):**
- One handler per subsystem (agent runtime)
- Does not import other handlers — window wires callbacks
- Receives dependencies via constructor
- Owns its state (`_runtime`, `_conv_map`)
- All GTK from background threads via `GLib.idle_add()`

**Relationship to existing GatewayHandler:**
- Both handlers coexist simultaneously — no mode toggle.
- `GatewayHandler` handles gateway agents; `AgentRuntimeHandler` handles special agents.
- `ChatHandler.on_send()` routes by session key prefix (`special:` → runtime, everything else → gateway).
- They share the same `ChatHandler` for rendering — messages look the same regardless of source.

**Public API:**
```python
class AgentRuntimeHandler:
    def __init__(
        self,
        *,
        GLib,                                           # gi.repository.GLib
        main_content,                                   # MainContent — for chat tabs
        chat_handler,                                   # ChatHandler — for rendering
        project_handler,                                # ProjectHandler — for active project
    ): ...

    def start(self) -> None:
        """Initialize and start the AgentRuntime."""

    def stop(self) -> None:
        """Stop the runtime, save conversations."""

    def is_running(self) -> bool:
        """True if runtime is started and ready."""

    def create_agent_tab(self, agent_name: str, model: str | None = None) -> str:
        """
        Create a new agent conversation and its chat tab.
        Returns the conversation ID (used as session_key internally).

        If a project is active, the conversation is bound to that project's path.
        """

    def send_message(self, conv_id: str, text: str) -> None:
        """Send a message to the agent. Starts or continues the tool loop."""

    def cancel(self, conv_id: str) -> None:
        """Cancel the current agent loop."""

    def get_active_agents(self) -> list[dict]:
        """Return info about active conversations for the Agents tab.
        [{"conv_id": ..., "name": ..., "model": ..., "status": "idle"|"working"}, ...]
        """

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """Called when a project tab opens. New agents created after this
        will be bound to this project's path."""

    def on_project_closed(self, project_name: str) -> None:
        """Called when a project tab closes."""

    def restore_conversations(self) -> None:
        """Load saved conversations and recreate their tabs.
        Called on app startup."""
```

**Internal state:**
```python
self._runtime: AgentRuntime | None = None
self._conv_map: dict[str, str] = {}      # session_key → conv_id
self._config: AgentConfig | None = None
```

**Callback wiring (how runtime events become UI updates):**

```python
# In __init__, wire runtime callbacks to ChatHandler rendering:

self._runtime = AgentRuntime(
    config=self._config,
    GLib=GLib,

    on_text_delta=lambda conv_id, delta:
        GLib.idle_add(lambda: self._chat_handler.handle_streaming_delta(conv_id, delta)),

    on_tool_call_start=lambda conv_id, name, args:
        GLib.idle_add(lambda: self._render_tool_card(conv_id, "started", name, args)),

    on_tool_call_result=lambda conv_id, name, result:
        GLib.idle_add(lambda: self._render_tool_card(conv_id, "completed", name, result)),

    on_response_complete=lambda conv_id, text:
        GLib.idle_add(lambda: self._chat_handler.handle_final(conv_id, text)),

    on_error=lambda conv_id, error:
        GLib.idle_add(lambda: self._chat_handler.handle_error(conv_id, error)),
)
```

**Tool card rendering:** When an agent uses a tool, a visual card appears in the chat tab showing:
- 🔧 `read_file("src/main.py")` → ✓ 2,340 bytes
- 🔧 `exec_command("pytest tests/")` → ✓ 12 passed, 0 failed
- 🔧 `write_file("src/auth.py", ...)` → ✓ wrote 1,892 bytes

These use the existing event card factories from `chat_bubble.py` (`create_tool_card`).

---

## Data Flow

### App Startup

```
App starts
  → window._build()
    → AgentRuntimeHandler.start()
      → load_agent_config() from ~/.config/crabcakes/agent.json
      → AgentRuntime(config, callbacks=...)
      → runtime.start()
      → For each special agent in SPECIAL_AGENTS:
        → runtime.create_conversation(
              agent_name=def.display_name,
              conv_id=def.conv_id_prefix,
          )
        → Load saved conversation from disk (if exists)
    → Left panel: render Crabcake Special Agents section
      → Coder card, Debugger card — always visible

    → GatewayHandler (existing code, unchanged)
      → If auto-connect is on: connect to gateway
      → On connect: populate Connected Agents section
      → If not connected: Connected Agents section is hidden
```

### Special Agent — Full Conversation Loop

```
PM clicks Coder in Agents tab
  → main_content.create_chat_tab("special:coder", "Coder")
    → Chat tab opens (with restored history if previously saved)

PM types "Refactor the auth module to use JWT tokens"
  → ChatHandler.on_send()
    → session_key starts with "special:" → routes to AgentRuntimeHandler
    → Render "You" bubble in chat tab
    → runtime.send_message("special:coder", text)
      → conversation.add_user_message(text)
      → build_system_prompt("Coder", project_path)
        → load_custom_system_prompt() — checks for .crabcakes/agent-system-prompt.md
        → build_file_context() — directory tree + key files
        → Returns full system prompt from Coder template
      → conversation.to_api_messages() — build API payload
      → _call_llm(conversation) — HTTP POST to provider

LLM responds with tool call: read_file("src/auth.py")
  → Runtime receives tool call in stream
    → on_tool_call_start → GLib.idle_add → tool card: 🔧 read_file("src/auth.py") ⏳
    → tools.execute_tool("read_file", {"path": "src/auth.py"}, project_path)
    → on_tool_call_result → GLib.idle_add → tool card: 🔧 read_file("src/auth.py") ✓ 2,340 bytes
    → conversation.add_tool_result(call_id, file_contents)
    → _call_llm(conversation) — call LLM again with tool result

LLM responds with tool call: write_file("src/auth.py", new_content)
  → Same loop
  → If review mode is active: write goes to staging (see review-layer-simple.md)

LLM responds with text: "I've refactored the auth module..."
  → Streaming text deltas → streaming bubble in chat tab
  → Final response → final bubble replaces streaming bubble
  → auto_save_conversation → saved to disk
```

### Gateway Agent — Unchanged

```
PM clicks Qaster in Connected Agents section
  → main_content.create_chat_tab(session_key, "Qaster")
    → Chat tab opens

PM types a message
  → ChatHandler.on_send()
    → session_key does NOT start with "special:" → routes to gateway (existing code)
    → gw.send_message(session_key, text)
    → Everything else is existing gateway behavior, unchanged
```

### Both Special + Gateway Agents Simultaneously

```
PM has three chat tabs open:
  1. Qaster (gateway)        — talking about general stuff
  2. Coder (special)          — implementing a feature
  3. Debugger (special)       — investigating a bug

Messages routed by session_key prefix:
  "special:coder"    → AgentRuntimeHandler → local LLM
  "special:debugger" → AgentRuntimeHandler → local LLM
  anything else      → GatewayHandler → OpenClaw gateway

No mode switching. Both paths active simultaneously.
```

---

## Integration with window.py

### New Instance Variables

```python
self._agent_runtime_handler: AgentRuntimeHandler    # created in _build()
```

### Wiring in `_build()`

```python
# Agent runtime handler — after other handlers are created
self._agent_runtime_handler = AgentRuntimeHandler(
    GLib=GLib,
    main_content=self._main_content,
    chat_handler=self._chat_handler,
    project_handler=self._project_handler,
)

# Start runtime immediately — special agents are always available
self._agent_runtime_handler.start()

# Wire project lifecycle — extend existing callbacks to also notify runtime handler
# When project opens: runtime binds special agents to project path
# When project closes: runtime unbinds special agents
```

### ChatHandler Modifications

`ChatHandler.on_send()` currently routes messages through the gateway. It needs routing logic based on the session key prefix:

```python
def on_send(self):
    session_key = self._main_content.get_current_session_key()
    text = self._main_content.get_input_text()

    if session_key.startswith("special:"):
        # Crabcake Special Agent — route to local runtime
        self._agent_runtime_handler.send_message(session_key, text)
    elif session_key.startswith("project:"):
        # Project tab — fan out to members
        self._fan_out_to_project(session_key, text)
    else:
        # Gateway agent — route through gateway
        self._gw.send_message(session_key, text)
```

This is the only change to ChatHandler. The rendering pipeline (ChatRenderHandler, streaming, event cards) is completely unchanged — it doesn't know or care where messages come from.

### Toolbar Modifications

The existing Connect button continues to work exactly as before — connecting to the gateway, discovering agents, populating the Connected Agents section.

No mode toggle needed. Special agents and gateway agents coexist simultaneously. `ChatHandler.on_send()` routes by session key prefix.

**Optional future addition:** A settings button that opens the agent configuration (API keys, default model) for the agent runtime.

### Left Panel Modifications

**Agents tab — dual section layout:**
- **Connected Agents section:** Populated by existing `AgentListHandler` when gateway is connected. Hidden when disconnected. Unchanged behavior.
- **Crabcake Special Agents section:** Always visible. Populated from `SPECIAL_AGENTS` registry in `agent/special_agents.py`. Each row shows emoji avatar + name + 💬 chat button.
- Clicking a special agent row opens its chat tab (or switches to existing tab).
- Double-click behavior same as gateway agents.

**Project tab:**
- Unchanged. FileTree works the same regardless of mode.
- When a project is opened, special agent conversations are automatically bound to that project's path (see Special Agent Conversation Lifecycle).

---

## Review Layer Integration

The agent runtime and the review layer (see `docs/review-layer-simple.md`) work together naturally:

1. **Agent writes a file** → `tools.execute_tool("write_file", ...)` checks if review mode is active
2. **If review mode is on:**
   - The write goes through `git_ops.stage_all()` instead of writing directly
   - The tool card in the chat shows "⚠️ staged for review" instead of "✓ wrote N bytes"
   - The agent's system prompt instructs it to commit changes after file writes
3. **If review mode is off:**
   - The write goes directly to the filesystem (current behavior)

**Review mode awareness in system prompt:**

```python
# In agent/context.py build_system_prompt():

if review_mode == "review":
    prompt += """
    REVIEW MODE IS ACTIVE. All file writes are staged for PM review.
    After making changes, commit them with a descriptive message.
    The PM will review your changes before they are finalized.
    Do NOT attempt to bypass the review system.
    """
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CRABCAKES_CONVERSATIONS_DIR` | `~/.config/crabcakes/conversations` | Directory for saved conversations |

### Config File (`~/.config/crabcakes/agent.json`)

```json
{
    "providers": {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-...",
            "default_model": "gpt-4o",
            "max_tokens": 128000,
            "supports_tools": true,
            "supports_streaming": true
        },
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "api_key": "...",
            "default_model": "MiniMax-M2.5",
            "max_tokens": 1048576,
            "supports_tools": true,
            "supports_streaming": true
        }
    },
    "default_provider": "openai",
    "default_model": "gpt-4o",
    "max_tool_iterations": 50,
    "tool_timeout_seconds": 120,
    "auto_save_conversations": true
}
```

### Per-Project Config (`.crabcakes/agent-config.json`)

```json
{
    "system_prompt_file": ".crabcakes/agent-system-prompt.md",
    "model_override": null,
    "review_mode": "off",
    "blocked_tools": [],
    "auto_context_files": ["README.md", "ARCHITECTURE.md", "package.json"]
}
```

---

## Tests

### `tests/test_tools.py`

| Test | What it verifies |
|------|-----------------|
| `test_read_file` | Reads existing file, returns contents |
| `test_read_file_not_found` | File doesn't exist → ToolResult.success=False |
| `test_read_file_binary` | Binary file → error message |
| `test_read_file_truncation` | Large file → truncated at 50KB |
| `test_read_file_with_offset` | Reads from offset, respects limit |
| `test_write_file` | Writes content, file exists on disk |
| `test_write_file_sandbox_escape` | Path "../../../etc/passwd" → rejected |
| `test_write_file_absolute_path` | Absolute path outside project → rejected |
| `test_exec_command` | Runs "echo hello" → output contains "hello" |
| `test_exec_command_timeout` | Long-running command → timeout error |
| `test_exec_command_blocklist` | "rm -rf /" → rejected |
| `test_exec_command_cwd` | Command runs in project_path, not CrabCakes dir |
| `test_list_files` | Lists directory contents correctly |
| `test_list_files_recursive` | Recursive listing includes subdirectories |
| `test_search_files` | Finds matching pattern in files |
| `test_search_files_no_match` | No matches → empty result, not error |
| `test_get_all_tools` | Returns expected tool definitions |
| `test_get_tool_definitions_for_api` | Output matches OpenAI function calling format |

### `tests/test_context.py`

| Test | What it verifies |
|------|-----------------|
| `test_build_system_prompt` | Contains agent name, project info, tool instructions |
| `test_build_file_context` | Includes directory tree and key file contents |
| `test_build_file_context_with_query` | Filters files relevant to query |
| `test_build_file_context_respects_gitignore` | Skips node_modules, .git, __pycache__ |
| `test_build_file_context_truncation` | Large projects → context capped at ~50K chars |
| `test_load_custom_system_prompt` | Loads from .crabcakes/agent-system-prompt.md |
| `test_load_custom_system_prompt_fallback` | Falls back to AGENTS.md |
| `test_load_custom_system_prompt_none` | No custom prompt → returns None |

### `tests/test_conversation.py`

| Test | What it verifies |
|------|-----------------|
| `test_add_user_message` | Message added with correct role |
| `test_add_assistant_message` | Message with tool calls |
| `test_add_tool_result` | Tool result linked by call_id |
| `test_to_api_messages` | Correct format for LLM API |
| `test_to_api_messages_with_tools` | Tool calls formatted correctly |
| `test_get_token_estimate` | Rough estimate within ±20% |
| `test_trim_to_token_limit` | Oldest messages removed, system prompt kept |
| `test_trim_never_removes_last_user` | Most recent user message always preserved |

### `tests/test_agent_runtime_handler.py`

Uses mock LLM responses (patch HTTP calls to return canned JSON).

| Test | What it verifies |
|------|-----------------|
| `test_start_stop` | Runtime starts and stops cleanly |
| `test_create_conversation` | Returns conv_id, conversation exists |
| `test_send_message_simple` | Single user message → single text response → complete |
| `test_send_message_with_tool` | User message → tool call → tool result → text response |
| `test_tool_loop_multiple` | Multiple tool calls in sequence |
| `test_max_iterations` | Loop stops after max_tool_iterations |
| `test_cancel` | Cancels mid-loop, no more callbacks |
| `test_streaming_deltas` | Text deltas fired incrementally |
| `test_error_handling` | LLM API error → on_error callback |
| `test_save_load_conversation` | Round-trip: save → load → same state |

---

## Phase Plan — Build Phase 1: Agent Runtime

Each phase includes updating `docs/ARCHITECTURE.md`. A phase is not complete until ARCHITECTURE.md reflects the new code.

### Step 1.1 — Data Models + Tool Execution

**Goal:** Conversation data model and tool execution work standalone.

**Steps:**
1. Create `models/conversation.py` — Conversation, Message, ToolCall dataclasses
2. Create `agent/__init__.py` — empty package
3. Create `agent/tools.py` — tool definitions + execution (read_file, write_file, exec_command, list_files, search_files)
4. Create `agent/config.py` — AgentConfig, load_agent_config()
5. Write `tests/test_conversation.py`
6. Write `tests/test_tools.py` — test against temp directories
7. Update `docs/ARCHITECTURE.md`

**Checkpoint:** A test script can create a Conversation, add messages, serialize to API format, and execute tools against a temp project directory.

### Step 1.2 — Context Builder

**Goal:** System prompt and file context are assembled correctly.

**Steps:**
1. Create `agent/context.py` — build_system_prompt, build_file_context, load_custom_system_prompt
2. Write `tests/test_context.py`
3. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Given a project directory, build_system_prompt() produces a complete system prompt with file listing and tool instructions. Custom prompts from .crabcakes/ are loaded.

### Step 1.3 — LLM API Runtime

**Goal:** The tool loop works end-to-end with a real or mock LLM.

**Steps:**
1. Create `agent/runtime.py` — AgentRuntime with full tool loop
2. Implement provider-specific API calling (start with OpenAI format as reference)
3. Implement streaming (SSE parsing for text deltas)
4. Implement conversation save/load
5. Write `tests/test_agent_runtime_handler.py` — mock HTTP, verify loop behavior
6. Update `docs/ARCHITECTURE.md`

**Checkpoint:** A test script sends "list the files in this project" to the runtime → agent calls list_files tool → returns file listing as text → conversation saved to disk.

### Step 1.4 — UI Integration

**Goal:** Agent runtime is wired into CrabCakes UI. Agent tabs work.

**Steps:**
1. Create `ui/handlers/agent_runtime_handler.py`
2. Modify `ui/handlers/chat_handler.py` — add `special:` prefix routing in on_send()
3. Modify `ui/window.py` — create AgentRuntimeHandler, wire callbacks
4. Modify `ui/views/left_panel.py` — add Crabcake Special Agents section below Connected Agents
5. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Running CrabCakes. Special agents always visible in Agents tab. Click Coder → chat tab opens → type message → agent responds with text and tool calls → streaming works → conversation saved. Gateway agents also work when connected. Both simultaneously.

### Step 1.5 — Review Layer Integration

**Note:** Full review layer spec is in `docs/review-layer.md` (Build Phase 2). This step only wires basic review awareness into the agent runtime so agent writes can be observed. The complete review UI (diff cards, ReviewBar, accept/reject) is built in Phase 2.

**Goal:** Agent writes are gated by review mode.

**Steps:**
1. Wire review mode into `agent/tools.py` — write_file checks review state
2. Add review awareness to system prompt in `agent/context.py`
3. Implement phases from `docs/review-layer-simple.md`
4. End-to-end test: agent writes file → review card appears → PM accepts → committed
5. Update `docs/ARCHITECTURE.md`
6. Update `docs/PROJECT_STATUS.md`

**Checkpoint:** Agent writes code → PM sees diff card → clicks Accept → change committed. Agent writes code → PM clicks Reject → files reverted, agent notified. Full development lifecycle works.

---

## Implementation Notes

- **LLM provider normalization:** The runtime normalizes tool calling across providers. OpenAI and Anthropic use slightly different formats. The runtime handles this so tools.py doesn't have to care.
- **Streaming via SSE:** Uses `httpx` with streaming responses. Each SSE chunk is parsed for delta text or tool call data. If a provider doesn't support streaming, the runtime falls back to blocking request.
- **Conversation history management:** Conversations grow over time. `trim_to_token_limit()` removes old messages when approaching the model's context window. System prompt is never removed.
- **Safety:** Tool execution is sandboxed to the project directory. Exec commands have a blocklist. Tool loop has a maximum iteration count. Timeouts on every tool execution.
- **Gateway coexistence:** The existing gateway code is not removed or modified. Special agents and gateway agents coexist simultaneously. The ChatHandler routes by session key prefix (`special:` → local runtime, everything else → gateway).
- **No new GTK widgets:** The agent runtime reuses existing chat tabs, streaming bubbles, tool cards, and event cards. No mode toggle needed — special agents and gateway agents coexist. The only new UI element is the special agents section in the Agents tab.
- **Cost awareness:** Token usage is tracked per conversation. `on_token_usage` callback fires after each LLM call. Displayed per-step in chat bubble footer.

---

## Features Inspired by Top Agent Projects

Research into the top open-source agent architectures (mini-swe-agent, Goose, OpenHands, Cline, Aider) yielded seven features worth incorporating. Each is mapped to its source project and integrated into the existing module structure.

### 1. Cost & Token Tracking with Limits and Per-Step Display — mini-swe-agent + Cline

**What:** Every conversation tracks cumulative token usage and estimated cost. Per-conversation configurable limits (`cost_limit`, `step_limit`, `token_limit`) prevent runaway agents. Each agent turn shows token count and cost in the chat bubble footer.

**From mini-swe-agent:** `AgentConfig` has `cost_limit` and `step_limit` as first-class fields. The agent stops when limits are exceeded.

**From Cline:** Token count and cost displayed per-step in the UI, keeping the user informed of spend at every turn.

**Spec changes:**
- `agent/runtime.py` — `RuntimeConfig` dataclass gains `cost_limit: float`, `step_limit: int`, `token_limit: int`. The tool loop checks limits before each LLM call.
- `models/conversation.py` — `Conversation` gains `total_cost: float`, `total_tokens: int`, `step_count: int` fields.
- `ui/views/chat_bubble.py` — Agent bubbles get an optional footer row showing tokens and cost (e.g., `1,247 tokens · $0.04`). Styled with muted text, small font.
- `agent/runtime.py` — `on_token_usage` callback already spec'd; now fires with `(tokens, cost, cumulative_cost, cumulative_tokens)` after each LLM response.

### 2. Repo Map Context Builder — Aider

**What:** Instead of loading entire files into context, build a structural summary of the codebase (functions, classes, imports, their line ranges) and send that as context. The agent can then request specific files to read.

**From Aider:** Aider builds a "repo map" — an AST-based tree of the entire codebase. This provides global awareness without consuming the full context window. Agents can intelligently decide which files to read based on the map.

**Spec changes:**
- `agent/context.py` — New function `build_repo_map(project_path: str) -> str`. Walks the project directory, parses Python/JS/TS files with `ast` module or tree-sitter (optional), outputs a compact text summary:
  ```
  src/main.py:
    class CrabcakesApp(Gtk.Application)
      def on_activate(app)
    function: bootstrap()
  src/handlers/chat_handler.py:
    class ChatHandler
      def on_send(session_key, text)
      def on_receive(message)
  ```
- `agent/context.py` — `build_context()` prepends the repo map to the system prompt. Full file contents are only included for files explicitly opened by the PM.
- Fallback: if tree-sitter not installed, use simple regex-based outline extraction.

### 3. Auto-Commit on Tool Use — Aider

**What:** In non-review mode, every successful file write or exec command is auto-committed to git with the agent's description as the commit message. This gives free undo history without the full review layer.

**From Aider:** Aider auto-commits after every change with sensible messages. Users can diff, manage, and undo AI changes with familiar git tools.

**Spec changes:**
- `agent/tools.py` — After `write_file` or `exec` tools succeed, call `git_ops.commit(project_path, f"{agent_name}: {description}")` if `auto_commit` is enabled.
- `agent/runtime.py` — `RuntimeConfig` gains `auto_commit: bool = True`.
- Uses existing `utils/git_ops.py` (shared with review-layer-simple). If project is not a git repo, auto-commit is silently skipped.
- Commit messages are generated from the tool call arguments (e.g., `Coder: write_file src/main.py — add error handling to on_send()`).

### 4. MCP Tool Extensibility — Goose

**What:** Tools are defined as MCP (Model Context Protocol) servers instead of hardcoded Python functions. New tools = new MCP servers, no code changes to CrabCakes. Each special agent gets its own set of MCP tool servers.

**From Goose:** Goose connects to 70+ extensions via MCP. Tools are plug-and-play — anyone can add new capabilities without modifying the agent core.

**Spec changes (Phase 2+ — future):**
- `agent/tools.py` — Refactored to support two tool sources: built-in (Python functions) and MCP (external servers).
- `agent/mcp_client.py` — New module. MCP client that connects to tool servers, discovers their capabilities, and translates between MCP protocol and the agent's tool-calling format.
- `agent/special_agents.py` — `SpecialAgentDef` gains `mcp_servers: list[str]` field (paths to MCP server configs).
- Coder gets: `read_file`, `write_file`, `exec`, `web_search`, `grep` MCP servers.
- Debugger gets: `read_file`, `exec`, `grep` MCP servers (no `write_file`).
- Built-in Python tools remain as fallback when MCP servers aren't configured.

**MCP Standard Compatibility:**

MCP (Model Context Protocol) is an open standard created by Anthropic and now governed by the Linux Foundation's Agentic AI Foundation (AAIF) — the same foundation that hosts Goose. Because MCP is a standard (not a proprietary API), CrabCakes' MCP client implementation will be **fully compatible with the entire Goose extension ecosystem** — 3,000+ MCP servers available from day one.

**What this means in practice:**
- Any MCP server listed in Goose's extension marketplace works with CrabCakes without modification
- Users configure MCP servers the same way: a JSON config pointing to the server's command/URL
- Community-built MCP tools (Jira integration, database querying, browser automation, etc.) are immediately available
- CrabCakes doesn't need to build its own tool ecosystem — it inherits one

**Goose extension compatibility checklist:**
- `agent/mcp_client.py` implements the standard MCP client protocol (JSON-RPC over stdio/SSE)
- Tool discovery via `tools/list` endpoint — matches Goose's discovery mechanism
- Tool invocation via `tools/call` — standard MCP method
- Server configuration format matches Goose's `~/.config/goose/config.yaml` structure for easy migration
- CrabCakes can read Goose's MCP server configs directly, so existing Goose users have zero migration cost

**Note:** This is a future enhancement. Phase 1 ships with built-in Python tools only. MCP is the migration path to ecosystem compatibility.

### 5. Lint-After-Write Feedback Loop — Aider

**What:** After any file write, automatically run the project's linter. If errors are found, feed them back to the agent for self-correction in the next tool loop iteration.

**From Aider:** Aider runs linters and tests after every change. If the linter catches errors (missing imports, syntax issues), the agent fixes them immediately — dramatically improving output quality.

**Spec changes:**
- `agent/tools.py` — `write_file` tool gains optional `lint_on_write: bool = True` config.
- After writing a file, if `lint_on_write` is enabled:
  1. Detect project type (Python → `ruff`/`pylint`, JS/TS → `eslint`, etc.)
  2. Run linter on the written file via `exec_command`
  3. If lint errors found, inject them as an automatic observation in the tool loop: `"Lint errors in {file_path}: {errors}"`
  4. Agent sees the errors and can self-correct in the next step
- `agent/runtime.py` — `RuntimeConfig` gains `lint_on_write: bool = True`.
- If no linter is detected for the project type, silently skipped.

### 6. Template-Based System Prompts — mini-swe-agent

**What:** System prompts are Jinja2 templates with variables injected from the environment (project path, repo map, file list, agent config). Makes agent customization declarative instead of requiring code changes.

**From mini-swe-agent:** System and instance templates use Jinja2 with `StrictUndefined`. Variables come from the environment, model, and agent config. Changing behavior = editing a template string.

**Spec changes:**
- `agent/special_agents.py` — `SpecialAgentDef.system_prompt` becomes a Jinja2 template string instead of a plain string.
- Available template variables: `{{ project_path }}`, `{{ repo_map }}`, `{{ file_list }}`, `{{ n_model_calls }}`, `{{ model_cost }}`, `{{ agent_name }}`, `{{ available_tools }}`.
- `agent/context.py` — `build_system_prompt()` renders the template with resolved variables.
- Example:
  ```python
  system_template = """You are {{ agent_name }}, a coding agent.
  Project: {{ project_path }}
  {% if repo_map %}
  Codebase structure:
  {{ repo_map }}
  {% endif %}
  Available tools: {{ available_tools }}
  """
  ```

### 7. Conversation Export — OpenHands

**What:** Export a conversation as a JSON file or shareable link. Useful for PM → developer handoffs, debugging, and documentation.

**From OpenHands:** OpenHands Cloud supports conversation sharing with RBAC. Export enables collaboration and review outside the app.

**Spec changes (low priority, future):**
- `models/conversation.py` — `Conversation` gains `to_json() -> str` and `from_json(data: str) -> Conversation` methods.
- `ui/handlers/agent_runtime_handler.py` — Right-click on agent tab → "Export Conversation" → saves JSON file via `Gtk.FileDialog`.
- Export includes: all messages, tool calls and results, token/cost stats, timestamps, agent config.
- Import: File → Open → load exported conversation into a new tab (read-only replay).

---

## Feature Priority

| # | Feature | Priority | Phase | Effort |
|---|---------|----------|-------|--------|
| 1 | Cost & token tracking with limits | High | Phase 1 | Small |
| 2 | Repo map context builder | High | Phase 1 | Medium |
| 3 | Auto-commit on tool use | High | Phase 1 | Small |
| 4 | Lint-after-write feedback | Medium | Phase 1 | Small |
| 5 | Template-based system prompts | Medium | Phase 1 | Small |
| 6 | MCP tool extensibility | Low | Phase 2+ | Large |
| 7 | Conversation export | Low | Future | Medium |

---

## What This Doesn't Do (Honestly)

| Feature | Why not |
|---------|---------|
| Multi-surface access (Telegram + CrabCakes) | Gateway agents support this. Special agents are CrabCakes-only. |
| Cross-agent messaging | Agents don't talk to each other directly. PM coordinates via project tabs. Future: agent-to-agent messaging within the runtime. |
| Persistent agent memory (MEMORY.md) | Conversations are saved, but there's no MEMORY.md-style long-term memory. Future: extract key decisions from conversations into a project-level memory file. |
| Agent sandboxing (OS-level isolation) | Agents run with the same permissions as CrabCakes. No chroot, no containers, no separate user accounts. The tool sandbox (path restriction + exec blocklist) is the safety layer. |
| Multiple LLM providers simultaneously | One provider per conversation. You can have different agents using different providers, but each conversation uses one model. |
| Built-in code execution (Jupyter-style) | Agents run shell commands, not code directly. If you want a Python REPL, the agent calls `exec_command("python3 -c '...'")`. |

---

## Relationship to Existing Code

| Existing Module | What Happens |
|----------------|-------------|
| `gateway/client.py` | **Unchanged.** Still used in gateway mode. |
| `ui/handlers/gateway_handler.py` | **Unchanged.** Still used in gateway mode. |
| `ui/handlers/chat_handler.py` | **Minor modification.** `on_send()` gets a mode branch. |
| `ui/views/chat_bubble.py` | **No changes.** Reused for agent messages and tool cards. |
| `ui/handlers/chat_render_handler.py` | **No changes.** Reused for streaming and rendering. |
| `ui/handlers/activity_handler.py` | **No changes.** Reused for status bar states. |
| `ui/views/main_content.py` | **No changes.** Reused for chat tabs. |
| `ui/views/left_panel.py` | **Minor modification.** Adds Crabcake Special Agents section below Connected Agents. |
| `ui/toolbar.py` | **No changes.** Connect button still works as before. |.
| `utils/improve.py` | **No changes.** MiniMax improve is independent. Could be migrated to use the agent runtime in the future, but no need now. |
| `utils/syntax_highlight.py` | **No changes.** Reused for tool output rendering. |
| `utils/projects.py` | **No changes.** Reused for project listing. |
| `utils/git_ops.py` | **New.** Created as part of review-layer-simple. Shared by review handler and agent tools. |
