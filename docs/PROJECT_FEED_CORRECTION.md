# Project Feed — Implementation Correction
## Correct UX and Complete Re-Implementation

**Document purpose:** This is the **only** authoritative spec for the Project Feed implementation.
PROJECT_FEED.md is superseded and should be ignored.

**Last updated:** 2026-04-29
**Status:** This document describes what must be built. No code has been written yet for the corrected implementation.
**Depends on:** ARCHITECTURE.md, existing models/ (feed_card.py, etc.), existing ui/views/feed_tab.py, existing ui/handlers/feed_handler.py

---

## Correct Understanding (Confirmed with Captain)

### User Flow

```
1. App opens → Left panel "Projects" tab shows project card list
   └── FileTree widget visible, notebook page index 2 (Projects tab)

2. User clicks a project card → LEFT PANEL PROJECTS TAB TRANSFORMS into project view
   └── Projects tab now shows FeedTab: [File Tree | Feed] sub-tabs
   └── Feed sub-tab is DEFAULT on open
   └── FileTree sub-tab shows the file tree for this project
   └── Original project card list is GONE (hidden, not destroyed)

3. User clicks a different project card → FeedTab loads that project's feed
   └── Same Projects tab, same FeedTab, different project data
   └── FileTree sub-tab updates to new project's tree

4. User closes project (← back button or X) → Projects tab returns to card list
   └── FeedTab is removed/hidden from Projects tab
   └── FileTree is restored/shown
   └── Project card list visible again
```

**Key invariant:** The Projects tab in LeftPanel is NEVER destroyed and rebuilt. It is transformed between two states:
- **Picker state:** Shows `FileTree` with project card list
- **Project state:** Shows `FeedTab` with File Tree / Feed sub-tabs

**No project chat tab in MainContent.** Opening a project does NOT create a tab in the main content notebook. The main content area is unchanged by project open/close.

---

## What The Current Code Does Wrong

### Problem 1: FeedTab is placed in the wrong location

**Current (wrong):**
```
MainContent (right panel)
├── Chat notebook (agent chat tabs)
└── Project bottom widget: FeedTab ← WRONG LOCATION
```

**Correct:**
```
LeftPanel (left sidebar)
├── Notebook
│   ├── [0] Prompts tab
│   ├── [1] Agents tab
│   └── [2] Projects tab
        └── FeedTab ← CORRECT LOCATION
```

`FeedTab` is currently being added to `MainContent` via `set_project_bottom_widget()`, but `MainContent` is the right-side chat panel. The Projects tab in `LeftPanel` still shows `FileTree`.

### Problem 2: Project open creates a chat tab in MainContent

**Current code in `project_handler.py` `open_project()`:**
```python
self._dispatch(lambda: self._mc.create_chat_tab(f"project:{name}", f"Project: {name}"))
```

This creates a new tab in `MainContent`'s notebook — like opening a chat with an agent. This is wrong. The spec says the **Projects tab transforms**, not that a new tab opens in main content.

### Problem 3: FeedTab is created once and shared awkwardly

**Current:**
```python
self._feed_tab = FeedTab(file_tree=left_panel._file_tree)  # shares FileTree
self._main_content.set_project_bottom_widget(n, self._feed_tab)  # adds to main content
```

`FeedTab` is created in `window.py` and awkwardly shared with `left_panel._file_tree`. The FileTree is passed into FeedTab as its "files" sub-tab, but then FeedTab is placed in MainContent's bottom. This is backwards.

### Problem 4: set_project_bottom_widget mechanism is wrong

`MainContent.set_project_bottom_widget()` adds FeedTab below the chat area in a project "chat" tab. This doesn't match the spec at all.

---

## Complete Removal List

The following code must be **completely removed**:

### 1. `ui/views/main_content.py` — Remove bottom widget mechanism

**Remove:**
- `_project_bottom_widget: tuple | None` instance variable
- `set_project_bottom_widget(self, project_name: str, widget: Gtk.Widget)` method
- `clear_project_bottom_widget(self)` method
- `_on_project_tab_close()` callback that calls `clear_project_bottom_widget()`
- Any CSS or layout code related to `_project_bottom_widget`

**Keep:**
- Everything else — `MainContent` manages chat tabs only, nothing project-specific

### 2. `ui/window.py` — Remove FeedTab creation and bottom widget wiring

