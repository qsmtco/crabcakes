# Project Feed — Specification

**Last updated:** 2026-04-28
**Status:** Design phase — ready for implementation planning
**Depends on:** Existing CrabCakes architecture (see `docs/ARCHITECTURE.md`)
**Supersedes:** `docs/review-layer.md` — the Project Feed IS the review layer. The session-based ReviewBar approach is replaced by the continuous feed.

---

## Overview

The Project Feed is a live, reverse-chronological activity feed embedded in the project tab. Every meaningful event in a project's lifecycle generates a **card** in the feed — git commits, file changes, agent activity, tasks, and more. Each card is color-coded by source type and includes Review/Accept/Reject buttons.

The Project Feed **replaces the original Review Layer's session-based workflow** (ReviewBar, start/end sessions) with a continuous, ambient review experience. Review happens naturally by engaging with cards.

**Key design principle:** Two sources of truth, one feed. Agents proactively create cards via chat output. CrabWatch independently detects file changes and creates system cards. This provides both intentional communication and ground-truth verification.

---

## UX Layout

When a project tab is open, the content area below the chat is split into **two bottom tabs:**

```
┌──────────────────────────────────────────────────┐
│ Project: my-project                              │
├──────────────────────────────────────────────────┤
│                                                  │
│            (chat area — existing)                 │
│                                                  │
├──────────────────────────────────────────────────┤
│  [File Viewer]  [Project Feed]                   │  ← Bottom tab bar
├──────────────────────────────────────────────────┤
│                                                  │
│  (file tree OR feed cards — based on active tab) │
│                                                  │
└──────────────────────────────────────────────────┘
```

| Tab | Content |
|-----|---------|
| **File Viewer** | Current file browser (existing functionality, unchanged) |
| **Project Feed** | Reverse-chronological card feed (new) |

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
    → FeedHandler.add_card(card_data, project_name)
      → feed_card.py: build_feed_card(card_data, callbacks)
      → Prepend card to feed container (reverse-chronological)
```

### Source 2: CrabWatch (system, file watcher)

```
CrabWatch detects file change
  → FeedHandler.add_card(card_data, project_name)
    → Same path as agent cards — single factory
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

### New Modules

| Module | Package | Responsibility |
|--------|---------|---------------|
| `models/feed_card.py` | `models/` | `FeedCardData` dataclass + serialization helpers. Pure data — no GTK, no git, no network. |
| `utils/crabcard_parser.py` | `utils/` | `extract_crabcards(text)` — parses ` ```crabcard ` blocks from chat text. Returns cleaned text + list of FeedCardData. Pure function — no GTK. |
| `ui/views/feed_card.py` | `ui/views/` | **Single card factory** — `build_feed_card()` produces all card widgets. Also builds feed reference widgets for chat. Pure view. |
| `ui/views/feed_tab.py` | `ui/views/` | Feed tab container — scrollable card list, empty state, bottom tab bar. Pure view. |
| `ui/handlers/feed_handler.py` | `ui/handlers/` | Feed logic — manages card list, handles button actions, delegates git ops. All GTK via `GLib.idle_add()`. |
| `utils/feed_store.py` | `utils/` | Persistence — loads/saves feed cards to `.crabcakes/feed.json`. Pure functions, no GTK. |
| `ui/handlers/crabwatch_handler.py` | `ui/handlers/` | Filesystem watcher — uses `Gio.FileMonitor` to detect project file changes. Creates system cards via FeedHandler callback. |

### Modified Modules

| Module | Change |
|--------|--------|
| `ui/views/chat_bubble.py` | Import `build_feed_reference_widget` from `feed_card.py`. When rendering event cards, use it for crabcard references. |
| `ui/handlers/chat_render_handler.py` | Call `extract_crabcards()` before rendering. Route extracted cards to `FeedHandler.add_card()`. |
| `ui/handlers/project_handler.py` | Add bottom tab layout to project tab content area (File Viewer / Project Feed). |
| `ui/styles.py` | Add feed card CSS classes to `APP_CSS`. |
| `ui/window.py` | Wire FeedHandler with callbacks. Connect to ChatRenderHandler and ProjectHandler. |

### CrabWatch Communication (Internal Module)

CrabWatch is NOT a separate process or service. It is an **internal handler** within CrabCakes that uses `Gio.FileMonitor` (GTK4 native, no external dependencies) to watch the active project directory for filesystem changes.

**Why internal:**
- `Gio.FileMonitor` integrates with the GLib main loop — no threading issues
- No IPC, no sockets, no DBus — just a callback to FeedHandler
- Same handler pattern as everything else in CrabCakes
- No new dependencies — Gio is already part of PyGObject

**Architecture fit:**
```
CrabWatchHandler (ui/handlers/crabwatch_handler.py)
  │
  ├── Owns: Gio.FileMonitor per active project directory
  ├── Watches: file created, modified, deleted; directory created, deleted
  ├── Does NOT own: FeedHandler, any GTK widgets, any state beyond monitors
  │
  └── On event → constructs FeedCardData(source="crabwatch") → calls on_filesystem_event callback
        → FeedHandler.add_card()
