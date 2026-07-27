# ui/views/file_tree.py
# File tree widget — GTK4 ColumnView with Gio.ListStore + FileTreeRow GObject model.
#
# Phase 1: Row widget, data model, factory, ColumnView setup.
# Expand/collapse, drawer toggle, and diff loading are in Phases 2-7.
#
# Public API:
#   tree = FileTree(on_file_selected=None)
#   tree.load_project(name, path)  # load a project root
#   tree.navigate_back()            # return to project picker

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, GLib, Gdk, Gio, GObject

import os
import threading
import time
from typing import Optional, cast

from utils.escaping import escape_for_pango
from utils.projects import scan_directory
from utils.git_ops import (
    diff_file_against_working_tree, diff_working_tree, file_log, diff_file_against, GitResult,
)
from utils.diff_parser import parse_diff
from ui.views.diff_card import render_diff_hunks, get_lang_from_path
from utils.file_icons import get_icon_for_path, guess_mime


# ── Module-level helpers ────────────────────────────────────────────────


def format_size(bytes_: int) -> str:
    """Human-readable file size. Float division for fractional KB/MB."""
    if bytes_ <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(bytes_)
    for unit in units:
        if val < 1024:
            if unit == "B":
                return f"{int(val)} B"
            return f"{val:.1f} {unit}".replace(".0 ", " ")
        val /= 1024.0
    return f"{val:.1f} PB"


def format_mtime(mtime_ns: int) -> str:
    """Relative time from nanosecond timestamp. Integer division (BUG #14)."""
    if mtime_ns < 1_000_000_000:  # sub-second-since-epoch is invalid (BUG #5)
        return "—"
    from datetime import datetime
    dt = datetime.fromtimestamp(mtime_ns // 1_000_000_000)
    now = datetime.now()
    diff = now - dt
    if diff.days < 0:  # future timestamp — show absolute date
        return dt.strftime("%b %d, %Y")
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
    """2-char porcelain → single-char badge. Index col has precedence."""
    if not status_code or len(status_code) < 2:
        return ""
    char = status_code[0] if status_code[0] != ' ' else status_code[1]
    return {'M': 'M', 'A': 'A', 'D': 'D', 'R': 'R', 'C': 'C', '?': '?', '!': '!'}.get(char, "")


# ── Phase 1: FileTreeRow — GObject data model for Gio.ListStore ─────────

class FileTreeRow(GObject.Object):
    """A single row in the file tree list store.

    Properties are GObject properties so ColumnView factory can bind/unbind them.
    """

    __gtype_name__ = 'FileTreeRow'

    display_name = GObject.Property(type=str, default="")
    full_path = GObject.Property(type=str, default="")
    is_dir = GObject.Property(type=bool, default=False)
    is_drawer = GObject.Property(type=bool, default=False)
    depth = GObject.Property(type=int, default=0)
    expanded = GObject.Property(type=bool, default=False)
    has_children = GObject.Property(type=bool, default=False)

    # Drawer state (mirrors old self._drawers[path] dict)
    drawer_widget = GObject.Property(type=GObject.TYPE_PYOBJECT, default=None)
    is_open = GObject.Property(type=bool, default=False)
    diff_text = GObject.Property(type=str, default="")
    history_selected_sha = GObject.Property(type=GObject.TYPE_PYOBJECT, default=None)
    history_loaded = GObject.Property(type=bool, default=False)

    # Phase 1 — file tree metadata
    file_size = GObject.Property(type=int, default=0)
    file_size_display = GObject.Property(type=str, default="—")
    modified_time = GObject.Property(type=int, default=0)
    modified_display = GObject.Property(type=str, default="—")
    git_status = GObject.Property(type=str, default="")
    git_status_display = GObject.Property(type=str, default="")
    mime_type = GObject.Property(type=str, default="")
    icon_name = GObject.Property(type=str, default="text-x-generic-symbolic")
    icon_color_class = GObject.Property(type=str, default="file-icon-default")
    parent_full_path = GObject.Property(type=str, default="")

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
                 mime_type: str = "",
                 icon_name: str = "text-x-generic-symbolic",
                 icon_color_class: str = "file-icon-default",
                 parent_full_path: str = ""):
        super().__init__()
        self.props.display_name = display_name
        self.props.full_path = full_path
        self.props.is_dir = is_dir
        self.props.is_drawer = is_drawer
        self.props.depth = depth
        self.props.expanded = expanded
        self.props.has_children = has_children
        self.props.drawer_widget = drawer_widget
        self.props.is_open = is_open
        self.props.diff_text = diff_text
        self.props.history_selected_sha = history_selected_sha
        self.props.history_loaded = history_loaded
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


# ── Phase 1: FileTreeRowWidget — Per-row Gtk.Box ─────────────────────────

class FileTreeRowWidget(Gtk.Box):
    """Widget for a single row in the ColumnView.

    Contains: expander button, icon, label, drawer_container (for drawer rows).
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add_css_class("file-tree-row")

        # Expander button (▶/▼ for dirs, spacer for files/drawers)
        self._expander_btn = Gtk.Button()
        self._expander_btn.add_css_class("file-tree-row-expander")
        self._expander_btn.set_size_request(16, 16)
        self._expander_btn.set_halign(Gtk.Align.CENTER)
        self._expander_btn.set_valign(Gtk.Align.CENTER)
        self.append(self._expander_btn)

        # Icon (folder/file)
        self._icon = Gtk.Image()
        self._icon.add_css_class("file-tree-row-icon")
        self._icon.set_pixel_size(16)
        self.append(self._icon)

        # Label (markup for prefix + name)
        self._label = Gtk.Label()
        self._label.add_css_class("file-tree-row-label")
        self._label.set_halign(Gtk.Align.START)
        self._label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self._label.set_hexpand(True)
        self._label.set_use_markup(True)
        self.append(self._label)

        # Drawer container — only populated for drawer rows (is_drawer=True)
        self._drawer_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._drawer_container.set_visible(False)
        self.append(self._drawer_container)

        # Track bound row for cleanup
        self._bound_row: Optional[FileTreeRow] = None
        # Phase 2: expander button signal handler ID
        self._expander_handler_id: Optional[int] = None

    def set_depth(self, depth: int) -> None:
        """Set indentation via CSS margin-left on the whole row."""
        self.set_margin_start(depth * 20)

    def set_expanded(self, expanded: bool) -> None:
        """Update expander button label (▶ / ▼)."""
        if expanded:
            self._expander_btn.set_label("▼")
        else:
            self._expander_btn.set_label("▶")

    def set_label(self, display_name: str) -> None:
        """Set label markup. Display name already includes prefix."""
        self._label.set_markup(escape_for_pango(display_name))

    def set_icon(self, icon_name: str, is_dir: bool, is_drawer: bool) -> None:
        """Set icon based on icon_name. Drawer rows hide the icon."""
        if is_drawer:
            self._icon.set_visible(False)
        else:
            self._icon.set_visible(True)
            self._icon.set_from_icon_name(icon_name)

    def set_icon_color(self, color_class: str) -> None:
        """Remove previous file-icon-* class, add the new one."""
        for cls in list(self._icon.get_css_classes()):
            if cls.startswith("file-icon-"):
                self._icon.remove_css_class(cls)
        if color_class:
            self._icon.add_css_class(color_class)

    def attach_drawer(self, revealer: Gtk.Revealer) -> None:
        """Attach a drawer revealer to this row's container."""
        while self._drawer_container.get_first_child():
            self._drawer_container.remove(self._drawer_container.get_first_child())
        self._drawer_container.append(revealer)
        self._drawer_container.set_visible(True)

    def detach_drawer(self) -> None:
        """Detach drawer revealer — called from factory unbind."""
        while self._drawer_container.get_first_child():
            self._drawer_container.remove(self._drawer_container.get_first_child())
        self._drawer_container.set_visible(False)

    def cleanup(self) -> None:
        """Detach drawer, clear bound row reference."""
        self.detach_drawer()
        self._bound_row = None

    def bind_row(self, row: FileTreeRow) -> None:
        """Store reference to bound row for signal connections."""
        self._bound_row = row


# ── Phase 1: FileTreeFactory — SignalListItemFactory ─────────────────────

