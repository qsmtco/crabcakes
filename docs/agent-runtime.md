# Agent Runtime — Specification (v0.4)

**Last updated:** 2026-04-21
**Changelog:**
- v0.1 → v0.2 — Added Crabcake Special Agents, dual-section Agents tab, Coder + Debugger definitions.
- v0.2 → v0.3 — Architecture audit fixes. 8 issues resolved: gateway guard blocking special agents, config path duplication, conv_id/session_key ambiguity, missing handler injection spec, ARCHITECTURE.md gaps, layer dependency, models purity.
- v0.3 → v0.4 — Qrusher review: cut speculative MCP section; exec_command now requires PM approval (not a silent tool); added LeftPanel.set_special_agents() wiring spec; ChatHandler routing change flagged as breaking; chmod enforcement added at startup; tool loop split into 1.3a (blocking) and 1.3b (streaming); dependency graph added; Phase 1 scoped to cost tracking + auto-commit only.
**Status:** Not implemented — ready for build
**Depends on:** Existing CrabCakes architecture (`docs/ARCHITECTURE.md`)
**New dependencies:** `httpx` (async HTTP client for LLM API calls), `gitpython` (shared with review-layer-simple)

---

## Overview

CrabCakes includes a built-in agent runtime that allows it to function as a standalone project development environment. Each agent tab runs an independent conversation loop with an LLM that has access to local tools (read files, write files, run commands with approval, search the web). The human acts as project manager — assigning tasks, reviewing work, accepting or rejecting changes.

**Key design:** CrabCakes is not a gateway client. It is the runtime. Each agent is a system prompt + a working directory + a tool loop. No WebSocket, no device auth, no external daemon.

**Why this instead of the OpenClaw gateway:** The gateway is designed for general-purpose agent assistance across multiple surfaces. CrabCakes is a project development environment where the human manages agents writing code. That use case benefits from owning the entire stack — direct file access, direct tool execution, no permission negotiation.

**Relationship to existing gateway code:** The gateway code (`gateway/client.py`) remains in the codebase and works as before. Special agents run locally and gateway agents connect through the OpenClaw gateway. Both coexist simultaneously — no mode toggle needed. Both share the same UI.

---

## What We're Building

1. **The human is the PM.** They open projects, assign tasks to agents, review work, accept or reject changes.
2. **Crabcake Special Agents are always available.** Two built-in agents — Coder and Debugger — are present from first launch. No gateway connection required.
3. **Special agents are local.** Conversations go directly from CrabCakes to the LLM provider. They never touch the OpenClaw gateway.
4. **Gateway agents coexist.** When connected to a gateway, discovered agents appear in a separate section. Both sections are visible simultaneously.
5. **Agents work on project files.** They read, write, and execute commands in the project directory. The review layer gates their changes (`docs/review-layer-simple.md`).
6. **Everything is local for special agents.** LLM API calls go directly from CrabCakes to the provider.

---

## Dependency Graph

Shows what blocks what. No phase begins before its dependencies are complete.

```
Phase 1.1 ──► Phase 1.2 ──► Phase 1.3a ──► Phase 1.3b ──► Phase 1.4 ──► Phase 1.5
                  │               │              │
                  │               │              └── Requires: Phase 1.3a
                  │               └── Phase 1.4 wiring needs runtime (1.3a+)
                  └── Context builder needs models (1.1)

Independent of all phases:
  • models/conversation.py (1.1 dependency only — no other deps)
  • agent/config.py (1.1 dependency only — reads config, no other deps)
  • agent/tools.py (1.1 dependency only — pure tool execution, no LLM)
```

**What can ship independently:**
- `models/conversation.py` can be built and tested in isolation from everything else
- `agent/tools.py` can be tested against temp directories with no LLM dependency
- `agent/config.py` is a standalone config loader — no runtime dependency

---

## Architecture

### How It Fits Into CrabCakes

```
Gateway agents (when connected):
  UI handlers → gateway/client.py → OpenClaw gateway → LLM provider

Crabcake Special Agents (always available):
  UI handlers → agent/runtime.py → LLM provider (direct)
```

Both paths share the same UI: same chat tabs, same streaming, same tool cards, same review layer.

### New Packages and Modules

