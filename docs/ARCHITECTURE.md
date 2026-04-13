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
- Prompt library: load `.md` files from the `prompts/` directory
- Agent discovery: connect to gateway, discover agents, open chat tabs per agent
- Project browser: browse directories from `CRABCAKES_PROJECTS_DIR` via TreeView
- **Project group chat**: open a project → fan-out message to all project members → responses routed back to the project tab
- **Membership toggles**: +/− buttons in the Agents tab add/remove agents from the active project

**Technology stack:**
- Python 3, GTK4 (via PyGObject)
- WebSocket client (Python `websockets` library)
- Ed25519 device authentication (via `cryptography`)
- Threaded async I/O with GLib main thread dispatch

---

## 2. Directory Structure

```
crabcakes/
├── main.py                    # Entry point — creates CrabcakesApp, runs Gtk.main()
│
├── gateway/                   # WebSocket client — self-contained, no UI dependencies
│   ├── __init__.py           # Exports: GatewayClient only
│   └── client.py              # GatewayClient — threaded WebSocket + v3 device auth
│
├── models/                    # Data models — no UI dependencies
│   ├── __init__.py           # Exports: AgentManager, next_agent_color, reset_color_indices
│   ├── agents.py              # AgentManager — session_key → name, colors, sessions
│   └── colors.py              # Color palettes + round-robin assignment
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
│   │   └── project_handler.py  # ProjectHandler — active project + agent-to-project routing
│   └── views/                 # View widgets
│       ├── __init__.py
│       ├── chat_bubble.py      # build_role_bubble() — chat bubble widget factories (Phase 1)
│       ├── chat_control_bar.py # ChatControlBar — planned stub (update() not wired)
│       ├── feedbar.py          # FeedBar — planned stub (update() not wired)
│       ├── file_tree.py        # FileTree — Gtk.TreeView directory browser
│       ├── left_panel.py       # LeftPanel — PAP notebook (Prompts/Agents/Projects)
│       ├── left_progress.py    # Stub — progress indicator placeholder
│       ├── main_content.py     # MainContent — chat notebook + input + button bar
│       └── session_menu.py     # Right-click session switcher popover
│
└── utils/                     # Pure Python utilities — no GTK, no network
    ├── __init__.py
    ├── escaping.py             # escape_for_pango(), xml_escape_text() — Pango-aware XML escape
    ├── markdown.py             # format_markdown() — inline markdown → Pango Markup
    ├── prompts.py             # load_prompts() — reads .md from prompts/
    ├── projects.py             # load_projects(), scan_directory(), load_members(), save_members()
    ├── favorites.py           # favorites persistence (favorites.json)
    ├── improve.py             # improve_prompt() — MiniMax API for prompt improvement
    ├── stt.py                 # STTEngine — faster-whisper push-to-talk
    └── icons.py               # Gdk.Texture SVG rendering (agent avatars + folder icons)
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

**Color system (`colors.py`):**
- `AGENT_COLORS` — round-robin palette for agents
- `next_agent_color()` — returns next color, advances counter
- `reset_color_indices()` — resets counters on reconnect

**Rules:**
- Models know nothing about GTK widgets.
- Models do not emit signals or have callbacks — they're plain data containers.
- UI code reads from models and responds to changes via callbacks.

### 3.4 `ui/toolbar.py` — Top Bar

**Responsibility:** App-level actions bar (Connect button + status).

**Public API:**
```python
toolbar = Toolbar(on_connect_clicked=callback_fn)
toolbar.update_connection_state("disconnected" | "connecting" | "connected")
```

**Internal state:** Owns the Connect button and status label widgets. Updates them based on calls to `update_connection_state()`.

### 3.5 `ui/styles.py` — Global CSS (169 lines)

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
self._agent_to_project = {}        # {agent_session_key: project_name} — reverse lookup for routing
```

**Phase 4 (MediaHandler) wiring:** `_media_handler` created and wired in `_build()`:
- `on_stt_click` → `_media_handler.on_stt_click`
- `on_improve_click` → `_media_handler.on_improve_click`
- STT transcript append → `_chat_handler.on_send()` via sync callback

**Rules:**
- Window creates all sub-components and passes callbacks to each.
- Window holds references to gateway client and agent manager.
- Window creates and wires handler instances (ChatHandler, etc.) — see `ui/handlers/`.
- Window defines callback handlers not yet extracted (`_on_agent_selected`, `_on_tab_close`, `_on_feed_bar_update`, `_on_file_tree_navigate_back`, `_on_ws_event`, `_on_prompt_selected`, `_on_project_selected`, `_on_connect_clicked`, `_on_input_key_press`, `_on_prompt_clicked`, `_on_improve_clicked`, `_on_stt_partial`, `_on_agent_chat`, `_on_prompt_loaded`, `_on_refresh_ui`).
- Window does NOT define GTK widgets directly — it composes sub-views.

