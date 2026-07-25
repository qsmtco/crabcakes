# SPEC: File Tree Enhancements — Icons, Git Status, Size/Time Columns, Sorting, Search

**Date:** 2026-07-21
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL_FILE_TREE_ENHANCEMENTS.md`
**Depends on:** ARCHITECTURE.md (handler pattern §3.16, CSS in styles.py §3.5, window as composition root §3.6)
**Target branch:** main

> Architecture compliance statement: This spec follows ARCHITECTURE.md — `ui/views/file_tree.py` remains a pure view (widgets only, no business logic), new `ui/handlers/file_tree_handler.py` owns all logic with no GTK imports, `utils/` stays pure Python, all CSS in `ui/styles.py` via `add_css_class()`, and `window.py` wires handler to view via callbacks.

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

Users working in large projects lose context: they can't see at a glance which files are changed, how large files are, when they were last touched, or quickly filter to a specific file.

### 1.2 Solution
Transform the file tree into a **rich, multi-column, searchable project browser** by adding:

| Feature | Description |
|---------|-------------|
| **1. File Type Icons** | Per-extension icons (🐍 .py, 📄 .md, 🖼️ .png, ⚙️ .json, etc.) via a small icon registry. Fallback to generic file icon. |
| **2. Git Status Badges** | Inline colored badges/labels in a "Status" column: `M` (modified), `A` (added/staged), `?` (untracked), `D` (deleted), `R` (renamed), `C` (copied), `!!` (ignored). Computed via `git status --porcelain`. |
| **3. Size & Modified Time Columns** | Two new columns: **Size** (human-readable: 1.2 KB, 4.5 MB) and **Modified** (relative: "2h ago", "Mar 14", or absolute timestamp). |
| **4. Reorder by Modified Time** | Toolbar dropdown: "Sort: Name ↑ / Name ↓ / Modified ↑ (oldest first) / Modified ↓ (newest first) / Size ↑ / Size ↓". Default: Name ↑ (dirs first). |
| **5. Search/Filter Within Tree** | Inline search entry in the tree header (replaces project-picker search when in tree mode). Filters rows in real time (substring match on name + path). Shows match count. Esc clears. |

### 1.3 Why Now
- The file tree is the primary navigation surface for every project.
- Git status is the #1 request from users doing code review — they currently have to open the diff drawer to see if a file is modified.
- Search/filter is essential for projects with >100 files (most real projects).
- The ColumnView architecture (already in place) supports multi-column natively — we just need to add columns and a sort model.

---

## 2. Discovery

### 2.1 Files Read and Key Findings

**`ui/views/file_tree.py`** (read in full):
- `FileTreeRow` GObject has 12 properties: `display_name`, `full_path`, `is_dir`, `is_drawer`, `depth`, `expanded`, `has_children`, `drawer_widget`, `is_open`, `diff_text`, `history_selected_sha`, `history_loaded`
- `FileTreeFactory` creates `FileTreeRowWidget` with expander, icon, label, drawer_container
- ColumnView has single "Name" column with factory
- Search entry (`_search_entry`) exists but only visible in picker mode (project list)
- `_on_search_changed` filters project cards, not tree rows
- Drawer state tracked via `_drawer_paths` dict mapping file_path → FileTreeRow (object identity, not index)
- Directory expand/collapse uses `_expand_directory`/`_collapse_directory` with background thread loading
- `_find_row_index` uses object identity scan (BUG #2 fix)
- `_clear_all_state` clears store, drawers, loaded_drawers, increments `_current_request_id` for async guard

**`utils/git_ops.py`** (read in full):
- `GitResult` dataclass: `success`, `stdout`, `error`, `sha`
- Functions: `is_repo`, `init_repo`, `get_head_sha`, `get_branch`, `stage_all`, `commit`, `diff_against`, `diff_stat_against`, `diff_file_against`, `diff_file_against_working_tree`, `checkout_paths`, `log`, `get_recent_commits`, `file_log`, `push`, `diff_working_tree`, `status`
- `status()` returns `GitResult` with porcelain output in `stdout`
- Uses `_safe_error` for sanitized error messages
- SHA validation via `_VALID_SHA_RE`

**`utils/projects.py`** (read in full):
- `scan_directory(path)` returns `[(name, full_path, is_dir)]` — skips `__pycache__`, `.git`, `node_modules`, `.venv`, `venv`, dotfiles
- `load_projects()` returns `[(name, path)]`
- Uses `_PROJECTS_DIR_REF[0]` for test patching

**`ui/styles.py`** (read in full):
- Single `APP_CSS` string with all styles
- `apply_styles()` called once at startup from `main.py`
- CSS classes used via `add_css_class()` on widgets
- Existing classes for file tree: `.file-tree-row`, `.file-tree-row-expander`, `.file-tree-row-icon`, `.file-tree-row-label`, `.file-tree-column-view`, `.file-tree-drawer`, `.file-tree-drawer-tab-bar`, `.file-tree-drawer-tab-btn`, `.diff-viewer-*`, etc.

**`ui/window.py`** (read key sections):
- Composition root — wires all handlers and views
- `FileTree` instantiated in `LeftPanel` (not directly in window)
- `ProjectListHandler` provides project data to `FileTree` via `set_project_list_handler()`
- `FileTree.set_project_handler()` sets `ProjectHandler` reference for checkpoint SHA
- Project open/close callbacks wired to `ProjectHandler`

**`ui/handlers/`** (listed — 21 handlers exist):
- Pattern: handlers receive dependencies via constructor/setters, never import other handlers
- No GTK imports in handlers
- Window.py wires callbacks from view to handler

### 2.2 Architecture Owner
- **View layer:** `ui/views/file_tree.py` (pure GTK widgets)
- **Logic layer:** NEW `ui/handlers/file_tree_handler.py` (all business logic, no GTK)
- **Utilities:** NEW `utils/file_icons.py` (pure Python), extended `utils/git_ops.py`, extended `utils/projects.py`
- **Styles:** Extended `ui/styles.py` (CSS classes only)
- **Composition:** `ui/window.py` (wires handler ↔ view via callbacks)

### 2.3 Existing Patterns to Copy
- **Handler pattern:** `ui/handlers/project_list_handler.py` — pure logic, callbacks to view
- **ColumnView factory:** `FileTreeFactory` in `file_tree.py` — `_on_bind` binds GObject properties to widget
- **Background thread + GLib.idle_add:** `_expand_directory` → `_on_directory_loaded` pattern
- **Object identity tracking:** `_drawer_paths[file_path] = FileTreeRow` (not index)
- **CSS in styles.py:** All classes defined in `APP_CSS`, applied via `add_css_class()`
- **Per-project persistence:** `.crabcakes/` directory for project-specific state

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
    """Return FileIcon for a path. Priority: explicit extension → MIME → default."""
```

