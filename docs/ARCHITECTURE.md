# Crabcakes — Architecture Document

**Purpose:** This document is the authoritative reference for the Crabcakes codebase. It defines the structure, patterns, and principles that all contributors — human or agent — must follow. Before writing any code, read this document. When in doubt, consult this document.

**Project root:** `/home/q/projects/crabcakes`
**Project status:** See `docs/PROJECT_STATUS.md` for current progress, completed phases, and planned work.

---

## 0. Keeping This Document Current

**This document is the law — and like the law, it must be kept current.**

When you change code, you **must** update this document in the same commit. If you don't, it becomes a lie, and future contributors will trust it and make wrong decisions.

**What to update after any code change:**

| If you... | Then update... |
|-----------|--------------|
| Add/remove/rename a module | Section 2 (directory structure) and Section 11 (file inventory) |
| Change a class's public API or responsibilities | Section 3 (module responsibilities) |
| Add/remove a public function or method | Section 3 (public API blocks) |
| Change environment variables | Section 10 |
| Change gateway protocol handling | Section 11 (protocol reference) |
| Change how events flow through the app | Section 4 (data flow) |
| Change a pattern or convention | Sections 5–7 |
| Change environment variables | Section 10 |

**Rule:** If the diff of your code change doesn't have a corresponding update to this file, the change is **incomplete**.

**Exception:** Minor refactors where nothing documented externally changes (e.g., renaming internal variables, extracting private methods, inlining simple helper functions) do not require ARCHITECTURE.md updates.

---

## 1. Project Overview

Crabcakes is a GTK4 desktop application that connects to an OpenClaw gateway via WebSocket, enabling multi-agent chat management. It provides:

- A split-panel UI: left sidebar (Prompts/Agents/Projects notebook) + right main content (chat tabs + input)
- Prompt library: load `.md` files from the `prompts/` directory (system prompts in `prompts/system/`)
- Agent discovery: connect to gateway, discover agents, open chat tabs per agent
- Project browser: browse directories from `CRABCAKES_PROJECTS_DIR` via TreeView
- **Project group chat**: open a project → fan-out message to all project members → responses routed back to the project tab
- **Membership toggles**: +/− buttons in the Agents tab add/remove agents from the active project
- **Crabcake Special Agents**: local agent runtime — Coder and Debugger agents run directly against OpenAI/MiniMax/Anthropic APIs with file/exec tools, no gateway required
- **Review layer**: git-backed code review for agent writes — checkpoint → diff → accept/reject

**Technology stack:**
- Python 3, GTK4 (via PyGObject)
- WebSocket client (Python `websockets` library)
- Ed25519 device authentication (via `cryptography`)
- Threaded async I/O with GLib main thread dispatch

---

## 2. Directory Structure

```
crabcakes/
├── main.py                    # Entry point — creates CrabcakesApp, runs Gtk.main() (~56 lines)
│
├── gateway/                   # WebSocket client — self-contained, no UI dependencies
│   ├── __init__.py           # Exports: GatewayClient, SnapshotValidationError
│   └── client.py              # GatewayClient — threaded WebSocket + v3 device auth
│
├── models/                    # Data models — no UI dependencies
│   ├── __init__.py           # Exports: AgentManager, AgentRoutingTable, Command, CommandResult, CommandRegistry,
│   │                          # StreamingBubble, FeedCardData, ActivityBubble, ToolStatus, Conversation, Message,
│   │                          # MessageRole, ToolCall, ToolCallStatus, ConversationSnapshot, SnapshotMessage,
│   │                          # ReviewState, TeamMember, ProjectTeam, Task, TaskStore, TASK_STATUS_LABELS,
│   │                          # PRIORITY_LABELS, next_agent_color, reset_color_indices
│   │                          # Also creates: task_store = TaskStore() singleton
│   ├── agents.py              # AgentManager — session_key → name, colors, sessions
│   ├── activity.py            # ActivityBubble dataclass — activity bubble state for ActivityHandler
│   ├── colors.py              # Color palettes + round-robin assignment
│   ├── routing.py             # AgentRoutingTable — session_key → project_name routing
│   ├── command.py             # Command + CommandResult + CommandRegistry data models (Phase 7)
│   ├── conversation.py        # Conversation + Message + ToolCall + MessageRole dataclasses (Agent Runtime Phase 1.1)
│   ├── conversation_snapshot.py # ConversationSnapshot + SnapshotMessage — conversation snapshot data
│   ├── feed_card.py           # FeedCardData dataclass + css_class_for_type() (Phase 5)
│   ├── review_state.py        # ReviewState dataclass — per-project review session data (Phase 7)
│   ├── streaming.py           # StreamingBubble dataclass — streaming bubble state (Phase 5)
│   ├── task.py                # Task + TaskStore + status/priority labels (Phase 3)
│   └── team.py                # TeamMember + ProjectTeam — project team membership data
│
├── agent/                     # Local agent runtime — no UI dependencies
│   ├── __init__.py           # Exports: AgentRuntime, LLMProviderConfig, EnforcementConfig, AgentConfig,
│   │                          # load_agent_config, get_api_key, SpecialAgentDef, SPECIAL_AGENTS,
│   │                          # get_special_agents, reload_registry, ToolDefinition, ToolResult,
│   │                          # build_system_prompt, build_file_context, check
│   ├── kb_lookup.py          # KB lookup — cosine-sim retrieval over indexed KB chunks (Auxilium Tier 1)
│   ├── runtime.py           # AgentRuntime — tool loop, LLM API, streaming, cost tracking + enforcement hook
│   ├── tools.py              # Tool definitions + execution (read_file, write_file, edit_file, exec_command, etc.)
│   ├── config.py             # LLM provider config + EnforcementConfig dataclass
│   ├── context.py            # System prompt builder (via prompts/system/ templates) + file context builder + .gitignore parsing
│   ├── special_agents.py     # Coder + Debugger + Crabcakes agent definitions (auto_open, api_key_built_in, auto_add_to_projects fields)
│   └── enforcement.py        # Post-write verification: syntax guard, test runner, lint check (Phase 3)
│
├── ui/                        # All UI components
│   ├── __init__.py
│   ├── toolbar.py             # Toolbar widget — connect button + status label
│   ├── styles.py              # All CSS — single source of truth (APP_CSS + apply_styles)
│   ├── window.py              # MainWindow — assembles all components, wires callbacks
│   ├── handlers/              # Handler modules (extracted from window.py)
│   │   ├── __init__.py
│   │   ├── prompts_handler.py  # PromptsHandler — favorites, search, last-used
│   │   ├── agent_list_handler.py  # AgentListHandler — avatar cards data
│   │   ├── chat_handler.py    # ChatHandler — send, fan-out, routing
│   │   ├── chat_render_handler.py  # ChatRenderHandler — escape + markdown + bubble pipeline
│   │   ├── gateway_handler.py # GatewayHandler — connect, agents, lifecycle
│   │   ├── media_handler.py   # MediaHandler — STT + improve
│   │   ├── project_handler.py  # ProjectHandler — active project + agent-to-project routing
│   │   ├── activity_handler.py  # ActivityHandler — 6-state activity machine (Phase 6)
│   │   ├── command_handler.py   # CommandHandler — slash-prefix command parser (Phase 7)
│   │   ├── review_handler.py    # ReviewHandler — review session lifecycle (Phase 7)
│   │   ├── task_handler.py      # TaskHandler — task commands: task/done/start/blocked/cancel/tasks/assign/priority (Phase 7)
│   │   ├── collab_handler.py   # CollabHandler — collaboration commands: ask/delegate/stop/tell (Phase 7)
│   │   ├── agent_runtime_handler.py  # AgentRuntimeHandler — local agent UI bridge (Phase 1.4)
│   │   ├── project_list_handler.py  # ProjectListHandler — project card data + color round-robin
│   │   ├── crabwatch_handler.py  # ~364 lines — CrabWatchHandler — Gio.FileMonitor filesystem watcher (Phase 5)
│   │   ├── input_toolbar_handler.py # ~395 lines — InputToolbarHandler — find/replace, spell check, word count logic
│   │   ├── agent_builder_handler.py # ~199 lines — AgentBuilderHandler — agent create/edit form + delete_agent_with_confirmation() (Phase 5)
│   │   ├── agent_command_handler.py # AgentCommandHandler — agent response slash-command parser (Phase 6.2)
│   │   ├── feed_handler.py        # ~867 lines — FeedHandler — feed card lifecycle, persistence, review actions (Phase 5)
│   │   └── session_handler.py     # ~164 lines — SessionHandler — session switching commands (Phase 7)
│   │   ├── connection_sync_handler.py  # post-connect wiring (Phase 3a extraction)
│   │   ├── forward_handler.py     # 17 tests (Phase 3b extraction)
│   └── views/                 # View widgets
│       ├── __init__.py
│       ├── activity_drawer.py  # NEW (SPEC-activity-drawer) — collapsible activity event panel
│       ├── chat_bubble.py      # build_role_bubble() — chat bubble widget factories (Phase 1)
│       ├── feedbar.py          # FeedBar — Response Status Bar + progress bar + ActivityHandler public API (Phase 6)
│       ├── feed_card.py        # ~581 lines — feed_card widget factory (Phase 5)
│       ├── diff_card.py         # Diff card widget factories — build_file_diff_card, build_diff_summary_card (Phase 7)
│       ├── review_bar.py        # ReviewBar widget — review mode dropdown + action buttons (Phase 7)
│       ├── file_tree.py        # FileTree — Gtk.TreeView directory browser
│       ├── left_panel.py       # LeftPanel — PAP notebook (Prompts/Agents/Projects)
│       ├── left_progress.py    # Stub — progress indicator placeholder
│       ├── main_content.py     # MainContent — chat notebook + input + button bar
│       ├── session_menu.py     # Right-click session switcher popover
│       ├── chat_input_toolbar.py # ~549 lines — ChatInputToolbar — find/replace bar + spell check popover (view only)
│       ├── feed_tab.py          # ~167 lines — FeedTab — project feed card container (view only)
│       └── agent_builder.py     # AgentBuilderDialog — modal dialog for creating/editing agents
│
├── knowledge/                # User-facing documentation files (read by Crabcakes agent via web_fetch)
│   ├── setup.md              # Installation and first-run guide
│   ├── configuration.md      # Configuration options and agent.json
│   ├── agents.md             # How agents work (Coder, Debugger, Crabcakes, custom)
│   ├── features.md           # Feature overview and how-tos
│   ├── commands.md           # Slash command reference
│   ├── gateway.md            # OpenClaw gateway connection
│   └── troubleshooting.md    # Common problems and solutions
│
└── utils/                     # Pure Python utilities — no GTK, no network
    ├── __init__.py
    ├── agent_defs.py            # Agent definition I/O — load, validate, save, list user-defined agents from agents/*.yaml
    ├── audit_parser.py          # extract_audit_reports() — parse ## Audit Report sections into AuditReport dataclasses
    ├── block_parser.py          # extract_blocks() — split message text into typed segments (code, quote, terminal, heading, task)
    ├── config.py                # config path helpers — get_config_dir(), get_projects_dir(), get_gateway_url(), COMMAND_PREFIX
    ├── conversation_store.py    # Snapshot creation — build ConversationSnapshot from message lists and git diffs
    ├── crabcard_parser.py       # extract_crabcards() — parse ```crabcard blocks from agent chat into FeedCardData (Phase 5)
    ├── diff_parser.py           # parse_diff() — unified diff → FileDiff/ParsedDiff data (Phase 7)
    ├── escaping.py              # escape_for_pango(), xml_escape_text() — Pango-aware XML escape
    ├── favorites.py             # favorites persistence (favorites.json)
    ├── feed_store.py            # Feed JSON persistence — load/save/append/update to .crabcakes/feed.json (Phase 5)
    ├── feedback_processor.py    # Audit report file I/O — write structured audit reports to agent bug journals
    ├── git_ops.py               # GitPython wrapper — git add/commit/diff/checkout/log/status/push via GitResult (Phase 7)
    ├── icons.py                 # Gdk.Texture SVG rendering (agent avatars + folder icons)
    ├── image_utils.py           # convert_logo_to_icons() — JPG to multi-size PNG conversion for app icons
    ├── improve.py               # improve_prompt() — MiniMax API for prompt improvement (template mode with {{USER_INPUT}} marker)
    ├── markdown.py              # format_markdown() — inline markdown → Pango Markup
    ├── mcp_client.py            # MCP client library — asyncio-to-threading bridge, stdio transport, connection pooling, tool discovery/call
    ├── mcp_config.py            # MCP server configuration loader — YAML/JSON deserialization with schema validation
    ├── project_awareness.py     # Project awareness system — manages .crabcakes/ directory per project (team, workflow, context)
    ├── prompt_loader.py         # System prompt template loader — loads/fills/composes prompts/system/*.md
    ├── prompts.py               # load_prompts() — reads .md from prompts/
    ├── projects.py              # load_projects(), scan_directory() — load project directories; load_members()/save_members() deprecated
    ├── quoting.py               # _parse_quoted_payload() — quoted-payload parsing with escape handling (A2A_QUOTED_PAYLOAD_SPEC)
    ├── review_log.py            # Review log persistence — append/retrieve review entries per project
    ├── spellcheck.py            # Spell check engine — Enchant-based misspelling detection and suggestion
    ├── stt.py                   # STTEngine — faster-whisper push-to-talk; respects STT_MODEL_SIZE env var (default tiny.en)
    ├── syntax_highlight.py      # highlight() — Pygments → Pango markup (Tokyo Night color scheme)
    └── workflow_state.py        # Workflow state tracker — manages .crabcakes/workflow.md per project
```

**Top-level packages and their rules:**

| Package | Responsibility | Dependencies |
|---------|---------------|--------------|
| `gateway/` | Network I/O, auth, event dispatch | `cryptography`, `websockets`, `gi.repository.GLib` |
| `models/` | Data structures, state management | None (pure Python) |
| `ui/` | GTK widgets, layout, user interaction | GTK4 only |
| `utils/` | File I/O for prompts, projects, membership | None |

**Critical rule:** `gateway/` and `models/` must NEVER import from `ui/`. They are the foundation that the UI depends on — not the other way around.

---

## 3. Module Responsibilities

### 3.1 `main.py` — Application Entry Point

**Responsibility:** Bootstrap the GTK application.

```python
class CrabcakesApp(Gtk.Application):
    def on_activate(self, app):
        win = MainWindow(application=app)
        win.present()
```

**Rules:**
- Must be thin. Only creates the application and the main window.
- All business logic lives in other modules.
- Never contains widget definitions.

### 3.2 `gateway/` — Network Layer

**Responsibility:** Handle all WebSocket communication with the OpenClaw gateway.

The `gateway/` package is the **only** place that knows about:
- WebSocket URLs (`ws://localhost:18789`)
- Device identity files (`~/.openclaw/identity/`)
- v3 device-auth handshake

**Key classes:**

| Class | File | Responsibility |
|-------|------|---------------|
| `GatewayClient` | `client.py` | Threaded WebSocket with reconnect, auth, message sending |

**Public API:**
```python
from gateway import GatewayClient

client = GatewayClient(
    url="ws://localhost:18789",
    on_connect=callback_fn,        # called when connected
    on_error=error_fn,            # called on connection error
    on_event=event_fn,            # called on gateway event (event_name, payload)
)
client.start()              # begins connecting in background thread
client.stop()               # disconnects
client.is_connected()       # True if connected
client.get_snapshot()       # returns hello-ok snapshot dict
client.send_message(session_key, text, on_sent=cb)
```



### 3.3 `models/` — Data Layer

**Responsibility:** Hold all application state and data structures. No UI code.

**Key classes:**

| Class | File | Responsibility |
|-------|------|---------------|
| `AgentManager` | `agents.py` | Tracks session_key → name, colors, sessions |
| `AgentRoutingTable` | `routing.py` | Maps session_key → project_name; shared between ProjectHandler and ChatHandler |
| `Command`, `CommandResult` | `command.py` | Parsed command input + result of command processing |
| `CommandRegistry` | `command.py` | Maps command names to handlers; extensible |
| `StreamingBubble` | `streaming.py` | Dataclass for streaming bubble state (Phase 5) |
| `FeedCardData` | `feed_card.py` | Dataclass for Project Feed cards (Phase 5) |
| `ActivityBubble` | `activity.py` | Dataclass for activity event state; `to_drawer_row()` builds the dict the ActivityDrawer consumes (SPEC-activity-drawer) |
| `Task`, `TaskStore` | `task.py` | Task data model + in-memory store (Phase 3) |
| `ReviewState` | `review_state.py` | Per-project review session data (Phase 7) |

### 3.3a `models/routing.py` — Agent Routing Table

**Responsibility:** Maps agent session keys to their active project name. Shared between
ProjectHandler (writes) and ChatHandler (reads). Replaces a raw shared dict with explicit
methods and a clear contract.

**Public API:**
```python
class AgentRoutingTable:
    def add(session_key, project_name) -> None
    def remove(session_key) -> None
    def remove_project(project_name) -> None
    def get_project(session_key) -> str | None
    def is_routed(session_key) -> bool
    def clear() -> None
```

**Rules:** Pure data container. No GTK, no network, no callbacks.

**Color system (`colors.py`):**
- `AGENT_COLORS` — round-robin palette for agents
- `next_agent_color()` — returns next color, advances counter
- `reset_color_indices()` — resets counters on reconnect

**Rules:**
- Models know nothing about GTK widgets.
- Models do not emit signals or have callbacks — they're plain data containers.
- UI code reads from models and responds to changes via callbacks.

### 3.3b `models/agents.py` — Agent Manager

**Public API:**
```python
class AgentManager:
    def register(session_key, agent_name) -> None    # register new agent session
    def get_name(session_key) -> str                  # get display name for session key
    def get_names_ref() -> dict[str, str]             # {session_key → name} for UI panels
    def get_sessions(agent_name) -> list[str]         # all session keys for an agent name
    def get_color(agent_name) -> str | None           # hex color for agent name
    def clear() -> None                              # clear all sessions (preserves colors)
```

### 3.3c `models/command.py` — Command Data Models

**Public API:**
```python
@dataclass Command:
    name, args, flags, raw_text, body, source_session_key, target_session_key
    is_broadcast, broadcast_targets

@dataclass CommandResult:
    handled, response_text, response_card, forward_to, forward_text, broadcast_targets

class CommandRegistry:
    def register(name, handler, aliases=None, help_text="") -> None
    def get(name) -> Callable | None
    def list_commands() -> list[str]
    def list_aliases() -> dict[str, str]
    def get_help(name) -> str | None
```

### 3.3d `models/task.py` — Task Data Model

**Public API:**
```python
@dataclass Task: id, title, description, assigned_to, created_by, status, priority,
                created_at, updated_at, blocked_reason

class TaskStore:
    def generate_id() -> str          # sequential 8-char zero-padded ID
    def create(task) -> Task
    def get(task_id) -> Task | None
    def update(task) -> Task
    def list_all() -> list[Task]
    def list_by_agent(session_key) -> list[Task]
    def delete(task_id) -> bool
```

### 3.3e `models/review_state.py` — Review State

```python
@dataclass ReviewState:
    project_path: str
    review_mode: str        # "off" | "review"
    checkpoint_sha: str | None
    is_dirty: bool
    last_check_files: list[str]

    def is_active() -> bool      # checkpoint exists and not resolved
    def can_checkpoint() -> bool   # review mode on, no active session
```

### 3.4 `ui/toolbar.py` — Top Bar

**Responsibility:** App-level actions bar (Stream toggle, Settings button, status label, Connect button).

**Layout:** `[Stream | ⚙ Settings]  ←—expanding spacer—→  [status label | Connect]`

**Public API:**
```python
toolbar = Toolbar(on_connect_clicked=callback_fn, on_settings_clicked=callback_fn)
toolbar.update_connection_state("disconnected" | "connecting" | "connected" | "offline")
toolbar.set_settings_status(has_verified_provider: bool)  # shows/hides the red dot on ⚙ Settings
```

**Internal state:** Owns the Stream toggle, Settings button (wrapped in a `Gtk.Overlay` with a status dot), status label, and Connect button. Updates them based on calls to `update_connection_state()` and `set_settings_status()`.

### 3.5 `ui/styles.py` — Global CSS (~1045 lines)

**Responsibility:** Single source of truth for all application CSS.

**Owns:** `APP_CSS` constant (all CSS rules) and `apply_styles()` function (registers CSS provider globally).

**Public API:**
```python
from ui.styles import APP_CSS, apply_styles

apply_styles()  # Call once at startup, before any windows are created
```

**Rules:**
- No other file may call `Gtk.CssProvider().load_from_data()` or define CSS inline.
- Views use `widget.add_css_class("name")` only — they never define what classes look like.
- See Section 9 for full CSS conventions.

### 3.6 `ui/window.py` — Main Window

**Responsibility:** Assemble all UI components and wire all callbacks. The **single place** where all modules are connected.