**Phase 1 (ChatHandler) extracted:** `_on_send`, `_on_send_clicked`, `_switch_to_session_tab`, and chat.final routing are now in `ui/handlers/chat_handler.py`.

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
content.set_chat_render_handler(handler)  # inject ChatRenderHandler (called by window.py)
content.set_feed_bar_text(text)  # update the project feed bar
content.set_agent_manager(agent_mgr)  # set AgentManager for session switch lookup
content.close_tabs(page_indices)       # close multiple tabs, reindex once
content.set_on_stt_click(cb)     # STT button clicked
content.set_on_improve_click(cb) # Improve button clicked
content.replace_input_text(text) # replace input with improved text
content.append_stt_text(text)    # append STT partial transcript
content.update_stt_state(state) # "idle" | "recording" — button label/style
```

**Tab close:** Each tab has an × button (top-right of tab label) and responds to middle-click. Both call `_close_tab(page_idx)` which removes the page and re-indexes tracking dicts.

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
| `improve_prompt(text, callback, GLib)` | `improve.py` | Sends text to MiniMax API, calls `callback(improved, error)` with GLib dispatch |
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
```

**Reentrancy guard (`_ReentrancySet`):** Tracks which session keys are currently being rendered. If a render is already in-flight for a key, subsequent calls with that same key are skipped.

**Processing pipeline:**
1. `escape_for_pango(text)` — protect existing Pango markup tags
2. `format_markdown(text)` — convert markdown → Pango inline markup
3. `build_role_bubble(role, text)` — create styled GTK bubble widget

### 3.14e `utils/block_parser.py` — Block Segment Extractor (Phase 2)

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

### 3.14f `utils/syntax_highlight.py` — Pygments → Pango Highlighter (Phase 2)

**Responsibility:** Convert source code to Pango Markup with syntax colors. Degrades gracefully if Pygments unavailable.

**Public API:**
```python
from utils.syntax_highlight import highlight

markup = highlight("def foo(): pass", "python")
# '<span foreground="#c792ea">def</span> ...'
```

**Color scheme:** Tokyo Night dark theme (16 token color mappings). Falls back to `<tt>escaped</tt>` if Pygments unavailable or lexer unknown.

**Security:** All output is HTML-escaped before span wrapping. Safe for untrusted code content.

### 3.14g `ui/views/chat_bubble.py` — Block-Aware Bubble Factory (Phase 2)

**Responsibility:** Build styled GTK bubble widgets for any message content. Handles both inline (Phase 1) and block-level (Phase 2) rendering.

**Phase 1** (unchanged API):
- `build_role_bubble(role, text)` — creates bubble, routes text through extract_blocks internally
- Text segments → `format_markdown()` → bold/italic/code links

**Phase 2 additions:**
- `code` segments → code block widget (syntax-highlighted header bar + copy button + monospace content)
- `quote` segments → left-bordered italic muted box
- `terminal` segments → amber-bordered block with `$` prefixes
- `heading` segments → scaled font sizes (h1–h4)
- `task` segments → checkbox characters (☑/☐)

**Architecture:** Each segment becomes a child widget inside a vertical `Gtk.Box`. The bubble's CSS class (`.chat-bubble-you` / `.chat-bubble-agent`) controls bubble background.


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
- `_agent_to_project` — shared dict mapping `session_key → project_name`; same instance that `ChatHandler` holds (injected by window at construction)

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

def set_on_members_changed(cb: Callable): pass
def set_on_navigate_back(cb: Callable): pass
def close_project(name: str): pass
```
### 3.20 `ui/views/session_menu.py` — Session Switcher Popover

**Responsibility:** GTK popover listing active sessions for an agent. Right-click to switch.

**Public API:**
```python
show_session_menu(parent, agent_name, sessions, on_select)
```

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
        → for member_key in load_members(name): _agent_to_project[member_key] = name
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

### 4.6 Project Membership — Toggle Agent

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

**Test coverage:**
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
| `CRABCAKES_GATEWAY_URL` | `ws://localhost:18789` | OpenClaw gateway WebSocket URL |
| `CRABCAKES_PROJECTS_DIR` | `~/projects` | Directory containing project folders for the Projects tab |
| `STT_MODEL_SIZE` | `tiny.en` | faster-whisper model size — "tiny.en" recommended for English (fastest CPU transcription) |

**External binaries required for STT:**
- `arecord` — ALSA audio capture (part of alsa-utils)
- `faster-whisper` Python package (already installed; downloads tiny.en model on first use)
- Model: `Systran/faster-whisper-tiny.en` (~75MB, HuggingFace cache)