**Extension Map** (covers 95% of common files):
```python
_EXTENSION_MAP = {
    ".py": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyw": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyi": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".js": FileIcon("text-javascript-symbolic", "file-icon-js"),
    ".jsx": FileIcon("text-javascript-symbolic", "file-icon-js"),
    ".ts": FileIcon("text-typescript-symbolic", "file-icon-ts"),
    ".tsx": FileIcon("text-typescript-symbolic", "file-icon-ts"),
    ".json": FileIcon("application-json-symbolic", "file-icon-json"),
    ".yaml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".yml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".toml": FileIcon("application-x-toml-symbolic", "file-icon-toml"),
    ".md": FileIcon("text-x-markdown-symbolic", "file-icon-md"),
    ".txt": FileIcon("text-x-generic-symbolic", "file-icon-txt"),
    # ... (full map in proposal, ~60 extensions)
}
_MIME_MAP = { ... }  # fallback for unknown extensions
_DEFAULT_FILE = FileIcon("text-x-generic-symbolic", "file-icon-default")
_DEFAULT_DIR = FileIcon("folder-symbolic", "file-icon-folder")
```

**Logic:** If `is_dir` → `_DEFAULT_DIR`. Else check extension (longest match first). Else check MIME. Else `_DEFAULT_FILE`.

**Verification:**
```bash
python3 -c "from utils.file_icons import get_icon_for_path; print(get_icon_for_path('test.py', False))"
# FileIcon(icon_name='text-x-python-symbolic', color_class='file-icon-python')
```

---

### 3.2 `utils/git_ops.py` — **EXTEND**

Add one function:

```python
def status_porcelain(project_path: str) -> GitResult:
    """Returns parsed dict: {rel_path: status_code} where status_code is
    2-char porcelain string: ' M', 'M ', 'A ', 'D ', 'R ', '??', '!!', etc.
    """
    repo = gitpython.Repo(project_path)
    raw = repo.git.status("--porcelain")
    result = {}
    for line in raw.strip().splitlines():
        if len(line) >= 3:
            status_code = line[:2]
            rel_path = line[3:]
            result[rel_path] = status_code
    return GitResult(success=True, stdout="", error="", sha=None, extra=result)
```

