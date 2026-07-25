# PROPOSAL: File Tree Enhancements — Icons, Git Status, Size/Time Columns, Sorting, Search

**Date:** 2026-07-21  
**Author:** Qaster  
**Status:** Draft — for implementation  
**Priority:** High  
**Effort:** ~12-16 hours

> Architecture compliance (ARCHITECTURE.md):  
> - `ui/views/file_tree.py` is a pure view — widgets only, no business logic.  
> - `ui/handlers/file_tree_handler.py` (NEW) owns all logic with no GTK imports.  
> - `utils/` stays pure Python, no GTK deps.  
> - All CSS in `ui/styles.py` via `add_css_class()`.  
> - `window.py` is the composition root — wires handler to view via callbacks.  
> - Handler pattern (§3.16) mandatory for all new logic.

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

## 2. Technical Design

### 2.1 Architecture — New Module Split

| File | Responsibility | Layer |
|------|---------------|-------|
| `ui/views/file_tree.py` | **VIEW ONLY** — ColumnView setup, cell renderers, CSS classes, search entry widget, sort dropdown widget. Emits callbacks: `on_file_selected`, `on_search_changed`, `on_sort_changed`, `on_drawer_toggle`. | View |
| `ui/handlers/file_tree_handler.py` | **NEW — HANDLER** — All logic: directory scanning (threaded), git status computation, file metadata (size, mtime), sort/filter model management, search debounce. No GTK imports. | Handler |
| `utils/file_icons.py` | **NEW — UTIL** — Pure Python: extension → icon name mapping, MIME type fallback, generic icons. No GTK. | Utils |
| `utils/git_ops.py` | **EXTEND** — Add `status_porcelain(path)` returning parsed status map `{rel_path: status_code}`. | Utils |
| `ui/styles.py` | **EXTEND** — CSS for status badges, size column, modified column, search entry, sort dropdown, file type icon colors. | Styles |

**window.py** wires it:
```python
# In MainWindow._build()
self._file_tree = FileTree(on_file_selected=...)
self._file_tree_handler = FileTreeHandler(
    project_path=...,
    file_tree_view=self._file_tree,
)
self._file_tree_handler.connect_signals()
```

### 2.2 Data Model Changes — `FileTreeRow` GObject

Add 4 new GObject properties to `FileTreeRow` (append to existing 12):

| Property | Type | Description |
|----------|------|-------------|
| `file_size` | `int` | Size in bytes (0 for dirs) |
| `file_size_display` | `str` | Human-readable (e.g. "1.2 KB", "—") |
| `modified_time` | `int` | Unix timestamp (seconds) |
| `modified_display` | `str` | Human-readable (e.g. "2h ago", "Mar 14") |
| `git_status` | `str` | Porcelain status code: `" M"`, `"M "`, `"??"`, `"D "`, `"R "`, `"!!"` |
| `git_status_display` | `str` | Short badge text: `"M"`, `"A"`, `"?"`, `"D"`, `"R"`, `"!"` |
| `mime_type` | `str` | MIME type for icon lookup (e.g. `text/x-python`) |
| `icon_name` | `str` | Icon name for GTK (e.g. `text-x-python-symbolic`) |

Total: 12 → **20 properties**. All bindable by ColumnView factory.

### 2.3 ColumnView Layout — 4 Columns

| Column | Factory Binding | Width | Sortable |
|--------|----------------|-------|----------|
| **Name** | `display_name` (markup) + `icon_name` + `expander` + `depth` margin | Expand (fill) | ✅ Name |
| **Status** | `git_status_display` + colored badge | 60px fixed | ✅ Git status |
| **Size** | `file_size_display` (right-aligned) | 80px fixed | ✅ Size (bytes) |
| **Modified** | `modified_display` (right-aligned) | 100px fixed | ✅ Modified (timestamp) |