---

## 11. Gateway Protocol Reference

**Events arrive as `(event_name, payload_dict)` tuples via `on_event` callback in `GatewayClient`.**

`window._on_ws_event` handles:

| event | payload state | Meaning |
|-------|---------------|---------|
| `"chat"` | `"final"` | Complete agent response — `payload["sessionKey"]`, `payload["message"]["content"]` |

**Other event types** arrive at `on_event` but are not yet handled (tool calls, approvals). Streaming and typing handled in Phase 3.

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

## 12. File Inventory

```
crabcakes/
├── main.py                     # 44 lines — bootstrap only
├── ARCHITECTURE.md             # This document
│
├── gateway/
│   ├── __init__.py            # 6 lines — exports GatewayClient only
│   └── client.py              # 418 lines — GatewayClient (threaded WebSocket + v3 device auth)
│
├── models/
│   ├── __init__.py            # 13 lines — exports AgentManager, next_agent_color, reset_color_indices
│   ├── agents.py              # 49 lines — AgentManager
│   └── colors.py              # 45 lines — agent + project color palette (round-robin)
│
├── ui/
│   ├── __init__.py            # 1 line
│   ├── toolbar.py             # 83 lines — Toolbar widget
│   ├── styles.py              # 338 lines — APP_CSS constant + apply_styles() (Phase 1 + 2 block CSS)
│   ├── window.py              # 260 lines — MainWindow + handler wiring
│   ├── handlers/
│   │   ├── __init__.py        # 0 lines — package marker
│   │   ├── project_list_handler.py  # 60 lines — project card data + color round-robin
│   │   ├── prompts_handler.py  # 187 lines — favorites, search, last-used, on_prompt_activated
│   │   ├── agent_list_handler.py  # 107 lines — agent card data (initials, colors, sorting)
│   │   ├── chat_handler.py     # 174 lines — send, fan-out, routing
│   │   ├── chat_render_handler.py  # 151 lines — escape + markdown + bubble pipeline (Phase 1)
│   │   ├── gateway_handler.py  # 188 lines — connect, agents, lifecycle (Phase 2)
│   │   ├── media_handler.py   # 89 lines — STT + improve (Phase 4)
│   │   └── project_handler.py  # 181 lines — active project + agent-to-project routing (Phase 3)
│   └── views/
│       ├── __init__.py        # 1 line
│       ├── chat_control_bar.py # 34 lines — ChatControlBar (stub: update() not wired)
│       ├── feedbar.py          # 48 lines — FeedBar (stub: update() not wired)
│       ├── file_tree.py        # 309 lines — FileTree (TreeView directory browser + project card picker)
│       ├── left_panel.py       # 442 lines — LeftPanel (Prompts/Agents/Projects notebook)
│       ├── left_progress.py    # 0 lines — stub placeholder
│       ├── chat_bubble.py      # 274 lines — build_role_bubble() widget factory (Phase 1 + 2 block-level rendering)
│       ├── main_content.py     # 512 lines — MainContent (tabs + input + STT/Improve/feed bar + tab close + bulk close)
│       └── session_menu.py     # 98 lines — right-click session switcher popover
│
└── utils/
    ├── __init__.py            # 1 line
    ├── prompts.py             # 25 lines — load_prompts()
    ├── projects.py            # 75 lines — load_projects, scan_directory, load/save_members
    ├── favorites.py           # 59 lines — favorites persistence (favorites.json)
    ├── escaping.py             # 169 lines — escape_for_pango(), xml_escape_text() — Pango-aware escape (Phase 1)
    ├── markdown.py             # 137 lines — format_markdown() — inline markdown → Pango (Phase 1)
    ├── block_parser.py          # 158 lines — extract_blocks() — block segment extraction (Phase 2)
    ├── syntax_highlight.py      # 164 lines — highlight() — Pygments → Pango markup (Phase 2)
    ├── improve.py             # 141 lines — improve_prompt (MiniMax API)
    ├── stt.py                 # 182 lines — STTEngine (faster-whisper push-to-talk, stop_async pattern)
    └── icons.py               # 165 lines — Gdk.Texture SVG rendering (agent avatars + folder icons)

tests/
    ├── test_block_parser.py     # 158 lines — extract_blocks() unit tests (Phase 2)
    ├── test_syntax_highlight.py # 67 lines — highlight() unit tests (Phase 2)
    ├── test_escaping.py         # 169 lines — escape_for_pango() tests
    ├── test_markdown.py         # 137 lines — format_markdown() tests
    ├── test_chat_handler.py     # ChatHandler tests
    ├── test_chat_render_handler.py  # ChatRenderHandler tests
    └── ...                      # other test files
```



---

## 13. Principles to Preserve

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
