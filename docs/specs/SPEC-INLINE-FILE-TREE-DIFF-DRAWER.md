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

The current implementation at `file_tree.py:374–408` clears drawers when loading a new project:

```python
# Clear drawer state
for revealer, _, _, _ in self._drawers.values():
    self._drawer_area.remove(revealer)
self._drawers.clear()
self._loaded_drawers.clear()
```

This is correct and unchanged. See `file_tree.py:384–387`.

#### 2.1.3 `_add_drawer_for_file()` — Create Drawer in `_drawer_area`

**Current implementation** (produced by Phases C-F): Creates a `Gtk.Revealer` with tabbed interface (Diff/History tabs via `Gtk.Stack`), action bar with revert + copy buttons, and keyboard handler. The revealer is appended to `self._drawer_area` and the drawer file path is stored in `self._drawers` dict.

This method is **unchanged** by this spec. See the implementation at `file_tree.py:410–560`.

Key invariants:
- `Gtk.Revealer` is child of `_drawer_area` box, NOT a TreeStore row
- `Gtk.TreeStore` remains 3-column: `(display_name, full_path, is_dir)`
- `self._drawers[file_path] = (revealer, display_name, is_open, drawer_box)` is the canonical state map
- `drawer_box` stores references to child widgets as attributes: `_diff_tab`, `_diff_box`, `_history_list`, `_stack`, `_revert_btn`, `_copy_btn`, `_history_selected_sha`, `_diff_text`

#### 2.1.4 `_update_drawer_prefix()` — Update Row Prefix (▶/▼)

See current implementation at `file_tree.py:956–978`. This method recursively walks the TreeStore to find a matching file path and updates the prefix character. No changes needed — the current implementation is correct.

#### 2.1.5 `_load_drawer_diff()` / `_on_drawer_diff_loaded()` — Load Diff Into `diff_box`

**Current signatures** (file_tree.py:580, 597):
```python
def _load_drawer_diff(self, file_path: str, drawer_box: Gtk.Box, project_path: str,
                       checkpoint_sha: str | None = None) -> None:
def _on_drawer_diff_loaded(self, result, subtitle: str,
                            drawer_box: Gtk.Box, file_path: str) -> None:
```

Both populate `drawer_box._diff_box` (inside the tabbed stack), handling: error labels, "no changes" labels, binary file labels, and syntax-highlighted diff hunks via `render_diff_hunks()`. Diff text is stored on `drawer_box._diff_text` for clipboard access. See `file_tree.py:580–634`.

The `_on_drawer_diff_loaded` method handles all UI states explicitly:
- Git error → error label with `result.error`
- Empty diff → "No changes to this file."
- Binary file → "Binary file — not shown"
- Normal diff → syntax-highlighted hunks

#### 2.1.6 History Tab — `_load_history()` / `_on_history_loaded()`

Current implementation at `file_tree.py:603–668`. On first click of the History tab, `_load_history` runs `file_log()` on a background thread, parses `\x1f`-delimited output into `(sha, date, message)` entries, then dispatches to `_on_history_loaded` on the main thread. Placeholder rows use `Gtk.ListBoxRow` with `set_activatable(False)`. Commit rows store `row.sha` for activation. See `file_tree.py:603–668` for full implementation.

#### 2.1.7 History Row Activation → `_load_historical_diff()`

```python
# file_tree.py:673–683 — called from row-activated signal
def _load_historical_diff(self, file_path: str, sha: str, stack: Gtk.Stack) -> None:
    def _do():
        project_path = self._project_path or ""
        result = diff_file_against(project_path, sha, file_path)
        GLib.idle_add(lambda: self._on_historical_diff_loaded(
            result, sha, file_path, stack))
    threading.Thread(target=_do, daemon=True).start()
```

`_on_historical_diff_loaded` (`file_tree.py:683–787`) switches the stack to the "diff" page, clears `diff_box`, renders the diff via `render_diff_hunks()` (handling errors, empty, binary cases), stores `drawer_box._history_selected_sha`, and shows the revert button.

#### 2.1.8 Revert Handling — `_on_drawer_revert_clicked()` / `_on_drawer_revert_confirmed()`

Current implementations at `file_tree.py:752–830`. Shows a `Gtk.MessageDialog` confirmation. On YES, calls `self._project_handler.revert_file_to_sha(self._project_name, file_path, target_sha)`, then switches to Diff tab, resets history tab's `_loaded` flag, and calls `_load_current_diff()` to reload the working-tree diff. See `file_tree.py:752–830` for full implementation.

#### 2.1.9 `_load_current_diff()` — Reload Current Diff After Revert

