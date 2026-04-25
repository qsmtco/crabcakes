# Project Search — Formal Proposal

**Date:** 2026-04-25
**Author:** Qaster
**Status:** Proposed — Awaiting Captain JAQx Approval
**Affects:** `ui/views/file_tree.py`, `ui/views/left_panel.py`, `ui/handlers/project_list_handler.py`

---

## 1. Objective

Add a search box to the Projects tab in the left sidebar, matching the existing Prompts tab search pattern. This allows filtering the project card grid by name when the user has many projects.

---

## 2. Discovery — Existing Pattern

The Prompts tab search is implemented as:

1. **Handler** (`PromptsHandler`): `search(query)` → sets `_search_query` → returns `_sorted_filtered()`
2. **View** (`LeftPanel`): `Gtk.SearchEntry` in tab header → `search-changed` signal → calls handler → rebuilds list
3. **Layout:** Horizontal header `[Title] [SearchEntry]` above a scrollable content area

The Projects tab currently has no header — `FileTree._show_project_picker()` renders directly into the card box. The header (`_header` box) only has a back button, folder icon, and title label.

---

## 3. Design

### 3.1 Architecture Decision

**Follow the Prompts tab pattern exactly.**

| Component | Prompts Tab | Projects Tab (proposed) |
|-----------|-------------|------------------------|
| Search state | `PromptsHandler._search_query` | `ProjectListHandler._search_query` |
| Filter method | `PromptsHandler.search(query)` | `ProjectListHandler.search(query)` |
| Search widget | `Gtk.SearchEntry` in header | `Gtk.SearchEntry` in `FileTree._header` |
| Signal | `search-changed` | `search-changed` |
| Re-render | `LeftPanel.refresh_prompts()` | `FileTree._show_project_picker()` |

### 3.2 Where does the search entry live?

**Decision:** In `FileTree._header` — visible only in picker mode (not when browsing a project tree).

**Rationale:** The header is already there and switches visibility based on mode. Adding the search entry next to the "Projects" title follows the Prompts tab layout pattern. When a project is opened (tree mode), the search entry hides along with the title.

### 3.3 Where does the filter logic live?

**Decision:** `ProjectListHandler.search(query)` — follows the handler pattern (Section 8.6).

The handler already has `get_projects()` which returns all projects. Adding a `search(query)` method that filters by name and returns a subset is the exact parallel to `PromptsHandler.search()`.

### 3.4 How does the card grid refresh?

**Decision:** `FileTree._show_project_picker()` already re-reads from `ProjectListHandler.get_projects()` each time it's called. The search handler will filter the stored list, and `_show_project_picker()` will be re-called after search changes.

**Issue:** `_show_project_picker()` currently destroys and recreates the entire card box on each call. This is fine for now (small number of projects), but the search will trigger it on every keystroke.

**Optimization:** Instead of calling `_show_project_picker()` (which rebuilds everything including the "+" card), extract the project card rendering into a separate method `_refresh_project_cards()` that only rebuilds the project list portion, preserving the "+" card and search state.

---

## 4. Implementation Plan

### Checkpoint 1: `ProjectListHandler.search(query)`

**File:** `ui/handlers/project_list_handler.py`

```python
def search(self, query: str) -> list[tuple[str, str, str]]:
    """Set search filter and return filtered projects."""
    self._search_query = query.strip().lower()
    return self._filtered_projects()
```

Internal `_filtered_projects()` filters `get_projects()` by name containing `_search_query`.

### Checkpoint 2: `SearchEntry` in `FileTree._header`

**File:** `ui/views/file_tree.py`

Add a `Gtk.SearchEntry` to the existing `_header` box, after the title label. Visible only in picker mode.

### Checkpoint 3: `search-changed` → refresh cards

**File:** `ui/views/file_tree.py`

Wire `search-changed` signal to a handler that calls `project_list_handler.search(query)` then re-renders only the project cards.

### Checkpoint 4: Clear search on project open / back

**File:** `ui/views/file_tree.py`

Clear the search entry when a project is opened (tree mode) or when navigating back. Reset the filter in `ProjectListHandler`.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `ui/handlers/project_list_handler.py` | Add `_search_query`, `search()`, `_filtered_projects()` |
| `ui/views/file_tree.py` | Add `SearchEntry` to header, wire `search-changed`, add `_refresh_project_cards()` |

**No new files. No window.py changes needed** — the callback is internal to FileTree + ProjectListHandler.

---

## 6. Architecture Compliance

- [x] Handler pattern (Section 8.6) — filter logic in `ProjectListHandler`
- [x] View owns widget layout (Section 8.5) — search entry in `FileTree`
- [x] No cross-handler imports — FileTree uses `ProjectListHandler` (injected via `set_project_list_handler`)
- [x] Follows existing pattern — mirrors Prompts tab search exactly
- [x] No new modules

---

## 7. ARCHITECTURE.md Updates

| Section | Update |
|---------|--------|
| 3.20 `ProjectListHandler` Public API | Add `search(query) -> list[tuple]` |

---

*This proposal covers the minimum viable implementation. Small, focused, follows existing patterns exactly.*
