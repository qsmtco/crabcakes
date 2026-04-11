# Prompts Tab Porting Plan — Deadcode → CrabCakes

**Date:** 2026-04-11
**Author:** Qaster
**Status:** Plan only — no code changes made

---

## What We're Porting

The Prompts tab from deadcode's `src/ui/sidebar.py` (`PromptLibraryPanel`) and `src/prompts/library.py` (`PromptLibrary`). This adds:
1. **Star/favorite system** — star prompts you like, they pin to the top
2. **Search box** — filter prompts by name in real-time
3. **Rich rows** — each row shows name + metadata (line count, file size, last used)
4. **Favorites persistence** — saved to `~/.config/crabcakes/favorites.json`

---

## Current State

### Deadcode (source)
- `src/prompts/library.py` — `PromptLibrary` class: favorites management (load/save/toggle), prompt scanning, search filtering, file content loading
- `src/ui/sidebar.py` — `PromptLibraryPanel` class: full prompts tab UI with search, star buttons, metadata rows, sort-by-favorite
- `src/styles.py` — CSS for `.lib-row`, `.lib-fav-star`, `.lib-tag`, `.selected`
- Favorites stored at `~/.config/crabcakes/favorites.json` as `{"favorites": ["/path/to/prompt.md", ...]}`

### CrabCakes (target)
- `utils/prompts.py` — bare-bones `load_prompts()` returning `[(name, content)]`
- `ui/views/left_panel.py` — `_build_prompts_list()`: plain `Gtk.ListBox` with text-only rows, no search, no favorites, no metadata
- No favorites persistence
- No `PromptLibrary` class

---

## Visual Design Being Ported

Each prompt row:
```
┌────────────────────────────────────────────┐
│  ☆  prompt-name                            │
│     142L · 3.2KB · 2h ago                  │
└────────────────────────────────────────────┘
```

**Star button (☆/★):** Left side. Click toggles favorite. Favorited prompts (★) sort to top. Amber color (`#f59e0b`).

**Name label:** Primary text, left-aligned, ellipsized.

**Metadata line:** Smaller muted text below name showing line count, file size, and time since last use. Rendered as a small tag with dark background.

**Search box:** Top-right of the header. Filters rows in real-time by name substring (case-insensitive). Rows that don't match are hidden (not removed).

**Row styling:** Dark background, transparent border. Hover shows indigo tint + border. Selected row gets darker background.

---

## Step-by-Step Plan (Following CrabCakes Architecture)

### Step 1: Create `utils/favorites.py`

**Per architecture:** utilities are stateless or near-stateless file I/O. No GTK imports.

Port the favorites persistence logic from deadcode's `PromptLibrary` into a standalone utility:

```python
# utils/favorites.py

FAVORITES_PATH = os.path.expanduser("~/.config/crabcakes/favorites.json")

def load_favorites() -> set[str]:
    """Load favorite file paths from favorites.json."""

def save_favorites(favorites: set[str]) -> None:
    """Persist favorites set to favorites.json."""

def is_favorite(filepath: str) -> bool:
    """Check if a filepath is in favorites."""

def toggle_favorite(filepath: str) -> bool:
    """Toggle favorite. Returns True if now favorited."""
```

This keeps persistence logic out of UI code and out of models.

### Step 2: Enhance `utils/prompts.py`

Add metadata scanning (currently only returns name + content):

```python
def scan_prompts() -> list[dict]:
    """
    Scan prompts/ directory. Returns list of dicts:
      - name, filepath, content, lines, size
    """
```

Keep existing `load_prompts()` for backward compatibility. The new function is what the prompts tab will use.

### Step 3: Create `ui/handlers/prompts_handler.py`

**Per architecture Section 8.6:** All new UI logic must go in a handler. This is non-negotiable.

The handler owns:
- Loading and scanning prompts from disk
- Favorites state (loaded from `utils/favorites.py`)
- Search filtering logic
- Last-used tracking (in-memory dict: filename → timestamp)

```python
class PromptsHandler:
    def __init__(self, *,
                 on_refresh_ui=None,    # callback to rebuild the prompt rows
                 on_prompt_loaded=None, # callback when user loads a prompt
                 GLib_module=None):
        ...

    def load_prompts(self) -> list[dict]:
        """Scan prompts dir, sort (favorites first, then alpha), return metadata list."""

    def toggle_favorite(self, filepath: str) -> bool:
        """Toggle star. Returns new state."""

    def search(self, query: str) -> list[dict]:
        """Filter prompts by name substring."""

    def record_usage(self, filename: str):
        """Track that a prompt was just used (for 'X ago' display)."""

    def get_last_used(self, filename: str) -> str:
        """Format last-used time as human-readable string."""
```

**Thread safety:** All prompt loading is file I/O (fast, local disk). No background threads needed. But if a future version fetches remote prompts, handler docstring must note `GLib.idle_add()` requirement.

