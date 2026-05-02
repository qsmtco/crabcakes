# Project Feed — Specification

**Last updated:** 2026-05-01
**Status:** Implementation in progress
**Depends on:** Existing CrabCakes architecture (see `docs/ARCHITECTURE.md`)
**Supersedes:** `docs/review-layer.md` — the Project Feed IS the review layer. The session-based ReviewBar approach is replaced by the continuous feed.
**Note:** `docs/PROJECT_FEED_CORRECTION.md` is now obsolete — its corrections have been incorporated below.

---

## Overview

The Project Feed is a live, reverse-chronological activity feed embedded in the project tab. Every meaningful event in a project's lifecycle generates a **card** in the feed — git commits, file changes, agent activity, tasks, and more. Each card is color-coded by source type and includes Review/Accept/Reject buttons.

The Project Feed **replaces the original Review Layer's session-based workflow** (ReviewBar, start/end sessions) with a continuous, ambient review experience. Review happens naturally by engaging with cards.

**Key design principle:** Two sources of truth, one feed. Agents proactively create cards via chat output. CrabWatch independently detects file changes and creates system cards. This provides both intentional communication and ground-truth verification.

---

## UX Layout

When a project is opened, the **Projects tab in the Left Panel** transforms from a card picker into a nested notebook with two sub-tabs:

```
┌──────────────────────────────────┐
│ Left Panel — Projects Tab       │
├──────────────────────────────────┤
│ [File Tree]  [Feed]             │  ← Nested notebook sub-tabs
├──────────────────────────────────┤
│                                  │
│  (file tree OR feed cards)       │
│                                  │
└──────────────────────────────────┘
```

| Sub-Tab | Content |
|---------|---------|
| **File Tree** | Project directory browser (existing FileTree widget, reparented into notebook) |
| **Feed** | Reverse-chronological card feed (FeedTab) |

**No project tab is created in MainContent.** The project view lives entirely in the Left Panel's Projects tab. MainContent continues to show agent chat tabs only.

---

## Project Open/Close Flow

### Open

1. User clicks a project card in the Projects tab (picker state)
2. `FileTree._on_project_card_click` → fires `_on_project_opened(name, path)` callback
3. `ProjectHandler.open_project(name, path)` runs — sets active project, populates routing, fires callbacks
4. `LeftPanel.open_project_view(feed_tab)` runs:
   - Reparents `FileTree` out of `_picker_box` into a new `Gtk.Notebook`
   - Appends `FeedTab` as the "Feed" sub-tab
   - Appends `FileTree` as the "File Tree" sub-tab
   - Places notebook in `_projects_open_page`
   - Switches `_projects_stack` to "open" page
5. `FeedHandler.on_project_opened(name, path)` runs — loads feed.json, renders cards
6. `CrabWatchHandler.start_watching(path, name)` runs — starts file monitoring

### Close

1. User clicks ← back button in FileTree header
2. `FileTree.navigate_back()` → fires `_on_navigate_back(project_name)` callback
3. `ProjectHandler.close_project(name)` runs — clears active project, fires callbacks
4. `LeftPanel.close_project_view()` runs:
   - Removes nested notebook from `_projects_open_page`
   - Reparents `FileTree` back into `_picker_box`
   - Switches `_projects_stack` to "picker" page
5. `FeedHandler.on_project_closed(name)` runs — clears in-memory cards
6. `CrabWatchHandler.stop_watching()` runs — stops file monitoring

---

## Card Design

Each card follows the visual style of **code blocks inside chat bubbles** — consistent with CrabCakes' existing design language.

### Card Anatomy

```
┌──────────────────────────────────────────────┐
│ ● Title Text                         [📋]   │  ← Header (color-coded by type)
├──────────────────────────────────────────────┤
│                                              │
│  Body content area                           │  ← Body
│  (diff, description, code, metadata...)      │
│                                              │
├──────────────────────────────────────────────┤
│ Author • 2 min ago                           │  ← Footer (metadata)
│ [Review]  [Accept]  [Reject]                 │  ← Action buttons
└──────────────────────────────────────────────┘
```

### Color Coding by Card Type

| `card_type` | CSS Class | Header BG | Header Text | Use For |
|---|---|---|---|---|
| `git_commit` | `.feed-card-git` | `#2d5a3d` | `#a8e6c1` | Commit hash, message, author |
| `diff` | `.feed-card-diff` | `#5a4a2d` | `#e6c1a8` | File diffs, line changes |
| `file_created` | `.feed-card-file-new` | `#2d4a5a` | `#a8c1e6` | New file added |
| `file_deleted` | `.feed-card-file-del` | `#5a2d2d` | `#e6a8a8` | File removed |
| `dir_created` | `.feed-card-dir-new` | `#2d5a5a` | `#a8e6e6` | New directory |
| `agent_action` | `.feed-card-agent` | `#4a2d5a` | `#c1a8e6` | Agent change, command |
| `task` | `.feed-card-task` | `#5a5a2d` | `#e6e6a8` | Task create/status change |
| `system` | `.feed-card-system` | `#3a3a3a` | `#b0b0b0` | CrabWatch, config events |