```

### Feed Persistence

Feed cards persist to `.crabcakes/feed.json` in each project directory. This follows the existing `.crabcakes/` convention (`project.md`, `team.json`, `context.md`, `awareness.json`).

```
.crabcakes/
├── project.md      # project manifest
├── team.json       # team membership
├── context.md      # freeform project memory (agent/PM authored)
├── awareness.json  # dynamic state snapshot
└── feed.json       # ← project feed cards (structured, machine-readable)
```

**Why not context.md:** context.md is freeform narrative ("we decided to use SQLite"). Feed cards are structured data with card_type, source, timestamp, accepted/rejected state. Mixing them would bloat context.md (50KB cap) and require fragile markdown↔JSON parsing. Separate file, separate concern.

**On project open:**
1. FeedHandler loads `.crabcakes/feed.json`
2. Deserializes into `list[FeedCardData]`
3. Renders all cards into the feed (reverse-chronological — oldest first, newest last)
4. **Project Feed tab is the default tab** (not File Viewer)
5. **Auto-scrolls to bottom** — newest card is visible immediately

**On card add/remove/accept/reject:**
- FeedHandler persists the full card list back to `feed.json`
- Write is synchronous (small JSON, fast) — no background thread needed

### No Changes To

| Module | Reason |
|--------|--------|
| `gateway/` | Feed is entirely client-side. No gateway protocol changes. CrabWatch is internal — no gateway events. |
| `agent/` | Agents output markdown. Crabcard format is just a code block — no SDK changes needed. |
| `utils/git_ops.py` | Already exists. FeedHandler calls it for Accept/Reject. |
| `utils/diff_parser.py` | Already exists. Used for diff card body rendering. |

---

## Module Specifications

### `models/feed_card.py` — Feed Card Data Model

**Responsibility:** Pure data structure for feed cards. Includes serialization helpers for JSON persistence. No GTK, no git, no network.

**Public API:**

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class FeedCardData:
    """Structured data for a project feed card."""
    card_type: str           # "git_commit" | "diff" | "file_created" | "file_deleted" |
                             # "dir_created" | "agent_action" | "task" | "system"
    source: str              # "agent" | "system" | "git" | "crabwatch"
    title: str               # Card header title
    body: str                # Card body content (text, diff, description)
    author: str              # Who/what created this card
    timestamp: datetime      # When the card was created
    project_name: str        # Which project this belongs to

    # Optional context fields
    file_path: str | None = None
    commit_sha: str | None = None
    additions: int | None = None
    deletions: int | None = None
    task_id: str | None = None
    metadata: dict = field(default_factory=dict)

    # Runtime fields (set by FeedHandler, not by source)
    card_id: str | None = None          # Unique ID assigned on add
    reviewed: bool = False              # Has PM reviewed this card
    accepted: bool | None = None        # True=accepted, False=rejected, None=pending

    @staticmethod
    def css_class_for_type(card_type: str) -> str:
        """Return CSS class name for a card type."""
        mapping = {
            "git_commit": "feed-card-git",
            "diff": "feed-card-diff",
            "file_created": "feed-card-file-new",
            "file_deleted": "feed-card-file-del",
            "dir_created": "feed-card-dir-new",
            "agent_action": "feed-card-agent",
            "task": "feed-card-task",
            "system": "feed-card-system",
        }
        return mapping.get(card_type, "feed-card-system")

    # ── Serialization (for feed.json persistence) ────────────────

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict. Includes all fields."""
        return {
            "card_type": self.card_type,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "project_name": self.project_name,
            "file_path": self.file_path,
            "commit_sha": self.commit_sha,
            "additions": self.additions,
            "deletions": self.deletions,
            "task_id": self.task_id,
            "metadata": self.metadata,
            "card_id": self.card_id,
            "reviewed": self.reviewed,
            "accepted": self.accepted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeedCardData":
        """Deserialize from a dict (e.g., loaded from feed.json)."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        return cls(
            card_type=data["card_type"],
            source=data["source"],
            title=data["title"],
            body=data.get("body", ""),
            author=data.get("author", "unknown"),
            timestamp=ts,
            project_name=data["project_name"],
            file_path=data.get("file_path"),
            commit_sha=data.get("commit_sha"),
            additions=data.get("additions"),
            deletions=data.get("deletions"),
            task_id=data.get("task_id"),
            metadata=data.get("metadata", {}),
            card_id=data.get("card_id"),
            reviewed=data.get("reviewed", False),
            accepted=data.get("accepted"),
        )
```

**Rules:** No imports from `ui/`, `gateway/`, `agent/`, `subprocess`.

---

### `utils/feed_store.py` — Feed Persistence

**Responsibility:** Load/save feed cards to `.crabcakes/feed.json`. Pure functions — no GTK, no state, no side effects beyond file I/O.

**Public API:**

