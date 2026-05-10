# Conversation Snapshot — Proposal

> **Status: IMPLEMENTED** — `models/conversation_snapshot.py`, `utils/conversation_store.py`, and snapshot creation in `ui/handlers/feed_handler.py` all exist. The `tab_key` fix resolved project session lookups.

**Last updated:** 2026-05-04
**Depends on:** Existing Project Feed (see `docs/PROJECT_FEED.md`), `docs/ARCHITECTURE.md`
**Author:** Qaster, per Captain JAQx request

---

## Overview

When a user clicks **Review** on a feed card, they currently get a text prompt injected into the input box. This proposal upgrades Review into an **inline context panel** that shows *why* the card was created:

- **Agent cards** (from crabcard blocks): show the conversation messages leading up to the card
- **System cards** (from CrabWatch): show the git diff of what changed on disk

No new tabs. No full chat history persistence. The context is **snapshotted at card creation time** and stored with the card.

---

## UX Behavior

### Current Behavior (before this proposal)

1. User clicks **Review** on a feed card
2. A review prompt is injected into the input box (e.g., "Review changes to src/main.py +5/-3 lines. Verify correctness.")
3. User must manually scroll through chat to find the original conversation

### Proposed Behavior

1. User clicks **Review** on a feed card
2. The card **expands downward**, revealing an inline context panel:
   - **Agent cards:** the last N chat messages from the session that created the card, rendered as compact mini-bubbles
   - **System cards:** a git diff showing what changed on disk, rendered as monospace diff text
3. The review prompt is **also** injected into the input box (current behavior preserved)
4. Clicking **Review** again (or clicking a collapse toggle) collapses the panel

### Visual Layout — Expanded Agent Card

```
┌──────────────────────────────────────────────┐
│ ● Added auth middleware to main.py     [📋]  │  ← Header (unchanged)
├──────────────────────────────────────────────┤
│ 📄 src/main.py                               │  ← Body (unchanged)
│ +from auth import middleware                  │
│ +app.use(middleware())                        │
├──────────────────────────────────────────────┤
│ ▼ Review Context                              │  ← NEW: expandable section
│ ┌────────────────────────────────────────┐    │
│ │ You: update the auth middleware        │    │  ← mini-bubble (user)
│ │ Agent: I'll add the auth middleware... │    │  ← mini-bubble (agent)
│ │ Agent: [crabcard: Added auth mid...]   │    │  ← mini-bubble (agent, with ref chip)
│ └────────────────────────────────────────┘    │
├──────────────────────────────────────────────┤
│ Author • 2 min ago                           │  ← Footer (unchanged)
│ [Review ▼]  [Accept]  [Reject]               │  ← Actions (Review toggles)
└──────────────────────────────────────────────┘
```

### Visual Layout — Expanded System Card (CrabWatch)

```
┌──────────────────────────────────────────────┐
│ ● Modified src/utils/helpers.py       [📋]   │  ← Header (unchanged)
├──────────────────────────────────────────────┤
│ ✏️ src/utils/helpers.py                       │  ← Body (unchanged)
├──────────────────────────────────────────────┤
│ ▼ Diff Context                                │  ← NEW: expandable section
│ ┌────────────────────────────────────────┐    │
│ │ -def old_helper():                     │    │  ← diff (red/green styling)
│ │ +def new_helper(x, y):                 │    │
│ │ +    return x + y                      │    │
│ └────────────────────────────────────────┘    │
├──────────────────────────────────────────────┤
│ system • 5 min ago                           │  ← Footer (unchanged)
│ [Review ▼]  [Accept]  [Reject]               │  ← Actions
└──────────────────────────────────────────────┘
```

---

## Architecture

### Package Rules (per ARCHITECTURE.md Section 2)

| New Module | Package | May Import From | May NOT Import From |
|------------|---------|----------------|-------------------|
| `models/conversation_snapshot.py` | `models/` | Nothing external | `ui/`, `gateway/`, `agent/` |
| `utils/conversation_store.py` | `utils/` | `models/` | `ui/`, `gateway/`, `agent/` |

No new handlers needed. Modifications to existing modules only.

### Module Inventory