| Module | Package | Responsibility |
|--------|---------|---------------|
| `agent/__init__.py` | `agent/` | Exports: AgentRuntime |
| `agent/special_agents.py` | `agent/` | Special agent definitions — Coder, Debugger |
| `agent/runtime.py` | `agent/` | AgentRuntime — tool loop, conversation management, LLM API calls |
| `agent/tools.py` | `agent/` | Tool definitions and execution |
| `agent/config.py` | `agent/` | LLM provider configuration |
| `agent/context.py` | `agent/` | System prompt + file context builder |
| `models/conversation.py` | `models/` | Conversation and Message dataclasses |
| `ui/handlers/agent_runtime_handler.py` | `ui/handlers/` | Bridge between UI and AgentRuntime |

### Layer Dependency Rules

```
gateway/           → no ui/ imports (unchanged)
agent/             → no ui/ imports (new rule, same pattern as gateway/)
agent/             → may import utils/ (config paths via utils/config.py)
models/            → no ui/ imports, no agent/ imports, no gateway/ imports (unchanged)
ui/handlers/       → imports agent/, models/ (new)
ui/views/          → no agent/ imports (views receive data, not runtime references)
utils/             → no ui/ imports, no agent/ imports (unchanged)
```

### Directory Impact

```
crabcakes/
├── agent/                          # NEW PACKAGE
│   ├── __init__.py                # Exports: AgentRuntime
│   ├── runtime.py                # AgentRuntime — tool loop + LLM API
│   ├── tools.py                  # Tool definitions + execution
│   ├── config.py                 # LLM provider config
│   ├── context.py                # System prompt + file context
│   └── special_agents.py         # Coder + Debugger definitions
│
├── models/
│   └── conversation.py           # NEW — Conversation, Message, ToolCall dataclasses
│
├── ui/handlers/
│   └── agent_runtime_handler.py  # NEW — bridge between UI and runtime
│
└── gateway/  (EXISTING — unchanged)
```

---

## Crabcake Special Agents

### What Makes Them Special

- **Always present** — cards appear in the Agents tab immediately on launch
- **Always local** — conversations go directly to the LLM provider, never through the gateway
- **Predefined roles** — each has a purpose-built system prompt and tool set
- **Persistent state** — conversation history saved to disk and restored on restart
- **Project-aware** — when a project tab is open, special agents automatically operate on that project

### Agent Definitions

#### 🛠️ Coder

**Role:** Implements features, refactors code, writes tests, builds infrastructure.

| Property | Value |
|----------|-------|
| Display name | Coder |
| Avatar | 🛠️ (colored circle with emoji) |
| Color | `#6366f1` (indigo — first from AGENT_COLORS) |
| Session key | `special:coder` |
| Default model | From config `default_model` |

**Tools:** read_file, write_file, exec_command **(PM approval required)**, list_files, search_files, web_search, web_fetch

#### 🐛 Debugger

**Role:** Diagnoses bugs, traces errors, analyzes logs. Investigates and reports — does not write files by default.

| Property | Value |
|----------|-------|
| Display name | Debugger |
| Avatar | 🐛 (colored circle with emoji) |
| Color | `#f43f5e` (rose — third from AGENT_COLORS) |
| Session key | `special:debugger` |
| Default model | From config `default_model` |

**Tools:** read_file, exec_command **(PM approval required)**, list_files, search_files, web_search, web_fetch

Note: Debugger does not get write_file by default. If the PM wants the Debugger to also fix issues, write_file can be enabled per-conversation via a toggle in the agent's chat tab.

### Agent Registry

Special agents are defined in code, not in config files:

```python
# agent/special_agents.py

@dataclass
class SpecialAgentDef:
    conv_id_prefix: str           # e.g. "special:coder" — used as session_key
    display_name: str             # e.g. "Coder"
    emoji: str                    # e.g. "🛠️"
    color: str                    # hex color from AGENT_COLORS
    tools: list[str]              # tool names this agent can use
    can_write: bool               # whether write_file is in the default tool set

SPECIAL_AGENTS: dict[str, SpecialAgentDef] = {
    "special:coder": SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        emoji="🛠️",
        color="#6366f1",
        tools=["read_file", "write_file", "exec_command", "list_files", "search_files", "web_search", "web_fetch"],
        can_write=True,
    ),
    "special:debugger": SpecialAgentDef(
        conv_id_prefix="special:debugger",
        display_name="Debugger",
        emoji="🐛",
        color="#f43f5e",
        tools=["read_file", "exec_command", "list_files", "search_files", "web_search", "web_fetch"],
        can_write=False,
    ),
}

def get_special_agents() -> list[SpecialAgentDef]:
    """Return all special agent definitions, in display order."""
    return list(SPECIAL_AGENTS.values())

def get_special_agent(prefix: str) -> SpecialAgentDef | None:
    return SPECIAL_AGENTS.get(prefix)
```

