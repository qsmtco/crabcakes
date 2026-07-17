# tests/test_file_tree_columnview.py
"""Tests for FileTree ColumnView migration.

Covers: FileTreeRow GObject, FileTreeRowWidget, FileTreeFactory,
drawer state machine, _clear_all_state, _find_row_index.
"""
import pytest
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio

from ui.views.file_tree import (
    FileTree, FileTreeRow, FileTreeRowWidget, FileTreeFactory
)


# ── FileTreeRow GObject Tests ──────────────────────────────────────────

class TestFileTreeRow:
    """Tests for the FileTreeRow GObject."""

    def test_all_12_properties_exist(self):
        """FileTreeRow has all 12 GObject properties."""
        expected = {
            'display-name', 'full-path', 'is-dir', 'is-drawer',
            'depth', 'expanded', 'has-children', 'drawer-widget',
            'is-open', 'diff-text', 'history-selected-sha', 'history-loaded'
        }
        actual = {p.name for p in FileTreeRow.list_properties()}
        assert expected.issubset(actual), f"Missing: {expected - actual}"

    def test_default_values(self):
        """All properties have correct defaults."""
        row = FileTreeRow()
        assert row.props.display_name == ""
        assert row.props.full_path == ""
        assert row.props.is_dir is False
        assert row.props.is_drawer is False
        assert row.props.depth == 0
        assert row.props.expanded is False
        assert row.props.has_children is False
        assert row.props.drawer_widget is None
        assert row.props.is_open is False
        assert row.props.diff_text == ""
        assert row.props.history_selected_sha is None
        assert row.props.history_loaded is False

    def test_constructor_with_all_kwargs(self):
        """Constructor accepts all 12 kwargs."""
        row = FileTreeRow(
            display_name="test.txt",
            full_path="/tmp/test.txt",
            is_dir=False,
            is_drawer=False,
            depth=1,
            expanded=True,
            has_children=False,
            drawer_widget=None,
            is_open=True,
            diff_text="+ added line",
            history_selected_sha="abc123",
            history_loaded=True,
        )
        assert row.props.display_name == "test.txt"
        assert row.props.full_path == "/tmp/test.txt"
        assert row.props.is_dir is False
        assert row.props.is_drawer is False
        assert row.props.depth == 1
        assert row.props.expanded is True
        assert row.props.has_children is False
        assert row.props.drawer_widget is None
        assert row.props.is_open is True
        assert row.props.diff_text == "+ added line"
        assert row.props.history_selected_sha == "abc123"
        assert row.props.history_loaded is True

    def test_property_setters(self):
        """Properties can be set after construction."""
        row = FileTreeRow()
        row.props.display_name = "new.txt"
        row.props.is_dir = True
        row.props.depth = 2
        assert row.props.display_name == "new.txt"
        assert row.props.is_dir is True
        assert row.props.depth == 2


# ── FileTreeRowWidget Tests ───────────────────────────────────────────