```python
# file_tree.py:834–881 — called after revert to show updated working-tree diff
def _load_current_diff(self, file_path: str) -> None:
    entry = self._drawers.get(file_path)
    if entry is None:
        return
    _, _, is_open, drawer_box = entry
    if not is_open:
        return
    project_path = self._project_path or ""
    # Clear diff_box
    diff_box = getattr(drawer_box, '_diff_box', None)
    if diff_box is not None:
        while diff_box.get_first_child() is not None:
            diff_box.remove(diff_box.get_first_child())
    # Resolve checkpoint SHA from review state
    checkpoint_sha = None
    if self._project_handler and self._project_name:
        try:
            from models.review_state import ReviewState
            review_state = self._project_handler.get_review_state(self._project_name)
            if review_state and review_state.is_active():
                checkpoint_sha = review_state.checkpoint_sha
        except Exception:
            pass
    self._load_drawer_diff(file_path, drawer_box, project_path, checkpoint_sha)
```

#### 2.1.10 Keyboard Navigation — `_on_drawer_key_pressed()` / `_on_history_key_pressed()`

Current implementations at `file_tree.py:868–933`:

**Unified drawer key handler** (`_on_drawer_key_pressed`, line 913): Handles `Escape` (closes drawer, re-focuses tree) and `Ctrl+C` (copies diff text to clipboard via `_copy_drawer_diff_to_clipboard`). Returns `True` for handled keys, `False` otherwise.

**History list key handler** (`_on_history_key_pressed`, line 878): Handles `Enter`/`KP_Enter` on a selected history row — activates it by emitting `row-activated` signal. Guarded by `row.get_activatable()` to skip placeholder rows.

#### 2.1.11 Copy to Clipboard — `_copy_drawer_diff_to_clipboard()`

```python
# file_tree.py:885–891
def _copy_drawer_diff_to_clipboard(self, drawer_box: Gtk.Box) -> None:
    diff_text = getattr(drawer_box, '_diff_text', None)
    if not diff_text:
        return
    clipboard = Gdk.Display.get_default().get_clipboard()
    clipboard.set(diff_text)
```

Called from both the Ctrl+C key shortcut and the "Copy diff" button click (`_on_copy_diff_to_clipboard`, line 896).

---

### 2.2 `ui/views/diff_card.py` — Reuse `render_diff_hunks()`

**No functional changes needed.** The existing `render_diff_hunks()` function is already used by `FileTree._on_drawer_diff_loaded()` and `_on_historical_diff_loaded()`. Verify it's imported and used correctly.

**Verification:** `FileTree._on_drawer_diff_loaded()` calls `render_diff_hunks(file_diff.hunks, lang)` — **already correct**.

---

### 2.3 `ui/views/diff_viewer.py` — No Changes Needed

The `DiffViewer` widget (used in main content area) is **unaffected**. It remains the full-width diff viewer for the chat/feed context. The inline drawer is a separate UX for the file tree.

---

### 2.4 `ui/handlers/project_handler.py` — `revert_file_to_sha()` Delegation

**Already implemented** at `project_handler.py:865–874`. Signature:

```python
def revert_file_to_sha(self, project_name: str, file_path: str, target_sha: str,
                       on_complete: Callable[[], None] | None = None) -> None:
```

This method delegates to `ReviewHandler.revert_file_to_sha()` (which performs `git checkout <sha> -- <file>` on a background thread). The `on_complete` callback is fired via `GLib.idle_add` after the git checkout succeeds.

**Key difference from the original spec draft:** The method returns `None`, not `GitResult`. Completion notification uses the callback pattern, not a return value, because the git operation runs on a background thread.

**Validation note:** File paths are validated by `ReviewHandler.revert_file_to_sha()` via `git_ops.checkout_paths()` which uses `_VALID_SHA_RE` for the SHA. File paths beginning with `-` could cause argument injection in `git checkout` — this is a known limitation tracked as BUG #12 in the spec audit.

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
| 1 | Double-click file → drawer opens with Diff tab showing current diff | Manual: open project, double-click file, verify drawer appears with syntax-highlighted diff |
| 2 | History tab shows commit list (SHA, date, message) | Click History tab → list populated with commit entries |
| 3 | Click history row → loads that commit's diff in Diff tab | Click row → stack switches to Diff page, shows historical diff |
| 4 | Revert button appears on historical diff, reverts file on confirm | Click Revert → confirmation dialog → YES → file restored, diff reloads to show working tree |
| 5 | Escape closes drawer | Press Esc → drawer closes, focus returns to tree |
| 6 | Ctrl+C copies diff to clipboard | Ctrl+C → paste in text editor shows diff text |
| 7 | Enter on selected history row activates it | Select history row with arrow keys → press Enter → loads diff |
| 8 | Multiple drawers can be open simultaneously | Open file A drawer, then file B drawer → both visible |
| 9 | Drawer scrolls with tree | Scroll tree → drawer moves with its file row |
| 10 | Project switch clears all drawers | Switch projects → no drawers remain open |
| 11 | All existing tests pass | `xvfb-run -a pytest tests/ -x -q` → 0 failures |

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