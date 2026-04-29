# ui/handlers/crabwatch_handler.py
# CrabWatch — Gio.FileMonitor-based filesystem watcher for project feed.
#
# Architecture: ui/handlers/ package. Uses Gio (GTK-adjacent) for file monitoring.
# Integrates with GLib main loop — no threading, no IPC, no external deps.
#
# Design (per docs/PROJECT_FEED.md and docs/PHASE5_SPEC.md):
#   - CrabWatch is NOT a separate process — internal handler within CrabCakes
#   - Uses Gio.FileMonitor (GTK4 native, no external dependencies)
#   - Monitors active project directory for file create/modify/delete events
#   - On event → constructs FeedCardData(source="crabwatch") → calls on_event callback
#
# Public API:
#   class CrabWatchHandler:
#       def __init__(self, GLib_module, on_event: Callable[[FeedCardData], None])
#       def start_watching(self, project_path: str, project_name: str) -> None
#       def stop_watching(self) -> None
#       def is_watching(self) -> bool

from __future__ import annotations

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

from datetime import datetime, timezone
from typing import Callable

from models.feed_card import FeedCardData


# Paths/dirs to ignore — never fire events for these
IGNORED_PREFIXES: tuple[str, ...] = (
    ".crabcakes/",
    ".git/",
    "node_modules/",
    "__pycache__/",
)

IGNORED_BASENAMES: tuple[str, ...] = (
    ".DS_Store",
)


def _should_ignore(relative_path: str) -> bool:
    """Return True if this path should be ignored from filesystem watch events."""
    # Check for ignored directory prefixes
    for prefix in IGNORED_PREFIXES:
        if relative_path.startswith(prefix):
            return True
    # Check for ignored basenames
    basename = relative_path.split("/")[-1]
    if basename in IGNORED_BASENAMES:
        return True
    # Ignore dotfiles (files starting with '.')
    if basename.startswith(".") and "/" not in relative_path:
        return True
    # Ignore .pyc files
    if relative_path.endswith(".pyc"):
        return True
    return False


def _get_relative_path(monitor_path: str, event_path: str) -> str:
    """Compute relative path from monitored directory to event path."""
    mp = monitor_path.rstrip("/") + "/"
    if event_path.startswith(mp):
        return event_path[len(mp):]
    return event_path


