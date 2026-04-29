# Phase 5 Implementation Spec — CrabWatch Filesystem Watcher

## Objective
Implement Phase 5 of CrabCakes per `docs/PROJECT_FEED.md` and `docs/ARCHITECTURE.md`.

---

## What Already Exists

| Component | Status | Location |
|-----------|--------|----------|
| `StreamingBubble` dataclass | ✅ Done | `models/streaming.py` |
| `_make_block_header` helper | ✅ Done | `chat_bubble.py` line 436 |
| Scroll-to-bottom button | ✅ Done | `main_content.py` |
| Solo DM per-project targeting | ✅ Done | `project_handler.py` + `session_menu.py` |
| `FeedHandler.on_filesystem_event()` stub | ✅ Done | `feed_handler.py` line 395 |
| Message grouping (`tight` param) | ✅ Done | `chat_bubble.py` |
| Forward button | ✅ Done | `chat_bubble.py` |

---

## New Components to Implement

### 1. `utils/crabwatch_handler.py` — Filesystem Watcher

**Responsibility:** Use `Gio.FileMonitor` to watch the active project directory for filesystem changes. Create `FeedCardData` cards on file create/modify/delete events and route them to `FeedHandler.on_filesystem_event()`.

**Architecture rules (per PROJECT_FEED.md):**
- Internal handler within CrabCakes — NOT a separate process
- Uses `Gio.FileMonitor` (GTK4 native, no external deps)  
- Integrates with GLib main loop — no threading issues
- No IPC, no sockets, no DBus

**Public API:**
```python
class CrabWatchHandler:
    def __init__(
        self,
        GLib_module,       # GLib reference for dispatch
        on_event: Callable[[FeedCardData], None],  # callback to FeedHandler.on_filesystem_event
    )
    def start_watching(self, project_path: str, project_name: str) -> None:
        """Start monitoring project_path. Stops any previous watch."""
    def stop_watching(self) -> None:
        """Stop monitoring."""
    def is_watching(self) -> bool
```

**Events to watch:**
- `Gio.FileMonitorEvent.CREATED` → `FeedCardData(card_type="file_created", source="crabwatch")`
- `Gio.FileMonitorEvent.CHANGED` → `FeedCardData(card_type="file_modified", source="crabwatch")`  
- `Gio.FileMonitorEvent.DELETED` → `FeedCardData(card_type="file_deleted", source="crabwatch")`
- Directory variants: `dir_created`, `dir_deleted`

**Ignored paths (don't fire events):**
- `.crabcakes/` directory
- `.git/` directory
- `node_modules/`
- `__pycache__/`
- `*.pyc` files
- `.DS_Store`
- Files starting with `.` (dotfiles)

**Card data construction:**
```python
FeedCardData(
    card_type="file_created" | "file_modified" | "file_deleted" | "dir_created" | "dir_deleted",
    source="crabwatch",
    title=f"{verb} {relative_path}",
    body=f"{icon} {relative_path}",
    author="system",
    timestamp=datetime.now(timezone.utc),
    project_name=project_name,
    file_path=relative_path,
)
```

**Debounce:** Fire immediately but batch rapid successive events on the same file (within 200ms) into a single card.

**Wire into window.py:**
- Create `CrabWatchHandler` alongside `FeedHandler`
- On `set_on_project_opened` callback: `crabwatch_handler.start_watching(project_path, project_name)`
- On project close: `crabwatch_handler.stop_watching()`

---

### 2. Add `file_modified` to `models/feed_card.py`

**Change:** Add `"file_modified"` to `CardType` literal union and to `css_class_for_type()` mapping.

---

### 3. Wire into `ui/window.py`

At the window construction, after `FeedHandler` creation:
```python
# CrabWatch (Phase 5 — filesystem watcher for project feed)
from ui.handlers.crabwatch_handler import CrabWatchHandler
self._crabwatch_handler = CrabWatchHandler(
    GLib=GLib,
    on_event=self._feed_handler.on_filesystem_event,
)
```

In `set_on_project_opened` callback chain, add:
```python
self._crabwatch_handler.start_watching(p, n) if n else None,
```

In `set_on_project_tab_close` callback chain, add:
```python
self._crabwatch_handler.stop_watching(),
```

---

## Verification Steps

After implementing each piece:
1. `cd /home/q/projects/crabcakes && python3 -c "import ui.handlers.crabwatch_handler"` — import check
2. `pytest tests/` — run full test suite
3. Manual test: open a project, create/modify/delete a file, verify system card appears in Project Feed

---

## Architecture Compliance

- `models/feed_card.py`: Already in `models/`, pure Python ✅
- `utils/crabwatch_handler.py`: Goes in `utils/` — no GTK widget creation, uses GLib only
- Window wiring in `ui/window.py` follows existing handler pattern
- `on_event` callback pattern matches `FeedHandler.on_filesystem_event` signature