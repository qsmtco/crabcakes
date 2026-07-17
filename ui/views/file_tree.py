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

    def __init__(self, display_name: str = "", full_path: str = "",
                 is_dir: bool = False, is_drawer: bool = False,
                 depth: int = 0, expanded: bool = False,
                 has_children: bool = False,
                 drawer_widget=None, is_open: bool = False,
                 diff_text: str = "", history_selected_sha=None,
                 history_loaded: bool = False):
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

        # Icon
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

    def set_icon(self, is_dir: bool, is_drawer: bool) -> None:
        """Set icon based on row type."""
        if is_drawer:
            self._icon.set_from_icon_name("text-x-generic-symbolic")
        elif is_dir:
            self._icon.set_from_icon_name("folder-symbolic")
        else:
            self._icon.set_from_icon_name("text-x-generic-symbolic")

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
        """Full cleanup — disconnect signals, detach drawer."""
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

    def _on_bind(self, factory: 'FileTreeFactory', list_item: Gtk.ListItem) -> None:
        row = cast(FileTreeRow, list_item.get_item())
        widget: FileTreeRowWidget = list_item.get_child()

        widget.bind_row(row)
        widget.set_depth(row.props.depth)
        widget.set_expanded(row.props.expanded)
        widget.set_label(row.props.display_name)
        widget.set_icon(row.props.is_dir, row.props.is_drawer)

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

        self._header.append(self._back_btn)
        self._header.append(self._folder_icon)
        self._header.append(self._title_lbl)
        self._header.append(self._search_entry)

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
        # BUG #4: Increment request ID to invalidate any in-flight async loads
        self._current_request_id += 1
        # Clear list store
        while self._store.get_n_items() > 0:
            self._store.remove(0)
        self._drawer_paths.clear()
        self._loaded_drawers.clear()
        self._last_toggle_per_file.clear()
        # Clear search when returning to picker
        if self._project_list_handler:
            self._project_list_handler.clear_search()
        # Block signal to prevent _on_search_changed from firing while FileTree
        # is still inside the nested notebook (would build cards in wrong parent).
        self._search_entry.handler_block(self._search_changed_handler_id)
        self._search_entry.set_text("")
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
        # BUG #4: Increment request ID to invalidate any in-flight async loads
        self._current_request_id += 1
        # Clear store before replacing content
        while self._store.get_n_items() > 0:
            self._store.remove(0)
        self._drawer_paths.clear()
        self._loaded_drawers.clear()
        self._last_toggle_per_file.clear()
        self._back_btn.set_visible(False)
        self._folder_icon.set_visible(False)
        self._title_lbl.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 11">Projects</span>'
        )
        self._search_entry.set_visible(True)
        # Rebuild title to not expand so search entry gets space
        self._title_lbl.set_hexpand(False)

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
        # BUG #4: Increment request ID to invalidate any in-flight async loads
        self._current_request_id += 1
        # Clear store with while-loop to ensure full removal
        while self._store.get_n_items() > 0:
            self._store.remove(0)
        self._drawer_paths.clear()
        self._loaded_drawers.clear()
        self._last_toggle_per_file.clear()
        self._back_btn.set_visible(True)
        self._folder_icon.set_visible(True)
        safe_name = escape_for_pango(name)
        self._title_lbl.set_markup(f"<b>{safe_name}</b>")
        self._title_lbl.set_use_markup(True)
        self._title_lbl.set_hexpand(True)
        self._search_entry.set_visible(False)

        # Populate root entries
        try:
            entries = scan_directory(path)
        except Exception as e:
            entries = [(f"[error: {type(e).__name__}: {e}]", "", False)]
        for entry_name, full_path, is_dir in entries:
            row = FileTreeRow(
                display_name=entry_name,
                full_path=full_path,
                is_dir=is_dir,
                depth=0,
                has_children=is_dir,
                expanded=False,
            )
            self._store.append(row)

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
        drawer_box.set_margin_start(20)
        drawer_box.set_margin_end(8)
        drawer_box.set_margin_top(4)
        drawer_box.set_margin_bottom(4)

        # Tab bar
        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tab_bar.add_css_class("file-tree-drawer-tab-bar")
        tab_bar.set_margin_bottom(4)

        diff_tab = Gtk.ToggleButton(label="Diff")
        diff_tab.set_active(True)
        history_tab = Gtk.ToggleButton(label="History")
        history_tab.set_group(diff_tab)

        tab_bar.append(diff_tab)
        tab_bar.append(history_tab)
        drawer_box.append(tab_bar)

        # Stack
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_vexpand(True)

        # Diff page
        diff_scroll = Gtk.ScrolledWindow()
        diff_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
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
        history_list = Gtk.ListBox()
        history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        history_scroll.set_child(history_list)
        stack.add_named(history_scroll, "history")

        drawer_box.append(stack)

        # Action bar
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.add_css_class("diff-viewer-action-bar")
        action_bar.set_margin_top(8)
        action_bar.set_margin_bottom(8)
        action_bar.set_margin_start(20)
        action_bar.set_margin_end(8)

        revert_btn = Gtk.Button(label="Revert file to this version")
        revert_btn.add_css_class("diff-viewer-revert-btn")
        revert_btn.set_visible(False)

        copy_btn = Gtk.Button(label="Copy diff")
        copy_btn.add_css_class("diff-viewer-copy-btn")

        spacer = Gtk.Label()
        spacer.set_hexpand(True)

        action_bar.append(revert_btn)
        action_bar.append(spacer)
        action_bar.append(copy_btn)
        drawer_box.append(action_bar)

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

        # BUG #3: Verify that the current drawer's widget child is still this drawer_box
        drawer_row = cast(FileTreeRow, self._drawer_paths.get(file_path))
        if drawer_row is not None:
            current_revealer = drawer_row.props.drawer_widget
            if current_revealer is not None:
                current_child = current_revealer.get_child()
                if current_child is not None and current_child is not drawer_box:
                    return  # Stale drawer_box — belongs to a different revealer/reopened drawer

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
        """(Phase 6+) Stub — load commit history for a file on background thread."""
        pass

    def _on_history_loaded(self, entries: list[dict], history_list: Gtk.ListBox,
                           file_path: str) -> None:
        """(Phase 6+) Stub — populate the history ListBox with commit entries."""
        pass

    def _load_historical_diff(self, file_path: str, sha: str, stack: Gtk.Stack) -> None:
        """(Phase 6+) Stub — load diff for a historical commit on background thread."""
        pass

    def _on_historical_diff_loaded(self, result, sha: str, file_path: str,
                                   stack: Gtk.Stack) -> None:
        """(Phase 6+) Stub — render historical diff and show revert button."""
        pass

    def _on_drawer_revert_clicked(self, file_path: str, drawer_box: Gtk.Box) -> None:
        """(Phase 7+) Stub — show confirmation dialog before reverting a file."""
        pass

    def _on_drawer_revert_confirmed(self, dialog, response_id: int, file_path: str,
                                    target_sha: str, drawer_box: Gtk.Box) -> None:
        """(Phase 7+) Stub — handle revert confirmation, call ProjectHandler."""
        pass

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
        """(Phase 8+) Stub — handle Enter key in history list."""
        return False

    def _on_drawer_key_pressed(self, keyval: int, keycode: int, state: Gdk.ModifierType,
                               file_path: str, drawer_box: Gtk.Box) -> bool:
        """(Phase 8+) Stub — handle keyboard shortcuts in the drawer."""
        return False

    def _on_copy_diff_to_clipboard(self, file_path: str, drawer_box: Gtk.Box) -> None:
        """(Phase 8+) Stub — copy diff text to clipboard from button click."""
        pass

    def _update_drawer_prefix(self, model, it, file_path: str, is_open: bool) -> bool:
        """(Phase 4+) Stub — update tree row display name prefix (▶/▼)."""
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
                entries = [(f"[error: {type(e).__name__}: {e}]", "", False)]
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
        for entry_name, full_path, is_dir in entries:
            child = FileTreeRow(
                display_name=entry_name,
                full_path=full_path,
                is_dir=is_dir,
                depth=parent_depth + 1,
                has_children=is_dir,
                expanded=False,
            )
            self._store.insert(insert_pos, child)
            insert_pos += 1

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

    def _on_key_pressed(self, controller: Gtk.EventControllerKey, keyval: int,
                        keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle keyboard shortcuts on the ColumnView.

        Phase 2+: Escape closes drawer, Ctrl+C copies diff.
        """
        return False

    # ── Search ────────────────────────────────────────────────────────────

    def _on_search_changed(self, entry):
        """Filter project cards on search-changed."""
        query = entry.get_text()
        if self._project_list_handler:
            self._project_list_handler.search(query)
            self._show_project_picker()

    def _on_back_clicked(self, button):
        """Navigate back to the project picker."""
        self.navigate_back()