**Header bar additions (above ColumnView):**
- Search entry (`Gtk.SearchEntry`) — visible in tree mode, hidden in picker mode
- Sort dropdown (`Gtk.DropDown`) — "Name ↑", "Name ↓", "Modified ↑", "Modified ↓", "Size ↑", "Size ↓"

### 2.4 Sorting — `Gtk.SortListModel`

Wrap the `Gio.ListStore` in a `Gtk.SortListModel` with a `Gtk.Sorter`:

```python
# In handler — no GTK imports, just constructs the sorter spec
def _make_sorter(sort_mode: str) -> Gtk.Sorter:
    if sort_mode == "name_asc":
        return Gtk.CustomSorter.new(_compare_name_asc)
    elif sort_mode == "name_desc":
        return Gtk.CustomSorter.new(_compare_name_desc)
    elif sort_mode == "modified_asc":
        return Gtk.CustomSorter.new(_compare_mtime_asc)
    elif sort_mode == "modified_desc":
        return Gtk.CustomSorter.new(_compare_mtime_desc)
    elif sort_mode == "size_asc":
        return Gtk.CustomSorter.new(_compare_size_asc)
    elif sort_mode == "size_desc":
        return Gtk.CustomSorter.new(_compare_size_desc)
```

**Directory-first ordering** is baked into each comparator: `is_dir` sorts before `!is_dir`.

### 2.5 Filtering — `Gtk.FilterListModel`

Wrap the `SortListModel` in a `Gtk.FilterListModel` with a `Gtk.CustomFilter`:

```python
filter_model = Gtk.FilterListModel.new(sort_model, custom_filter)
custom_filter.set_filter_func(_filter_func)
```

Search text → `_filter_func(row)` returns `True` if `query.lower() in row.props.full_path.lower()` or `query.lower() in row.props.display_name.lower()`.

**Debounce:** 150ms on search entry `search-changed` → handler updates filter.

### 2.6 Git Status Computation

**New `git_ops.py` function:**
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

**Handler caches** the status map and invalidates on:
- File tree refresh (user clicks refresh or navigates)
- After drawer revert (file content changed)
- Debounced: max once per 2 seconds during active editing

### 2.7 File Icons — `utils/file_icons.py`

