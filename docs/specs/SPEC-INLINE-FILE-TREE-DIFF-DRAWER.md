# SPEC: Inline File Tree Diff Drawer

**Date:** 2025-07-12
**Author:** Supervisor (Qaster)
**Status:** Draft — for implementation
**Implements:** Follow-up to SPEC-ONE-CLICK-DIFF.md
**Depends on:** SPEC-ONE-CLICK-DIFF.md (phases A-E implemented)
**Target branch:** main

> **Architecture compliance:** This spec modifies `ui/views/file_tree.py` (view) and `ui/handlers/project_handler.py` (handler). Per ARCHITECTURE.md §3.6, views contain no business logic; handlers own git operations. CSS lives only in `ui/styles.py`.

---

## 1. Overview

### Problem Statement

The inline file tree diff drawer has been implemented across Phases C–F and includes: tabbed Diff/History interface, commit history loading, historical diff viewing, file revert, keyboard shortcuts (Escape, Ctrl+C, Enter), clipboard copy, and loading spinners.

This spec documents the final architecture and serves as the reference for any future maintenance or extension.

### Solution (Implemented)

The diff drawer lives in a `Gtk.Revealer` appended to `_drawer_area` below the tree view, inside the same `Gtk.ScrolledWindow`. This ensures drawers scroll naturally with the tree. The `Gtk.TreeView` cell-renderer architecture is preserved (no widget-in-row embedding, which GTK 4 does not support).

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Convert drawer from `_drawer_area` child to inline TreeStore row | Breadcrumb navigation (separate proposal) |
| Drawer content: Diff tab + History tab + Revert button | Cross-file revert (multi-file revert) |
| Inline reveal/hide animation via `Gtk.Revealer` | Syntax highlighting changes (separate) |
| History tab with commit list + revert button | Git blame integration |
| Keyboard navigation (Esc, Ctrl+C, Enter) | Git blame inline annotations |
| Copy diff to clipboard (button + Ctrl+C) | Three-way merge UI |
| Escape closes drawer, Ctrl+C copies diff | Multi-repo support |

### Architecture Principles (per ARCHITECTURE.md)

- **View layer** (`ui/views/file_tree.py`): Pure GTK widgets, callbacks only. No git calls.
- **Handler layer** (`ui/handlers/project_handler.py`): Owns git operations, called via callbacks.
- **Utils** (`utils/git_ops.py`, `utils/diff_parser.py`): Pure functions, no GTK.
- **CSS**: All new classes in `ui/styles.py` only.
- **Threading**: Background threads for git ops; `GLib.idle_add` for UI updates.

---

## 2. Changes by File

### 2.1 `ui/views/file_tree.py` — Core Changes

#### 2.1.1 Drawer Area Architecture (Unchanged)

`Gtk.TreeView` in GTK 4 uses cell renderers — arbitrary widgets (`Gtk.Revealer`) cannot be embedded in rows. Drawers are attached to a `_drawer_area` box placed below the tree view inside the same `Gtk.ScrolledWindow` (`file_tree.py:120-122`). This means drawers ALREADY scroll in sync with tree rows — no inline-row approach is needed or possible.

**Current schema** (unchanged): `Gtk.TreeStore.new([str, str, bool])` → (display_name, full_path, is_dir)  
No columns are added. All drawer state lives in the `self._drawers: dict[str, tuple[Gtk.Revealer, str, bool, Gtk.Box]]` map, keyed by file path.

**Layout:**
```
Gtk.ScrolledWindow
└── Gtk.Box (vertical)              ← _tree_and_drawers
    ├── Gtk.TreeView                ← self._tree
    │   └── rows (cell renderers)
    │       ├── dir/
    │       ├── file_a.py           ← double-click opens drawer
    │       └── file_b.py
    └── Gtk.Box (vertical)          ← _drawer_area
        ├── Gtk.Revealer            ← drawer for file_a.py
        │   └── drawer_box          ← tabs + stack + action bar
        └── Gtk.Revealer            ← drawer for file_b.py
            └── drawer_box
```