**Note:** `GitResult.extra` field doesn't exist yet — add it to `GitResult` dataclass or return the dict directly. Proposal returns `extra=result`; we'll add `extra: dict | None = None` to `GitResult`.

**Verification:**
```bash
python3 -c "
from utils.git_ops import status_porcelain
result = status_porcelain('/home/q/projects/crabcakes')
print(result.success, result.extra)
"
```

---

### 3.3 `utils/projects.py` — **EXTEND**

Modify `scan_directory` to return metadata:

```python
def scan_directory(path: str) -> list[tuple[str, str, bool, int, int]]:
    """
    Return [(name, full_path, is_dir, size_bytes, mtime_ns)] for one level, filtered.
    Skips __pycache__, .git, node_modules, .venv, venv, dotfiles.
    """
    if not os.path.isdir(path):
        return []
    skip = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}
    result = []
    for name in sorted(os.listdir(path)):
        if name.startswith('.') or name in skip:
            continue
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
            result.append((name, full, os.path.isdir(full), st.st_size, int(st.st_mtime_ns)))
        except OSError:
            result.append((name, full, os.path.isdir(full), 0, 0))
    return result
```

**Return tuple change:** `(name, full_path, is_dir)` → `(name, full_path, is_dir, size_bytes, mtime_ns)`

**Impact:** Callers in `file_tree.py` (`_show_tree`, `_expand_directory` via `_on_directory_loaded`) must be updated to handle 5-tuple.

**Verification:**
```bash
python3 -c "from utils.projects import scan_directory; print(scan_directory('/home/q/projects/crabcakes')[:2])"
```

---

### 3.4 `ui/views/file_tree.py` — **MODIFY**

#### 3.4.1 `FileTreeRow` — Add 8 New GObject Properties

```python
# Append to existing properties (after history_loaded)
file_size = GObject.Property(type=int, default=0)
file_size_display = GObject.Property(type=str, default="—")
modified_time = GObject.Property(type=int, default=0)
modified_display = GObject.Property(type=str, default="—")
git_status = GObject.Property(type=str, default="")
git_status_display = GObject.Property(type=str, default="")
mime_type = GObject.Property(type=str, default="")
icon_name = GObject.Property(type=str, default="text-x-generic-symbolic")
```

**Total properties:** 12 → **20**. All bindable by ColumnView factory.

#### 3.4.2 `FileTreeRowWidget` — Update for Multi-Column

Currently only handles "Name" column (single widget per row). With 4 columns, `ColumnView` creates **one widget per cell** via column-specific factories. We need:

1. **Name column factory** — existing `FileTreeRowWidget` (expander, icon, label, drawer)
2. **Status column factory** — new simple widget showing badge
3. **Size column factory** — new simple widget showing right-aligned size
4. **Modified column factory** — new simple widget showing right-aligned time

**Change:** Convert `FileTreeFactory` to be **Name-column-specific**. Create 3 new factory classes:
- `FileTreeStatusFactory` — binds `git_status_display` + applies CSS class
- `FileTreeSizeFactory` — binds `file_size_display`, right-align
- `FileTreeModifiedFactory` — binds `modified_display`, right-align

Each factory's `_on_setup` creates appropriate widget (Label or Box with badge), `_on_bind` sets text/class.

#### 3.4.3 `FileTree` — Header Bar Additions

Add to `_build()` (after `_search_entry`):
```python
# Sort dropdown (visible in tree mode only)
self._sort_dropdown = Gtk.DropDown.new_from_strings([
    "Name ↑", "Name ↓", "Modified ↑", "Modified ↓", "Size ↑", "Size ↓"
])
self._sort_dropdown.set_selected(0)  # Name ↑ default
self._sort_dropdown.connect("notify::selected", self._on_sort_changed)
self._sort_dropdown.set_visible(False)  # hidden in picker mode
self._header.append(self._sort_dropdown)

# Search entry — move to be visible in TREE mode (not picker)
# Currently: visible in picker, hidden in tree. FLIP THIS.
```

**Callbacks to emit (view → handler):**
- `on_search_changed(query: str)` — debounced by handler
- `on_sort_changed(sort_mode: str)` — "name_asc", "name_desc", "modified_asc", "modified_desc", "size_asc", "size_desc"
- `on_file_selected(full_path: str, is_dir: bool)` — existing `_on_row_activated` logic
- `on_drawer_toggle(file_path: str)` — existing `_toggle_drawer`

