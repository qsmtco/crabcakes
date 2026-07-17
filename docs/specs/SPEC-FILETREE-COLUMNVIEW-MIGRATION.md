# SPEC: FileTree Migration to Gtk.ColumnView for Inline Diff Drawers

**Date:** 2025-07-12
**Author:** Supervisor (Qaster)
**Status:** Draft — for implementation
**Depends on:** SPEC-INLINE-FILE-TREE-DIFF-DRAWER.md (reference doc for current implementation)
**Target branch:** main

> **Architecture compliance:** This spec modifies `ui/views/file_tree.py` (view) and `ui/handlers/project_handler.py` (handler). Per ARCHITECTURE.md §3.6, views contain no business logic; handlers own git operations. CSS lives only in `ui/styles.py`. Threading: background threads for git ops; `GLib.idle_add` for UI updates.

---

## 1. Overview

### Problem Statement

The current `FileTree` uses `Gtk.TreeView` + `Gtk.TreeStore`, which **cannot embed arbitrary widgets in rows** (cell renderers only). The inline diff drawer UX — expanding a diff panel directly below a file row with tabs, history list, revert button, keyboard navigation — requires widget embedding. `Gtk.ColumnView` (GTK 4's modern list widget) supports this via `Gtk.ListItemFactory` + `Gtk.ColumnViewColumn` with custom widgets per row.

### Solution

Migrate `FileTree` from `Gtk.TreeView`/`Gtk.TreeStore` to `Gtk.ColumnView`/`Gio.ListStore` with a custom `Gtk.SignalListItemFactory` that produces row widgets capable of hosting an inline `Gtk.Revealer` drawer.

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Replace `Gtk.TreeView` + `Gtk.TreeStore` with `Gtk.ColumnView` + `Gio.ListStore` | Breadcrumb navigation (separate) |
| Row widget: `Gtk.Box` with expander, icon, label, **inline `Gtk.Revealer` drawer** | Git blame inline annotations |
| Drawer content: Diff tab + History tab + Revert button (reusing current UI) | Three-way merge UI |
| Lazy-load diff/history on first expand | Multi-repo support |
| Keyboard navigation (Esc, Ctrl+C, Enter) | — |
| Copy diff to clipboard | — |
| Project switch clears all state | — |
| All existing tests pass + new ColumnView tests | — |

---

## 2. Architecture

### 2.1 Data Model

```python
# Each row in the Gio.ListStore is a FileTreeRow dataclass
@dataclass
class FileTreeRow:
    display_name: str          # "▶  main.py" or "  main.py" (prefix + name)
    full_path: str             # absolute path (empty for drawer rows)
    is_dir: bool               # True for directories
    is_drawer: bool            # True for drawer detail rows
    depth: int                 # indentation level (0 = root)
    drawer_widget: Gtk.Widget | None  # the drawer revealer (for drawer rows)
    expanded: bool             # for directories
    has_children: bool         # for directories (lazy load placeholder)
```

### 2.2 Row Types

| Type | `is_dir` | `is_drawer` | `full_path` | `drawer_widget` |
|------|----------|-------------|-------------|-----------------|
| Directory | True | False | "/project/src" | None |
| File | False | False | "/project/src/main.py" | None |
| Drawer (diff/history) | False | True | "" | `Gtk.Revealer` |

### 2.3 Factory Pattern

```python
class FileTreeFactory(Gtk.SignalListItemFactory):
    def setup(self, factory, list_item):
        # Create row widget: Gtk.Box with expander/icon/label + placeholder for drawer
        pass

    def bind(self, factory, list_item):
        # Get FileTreeRow from list_item.get_item()
        # Configure row widget: set label, icon, expander state
        # If is_drawer: append drawer_widget as child of row's content box
        pass

    def unbind(self, factory, list_item):
        # Clean up: remove drawer widget if present, disconnect signals
        pass
```

### 2.4 Tree Structure (Flat List with Depth)

`Gio.ListStore` is flat. Tree hierarchy is represented by `depth` and expand/collapse logic:

- **Expand directory**: insert its children at `position + 1` with `depth + 1`
- **Collapse directory**: remove all descendants until next row with `depth <= current_depth`
- **Expand file (show drawer)**: insert drawer row at `position + 1` with `is_drawer=True`

This mirrors the current `_on_row_expanded` / `_on_row_collapsed` logic but operates on list indices.

---

## 3. Changes by File

### 3.1 `ui/views/file_tree.py` — **Major Rewrite** (~1000 lines → ~1200 lines)

**Remove:**
- `Gtk.TreeView`, `Gtk.TreeStore`, `Gtk.TreeSelection`, `Gtk.CellRendererText`
- All `TreeIter` manipulation (`_find_file_iter`, `_store.append`, `model.iter_children`, etc.)
- `_drawer_area` box (drawers become inline rows)
- `_drawers` dict mapping `file_path → (revealer, name, is_open, box)` — replaced by drawer rows in the list store

**Add:**
- `Gio.ListStore` of `FileTreeRow` objects
- `Gtk.ColumnView` with single column using `FileTreeFactory`
- `FileTreeRow` dataclass
- `FileTreeRowWidget` — the per-row `Gtk.Box` containing expander, icon, label, and optional drawer child
- `FileTreeFactory` — `Gtk.SignalListItemFactory` subclass
- Expand/collapse logic operating on list indices
- Drawer toggle inserts/removes drawer row in list store

**Preserve (adapt):**
- All git operations via `_project_handler` callbacks (unchanged)
- `_load_drawer_diff`, `_on_drawer_diff_loaded`, `_load_history`, `_on_history_loaded`, `_load_historical_diff`, `_on_historical_diff_loaded` — same logic, just targeting drawer row's widget
- `_on_drawer_revert_clicked`, `_on_drawer_revert_confirmed`, `_load_current_diff` — same
- Keyboard handlers (Esc, Ctrl+C, Enter) — adapted to ColumnView focus/selection
- `_show_tree`, `navigate_back`, `navigate_into` — adapted to list store
- CSS classes (same names, works on new widgets)

### 3.2 `ui/handlers/project_handler.py` — **No Changes**

Existing `revert_file_to_sha`, `get_project_path`, `scan_directory` APIs unchanged.

### 3.3 `ui/window.py` — **Minor Wiring**

- `FileTree` constructor signature unchanged
- `set_project_handler` call unchanged

### 3.4 `ui/styles.py` — **Additions Only**

```css
/* ColumnView row styling */
.file-tree-row {
    padding: 2px 8px;
    min-height: 24px;
}
.file-tree-row:selected {
    background: alpha(@theme_selected_bg_color, 0.3);
}
.file-tree-row-expander {
    margin-right: 4px;
    min-width: 16px;
}
.file-tree-row-icon {
    margin-right: 6px;
}
.file-tree-row-label {
    /* existing */
}

/* Inline drawer (reuses existing .file-tree-drawer classes) */
.file-tree-drawer-row {
    /* drawer row has no label, just the revealer child */
}
```

---

## 4. Implementation Phases

| Phase | Description | Files | Verification |
|-------|-------------|-------|--------------|
| **1. Data model & row widget** | `FileTreeRow` dataclass, `FileTreeRowWidget` (Gtk.Box with expander/icon/label + drawer placeholder), basic CSS | `file_tree.py` | Unit test: row widget renders correctly for each type |
| **2. ColumnView + Factory** | Replace TreeView/TreeStore with ColumnView + Gio.ListStore + FileTreeFactory (setup/bind/unbind) | `file_tree.py` | Manual: project opens, file list renders, selection works |
| **3. Directory expand/collapse** | Implement lazy-load children insertion/removal by index/depth | `file_tree.py` | Manual: expand dir → children appear; collapse → children removed |
| **4. File double-click → drawer row** | On row-activated (file), insert drawer row below with Revealer; animate reveal | `file_tree.py` | Manual: double-click file → drawer opens inline with animation |
| **5. Drawer content (Diff tab)** | Port `_load_drawer_diff` / `_on_drawer_diff_loaded` to target drawer row's widget | `file_tree.py` | Manual: Diff tab shows syntax-highlighted diff |
| **6. Drawer content (History tab)** | Port `_load_history` / `_on_history_loaded` / history row activation | `file_tree.py` | Manual: History tab loads commits; click row → historical diff |
| **7. Revert flow** | Port `_on_drawer_revert_clicked` / `_on_drawer_revert_confirmed` / `_load_current_diff` | `file_tree.py` | Manual: Revert button works, diff reloads |
| **8. Keyboard navigation** | Esc closes drawer, Ctrl+C copies diff, Enter on history row activates | `file_tree.py` | Manual: all keys work |
| **9. Project switch / navigate_back** | Clear list store, reset state | `file_tree.py` | Manual: switch project → clean state |
| **10. CSS polish** | Add ColumnView row classes, verify drawer styling | `styles.py` | Visual: no regressions |
| **11. Tests** | `tests/test_file_tree_columnview.py` — factory, expand/collapse, drawer toggle | `tests/` | `pytest tests/test_file_tree_columnview.py -x -q` |
| **12. Full regression** | Run full suite | — | `xvfb-run -a pytest tests/ -x -q` → 0 failures |

---

## 5. Detailed Phase Specs

### Phase 1: Data Model & Row Widget

**File:** `ui/views/file_tree.py`

```python
from dataclasses import dataclass
from typing import Optional
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

@dataclass
class FileTreeRow:
    display_name: str
    full_path: str
    is_dir: bool
    is_drawer: bool
    depth: int
    drawer_widget: Optional[Gtk.Widget] = None
    expanded: bool = False
    has_children: bool = False
```

**Row Widget:** `FileTreeRowWidget(Gtk.Box)` with:
- `expander_btn` (Gtk.Button, ▶/▼ for dirs, spacer for files)
- `icon` (Gtk.Image, folder/file/drawer)
- `label` (Gtk.Label, markup for prefix + name)
- `drawer_container` (Gtk.Box, initially empty, receives drawer_widget for drawer rows)

**CSS classes:** `.file-tree-row`, `.file-tree-row-expander`, `.file-tree-row-icon`, `.file-tree-row-label`, `.file-tree-drawer-row`

**Test:** `test_file_tree_row_widget.py` — instantiate each row type, verify children, classes, markup.

---

### Phase 2: ColumnView + Factory

**File:** `ui/views/file_tree.py`

```python
class FileTreeFactory(Gtk.SignalListItemFactory):
    def __init__(self, tree: 'FileTree'):
        super().__init__()
        self._tree = tree
        self.connect('setup', self._on_setup)
        self.connect('bind', self._on_bind)
        self.connect('unbind', self._on_unbind)

    def _on_setup(self, factory, list_item):
        widget = FileTreeRowWidget()
        list_item.set_child(widget)

    def _on_bind(self, factory, list_item):
        row: FileTreeRow = list_item.get_item()
        widget: FileTreeRowWidget = list_item.get_child()
        # configure widget from row
        widget.set_depth(row.depth)
        widget.set_expanded(row.expanded)
        widget.set_label(row.display_name)
        widget.set_icon(row.is_dir, row.is_drawer)
        if row.is_drawer and row.drawer_widget:
            widget.attach_drawer(row.drawer_widget)
        # connect signals: expander clicked, row activated
        widget.connect_expander(self._tree._on_expander_clicked)
        widget.connect_activated(self._tree._on_row_activated)

    def _on_unbind(self, factory, list_item):
        widget: FileTreeRowWidget = list_item.get_child()
        widget.cleanup()  # remove drawer, disconnect signals
```

**FileTree.__init__:**
- `self._store = Gio.ListStore.new(FileTreeRow)` — **but** GObject ListStore requires GObject types. Use `Gio.ListStore` with `item_type=GObject.TYPE_PYOBJECT` or wrap in `GObject.Object` subclass. Simpler: `self._store = []` (Python list) + `Gtk.ColumnView` with `Gtk.NoSelection` + custom `Gtk.SingleSelection` wrapper? **Better:** Use `Gio.ListStore.new(GObject.TYPE_PYOBJECT)` — PyGObject supports Python objects in `G_TYPE_PYOBJECT` columns.

```python
self._store = Gio.ListStore.new(GObject.TYPE_PYOBJECT)
self._selection = Gtk.SingleSelection.new(self._store)
self._column_view = Gtk.ColumnView.new(self._selection)
factory = FileTreeFactory(self)
column = Gtk.ColumnViewColumn.new("Name", factory)
self._column_view.append_column(column)
```

**Test:** Open project → file list renders, selection works, no crashes.

---

### Phase 3: Directory Expand/Collapse

**Logic:** On expander click for directory row at index `i`:
- If collapsed → expand: scan `scan_directory(full_path)`, create `FileTreeRow` for each child with `depth = row.depth + 1`, insert at `i+1` ... `i+n` in `_store`.
- If expanded → collapse: remove all subsequent rows while `row.depth > current_depth`.

**Async:** `scan_directory` in background thread, `GLib.idle_add` to insert.

**Test:** Expand root → children appear. Collapse → children removed. Nested expand/collapse works.

---

### Phase 4: File Double-Click → Drawer Row

**Logic:** On row-activated for file row at index `i`:
- Create `drawer_revealer = Gtk.Revealer(transition_type=SLIDE_DOWN, transition_duration=150)`
- Build drawer widget (tabs, stack, diff_box, history_list, action_bar) — **reuse exact current UI code**
- Create `drawer_row = FileTreeRow(display_name="", full_path="", is_dir=False, is_drawer=True, depth=file_row.depth, drawer_widget=drawer_revealer)`
- Insert at `i+1` in `_store`
- `drawer_revealer.set_reveal_child(True)`
- Update file row's expander to ▼ (reuse prefix logic)

**On second click (close):**
- `drawer_revealer.set_reveal_child(False)`
- Connect to `notify::child-revealed` → when `False`, remove drawer row from `_store`

**Debounce:** Per-file `_last_toggle_time` dict (same as current).

---

### Phase 5-8: Drawer Content, Revert, Keyboard

**Port existing methods** — target drawer row's widget instead of `_drawers[file_path][3]`.

Key mapping:
- Current: `self._drawers[file_path] = (revealer, name, is_open, drawer_box)`
- New: `drawer_row.drawer_widget` is the revealer; `drawer_box` is built inside it

`_on_drawer_diff_loaded(result, subtitle, file_path)`:
- Find drawer row in store: `next((r for r in self._store if r.is_drawer and r.drawer_widget.get_child()._file_path == file_path), None)`
- Update its `drawer_box._diff_box` etc.

Same for history, historical diff, revert.

**Keyboard:** ColumnView key controller on the view. Escape → find selected row, if it's a file with open drawer → close drawer. Ctrl+C → copy diff from selected drawer row. Enter on history row → activate.

---

### Phase 9: Project Switch / Navigation

`_show_tree(name, path)`:
- `self._store.splice(0, len(self._store), [])` — clear all
- Reset `_last_toggle_time`, `_loaded_drawers`, etc.
- Populate root entries from `scan_directory(path)`

`navigate_back()` / `navigate_into(dir_name)` — same logic, rebuild store.

---

## 6. Acceptance Criteria

| # | Criterion | Test Method |
|---|-----------|-------------|
| 1 | Project opens, file tree renders with correct icons, indentation | Manual + unit test |
| 2 | Directory expand/collapse works recursively, lazy-loaded | Manual + unit test |
| 3 | Double-click file → inline drawer opens below with slide-down animation | Manual |
| 4 | Drawer shows Diff tab with syntax-highlighted diff | Manual |
| 5 | History tab loads commits (SHA, date, message) | Manual |
| 6 | Click history row → loads that commit's diff in Diff tab | Manual |
| 7 | Revert button appears on historical diff, reverts file, diff reloads | Manual |
| 8 | Esc closes drawer, focus returns to tree | Manual |
| 9 | Ctrl+C copies current diff to clipboard | Manual |
| 10 | Enter on history row activates it | Manual |
| 11 | Multiple drawers can be open simultaneously | Manual |
| 12 | Drawers scroll with tree (same ScrolledWindow) | Manual |
| 13 | Project switch clears all drawers and tree state | Manual |
| 14 | `xvfb-run -a pytest tests/ -x -q` → 0 failures | Automated |
| 15 | No CSS regressions (visual parity with current drawer styling) | Visual |

---

## 7. Edge Cases

| Case | Handling |
|------|----------|
| Binary file diff | "Binary file — not shown" label (current behavior) |
| No changes | "No changes to this file." label |
| Git error (permission, corrupt) | Error label in diff area |
| Empty history (new file) | "No commit history for this file." |
| Revert to commit where file didn't exist | "File did not exist at this commit" |
| Rapid toggle (debounce) | Per-file 300ms debounce (current logic) |
| Large repo (10k+ files) | Lazy-load directories; drawer rows created on-demand |
| Project switch mid-diff-load | `_on_drawer_diff_loaded` checks `file_path in active_drawer_paths` set |
| Directory with 0 children | Expander hidden (current logic) |

---

## 8. ARCHITECTURE.md Updates Required

| Section | Update |
|---------|--------|
| §3.8 `ui/views/file_tree.py` | Document ColumnView + ListStore + Factory architecture |
| §5 CSS | Document `.file-tree-row*`, `.file-tree-drawer-row` classes |
| §8.6 Handler Pattern | No change (handler API unchanged) |

---

## 9. Verification Checklist (Pre-Commit)

- [ ] `xvfb-run -a pytest tests/test_file_tree_columnview.py -x -q` → passes
- [ ] `xvfb-run -a pytest tests/ -x -q` → 0 failures
- [ ] `grep -rn "TreeStore\|TreeView\|TreeIter" ui/views/file_tree.py` → 0 matches
- [ ] `grep -rn "Gio.ListStore\|ColumnView\|SignalListItemFactory" ui/views/file_tree.py` → present
- [ ] Manual test all 15 acceptance criteria
- [ ] `git diff ui/styles.py` → only additions, no removals of existing classes
- [ ] Post-mortem written per `implementationLoop.md` §6 format

---

## 10. Estimated Effort

| Phase | Est. Hours |
|-------|------------|
| 1-2: Model + Factory | 4 |
| 3: Expand/collapse | 3 |
| 4: Drawer row toggle | 3 |
| 5-7: Drawer content (diff, history, revert) | 6 |
| 8: Keyboard | 2 |
| 9: Navigation | 1 |
| 10: CSS | 1 |
| 11: Tests | 3 |
| 12: Regression + polish | 2 |
| **Total** | **~25 hours** |

---

**Spec file location:** `docs/specs/SPEC-FILETREE-COLUMNVIEW-MIGRATION.md`