**Remove:**
- `FeedTab` creation (`from ui.views.feed_tab import FeedTab`)
- `self._feed_tab = FeedTab(...)` — FeedTab is created in `LeftPanel`, not window
- `self._main_content.set_project_bottom_widget(n, self._feed_tab)` call
- `self._main_content.clear_project_bottom_widget()` call
- `on_tab_switch` callback referencing `self._feed_tab.show_feed_tab()`
- `FeedHandler` construction that passes `feed_tab=self._feed_tab` — window should pass a callback for tab switching instead
- The `_on_crabcards_extracted` callback that calls `self._feed_handler.add_card()` — this stays, but `feed_handler` needs to be created differently
- All `_on_feed_bar_update` calls related to FeedTab bottom widget
- `_on_populate_input` — this should live in `LeftPanel`, not window

**Keep:**
- `FeedHandler` creation (but constructor changes — see new implementation)
- `CrabWatchHandler` creation
- `CrabWatchHandler.start_watching()` call on project open
- `CrabWatchHandler.stop_watching()` call on project close
- `FeedHandler.on_project_opened()` call on project open
- `FeedHandler.on_project_closed()` call on project close
- Crabcard extraction wiring to FeedHandler (this is correct)

### 3. `ui/handlers/project_handler.py` — Remove chat tab creation

**Remove from `open_project()`:**
```python
self._dispatch(lambda: self._mc.create_chat_tab(f"project:{name}", f"Project: {name}"))
```
This line creates a chat tab in MainContent. Must be removed. The project view lives in LeftPanel's Projects tab.

**Remove from `close_project()`:**
- Any reference to closing a MainContent tab for the project (no such tab exists)

**Keep:**
- `_agent_to_project` routing table population (needed for ChatHandler fan-out)
- `_lp.refresh_agents_with_project(name)` — refreshes Agents tab to show +/− buttons
- `_on_project_opened` callbacks (feed loading, crabwatch start)
- `get_active_project_path()` — used by FeedHandler for persistence

**Note:** Since project tabs no longer exist in MainContent, the question of whether project sessions route chat to agents is replaced by a simpler model: the Feed lives in the Projects tab, and chat with agents happens in the main content area's agent tabs. When the user wants to chat with an agent about a project, they open an agent tab and @mention the project. This is existing behavior that stays unchanged.

### 4. `ui/views/left_panel.py` — No change needed for removal, but major restructure for new implementation

See implementation section below.

---

## New Implementation

### Overview

The Projects tab in `LeftPanel` becomes a `Gtk.Stack` with two pages:
- **"picker"** (default): `FileTree` showing project card list — normal state
- **"project"**: `FeedTab` showing File Tree / Feed sub-tabs — when a project is open

When a project is opened:
1. `LeftPanel` switches Projects tab stack to "project" page
2. `FeedTab` is populated with that project's data
3. File Tree / Feed sub-tabs within FeedTab work normally

When a project is closed:
1. `LeftPanel` switches Projects tab stack back to "picker" page
2. `FeedTab` is cleared
3. FileTree project card list is visible again

### File: `ui/views/left_panel.py` — Major Restructure

**Changes:**

The Projects tab (`notebook.append_page(self._file_tree, ...)`) is replaced with a `Gtk.Stack` that can switch between `FileTree` and `FeedTab`.

```python
class LeftPanel(Gtk.Box):
    def __init__(self, ...):
        # ... existing code ...

        # Projects tab: Gtk.Stack that can show "picker" (FileTree) or "project" (FeedTab)
        self._projects_stack = Gtk.Stack()
        self._projects_stack.set_vexpand(True)

        # "picker" page — FileTree with project cards
        self._file_tree = FileTree(on_file_selected=self._on_project_selected)
        self._projects_stack.add_titled(self._file_tree, "picker", "Projects")

        # "project" page — FeedTab (empty until project is opened)
        self._feed_tab = None  # created lazily on first project open

        # Stack switcher for the Projects tab — shows between picker/project
        self._projects_switcher = Gtk.StackSwitcher()
        self._projects_switcher.set_stack(self._projects_stack)

        # Notebook page: use the stack as the page child
        projects_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        projects_page.append(self._projects_switcher)  # optional: hide when on picker
        projects_page.append(self._projects_stack)
        PAP_notebook.append_page(projects_page, Gtk.Label(label="Projects"))
```

**New methods:**