```python
from models.feed_card import FeedCardData

FEED_FILENAME = "feed.json"

def load_feed(project_path: str) -> list[FeedCardData]:
    """
    Load feed cards from .crabcakes/feed.json.

    Returns cards in chronological order (oldest first).
    Returns empty list if file doesn't exist or is invalid JSON.
    Logs errors instead of raising.
    """

def save_feed(project_path: str, cards: list[FeedCardData]) -> None:
    """
    Save feed cards to .crabcakes/feed.json.

    Serializes each card via FeedCardData.to_dict().
    Creates .crabcakes/ directory if it doesn't exist.
    Logs errors instead of raising.
    """

def append_feed_card(project_path: str, card: FeedCardData) -> None:
    """
    Append a single card to the existing feed file.
    Loads -> appends -> saves. Convenience wrapper.
    """

def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool:
    """
    Update a specific card by card_id (e.g., set accepted=True).
    Loads -> finds card -> applies updates -> saves.
    Returns True if card was found and updated, False otherwise.
    """
```

**File format:**
```json
[
  {
    "card_type": "diff",
    "source": "agent",
    "title": "Added auth middleware",
    "body": "+from auth import middleware",
    "author": "Qaster",
    "timestamp": "2026-04-28T16:05:00+00:00",
    "project_name": "crabcakes",
    "card_id": "a1b2c3d4",
    "reviewed": false,
    "accepted": null
  }
]
```

**Rules:** No imports from `ui/`, `gateway/`, `agent/`, `subprocess`. May import from `models/`.

---

### `utils/crabcard_parser.py` — Crabcard Block Parser

**Responsibility:** Extract `\`\`\`crabcard` blocks from chat message text. Returns cleaned text + structured card data. Pure function.

**Public API:**

```python
from models.feed_card import FeedCardData

def extract_crabcards(text: str, project_name: str) -> tuple[str, list[FeedCardData]]:
    """
    Parse crabcard blocks from chat message text.

    Args:
        text: Raw chat message text from agent.
        project_name: Project name to assign to cards.

    Returns:
        (cleaned_text, cards) where:
          - cleaned_text: original text with crabcard blocks removed
          - cards: list of FeedCardData parsed from the blocks

    Crabcard format:
        ```crabcard
        type: <card_type>
        title: <title>
        file: <optional file path>
        ---
        <body content>
        ```

    The parser:
    1. Finds all ```crabcard ... ``` blocks
    2. Parses header fields (key: value pairs before ---)
    3. Body is everything after ---
    4. Constructs FeedCardData with source="agent", author from metadata
    5. Returns cleaned text with blocks replaced by empty string
    """
```

**Rules:** No imports from `ui/`, `gateway/`, `subprocess`. May import from `models/`.

---

### `ui/views/feed_card.py` — Single Card Factory

**Responsibility:** Builds ALL card widgets — feed cards and chat reference widgets. The **only** place in the codebase that constructs feed card GTK widgets.

**Public API:**

```python
def build_feed_card(
    card_data: FeedCardData,
    *,
    on_review: callable,      # callback(card_id: str) -> None
    on_accept: callable,      # callback(card_id: str) -> None
    on_reject: callable,      # callback(card_id: str) -> None
    on_copy: callable,        # callback(text: str) -> None
) -> Gtk.Widget:
    """
    Build a complete feed card widget from FeedCardData.

    Returns a Gtk.Box containing:
      - Header: colored bar with title + copy button
      - Body: content area with card-specific rendering
      - Footer: author + timestamp + Review/Accept/Reject buttons

    Card-specific body rendering:
      - "diff" / "git_commit": uses diff_parser to render syntax-highlighted diff
      - "file_created" / "file_deleted": shows file path + preview snippet
      - "agent_action": shows action description
      - "task": shows task title + status
      - "system": shows event description
      - Unknown: renders body as plain text
    """

def build_feed_reference_widget(
    card_data: FeedCardData,
    *,
    on_click: callable,       # callback() -> None  (switches to feed tab)
) -> Gtk.Widget:
    """
    Build a small inline widget for chat bubbles that replaces a crabcard block.

    Returns a Gtk.Box containing:
      - Feed icon (📋)
      - Card title text
      - Clickable — on_click switches to Project Feed tab and scrolls to card

    CSS class: .feed-reference
    """

def build_empty_feed_widget() -> Gtk.Widget:
    """
    Build the empty state widget shown when feed has no cards.

    Returns a Gtk.Box with centered text: "No activity yet"
    CSS class: .feed-empty
    """
```

**Rules:** Pure view — no business logic, no state mutations. All actions via callbacks. May import from `models/`, `utils/` (diff_parser, escaping), GTK4 only.

---

### `ui/views/feed_tab.py` — Feed Tab Container

**Responsibility:** The bottom-tab container that holds File Viewer and Project Feed. Pure view.

**Public API:**

