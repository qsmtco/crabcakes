# ui/views/file_tree.py
# File tree widget — GTK4 TreeView with lazy-loading directory expansion.
#
# Single-click expands/collapses directories, loads children on first expand.
# Double-click on a file toggles the inline diff drawer.
# Fires on_file_selected(path) callback when a file is activated (fallback).
#
# Public API:
#   tree = FileTree(on_file_selected=None)
#   tree.load_project(name, path)  # load a project root
#   tree.navigate_back()            # return to project picker

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

import time

from utils.projects import scan_directory


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
        # The notebook page container (set by LeftPanel)
        self._page = None

        # Drawer state: file_path -> (revealer, label, is_open)
        self._drawers: dict[str, tuple[Gtk.Revealer, str, bool]] = {}

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

        # ── Tree view ──────────────────────────────────────────────────────
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # TreeStore columns: (display_name, full_path, is_dir, is_loaded)
        self._store = Gtk.TreeStore.new([str, str, bool, bool])
        self._tree = Gtk.TreeView(model=self._store)
        self._tree.set_show_expanders(True)
        self._tree.set_activate_on_single_click(False)
        self._tree.set_headers_visible(False)
        self._tree.connect("row-activated", self._on_row_activated)
        self._tree.connect("row-expanded", self._on_row_expanded)

        renderer = Gtk.CellRendererText()
        renderer.set_padding(4, 2)
        column = Gtk.TreeViewColumn("Files", renderer, text=0)
        column.set_expand(True)
        self._tree.append_column(column)

        # ── Drawer area (below tree view, inside scroll) ──────────────────
        self._drawer_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Wrap tree + drawer_area in a vertical box so drawers scroll with tree
        self._tree_and_drawers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._tree_and_drawers.append(self._tree)
        self._tree_and_drawers.append(self._drawer_area)

        self._scroll.set_child(self._tree_and_drawers)
        # Content widget — switches between TreeView (tree mode) and card box (picker mode)
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
        # Clear open drawers
        for revealer, _, _ in self._drawers.values():
            self._drawer_area.remove(revealer)
        self._drawers.clear()
        # Clear search when returning to picker
        if self._project_list_handler:
            self._project_list_handler.clear_search()
        # Block signal to prevent _on_search_changed from firing while FileTree
        # is still inside the nested notebook (would build cards in wrong parent).
        # The explicit _show_project_picker() call below runs after reparenting is complete.
        self._search_entry.handler_block(self._search_changed_handler_id)
        self._search_entry.set_text("")
        self._search_entry.handler_unblock(self._search_changed_handler_id)
        if fire_callback and self._on_navigate_back:
            self._on_navigate_back(project_name)
        self._show_project_picker()

    def set_page(self, page):
        """Set the notebook page container (for clearing content)."""
        self._page = page

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

    # ── Private ───────────────────────────────────────────────────────────

    def _show_project_picker(self):
        """Show project cards (replaces TreeView picker rows)."""
        self._store.clear()
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

        # Replace TreeView content with card box
        self.remove(self._content)
        self._content = card_box
        self.append(self._content)

    def _make_project_card(self, name: str, path: str, color_hex: str) -> Gtk.Widget:
        """
        Build a project card widget: [folder_icon] [name] [path]
        Colored folder icon with first letter of project name.
        """
        from utils.icons import render_folder_icon
        # CSS loaded globally at startup from main.py via apply_styles()

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
            # Fallback: colored box with letter
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

        # Plus icon
        plus_lbl = Gtk.Label(label="+")
        plus_lbl.set_halign(Gtk.Align.CENTER)
        plus_lbl.set_valign(Gtk.Align.CENTER)
        plus_lbl.set_size_request(44, 44)
        plus_lbl.add_css_class("new-project-plus")

        # Text
        text_lbl = Gtk.Label(label="New Project")
        text_lbl.set_halign(Gtk.Align.START)
        text_lbl.set_valign(Gtk.Align.CENTER)
        text_lbl.add_css_class("dim-label")

        card.append(plus_lbl)
        card.append(text_lbl)

        # Click → show popover
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

        # Enter key submits
        name_entry.connect("activate", lambda _e: on_create(create_btn))

        vbox.append(name_entry)
        vbox.append(create_btn)
        popover.set_child(vbox)
        popover.popup()

        # Focus the entry after popover appears
        GLib.idle_add(lambda: name_entry.grab_focus() and False)

    def _show_tree(self, name, path):
        """Show the directory tree for a project. Restores TreeView."""
        # Swap card box back to TreeView
        if self._content != self._scroll:
            self.remove(self._content)
            self._content = self._scroll
            self.append(self._content)
        self._store.clear()
        # Clear drawer state
        for revealer, _, _ in self._drawers.values():
            self._drawer_area.remove(revealer)
        self._drawers.clear()
        self._back_btn.set_visible(True)
        self._folder_icon.set_visible(True)
        self._title_lbl.set_markup(f"<b>{name}</b>")
        self._title_lbl.set_use_markup(True)
        self._title_lbl.set_hexpand(True)
        self._search_entry.set_visible(False)

        entries = scan_directory(path)
        for entry_name, full_path, is_dir in entries:
            prefix = "📁 " if is_dir else "  "
            parent = self._store.append(None, [
                prefix + entry_name, full_path, is_dir, False
            ])
            if is_dir:
                # Placeholder row — children loaded on first expand
                self._store.append(parent, ["…", "", True, False])
            else:
                # Create drawer revealer for file rows
                self._add_drawer_for_file(full_path, entry_name)

    def _add_drawer_for_file(self, file_path: str, display_name: str) -> None:
        """Create a drawer revealer for a file row and attach it to the drawer area.

        The drawer is hidden by default. It lives below the tree view so it
        scrolls in sync with the tree rows. On toggle, the revealer slides
        open to reveal the drawer content.
        """
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)
        revealer.set_transition_duration(150)
        revealer.add_css_class("file-tree-drawer")

        # Skeleton content box — will be populated in Phase B
        drawer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        drawer_box.set_margin_start(20)
        drawer_box.set_margin_end(8)
        drawer_box.set_margin_top(4)
        drawer_box.set_margin_bottom(4)

        # Phase A: Just a placeholder label
        placeholder = Gtk.Label(label=" ")
        placeholder.set_size_request(-1, 1)
        drawer_box.append(placeholder)

        revealer.set_child(drawer_box)

        # Keep drawer in the area but collapsed
        self._drawer_area.append(revealer)
        self._drawers[file_path] = (revealer, display_name, False)

    def _toggle_drawer(self, file_path: str) -> None:
        """Toggle a file's drawer revealer open/closed."""
        # Debounce: prevent double-click race during revealer animation
        now = time.monotonic()
        if now - getattr(self, '_last_toggle_time', 0) < 0.3:
            return
        self._last_toggle_time = now

        entry = self._drawers.get(file_path)
        if entry is None:
            return
        revealer, display_name, is_open = entry
        new_state = not is_open
        revealer.set_reveal_child(new_state)
        self._drawers[file_path] = (revealer, display_name, new_state)

        # Update the tree row display name to show ▶ or ▼
        model = self._store
        root_iter = model.get_iter_first()
        self._update_drawer_prefix(model, root_iter, file_path, new_state)

    def _update_drawer_prefix(self, model, it, file_path: str, is_open: bool) -> bool:
        """Recursively search for a file path in the tree and update its prefix."""
        while it is not None:
            # Check if this is a file row (is_dir=False) matching our path
            if not model.get_value(it, 2) and model.get_value(it, 1) == file_path:
                current = model.get_value(it, 0)
                name_part = current.lstrip("  ").lstrip("▶ ").lstrip("▼ ")
                new_prefix = "▼ " if is_open else "▶ "
                model.set_value(it, 0, new_prefix + name_part)
                return True
            # Recurse into children
            child = model.iter_children(it)
            if child is not None:
                if self._update_drawer_prefix(model, child, file_path, is_open):
                    return True
            it = model.iter_next(it)
        return False

    def _on_row_activated(self, tree, path, column):
        """
        In picker mode (no project loaded): double-click on a project row loads it.
        In tree mode: double-click on a directory expands/collapses it; on a file
        toggles the inline diff drawer.

        Note: set_activate_on_single_click(False) means row-activated fires on
        double-click only — no timing hack needed for picker mode.
        """
        model = tree.get_model()
        it = model.get_iter(path)
        if it is None:
            return

        display_name = model.get_value(it, 0).lstrip("📁 ").lstrip("  ").lstrip("▶ ").lstrip("▼ ")
        full_path = model.get_value(it, 1)
        is_dir = model.get_value(it, 2)
        parent_it = model.iter_parent(it)
        is_top_level = parent_it is None

        if is_dir:
            if is_top_level and self._project_path is None:
                # Picker mode — double-click loads the project directly
                self.load_project(display_name, full_path)
            elif tree.row_expanded(path):
                tree.collapse_row(path)
            else:
                tree.expand_row(path, open_all=False)
        else:
            # File row - toggle drawer if we have one, otherwise fire callback
            if full_path in self._drawers:
                self._toggle_drawer(full_path)
            elif self._on_file_selected:
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
            else:
                # Create drawer revealer for file children
                self._add_drawer_for_file(full_path, entry_name)

    def _on_search_changed(self, entry):
        """Filter project cards on search-changed. Mirrors LeftPanel._on_prompt_search_changed."""
        query = entry.get_text()
        if self._project_list_handler:
            self._project_list_handler.search(query)
            self._show_project_picker()

    def _on_back_clicked(self, button):
        """Navigate back to the project picker."""
        self.navigate_back()