**Adding a new special agent:** Create a new `SpecialAgentDef`, add it to the `SPECIAL_AGENTS` dict, and it automatically appears in the Agents tab on next launch.

### Agents Tab Layout

```
┌─────────────────────────────┐
│  AGENTS                     │
│                             │
│  Connected Agents           │  ← shown only when gateway connected
│  ┌───────────────────────┐  │
│  │ ● Qaster        [💬]  │  │
│  └───────────────────────┘  │
│                             │
│  Crabcake Special Agents    │  ← always shown
│  ┌───────────────────────┐  │
│  │ 🛠️ Coder        [💬]  │  │
│  │ 🐛 Debugger      [💬]  │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

**LeftPanel wiring (new method — required):**
```python
# ui/views/left_panel.py

def set_special_agents(self, agents: list[SpecialAgentDef]) -> None:
    """
    Inject the special agents list into the left panel.
    Called once from window.py during startup.

    Each agent renders as a row: emoji avatar + name + 💬 button.
    Clicking 💬 fires self._on_agent_selected(session_key, display_name).
    """
    self._special_agents = agents
    self._rebuild_agents_list()
```

The `_on_agent_selected` callback is already wired by the existing `set_agents()` pattern. Special agent rows go through the same callback — `window.py` uses the session key prefix to determine routing.

**GTK ListBox structure:**
- Two `Gtk.ListBoxRow` separators with section header labels
- Gateway agents section: populated by existing `AgentListHandler` (unchanged). Hidden when not connected.
- Special agents section: always visible. Populated from `SPECIAL_AGENTS` via `set_special_agents()`.

---

## Module Specifications

### `models/conversation.py`

**Responsibility:** Data classes for conversation state. Pure data — no GTK, no network, no LLM calls.

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
    call_id: str
    tool_name: str                  # e.g. "read_file", "exec_command"
    arguments: dict                 # parsed JSON arguments
    result: str | None = None
    status: ToolCallStatus = ToolCallStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None

@dataclass
class Message:
    role: MessageRole
    content: str                    # empty for tool call messages
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None # non-None only for tool result messages
    timestamp: datetime = field(default_factory=datetime.now)
    tokens_used: int = 0

@dataclass
class Conversation:
    agent_name: str
    project_path: str | None = None
    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    model: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    total_cost: float = 0.0        # cumulative USD cost
    step_count: int = 0            # number of agent turns

    def add_user_message(self, content: str) -> Message: ...
    def add_assistant_message(self, content: str, tool_calls: list[ToolCall] | None = None) -> Message: ...
    def add_tool_result(self, call_id: str, result: str) -> Message: ...
    def to_api_messages(self) -> list[dict]: ...
    def get_token_estimate(self) -> int: ...
    def trim_to_token_limit(self, max_tokens: int) -> None: ...
```

**Rules:**
- No imports from `ui/`, `agent/`, `gateway/`, `subprocess`
- `to_api_messages()` is the serialization layer for LLM API formats

---

### `agent/config.py`

**Responsibility:** LLM provider configuration. Reads from config file.

**Config path:** Uses `utils/config.get_config_dir()` for path resolution. Never hardcodes `~/.config/crabcakes/`.

**Startup security check:** On `load_agent_config()`, check that `agent.json` is not group/world-readable. If `stat` reports permissions > 600, log a warning to console. Do not block startup — just warn.

**Public API:**
```python
@dataclass
class LLMProviderConfig:
    name: str                       # e.g. "openai", "minimax"
    base_url: str
    api_key: str
    default_model: str
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128000

@dataclass
class AgentConfig:
    providers: dict[str, LLMProviderConfig]
    default_provider: str
    default_model: str
    max_tool_iterations: int = 50
    tool_timeout_seconds: int = 120
    auto_save_conversations: bool = True
    cost_limit: float | None = None   # per-conversation USD limit
    step_limit: int | None = None     # per-conversation turn limit

def load_agent_config() -> AgentConfig:
    """Load from <config_dir>/agent.json. Returns defaults for missing fields."""

def get_api_key(provider_name: str) -> str | None: ...
```

**Example `agent.json`:**
```json
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
    "tool_timeout_seconds": 120,
    "cost_limit": 5.00,
    "step_limit": 100
}
```

---

### `agent/tools.py`

**Responsibility:** Tool definitions and execution. Runs locally in the project directory.

