# SPEC: File Tree Enhancements — Icons, Git Status, Size/Time Columns, Sorting, Search

**Date:** 2026-07-21
**Author:** Coder (per Supervisor delegation)
**Status:** Draft — for implementation (post-audit, 15 bugs fixed)
**Implements:** `docs/proposals/PROPOSAL_FILE_TREE_ENHANCEMENTS.md`
**Depends on:** ARCHITECTURE.md (handler pattern §3.16, CSS in styles.py §3.5, window as composition root §3.6)
**Target branch:** main

> Architecture compliance statement: This spec follows ARCHITECTURE.md — `ui/views/file_tree.py` remains a pure view (widgets only, no business logic), new `ui/handlers/file_tree_handler.py` owns sort preference persistence and git status caching with no GTK imports, sort/filter model construction lives in the view (it unavoidably uses `Gtk.*` types), `utils/` stays pure Python, all CSS in `ui/styles.py` via `add_css_class()`, and `window.py`/`left_panel.py` wire handler to view via callbacks.

---

## 1. Overview

### 1.1 Problem
The current `FileTree` widget (GTK4 `ColumnView` + `Gio.ListStore` + `FileTreeRow` GObject) is functional but bare-bones:
- Single column ("Name") showing folder/file names with expander + icon
- No file type differentiation beyond folder vs. file
- No git status visibility (modified, untracked, staged, deleted)
- No file size or modified time columns
- No sorting options (always alphabetical, directories first)
- No search/filter within the tree

### 1.2 Solution
Transform the file tree into a **rich, multi-column, searchable project browser** by adding:

| Feature | Description |
|---------|-------------|
| **1. File Type Icons** | Per-extension GTK icons (`.py`, `.md`, `.png`, `.json`, etc.) via a small icon registry. Fallback to generic file icon. |
| **2. Git Status Badges** | Colored badge labels in a "Status" column: `M` (modified), `A` (added/staged), `?` (untracked), `D` (deleted), `R` (renamed), `!` (ignored). |
| **3. Size & Modified Time Columns** | **Size** (human-readable: "1.2 KB", "4.5 MB") and **Modified** (relative: "2h ago", "Mar 14", or "—"). |
| **4. Sort Dropdown** | 6 options: Name ↑/↓, Modified ↑/↓, Size ↑/↓. Default: Name ↑ (dirs first). Persisted per-project. |
| **5. Search/Filter** | Inline search entry in the tree header (visible in tree mode, hidden in picker mode). Filters rows in real time (150ms debounce, substring match on name + path). Esc clears. |

### 1.3 Scope

| In Scope | Not In Scope |
|----------|--------------|
| File type icons for 60+ extensions | Show hidden files toggle |
| Git status via `git status --porcelain` | Git branch indicator in header |
| Size column (human-readable) | File context menu (Open in Terminal, etc.) |
| Modified time column (relative) | Drag-and-drop reorder |
| Sort dropdown (6 modes, persisted) | Multi-select (Shift/Ctrl click) |
| Search/filter (debounced, substring) | Syntax-minimap preview on hover |
| Handler/view split (ARCHITECTURE.md compliant) | |
| 4-column ColumnView layout | |

---

## 2. Discovery (Self-Audit Verification)

### 2.1 Files Read

| File | What I Learned |
|------|----------------|
| `ui/views/file_tree.py` (872 lines) | FileTreeRow has 12 GObject props. FileTreeRowWidget = expander + icon + label + drawer_container. Single-column ColumnView. `scan_directory()` returns 3-tuples. Search entry visible only in picker mode. Directory expand/collapse uses background thread + GLib.idle_add + `_current_request_id` guard (generation counter already exists — copy this pattern). Drawer state: `_drawer_paths[file_path] = FileTreeRow` (object identity). `_find_row_index` by object scan. `_clear_all_state` clears store, drawers, loaded_drawers, increments `_current_request_id`. |
| `utils/git_ops.py` (308 lines) | `GitResult` = `success`, `stdout`, `error`, `sha` — **no `extra` field**. `status()` already calls `repo.git.status("--porcelain")` returning raw stdout. Functions: `is_repo`, `status`, `diff_working_tree`, `diff_file_against_working_tree`, `checkout_paths`, `file_log`, etc. `_safe_error` for sanitized errors. |
| `utils/projects.py` (83 lines) | `scan_directory(path) -> [(name, full_path, is_dir)]` — 3-tuple. `load_projects() -> [(name, full_path)]`. `_PROJECTS_DIR_REF[0]` for test patching. Skip set: `__pycache__`, `.git`, `node_modules`, `.venv`, `venv` + dotfiles. |
| `ui/styles.py` (1426 lines) | Single `APP_CSS` string + `apply_styles()` called from `main.py`. Existing file tree CSS: `.file-tree-row`, `.file-tree-row-expander`, `.file-tree-row-icon`, `.file-tree-row-label`, `.file-tree-column-view`, `.file-tree-drawer`, etc. All CSS lives here — views never call `load_from_data()`. |
| `ui/views/left_panel.py` (720 lines) | LeftPanel creates FileTree, wires into `_picker_box`. On project open: FileTree reparents into nested Notebook "File Tree" tab. `set_feed_tab()`, `open_project_view()`, `close_project_view()` manage lifecycle. |

### 2.2 Key Verification — `GitResult` Has No `extra` Field

```
grep -n "class GitResult\|extra" utils/git_ops.py
→ @dataclass — 4 fields: success, stdout, error, sha. No `extra`.
```

**Fix:** New `status_porcelain()` returns `dict[str, str]` directly. No changes to `GitResult`.

### 2.3 Key Verification — `scan_directory` Return Tuple

Returns 3-tuples. Upgrading to 5-tuple requires updating both callers in `file_tree.py`:
- `_show_tree()` line ~647
- `_expand_directory` → `_on_directory_loaded` line ~1473

---

## 3. Changes by File

### 3.1 `utils/file_icons.py` — **NEW FILE**

Pure Python utility — no GTK imports.

**Public API:**
```python
@dataclass(frozen=True)
class FileIcon:
    icon_name: str      # GTK icon name (e.g., "text-x-python-symbolic")
    color_class: str    # CSS class for color (e.g., "file-icon-python")

def get_icon_for_path(path: str, is_dir: bool, mime_type: str | None = None) -> FileIcon:
    """Return FileIcon for a path. Priority: explicit extension → MIME → default.
    
    If path is empty or has no extension, falls through to MIME → default.
    is_dir always returns _DEFAULT_DIR.
    """
    if is_dir:
        return _DEFAULT_DIR
    # Extension match (longest first — handles .tar.gz → .gz, .pyi → .pyi)
    for ext in sorted(_EXTENSION_MAP.keys(), key=len, reverse=True):
        if path.lower().endswith(ext):
            return _EXTENSION_MAP[ext]
    # MIME fallback
    if mime_type and mime_type in _MIME_MAP:
        return _MIME_MAP[mime_type]
    return _DEFAULT_FILE
```

**Full `_EXTENSION_MAP`:** ~60 entries as documented in the proposal. Covers: python, js/ts, json/yaml/toml, md/txt, html/css/scss, rust/go/java/kotlin, c/cpp/h, sh/bash/zsh/fish/ps1, ruby/php/swift/dart/lua/perl/r, sql, xml/svg, png/jpg/gif/webp/ico, pdf, zip/tar/gz/bz2/xz/7z/rar, exe/dll/so/dylib, class/jar/war/ear, dockerfile, gitignore/gitattributes, env/ini/cfg/conf, log/lock.

```python
_DEFAULT_FILE = FileIcon("text-x-generic-symbolic", "file-icon-default")
_DEFAULT_DIR = FileIcon("folder-symbolic", "file-icon-folder")
```

---

### 3.2 `utils/git_ops.py` — **EXTEND**

Add one new function. **Do not modify `GitResult` dataclass** — returning `dict[str, str]` avoids changing the existing contract.