```python
# utils/file_icons.py — Pure Python, no GTK
from dataclasses import dataclass

@dataclass(frozen=True)
class FileIcon:
    icon_name: str          # GTK icon name (e.g. "text-x-python-symbolic")
    color_class: str        # CSS class for color (e.g. "file-icon-python")

# Extension → icon map (covers 95% of common files)
_EXTENSION_MAP: dict[str, FileIcon] = {
    ".py":   FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyw":  FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyi":  FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".js":   FileIcon("text-javascript-symbolic", "file-icon-js"),
    ".jsx":  FileIcon("text-javascript-symbolic", "file-icon-js"),
    ".ts":   FileIcon("text-typescript-symbolic", "file-icon-ts"),
    ".tsx":  FileIcon("text-typescript-symbolic", "file-icon-ts"),
    ".json": FileIcon("application-json-symbolic", "file-icon-json"),
    ".yaml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".yml":  FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".toml": FileIcon("application-x-toml-symbolic", "file-icon-toml"),
    ".md":   FileIcon("text-x-markdown-symbolic", "file-icon-md"),
    ".txt":  FileIcon("text-x-generic-symbolic", "file-icon-txt"),
    ".html": FileIcon("text-html-symbolic", "file-icon-html"),
    ".css":  FileIcon("text-css-symbolic", "file-icon-css"),
    ".scss": FileIcon("text-css-symbolic", "file-icon-scss"),
    ".rs":   FileIcon("text-x-rust-symbolic", "file-icon-rust"),
    ".go":   FileIcon("text-x-go-symbolic", "file-icon-go"),
    ".java": FileIcon("text-x-java-symbolic", "file-icon-java"),
    ".kt":   FileIcon("text-x-kotlin-symbolic", "file-icon-kotlin"),
    ".cpp":  FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    ".cc":   FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    ".c":    FileIcon("text-x-csrc-symbolic", "file-icon-c"),
    ".h":    FileIcon("text-x-chdr-symbolic", "file-icon-h"),
    ".hpp":  FileIcon("text-x-chdr-symbolic", "file-icon-hpp"),
    ".sh":   FileIcon("application-x-shellscript-symbolic", "file-icon-sh"),
    ".bash": FileIcon("application-x-shellscript-symbolic", "file-icon-sh"),
    ".zsh":  FileIcon("application-x-shellscript-symbolic", "file-icon-sh"),
    ".fish": FileIcon("application-x-shellscript-symbolic", "file-icon-sh"),
    ".ps1":  FileIcon("application-x-shellscript-symbolic", "file-icon-ps1"),
    ".rb":   FileIcon("text-x-ruby-symbolic", "file-icon-rb"),
    ".php":  FileIcon("text-x-php-symbolic", "file-icon-php"),
    ".swift":FileIcon("text-x-swift-symbolic", "file-icon-swift"),
    ".dart": FileIcon("text-x-dart-symbolic", "file-icon-dart"),
    ".lua":  FileIcon("text-x-lua-symbolic", "file-icon-lua"),
    ".pl":   FileIcon("text-x-perl-symbolic", "file-icon-pl"),
    ".r":    FileIcon("text-x-r-symbolic", "file-icon-r"),
    ".sql":  FileIcon("application-x-sql-symbolic", "file-icon-sql"),
    ".xml":  FileIcon("application-xml-symbolic", "file-icon-xml"),
    ".svg":  FileIcon("image-svg+xml-symbolic", "file-icon-svg"),
    ".png":  FileIcon("image-png-symbolic", "file-icon-png"),
    ".jpg":  FileIcon("image-jpeg-symbolic", "file-icon-jpg"),
    ".jpeg": FileIcon("image-jpeg-symbolic", "file-icon-jpg"),
    ".gif":  FileIcon("image-gif-symbolic", "file-icon-gif"),
    ".webp": FileIcon("image-webp-symbolic", "file-icon-webp"),
    ".ico":  FileIcon("image-x-icon-symbolic", "file-icon-ico"),
    ".pdf":  FileIcon("application-pdf-symbolic", "file-icon-pdf"),
    ".zip":  FileIcon("application-zip-symbolic", "file-icon-zip"),
    ".tar":  FileIcon("application-x-tar-symbolic", "file-icon-tar"),
    ".gz":   FileIcon("application-gzip-symbolic", "file-icon-gz"),
    ".bz2":  FileIcon("application-x-bzip2-symbolic", "file-icon-bz2"),
    ".xz":   FileIcon("application-x-xz-symbolic", "file-icon-xz"),
    ".7z":   FileIcon("application-x-7z-compressed-symbolic", "file-icon-7z"),
    ".rar":  FileIcon("application-x-rar-symbolic", "file-icon-rar"),
    ".exe":  FileIcon("application-x-executable-symbolic", "file-icon-exe"),
    ".dll":  FileIcon("application-x-sharedlib-symbolic", "file-icon-dll"),
    ".so":   FileIcon("application-x-sharedlib-symbolic", "file-icon-so"),
    ".dylib":FileIcon("application-x-sharedlib-symbolic", "file-icon-dylib"),
    ".class":FileIcon("application-x-java-archive-symbolic", "file-icon-class"),
    ".jar":  FileIcon("application-x-java-archive-symbolic", "file-icon-jar"),
    ".war":  FileIcon("application-x-java-archive-symbolic", "file-icon-war"),
    ".ear":  FileIcon("application-x-java-archive-symbolic", "file-icon-ear"),
    ".dockerfile": FileIcon("text-x-dockerfile-symbolic", "file-icon-docker"),
    ".gitignore": FileIcon("text-x-generic-symbolic", "file-icon-gitignore"),
    ".gitattributes": FileIcon("text-x-generic-symbolic", "file-icon-git"),
    ".env":  FileIcon("text-x-generic-symbolic", "file-icon-env"),
    ".ini":  FileIcon("text-x-generic-symbolic", "file-icon-ini"),
    ".cfg":  FileIcon("text-x-generic-symbolic", "file-icon-cfg"),
    ".conf": FileIcon("text-x-generic-symbolic", "file-icon-conf"),
    ".log":  FileIcon("text-x-log-symbolic", "file-icon-log"),
    ".lock": FileIcon("text-x-generic-symbolic", "file-icon-lock"),
}

# MIME fallback map
_MIME_MAP: dict[str, FileIcon] = {
    "text/x-python": _EXTENSION_MAP[".py"],
    "text/javascript": _EXTENSION_MAP[".js"],
    "application/json": _EXTENSION_MAP[".json"],
    "text/x-markdown": _EXTENSION_MAP[".md"],
    "text/html": _EXTENSION_MAP[".html"],
    "text/css": _EXTENSION_MAP[".css"],
    "application/xml": _EXTENSION_MAP[".xml"],
    "image/svg+xml": _EXTENSION_MAP[".svg"],
    "image/png": _EXTENSION_MAP[".png"],
    "image/jpeg": _EXTENSION_MAP[".jpg"],
    "application/pdf": _EXTENSION_MAP[".pdf"],
    "application/zip": _EXTENSION_MAP[".zip"],
    "application/x-tar": _EXTENSION_MAP[".tar"],
    "application/gzip": _EXTENSION_MAP[".gz"],
    "application/x-bzip2": _EXTENSION_MAP[".bz2"],
    "application/x-xz": _EXTENSION_MAP[".xz"],
    "application/x-7z-compressed": _EXTENSION_MAP[".7z"],
    "application/x-rar": _EXTENSION_MAP[".rar"],
    "application/x-executable": _EXTENSION_MAP[".exe"],
    "application/x-sharedlib": _EXTENSION_MAP[".so"],
    "application/java-archive": _EXTENSION_MAP[".jar"],
}

_DEFAULT_FILE = FileIcon("text-x-generic-symbolic", "file-icon-default")
_DEFAULT_DIR = FileIcon("folder-symbolic", "file-icon-folder")

def get_icon_for_path(path: str, is_dir: bool, mime_type: str | None = None) -> FileIcon:
    """Return FileIcon for a path. Priority: explicit extension → MIME → default."""
    if is_dir:
        return _DEFAULT_DIR
    # Extension match (longest first)
    for ext in sorted(_EXTENSION_MAP.keys(), key=len, reverse=True):
        if path.lower().endswith(ext):
            return _EXTENSION_MAP[ext]
    # MIME fallback
    if mime_type and mime_type in _MIME_MAP:
        return _MIME_MAP[mime_type]
    return _DEFAULT_FILE
```