**Public API:**
```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict                # JSON Schema
    requires_approval: bool = False  # if True, blocked until PM approves

@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    duration_ms: int = 0

def get_all_tools() -> list[ToolDefinition]: ...
def get_tool_definitions_for_api() -> list[dict]: ...  # OpenAI function-calling format
def execute_tool(name: str, arguments: dict, project_path: str) -> ToolResult: ...
def set_approval_callback(cb: Callable[[str, dict], bool]) -> None:
    """
    Register a callback that asks the PM for exec_command approval.
    The callback receives (session_key, {"command": "...", "cwd": "..."}).
    Returns True to allow, False to block.
    """
```

**Available tools:**

| Tool | Approval required | Description |
|------|------------------|-------------|
| `read_file` | No | Read file contents (max 50KB, binary → error) |
| `write_file` | No | Write content to file (sandboxed to project path) |
| `exec_command` | **Yes** | Run shell command (PM must approve each call) |
| `list_files` | No | List directory contents |
| `search_files` | No | Grep/ripgrep for pattern |
| `web_search` | No | Brave Search API |
| `web_fetch` | No | Fetch URL as text |

**File sandboxing:** All file paths resolved relative to `project_path`. If the resolved path escapes (`os.path.realpath(result)` outside `project_path`), the operation is rejected with an error result. This prevents reading `~/.ssh/id_rsa` or writing to `/etc/passwd`.

**Exec safety — PM approval required:**

`exec_command` is the highest-risk tool. It is **never silent**. Every exec call requires explicit PM approval via the registered callback:

```python
# When agent calls exec_command:
# 1. Render a tool card: 🔧 exec_command("pytest tests/") ⏳ [Awaiting approval]
# 2. Fire the approval callback to the UI
# 3. PM clicks Allow/Deny in the chat tab
# 4. If denied: return ToolResult(success=False, error="PM denied exec_command")
# 5. If allowed: execute, return result

# Hardcoded blocklist (always denied, even with approval):
# rm -rf /, mkfs, dd if=/dev/zero of=/dev/sda
# These are rejected before the approval callback fires.
```

This means the exec tool works — it's not disabled. But the PM sees every command before it runs and can deny destructive ones. The blocklist catches the catastrophic cases (dev/sda, etc.) that can't be undone.

**Output truncation:** File reads at 50KB, exec output at 100KB. Truncation is noted in the output.

**No GTK:** `tools.py` is pure Python. Imports `subprocess`, `os`, `pathlib` only.

---

### `agent/context.py`

**Responsibility:** Build the system prompt and file context for an LLM call.

**Public API:**
```python
def build_system_prompt(
    agent_name: str,
    project_path: str | None,
    tools: list[str],              # tools this agent has access to
    review_mode: str = "off",      # "off" | "review"
) -> str:
    """
    Build the system prompt for an agent.
    Includes: agent identity, project context, tool usage instructions,
    review mode awareness, output format guidelines.
    """

def build_file_context(project_path: str, query: str | None = None) -> str:
    """
    Build a file context block.

    Strategy:
    - With query: include files matching the query (by name)
    - Without query: directory tree + key files (README, ARCHITECTURE, package.json, etc.)
    - Respects .gitignore
    - Total context capped at ~50K chars

    Returns: formatted text block.
    """

def load_custom_system_prompt(project_path: str) -> str | None:
    """
    Load custom prompt from (in order):
    1. .crabcakes/agent-system-prompt.md
    2. AGENTS.md (project root)
    3. None
    """
```

---

### `agent/runtime.py`

**Responsibility:** The core agent loop. Manages conversations, calls LLM API, executes tools, streams responses.

