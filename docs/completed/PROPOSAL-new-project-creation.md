# New Project Creation — Formal Proposal

> **Status: PARTIALLY IMPLEMENTED** — Verified in code as of 2026-05-09
> - `ProjectHandler.create_project()` exists
> - Full proposal scope may have remaining items

**Date:** 2026-04-25
**Author:** Qaster
**Affects:** `ui/views/file_tree.py`, `ui/handlers/project_handler.py`, `utils/project_awareness.py`

---

## 1. Objective

Add the ability to create new projects from within CrabCakes' Projects tab. Currently, projects can only be opened if they already exist as directories in `$CRABCAKES_PROJECTS_DIR` (default `~/projects`). There is no UI to create one.

This feature also serves as the primary test path for the Project Awareness System — a new project triggers `init_project_config()`, creating `.crabcakes/` and all awareness artifacts.

---

## 2. User Story

1. User clicks the Projects tab in the left panel
2. User sees the project card grid (existing) + a **"+" card** at the top
3. User clicks the "+" card
4. A popover appears with:
   - Project name field (required)
   - An optional path override (defaults to `$CRABCAKES_PROJECTS_DIR/<name>`)
5. User clicks "Create"
6. CrabCakes creates the directory, calls `init_project_config()`, opens the project tab
7. The new project appears in the card grid immediately

---

## 3. Design Decisions

### 3.1 Where does the creation logic live?

**Decision:** `ProjectHandler` — it already owns `open_project()` and calls `init_project_config()`. A new `create_project(name, path)` method fits naturally.

**Rationale:** Section 8.6 (Handler Pattern) requires all UI logic in handlers. `ProjectHandler` already manages project lifecycle (open, close, toggle agent). Creation is the missing lifecycle step.

### 3.2 Where does the "+" button live?

**Decision:** `FileTree._show_project_picker()` — add a "New Project" card at the top of the card grid, before the project list.

**Rationale:** The project picker is already rendered as cards. A "+" card follows the established visual pattern. No new widgets needed — it's just another card with different styling.

### 3.3 What UI for the creation form?

**Decision:** `Gtk.Popover` anchored to the "+" card, following the existing popover pattern in `window.py` (forward popover) and `session_menu.py`.

**Rationale:** Section 8.5 says follow existing patterns. The codebase has 3 popover examples already. A dialog would be heavier than needed for two fields.

### 3.4 What gets created?

```
$CRABCAKES_PROJECT_DIR/<name>/
  .crabcakes/
    project.md      ← generated skeleton
    team.json       ← empty team with PM info
    context.md      ← empty
    awareness.json  ← initial snapshot
```

This is exactly what `init_project_config()` already generates. No new code needed for the disk side.

---

## 4. Implementation Plan

### Checkpoint 1: `ProjectHandler.create_project()`

**File:** `ui/handlers/project_handler.py`
**Architecture home:** ProjectHandler owns project lifecycle.

```python
def create_project(self, name: str, path: str | None = None) -> str | None:
    """
    Create a new project directory and open it.
    Returns the project path on success, None on failure.
    """
    # Resolve path
    if not path:
        # Default: $CRABCAKES_PROJECTS_DIR/<name>
        for pname, ppath in self._projects.load_projects():
            pass  # just need the projects dir
        path = os.path.join(self._projects._PROJECTS_DIR_REF[0], name)

    # Validate name
    if not name or not name.strip():
        return None
    name = name.strip()

    # Check if directory already exists
    if os.path.exists(path):
        return None  # Already exists — don't overwrite

    # Create directory
    os.makedirs(path, exist_ok=True)

    # Initialize .crabcakes/
    if self._awareness:
        self._awareness.init_project_config(path, name)

    # Open the project (creates tab, refreshes agents, etc.)
    self.open_project(name, path)

    return path
```

**Wire-up:** Called from `FileTree` via a new callback `set_on_create_project(cb)`.

### Checkpoint 2: Add "+" card to `FileTree._show_project_picker()`