### Action Buttons (All Cards)

| Button | GTK Widget | Behavior |
|--------|-----------|----------|
| **Review** | `Gtk.Button` with `.feed-btn-review` | Calls `on_review(card_id)` callback → populates input box |
| **Accept** | `Gtk.Button` with `.feed-btn-accept` | Calls `on_accept(card_id)` callback → git commit or task approve |
| **Reject** | `Gtk.Button` with `.feed-btn-reject` | Calls `on_reject(card_id)` callback → git revert or agent notify |

All three buttons appear on every card, regardless of type. This keeps the UI consistent and simplifies the factory.

---

## Card Sources & Data Flow

### Source 1: Agent Chat (crabcard blocks)

Agents output cards using tagged code blocks in their chat messages:

    ```crabcard
    type: diff
    title: Added auth middleware to main.py
    file: src/main.py
    +from auth import middleware
    +
    +app.use(middleware())
    ```

**Data flow:**

```
Agent sends message containing ```crabcard block
  → ChatRenderHandler.render_sync()
    → utils/crabcard_parser.py: extract_crabcards(text)
      → returns (cleaned_text, list[FeedCardData])
    → ChatRenderHandler renders cleaned_text as normal chat bubble
      → Where crabcard was removed: render feed reference widget (title + feed icon)
    → _on_crabcard_extracted callback fires with (cards, session_key)
      → FeedHandler.add_card(card_data) for each card
        → feed_card.py: build_feed_card(card_data, callbacks)
        → FeedTab.append_card(widget, card_id)
```

### Source 2: CrabWatch (system, file watcher)

```
CrabWatch detects file change
  → CrabWatchHandler._on_file_changed()
    → constructs FeedCardData(source="crabwatch")
    → calls on_event callback → FeedHandler.on_filesystem_event(card_data)
      → FeedHandler.add_card(card_data)
```

CrabWatch cards go directly to `FeedHandler.add_card()`. They do NOT pass through chat.

### Ground Truth: Agent + System Card Pairing

```
1. Agent outputs crabcard → purple agent_action card appears in feed
2. CrabWatch detects same change → gray system card appears in feed
3. PM sees both — intentional + confirmed

If agent forgets crabcard:
  CrabWatch still detects → system card appears → PM sees unannounced change
```

---

## Architecture

### Package Rules (per ARCHITECTURE.md Section 2)

| Package | May Import From | May NOT Import From |
|---------|----------------|-------------------|
| `models/` | Nothing external | `ui/`, `gateway/`, `agent/` |
| `utils/` | `models/` | `ui/`, `gateway/`, `agent/` |
| `ui/views/` | `models/`, `utils/`, GTK4 | `ui/handlers/`, `gateway/`, `agent/` |
| `ui/handlers/` | `models/`, `utils/`, GTK4 (via GLib only) | Other handlers (use callbacks), `gateway/` |

### Module Inventory

| Module | Package | Status | Responsibility |
|--------|---------|--------|---------------|
| `models/feed_card.py` | `models/` | ✅ Implemented | `FeedCardData` dataclass + `css_class_for_type()` + serialization (`to_dict`/`from_dict`). Pure data. |
| `utils/crabcard_parser.py` | `utils/` | ✅ Implemented | `extract_crabcards(text, project_name)` — parses `` ```crabcard `` blocks. Returns cleaned text + list of FeedCardData. |
| `ui/views/feed_card.py` | `ui/views/` | ✅ Implemented | `build_feed_card()`, `build_feed_reference_widget()`, `build_empty_feed_widget()` — GTK widget factories. |
| `ui/views/feed_tab.py` | `ui/views/` | ✅ Implemented | `FeedTab(Gtk.Box)` — scrollable card list with append/remove/empty state/scroll-to-bottom. |
| `ui/handlers/feed_handler.py` | `ui/handlers/` | ✅ Implemented | `FeedHandler` — card lifecycle, button actions, project open/close, persistence. |
| `utils/feed_store.py` | `utils/` | ✅ Implemented | `load_feed()`, `save_feed()`, `append_feed_card()`, `update_feed_card()` — JSON persistence to `.crabcakes/feed.json`. |
| `ui/handlers/crabwatch_handler.py` | `ui/handlers/` | ✅ Implemented | `CrabWatchHandler` — `Gio.FileMonitor` per project, debounce, `.gitignore`-aware event filtering. |
| `ui/views/left_panel.py` | `ui/views/` | ✅ Modified | `Gtk.Stack` ("picker"/"open") + nested `Gtk.Notebook` (File Tree/Feed) for project view. |
| `ui/views/main_content.py` | `ui/views/` | ✅ Cleaned | Bottom widget mechanism removed. MainContent manages chat tabs only. |