**Public API:**
```python
class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        *,
        GLib=None,                                    # for GTK thread dispatch
        on_text_delta: Callable | None = None,         # (session_key, delta_text)
        on_tool_call_start: Callable | None = None,    # (session_key, tool_name, args)
        on_tool_call_result: Callable | None = None,   # (session_key, tool_name, result)
        on_tool_call_approval_needed: Callable | None = None,  # (session_key, tool_name, args) → PM approval
        on_response_complete: Callable | None = None,  # (session_key, full_text)
        on_error: Callable | None = None,             # (session_key, error_message)
        on_token_usage: Callable | None = None,        # (session_key, tokens, cost)
    ): ...

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def create_conversation(
        self,
        agent_name: str,
        session_key: str,              # stable ID — also used as tab session_key
        project_path: str | None = None,
        model: str | None = None,
    ) -> str: ...

    def send_message(self, session_key: str, text: str) -> None:
        """
        Send a user message. Runs the tool loop:

        1. Append user message to conversation
        2. Build API messages (system + history)
        3. Call LLM API
        4. If response has tool calls:
           a. For each tool:
              - If requires_approval: fire on_tool_call_approval_needed
              - If denied: return error result
              - Execute tool
           b. Append tool results
           c. Call LLM again
        5. If response is text only:
           a. Append assistant message
           b. Fire on_response_complete
           c. Check cost_limit / step_limit — stop if exceeded

        Safety:
        - Loop terminates after max_tool_iterations (default 50)
        - Each tool: timeout from config (default 120s)
        - On error/timeout: reported via on_error, loop stops
        """

    def cancel(self, session_key: str) -> None: ...
    def get_conversation(self, session_key: str) -> Conversation | None: ...
    def save_conversation(self, session_key: str) -> str: ...  # → file path
    def load_conversation(self, session_key: str) -> bool: ...
    def list_conversations(self) -> list[tuple[str, str]]: ...  # [(session_key, agent_name)]
```

**Provider support:**

| Model prefix | Provider | API |
|-------------|----------|-----|
| `openai/*` | OpenAI | Chat Completions |
| `minimax/*` | MiniMax | ChatCompletion v2 |
| `anthropic/*` | Anthropic | Messages API |

Provider selection by model string prefix. Each provider has a different tool calling format — `_normalize_tool_calls()` extracts tool calls into the internal `ToolCall` format regardless of source.

**Streaming (Phase 1.3b):** Uses SSE for providers that support it. Text deltas fire `on_text_delta` immediately. Tool calls are buffered until complete, then fire `on_tool_call_start`. If provider doesn't support streaming, the full response is delivered at once.

**Cost tracking:** After each LLM call, `on_token_usage(session_key, tokens, cost)` fires. Cost is computed from provider-specific pricing tables. The Conversation's `total_tokens` and `total_cost` are updated. If `cost_limit` is set and exceeded, the tool loop stops.

**Conversation persistence:** Saved to `<config_dir>/conversations/<session_key>.json`. Auto-saved after each `send_message()` completes (if `auto_save_conversations=True`). Loaded on startup to restore agent tabs.

---

### `ui/handlers/agent_runtime_handler.py`

**Responsibility:** Bridge between the CrabCakes UI and AgentRuntime. Creates conversations, routes messages, renders streamed responses in chat tabs. All GTK via `GLib.idle_add()`.

**Public API:**
```python
class AgentRuntimeHandler:
    def __init__(
        self,
        *,
        GLib,
        main_content,               # MainContent — for chat tabs
        chat_handler,               # ChatHandler — for rendering
        project_handler,            # ProjectHandler — for active project
    ): ...

    def start(self) -> None:
        """Load config, start AgentRuntime, load saved conversations."""

    def stop(self) -> None:
        """Save all conversations, stop runtime."""

    def is_running(self) -> bool: ...

    def create_agent_tab(self, agent_name: str, model: str | None = None) -> str:
        """Create conversation + chat tab. Returns session_key."""

    def send_message(self, session_key: str, text: str) -> None: ...

    def cancel(self, session_key: str) -> None: ...

    def approve_exec(self, session_key: str, tool_name: str, args: dict, approved: bool) -> None:
        """
        Called when PM clicks Allow/Deny on an exec_command approval request.
        If approved: re-execute the tool and continue the loop.
        If denied: return error result to the agent.
        """

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """Bind all special agent conversations to the project path."""

    def on_project_closed(self, project_name: str) -> None:
        """Unbind all special agent conversations from the project path."""

    def restore_conversations(self) -> None:
        """Load saved conversations and recreate their chat tabs. Called on startup."""
```

**Callback wiring:**
```python
self._runtime = AgentRuntime(
    config=self._config,
    GLib=GLib,
    on_text_delta=lambda sk, delta:
        GLib.idle_add(lambda: self._chat_handler.handle_streaming_delta(sk, delta)),
    on_tool_call_start=lambda sk, name, args:
        GLib.idle_add(lambda: self._render_tool_card(sk, "pending", name, args)),
    on_tool_call_result=lambda sk, name, result:
        GLib.idle_add(lambda: self._update_tool_card(sk, name, result)),
    on_tool_call_approval_needed=lambda sk, name, args:
        GLib.idle_add(lambda: self._request_exec_approval(sk, name, args)),
    on_response_complete=lambda sk, text:
        GLib.idle_add(lambda: self._chat_handler.handle_final(sk, text)),
    on_error=lambda sk, error:
        GLib.idle_add(lambda: self._chat_handler.handle_error(sk, error)),
    on_token_usage=lambda sk, tokens, cost:
        GLib.idle_add(lambda: self._update_token_display(sk, tokens, cost)),
)
```