class TestFileTreeRowWidget:
    """Tests for the FileTreeRowWidget per-row widget."""

    def test_widget_creation(self):
        """FileTreeRowWidget can be instantiated."""
        widget = FileTreeRowWidget()
        assert widget is not None
        assert "file-tree-row" in widget.get_css_classes()

    def test_widget_has_children(self):
        """Widget has expander (Gtk.Button), icon (Gtk.Image), label (Gtk.Label), drawer_container (Gtk.Box)."""
        widget = FileTreeRowWidget()
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        assert len(children) >= 4
        # Check types of first 4 children
        assert isinstance(children[0], Gtk.Button)  # expander
        assert isinstance(children[1], Gtk.Image)   # icon
        assert isinstance(children[2], Gtk.Label)   # label
        assert isinstance(children[3], Gtk.Box)     # drawer_container

    def test_set_depth(self):
        """set_depth sets margin-start on the widget."""
        widget = FileTreeRowWidget()
        widget.set_depth(3)
        assert widget.get_margin_start() == 60  # 3 * 20

    def test_set_expanded(self):
        """set_expanded updates the expander button label."""
        widget = FileTreeRowWidget()
        widget.set_expanded(True)
        expander = widget.get_first_child()
        assert expander.get_label() == "▼"
        widget.set_expanded(False)
        assert expander.get_label() == "▶"

    def test_set_label(self):
        """set_label sets the label markup."""
        widget = FileTreeRowWidget()
        widget.set_label("test.txt")
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        label = children[2]
        assert label.get_text() == "test.txt"

    def test_set_icon_dir(self):
        """set_icon sets folder icon for directories."""
        widget = FileTreeRowWidget()
        widget.set_icon(is_dir=True, is_drawer=False)
        icon = widget.get_first_child().get_next_sibling()
        assert icon.get_icon_name() == "folder-symbolic"

    def test_set_icon_file(self):
        """set_icon sets file icon for files."""
        widget = FileTreeRowWidget()
        widget.set_icon(is_dir=False, is_drawer=False)
        icon = widget.get_first_child().get_next_sibling()
        assert icon.get_icon_name() == "text-x-generic-symbolic"

    def test_attach_detach_drawer(self):
        """attach_drawer and detach_drawer work correctly."""
        widget = FileTreeRowWidget()
        # Find the drawer container (last child)
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        drawer_container = children[-1]

        # Initially container has no children and is invisible
        assert drawer_container.get_first_child() is None
        assert drawer_container.get_visible() is False

        # Attach a drawer
        revealer = Gtk.Revealer()
        revealer.set_child(Gtk.Label(label="drawer content"))
        widget.attach_drawer(revealer)
        assert drawer_container.get_first_child() is revealer
        assert drawer_container.get_visible() is True

        # Detach the drawer
        widget.detach_drawer()
        assert drawer_container.get_first_child() is None
        assert drawer_container.get_visible() is False

    def test_cleanup(self):
        """cleanup() detaches drawer and clears bound_row."""
        widget = FileTreeRowWidget()
        row = FileTreeRow()
        widget.bind_row(row)
        revealer = Gtk.Revealer()
        widget.attach_drawer(revealer)
        widget.cleanup()
        assert widget._bound_row is None


# ── FileTreeFactory Tests ─────────────────────────────────────────────

class TestFileTreeFactory:
    """Tests for the FileTreeFactory SignalListItemFactory."""

    def test_factory_creation(self):
        """FileTreeFactory can be instantiated."""
        factory = FileTreeFactory(None)
        assert factory is not None

    def test_setup_creates_widget(self):
        """_on_setup creates a FileTreeRowWidget and sets it as the list_item child."""
        factory = FileTreeFactory(None)
        list_item = Gtk.ListItem()
        factory._on_setup(factory, list_item)
        widget = list_item.get_child()
        assert isinstance(widget, FileTreeRowWidget)

    def test_bind_populates_widget(self):
        """_on_bind populates the widget from the row properties."""
        factory = FileTreeFactory(None)
        list_item = Gtk.ListItem()
        factory._on_setup(factory, list_item)
        row = FileTreeRow(
            display_name="test.txt",
            full_path="/tmp/test.txt",
            is_dir=False,
            depth=2,
            expanded=False,
        )
        # Set the item so get_item() returns it
        list_item.item = row
        factory._on_bind(factory, list_item)
        widget = list_item.get_child()
        assert widget.get_margin_start() == 40  # 2 * 20

    def test_unbind_cleans_up(self):
        """_on_unbind calls cleanup() on the widget."""
        factory = FileTreeFactory(None)
        list_item = Gtk.ListItem()
        factory._on_setup(factory, list_item)
        row = FileTreeRow()
        # Set the item so get_item() returns it
        list_item.item = row
        factory._on_bind(factory, list_item)
        factory._on_unbind(factory, list_item)
        widget = list_item.get_child()
        assert widget._bound_row is None


# ── FileTree Integration Tests ────────────────────────────────────────