class FileTreeFactory(Gtk.SignalListItemFactory):
    """Factory for ColumnView rows. Creates FileTreeRowWidget and binds FileTreeRow properties."""

    def __init__(self, tree: 'FileTree'):
        super().__init__()
        self._tree = tree
        self.connect('setup', self._on_setup)
        self.connect('bind', self._on_bind)
        self.connect('unbind', self._on_unbind)

    def _on_setup(self, factory: 'FileTreeFactory', list_item: Gtk.ListItem) -> None:
        widget = FileTreeRowWidget()
        list_item.set_child(widget)

        # Right-click gesture for context menu (Copy Path / Copy File)
        # NOTE: Gesture is attached ONCE per widget instance. The row is read
        # LIVE at click time from widget._bound_row to avoid stale-row bugs
        # from ColumnView recycling.
        right_ctrl = Gtk.GestureClick()
        right_ctrl.set_button(Gdk.BUTTON_SECONDARY)
        right_ctrl.connect("pressed", self._tree._on_tree_row_right_click, widget)
        widget.add_controller(right_ctrl)

    def _on_bind(self, factory: 'FileTreeFactory', list_item: Gtk.ListItem) -> None:
        row = cast(FileTreeRow, list_item.get_item())
        widget: FileTreeRowWidget = list_item.get_child()

        widget.bind_row(row)
        widget.set_depth(row.props.depth)
        widget.set_expanded(row.props.expanded)
        widget.set_label(row.props.display_name)
        widget.set_icon(row.props.icon_name, row.props.is_dir, row.props.is_drawer)
        widget.set_icon_color(row.props.icon_color_class)

        # Drawer rows: hide label (no text needed), let drawer_container fill space
        if row.props.is_drawer:
            widget._label.set_visible(False)
            widget._label.set_hexpand(False)  # don't compete for space
            widget._drawer_container.set_hexpand(True)
        else:
            widget._label.set_visible(True)
            widget._label.set_hexpand(True)
            widget._drawer_container.set_hexpand(False)

        if row.props.is_drawer and row.props.drawer_widget:
            widget.attach_drawer(row.props.drawer_widget)

        # Phase 2: Wire expander button for directories
        if row.props.is_dir and not row.props.is_drawer:
            # Disconnect previous handler if re-binding
            if widget._expander_handler_id is not None:
                widget._expander_btn.disconnect(widget._expander_handler_id)
            # BUG #2: Pass `row` object instead of stale `position`.
            # The current position is re-queried at click time via _find_row_index.
            widget._expander_handler_id = widget._expander_btn.connect(
                "clicked", lambda btn: self._on_expander_clicked(row)
            )
            widget._expander_btn.set_visible(True)
        else:
            widget._expander_btn.set_visible(False)

    def _on_unbind(self, factory: 'FileTreeFactory', list_item: Gtk.ListItem) -> None:
        widget: FileTreeRowWidget = list_item.get_child()
        widget.cleanup()

    def _on_expander_clicked(self, row: FileTreeRow) -> None:
        """Handle expander button click for a directory row.

        Re-queries the row's current position at click time to handle
        stale indices from prior store mutations (BUG #2).
        """
        position = self._tree._find_row_index(row)
        if position is not None:
            self._tree._on_expander_clicked(row, position)


# ── Phase 2: Multi-column factories (Status, Size, Modified) ────────────

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
        # Clear previous status class, add current
        for cls in list(label.get_css_classes()):
            if cls.startswith("file-tree-status-"):
                label.remove_css_class(cls)
        class_map = {
            "M": "file-tree-status-modified",
            "A": "file-tree-status-staged",
            "?": "file-tree-status-untracked",
            "D": "file-tree-status-deleted",
            "R": "file-tree-status-renamed",
            "!": "file-tree-status-ignored",
        }
        if display in class_map:
            label.add_css_class(class_map[display])

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


# ── FileTree — Main widget class ─────────────────────────────────────────