**CSS in `styles.py`:**
```css
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
```

### 2.8 File Metadata (Size + Mtime)

**Handler scans directory** (background thread via `utils.projects.scan_directory` extended to return `os.stat_result`):

```python
# In handler — pure Python, no GTK
def _scan_with_metadata(path: str) -> list[FileEntry]:
    """FileEntry = (name, full_path, is_dir, size_bytes, mtime_ns)"""
    entries = []
    for name in sorted(os.listdir(path)):
        if name.startswith('.') or name in SKIP_DIRS:
            continue
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
            entries.append((name, full, os.path.isdir(full), st.st_size, int(st.st_mtime_ns)))
        except OSError:
            entries.append((name, full, os.path.isdir(full), 0, 0))
    return entries
```

**Human-readable formatting** (pure Python, handler):
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
    return dt.strftime("%b %d")  # "Mar 14"
```

---

## 3. UI/UX Details

### 3.1 Header Bar (Tree Mode)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ◀  📁  MyProject                                    [🔍 Search...]  │
│ ┌────────────────┐                                                    │
│ │ Sort: Name ↑ ▾ │                                                    │
│ └────────────────┘                                                    │
├────────┬────────┬────────┬──────────────────────────────────────────┤
│ Name                     │ Status │ Size    │ Modified              │
├────────┼────────┼────────┼──────────────────────────────────────────┤
│ 📁 src                   │        │ —       │ 2h ago                │
│   🐍 main.py             │  M     │ 2.1 KB  │ 5m ago                │
│   🐍 utils.py            │        │ 845 B   │ 3d ago                │
│ 📁 tests                 │        │ —       │ 1w ago                │
│   🐍 test_main.py        │  ?     │ 1.2 KB  │ 2h ago                │
│ 📄 README.md             │        │ 4.2 KB  │ Mar 14                │
│ 📄 pyproject.toml        │  A     │ 567 B   │ 2d ago                │
└────────┴────────┴────────┴──────────────────────────────────────────┘
```