**Exec approval UI flow:**
```python
def _request_exec_approval(self, session_key, tool_name, args):
    """Show an approval dialog/card in the chat tab for exec_command."""
    # Renders a tool card with [Allow] [Deny] buttons
    # PM clicks → self.approve_exec(session_key, tool_name, args, approved)
    pass
```

---

## Integration

### ChatHandler Modifications

**⚠️ BREAKING CHANGE — routing order matters**

`ChatHandler.on_send()` currently has a gateway connectivity guard as its first check. The special: routing branch MUST execute *before* that guard. If it doesn't, special agents are dead when no gateway is connected — defeating their entire purpose.

```python
# CURRENT (gateway guard blocks special agents when no gateway connected):
if self._gw is None or not self._gw.is_connected():
    return  # ← BLOCKS special: prefix when offline

# FIXED (special: routing before gateway guard):
if session_key.startswith("special:"):
    # Route to AgentRuntimeHandler — NO gateway needed
    self._show_and_send_special(session_key, text)
    return

# Gateway guard now only applies to non-special agents
if self._gw is None or not self._gw.is_connected():
    return
```

**New injection method (required):**
```python
# ui/handlers/chat_handler.py

def set_agent_runtime_handler(self, handler: AgentRuntimeHandler) -> None:
    """Inject AgentRuntimeHandler. Called by window.py during _build()."""
    self._agent_runtime_handler = handler
```

Follows the existing injection pattern (same as `set_project_handler()`, `set_command_handler()`, etc.).

**New internal method:**
```python
def _show_and_send_special(self, session_key: str, text: str) -> None:
    """Render user bubble and send to AgentRuntimeHandler."""
    ...
```

### window.py Wiring

```python
# In _build() — after other handlers:

self._agent_runtime_handler = AgentRuntimeHandler(
    GLib=GLib,
    main_content=self._main_content,
    chat_handler=self._chat_handler,
    project_handler=self._project_handler,
)
self._agent_runtime_handler.start()

# Inject into ChatHandler (after ChatHandler construction):
self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)

# Wire project lifecycle into runtime handler:
self._project_handler.set_on_project_opened(
    lambda name, path: self._agent_runtime_handler.on_project_opened(name, path)
)
self._project_handler.set_on_project_closed(
    lambda name: self._agent_runtime_handler.on_project_closed(name)
)
```

### LeftPanel — Special Agents Section

```python
# In window._build(), after LeftPanel construction:

from agent.special_agents import get_special_agents
self._left_panel.set_special_agents(get_special_agents())
```

`set_special_agents()` rebuilds the special agents section of the Agents tab ListBox. The section is always visible — gateway-connected or not.

---

## Data Flow

### App Startup

```
App starts
  → window._build()
    → AgentRuntimeHandler.start()
      → load_agent_config() — also checks agent.json permissions
      → AgentRuntime(config, callbacks=...)
      → runtime.start()
      → For each special agent in SPECIAL_AGENTS:
        → runtime.create_conversation(session_key=def.conv_id_prefix, ...)
        → Load saved conversation from disk (if exists)
    → Left panel: set_special_agents(get_special_agents())
      → Render Coder + Debugger rows — always visible
    → GatewayHandler (existing code, unchanged)
      → If auto-connect: connect to gateway → show Connected Agents section
```

### Special Agent Conversation

```
PM types message in Coder tab
  → ChatHandler.on_send()
    → session_key.startswith("special:") → AgentRuntimeHandler.send_message()
      → conversation.add_user_message(text)
      → build_system_prompt(Coder, project_path)
      → _call_llm(conversation) → HTTP POST to LLM provider

LLM responds with tool call: exec_command("pytest tests/")
  → on_tool_call_approval_needed → _request_exec_approval()
    → Renders tool card: 🔧 exec_command("pytest tests/") [Allow] [Deny]
  → PM clicks Allow
    → approve_exec(session_key, "exec_command", {"command": "pytest"}, True)
    → tools.execute_tool("exec_command", ...) → subprocess.run(...)
    → on_tool_call_result → update tool card: ✓ 12 passed

LLM responds with text: "Tests passing. Refactoring auth module..."
  → Streaming text → streaming bubble in chat tab
  → on_token_usage → update token footer: 1,247 tokens · $0.04
  → Final response → complete bubble
  → auto_save_conversation → saved to disk
```