| Module | Package | Type | Responsibility |
|--------|---------|------|---------------|
| `models/conversation_snapshot.py` | `models/` | **NEW** | `ConversationSnapshot` dataclass — stores message list with serialization |
| `utils/conversation_store.py` | `utils/` | **NEW** | `snapshot_from_messages()`, `snapshot_from_git_diff()` — snapshot creation utilities |
| `models/feed_card.py` | `models/` | **MODIFIED** | Add `conversation_snapshot: ConversationSnapshot \| None = None` field |
| `ui/views/feed_card.py` | `ui/views/` | **MODIFIED** | Add expandable context panel rendering in `build_feed_card()` |
| `ui/handlers/feed_handler.py` | `ui/handlers/` | **MODIFIED** | Snapshot creation in `add_card()` + `on_filesystem_event()` |
| `ui/window.py` | `ui/` | **MODIFIED** | Pass `MainContent` reference to `FeedHandler` for chat box access |
| `ui/styles.py` | `ui/` | **MODIFIED** | Add CSS for context panel, mini-bubbles, diff display |

---

## Module Specifications

### `models/conversation_snapshot.py` — NEW

**Package:** `models/` — pure Python, no GTK, no git, no network.
**Architecture rule:** Foundation that `ui/` depends on — not the other way around.

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SnapshotMessage:
    """A single message in a conversation snapshot."""
    role: str           # "User" | "Agent" | "System"
    text: str           # Message content (plain text, truncated if long)
    timestamp: str | None = None   # ISO format, optional

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotMessage": ...


@dataclass
class ConversationSnapshot:
    """
    A frozen snapshot of conversation context that produced a feed card.

    For agent cards: contains the last N messages from the chat session.
    For system cards: contains a git diff string.
    """
    snapshot_type: str  # "conversation" | "diff"
    messages: list[SnapshotMessage] = field(default_factory=list)  # for "conversation"
    diff_text: str = ""                                            # for "diff"
    session_key: str = ""         # session that produced this card
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # How many messages were available (may be > len(messages) if truncated)
    total_messages: int = 0

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "ConversationSnapshot": ...
```

**Serialization:** The `ConversationSnapshot` is stored inside `FeedCardData.metadata["snapshot"]` as a dict (via `to_dict()`). This keeps `feed.json` self-contained — no separate files needed.

**Size limit:** Snapshots are capped at **5 messages** (configurable via `MAX_SNAPSHOT_MESSAGES` in `conversation_store.py`) and **2000 characters per message** (truncated with `…`). Snapshots exceeding **50KB** are rendered in-memory but **not persisted** to `feed.json` (a warning is logged).

---

### `utils/conversation_store.py` — NEW

**Package:** `utils/` — may import from `models/` only. No GTK, no network.

```python
from models.conversation_snapshot import ConversationSnapshot, SnapshotMessage
from models.feed_card import FeedCardData

# ── Snapshot creation ────────────────────────────────────────────────────

def snapshot_from_messages(
    chat_box: "Gtk.Box",
    session_key: str,
    max_messages: int = 5,  # ← SNAPSHOT MESSAGE LIMIT — adjust if needed
    max_chars_per_message: int = 2000,
) -> ConversationSnapshot:
    """
    Walk the children of a Gtk.Box (chat_box) and extract recent messages.

    Gtk.Box children are chat bubbles. Each bubble is expected to have:
      - A data attribute or accessible text indicating role and content
      - OR a child structure that can be introspected

    Implementation approach:
      1. Iterate chat_box children (Gtk.Widgets) from last to first
      2. For each child, attempt to extract:
         - role: look for CSS class or stored attribute
         - text: get_label() or get_text() on descendant labels
      3. Collect up to max_messages
      4. Return ConversationSnapshot with snapshot_type="conversation"

    NOTE: The exact extraction method depends on how chat bubbles store
    their data. The recommended approach is to store role+text as
    custom attributes on the widget at creation time (see Modification
    to chat_bubble.py below).

    Args:
        chat_box: The Gtk.Box containing chat bubbles for a session.
        session_key: The session key for context.
        max_messages: Maximum number of messages to snapshot (default 10).
        max_chars_per_message: Truncate messages longer than this (default 2000).

    Returns:
        ConversationSnapshot with snapshot_type="conversation".
    """


def snapshot_from_git_diff(
    project_path: str,
    file_path: str,
) -> ConversationSnapshot:
    """
    Create a snapshot from git diff for a file change.

    Implementation:
      1. Call git_ops.diff_file_against(project_path, "HEAD", file_path)
      2. If HEAD doesn't exist (new repo), try git_ops.status() for untracked
      3. Return ConversationSnapshot with snapshot_type="diff" and diff_text
      4. If diff fails, return empty snapshot with a note

    Args:
        project_path: Absolute path to the project root.
        file_path: Relative path to the changed file.

    Returns:
        ConversationSnapshot with snapshot_type="diff".
    """