#### 2.1.2 `_show_tree()` — Clear Drawer State on Project Load

```python
def _show_tree(self, name, path):
    # ... existing code ...
    self._store.clear()
    # Clear ALL drawer state on project load
    for revealer, _, _, _ in self._drawers.values():
        self._drawer_area.remove(revealer)  # Will be removed with TreeStore clear
    self._drawers.clear()
    self._loaded_drawers.clear()
    # ... rest unchanged
```

#### 2.1.3 `_add_drawer_for_file()` — Create Drawer in `_drawer_area`

**Current implementation** (produced by Phases C-F): Creates a `Gtk.Revealer` with tabbed interface (Diff/History tabs via `Gtk.Stack`), action bar with revert + copy buttons, and keyboard handler. The revealer is appended to `self._drawer_area` and the drawer file path is stored in `self._drawers` dict.

This method is **unchanged** by this spec. See the implementation at `file_tree.py:410–560`.

Key invariants:
- `Gtk.Revealer` is child of `_drawer_area` box, NOT a TreeStore row
- `Gtk.TreeStore` remains 3-column: `(display_name, full_path, is_dir)`
- `self._drawers[file_path] = (revealer, display_name, is_open, drawer_box)` is the canonical state map
- `drawer_box` stores references to child widgets as attributes: `_diff_tab`, `_diff_box`, `_history_list`, `_stack`, `_revert_btn`, `_copy_btn`, `_history_selected_sha`, `_diff_text`

#### 2.1.4 `_update_drawer_prefix()` — Update Row Prefix (▶/▼)

```python
def _update_drawer_prefix(self, model, it, file_path: str, is_open: bool) -> bool:
    """Update the prefix (▶/▼) on the file row."""
    while it is not None:
        if not model.get_value(it, 2) and model.get_value(it, 1) == file_path:
            current = model.get_value(it, 0)
            # Strip existing prefix
            for prefix in ("  ", "▶ ", "▼ "):
                if current.startswith(prefix):
                    current = current[len(prefix):]
                    break
            new_prefix = "▼ " if is_open else "▶ "
            model.set_value(it, 0, new_prefix + current[len("▶ "):] if current.startswith(("▶ ", "▼ ")) else new_prefix + current)
            return True
        # Recurse into children
        child = model.iter_children(it)
        if child and self._update_drawer_prefix(model, child, file_path, is_open):
            return True
        it = model.iter_next(it)
    return False
```

#### 2.1.5 `_load_drawer_diff()` / `_on_drawer_diff_loaded()` — Update `diff_box` In-Place

```python
def _load_drawer_diff(self, file_path: str, project_path: str, checkpoint_sha: str | None = None) -> None:
    """Load current diff for a file into the drawer box on background thread."""
    def _do():
        if checkpoint_sha:
            result = diff_file_against_working_tree(project_path, checkpoint_sha, file_path)
            subtitle = f"since checkpoint {checkpoint_sha[:7]}"
        else:
            result = diff_working_tree(project_path, file_path)
            subtitle = "since HEAD"
        GLib.idle_add(lambda: self._on_drawer_diff_loaded(
            result, subtitle, file_path
        ))
    threading.Thread(target=_do, daemon=True).start()

def _on_drawer_diff_loaded(self, result, subtitle: str, file_path: str) -> None:
    if file_path not in self._drawers:
        return
    _, _, _, drawer_box = self._drawers[file_path]
    diff_box = getattr(drawer_box, '_diff_box', None)
    if diff_box is None:
        return

    # Update subtitle in drawer header (if we add one)
    # Clear and populate diff_box
    while diff_box.get_first_child() is not None:
        diff_box.remove(diff_box.get_first_child())

    if not result.success:
        # ... error handling ...
        return

    if not result.stdout.strip():
        # ... no changes label ...
        return

    parsed = parse_diff(result.stdout)
    if not parsed.files:
        return

    file_diff = parsed.files[0]
    if file_diff.is_binary:
        # ... binary label ...
        return

    lang = get_lang_from_path(file_diff.display_path)
    diff_box.append(render_diff_hunks(file_diff.hunks, lang))
    drawer_box._diff_text = result.stdout  # for clipboard
```