```python
class FeedTab(Gtk.Box):
    """
    Bottom tab container for project content area.

    Contains two tabs:
      - File Viewer: existing FileTree widget
      - Project Feed: scrollable card list
    """

    def __init__(
        self,
        file_tree: Gtk.Widget,        # existing FileTree widget
    ):
        """
        Build the bottom tab layout.

        Layout:
          Gtk.Box (vertical)
            ├── Gtk.StackSwitcher (tab bar: "Files" | "Feed")
            └── Gtk.Stack
                 ├── "files" → file_tree
                 └── "feed"  → Gtk.ScrolledWindow → Gtk.Box (vertical, card container)
        """

    def get_card_container(self) -> Gtk.Box:
        """Return the vertical box that holds feed cards. Cards are prepended here."""

    def get_stack(self) -> Gtk.Stack:
        """Return the stack for external tab switching."""

    def show_feed_tab(self) -> None:
        """Switch to the feed tab."""

    def show_files_tab(self) -> None:
        """Switch to the files tab."""

    def show_empty_state(self) -> None:
        """Clear cards and show empty state widget."""

    def prepend_card(self, card_widget: Gtk.Widget) -> None:
        """Prepend a card widget to the top of the feed (reverse-chronological)."""

    def remove_card(self, card_id: str) -> None:
        """Remove a card widget by card_id."""

    def scroll_to_bottom(self) -> None:
        """Scroll the feed so the newest card (bottom) is visible."""
```

**CSS classes:**
- `.feed-tab-bar` — the tab switcher
- `.feed-scroll` — the scrolled window for the card list
- `.feed-card-list` — the vertical box holding cards

**Rules:** Pure view. No business logic. Card creation delegated to `feed_card.py` factory.

---

### `ui/handlers/feed_handler.py` — Feed Logic Handler

**Responsibility:** Manages feed state and coordinates card lifecycle. Delegates rendering to `feed_card.py`, git ops to `git_ops.py`. All GTK from background threads via `GLib.idle_add()`.

**Handler pattern compliance (per ARCHITECTURE.md Section 8.6):**
- One handler per subsystem (feed)
- Does NOT import other handlers — window wires callbacks
- Receives dependencies via constructor
- Owns its state (`_cards` dict)
- All GTK from background threads via `GLib.idle_add()`

**Public API:**

```python
class FeedHandler:
    def __init__(
        self,
        *,
        GLib,                                       # gi.repository.GLib
        feed_tab: FeedTab,                          # FeedTab instance
        on_populate_input: Callable[[str], None],   # callback(text) → fills input box
        on_send_to_agent: Callable[[str, str], None], # callback(session_key, text) → send message
        on_tab_switch: Callable[[], None],           # callback() → switch to feed tab
    ):
        """
        Initialize FeedHandler.

        Constructor dependencies:
          - GLib: for idle_add, timeout_add
          - feed_tab: FeedTab view for adding/removing cards
          - on_populate_input: window-provided callback to fill input box (for Review)
          - on_send_to_agent: window-provided callback to send to agent (for Accept/Reject notification)
          - on_tab_switch: window-provided callback to switch project tab to feed view
        """

    # ── Card lifecycle ──────────────────────────────────

    def add_card(self, card_data: FeedCardData) -> str:
        """
        Add a card to the project feed.

        1. Assign unique card_id (uuid4)
        2. Store in self._cards[card_id]
        3. Build widget via feed_card.build_feed_card()
        4. Prepend to feed_tab
        5. Persist to feed.json via feed_store.append_feed_card()
        6. Auto-scroll feed to bottom (newest card visible)
        7. Return card_id

        Thread-safe: GTK operations via GLib.idle_add().
        """

    def remove_card(self, card_id: str) -> None:
        """Remove a card from the feed."""

    def get_card(self, card_id: str) -> FeedCardData | None:
        """Get card data by ID."""

    def get_cards_for_project(self, project_name: str) -> list[FeedCardData]:
        """Get all cards for a project, reverse-chronological."""

    def clear_project(self, project_name: str) -> None:
        """Remove all cards for a project (on project close)."""

    # ── Button action handlers ──────────────────────────

    def handle_review(self, card_id: str) -> None:
        """
        Review button clicked.

        1. Get FeedCardData for card_id
        2. Construct review prompt based on card_type:
           - git_commit: "Review commit {sha}: '{title}'. Is this change accurate?"
           - diff: "Review changes to {file_path}. +{add}/-{del} lines. Verify correctness."
           - file_created: "Review new file {file_path}. Is this needed and correctly placed?"
           - task: "Review task: {title}. Status: {status}. Is this done?"
           - system: "System detected change to {file_path}. Verify this change."
           - default: "Review: {title}. {body}"
        3. Call on_populate_input(prompt)
        """

    def handle_accept(self, card_id: str) -> None:
        """
        Accept button clicked.

        For git-backed cards (diff, file_created, file_deleted, git_commit):
          1. Run git_ops.stage_all() in background thread
          2. Run git_ops.commit() with message derived from card
          3. Update card.accepted = True
          4. Persist to feed.json via feed_store.update_feed_card()
          5. Visual feedback: green checkmark overlay on card

        For task cards:
          1. Update task status (via callback)
          2. Update card.accepted = True
          3. Persist to feed.json

        For other cards:
          1. Mark card.accepted = True
          2. Persist to feed.json
          3. Visual feedback only
        """

    def handle_reject(self, card_id: str) -> None:
        """
        Reject button clicked.

        For git-backed cards:
          1. Run git_ops.checkout_paths() in background thread (revert to checkpoint)
          2. Update card.accepted = False
          3. Persist to feed.json via feed_store.update_feed_card()
          4. Call on_send_to_agent(agent_session, rejection_message)
          5. Visual feedback: red X overlay on card

        For other cards:
          1. Mark card.accepted = False
          2. Persist to feed.json
          3. Notify agent via on_send_to_agent if applicable
        """

    def handle_copy(self, text: str) -> None:
        """Copy card body text to clipboard."""

    # ── Project lifecycle hooks ──────────────────────────

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """Called when project opens.

        1. Load cards from .crabcakes/feed.json via feed_store.load_feed()
        2. Render all cards (chronological order → newest at bottom)
        3. Switch to Project Feed tab (default tab on open)
        4. Auto-scroll to bottom (newest card visible)
        5. If no cards, show empty state widget
        """

    def on_project_closed(self, project_name: str) -> None:
        """Called when project closes. Clear cards for this project (in-memory only; feed.json persists on disk)."""

    # ── CrabWatch integration ───────────────────────────

    def on_filesystem_event(self, card_data: FeedCardData) -> None:
        """
        Entry point for CrabWatch file change events.

        Same as add_card() but source is always "system" or "crabwatch".
        """
```