**File:** `ui/views/file_tree.py`
**Architecture home:** FileTree owns the project picker view.

Add a "New Project" card before the project list. The card uses the same `_make_project_card` pattern but with a distinctive "+" icon and placeholder text.

```python
# In _show_project_picker(), after card_box creation:
new_card = self._make_new_project_card()
card_box.append(new_card)
# Then append project cards as before...
```

### Checkpoint 3: Creation popover form

**File:** `ui/views/file_tree.py` (private method)
**Architecture home:** FileTree owns its own popovers (Section 8.5 — view owns widget layout).

The popover contains:
- `Gtk.Entry` for project name
- `Gtk.Button` "Create"
- On click: validate, call `self._on_create_project(name)`, close popover

Pattern copied from `window.py:1010` (`_show_forward_popover`).

### Checkpoint 4: Wire FileTree → ProjectHandler via window.py

**File:** `ui/window.py`

```python
# In _build(), after file_tree setup:
self._file_tree.set_on_create_project(self._project_handler.create_project)
```

This follows the existing callback wiring pattern (Section 5).

### Checkpoint 5: Refresh project list after creation

**File:** `ui/handlers/project_handler.py`

After `create_project()` succeeds, the card grid needs refreshing. FileTree's `_show_project_picker()` re-reads `ProjectListHandler.get_projects()` each time, so calling `navigate_back()` then `load_project()` would work — but that's jarring.

**Better approach:** Add a callback `set_on_project_created(cb)` that window uses to refresh the left panel's project list. Or simply: `create_project` calls `open_project`, which already works. The card grid will be correct next time the user navigates back.

**Decision:** Keep it simple. The user lands in the new project immediately. Next time they hit "back", the card grid refreshes automatically because `_show_project_picker()` re-reads from `load_projects()`.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `ui/handlers/project_handler.py` | Add `create_project(name, path)` method |
| `ui/views/file_tree.py` | Add "+" card, creation popover, `set_on_create_project()` callback |
| `ui/window.py` | Wire `file_tree.set_on_create_project()` → `project_handler.create_project` |
| `ui/styles.py` | Add `.new-project-card` CSS class (subtle dashed border) |

---

## 6. ARCHITECTURE.md Updates Required

Per Section 0:

| Section | Update |
|---------|--------|
| 3.19 `ProjectHandler` Public API | Add `create_project(name, path) -> str | None` |
| 3.24 `FileTree` Public API | Add `set_on_create_project(cb)` |
| 11 File Inventory | Update line counts for changed files |

---

## 7. Architecture Compliance Checklist

- [x] Handler pattern (Section 8.6) — creation logic in `ProjectHandler`, not in view
- [x] View owns widget layout (Section 8.5) — popover in `FileTree`
- [x] Callback wiring (Section 5) — `window.py` connects FileTree to ProjectHandler
- [x] No cross-handler imports — window wires via callbacks
- [x] `utils/project_awareness.py` not modified — `init_project_config()` already does everything
- [x] No new modules — all changes in existing files
- [x] GTK calls via `_dispatch()` / `GLib.idle_add()` where needed

---

## 8. Testing

| Test | What It Verifies |
|------|-----------------|
| `test_project_handler.py::TestCreateProject` | `create_project()` creates dir, calls init, opens project |
| `test_project_handler.py::TestCreateProjectDuplicate` | Returns None if directory exists |
| `test_project_handler.py::TestCreateProjectEmptyName` | Returns None for empty name |
| `test_project_awareness.py::TestInitOnCreate` | `.crabcakes/` artifacts created in new project |
| Manual test | Click "+" → fill name → Create → project tab opens with awareness |

---

## 9. Future Enhancements (Out of Scope)

- Project templates (pre-populate files from a template)
- Project deletion (with confirmation)
- Project rename
- Custom path picker (Gtk.FileDialog for non-default location)

---

*This proposal covers the minimum viable implementation. Upon approval, implementation follows the checkpoint discipline.*