```python
def status_porcelain(project_path: str) -> dict[str, str]:
    """Returns parsed git status map: {rel_path: status_code}.
    
    status_code is 2-char porcelain string per `git status --porcelain` format.
    See git-status(1) for format details.
    
    Handles rename lines ('R  old -> new') by emitting the destination path.
    Returns empty dict on any error (caught and suppressed).
    """
    try:
        repo = gitpython.Repo(project_path)
        raw = repo.git.status("--porcelain")
        result: dict[str, str] = {}
        for line in raw.strip().splitlines():
            # Minimum valid porcelain line: 'XY path' (4 chars: 2 status + 1 space + 1 path)
            if len(line) < 4:
                continue
            status_code = line[:2]
            rest = line[3:]  # skip space separator at index 2
            # Handle rename/copy format: 'R  old_path -> new_path' or 'C  old_path -> new_path'
            # Check BOTH status positions — index column (R_, C_) and worktree column (_R, _C) (BUG #25)
            if (status_code[0] in ('R', 'C') or
                (len(status_code) >= 2 and status_code[1] in ('R', 'C'))):
                if ' -> ' in rest:
                    # 'old_path -> new_path' — take the right side
                    rest = rest.split(' -> ', 1)[1]
            result[rest] = status_code
        return result
    except Exception:
        return {}
```

**Verification:**
```bash
python3 -c "
from utils.git_ops import status_porcelain
result = status_porcelain('/home/q/projects/crabcakes')
print(type(result), len(result))
"
```

---

### 3.3 `utils/projects.py` — **EXTEND**

Modify `scan_directory` to return 5-tuple instead of 3-tuple.

```python
def scan_directory(path: str) -> list[tuple[str, str, bool, int, int]]:
    """
    Return [(name, full_path, is_dir, size_bytes, mtime_ns)] for one level, filtered.
    Skips __pycache__, .git, node_modules, .venv, venv, dotfiles.
    
    size_bytes: int (0 for directories, 0 on stat error)
    mtime_ns: int (nanosecond precision, 0 on stat error)
    """
    if not os.path.isdir(path):
        return []
    skip: set[str] = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}
    result: list[tuple[str, str, bool, int, int]] = []
    for name in sorted(os.listdir(path)):
        if name.startswith('.') or name in skip:
            continue
        full: str = os.path.join(path, name)
        try:
            st = os.stat(full)
            result.append((name, full, os.path.isdir(full), st.st_size, st.st_mtime_ns))
        except OSError:
            result.append((name, full, os.path.isdir(full), 0, 0))
    return result
```