**Project group chat state:**
```python
self._active_project_name = None   # set when a project tab is opened
self._agent_to_project = AgentRoutingTable()  # shared with ProjectHandler (writes), ChatHandler (reads), and ActivityHandler (via set_agent_routing())
```

**Phase 4 (MediaHandler) wiring:** `_media_handler` created and wired in `_build()`:
- `on_stt_click` → `_media_handler.on_stt_click`
- `on_improve_click` → `_media_handler.on_improve_click`
- STT transcript append → `_chat_handler.on_send()` via sync callback

**Rules:**
- Window creates all sub-components and passes callbacks to each.
- Window holds references to gateway client and agent manager.
- Window creates and wires handler instances (ChatHandler, etc.) — see `ui/handlers/`.
- Window defines callback handlers not yet extracted (major business logic extracted to handlers per SPEC-window-business-logic-extraction.md).
- Window does NOT define GTK widgets directly — it composes sub-views.

**Phase 1 (ChatHandler) extracted:** `_on_send`, `_on_send_clicked`, `_switch_to_session_tab`, and chat.final routing are now in `ui/handlers/chat_handler.py`.
**Phase 5 extracted:** `_on_audit_report_card` (FeedHandler.add_audit_report_card), `_on_agent_saved`/`_on_agent_deleted` (AgentRuntimeHandler.reload_agents_and_mcp), `_confirm_delete_agent` (AgentBuilderHandler.delete_agent_with_confirmation), `_register_stub_commands` (CommandHandler auto-registration).

### 3.7 `ui/views/left_panel.py` — Left Sidebar

**Responsibility:** Three-tab notebook: Prompts, Agents, Projects.

**Prompts tab:** PromptsHandler-backed list with search, favorites, and rich metadata rows. Star/favorite persisted to `~/.config/crabcakes/favorites.json`. Double-click or `+` button calls `on_prompt_loaded(filepath, name, content)`, which loads content into chat input. Search filters by name (case-insensitive). Favorites sort to top.

**Agents tab:** Initially empty placeholder. After `set_agents()` is called, builds avatar cards (colored circle + initials + name + +/− toggle button). Double-click calls `on_agent_selected(session_key, name)`. CSS for agent rows is scoped to `left_panel`. When a project is open, the toggle button is visible — `+` adds the agent to the project, `−` removes them. Toggle button uses `.agent-add-btn` (green) or `.agent-remove-btn` (red) CSS classes.

**Projects tab:** `FileTree` widget — `Gtk.TreeView` with `Gtk.TreeStore`, lazy-loading subdirectories, back button.

**Public API:**
```python
panel = LeftPanel(on_prompt_selected=cb, on_project_selected=cb)
panel.set_agents(agent_names_dict, on_agent_selected_callback)
panel.set_agent_list_handler(handler)         # wires AgentListHandler for avatar cards
panel.set_prompts_handler(handler)             # wires PromptsHandler for prompt library
panel.refresh_prompts()                       # rebuilds the prompts list
panel.set_on_project_opened(cb)               # fires when project tab opens
panel.refresh_agents_with_project(name)      # rebuilds agents list with +/− buttons
panel.set_toggle_agent_callback(cb)            # wires +/− toggle to ProjectHandler.toggle_agent()
```

### 3.8 `ui/views/file_tree.py` — FileTree Widget

**Responsibility:** Expandable directory browser with lazy-loading. Used by the Projects tab.

**Features:**
- `Gtk.TreeView` + `Gtk.TreeStore`
- Clicking expander icons expands/collapses directories; row-activated fires on double-click
- Double-click on a project directory calls `on_project_opened(name, path)`
- Subdirectory children are placeholder rows until first expand, then populated via `scan_directory()`

**Public API:**
```python
tree = FileTree(on_file_selected=cb)  # double-click file selection
tree.set_on_project_opened(cb)        # double-click on project row fires callback
```

### 3.9 `ui/views/main_content.py` — Main Content Area

**Responsibility:** Right panel — chat notebook + user input.

**Public API:**
```python
content = MainContent()
content.user_input              # property → Gtk.TextView
content.send_button             # property → Gtk.Button
content.notebook                # property → Gtk.Notebook (chat tabs)
content.create_chat_tab(session_key, agent_name)   # creates/returns to existing tab
content.get_chat_box(page_index=None)  # get the chat box for a tab (used by ChatHandler)
content.get_current_session_key()  # session_key of active tab, or None (used by ActivityHandler)
content.set_chat_render_handler(handler)  # inject ChatRenderHandler (called by window.py)
content.set_feed_bar_text(text)  # update the project feed bar
content.set_review_bar(bar)     # add/remove ReviewBar widget above chat (used by ReviewHandler)
content.get_review_bar()      # get current ReviewBar or None (Phase 7)
content.set_agent_manager(agent_mgr)  # set AgentManager for session switch lookup
content.close_tabs(page_indices)       # close multiple tabs, reindex once
content.set_on_stt_click(cb)     # STT button clicked
content.set_on_improve_click(cb) # Improve button clicked
content.replace_input_text(text) # replace input with improved text
content.append_stt_text(text)    # append STT partial transcript
content.update_stt_state(state) # "idle" | "recording" — button label/style
```

**Tab close:** Each tab has an × button (top-right of tab label) and responds to middle-click. Both call `_close_tab(page_idx)` which removes the page and re-indexes tracking dicts.

**Tab session switch:** Right-click → session switcher menu calls `_switch_tab_session(page_idx, new_session_key)`. This updates both `_tab_sessions[page_idx]` (the internal lookup dict) **and** `tab_label_box._session_key` (the GTK widget attribute). The widget attribute must stay in sync because `_find_page_by_session` reads it — a split-brain causes `_update_tab_dot` to miss the tab, breaking the unread dot indicator.

**Review bar integration (Phase 7):** ReviewHandler calls `set_review_bar(bar)` to insert a `ReviewBar` widget above the notebook, and `get_review_bar()` to retrieve the current bar for state updates without accessing MainContent internal state.

### 3.10 `utils/favorites.py` — Favorites Persistence

**Responsibility:** Read/write the favorites set for the prompt library.

**Public API:**
```python
load_favorites() -> set[str]        # may be empty set on error
save_favorites(set[str]) -> None
is_favorite(filepath) -> bool
toggle_favorite(filepath) -> bool   # True if now favorited
```

**Security:** No secrets. File I/O only — reads/writes favorites set to `~/.config/crabcakes/favorites.json`.

### 3.11 `utils/` — Utilities

**Responsibility:** File I/O helpers for prompts, projects, and project membership.

| Function | File | Responsibility |
|----------|------|---------------|
| `load_prompts()` | `prompts.py` | Returns `[(name, content), ...]` from `prompts/` |
| `load_projects()` | `projects.py` | Returns `[(name, full_path), ...]` from `CRABCAKES_PROJECTS_DIR` |
| `scan_directory(path)` | `projects.py` | Returns `[(name, full_path, is_dir), ...]` for one level, filtered (skips `__pycache__`, `.git`, etc.) |
| `load_members(project_name)` | `projects.py` | Returns `[{session_key}, ...]` from `~/.config/crabcakes/projects/<name>/members.json` |
| `save_members(project_name, members)` | `projects.py` | Writes members list to `members.json`, creates dir if needed |
| `improve_prompt(text, callback, GLib)` | `improve.py` | Loads template from `prompts/system/improve.md`, injects user text at `{{USER_INPUT}}` marker (or legacy split), sends to MiniMax API, calls `callback(improved, error)` with GLib dispatch |
| `load_prompt_template(name)` | `prompt_loader.py` | Load `prompts/system/<name>.md` template, return raw string or None |
| `fill_template(template, variables)` | `prompt_loader.py` | Replace `{{KEY}}` markers with values from dict |
| `compose_system_prompt(agent_name, ...)` | `prompt_loader.py` | Compose full system prompt from templates: (1) default.md, (1b) collab.md, (1c) crabcakes-context.md, (2) project-awareness.md, (3) crabcakes-commands.md, (4) project-onboarding.md, (5) code-review.md, (6) coder.md/debugger.md, (7) {role}-bugs.md/{role}-rules.md |
| `STTEngine` class | `stt.py` | Push-to-talk STT via faster-whisper — arecord → PCM buffer → faster-whisper (tiny.en model) → stop_async callback |
| `show_session_menu(parent, agent_name, sessions, on_select)` | `session_menu.py` | GTK popover menu listing sessions; clicking fires `on_select(session_key)` |

### 3.12 `ui/handlers/agent_list_handler.py` — Agent List Handler (Agent Cards)

**Responsibility:** Agent card rendering data — initials, colors, sorting. Does NOT build widgets (view does).

**Owns:** AgentManager reference (set after connect), color assignment per agent name, sorting/grouping logic.

**Public API:**
```python
def set_agent_mgr(agent_mgr): pass
def has_agent_mgr() -> bool: pass          # True if AgentManager is populated
def compute_initials(name: str) -> str: pass
def get_agent_color(name: str) -> str: pass
def get_sorted_agents(project_members=None) -> list[(sk, name, in_project)]: pass
def on_chat_clicked(session_key: str, name: str): pass
def on_toggle_clicked(session_key: str, name: str, in_project: bool): pass
```

### 3.13 `ui/handlers/prompts_handler.py` — Prompts Handler

**Responsibility:** Prompts tab data and logic — favorites, search, last-used tracking, prompt content loading. Does NOT build widgets (view does).

**Owns:** In-memory prompt list, favorites set, last-used timestamps, active search query.

**Public API:**
```python
def load_prompts() -> list[dict]:         # scan prompts/ dir, sort (favs first), apply filter
def toggle_favorite(filepath: str) -> bool:   # True if now favorited
def search(query: str) -> list[dict]:    # set filter + return filtered results
def record_usage(filepath: str):          # track last-used timestamp
def get_last_used_str(filepath: str) -> str:   # "just now", "5m ago", etc.
def get_prompt_content(filepath: str) -> tuple[str, str]:   # (name, content)
def on_prompt_activated(filepath: str):   # load + fire on_prompt_loaded callback
```

### 3.14 `ui/handlers/chat_handler.py` — Chat Handler (Phase 1)

**Responsibility:** All chat logic — sending, project fan-out, incoming message routing, tab switching. Extracted from `window.py` in Phase 1.

**Special agent routing:** In project fan-out (solo DM + group broadcast), special agents are detected via `AgentRuntimeHandler.get_special_agents()` and routed through `send_to_special_agent()` instead of `gw.send_message()`. Gateway agents receive awareness data via `_build_awareness_prefix()` (raw `build_awareness_block` — no identity injection).

**Key setters:** `set_gateway_client()`, `set_project_handler()`, `set_command_handler()`, `set_chat_render_handler()`, `set_agent_runtime_handler()`, `set_agent_manager()`, `set_on_forward_message()`, `set_on_send_initiated()`, `set_on_res_confirmed()`, `set_on_activity_bubble()`

**Bug fix (Phase 1 of SPEC-smarter-chat-ux) — missing message recovery:**

New state variables:
- `_assistant_text_buffer[session_key] → str`: last assistant text per session (populated by `_buffer_assistant_text()` callback from ActivityHandler)
- `_chat_final_rendered[session_key] → bool`: True when a final response has rendered — prevents double-render. Cleared on each new agent round via `_clear_render_guard()`.

New methods:
- `_buffer_assistant_text(session_key, text)`: callback target for ActivityHandler's `set_on_assistant_buffer()` — populates `_assistant_text_buffer`
- `_clear_render_guard(session_key)`: callback target for ActivityHandler's `set_on_agent_start()` — clears `_chat_final_rendered` so subsequent responses render. Receives RAW `session_key` from the gateway event (not resolved via `_active_session()`).
- `_handle_lifecycle_completed(session_key, text)`: fallback render path — called when ActivityHandler fires lifecycle end/error but no chat final has rendered; resolves project tab via `agent_to_project` routing table (same pattern as `on_chat_event`), then renders buffered assistant text via `_handle_final_response()` with resolved `target_tab` and original `session_key`. Guarded by `_chat_final_rendered`.
- `_render_activity_bubble(bubble)`: called by ActivityHandler via `set_on_activity_bubble()` — dispatches to `_render_activity_bubble_impl` on main thread. Activity bubbles are NOT guarded by `_chat_final_rendered`.
- `_render_activity_bubble_impl(session_key, text)`: thread-unsafe internal render — resolves project tab via `agent_to_project` routing table when no direct tab exists, then calls `render_sync(role="System", text=..., tight=True)`, appends to chat box, scrolls.

**Architecture:** ChatHandler owns all render decisions. ActivityHandler only tracks state. The lifecycle-completed callback is the fallback path when the gateway sends `stream=assistant` text but the corresponding `chat final` event carries no message body. The render guard is cleared when a new agent round starts (lifecycle phase=start) so that multiple responses per session work correctly. Activity bubbles are separate from the conversation message flow — they don't interact with `_chat_final_rendered`.

### 3.14a `utils/escaping.py` — Pango-Aware XML Escape

**Responsibility:** Escape XML/Pango specials while preserving known Pango markup tags.

**Public API:**
```python
from utils.escaping import escape_for_pango, xml_escape_text

# Escape specials, preserve known Pango tags (<b>, <i>, <span>, <a>, <br>, etc.)
# Unknown tags (<script>, <div>) are escaped — prevents Pango from silently
# rendering the ENTIRE message as empty when it encounters an unknown tag.
safe = escape_for_pango("<b>bold</b> and <script>x</script>")
# → "<b>bold</b> and &lt;script&gt;x&lt;/script&gt;"

# Simple XML entity escaping for plain text (no Pango markup)
xml_escape_text("Tom & Jerry")  # → "Tom &amp; Jerry"
```

**Key design:** Uses a Pango-known-tag whitelist (`_PANGO_KNOWN_TAGS`). Only tags in this set are preserved; everything else (HTML, `<script>`, `<div>`) is escaped. This prevents the critical bug where Pango renders unknown tags as invisible, making the entire message content disappear.

### 3.14b `utils/markdown.py` — Inline Markdown → Pango Markup

**Responsibility:** Convert inline markdown formatting to Pango Markup for use in `Gtk.Label.set_markup()`.

**Public API:**
```python
from utils.markdown import format_markdown

# Conversion rules:
#   **bold**   → <b>bold</b>
#   *italic*   → <i>italic</i>
#   `code`     → <tt>code</tt>   (underscores inside code are protected)
#   ~~strike~~ → <s>strike</s>
#   [text](url)→ <a href="url"><u>text</u></a>
#   bare URL   → clickable <a href="..."> link (trailing punctuation stripped)
result = format_markdown("use `my_var` for **bold** and *italic*")
```

**Important:** Handles ONLY inline formatting. Block-level elements (code blocks, blockquotes) are handled by `utils/block_parser.py` in Phase 2.

### 3.14c `ui/views/chat_bubble.py` — Chat Bubble Widget Factories

**Responsibility:** Create styled GTK bubble widgets for chat messages.

**Public API:**
```python
from ui.views.chat_bubble import build_role_bubble

# "You" bubbles are right-aligned, agent bubbles left-aligned.
# CSS classes: .chat-bubble-you / .chat-bubble-agent
widget = build_role_bubble("Agent", "<b>Hello</b> and **bold** text")
```

**Architecture:** A **view** — only creates widgets. No state, no callbacks, no logic.

### 3.14d `ui/handlers/chat_render_handler.py` — Chat Render Orchestrator

**Responsibility:** Owns bubble creation. Calls `build_role_bubble()` which owns the full text processing pipeline (extract_blocks → per-segment escape/markdown/highlight). Exposes `render_sync()` for synchronous use and `render()` for thread-safe async use.

**Public API:**
```python
from ui.handlers.chat_render_handler import ChatRenderHandler

handler = ChatRenderHandler(GLib_module=GLib)

# Async (thread-safe): dispatch work to main thread, call callback with bubble
# session_key enables reentrancy guarding — concurrent renders for the same
# session_key are skipped to prevent visual glitches.
handler.render(role, text, session_key, on_bubble_ready, on_error=None)

# Sync (main thread only): return bubble immediately
widget = handler.render_sync(role, text, session_key=None)

# Phase 4: special event card (file_read, edit_proposal, tool_call, error, thinking)
handler.render_event_card(event_type, container, **fields)
```

**Phase 4 — `render_event_card(event_type, container, **fields)`:**
Dispatches to the appropriate event card factory in `chat_bubble.py`. Thread-safe via `_dispatch()`. Unknown event types are silently ignored.

**Reentrancy guard (`_ReentrancySet`):** Tracks which session keys are currently being rendered. If a render is already in-flight for a key, subsequent calls with that same key are skipped.

**Processing pipeline:**
1. `escape_for_pango(text)` — protect existing Pango markup tags
2. `format_markdown(text)` — convert markdown → Pango inline markup
3. `build_role_bubble(role, text)` — create styled GTK bubble widget

### 3.14e `ui/views/chat_bubble.py` — Bubble Widget Factories (Phase 2–5)

**Responsibility:** Pure widget factories — create GTK bubble widgets for all message types. No state, no callbacks beyond widget signals.

**Phase 5 additions:**
- `build_role_bubble(role, text, on_forward_click=None, tight=False)`:
  - `on_forward_click`: optional callback; when set, agent bubbles get Copy+Forward buttons
  - `tight`: reduces margin_top from 4→1 for consecutive same-role messages (message grouping)
  - Action buttons row (Copy/Forward) only on agent bubbles — revealed via CSS hover (opacity 0 → 1)
  - Copy button: `_copy_to_clipboard(text)` copies full bubble text
  - Forward button: calls `on_forward_click()` if registered, else logs stub

**Message grouping:** Consecutive messages from same role+session get tight spacing (1px top margin instead of 4px). Tracked in `ChatRenderHandler._last_message_key`.

### 3.14f `ui/views/main_content.py` — Scroll-to-Bottom Button (Phase 5)

**Phase 5 addition:** Floating ↓ button bottom-right of chat overlay.

**New components:**
- `self._scroll_btn` — Gtk.Button, opacity 0 by default
- `self._scroll_btn_box` — positioned bottom-right via `Gtk.Align.END`

**Wired in `create_chat_tab()`:**
- Scroll button box added to each tab's `chat_overlay`
- Each tab's `vadjustment.value-changed` → `_on_vadjustment_changed()`
- Shows (opacity=1) when scrolled >80px from bottom; hides when near bottom

**Scroll handler (`_on_vadjustment_changed`):**
```python
distance_from_bottom = upper - page_size - value
self._scroll_btn.set_opacity(1 if distance_from_bottom > 80 else 0)
```

**Click handler (`_on_scroll_to_bottom_clicked`):**
```python
self.scroll_chat_to_bottom()
self._scroll_btn.set_opacity(0)
```

### 3.14g `utils/block_parser.py` — Block Segment Extractor (Phase 2)

**Responsibility:** Split raw message text into typed block segments. Pure function, no GTK, no network.

**Public API:**
```python
from utils.block_parser import extract_blocks

segments = extract_blocks("Hello\n\n```python\nx = 1\n```")
# [{'type': 'text', 'content': 'Hello'},
#  {'type': 'code', 'content': 'x = 1', 'lang': 'python'}]
```

**Segment types produced:**

| Type | Description | Key fields |
|------|-------------|------------|
| `text` | Plain paragraph | `content` |
| `code` | Fenced code block | `content`, `lang` |
| `quote` | `>` blockquote | `content` |
| `terminal` | `$` command lines | `content` |
| `heading` | `#` heading | `content`, `level` (1-4) |
| `task` | `- [ ]` / `- [x]` | `content` |

**Processing order:** Fenced code blocks are extracted first (since they can contain `$`, `#`, `>` chars). Remaining text is split on blank lines and classified.

### 3.14h `utils/syntax_highlight.py` — Pygments → Pango Highlighter (Phase 2)

**Responsibility:** Convert source code to Pango Markup with syntax colors. Degrades gracefully if Pygments unavailable.

**Public API:**
```python
from utils.syntax_highlight import highlight

markup = highlight("def foo(): pass", "python")
# '<span foreground="#c792ea">def</span> ...'
```

**Color scheme:** Tokyo Night dark theme (16 token color mappings). Falls back to `<tt>escaped</tt>` if Pygments unavailable or lexer unknown.

**Security:** All output is HTML-escaped before span wrapping. Safe for untrusted code content.

### 3.14i `ui/views/chat_bubble.py` — Block-Aware Bubble Factory (Phase 2+4)

**Responsibility:** Build styled GTK bubble widgets for any message content. Handles both inline (Phase 1) and block-level (Phase 2) rendering.

**Phase 1** (unchanged API):
- `build_role_bubble(role, text)` — creates bubble, routes text through extract_blocks internally
- Text segments → `format_markdown()` → bold/italic/code links

**New helper (Phase 5 — shared header factory):**

```python
def _make_block_header(
    label_text: str,
    content_for_copy: str,
    header_css: str,
    copy_btn_css: str = "code-copy-btn",
) -> tuple[Gtk.Box, Gtk.Button]:
    """
    Shared header bar factory for code/terminal block widgets.
    Returns (header_box, copy_btn) — copy_btn is pre-wired.
    """
```

