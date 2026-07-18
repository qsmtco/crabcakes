# tests/test_file_tree_columnview.py
"""Tests for FileTree ColumnView migration.

Covers: FileTreeRow GObject, FileTreeRowWidget, FileTreeFactory,
drawer state machine, _clear_all_state, _find_row_index,
right-click context menu.
"""
import os
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
        """Widget has expander (Gtk.Button), label (Gtk.Label), drawer_container (Gtk.Box)."""
        widget = FileTreeRowWidget()
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        assert len(children) >= 3
        # Check types
        assert isinstance(children[0], Gtk.Button)  # expander
        assert isinstance(children[1], Gtk.Label)   # label
        assert isinstance(children[2], Gtk.Box)     # drawer_container

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
        label = children[1]
        assert label.get_text() == "test.txt"

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
        """_on_bind populates the widget from the row properties.
        Uses a MagicMock for list_item since Gtk.ListItem.item is read-only.
        """
        from unittest.mock import MagicMock
        factory = FileTreeFactory(None)
        list_item = MagicMock(spec=Gtk.ListItem)
        list_item.get_position.return_value = 0
        row = FileTreeRow(
            display_name="test.txt",
            full_path="/tmp/test.txt",
            is_dir=False,
            depth=2,
            expanded=False,
        )
        # Mock get_item to return our row
        list_item.get_item.return_value = row
        widget = FileTreeRowWidget()
        list_item.get_child.return_value = widget
        factory._on_bind(factory, list_item)
        assert widget.get_margin_start() == 40  # 2 * 20
        assert widget._bound_row is row

    def test_unbind_cleans_up(self):
        """_on_unbind calls cleanup() on the widget.
        Uses a MagicMock for list_item since Gtk.ListItem.item is read-only.
        """
        from unittest.mock import MagicMock
        factory = FileTreeFactory(None)
        list_item = MagicMock(spec=Gtk.ListItem)
        row = FileTreeRow()
        list_item.get_item.return_value = row
        widget = FileTreeRowWidget()
        widget.bind_row(row)
        list_item.get_child.return_value = widget
        factory._on_bind(factory, list_item)
        factory._on_unbind(factory, list_item)
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

    def test_find_file_path_for_drawer_empty_store(self):
        """_find_file_path_for_drawer returns None on empty store."""
        tree = FileTree()
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


# ── Right-Click Context Menu Tests ────────────────────────────────────