**State ownership:**
```python
self._cards: dict[str, FeedCardData] = {}           # card_id → FeedCardData
self._card_widgets: dict[str, Gtk.Widget] = {}      # card_id → widget reference
self._project_cards: dict[str, list[str]] = {}      # project_name → [card_ids]
```

**Thread safety:**
- `add_card`, `handle_accept`, `handle_reject` may run git ops in background threads
- All GTK widget updates via `GLib.idle_add()`
- `_cards` dict only modified from main thread (inside `GLib.idle_add()` callbacks)

**Error handling:**
- Git operation failures: show error card in feed (red system card)
- Missing card_id: no-op (log warning)

---

### `ui/handlers/crabwatch_handler.py` — Filesystem Watcher (CrabWatch)

**Responsibility:** Watches the active project directory for filesystem changes using `Gio.FileMonitor`. Creates system cards and routes them to FeedHandler via callback. Part of the ground-truth verification system.

**Handler pattern compliance (per ARCHITECTURE.md Section 8.6):**
- One handler per subsystem (file watching)
- Does NOT import other handlers — window wires callbacks
- Receives dependencies via constructor
- Owns its state (`_monitors` dict)
- Runs entirely on GLib main loop — no threading needed (Gio.FileMonitor is async)

**Public API:**

```python
class CrabWatchHandler:
    def __init__(
        self,
        *,
        on_filesystem_event: Callable[[FeedCardData], None],  # callback → FeedHandler.on_filesystem_event
    ):
        """
        Initialize CrabWatchHandler.

        Constructor dependencies:
          - on_filesystem_event: FeedHandler-provided callback to add cards
        """

    # ── Project lifecycle ─────────────────────────────────

    def start_watching(self, project_name: str, project_path: str) -> None:
        """
        Start monitoring a project directory.

        1. Create Gio.FileMonitor for project_path (recursive)
        2. Store monitor in self._monitors[project_name]
        3. Connect Gio signals: changed, moves, renames
        4. Respect .gitignore — skip node_modules, .git, __pycache__, etc.
        """

    def stop_watching(self, project_name: str) -> None:
        """
        Stop monitoring a project directory.
        Cancels and removes the Gio.FileMonitor.
        """

    def is_watching(self, project_name: str) -> bool:
        """True if currently watching this project."""

    # ── Event filtering ───────────────────────────────────

    IGNORED_PATTERNS: list[str]  # [".git/", "node_modules/", "__pycache__/", ".gitignore"]

    def _should_ignore(self, file_path: str) -> bool:
        """Check if a file path matches ignored patterns."""

    # ── Event handling ────────────────────────────────────

    def _on_file_changed(self, monitor, file, other_file, event_type) -> None:
        """
        Gio.FileMonitor callback.

        Maps Gio.FileMonitorEvent to FeedCardData:
          - CREATED → FeedCardData(card_type="file_created" or "dir_created", source="crabwatch")
          - DELETED → FeedCardData(card_type="file_deleted", source="crabwatch")
          - CHANGES_DONE_HINT → FeedCardData(card_type="diff", source="crabwatch")
          - RENAMED → FeedCardData(card_type="file_deleted" + "file_created", source="crabwatch")

        Calls on_filesystem_event(card_data) for each event.
        """
```

**State ownership:**
```python
self._monitors: dict[str, Gio.FileMonitor] = {}  # project_name → active monitor
self._project_paths: dict[str, str] = {}          # project_name → absolute path
```