class CrabWatchHandler:
    """
    Filesystem watcher for project file change events.

    Uses Gio.FileMonitor to watch the active project directory.
    Fires FeedCardData events via on_event callback.

    Lifecycle:
      start_watching() → monitors directory
      stop_watching()  → releases monitor
      start_watching() again → replaces previous watch

    Thread safety: all GTK/GLib calls dispatched via GLib.idle_add when GLib is set.
    If GLib is None (tests), calls are made directly — only safe when caller
    is already on the main thread.
    """

    def __init__(self, GLib_module: object, on_event: Callable[[FeedCardData], None]):
        """
        Args:
            GLib_module: gi.repository.GLib — for thread-safe dispatch. None in tests.
            on_event: callback(FeedCardData) — called for each filesystem event.
        """
        self._GLib = GLib_module
        self._on_event = on_event

        # Monitor state — one monitor per watched directory (recursive)
        self._monitors: dict[str, Gio.FileMonitor] = {}  # abs_path → monitor
        self._watched_path: str | None = None
        self._watched_name: str | None = None

        # Debounce: batch rapid successive events on the same file within 200ms
        self._debounce_map: dict[str, GLib.Source | None] = {}  # path → timeout source
        self._pending_events: dict[str, dict] = {}  # path → event fields
        self._debounce_ms = 200

    def _dispatch(self, fn, *args):
        """Dispatch a callable to the main thread via GLib.idle_add."""
        if self._GLib is not None:
            self._GLib.idle_add(fn, *args)
        else:
            fn(*args)

    def _emit_event(self, event_type: str, relative_path: str):
        """Fire a filesystem event as a FeedCardData via the on_event callback."""
        icons = {
            "file_created": "📄",
            "file_modified": "✏️",
            "file_deleted": "🗑️",
            "dir_created": "📁",
            "dir_deleted": "📁",
        }
        verbs = {
            "file_created": "Created",
            "file_modified": "Modified",
            "file_deleted": "Deleted",
            "dir_created": "Created dir",
            "dir_deleted": "Deleted dir",
        }
        icon = icons.get(event_type, "📄")
        verb = verbs.get(event_type, "Changed")

        card = FeedCardData(
            card_type=event_type,
            source="crabwatch",
            title=f"{verb} {relative_path}",
            body=f"{icon} {relative_path}",
            author="system",
            timestamp=datetime.now(timezone.utc),
            project_name=self._watched_name or "",
            file_path=relative_path,
        )
        self._dispatch(self._on_event, card)

    def _schedule_debounced(self, relative_path: str, event_type: str):
        """
        Schedule a debounced event for relative_path.

        If a pending event for this path is already scheduled, update it.
        Otherwise schedule a new one to fire after _debounce_ms.
        """
        # Cancel existing scheduled event for this path
        existing = self._debounce_map.get(relative_path)
        if existing is not None:
            existing.destroy()
            del self._debounce_map[relative_path]

        # Store pending event data
        self._pending_events[relative_path] = {
            "event_type": event_type,
        }

        # Schedule new timeout
        def _fire():
            event_data = self._pending_events.pop(relative_path, None)
            if event_data is not None:
                self._emit_event(event_data["event_type"], relative_path)
            self._debounce_map.pop(relative_path, None)

        source = self._GLib.timeout_add(
            self._debounce_ms,
            _fire,
        )
        self._debounce_map[relative_path] = source

    def _on_monitor_event(
        self,
        monitor: Gio.FileMonitor,
        file: Gio.File,
        other_file: Gio.File | None,
        event_type: Gio.FileMonitorEvent,
    ):
        """
        Called by Gio.FileMonitor when a filesystem event occurs.

        Runs on the GLib main loop (not a separate thread).
        Dispatches debounced events to the on_event callback.
        """
        if self._watched_path is None:
            return

        event_path = file.get_path() or ""
        if not event_path:
            return

        relative_path = _get_relative_path(self._watched_path, event_path)
        if _should_ignore(relative_path):
            return

        # Determine card type and scheduling strategy
        if event_type == Gio.FileMonitorEvent.CREATED:
            is_dir = file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY
            event_type_str = "dir_created" if is_dir else "file_created"
            # Recursively watch new subdirectories
            if is_dir:
                self._add_monitor_recursive(event_path)
        elif event_type == Gio.FileMonitorEvent.CHANGED:
            event_type_str = "file_modified"
        elif event_type == Gio.FileMonitorEvent.DELETED:
            # Remove monitor for deleted directory if we had one
            abs_path = event_path
            if abs_path in self._monitors:
                self._monitors[abs_path].cancel()
                del self._monitors[abs_path]
            is_dir = other_file is not None and (
                other_file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY
                if other_file else False
            )
            # Try to infer from original file if available
            try:
                if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
                    is_dir = True
            except Exception:
                pass
            event_type_str = "dir_deleted" if is_dir else "file_deleted"
        else:
            return  # IGNORED, WILL_SHOOT, UNKNOWN, BACKUP, RENAMED — ignored

        self._schedule_debounced(relative_path, event_type_str)

    def _add_monitor_recursive(self, dir_path: str) -> None:
        """Add a Gio.FileMonitor for dir_path and all subdirectories."""
        gfile = Gio.File.new_for_path(dir_path)
        if not gfile.query_exists(None):
            return

        # Skip ignored directories
        rel = _get_relative_path(self._watched_path or dir_path, dir_path)
        if rel and _should_ignore(rel + "/"):
            return

        if dir_path not in self._monitors:
            monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            if monitor is not None:
                monitor.connect("changed", self._on_monitor_event)
                self._monitors[dir_path] = monitor

        # Recurse into subdirectories
        try:
            enumerator = gfile.enumerate_children(
                "standard::name,standard::type",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
            if enumerator is not None:
                for info in enumerator:
                    if info.get_file_type() == Gio.FileType.DIRECTORY:
                        child = gfile.get_child(info.get_name())
                        self._add_monitor_recursive(child.get_path())
        except Exception:
            pass

    def start_watching(self, project_path: str, project_name: str) -> None:
        """
        Start monitoring project_path for filesystem changes.

        Creates monitors for the project root and all subdirectories (recursive).
        Stops any previous watch before starting the new one.

        Args:
            project_path: Absolute path to the project directory to monitor.
            project_name: Human-readable project name (used in FeedCardData).
        """
        # Stop any existing watch first
        self.stop_watching()

        # Resolve to absolute path
        gfile = Gio.File.new_for_path(project_path)
        if not gfile.query_exists(None):
            return  # Project directory doesn't exist yet

        self._watched_path = project_path
        self._watched_name = project_name

        # Recursively add monitors for all directories
        self._add_monitor_recursive(project_path)

    def stop_watching(self) -> None:
        """Stop monitoring all directories."""
        for monitor in self._monitors.values():
            monitor.cancel()
        self._monitors.clear()

        # Cancel all pending debounce timers
        for source in self._debounce_map.values():
            if source is not None:
                source.destroy()
        self._debounce_map.clear()
        self._pending_events.clear()

        self._watched_path = None
        self._watched_name = None

    def is_watching(self) -> bool:
        """Return True if currently monitoring a project directory."""
        return len(self._monitors) > 0