#### 3.4.4 ColumnView Setup — 4 Columns

```python
# In _show_tree() after clearing state:
# Column 1: Name (existing factory)
factory_name = FileTreeFactory(self)
col_name = Gtk.ColumnViewColumn.new("Name", factory_name)
col_name.set_expand(True)
self._column_view.append_column(col_name)

# Column 2: Status
factory_status = FileTreeStatusFactory()
col_status = Gtk.ColumnViewColumn.new("Status", factory_status)
col_status.set_fixed_width(60)
col_status.set_resizable(False)
self._column_view.append_column(col_status)

# Column 3: Size
factory_size = FileTreeSizeFactory()
col_size = Gtk.ColumnViewColumn.new("Size", factory_size)
col_size.set_fixed_width(80)
col_size.set_resizable(False)
self._column_view.append_column(col_size)

# Column 4: Modified
factory_modified = FileTreeModifiedFactory()
col_modified = Gtk.ColumnViewColumn.new("Modified", factory_modified)
col_modified.set_fixed_width(100)
col_modified.set_resizable(False)
self._column_view.append_column(col_modified)
```

#### 3.4.5 `_show_tree` / `_show_project_picker` — Toggle Header Visibility

```python
def _show_tree(self, name, path):
    # ... existing code ...
    self._search_entry.set_visible(True)   # NOW visible in tree mode
    self._search_entry.set_placeholder_text("Search files... (Esc to clear)")
    self._sort_dropdown.set_visible(True)
    self._title_lbl.set_hexpand(False)  # make room for search/sort

def _show_project_picker(self):
    # ... existing code ...
    self._search_entry.set_visible(True)  # picker search
    self._search_entry.set_placeholder_text("Search projects...")
    self._sort_dropdown.set_visible(False)
    self._title_lbl.set_hexpand(True)
```

#### 3.4.6 Remove Logic from View

**DELETE from `FileTree`:**
- Directory scanning (`_expand_directory`, `_on_directory_loaded`, `_collapse_directory`)
- Git status computation
- Sort/filter model management
- Search debounce
- Metadata formatting (`format_size`, `format_mtime`)
- Persistence load/save

**KEEP in `FileTree` (view only):**
- `FileTreeRow` GObject definition
- `FileTreeRowWidget` and 4 factories
- ColumnView + ListStore setup
- Header bar widgets (search, sort dropdown, back button, title)
- Drawer row insertion/removal (`_toggle_drawer`, `_add_drawer_for_file`, `_on_revealer_child_revealed`)
- Row activation (`_on_row_activated` → emit `on_file_selected`)
- Right-click context menu
- Keyboard shortcuts (Esc, Ctrl+C)
- Project picker card rendering

---

### 3.5 `ui/handlers/file_tree_handler.py` — **NEW FILE**

**No GTK imports.** Pure logic handler.

**Constructor:**
```python
class FileTreeHandler:
    def __init__(
        self,
        project_path: str,
        file_tree_view: 'FileTree',  # view instance for callbacks
        GLib_module=None,            # for idle_add/timeout_add (testable)
    ):
        self._project_path = project_path
        self._view = file_tree_view
        self._GLib = GLib_module or __import__('gi.repository.GLib')
        # State
        self._git_status_cache: dict[str, str] = {}
        self._git_status_dirty = True
        self._sort_mode = "name_asc"
        self._search_query = ""
        self._search_timeout_id = None
        # Models
        self._store: Gio.ListStore = None
        self._sort_model: Gtk.SortListModel = None
        self._filter_model: Gtk.FilterListModel = None
        # Persistence
        self._prefs_path = os.path.join(project_path, ".crabcakes", "file_tree_prefs.json")
        self._load_prefs()
```

**Public Methods:**
```python
def connect_signals(self) -> None:
    """Wire view callbacks to handler methods."""
    self._view.on_search_changed = self._on_search_changed
    self._view.on_sort_changed = self._on_sort_changed
    self._view.on_file_selected = self._on_file_selected
    self._view.on_drawer_toggle = self._on_drawer_toggle

def set_project(self, project_path: str) -> None:
    """Called when project switches — refresh all state."""
    self._project_path = project_path
    self._git_status_cache.clear()
    self._git_status_dirty = True
    self._prefs_path = os.path.join(project_path, ".crabcakes", "file_tree_prefs.json")
    self._load_prefs()
    self._refresh_git_status()
    self._repopulate_tree()

def refresh(self) -> None:
    """Manual refresh (e.g., after drawer revert)."""
    self._git_status_dirty = True
    self._refresh_git_status()
    self._repopulate_tree()
```