```

---

### Modifications to Existing Modules

#### `models/feed_card.py` — MODIFIED

Add one field to `FeedCardData`:

```python
@dataclass
class FeedCardData:
    # ... existing fields ...

    # NEW: Conversation snapshot (set by FeedHandler at card creation time)
    conversation_snapshot: "ConversationSnapshot | None" = None
```

**Serialization changes:**
- `to_dict()`: serialize `conversation_snapshot` as `metadata["snapshot"]` (a dict) if present
- `from_dict()`: deserialize `metadata["snapshot"]` back into `ConversationSnapshot` if present

This keeps the snapshot nested inside metadata — no new top-level keys in `feed.json`.

#### `ui/views/chat_bubble.py` — MODIFIED

Add custom attributes to chat bubbles at creation time so `snapshot_from_messages()` can extract them:

```python
# In build_role_bubble(), after creating the root widget:
widget._crabcakes_role = role       # "User", "Agent", "System"
widget._crabcakes_text = text       # raw message text
```

These are simple Python attributes on the GTK widget object — no GTK API needed. The `snapshot_from_messages()` function reads these attributes when walking the chat box children.

**Why this approach:** GTK widgets are regular Python objects. Adding custom attributes is standard practice and avoids maintaining a separate message store. The attributes live as long as the widget lives.

#### `ui/views/feed_card.py` — MODIFIED

**New function:**

```python
def build_context_panel(
    snapshot: ConversationSnapshot,
) -> Gtk.Widget:
    """
    Build the expandable context panel for a feed card.

    For snapshot_type="conversation":
      - Vertical box of compact mini-bubbles (role + text)
      - User messages: right-aligned, muted background
      - Agent messages: left-aligned, default background
      - CSS class: .feed-context-panel

    For snapshot_type="diff":
      - Monospace label with diff text
      - Red/green styling for -/+ lines
      - CSS class: .feed-context-diff

    Returns a Gtk.Box with CSS class "feed-context-panel".
    Initially hidden (set_visible(False)). Toggled by Review button.
    """
```

**Modification to `build_feed_card()`:**

After the action buttons section, if `card_data.conversation_snapshot` is not None:
1. Call `build_context_panel(snapshot)` to create the panel widget
2. Append it to the card (after actions, at the bottom)
3. Store a reference on the card widget: `card._context_panel = panel`
4. The panel starts hidden (`panel.set_visible(False)`)

**Modification to Review button behavior:**

The Review button callback toggles the context panel visibility:
- If panel is hidden → show it, inject review prompt into input
- If panel is visible → hide it (collapse)

The `on_review` callback signature changes from `Callable[[str], None]` to `Callable[[str, Gtk.Widget], None]` — it now receives the card widget as a second argument so it can toggle the panel.

#### `ui/handlers/feed_handler.py` — MODIFIED

**Constructor change:**

Add a new callback parameter for chat box access:

```python
def __init__(
    self,
    *,
    GLib,
    on_populate_input,
    on_send_to_agent,
    on_tab_switch,
    on_card_added=None,
    get_chat_box_for_session: "Callable[[str], Gtk.Box | None]" = None,  # NEW
):
```

**`add_card()` changes:**

After creating the card_id but before building the widget, create a conversation snapshot:

```python
# For agent-sourced cards (from crabcard blocks):
if card_data.source == "agent" and self._get_chat_box_for_session:
    session_key = card_data.metadata.get("session_key", "")
    chat_box = self._get_chat_box_for_session(session_key)
    if chat_box is not None:
        snapshot = conversation_store.snapshot_from_messages(messages_raw, session_key)
        card_data.conversation_snapshot = snapshot
```

**`on_filesystem_event()` changes:**

For CrabWatch system cards, create a diff snapshot:

```python
# In on_filesystem_event(), after constructing the FeedCardData:
project_path = self._project_paths.get(card_data.project_name, "")
if project_path and card_data.file_path:
    snapshot = conversation_store.snapshot_from_git_diff(project_path, card_data.file_path)
    card_data.conversation_snapshot = snapshot
```

**`handle_review()` changes:**

The review handler now receives the card widget and toggles the context panel:

```python
def handle_review(self, card_id: str, card_widget: "Gtk.Widget | None" = None) -> None:
    # ... existing review prompt logic ...

    # NEW: Toggle context panel visibility
    if card_widget is not None and hasattr(card_widget, '_context_panel'):
        panel = card_widget._context_panel
        panel.set_visible(not panel.get_visible())