### Modified Modules (from existing codebase)

| Module | Change |
|--------|--------|
| `ui/handlers/chat_render_handler.py` | Added `set_on_crabcard_extracted()` callback, `set_project_name()`, calls `extract_crabcards()` before rendering. |
| `ui/views/chat_bubble.py` | Imports `build_feed_reference_widget` from `feed_card.py`. Renders crabcard reference widgets in chat. |
| `ui/handlers/project_handler.py` | **Removed** `create_chat_tab(f"project:{name}")` from `open_project()`. Project view is in LeftPanel. |
| `ui/handlers/chat_handler.py` | Per-member awareness prefix in group broadcast (fixed). Solo DM path cleanup. |
| `ui/styles.py` | All feed CSS classes added to `APP_CSS`. |
| `ui/window.py` | Creates `FeedHandler`, `CrabWatchHandler`, `FeedTab`. Wires all callbacks. No `set_project_bottom_widget`. |

---

## Module Specifications

### `models/feed_card.py` — Feed Card Data Model

**Responsibility:** Pure data structure for feed cards. Includes serialization helpers for JSON persistence. No GTK, no git, no network.

**Public API:**

```python
@dataclass
class FeedCardData:
    card_type: str           # "git_commit" | "diff" | "file_created" | "file_deleted" |
                             # "dir_created" | "agent_action" | "task" | "system"
    source: str              # "agent" | "system" | "git" | "crabwatch"
    title: str
    body: str
    author: str
    timestamp: datetime
    project_name: str

    # Optional context fields
    file_path: str | None = None
    commit_sha: str | None = None
    additions: int | None = None
    deletions: int | None = None
    task_id: str | None = None
    metadata: dict = field(default_factory=dict)

    # Runtime fields (set by FeedHandler)
    card_id: str | None = None
    reviewed: bool = False
    accepted: bool | None = None        # True=accepted, False=rejected, None=pending

    @staticmethod
    def css_class_for_type(card_type: str) -> str: ...

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "FeedCardData": ...
```

---

### `utils/feed_store.py` — Feed Persistence

**Public API:**

```python
def load_feed(project_path: str) -> list[FeedCardData]:
    """Load cards from .crabcakes/feed.json. Chronological order (oldest first)."""

def save_feed(project_path: str, cards: list[FeedCardData]) -> None:
    """Save cards to .crabcakes/feed.json. Creates .crabcakes/ if needed."""

def append_feed_card(project_path: str, card: FeedCardData) -> None:
    """Append a single card. Load → append → save."""

def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool:
    """Update a card by card_id. Returns True if found and updated."""
```

**File format:** JSON array of card dicts (see `FeedCardData.to_dict()`).

---

### `utils/crabcard_parser.py` — Crabcard Block Parser

**Public API:**