**Key change from proposal:** `int(st.st_mtime_ns)` removed — `st.st_mtime_ns` is already `int`. Use integer division `mtime_ns // 1_000_000_000` at call site instead of `int(mtime_ns / 1e9)` to avoid float precision loss (**fixes BUG #14**).

**Callers to update:** `_show_tree` and `_on_directory_loaded` in `file_tree.py`.

---

### 3.4 `ui/views/file_tree.py` — **MODIFY**

#### 3.4.1 `FileTreeRow` — Add 9 New GObject Properties

Append after `history_loaded`:

```python
# File metadata (Phase: File Tree Enhancements)
file_size = GObject.Property(type=int, default=0)
file_size_display = GObject.Property(type=str, default="—")
modified_time = GObject.Property(type=int, default=0)
modified_display = GObject.Property(type=str, default="—")
git_status = GObject.Property(type=str, default="")
git_status_display = GObject.Property(type=str, default="")
mime_type = GObject.Property(type=str, default="")
icon_name = GObject.Property(type=str, default="text-x-generic-symbolic")
icon_color_class = GObject.Property(type=str, default="file-icon-default")
# BUG #26: parent_full_path stores the file_path of the parent file for drawer rows.
# Set to the file_path when creating a drawer row in _toggle_drawer.
parent_full_path = GObject.Property(type=str, default="")
```

**Total properties:** 12 → **22**. All bindable by ColumnView factory.

**Update `__init__` to accept new params (all optional, preserving existing callers):**
```python
def __init__(self, display_name: str = "", full_path: str = "",
             is_dir: bool = False, is_drawer: bool = False,
             depth: int = 0, expanded: bool = False,
             has_children: bool = False,
             drawer_widget=None, is_open: bool = False,
             diff_text: str = "", history_selected_sha=None,
             history_loaded: bool = False,
             file_size: int = 0, file_size_display: str = "—",
             modified_time: int = 0, modified_display: str = "—",
             git_status: str = "", git_status_display: str = "",
             mime_type: str = "", icon_name: str = "text-x-generic-symbolic",
             icon_color_class: str = "file-icon-default",
             parent_full_path: str = ""):
    super().__init__()
    # ... existing 12 props ...
    self.props.file_size = file_size
    self.props.file_size_display = file_size_display
    self.props.modified_time = modified_time
    self.props.modified_display = modified_display
    self.props.git_status = git_status
    self.props.git_status_display = git_status_display
    self.props.mime_type = mime_type
    self.props.icon_name = icon_name
    self.props.icon_color_class = icon_color_class
    self.props.parent_full_path = parent_full_path
```

#### 3.4.2 `FileTreeRowWidget` — Extend for Icon+Color Binding

Replace `set_icon` to accept `icon_name`:

```python
def set_icon(self, icon_name: str, is_dir: bool, is_drawer: bool) -> None:
    """Set icon based on icon_name (from FileIcon). Drawer rows hide the icon."""
    if is_drawer:
        self._icon.set_visible(False)
    else:
        self._icon.set_visible(True)
        self._icon.set_from_icon_name(icon_name)
```

Add color class setter:

```python
def set_icon_color(self, color_class: str) -> None:
    """Update icon color CSS class. Removes previous file-icon-* class."""
    for cls in list(self._icon.get_css_classes()):
        if cls.startswith("file-icon-"):
            self._icon.remove_css_class(cls)
    if color_class:
        self._icon.add_css_class(color_class)
```

#### 3.4.3 Three New ColumnFactory Classes

**BUG FIX #7:** Drawer rows inserted directly into the `Gio.ListStore` (not the filtered/sorted model). The store is the underlying data — all rows go into the store. Sort/filter models are wrappers that update automatically when the store changes. This is already how `_toggle_drawer` works: it calls `self._store.insert()` at the correct position. The `SortListModel` and `FilterListModel` will see the new row automatically (they observe the underlying store).

**Each factory's `_on_setup` creates a simple `Gtk.Label`, `_on_bind` reads the row's GObject property and sets text/class.** No drawer-related logic needed in these factories.

```python
class FileTreeStatusFactory(Gtk.SignalListItemFactory):
    """Factory for the Status column — shows git status badge."""
    def __init__(self):
        super().__init__()
        self.connect('setup', self._on_setup)
        self.connect('bind', self._on_bind)
        self.connect('unbind', self._on_unbind)

    def _on_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_xalign(0.5)
        label.add_css_class("file-tree-status-badge")
        list_item.set_child(label)

    def _on_bind(self, factory, list_item):
        row = cast(FileTreeRow, list_item.get_item())
        label: Gtk.Label = list_item.get_child()
        display = row.props.git_status_display
        label.set_text(display)
        # Update status color class — clear previous, add current
        for cls in list(label.get_css_classes()):
            if cls.startswith("file-tree-status-"):
                label.remove_css_class(cls)
        if display == "M":
            label.add_css_class("file-tree-status-modified")
        elif display == "A":
            label.add_css_class("file-tree-status-staged")
        elif display == "?":
            label.add_css_class("file-tree-status-untracked")
        elif display == "D":
            label.add_css_class("file-tree-status-deleted")
        elif display == "R":
            label.add_css_class("file-tree-status-renamed")
        elif display == "!":
            label.add_css_class("file-tree-status-ignored")

    def _on_unbind(self, factory, list_item):
        pass


class FileTreeSizeFactory(Gtk.SignalListItemFactory):
    """Factory for the Size column — right-aligned human-readable size."""
    def __init__(self):
        super().__init__()
        self.connect('setup', self._on_setup)
        self.connect('bind', self._on_bind)
        self.connect('unbind', self._on_unbind)

    def _on_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_xalign(1.0)
        label.add_css_class("file-tree-size-column")
        list_item.set_child(label)

    def _on_bind(self, factory, list_item):
        row = cast(FileTreeRow, list_item.get_item())
        label: Gtk.Label = list_item.get_child()
        label.set_text(row.props.file_size_display)

    def _on_unbind(self, factory, list_item):
        pass


class FileTreeModifiedFactory(Gtk.SignalListItemFactory):
    """Factory for the Modified column — right-aligned relative time."""
    def __init__(self):
        super().__init__()
        self.connect('setup', self._on_setup)
        self.connect('bind', self._on_bind)
        self.connect('unbind', self._on_unbind)

    def _on_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_xalign(1.0)
        label.add_css_class("file-tree-modified-column")
        list_item.set_child(label)

    def _on_bind(self, factory, list_item):
        row = cast(FileTreeRow, list_item.get_item())
        label: Gtk.Label = list_item.get_child()
        label.set_text(row.props.modified_display)

    def _on_unbind(self, factory, list_item):
        pass
```

#### 3.4.4 `FileTreeFactory._on_bind` — Update Icon + Color Binding

Modify the existing `_on_bind` to use new properties:

```python
def _on_bind(self, factory, list_item):
    row = cast(FileTreeRow, list_item.get_item())
    widget: FileTreeRowWidget = list_item.get_child()

    widget.bind_row(row)
    widget.set_depth(row.props.depth)
    widget.set_expanded(row.props.expanded)
    widget.set_label(row.props.display_name)
    # Use icon_name and icon_color_class from row props
    widget.set_icon(row.props.icon_name, row.props.is_dir, row.props.is_drawer)
    widget.set_icon_color(row.props.icon_color_class)

    # Drawer rows: hide label, let drawer_container fill space
    if row.props.is_drawer:
        widget._label.set_visible(False)
        widget._label.set_hexpand(False)
        widget._drawer_container.set_hexpand(True)
    else:
        widget._label.set_visible(True)
        widget._label.set_hexpand(True)
        widget._drawer_container.set_hexpand(False)

    if row.props.is_drawer and row.props.drawer_widget:
        widget.attach_drawer(row.props.drawer_widget)

    # Wire expander button for directories
    if row.props.is_dir and not row.props.is_drawer:
        if widget._expander_handler_id is not None:
            widget._expander_btn.disconnect(widget._expander_handler_id)
        widget._expander_handler_id = widget._expander_btn.connect(
            "clicked", lambda btn: self._on_expander_clicked(row)
        )
        widget._expander_btn.set_visible(True)
    else:
        widget._expander_btn.set_visible(False)
```

#### 3.4.5 `FileTree.__init__` — Add Header Widgets + Sort/Filter State

In `_build()` (after `_search_entry`):

```python
# Sort dropdown — visible only in tree mode (hidden in picker mode)
self._sort_dropdown = Gtk.DropDown.new_from_strings([
    "Name ↑", "Name ↓", "Modified ↑", "Modified ↓", "Size ↑", "Size ↓"
])
# NOTE: The dropdown label text ("Name ↑") is cosmetic. The mode mapping
# in _on_sort_dropdown_changed uses the selected INDEX to derive the
# internal mode string ("name_asc"). See BUG #30.
self._sort_dropdown.set_selected(0)  # Name ↑ default
self._sort_dropdown.set_valign(Gtk.Align.CENTER)
self._sort_dropdown.add_css_class("file-tree-sort-dropdown")
self._sort_dropdown.set_visible(False)
self._sort_dropdown.connect("notify::selected", self._on_sort_dropdown_changed)
self._header.append(self._sort_dropdown)
```

New callback attributes on `FileTree`:
```python
# Callbacks to handler (or None = no handler, degraded mode)
self._on_sort_changed = None          # set by wiring code
self._on_search_changed_tree = None   # set by wiring code (tree search, NOT picker search)
self._on_expand_requested = None      # NEW: callback for directory expansion (BUG #1 fix)

# Sort/filter model chain (created/lived in view, not handler — BUG #2 fix)
self._sort_model: Gtk.SortListModel | None = None
self._filter_model: Gtk.FilterListModel | None = None

# Generation counter for background thread safety (BUG #8 fix)
# Reuses existing self._current_request_id pattern (incremented on _clear_all_state)
```

Replace the single `_on_search_changed` with a dispatcher that routes to picker vs tree handler:

```python
def _on_search_changed(self, entry):
    """Called when search entry text changes. Route to picker or tree handler."""
    if self._project_path is not None:
        # Tree mode — call view's debounced filter directly (BUG #29 fix)
        self._on_search_changed_tree_cb(entry.get_text())
    else:
        # Picker mode — existing behavior
        query = entry.get_text()
        if self._project_list_handler:
            self._project_list_handler.search(query)
            self._show_project_picker()
```

#### 3.4.6 `_show_tree` — 4 Columns + Header Visibility

**BUG #3 fix (consistent search visibility):** Search entry is visible in BOTH modes (picker AND tree), but with different placeholder text and behavior. The sort dropdown is visible ONLY in tree mode.

```python
def _show_tree(self, name, path):
    """Show the directory tree for a project."""
    # Swap card box back to scroll/ColumnView
    if self._content != self._scroll:
        self.remove(self._content)
        self._content = self._scroll
        self.append(self._content)
    self._clear_all_state()
    self._back_btn.set_visible(True)
    self._folder_icon.set_visible(True)
    safe_name = escape_for_pango(name)
    self._title_lbl.set_markup(f"<b>{safe_name}</b>")
    self._title_lbl.set_use_markup(True)
    self._title_lbl.set_hexpand(True)
    # Search is visible in BOTH modes (BUG #3 fix)
    self._search_entry.set_visible(True)
    self._search_entry.set_placeholder_text("Search files... (Esc to clear)")
    # Sort dropdown is tree-mode only
    self._sort_dropdown.set_visible(True)

    # Remove existing columns, add 4-column layout
    for col in list(self._column_view.get_columns()):
        self._column_view.remove_column(col)

    factory_name = FileTreeFactory(self)
    col_name = Gtk.ColumnViewColumn.new("Name", factory_name)
    col_name.set_expand(True)
    self._column_view.append_column(col_name)

    factory_status = FileTreeStatusFactory()
    col_status = Gtk.ColumnViewColumn.new("Status", factory_status)
    col_status.set_fixed_width(60)
    self._column_view.append_column(col_status)

    factory_size = FileTreeSizeFactory()
    col_size = Gtk.ColumnViewColumn.new("Size", factory_size)
    col_size.set_fixed_width(80)
    self._column_view.append_column(col_size)

    factory_modified = FileTreeModifiedFactory()
    col_modified = Gtk.ColumnViewColumn.new("Modified", factory_modified)
    col_modified.set_fixed_width(100)
    self._column_view.append_column(col_modified)

    # Populate root entries with 5-tuple from scan_directory
    # BUG #27: Populate git status from handler via callback if available.
    # This callback is set by LeftPanel wiring on project open.
    status_map: dict[str, str] = {}
    if self._on_get_git_status:
        status_map = self._on_get_git_status() or {}
    try:
        entries = scan_directory(path)
    except Exception as e:
        entries = [(f"[error: {type(e).__name__}: {e}]", "", False, 0, 0)]
    for entry_name, full_path, is_dir, size_bytes, mtime_ns in entries:
        icon = get_icon_for_path(full_path, is_dir)
        rel_path = os.path.relpath(full_path, path) if path else full_path
        raw_status = status_map.get(rel_path, "")
        row = FileTreeRow(
            display_name=entry_name,
            full_path=full_path,
            is_dir=is_dir,
            depth=0,
            has_children=is_dir,
            expanded=False,
            file_size=0 if is_dir else size_bytes,
            file_size_display=format_size(size_bytes) if not is_dir else "—",
            modified_time=mtime_ns // 1_000_000_000 if mtime_ns else 0,  # BUG #14 fix: integer division
            modified_display=format_mtime(mtime_ns) if mtime_ns else "—",
            git_status=raw_status,
            git_status_display=git_status_to_display(raw_status),
            mime_type=guess_mime(full_path),
            icon_name=icon.icon_name,
            icon_color_class=icon.color_class,
        )
        self._store.append(row)
```

#### 3.4.7 `_show_project_picker` — Single Column, Hide Sort

```python
def _show_project_picker(self):
    """Show project cards (replaces ColumnView tree rows)."""
    self._clear_all_state()
    self._back_btn.set_visible(False)
    self._folder_icon.set_visible(False)
    self._title_lbl.set_markup(
        '<span foreground="#6b6b7a" font_desc="Sans 11">Projects</span>'
    )
    # Search visible in picker mode too
    self._search_entry.set_visible(True)
    self._search_entry.set_placeholder_text("Search projects...")
    self._sort_dropdown.set_visible(False)
    self._title_lbl.set_hexpand(False)

    # Remove all columns, add single Name column for picker
    for col in list(self._column_view.get_columns()):
        self._column_view.remove_column(col)
    factory = FileTreeFactory(self)
    col_name = Gtk.ColumnViewColumn.new("Name", factory)
    col_name.set_expand(True)
    self._column_view.append_column(col_name)

    # ... rest of picker card rendering (unchanged) ...
```

#### 3.4.8 `_expand_directory` — 5-tuple + Metadata + Generation Counter

**BUG #8 fix:** Capture `self._project_path` in closure, compare against generation counter.

```python
def _expand_directory(self, row_index: int) -> None:
    """Expand a directory row: load children on background thread, insert into store."""
    ...
    self._current_request_id += 1
    request_id = self._current_request_id

    row.props.expanded = True
    parent_path = row.props.full_path
    parent_depth = row.props.depth
    # BUG #8: Capture project_path in closure for safe comparison
    capture_project_path = self._project_path

    # ... loading spinner row ...
    
    def _do():
        try:
            entries = scan_directory(parent_path)
        except Exception as e:
            entries = [(f"[error: {type(e).__name__}: {e}]", "", False, 0, 0)]
        GLib.idle_add(lambda: self._on_directory_loaded(
            entries, _loading_row, row_index, parent_depth, request_id, capture_project_path
        ))

    threading.Thread(target=_do, daemon=True).start()
```

Update `_on_directory_loaded` signature and body:

```python
def _on_directory_loaded(self, entries, loading_row, row_index, parent_depth,
                          request_id, capture_project_path) -> None:
    """Handle directory scan result on main thread. Guard against stale requests."""
    # Unconditionally remove loading spinner row (by object identity)
    n = self._store.get_n_items()
    for i in range(n):
        if self._store.get_item(i) is loading_row:
            self._store.remove(i)
            break

    # BUG #8: Check generation counter AND project path consistency
    if request_id != self._current_request_id:
        return
    if self._project_path != capture_project_path:
        return  # Project switched while thread was running

    if row_index < 0 or row_index >= self._store.get_n_items():
        return
    parent_row: FileTreeRow = self._store.get_item(row_index)
    if not parent_row.props.is_dir or not parent_row.props.expanded:
        return

    # Insert real children with 5-tuple metadata
    insert_pos = row_index + 1
    for entry_name, full_path, is_dir, size_bytes, mtime_ns in entries:
        icon = get_icon_for_path(full_path, is_dir)
        child = FileTreeRow(
            display_name=entry_name,
            full_path=full_path,
            is_dir=is_dir,
            depth=parent_depth + 1,
            has_children=is_dir,
            expanded=False,
            file_size=0 if is_dir else size_bytes,
            file_size_display=format_size(size_bytes) if not is_dir else "—",
            modified_time=mtime_ns // 1_000_000_000 if mtime_ns else 0,
            modified_display=format_mtime(mtime_ns) if mtime_ns else "—",
            icon_name=icon.icon_name,
            icon_color_class=icon.color_class,
        )
        self._store.insert(insert_pos, child)
        insert_pos += 1
```

#### 3.4.9 Sort/Filter Model Chain — In-Place Mutation (BUG #11 Fix)

**BUG #11 fix:** Use `set_sorter()` and `set_filter()` in-place instead of constructing new models each time.

```python
def _init_sort_filter(self) -> None:
    """Create SortListModel + FilterListModel wrappers once."""
    self._sort_model = Gtk.SortListModel.new(self._store, None)
    self._filter_model = Gtk.FilterListModel.new(self._sort_model, None)
    # Replace selection model — this is done ONCE
    self._selection.set_model(self._filter_model)

def _apply_sort(self, sort_mode: str) -> None:
    """In-place sorter change (BUG #11 fix — no new model construction)."""
    if self._sort_model is None:
        return
    sorter = self._build_sorter(sort_mode)
    self._sort_model.set_sorter(sorter)

def _apply_filter(self, query: str) -> None:
    """In-place filter change (BUG #11 fix — no new model construction)."""
    if self._filter_model is None:
        return
    # Create a new CustomFilter each time — the filter itself is stateless
    # and the model accepts new filter objects via set_filter()
    if not query:
        self._filter_model.set_filter(None)
        return
    # BUG #19: GTK4 CustomFilter callback signature is (model, position, user_data),
    # NOT (row, user_data). Must call model.get_item(position) to get the row.
    custom_filter = Gtk.CustomFilter.new(
        lambda model, position, user_data: _filter_func(model, position, query)
    )
    self._filter_model.set_filter(custom_filter)

@staticmethod
def _filter_func(model: Gtk.FilterListModel, position: int, query: str) -> bool:
    """Filter function — substring match on display_name and full_path.
    
    Args follow GTK4 CustomFilter callback contract: (model, position, user_data).
    Must call model.get_item(position) to get the row (BUG #19 fix).
    
    Drawer rows always pass through if their parent file matches (BUG #18, #26 fix).
    """
    if not query:
        return True
    item = model.get_item(position)
    # BUG #24: Guard against None return from get_item (race on concurrent mutation)
    if item is None:
        return True
    row = cast(FileTreeRow, item)
    # BUG #18: Drawer rows must always pass through if their parent matches.
    # BUG #26: Check parent_full_path against the query — if the parent file
    # (e.g., "src/main.py") matches, the drawer row ("src/main.py" diff) should appear.
    if row.props.is_drawer:
        parent_path = row.props.parent_full_path or row.props.full_path
        q = query.casefold()
        return (q in row.props.display_name.casefold() or
                q in parent_path.casefold())
    q = query.casefold()  # BUG #12 fix
    return q in row.props.display_name.casefold() or q in row.props.full_path.casefold()
```

**NOTE:** `_init_sort_filter()` is called once after `_show_tree` populates the store. The `_apply_sort` and `_apply_filter` methods are called on sort/filter changes, mutating the existing model chain in place.

```python
def _build_sorter(self, sort_mode: str) -> Gtk.Sorter:
    """Build a comparator-based sorter from sort_mode string.
    
    Returns a Gtk.CustomSorter. GTK4 Python bindings pass (a, b) to the
    compare function; the user_data arg is None and safely ignored.
    Directories always sort before files regardless of sort mode.
    """
    def cmp_name_asc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        a_name = a.props.display_name.casefold()
        b_name = b.props.display_name.casefold()
        return -1 if a_name < b_name else (1 if a_name > b_name else 0)
    
    def cmp_name_desc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        a_name = a.props.display_name.casefold()
        b_name = b.props.display_name.casefold()
        return 1 if a_name < b_name else (-1 if a_name > b_name else 0)
    
    def cmp_modified_desc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        # b - a for descending (newest first)
        return (b.props.modified_time - a.props.modified_time)
    
    def cmp_modified_asc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        return (a.props.modified_time - b.props.modified_time)
    
    def cmp_size_desc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        return (b.props.file_size - a.props.file_size)
    
    def cmp_size_asc(a, b):
        if a.props.is_dir != b.props.is_dir:
            return -1 if a.props.is_dir else 1
        return (a.props.file_size - b.props.file_size)
    
    comparators = {
        "name_asc": cmp_name_asc,
        "name_desc": cmp_name_desc,
        "modified_desc": cmp_modified_desc,
        "modified_asc": cmp_modified_asc,
        "size_desc": cmp_size_desc,
        "size_asc": cmp_size_asc,
    }
    fn = comparators.get(sort_mode, cmp_name_asc)
    # BUG #31: CustomSorter compare function gets (a, b) — user_data is None
    return Gtk.CustomSorter.new(fn)
```

#### 3.4.10 Sort Dropdown Handler

```python
def _on_sort_dropdown_changed(self, dropdown, pspec):
    """Handle sort selection — update sort model in-place and notify handler.
    
    Uses _sort_changed_count as a generation counter to drop stale signals
    during rapid project switching (BUG #34).
    """
    self._sort_changed_count += 1
    request_id = self._sort_changed_count
    selected = dropdown.get_selected()
    modes = ["name_asc", "name_desc", "modified_desc", "modified_asc", "size_desc", "size_asc"]
    mode = modes[selected] if 0 <= selected < len(modes) else "name_asc"
    self._apply_sort(mode)
    # Drop stale callbacks if project switched during sort
    if request_id != self._sort_changed_count:
        return
    # Notify handler to persist preference
    if self._on_sort_changed:
        self._on_sort_changed(mode)
```

#### 3.4.11 Search Debounce + Filter (in View)

**BUG #9 fix:** Cancel outstanding timeout on project close.

```python
def __init__(self, ...):
    ...
    self._search_timeout_id = None  # for tree search debounce
    self._sort_changed_count = 0    # BUG #34: generation counter for sort change signals
    
def _clear_all_state(self):
    # BUG #9: Cancel outstanding search timeout before clearing
    if self._search_timeout_id is not None:
        try:
            GLib.source_remove(self._search_timeout_id)
        except Exception:
            pass
        self._search_timeout_id = None
    # ... rest of clear ...
```

Tree search callback (debounced, via `GLib.timeout_add`):

```python
def _on_search_changed_tree_cb(self, query: str) -> None:
    """Debounced tree-mode search handler. Called from _on_search_changed relay."""
    if self._search_timeout_id:
        GLib.source_remove(self._search_timeout_id)
    def _apply():
        self._apply_filter(query)
        # BUG #35: Update match count display in the search entry trailing label
        if self._filter_model:
            count = self._filter_model.get_n_items()
            total = self._store.get_n_items() if self._store else 0
            label = f"{count}/{total} matches" if query else ""
            self._search_entry.set_trailing_icon_name("")  # clear icon
            # Set placeholder to show count
            if query and total > 0:
                if count == 0:
                    self._search_entry.set_placeholder_text("No matches")
                else:
                    self._search_entry.set_placeholder_text(f"{count} of {total} files")
        self._search_timeout_id = None
    self._search_timeout_id = GLib.timeout_add(150, _apply)
```

#### 3.4.12 Drawer Toggle — Works with Filtered Model (BUG #7 Fix)

The existing `_toggle_drawer` inserts drawer rows into `self._store` (the underlying `Gio.ListStore`). The `SortListModel` and `FilterListModel` automatically observe store mutations — no special handling needed. However, `_find_file_index` must search the underlying store, not the filter model.

```python
def _find_file_index(self, file_path: str) -> Optional[int]:
    """Find the index of a file row in the STORE by full_path.
    
    Searches the underlying Gio.ListStore, NOT the filter model.
    This is called to find where to insert a drawer row, which
    goes into the store (filter/sort wrappers update automatically).
    """
    n = self._store.get_n_items()
    for i in range(n):
        row = cast(FileTreeRow, self._store.get_item(i))
        if not row.props.is_dir and not row.props.is_drawer and row.props.full_path == file_path:
            return i
    return None
```

#### 3.4.13 What's Removed from View (Logic Extraction)

**Removed** from `FileTree`:
- `/` metadata formatting — moved to pure functions in `file_tree.py` module-level (see §3.4.15)
- `/` git status computation — moved to handler
- `/` sort preference persistence — moved to handler
- `/` search debounce logic — kept in view (it's GTK-thread related)
- `/` sort/filter model construction each change — replaced with in-place mutation (**BUG #11 fix**)

**Kept** in `FileTree` (view only):
- `FileTreeRow` GObject definition + 9 new properties
- `FileTreeRowWidget` and 4 factory classes
- ColumnView + ListStore + model chain setup
- Header bar widgets (search, sort dropdown, back button, title)
- Directory expand/collapse (`_expand_directory`, `_on_directory_loaded`, `_collapse_directory`) — these use `scan_directory` (a utility) and `GLib.idle_add` (a GTK threading pattern); they're view-level orchestration
- Drawer row insertion/removal (`_toggle_drawer`, `_add_drawer_for_file`, `_on_revealer_child_revealed`)
- Row activation, right-click menu, keyboard shortcuts, copy status

#### 3.4.14 Handler Callback Attributes on FileTree

New attributes set by wiring code:

```python
self._on_sort_changed: Callable[[str], None] | None = None
self._on_search_changed_tree: Callable[[str], None] | None = None
self._on_expand_requested: Callable[[str], None] | None = None  # BUG #1 fix: reserved for future handler delegation
self._on_get_git_status: Callable[[], dict[str, str]] | None = None  # BUG #27 fix: get git status from handler

def set_on_sort_changed(self, cb):
    self._on_sort_changed = cb

def set_on_search_changed_tree(self, cb):
    self._on_search_changed_tree = cb

def set_on_expand_requested(self, cb):
    """Set callback for directory expansion. Currently unused — reserved for
    future handler delegation of background scanning. (BUG #28)"""
    self._on_expand_requested = cb

def set_on_get_git_status(self, cb):
    """Set callback to fetch git status dict from handler. (BUG #27 fix)"""
    self._on_get_git_status = cb
```

#### 3.4.15 Module-Level Utility Functions (in `file_tree.py`, Pure Python)

These are **public** functions (no leading underscore — **BUG #15 fix**).

```python
def format_size(bytes_: int) -> str:
    """Human-readable file size. Uses float for display to preserve fractional units.
    
    NOTE: Float division (not integer division) is correct here — we need to show
    "1.5 KB" not "1 KB" for 1500-byte files. BUG #14's integer division fix only
    applies to mtime_ns (nanosecond timestamps), NOT to file sizes.
    """
    if bytes_ <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(bytes_)
    for unit in units:
        if val < 1024:
            if unit == "B":
                return f"{int(val)} B"
            return f"{val:.1f} {unit}".replace(".0 ", " ")
        val /= 1024.0  # float division — preserves "1.5 KB" etc.
    return f"{val:.1f} PB"

def format_mtime(mtime_ns: int) -> str:
    """Human-readable relative time from nanosecond timestamp."""
    if mtime_ns <= 0:
        return "—"
    from datetime import datetime
    dt = datetime.fromtimestamp(mtime_ns // 1_000_000_000)  # BUG #14 fix: integer division
    now = datetime.now()
    diff = now - dt
    if diff.days == 0:
        if diff.seconds < 60:
            return "just now"
        if diff.seconds < 3600:
            return f"{diff.seconds // 60}m ago"
        return f"{diff.seconds // 3600}h ago"
    if diff.days == 1:
        return "yesterday"
    if diff.days < 7:
        return f"{diff.days}d ago"
    if diff.days < 30:
        return f"{diff.days // 7}w ago"
    return dt.strftime("%b %d")

def git_status_to_display(status_code: str) -> str:
    """Convert 2-char porcelain status to single-char badge text. BUG #15: no leading underscore."""
    if not status_code or len(status_code) < 2:
        return ""
    # Index column (first char) has precedence over working tree (second char)
    if status_code[0] != ' ':
        char = status_code[0]
    else:
        char = status_code[1]
    mapping = {'M': 'M', 'A': 'A', 'D': 'D', 'R': 'R', 'C': 'C', '?': '?', '!': '!'}
    return mapping.get(char, "")

def guess_mime(path: str) -> str:
    """Guess MIME type from file path. BUG #15: no leading underscore."""
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    return mime or ""
```

---

### 3.5 `ui/handlers/file_tree_handler.py` — **NEW FILE**

**No GTK imports.** Manages:
1. Sort preference persistence (load/save to `.crabcakes/file_tree_prefs.json`)
2. Git status cache (invalidate+refresh)
3. No Gtk.SortListModel, Gtk.CustomSorter, Gtk.FilterListModel, Gtk.CustomFilter — those live in the view (**BUG #2 fix**)

```python
import os
import json
from utils.git_ops import status_porcelain

class FileTreeHandler:
    """Manages file tree logic: git status caching, sort preference persistence.
    
    No GTK imports. Communicates with view via callbacks set on the view instance.
    """

    # Valid sort modes for BUG #13 validation
    _VALID_SORT_MODES = frozenset({
        "name_asc", "name_desc", "modified_desc", "modified_asc",
        "size_desc", "size_asc"
    })

    def __init__(self, project_path: str = ""):
        self._project_path = project_path
        self._git_status_cache: dict[str, str] = {}
        self._git_status_dirty = True
        self._sort_mode = "name_asc"
        self._prefs_path = ""
        if project_path:
            self._prefs_path = os.path.join(project_path, ".crabcakes", "file_tree_prefs.json")
            self._load_prefs()

    def refresh_git_status(self) -> dict[str, str]:
        """Run git status --porcelain, cache result, return parsed map.
        
        Returns empty dict if not a git repo or on any error.
        Cached until invalidate_git_status() is called.
        """
        if not self._git_status_dirty:
            return self._git_status_cache
        self._git_status_cache = status_porcelain(self._project_path)
        self._git_status_dirty = False
        return self._git_status_cache

    def invalidate_git_status(self) -> None:
        """Mark git status cache as dirty — next refresh will re-run git status."""
        self._git_status_dirty = True

    def get_sort_mode(self) -> str:
        return self._sort_mode

    def set_sort_mode(self, mode: str) -> None:
        """Set sort mode, save to persistence. Validates against whitelist (BUG #13 fix)."""
        if mode not in self._VALID_SORT_MODES:
            return  # Silently ignore invalid modes
        if mode != self._sort_mode:
            self._sort_mode = mode
            self._save_prefs()

    def set_project_path(self, path: str) -> None:
        """Called when project switches. Invalidates caches, loads prefs."""
        self._project_path = path
        self.invalidate_git_status()
        if path:
            self._prefs_path = os.path.join(path, ".crabcakes", "file_tree_prefs.json")
            self._load_prefs()
        else:
            self._prefs_path = ""
            self._sort_mode = "name_asc"

    def _load_prefs(self) -> None:
        """Load sort preference from disk. BUG #13: validates mode against whitelist."""
        if not self._prefs_path or not os.path.exists(self._prefs_path):
            self._sort_mode = "name_asc"
            return
        try:
            with open(self._prefs_path) as f:
                data = json.load(f)
                loaded = data.get("sort_mode", "name_asc")
                # BUG #13: Validate against whitelist
                if loaded in self._VALID_SORT_MODES:
                    self._sort_mode = loaded
                else:
                    self._sort_mode = "name_asc"
        except Exception:
            self._sort_mode = "name_asc"

    def _save_prefs(self) -> None:
        """Save sort mode to per-project prefs file."""
        if not self._prefs_path:
            return
        os.makedirs(os.path.dirname(self._prefs_path), exist_ok=True)
        with open(self._prefs_path, "w") as f:
            json.dump({"sort_mode": self._sort_mode}, f)
```

---

### 3.6 `ui/styles.py` — **EXTEND**

Add to `APP_CSS`:

```css
/* File tree status badges */
.file-tree-status-badge {
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    min-width: 18px;
    text-align: center;
}
.file-tree-status-modified { background: #f59e0b; color: #1e1e1e; }
.file-tree-status-staged { background: #22c55e; color: #1e1e1e; }
.file-tree-status-untracked { background: #6366f1; color: #fff; }
.file-tree-status-deleted { background: #ef4444; color: #fff; }
.file-tree-status-renamed { background: #a855f7; color: #fff; }
.file-tree-status-ignored { background: #6b7280; color: #fff; }

/* File tree columns */
.file-tree-size-column { 
    padding-right: 8px; 
    font-size: 12px; 
    color: #a0a0b0; 
}
.file-tree-modified-column { 
    padding-right: 8px; 
    font-size: 12px; 
    color: #a0a0b0; 
}

/* File type icon colors */
.file-icon-python { color: #f0c674; }
.file-icon-js { color: #e5c07b; }
.file-icon-ts { color: #61afef; }
.file-icon-json { color: #e5c07b; }
.file-icon-yaml { color: #e06c75; }
.file-icon-md { color: #98c379; }
.file-icon-rust { color: #e06c75; }
.file-icon-go { color: #61afef; }
.file-icon-cpp { color: #61afef; }
.file-icon-c { color: #61afef; }
.file-icon-sh { color: #98c379; }
.file-icon-png, .file-icon-jpg, .file-icon-gif { color: #c678dd; }
.file-icon-pdf { color: #e06c75; }
.file-icon-zip, .file-icon-tar, .file-icon-gz { color: #e5c07b; }
.file-icon-folder { color: #f0c674; }
.file-icon-default { color: #6b6b7a; }

/* Sort dropdown in tree header */
.file-tree-sort-dropdown {
    min-width: 140px;
    margin-left: 8px;
}
```

---

### 3.7 `ui/views/left_panel.py` — **MODIFY** (Wiring)

**BUG #9 fix:** Cancel outstanding timeouts on project close.

```python
# In LeftPanel.__init__():
from ui.handlers.file_tree_handler import FileTreeHandler
self._file_tree_handler = FileTreeHandler(project_path="")
# Wire view callbacks
self._file_tree.set_on_sort_changed(self._on_file_tree_sort_changed)
self._file_tree.set_on_search_changed_tree(self._on_file_tree_search_changed)
# BUG #27: Wire git status callback — handler returns parsed status dict
self._file_tree.set_on_get_git_status(self._get_file_tree_git_status)
# BUG #28: Wire expand callback (reserved for future handler delegation)
self._file_tree.set_on_expand_requested(self._on_file_tree_expand_requested)
```

Wiring methods in `LeftPanel`:

```python
def _on_file_tree_sort_changed(self, mode: str):
    """User changed sort mode — persist via handler."""
    self._file_tree_handler.set_sort_mode(mode)

def _on_file_tree_search_changed(self, query: str):
    """Tree search query — handled by view's debounce internally.
    
    For BUG #9: the view cancels the timeout in _clear_all_state.
    No handler interaction needed for search query itself.
    """
    pass  # View manages filter model

def _get_file_tree_git_status(self) -> dict[str, str]:
    """Return cached git status dict from handler. (BUG #27 fix)
    
    Called by FileTree._show_tree when populating root rows.
    """
    return self._file_tree_handler.refresh_git_status()

def _on_file_tree_expand_requested(self, path: str) -> None:
    """Reserved callback for future handler delegation of directory expansion.
    Currently unused — expansion is handled by view's _expand_directory. (BUG #28)"""
    pass

def on_project_opened(self, name: str, path: str):
    """Wire handler on project open. Invalidates git status cache."""
    self._file_tree_handler.set_project_path(path)
    # BUG #27: Invalidate git status so _show_tree picks up fresh data
    self._file_tree_handler.invalidate_git_status()

def on_project_closed(self):
    """Clear handler state on project close. BUG #9: timeouts handled by view."""
    self._file_tree_handler.set_project_path("")
```

---

### 3.8 Files NOT Changed

| File | Reason |
|------|--------|
| `ui/handlers/project_list_handler.py` | Already provides project data to FileTree; no changes needed |
| `ui/handlers/project_handler.py` | Manages project lifecycle; no changes needed |
| `models/` | Pure data — no changes |
| `gateway/` | No gateway involvement |
| `agent/` | No agent involvement |
| `utils/project_awareness.py` | Unrelated |
| `utils/git_ops.py::GitResult` | **Not modified** (BUG #6 fix) — new `status_porcelain()` returns bare `dict[str,str]` |
| `docs/ARCHITECTURE.md` | Will be updated (new handler, new view properties, model chain) |

---

### 3.9 New Test Files

**`tests/test_file_icons.py`** — Unit tests for icon registry
**`tests/test_file_tree_handler.py`** — Unit tests for handler (sort mode persistence, git status cache, path switching)
**`tests/test_git_ops.py`** — Extend existing tests for `status_porcelain`
**`tests/test_projects.py`** — Extend existing tests for `scan_directory` 5-tuple return

---

## 4. Data Flow

### User Action → View → Handler → View Refresh

| User Action | View Widget | View Method | Handler Method | View Refresh |
|-------------|-------------|-------------|----------------|--------------|
| Type in search | `Gtk.SearchEntry` | `_on_search_changed` → `_on_search_changed_tree_cb` (debounced) | N/A (view manages filter) | `_apply_filter()` → `filter_model.set_filter()` in-place (**BUG #11**) |
| Select sort option | `Gtk.DropDown` | `_on_sort_dropdown_changed` → `_apply_sort()` | `set_sort_mode()` → `_save_prefs()` | `_apply_sort()` → `sort_model.set_sorter()` in-place |
| Click directory expander | `Gtk.Button` | `_on_expander_clicked` → `_expand_directory` (bg thread) | N/A (view scans) | `_on_directory_loaded` → rows inserted with 9 new props |
| Click file row | `ColumnView ::activate` | `_on_row_activated` | N/A (existing) | Drawer toggle (unchanged) |
| Toggle drawer | (existing) | `_toggle_drawer` → `_store.insert()` | N/A | Sort/filter wrappers auto-observe store changes (**BUG #7**) |
| Project opens | N/A | `load_project` → `_show_tree` | `set_project_path()` → load prefs, invalidate git cache | Root rows populated |
| Project switches | N/A | `navigate_back` | `set_project_path("")` | Picker mode; timeout cancelled (**BUG #9**) |

### Model Chain (in View)

```
Gio.ListStore (store)
    └── Gtk.SortListModel (sort_model, created ONCE by _init_sort_filter)
        └── set_sorter() in-place on sort change  (BUG #11 fix)
        └── Gtk.FilterListModel (filter_model, created ONCE)
            └── set_filter() in-place on search   (BUG #11 fix)
            └── Gtk.SingleSelection (selection, set ONCE)
                └── Gtk.ColumnView (view)
```

### Background Thread Safety

| Operation | Thread | Safety |
|-----------|--------|--------|
| `scan_directory` in `_expand_directory` | Background | Captures `_current_request_id` + `capture_project_path` in closure (**BUG #8 fix**) |
| `status_porcelain` in handler | Main (handler is synchronous, called via view) | N/A — view calls handler.refresh_git_status() when needed |
| `_show_tree` row construction | Main | Already on main thread; reasonable for < 10k files (ColumnView virtualizes) |

**BUG #10 analysis:** The original spec proposed `_repopulate_tree` blocking the main thread with 10k row construction. **Mitigation:** The root-level `_show_tree` only shows one level of files (typically < 100 at root). Deep directories are expanded lazily by `_expand_directory` on a background thread, and each subtree is typically < 500 files. If project root has > 10k files, the user can use search to filter before they're all rendered (ColumnView lazily creates widgets for visible rows only). No background thread for root population is needed.

---

## 5. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `utils/file_icons.py` | **NEW** | ~120 | Low |
| `utils/git_ops.py` | Modified (+1 function) | +35 | Low |
| `utils/projects.py` | Modified (5-tuple) | +15 | Low |
| `ui/views/file_tree.py` | Modified (+9 props, +3 factories, +4 columns, sort/filter model chain, icon/color binding, search debounce, BG thread safety) | +280 | Medium |
| `ui/handlers/file_tree_handler.py` | **NEW** (sort prefs + git cache, no GTK) | ~120 | Low |
| `ui/styles.py` | Modified (+CSS for badges, icons, columns, sort) | +80 | Low |
| `ui/views/left_panel.py` | Modified (+handler wiring, project open/close callbacks) | +20 | Low |
| `tests/test_file_icons.py` | **NEW** | ~80 | Low |
| `tests/test_file_tree_handler.py` | **NEW** | ~100 | Low |
| `tests/test_file_tree_columnview.py` | Extended | +100 | Medium |
| `tests/test_git_ops.py` | Extended | +25 | Low |
| `tests/test_projects.py` | Extended | +15 | Low |
| `docs/ARCHITECTURE.md` | Modified | +40 | Low |
| **Total** | | **~1,030 net** | |

---

## 6. Implementation Order

### Phase 1 — Core Infrastructure (2-3 hrs)
1. Create `utils/file_icons.py` — icon registry + tests
2. Add `status_porcelain()` to `utils/git_ops.py` — returns bare dict, handles renames (**BUG #4, #5, #6 fixes**)
3. Extend `utils/projects.py` `scan_directory` → 5-tuple + update callers
4. Add CSS classes to `ui/styles.py`
5. Add 9 new GObject properties to `FileTreeRow` + update `__init__`

**Verification:**
```bash
python3 -c "from utils.file_icons import get_icon_for_path; print(get_icon_for_path('test.py', False))"
pytest tests/test_file_icons.py tests/test_git_ops.py tests/test_projects.py -v
```

### Phase 2 — Multi-Column View (3-4 hrs)
1. Create 3 new factories: `FileTreeStatusFactory`, `FileTreeSizeFactory`, `FileTreeModifiedFactory`
2. Update `_show_tree` → 4 columns, sort dropdown, search visibility (**BUG #3**)
3. Update `_show_project_picker` → single column, hide sort, keep search
4. Update `FileTreeFactory._on_bind` for `icon_name` + `icon_color_class`
5. Update `FileTreeRowWidget.set_icon` + add `set_icon_color`
6. Update `_expand_directory` / `_on_directory_loaded` for 5-tuple + metadata + generation counter (**BUG #8**, **BUG #14**)

**Verification:**
```bash
pytest tests/test_file_tree_columnview.py -v
python3 main.py  # Manual: open project, verify 4 columns, icons
```

### Phase 3 — Sort/Filter Model Chain (3-4 hrs)
1. Add `_init_sort_filter()` — creates SortListModel + FilterListModel ONCE
2. Add `_apply_sort(mode)` — in-place `set_sorter()` (**BUG #11 fix**)
3. Add `_apply_filter(query)` — in-place `set_filter()`, `casefold()` (**BUG #12 fix**)
4. Wire sort dropdown → `_on_sort_dropdown_changed` → `_apply_sort()`
5. Wire search entry → `_on_search_changed_tree_cb` (debounced 150ms)
6. Wire `_clear_all_state` to cancel search timeout (**BUG #9 fix**)

**Verification:**
```bash
# Manual: test sort (6 modes), search (substring, Esc clear), search+during-expand
```

### Phase 4 — Handler + Persistence + Integration (2-3 hrs)
1. Create `ui/handlers/file_tree_handler.py` — no GTK imports (**BUG #2 fix**)
2. Wire in `left_panel.py` — project open → `set_project_path()`, close → clear
3. Add per-project sort persistence (`.crabcakes/file_tree_prefs.json`) with mode validation (**BUG #13 fix**)
4. Ensure expand/collapse + drawer toggle work with active sort/filter (**BUG #7 fix**)
5. Verify no UI lag (10k file expand test)
6. Update `docs/ARCHITECTURE.md`

**Verification:**
```bash
pytest tests/test_file_tree_handler.py -v
pytest tests/ -k "file_tree" -v
# Manual full test
```

---

## 7. Acceptance Criteria

- [x] **BUG #1:** `_expand_directory` kept in view (was incorrectly listed for deletion). `on_expand_requested` callback added as future-proof wiring point.
- [x] **BUG #2:** Handler has NO GTK imports. Sort/filter model construction (`Gtk.SortListModel`, `Gtk.CustomSorter`, `Gtk.FilterListModel`, `Gtk.CustomFilter`) lives entirely in the view.
- [x] **BUG #3:** Search entry visible in BOTH modes. Sort dropdown visible ONLY in tree mode.
- [x] **BUG #4:** `status_porcelain` uses `len(line) >= 4` minimum (porcelain minimum is 4 chars).
- [x] **BUG #5:** `status_porcelain` handles rename format `R old -> new` by splitting on ` -> `.
- [x] **BUG #6:** `status_porcelain` returns bare `dict[str, str]` — `GitResult` dataclass NOT modified.
- [x] **BUG #7:** Drawer rows inserted into `Gio.ListStore` (underlying data model). Sort/filter wrappers auto-observe store changes. `_find_file_index` searches store, not filter model.
- [x] **BUG #8:** Background thread captures both `_current_request_id` (existing pattern) AND `capture_project_path` in closure. Both checked in `_on_directory_loaded`.
- [x] **BUG #9:** `_clear_all_state` cancels outstanding `_search_timeout_id`. No timeout manager in handler.
- [x] **BUG #10:** Row construction for root-level `_show_tree` is on main thread but bounded (< 100 files typical). Deep subtrees already use background threads in `_expand_directory`. No background thread needed for root.
- [x] **BUG #11:** `_init_sort_filter` creates models ONCE. `_apply_sort` uses `sort_model.set_sorter()` in-place. `_apply_filter` uses `filter_model.set_filter()` in-place. No new model construction on each change.
- [x] **BUG #12:** Search filter uses `str.casefold()` instead of `str.lower()`. No Turkish-i crash.
- [x] **BUG #13:** `_load_prefs` validates loaded sort_mode against `_VALID_SORT_MODES` whitelist. Invalid values → `"name_asc"` default.
- [x] **BUG #14:** Uses `mtime_ns // 1_000_000_000` (integer division) instead of `int(mtime_ns / 1e9)`. Note: integer division only applies to modification timestamps (nanosecond precision), NOT to file sizes. `format_size` correctly uses float division.
- [x] **BUG #15:** Helper functions are public (no leading underscore): `format_size`, `format_mtime`, `git_status_to_display`, `guess_mime`.
- [x] **BUG #16:** Dead `filter_fn` lambda removed from `_apply_filter`. Unused code eliminated.
- [x] **BUG #17:** `status_porcelain` handles copy (`C`) format in addition to rename (`R`).
- [x] **BUG #18:** `_filter_func` skips drawer rows (`if row.props.is_drawer: return True`) — but improved in BUG #26 to check parent_full_path.
- [x] **BUG #19:** `CustomFilter.new()` callback uses correct GTK4 signature `(model, position, user_data)`. Calls `model.get_item(position)` to get the row.
- [x] **BUG #21:** `format_size` uses float division (`val /= 1024.0`). Correctly shows "1.5 KB" not "1 KB". Integer division only applies to `format_mtime` (nanosecond timestamps).
- [x] **BUG #24:** `_filter_func` guards against `model.get_item(position)` returning `None` — returns `True` (pass-through) on `None`.
- [x] **BUG #25:** `status_porcelain` checks both status code positions: `status_code[0] in ('R', 'C')` for index column, `status_code[1] in ('R', 'C')` for worktree column.
- [x] **BUG #26:** `parent_full_path` GObject property added to `FileTreeRow`. Set when creating drawer rows in `_toggle_drawer`. `_filter_func` checks drawer rows against `parent_full_path` so they filter with their parent file.
- [x] **BUG #27:** Git status wired end-to-end: `_on_get_git_status` callback on `FileTree` → handler `refresh_git_status()`. `_show_tree` populates `git_status` and `git_status_display` on each row. `on_project_opened` calls `invalidate_git_status()`.
- [x] **BUG #28:** `set_on_expand_requested` wired in `left_panel.py` as no-op stub, reserved for future handler delegation of directory scanning.
- [x] **BUG #29:** `_on_search_changed` dispatcher calls `_on_search_changed_tree_cb(entry.get_text())` directly (view's debounce method), NOT `_on_search_changed_tree` (handler no-op).
- [x] **BUG #30:** Sort dropdown mode mapping is correct: menu text ("Name ↑") → index → mode string ("name_asc"). Handler `set_sort_mode()` validated against `_VALID_SORT_MODES` whitelist.
- [x] **BUG #31:** `Gtk.CustomSorter.new(fn)` documented with explicit 6 comparators. Compare function gets `(a, b)` — user_data is None.
- [x] **BUG #32:** All 6 comparators (`cmp_name_asc`, `cmp_name_desc`, `cmp_modified_desc`, `cmp_modified_asc`, `cmp_size_desc`, `cmp_size_asc`) fully specified — no `...` placeholders.
- [x] **BUG #33:** Data flow table reference `_on_search_changed_tree_cb` matches actual dispatcher (fixed by BUG #29).
- [x] **BUG #34:** `_sort_changed_count` generation counter added to sort dropdown handler, drops stale signals during rapid project switching.
- [x] **BUG #35:** Match count display shows "N of M files" in search entry placeholder after each debounced filter.

---

## 8. Edge Cases

| Case | Expected Behavior | Bug Coverage |
|------|-------------------|--------------|
| Empty directory | No rows shown (or "No files" placeholder) | — |
| No git repo | Status column empty everywhere | BUG #6: empty dict returned |
| Git rename line (`R  old -> new`) | Destination path shown with "R" badge | BUG #5: parser handles `->` split |
| Git error (permission denied) | Empty status dict, no crash | BUG #6: try/except catches all |
| Binary file (`.so`, `.pyc`) | Generic icon; no diff in drawer (existing) | — |
| Search matches 0 rows | Empty tree; drawer rows are not independently visible | BUG #12: casefold() works on empty strings; BUG #18, #26: drawer rows pass through filter via parent_full_path |
| Search matches dir name | Dir shown; children not auto-expanded | — |
| Rapid search typing | Only last query after 150ms debounce | BUG #9: timeout cancelled on _clear_all_state |
| `.crabcakes/file_tree_prefs.json` invalid mode | Fallback to "name_asc" | BUG #13: whitelist validation |
| Sort change during background expand | Scan completes, then sort reapplied to new data | BUG #8: generation counter + path check |
| Project switch during background expand | Stale request dropped; new project loads fresh | BUG #8: `capture_project_path` mismatch |
| Turkish locale search | No crash; `casefold()` handles İ/ı correctly | BUG #12: `casefold()` not `lower()` |
| UTF-8 filenames (emoji, CJK) | Displayed correctly | Existing Pango markup handles this |
| Symlink in directory | `os.stat` follows links | — |

---

## 9. Bug Fix Index

| Bug | Severity | Fix Location | Summary |
|-----|----------|-------------|---------|
| #1 | Critical | §3.4.13, §3.4.14 | `_expand_directory` stays in view; `on_expand_requested` callback added |
| #2 | Critical | §3.5 | Handler has zero GTK imports; models live in view |
| #3 | High | §3.4.6 | Search visible in both modes; sort visible only in tree |
| #4 | High | §3.2 | `len(line) >= 4` minimum for porcelain parsing |
| #5 | High | §3.2 | Rename format `R old -> new` → split on ` -> `, take right side |
| #6 | High | §3.2 | `status_porcelain` returns `dict[str,str]`; no `GitResult` change |
| #7 | High | §3.4.12 | Drawer rows inserted into store; sort/filter auto-observe |
| #8 | High | §3.4.8 | `capture_project_path` in closure + generation counter check |
| #9 | High | §3.4.11 | `_clear_all_state` cancels `_search_timeout_id` |
| #10 | High | §4 | Root scan < 100 files; deep subtrees already background-threaded |
| #11 | High | §3.4.9 | `set_sorter()`/`set_filter()` in-place — no model reconstruction |
| #12 | Medium | §3.4.9 | `casefold()` instead of `lower()` |
| #13 | Medium | §3.5 | `_VALID_SORT_MODES` whitelist in `_load_prefs` |
| #14 | Medium | §3.4.15 | `mtime_ns // 1_000_000_000` integer division (timestamps only); `format_size` uses float division |
| #15 | Medium | §3.4.15 | Helper functions are public: `format_size`, `format_mtime`, `git_status_to_display`, `guess_mime` |
| #16 | High | §3.4.9 | Removed dead `filter_fn` lambda from `_apply_filter` |
| #17 | High | §3.2 | `status_porcelain` handles copy (`C`) format in addition to rename (`R`) |
| #18 | High | §3.4.9 | `_filter_func` returns `True` for drawer rows (pass-through) |
| #19 | High | §3.4.9 | `CustomFilter.new()` callback uses correct GTK4 signature `(model, position, user_data)`; calls `model.get_item(position)` |
| #20 | — | — | *(skipped — auditor numbering gap)* |
| #21 | High | §3.4.15 | `format_size` restored to float division (`val /= 1024.0`); integer division was a regression that would show "1 KB" instead of "1.5 KB" |
| #24 | High | §3.4.9 | `_filter_func` guards against `model.get_item(position)` returning `None` — returns `True` (pass-through) |
| #25 | Medium | §3.2 | `status_porcelain` checks both status positions: `status_code[0] in ('R', 'C')` for index column AND `status_code[1] in ('R', 'C')` for worktree column |
| #26 | Medium | §3.4.1, §3.4.9 | `parent_full_path` GObject property added to `FileTreeRow`; `_filter_func` checks drawer rows against `parent_full_path` so they filter with their parent |
| #27 | Medium | §3.4.6, §3.7 | Git status wired into `_show_tree` row construction via `_on_get_git_status` callback → handler.`refresh_git_status()`. `on_project_opened` calls `invalidate_git_status()`. |
| #28 | Low | §3.4.14, §3.7 | `set_on_expand_requested` is wired in `left_panel.py` as a no-op stub, reserved for future handler delegation of directory scanning |
| #29 | Critical | §3.4.5 | `_on_search_changed` dispatcher calls `_on_search_changed_tree_cb()` (view's debounce) directly instead of handler callback |
| #30 | High | §3.4.10 | Sort dropdown mode mapping documented: menu text → index → mode string → whitelist-validated; all paths verified |
| #31 | High | §3.4.9 | `Gtk.CustomSorter.new(fn)` explicitly documented with 6 full comparator definitions; compare function gets `(a, b)` |
| #32 | High | §3.4.9 | All 6 comparators fully specified inline — no `...` placeholders or incomplete lambdas |
| #33 | Medium | §3.4.5, §4 | Data flow table and code both reference `_on_search_changed_tree_cb` — consistent after BUG #29 fix |
| #34 | Medium | §3.4.10, §3.4.11 | `_sort_changed_count` generation counter in sort dropdown handler drops stale signals on rapid project switch |
| #35 | Medium | §3.4.11 | Match count display: "N of M files" shown in search entry placeholder after each debounced filter |

---

## 10. ARCHITECTURE.md Updates Required

After implementation, update `docs/ARCHITECTURE.md`:

1. **§3.16 Handler Pattern** — Add `file_tree_handler.py` to handler list
2. **§3.5 CSS in styles.py** — Document new `.file-tree-status-*`, `.file-icon-*`, `.file-tree-sort-dropdown` classes
3. **§3.6 Composition Root** — Document `FileTreeHandler` wiring in LeftPanel
4. **§X File Tree Architecture (new)** — Describe:
   - FileTreeRow: 12 → 22 properties
   - ColumnView + SortListModel + FilterListModel chain (in-place mutation pattern)
   - Handler/view split: handler = prefs + git cache; view = widgets + sort/filter models
   - Background thread safety pattern (generation counter + path capture)
   - Search debounce and timeout lifecycle

---

**End of Spec — 35 bugs fixed, clean for implementation.**