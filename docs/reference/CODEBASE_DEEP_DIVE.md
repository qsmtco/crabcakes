# Crabcakes Codebase Deep Dive

> **Status: PARTIALLY STALE (2026-06-12)** — The `ChatControlBar` row in the file tree (`ui/views/ChatControlBar`) was replaced by `ChatInputToolbar` in Phases 1-9 (2026-06-12). All other subsystems described below are still accurate as of 2026-05-09. See `docs/post-mortems/2026-06-12-CHAT-INPUT-TOOLBAR-PHASES-1-7-POST-MORTEM.md` for the migration summary.

> **Status: ACTIVE REFERENCE** — All described subsystems verified present in codebase as of 2026-05-09. Accurate companion to ARCHITECTURE.md.

> **Purpose:** Comprehensive reference for understanding Crabcakes architecture, key subsystems, and what makes it genuinely novel as a "project development environment" vs the IDE+chatbot paradigm.

**Companion:** Start with [ARCHITECTURE.md](./ARCHITECTURE.md) for the authoritative module-level reference.

---

## 1. Architecture Overview

Crabcakes is a GTK4 desktop application that connects to an [OpenClaw](https://github.com/qsmtco/openclaw) gateway via WebSocket. It wraps a multi-agent chat interface around a project directory structure, treating projects as first-class chat rooms with fan-out messaging.

### 1.1 Technology Stack

| Layer | Technology | Role |
|-------|-----------|------|
| UI framework | GTK4 (PyGObject) | Desktop UI |
| Network | `websockets` Python library | Gateway WebSocket client |
| Auth | Ed25519 device auth (`cryptography`) | v3 device-auth handshake |
| Local agents | OpenAI / MiniMax / Anthropic APIs | `agent/runtime.py` — tool-use agent loop |
| Filesystem watch | `Gio.FileMonitor` | CrabWatch filesystem watcher |
| State | Pure Python dataclasses | `models/` — zero GTK deps |

### 1.2 Critical Architectural Rule

```
gateway/  and  models/  must NEVER import from  ui/
```

`gateway/` and `models/` are the foundation. The UI depends on them — not the other way around. This separation enables:
- Testing models without GTK
- Running the local agent runtime without any UI
- Swapping the UI without touching the network layer

### 1.3 Directory Structure (Simplified)

```
crabcakes/
├── main.py                  # GtkApplication entry point — thin
├── gateway/                 # WebSocket client (network, auth, event dispatch)
├── models/                  # Pure data: agents, routing, feed cards, tasks, commands
├── agent/                   # Local agent runtime (LLM API, tool loop, enforcement)
├── ui/
│   ├── window.py           # Composition root — all handlers wired here
│   ├── handlers/           # One file per subsystem (chat, project, gateway, feed, ...)
│   └── views/              # GTK widget factories (no business logic)
└── utils/                  # Pure Python I/O: prompts, projects, markdown, git_ops
```

---

## 2. Key Subsystems

### 2.1 Project Feed System (`models/feed_card.py`, `utils/feed_store.py`, `utils/crabcard_parser.py`, `ui/handlers/feed_handler.py`, `ui/handlers/crabwatch_handler.py`)

The project feed is a persistent, scrollable activity log for a project. It is the **primary output surface** for agent work — not just chat messages, but structured events that can be reviewed and accepted/rejected.

#### Feed Card Data Model (`models/feed_card.py`)

`FeedCardData` is a pure Python dataclass — no GTK, no git, no network. It represents one activity entry in the feed:

```
FeedCardData
├── card_type: git_commit | diff | file_created | file_modified | file_deleted |
│             dir_created | dir_deleted | agent_action | task | system
├── source:    agent | system | git | crabwatch
├── title:     str  (short description)
├── body:      str  (detail text or diff content)
├── author:    str
├── timestamp:  datetime
├── project_name: str
├── file_path:  str | None
├── additions:  int | None
├── deletions:  int | None
├── task_id:    str | None
├── metadata:   dict  (arbitrary extensible context)
├── conversation_snapshot: ConversationSnapshot | None  (captured at card creation)
├── card_id:    str | None  (assigned by FeedHandler)
├── reviewed:   bool
└── accepted:   bool | None  (True=accepted, False=rejected, None=pending)
```

#### Feed Persistence (`utils/feed_store.py`)

Feed cards are stored in `.crabcakes/feed.json` per project directory. This is a plain JSON file — readable by external tools, version-control-friendly, and project-local (not in a global app config).

```
<project_path>/.crabcakes/feed.json
```

Operations:
- `load_feed(path)` → `list[FeedCardData]`
- `save_feed(path, cards)` → writes full list (not append-only; feed.json is the canonical store)
- `append_feed_card(path, card)` → load → append → save
- `update_feed_card(path, card_id, updates)` → find → update → save

#### Crabcard Parser (`utils/crabcard_parser.py`)

Agents emit structured cards by including ` ```crabcard ` blocks in their plain text chat output:

```
```crabcard
type: file_created
title: Created src/main.py
file: src/main.py
---
Body content (description, diff, etc.)
```
```

`extract_crabcards(text, project_name, agent_name)` parses these out:
- Returns `(cleaned_text, cards)` where cleaned_text has the crabcard blocks replaced by placeholder markers (`\x00CRABCARD_REF:0\x00`)
- Placeholders are detected by `build_role_bubble()` in `chat_bubble.py` and swapped for inline `📋` reference widgets that link to the Feed tab
- `FeedCardData` objects from parser have `source="agent"` and carry the full crabcard body as `card.body`

#### CrabWatch Filesystem Watcher (`ui/handlers/crabwatch_handler.py`)

CrabWatch uses GTK-adjacent `Gio.FileMonitor` (no external deps) to watch the entire project directory tree recursively. It fires `FeedCardData` events for:

| Event | Card type |
|-------|-----------|
| File created | `file_created` |
| File modified | `file_modified` |
| File deleted | `file_deleted` (with atomic-replace detection: delays 500ms to catch CREATE-after-DELETE within that window, merging into `file_modified`) |
| Directory created | `dir_created` |
| Directory deleted | `dir_deleted` |

Key design: **debouncing** — rapid successive events on the same path within 200ms are batched into one event. This prevents feed spam during editor auto-save or git operations.

#### FeedHandler Orchestration (`ui/handlers/feed_handler.py`)

`FeedHandler` is the central coordinator for all feed activity:

```
FeedHandler
├── _cards: dict[card_id → FeedCardData]     (in-memory store)
├── _card_widgets: dict[card_id → Gtk.Widget]  (built widgets)
├── _project_cards: dict[project → [card_ids]] (index, newest first)
├── _project_paths: dict[project → path]       (for persistence)
└── _loading: bool                            (suppresses feed.json writes during load)
```

Card lifecycle:

```
1. add_card(card_data)
   ├── Assign card_id (uuid4)
   ├── Store in _cards + _project_cards index
   ├── Create ConversationSnapshot via idle_add deferred (reads chat box after bubble appended)
   ├── Build widget via build_feed_card() (pure view, no shared state)
   ├── Store widget in _card_widgets
   ├── idle_add → _feed_tab.append_card(widget)  (prepend = newest at bottom)
   ├── Persist in background thread → feed_store.append_feed_card()
   └── Return card_id
```

Button actions (Review / Accept / Reject):
- Each button gets a closure callback capturing `card_id`
- Accept → `feed_store.update_feed_card(card_id, {accepted: True})` + badge widget update
- Reject → same with `accepted: False`
- Review → toggle expandable context panel (conversation snapshot or diff)

---

### 2.2 Agent Management (`models/agents.py`, `models/colors.py`, `models/routing.py`)

#### AgentManager (`models/agents.py`)

```
AgentManager
├── _agent_names:   dict[session_key → display_name]  (session_key is sticky — first register wins)
├── _agent_colors:  dict[name → hex_color]            (round-robin assignment)
└── _agent_sessions: dict[name → list[session_key]]   (multi-session support per agent)
```

Key methods:
- `register(session_key, agent_name)` — first registration is sticky; later calls with same key ignored
- `get_primary_session(agent_name)` — prefers `:main` suffix, else first registered
- `get_color(agent_name)` — returns round-robin assigned hex color
- `clear()` — clears session tracking but preserves colors (agents keep colors on reconnect)

#### Color Palette (`models/colors.py`)

`AGENT_COLORS` — 10-color round-robin palette. Two separate counters:
- `next_agent_color()` — for agents (Agents tab)
- `next_project_color()` — for projects (Projects tab)

#### AgentRoutingTable (`models/routing.py`)

Maps `session_key → project_name`. Shared write/read between:
- **Writes:** `ProjectHandler.toggle_agent()` and `ProjectHandler.open_project()`
- **Reads:** `ChatHandler.on_chat_event()` — determines response routing

```
AgentRoutingTable
├── _map: dict[session_key → project_name]
├── add(session_key, project_name)
├── remove(session_key)
├── remove_project(project_name)   ← removes all agents for a project
├── get_project(session_key) → str | None
├── is_routed(session_key) → bool
└── clear()
```

---

### 2.3 Group Chat / Fan-Out (`ui/handlers/chat_handler.py`, `ui/handlers/project_handler.py`)

This is the core messaging flow. The key insight: **project tabs are multi-agent sessions**, while agent tabs are single-agent sessions.

#### Fan-Out Flow

```
User types message in a "project:<name>" tab
        ↓
ChatHandler.on_send()
        ↓
session_key.startswith("project:") ?
        ├── YES: fan-out
        │     ├── Check solo_target (per-project DM override set by right-click menu)
        │     │   ├── solo_target set → send to single member only
        │     │   └── solo_target None → group broadcast to all members
        │     │
        │     └── For each target member:
        │           ├── First message to member: inject project awareness prefix
        │           │   (system prompt composed from prompts/system/ templates)
        │           └── gw.send_message(member_session_key, prefixed_text)
        │           └── Track (project_name, member) in _awareness_sent
        │
        └── NO: direct send
              gw.send_message(session_key, text)
```

#### Solo DM Override (Phase 5)

Right-clicking a project tab label shows a **project-specific menu** (All / member entries) instead of the generic session switcher. This overrides group broadcast for that project:

```
ProjectHandler._solo_targets: dict[project_name → member_session_key | None]
```

- `get_solo_target(project)` → current solo target or None (group)
- `set_solo_target(project, member_session_key | None)` → set/clear solo mode

#### Response Routing

When an agent sends a message back:

```
ChatHandler.on_chat_event(event, payload)
        ↓
session_key = payload.get("sessionKey", "")
        ↓
agent_to_project.get_project(session_key) → project_name | None
        ↓
target_tab = f"project:{project_name}" if project_name else session_key
        ↓
Route to: project tab (if agent is a member) OR agent's personal tab
```

This means agents can reply to a project AND to a personal chat — the routing table disambiguates which tab receives the response.

#### Awareness Prefix

The **awareness prefix** is injected on the first message to each project member. It is a composed system prompt that gives the agent project context:

```
build_awareness_dict(project_path)
        ↓
compose_system_prompt(agent_name, project_path, project_awareness, review_mode)
        ↓
"[System Instructions]\n<composed prompt>\n\n[User Message]\n"
```

Loaded from `prompts/system/` templates (e.g. `prompts/system/coder.md`). Templates are composed per-agent, per-project, and per-review-mode.

---

### 2.4 Project Model (`ui/handlers/project_handler.py`, `utils/projects.py`)

#### ProjectHandler — Owns Active Project State

```
ProjectHandler
├── _active_project_name: str | None
├── _active_project_path:  str | None
├── _agent_to_project:    AgentRoutingTable  (shared with ChatHandler)
├── _solo_targets:         dict[project → session_key | None]
├── _agent_mgr:            AgentManager | None
├── _awareness:            project_awareness module (for .crabcakes/ access)
└── _on_project_opened / _on_project_closed / _on_members_changed: callbacks
```

**Project lifecycle:**

```
open_project(name, path)
  ├── Set _active_project_name, _active_project_path
  ├── _awareness.init_project_config(path, name)  → creates .crabcakes/
  ├── init_workflow(path)  → creates workflow.md if absent
  ├── _lp.refresh_agents_with_project(name)  → show +/− buttons
  ├── _agent_to_project.add(member, name) for each member  → register routing
  └── fire _on_project_opened callbacks
       → MainContent.create_chat_tab("project:<name>", ...)
       → LeftPanel.open_project_view(feed_tab)  → nested Notebook (FileTree + Feed)
       → FeedHandler.on_project_opened(name, path)  → load feed.json
       → CrabWatchHandler.start_watching(path, name)
       → ChatRenderHandler.set_project_name(name)
       → AgentRuntimeHandler.set_active_project(name, path)

close_project(name)
  ├── Clear _active_project_name, _active_project_path
  ├── _agent_to_project.remove_project(name)
  ├── _lp.refresh_agents_with_project(None)  → hide +/− buttons
  └── fire _on_project_closed callbacks
       → FeedHandler.on_project_closed(name)
       → CrabWatchHandler.stop_watching()
       → ChatRenderHandler.set_project_name("")
       → AgentRuntimeHandler.clear_active_project()

toggle_agent(session_key)
  ├── load_members() → check if session_key in members
  ├── If in project: remove; if not: add
  ├── save_members()  → persists to .crabcakes/team.json via awareness module
  ├── Rebuild _agent_to_project routing
  ├── _lp.refresh_agents_with_project(name)  → update +/− button states
  └── fire _on_members_changed callbacks
```

#### Membership Storage

Migrated from legacy `~/.config/crabcakes/projects/<name>/members.json` to the **Project Awareness System** in `.crabcakes/`:
- `.crabcakes/team.json` — team roster (`TeamMember` objects with session_key, name, roles)
- `.crabcakes/workflow.md` — task workflow state
- `.crabcakes/awareness_snapshot.json` — project context snapshot (git state, open files, etc.)

Legacy `load_members()` / `save_members()` in `utils/projects.py` now delegate to `project_awareness.load_team()` / `project_awareness.save_team()`.

---

### 2.5 Local Agent Runtime (`agent/runtime.py`, `agent/tools.py`, `agent/special_agents.py`)

#### Special Agents (`agent/special_agents.py`)

Built-in agents that run **without a gateway connection**:

| Agent | Session key | Tools | Description |
|-------|------------|-------|-------------|
| Coder | `special:coder` | read_file, write_file, edit_file, exec_command, list_files, search_files, web_search, web_fetch | Full read/write agent |
| Debugger | `special:debugger` | read_file, exec_command, list_files, search_files, web_search, web_fetch | Read-only agent |

Each is a `SpecialAgentDef` dataclass: `conv_id_prefix`, `display_name`, `emoji`, `color`, `tools`, `can_write`.

#### AgentRuntime (`agent/runtime.py`)

Core agent loop. Thread-safe via `threading.Lock` and optional `GLib.idle_add` for GTK dispatch.

```
AgentRuntime.send_message(session_key, text)
  → spawns _run_loop in background thread
        ↓
   1. conv.add_user_message(text)
   2. Build API messages (system + history)
   3. Call LLM (streaming or blocking per provider)
   4. Extract text_content + tool_calls
   5. If no tool_calls:
         conv.add_assistant_message(text_content)
         fire on_response_complete callback
         check cost/step limits
   6. If tool_calls:
         For each tool call:
           a. Approval gating for exec_command (dispatch_approval → wait for PM click)
           b. fire on_tool_call_start callback
           c. execute_tool(tool_name, args, project_path, session_key)
           d. Enforcement layer hook (write_file/edit_file → syntax guard, test runner, lint)
           e. fire on_tool_call_result callback
           f. conv.add_tool_result(call_id, result)
         Check cost/step limits → loop or stop
```

**LLM Provider Support:**
- OpenAI (`_call_openai`, `_stream_openai_events`)
- MiniMax (`_call_minimax`, `_stream_minimax_events`)
- Anthropic (`_call_anthropic`, `_stream_anthropic_events`)

Each provider has both a blocking caller and an SSE streamer. The streamer yields `SSEEvent` namedtuples (`text_delta`, `tool_call_delta`, `tool_call_done`, `done`).

**Conversation Persistence:**
- `create_conversation()` — builds system prompt from templates + tool list
- `_save_conversation_to_disk()` — saves to `~/.config/crabcakes/conversations/<session_key>.json`
- `load_conversation(session_key)` — restores from disk

**Cost Tracking:**
- Cost tables per provider (USD per 1M tokens)
- `_cost_for_model(model, prompt_tokens, completion_tokens)` → USD
- Enforced via `cost_limit` and `step_limit` in config

---

### 2.6 UI Structure

#### MainWindow (`ui/window.py`) — Composition Root

MainWindow does NOT define GTK widgets directly. It is the **single place** where all handlers and views are instantiated and wired together:

```
MainWindow._build()
  ├── Create ChatRenderHandler (shared by MainContent and ChatHandler)
  ├── Create MainContent (right panel — notebook + input)
  ├── Create Toolbar (top bar — connect button + status)
  ├── Create LeftPanel (left sidebar — PAP notebook)
  ├── Create all handlers:
  │   ├── GatewayHandler — owns GatewayClient + AgentManager
  │   ├── ChatHandler — send/fan-out/routing
  │   ├── ProjectHandler — project state + routing table writes
  │   ├── FeedHandler — feed card lifecycle
  │   ├── CrabWatchHandler — filesystem watcher
  │   ├── AgentRuntimeHandler — special agent runtimes
  │   ├── ActivityHandler — 6-state activity machine
  │   ├── MediaHandler — STT + improve
  │   ├── CommandHandler — backtick command parsing
  │   ├── ReviewHandler — git-backed code review
  │   ├── TaskHandler, CollabHandler, SessionHandler — Phase 7 commands
  │   └── AgentListHandler, PromptsHandler, ProjectListHandler — data handlers
  ├── Wire callbacks between handlers (set_*_handler, set_*_callback)
  └── Register all commands with CommandHandler
```

#### LeftPanel (`ui/views/left_panel.py`)

Three-tab notebook (PAP = Prompts / Agents / Projects):

```
LeftPanel
├── Prompts tab — PromptsHandler-backed list
│   ├── Search entry → PromptsHandler.search()
│   ├── Favorites (★) → toggle → persist → refresh
│   ├── + new prompt row → file picker → import
│   └── Double-click → load into chat input
│
├── Agents tab — AgentListHandler-backed avatar cards
│   ├── Colored circle avatar (initials + color)
│   ├── Agent name + source tag (Openclaw/Crabcakes) + session count
│   ├── +/− button (project context only)
│   │   └── Calls toggle_agent_callback(session_key) → ProjectHandler.toggle_agent()
│   └── Right-click → session switcher menu (show_session_menu)
│
└── Projects tab — Gtk.Stack switching between:
    ├── "picker" page — FileTree (always present, stable parent)
    │   └── Double-click project → open_project_view()
    └── "open" page — nested Notebook:
        ├── "File Tree" sub-tab — FileTree reparented from Stack picker
        └── "Feed" sub-tab — FeedTab
```

When a project opens: FileTree moves from Stack "picker" page → nested Notebook "File Tree" tab. This is the **key UX pattern** — the same FileTree widget is reparented between two container contexts without being destroyed.

#### MainContent (`ui/views/main_content.py`)

Right panel — chat notebook + user input:

```
MainContent
├── Gtk.Paned (vertical split)
│   ├── Top (start child):
│   │   ├── Gtk.Notebook (chat tabs)
│   │   │   ├── Tab per session (agent or project)
│   │   │   │   ├── Tab label: [dot] [name] [•] [channel] [×]
│   │   │   │   ├── Chat overlay: ScrolledWindow + chat box + scroll-to-bottom button
│   │   │   │   ├── Tab label dot: green (idle) / yellow (unread)
│   │   │   │   ├── Right-click → session switcher OR project solo-DM menu
│   │   │   │   └── Middle-click / × button → close tab
│   │   │   └── Project settings bar (floating over notebook, above tab row)
│   │   └── ChatControlBar
│   └── Bottom (end child):
│       ├── ScrolledWindow → TextView (user input)
│       └── Button bar: [Prompt] [Improve ✦] [Send ↵]
```

**Unread tab tracking:**
- `increment_unread(session_key)` → yellow dot on tab label
- `clear_unread(session_key)` → green dot
- `_update_tab_dot()` uses `_session_key` attribute stored directly on `tab_label_box` (not via GTK child ordering, which is unreliable in GTK4)

#### Chat Render Pipeline

```
ChatHandler.on_send() or on_chat_event()
        ↓
ChatRenderHandler.render_sync(role, text, session_key, on_forward_click, tab_key)
  OR  ChatRenderHandler.render_async(role, text, session_key, on_bubble_ready, on_forward_click, agent_name)
        ↓
extract_blocks(text)  → split into typed segments
  ├── text: plain paragraph
  ├── code: fenced code block (lang detected)
  ├── quote: > blockquote
  ├── terminal: $ command lines
  ├── heading: # heading
  └── task: - [ ] / - [x]
        ↓
For each segment:
  escape_for_pango(text)  → protect Pango markup tags, escape unknown ones
        ↓
  format_markdown(text)    → inline markdown → Pango markup (bold/italic/code/links)
        ↓
  highlight(code, lang)    → Pygments → Pango markup with syntax colors (graceful fallback)
        ↓
  build_role_bubble(role, processed_segments)
        ↓
  GTK Box widget returned → appended to chat_box
```

---

## 3. The Project-as-Chat Paradigm in Practice

### One Complete Flow: User Opens a Project → Types → Agents Respond → Feed Card Appears

```
1. User double-clicks "manopea" directory in FileTree
        ↓
   LeftPanel._file_tree emits on_project_opened("manopea", "/home/q/projects/manopea")
        ↓
   ProjectHandler.open_project("manopea", "/home/q/projects/manopea")
        ├── Sets _active_project_name, _active_project_path
        ├── init_project_config() → creates .crabcakes/ if absent
        ├── load_members("manopea") → loads team roster
        ├── _agent_to_project.add(member, "manopea") for each member  ← routing table populated
        ├── refresh_agents_with_project("manopea") → agents tab shows +/− buttons
        └── fires _on_project_opened callbacks:
              ├── MainContent.create_chat_tab("project:manopea", "Project: manopea")
              │        └── Creates new tab in chat notebook with project tab label
              ├── LeftPanel.open_project_view(feed_tab)
              │        └── Reparents FileTree → nested Notebook (FileTree + Feed sub-tabs)
              ├── FeedHandler.on_project_opened("manopea", "/home/q/projects/manopea")
              │        ├── load_feed() → load .crabcakes/feed.json → render cards
              │        └── sets _active_project_name
              ├── CrabWatchHandler.start_watching("/home/q/projects/manopea", "manopea")
              │        └── Gio.FileMonitor recursive tree monitoring starts
              ├── ChatRenderHandler.set_project_name("manopea")
              │        └── sets crabcard parser context
              └── AgentRuntimeHandler.set_active_project("manopea", "/home/q/projects/manopea")

2. User types "fix the auth bug" in the project tab input, presses Send
        ↓
   ChatHandler.on_send()
        ├── session_key = "project:manopea"
        ├── buf.get_text() → "fix the auth bug"
        ├── session_key.startswith("project:") → YES
        ├── project_name = "manopea"
        ├── Check _project_handler.get_solo_target("manopea") → None (group broadcast)
        ├── members = ProjectHandler.get_project_members("manopea")
        │        └── [agent:qtr:..., agent:qat:..., special:coder]
        ├── For each member, send prefixed message via gateway:
        │     gw.send_message("agent:qtr:...", awareness_prefix + "fix the auth bug")
        │     gw.send_message("agent:qat:...", awareness_prefix + "fix the auth bug")
        │     AgentRuntimeHandler.send_to_special_agent("special:coder", "fix the auth bug")
        │           └── AgentRuntime._run_loop → LLM → tool calls → write_file → exec_command
        │                 └── If write_file used with enforcement enabled:
        │                     enforcement.check() → syntax guard → test runner → lint
        │                 └── Fire tool_call event → ActivityHandler.on_tool_use()
        │                 └── On completion: on_response_complete → ChatRenderHandler → bubble
        │                 └── If agent emits ```crabcard ``` block:
        │                     ChatRenderHandler._extract_crabcards()
        │                     → FeedHandler.add_card(crabcard_data)
        │                     → FeedCardData → build_feed_card() widget → FeedTab.append_card()
        │                 └── Also: CrabWatch detects file write
        │                     → CrabWatchHandler._on_monitor_event()
        │                     → FeedCardData(source="crabwatch") → FeedHandler.add_card()
        │
        └── Also: ChatHandler.on_chat_event() fires for each agent's responses:
              ├── session_key = agent:qtr:... → routing.get_project("agent:qtr:...") = "manopea"
              ├── target_tab = "project:manopea"
              ├── Messages appear in the project tab (not agent's personal tab)
              └── Tab dot turns yellow if user is in a different tab (unread tracking)

3. User clicks "Feed" sub-tab in Projects notebook → sees activity cards:
   - crabcard from agent (source="agent"): "Created auth_fix.py"
   - crabwatch card (source="crabwatch"): "Modified auth_fix.py"
   - Can click Review → expand context panel → see conversation snapshot
   - Can click Accept → git add -A && git commit; badge updates to ACCEPTED
   - Can click Reject → git checkout <sha> -- .; badge updates to REJECTED
```

---

## 4. Key Data Structures

### ConversationSnapshot (`models/conversation_snapshot.py`)

Captured at card creation time — contains the last N messages (or diff) for context in the Review panel:

```
ConversationSnapshot
├── snapshot_type: "conversation" | "diff"
├── messages: list[Message(role, text, timestamp)]
├── total_messages: int  (original count before truncation)
├── diff_text: str | None  (for diff type)
└── to_dict() / from_dict()  (JSON serialization for feed.json)
```

### Command (`models/command.py`)

Backtick command parsed from input text:

```
Command
├── name:      str        (e.g. "task", "delegate")
├── args:      str        (everything after agent mention)
├── flags:     dict       (e.g. --priority=high)
├── raw_text:  str        (original text)
├── body:      str        (text after --- marker)
├── source_session_key: str  (who sent it)
├── target_session_key: str | None  (who it's directed at)
├── is_broadcast: bool
└── broadcast_targets: list[str]
```

### ReviewState (`models/review_state.py`)

Per-project review session:

```
ReviewState
├── project_path: str
├── review_mode: "off" | "review"
├── checkpoint_sha: str | None  (git commit SHA of checkpoint)
├── is_dirty: bool              (changes since checkpoint)
└── last_check_files: list[str]
```

---

## 5. What Makes Crabcakes Genuinely Novel

The key distinction: **Crabcakes is a project-centric multi-agent environment**, not a chatbot with a file browser bolted on. The "IDE + chatbot" paradigm (Cursor, Copilot) centers on a single developer working with one AI. Crabcakes centers on a **project** with **multiple agents and one project manager** (PM).

### 5.1 Project as Chat Room

Every project is a **first-class chat room** — not a shared context window, but a persistent multi-agent space with:

- **Fan-out messaging**: one PM message → all project agents receive it simultaneously
- **Membership tracking**: +/− in the Agents tab adds/removes agents from the project roster (`.crabcakes/team.json`)
- **Solo DM override**: right-click project tab → target one agent without broadcasting
- **Response routing**: agents replying to project messages route back to the project tab automatically via `AgentRoutingTable`

This is categorically different from "add files to context" in a chatbot. The project is a live, persistent communication channel.

### 5.2 Feed as Output Surface

The project feed is **not** a chat log — it's a structured activity feed that:

- Captures **agent-authored crabcards** (` ```crabcard ` blocks in plain text output)
- Captures **filesystem events** (CrabWatch via Gio.FileMonitor)
- Is **persistent** (`.crabcakes/feed.json`) and **reviewable** (Accept/Reject with git backing)
- Contains **conversation snapshots** captured at card creation time for audit

In an IDE+chatbot, agent actions are buried in chat history. In Crabcakes, agent actions produce structured, reviewable, persistent records.

### 5.3 Git-Backed Review Layer

Agent writes are not applied directly. The review layer:

```
`review   → git add -A && git commit → checkpoint SHA (ReviewState.checkpoint_sha)
`check    → git diff <sha> → show diff cards in chat
`accept   → git add -A && git commit (new checkpoint)
`reject   → git checkout <sha> -- .  (revert to checkpoint)
```

This is **not** a code review tool bolted on after the fact. It's integrated into the agent's write pipeline — the PM must actively Accept agent writes before they become permanent. Combined with the enforcement layer (syntax guard, test runner, lint as post-write hooks), this is a structured human-in-the-loop workflow.

### 5.4 Local Agent Runtime Without Gateway

The **Crabcake Special Agents** (Coder, Debugger) run locally against LLM APIs with file/exec tools — **no gateway required**. This means:

- You can have a fully functional dev environment for coding tasks without any server infrastructure
- The PM can spin up a Coder agent for a specific project, and it operates with project context (read from project files, write to project directory)
- Tool execution is approval-gated: `exec_command` requires PM to click Approve before running

### 5.5 Enforcement Layer

Post-write verification that runs automatically after every `write_file` / `edit_file`:

- **Syntax guard**: verify syntax is valid Python (compile check)
- **Test runner**: run pytest on the modified file (optional, per-config)
- **Lint check**: run ruff or flake8

Results are appended to the tool result and dispatched as enforcement status events. The PM sees test failures/lint warnings as part of the agent's output, not as a separate CI step.

### 5.6 Architecture Philosophy

Crabcakes is built from the ground up around **layer separation**:
- `models/` — pure data, zero dependencies on anything else
- `gateway/` — network I/O, no UI imports
- `utils/` — pure Python I/O, no GTK, no network
- `agent/` — LLM runtime, no GTK
- `ui/handlers/` — one file per subsystem, no handler imports other handlers
- `ui/views/` — pure widget factories, no business logic

This is not a typical "monolithic GUI app" architecture. The system could be driven headlessly (without GTK) by swapping `ui/views/` for a different rendering layer.

---

## 6. Module Dependency Graph (Simplified)

```
main.py
  └── MainWindow
        ├── Toolbar
        ├── FeedBar
        ├── LeftPanel
        │     ├── FileTree
        │     │     └── ProjectListHandler
        │     ├── FeedTab
        │     ├── PromptsHandler
        │     └── AgentListHandler
        ├── MainContent
        │     ├── ChatNotebook (chat tabs)
        │     └── Input + ButtonBar
        │
        ├── AgentRoutingTable (shared write↔read)
        │
        ├── ChatHandler ←→ ChatRenderHandler
        │                      └── crabcard extraction → FeedHandler
        ├── ProjectHandler ←→ AgentRoutingTable (write)
        ├── FeedHandler ←→ FeedCard + FeedStore
        ├── CrabWatchHandler ←→ FeedHandler (on_event callback)
        ├── GatewayHandler ←→ GatewayClient + AgentManager
        ├── AgentRuntimeHandler ←→ AgentRuntime
        ├── ActivityHandler ←→ FeedBar
        ├── MediaHandler ←→ STTEngine + improve_prompt
        ├── CommandHandler ←→ all command handlers
        ├── ReviewHandler ←→ git_ops + diff_parser
        └── TaskHandler, CollabHandler, SessionHandler
```

---

## 7. Notable Implementation Patterns

### Thread Safety
All GTK calls from background threads go through `GLib.idle_add()` or `GLib.timeout_add()`. The gateway client runs in its own background thread and fires callbacks that dispatch to the main thread.

### Composition Root
`MainWindow._build()` is the single place where all components are instantiated and cross-wired. Handlers never import other handlers — the window passes dependencies explicitly via setters and constructor args.

### Handler Extraction
Business logic is progressively extracted from `MainWindow` into handler modules:
- Phase 1: ChatHandler extracted
- Phase 2: GatewayHandler, PromptsHandler extracted
- Phase 3: ProjectHandler, ActivityHandler extracted
- Phase 4: MediaHandler, ChatRenderHandler extracted
- Phase 5: FeedHandler, CrabWatchHandler, AgentRuntimeHandler extracted
- Phase 7: CommandHandler, ReviewHandler, TaskHandler, CollabHandler, SessionHandler extracted

This follows the "coarse-grained handler per subsystem" pattern described in SOUL.md's operational mode section.

### Reentrancy Guard
`ChatRenderHandler._ReentrancySet` tracks in-flight renders per session_key. Concurrent renders for the same key are skipped to prevent visual glitches from overlapping bubble creation.

### Debouncing / Atomic Replace Detection
CrabWatch batches rapid events (200ms debounce) and detects editor "save" patterns where a file is deleted and recreated within 500ms — merging into a single `file_modified` event rather than separate delete/create.

### Tab Session Tracking
GTK4 page indices are **not stable** across tab additions/removals (GTK reuses and shifts indices). Crabcakes stores `_session_key` as an explicit attribute on the tab label box widget, and uses `_find_page_by_session()` to look up tabs dynamically rather than capturing indices in closures.