```python
def extract_crabcards(text: str, project_name: str) -> tuple[str, list[FeedCardData]]:
    """Parse ```crabcard blocks. Returns (cleaned_text, cards)."""
```

---

### `ui/views/feed_card.py` — Single Card Factory

**Public API:**

```python
def build_feed_card(card_data, *, on_review, on_accept, on_reject, on_copy) -> Gtk.Widget
def build_feed_reference_widget(card_data, *, on_click) -> Gtk.Widget
def build_empty_feed_widget() -> Gtk.Widget
```

---

### `ui/views/feed_tab.py` — Feed Tab Container

**Current implementation:** `FeedTab(Gtk.Box)` — a vertical box containing a `Gtk.ScrolledWindow` with a card container. No sub-tab switching (it IS the feed sub-tab content).

**Public API:**

```python
class FeedTab(Gtk.Box):
    def get_card_container(self) -> Gtk.Box
    def append_card(card_widget, card_id=None) -> None     # newest at bottom
    def remove_card(card_id) -> None
    def scroll_to_bottom() -> None
    def show_empty_state() -> None
```

---

### `ui/views/left_panel.py` — Projects Tab (Modified)

**Projects tab structure:**

```
Gtk.Stack ("picker" / "open")
  ├── "picker" page: _picker_box (Gtk.Box)
  │     └── FileTree (project card list)
  └── "open" page: _projects_open_page (Gtk.Box)
        └── Gtk.Notebook (nested, created on project open)
              ├── Tab 0: "File Tree" → FileTree (reparented from picker)
              └── Tab 1: "Feed" → FeedTab (wrapped in Gtk.Box)
```

**Public API (project view methods):**

```python
def set_feed_tab(self, feed_tab: FeedTab) -> None
def get_feed_tab(self) -> FeedTab | None
def open_project_view(self, feed_tab: FeedTab) -> None
def close_project_view(self) -> None
def switch_to_feed_tab(self) -> None
def switch_to_file_tree_tab(self) -> None
```

---

### `ui/handlers/feed_handler.py` — Feed Logic Handler

**Constructor:**

```python
class FeedHandler:
    def __init__(
        self,
        *,
        GLib,                                    # gi.repository.GLib
        on_populate_input: Callable[[str], None], # fill input box (Review)
        on_send_to_agent: Callable[[str, str], None], # send to agent
        on_tab_switch: Callable[[], None],        # switch to feed sub-tab
        on_card_added: Callable[[str], None] | None = None,  # card_id after add
    )
```

**Note:** `feed_tab` is NOT a constructor parameter. Set via `set_feed_tab()` after construction.

**Public API:**

```python
def set_feed_tab(self, feed_tab) -> None
def add_card(self, card_data: FeedCardData) -> str
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

**State:**

```python
self._cards: dict[str, FeedCardData]           # card_id → data
self._card_widgets: dict[str, Gtk.Widget]      # card_id → widget
self._project_cards: dict[str, list[str]]      # project_name → [card_ids] (newest first)
self._project_paths: dict[str, str]            # project_name → absolute path
self._lock: threading.Lock                      # protects shared dicts
```

**Thread safety:** All GTK operations via `GLib.idle_add()`. Git ops in background threads. `_lock` protects dict mutations.

---

### `ui/handlers/crabwatch_handler.py` — Filesystem Watcher

**Constructor:**

```python
class CrabWatchHandler:
    def __init__(self, *, GLib_module, on_event: Callable[[FeedCardData], None])
```

**Public API:**

```python
def start_watching(self, project_path: str, project_name: str) -> None
def stop_watching(self) -> None
def is_watching(self) -> bool
```

**Implementation notes:**
- Uses `Gio.FileMonitor` — runs on GLib main loop, no threading needed
- Debounces events for the same file within a configurable window
- Respects `.gitignore` patterns
- Ignores `.git/`, `node_modules/`, `__pycache__/`, `.crabcakes/`, `*.pyc`

---

## Callback Wiring (window.py)

Per ARCHITECTURE.md Section 5, handlers communicate via callbacks — never direct imports.

```python
# 1. FeedHandler (no feed_tab yet — set later)
self._feed_handler = FeedHandler(
    GLib=GLib,
    on_populate_input=_on_populate_input,
    on_send_to_agent=_on_send_to_agent,
    on_tab_switch=_on_show_feed_subtab,
)

# 2. CrabWatchHandler → FeedHandler
self._crabwatch_handler = CrabWatchHandler(
    GLib_module=GLib,
    on_event=self._feed_handler.on_filesystem_event,
)

# 3. FeedTab created once, injected into LeftPanel
self._feed_tab = FeedTab()
self._feed_handler.set_feed_tab(self._feed_tab)
self._left_panel.set_feed_tab(self._feed_tab)

# 4. ChatRenderHandler → FeedHandler (crabcard interception)
self._chat_render_handler.set_on_crabcard_extracted(_on_crabcards_extracted)

# 5. Project lifecycle → LeftPanel + FeedHandler + CrabWatch
self._project_handler.set_on_project_opened(
    lambda n, p: (
        self._left_panel.open_project_view(self._feed_tab),
        self._feed_handler.on_project_opened(n, p),
        self._crabwatch_handler.start_watching(p, n),
        self._on_feed_bar_update(n, ...),
    )
)
self._project_handler.set_on_project_closed(
    lambda name: (
        self._feed_handler.on_project_closed(name),
        self._crabwatch_handler.stop_watching(),
        self._on_feed_bar_update(None, 0),
    )
)
```

---

## Feed Persistence

Feed cards persist to `.crabcakes/feed.json` in each project directory.

```
.crabcakes/
├── project.md      # project manifest
├── team.json       # team membership
├── context.md      # freeform project memory
├── awareness.json  # dynamic state snapshot
└── feed.json       # project feed cards (structured)
```

**On project open:** `FeedHandler.on_project_opened()` loads `feed.json`, deserializes cards, renders them chronologically (oldest at top, newest at bottom), auto-scrolls to bottom.

**On card add/accept/reject:** `FeedHandler` persists to `feed.json` via `feed_store` functions. Writes happen in background threads.

---

## CSS Classes

All feed CSS classes are in `ui/styles.py` → `APP_CSS`. See the original spec's CSS section for the full list (`.feed-card`, `.feed-card-header`, `.feed-card-body`, type-specific colors, action buttons, etc.).

---

*This document is the single source of truth for the Project Feed feature. It reflects the current state of the codebase as of 2026-05-01. `docs/PROJECT_FEED_CORRECTION.md` is now obsolete — its corrections have been incorporated here.*