```python
def open_project_view(self, feed_tab: "FeedTab") -> None:
    """
    Switch Projects tab from picker (FileTree) to project (FeedTab) view.
    Called by window when a project card is clicked.

    Args:
        feed_tab: FeedTab instance to show in the project view.
                  The FeedTab is created by LeftPanel on first project open.
    """
    # Add FeedTab to the "project" page if not already added
    if self._feed_tab is None:
        self._feed_tab = feed_tab
        self._projects_stack.add_titled(self._feed_tab, "project", "Project")
    else:
        # Already created — just make sure it's in the stack
        if self._feed_tab.get_parent() != self._projects_stack:
            self._projects_stack.add_named(self._feed_tab, "project")
    # Switch to project page
    self._projects_stack.set_visible_child_name("project")

def close_project_view(self) -> None:
    """
    Switch Projects tab from project (FeedTab) back to picker (FileTree) view.
    Called by window when user navigates back or closes project.
    """
    self._projects_stack.set_visible_child_name("picker")

def get_feed_tab(self) -> "FeedTab | None":
    """Return the FeedTab instance, creating it on first access."""
    return self._feed_tab
```

**Note:** The `FeedTab` must be created by `LeftPanel` (not `window.py`) because `FeedTab` needs the `FileTree` from `LeftPanel` for its sub-tabs. The `LeftPanel` creates the `FeedTab` lazily on first project open, passing its own `FileTree` into FeedTab.

### File: `ui/views/feed_tab.py` — Minor Adjustment

**No structural changes needed.** The existing `FeedTab` with its `Gtk.Stack` (Files | Feed sub-tabs) is correct.

The FeedTab should be created by `LeftPanel` on first project open. The `window.py` should NOT create FeedTab.

### File: `ui/handlers/feed_handler.py` — Constructor Change

**Change constructor signature:**

Remove `feed_tab` as a constructor dependency. Instead pass a callback for adding widgets to the feed tab:

```python
class FeedHandler:
    def __init__(
        self,
        *,
        GLib,                                   # gi.repository.GLib
        on_populate_input: Callable[[str], None],  # fill input box (Review)
        on_send_to_agent: Callable[[str, str], None],  # send to agent
        on_tab_switch: Callable[[], None],       # switch to feed sub-tab
    ):
```

**New internal method:**

```python
def set_feed_tab(self, feed_tab: FeedTab) -> None:
    """Set the FeedTab view. Called by window after FeedTab is created."""
    self._feed_tab = feed_tab
```

**Why this change:** `window.py` no longer creates `FeedTab` — `LeftPanel` does. So window can't pass FeedTab to FeedHandler in the constructor. Instead, `LeftPanel` tells FeedHandler about the FeedTab via `set_feed_tab()` after creating it.

### File: `ui/handlers/project_handler.py` — Remove chat tab creation

**In `open_project()` — REMOVE this line:**
```python
self._dispatch(lambda: self._mc.create_chat_tab(f"project:{name}", f"Project: {name}"))
```