Used by `_build_code_segment` and `_build_terminal_segment`. Eliminates copy-paste between block builders.

**Phase 5 — Project Solo DM (per-project direct message override):**

Right-clicking a project tab now shows a project-specific menu (All / member entries) instead of the generic session switcher. This allows routing messages to a single project member rather than broadcasting to all.

- `ProjectHandler._solo_targets: dict[str, str | None]` — maps project_name → solo target session_key, or None for group broadcast
- `ProjectHandler.get_solo_target(project_name) -> str | None`
- `ProjectHandler.set_solo_target(project_name, member_session_key | None)`
- `ChatHandler.on_send()` queries `get_solo_target()` before fan-out; if set, sends to only that member
- `MainContent._on_tab_right_click()` detects `session_key.startswith("project:")` and routes to `show_project_menu()` instead of `show_session_menu()`
- `session_menu.show_project_menu(parent, project_name, member_names, current_solo, on_select)` — builds the popover with checkmark on current selection

**Phase 4 additions** — Event card widget factories:
- `create_file_card(file_path, snippet, line_range)` → `.bubble-file-read` card (green border, 📄 icon)
- `create_edit_card(file_path, diff)` → `.bubble-edit-proposal` card (amber border, ✏️ icon)
- `create_tool_card(tool_name, detail)` → `.bubble-tool-call` card (slate border, 🔧 icon)
- `create_error_bubble(error_msg)` → `.bubble-error` bubble (red border + tint, ❌ icon)
- All user content is Pango-escaped via `escape_for_pango()`
- All content is `set_selectable(True)` for copy

**Architecture:** Each segment becomes a child widget inside a vertical `Gtk.Box`. The bubble's CSS class (`.chat-bubble-you` / `.chat-bubble-agent`) controls bubble background.


### 3.14j `ui/views/activity_drawer.py` — Activity Drawer (SPEC-activity-drawer)

**Responsibility:** Collapsible GTK panel below the chat that displays activity events (tool calls, plans, approvals, command output, patches, lifecycle separators) in a scrollable `Gtk.ListBox`. Pure view — no business logic, no gateway calls, no state mutations beyond its own widget tree.

**Owns:** Internal widget tree (header bar, list, filter state, per-agent counters, separator tracking, expanded revealers). All state is private to the drawer.

**Public API:**
```python
class ActivityDrawer(Gtk.Box):
    def __init__(self) -> None
    def append_event(self, row: dict) -> None     # row from ActivityBubble.to_drawer_row()
    def on_agent_start(self, session_key: str, agent_name: str) -> None
    def on_agent_end(self, session_key: str, agent_name: str) -> None
    def clear_events(self) -> None                  # remove all rows, reset state
    def toggle(self) -> None                       # programmatic expand/collapse
```

**Counter-collapse behavior:** Consecutive events with the same `(agent_name, activity_type)` are merged in place — count increments, duration sums. The first event of a new `(agent, type)` pair opens a new row.

**Filter semantics:** Two filter dropdowns (agent, type) with AND semantics. Empty set = all pass. Filter state lives in `self._visible_agents` and `self._visible_types`. Filter resets on `clear_events()`.

**Click-to-expand:** Rows with `output` set (command_output, tool_end, tool_error) get a `Gtk.Revealer` that toggles on row click, showing the last 10 lines.

**Lifecycle separators:** `on_agent_start` / `on_agent_end` insert marker rows that break the counter chain for the named agent and show per-agent stats on end.

**Thread safety:** `append_event`, `on_agent_start`, `on_agent_end`, `clear_events`, `toggle` must all be called on the GTK main thread. ActivityHandler already dispatches via `GLib.idle_add()` before firing callbacks.

**Architecture rules:**
- Lives in `ui/views/` — no imports from `gateway/`, `agent/`, `ui/handlers/`
- Receives data as flat dicts (see `models/activity.py:ActivityBubble.to_drawer_row()`)
- Pure view — no business logic, no state beyond the widget tree
- Connected to ActivityHandler via `set_on_activity_bubble` (adapter in `connection_sync_handler.sync()` converts `ActivityBubble` to dict via `to_drawer_row()`)


### 3.15 `ui/handlers/gateway_handler.py` — Gateway Handler (Phase 2)

**Responsibility:** All gateway lifecycle — connecting, disconnecting, agent discovery, error handling, and thread-safe state dispatch to GTK. Extracted from `window.py` in Phase 2.

**Owns:**
- `GatewayClient` instance (`_gw`)
- `AgentManager` instance (`_agent_mgr`)
- Sync callback (`_sync_callback`) — window uses this to sync `_gw` reference into `ChatHandler`

**Key invariant:** All GTK calls go through `GLib.idle_add()`. Gateway callbacks fire from the gateway's background thread; GTK is not thread-safe.

**Public API:**
```python
def connect() -> None:
    """Create GatewayClient, start it, set connection state to 'connecting'."""

def disconnect() -> None:
    """Stop GatewayClient, set connection state to 'disconnected', clear AgentManager."""

def is_connected() -> bool:
    """True if GatewayClient is running and connected."""

@property
def agent_mgr() -> AgentManager | None:
    """Returns AgentManager if connected, else None."""

def set_sync_callback(cb: Callable) -> None:
    """Window calls this to receive the live GatewayClient reference after connect succeeds."""

def dispatch(fn: Callable, *args, **kwargs) -> None:
    """Thread-safe dispatch to main thread via GLib.idle_add(fn, *args, **kwargs)."""
```

### 3.16 `ui/handlers/media_handler.py` — Media Handler (Phase 4)

**Responsibility:** All media I/O — STT (whisper.cpp push-to-talk) and prompt improvement. Extracted from `window.py` in Phase 4.

**Owns:**
- `STTEngine` instance (`_stt_engine`) — owns its own background capture thread
- Sync callback (`_sync_callback`) — window sets this to trigger `ChatHandler.on_send()` after voice input

**Thread safety:** `_on_stt_partial` fires from the STT background thread. GTK calls go through `GLib.idle_add()`.

**Public API:**
```python
def on_stt_click(_btn=None):
    """Toggle STT recording — start or stop. On stop, appends transcript and calls sync callback."""

def on_improve_click(_btn=None):
    """Send current input text to MiniMax improve API. Disables button, calls _on_improve_result on response."""

def set_on_send_callback(cb: Callable):
    """Window sets this so voice input automatically triggers ChatHandler.on_send()."""
```
```
**Rules:**
- Handler does NOT import other handlers -- window wires them together
- STTEngine runs its own background thread; handler dispatches all GTK calls via `GLib.idle_add()`
- improve_prompt() callback is already GLib-dispatched when `GLib_module` is provided

### 3.17 `utils/icons.py` — SVG Icon Rendering

**Responsibility:** Renders agent avatars and project folder icons as `Gdk.Texture`.

**Public API:**
```python
def render_agent_icon(color_hex: str, initials: str, size: int = 44) -> Gdk.Texture:
    """Colored circle with inscribed hexagon outline + 2-char initials."""

def render_folder_icon(color_hex: str, letter: str, size: int = 44) -> Gdk.Texture | None:
    """Colored folder SVG with tab notch + white letter. Returns None on error."""
```

### 3.17a `utils/improve.py` — Prompt Improvement (Template Mode)

**Responsibility:** Improve user prompt text via MiniMax API. Loads a system prompt template from `prompts/improve-system-prompt.md`, injects the user's input text at the `{{USER_INPUT}}` marker, and sends the assembled prompt to the API.

**Template mode:** If `{{USER_INPUT}}` is found in the loaded prompt file, the marker is replaced with the user's text and sent as a single `user` message. This gives the prompt file full control over structure and placement.

**Legacy mode:** If `{{USER_INPUT}}` is not found, falls back to two-message split (`system` + `user`). Backward compatible with prompt files that don't use the marker.

**Public API:**
```python
USER_INPUT_MARKER = "{{USER_INPUT}}"

def improve_prompt(raw_text, callback, GLib=None)
    # raw_text: user input box text
    # callback(improved_text, error) — GLib.idle_add dispatched if GLib provided
```

**Config:** Reads `apiKey`, `baseUrl`, `model` from `~/.config/crabcakes/config.json`. Defaults: MiniMax API, `MiniMax-M2.5-Lightning`.

### 3.18 `models/colors.py` — Color Palette

**Responsibility:** Agent and project color assignment via round-robin.

**Public API:**
```python
AGENT_COLORS: list[str]  # 10-color palette
next_agent_color() -> str
next_project_color() -> str  # same palette, separate counter — used by ProjectListHandler
reset_color_indices()
```

### 3.19 `ui/handlers/project_handler.py` — Project Handler (Phase 3)

**Responsibility:** Project tab lifecycle and agent-to-project membership routing. Extracted from `window.py` in Phase 3.

**Owns:**
- `_active_project_name` — currently open project name (or None)
- `_agent_to_project` — AgentRoutingTable instance; shared with ChatHandler (injected by window at construction)

**Does NOT own:** MainContent, LeftPanel, ChatHandler — received as dependencies.

**Thread safety:** All GTK operations dispatched via `GLib.idle_add()`. Entry points (`open_project`, `toggle_agent`) are called from the GTK main thread, so no background thread concerns.

**Public API:**
```python
def open_project(name: str, path: str):
    """Create a project tab and populate agent-to-project routing lookup."""

def toggle_agent(session_key: str):
    """Add or remove an agent from the active project membership."""

def is_project_session(session_key: str) -> bool:
    """True if session_key belongs to any known project. Used by ChatHandler."""

def get_project_for_agent(session_key: str) -> str | None:
    """Return project name for agent's session_key. Used by ChatHandler for response routing."""

def get_project_members(project_name: str) -> list[str]:
    """Return member session keys for a project. Used by ChatHandler for fan-out."""

def get_active_project_name() -> str | None:
    """Return currently active project name, or None."""

def get_agent_session_in_project(project_name: str, agent_name: str) -> str | None:
    """Return the session key an agent currently uses in a project."""

def update_agent_session(project_name: str, old_session_key: str, new_session_key: str):
    """Replace an agent's session key in a project. Updates members.json + routing table."""

def set_agent_manager(agent_mgr) -> None:
    """Inject AgentManager after gateway connect."""

def set_on_members_changed(cb: Callable): pass
def set_on_navigate_back(cb: Callable): pass
def close_project(name: str): pass
```

### 3.20 `ui/handlers/project_list_handler.py` — Project List Handler

**Responsibility:** Project card data for the Projects tab — color assignment, project listing, click handling. Does NOT build widgets (view does).

**Owns:** Project color round-robin (separate counter from agent colors), in-memory project list.

**Public API:**
```python
class ProjectListHandler:
    def __init__(self, *, on_project_opened: Callable | None = None)
    def get_projects() -> list[tuple[str, str, str]]    # (name, path, color)
    def get_project_color(path: str) -> str
    def on_project_clicked(name: str, path: str)
```

### 3.21 `ui/views/session_menu.py` — Session Switcher Popover

**Responsibility:** GTK popover listing active sessions for an agent. Right-click to switch.

**Public API:**
```python
show_session_menu(parent, agent_name, sessions, on_select)
show_project_menu(parent, project_name, member_names, current_solo, on_select)
```

### 3.21a `ui/handlers/command_handler.py` — Command Parser — Slash Prefix (Phase 7)

**Responsibility:** Parse slash-prefixed commands, resolve `@mentions`, dispatch to command handlers.

**Quoted payloads:** A2A commands use quoted payloads per `A2A_QUOTED_PAYLOAD_SPEC` — the payload is wrapped in double quotes (`"payload"`). The parser (`_parse_quoted_payload()` in `utils/quoting.py`) handles `\"` and `\\` escapes. The canonical format is `/cmd @Agent "payload"`.

**Owns:** CommandRegistry, command prefix, `@mention` resolution.

**Public API:**
```python
CommandHandler(gateway_client, agent_manager, project_handler, GLib_module, on_display_card, on_display_text)

def process_input(session_key, text, skip_dispatch=False) -> CommandResult    # parse + execute command
def set_gateway_client(gw) -> None
def set_agent_manager(agent_mgr) -> None
def register_command(name, handler, aliases=None, help_text="") -> None
def set_prefix(char) -> None
def get_help(name) -> str | None
```

**Thread safety:** All GTK via `GLib.idle_add()`.

### 3.21b `ui/handlers/review_handler.py` — Review Session Handler (Phase 7) — *Superseded by Feed Cards*

**Responsibility:** Review session lifecycle — checkpoint, check changes, accept, reject. Coordinates git_ops, diff_parser, and GTK views.

**Status:** **Superseded by the project feed card system + SPEC-3 structured feedback protocol.** The `/review`/`check`/`accept`/`reject` commands and ReviewBar are kept in the codebase for potential future use, but the primary review workflow is now: enforcement layer catches issues on write → feed cards surface events in the feed bar → audit reports (`## Audit Report` blocks) log bugs to the target agent's bug journal. This is more intuitive and always-on compared to the mode-gated checkpoint flow. See `docs/specs/SPEC-3-structured-feedback.md`.

**Owns:** Per-project `ReviewState` dict.

**Public API:**
```python
ReviewHandler(GLib, main_content, project_handler, on_review_started, on_review_ended, on_display_card, on_display_text)

def set_review_mode(project_name, mode)        # "off" | "review"
def get_review_mode(project_name) -> str
def start_review(project_name)                   # git add -A && git commit → checkpoint SHA
def check_changes(project_name)                  # git diff <sha> → display diff cards
def accept_changes(project_name, message)       # git add -A && git commit
def reject_changes(project_name, reason)        # git checkout <sha> -- .
def reject_file(project_name, file_path)
def get_state(project_name) -> ReviewState | None
def on_project_opened(project_name, project_path)
def on_project_closed(project_name)
def set_chat_handler(chat_handler)
def set_gateway_client(gw)
```

**Thread safety:** All GTK via `GLib.idle_add()`. All git calls in background threads.

### 3.21c `ui/views/review_bar.py` — Review Bar Widget (Phase 7) — *Superseded by Feed Cards*

**Responsibility:** GTK widget for review mode controls — dropdown, status, action buttons.

**Status:** **Superseded.** See 3.21b. The ReviewBar was non-functional from creation (GTK3 `pack_start` call) until 2026-05-21 (fixed to `prepend()`). It works now but is not the primary review mechanism — feed cards serve that role.

**Public API:**
```python
ReviewBar(on_mode_changed, on_start_clicked, on_check_clicked)

def set_review_mode(mode)              # update dropdown without firing callback
def set_status(text)
def set_state_idle()
def set_state_reviewing(checkpoint_sha)
def set_state_has_changes(file_count, additions, deletions)
def set_loading(loading)
def set_accept_callback(cb)
def set_reject_callback(cb)
```

### 3.21d `ui/handlers/task_handler.py` — Task Commands (Phase 7)

**Public API:**
```python
class TaskHandler:
    def __init__(self, on_display_card, on_display_text, GLib_module)
    def cmd_task(cmd) -> CommandResult
    def cmd_done(cmd) -> CommandResult
    def cmd_start(cmd) -> CommandResult
    def cmd_blocked(cmd) -> CommandResult
    def cmd_cancel(cmd) -> CommandResult
    def cmd_tasks(cmd) -> CommandResult
    def cmd_assign(cmd) -> CommandResult
    def cmd_priority(cmd) -> CommandResult
```

### 3.21e `ui/handlers/collab_handler.py` — Collaboration Commands (Phase 7)

**Public API:**
```python
class CollabHandler:
    def cmd_ask(cmd) -> CommandResult
    def cmd_delegate(cmd) -> CommandResult
    def cmd_stop(cmd) -> CommandResult
    def cmd_tell(cmd) -> CommandResult
```

### 3.21f `ui/handlers/agent_command_handler.py` — Agent Response Command Parser (Phase 6.2)

**Responsibility:** Scan agent response text for slash-prefixed commands, route them through `CommandHandler.process_input()`, and relay agent-to-agent answers back to the asking agent via pending-ask tracking.

**Owns:** `_pending_asks` (target_sk → source_sk), `_chain_depth` (session_key → depth counter).

**Wiring:** `window.py` creates the handler and wires callbacks into both response pipelines:
- `ChatHandler.set_on_agent_response(ach.on_agent_response)` — gateway agent responses
- `AgentRuntimeHandler.set_on_agent_response(ach.on_agent_response)` — special agent responses

**Architecture:** Follows §8.6 handler pattern — receives all dependencies via setters, never imports from `ui/handlers/`.

**Thread safety:** `on_agent_response()` is called from main thread via `GLib.idle_add()` in both pipelines — no additional dispatch needed.

**Public API:**
```python
class AgentCommandHandler:
    def __init__(self, *, GLib_module=None)

    # Setters (wired by window.py)
    def set_command_handler(handler)             # CommandHandler — process_input() + get_command_names()
    def set_agent_runtime_handler(handler)       # AgentRuntimeHandler — for special agent routing
    def set_gateway_client(gw)                  # GatewayClient — gateway agent routing (may be None)
    def set_agent_manager(mgr)                  # AgentManager — display name resolution
    def set_agent_routing(routing_table)         # AgentRoutingTable — project→agent lookups
    def set_project_handler(handler)             # ProjectHandler — project_path for awareness prefix
    def set_awareness_sent(awareness_set)       # Shared set[str] from ChatHandler — deduplicate awareness

    # Entry point (wired into both response pipelines)
    def on_agent_response(session_key, text, project_name) -> None
        # Step 1: RELAY — if agent has pending ask, deliver response to asking agent
        # Step 2: SCAN — parse slash commands, route through CommandHandler.process_input()
```

**Constants:**
- `_MAX_CHAIN_DEPTH = 3` — max nested command hops before cutoff
- `_MAX_COMMANDS_PER_RESPONSE = 3` — max commands parsed per response
- `_extract_quoted_commands()` function — extracts A2A commands in quoted-payload format (`/cmd @Agent "payload"`) from agent response text. Uses `_parse_quoted_payload()` from `utils/quoting.py` for escape-aware payload extraction. Fenced code blocks (```` ```...``` ````) stripped first. Returns `ParsedCommand` namedtuples. Maximum 3 commands per response.

**Relay mechanism:** `/ask @B "question"` from A → `_pending_asks[B] = A`. When B responds → `_relay_response(A, B, text)` delivers B's answer wrapped as `"[{B} responded]: {text}"`. Only `/ask` and `/delegate` create pending asks — `/tell` is one-way.

**Sender identity:** Outbound messages to target agents are prefixed with `"[{sender_name} asks]: {question}"` so the target knows who's consulting them — not the human.