**Private Methods — Data Loading:**
```python
def _repopulate_tree(self) -> None:
    """Scan directory, create FileTreeRow objects, populate store."""
    # 1. Get raw entries with metadata
    entries = scan_directory(self._project_path)  # 5-tuples
    # 2. Get git status map
    status_map = self._get_git_status_map()
    # 3. Build rows
    rows = []
    for name, full_path, is_dir, size, mtime_ns in entries:
        rel_path = os.path.relpath(full_path, self._project_path)
        git_status = status_map.get(rel_path, "")
        icon = get_icon_for_path(full_path, is_dir)
        row = FileTreeRow(
            display_name=name,
            full_path=full_path,
            is_dir=is_dir,
            depth=0,
            has_children=is_dir,
            expanded=False,
            file_size=0 if is_dir else size,
            file_size_display=format_size(size) if not is_dir else "—",
            modified_time=int(mtime_ns / 1e9) if mtime_ns else 0,
            modified_display=format_mtime(mtime_ns) if mtime_ns else "—",
            git_status=git_status,
            git_status_display=self._git_status_to_display(git_status),
            mime_type=self._guess_mime(full_path),
            icon_name=icon.icon_name,
        )
        rows.append(row)
    # 4. Update store (on main thread via idle_add)
    self._GLib.idle_add(self._replace_store_contents, rows)

def _replace_store_contents(self, rows: list[FileTreeRow]) -> None:
    """Replace ListStore contents on main thread."""
    store = self._view._store  # access view's store
    while store.get_n_items() > 0:
        store.remove(0)
    for row in rows:
        store.append(row)
    # Re-apply sort/filter
    self._rebuild_sort_filter()

def _rebuild_sort_filter(self) -> None:
    """Wrap store → sort → filter → set on column_view.selection."""
    store = self._view._store
    # Sort model
    sorter = self._make_sorter(self._sort_mode)
    self._sort_model = Gtk.SortListModel.new(store, sorter)
    # Filter model
    custom_filter = Gtk.CustomFilter.new(self._filter_func)
    self._filter_model = Gtk.FilterListModel.new(self._sort_model, custom_filter)
    # Replace selection model
    self._view._selection.set_model(self._filter_model)
```

**Private Methods — Git Status:**
```python
def _get_git_status_map(self) -> dict[str, str]:
    if not self._git_status_dirty:
        return self._git_status_cache
    # Run in background thread
    def _do():
        result = status_porcelain(self._project_path)
        if result.success:
            self._git_status_cache = result.extra or {}
        else:
            self._git_status_cache = {}
        self._git_status_dirty = False
        # Rebuild tree with new status
        self._GLib.idle_add(self._repopulate_tree)
    threading.Thread(target=_do, daemon=True).start()
    return self._git_status_cache  # stale but non-blocking
```

**Private Methods — Sorting:**
```python
def _make_sorter(self, sort_mode: str) -> Gtk.Sorter:
    comparators = {
        "name_asc": self._cmp_name_asc,
        "name_desc": self._cmp_name_desc,
        "modified_asc": self._cmp_mtime_asc,
        "modified_desc": self._cmp_mtime_desc,
        "size_asc": self._cmp_size_asc,
        "size_desc": self._cmp_size_desc,
    }
    return Gtk.CustomSorter.new(comparators[sort_mode])

def _cmp_name_asc(self, a: FileTreeRow, b: FileTreeRow) -> int:
    # Directory first
    if a.props.is_dir != b.props.is_dir:
        return -1 if a.props.is_dir else 1
    return (a.props.display_name.lower() > b.props.display_name.lower()) - (a.props.display_name.lower() < b.props.display_name.lower())

# ... similar for others, all using props.file_size, props.modified_time
```

**Private Methods — Filtering:**
```python
def _filter_func(self, row: FileTreeRow) -> bool:
    if not self._search_query:
        return True
    q = self._search_query.lower()
    return q in row.props.display_name.lower() or q in row.props.full_path.lower()
```

**Private Methods — Search Debounce:**
```python
def _on_search_changed(self, query: str) -> None:
    if self._search_timeout_id:
        self._GLib.source_remove(self._search_timeout_id)
    def _apply():
        self._search_query = query
        if self._filter_model:
            self._filter_model.get_filter().changed(Gtk.FilterChange.DIFFERENT)
        # Update match count in view
        count = sum(1 for i in range(self._filter_model.get_n_items()) if True)  # or iterate
        self._view.update_match_count(count)
        self._search_timeout_id = None
    self._search_timeout_id = self._GLib.timeout_add(150, _apply)
```