**In `close_project()` — REMOVE any references to closing a project tab in `MainContent` (there shouldn't be any after the above fix).**

**Keep everything else:**
- Member routing table population
- `_lp.refresh_agents_with_project(name)`
- `_on_project_opened` callbacks

### File: `ui/window.py` — Complete Feedtab Wiring Overhaul

**Before (wrong):**
```python
# window creates FeedTab
self._feed_tab = FeedTab(file_tree=left_panel._file_tree)

# window adds FeedTab as bottom widget in MainContent
self._main_content.set_project_bottom_widget(n, self._feed_tab)

# window clears it on close
self._main_content.clear_project_bottom_widget()
```

**After (correct):**

```python
# FeedHandler created FIRST (before LeftPanel project wiring)
self._feed_handler = FeedHandler(
    GLib=GLib,
    on_populate_input=_on_populate_input,
    on_send_to_agent=_on_send_to_agent,
    on_tab_switch=_on_show_feed_subtab,
)

# LeftPanel creates FeedTab lazily and tells FeedHandler about it
# Wire LeftPanel → project open/close to switch Projects tab view
left_panel.set_on_project_view_opened(lambda name, path: (
    self._feed_handler.set_feed_tab(left_panel.get_feed_tab()),
    self._feed_handler.on_project_opened(name, path),
    self._crabwatch_handler.start_watching(path, name),
))
left_panel.set_on_project_view_closed(lambda: (
    self._feed_handler.on_project_closed(),
    self._crabwatch_handler.stop_watching(),
))

# FeedHandler card adds go through normal callback
def _on_crabcards_extracted(cards, session_key):
    for card in cards:
        self._feed_handler.add_card(card)
self._chat_render_handler.set_on_crabcard_extracted(_on_crabcards_extracted)
```

**What window still does (unchanged):**
- Creates `FeedHandler` and `CrabWatchHandler`
- Wires crabcard extraction from ChatRenderHandler to FeedHandler
- Wires `CrabWatchHandler.on_filesystem_event` → `FeedHandler.on_filesystem_event`
- Calls `FeedHandler.on_project_opened(n, p)` on project open (via LeftPanel callback)
- Calls `FeedHandler.on_project_closed()` on project close (via LeftPanel callback)
- Calls `CrabWatchHandler.start_watching(p, n)` / `stop_watching()` on project open/close

### File: `ui/views/main_content.py` — Remove bottom widget mechanism

**Remove entirely:**
- `_project_bottom_widget` instance variable
- `set_project_bottom_widget()` method
- `clear_project_bottom_widget()` method
- The `_on_project_tab_close()` callback that clears the bottom widget

These were the wrong approach. MainContent should know nothing about project feeds.

---

## Data Flow (Corrected)

### Flow 1: User clicks a project card

```
LeftPanel._file_tree._on_row_activated()  (or equivalent)
  → left_panel.on_project_clicked(name, path)   [already exists]
    → ProjectListHandler.on_project_opened(name, path)  [already exists]
      → ProjectHandler.open_project(name, path)   [MODIFIED — remove create_chat_tab]
        → _lp.refresh_agents_with_project(name)   [already exists]
        → _agent_to_project routing table         [already exists]
        → _on_project_opened callbacks fire:
            → LeftPanel.open_project_view(feed_tab)   [NEW]
              → Projects tab switches from "picker" to "project" page
              → FeedTab is now visible with File Tree / Feed sub-tabs
              → Feed sub-tab is default (visible_child_name = "feed")
            → FeedHandler.set_feed_tab(feed_tab)    [NEW — so FeedHandler knows where to add cards]
            → FeedHandler.on_project_opened(name, path)   [existing]
              → loads feed.json → renders cards → shows Feed sub-tab
            → CrabWatchHandler.start_watching(path, name)  [existing]
```

### Flow 2: User clicks the ← back button or closes project

```
LeftPanel._on_back_clicked()  (or close signal)
  → ProjectHandler.close_project(name)   [existing — remove MainContent tab close]
    → _agent_to_project.remove_project(name)   [existing]
    → _lp.refresh_agents_with_project(None)    [existing]
    → _on_project_opened callbacks fire with (None, None):
        → LeftPanel.close_project_view()   [NEW]
          → Projects tab switches from "project" to "picker" page
          → FeedTab hidden, FileTree visible
        → FeedHandler.on_project_closed()  [existing]
        → CrabWatchHandler.stop_watching()  [existing]
```

### Flow 3: Agent outputs a crabcard in chat

```
Agent message arrives
  → ChatRenderHandler.render_sync()
    → extract_crabcards(text) → cards list
    → FeedHandler.add_card(card) for each card
      → FeedHandler._feed_tab.prepend_card(widget, card_id)
        → FeedTab prepends card to feed container
        → Card appears in Feed sub-tab (if visible)
        → If File Tree sub-tab is visible, user sees no card until switching
```

**Note:** Since the project view is now in the left panel's Projects tab, not in a main content tab, "switching to feed tab" means the user is already looking at it when they're in the project view. The feed is always visible when in the project state.

### Flow 4: CrabWatch detects file change

```
Gio.FileMonitor callback
  → CrabWatchHandler._on_file_changed()
    → constructs FeedCardData
    → calls on_filesystem_event(card_data)
      → FeedHandler.on_filesystem_event(card_data)
        → same add_card() path as crabcards
```

---

## Architecture Adherence

### Package rules (from ARCHITECTURE.md Section 2)

| Package | May Import From | May NOT Import From |
|---------|----------------|---------------------|
| `models/` | Nothing | `ui/`, `gateway/`, `agent/` |
| `utils/` | `models/` | `ui/`, `gateway/`, `agent/` |
| `ui/views/` | `models/`, `utils/`, GTK4 | `ui/handlers/`, `gateway/`, `agent/` |
| `ui/handlers/` | `models/`, `utils/`, GTK4 (via GLib only) | Other handlers (use callbacks), `gateway/` |

**Compliance check:**
- `FeedHandler` (handler) does NOT import any other handler ✓
- `FeedTab` (view) does NOT import any handler ✓
- `LeftPanel` (view) does NOT import any handler ✓
- All handler→handler communication via callbacks set in `window.py` ✓
- All GTK from background threads via `GLib.idle_add()` ✓

### Handler isolation (from ARCHITECTURE.md Section 8.6)

Each handler owns one subsystem. Communication is via callbacks only.

| Handler | Owns | Communicates via |
|---------|------|-----------------|
| `FeedHandler` | Feed card list, card lifecycle | `set_feed_tab()` from window, `on_project_opened()` from window |
| `CrabWatchHandler` | File monitors per project | `on_filesystem_event` callback to FeedHandler |
| `ProjectHandler` | Project open/close, routing table | `_on_project_opened` callbacks to window |
| `LeftPanel` | Projects tab view state | `open_project_view()` / `close_project_view()` called by window |

---

## What Stays The Same

The following existing modules are correct and need NO changes (except where noted):

| Module | Status | Notes |
|--------|--------|-------|
| `models/feed_card.py` | ✅ Keep | No changes needed |
| `ui/views/feed_tab.py` | ✅ Keep | Minor: `show_feed_tab()` called by FeedHandler's `on_tab_switch` callback — keep |
| `ui/handlers/feed_handler.py` | ✅ Keep | Minor: constructor signature change — remove `feed_tab`, add `set_feed_tab()` |
| `ui/handlers/crabwatch_handler.py` | ✅ Keep | No changes needed |
| `utils/feed_store.py` | ✅ Keep | No changes needed |
| `ui/styles.py` | ✅ Keep | All feed CSS classes already added |
| `ui/handlers/chat_render_handler.py` | ✅ Keep | Crabcard extraction wiring is correct |
| `utils/crabcard_parser.py` | ✅ Keep | No changes needed |

---

## Implementation Order

### Step 1: Clean MainContent
- Remove `_project_bottom_widget`, `set_project_bottom_widget()`, `clear_project_bottom_widget()` from `ui/views/main_content.py`
- Remove any calls to these methods from `ui/window.py`

### Step 2: Restructure LeftPanel
- Change Projects tab from single `FileTree` child to `Gtk.Stack` with "picker" / "project" pages
- Add `open_project_view(feed_tab)` method
- Add `close_project_view()` method
- Add `get_feed_tab()` method (lazy creation)

### Step 3: Update FeedHandler
- Remove `feed_tab` from constructor
- Add `set_feed_tab(feed_tab)` method
- All other logic unchanged

### Step 4: Update ProjectHandler
- Remove `create_chat_tab(f"project:{name}")` from `open_project()`
- Everything else unchanged

### Step 5: Rewrite window.py wiring
- Remove `FeedTab` creation from window
- Change FeedHandler construction (no `feed_tab` argument)
- Wire `LeftPanel.open_project_view()` / `close_project_view()` as project lifecycle callbacks
- Wire `FeedHandler.set_feed_tab()` after LeftPanel creates FeedTab
- Remove all `set_project_bottom_widget` / `clear_project_bottom_widget` calls

### Step 6: Test
- Open app → Projects tab shows project cards ✓
- Click project → Projects tab switches to FeedTab, Feed sub-tab visible, File Tree sub-tab available ✓
- Close project → Projects tab returns to project cards ✓
- Agent crabcard → card appears in feed ✓
- CrabWatch file change → system card appears ✓

---

## Summary of Changes

| File | Action | Reason |
|------|--------|--------|
| `ui/views/main_content.py` | **Remove** bottom widget methods | Wrong mechanism — MainContent shouldn't know about project feeds |
| `ui/views/left_panel.py` | **Rewrite** Projects tab | Must transform between FileTree and FeedTab |
| `ui/views/feed_tab.py` | **Keep as-is** | Correct structure, just created in different place |
| `ui/handlers/feed_handler.py` | **Modify** constructor | Remove `feed_tab` dep, add `set_feed_tab()` |
| `ui/handlers/project_handler.py` | **Remove** `create_chat_tab()` call | Project view is in LeftPanel, not MainContent |
| `ui/window.py` | **Rewrite** FeedTab wiring | FeedTab created by LeftPanel, window wires callbacks only |
| `models/feed_card.py` | **Keep as-is** | Correct |
| `utils/feed_store.py` | **Keep as-is** | Correct |
| `utils/crabcard_parser.py` | **Keep as-is** | Correct |
| `ui/handlers/crabwatch_handler.py` | **Keep as-is** | Correct |
| `ui/styles.py` | **Keep as-is** | All CSS already present |
| `ui/handlers/chat_render_handler.py` | **Keep as-is** | Crabcard wiring correct |

---

*This document is the single source of truth for the corrected Project Feed implementation.*