#### 2.1.6 History Tab — `_load_history()` / `_on_history_loaded()`

```python
def _load_history(self, file_path: str, history_list: Gtk.ListBox) -> None:
    if getattr(history_list, '_loaded', False):
        return
    history_list._loaded = True

    def _do():
        project_path = self._project_path or ""
        result = file_log(self._project_path or "", file_path, count=20)
        entries = []
        if result.success and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split("\x1f")
                if len(parts) == 3:
                    entries.append({"sha": parts[0], "date": parts[1], "message": parts[2]})
        GLib.idle_add(lambda: self._on_history_loaded(entries, history_list, file_path))

    threading.Thread(target=_do, daemon=True).start()
```

#### 2.1.7 History Row Activation → `_load_historical_diff()`

```python
def _on_history_row_activated(self, listbox, row):
    if not hasattr(row, 'sha'):
        return
    self._load_historical_diff(file_path, row.sha, stack)

def _load_historical_diff(self, file_path: str, sha: str, stack: Gtk.Stack):
    def _do():
        project_path = self._project_path or ""
        result = diff_file_against(self._project_path or "", sha, file_path)
        GLib.idle_add(lambda: self._on_historical_diff_loaded(result, sha, file_path, stack))
    threading.Thread(target=_do, daemon=True).start()
```

#### 2.1.8 Revert Handling — `_on_drawer_revert_clicked()` / `_on_drawer_revert_confirmed()`

```python
def _on_drawer_revert_clicked(self, file_path: str, drawer_box: Gtk.Box):
    target_sha = getattr(drawer_box, '_history_selected_sha', None)
    if not target_sha or not self._project_handler or not self._project_name:
        return
    # ... show confirmation dialog ...
    # On confirm: call self._project_handler.revert_file_to_sha(...)
    # then self._load_current_diff(file_path)
```

#### 2.1.7 `_load_current_diff()` — Reload Current Diff After Revert

```python
def _load_current_diff(self, file_path: str) -> None:
    entry = self._drawers.get(file_path)
    if not entry:
        return
    _, _, is_open, drawer_box = entry
    if not is_open:
        return
    # ... same as _load_drawer_diff but uses current working tree vs checkpoint
```

#### 2.1.8 Keyboard Navigation — `_on_drawer_key_pressed()`

```python
def _on_drawer_key_pressed(self, keyval, keycode, state, file_path, drawer_box):
    if keyval == Gdk.KEY_Escape:
        self._toggle_drawer(file_path)
        self._tree.grab_focus()
        return True
    if (keyval in (Gdk.KEY_c, Gdk.KEY_C)) and (state & Gdk.ModifierType.CONTROL_MASK):
        self._copy_drawer_diff_to_clipboard(drawer_box)
        return True
    return False
```

#### 2.1.9 Copy to Clipboard

```python
def _copy_drawer_diff_to_clipboard(self, drawer_box):
    diff_text = getattr(drawer_box, '_diff_text', '')
    if not diff_text:
        return
    clipboard = Gdk.Display.get_default().get_clipboard()
    clipboard.set(diff_text)
```

#### 2.1.9 Escape Key Handler — `_on_drawer_key_pressed()`

```python
def _on_drawer_key_pressed(self, keyval, keycode, state, file_path, drawer_box):
    if keyval == Gdk.KEY_Escape:
        self._toggle_drawer(file_path)
        self._tree.grab_focus()
        return True
    if (keyval in (Gdk.KEY_c, Gdk.KEY_C)) and (state & Gdk.ModifierType.CONTROL_MASK):
        self._copy_drawer_diff_to_clipboard(drawer_box)
        return True
    return False
```

---

### 2.2 `ui/views/diff_card.py` — Reuse `render_diff_hunks()`

**No functional changes needed.** The existing `render_diff_hunks()` function is already used by `FileTree._on_drawer_diff_loaded()` and `_on_historical_diff_loaded()`. Verify it's imported and used correctly.