```

#### `ui/window.py` — MODIFIED

Pass `MainContent.get_chat_box_for_session` to `FeedHandler`:

```python
# In _build(), when constructing FeedHandler:
self._feed_handler = FeedHandler(
    GLib=GLib,
    on_populate_input=self._main_content.populate_input,
    on_send_to_agent=self._chat_handler.send_raw_message,
    on_tab_switch=self._left_panel.switch_to_feed_tab,
    on_card_added=lambda cid: None,
    get_chat_box_for_session=self._main_content.get_chat_box_for_session,  # NEW
)
```

Update `_on_crabcards_extracted` to store `session_key` on card metadata:

```python
def _on_crabcards_extracted(cards: list, session_key: str):
    from ui.views.chat_bubble import _set_crabcards_registry
    _set_crabcards_registry(cards, _on_show_feed_subtab)
    for card in cards:
        card.metadata["session_key"] = session_key  # NEW: for snapshot extraction
        self._feed_handler.add_card(card)
```

#### `ui/styles.py` — MODIFIED

Add CSS for the new context panel:

```css
/* ── Feed Card Context Panel ────────────────────────────────────── */
.feed-context-panel {
    background: alpha(@theme_bg_color, 0.5);
    border-top: 1px solid alpha(@theme_fg_color, 0.1);
    border-radius: 0 0 8px 8px;
    padding: 8px;
    margin: 4px 6px 6px 6px;
}

.feed-context-mini-bubble {
    padding: 4px 8px;
    border-radius: 6px;
    margin: 2px 0;
    font-size: 0.85em;
}

.feed-context-mini-bubble-user {
    background: alpha(@theme_selected_bg_color, 0.15);
    margin-left: 24px;
}

.feed-context-mini-bubble-agent {
    background: alpha(@theme_fg_color, 0.08);
    margin-right: 24px;
}

