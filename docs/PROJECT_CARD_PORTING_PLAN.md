# Project Card Porting Plan — Deadcode → CrabCakes

**Date:** 2026-04-11
**Author:** Qaster
**Status:** Plan only — no code changes made

---

## What We're Porting

The project card system from `/home/q/projects/deadcode/src/app.py` and `src/ui/widgets.py` — specifically the `render_folder_icon()` function and the `_make_project_card()` card layout. This gives CrabCakes polished folder-icon cards in the Projects tab instead of plain TreeView text rows.

---

## Current State

### Deadcode (source)
- `src/ui/widgets.py` — `render_folder_icon(color_hex, letter, size=44)` → renders SVG folder icon → `Gdk.Texture`
- `src/app.py` lines 1464-1570 — `_populate_project_cards()` and `_make_project_card()` build the card rows
- `src/styles.py` — CSS for `.project-card`, `.project-folder-box`, `.project-folder-lbl`, `.project-folder-0` through `.project-folder-9`
- `src/models.py` — `next_project_color()` returns hex string from same 10-color palette

### CrabCakes (target)
- `ui/views/file_tree.py` — `FileTree` widget uses `Gtk.TreeStore`/`Gtk.TreeView` for project listing (text-only rows with 📁 emoji prefix)
- No folder icon rendering exists
- `utils/projects.py` — `load_projects()`, `scan_directory()`, membership I/O

---

## Visual Design Being Ported

Each project card is a horizontal row:
```
┌─────────────────────────────────────────────┐
│  [Folder]   Project Name                    │
│  44×44px    /path/to/project                │
│  colored    muted gray, smaller text        │
└─────────────────────────────────────────────┘
```

**Folder icon:** Colored folder shape (SVG) with tab notch at top-left, rounded body, and a white bold letter (first character of project name) centered on the body. 44×44px. Same 10-color palette as agent avatars.

**Card:** Dark semi-transparent background (`rgba(255,255,255,0.04)`), 6px border radius, subtle border. Hover shows indigo tint + border. Pointer cursor on whole card.

**Text area:** Two lines — project name (13px, near-white, weight 500) and project path (dim-label, small, muted gray).

**Interaction:** Single click opens the project (navigates to file tree view). Double-click also works.

---

## Step-by-Step Plan

### Step 1: Add `render_folder_icon()` to `utils/icons.py`

If `utils/icons.py` already exists from the agent card port, add `render_folder_icon()` alongside `render_agent_icon()`. Otherwise create the file. The function (~30 lines):
- Takes `color_hex` (string), `letter` (string), `size` (int, default 44)
- Generates SVG with: folder tab notch path, folder body rect, centered white letter
- Writes to temp file, loads as `Gdk.Texture`, deletes temp file
- Returns `Gdk.Texture`

Dependencies: `tempfile`, `os`, `gi.repository.Gdk` — all standard.

### Step 2: Add project color management

Deadcode uses `next_project_color()` which returns hex strings from the same 10-color palette as agents. Options:
- Add `next_project_color()` to `models/colors.py`
- Store assigned colors persistently (per-session is fine, like agents)

### Step 3: Create `ui/handlers/project_list_handler.py`

**Per architecture Section 8.6:** All new UI logic must go in a handler.

The handler owns:
- Project color assignment and persistence (in-memory dict: path → hex color)
- Project scanning (calls `utils/projects.py`)
- Project open logic (delegating to `on_project_opened` callback)

```python
class ProjectListHandler:
    def __init__(self, *, on_project_opened=None):
        ...

    def get_projects(self) -> list[tuple[str, str]]:
        """Return [(name, path)] from CRABCAKES_PROJECTS_DIR."""

    def get_project_color(self, path: str) -> str:
        """Get or assign a color for a project path."""

    def on_project_clicked(self, name: str, path: str):
        """Handle project card click via callback."""
```

**Handler rules (per Section 8.6):**
- Does NOT import other handlers
- Receives dependencies via constructor
- No GTK imports — purely logic and data
- `window.py` wires callbacks between this handler and views

### Step 4: Replace TreeView project picker with card-based layout

In `ui/views/file_tree.py`, modify `_show_project_picker()`:
- Instead of populating `Gtk.TreeStore` rows, build a vertical `Gtk.Box` with project cards
- Each card built via a `_make_project_card(name, path)` method
- Call `ProjectListHandler` for colors and project list
- Use `render_folder_icon()` from `utils/icons.py` for the folder avatar
- Card layout: `Gtk.Box(HORIZONTAL)` → [folder_picture] [text_box] 
- Single-click opens project (replaces current double-click requirement)
- Keep back button / tree view for after a project is opened

