# ui/views/file_tree.py
# File tree widget — GTK4 TreeView with lazy-loading directory expansion.
#
# Single-click expands/collapses directories, loads children on first expand.
# Fires on_file_selected(path) callback when a file is activated.
#
# Public API:
#   tree = FileTree(on_file_selected=None)
#   tree.load_project(name, path)  # load a project root
#   tree.navigate_back()            # return to project picker

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

import time

from utils.projects import load_projects, scan_directory


class FileTree(Gtk.Box):
    """
    File tree browser widget.
    Displays project list, or directory tree when a project is selected.
    """

    def __init__(self, on_file_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_file_selected = on_file_selected
        self._on_project_opened = None

        # Project state
        self._project_name = None
        self._project_path = None
        # Double-click tracking for picker mode
        self._pending_project_row = None
        self._last_click_time = 0

        # Project state
        self._project_name = None
        self._project_path = None
        self._project_history = []  # stack of paths for back navigation

        # The notebook page container (set by LeftPanel)
        self._page = None

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
        self._title_lbl.set_hexpand(True)
        self._title_lbl.add_css_class("project-selector-title")

        self._header.append(self._back_btn)
        self._header.append(self._folder_icon)
        self._header.append(self._title_lbl)

        # ── Tree view ──────────────────────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # TreeStore columns: (display_name, full_path, is_dir, is_loaded)
        self._store = Gtk.TreeStore.new([str, str, bool, bool])
        self._tree = Gtk.TreeView(model=self._store)
        self._tree.set_show_expanders(True)
        self._tree.set_activate_on_single_click(True)
        self._tree.set_headers_visible(False)
        self._tree.connect("row-activated", self._on_row_activated)
        self._tree.connect("row-expanded", self._on_row_expanded)

        renderer = Gtk.CellRendererText()
        renderer.set_padding(4, 2)
        column = Gtk.TreeViewColumn("Files", renderer, text=0)
        column.set_expand(True)
        self._tree.append_column(column)

        scroll.set_child(self._tree)
        self.append(self._header)
        self.append(scroll)

        # Load project picker on init
        self._show_project_picker()

    # ── Public API ────────────────────────────────────────────────────────

    def load_project(self, name, path):
        """Load a project root and show its directory tree."""
        self._pending_project_row = None
        self._project_name = name
        if self._on_project_opened:
            self._on_project_opened(name, path)
        self._project_path = path
        self._project_history.clear()
        self._show_tree(name, path)

    def navigate_back(self):
        """Return to the project picker."""
        self._pending_project_row = None
        self._project_name = None
        self._project_path = None
        self._project_history.clear()
        self._show_project_picker()

    def set_page(self, page):
        """Set the notebook page container (for clearing content)."""
        self._page = page

    def set_on_project_opened(self, cb):
        """Set callback for when a project is opened (name, path)."""
        self._on_project_opened = cb

    # ── Private ───────────────────────────────────────────────────────────

    def _show_project_picker(self):
        """Show the list of projects."""
        self._pending_project_row = None
        self._store.clear()
        self._back_btn.set_visible(False)
        self._folder_icon.set_visible(False)
        self._title_lbl.set_text("Projects")
        self._title_lbl.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 11">'
            'Projects</span>'
        )

        projects = load_projects()
        if not projects:
            self._store.append(None, [
                'No projects found', '', False, True
            ])
            return

        for name, full_path in projects:
            self._store.append(None, [name, full_path, True, True])

    def _show_tree(self, name, path):
        """Show the directory tree for a project."""
        self._store.clear()
        self._back_btn.set_visible(True)
        self._folder_icon.set_visible(True)
        self._title_lbl.set_markup(f"<b>{name}</b>")
        self._title_lbl.set_use_markup(True)

        entries = scan_directory(path)
        for entry_name, full_path, is_dir in entries:
            prefix = "📁 " if is_dir else "  "
            parent = self._store.append(None, [
                prefix + entry_name, full_path, is_dir, False
            ])
            if is_dir:
                # Placeholder row — children loaded on first expand
                self._store.append(parent, ["…", "", True, False])

    def _on_row_activated(self, tree, path, column):
        """Single-click expands dirs in tree mode; double-click required to load a project."""
        model = tree.get_model()
        it = model.get_iter(path)
        if it is None:
            return

        display_name = model.get_value(it, 0).lstrip("📁 ").lstrip("  ")
        full_path = model.get_value(it, 1)
        is_dir = model.get_value(it, 2)
        parent_it = model.iter_parent(it)
        is_top_level = parent_it is None

        if is_dir:
            if is_top_level and self._project_path is None:
                # Picker mode — require double-click to load project
                now = time.time()
                if (self._pending_project_row == full_path
                        and now - self._last_click_time < 0.5):
                    # Double-click — load project
                    self._pending_project_row = None
                    self.load_project(display_name, full_path)
                else:
                    # First click — arm pending
                    self._pending_project_row = full_path
                    self._last_click_time = now
            elif tree.row_expanded(path):
                tree.collapse_row(path)
            else:
                tree.expand_row(path, open_all=False)
        else:
            if self._on_file_selected:
                self._on_file_selected(full_path)

    def _on_row_expanded(self, tree, it, path):
        """Lazy load children on first expand."""
        model = tree.get_model()
        child_it = model.iter_children(it)
        if child_it is None:
            return

        first_name = model.get_value(child_it, 0)
        if first_name != "…":
            return  # already loaded

        # Remove placeholder
        model.remove(child_it)

        # Load real children
        parent_path = model.get_value(it, 1)
        entries = scan_directory(parent_path)
        for entry_name, full_path, is_dir in entries:
            prefix = "📁 " if is_dir else "  "
            child = model.append(it, [prefix + entry_name, full_path, is_dir, False])
            if is_dir:
                model.append(child, ["…", "", True, False])

    def _on_back_clicked(self, button):
        """Navigate back to the project picker."""
        self.navigate_back()