**Thread safety:**
- Gio.FileMonitor runs on the GLib main loop — no threading needed
- All callbacks fire on the main thread
- No `GLib.idle_add()` required (already on main thread)

**Ignored paths (default):**
- `.git/`
- `node_modules/`
- `__pycache__/`
- `.gitignore`
- `*.pyc`
- `.crabcakes/` (internal config directory)

**Debounce:** File saves often trigger multiple Gio events (write + truncate + change-done). CrabWatch should debounce events for the same file within a 200ms window to avoid duplicate cards.

---

---

## Callback Wiring Diagram

Per ARCHITECTURE.md Section 5, handlers communicate via callbacks — never direct imports.

```
window._build()
  │
  ├── Creates FeedTab (view)
  ├── Creates FeedHandler (handler)
  │     ├── GLib = gi.repository.GLib
  │     ├── feed_tab = feed_tab
  │     ├── on_populate_input = window._on_populate_input
  │     ├── on_send_to_agent = chat_handler.send_message
  │     └── on_tab_switch = feed_tab.show_feed_tab
  │
  ├── Creates CrabWatchHandler (handler)
  │     └── on_filesystem_event = feed_handler.on_filesystem_event
  │
  ├── Wires ChatRenderHandler → FeedHandler:
  │     chat_render_handler.set_on_crabcard_extracted(feed_handler.add_card)
  │     chat_render_handler.set_on_tab_switch_request(feed_tab.show_feed_tab)
  │
  ├── Wires ProjectHandler → FeedTab:
  │     project_handler.set_feed_tab(feed_tab)   # adds bottom tabs to project layout
  │
  ├── Wires ProjectHandler → CrabWatchHandler:
  │     project_handler.on_project_opened → crabwatch_handler.start_watching
  │     project_handler.on_project_closed → crabwatch_handler.stop_watching
  │
  └── Wires FeedHandler → Project lifecycle:
        project_handler.on_project_opened → feed_handler.on_project_opened
        project_handler.on_project_closed → feed_handler.on_project_closed
```

**Handler isolation:**
- `FeedHandler` does NOT import `ChatHandler`, `ChatRenderHandler`, `ProjectHandler`, or `CrabWatchHandler`
- `CrabWatchHandler` does NOT import any other handler — communicates via `on_filesystem_event` callback only
- All communication via callbacks set in `window._build()`
- `FeedHandler` may import `utils/git_ops.py` and `utils/diff_parser.py` (utils are safe)
- `CrabWatchHandler` may import `models/feed_card.py` (models are safe)

---

## CSS Classes

Added to `ui/styles.py` → `APP_CSS`:

```css
/* Feed tab container */
.feed-tab-bar { background: @card_bg; border-radius: 6px; margin: 4px 8px; }
.feed-tab-bar button { padding: 6px 16px; }
.feed-tab-bar button:checked { background: @accent_bg; color: @accent_fg; border-radius: 4px; }
.feed-scroll { background: transparent; }
.feed-card-list { padding: 8px; spacing: 8px; }
.feed-empty { padding: 48px; color: alpha(@window_fg_color, 0.4); }

/* Feed card base */
.feed-card { border-radius: 8px; overflow: hidden; margin-bottom: 8px; }
.feed-card-header { padding: 8px 12px; font-weight: bold; font-size: 13px; }
.feed-card-body { padding: 8px 12px; font-family: monospace; font-size: 12px; min-height: 24px; }
.feed-card-footer { padding: 6px 12px; font-size: 11px; color: alpha(@window_fg_color, 0.6); }
.feed-card-actions { padding: 4px 12px 8px; }

/* Card type colors */
.feed-card-git .feed-card-header { background: #2d5a3d; color: #a8e6c1; }
.feed-card-diff .feed-card-header { background: #5a4a2d; color: #e6c1a8; }
.feed-card-file-new .feed-card-header { background: #2d4a5a; color: #a8c1e6; }
.feed-card-file-del .feed-card-header { background: #5a2d2d; color: #e6a8a8; }
.feed-card-dir-new .feed-card-header { background: #2d5a5a; color: #a8e6e6; }
.feed-card-agent .feed-card-header { background: #4a2d5a; color: #c1a8e6; }
.feed-card-task .feed-card-header { background: #5a5a2d; color: #e6e6a8; }
.feed-card-system .feed-card-header { background: #3a3a3a; color: #b0b0b0; }

/* Card body backgrounds (slightly different shade from header) */
.feed-card-git .feed-card-body { background: #1a3d2a; }
.feed-card-diff .feed-card-body { background: #3d321a; }
.feed-card-file-new .feed-card-body { background: #1a323d; }
.feed-card-file-del .feed-card-body { background: #3d1a1a; }
.feed-card-dir-new .feed-card-body { background: #1a3d3d; }
.feed-card-agent .feed-card-body { background: #321a3d; }
.feed-card-task .feed-card-body { background: #3d3d1a; }
.feed-card-system .feed-card-body { background: #2a2a2a; }

/* Feed action buttons */
.feed-btn-review { padding: 4px 12px; border-radius: 4px; background: #3a5068; color: #a8c8e8; }
.feed-btn-accept { padding: 4px 12px; border-radius: 4px; background: #2d5a3d; color: #a8e6c1; }
.feed-btn-reject { padding: 4px 12px; border-radius: 4px; background: #5a2d2d; color: #e6a8a8; }

/* Feed reference in chat */
.feed-reference { background: alpha(@card_bg, 0.6); border-radius: 4px; padding: 4px 8px; }
.feed-reference:hover { background: alpha(@accent_bg, 0.3); }
```