**Verification:** `FileTree._on_drawer_diff_loaded()` calls `render_diff_hunks(file_diff.hunks, lang)` — **already correct**.

---

### 2.3 `ui/views/diff_viewer.py` — No Changes Needed

The `DiffViewer` widget (used in main content area) is **unaffected**. It remains the full-width diff viewer for the chat/feed context. The inline drawer is a separate UX for the file tree.

---

### 2.4 `ui/handlers/project_handler.py` — Add `revert_file_to_sha()`

```python
def revert_file_to_sha(self, project_name: str, file_path: str, target_sha: str) -> GitResult:
    """
    Revert a single file to its state at a specific commit.
    Equivalent to: git checkout <sha> -- <file_path>
    """
    project_path = self.get_project_path(project_name)
    if not project_path:
        return GitResult(success=False, stdout="", error="Project not found")

    try:
        repo = gitpython.Repo(project_path)
        # git checkout <sha> -- <file_path>
        repo.git.checkout(target_sha, "--", file_path)
        return GitResult(success=True, stdout=f"Reverted {file_path} to {sha[:7]}", error="")
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e))
```

**Also add `revert_file_to_sha` to `ProjectHandler` public API** and wire in `window.py` when constructing `FileTree`:

```python
# In window.py _build() after creating FileTree:
left_panel._file_tree.set_project_handler(self._project_handler)
```

---

### 2.5 `ui/styles.py` — New CSS Classes

```css
/* ── File Tree Inline Drawer ──────────────────────────────────────── */
.file-tree-drawer {
    padding: 0;
    margin-left: 24px;
    border-left: 2px solid alpha(@theme_selected_bg_color, 0.3);
    background-color: alpha(@theme_bg_color, 0.3);
}

.file-tree-drawer-tab-bar {
    padding: 4px 8px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.1);
}

.file-tree-drawer-tab-bar > togglebutton {
    padding: 2px 12px;
    border-radius: 4px 4px 0 0;
    margin-right: 4px;
}

.file-tree-drawer-tab-bar > togglebutton:checked {
    background: alpha(@theme_selected_bg_color, 0.3);
    color: @theme_selected_fg_color;
}

.diff-history-row {
    padding: 4px 12px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.06);
}

.diff-history-row:hover {
    background: alpha(@theme_selected_bg_color, 0.1);
}

.diff-history-row-sha {
    font-family: monospace;
    font-size: 0.85em;
    color: #06b6d4;
    min-width: 6em;
}

.diff-history-row-date {
    font-size: 0.85em;
    color: alpha(@theme_fg_color, 0.5);
    min-width: 8em;
}

.diff-history-row-msg {
    font-size: 0.9em;
}

.file-tree-drawer-tab-bar {
    padding: 4px 8px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
    background: alpha(@theme_bg_color, 0.05);
}

.file-tree-drawer-action-bar {
    padding: 6px 12px;
    border-top: 1px solid alpha(@theme_fg_color, 0.08);
    background: rgba(0, 0, 0, 0.03);
}

.diff-viewer-revert-btn {
    background: rgba(244, 63, 94, 0.2);
    color: #f43f5e;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 0.9em;
}

.diff-viewer-revert-btn:hover {
    background: rgba(244, 63, 94, 0.3);
}

.diff-viewer-copy-btn {
    background: rgba(6, 182, 212, 0.2);
    color: #06b6d4;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 0.9em;
}

.diff-viewer-copy-btn:hover {
    background: rgba(6, 182, 212, 0.3);
}
```

---

## 3. Data Flow

```
User double-clicks file row
    │
    ▼
FileTree._on_row_activated() → _toggle_drawer(file_path)
    │
    ├─► revealer.set_reveal_child(True)
    ├─► Update row prefix (▶ → ▼)
    ├─► If first open: _loaded_drawers.add(file_path)
    │
    ▼
_load_drawer_diff() ──────────────────────────────────────┐
    │                                                     │
    ▼                                                     │
git_ops.diff_file_against_working_tree()                  │
    │                                                     │
    ▼                                                     │
parse_diff() ─────────────────────────────────────────────┤
    │                                                     │
    ▼                                                     │
GLib.idle_add(_on_drawer_diff_loaded) ◄───────────────────┘
    │
    ▼
_on_drawer_diff_loaded():
    1. Clear diff_box children
    2. Parse diff → render_diff_hunks() → append to diff_box
    2. Store diff text in drawer_box._diff_text for clipboard
```