**Private Methods — Sort Change:**
```python
def _on_sort_changed(self, sort_mode: str) -> None:
    self._sort_mode = sort_mode
    self._save_prefs()
    self._rebuild_sort_filter()
```

**Private Methods — Persistence:**
```python
def _load_prefs(self) -> None:
    try:
        with open(self._prefs_path) as f:
            data = json.load(f)
            self._sort_mode = data.get("sort_mode", "name_asc")
            self._view.set_sort_dropdown(self._sort_mode)
    except Exception:
        self._sort_mode = "name_asc"

def _save_prefs(self) -> None:
    os.makedirs(os.path.dirname(self._prefs_path), exist_ok=True)
    with open(self._prefs_path, "w") as f:
        json.dump({"sort_mode": self._sort_mode}, f)
```

**Helper Functions (module-level, pure Python):**
```python
def format_size(bytes_: int) -> str:
    if bytes_ == 0:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}".rstrip(".0")
        bytes_ /= 1024
    return f"{bytes_:.1f} PB"

def format_mtime(ts_ns: int) -> str:
    if ts_ns == 0:
        return "—"
    dt = datetime.fromtimestamp(ts_ns / 1e9)
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

def _git_status_to_display(status_code: str) -> str:
    if not status_code:
        return ""
    # status_code is 2-char: ' M', 'M ', 'A ', 'D ', 'R ', '??', '!!'
    idx = 0 if status_code[0] != ' ' else 1
    char = status_code[idx]
    mapping = {'M': 'M', 'A': 'A', 'D': 'D', 'R': 'R', 'C': 'C', '?': '?', '!': '!'}
    return mapping.get(char, char)

def _guess_mime(path: str) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    return mime or ""
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
.file-tree-status-modified { background: #f59e0b; color: #1e1e1e; }      /* amber */
.file-tree-status-staged { background: #22c55e; color: #1e1e1e; }        /* green */
.file-tree-status-untracked { background: #6366f1; color: #fff; }        /* indigo */
.file-tree-status-deleted { background: #ef4444; color: #fff; }          /* red */
.file-tree-status-renamed { background: #a855f7; color: #fff; }          /* purple */
.file-tree-status-ignored { background: #6b7280; color: #fff; }          /* gray */

/* File tree columns */
.file-tree-size-column { text-align: right; padding-right: 8px; }
.file-tree-modified-column { text-align: right; padding-right: 8px; }
.file-tree-name-column { /* default */ }

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

/* Search entry in tree header */
.file-tree-search-entry { min-width: 200px; }
.file-tree-sort-dropdown { min-width: 140px; }
```

---

### 3.7 `ui/window.py` — **MODIFY**

In `LeftPanel` initialization (or wherever `FileTree` is created), wire the handler:

```python
# In MainWindow._build() or LeftPanel.__init__
from ui.handlers.file_tree_handler import FileTreeHandler

self._file_tree_handler = FileTreeHandler(
    project_path=project_path,  # when project opens
    file_tree_view=self._left_panel._file_tree,
    GLib_module=GLib,
)
self._file_tree_handler.connect_signals()
```

**Project open callback** (in `ProjectHandler` or window):
```python
def _on_project_opened(self, name, path):
    # ... existing ...
    self._file_tree_handler.set_project(path)
```

**Project close callback:**
```python
def _on_project_closed(self, name):
    # ... existing ...
    self._file_tree_handler.set_project(None)  # or clear
```

---

### 3.8 Files NOT Changed

| File | Reason |
|------|--------|
| `ui/handlers/project_list_handler.py` | Already provides project data to `FileTree`; no changes needed |
| `ui/handlers/project_handler.py` | Manages project lifecycle; just needs to call `handler.set_project()` |
| `models/` | Pure data — no changes |
| `gateway/` | No gateway involvement |
| `agent/` | No agent involvement |
| `utils/project_awareness.py` | Unrelated |
| `tests/test_file_tree_columnview.py` | **Will be extended** (see below) |

---

### 3.9 New Test Files

