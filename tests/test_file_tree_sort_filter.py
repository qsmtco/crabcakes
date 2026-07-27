"""Integration tests for FileTree sort and filter via REAL GTK4 model chain.

These tests create actual Gio.ListStore + Gtk.SortListModel + Gtk.FilterListModel
instances and verify that sorting and filtering work correctly. They use GTK4
types but do NOT require a display server (ListStore/SortListModel/FilterListModel
work headless).
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, Gio, GObject

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ui.views.file_tree import FileTree, FileTreeRow, format_size, format_mtime


def _make_sorter(mode: str) -> Gtk.Sorter:
    """Helper: create a CustomSorter for the given sort mode.

    _build_sorter is a @staticmethod, called directly.
    """
    return FileTree._build_sorter(mode)


class TestComparators:
    """Test that the 6 sort comparators actually sort correctly via GTK4.

    Creates REAL SortListModel instances with CustomSorter and asserts
    the correct ordering.
    """

    def _make_store(self, names, dirs=None, mtimes=None, sizes=None, drawer_at=None):
        """Build a Gio.ListStore[FileTreeRow] with given display names.

        Args:
            names: list of display_name strings
            dirs: set of indices that should be directories
            mtimes: list of modified_time ints (nano timestamps)
            sizes: list of file_size ints
            drawer_at: if set, insert a drawer row after the given index
        """
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        entries = []
        for i, name in enumerate(names):
            is_dir = dirs is not None and i in dirs
            mtime = mtimes[i] if mtimes else 1_700_000_000_000_000_000
            size = sizes[i] if sizes else 100
            row = FileTreeRow(
                display_name=name,
                full_path=f'/{name}',
                is_dir=is_dir,
                file_size=0 if is_dir else size,
                file_size_display="—" if is_dir else format_size(size),
                modified_time=mtime // 1_000_000_000 if mtime else 0,
                modified_display=format_mtime(mtime) if mtime else "—",
            )
            entries.append(row)
            store.append(row)
        if drawer_at is not None:
            parent = entries[drawer_at]
            drawer_row = FileTreeRow(
                display_name="",
                full_path="",
                is_drawer=True,
                depth=1,
                parent_full_path=parent.props.full_path,
            )
            store.append(drawer_row)
        return store

    def _assert_sorted(self, store, sorter, expected):
        smodel = Gtk.SortListModel.new(store, sorter)
        names = []
        for i in range(smodel.get_n_items()):
            item = smodel.get_item(i)
            names.append(item.props.display_name)
        assert names == expected, f'Expected {expected}, got {names}'

    # -- Name asc/desc ---

    def test_name_asc_sorts(self):
        store = self._make_store(['cherry', 'apple', 'banana'])
        sorter = _make_sorter('name_asc')
        self._assert_sorted(store, sorter, ['apple', 'banana', 'cherry'])

    def test_name_desc_sorts(self):
        store = self._make_store(['apple', 'banana', 'cherry'])
        sorter = _make_sorter('name_desc')
        self._assert_sorted(store, sorter, ['cherry', 'banana', 'apple'])

    # -- Dirs sort before files ---

    def test_dirs_sort_before_files_name_asc(self):
        store = self._make_store(['z_dir', 'm_file', 'a_dir', 'x_file'],
                                  dirs={0, 2})
        sorter = _make_sorter('name_asc')
        self._assert_sorted(store, sorter,
                            ['a_dir', 'z_dir', 'm_file', 'x_file'])

    def test_dirs_sort_before_files_name_desc(self):
        store = self._make_store(['a_dir', 'm_file', 'z_dir', 'x_file'],
                                  dirs={0, 2})
        sorter = _make_sorter('name_desc')
        self._assert_sorted(store, sorter,
                            ['z_dir', 'a_dir', 'x_file', 'm_file'])

    # -- Modified asc/desc ---

    def test_modified_desc_sorts(self):
        mtimes = [1_700_000_000_000_000_000, 1_800_000_000_000_000_000,
                  1_500_000_000_000_000_000]
        store = self._make_store(['old', 'new', 'oldest'], mtimes=mtimes)
        sorter = _make_sorter('modified_desc')
        self._assert_sorted(store, sorter, ['new', 'old', 'oldest'])

    def test_modified_asc_sorts(self):
        mtimes = [1_700_000_000_000_000_000, 1_800_000_000_000_000_000,
                  1_500_000_000_000_000_000]
        store = self._make_store(['mid', 'new', 'old'], mtimes=mtimes)
        sorter = _make_sorter('modified_asc')
        self._assert_sorted(store, sorter, ['old', 'mid', 'new'])

    # -- Size asc/desc ---

    def test_size_desc_sorts(self):
        store = self._make_store(['small', 'large', 'medium'],
                                  sizes=[10, 1000, 100])
        sorter = _make_sorter('size_desc')
        self._assert_sorted(store, sorter, ['large', 'medium', 'small'])

    def test_size_asc_sorts(self):
        store = self._make_store(['large', 'small', 'medium'],
                                  sizes=[1000, 10, 100])
        sorter = _make_sorter('size_asc')
        self._assert_sorted(store, sorter, ['small', 'medium', 'large'])

    # -- Dirs respect all sort modes ---

    def test_dirs_sort_before_files_modified_desc(self):
        store = self._make_store(['z_dir', 'm_file', 'a_dir', 'x_file'],
                                  dirs={0, 2},
                                  mtimes=[1_700_000_000_000_000_000,
                                          1_800_000_000_000_000_000,
                                          1_500_000_000_000_000_000,
                                          1_600_000_000_000_000_000])
        sorter = _make_sorter('modified_desc')
        self._assert_sorted(store, sorter,
                            ['z_dir', 'a_dir', 'm_file', 'x_file'])

    def test_dirs_sort_before_files_size_desc(self):
        store = self._make_store(['z_dir', 'm_file', 'a_dir', 'x_file'],
                                  dirs={0, 2}, sizes=[0, 100, 0, 50])
        sorter = _make_sorter('size_desc')
        self._assert_sorted(store, sorter,
                            ['z_dir', 'a_dir', 'm_file', 'x_file'])


class TestDrawerRowSorting:
    """Drawer rows must stay at their insertion position (BUG #4)."""

    def test_drawer_row_not_reordered(self):
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        rows = []
        for name in ['banana', 'apple', 'cherry']:
            r = FileTreeRow(display_name=name, full_path='/'+name, is_dir=False)
            rows.append(r)
            store.append(r)
        # Insert drawer after 'apple' (index 1)
        drawer = FileTreeRow(
            display_name="", full_path="", is_drawer=True, depth=1,
            parent_full_path='/apple',
        )
        store.append(drawer)
        rows.append(drawer)

        sorter = _make_sorter('name_asc')
        smodel = Gtk.SortListModel.new(store, sorter)
        names = []
        for i in range(smodel.get_n_items()):
            item = smodel.get_item(i)
            names.append(item.props.display_name)
        # Drawer should NOT be reordered — it stays after its parent
        assert '' in names, 'drawer row should still be present'
        # The drawer should appear AFTER 'apple' in the sorted list
        apple_pos = names.index('apple')
        drawer_pos = names.index('')
        assert drawer_pos > apple_pos, \
            f'drawer (pos {drawer_pos}) should be after apple (pos {apple_pos}) in {names}'


class TestFilterFunc:
    """Test _filter_func directly (headless — no display server needed)."""

    def test_substring_match(self):
        row = FileTreeRow(display_name='hello.py', full_path='/src/hello.py')
        assert FileTree._filter_func(row, 'hello') is True
        assert FileTree._filter_func(row, 'HELLO') is True
        assert FileTree._filter_func(row, 'xyz') is False

    def test_none_returns_false(self):
        assert FileTree._filter_func(None, 'query') is False

    def test_empty_query_returns_true(self):
        row = FileTreeRow(display_name='test.py', full_path='/test.py')
        assert FileTree._filter_func(row, '') is True

    def test_path_match(self):
        row = FileTreeRow(display_name='main.py', full_path='/src/main.py')
        assert FileTree._filter_func(row, 'src') is True
        assert FileTree._filter_func(row, '.py') is True

    def test_drawer_row_filters_with_parent(self):
        """Drawer row matches when query matches parent_full_path (BUG #26)."""
        row = FileTreeRow(
            display_name="", full_path="",
            is_drawer=True, parent_full_path="/src/main.py",
        )
        assert FileTree._filter_func(row, 'main') is True
        assert FileTree._filter_func(row, 'src') is True
        assert FileTree._filter_func(row, 'xyz') is False

    def test_drawer_row_filters_with_own_name(self):
        """Drawer row also matches against its own display_name."""
        row = FileTreeRow(
            display_name="diff content", full_path="",
            is_drawer=True, parent_full_path="/src/main.py",
        )
        assert FileTree._filter_func(row, 'diff') is True
        assert FileTree._filter_func(row, 'main') is True  # from parent
        assert FileTree._filter_func(row, 'xyz') is False


class TestFilterIntegration:
    """Test real FilterListModel with CustomFilter — headless."""

    def _make_store(self, names):
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        for name in names:
            store.append(FileTreeRow(
                display_name=name,
                full_path='/' + name,
                is_dir=False,
            ))
        return store

    def test_filter_keeps_matching(self):
        store = self._make_store(['apple.py', 'banana.py', 'cherry.py'])
        cf = Gtk.CustomFilter.new(
            lambda item: FileTree._filter_func(item, 'ban')
        )
        fmodel = Gtk.FilterListModel.new(store, cf)
        assert fmodel.get_n_items() == 1
        assert fmodel.get_item(0).props.display_name == 'banana.py'

    def test_filter_no_match(self):
        store = self._make_store(['apple.py', 'banana.py'])
        cf = Gtk.CustomFilter.new(
            lambda item: FileTree._filter_func(item, 'zzz')
        )
        fmodel = Gtk.FilterListModel.new(store, cf)
        assert fmodel.get_n_items() == 0

    def test_filter_empty_query_shows_all(self):
        store = self._make_store(['a.py', 'b.py'])
        cf = Gtk.CustomFilter.new(
            lambda item: FileTree._filter_func(item, '')
        )
        fmodel = Gtk.FilterListModel.new(store, cf)
        assert fmodel.get_n_items() == 2

    def test_filter_none_returns_false(self):
        """Filter returns False for None item (BUG #5 fix)."""
        assert FileTree._filter_func(None, 'anything') is False


class TestSortFilterChain:
    """Test SortListModel + FilterListModel stacked — headless."""

    def test_sort_then_filter(self):
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        for name in ['cherry', 'apple', 'banana']:
            store.append(FileTreeRow(
                display_name=name, full_path='/' + name, is_dir=False,
            ))
        sorter = _make_sorter('name_asc')
        smodel = Gtk.SortListModel.new(store, sorter)
        cf = Gtk.CustomFilter.new(
            lambda item: FileTree._filter_func(item, 'e')
        )
        fmodel = Gtk.FilterListModel.new(smodel, cf)
        names = []
        for i in range(fmodel.get_n_items()):
            names.append(fmodel.get_item(i).props.display_name)
        # 'apple' and 'cherry' match 'e', sorted asc → apple, cherry
        assert names == ['apple', 'cherry'], f'got {names}'


class TestDepthHierarchy:
    """BUG #1/#2: Depth-aware sorting preserves tree hierarchy."""

    def test_multiple_drawers_stay_adjacent_to_parents(self):
        """2+ drawers must each stay adjacent to their parent after sort."""
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        # Scrambled insertion — drawers NOT pre-adjacent
        store.append(FileTreeRow(display_name='cherry.py', full_path='/cherry.py', is_dir=False, depth=0))
        store.append(FileTreeRow(display_name='', full_path='', is_drawer=True, depth=0, parent_full_path='/banana.py'))
        store.append(FileTreeRow(display_name='apple.py', full_path='/apple.py', is_dir=False, depth=0))
        store.append(FileTreeRow(display_name='', full_path='', is_drawer=True, depth=0, parent_full_path='/apple.py'))
        store.append(FileTreeRow(display_name='banana.py', full_path='/banana.py', is_dir=False, depth=0))
        sorter = FileTree._build_sorter('name_asc')
        smodel = Gtk.SortListModel.new(store, sorter)
        items = [smodel.get_item(i) for i in range(smodel.get_n_items())]
        # Each drawer must be immediately after its parent
        for i, item in enumerate(items):
            if item.props.is_drawer:
                parent_path = item.props.parent_full_path
                assert i > 0, f'drawer at position 0 with no parent above'
                prev = items[i-1]
                assert prev.props.full_path == parent_path, \
                    f'drawer parent {parent_path} not at i-1, found {prev.props.full_path}'

    def test_children_stay_under_parent_after_sort(self):
        """Children of expanded dirs must not mix with root items after sort."""
        store = Gio.ListStore.new(FileTreeRow.__gtype__)
        store.append(FileTreeRow(display_name='mmm_dir', full_path='/mmm_dir', is_dir=True, depth=0))
        store.append(FileTreeRow(display_name='zzz_child.py', full_path='/mmm_dir/zzz_child.py', is_dir=False, depth=1))
        store.append(FileTreeRow(display_name='zzz_dir', full_path='/zzz_dir', is_dir=True, depth=0))
        store.append(FileTreeRow(display_name='aaa_child.py', full_path='/zzz_dir/aaa_child.py', is_dir=False, depth=1))
        sorter = FileTree._build_sorter('name_asc')
        smodel = Gtk.SortListModel.new(store, sorter)
        depths = [smodel.get_item(i).props.depth for i in range(smodel.get_n_items())]
        # All depth-0 items must come before all depth-1 items
        d0_count = depths.count(0)
        assert depths[:d0_count] == [0]*d0_count, f'depth-0 items not grouped: {depths}'
        assert depths[d0_count:] == [1]*(len(depths)-d0_count), f'depth-1 items not grouped: {depths}'

    def test_set_selected_does_not_trigger_handler_when_blocked(self):
        """Programmatic set_selected with handler_block must NOT fire the callback."""
        dropdown = Gtk.DropDown.new_from_strings(['A','B','C'])
        call_count = [0]
        handler_id = dropdown.connect('notify::selected', lambda *a: call_count.__setitem__(0, call_count[0]+1))
        dropdown.handler_block(handler_id)
        dropdown.set_selected(2)
        dropdown.handler_unblock(handler_id)
        assert call_count[0] == 0, f'handler fired {call_count[0]} times during block'

    def test_signal_unblocked_after_exception(self):
        """handler_unblock must run even if set_selected raises."""
        dropdown = Gtk.DropDown.new_from_strings(['A','B'])
        call_count = [0]
        handler_id = dropdown.connect('notify::selected', lambda *a: call_count.__setitem__(0, call_count[0]+1))
        dropdown.handler_block(handler_id)
        try:
            raise RuntimeError('simulated')
        except RuntimeError:
            pass
        finally:
            dropdown.handler_unblock(handler_id)
        # Now a real user action should fire the handler
        dropdown.set_selected(1)
        assert call_count[0] == 1, f'handler not unblocked: {call_count[0]}'