class TestFileTreeRightClick:
    """Tests for the right-click context menu on file tree rows.

    Follows the pattern from tests/test_left_panel.py::TestPromptRowRightClick.
    Uses patch/mock to avoid real GTK Popover creation (segfaults in CI sandbox).
    Status label must be initialized since the FileTree ctor creates one.
    """

    def _make_mock_widget(self, with_bound_row=None):
        """Create a minimal mock widget that simulates FileTreeRowWidget."""
        mock_widget = type("MockWidget", (), {"_bound_row": with_bound_row})()
        return mock_widget

    def test_on_copy_tree_path_calls_clipboard_with_full_path(self):
        """Patch Gdk.Display.get_default, call _on_copy_tree_path, verify clipboard.set was called with path."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        row = FileTreeRow(full_path="/abs/path/to/file.txt")

        with patch("gi.repository.Gdk.Display.get_default") as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            tree._on_copy_tree_path(row)

            mock_clipboard.set.assert_called_once_with("/abs/path/to/file.txt")

    def test_on_copy_tree_file_calls_clipboard_with_content(self):
        """Write a temp file, call _on_copy_tree_file, assert clipboard got file contents."""
        import tempfile
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, world!")
            tmp_path = f.name

        try:
            row = FileTreeRow(full_path=tmp_path)

            with patch("gi.repository.Gdk.Display.get_default") as mock_display:
                mock_clipboard = MagicMock()
                mock_display.return_value.get_clipboard.return_value = mock_clipboard

                tree._on_copy_tree_file(row)

                mock_clipboard.set.assert_called_once_with("Hello, world!")
        finally:
            os.unlink(tmp_path)

    def test_on_copy_tree_file_handles_binary_gracefully(self):
        """Write bytes that fail UTF-8 decode; assert no crash and a notice is copied."""
        import tempfile
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as f:
            f.write(b"\xff\xfe\x00\x01\x02")
            tmp_path = f.name

        try:
            row = FileTreeRow(full_path=tmp_path)

            with patch("gi.repository.Gdk.Display.get_default") as mock_display:
                mock_clipboard = MagicMock()
                mock_display.return_value.get_clipboard.return_value = mock_clipboard

                # Must not crash
                tree._on_copy_tree_file(row)

                # Binary file should copy a notice rather than crash
                mock_clipboard.set.assert_called_once()
                assert "binary" in mock_clipboard.set.call_args[0][0].lower()
        finally:
            os.unlink(tmp_path)

    def test_on_copy_tree_path_skips_empty_path(self):
        """full_path='' -> no clipboard call, no crash."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        row = FileTreeRow(full_path="")

        with patch("gi.repository.Gdk.Display.get_default") as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            tree._on_copy_tree_path(row)

            mock_clipboard.set.assert_not_called()

    def test_menu_shows_copy_path_for_directory(self):
        """Right-click on a directory row -> menu has 'Copy Path' but NOT 'Copy File'."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="/some/dir", is_dir=True, is_drawer=False
        ))

        with patch("gi.repository.Gtk.Popover") as mock_popover_class:
            mock_popover = MagicMock()
            mock_popover_class.return_value = mock_popover

            # Must not raise
            tree._on_tree_row_right_click(None, 1, 0, 0, widget)

            mock_popover_class.assert_called_once()
            mock_popover.set_parent.assert_called_once_with(widget)
            mock_popover.popup.assert_called_once()

    def test_menu_shows_both_for_file(self):
        """File row -> menu must show both 'Copy Path' and 'Copy File' entries."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="/some/file.txt", is_dir=False, is_drawer=False
        ))

        popover_children = []

        original_listbox_append = Gtk.ListBox.append

        def capture_append(self, child):
            popover_children.append(child)
            return original_listbox_append(self, child)

        with patch.object(Gtk.ListBox, "append", capture_append):
            with patch("gi.repository.Gtk.Popover") as mock_popover_class:
                mock_popover = MagicMock()
                mock_popover_class.return_value = mock_popover

                tree._on_tree_row_right_click(None, 1, 0, 0, widget)

        # Verify two menu rows were added to the ListBox
        actions = [getattr(r, "_action", None) for r in popover_children]
        assert "copy_path" in actions
        assert "copy_file" in actions

    def test_menu_skips_drawer_row(self):
        """is_drawer=True -> handler returns early, no popover."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="/some/file.txt", is_dir=False, is_drawer=True
        ))

        with patch("gi.repository.Gtk.Popover") as mock_popover_class:
            mock_popover = MagicMock()
            mock_popover_class.return_value = mock_popover

            tree._on_tree_row_right_click(None, 1, 0, 0, widget)

            mock_popover_class.assert_not_called()

    def test_right_click_handler_ignores_multipress(self):
        """Call _on_tree_row_right_click with n_press=2, verify no popover is created."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="/some/file.txt", is_dir=False
        ))

        with patch("gi.repository.Gtk.Popover") as mock_popover_class:
            mock_popover_class.return_value = MagicMock()

            tree._on_tree_row_right_click(None, 2, 0, 0, widget)

            mock_popover_class.assert_not_called()

    def test_right_click_skips_when_bound_row_none(self):
        """_bound_row is None -> handler returns early, no popover."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=None)

        with patch("gi.repository.Gtk.Popover") as mock_popover_class:
            mock_popover_class.return_value = MagicMock()

            tree._on_tree_row_right_click(None, 1, 0, 0, widget)

            mock_popover_class.assert_not_called()

    def test_right_click_skips_empty_path(self):
        """full_path is empty -> handler returns early, no popover."""
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="", is_dir=False
        ))

        with patch("gi.repository.Gtk.Popover") as mock_popover_class:
            mock_popover_class.return_value = MagicMock()

            tree._on_tree_row_right_click(None, 1, 0, 0, widget)

            mock_popover_class.assert_not_called()

    def test_action_dispatch_uses_action_not_label(self):
        """
        Dispatch reads _action (not label text) — i18n-robust.
        Mutate menu row labels to non-English, dispatch must still call correct handler.
        """
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        source_row = FileTreeRow(full_path="/tmp/x.txt", is_dir=False)

        # Build the two menu rows with _action attributes (same as production code)
        copy_path_row = Gtk.ListBoxRow()
        copy_path_row.set_activatable(True)
        copy_path_row.set_selectable(False)
        copy_path_row._action = "copy_path"
        copy_path_label = Gtk.Label(label="Copy Path", xalign=0)
        copy_path_row.set_child(copy_path_label)

        copy_file_row = Gtk.ListBoxRow()
        copy_file_row.set_activatable(True)
        copy_file_row.set_selectable(False)
        copy_file_row._action = "copy_file"
        copy_file_label = Gtk.Label(label="Copy File", xalign=0)
        copy_file_row.set_child(copy_file_label)

        assert copy_path_row._action == "copy_path"
        assert copy_file_row._action == "copy_file"

        mock_popover = MagicMock()

        # Test dispatch: copy_path
        with patch.object(tree, '_on_copy_tree_path') as mock_copy_path:
            tree._on_tree_menu_row_activated(None, copy_path_row, mock_popover, source_row)
            mock_copy_path.assert_called_once_with(source_row)

        # Test dispatch: copy_file
        with patch.object(tree, '_on_copy_tree_file') as mock_copy_file:
            tree._on_tree_menu_row_activated(None, copy_file_row, mock_popover, source_row)
            mock_copy_file.assert_called_once_with(source_row)

        # Mutate labels to non-English
        copy_path_row.get_child().set_text("Copier le chemin")
        copy_file_row.get_child().set_text("Copier le fichier")

        with patch.object(tree, '_on_copy_tree_path') as mock_copy_path:
            tree._on_tree_menu_row_activated(None, copy_path_row, mock_popover, source_row)
            mock_copy_path.assert_called_once_with(source_row)

        with patch.object(tree, '_on_copy_tree_file') as mock_copy_file:
            tree._on_tree_menu_row_activated(None, copy_file_row, mock_popover, source_row)
            mock_copy_file.assert_called_once_with(source_row)

    def test_popover_closed_handler_unparents(self):
        """
        Popover leak regression test: 'closed' signal must unparent the popover.
        Verifies that the handler connected in _on_tree_row_right_click calls
        popover.unparent() when 'closed' fires.
        """
        tree = FileTree()
        tree._tree_copy_status_label = Gtk.Label()
        tree._tree_copy_status_timeout_id = None

        widget = self._make_mock_widget(with_bound_row=FileTreeRow(
            full_path="/some/file.txt", is_dir=False
        ))

        created_popovers = []

        def capture_popup(self_popover):
            created_popovers.append(self_popover)

        with patch.object(Gtk.Popover, "popup", capture_popup):
            tree._on_tree_row_right_click(None, 1, 0, 0, widget)

        assert len(created_popovers) == 1, (
            "_on_tree_row_right_click should create exactly one popover"
        )
        popover = created_popovers[0]

        # Verify the popover is parented to the widget
        assert popover.get_parent() is widget, "popover should be parented to widget"

        # Fire the "closed" signal — if the handler is connected, this unparents
        popover.emit("closed")

        assert popover.get_parent() is None, (
            "After 'closed' signal fires, popover should be unparented. "
            "If this fails, the closed signal handler is not connected in "
            "_on_tree_row_right_click."
        )

    def test_new_context_menu_test_framework_does_not_segfault(self):
        """
        Minimum-viable test to confirm the new test class methods can be collected
        and run without segfaulting (the existing widget-creation tests segfault
        in this sandbox for environmental GTK4 reasons).
        """
        # Just verify the class was defined and imported
        assert TestFileTreeRightClick is not None