**`tests/test_file_icons.py`** — Unit tests for icon registry
**`tests/test_file_tree_handler.py`** — Unit tests for handler (sort, filter, git status, metadata, persistence)
**`tests/test_git_ops.py`** — Extend existing tests for `status_porcelain`
**`tests/test_projects.py`** — Extend existing tests for `scan_directory` 5-tuple return

---

## 4. Data Flow

```
User Action → View Callback → Handler Logic → Model Update → View Refresh
```

| User Action | View Callback | Handler Method | Result |
|-------------|---------------|----------------|--------|
| Type in search | `on_search_changed(query)` | `_on_search_changed` → debounce → `_filter_func` → `filter_model.changed()` | Rows filtered |
| Select sort dropdown | `on_sort_changed(mode)` | `_on_sort_changed` → `_make_sorter` → rebuild sort_model | Rows reordered |
| Click directory expander | `_on_expander_clicked` (view) | `_expand_directory` (handler) → background scan → `_on_directory_loaded` → append rows | Children shown |
| Click file row | `_on_row_activated` (view) | `on_file_selected(path, is_dir)` (handler) | Open file/diff |
| Toggle drawer | `_toggle_drawer` (view) | `on_drawer_toggle(path)` (handler) | Drawer open/close |
| Project opens | `set_project(path)` (handler) | `_repopulate_tree` → scan + git status → populate store | Tree loaded |
| Project switches | `set_project(new_path)` | Clear caches, reload prefs, repopulate | Fresh state |

**Background Threads:**
- Directory scan (`scan_directory`) → `GLib.idle_add` to update store
- Git status (`status_porcelain`) → `GLib.idle_add` to rebuild tree

**Model Chain:**
```
Gio.ListStore (store)
    → Gtk.SortListModel (sort_model, wraps store)
        → Gtk.FilterListModel (filter_model, wraps sort_model)
            → Gtk.SingleSelection (selection, wraps filter_model)
                → Gtk.ColumnView (view)
```

---

## 5. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `utils/file_icons.py` | **NEW** | ~120 | Low |
| `utils/git_ops.py` | Modified | +40 | Low |
| `utils/projects.py` | Modified | +30 | Low |
| `ui/views/file_tree.py` | Modified | +200 | Medium |
| `ui/handlers/file_tree_handler.py` | **NEW** | ~350 | Medium |
| `ui/styles.py` | Modified | +60 | Low |
| `ui/window.py` | Modified | +25 | Low |
| `tests/test_file_tree_columnview.py` | Modified | +150 | Medium |
| `tests/test_file_tree_handler.py` | **NEW** | ~200 | Medium |
| `tests/test_file_icons.py` | **NEW** | ~80 | Low |
| `tests/test_git_ops.py` | Modified | +30 | Low |
| `tests/test_projects.py` | Modified | +20 | Low |
| `docs/ARCHITECTURE.md` | Modified | +40 | Low |
| **Total** | | **~1,215 net** | |

---

## 6. Implementation Order

### Phase 1: Core Infrastructure (2-3 hrs)
1. Create `utils/file_icons.py` with tests
2. Extend `utils/git_ops.py` with `status_porcelain()` + test
3. Extend `utils/projects.py` `scan_directory()` → 5-tuple + test
4. Add 8 GObject properties to `FileTreeRow` in `file_tree.py`
5. Add CSS classes to `ui/styles.py`

**Verification:**
```bash
python3 -c "from utils.file_icons import get_icon_for_path; print(get_icon_for_path('test.py', False))"
python3 -c "from utils.git_ops import status_porcelain; print(status_porcelain('/home/q/projects/crabcakes'))"
python3 -c "from utils.projects import scan_directory; print(scan_directory('/home/q/projects/crabcakes')[:1])"
pytest tests/test_file_icons.py tests/test_git_ops.py tests/test_projects.py -v
```

### Phase 2: Handler + ColumnView (4-5 hrs)
1. Create `ui/handlers/file_tree_handler.py` with all logic
2. Refactor `ui/views/file_tree.py`:
   - Create 3 new factory classes (`StatusFactory`, `SizeFactory`, `ModifiedFactory`)
   - Add 4 columns to ColumnView
   - Add search entry + sort dropdown to header (toggle visibility tree vs picker)
   - Emit callbacks: `on_search_changed`, `on_sort_changed`, `on_file_selected`, `on_drawer_toggle`
   - Remove all logic (scanning, git status, sort/filter, formatting, persistence)
3. Wire in `window.py` / `LeftPanel` — create handler, connect signals

**Verification:**
```bash
pytest tests/test_file_tree_handler.py -v
pytest tests/test_file_tree_columnview.py -v
# Manual: run app, open project, verify 4 columns, icons, git badges, sort, search
```