---

## Phase Plan

Each phase is complete when: code is written, tests pass, ARCHITECTURE.md is updated.

### Phase 1.1 — Data Models + Tool Execution

**Goal:** `models/conversation.py` and `agent/tools.py` work standalone against temp directories.

**Steps:**
1. `models/conversation.py` — Conversation, Message, ToolCall, MessageRole, ToolCallStatus
2. `agent/__init__.py` — empty package
3. `agent/tools.py` — read_file, write_file, exec_command, list_files, search_files, web_search, web_fetch
4. `agent/config.py` — AgentConfig, LLMProviderConfig, load_agent_config() with chmod check
5. `tests/test_conversation.py` — all Conversation methods
6. `tests/test_tools.py` — sandbox escape, truncation, exec approval callback
7. Update `docs/ARCHITECTURE.md`

**Pass criteria:** `python3 -c "from agent.tools import execute_tool; print(execute_tool('read_file', {'path': '/etc/hostname'}, '/tmp').output[:50])"` — returns content or sandbox error. `python3 -c "from agent.tools import execute_tool; print(execute_tool('read_file', {'path': '/etc/shadow'}, '/tmp').success)"` — returns False.

### Phase 1.2 — Context Builder

**Goal:** System prompt and file context are assembled correctly.

**Steps:**
1. `agent/context.py` — build_system_prompt, build_file_context, load_custom_system_prompt
2. `tests/test_context.py`
3. Update ARCHITECTURE.md

**Pass criteria:** Given a real project directory, `build_system_prompt()` returns a string containing agent name, project path, and tool list. `build_file_context()` respects .gitignore and truncates at ~50K chars.

### Phase 1.3a — LLM API Runtime (Blocking)

**Goal:** Tool loop works end-to-end with a mock LLM. No streaming.

**Steps:**
1. `agent/runtime.py` — AgentRuntime with tool loop (blocking HTTP, no SSE)
2. Implement provider normalization (OpenAI format as reference, MiniMax second)
3. Implement conversation save/load (JSON to disk)
4. Implement cost tracking and limit enforcement
5. `tests/test_agent_runtime.py` — mock HTTP, verify loop behavior, cost limits
6. Update ARCHITECTURE.md

**Pass criteria:** A test sends "list the files in this project" → agent calls list_files tool → returns file listing → conversation saved to disk. A test exceeds cost_limit → loop stops → error reported.

### Phase 1.3b — Streaming

**Goal:** Responses stream in real-time via SSE.

**Steps:**
1. Add SSE parsing to `agent/runtime.py`
2. `on_text_delta` fires incrementally as chunks arrive
3. `on_tool_call_start` fires when complete tool call is received
4. Update tests to verify delta ordering
5. Update ARCHITECTURE.md

**Pass criteria:** A test with a mock SSE stream verifies `on_text_delta` is called N times with correct partial texts, and `on_response_complete` fires once with the full accumulated text.

### Phase 1.4 — UI Integration

**Goal:** Agent runtime is wired into CrabCakes UI. Agent tabs work.

**Steps:**
1. `ui/handlers/agent_runtime_handler.py`
2. Modify `chat_handler.py`:
   - Add `set_agent_runtime_handler()` injection method
   - Restructure `on_send()`: special: routing BEFORE gateway guard ⚠️
   - Add `_show_and_send_special()` method
3. Modify `window.py` — create and wire AgentRuntimeHandler
4. Modify `left_panel.py` — add `set_special_agents()` method and rebuild agents list
5. Update ARCHITECTURE.md

**Pass criteria:** Running CrabCakes. Special agents visible without gateway. Click Coder → chat tab opens → type message → agent responds with text and tool calls → streaming works → conversation saved. Gateway agents still work when connected. Both simultaneously.

### Phase 1.5 — Review Layer Integration

**Goal:** Agent writes are gated by review mode.

**Steps:**
1. Wire review mode into `agent/tools.py` — write_file checks review state
2. Review mode awareness in system prompt
3. End-to-end: agent writes → PM sees diff → accepts → committed
4. Update ARCHITECTURE.md

---

## Test Plan

### Pass/Fail Criteria Per Phase

**Phase 1.1:**
- [ ] `test_conversation.py` — 9 tests pass (add messages, serialization, token estimate, trim)
- [ ] `test_tools.py` — sandbox escape returns success=False, exec with approval callback fires callback

**Phase 1.2:**
- [ ] `test_context.py` — build_system_prompt includes agent name + tools, .gitignore respected, truncation at ~50K chars