**History tab flow:**
```
History tab clicked → _load_history() → file_log() → _on_history_loaded()
    │
    ▼
User clicks history row → _on_history_row_activated() → _load_historical_diff()
    │
    ▼
diff_file_against() → parse_diff() → render_diff_hunks() → diff_box.append()
    │
    ▼
Show revert button, store sha in drawer_box._history_selected_sha
```

**Revert flow:**
```
Click "Revert" → confirmation dialog → YES
    │
    ▼
ProjectHandler.revert_file_to_sha(project_name, file_path, target_sha)
    │
    ▼
ReviewHandler.revert_file_to_sha() → git checkout <sha> -- <file>
    │
    ▼
_on_revert_confirmed() → _load_current_diff(file_path)  # reload current diff
```

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `ui/views/file_tree.py` | Major rewrite | +300/-150 | High |
| `ui/handlers/project_handler.py` | Add `revert_file_to_sha()` | +25 | Medium |
| `ui/views/file_tree.py` | Add inline drawer logic | +200 | High |
| `ui/styles.py` | Add CSS classes | +60 | Low |
| `ui/window.py` | Wire `set_project_handler` | 1 line | Low |

---

## 5. Implementation Order

| Step | Description | Verification |
|------|-------------|--------------|
| 1 | Add TreeStore column 3/4 (`is_drawer_row`, `drawer_revealer`) | `grep -n "TreeStore.new" ui/views/file_tree.py` |
| 2 | Modify `_show_tree()` to clear drawers on project load | `grep -n "_show_tree" ui/views/file_tree.py` |
| 3 | Rewrite `_add_drawer_for_file()` to insert child row in TreeStore | `grep -n "_add_drawer_for_file" ui/views/file_tree.py` |
| 4 | Implement `_toggle_drawer()` with lazy load | `grep -n "_toggle_drawer" ui/views/file_tree.py` |
| 5 | Implement `_update_drawer_prefix()` | `grep -n "_update_drawer_prefix"` |
| 6 | Implement `_load_drawer_diff()` / `_on_drawer_diff_loaded()` | `grep -n "_load_drawer_diff" ui/views/file_tree.py` |
| 7 | Implement history tab (`_load_history`, `_on_history_loaded`) | `grep -n "_load_history" ui/views/file_tree.py` |
| 8 | Implement historical diff (`_load_historical_diff`, `_on_historical_diff_loaded`) | `grep -n "_load_historical_diff"` |
| 8 | Implement revert flow (`_on_drawer_revert_clicked`, `_on_drawer_revert_confirmed`, `_load_current_diff`) | `grep -n "_on_drawer_revert" ui/views/file_tree.py` |
| 9 | Add keyboard handlers (`_on_drawer_key_pressed`, `_on_history_key_pressed`) | `grep -n "_on_drawer_key_pressed\|_on_history_key_pressed"` |
| 9 | Implement clipboard copy (`_copy_drawer_diff_to_clipboard`) | `grep -n "_copy_drawer_diff_to_clipboard"` |
| 10 | Add `revert_file_to_sha()` to `ProjectHandler` | `grep -n "class ProjectHandler" ui/handlers/project_handler.py` |
| 11 | Wire `set_project_handler()` in `window.py` | `grep -n "set_project_handler" ui/window.py` |
| 11 | Add CSS classes to `ui/styles.py` | `grep -n "file-tree-drawer" ui/styles.py` |
| 12 | Run full test suite | `xvfb-run -a pytest tests/ -x -q` |

---

## 6. Acceptance Criteria