### Step 4: Update `ui/views/left_panel.py`

Replace `_build_prompts_list()` with a richer implementation:

**Header row** (existing but enhanced):
- "Prompts" title label (keep)
- Search `Gtk.Entry` with placeholder "Search prompts…" (new)

**Prompt rows** (replacing plain `Gtk.ListBox`):
- Use `Gtk.Box(VERTICAL)` container with custom rows (not `Gtk.ListBox`)
- Each row is a `Gtk.Box(HORIZONTAL)`: [star_btn] [text_box]
  - `star_btn`: `Gtk.Button` with ☆/★ label, flat, 24×24
  - `text_box`: `Gtk.Box(VERTICAL)` with name label + metadata label
- Connect star button to `PromptsHandler.toggle_favorite()`
- Connect double-click to load prompt (call handler, which calls `on_prompt_loaded` callback)
- Single-click highlights row (adds `.selected` CSS class)

**Wiring in `window.py`:**
```python
# In _build():
self._prompts_handler = PromptsHandler(
    on_refresh_ui=self._left_panel.refresh_prompts,
    on_prompt_loaded=self._on_prompt_loaded,
    GLib_module=GLib,
)
self._left_panel.set_prompts_handler(self._prompts_handler)
```

### Step 5: Add CSS

Port from deadcode's `styles.py`:
- `.lib-row` — transparent background, hover effect, transition
- `.lib-row:hover` — indigo tint + border
- `.lib-row.selected` — darker background
- `.lib-fav-star` — amber color (`#f59e0b`)
- `.lib-tag` — dark background, muted text, small font, rounded

### Step 6: Update `ARCHITECTURE.md`

- Add `utils/favorites.py` to Section 11 file inventory
- Add `ui/handlers/prompts_handler.py` to Section 3 and Section 11
- Document `PromptsHandler` public API in Section 3
- Update `ui/views/left_panel.py` description to note search + favorites integration

### Step 7: Tests

**`tests/test_favorites.py`** (new):
- Load favorites from non-existent file → empty set
- Save and reload → round-trip
- Toggle favorite → correct state change
- Corrupted JSON → graceful fallback to empty set

**`tests/test_prompts_handler.py`** (new):
- Search filtering with query → correct subset
- Search with empty query → all prompts
- Toggle favorite → sorts to top on next `load_prompts()`
- Record usage → get_last_used returns formatted string

### Step 8: Commit & Push

```
git add -A
git commit -m "feat: prompts tab with favorites, search, and metadata rows"
git push
```

---

## Files Changed

| File | Action |
|------|--------|
| `utils/favorites.py` | NEW — favorites persistence (load/save/toggle) |
| `utils/prompts.py` | MODIFY — add `scan_prompts()` with metadata |
| `ui/handlers/prompts_handler.py` | NEW — prompts logic handler (Section 8.6 compliance) |
| `ui/views/left_panel.py` | MODIFY — search box, star buttons, metadata rows |
| `ui/window.py` | MODIFY — wire PromptsHandler |
| `ARCHITECTURE.md` | MODIFY — document new files and handler |
| `tests/test_favorites.py` | NEW — favorites persistence tests |
| `tests/test_prompts_handler.py` | NEW — handler logic tests |

---

## Architecture Compliance Notes

**Why `ui/handlers/prompts_handler.py` and not inline in `left_panel.py`:**
Section 8.6 mandates all new UI logic goes in handlers. The prompts handler owns state (favorites, search query, last-used timestamps) and logic (filtering, sorting, persistence). The view (`left_panel.py`) only renders what the handler tells it to.

**Why `utils/favorites.py` and not in the handler:**
Favorites persistence is pure file I/O. Per architecture, utilities handle file operations. The handler calls the utility; it doesn't do its own JSON serialization.

**Why not `models/`:**
Favorites state could go in a model, but it's tightly coupled to the prompts handler's workflow. The handler manages the state in-memory and delegates persistence to `utils/favorites.py`. A separate model would be over-engineering for a single `set[str]`.

**No handler-to-handler imports:**
`PromptsHandler` does NOT import `ChatHandler`. When a prompt is loaded, it calls the `on_prompt_loaded` callback, which `window.py` wires to whatever it wants (typically injecting text into the chat input).

---

## Differences from Deadcode

1. **Deadcode bundles `PromptLibrary` as both model and manager.** CrabCakes splits this: `utils/favorites.py` (persistence), `utils/prompts.py` (scanning), `ui/handlers/prompts_handler.py` (logic/state).
2. **Deadcode uses `load_config()` for paths.** CrabCakes uses env vars / hardcoded defaults. Already compatible.
3. **Deadcode installs bundled prompts on first run.** Skip this for now — CrabCakes already has prompts in its repo.
4. **Deadcode uses `_last_used` dict in the panel.** CrabCakes moves this to the handler (where state belongs per Section 8.6).
