# New Prompt Creation Card — Formal Proposal

**Date:** 2026-04-25
**Author:** Qaster
**Status:** Proposed — Awaiting Captain JAQx Approval
**Affects:** `ui/views/left_panel.py`, `ui/handlers/prompts_handler.py`, `ui/styles.py`

---

## 1. Objective

Add a "+" card at the top of the Prompts tab list (beneath the search bar) that opens a file picker for importing `.md` files into the prompts library. This establishes visual and functional parity with the Projects tab's "+" creation card.

---

## 2. User Story

1. User opens the Prompts tab in the left sidebar
2. User sees a "+" card at the top of the prompt list, below the search bar
3. User clicks the "+" card
4. A GTK4 `Gtk.FileDialog` opens, filtered to `.md` files only
5. User selects a file and clicks "Open"
6. The file is copied to the `prompts/` directory
7. The prompts list refreshes immediately — no app restart needed
8. The new prompt is visible and usable

---

## 3. Design Decisions

### 3.1 Where does the "+" card live?

**Decision:** `LeftPanel._build_prompts_tab()` — prepend a "+" row to the `Gtk.ListBox` before the prompt rows.

**Rationale:** The prompts tab uses a `Gtk.ListBox` for its rows. A persistent first row styled as a "new prompt" card follows the same pattern as the Projects tab's "+" card. The row is always at index 0 and is never removed by `refresh_prompts()`.

### 3.2 Where does the import logic live?

**Decision:** `PromptsHandler.import_prompt(source_path)` — the handler owns file operations on the prompts directory.

**Rationale:** Section 8.6 (Handler Pattern) requires all logic in handlers. `PromptsHandler` already owns `_get_prompts_dir()` and file scanning. Adding `import_prompt()` here is the natural extension.

### 3.3 What file picker?

**Decision:** `Gtk.FileDialog` (GTK4 async API) with a `Gtk.FileFilter` for `*.md` only.

**Rationale:** ARCHITECTURE.md Section 2 notes `Gtk.FileChooserDialog` → `Gtk.FileDialog` (async) as the GTK4 pattern. No existing usage in the codebase, but the API is standard GTK4.

### 3.4 How does the list refresh?

**Decision:** `LeftPanel.refresh_prompts()` is already called after search and favorite toggles. After `import_prompt()` succeeds, call `refresh_prompts()` to rebuild the list.

The "+" row must be preserved across refreshes. Two approaches:
- **Option A:** `refresh_prompts()` clears all rows and rebuilds, but always prepends the "+" row first.
- **Option B:** Keep the "+" row as a permanent header widget outside the ListBox.

**Decision:** Option A — simpler, matches the existing pattern. `refresh_prompts()` will prepend the "+" row before iterating prompt results.

### 3.5 Visual design

The "+" card matches the Projects tab pattern: a row with a "+" label and "Add Prompt" text, styled with `.new-prompt-row` CSS class (subtle dashed border).

---

## 4. Implementation Plan

### Checkpoint 1: `PromptsHandler.import_prompt(source_path)`

**File:** `ui/handlers/prompts_handler.py`

```python
def import_prompt(self, source_path: str) -> str | None:
    """
    Copy a .md file into the prompts directory.
    Returns the new filepath on success, None on failure.
    Skips if a file with the same name already exists.
    """
    filename = os.path.basename(source_path)
    dest = os.path.join(self._get_prompts_dir(), filename)
    if os.path.exists(dest):
        return None
    import shutil
    shutil.copy2(source_path, dest)
    return dest
```

### Checkpoint 2: "+" row in `LeftPanel._build_prompts_tab()`

**File:** `ui/views/left_panel.py`

After creating the `Gtk.ListBox`, prepend a permanent "+" row styled as a new-prompt card. Wire its click to `_on_new_prompt_clicked()`.

### Checkpoint 3: `_on_new_prompt_clicked()` — file picker

**File:** `ui/views/left_panel.py`

Uses `Gtk.FileDialog` with `Gtk.FileFilter` for `*.md`. On success, calls `prompts_handler.import_prompt()` then `refresh_prompts()`.

```python
def _on_new_prompt_clicked(self, row):
    """Open file picker to import a .md file into the prompts library."""
    if self._prompts_handler is None:
        return

    dialog = Gtk.FileDialog()
    dialog.set_title("Select a prompt file")

    # Filter to .md only
    filter_md = Gtk.FileFilter()
    filter_md.set_name("Markdown files")
    filter_md.add_pattern("*.md")
    filter_list = Gio.ListStore.new(Gtk.FileFilter)
    filter_list.append(filter_md)
    dialog.set_filters(filter_list)

    # Get parent window
    root = self.get_root()
    dialog.open(root, None, self._on_file_selected)

def _on_file_selected(self, dialog, result):
    """Handle file selection from the import dialog."""
    try:
        file = dialog.open_finish(result)
        if file is None:
            return
        source_path = file.get_path()
        new_path = self._prompts_handler.import_prompt(source_path)
        if new_path:
            self.refresh_prompts()
    except GLib.Error:
        pass  # User cancelled
```

### Checkpoint 4: Preserve "+" row in `refresh_prompts()`

**File:** `ui/views/left_panel.py`

Update `refresh_prompts()` to prepend the "+" row after clearing the list.

### Checkpoint 5: CSS for `.new-prompt-row`

**File:** `ui/styles.py`

---

## 5. Files Changed

| File | Change |
|------|--------|
| `ui/handlers/prompts_handler.py` | Add `import_prompt(source_path)` |
| `ui/views/left_panel.py` | Add "+" row, file picker, update `refresh_prompts()` |
| `ui/styles.py` | Add `.new-prompt-row` CSS |

---

## 6. Architecture Compliance

- [x] Handler pattern (Section 8.6) — import logic in `PromptsHandler`
- [x] View owns widgets (Section 8.5) — file picker and "+" row in `LeftPanel`
- [x] GTK4 FileDialog (async) — per Section 2 GTK4 migration notes
- [x] No new modules — all changes in existing files
- [x] No cross-handler imports

---

## 7. ARCHITECTURE.md Updates

| Section | Update |
|---------|--------|
| 3.17 `PromptsHandler` Public API | Add `import_prompt(source_path) -> str | None` |

---

*This proposal covers the minimum viable implementation, establishing feature parity with the Projects tab "+" card.*