| # | Criterion | Test Method |
|---|-----------|-------------|
| 1 | Double-click file → drawer opens inline below row | Manual: open project, double-click file, verify drawer appears below row |
| 2 | Drawer shows Diff tab with syntax-highlighted diff | Visual: syntax colors present |
| 3 | History tab shows commit list (SHA, date, message) | Click History tab → list populated |
| 4 | Click history row → loads that commit's diff | Click row → diff updates |
| 5 | Revert button appears on historical diff, reverts file | Click Revert → confirm → file restored, diff reloads |
| 4 | Escape closes drawer | Press Esc → drawer closes, focus returns to tree |
| 5 | Ctrl+C copies diff to clipboard | Ctrl+C → paste in editor shows diff text |
| 6 | Enter on history row activates it | Press Enter on row → loads diff |
| 6 | Escape closes drawer | Press Esc → drawer closes |
| 7 | Multiple drawers can be open simultaneously | Open file A, then file B → both open |
| 8 | Drawer scrolls with tree | Scroll tree → drawer moves with its file row |
| 9 | Project switch clears all drawers | Switch projects → no drawers remain open |
| 10 | All existing tests pass | `xvfb-run -a pytest tests/ -x -q` → 0 failures |

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Binary file diff | Show "Binary file — not shown" label |
| No changes | Show "No changes to this file." |
| Git error (permission, corrupt repo) | Show error label in diff area |
| Empty history (new file) | Show "No commit history for this file." |
| Revert during active edit | Revert succeeds, diff reloads to show no changes |
| Rapid toggle (debounce) | Second click within 300ms ignored |
| Project switch with open drawers | All drawers closed, state cleared |
| File deleted externally | Drawer shows "File not found" or closes |
| Revert to commit where file didn't exist | Show "File did not exist at this commit" |

---

## 8. ARCHITECTURE.md Updates Required

| Section | Update |
|---------|--------|
| §3.8 `ui/views/file_tree.py` | Document inline drawer architecture, TreeStore column layout |
| §3.9 `ui/handlers/project_handler.py` | Add `revert_file_to_sha()` to public API |
| §5 CSS | Document new `.file-tree-drawer*`, `.diff-history-row*` classes |
| §8.6 Handler Pattern | Note `ProjectHandler.revert_file_to_sha()` delegates to `ReviewHandler` |

---

## 9. Implementation Notes for Coder

### Critical Implementation Details

1. **TreeStore column order matters** — new columns at index 3 (`is_drawer_row`), 4 (`drawer_revealer`). Update ALL `append()` calls.

2. **Row iteration in `_update_drawer_prefix()`** must use `model.iter_children()` + `model.iter_next()` correctly. Test with nested directories.

3. **Thread safety**: All git operations in `threading.Thread(daemon=True)`. UI updates **only** via `GLib.idle_add()`.

4. **Memory management**: When clearing drawers (`navigate_back()`, `_show_tree()`), call `revealer.unparent()` or `drawer_area.remove(revealer)` before clearing dicts.

5. **Debounce** is per-file (`_last_toggle_per_file` dict), not global.

6. **History list `_loaded` flag** prevents duplicate loads on tab re-click.

---

## 10. Verification Checklist (Rule 10)

Before declaring complete:

- [ ] `xvfb-run -a pytest tests/ -x -q` → 0 failures
- [ ] `grep -rn "FileDiff" ui/views/diff_card.py` → only in type annotations
- [ ] `grep -rn "_drawer_area" ui/views/file_tree.py` → 0 matches (removed)
- [ ] `grep -rn "_drawer_area" ui/views/` → 0 matches
- [ ] `grep -rn "_loaded_drawers" ui/views/file_tree.py` → used correctly
- [ ] `xvfb-run -a pytest tests/test_file_tree.py -x -q` (if exists, else create)
- [ ] Manual test: open project, double-click file → drawer opens inline
- [ ] Manual test: History tab loads commits, click row → diff loads
- [ ] Manual test: Revert works, diff reloads
- [ ] Manual test: Escape closes, Ctrl+C copies, Enter activates history row

---

**Spec file location:** `docs/specs/SPEC-INLINE-FILE-TREE-DIFF-DRAWER.md`