**Phase 1.3a:**
- [ ] `test_agent_runtime.py` — tool loop: user message → tool call → tool result → text response
- [ ] Cost limit exceeded → loop stops with on_error
- [ ] Conversation saved to disk → loaded → identical state

**Phase 1.3b:**
- [ ] Streaming deltas arrive in order
- [ ] Tool call fires only after complete call is received

**Phase 1.4:**
- [ ] Manual: click Coder → chat tab → send message → response streams
- [ ] Manual: gateway disconnected → special agents still work
- [ ] Manual: gateway connected → special agents + gateway agents both work

**Phase 1.5:**
- [ ] Manual: agent writes file → diff card appears → Accept → committed
- [ ] Manual: agent writes file → Reject → files reverted

---

## Phase 1 Feature Subset

The full spec includes 7 features inspired by research. For Phase 1, only two are included:

| Feature | Included | Reason |
|---------|----------|--------|
| Cost & token tracking | ✅ Yes | Essential for controlling agent spend; small effort |
| Auto-commit on tool use | ✅ Yes | Gives free undo history; uses existing git_ops |
| Repo map context builder | ❌ Cut | Medium effort; defer to Phase 2 |
| Lint-after-write | ❌ Cut | Small effort but adds complexity; defer |
| Template-based prompts | ❌ Cut | Jinja2 dependency; defer |
| MCP extensibility | ❌ Cut | Entirely speculative; write `agent-mcp.md` separately |
| Conversation export | ❌ Cut | Low priority; defer indefinitely |

---

## What This Doesn't Do (Honestly)

| Feature | Why not |
|---------|---------|
| Multi-surface access | Gateway agents support this. Special agents are CrabCakes-only. |
| Cross-agent messaging | Agents don't talk to each other directly. PM coordinates via project tabs. |
| Persistent agent memory | Conversations are saved, but no MEMORY.md-style long-term memory extraction. |
| OS-level sandboxing | Agents run with the same permissions as CrabCakes. Tool sandbox (path restriction + exec approval) is the safety layer. |
| Built-in code execution | Agents run shell commands. Python REPL via `exec_command("python3 -c '...'")`. |
| MCP extensibility | Write `agent-mcp.md` when actually implementing. Not in Phase 1. |

---

## Relationship to Existing Code

| Module | What Happens |
|--------|-------------|
| `gateway/client.py` | **Unchanged.** |
| `ui/handlers/gateway_handler.py` | **Unchanged.** |
| `ui/handlers/chat_handler.py` | **Modified.** `on_send()` gets special: routing branch + `set_agent_runtime_handler()`. |
| `ui/views/chat_bubble.py` | **No changes.** Reused for agent messages and tool cards. |
| `ui/views/main_content.py` | **No changes.** |
| `ui/views/left_panel.py` | **Modified.** `set_special_agents()` added, dual-section ListBox. |
| `ui/toolbar.py` | **No changes.** |
| `utils/improve.py` | **No changes.** Independent. |
| `utils/git_ops.py` | **No changes.** Shared with review layer. |

---

## Phase 1.5 — Review Layer Integration (IMPLEMENTED)

### Design

**Pattern**: write_file in review mode → stage to shadow path instead of real path.

**Flow**:
1. `AgentRuntimeHandler._on_tool_call_result` intercepts `write_file` results
2. If review mode is active for the project, move staged file to real path (so agent sees the write)
3. On `on_response_complete`, `AgentRuntimeHandler` calls `ReviewHandler.check_changes(project_name)` which computes the diff vs the checkpoint
4. PM sees diff cards and chooses Accept/Reject

**Staging mechanism**: Shadow directory at `<project_path>/.crabcakes_review_staging/`:
- Files written by the agent land here during a review session
- Accept: `git add . && git commit`
- Reject: `rm -rf .crabcakes_review_staging/*` + restore working tree to checkpoint SHA

**Files modified**:
- `ui/handlers/agent_runtime_handler.py` — `_on_tool_call_result` intercepts write_file, calls review_handler.check_changes on response complete
- `agent/runtime.py` — `_on_tool_call_result` callback param added to AgentRuntime
- `agent/config.py` — `review_staging_dirname: ".crabcakes_review_staging"` added to AgentConfig

**Key invariants**:
- Agent always sees "wrote N bytes to path" immediately (optimistic — writes go to staging)
- ReviewHandler sees all changes because staging is inside the project git working tree
- PM's Accept does `git add -A` which picks up both staging files and any other changes