class TestFileTree:
    """Integration tests for FileTree."""

    def test_file_tree_creation(self):
        """FileTree can be instantiated."""
        tree = FileTree()
        assert tree is not None

    def test_store_creation(self):
        """FileTree has a Gio.ListStore of FileTreeRow."""
        tree = FileTree()
        assert isinstance(tree._store, Gio.ListStore)
        assert tree._store.get_item_type() == FileTreeRow.__gtype__

    def test_column_view_creation(self):
        """FileTree has a Gtk.ColumnView."""
        tree = FileTree()
        assert isinstance(tree._column_view, Gtk.ColumnView)

    def test_clear_all_state(self):
        """_clear_all_state clears the store and all tracking dicts."""
        tree = FileTree()
        tree._store.append(FileTreeRow(display_name="a.txt"))
        tree._store.append(FileTreeRow(display_name="b.txt"))
        # Use FileTreeRow objects for _drawer_paths now
        dummy_row = FileTreeRow()
        tree._drawer_paths["/test"] = dummy_row
        tree._loaded_drawers.add("/test")
        tree._last_toggle_per_file["/test"] = 1.0
        old_request_id = tree._current_request_id

        tree._clear_all_state()

        assert tree._store.get_n_items() == 0
        assert len(tree._drawer_paths) == 0
        assert len(tree._loaded_drawers) == 0
        assert len(tree._last_toggle_per_file) == 0
        assert tree._current_request_id == old_request_id + 1

    def test_find_row_index(self):
        """_find_row_index finds a row by object identity."""
        tree = FileTree()
        row = FileTreeRow(display_name="test.txt", full_path="/tmp/test.txt")
        tree._store.append(row)
        index = tree._find_row_index(row)
        assert index == 0
        other_row = FileTreeRow(display_name="other.txt")
        assert tree._find_row_index(other_row) is None

    def test_is_drawer_open_false_by_default(self):
        """is_drawer_open returns False for a file with no drawer."""
        tree = FileTree()
        assert tree.is_drawer_open("/nonexistent") is False

    def test_find_file_path_for_drawer(self):
        """_find_file_path_for_drawer walks backwards to find the file row."""
        tree = FileTree()
        # Add a file row
        file_row = FileTreeRow(display_name="test.txt", full_path="/tmp/test.txt")
        tree._store.append(file_row)
        # Add a drawer row after it
        drawer_row = FileTreeRow(is_drawer=True, full_path="")
        tree._store.append(drawer_row)
        # The drawer row is at index 1, file row is at index 0
        path = tree._find_file_path_for_drawer(1)
        assert path == "/tmp/test.txt"
        # For a file row, should return None (no drawer before it)
        assert tree._find_file_path_for_drawer(0) is None

    def test_find_file_path_for_drawer_no_file_before(self):
        """_find_file_path_for_drawer returns None when no file row exists before."""
        tree = FileTree()
        drawer_row = FileTreeRow(is_drawer=True, full_path="")
        tree._store.append(drawer_row)
        assert tree._find_file_path_for_drawer(0) is None


# ── Drawer State Machine Tests ────────────────────────────────────────

class TestDrawerStateMachine:
    """Tests for the drawer open/close state machine."""

    def test_toggle_drawer_no_file(self):
        """_toggle_drawer is a no-op for a nonexistent file."""
        tree = FileTree()
        tree._toggle_drawer("/nonexistent")
        assert "/nonexistent" not in tree._drawer_paths

    def test_drawer_paths_identity_tracking(self):
        """_drawer_paths uses FileTreeRow identity, not index."""
        tree = FileTree()
        row = FileTreeRow(
            display_name="test.txt",
            full_path="/tmp/test.txt",
        )
        tree._store.append(row)
        tree._drawer_paths["/tmp/test.txt"] = row
        # Insert another row before test.txt — index shifts but identity preserved
        tree._store.insert(0, FileTreeRow(display_name="a.txt"))
        assert tree._drawer_paths["/tmp/test.txt"] is row

    def test_loaded_drawers_cleanup(self):
        """_loaded_drawers is cleared on _clear_all_state."""
        tree = FileTree()
        tree._loaded_drawers.add("/test")
        tree._clear_all_state()
        assert "/test" not in tree._loaded_drawers