**Command canonicalization:** `ParsedCommand` results from `_extract_quoted_commands()` are rebuilt into canonical slash-prefix format (`/cmd @Agent "escaped_payload"`) before calling `process_input()`. Backslashes and quotes in the payload are escaped (`\` → `\\`, `"` → `\"`) per A2A_QUOTED_PAYLOAD_SPEC §5.4. Payload-free commands (e.g. `stop`) omit the payload.

**Dispatch suppression:** `process_input()` is called with `skip_dispatch=True` to prevent GTK UI side effects (error bubbles) from background agent-to-agent routing.

**Chain depth:** Each hop increments `_chain_depth[target_sk]`. At `_MAX_CHAIN_DEPTH`, commands dropped and depth cleared. Relay messages do NOT count as hops.

**Routing priority:** direct special agent session key → display name reverse-lookup → gateway send. Gateway sends inject project awareness prefix on first "project:agent" pair.

### 3.21g `ui/handlers/session_handler.py` — Session Switching (Phase 7)

**Public API:**
```python
class SessionHandler:
    def __init__(self, agent_manager, project_handler)
    def set_agent_manager(agent_mgr) -> None
    def set_project_handler(project_handler) -> None
    def cmd_session(cmd) -> CommandResult
```

### 3.21h `ui/views/diff_card.py` — Diff Card Widget Factories (Phase 7)

**Responsibility:** GTK widget factories for diff display in project chat tabs.


**Public API:**
```python
build_file_diff_card(file_diff, on_accept_file=None, on_reject_file=None) -> Gtk.Widget
build_diff_summary_card(parsed_diff, on_accept_all=None, on_reject_all=None) -> Gtk.Widget
```

### 3.21i `utils/diff_parser.py` — Diff Parser (Phase 7)

**Public API:**
```python
parse_diff(diff_text) -> ParsedDiff
parse_diff_stat(stat_text) -> list[(file_path, additions, deletions)]

@dataclass DiffLine: type, content, old_line_no, new_line_no
@dataclass DiffHunk: header, old_start, new_start, lines[DiffLine]
@dataclass FileDiff: old_path, new_path, display_path, is_binary, is_new, is_deleted, is_renamed, hunks, additions, deletions
@dataclass ParsedDiff: files, total_additions, total_deletions, summary
```

### 3.21j `utils/git_ops.py` — Git Operations (Phase 7)

**Public API:**
```python
is_repo(project_path) -> bool
init_repo(project_path) -> GitResult
get_head_sha(project_path) -> GitResult
stage_all(project_path) -> GitResult
commit(project_path, message) -> GitResult
diff_against(project_path, sha) -> GitResult
diff_stat_against(project_path, sha) -> GitResult
diff_file_against(project_path, sha, file_path) -> GitResult
checkout_paths(project_path, sha, paths) -> GitResult
log(project_path, count=10) -> GitResult
push(project_path, remote="origin", branch="main") -> GitResult
status(project_path) -> GitResult

@dataclass GitResult: success, stdout, error, sha
```

### 3.21k `utils/config.py` — Config Path Helpers (Phase 7)

**Public API:**
```python
get_config_dir() -> str                         # ~/.config/crabcakes (or $XDG_CONFIG_HOME)
get_config_file() -> str                       # config.json path
get_projects_config_dir() -> str               # ~/.config/crabcakes/projects
get_projects_dir() -> str                      # ~/projects (or $CRABCAKES_PROJECTS_DIR)
get_gateway_url() -> str                        # ws://localhost:18789 (or $CRABCAKES_GATEWAY_URL)
get_identity_dir() -> str                       # ~/.openclaw/identity/

COMMAND_PREFIX = "/"                            # slash command prefix
```

### 3.21l `models/conversation.py` — Conversation Data Models (Agent Runtime Phase 1.1)

**Responsibility:** Dataclasses for agent conversation state. Pure data — no GTK, no network, no LLM calls.

**Public API:**
```python
class MessageRole(str, Enum): SYSTEM = "system" | USER = "user" | ASSISTANT = "assistant" | TOOL_RESULT = "tool"
class ToolCallStatus(str, Enum): PENDING = "pending" | EXECUTING = "executing" | COMPLETED = "completed" | FAILED = "failed"

@dataclass ToolCall: call_id, tool_name, arguments, result, status, started_at, completed_at
@dataclass Message: role, content, tool_calls, tool_call_id, timestamp, tokens_used
@dataclass Conversation: agent_name, project_path, system_prompt, messages, model, created_at, total_tokens, total_cost, step_count

    def add_user_message(content) -> Message
    def add_assistant_message(content, tool_calls) -> Message
    def add_tool_result(call_id, result) -> Message
    def to_api_messages() -> list[dict]
    def get_token_estimate() -> int
    def _count_char_tokens() -> tuple[int, int]  # shared char counter for estimate + breakdown
    def get_token_breakdown(model_max_tokens) -> dict  # §4.15: per-turn system/conv/remaining breakdown
    def trim_to_token_limit(max_tokens)  # §4.10: injects summary of trimmed messages when 8+ msgs remain
    def _last_exchange_summary() -> str  # compact summary of prior user turns
```

**Rules:** No imports from `ui/`, `agent/`, `gateway/`, `subprocess`.

### 3.21m `agent/runtime.py` — Agent Runtime (Phase 1.3a)

**Responsibility:** Core agent loop — conversation management, LLM API calls, tool execution, streaming SSE responses, cost tracking, conversation persistence.

**Owns:** `AgentConfig`, provider adapters (OpenAI/MiniMax/Anthropic), conversation store, tool loop.

**Public API:**
```python
class AgentRuntime:
    def __init__(config, GLib, on_text_delta, on_tool_call_start, on_tool_call_result,
                 on_tool_call_approval_needed, on_response_complete, on_error, on_token_usage,
                 on_enforcement_status=None)
    def start() / def stop()
    def create_conversation(agent_name, session_key, project_path, model, allowed_tools=None, agent_role="") -> str
    def send_message(session_key, text)         # tool loop: user msg → LLM → tool calls → results → LLM → response
    def cancel(session_key)
    def get_conversation(session_key) -> Conversation | None
    def save_conversation(session_key) -> str    # → <config_dir>/conversations/<session_key>.json
    def load_conversation(session_key) -> bool
    def list_conversations() -> list[(session_key, agent_name)]
```

**Tool loop:** Append user message → build API messages → call LLM → if tool calls: execute each tool → append results → call LLM again → if text: append assistant message → fire callbacks → check cost/step limits.

**Enforcement hook (§F):** After each `write_file`/`edit_file` tool execution, the enforcement layer runs verification tiers (syntax, tests, lint). Results are appended to the tool result text and dispatched via `on_enforcement_status` callback.

**Stuck detection (§E):** `_check_stuck()` monitors tool call history for loops (same tool+args 3×, or 8+ writes without verification). Intervention messages are appended to the conversation's tool result with a `⚠️` separator. History is per-session, capped at 20 entries, cleaned up on `cancel()`. Thread-safe via `_tool_history_lock`.

**Providers:** OpenAI (`openai/*`), MiniMax (`minimax/*`), Anthropic (`anthropic/*`), OpenRouter (`openrouter/*`), ZAI (`zai/*`) — selected by explicit `caller` field on `LLMProviderConfig` (persisted in `providers.yaml`); falls back to model-prefix derivation for legacy configs without an explicit caller. See §12 for full resolution details. Tool calls normalized to internal `ToolCall` format regardless of provider.

**Streaming:** SSE for supported providers. `on_text_delta` fires incrementally. `on_tool_call_start` fires when complete call is received.

**Cost tracking:** Provider-specific pricing tables. Fires `on_token_usage(session_key, tokens, cost)` after each LLM call. Stops loop if `cost_limit` exceeded.

**Thread safety:** All callbacks dispatched via `GLib.idle_add()`. `_tool_history` protected by dedicated `_tool_history_lock` (separate from `self._lock` to avoid deadlock with `cancel()`).

### 3.21n `agent/tools.py` — Tool Definitions + Execution (Phase 1.1)

**Responsibility:** 8 tools for local file/exec/web operations, sandboxed to `project_path`, with PM approval gating for `exec_command`.


**Public API:**
```python
@dataclass ToolDefinition: name, description, parameters, requires_approval
@dataclass ToolResult: success, output, error, duration_ms, stdout, stderr, exit_code  # §4.13: separate stdout/stderr/exit_code

def get_all_tools() -> list[ToolDefinition]
def get_tool_definitions_for_api() -> list[dict]    # OpenAI function-calling format
def execute_tool(name, arguments, project_path) -> ToolResult
def set_approval_callback(cb) -> None              # cb(session_key, tool_name, args) → bool
```

**Available tools:**

| Tool | Approval | Description |
|------|----------|-------------|
| `read_file` | No | Read file (max 50KB, binary → error) |
| `write_file` | No | Write file (sandboxed to project path) |
| `edit_file` | No | Replace exact text in file (sandboxed, unique match required) |
| `exec_command` | **Yes** | Run shell command (PM must approve; hardcoded blocklist rejects catastrophic calls first) |
| `list_files` | No | List directory contents |
| `search_files` | No | Grep/ripgrep for pattern |
| `web_search` | No | Brave Search API |
| `web_fetch` | No | Fetch URL as text |

**Sandbox:** All paths resolved relative to `project_path`. Escape attempt (`realpath` outside `project_path`) rejected with error result.

**Blocklist:** `rm -rf /`, `mkfs`, `dd if=/dev/zero of=/dev/sda` — always denied before approval callback fires.

### 3.21o `agent/config.py` — LLM Provider Config (Phase 1.1)

**Public API:**
```python
@dataclass LLMProviderConfig: name, base_url, api_key, default_model, supports_tools, supports_streaming, max_tokens
@dataclass EnforcementConfig: enabled, syntax_check, test_run, lint_check, syntax_timeout_seconds, test_timeout_seconds, lint_timeout_seconds, max_output_chars, skip_patterns
@dataclass AgentConfig: providers, default_provider, default_model, max_tool_iterations, tool_timeout_seconds, auto_save_conversations, cost_limit, step_limit, enforcement

def load_agent_config() -> AgentConfig      # reads <config_dir>/agent.json; checks chmod >600
def get_api_key(provider_name) -> str | None
```

### 3.21p `agent/context.py` — System Prompt + File Context Builder (Phase 1.2)

**Public API:**
```python
def build_system_prompt(agent_name, project_path, tools, review_mode, agent_role="") -> str
def build_file_context(project_path, query=None) -> str    # respects .gitignore, capped ~50K chars; §4.4a prepends .crabcakes/ docs
def _read_crabcakes_docs(project_path) -> str               # §4.4a — always include project docs in context
def _load_crabcakes_doc(doc_name, project_path) -> str | None  # individual doc access
def load_custom_system_prompt(project_path) -> str | None  # .crabcakes/agent-system-prompt.md → AGENTS.md → None
```

### 3.21q.5 `agent/kb_lookup.py` — Knowledge-Base Lookup (Auxilium Tier 1)

**Responsibility:** Semantic search over the project's `knowledge/*.md` files. Embeds the user's question with a local Sentence-Transformers model, computes cosine similarity against pre-built chunk embeddings, and returns the top-K most relevant chunks. Powers the Auxilium help agent's "KB-first" answer engine.

**Public API:**
```python
@dataclass
class KBChunk:
    id: str                # e.g. "setup.md#0.0"
    source: str            # e.g. "knowledge/setup.md"
    section: str           # e.g. "Installation"
    text: str              # chunk text
    score: float           # cosine similarity, 0..1

def kb_lookup(question: str, top_k: int = 3, min_score: float = 0.3,
              model_name: str = "BAAI/bge-small-en-v1.5") -> list[KBChunk]
def is_index_available() -> bool   # True if knowledge/.index/{chunks.json, embeddings.npy} exist
def get_index_path() -> Path       # knowledge/.index/
def reset_cache() -> None          # clears module-level state (for tests)
```

**Architecture:**
- Pure Python — no GTK, no network at import time.
- Lazy-loads the Sentence-Transformers model and index on first call. Module-level singleton state cached across calls.
- Default model: `BAAI/bge-small-en-v1.5` (130MB, MIT-licensed, 384-dim, runs on CPU).
- Index format: `knowledge/.index/chunks.json` (list of `{id, source, section, text}`) + `knowledge/.index/embeddings.npy` (float32, shape `(N, 384)`, L2-normalized).
- Index is built offline by `scripts/rebuild_kb_index.py` and committed to the repo.

**Fail-soft behavior:** Returns `[]` on missing index, missing model, no confident match, or any internal error. Logs at DEBUG/WARNING. The agent must treat empty list as "I don't have info on that" — never as a crash.

**Integration with AgentRuntime (Phase 2, not in this module):** Two options:
- *Option A (preprocessing):* In `AgentRuntime.send_message()`, before building the API message list, check `agent_role == "helper"` and prepend `kb_lookup(question)` results to the user message.
- *Option B (formal tool):* Register `kb_lookup` in `agent/tools.py` as a no-approval tool. LLM calls it when it needs KB context.

**No `ui/` imports.** Lives in `agent/` per §2.

### 3.21q `agent/special_agents.py` — Special Agent Definitions (Phase 1.4 → User-Defined Agents)

**Responsibility:** Agent definition registry — loads agent definitions from `~/.config/crabcakes/agents/*.yaml` (or `.json`). Built-in defaults (Coder, Debugger, Crabcakes) are seeded from `prompts/default_agents/` on first launch. New agents are created via the Agent Builder UI.

**Public API:**
```python
@dataclass SpecialAgentDef:
    conv_id_prefix, display_name, role, emoji, color, tools, can_write,
    provider: str | None, model: str | None, self_improvement: dict,
    mcp_servers: list[str],
    auto_open: bool = False,              # open tab on every app launch
    api_key_built_in: bool = False,       # reserved, not currently used
    auto_add_to_projects: bool = False,   # auto-add to every new project
    def get_self_improvement_config() -> dict

def get_special_agents() -> list[SpecialAgentDef]
def get_special_agent(prefix) -> SpecialAgentDef | None
def get_auto_open_agents() -> list[SpecialAgentDef]      # agents to auto-open on launch
def get_project_onboarding_agents() -> list[SpecialAgentDef]  # auto-add to new projects
def reload_registry() -> None   # force reload after create/edit/delete
```

**Lazy loading:** Registry loads from config files on first access. `reload_registry()` clears and reloads.

**Self-improvement:** Each agent carries `self_improvement` toggles (bug_journal, project_rules, enforcement, structured_feedback, dream_consolidation). Defaults from `utils/agent_defs.get_default_si_config()`. Override via YAML.

**Auto-open agents:** Agents with `auto_open=True` (currently only Crabcakes 🦀) get a chat tab created automatically on every app launch. See `ui/window.py` Phase 4.

**Project onboarding agents:** Agents with `auto_add_to_projects=True` are automatically added to every new project's team. See `ui/handlers/project_handler.py` Phase 5.

**Per-agent model:** `provider` and `model` fields override the global default for this agent. Resolved in `AgentRuntimeHandler._resolve_agent_model()`.

**Default agents:**
- **Coder:** Full tool set, `can_write=True`, all SI layers on
- **Debugger:** Read-only tools, `can_write=False`, context-only SI

### 3.21r `utils/agent_defs.py` — Agent Definition I/O (User-Defined Agents)

**Responsibility:** Load, validate, save, and list agent definition files from `~/.config/crabcakes/agents/`. Pure Python — no GTK, no network. Follows the `utils/projects.py` pattern.

**Public API:**
```python
def load_agent_defs() -> list[dict]             # scan agents dir, seed defaults if empty
def load_agent_def(name: str) -> dict | None    # load by display name
def load_agent_def_by_role(role: str) -> dict | None  # load by role identifier
def save_agent_def(agent_def: dict) -> str      # write to YAML (or JSON fallback)
def delete_agent_def(name: str) -> bool         # remove definition file
def validate_agent_def(agent_def: dict) -> list[str]  # check required fields, tools, prompts
def get_available_tools() -> list[dict]         # [{name, description}] from agent/tools.py
def get_available_prompts() -> list[dict]       # [{name, filepath}] from prompts/ directory
def get_available_providers() -> list[dict]     # [{name, base_url, default_model}] from agent.json
def get_default_si_config(can_write: bool) -> dict  # canonical SI defaults — single source of truth
```

**Default seeding:** Copies YAML files from `prompts/default_agents/` that don't already exist in the agents config dir. New default agents (like Crabcakes) are seeded on existing installations.

**Validation:** Checks required fields (name, prompts, tools, provider), verifies tool names against `agent/tools.py`, prompt file existence, and provider availability.

### 3.21s `ui/handlers/agent_builder_handler.py` — Agent Builder Logic (User-Defined Agents)

**Responsibility:** Form logic for the Create/Edit Agent flow. No GTK imports. Delegates I/O to `utils/agent_defs.py`.

**Public API:**
```python
class AgentBuilderHandler:
    def __init__(*, on_agent_saved: Callable, on_agent_deleted: Callable)
    def create_new() -> dict          # blank template with defaults
    def load_for_edit(name) -> dict | None
    def save(agent_def) -> (bool, list[str])  # validate + persist
    def delete(name) -> bool
    def get_tool_options() -> list[dict]
    def get_prompt_options() -> list[dict]
    def get_provider_options() -> list[dict]
```

### 3.21t `ui/views/agent_builder.py` — Agent Builder Dialog (User-Defined Agents)

**Responsibility:** GTK4 modal dialog for creating and editing agents. Pure view — receives data from `AgentBuilderHandler`, emits user actions via callbacks.

**Layout:** Name, Emoji, Role, **Provider dropdown (populated from `handler.get_provider_options()` at construction)**, Prompts multi-select, Tools checkboxes with presets (Full Access / Read Only / Custom).

**Simplifications (Phase 4 of SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN):**
- **No Model dropdown** — the agent's model is resolved at runtime from `providers.yaml` using the provider's `default_model`. The runtime in `agent/runtime.py` handles this.
- **No Manual entry mode** — the user adds providers only via the Settings dialog.
- **No API key field** — API keys live in `providers.yaml`, never in agent definitions.

**Save button enables when:** name (non-empty) AND prompts (≥1 selected) AND tools (≥1 selected) AND provider (selected in dropdown).

**`get_values()` returns:** `{"name", "emoji", "role", "prompts", "tools", "provider", "model": "", "mcp_servers", "self_improvement"}`. The `model` field is always empty string for new agents; the runtime resolves it from the provider's `default_model`.

**Public API:**
```python
class AgentBuilderDialog:
    def __init__(parent, *, handler, agent_def=None, on_save=None, on_cancel=None)
    def get_values() -> dict
    def set_provider_options(providers: list[ProviderConfig]) -> None
    def show() -> None
    def close() -> None
    def show_errors(errors: list[str]) -> None
```

**Live updates:** When providers change in Settings while the dialog is open, the wiring (`ui/wiring.py`) calls `set_provider_options()` on this dialog. The dropdown rebuilds. The handler resolves the new model from `providers.yaml` at save time, not at dialog open time.

### 3.21u.a `ui/wiring.py` — SettingsHandler Callback Wiring (Phase 1 of SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN)

**Responsibility:** Wire the `SettingsHandler`'s `on_status_changed` and `on_providers_changed` callbacks to the toolbar and dialogs. Pure composition — no business logic, no GTK widget creation.

**Owns:** None — this is a stateless wiring function. The handler is owned by the window; the toolbar is owned by the window; the dialogs are owned by the window.

**Public API:**
```python
def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable[[], Any] | None = None,
    agent_builder_factory: Callable[[], Any] | None = None,
) -> SettingsHandler
```

**Idempotency:** The function is idempotent — calling it twice on the same handler is a no-op (uses a `_wired` flag on the handler). The composition root (`ui/window.py`) calls it exactly once during `_build()`.

**Factories:** Both `settings_dialog_factory` and `agent_builder_factory` are LAZY factories that return a dialog or `None` if the dialog is not open. This is critical — the dialogs may not exist when the wiring is set up (e.g., the agent builder is only created when the user clicks the `+ Agent` button). The factory is called only when `on_providers_changed` fires.

**Behavior:**
- Initial call: `toolbar.set_settings_status(has_any_verified_provider(load_providers()))` is invoked (wrapped in try/except so a toolbar failure doesn't break the wiring).
- On `on_status_changed`: forwards to `toolbar.set_settings_status(has_any_verified_provider(providers))`.
- On `on_providers_changed`: calls both factories, forwards the providers list to whichever returned non-None.

**Architecture compliance:**
- Composition root pattern: the wiring is a function, not a class. It has no state.
- Lazy factories: dialogs are constructed on demand, not at wiring time. This matches the "dialogs are not widgets, they're ephemeral UI" principle in §3.6.
- Idempotency: makes the wiring safe to call from tests (multiple wire_settings_handler calls in a test do not produce double-callbacks).

### 3.21u `agent/enforcement.py` — Post-Write Verification (Phase 3)

**Responsibility:** Run automatic verification checks after every file write (write_file / edit_file). Three tiers: syntax guard, test runner, lint check. Pure logic — no UI imports, no GTK.

**Owns:** EnforcementCheck, EnforcementResult, TestConfig, SYNTAX_CHECKERS map, DEFAULT_SKIP_PATTERNS, tier detection logic, venv detection, test config loading.

**Public API:**
```python
@dataclass EnforcementCheck: tier, tool, file, passed, detail, output, duration_ms
@dataclass EnforcementResult: checks, appended_message
@dataclass TestConfig: command, full_suite_command, test_dir, naming_pattern, venv_path, run_full_suite, timeout_seconds, extra_args
    from_dict(data) -> TestConfig

def check(tool_name, tool_args, tool_result, project_path, config) -> EnforcementResult
```

**Internal functions:**
```python
def _detect_venv_prefix(project_path, venv_path) -> str   # POSIX "." activation prefix or ""
def _load_test_config(project_path) -> TestConfig | None   # TTL-cached loader from .crabcakes/enforcement.json test section
def _find_related_test(file_path, project_path, test_dir, naming_pattern) -> str | None
def _check_tests(file_path, project_path, config, syntax_passed) -> EnforcementCheck | None
```

**Tiers:**
1. Syntax guard (`_check_syntax`): py_compile, node --check, bash -n, etc. Per-extension mapping.
2. Test runner (`_check_tests`): detect framework (pytest, jest, make test), find related test file, run it. Skipped if syntax fails. Uses per-project `TestConfig` for custom command templates, venv activation (`_detect_venv_prefix`), configurable test directory and naming patterns, and timeout overrides.
3. Lint check (`_check_lint`): detect linter (ruff, mypy, eslint), run on changed file. Skipped if syntax fails.

**Per-project override (§F):** `.crabcakes/enforcement.json` overrides global enforcement config. Two caches:
- `_ENFORCEMENT_CONFIG_CACHE` — tier toggles (syntax_check, test_run, lint_check, skip_patterns)
- `_TEST_CONFIG_CACHE` — per-project test configuration (command, venv, naming, timeout)
Both use 30-second TTL. Applied BEFORE all tier checks so `syntax_check: false` actually skips syntax.

**Test config schema (`.crabcakes/enforcement.json` → `test` section):**
```json
"test": {
  "command": ". .venv/bin/activate && python3 -m pytest {test_file} -v --tb=short",
  "full_suite_command": ". .venv/bin/activate && python3 -m pytest tests/ -v --tb=short",
  "test_dir": "tests",
  "naming_pattern": "test_{module}.py",
  "venv_path": ".venv",
  "run_full_suite": false,
  "timeout_seconds": 30,
  "extra_args": "-x -q"
}
```
**Note:** venv activation uses POSIX `.` command (not `source`) with `shlex.quote()` on the activate path for `/bin/sh` compatibility and safe handling of spaces in venv paths.

**Configuration:** `EnforcementConfig` on `AgentConfig` — enabled/syntax_check/test_run/lint_check toggles, timeouts, skip patterns.

### 3.21v `ui/handlers/agent_runtime_handler.py` — Agent Runtime UI Bridge (Phase 1.4)

**Responsibility:** Bridge between CrabCakes UI and `AgentRuntime`. Creates conversations, routes messages, renders streamed responses in chat tabs.


**Public API:**
```python
class AgentRuntimeHandler:
    def __init__(GLib, main_content, chat_handler, project_handler)
    def start() / def stop()
    def is_running() -> bool
    def send_to_special_agent(session_key, text)              # routes through AgentRuntime, not gateway
    def send_message(session_key, text)
    def cancel(session_key)
    def approve_exec(session_key, tool_name, args, approved)  # PM Allow/Deny callback
    def on_project_opened(project_name, project_path)        # bind special agent conversations
    def on_project_closed(project_name)
    def restore_conversations()                                # reload saved from disk on startup
    def get_special_agents() -> dict[str, str]                # {session_key: display_name} for routing
    def get_special_agent_def(session_key) -> SpecialAgentDef | None
```

**Callback wiring:** All callbacks dispatch to GTK via `GLib.idle_add()`. `on_enforcement_status` is wired into per-agent runtimes for observability logging. `_on_tool_call_approval_needed` currently logs the approval request — the Allow/Deny card UI is not yet wired to a PM-clickable action.

**Special agent routing:** ChatHandler routes special agents through `send_to_special_agent()` (both solo DM and group broadcast paths). Gateway agents go through `gw.send_message()`. This ensures local AgentRuntime agents never hit the gateway.

### 3.21w `utils/mcp_config.py` — MCP Server Configuration (MCP Phase A)

**Responsibility:** Pure Python — loads MCP server configurations from YAML and JSON files. Validates transport type, command, args, environment variables, and enabled flag. No GTK, no network at import time.

**Schema (MCPServerConfig dataclass):**
```python
@dataclass
class MCPServerConfig:
    name: str
    transport: str        # "stdio" (v1), "http" (deferred to v2)
    command: str          # e.g. "npx" or "uvx" or system binary
    args: list[str]       # e.g. ["-y", "@mcp/server-memory"]
    env: dict[str, str]   # env vars to prepend
    enabled: bool = True
```

**Config location (actual code):**
- `get_mcp_servers_path()` returns `~/.config/crabcakes/mcp-servers.json` (exact path: see `utils/mcp_config.py:87`)
- `os.path.expanduser("~")/.config/crabcakes/mcp-servers.json`

**Rationale:** Single config file keeps MCP registration explicit and user-scoped. Projects can extend via `mcp_servers` field in agent definitions; servers are added/removed via config edits or future UI.

**Validation rules (validate_agent_def):**
- `mcp_servers` must be a `list[str]` (string entry gets coerced to single-element list)
- Server names must not contain `"/"` (reserved for namespacing separator)
- Invalid entries rejected with error messages

### 3.21x `utils/mcp_client.py` — MCP Client Library (MCP Phase A/B)

**Responsibility:** asyncio-to-threading bridge for MCP stdio transport. Manages persistent background event loops per conversation key, connection pooling, tool discovery, tool invocation, and OpenAI-format conversion. All async SDK calls bridged to sync Python via `_MCPLoopThread.get_thread()`.

**Key design decisions:**
- **One loop thread per conversation key** (`_MCPLoopThread._instances`) - avoids `asyncio.run()` per-call failure
- **Two-phase connect** - fast dict ops under global lock (mus), slow MCP handshake unlocked; sentinel `("connecting", thread_name)` prevents TOCTOU races
- **Tool cache** (`_tools_cache`) - per-conversation, per-server; invalidated on new connect to avoid repeated `list_tools()` round-trips
- **Sentinel guard** - sentinel stored in `_conversations` until async future completes; `is_connected()` returns False while sentinel present

**Public API** (verified by `inspect.signature()`; parameter is `conversation_key`, default `None`):
```python
connect(server_name: str, conversation_key: str | None = None) -> None
    # On success, returns None. On error, raises RuntimeError (contain subprocess failure) or TimeoutError.
disconnect(server_name: str, conversation_key: str | None = None) -> None
disconnect_all(conversation_key: str | None = None) -> None
get_connected_servers(conversation_key: str | None = None) -> list[str]
is_connected(conversation_key: str | None, server_name: str) -> bool
    # Parameter order matches source: conversation_key first, server_name second.
discover_tools(server_name: str, conversation_key: str | None = None) -> list[MCPToolDefinition]
call_tool(server_name: str, tool_name: str, arguments: dict, conversation_key: str | None = None) -> MCPToolResult
get_tools_for_api(server_names: list[str], conversation_key: str | None = None) -> list[dict]
    # Returns OpenAI-format tool definitions: [{"type":"function","function":{"name":"memory/search_nodes",...}}]
```

**Internal types:**
```python
@dataclass
class MCPToolDefinition:
    name: str           # namespaced: "server_name/tool_name"
    description: str
    input_schema: dict  # JSON Schema for tool arguments

@dataclass
class MCPToolResult:
    output: str         # Text output from tool
    error: str | None   # Error if failed
```

**Cleanup:**
- `create_conversation()` calls `mcp_disconnect_all(session_key)` on replacement (same session_key)
- `stop_all()` calls `mcp_disconnect_all()` (default conversation_key=None) before stopping AgentRuntime
- Thread drain (`_drain_and_stop`) waits for pending ops before join

### 3.21y `ui/handlers/connection_sync_handler.py` — Connection Sync Handler (Phase 3a extraction)

**Responsibility:** Post-connect wiring of live references into all dependent handlers. Called once by `GatewayHandler` via `set_sync_callback()` after the gateway WebSocket handshake completes. Injects the live `GatewayClient` and `AgentManager` into every handler that needs them (chat, command, project, agent_command, session, activity, etc.).

**Owns:** None — this is a stateless wiring function. All references it sets are owned by the handlers it injects them into.

**Constructor:**
```python
class ConnectionSyncHandler:
    def __init__(
        self,
        *,
        chat_handler,                  # ChatHandler — gets gateway_client + agent_manager
        main_content,                  # MainContent — gets agent_manager
        agent_list_handler,            # AgentListHandler — gets agent_mgr
        gateway_handler,               # GatewayHandler — SOURCE of live agent_mgr
        project_handler,               # ProjectHandler — gets agent_manager + review_handler
        command_handler,               # CommandHandler — gets gateway_client + agent_manager
        agent_command_handler,         # AgentCommandHandler — gets 6 setters wired at once
        session_handler,               # SessionHandler — gets agent_manager
        feed_handler,                  # FeedHandler — receives audit-report callback
        left_panel,                    # LeftPanel — refreshed on connect if a project is open
        review_handler,                # ReviewHandler — wired into project_handler
        activity_handler,              # ActivityHandler — gets 4 lifecycle callbacks from chat_handler
        agent_to_project,              # AgentRoutingTable — shared with agent_command_handler
        on_forward_clicked: Callable,  # chat bubble forward-button → ForwardHandler.show_forward_popover
        project_path_provider: Callable[[], str | None],  # lambda for agent_command_handler
    ) -> None
```

**Public API:**
```python
    def sync(self, gw: GatewayClient) -> None
        # Inject live GatewayClient + AgentManager into all 16 dependencies.
        # Called by GatewayHandler via set_sync_callback() — fires once per connect.
        # Idempotent: callers may invoke multiple times safely.
```

**Thread safety:** Called on the main thread by `GatewayHandler.on_connected()` (which itself is dispatched via `GLib.idle_add` from the gateway's background thread). All downstream setter calls must therefore be main-thread safe.

**Extracted from:** `window._sync_gateway_to_chat_handler` (former location: ui/window.py). The original method was 73 lines and violated the §3.6 boundary between window.py (composition root) and handlers (business logic).

### 3.21z `ui/handlers/forward_handler.py` — Forward Handler (Phase 3b extraction)

**Responsibility:** Agent-to-agent message forwarding flow. Builds a `Gtk.Popover` listing every other agent the user could forward to; on selection, routes the text to the target (special agent or gateway agent), creates/selects the target's chat tab, and renders a "forwarded from <source>" bubble into it.

**Owns:** The popover widget construction, target agent resolution (special vs gateway), and forwarded bubble rendering. Stateless otherwise.

**Constructor:**
```python
class ForwardHandler:
    def __init__(
        self,
        *,
        main_content,                  # MainContent — for create_chat_tab, get_chat_box, _chat_notebook, scroll_chat_to_bottom, _tab_sessions
        chat_handler,                  # ChatHandler — placeholder for future evolution; not currently read
        chat_render_handler,           # ChatRenderHandler — for render_sync (forwarded bubble) + _on_forward_message
        agent_runtime_handler,         # AgentRuntimeHandler — for get_special_agents() + send_to_special_agent()
        gateway_handler,               # GatewayHandler — for agent_mgr.get_name() + gw.send_message() + gw.is_connected()
    ) -> None
```

**Public API:**
```python
    def show_forward_popover(
        self,
        text: str,
        anchor_widget,                 # Gtk.Widget — the popover's parent (e.g. a chat bubble)
        source_session_key: str | None,
    ) -> None
        # Build a Gtk.Popover with one button per other agent.
        # Excludes source_session_key from the list.
        # Deduplicates between special-agent and gateway-tab lists.
        # Returns silently if no other agents exist.

    def forward_to_agent(
        self,
        target_session_key: str,
        text: str,
        source_session_key: str | None,
        popover,                       # Gtk.Popover — popped down at start
    ) -> None
        # Route text to special-agent (send_to_special_agent) or gateway (gw.send_message).
        # Resolve source_name for the forwarded_from label.
        # Create new tab if target not in _tab_sessions, else select existing.
        # Render "You" bubble with forwarded_from=<source_name> via chat_render_handler.
        # Defer scroll to bottom via GLib.timeout_add(16, ...).
```

**Thread safety:** Called only on the main thread (button click handler). The `GLib.timeout_add(16, ...)` deferral runs on the default main loop context.

**Extracted from:** `window._on_forward_clicked` and `window._forward_to_agent` (former location: ui/window.py, 100 combined lines). The methods were tightly coupled via a shared `popover` variable and were extracted as a single unit to preserve that coupling.

### 3.22 `ui/views/feedbar.py` — Response Status Bar (Phase 6)

**Responsibility:** Horizontal bar between toolbar and main content. Pure view — no business logic.

**Owns:** Status label + progress bar GTK widgets.

**Does NOT own:** Any state. All updates come from ActivityHandler via public API.

**Layout:** Horizontal outer box containing a vertical inner box (label on top, progress bar below).

**Public API:**
```python
set_status_text(markup)           # Update the state label (Pango markup)
set_progress_fraction(fraction)    # Set 0.0..1.0 bar fill; stops any active pulse
set_progress_hidden(hidden)         # Show/hide the progress bar (opacity 0 or 1)
set_progress_pulse(enable)         # Start/stop GTK pulse animation
pulse_progress()                   # Advance the pulse by one step (call every ~100ms)
set_progress_opacity(opacity)      # Set bar opacity 0.0..1.0 (for subtle idle pulse)
```

**States driven by ActivityHandler:** idle | sending | reasoning | streaming | tool_use | done

### 3.22a `ui/views/feed_card.py` — Project Feed Card Widgets (Phase 5)

**Responsibility:** GTK widget factories for individual feed cards in the project tab. Pure view — no business logic.

**Owns:** Card widget layout and CSS class application. State comes from `FeedCardData` dicts passed at construction.

**Public API:**
```python
build_feed_card(card_data: FeedCardData, *, on_review, on_accept, on_reject, on_copy) -> Gtk.Widget
build_feed_reference_widget(card_data: FeedCardData, *, on_click) -> Gtk.Widget
build_empty_feed_widget() -> Gtk.Widget
update_card_badge(card_widget: Gtk.Widget, accepted: bool | None) -> None
    # Post-construction badge update — called by FeedHandler after accept/reject
```

**card_type key determines card variant and icon** (see `models/feed_card.py` for the authoritative `css_class_for_type()` mapping; `utils/crabcard_parser.py` for the wire format):
- `file_created` — green dot icon, CSS: `feed-card-file-new`
- `file_modified` — amber dot icon, CSS: `feed-card-file-mod`
- `file_deleted` — red dot icon, CSS: `feed-card-file-del`
- `dir_created` — folder icon, CSS: `feed-card-dir-new`
- `dir_deleted` — folder icon, CSS: `feed-card-dir-del`
- `git_commit` — git-commit icon, CSS: `feed-card-git`
- `diff` — diff icon, CSS: `feed-card-diff`
- `agent_action` — user icon, CSS: `feed-card-agent`
- `task` — task icon, CSS: `feed-card-task`
- `system` — info icon, CSS: `feed-card-system`

### 3.22b `models/feed_card.py` — FeedCardData Dataclass (Phase 5)

**Responsibility:** Plain data container for Project Feed card state. No GTK, no network.

**Public API:**
```python
@dataclass FeedCardData:
    card_type: str       # "file_created" | "file_modified" | "file_deleted" |
                         # "dir_created" | "dir_deleted" | "commit" |
                         # "agent_joined" | "agent_left" |
                         # "member_joined" | "member_left" | "system"
    source: str          # "gateway" | "crabwatch" | "system"
    title: str           # Short title text
    body: str            # Body subtitle text
    author: str          # Display name of actor
    timestamp: datetime  # UTC timestamp
    project_name: str | None   # Set for project-scoped cards
    file_path: str | None      # Set for file/dir change cards (crabwatch)
    commit_sha: str | None     # Set for commit cards

def css_class_for_type(card_type: str) -> str:
    """Map card_type to CSS class name for feed card styling."""
```

---


### 3.22c `ui/handlers/feed_handler.py` — Project Feed Handler (Phase 5)

**Responsibility:** Manages project feed card lifecycle — add, remove, persist, accept/reject. Coordinates with `CrabWatchHandler` (filesystem events) and `ChatRenderHandler` (crabcard extraction). Delegates rendering to `feed_card.py`, persistence to `feed_store.py`, git ops to `git_ops.py`.

**Owns:** `_cards` (dict: card_id → FeedCardData), `_card_widgets` (dict: card_id → Gtk.Widget), `_project_cards` (dict: project_name → [card_ids]), `_project_paths` (dict: project_name → abs_path), `_recent_git_paths` (dict: file_path → monotonic timestamp for echo suppression), `_lock` (threading.Lock).

**Constructor:**
```python
class FeedHandler:
    def __init__(
        self,
        *,
        GLib,                        # gi.repository.GLib — for idle_add dispatch
        on_send_to_agent,            # Callable[[str, str], None] — send to agent
        on_card_added=None,          # Callable[[str], None] | None — card_id after add
        get_chat_box_for_session=None,  # Callable[[str], Gtk.Box | None] — chat box lookup for snapshots
    )
```

**Note:** `feed_tab` is NOT a constructor parameter. Set via `set_feed_tab()` after construction.

**Public API:**
```python
    def set_feed_tab(self, feed_tab) -> None
    def add_card(self, card_data: FeedCardData) -> str    # returns card_id
    def remove_card(self, card_id: str) -> None
    def get_card(self, card_id: str) -> FeedCardData | None
    def get_cards_for_project(self, project_name: str) -> list[FeedCardData]
    def clear_project(self, project_name: str) -> None
    def on_project_opened(self, project_name: str, project_path: str) -> None
    def on_project_closed(self, project_name: str) -> None
    def on_filesystem_event(self, card_data: FeedCardData) -> None
    def handle_review(self, card_id: str) -> None
    def handle_accept(self, card_id: str) -> None
    def handle_reject(self, card_id: str) -> None
    def handle_copy(self, text: str) -> None
```

**Thread safety:** All GTK operations via `GLib.idle_add()`. Git ops in background threads. `_lock` protects dict mutations.

**Echo suppression:** Git accept/reject operations modify files on disk, causing CrabWatch to fire filesystem events that would create duplicate cards. FeedHandler suppresses these echoes by recording `file_path` + timestamp in `_recent_git_paths` before starting git threads. `on_filesystem_event()` checks this map and drops events for paths operated on within the last 3 seconds.

---

## 3.23 `ui/handlers/activity_handler.py` — Activity State Machine (Phase 6)

**Responsibility:** The 6-state activity machine that drives the Response Status bar (FeedBar). Manages state transitions, live timers, and FeedBar updates.

**Owns:** All state machine state (timers, counters, timestamps). Does NOT own any GTK widgets — manipulates FeedBar only through its public API.

**Does NOT own:** FeedBar or MainContent — received as constructor dependencies.

**Constructor dependencies:**
- `feedbar`: FeedBar instance — updated via public API
- `main_content`: MainContent instance — used via `main_content.get_review_bar()` to read current ReviewBar state
- `GLib_module`: optional GLib reference for thread dispatch

**Thread safety:** All GTK calls via `GLib.idle_add()` / `timeout_add()`. Entry points are called from GTK main thread only.

**States:** idle | sending | reasoning | streaming | tool_use | done

**Public API (entry points — called from `window._on_ws_event`):**
```python
on_agent_start(session_key, data=None)           # agent phase=start → reasoning
on_agent_end(session_key, data=None)            # agent phase=end → done (+ 5s idle timer)
on_agent_error(session_key, data=None)          # agent phase=error → idle
on_tool_use(tool_name, session_key, data=None)  # tool_call event → tool_use
on_chat_delta(delta_text, session_key)           # first delta → streaming
on_agent_message_received(session_key)           # pre-flight → sending
on_send_initiated(session_key)                    # send button pressed → sending + 30s pre-flight timeout
on_res_confirmed(session_key)                     # gateway res confirmed → reasoning (phase 2 begins)
on_gateway_event(event, payload)                 # universal entry — routes agent/chat/tool_call/res events
on_chat_final(session_key)                       # chat final (no-op; on_agent_end handles completion)
```

**Bug fix (Phase 1 of SPEC-smarter-chat-ux) — missing message recovery:**

State tracked for recovery when chat final arrives with no message body:
- `_assistant_text_buffer[session_key] → str`: last assistant text per session

Public setters for the recovery callbacks:
```python
set_on_assistant_buffer(cb)                     # cb(session_key, text) — forward each assistant delta
set_on_lifecycle_completed(cb)                 # cb(session_key, text) — lifecycle end/error fires this; ChatHandler renders fallback
set_on_activity_bubble(cb)                     # cb(ActivityBubble) — tool/plan/approval/command_output/patch events; Phase 2 of SPEC-smarter-chat-ux
set_on_agent_lifecycle(cb)                      # NEW (SPEC-activity-drawer) — cb(session_key, agent_name, "start"|"end") for per-agent separator rows in the drawer
set_on_agent_start(cb)                          # cb(session_key) — clears ChatHandler render guard for next round. Receives RAW session_key from the gateway event (the agent key), not _active_session() key.
set_agent_routing(routing_table)                # Injected by window.py._build(). Enables _is_ui_active() to resolve project tabs for agent session keys.
```

**Activity Bubbles (Phase 2 of SPEC-smarter-chat-ux):**

ActivityHandler fires `_activity_bubble_callback` for each gateway event that warrants a visible status indicator in the chat:
- `stream=lifecycle phase=start` → ⏳ Agent started...
- `stream=tool phase=start` → 🔧 Running {name}...
- `stream=tool phase=end` → ✅ {name} ({durationMs}ms)  or  ❌ {name} — error
- `stream=plan` → 📋 Plan: {title} ({n} steps)
- `stream=approval phase=requested` → 🔒 Approval needed: {command}
- `stream=patch phase=end` → ✏️ {name}: +{added} ~{modified} -{deleted} files

Architecture: ActivityHandler only creates ActivityBubble dataclass instances and fires the callback. As of SPEC-activity-drawer Phase 1, the callback target is `ActivityDrawer.append_event(bubble.to_drawer_row())` — the adapter that converts the dataclass to the drawer's dict shape lives in `connection_sync_handler.sync()`. ChatHandler no longer renders activity bubbles.

Activity bubbles (Phase 2 of SPEC-smarter-chat-ux):
- `on_gateway_event()` parses `stream` values `tool`, `plan`, `approval`, `patch`
- Constructs `ActivityBubble` (from `models/activity.py`) and fires the callback
- ChatHandler's `render_activity_bubble()` renders via `ChatRenderHandler.render_activity()`

Tab routing uses `agent_to_project` (AgentRoutingTable). In ChatHandler this is passed via constructor; in ActivityHandler it's injected via `set_agent_routing(routing_table)`. Lazy import of `models.activity` inside method body to avoid circular deps.

**Two-phase progress tracking:**
- Phase 1 (send-initiated): Time-driven progress bar — on_send_initiated starts 30s timer
- Phase 2 (event-driven): Event-driven hop counting — on_res_confirmed transitions to phase 2

**State transitions:**
- `agent phase=start` → `reasoning`
- `agent phase=end` → `done` (auto → `idle` after 5s)
- `agent phase=error` → `idle`
- `tool_call` event → `tool_use`
- First chat delta → `streaming`
- Agent message in history → `sending` (pre-flight)

### 3.22d `utils/feed_store.py` — Feed Persistence (Phase 5)

**Responsibility:** JSON persistence for feed cards. Pure functions — no classes, no GTK, no state. Loads/saves `FeedCardData` lists from `.crabcakes/feed.json` per project.

**Public API:**
```python
def load_feed(project_path: str) -> list[FeedCardData]
    # Load cards from .crabcakes/feed.json. Chronological (oldest first). Empty list if missing/invalid.

def save_feed(project_path: str, cards: list[FeedCardData]) -> None
    # Save cards to .crabcakes/feed.json. Creates .crabcakes/ if needed.

def append_feed_card(project_path: str, card: FeedCardData) -> None
    # Append single card. Load → append → save.

def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool
    # Update card by card_id. Returns True if found. Only allows runtime fields (accepted, reviewed, metadata).
```

**Architecture rules:**
- Lives in `utils/` — pure Python, no GTK, no network
- Thread-safe via file I/O (called from background threads by FeedHandler)
- Imports `models.feed_card.FeedCardData` only
- No imports from `ui/` or `gateway/`

### 3.22e `utils/crabcard_parser.py` — Crabcard Block Parser (Phase 5)

**Responsibility:** Parse `` ```crabcard `` blocks from agent chat messages into `FeedCardData`. Pure function — no GTK, no state. Returns cleaned text with placeholder markers for downstream rendering.

**Public API:**
```python
def extract_crabcards(text: str, project_name: str, agent_name: str = "agent") -> tuple[str, list[FeedCardData]]
    # Parse ```crabcard blocks. Returns (cleaned_text, cards).
    # Cleaned text contains \x00CRABCARD_REF:N\x00 placeholders.

def is_crabcards_placeholder(text: str) -> bool
    # True if text contains a crabcard placeholder marker.

def get_placeholder_index(placeholder: str) -> int | None
    # Extract card index from placeholder string.
```

**Crabcard format:**
```
```crabcard
type: <card_type>
title: <title text>
file: <optional file path>
additions: <optional int>
deletions: <optional int>
commit_sha: <optional str>
task_id: <optional str>
---
<body content — diff text, description, etc.>
```
```

**Architecture rules:**
- Lives in `utils/` — pure Python, no GTK, no network
- Imports `models.feed_card.FeedCardData` only
- No imports from `ui/` or `gateway/`
- Called from `ui/handlers/chat_render_handler.py` during `render_sync()`

---

## 3.24 `ui/handlers/crabwatch_handler.py` — CrabWatch Filesystem Watcher (Phase 5)

**Responsibility:** Watch the active project directory for filesystem changes via `Gio.FileMonitor`. Route `FeedCardData` events to `FeedHandler.on_filesystem_event()` for display in the Project Feed.

**Architecture rules:**
- Lives in `ui/handlers/` — uses GLib only (no GTK widget creation)
- Thread-safe via GLib event callbacks; GTK dispatch via `GLib.idle_add()` where needed
- No IPC, no sockets, no external processes — pure GTK4/Gio integration

**Constructor dependencies:**
- `GLib_module`: GLib reference for dispatch
- `on_event`: callback receiving `FeedCardData` dicts — wired to `FeedHandler.on_filesystem_event()`

**Public API:**
```python
class CrabWatchHandler:
    def start_watching(project_path: str, project_name: str) -> None:
        """Start monitoring project_path. Stops any previous watch."""
    def stop_watching() -> None:
        """Stop monitoring."""
    def is_watching() -> bool
```

**Events fired as `FeedCardData`:**

| Gio event | card_type | title format |
|-----------|-----------|--------------|
| `CREATED` (file) | `file_created` | "Created <filename>" |
| `CHANGED` (file) | `file_modified` | "Modified <filename>" |
| `DELETED` (file) | `file_deleted` | "Deleted <filename>" |
| `CREATED` (dir) | `dir_created` | "Created directory <filename>" |
| `DELETED` (dir) | `dir_deleted` | "Deleted directory <filename>" |

**Ignored paths (no events):**
- `.crabcakes/`, `.git/`, `node_modules/`, `__pycache__/`
- `*.pyc` files, `.DS_Store`, dotfiles (names starting with `.`)

**Debouncing:** Events on the same relative path within 200ms are batched — only the final state fires a card.

**Wiring in `window.py`:**
- Created alongside `FeedHandler` in `_build()`
- `start_watching(p, n)` called in `set_on_project_opened` callback chain
- `stop_watching()` called in `set_on_project_tab_close` callback chain


### 3.25 `models/conversation_snapshot.py` — Conversation Snapshot Data

**Responsibility:** Plain data containers for conversation snapshots. No GTK, no network, no git.

**Public API:**
```python
@dataclass SnapshotMessage:
    role: str
    content: str
    timestamp: str | None

@dataclass ConversationSnapshot:
    session_key: str
    agent_name: str
    messages: list[SnapshotMessage]
    created_at: str
    token_count: int
```

**Used by:** `utils/conversation_store.py` (creation), `utils/feed_store.py` (persistence)

---

### 3.26 `models/team.py` — Project Team Data

**Responsibility:** Data models for project team membership. Pure data — no GTK, no network, no file I/O.

**Public API:**
```python
@dataclass TeamMember:
    session_key: str
    display_name: str
    role: str
    color: str

@dataclass ProjectTeam:
    project_path: str
    members: list[TeamMember]

    def get_session_keys() -> list[str]
    def to_dict() -> dict
    @staticmethod
    def from_dict(data: dict, project_path: str) -> ProjectTeam
```

**Used by:** `utils/project_awareness.py` (load/save team), `utils/projects.py` (deprecated shim)

---

### 3.27 `utils/project_awareness.py` — Project Awareness System

**Responsibility:** Manages the `.crabcakes/` directory per project. Reads/writes project metadata, team membership, workflow state, git context, and awareness documents. Pure Python — no GTK, no network. This is the authoritative source for project context; `utils/projects.py` deprecated its membership functions in favor of this module.

**Manifest:**
- Reads: `.crabcakes/*` (project.md, team.json, context.md, awareness.json, workflow.md)
- Writes: `.crabcakes/*` (same files)

**Public API:**
```python
def get_crabcakes_dir(project_path: str) -> str
def load_team(project_path: str) -> ProjectTeam
def save_team(project_path: str, team: ProjectTeam) -> None
def is_project_onboarded(project_path: str) -> bool
def get_project_context(project_path: str) -> str
def get_workflow_content(project_path: str) -> str
def build_awareness_block(project_path: str, ...) -> str
def load_custom_identity(project_path: str) -> dict | None
```

**Architecture rules:**
- Lives in `utils/` — may import `models/` only (TeamMember, ProjectTeam, TaskStore)
- Imports `utils/config.py`, `utils/git_ops.py`, `utils/workflow_state.py`
- No imports from `ui/` or `gateway/`

---

### 3.28 `utils/audit_parser.py` — Audit Report Extraction

**Responsibility:** Parse structured `## Audit Report` sections from agent messages into typed `AuditReport` dataclass instances. Pure functions — no GTK, no state.

**Public API:**
```python
@dataclass AuditReport:
    severity: str          # "bug" | "issue" | "suggestion"
    file_path: str
    task: str
    bug_description: str
    pattern: str | None
    reviewer: str
    target_role: str
    project_path: str | None

def extract_audit_reports(text: str) -> list[AuditReport]
```

**Used by:** `ui/handlers/agent_command_handler.py` (scan agent responses), `utils/feedback_processor.py` (persistence)

---

### 3.29 `utils/conversation_store.py` — Snapshot Creation Utilities

**Responsibility:** Create `ConversationSnapshot` data objects from plain Python data (message lists) and git diffs. Pure functions — no GTK, no network.

**Public API:**
```python
def build_snapshot(session_key, agent_name, messages, git_diff=None) -> ConversationSnapshot
def build_snapshot_from_conversation(conv, git_diff=None) -> ConversationSnapshot
```

**Architecture rules:**
- Lives in `utils/` — imports `models/` only (ConversationSnapshot, SnapshotMessage)
- May import `utils/git_ops.py` for git diff retrieval
- No imports from `ui/` or `gateway/`

---

### 3.30 `utils/feedback_processor.py` — Audit Report File I/O

**Responsibility:** All file I/O for structured audit report processing. Writes audit reports to agent bug journals, reads agent definitions for role resolution. Pure Python — no GTK, no network.

**Public API:**
```python
def process_audit_report(report: AuditReport, project_path: str) -> str
def get_bug_journal_path(project_path: str, target_role: str) -> str
def append_review_entry(project_path: str, entry: str) -> None
```

**Architecture rules:**
- Lives in `utils/` — imports `models/` only (AuditReport via audit_parser)
- Imports `utils/agent_defs.py` for role resolution, `utils/review_log.py` for persistence
- No imports from `ui/` or `gateway/`

---

### 3.31 `utils/review_log.py` — Review Log Persistence

**Responsibility:** Append and retrieve review log entries per project. Pure file I/O — no GTK, no network.

**Public API:**
```python
def append_review_entry(project_path: str, entry: str) -> None
def get_review_log(project_path: str) -> list[str]
```

---

### 3.32 `utils/spellcheck.py` — Spell Check Engine

**Responsibility:** Detect misspelled words and provide suggestions via Enchant. Pure logic — no GTK, no network.

**Public API:**
```python
def check_text(text: str) -> list[tuple[int, int, str]]
def get_suggestions(word: str) -> list[str]
def is_available() -> bool
```

**Used by:** `ui/handlers/input_toolbar_handler.py` (spell check logic), `ui/views/chat_input_toolbar.py` (spell check popover)

---

### 3.33 `utils/workflow_state.py` — Workflow State Tracker

**Responsibility:** Manage `.crabcakes/workflow.md` per project. Tracks which workflow phases are complete, which is current, and timestamps. Pure file I/O — no GTK, no network.

**Public API:**
```python
def init_workflow(project_path: str) -> None
def advance_phase(project_path: str, phase: str) -> None
def get_current_phase(project_path: str) -> str | None
def get_workflow_content(project_path: str) -> str
```

**Architecture rules:**
- Lives in `utils/` — pure Python, no GTK, no network
- May import `utils/config.py` for project path helpers, `utils/project_awareness.py` for directory management
- No imports from `ui/` or `gateway/`

---

### 3.34 `ui/views/chat_input_toolbar.py` — Chat Input Toolbar (View)

**Responsibility:** Compact toolbar for the chat input area — find/replace bar and spell check popover. Pure view — widgets only, no business logic. All logic lives in `InputToolbarHandler`.

**Public API:**
```python
class ChatInputToolbar(Gtk.Box):
    def __init__(self, on_find_changed=None, on_find_next=None, on_find_prev=None,
                 on_replace=None, on_replace_all=None, on_spell_suggestion=None)
    def show_find_bar(self) -> None
    def hide_find_bar(self) -> None
    def get_find_text(self) -> str
    def set_find_text(self, text: str) -> None
```

---

### 3.35 `ui/views/feed_tab.py` — Feed Tab View

**Responsibility:** Pure view container for the Projects notebook's "Feed" sub-tab. No business logic, no state mutations.

**Public API:**
```python
class FeedTab(Gtk.Box):
    def get_card_container() -> Gtk.Box
    def append_card(card_widget: Gtk.Widget, card_id: str | None) -> None
    def remove_card(card_id: str) -> None
    def scroll_to_bottom() -> None
```

---

### 3.36 `ui/handlers/input_toolbar_handler.py` — Input Toolbar Handler

**Responsibility:** Owns all input toolbar logic — find/replace, spell check, file I/O, word count. Does NOT import GTK. All GTK dispatch via `GLib.idle_add()`. Pattern copied from `MediaHandler`.

**Owns:** Find bar state (current query, match count, replace text), spell check state (current misspelled word, suggestion popover).

**Public API:**
```python
class InputToolbarHandler:
    def __init__(GLib, on_show_spell_suggestions, on_replace_word)
    def find_next(text: str) -> int
    def find_prev() -> int
    def replace_current() -> None
    def replace_all() -> None
    def get_word_count() -> int
    def check_spell_at_position(text: str, pos: int) -> list[str]
```

**Thread safety:** All GTK operations via `GLib.idle_add()`. Spell check runs synchronously on the main thread (Enchant is fast).

---

## 4. Data Flow

### 4.1 Gateway Connection Flow

```
User clicks Connect
  → window._on_connect_clicked()
    → window._connect_gateway()
      → creates AgentManager()
      → creates GatewayClient(on_connect=window._on_ws_connect, ...)
      → client.start()

Connected
  → window._on_ws_connect()
    → toolbar.update_connection_state("connected")
    → snapshot = gw.get_snapshot()
    → for each agent: agent_mgr.register(session_key, name)
    → left_panel.set_agents(names_ref, _on_agent_selected)

User clicks Disconnect
  → window._on_disconnect_gateway()
    → gw.stop()
    → toolbar.update_connection_state("disconnected")
```

### 4.2 Agent Selection Flow

```
User clicks agent row
  → left_panel._on_agent_row_activated()
    → _on_agent_selected(session_key, agent_name)
      → main_content.create_chat_tab(session_key, agent_name)
```

### 4.3 Project Group Chat — Open Project

```
User double-clicks project directory
  → FileTree._on_row_activated()
    → FileTree.on_project_opened(name, path) callback
      → window._on_project_opened(name, path)
        → _active_project_name = name
        → main_content.create_chat_tab(f"project:{name}", f"Project: {name}")
        → left_panel.refresh_agents_with_project(name)  # shows +/− buttons
        → for member_key in load_members(name): _agent_to_project.add(member_key, name)
```

### 4.4 Project Group Chat — Fan-Out Send

```
User types message in project tab and clicks Send
  → ChatHandler.on_send()
    → session_key = main_content.get_current_session_key()
    → if session_key.startswith("project:"):
        project_name = session_key.split(":", 1)[1]
        members = load_members(project_name)
        for member_key in members: gw.send_message(member_key, text)
      else:
        gw.send_message(session_key, text)
    → get_chat_box().append(render_sync("You", text, session_key))
```

### 4.5 Project Group Chat — Response Routing (Phase 3)

```
Gateway sends events → ChatHandler.on_chat_event(event, payload)

  event="chat", state="delta":
    → _handle_streaming_delta(session_key, target_tab, delta_text)
      → ChatRenderHandler.start_streaming(session_key, chat_box)  # first delta only
        → build_streaming_bubble() — pending bubble with cursor (▍)
      → ChatRenderHandler.update_streaming(session_key, delta_text)
        → update label with gateway's cumulative delta text (no local accumulation)

  event="chat", state="final":
    → _handle_final_response(tab, session_key, final_text)
      → ChatRenderHandler.end_streaming(session_key)
        → remove cursor, replace with final bubble via build_role_bubble()
      → chat_box.record("Agent", final_text)
```

### 4.6 Special Event Cards — Phase 4

```
Gateway sends special events → ChatHandler.on_chat_event(event, payload)

  (non-"chat" events only)

  event in ("file_read", "edit_proposal", "tool_call", "error", "thinking"):
    → _handle_special_event(event, session_key, target_tab, payload)
      → switch_to_tab(target_tab)        # route to project or agent tab
      → chat_box = get_chat_box_for_session(target_tab)
      → ChatRenderHandler.render_event_card(event, chat_box, **fields)
        → route to factory:
            "file_read"       → create_file_card(file_path, snippet, line_range)
            "edit_proposal"   → create_edit_card(file_path, diff)
            "tool_call"       → create_tool_card(tool_name, detail)
            "error"           → create_error_bubble(error_msg)
            "thinking"        → build_role_bubble("Agent", thought_text)  # plain text
            (unknown)         → no-op (silently ignored)
```

**New widget factories** (Phase 4 additions to `ui/views/chat_bubble.py`):
- `create_file_card(file_path, snippet, line_range)` — green left border, 📄 icon
- `create_edit_card(file_path, diff)` — amber left border, ✏️ icon
- `create_tool_card(tool_name, detail)` — slate left border, 🔧 icon
- `create_error_bubble(error_msg)` — red left border + tint, ❌ icon

**New CSS classes** (`ui/styles.py`):
- `.bubble-file-read`, `.bubble-edit-proposal`, `.bubble-tool-call`
- `.bubble-error`, `.bubble-thinking`, `.bubble-streaming`

### 4.7 Forward Callback Wiring Chain

```
window._build()
  → ChatHandler.set_on_forward_message(cb)     # window provides the callback
    → ChatRenderHandler.set_on_forward_message(cb) # render handler stores it

On render_sync() call:
  → ChatHandler.render_sync(role, text, session_key, on_forward_click=self._on_forward_message)
    → ChatRenderHandler.render_sync(role, text, session_key, on_forward_click=cb)
      → build_role_bubble(role, text, on_forward_click=cb, tight=...)
        → creates Forward button → on click → cb(text, anchor_widget)

On forward click (user clicks Forward button on agent bubble):
  → bubble._on_forward_click(text, widget)
    → ChatHandler._on_forward_message(text, widget)
      → window._on_forward_message(text, widget)   # (future: popover to pick target)
```

### 4.8 Scroll-to-Bottom Button

```
User scrolls up in chat tab
  → vadjustment.value-changed → _on_vadjustment_changed()
    → if distance_from_bottom > 80px: _scroll_btn.set_opacity(1)
      else: _scroll_btn.set_opacity(0)

User clicks scroll button
  → _on_scroll_to_bottom_clicked()
    → scroll_chat_to_bottom()  # GLib deferred via idle_add
    → _scroll_btn.set_opacity(0)
```

### 4.9 Project Membership — Toggle Agent

```
User clicks +/− button on agent row
  → left_panel._on_agent_toggle_clicked(button)
    → members = load_members(active_project_name)
    → if session_key in members: members.remove(session_key)
      else: members.append(session_key)
    → save_members(active_project_name, members)
    → _on_project_members_changed(active_project_name, members)
      → window._on_project_members_changed(name, members)
        → rebuild _agent_to_project for this project
```

---

### 4.10 Activity State Machine (Phase 6)

```
Gateway events → window._on_ws_event() → ActivityHandler methods
```

**Phase routing logic (two distinct gateway event structures):**

Lifecycle events (`payload.stream == "lifecycle"`) — phase at `payload.data.phase`:
```json
{"type":"event","event":"agent","payload":{"stream":"lifecycle","data":{"phase":"end","livenessState":"working"}}}
```

Item-level events (`payload.stream == "item"`) — phase at `payload.phase`:
```json
{"type":"event","event":"agent","payload":{"stream":"item","data":{"itemId":"tool:call_function_...","phase":"end","kind":"tool"}}}
```

**Routing table in `window._on_ws_event`:**

| `event` | `payload.stream` | phase location | Handler method |
|---------|-----------------|----------------|---------------|
| `chat` | — | `payload.state` | ChatHandler routing |
| `chat` | — | `payload.state=delta` | streaming delta handler |
| `agent` | `lifecycle` | `payload.data.phase=start` | `on_agent_start()` |
| `agent` | `lifecycle` | `payload.data.phase=end` | `on_agent_end()` |
| `agent` | `lifecycle` | `payload.data.phase=error` | `on_agent_error()` |
| `agent` | `item` | `payload.phase` (kind=tool) | `on_tool_use()` |
| `agent` | `item` | `payload.phase` (kind=message) | streaming handler |


**State transitions:**
- `agent phase=start` → `reasoning`
- `agent phase=end` → `done` (auto → `idle` after 5s)
- `agent phase=error` → `idle`
- `tool_call` event → `tool_use`
- First chat delta → `streaming`
- Agent message in history → `sending` (pre-flight)

**ActivityHandler → FeedBar public API:**
  set_status_text(markup)              → updates state label
  set_progress_fraction(fraction)       → 0.0..1.0 bar fill (stops pulse)
  set_progress_hidden(hidden)          → show/hide bar
  set_progress_pulse(enable)          → start/stop GTK pulse animation
  pulse_progress()                     → advance pulse by one step
  set_progress_opacity(opacity)        → 0.0..1.0 (for subtle idle pulse)

FeedBar → GTK widgets:
  _status_label (Gtk.Label)            → state text
  _progress_bar (Gtk.ProgressBar)       → animated fill / pulse
```

### 4.11 Agent-to-Agent (A2A) Consultation — Command-Based (Phase 6.1)

Agent-to-agent consultation is entirely command-based. There are no automatic @mention
detectors, no relay threads, no convergence loops, and no capture_response cycles.

**The only mechanism:** `/ask @AgentName "question"` — typed by a human or emitted
by an agent in its response text.

**Commands** (see §3.21d for CollabHandler):
| Command | Effect |
|---------|--------|
| `/ask @Agent "question"` | Forward question to target agent; response appears in same tab |
| `` `delegate @Agent "task"` `` | Assign a task to an agent |
| `` `stop @Agent` `` | Send stop signal to a collaboration |
| `` `tell @Agent "info"` `` | Share information with an agent |

**Data flow — `` `ask @Coder "is this edge case valid?"` `` in a project tab:**
```
User types `ask @Coder "is this edge case valid?"`
         │
         ▼
ChatHandler.on_send() → CommandHandler.process_input()
         │
         ▼
CommandHandler resolves @Coder → Coder's session_key (via AgentManager + _special_agents)
         │
         ▼
CollabHandler.cmd_ask() → CommandResult(forward_to=coder_sk, forward_text=question)
         │
         ▼
ChatHandler echoes "→ @Coder: is this edge case valid?" in project tab
         │
         ▼
gw.send_message(coder_sk, "is this edge case valid?")
         │
         ▼
Coder responds → response appears in project tab
```

**Special agents (Coder, Debugger):** Forwarded via `AgentRuntimeHandler.send_to_special_agent()`
when the target is a registered special agent. ChatHandler checks `agent_runtime_handler.get_special_agents()`
before routing via gateway.

**What was removed (Phase 6.1):**
- CollabManager — automatic @mention detection, relay thread engine, response capture, convergence detection
- `[A2A relay from ...]` prefix handling in both ChatHandler and AgentRuntimeHandler
- `is_pending_relay()` / `capture_response()` / `start_relay()` / `detect_a2a_mention()` throughout
- §3.21n (CollabManager module) and the old §4.11 A2A data flow

**Architecture rule:** Agents that need another agent's input include a slash-prefixed command
in their response text. The slash command is parsed by CommandHandler like any other
human input — no special casing, no detection, no loops. Agent-initiated parsing is
handled by `AgentCommandHandler` (Phase 6.2) which hooks into the response pipeline
and routes commands through CommandHandler.process_input().

### 4.12 MCP Tool Execution Flow (MCP Phase B)

**When:** An agent with `mcp_servers: ["memory", "fetch"]` is loaded and a tool call arrives.

**Data flow:**
```
Agent YAML definition (mcp_servers: ["memory", "fetch"])
         │
         ▼
SpecialAgentDef(conv_id_prefix, ..., mcp_servers=["memory", "fetch"])
         │
         ▼
AgentRuntimeHandler.send_to_special_agent() → create_conversation(session_key, mcp_servers=["memory", "fetch"])
         │
         ▼
Conversation.mcp_servers = ["memory", "fetch"] (stored in Conversation dataclass)
         │
         ▼
AgentRuntime.create_run_for(conv) → get_tool_definitions_for_api(conv)
         │
         ▼
Tools.get_tool_definitions_for_api() → get_tools_for_api(mcp_servers, session_key)
         │
         ▼
utils/mcp_client.py:
    for each server in mcp_servers:
        if not is_connected(session_key, server): connect(server, session_key)
        discover_tools(server, session_key)  # calls session.list_tools(), caches result
        convert to OpenAI format: name = "server_name/tool_name"
         │
         ▼
Merge MCP tools + built-in tools → agent sees unified tool list
         │
         ▼
LLM requests tool call: "memory/search_nodes" with {"query": "test"}
         │
         ▼
AgentRuntime.on_tool_call() → execute_tool("memory/search_nodes", {"query": "test"}, project_path, session_key)
         │
         ▼
agent/tools.py execute_tool():
    if "/" in tool_name:  # MCP tool routing
        server_name, tool_name = tool_name.split("/", 1)
        result = call_tool(server_name, tool_name, arguments, session_key)
    else:
        # Built-in tool routing (read_file, write_file, etc.)
```

**Namespacing rule:** All MCP tool names are prefixed with `server_name/` using the `server_name/tool_name` convention. Built-in tools have no slash. This allows unambiguous routing.

**Cleanup on conversation end:** `create_conversation(session_key)` with same key → `mcp_disconnect_all(session_key)` to kill stale MCP subprocesses.

**Graceful degradation:** If MCP server fails (not found, can't spawn, network timeout), `execute_tool` returns `ToolResult(success=False, error=...)` and logs warning. Built-in tools still work.

### 4.13 Provider Change → Open Agent Builder Refresh

User adds a provider in Settings while the Agent Builder is open
  → SettingsDialog._on_add_provider()
    → handler.add_or_update(ProviderConfig)
      → handler._on_providers_changed(providers)  (if handler is the SettingsHandler)
        → wire_settings_handler._on_providers_changed(providers)  (closure)
          → settings_dialog_factory() → None (or settings dialog) → refresh_providers(providers)
          → agent_builder_factory() → AgentBuilderDialog or None
            → dialog.set_provider_options(providers)  (rebuilds dropdown)

User removes a provider in Settings while the Agent Builder is open (with that provider selected)
  → same chain as above
    → agent_builder._providers updates
      → _rebuild_provider_dropdown() runs
        → if no providers left: dropdown shows "(no providers — open Settings)"
        → if providers remain: dropdown shows remaining names
        → _get_selected_provider_id() returns "" if the selected index is now invalid
          → _update_save_button() disables Save

## 5. Callback Pattern

**Primary pattern for all component communication.** A callback is a function reference passed to a component at construction time or via a setter. The component calls it when something happens. The component does NOT know what happens after.

**Rules:**
- Callbacks are always passed, never hardcoded.
- A component never imports another component's module for the purpose of calling it.
- Callbacks use the component's internal state only — no access to widgets outside the component.

**Setter pattern** (for data available after construction):
```python
panel.set_agents(agent_names, on_agent_selected)
panel.set_on_project_opened(cb)
panel.refresh_agents_with_project(name)
```

**Constructor pattern** (for data available at construction):
```python
toolbar = Toolbar(on_connect_clicked=self._on_connect_clicked)
file_tree = FileTree(on_file_selected=self._on_project_selected)
```

---

## 6. Naming Conventions

### 6.1 Variables and Functions

| Pattern | Example | Usage |
|---------|---------|-------|
| `snake_case` | `user_input`, `on_prompt_selected` | Variables, functions, methods |
| `_camelCase` | `_on_connect_clicked` | Private methods (single underscore prefix) |
| `ALL_CAPS` | `GATEWAY_URL`, `PROJECTS_DIR` | Module-level constants |
| `_ALL_CAPS` | `_IDENTITY_CACHE` | Module-level private constants |

### 6.2 Classes

| Pattern | Example | Usage |
|---------|---------|-------|
| `PascalCase` | `GatewayClient`, `LeftPanel` | Class names |
| `_PascalCase` | `_build_agents_list` | Private class methods |

### 6.3 GTK Widgets

| Pattern | Example | Usage |
|---------|---------|-------|
| `_widget_name` | `_user_input`, `_send_btn` | Instance-level widget references (via properties) |
| Local vars | `scroll`, `list_box`, `row` | Local variables in methods |

### 6.4 Files

| Pattern | Example | Usage |
|---------|---------|-------|
| `snake_case.py` | `left_panel.py`, `file_tree.py` | All Python files |

---

## 7. GTK4 Specific Patterns

### 7.1 Import Pattern

Every file that uses GTK must call `gi.require_version()` **before** importing Gtk:

```python
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
```

### 7.2 Widget Construction

```python
# Correct — pass kwargs to __init__
label = Gtk.Label(label="Hello", xalign=0)

# Correct — use setter methods
label.set_margin_top(8)
label.set_margin_start(8)
```

### 7.3 ListBox Row Activation

GTK4 `Gtk.ListBox` fires `row_activated` on **single click** by default. To require **double-click**:

```python
list_box.set_activate_on_single_click(False)
```

### 7.4 TreeView / TreeStore

`Gtk.TreeView` + `Gtk.TreeStore` is used for the Projects directory browser (`FileTree`). Pattern:

```python
# Column setup
renderer = Gtk.CellRendererText()
column = Gtk.TreeViewColumn(title, renderer, text=column_index)
tree_view.append_column(column)

# Store structure: (name, full_path, is_dir, is_expanded)
# Use None as parent to append top-level rows
self._store.append(None, ['item_name', '/path', True, True])
# Use iter as parent for children
self._store.append(parent_iter, ['subitem', '/path/sub', True, True])
```

### 7.5 Paned (Resizable Split)

```python
paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
paned.set_start_child(top_widget)
paned.set_end_child(bottom_widget)
paned.set_resize_start_child(True)
paned.set_resize_end_child(True)
paned.set_shrink_start_child(False)
paned.set_shrink_end_child(False)
paned.set_position(400)
```

### 7.6 Thread Safety

**All GTK operations must happen on the main thread.** Gateway client runs in a background thread. To safely call GTK from the gateway thread:

```python
from gi.repository import GLib
GLib.idle_add(callback_function, *args)
```

`GLib.idle_add()` schedules the callback to run on the next GTK idle cycle.

---

## 8. Rules for Adding New Code

### 8.1 Before Writing Any Code

1. **Identify ownership:** Which module owns this data or behavior?
2. **Find existing patterns:** Has something similar been done? Copy the pattern.
3. **Determine the right module:** Does it belong in `models/`, `utils/`, `ui/views/`, or a new module?
4. **Trace the wiring:** Where will this be called from? Verify the call path exists.

### 8.2 Adding a New UI Component

1. Create a new file in `ui/views/`
2. Component accepts callbacks at construction or via setters
3. Component **never** imports other UI components directly
4. Component exposes widget references via properties when needed
5. Update `ui/window.py` to create and wire the component

### 8.3 Adding a New Model

1. Create a new file in `models/`
2. Export it from `models/__init__.py`
3. Model is a plain Python class — no GTK imports
4. Document the class in this document

### 8.4 Adding a Utility

1. Add to an existing utility file in `utils/` if related, or create a new file
2. Keep utilities **stateless** when possible
3. If a utility needs to be stateful, it probably belongs in `models/`

### 8.5 Testing

Tests live in `tests/` — one file per module being tested.

**Run tests:**
```bash
cd /home/q/projects/crabcakes
pytest              # auto-discovers tests/ via pytest.ini
```

**Test coverage (descriptions for key tests — see Section 12 for full inventory):**
- `tests/test_architecture.py` — AST guard: handler isolation, models/gateway layer separation, public API existence
- `tests/test_favorites.py` — favorites persistence: missing file, empty list, round-trip, JSON corruption
- `tests/test_prompts_handler.py` — PromptsHandler: search/filter, favorites sort, last-used timestamps
- `tests/test_agent_list_handler.py` — AgentListHandler: initials, colors, sorting, callbacks
- `tests/test_agents.py` — AgentManager: edge cases, unknown inputs, clear/reregister
- `tests/test_chat_handler.py` — ChatHandler: send, fan-out, routing, tab switching
- `tests/test_gateway_handler.py` — GatewayHandler: connect lifecycle, thread safety, GTK dispatch
- `tests/test_media_handler.py` — MediaHandler: STT toggle, improve API, GLib dispatch
- `tests/test_projects.py` — file I/O: missing files, empty dirs, JSON corruption, round-trip
- `tests/test_improve.py` — API calls: missing key, HTTP errors, malformed responses
- `tests/test_icons.py` — icons.py: import smoke test
- `tests/test_activity_bubbles.py` — ActivityHandler state transitions + activity bubble rendering
- `tests/test_agent_command_handler.py` — AgentCommandHandler: relay, command extraction, chain depth
- `tests/test_agent_defs.py` — agent_defs: load, validate, save, default seeding
- `tests/test_agent_runtime.py` — AgentRuntime: conversation lifecycle, tool loop, streaming
- `tests/test_audit_parser.py` — audit_parser: extract AuditReport from agent messages
- `tests/test_block_parser.py` — block_parser: extract_blocks() segment classification
- `tests/test_bug_fixes.py` — regression tests for specific fixed bugs
- `tests/test_chat_render_handler.py` — ChatRenderHandler: escape, markdown, highlight pipeline
- `tests/test_command_handler.py` — CommandHandler: slash parsing, @mention resolution, dispatch
- `tests/test_command_models.py` — Command, CommandResult, CommandRegistry data models
- `tests/test_config.py` — agent config loading, provider resolution
- `tests/test_context.py` — system prompt builder, file context, .gitignore parsing
- `tests/test_conversation.py` — Conversation, Message, ToolCall data models + token estimation
- `tests/test_crabcard_parser.py` — crabcard block extraction from agent messages
- `tests/test_crabwatch_handler.py` — CrabWatchHandler: filesystem event debouncing
- `tests/test_create_project.py` — project creation workflow
- `tests/test_diff_parser.py` — unified diff parsing → FileDiff/ParsedDiff
- `tests/test_enforcement.py` — enforcement tier execution: syntax, tests, lint
- `tests/test_escaping.py` — escape_for_pango(), xml_escape_text()
- `tests/test_feed_card.py` — FeedCardData dataclass + css_class_for_type()
- `tests/test_feed_handler.py` — FeedHandler: card lifecycle, echo suppression, persistence
- `tests/test_feed_store.py` — feed JSON persistence: load/save/append/update
- `tests/test_git_ops.py` — git operations: stage, commit, diff, checkout
- `tests/test_mcp_client.py` — MCP client: asyncio bridge, connection pooling, tool discovery
- `tests/test_mcp_config.py` — MCP server config loading + validation
- `tests/test_mcp_integration.py` — end-to-end MCP tool execution flow
- `tests/test_missing_message_fix.py` — regression test for missing message recovery
- `tests/test_phase4.py` — Phase 4 event card rendering
- `tests/test_project_awareness.py` — project awareness system: .crabcakes/ management
- `tests/test_project_handler.py` — ProjectHandler: tab lifecycle, membership routing
- `tests/test_project_list_handler.py` — ProjectListHandler: project card data
- `tests/test_project_search.py` — project directory search
- `tests/test_prompt_loader.py` — prompt template loading + composition
- `tests/test_quoting.py` — quoted-payload parsing with escapes
- `tests/test_review_log.py` — review log persistence
- `tests/test_review_state.py` — ReviewState dataclass
- `tests/test_routing.py` — AgentRoutingTable: add/remove/lookup
- `tests/test_special_agents.py` — SpecialAgentDef loading, auto-open, auto-add
- `tests/test_streaming.py` — StreamingBubble dataclass
- `tests/test_syntax_highlight.py` — Pygments → Pango highlighter
- `tests/test_tasks.py` — TaskStore CRUD + status transitions
- `tests/test_tools.py` — tool execution: sandbox, blocklist, file ops

**Writing new tests:** aim to break the code, not confirm it works. Test:
- Unknown/missing inputs → what does the code do?
- Empty collections → does it return [] or crash?
- Corrupt data → does it fail gracefully?
- Type errors → does a dict arrive where a string was expected?

**Mock pattern:** use `unittest.mock.patch` to intercept network calls (`urllib.request.urlopen`) or config loading. Pass `GLib=None` to `improve_prompt` to call the callback synchronally in tests.

### 8.6 Handler Pattern — MANDATORY for All New Code

**All new UI logic must follow the handler pattern. No exceptions.**

The `ui/handlers/` directory contains self-contained logic modules extracted from `window.py`. This is not a suggestion — it is the architectural law. Every piece of new behavior must live in a handler, not in `window.py`.

**What goes in a handler:**
- Any logic that responds to user actions (clicks, input, gestures)
- Any logic that processes gateway events, STT results, or external callbacks
- Any logic that coordinates between models, gateway, and UI views
- Any logic involving state transitions (connecting, recording, sending)

**What stays in `window.py`:**
- Creating handler instances and passing them references to shared objects
- Wiring callbacks between handlers (e.g., MediaHandler's STT result → ChatHandler's send)
- Top-level GTK signal connections that delegate immediately to a handler method

**Handler rules:**
1. **One handler per subsystem.** Chat logic → `ChatHandler`. Gateway lifecycle → `GatewayHandler`. Media I/O → `MediaHandler`. New subsystem → new handler file.
2. **Handlers never import other handlers.** If ChatHandler needs something from GatewayHandler, `window.py` wires it via a callback or sync function.
3. **Handlers receive dependencies via constructor or setters.** They do not reach out to find them.
4. **All GTK calls from background threads go through `GLib.idle_add()`.** Every handler docstring must note this.
5. **Handlers own their state.** If a handler needs persistent state, it holds it internally. It does not store state on `window.py`.
6. **Tests go in `tests/test_<handler_name>.py`.** Every handler must have tests. See Section 8.5.

**Adding a new handler — checklist:**
1. Create `ui/handlers/<subsystem>_handler.py`
2. Define the class with constructor accepting needed callbacks/references
3. Add a docstring explaining responsibilities and thread safety
4. Implement logic, dispatching GTK calls via `GLib.idle_add()` where needed
5. Create `tests/test_<subsystem>_handler.py` with full test coverage
6. Wire the handler in `window.py` (`_build()` method)
7. Update this ARCHITECTURE.md (Section 3, Section 11, this section)

**Why this matters:**
`window.py` was once a 2,300-line monolith. The handler pattern exists to prevent that from happening again. Every line of logic added directly to `window.py` is technical debt. Extract it into a handler instead.

### 8.7 Anti-Patterns

| Anti-pattern | Correct approach |
|-------------|-----------------|
| Creating new globals instead of using models | Put state in `models/` |
| Parsing strings to extract data | Use the API that owns the data |
| Importing UI modules in gateway code | Keep layers separate |
| Large monolithic files | Split at natural boundaries |
| Writing code without wiring it | Every piece of code must be called somewhere |
| Skipping verification | Compile + test every checkpoint |
| Adding logic directly to `window.py` | Extract into a handler in `ui/handlers/` |
| A handler importing another handler | Use callbacks wired through `window.py` |
| New UI behavior without a handler file | Create one first, then implement |

---

## 9. CSS and Styling

### 9.1 Single Source of Truth

All CSS for the application lives in **`ui/styles.py`**. No other file may define CSS.

- `ui/styles.py` contains a single `APP_CSS` string constant with all style rules
- `apply_styles()` registers the CSS provider once at app startup
- This function is called from `main.py` before the window is created

### 9.2 Rule: Views Add Classes, Never Define Them

Views use `widget.add_css_class("class-name")` to apply styles. They **never** call `Gtk.CssProvider().load_from_data()` or define CSS inline.

```python
# ✅ Correct — view applies a class name
self._send_button.add_css_class("suggested-action")

# ❌ Wrong — view defines its own CSS
provider = Gtk.CssProvider()
provider.load_from_data(b".my-button { background: red; }")
```

The reasoning: a view decides *what* something is ("this is a send button"), not *how it looks* ("indigo with 6px border-radius"). Appearance belongs in one place.

### 9.3 Naming Conventions for CSS Classes

| Pattern | Example | Usage |
|---------|---------|-------|
| `component-element` | `agent-row`, `code-block-header` | Widget-specific styles |
| `chat-bubble-*` | `.chat-bubble-you`, `.chat-bubble-agent` | Chat message bubbles (Phase 1) |
| `chat-role-*` | `.chat-role-label` | Role label inside bubbles |
| `chat-msg-*` | `.chat-msg-label` | Message content inside bubbles |
| `chat-bubble-pending` | `.chat-bubble-pending` | Optimistic UI state (semi-transparent, Phase 1) |
| `component-element-state` | `agent-row:hover`, `agent-add-btn:hover` | Pseudo-states (in CSS, not the class name) |
| `component-element-variant` | `agent-avatar-3`, `lang-python` | Numbered or named variants |
| `semantic-role` | `suggested-action`, `destructive-action` | Reusable semantic roles (GTK convention) |
| `flat` | `flat` | Ghost/transparent button style |

### 9.4 Adding New CSS

1. Add the CSS rule to the `APP_CSS` constant in `ui/styles.py`
2. Add the corresponding `add_css_class()` call in the view that uses it
3. Document the class name in a comment above the CSS rule
4. If it's a new color, check `models/colors.py` — don't hardcode new palette entries in CSS

### 9.5 CSS Architecture Anti-Patterns

| Anti-pattern | Correct approach |
|-------------|-----------------|
| Inline `load_from_data()` in a view file | Add CSS to `ui/styles.py` instead |
| Multiple CSS providers across the app | One provider, applied once globally |
| Hardcoded hex colors in Python code | Use CSS classes or `models/colors.py` |
| View files containing CSS strings | All CSS in `ui/styles.py` |
| `set_background_color()` or `override_background_color()` | Use CSS classes instead |

### 9.6 Color Palette

The app uses a dark theme. Core colors defined in CSS:

| Role | Color | Variable |
|------|-------|----------|
| Background | `#1a1a20` | `CLR_BG` |
| Panel | `#2a2a35` | `CLR_PANEL` |
| Text | `#e8e8ec` | `CLR_TEXT` |
| Muted text | `#6b6b7a` | `CLR_MUTED` |
| Accent | `#6366f1` | `CLR_ACCENT` |
| Success | `#10b981` / `#6ee7b7` | green tones |
| Danger | `#f43f5e` / `#fda4af` | red tones |
| Warning | `#f59e0b` | amber |

Agent and project avatars use a 10-color round-robin palette defined in `models/colors.py`.

---

## 10. Environment Variables

| Variable | Default | Purpose |
|---------|---------|---------|
| `CRABCAKES_DEBUG` | (unset) | Set to `1` to enable `logging.DEBUG` for all modules — agent runtime, handlers, utilities |
| `CRABCAKES_GATEWAY_DEBUG` | (unset) | Set to `1` to enable raw WebSocket message dump in `gateway/client.py` — independent of `CRABCAKES_DEBUG` |
| `CRABCAKES_GATEWAY_URL` | `ws://localhost:18789` | OpenClaw gateway WebSocket URL |
| `CRABCAKES_PROJECTS_DIR` | `~/projects` | Directory containing project folders for the Projects tab |
| `STT_MODEL_SIZE` | `tiny.en` | faster-whisper model size — "tiny.en", "base.en", "small.en", "medium.en", etc. Respects env var or explicit param; defaults to "tiny.en". |

**External binaries required for STT:**
- `arecord` — ALSA audio capture (part of alsa-utils)
- `faster-whisper` Python package (already installed; downloads tiny.en model on first use)
- Model: `Systran/faster-whisper-tiny.en` (~75MB, HuggingFace cache)

---

## 11. Gateway Protocol Reference

**Events arrive as `(event_name, payload_dict)` tuples via `on_event` callback in `GatewayClient`.**

`window._on_ws_event` handles two distinct event structures:

**Lifecycle events** (`payload.stream == "lifecycle"`) — phase at `payload.data.phase`:
```json
{"type":"event","event":"agent","payload":{"stream":"lifecycle","data":{"phase":"end","livenessState":"working","endedAt":1776790638851}}}
```

**Item-level events** (`payload.stream == "item"`) — phase at `payload.phase`:
```json
{"type":"event","event":"agent","payload":{"stream":"item","data":{"itemId":"tool:call_function_...","phase":"end","kind":"tool"}}}
```

**Routing table:**

| event | stream | phase location | Meaning |
|-------|---------|----------------|---------|
| `"chat"` | — | `payload.state=final` | Complete response — route to ChatHandler |
| `"chat"` | — | `payload.state=delta` | Streaming delta — accumulate in bubble |
| `"agent"` | `"lifecycle"` | `payload.data.phase=start` | Agent started reasoning |
| `"agent"` | `"lifecycle"` | `payload.data.phase=end` | Agent finished — trigger idle |
| `"agent"` | `"lifecycle"` | `payload.data.phase=error` | Agent error — reset |
| `"agent"` | `"item"` | `payload.phase` (kind=`tool`) | Tool call complete |
| `"agent"` | `"item"` | `payload.phase` (kind=`message`) | Message delta |

**Phase routing logic:**
```python
stream = payload.get("stream", "")
if stream == "lifecycle":
    phase = payload.get("data", {}).get("phase", "")
else:
    phase = payload.get("phase", "")
```

**Snapshot structure (`get_snapshot()`):**
```python
{
  "health": {
    "agents": [
      {
        "agentId": "qat",
        "name": "Qat",
        "sessions": {
          "recent": [
            {"key": "agent:qat:main", "lastActive": 1234567890}
          ]
        }
      }
    ]
  }
}
```

**Project membership storage:**
- Path: `~/.config/crabcakes/projects/<project-name>/members.json`
- Format: `["agent:qat:main", "agent:qtr:telegram:direct:7478874934", ...]`
- Each entry is a session key string

---

## 12. Provider Resolution & API Caller

As of PHASE-10, the API caller for a provider is resolved via `provider_cfg.caller`, a per-provider attribute persisted in `providers.yaml`. The runtime's `_resolve_caller_key(provider_cfg, model)` helper returns the explicit `caller` if set, otherwise derives it from `provider_cfg.default_model.split("/")[0]`, and finally falls back to `model.split("/")[0]`. This decouples the model-string prefix structure (which is the API's contract — e.g. `openrouter/owl-alpha` for OpenRouter) from the caller's identity (which is one of the five built-in implementations: `openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

**Resolution priority** (highest to lowest):
1. `provider_cfg.caller` (explicit, lowercased)
2. `provider_cfg.default_model.split("/")[0]` (derivation from configured model)
3. `model.split("/")[0]` (legacy fallback for callers without a `ProviderConfig`)

**Why explicit caller + derivation:** existing providers in `providers.yaml` (pre-PHASE-10) don't have a `caller` field. The derivation fallback (`default_model.split("/")[0]`) handles migration transparently — all 6 of the user's existing providers have slashed `default_model` values, so the runtime resolves the correct caller without requiring a re-save.

**Why the model string is still slashed:** the API caller functions receive the model string verbatim. OpenRouter expects `vendor/model` (e.g. `openrouter/owl-alpha`); Anthropic expects a bare model name (e.g. `claude-3-5-sonnet`); OpenAI expects a bare model name. The slash in the model string is the API's contract, not a caller identifier. The runtime's `_resolve_agent_model` handler (P4) preserves the model string exactly as configured when `default_model` contains a slash.

**Streamer resolution:** the streaming path (`_call_llm_streaming` callers) uses the same `_resolve_caller_key` helper to look up the streamer function in `_PROVIDER_STREAMERS`. The streamer keys mirror the caller keys (`openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

**Test Connection:** the Settings dialog's "Test" button calls `test_connection(base_url, api_key, model, caller=provider.caller)`. The `caller` kwarg (added in PHASE-10) overrides the legacy model-prefix derivation so the test uses the same caller the runtime would use at message-send time.

---

## 13. File Inventory

```
crabcakes/
├── main.py                         # 56 lines — bootstrap only
│
├── gateway/
│   ├── __init__.py                # 6 lines — exports GatewayClient, SnapshotValidationError
│   └── client.py                 # ~486 lines — GatewayClient (threaded WebSocket + v3 device auth)
│
├── models/
│   ├── __init__.py               # exports 28 symbols: AgentManager, AgentRoutingTable, Command/Result/Registry,
│   │                               #   FeedCardData, StreamingBubble, ActivityBubble, ToolStatus,
│   │                               #   Conversation/Message/MessageRole/ToolCall/ToolCallStatus,
│   │                               #   ConversationSnapshot/SnapshotMessage, ReviewState, TeamMember/ProjectTeam,
│   │                               #   Task/TaskStore/TASK_STATUS_LABELS/PRIORITY_LABELS, next_agent_color, reset_color_indices
│   ├── activity.py               # ActivityBubble dataclass — activity bubble state
│   ├── agents.py                 # AgentManager — session_key → name, color, sessions
│   ├── colors.py                 # AGENT_COLORS palette + round-robin
│   ├── command.py                # Command, CommandResult, CommandRegistry (Phase 7)
│   ├── conversation.py           # MessageRole, ToolCall, Message, Conversation + summary-on-trim + token breakdown
│   ├── conversation_snapshot.py  # ConversationSnapshot, SnapshotMessage — conversation snapshot data
│   ├── feed_card.py              # FeedCardData + css_class_for_type() (Phase 5)
│   ├── review_state.py           # ReviewState dataclass (Phase 7)
│   ├── routing.py                # AgentRoutingTable (session_key → project_name)
│   ├── streaming.py              # StreamingBubble dataclass (Phase 5)
│   ├── task.py                   # Task + TaskStore + labels (Phase 3)
│   └── team.py                   # TeamMember, ProjectTeam — project team membership data
│
├── agent/
│   ├── __init__.py               # exports: AgentRuntime, AgentConfig, EnforcementConfig, LLMProviderConfig,
│   │                              # SpecialAgentDef, SPECIAL_AGENTS, ToolDefinition, ToolResult,
│   │                              # build_system_prompt, build_file_context, check, get_api_key, get_special_agents,
│   │                              # load_agent_config, reload_registry
│   ├── config.py                 # ~249 lines — LLMProviderConfig, EnforcementConfig, AgentConfig, load_agent_config(), get_api_key()
│   ├── context.py                # ~437 lines — build_system_prompt, build_file_context, _read_crabcakes_docs + .gitignore parsing
│   ├── enforcement.py            # ~761 lines — Post-write verification: 3-tier checks + per-project override + TestConfig + venv detection
│   ├── kb_lookup.py              # KB lookup — cosine-sim retrieval over indexed KB chunks (Auxilium Tier 1)
│   ├── runtime.py                # ~1420 lines — AgentRuntime: tool loop, enforcement hook, stuck detection, providers, streaming, cost
│   ├── special_agents.py         # ~182 lines — SpecialAgentDef, get_special_agents(), reload_registry()
│   └── tools.py                  # ~892 lines — 8 tools: read_file, write_file, edit_file, exec_command, list_files, search_files, web_search, web_fetch
│
├── scripts/
│   └── rebuild_kb_index.py       # offline indexer — builds knowledge/.index/ from knowledge/*.md (Auxilium Tier 1)
│
├── ui/
│   ├── __init__.py               # 1 line
│   ├── toolbar.py                # ~112 lines — Toolbar widget (connect button + status label)
│   ├── styles.py                 # ~1045 lines — APP_CSS constant + apply_styles()
│   ├── window.py                 # ~693 lines — MainWindow — assembles all components, wires callbacks. Business logic extracted to handlers (see Section 3.6). Most recent extractions: ConnectionSyncHandler (§3.21y) and ForwardHandler (§3.21z).
│   ├── handlers/
│   │   ├── __init__.py           # 0 lines — package marker
│   │   ├── activity_handler.py   # ~610 lines — 6-state activity machine + two-phase progress (Phase 6)
│   │   ├── agent_builder_handler.py # ~199 lines — AgentBuilderHandler — agent create/edit form + delete_agent_with_confirmation() (Phase 5)
│   │   ├── agent_command_handler.py # ~546 lines — agent response command parser + relay (Phase 6.2)
│   │   ├── agent_list_handler.py # ~126 lines — agent card data (initials, colors, sorting)
│   │   ├── agent_runtime_handler.py # ~867 lines — AgentRuntime UI bridge: conversation lifecycle, tool approval, reload_agents_and_mcp() (Phase 5)
│   │   ├── chat_handler.py       # ~853 lines — send, fan-out, routing, special agent routing, tab switching
│   │   ├── chat_render_handler.py # ~770 lines — escape + markdown + highlight + bubble pipeline
│   │   ├── collab_handler.py     # Collaboration commands: ask, delegate, stop, tell (Phase 7)
│   │   ├── command_handler.py    # ~601 lines — slash-prefix command parser + @mention resolution; auto-registers 21 commands on init (Phase 7)
│   │   ├── connection_sync_handler.py # ~173 lines — ConnectionSyncHandler — post-connect wiring of live GatewayClient + AgentManager into 16 dependents (Phase 3a extraction)
│   │   ├── crabwatch_handler.py  # ~364 lines — CrabWatchHandler — Gio.FileMonitor filesystem watcher (Phase 5)
│   │   ├── feed_handler.py       # ~932 lines — FeedHandler — feed card lifecycle, persistence, add_audit_report_card() (Phase 5)
│   │   ├── forward_handler.py    # ~194 lines — ForwardHandler — agent-to-agent popover + routing + forwarded bubble (Phase 3b extraction)
│   │   ├── gateway_handler.py    # ~233 lines — connect, agents, lifecycle (Phase 2)
│   │   ├── input_toolbar_handler.py # ~395 lines — InputToolbarHandler — find/replace, spell check, word count logic
│   │   ├── media_handler.py      # ~99 lines — STT + improve (Phase 4)
│   │   ├── project_handler.py    # ~551 lines — active project + agent-to-project routing + session switching
│   │   ├── project_list_handler.py # ~86 lines — project card data + color round-robin
│   │   ├── prompts_handler.py    # ~208 lines — favorites, search, last-used, load_prompt()
│   │   ├── review_handler.py     # ~400 lines — review session lifecycle: checkpoint/check/accept/reject (Phase 7)
│   │   └── session_handler.py    # ~164 lines — SessionHandler — session switching commands (Phase 7)
│   │   ├── connection_sync_handler.py  # post-connect wiring
│   │   ├── forward_handler.py     # 17 tests (Phase 3b extraction)
│   └── views/
│       ├── __init__.py           # 1 line
│       ├── activity_drawer.py     # NEW (SPEC-activity-drawer) — collapsible activity event panel
│       ├── agent_builder.py      # AgentBuilderDialog — modal dialog for creating/editing agents
│       ├── chat_bubble.py        # ~1015 lines — build_role_bubble() factory (Phase 1 + 2 block-level)
│       ├── chat_input_toolbar.py # ~549 lines — ChatInputToolbar — find/replace bar + spell check popover (view only)
│       ├── diff_card.py          # ~356 lines — build_file_diff_card(), build_diff_summary_card() (Phase 7)
│       ├── feed_card.py          # ~581 lines — feed_card widget factory (Phase 5)
│       ├── feed_tab.py           # ~167 lines — FeedTab — project feed card container (view only)
│       ├── feedbar.py            # ~124 lines — FeedBar + progress bar (Phase 6)
│       ├── file_tree.py          # ~439 lines — FileTree (TreeView directory browser)
│       ├── left_panel.py         # ~838 lines — LeftPanel (Prompts/Agents/Projects notebook)
│       ├── left_progress.py      # 0 lines — stub placeholder
│       ├── main_content.py       # ~857 lines — MainContent (tabs + input + review bar integration)
│       ├── review_bar.py         # ~166 lines — ReviewBar widget: dropdown + action buttons (Phase 7)
│       └── session_menu.py       # ~212 lines — right-click session/project switcher popover
│
└── utils/
    ├── __init__.py               # 1 line
    ├── agent_defs.py             # ~570 lines — agent definition I/O: load, validate, save, list from agents/*.yaml
    ├── audit_parser.py           # extract_audit_reports() — parse ## Audit Report sections
    ├── block_parser.py           # ~158 lines — extract_blocks() — block segment extraction (Phase 2)
    ├── config.py                 # ~72 lines — config path helpers + COMMAND_PREFIX
    ├── conversation_store.py     # Snapshot creation — build ConversationSnapshot from messages + git diffs
    ├── crabcard_parser.py        # extract_crabcards() — parse ```crabcard blocks into FeedCardData (Phase 5)
    ├── diff_parser.py            # ~321 lines — parse_diff() → FileDiff/ParsedDiff (Phase 7)
    ├── escaping.py               # ~182 lines — escape_for_pango(), xml_escape_text()
    ├── favorites.py              # ~60 lines — favorites persistence (favorites.json)
    ├── feed_store.py             # Feed JSON persistence — load/save/append/update feed.json
    ├── feedback_processor.py     # Audit report file I/O — write to agent bug journals + role resolution
    ├── git_ops.py                # ~147 lines — GitPython wrapper: stage/commit/diff/checkout/log/status/push (Phase 7)
    ├── icons.py                  # ~165 lines — Gdk.Texture SVG rendering (avatars + folder icons)
    ├── image_utils.py            # convert_logo_to_icons() — JPG to multi-size PNG for app icons
    ├── improve.py                # ~160 lines — improve_prompt() MiniMax API (template mode + {{USER_INPUT}})
    ├── markdown.py               # ~220 lines — format_markdown() — inline markdown → Pango (Phase 1)
    ├── mcp_client.py             # ~488 lines — MCP asyncio-threading bridge, stdio transport, tool discovery/call
    ├── mcp_config.py             # ~240 lines — MCP server configuration loader with YAML/JSON schema validation
    ├── project_awareness.py      # ~641 lines — project awareness system managing .crabcakes/ directory per project
    ├── prompt_loader.py          # System prompt template loader — loads/fills/composes prompts/system/*.md
    ├── prompts.py                # ~25 lines — load_prompts() — reads .md from prompts/
    ├── projects.py               # ~77 lines — load_projects(), scan_directory(); load_members()/save_members() deprecated
    ├── quoting.py                # ~50 lines — _parse_quoted_payload() — escape-aware quoted-payload parsing
    ├── review_log.py             # Review log persistence — append/retrieve entries per project
    ├── spellcheck.py             # Spell check engine — Enchant-based detection + suggestions
    ├── stt.py                    # ~182 lines — STTEngine (faster-whisper push-to-talk; respects STT_MODEL_SIZE env var)
    ├── syntax_highlight.py       # ~164 lines — highlight() — Pygments → Pango markup (Tokyo Night)
    └── workflow_state.py         # Workflow state tracker — manages .crabcakes/workflow.md per project

prompts/                         # System prompt templates for agent runtime
    └── system/
        ├── cc-implementation.md
        ├── claude-12rules.md
        ├── code-review.md
        ├── coder.md               # Coder agent system prompt
        ├── collab.md              # A2A collaboration protocol
        ├── crabcakes-commands.md  # Slash command reference
        ├── crabcakes-context.md   # Platform context for agents
        ├── crabcakes.md           # Crabcakes help agent context
        ├── debugger.md            # Debugger agent system prompt
        ├── default.md             # Default system prompt
        ├── improve.md             # Prompt improvement template
        ├── mcp-phase-b.md         # MCP Phase B implementation spec
        ├── project-awareness.md   # Project context awareness prompt
        └── project-onboarding.md  # Project onboarding prompt

knowledge/                       # User-facing documentation (read by Crabcakes agent via web_fetch)
    ├── agents.md
    ├── commands.md
    ├── configuration.md
    ├── features.md
    ├── gateway.md
    ├── setup.md
    └── troubleshooting.md

tests/                           # 61 files (57 test + 4 support)
    ├── conftest.py
    ├── css_test.py               # CSS variant tests
    ├── format_test.py            # Format tests
    ├── generate_synthetic_conversations.py  # Test data generator
    ├── fixtures/
    ├── test_activity_bubbles.py
    ├── test_activity_drawer.py     # NEW (SPEC-activity-drawer) — drawer view tests
    ├── test_agent_builder_handler.py
    ├── test_agent_command_handler.py  # ~713 lines
    ├── test_agent_defs.py
    ├── test_agent_list_handler.py
    ├── test_agent_runtime.py
    ├── test_agents.py
    ├── test_architecture.py
    ├── test_audit_parser.py
    ├── test_block_parser.py
    ├── test_bug_fixes.py         # Regression tests for specific fixed bugs
    ├── test_chat_handler.py
    ├── test_chat_render_handler.py
    ├── test_command_handler.py
    ├── test_command_models.py
    ├── test_config.py
    ├── test_context.py           # ~329 lines
    ├── test_connection_sync_handler.py  # 28 tests (Phase 3a extraction)
    ├── test_conversation.py      # ~299 lines
    ├── test_crabcard_parser.py
    ├── test_crabwatch_handler.py
    ├── test_create_project.py
    ├── test_diff_parser.py
    ├── test_enforcement.py
    ├── test_escaping.py
    ├── test_favorites.py
    ├── test_feedback_processor.py
    ├── test_feed_card.py
    ├── test_feed_handler.py
    ├── test_feed_store.py
    ├── test_forward_handler.py   # 17 tests (Phase 3b extraction)
    ├── test_gateway_handler.py
    ├── test_git_ops.py
    ├── test_icons.py
    ├── test_improve.py
    ├── test_markdown.py
    ├── test_mcp_client.py        # ~304 lines
    ├── test_mcp_config.py        # ~216 lines
    ├── test_mcp_integration.py   # ~358 lines
    ├── test_media_handler.py
    ├── test_missing_message_fix.py  # Regression test for missing message recovery
    ├── test_phase4.py            # Phase 4 event card rendering
    ├── test_project_awareness.py
    ├── test_project_handler.py
    ├── test_project_list_handler.py
    ├── test_project_search.py
    ├── test_prompts_handler.py
    ├── test_prompt_loader.py
    ├── test_quoting.py
    ├── test_review_log.py
    ├── test_review_state.py
    ├── test_routing.py
    ├── test_special_agents.py
    ├── test_streaming.py
    ├── test_syntax_highlight.py
    ├── test_tasks.py
    └── test_tools.py             # ~334 lines

**Test count:** 61 test files (snapshot as of 2026-05-31: 1680 tests collected; 1632 passed, 1 failed, 0 errors). 22 TestUpdateAgentSession errors resolved in Phase 5; 1 pre-existing failure in test_agents.py::TestLoadAgentDefs::test_does_not_overwrite_existing. Run `pytest --co -q` for current count.

---

## 14. Principles to Preserve

1. **Gateway is foundational.** It must remain independent of UI. Never import `ui/` from `gateway/`.

2. **Models are pure data.** They contain no GTK code. They are the single source of truth.

3. **UI is composed, not inherited.** Components are assembled in `window.py`. Each component is responsible for its own layout.

4. **Callbacks are the communication mechanism.** Components communicate through callbacks, not direct method calls on sibling components.

5. **Checkpoints over shortcuts.** Every significant piece of work should be verified (compiled, wired, tested) before moving on.

6. **Structure before features.** New features must fit the existing structure. If they don't, the structure must be updated — not circumvented.

7. **Comments for humans.** Every non-obvious decision, every non-standard pattern, every important constant — documented.

---

*This document is the law. Violations require discussion with the team before the code is merged.*

---

**For current project status — what's done, what's in progress, what's planned — see [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).**