**Wiring in `window.py`:**
```python
self._project_list_handler = ProjectListHandler(
    on_project_opened=self._on_project_opened,
)
self._left_panel.set_project_list_handler(self._project_list_handler)
```

**Alternative approach:** Keep the existing `FileTree` for the tree view but swap the project picker (top-level view) to use cards. This means:
- `_show_project_picker()` builds card layout instead of TreeStore rows
- `_show_tree()` remains unchanged (directory browsing within a project)
- Need to track which view mode is active (picker vs tree)

### Step 5: Add CSS

Port these CSS classes from deadcode's `styles.py`:
- `.project-card` — dark background, rounded, hover effect, pointer cursor
- `.project-card-name` — project name text styling
- `.project-folder-box` — folder icon container
- `.project-folder-lbl` — folder icon text
- `.project-folder-0` through `.project-folder-9` — color variants

### Step 6: Update `ARCHITECTURE.md`

- Document `render_folder_icon()` in Section 3.9 (utils/icons)
- Add `ui/handlers/project_list_handler.py` to Section 3 and Section 11
- Document `ProjectListHandler` public API in Section 3
- Update `ui/views/file_tree.py` description to note card-based project picker
- Update Section 11 file inventory

### Step 7: Tests

**`tests/test_icons.py`** (new or modify):
- Test `render_folder_icon()` with valid inputs → returns non-None texture
- Test edge cases: empty letter, single char, size boundaries

**`tests/test_project_list_handler.py`** (new):
- Test `get_projects()` — scans directory, returns sorted list
- Test `get_project_color()` — assigns colors round-robin, persists across calls
- Test `on_project_clicked()` — callback fires with correct name/path

### Step 8: Commit & Push

```
git add -A
git commit -m "feat: add project cards with folder icon rendering"
git push
```

---

## Files Changed

| File | Action |
|------|--------|
| `utils/icons.py` | NEW or MODIFY — add `render_folder_icon()` |
| `models/colors.py` | MODIFY — add `next_project_color()` |
| `ui/handlers/project_list_handler.py` | NEW — project card logic handler (Section 8.6 compliance) |
| `ui/views/file_tree.py` | MODIFY — card-based project picker |
| `ui/window.py` | MODIFY — wire ProjectListHandler |
| `ARCHITECTURE.md` | MODIFY — document new functions and UI change |
| `tests/test_icons.py` | NEW or MODIFY — folder icon tests |
| `tests/test_project_list_handler.py` | NEW — handler logic tests |

---

## Architecture Compliance Notes

**Why `ui/handlers/project_list_handler.py`:**
Section 8.6 mandates all new UI logic goes in handlers. Color assignment, project scanning, and open logic are all handler responsibilities.

**No handler-to-handler imports:**
`ProjectListHandler` does NOT import `ChatHandler` or `AgentListHandler`. Project open events go through the `on_project_opened` callback, wired by `window.py`.

**`utils/icons.py` for rendering:**
Same rationale as agent cards — `render_folder_icon()` uses `Gdk.Texture` which is GTK-dependent, but `utils/` is allowed to use GTK.

## Key Differences from Deadcode Implementation

1. **Deadcode has no Chat/+ buttons on project cards** — just a single-click to open. Simpler than agent cards.
2. **Deadcode stores project colors in `self._project_colors` dict** (path → color). CrabCakes should do the same, or use a module-level state in `models/colors.py`.
3. **Deadcode uses `load_config()` for projects path.** CrabCakes uses `CRABCAKES_PROJECTS_DIR` env var via `utils/projects.py`. Already compatible.
4. **Deadcode's `_populate_project_cards()` is in `app.py`** (the monolith). CrabCakes puts logic in `ui/handlers/project_list_handler.py` per Section 8.6.

---

## Risks / Notes

- The card layout replaces the TreeView for the project picker view. The TreeView is still used for directory browsing within a project. Need to handle view switching cleanly.
- Consider whether `FileTree` should be split into two components: `ProjectPicker` (cards) and `DirectoryTree` (TreeView). This would be cleaner but more work.
- The current double-click-to-open behavior in CrabCakes would change to single-click with the card layout (matching deadcode). This is arguably better UX.
- Folder icon SVG is simpler than agent avatar (no hexagon geometry) — lower rendering overhead.