### 3.2 Status Badge Colors (CSS)

```css
/* In styles.py — APP_CSS */
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
```

### 3.3 Search Entry Behavior

- Visible **only in tree mode** (hidden in project picker)
- Placeholder: `"Search files... (Esc to clear)"`
- Debounced 150ms
- Shows match count in trailing label: `"12 matches"`
- `Escape` key clears search and restores full tree
- Search matches **both name and relative path** (substring, case-insensitive)

### 3.4 Sort Dropdown Options

| Option | Internal Key | Comparator |
|--------|-------------|------------|
| Name A–Z (dirs first) | `name_asc` | `is_dir desc, name.lower asc` |
| Name Z–A (dirs first) | `name_desc` | `is_dir desc, name.lower desc` |
| Modified ↓ (newest first) | `modified_desc` | `is_dir desc, mtime_ns desc` |
| Modified ↑ (oldest first) | `modified_asc` | `is_dir desc, mtime_ns asc` |
| Size ↓ (largest first) | `size_desc` | `is_dir desc, size_bytes desc` |
| Size ↑ (smallest first) | `size_asc` | `is_dir desc, size_bytes asc` |

**Default:** `name_asc`

**Persisted:** Per-project preference in `.crabcakes/file_tree_prefs.json`:
```json
{ "sort_mode": "modified_desc", "show_hidden": false }
```

---

## 4. Implementation Plan

### Phase 1: Core Infrastructure (2-3 hrs)
1. **Create `utils/file_icons.py`** — pure Python icon registry, tests
2. **Extend `utils/git_ops.py`** — add `status_porcelain()` returning parsed map
3. **Extend `utils/projects.scan_directory()`** — return `(name, path, is_dir, size, mtime_ns)`
4. **Add `FileTreeRow` properties** — 8 new GObject properties (size, mtime, git_status, icon, mime)
5. **Add CSS classes** to `ui/styles.py` for status badges, size column, modified column, icons

### Phase 2: Handler + ColumnView (4-5 hrs)
1. **Create `ui/handlers/file_tree_handler.py`** — logic for:
   - Directory scanning (threaded, with metadata)
   - Git status computation (cached, debounced)
   - Sort model management (`Gtk.SortListModel` + custom sorters)
   - Filter model management (`Gtk.FilterListModel` + custom filter)
   - Search debounce (150ms)
   - Sort dropdown callback
   - Persist/load per-project sort preference
2. **Refactor `ui/views/file_tree.py`** — view only:
   - Add 3 new columns (Status, Size, Modified) to ColumnView
   - Add search entry + sort dropdown to header bar (tree mode only)
   - Update factory `_on_bind` to bind new properties
   - Emit callbacks: `on_search_changed`, `on_sort_changed`, `on_file_selected`, `on_drawer_toggle`
3. **Wire in `window.py`** — create handler, connect view callbacks to handler methods