---

## Data Flow Diagrams

### Flow 1: Agent outputs crabcard in chat

```
1. Agent message arrives via gateway
   → window._on_ws_event()
     → chat_handler.on_chat_event()
       → chat_render_handler.render_sync(agent_name, text, session_key)

2. render_sync() intercepts crabcard blocks
   → extract_crabcards(text, project_name)
     → returns (cleaned_text, [FeedCardData, ...])

3. Chat bubble rendered with cleaned_text
   → For each removed crabcard: build_feed_reference_widget(card, on_click=callback)
   → Reference widget shows: "📋 Added auth middleware to main.py"
   → Clicking reference → feed_tab.show_feed_tab()

4. Cards routed to feed
   → feed_handler.add_card(card_data)
     → assigns card_id
     → build_feed_card(card_data, on_review, on_accept, on_reject)
     → feed_tab.prepend_card(widget)
```

### Flow 2: PM clicks Review

```
1. PM clicks Review button on card
   → feed_card widget calls on_review(card_id) callback
     → feed_handler.handle_review(card_id)
       → constructs prompt from FeedCardData
       → calls on_populate_input(prompt)
         → window._on_populate_input(text)
           → main_content.set_input_text(text)

2. Input box now contains: "Review changes to src/main.py. +12/-3 lines. Verify correctness."
   PM edits if needed, clicks Send → normal message flow
```

### Flow 3: PM clicks Accept

```
1. PM clicks Accept button on card
   → feed_card widget calls on_accept(card_id) callback
     → feed_handler.handle_accept(card_id)

2. If git-backed card:
   → Thread: git_ops.stage_all(project_path)
   → Thread: git_ops.commit(project_path, message=f"Accept: {card.title}")
   → GLib.idle_add: update card.accepted = True
   → GLib.idle_add: visual green checkmark on card

3. If task card:
   → Update task status via callback
   → GLib.idle_add: visual green checkmark
```

### Flow 4: PM clicks Reject

```
1. PM clicks Reject button on card
   → feed_card widget calls on_reject(card_id) callback
     → feed_handler.handle_reject(card_id)

2. If git-backed card:
   → Thread: git_ops.checkout_paths(project_path, checkpoint_sha, [card.file_path])
   → GLib.idle_add: update card.accepted = False
   → GLib.idle_add: visual red X on card
   → on_send_to_agent(agent_session, f"Rejected: {card.title}. Reason: auto-revert.")

3. If task/other card:
   → on_send_to_agent with rejection message
   → GLib.idle_add: visual red X
```

### Flow 5: CrabWatch detects file change

```
1. Gio.FileMonitor fires callback on GLib main loop
   → CrabWatchHandler._on_file_changed(monitor, file, other_file, event_type)

2. Filter: check _should_ignore(file_path)
   → Skip .git/, node_modules/, __pycache__, etc.

3. Debounce: check if same file was seen within 200ms
   → Skip duplicate event

4. Construct FeedCardData
   → card_type based on event_type (file_created, file_deleted, dir_created, diff)
   → source="crabwatch"
   → author="CrabWatch"

5. Route to FeedHandler
   → on_filesystem_event(card_data)
     → Same path as agent cards — single factory
```

### Flow 6: Project open → load feed + default to Feed tab

```
1. PM opens project tab
   → window._on_project_opened(name, path)
     → feed_handler.on_project_opened(name, path)

2. Load persisted feed from disk
   → cards = feed_store.load_feed(path)
   → Returns list[FeedCardData] in chronological order (oldest first)

3. Render all cards
   → For each card: build_feed_card() → feed_tab.prepend_card()
   → Cards render oldest→newest, so newest ends up at bottom

4. Switch to Feed tab (default)
   → feed_tab.show_feed_tab()
   → (NOT File Viewer — Feed is the default view)

5. Auto-scroll to bottom
   → feed_tab.scroll_to_bottom()
   → Newest card is immediately visible

6. If no cards: show empty state widget
```

---

## Crabcard Block Format

Agents output cards using this markdown code block format:

    ```crabcard
    type: <card_type>
    title: <title text>
    file: <optional file path>
    ---
    <body content — plain text, diff, code, etc.>
    ```