.feed-context-diff {
    font-family: monospace;
    font-size: 0.82em;
    padding: 8px;
    background: alpha(#1e1e1e, 0.9);
    border-radius: 4px;
    color: #d4d4d4;
    white-space: pre;
}

.feed-context-diff-line-add {
    color: #6a9955;
}

.feed-context-diff-line-del {
    color: #f44747;
}

.feed-context-empty {
    color: alpha(@theme_fg_color, 0.4);
    font-style: italic;
    padding: 8px;
    text-align: center;
}
```

---

## Data Flow

### Agent Card Creation (with snapshot)

```
Agent sends message containing ```crabcard block
  → ChatRenderHandler.render_sync()
    → extract_crabcards(text) → (cleaned_text, cards)
    → Each card gets metadata["session_key"] = session_key (NEW in window.py)
  → _on_crabcards_extracted callback fires with (cards, session_key)
    → FeedHandler.add_card(card_data)
      → NEW: get_chat_box_for_session(session_key) → Gtk.Box
      → NEW: conversation_store.snapshot_from_messages(messages_raw, session_key)
      → NEW: card_data.conversation_snapshot = snapshot
      → build_feed_card(card_data, ...) — now includes context panel
      → feed_store.append_feed_card() — snapshot serialized to metadata["snapshot"]
```

### System Card Creation (with diff snapshot)

```
CrabWatch detects file change
  → CrabWatchHandler._on_monitor_event()
    → constructs FeedCardData(source="crabwatch")
    → FeedHandler.on_filesystem_event(card_data)
      → NEW: conversation_store.snapshot_from_git_diff(project_path, file_path)
      → NEW: card_data.conversation_snapshot = snapshot
      → FeedHandler.add_card(card_data)
        → build_feed_card(card_data, ...) — now includes context panel
        → feed_store.append_feed_card()
```

### Review Button Click (expanded behavior)

```
User clicks Review on card
  → on_review(card_id, card_widget)  ← NEW: widget passed as 2nd arg
    → FeedHandler.handle_review(card_id, card_widget)
      → Builds review prompt text (existing behavior)
      → Injects prompt into input box (existing behavior)
      → NEW: toggles card_widget._context_panel visibility
      → Switches to feed tab (existing behavior)
```

---

## Persistence Format

The snapshot is stored inside `feed.json` as part of the card's `metadata` dict:

```json
{
  "card_type": "diff",
  "source": "agent",
  "title": "Added auth middleware to main.py",
  "body": "+from auth import middleware\n+app.use(middleware())",
  "author": "qaster",
  "timestamp": "2026-05-04T14:30:00+00:00",
  "project_name": "crabcakes",
  "file_path": "src/main.py",
  "metadata": {
    "session_key": "agent:qaster:telegram:direct:7478874934",
    "project_path": "/home/q/projects/crabcakes",
    "snapshot": {
      "snapshot_type": "conversation",
      "messages": [
        {"role": "User", "text": "update the auth middleware", "timestamp": null},
        {"role": "Agent", "text": "I'll add the auth middleware to main.py...", "timestamp": null},
        {"role": "Agent", "text": "Done. I've added the middleware import and...", "timestamp": null}
      ],
      "session_key": "agent:qaster:telegram:direct:7478874934",
      "captured_at": "2026-05-04T14:30:00+00:00",
      "total_messages": 3
    }
  }
}
```

For system cards with a diff:

```json
{
  "card_type": "file_modified",
  "source": "crabwatch",
  "metadata": {
    "snapshot": {
      "snapshot_type": "diff",
      "messages": [],
      "diff_text": "diff --git a/src/utils/helpers.py b/src/utils/helpers.py\n-old_helper()\n+new_helper(x, y)\n+    return x + y",
      "session_key": "",
      "captured_at": "2026-05-04T14:35:00+00:00",
      "total_messages": 0
    }
  }
}
```

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Card created before this feature was deployed (old `feed.json`) | `from_dict()` finds no snapshot in metadata → `conversation_snapshot = None` → no context panel rendered. Review button works as before (input box only). |
| Chat tab already closed when card is created | `get_chat_box_for_session()` returns None → snapshot is skipped. Card has no context panel. Graceful degradation. |
| Project has no git repo | `snapshot_from_git_diff()` returns empty snapshot with `diff_text=""`. Context panel shows "No diff available." |
| Very long conversation (>5 messages) | `snapshot_from_messages()` captures the last 5 messages. `total_messages` field indicates truncation. Panel shows "Showing last 5 of 47 messages" if truncated. |
| Very long individual messages (>2000 chars) | Truncated to 2000 chars with "…" suffix. |
| Binary file changed (no readable diff) | `snapshot_from_git_diff()` returns snapshot with `diff_text="Binary file changed."` |

---

## Implementation Order

| Step | Module | Change | Lines (est.) |
|------|--------|--------|-------------|
| 1 | `models/conversation_snapshot.py` | New file — dataclasses + serialization | ~80 |
| 2 | `utils/conversation_store.py` | New file — snapshot_from_messages + snapshot_from_git_diff + `MAX_SNAPSHOT_MESSAGES` / `MAX_SNAPSHOT_SIZE_KB` constants | ~120 |
| 3 | `models/feed_card.py` | Add `conversation_snapshot` field + serialization | ~15 |
| 4 | `ui/views/chat_bubble.py` | Store `_crabcakes_role` and `_crabcakes_text` on widgets | ~5 |
| 5 | `ui/views/feed_card.py` | Add `build_context_panel()` + modify `build_feed_card()` | ~120 |
| 6 | `ui/handlers/feed_handler.py` | Snapshot creation in add_card/on_filesystem_event, toggle in handle_review | ~40 |
| 7 | `ui/window.py` | Pass get_chat_box_for_session + store session_key in metadata | ~10 |
| 8 | `ui/styles.py` | Context panel CSS | ~50 |
| **Total** | | | **~440 lines** |

---

## What This Does NOT Do

This proposal intentionally does **not** include:

- **Full chat history persistence** — only snapshots relevant to cards are saved
- **Searchable message archive** — snapshots are opaque blobs on cards
- **Cross-card conversation threading** — each card has its own isolated snapshot
- **Editable snapshots** — they're read-only historical records
- **Streaming/syncing snapshots** — they're captured once at creation time and frozen

These are deliberate scope boundaries. Future phases could build on top of the snapshot infrastructure if needed.

---

## Naming Convention

| Term | Meaning |
|------|---------|
| **Snapshot** | A frozen copy of conversation context at a point in time |
| **Context Panel** | The expandable UI section in a feed card showing the snapshot |
| **Mini-bubble** | A compact chat message rendered inside the context panel |
| **Diff snapshot** | A snapshot containing git diff text instead of conversation messages |

---

## Decisions (resolved by Captain JAQx)

1. **Default expanded/collapsed?** → **Collapsed.** Click Review to expand. Click again to collapse.
2. **Message count limit** → **5 messages.** Configurable via `MAX_SNAPSHOT_MESSAGES` constant in `utils/conversation_store.py` with a prominent comment.
3. **Diff for agent cards too?** → **No.** Agent cards get conversation only. System cards get diff only. Clean separation for v1.
4. **Snapshot size cap** → **Yes, 50KB.** Skip persisting to `feed.json` if snapshot exceeds 50KB, but still render in-memory. Log a warning when skipping.

---

*This proposal is ready for review. Once approved, any agent with access to this document and `docs/ARCHITECTURE.md` should be able to implement it without additional context.*
