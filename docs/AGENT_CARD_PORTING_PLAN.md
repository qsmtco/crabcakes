# Agent Card Porting Plan — Deadcode → CrabCakes

**Date:** 2026-04-11
**Author:** Qaster
**Status:** Plan only — no code changes made

---

## What We're Porting

The agent avatar card system from `/home/q/projects/deadcode/src/ui/widgets.py` — specifically the `render_agent_icon()` function and its associated CSS/styles. This gives CrabCakes polished, colorful avatar cards in the Agents tab instead of plain text rows.

---

## Current State

### Deadcode (source)
- `src/ui/widgets.py` — `render_agent_icon(color_hex, initials, size=44)` → renders SVG → `Gdk.Texture`
- `src/ui/sidebar.py` — `AgentSelectorPanel._build_row()` wires the avatar into each agent row
- `src/styles.py` — CSS for `.agent-row`, `.agent-avatar-*`, `.agent-chat-btn`, `.agent-add-btn`

### CrabCakes (target)
- `ui/views/left_panel.py` — agents are plain clickable text rows in a `Gtk.ListBox`
- `models/colors.py` — already has `AGENT_COLORS` palette (matches deadcode's)
- No icon rendering utility exists yet

---

## Visual Design Being Ported

Each agent card is a horizontal row:
```
┌──────────────────────────────────────────┐
│  [Avatar]   Agent Name         [+] [Chat]│
│  44×44px    left-aligned       right side│
└──────────────────────────────────────────┘
```

**Avatar:** Colored circle (44×44) with inscribed hexagon outline + 2-letter white initials. Rendered programmatically as SVG at runtime — no image files needed.

**Colors:** 10-color round-robin palette — pink, purple, deep purple, indigo, blue, cyan, teal, green, orange, deep orange.

**Row:** Dark semi-transparent background, 6px border radius. Hover shows indigo tint + indigo border.

**Buttons:** "+" (green-tinted, for adding to project) and "Chat" (indigo-tinted, to open chat tab).

---

## Step-by-Step Plan

### Step 1: Create `utils/icons.py`

Copy `render_agent_icon()` from deadcode's `src/ui/widgets.py` (~60 lines). The function:
- Takes `color_hex` (string), `initials` (string), `size` (int, default 44)
- Generates SVG with: circle fill, hexagon path stroke, centered bold text
- Writes to temp file, loads as `Gdk.Texture`, deletes temp file
- Returns `Gdk.Texture` for use with `Gtk.Picture`

Dependencies: `math`, `os`, `tempfile`, `gi.repository.Gdk` — all standard.

### Step 2: Verify Color Palette

Compare `models/colors.py` `AGENT_COLORS` with deadcode's palette. Should match. If any colors are missing, add them.

### Step 3: Create `ui/handlers/agent_list_handler.py`

**Per architecture Section 8.6:** All new UI logic must go in a handler.

The handler owns:
- Agent card rendering data (computing initials, color assignment)
- Chat button click logic (delegating to `on_agent_chat` callback)
- Add/remove from project logic (delegating to `on_agent_toggle` callback)
- Active agent tracking (which agent's tab is currently visible)

```python
class AgentListHandler:
    def __init__(self, *, agent_mgr=None,
                 on_agent_chat=None, on_agent_toggle=None):
        ...

    def compute_initials(self, name: str) -> str:
        """Derive 2-letter initials from agent name."""

    def get_agent_color(self, agent_name: str) -> str:
        """Get hex color for agent from AgentManager."""

    def get_sorted_agents(self) -> list[tuple[str, str]]:
        """Return [(session_key, name)] grouped by agent, prefer :main session."""

    def on_chat_clicked(self, session_key: str, name: str):
        """Handle Chat button click via callback."""

    def on_toggle_clicked(self, session_key: str, name: str):
        """Handle +/− button click via callback."""
```

**Handler rules (per Section 8.6):**
- Does NOT import other handlers
- Receives dependencies via constructor
- No GTK imports — purely logic and data
- `window.py` wires callbacks between this handler and other handlers/views

### Step 4: Update `ui/views/left_panel.py`

In the agent row builder, replace plain text rows with card layout:
- Import `render_agent_icon` from `utils.icons`
- Call `AgentListHandler` methods for initials, colors, sorting
- Build row layout:
  - `Gtk.Picture` for avatar (44×44) via `render_agent_icon(color, initials)`
  - `Gtk.Label` for agent name (14px, #e8e8ec)
  - `Gtk.Box` with Chat button and +/− button (project membership toggle)
- Connect buttons to handler methods
- Keep existing click-to-open-chat behavior

**Wiring in `window.py`:**
```python
self._agent_list_handler = AgentListHandler(
    agent_mgr=self._agent_mgr,
    on_agent_chat=self._chat_handler.on_send,
    on_agent_toggle=self._on_project_members_changed,
)
self._left_panel.set_agent_list_handler(self._agent_list_handler)
```

### Step 4: Add CSS

Port these CSS classes from deadcode's `styles.py` into CrabCakes's CSS provider:
- `.agent-row` — dark background, rounded, hover effect
- `.agent-avatar-circle` + `.agent-avatar-lbl` — avatar styling
- `.agent-avatar-0` through `.agent-avatar-9` — color variants
- `.agent-chat-btn` — indigo-tinted chat button
- `.agent-add-btn` — green-tinted add button
- `.agent-name-label` — white text, 14px

### Step 6: Update `ARCHITECTURE.md`

- Add `utils/icons.py` to Section 11 file inventory
- Add `ui/handlers/agent_list_handler.py` to Section 3 and Section 11
- Document `AgentListHandler` public API in Section 3
- Document `render_agent_icon()` in Section 3.9 (utils)
- Update line counts

### Step 7: Tests

**`tests/test_icons.py`** (new):
- Test `render_agent_icon()` with valid inputs → returns non-None texture
- Test with edge cases: single char name, empty initials, size boundaries
- Note: full texture rendering requires GDK display; mock or skip in headless CI

**`tests/test_agent_list_handler.py`** (new):
- Test `compute_initials()` — two words, one word, empty string
- Test `get_sorted_agents()` — grouping, :main preference
- Test callbacks fire correctly on chat/toggle clicks

### Step 8: Commit & Push

```
git add -A
git commit -m "feat: add agent avatar cards with hexagon icon rendering"
git push
```

---

## Files Changed

| File | Action |
|------|--------|
| `utils/icons.py` | NEW — `render_agent_icon()` function |
| `ui/handlers/agent_list_handler.py` | NEW — agent card logic handler (Section 8.6 compliance) |
| `ui/views/left_panel.py` | MODIFY — replace text rows with avatar cards |
| `ui/window.py` | MODIFY — wire AgentListHandler |
| `ARCHITECTURE.md` | MODIFY — document new files, handler, and function |
| `tests/test_icons.py` | NEW — icon rendering tests |
| `tests/test_agent_list_handler.py` | NEW — handler logic tests |

CSS may go in an existing styles file or a new one depending on how CrabCakes manages its CSS provider.

---

## Architecture Compliance Notes

**Why `ui/handlers/agent_list_handler.py`:**
Section 8.6 mandates all new UI logic goes in handlers. Computing initials, assigning colors, sorting agents, and handling button clicks are all logic that belongs in a handler — not in the view.

**No handler-to-handler imports:**
`AgentListHandler` does NOT import `ChatHandler`. When the Chat button is clicked, it calls the `on_agent_chat` callback, which `window.py` wires to `ChatHandler`.

**`utils/icons.py` for rendering:**
`render_agent_icon()` uses `Gdk.Texture` (GTK dependency). Per architecture, `utils/` can use GTK — it's not `gateway/` or `models/` which must remain GTK-free.

## Risks / Notes

- The SVG→temp file→texture approach works but creates temporary I/O on every avatar render. For a small number of agents (<50) this is negligible.
- `Gdk.Texture.new_from_filename()` requires a running GDK display — tests need mocking or `Gtk.init()` in setup.
- The function is GTK4-only (uses `Gdk.Texture`) — cannot go in `gateway/` or `models/` per architecture rules. `utils/` is the right home.