**Parsing rules:**
1. Block starts with ` ```crabcard ` and ends with ` ``` `
2. Before `---`: header fields as `key: value` pairs
3. After `---`: body content (everything, including newlines)
4. Required fields: `type`, `title`
5. Optional fields: `file`, `additions`, `deletions`, `commit_sha`, `task_id`
6. `author` defaults to the agent name from the chat context
7. `source` is always `"agent"` for chat-extracted cards
8. `timestamp` is set to current time by the parser
9. `project_name` is set from the active project context

**Supported `type` values:**
- `diff` — code change with diff content in body
- `file_created` — new file
- `file_deleted` — file removed
- `agent_action` — agent performed an action
- `task` — task-related card
- Unknown types → card_type="system", body rendered as plain text

---

## Implementation Phases

### Phase 1 — Data Model + Card Factory + Feed Tab

**Files:** `models/feed_card.py`, `ui/views/feed_card.py`, `ui/views/feed_tab.py`, `ui/styles.py`

- Build `FeedCardData` model
- Build `build_feed_card()` factory with all card types
- Build `build_feed_reference_widget()` for chat
- Build `build_empty_feed_widget()`
- Build `FeedTab` container with bottom tabs (Gtk.Stack + Gtk.StackSwitcher)
- Add all CSS classes to `APP_CSS`
- **Verification:** Can create FeedCardData, render it as a card widget, and display in FeedTab

### Phase 2 — FeedHandler + FeedStore + Wiring

**Files:** `ui/handlers/feed_handler.py`, `utils/feed_store.py`, `ui/views/feed_tab.py` (add scroll_to_bottom), `ui/window.py`

- Build `utils/feed_store.py` — load_feed, save_feed, append_feed_card, update_feed_card
- Add `to_dict()` / `from_dict()` serialization to `models/feed_card.py`
- Build `FeedHandler` with card lifecycle and button handlers
- Add `scroll_to_bottom()` method to `FeedTab`
- Wire FeedHandler into window._build() with callbacks
- Wire FeedTab into project tab layout (via ProjectHandler)
- Wire project open/close hooks
- Wire Review → populate input box
- **On project open:** load feed.json → render cards → switch to Feed tab → auto-scroll to bottom
- **On card add:** persist to feed.json
- **On accept/reject:** persist updated card state to feed.json
- **Verification:** Open project → see persisted cards in Feed tab → add test card → close project → reopen → card still there

### Phase 3 — Crabcard Intercept

**Files:** `utils/crabcard_parser.py`, `ui/handlers/chat_render_handler.py`, `ui/views/chat_bubble.py`

- Build `extract_crabcards()` parser
- Modify `chat_render_handler.render_sync()` to call extract_crabcards before rendering
- Route extracted cards to FeedHandler via callback
- Render feed reference widget in place of crabcard blocks in chat
- **Verification:** Agent message with crabcard → card appears in feed, reference in chat, clicking reference switches to feed tab

### Phase 4 — Accept/Reject (Git Integration)

**Files:** `ui/handlers/feed_handler.py` (extends handle_accept, handle_reject)

- Wire Accept → `git_ops.stage_all()` + `git_ops.commit()`
- Wire Reject → `git_ops.checkout_paths()` + agent notification
- Visual feedback (green checkmark / red X) on cards after action
- Background threading for git ops + GLib.idle_add for UI updates
- **Verification:** Diff card in feed → Accept → git commit logged → card shows checkmark

### Phase 5 — CrabWatch (File Watcher)

**Files:** `ui/handlers/crabwatch_handler.py`, `ui/window.py` (extends wiring)

- Build `CrabWatchHandler` with `Gio.FileMonitor` per project
- Map Gio events to FeedCardData types
- Implement ignored patterns (.git, node_modules, etc.)
- Implement 200ms debounce for duplicate events
- Wire CrabWatchHandler into window._build() with `on_filesystem_event` callback
- Wire project open/close to start/stop watching
- **Verification:** Open project → edit file externally → system card appears in feed

---

## Relationship to review-layer.md

This document **supersedes** `docs/review-layer.md`. The review-layer concepts are absorbed:

| review-layer.md Concept | Project Feed Location |
|---|---|
| `utils/git_ops.py` | Unchanged — FeedHandler calls it |
| `utils/diff_parser.py` | Unchanged — feed_card.py uses it for diff body rendering |
| `models/review_state.py` | **Removed** — FeedCardData.accepted replaces session state |
| `ui/views/diff_card.py` | **Removed** — feed_card.py is the single factory |
| `ui/views/review_bar.py` | **Removed** — feed is always visible, no overlay |
| `ui/handlers/review_handler.py` | **Removed** — FeedHandler handles all review actions |
| `ui/handlers/crabwatch_handler.py` | **New** — internal file watcher, replaces external CrabWatch concept |
| Checkpoint/accept/reject flow | Accept/Reject buttons on each card |
| Visual diff rendering | feed_card.py diff body rendering |

`docs/review-layer.md` should be archived (moved to `docs/archive/`) after Project Feed is implemented.

---

*This document is the single source of truth for the Project Feed feature. All implementation must follow ARCHITECTURE.md patterns and the specifications defined here.*