### Phase 3: Integration & Polish (3-4 hrs)
1. **Expand/collapse preserves sort/filter** — test that expanding a dir doesn't reset search
2. **Drawer toggle works with filtered/sorted model** — `_find_row_index` must work on filtered model
3. **Project switch refreshes git status** — clear caches on `load_project` / `navigate_back`
4. **Performance** — virtualized ColumnView handles 10k+ rows; ensure background scan doesn't block UI
5. **Accessibility** — column headers have proper `accessible-name`, search entry labeled
6. **Tests** — unit tests for handler (sort, filter, git status parsing), view tests for binding

### Phase 4: Documentation (1 hr)
1. Update `docs/ARCHITECTURE.md` — new handler, utils, view changes
2. Add entry to `README.md` features list
3. Update `docs/proposals/DEFERRED-ITEMS.md` if any items resolved

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
| `docs/ARCHITECTURE.md` | Modified | +40 | Low |
| **Total** | | **~1,215 net** | |

---

## 6. Acceptance Criteria

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

## 7. Future Enhancements (Not In Scope)

| Feature | Reason Deferred |
|---------|-----------------|
| Show hidden files toggle | Can add as toolbar checkbox later |
| Git branch indicator in header | Requires git_ops.get_branch() integration |
| File context menu (Open in Terminal, Copy Path, Reveal in Files) | Right-click menu already exists for Copy Path/Copy File — extend it |
| Drag-and-drop reorder/move | GTK4 DnD on ColumnView is complex; not needed for read-only tree |
| Syntax-minimap preview on hover | Nice-to-have, high effort |
| Multi-select (Shift/Ctrl click) | ColumnView supports it but needs handler work; defer |

---

## 8. Why This Design Works

1. **Leverages existing ColumnView** — We're not rewriting the tree, just adding columns and a sort/filter model wrapper. The GObject row model already supports binding arbitrary properties.

2. **Handler/view separation is clean** — All the "how" (git status parsing, metadata scanning, sort comparators, filter logic) lives in the handler. The view just binds properties and emits callbacks.

3. **Performance by design** — `Gio.ListStore` + `Gtk.SortListModel` + `Gtk.FilterListModel` is GTK4's intended pattern for large lists. Virtualization is automatic. Background thread for scanning keeps UI responsive.

4. **Git status is cached & debounced** — We don't run `git status` on every keystroke. Cache invalidates on explicit user actions (refresh, revert, project switch).

5. **Per-project persistence** — Sort preference saved to `.crabcakes/file_tree_prefs.json` so users don't lose their workflow.

6. **Icons are pure data** — `utils/file_icons.py` returns icon name + CSS class. View applies CSS class. No GTK in utils. Easy to extend.

7. **Search is substring on path** — Matches how developers actually search: "test" finds `test_main.py`, `tests/integration/test_auth.py`, `src/utils/test_helpers.py`.

---

## 9. Dependencies

- No new external dependencies
- Uses existing: `gi.repository.Gtk`, `Gio`, `GObject`, `gitpython`, `os`, `datetime`
- `enchant-2` already installed (for spellcheck, unrelated)

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ColumnView sort/filter model interaction bugs | Medium | High | Write integration tests for sorted+filtered expand/collapse/drawer |
| Git status stale during active agent edits | Medium | Medium | Invalidate cache on drawer revert + explicit refresh button |
| Large directory scan blocks UI | Low | High | Already threaded; add progress spinner in header if >2s |
| Icon CSS classes not applied | Low | Low | Test binding in `_on_bind`; verify with `add_css_class` |
| Sort persistence file corruption | Very Low | Low | JSON parse with try/except, fallback to default |

---

**End of Proposal**

*This proposal follows the format established in `docs/proposals/PROPOSAL_CHAT_INPUT_TOOLBAR.md` and complies with ARCHITECTURE.md §3.16 handler pattern, §3.5 CSS-in-styles.py, and §3.6 window-as-composition-root.*