### Phase 3: Integration & Polish (3-4 hrs)
1. Expand/collapse preserves sort/filter
2. Drawer toggle works with filtered/sorted model (`_find_row_index` on filtered model)
3. Project switch refreshes git status (cache cleared)
4. Performance: virtualized ColumnView handles 10k+ rows; background scan non-blocking
5. Accessibility: column headers have `accessible-name`, search entry labeled
6. Per-project sort persistence (`.crabcakes/file_tree_prefs.json`)

**Verification:**
```bash
pytest tests/ -k "file_tree" -v
# Manual test: 5000+ file project, verify no UI lag
```

### Phase 4: Documentation (1 hr)
1. Update `docs/ARCHITECTURE.md` — new handler, utils, view changes
2. Add entry to `README.md` features list
3. Update `docs/proposals/DEFERRED-ITEMS.md` if any items resolved

---

## 7. Acceptance Criteria

- [ ] File tree shows 4 columns: Name, Status, Size, Modified
- [ ] File type icons render for common extensions (py, js, ts, json, md, png, pdf, etc.)
- [ ] Git status badges show: `M` (modified), `A` (staged), `?` (untracked), `D` (deleted), `R` (renamed), `!` (ignored) with correct colors
- [ ] Size column shows human-readable sizes (B, KB, MB, GB), right-aligned, "—" for dirs
- [ ] Modified column shows relative times ("2h ago", "yesterday", "Mar 14"), right-aligned
- [ ] Sort dropdown works: 6 options, persists per-project, directories always first
- [ ] Search entry filters in real-time (150ms debounce), matches name + path, shows match count, Esc clears
- [ ] Expand/collapse works correctly with active search/sort
- [ ] Drawer toggle works with active search/sort (finds correct row in filtered model)
- [ ] Project switch refreshes all state (git status cache cleared)
- [ ] No UI lag on 5000+ file trees (virtualization works)
- [ ] All existing tests pass + new tests for handler (sort, filter, git status, metadata)
- [ ] Follows ARCHITECTURE.md: handler no GTK, view no logic, CSS in styles.py, window wires callbacks

---

## 8. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Empty directory | Shows no rows (or "Empty" placeholder) |
| No git repo | Status column empty for all rows |
| Git error (no repo, perm denied) | Status column empty, no crash |
| Binary file | Size shown, icon = generic, no diff in drawer (existing behavior) |
| Very long filename | Ellipsized in Name column (existing `set_ellipsize`) |
| Search query matches 0 rows | Tree empty, match count = "0 matches" |
| Search query matches dir name | Dir row shown; children not auto-expanded |
| Sort by size on dirs | Dirs always first (size 0), then files by size |
| Rapid search typing | Debounced — only last query after 150ms applied |
| Project with 10k files | Background scan, UI responsive, virtualization renders visible only |
| `.crabcakes/file_tree_prefs.json` corrupt | Fallback to default `name_asc`, no crash |
| Esc key in search entry | Clears search, restores full tree |
| Sort change during background scan | Scan completes, then sort reapplied to new data |

---

## 9. ARCHITECTURE.md Updates Required

After implementation, update `docs/ARCHITECTURE.md`:

1. **§3.16 Handler Pattern** — Add `file_tree_handler.py` to handler list
2. **§3.5 CSS in styles.py** — Document new `.file-tree-*` and `.file-icon-*` classes
3. **§3.6 Composition Root** — Document `FileTreeHandler` wiring in window/LeftPanel
4. **File tree architecture section** — Add subsection describing ColumnView + SortListModel + FilterListModel chain, handler/view split, background scanning, git status caching

---

## 10. Verification Commands

```bash
# Unit tests
pytest tests/test_file_icons.py -v
pytest tests/test_git_ops.py -v
pytest tests/test_projects.py -v
pytest tests/test_file_tree_handler.py -v
pytest tests/test_file_tree_columnview.py -v

# Integration test (manual)
python3 main.py
# 1. Open a project with git changes
# 2. Verify 4 columns visible
# 3. Verify icons on files
# 4. Verify git status badges (M, ?, A, etc.)
# 5. Test sort dropdown — all 6 options
# 6. Test search — type "test", verify filter
# 7. Test expand/collapse with search active
# 8. Test drawer toggle with sort active
# 9. Switch projects — verify refresh
# 10. Close/reopen — verify sort persisted
```

---

**End of Spec**