class FileTree(Gtk.Box):
    """
    File tree browser widget.
    Displays project list, or directory tree when a project is selected.
    """

    def __init__(self, on_file_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_file_selected = on_file_selected
        # Project list handler — wired by window via set_project_list_handler()
        self._project_list_handler = None
        # On project opened callback — wired by window via set_on_project_opened()
        self._on_project_opened = None
        # On create project callback — wired by window via set_on_create_project()
        self._on_create_project = None
        # Callback when navigate_back is called — window wires this to close project tabs
        self._on_navigate_back = None

        # Project state
        self._project_name = None
        self._project_path = None
        self._project_history = []  # stack of paths for back navigation
        # ProjectHandler reference — set externally for checkpoint SHA resolution
        self._project_handler = None

        # Phase 1: Drawer state tracking (replaces old self._drawers dict)
        self._drawer_paths: dict[str, FileTreeRow] = {}  # file_path -> drawer row object
        self._loaded_drawers: set[str] = set()
        self._last_toggle_per_file: dict[str, float] = {}
        self._current_request_id = 0  # For async guard (BUG #7)

        # Phase 2: Git status stub callback — wired by handler in Phase 4
        self._on_get_git_status = None
        # Phase 2: Git status map for child rows — set in _show_tree, used in _on_directory_loaded
        self._git_status_map: dict[str, str] = {}

        # Phase 3: Sort/filter model chain (lives in view — uses Gtk types)
        self._sort_model: Gtk.SortListModel | None = None
        self._filter_model: Gtk.FilterListModel | None = None
        self._sort_dropdown = None  # created in _build_header
        self._current_sort_mode = "name_asc"  # tracked for re-apply on subtree expand
        self._search_timeout_id = None  # BUG #9: tree search debounce timeout

        # Phase 3: Callbacks to handler (Phase 4 wires these)
        self._on_sort_changed = None
        self._on_get_sort_mode = None

        # ── Header ────────────────────────────────────────────────────────
        self._header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._header.set_halign(Gtk.Align.FILL)
        self._header.set_margin_start(4)
        self._header.set_margin_end(4)
        self._header.set_margin_top(4)
        self._header.set_margin_bottom(4)

        self._back_btn = Gtk.Button()
        self._back_btn.set_tooltip_text("Back to projects")
        self._back_btn.set_size_request(28, 28)
        self._back_btn.add_css_class("flat")
        back_img = Gtk.Image.new_from_icon_name("go-previous-symbolic")
        back_img.set_pixel_size(20)
        self._back_btn.set_child(back_img)
        self._back_btn.connect("clicked", self._on_back_clicked)
        self._back_btn.set_visible(False)

        self._folder_icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        self._folder_icon.set_pixel_size(18)
        self._folder_icon.set_margin_end(6)

        self._title_lbl = Gtk.Label()
        self._title_lbl.set_halign(Gtk.Align.START)
        self._title_lbl.add_css_class("project-selector-title")

        # Search entry — visible only in picker mode
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search projects...")
        self._search_entry.set_hexpand(True)
        self._search_entry.set_valign(Gtk.Align.CENTER)
        self._search_changed_handler_id = self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.set_visible(False)

        # Phase 3: Sort dropdown — visible only in tree mode
        self._sort_dropdown = Gtk.DropDown.new_from_strings([
            "Name ↑", "Name ↓", "Modified ↑", "Modified ↓", "Size ↑", "Size ↓"
        ])
        self._sort_dropdown.set_selected(0)
        self._sort_dropdown.set_valign(Gtk.Align.CENTER)
        self._sort_dropdown.add_css_class("file-tree-sort-dropdown")
        self._sort_dropdown.set_visible(False)  # hidden until _show_tree
        self._sort_dropdown_handler_id = self._sort_dropdown.connect(
            "notify::selected", self._on_sort_dropdown_changed)

        self._header.append(self._back_btn)
        self._header.append(self._folder_icon)
        self._header.append(self._title_lbl)
        self._header.append(self._search_entry)
        self._header.append(self._sort_dropdown)

        # Status label for copy confirmation (transient, ~2.5s)
        self._tree_copy_status_label = Gtk.Label()
        self._tree_copy_status_label.add_css_class("dim-label")
        self._tree_copy_status_label.set_halign(Gtk.Align.END)
        self._tree_copy_status_label.set_valign(Gtk.Align.CENTER)
        self._tree_copy_status_label.set_margin_end(8)
        self._tree_copy_status_label.set_visible(False)  # start hidden
        self._tree_copy_status_timeout_id = None
        self._header.append(self._tree_copy_status_label)

        # ── Phase 1: ColumnView + ListStore ───────────────────────────────
        self._store = Gio.ListStore.new(FileTreeRow.__gtype__)
        self._selection = Gtk.SingleSelection.new(self._store)
        self._column_view = Gtk.ColumnView.new(self._selection)
        self._column_view.set_show_row_separators(False)
        self._column_view.set_show_column_separators(False)
        self._column_view.add_css_class("file-tree-column-view")

        factory = FileTreeFactory(self)
        column = Gtk.ColumnViewColumn.new("Name", factory)
        column.set_expand(True)
        self._column_view.append_column(column)

        # Key controller for keyboard nav (Esc, Ctrl+C, Enter)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self._column_view.add_controller(key_controller)

        # Row activation (double-click)
        self._column_view.connect("activate", self._on_row_activated)

        # ScrolledWindow
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(self._column_view)

        # Content widget — switches between ColumnView (tree mode) and card box (picker mode)
        self._content = self._scroll
        self.append(self._header)
        self.append(self._content)

        # Load project picker on init
        self._show_project_picker()

    # ── Public API ────────────────────────────────────────────────────────

    def _clear_all_state(self) -> None:
        """Clear all FileTree state — store, drawers, async requests.

        Called on project switch (navigate_back) and when switching to project picker.
        """
        # Clear the store
        while self._store.get_n_items() > 0:
            self._store.remove(0)

        # Clear drawer state
        self._drawer_paths.clear()
        self._loaded_drawers.clear()
        self._last_toggle_per_file.clear()

        # Clear git status map
        self._git_status_map = {}

        # BUG #9: cancel outstanding search timeout
        if self._search_timeout_id is not None:
            try:
                GLib.source_remove(self._search_timeout_id)
            except Exception:
                pass
            self._search_timeout_id = None

        # Clear sort/filter model references (will be recreated in _init_sort_filter)
        self._sort_model = None
        self._filter_model = None

        # Invalidate any in-flight async requests
        self._current_request_id += 1

    def load_project(self, name, path):
        """Load a project root and show its directory tree."""
        self._project_name = name
        self._project_path = path
        self._project_history.clear()
        if self._on_project_opened:
            self._on_project_opened(name, path)
        self._show_tree(name, path)

    def navigate_back(self, fire_callback: bool = True):
        """
        Return to the project picker. Fires on_navigate_back if set.

        Args:
            fire_callback: If True (default), fires _on_navigate_back callback.
                          Pass False when caller manages the callback to avoid double-fire.
        """
        project_name = self._project_name  # capture before clearing
        self._project_name = None
        self._project_path = None
        self._project_history.clear()
        # Clear all FileTree state
        self._clear_all_state()
        # Clear search when returning to picker
        if self._project_list_handler:
            self._project_list_handler.clear_search()
        # Block signal to prevent _on_search_changed from firing while FileTree
        # is still inside the nested notebook (would build cards in wrong parent).
        self._search_entry.handler_block(self._search_changed_handler_id)
        try:
            self._search_entry.set_text("")
        finally:
            self._search_entry.handler_unblock(self._search_changed_handler_id)
        if fire_callback and self._on_navigate_back:
            self._on_navigate_back(project_name)
        self._show_project_picker()

    def set_on_navigate_back(self, cb):
        """Set callback for when navigate_back is called. cb(project_name)."""
        self._on_navigate_back = cb

    def set_on_project_opened(self, cb):
        """Set callback for when a project is opened (name, path)."""
        self._on_project_opened = cb

    def set_on_create_project(self, cb):
        """Set callback for creating a new project. cb(name) -> path | None."""
        self._on_create_project = cb

    def set_project_list_handler(self, handler):
        """Set the ProjectListHandler — provides project data and colors for cards."""
        self._project_list_handler = handler
        # Refresh the picker if it's currently showing
        self._show_project_picker()

    def set_project_handler(self, handler) -> None:
        """Set ProjectHandler reference for checkpoint SHA resolution in diff loading."""
        self._project_handler = handler

    def set_on_get_git_status(self, cb):
        """Set callback to fetch git status dict {rel_path: code} from handler.
        Returns dict[str, str]. Called by _show_tree when populating root rows."""
        self._on_get_git_status = cb

    # ── Phase 3: Sort/Filter Model Chain ──────────────────────────────

    def _init_sort_filter(self) -> None:
        """Create SortListModel + FilterListModel chain once, repoint selection."""
        self._sort_model = Gtk.SortListModel.new(self._store, None)
        self._filter_model = Gtk.FilterListModel.new(self._sort_model, None)
        self._selection.set_model(self._filter_model)

    def _apply_sort(self, sort_mode: str) -> None:
        """In-place sorter change. Tracks _current_sort_mode for re-apply (M6)."""
        self._current_sort_mode = sort_mode
        if self._sort_model is None:
            return
        sorter = self._build_sorter(sort_mode)
        self._sort_model.set_sorter(sorter)

    @staticmethod
    def _build_sorter(sort_mode: str) -> Gtk.Sorter:
        """Build comparator-based sorter that preserves tree hierarchy.

        Sort is depth-aware: items only sort within their depth group, so
        children stay under their parent directory. Drawer rows sort
        immediately after their parent file (using parent_full_path as key).
        Directories always sort before files within the same depth group.
        Drawers are in the file group (rank=1) and use their parent's basename
        as sort key, so they interleave with files rather than clumping at the end.
        """

        import os as _os

        def cmp(a, b, _ud=None):
            # Rule 1: Depth groups — NEVER mix depths (children stay under parents)
            if a.props.depth != b.props.depth:
                return -1 if a.props.depth < b.props.depth else 1

            # Rule 2: Within same depth, dirs before files/drawers (both rank 1).
            # Drawers interleave with files using parent basename as sort key.
            def group_rank(row):
                if row.props.is_dir:
                    return 0
                return 1  # files and drawers share rank 1
            ga, gb = group_rank(a), group_rank(b)
            if ga != gb:
                return -1 if ga < gb else 1

            # Rule 3: For drawers, use basename of parent_full_path so the sort
            # key matches the parent file's display_name. This ensures the drawer
            # sorts at the exact same position as its parent (insertion order
            # places drawer after parent).
            if a.props.is_drawer:
                name_a = _os.path.basename(a.props.parent_full_path or "").casefold()
            else:
                name_a = (a.props.display_name or "").casefold()
            if b.props.is_drawer:
                name_b = _os.path.basename(b.props.parent_full_path or "").casefold()
            else:
                name_b = (b.props.display_name or "").casefold()

            # Rule 3a: Tiebreaker — when names match and one is a drawer,
            # the file sorts before the drawer (parent before child drawer).
            # This handles scrambled insertion order where a drawer row
            # was inserted before its parent file in the store.
            if name_a == name_b:
                if not a.props.is_drawer and b.props.is_drawer:
                    return -1  # file before its drawer
                if a.props.is_drawer and not b.props.is_drawer:
                    return 1   # drawer after its file

            # Rule 4: Apply the actual sort mode within the group
            if sort_mode in ("name_asc", "name_desc"):
                if name_a != name_b:
                    if sort_mode == "name_asc":
                        return -1 if name_a < name_b else 1
                    else:
                        return 1 if name_a < name_b else -1
                return 0

            if sort_mode in ("modified_asc", "modified_desc"):
                ta, tb = a.props.modified_time, b.props.modified_time
                if ta != tb:
                    if sort_mode == "modified_asc":
                        return -1 if ta < tb else 1
                    else:
                        return 1 if ta < tb else -1
                # Tie-break by name for stable order
                return -1 if name_a < name_b else (1 if name_a > name_b else 0)

            if sort_mode in ("size_asc", "size_desc"):
                sa, sb = a.props.file_size, b.props.file_size
                if sa != sb:
                    if sort_mode == "size_asc":
                        return -1 if sa < sb else 1
                    else:
                        return 1 if sa < sb else -1
                return -1 if name_a < name_b else (1 if name_a > name_b else 0)

            # Default: name ascending
            return -1 if name_a < name_b else (1 if name_a > name_b else 0)

        return Gtk.CustomSorter.new(cmp)

    def _apply_filter(self, query: str) -> None:
        """In-place filter change. casefold() for Unicode-safe match (BUG #12)."""
        if self._filter_model is None:
            return
        if not query:
            self._filter_model.set_filter(None)
            return
        custom_filter = Gtk.CustomFilter.new(
            lambda item, q=query: FileTree._filter_func(item, q)
        )
        self._filter_model.set_filter(custom_filter)

    @staticmethod
    def _filter_func(item, query: str) -> bool:
        """Substring match on name + path. casefold() (BUG #12).
        Drawer rows pass through via parent_full_path (BUG #18, #26).
        Defensive None handling for full_path/parent_full_path (BUG #4).
        """
        if not query:
            return True
        if item is None:  # BUG #24: race on concurrent mutation
            return False
        row = cast(FileTreeRow, item)
        q = query.casefold()
        name = (row.props.display_name or "").casefold()
        if row.props.is_drawer:
            parent = (row.props.parent_full_path or "").casefold()
            return q in name or q in parent
        path = (row.props.full_path or "").casefold()
        return q in name or q in path

    # ── Phase 3: Sort dropdown handler ─────────────────────────────────

    def _on_sort_dropdown_changed(self, dropdown, pspec):
        """Handle sort selection — update sort model + notify handler."""
        selected = dropdown.get_selected()
        modes = ["name_asc", "name_desc", "modified_asc", "modified_desc",
                 "size_asc", "size_desc"]
        mode = modes[selected] if 0 <= selected < len(modes) else "name_asc"
        self._apply_sort(mode)
        if self._on_sort_changed:
            self._on_sort_changed(mode)

    # ── Phase 3: Setters for sort-related callbacks ────────────────────

    def set_on_sort_changed(self, cb):
        """Set callback for sort mode changes. cb(mode_str)."""
        self._on_sort_changed = cb

    def set_on_get_sort_mode(self, cb):
        """Set callback to fetch saved sort mode. cb() -> str."""
        self._on_get_sort_mode = cb

    def toggle_drawer_for_file(self, file_path: str) -> None:
        """Public method to toggle a file's diff drawer open/closed from outside.

        Called by MainContent when the user requests a file diff from a tab.
        """
        self._toggle_drawer(file_path)

    def is_drawer_open(self, file_path: str) -> bool:
        """Return True if the drawer for the given file path is currently open."""
        return file_path in self._drawer_paths

    # ── Private ───────────────────────────────────────────────────────────

    def _show_project_picker(self):
        """Show project cards (replaces ColumnView tree rows)."""
        # Clear all FileTree state
        self._clear_all_state()
        self._back_btn.set_visible(False)
        self._folder_icon.set_visible(False)
        self._title_lbl.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 11">Projects</span>'
        )
        # Phase 2: search visible in both modes
        self._search_entry.set_visible(True)
        self._search_entry.set_placeholder_text("Search projects...")
        # Phase 3: hide sort dropdown in picker mode
        self._sort_dropdown.set_visible(False)
        # Rebuild title to not expand so search entry gets space
        self._title_lbl.set_hexpand(False)

        # Phase 2: Reset ColumnView to single Name column for picker mode
        for col in list(self._column_view.get_columns()):
            self._column_view.remove_column(col)
        factory = FileTreeFactory(self)
        col_name = Gtk.ColumnViewColumn.new("Name", factory)
        col_name.set_expand(True)
        self._column_view.append_column(col_name)

        # Build card grid
        card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card_box.set_margin_start(8)
        card_box.set_margin_end(8)
        card_box.set_margin_top(4)
        card_box.set_spacing(6)

        if self._project_list_handler is None:
            # No handler wired — show nothing (degraded but non-crashing)
            pass
        else:
            # New project card (always first)
            new_card = self._make_new_project_card()
            card_box.append(new_card)

            # Use filtered results (respects current search query)
            projects = self._project_list_handler._filtered_projects()
            if not projects:
                query = self._project_list_handler._search_query
                if query:
                    empty_lbl = Gtk.Label(label=f"No projects matching \"{query}\"")
                else:
                    empty_lbl = Gtk.Label(label="No projects found")
                empty_lbl.add_css_class("dim-label")
                card_box.append(empty_lbl)
            else:
                for name, path, color in projects:
                    card = self._make_project_card(name, path, color)
                    card_box.append(card)

        # Replace ColumnView content with card box
        self.remove(self._content)
        self._content = card_box
        self.append(self._content)

    def _make_project_card(self, name: str, path: str, color_hex: str) -> Gtk.Widget:
        """
        Build a project card widget: [folder_icon] [name] [path]
        Colored folder icon with first letter of project name.
        """
        from utils.icons import render_folder_icon

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        card.set_halign(Gtk.Align.FILL)
        card.set_spacing(10)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.add_css_class("project-card")

        # Folder icon (44x44)
        letter = name[0].upper() if name else "?"
        texture = render_folder_icon(color_hex, letter, size=44)

        icon_pic = Gtk.Picture()
        icon_pic.set_size_request(44, 44)
        if texture is not None:
            icon_pic.set_paintable(texture)
        else:
            fallback = Gtk.Label(label=letter)
            fallback.set_halign(Gtk.Align.CENTER)
            fallback.set_valign(Gtk.Align.CENTER)
            icon_pic.set_child(fallback)

        # Text column
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text_box.set_valign(Gtk.Align.CENTER)

        name_lbl = Gtk.Label(label=name)
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.add_css_class("project-card-name")

        path_lbl = Gtk.Label(label=path)
        path_lbl.set_halign(Gtk.Align.START)
        path_lbl.add_css_class("project-card-path")

        text_box.append(name_lbl)
        text_box.append(path_lbl)

        card.append(icon_pic)
        card.append(text_box)

        # Single-click opens project
        ev = Gtk.GestureClick()
        ev.connect("pressed", lambda *a: self.load_project(name, path))
        card.add_controller(ev)

        return card

    def _make_new_project_card(self) -> Gtk.Widget:
        """Build the '+' new project card with dashed border."""
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        card.set_halign(Gtk.Align.FILL)
        card.set_spacing(10)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.add_css_class("new-project-card")

        plus_lbl = Gtk.Label(label="+")
        plus_lbl.set_halign(Gtk.Align.CENTER)
        plus_lbl.set_valign(Gtk.Align.CENTER)
        plus_lbl.set_size_request(44, 44)
        plus_lbl.add_css_class("new-project-plus")

        text_lbl = Gtk.Label(label="New Project")
        text_lbl.set_halign(Gtk.Align.START)
        text_lbl.set_valign(Gtk.Align.CENTER)
        text_lbl.add_css_class("dim-label")

        card.append(plus_lbl)
        card.append(text_lbl)

        ev = Gtk.GestureClick()
        ev.connect("pressed", lambda *a: self._show_create_popover(card))
        card.add_controller(ev)

        return card

    def _show_create_popover(self, anchor: Gtk.Widget):
        """Show a popover form to create a new project."""
        if not self._on_create_project:
            return

        popover = Gtk.Popover()
        popover.set_parent(anchor)
        popover.set_position(Gtk.PositionType.BOTTOM)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)

        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("Project name")
        name_entry.set_hexpand(True)

        create_btn = Gtk.Button(label="Create")
        create_btn.add_css_class("suggested-action")

        def on_create(_btn):
            name = name_entry.get_text().strip()
            if not name:
                return
            result = self._on_create_project(name)
            if result is not None:
                popover.popdown()
                self.load_project(name, result)

        create_btn.connect("clicked", on_create)

        name_entry.connect("activate", lambda _e: on_create(create_btn))

        vbox.append(name_entry)
        vbox.append(create_btn)
        popover.set_child(vbox)
        popover.popup()

        GLib.idle_add(lambda: name_entry.grab_focus() and False)

    def _show_tree(self, name, path):
        """Show the directory tree for a project. Populates ListStore with root entries."""
        # Swap card box back to scroll/ColumnView
        if self._content != self._scroll:
            self.remove(self._content)
            self._content = self._scroll
            self.append(self._content)
        # Clear all FileTree state
        self._clear_all_state()
        self._back_btn.set_visible(True)
        self._folder_icon.set_visible(True)
        safe_name = escape_for_pango(name)
        self._title_lbl.set_markup(f"<b>{safe_name}</b>")
        self._title_lbl.set_use_markup(True)
        self._title_lbl.set_hexpand(True)
        # Phase 2: search visible in both modes
        self._search_entry.set_visible(True)
        self._search_entry.set_placeholder_text("Search files...")
        # Phase 3: sort dropdown visible only in tree mode
        self._sort_dropdown.set_visible(True)

        # Phase 2: Remove existing columns, add 4-column layout
        for col in list(self._column_view.get_columns()):
            self._column_view.remove_column(col)

        factory_name = FileTreeFactory(self)
        col_name = Gtk.ColumnViewColumn.new("Name", factory_name)
        col_name.set_expand(True)
        self._column_view.append_column(col_name)

        col_status = Gtk.ColumnViewColumn.new("Status", FileTreeStatusFactory())
        col_status.set_fixed_width(60)
        self._column_view.append_column(col_status)

        col_size = Gtk.ColumnViewColumn.new("Size", FileTreeSizeFactory())
        col_size.set_fixed_width(80)
        self._column_view.append_column(col_size)

        col_modified = Gtk.ColumnViewColumn.new("Modified", FileTreeModifiedFactory())
        col_modified.set_fixed_width(100)
        self._column_view.append_column(col_modified)

        # Phase 2: Query git status via stub callback
        status_map: dict[str, str] = {}
        if self._on_get_git_status:
            status_map = self._on_get_git_status() or {}
        self._git_status_map = status_map

        # Populate root entries
        try:
            entries = scan_directory(path)
        except Exception as e:
            entries = [(f"[error: {type(e).__name__}: {e}]", "", False, 0, 0)]
        for entry_name, full_path, is_dir, size_bytes, mtime_ns in entries:
            icon = get_icon_for_path(full_path, is_dir)
            # Look up git status from status_map
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
                file_size_display="—" if is_dir else format_size(size_bytes),
                modified_time=mtime_ns // 1_000_000_000 if mtime_ns else 0,
                modified_display=format_mtime(mtime_ns) if mtime_ns else "—",
                git_status=raw_status,
                git_status_display=git_status_to_display(raw_status),
                mime_type=guess_mime(full_path),
                icon_name=icon.icon_name,
                icon_color_class=icon.color_class,
            )
            self._store.append(row)

        # Phase 3: Initialize sort/filter model chain and restore saved sort mode (M6)
        # Reset dropdown to default before restoring (BUG #7 fix)
        self._sort_dropdown.handler_block(self._sort_dropdown_handler_id)
        try:
            self._sort_dropdown.set_selected(0)
        finally:
            self._sort_dropdown.handler_unblock(self._sort_dropdown_handler_id)
        self._init_sort_filter()
        # Always apply default sort first (P3-1 fix)
        self._apply_sort("name_asc")
        # Restore saved mode if handler provides one (block signal to avoid feedback loop — BUG #3)
        if self._on_get_sort_mode:
            saved = self._on_get_sort_mode()
            valid = ["name_asc", "name_desc", "modified_desc", "modified_asc",
                     "size_desc", "size_asc"]
            if saved in valid:
                idx = valid.index(saved)
                self._sort_dropdown.handler_block(self._sort_dropdown_handler_id)
                try:
                    self._sort_dropdown.set_selected(idx)
                finally:
                    self._sort_dropdown.handler_unblock(self._sort_dropdown_handler_id)
                self._apply_sort(saved)

    # ── Phase 3: Drawer Row Insertion ──────────────────────────────────

    def _add_drawer_for_file(self, file_path: str, display_name: str) -> Gtk.Revealer:
        """Create a drawer revealer for a file row.

        The drawer is inserted as a separate row in the ListStore (is_drawer=True)
        immediately below the file row. On toggle, the revealer slides open.

        Returns the Gtk.Revealer so _toggle_drawer can insert it into the store.
        """
        drawer_box = self._build_drawer_content(file_path, display_name)

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)
        revealer.set_transition_duration(150)
        revealer.add_css_class("file-tree-drawer")
        revealer.set_child(drawer_box)

        revealer.connect("notify::child-revealed", self._on_revealer_child_revealed, file_path)

        return revealer

    def _build_drawer_content(self, file_path: str, display_name: str) -> Gtk.Box:
        """Build the drawer content widget (tabs, stack, action bar).

        Returns the drawer_box Gtk.Box. The revealer is created in _add_drawer_for_file.
        """
        drawer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        drawer_box.set_margin_start(10)
        drawer_box.set_margin_end(8)
        drawer_box.set_margin_top(4)
        drawer_box.set_margin_bottom(4)
        drawer_box.set_hexpand(True)

        # Top bar: Tabs (left) + Action buttons (right)
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top_bar.add_css_class("file-tree-drawer-tab-bar")
        top_bar.set_margin_bottom(4)
        top_bar.set_hexpand(True)

        diff_tab = Gtk.ToggleButton(label="Diff")
        diff_tab.set_active(True)
        diff_tab.add_css_class("file-tree-drawer-tab-btn")
        history_tab = Gtk.ToggleButton(label="History")
        history_tab.set_group(diff_tab)
        history_tab.add_css_class("file-tree-drawer-tab-btn")

        # Spacer to push action buttons to the right
        top_spacer = Gtk.Label()
        top_spacer.set_hexpand(True)

        revert_btn = Gtk.Button(label="Revert file to this version")
        revert_btn.add_css_class("diff-viewer-revert-btn")
        revert_btn.add_css_class("file-tree-drawer-tab-btn")
        revert_btn.set_visible(False)

        copy_btn = Gtk.Button(label="Copy diff")
        copy_btn.add_css_class("diff-viewer-copy-btn")
        copy_btn.add_css_class("file-tree-drawer-tab-btn")

        top_bar.append(diff_tab)
        top_bar.append(history_tab)
        top_bar.append(top_spacer)
        top_bar.append(revert_btn)
        top_bar.append(copy_btn)
        drawer_box.append(top_bar)

        # Stack
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_vexpand(True)
        stack.set_hexpand(True)

        # Diff page
        diff_scroll = Gtk.ScrolledWindow()
        diff_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        diff_scroll.set_propagate_natural_height(True)
        diff_scroll.set_min_content_height(72)
        diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        diff_box.set_margin_top(2)
        diff_box.set_margin_bottom(2)
        diff_scroll.set_child(diff_box)
        stack.add_named(diff_scroll, "diff")

        loading_spinner = Gtk.Spinner()
        loading_spinner.set_margin_top(8)
        loading_spinner.set_margin_bottom(8)
        loading_spinner.set_halign(Gtk.Align.CENTER)
        loading_spinner.set_size_request(24, 24)
        loading_spinner.start()
        diff_box.append(loading_spinner)

        # History page
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        history_scroll.set_propagate_natural_height(True)
        history_scroll.set_min_content_height(72)
        history_list = Gtk.ListBox()
        history_list.set_margin_top(2)
        history_list.set_margin_bottom(2)
        history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        history_scroll.set_child(history_list)
        stack.add_named(history_scroll, "history")

        drawer_box.append(stack)

        # Wire tab switching
        diff_tab.connect("toggled", lambda btn:
            stack.set_visible_child_name("diff") if btn.get_active() else None)
        history_tab.connect("toggled", lambda btn:
            (stack.set_visible_child_name("history"),
             self._load_history(file_path, history_list)) if btn.get_active() else None)

        # Wire revert button
        revert_btn.connect("clicked", lambda btn:
            self._on_drawer_revert_clicked(file_path, drawer_box))

        # Wire copy button
        copy_btn.connect("clicked", lambda btn:
            self._on_copy_diff_to_clipboard(file_path, drawer_box))

        # Wire history row activation
        history_list.connect("row-activated", lambda lb, row:
            self._load_historical_diff(file_path, getattr(row, 'sha', 'HEAD'), stack)
            if isinstance(row, Gtk.ListBoxRow) and row.get_activatable()
            else None)

        # Keyboard navigation in history list
        history_list.connect("keynav-failed", lambda lb, direction: True)
        history_list_controller = Gtk.EventControllerKey()
        history_list_controller.connect("key-pressed", lambda ctrl, keyval, keycode, state:
            self._on_history_key_pressed(keyval, history_list))
        history_list.add_controller(history_list_controller)

        # Store references on drawer_box for later access
        drawer_box._diff_tab = diff_tab
        drawer_box._history_tab = history_tab
        drawer_box._stack = stack
        drawer_box._diff_box = diff_box
        drawer_box._history_list = history_list
        drawer_box._revert_btn = revert_btn
        drawer_box._copy_btn = copy_btn
        drawer_box._history_selected_sha = None
        drawer_box._diff_text = ""

        # Unified key controller: Escape closes drawer, Ctrl+C copies diff
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", lambda ctrl, keyval, keycode, state:
            self._on_drawer_key_pressed(keyval, keycode, state, file_path, drawer_box))
        drawer_box.add_controller(key_controller)

        return drawer_box

    def _toggle_drawer(self, file_path: str) -> None:
        """Toggle a file's drawer open/closed.

        On first open, creates the drawer revealer and inserts it as a row below the file.
        On close, animates the revealer closed and removes the row.
        """
        # Debounce
        now = time.monotonic()
        if now - self._last_toggle_per_file.get(file_path, 0) < 0.3:
            return
        self._last_toggle_per_file[file_path] = now

        if file_path in self._drawer_paths:
            # Drawer entry exists — get the row object directly (BUG #1-R)
            drawer_row: FileTreeRow = self._drawer_paths[file_path]
            # Verify the row is still alive in the store (not removed by collapse)
            alive = False
            n = self._store.get_n_items()
            for i in range(n):
                if self._store.get_item(i) is drawer_row:
                    alive = True
                    break

            if not alive:
                # Stale entry from ancestor collapse — clean up and re-open
                del self._drawer_paths[file_path]
            else:
                # Drawer row is alive — close it
                revealer = drawer_row.props.drawer_widget
                if revealer is not None:
                    revealer.set_reveal_child(False)
                    # Row removal happens in _on_revealer_child_revealed
                else:
                    # BUG #2: Revealer is None — orphan state. Remove row directly.
                    self._store.remove(i)  # i is the index from the scan above
                    del self._drawer_paths[file_path]
                return  # Close path done

        if file_path not in self._drawer_paths:
            # Drawer doesn't exist (or was cleaned up above) — create and insert
            file_index = self._find_file_index(file_path)
            if file_index is None:
                return

            file_row = cast(FileTreeRow, self._store.get_item(file_index))
            revealer = self._add_drawer_for_file(file_path, file_row.props.display_name)

            # Create drawer row
            drawer_row = FileTreeRow(
                display_name="",
                full_path="",
                is_dir=False,
                is_drawer=True,
                depth=file_row.props.depth,
                drawer_widget=revealer,
                is_open=True,
                parent_full_path=file_path,
            )
            self._store.insert(file_index + 1, drawer_row)
            # BUG #1-R: Store the row object, not the index
            self._drawer_paths[file_path] = drawer_row

            # Animate open
            revealer.set_reveal_child(True)

            # Trigger lazy load of diff content
            if file_path not in self._loaded_drawers:
                self._loaded_drawers.add(file_path)
                self._trigger_diff_load(file_path, revealer.get_child())

    def _find_file_index(self, file_path: str) -> Optional[int]:
        """Find the index of a file row in the store by full_path. O(n) walk."""
        n = self._store.get_n_items()
        for i in range(n):
            row = cast(FileTreeRow, self._store.get_item(i))
            if not row.props.is_dir and not row.props.is_drawer and row.props.full_path == file_path:
                return i
        return None

    def _on_revealer_child_revealed(self, revealer: Gtk.Revealer, pspec, file_path: str) -> None:
        """When revealer animation completes and reveal_child is False, remove the drawer row."""
        # BUG #2-R: Guard against None revealer
        if revealer is None:
            return

        if revealer.get_reveal_child():
            return

        # BUG #1-R: Walk the store to find the row whose drawer_widget is this revealer.
        # Using object identity instead of a potentially-stale index.
        n = self._store.get_n_items()
        drawer_index = None
        for i in range(n):
            row = cast(FileTreeRow, self._store.get_item(i))
            if row.props.drawer_widget is revealer:
                drawer_index = i
                break

        if drawer_index is None:
            # Revealer not found in store — clean up any stale _drawer_paths entry
            if file_path in self._drawer_paths:
                del self._drawer_paths[file_path]
            return

        # Remove the drawer row
        self._store.remove(drawer_index)

        # Clean up _drawer_paths
        if file_path in self._drawer_paths:
            del self._drawer_paths[file_path]

        # BUG #2: Allow lazy reload on next open
        self._loaded_drawers.discard(file_path)

    def _trigger_diff_load(self, file_path: str, drawer_box: Gtk.Box) -> None:
        """Trigger lazy load of diff content for a file's drawer.

        Resolves checkpoint SHA from active review if ProjectHandler is available.
        """
        if not isinstance(drawer_box, Gtk.Box):
            return
        project_path = self._project_path or ""
        checkpoint_sha = None
        if self._project_handler and self._project_name:
            try:
                from models.review_state import ReviewState
                review_state = self._project_handler.get_review_state(self._project_name)
                if review_state and review_state.is_active():
                    checkpoint_sha = review_state.checkpoint_sha
            except Exception:
                pass  # Non-fatal — fall back to HEAD
        self._load_drawer_diff(file_path, drawer_box, project_path, checkpoint_sha)

    # ── Phase 4: Drawer Content — Diff Tab ────────────────────────────

    # BUG #1: Set of known binary file extensions for quick check
    _BINARY_EXTENSIONS: frozenset = frozenset({
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.so', '.dll', '.dylib', '.o', '.a', '.lib',
        '.pyc', '.pyo', '.pyd',
        '.zip', '.tar', '.gz', '.bz2', '.xz', '.zst', '.7z', '.rar',
        '.exe', '.bin', '.dat', '.db', '.sqlite', '.sqlite3',
        '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.wav', '.flac', '.ogg',
        '.ttf', '.otf', '.woff', '.woff2', '.eot',
    })

    @staticmethod
    def _is_binary_path(file_path: str) -> bool:
        """Return True if the file path has a known binary extension."""
        idx = file_path.rfind('.')
        if idx == -1:
            return False
        ext = file_path[idx:].lower()
        return ext in FileTree._BINARY_EXTENSIONS

    def _load_drawer_diff(self, file_path: str, drawer_box: Gtk.Box, project_path: str,
                          checkpoint_sha: str | None = None) -> None:
        """Load current diff for a file into the drawer box on background thread."""
        def _do():
            try:
                if checkpoint_sha:
                    result = diff_file_against_working_tree(
                        project_path, checkpoint_sha, file_path
                    )
                    subtitle = f"since checkpoint {checkpoint_sha[:7]}"
                else:
                    result = diff_working_tree(project_path, file_path)
                    subtitle = "since HEAD"
            except Exception as e:
                result = GitResult(success=False, stdout="", error=str(e))
                subtitle = ""
            GLib.idle_add(lambda: self._on_drawer_diff_loaded(
                result, subtitle, drawer_box, file_path
            ))
        threading.Thread(target=_do, daemon=True).start()

    def _on_drawer_diff_loaded(self, result, subtitle: str,
                               drawer_box: Gtk.Box, file_path: str) -> None:
        """Handle diff load result for drawer — update the Diff page on main thread."""
        # Check if drawer still exists (not cleaned up)
        if file_path not in self._drawer_paths:
            return

        # BUG #3: Verify the current drawer's child box is still this drawer_box
        # (not a stale reference from a reopened/replaced drawer)
        drawer_row = cast(FileTreeRow, self._drawer_paths.get(file_path))
        if drawer_row is not None:
            current_revealer = drawer_row.props.drawer_widget
            if current_revealer is not None:
                current_child = current_revealer.get_child()
                if current_child is not drawer_box:
                    return

        # Populate the diff_box inside the tabbed stack
        diff_box = getattr(drawer_box, '_diff_box', drawer_box)

        # Clear loading placeholder / previous content
        while diff_box.get_first_child() is not None:
            diff_box.remove(diff_box.get_first_child())

        if not result.success:
            error_lbl = Gtk.Label(label=f"Error: {result.error}")
            error_lbl.add_css_class("diff-viewer-subtitle")
            error_lbl.set_margin_top(12)
            error_lbl.set_margin_bottom(12)
            diff_box.append(error_lbl)
            return

        if not result.stdout.strip():
            no_changes_lbl = Gtk.Label(label="No changes to this file.")
            no_changes_lbl.add_css_class("diff-viewer-subtitle")
            no_changes_lbl.set_margin_top(12)
            no_changes_lbl.set_margin_bottom(12)
            diff_box.append(no_changes_lbl)
            return

        # BUG #1: Check for binary extension before attempting to parse diff
        if self._is_binary_path(file_path):
            bin_lbl = Gtk.Label(label="Binary file — not shown")
            bin_lbl.add_css_class("diff-viewer-subtitle")
            bin_lbl.set_margin_top(12)
            bin_lbl.set_margin_bottom(12)
            diff_box.append(bin_lbl)
            return

        parsed = parse_diff(result.stdout)
        if not parsed.files:
            no_changes_lbl = Gtk.Label(label="No changes to this file.")
            no_changes_lbl.add_css_class("diff-viewer-subtitle")
            no_changes_lbl.set_margin_top(12)
            no_changes_lbl.set_margin_bottom(12)
            diff_box.append(no_changes_lbl)
            return

        file_diff = parsed.files[0]

        if file_diff.is_binary:
            bin_lbl = Gtk.Label(label="Binary file — not shown")
            bin_lbl.add_css_class("diff-viewer-subtitle")
            bin_lbl.set_margin_top(12)
            bin_lbl.set_margin_bottom(12)
            diff_box.append(bin_lbl)
            return

        lang = get_lang_from_path(file_diff.display_path)
        diff_box.append(render_diff_hunks(file_diff.hunks, lang))

        # Store diff text for clipboard
        drawer_box._diff_text = result.stdout

    # ── Phase 5+ Stubs (History, Revert, Keyboard) ────────────────────

    def _load_history(self, file_path: str, history_list: Gtk.ListBox) -> None:
        """Load commit history for a file into the history list (background thread).

        Only loads once per drawer — subsequent clicks are no-ops unless
        the drawer is closed and re-opened (which creates a new drawer row).
        """
        if file_path not in self._drawer_paths:
            return  # Drawer was closed
        drawer_row: FileTreeRow = self._drawer_paths[file_path]
        if drawer_row.props.history_loaded:
            return  # Already loaded for this drawer

        drawer_row.props.history_loaded = True

        def _do():
            try:
                project_path = self._project_path or ""
                result = file_log(project_path, file_path, count=20)
            except Exception as e:
                result = GitResult(success=False, stdout="", error=str(e))
            entries: list[dict] = []
            if result.success and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    parts = line.split("\x1f")
                    if len(parts) == 3:
                        entries.append({
                            "sha": parts[0],
                            "date": parts[1],
                            "message": parts[2],
                        })
            GLib.idle_add(lambda: self._on_history_loaded(entries, history_list, file_path))

        threading.Thread(target=_do, daemon=True).start()

    def _on_history_loaded(self, entries: list[dict], history_list: Gtk.ListBox,
                           file_path: str) -> None:
        """Populate the history ListBox with commit entries (main thread)."""
        if file_path not in self._drawer_paths:
            return  # Drawer was closed

        # Clear previous rows
        while history_list.get_first_child() is not None:
            history_list.remove(history_list.get_first_child())

        if not entries:
            placeholder_row = Gtk.ListBoxRow()
            placeholder_row.set_activatable(False)
            placeholder_row.set_selectable(False)
            placeholder = Gtk.Label(label="No commit history for this file.")
            placeholder.set_halign(Gtk.Align.CENTER)
            placeholder.set_valign(Gtk.Align.CENTER)
            placeholder.add_css_class("diff-viewer-subtitle")
            placeholder_row.set_child(placeholder)
            history_list.append(placeholder_row)
            return

        for entry in entries:
            row = Gtk.ListBoxRow()
            row.sha = entry["sha"]
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.add_css_class("diff-history-row")

            sha_lbl = Gtk.Label(label=entry["sha"][:7])
            sha_lbl.add_css_class("diff-history-row-sha")

            date_lbl = Gtk.Label(label=entry["date"][:10])
            date_lbl.add_css_class("diff-history-row-date")

            msg_lbl = Gtk.Label(label=entry["message"])
            msg_lbl.add_css_class("diff-history-row-msg")
            msg_lbl.set_ellipsize(3)
            msg_lbl.set_hexpand(True)

            row_box.append(sha_lbl)
            row_box.append(date_lbl)
            row_box.append(msg_lbl)
            row.set_child(row_box)
            history_list.append(row)

    def _load_historical_diff(self, file_path: str, sha: str, stack: Gtk.Stack) -> None:
        """Load diff for a historical commit on a background thread."""
        if file_path not in self._drawer_paths:
            return
        drawer_row: FileTreeRow = self._drawer_paths[file_path]
        revealer = drawer_row.props.drawer_widget
        if revealer is None:
            return
        drawer_box = revealer.get_child()
        if drawer_box is None:
            return

        def _do():
            try:
                project_path = self._project_path or ""
                result = diff_file_against(project_path, sha, file_path)
            except Exception as e:
                result = GitResult(success=False, stdout="", error=str(e))
            GLib.idle_add(lambda: self._on_historical_diff_loaded(
                result, sha, file_path, stack, drawer_box))

        threading.Thread(target=_do, daemon=True).start()

    def _on_historical_diff_loaded(self, result, sha: str, file_path: str,
                                   stack: Gtk.Stack, drawer_box: Gtk.Box) -> None:
        """Render diff from a historical commit in the diff_box and show revert button."""
        if file_path not in self._drawer_paths:
            return
        drawer_row: FileTreeRow = self._drawer_paths[file_path]
        revealer = drawer_row.props.drawer_widget
        if revealer is None:
            return
        current_drawer_box = revealer.get_child()
        if current_drawer_box is not drawer_box:
            return  # Stale drawer_box

        # Switch to diff view
        stack.set_visible_child_name("diff")

        diff_box = getattr(drawer_box, '_diff_box', None)
        if diff_box is None:
            return

        while diff_box.get_first_child() is not None:
            diff_box.remove(diff_box.get_first_child())

        if not result.success:
            error_lbl = Gtk.Label(label=f"Error: {result.error}")
            error_lbl.add_css_class("diff-viewer-subtitle")
            error_lbl.set_margin_top(12)
            error_lbl.set_margin_bottom(12)
            diff_box.append(error_lbl)
            return

        if not result.stdout.strip():
            no_changes_lbl = Gtk.Label(label="No changes since this commit.")
            no_changes_lbl.add_css_class("diff-viewer-subtitle")
            no_changes_lbl.set_margin_top(12)
            no_changes_lbl.set_margin_bottom(12)
            diff_box.append(no_changes_lbl)
            return

        parsed = parse_diff(result.stdout)
        if not parsed.files:
            no_changes_lbl = Gtk.Label(label="No changes since this commit.")
            no_changes_lbl.add_css_class("diff-viewer-subtitle")
            no_changes_lbl.set_margin_top(12)
            no_changes_lbl.set_margin_bottom(12)
            diff_box.append(no_changes_lbl)
            return

        file_diff = parsed.files[0]

        if file_diff.is_binary:
            bin_lbl = Gtk.Label(label="Binary file — not shown")
            bin_lbl.add_css_class("diff-viewer-subtitle")
            bin_lbl.set_margin_top(12)
            bin_lbl.set_margin_bottom(12)
            diff_box.append(bin_lbl)
            return

        lang = get_lang_from_path(file_diff.display_path)
        diff_box.append(render_diff_hunks(file_diff.hunks, lang))

        # Store selected sha on drawer for revert
        drawer_row.props.history_selected_sha = sha

        # Store diff text for clipboard
        drawer_box._diff_text = result.stdout

        # Show revert button
        revert_btn = getattr(drawer_box, '_revert_btn', None)
        if revert_btn is not None:
            revert_btn.set_visible(True)

    def _on_drawer_revert_clicked(self, file_path: str, drawer_box: Gtk.Box) -> None:
        """Show confirmation dialog before reverting a file to a historical commit."""
        if file_path not in self._drawer_paths:
            return
        drawer_row: FileTreeRow = self._drawer_paths[file_path]
        target_sha = drawer_row.props.history_selected_sha
        if not target_sha or not self._project_handler or not self._project_name:
            return

        root = self.get_root()
        dialog = Gtk.MessageDialog(
            transient_for=root if isinstance(root, Gtk.Window) else None,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Revert {file_path}?",
            secondary_text=f"This will restore the file to its state from commit "
                           f"{target_sha[:7]}. Any uncommitted changes will be lost."
        )
        dialog.connect("response", lambda d, r:
            self._on_drawer_revert_confirmed(d, r, file_path, target_sha, drawer_box))
        dialog.present()

    def _on_drawer_revert_confirmed(self, dialog, response_id: int, file_path: str,
                                    target_sha: str, drawer_box: Gtk.Box) -> None:
        """Handle revert confirmation — call ProjectHandler and reload diff."""
        # BUG #2: Guard against None dialog
        if dialog is not None:
            dialog.destroy()
        if response_id != Gtk.ResponseType.YES:
            return

        # Validate drawer still exists
        if file_path not in self._drawer_paths:
            return
        drawer_row: FileTreeRow = self._drawer_paths[file_path]
        revealer = drawer_row.props.drawer_widget
        if revealer is None:
            return
        current_drawer_box = revealer.get_child()
        if current_drawer_box is not drawer_box:
            return  # Stale drawer_box

        # BUG #1: Wrap revert in try/except — show error in diff_box on failure
        if self._project_name:
            try:
                self._project_handler.revert_file_to_sha(self._project_name, file_path, target_sha)
            except Exception as e:
                diff_box = getattr(drawer_box, '_diff_box', None)
                if diff_box is not None:
                    while diff_box.get_first_child() is not None:
                        diff_box.remove(diff_box.get_first_child())
                    error_lbl = Gtk.Label(label=f"Revert failed: {e}")
                    error_lbl.add_css_class("diff-viewer-subtitle")
                    error_lbl.set_margin_top(12)
                    error_lbl.set_margin_bottom(12)
                    diff_box.append(error_lbl)
                return

        # Switch back to Diff tab
        diff_tab = getattr(drawer_box, '_diff_tab', None)
        if diff_tab is not None:
            diff_tab.set_active(True)

        # BUG #4: Reset state to prevent accidental double-revert
        drawer_row.props.history_selected_sha = None
        revert_btn = getattr(drawer_box, '_revert_btn', None)
        if revert_btn is not None:
            revert_btn.set_visible(False)

        # Reset history tab so it can be re-fetched after revert
        drawer_row.props.history_loaded = False

        # Reload current diff content
        self._load_current_diff(file_path)

    def _load_current_diff(self, file_path: str) -> None:
        """Reload the current working-tree diff for a file (e.g. after revert)."""
        if file_path not in self._drawer_paths:
            return
        drawer_row = cast(FileTreeRow, self._drawer_paths.get(file_path))
        if drawer_row is None:
            return
        revealer = drawer_row.props.drawer_widget
        if revealer is None:
            return
        drawer_box = revealer.get_child()
        if drawer_box is None or not isinstance(drawer_box, Gtk.Box):
            return

        # Clear existing diff content
        diff_box = getattr(drawer_box, '_diff_box', None)
        if diff_box is not None:
            while diff_box.get_first_child() is not None:
                diff_box.remove(diff_box.get_first_child())

        # Resolve checkpoint SHA
        project_path = self._project_path or ""
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

    def _on_history_key_pressed(self, keyval: int, history_list: Gtk.ListBox) -> bool:
        """Handle Enter key in history list to activate selected row."""
        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            selected = history_list.get_selected_row()
            if selected is not None and isinstance(selected, Gtk.ListBoxRow) and selected.get_activatable():
                history_list.emit("row-activated", selected)
                return True
        return False

    def _on_drawer_key_pressed(self, keyval: int, keycode: int, state: Gdk.ModifierType,
                               file_path: str, drawer_box: Gtk.Box) -> bool:
        """Handle keyboard shortcuts in the drawer: Escape closes, Ctrl+C copies."""
        # Escape: close the drawer
        if keyval == Gdk.KEY_Escape:
            if file_path not in self._drawer_paths:
                return False
            drawer_row: FileTreeRow = self._drawer_paths[file_path]
            revealer = drawer_row.props.drawer_widget
            if revealer is None or not revealer.get_reveal_child():
                return False
            self._toggle_drawer(file_path)
            self._column_view.grab_focus()
            return True

        # Ctrl+C: copy diff text to clipboard
        if (keyval == Gdk.KEY_c or keyval == Gdk.KEY_C) and (state & Gdk.ModifierType.CONTROL_MASK):
            # BUG #1: Only return True if copy succeeded
            return self._copy_drawer_diff_to_clipboard(drawer_box)

        return False

    def _on_copy_diff_to_clipboard(self, file_path: str, drawer_box: Gtk.Box) -> bool:
        """Button click handler — delegates to _copy_drawer_diff_to_clipboard.
        Returns True if the copy succeeded, False otherwise.
        """
        return self._copy_drawer_diff_to_clipboard(drawer_box)

    def _copy_drawer_diff_to_clipboard(self, drawer_box: Gtk.Box) -> bool:
        """Copy the diff text from a drawer to the system clipboard.
        Returns True if the copy succeeded, False otherwise.
        """
        diff_text = getattr(drawer_box, '_diff_text', None)
        if not diff_text:
            return False
        # BUG #2: None check for display
        display = Gdk.Display.get_default()
        if display is None:
            return False
        clipboard = display.get_clipboard()
        clipboard.set(diff_text)
        return True

    def _update_drawer_prefix(self, model, it, file_path: str, is_open: bool) -> bool:
        """No-op in ColumnView. The expander button label is set by the factory."""
        return False

    # ── Phase 2: Directory Expand/Collapse ──────────────────────────────

    def _find_row_index(self, row: FileTreeRow) -> Optional[int]:
        """Find the current index of a FileTreeRow in the store.

        Returns None if the row is no longer in the store (e.g. deleted
        by collapse or project switch). Linear scan — safe for typical tree
        sizes. (BUG #2)
        """
        n = self._store.get_n_items()
        for i in range(n):
            if self._store.get_item(i) is row:
                return i
        return None

    def _on_expander_clicked(self, row: FileTreeRow, position: int) -> None:
        """Handle expander button click for a directory row."""
        if position < 0 or position >= self._store.get_n_items():
            return
        # Verify the row at this position is still the one we expect
        current = self._store.get_item(position)
        if current is not row:
            return
        if row.props.expanded:
            self._collapse_directory(position)
        else:
            self._expand_directory(position)

    def _expand_directory(self, row_index: int) -> None:
        """Expand a directory row: load children on background thread, insert into store."""
        if row_index < 0 or row_index >= self._store.get_n_items():
            return
        row: FileTreeRow = self._store.get_item(row_index)
        if not row.props.is_dir or row.props.expanded:
            return

        # BUG #7: Increment request ID, capture in closure
        self._current_request_id += 1
        request_id = self._current_request_id

        # Mark as expanded immediately for UI feedback
        row.props.expanded = True
        parent_path = row.props.full_path
        parent_depth = row.props.depth

        # BUG #8: Insert loading spinner row
        loading_row = FileTreeRow(
            display_name="Loading...",
            full_path="",
            is_dir=False,
            depth=parent_depth + 1,
        )
        self._store.insert(row_index + 1, loading_row)

        def _do():
            try:
                entries = scan_directory(parent_path)
            except Exception as e:
                entries = [(f"[error: {type(e).__name__}: {e}]", "", False, 0, 0)]
            # BUG #1: Capture loading_row object identity, not position.
            # Store mutations (sibling expand/collapse) can shift positions.
            _loading_row = loading_row
            GLib.idle_add(lambda: self._on_directory_loaded(
                entries, _loading_row, row_index, parent_depth, request_id
            ))

        threading.Thread(target=_do, daemon=True).start()

    def _on_directory_loaded(self, entries, loading_row: FileTreeRow, row_index: int, parent_depth: int, request_id: int) -> None:
        """Handle directory scan result on main thread. Guard against stale requests.

        Unconditionally removes the loading spinner row (by object identity)
        before any early return to prevent orphan "Loading..." rows (BUG #1).
        """
        # Unconditionally remove loading spinner row by object identity
        # Walk the store to find it — survives intervening store mutations
        n = self._store.get_n_items()
        for i in range(n):
            if self._store.get_item(i) is loading_row:
                self._store.remove(i)
                break

        # BUG #7: Ignore stale callbacks
        if request_id != self._current_request_id:
            return

        if row_index < 0 or row_index >= self._store.get_n_items():
            return
        parent_row: FileTreeRow = self._store.get_item(row_index)
        if not parent_row.props.is_dir or not parent_row.props.expanded:
            # Parent was collapsed; loading row already removed above
            return

        # Insert real children
        insert_pos = row_index + 1
        for entry_name, full_path, is_dir, size_bytes, mtime_ns in entries:
            icon = get_icon_for_path(full_path, is_dir)
            rel_path = os.path.relpath(full_path, self._project_path) if self._project_path else full_path
            raw_status = self._git_status_map.get(rel_path, "")
            child = FileTreeRow(
                display_name=entry_name,
                full_path=full_path,
                is_dir=is_dir,
                depth=parent_depth + 1,
                has_children=is_dir,
                expanded=False,
                file_size=0 if is_dir else size_bytes,
                file_size_display="—" if is_dir else format_size(size_bytes),
                modified_time=mtime_ns // 1_000_000_000 if mtime_ns else 0,
                modified_display=format_mtime(mtime_ns) if mtime_ns else "—",
                git_status=raw_status,
                git_status_display=git_status_to_display(raw_status),
                mime_type=guess_mime(full_path),
                icon_name=icon.icon_name,
                icon_color_class=icon.color_class,
            )
            self._store.insert(insert_pos, child)
            insert_pos += 1

        # SortListModel auto-sorts on store mutation — no need for explicit _apply_sort

    def _collapse_directory(self, row_index: int) -> None:
        """Collapse a directory row: remove all descendants with greater depth."""
        if row_index < 0 or row_index >= self._store.get_n_items():
            return
        row: FileTreeRow = self._store.get_item(row_index)
        if not row.props.is_dir or not row.props.expanded:
            return

        parent_depth = row.props.depth
        row.props.expanded = False

        # BUG #7: Increment request ID to invalidate any in-flight async loads
        self._current_request_id += 1

        # Remove all descendants with depth > parent_depth
        i = row_index + 1
        while i < self._store.get_n_items():
            descendant = self._store.get_item(i)
            if descendant.props.depth > parent_depth:
                self._store.remove(i)
                # Don't increment i — next item shifted down
            else:
                break

    # ── Row Activation (ColumnView ::activate signal) ─────────────────────

    def _on_row_activated(self, column_view: Gtk.ColumnView, position: int) -> None:
        """
        Handle row activation (double-click or Enter) on the ColumnView.

        Directories toggle expand/collapse, files toggle inline drawer.
        """
        if position < 0 or position >= self._store.get_n_items():
            return
        row: FileTreeRow = self._store.get_item(position)
        if row.props.is_dir:
            # Directory — expand/collapse
            if row.props.expanded:
                self._collapse_directory(position)
            else:
                self._expand_directory(position)
        elif not row.props.is_drawer:
            # File — toggle drawer
            self._toggle_drawer(row.props.full_path)
        # Drawer rows are not activatable

    # ── Keyboard Navigation ───────────────────────────────────────────────

    def _on_key_pressed(self, controller, keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle keyboard shortcuts at the ColumnView level.

        Esc closes the active drawer (any open drawer, not just selected).
        Ctrl+C copies the current diff from the selected drawer row.
        """
        selected_pos = self._selection.get_selected()
        if selected_pos == Gtk.INVALID_LIST_POSITION:
            return False
        if selected_pos < 0 or selected_pos >= self._store.get_n_items():
            return False

        # BUG #3: Escape closes any active drawer — not just the selected row.
        # Iterate the store to find any open drawer and close it.
        if keyval == Gdk.KEY_Escape:
            n = self._store.get_n_items()
            for i in range(n):
                row = cast(FileTreeRow, self._store.get_item(i))
                if row.props.is_drawer and row.props.drawer_widget is not None:
                    revealer = row.props.drawer_widget
                    if revealer.get_reveal_child():
                        file_path = self._find_file_path_for_drawer(i)
                        if file_path:
                            self._toggle_drawer(file_path)
                            self._column_view.grab_focus()
                            return True
            return False

        # Ctrl+C: copy the current diff from the selected drawer row
        if (keyval == Gdk.KEY_c or keyval == Gdk.KEY_C) and (state & Gdk.ModifierType.CONTROL_MASK):
            row: FileTreeRow = self._store.get_item(selected_pos)
            if row.props.is_drawer and row.props.drawer_widget is not None:
                drawer_box = row.props.drawer_widget.get_child()
                if drawer_box is not None:
                    # BUG #1: Only return True if copy succeeded
                    return self._copy_drawer_diff_to_clipboard(drawer_box)
            return False

        return False

    def _find_file_path_for_drawer(self, drawer_pos: int) -> Optional[str]:
        """Find the file_path for a drawer row by walking backwards to find the file row."""
        for i in range(drawer_pos - 1, -1, -1):
            row: FileTreeRow = self._store.get_item(i)
            if not row.props.is_dir and not row.props.is_drawer:
                return row.props.full_path
        return None

    # ── Search ────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry):
        """Route search to picker or tree handler."""
        if self._project_path is not None:
            # Tree mode — debounced filter
            self._on_search_changed_tree_cb(entry.get_text())
        else:
            # Picker mode — existing behavior
            query = entry.get_text()
            if self._project_list_handler:
                self._project_list_handler.search(query)
                self._show_project_picker()

    def _on_search_changed_tree_cb(self, query: str) -> None:
        """Debounced tree search. 150ms via GLib.timeout_add (BUG #9)."""
        if self._search_timeout_id is not None:
            GLib.source_remove(self._search_timeout_id)

        def _apply():
            self._apply_filter(query)
            # BUG #35: update match count in placeholder
            if self._filter_model and self._store:
                count = self._filter_model.get_n_items()
                total = self._store.get_n_items()
                if query and total > 0:
                    if count == 0:
                        self._search_entry.set_placeholder_text("No matches")
                    else:
                        self._search_entry.set_placeholder_text(f"{count} of {total} files")
            self._search_timeout_id = None
            return GLib.SOURCE_REMOVE

        self._search_timeout_id = GLib.timeout_add(150, _apply)

    def _on_back_clicked(self, button):
        """Navigate back to the project picker."""
        self.navigate_back()

    # ── Right-Click Context Menu (Copy Path / Copy File) ──────────────────

    def _on_tree_row_right_click(self, ctrl, n_press, x, y, widget) -> None:
        """
        Right-click on a file tree row — show the context popover menu.

        Args:
            ctrl:    Gtk.GestureClick (sender).
            n_press: int — number of presses (only respond to single click).
            x, y:    float — local click coordinates (unused).
            widget:  FileTreeRowWidget — the right-clicked widget.
        """
        if n_press != 1:
            return

        # Read the bound row LIVE at click time — never capture in closure.
        # This avoids stale-row bugs from ColumnView recycling.
        row = widget._bound_row
        if row is None:
            return  # unbind/rebind window

        # Skip drawer rows (inline containers, not navigable files/dirs)
        if row.props.is_drawer:
            return

        # Skip loading rows (empty path)
        path = row.props.full_path
        if not path:
            return

        popover = Gtk.Popover()
        popover.set_parent(widget)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_margin_top(6)
        vbox.set_margin_bottom(6)
        vbox.set_margin_start(6)
        vbox.set_margin_end(6)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        # Row 1: Copy Path (always shown — for files and directories)
        copy_path_row = Gtk.ListBoxRow()
        copy_path_row.set_activatable(True)
        copy_path_row.set_selectable(False)
        copy_path_row._action = "copy_path"
        copy_path_label = Gtk.Label(label="Copy Path", xalign=0)
        copy_path_label.set_margin_top(4)
        copy_path_label.set_margin_bottom(4)
        copy_path_label.set_margin_start(8)
        copy_path_label.set_margin_end(8)
        copy_path_row.set_child(copy_path_label)
        list_box.append(copy_path_row)

        # Row 2: Copy File (only shown for files, not directories)
        if not row.props.is_dir:
            copy_file_row = Gtk.ListBoxRow()
            copy_file_row.set_activatable(True)
            copy_file_row.set_selectable(False)
            copy_file_row._action = "copy_file"
            copy_file_label = Gtk.Label(label="Copy File", xalign=0)
            copy_file_label.set_margin_top(4)
            copy_file_label.set_margin_bottom(4)
            copy_file_label.set_margin_start(8)
            copy_file_label.set_margin_end(8)
            copy_file_row.set_child(copy_file_label)
            list_box.append(copy_file_row)

        list_box.connect("row-activated", self._on_tree_menu_row_activated, popover, row)
        vbox.append(list_box)
        popover.set_child(vbox)
        popover.connect("closed", lambda *_: popover.unparent())
        popover.popup()

    def _on_tree_menu_row_activated(self, _lb, menu_row, popover, source_row) -> None:
        """
        One of "Copy Path" / "Copy File" was clicked. Dispatch and dismiss the popover.

        Dispatch uses the menu_row._action attribute (set at row build time), NOT
        the label text — robust to i18n.
        """
        popover.popdown()
        action = getattr(menu_row, "_action", None)
        if action == "copy_path":
            self._on_copy_tree_path(source_row)
        elif action == "copy_file":
            self._on_copy_tree_file(source_row)
        # Unknown action → no-op (defensive).

    def _on_copy_tree_path(self, row) -> None:
        """Copy the absolute path of the right-clicked row to the clipboard."""
        path = row.props.full_path if hasattr(row, 'props') else None
        if not path:
            return
        self._copy_text_to_clipboard(path)
        self._show_tree_copy_status("Copied path")

    def _on_copy_tree_file(self, row) -> None:
        """Copy the file content of the right-clicked row to the clipboard.

        Handles binary files gracefully: on UnicodeDecodeError, copies a
        notice message instead of crashing.
        """
        path = row.props.full_path if hasattr(row, 'props') else None
        if not path:
            return
        try:
            from pathlib import Path
            content = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = "<binary file — not copied>"
            # Stay consistent with the drawer's "Binary file — not shown" wording.
        except Exception:
            return  # I/O error — silently skip (no crash)
        self._copy_text_to_clipboard(content)
        self._show_tree_copy_status("Copied file")

    def _copy_text_to_clipboard(self, text: str) -> None:
        """Copy text to the system clipboard using GTK4 clipboard API."""
        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()
        clipboard.set(text)

    def _show_tree_copy_status(self, message: str) -> None:
        """Show a transient confirmation in the file tree header for ~2.5s."""
        if self._tree_copy_status_label is None:
            return
        self._tree_copy_status_label.set_text(message)
        self._tree_copy_status_label.set_visible(True)
        # Cancel any pending clear, then schedule a new one.
        if self._tree_copy_status_timeout_id is not None:
            try:
                GLib.source_remove(self._tree_copy_status_timeout_id)
            except Exception:
                pass
            self._tree_copy_status_timeout_id = None

        def _clear():
            if self._tree_copy_status_label is not None:
                self._tree_copy_status_label.set_text("")
                self._tree_copy_status_label.set_visible(False)
            self._tree_copy_status_timeout_id = None
            return GLib.SOURCE_REMOVE

        self._tree_copy_status_timeout_id = GLib.timeout_add(2500, _clear)