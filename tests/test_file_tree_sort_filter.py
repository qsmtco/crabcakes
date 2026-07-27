"""Tests for FileTree sort (local sibling-group sort) and filter (FilterListModel).

Phase 3 redesign: SortListModel was removed because a flat sorter cannot
preserve tree hierarchy. Sort is now applied locally to contiguous sibling
groups at insertion time. Filter uses FilterListModel for search.
"""

import pytest
import os
import sys
import functools

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GObject

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.views.file_tree import FileTree, FileTreeRow


def _make_row(name, full_path, is_dir=False, depth=0, parent="", drawer=False,
              parent_fp="", mtime=0, size=0):
    """Helper to create a FileTreeRow with common defaults."""
    return FileTreeRow(
        display_name=name,
        full_path=full_path,
        is_dir=is_dir,
        is_drawer=drawer,
        depth=depth,
        parent_full_path=parent_fp or parent,
        modified_time=mtime,
        file_size=size,
    )


class FakeTree:
    """Minimal stand-in for FileTree to hold _current_sort_mode."""
    def __init__(self, mode="name_asc"):
        self._current_sort_mode = mode


def _sort_items(items, mode="name_asc"):
    """Sort a list of FileTreeRow items using FileTree's group comparator.

    Simulates _sort_store_in_place: finds contiguous sibling groups (same
    parent_full_path) and sorts each group.
    """
    ft = FakeTree(mode)
    cmp_fn = FileTree._make_group_comparator(ft)
    result = []
    i = 0
    while i < len(items):
        group_parent = items[i].props.parent_full_path or ""
        j = i
        while j < len(items) and (items[j].props.parent_full_path or "") == group_parent:
            j += 1
        group = items[i:j]
        group.sort(key=functools.cmp_to_key(cmp_fn))
        result.extend(group)
        i = j
    return result


class TestGroupComparator:
    """Test the sibling-group comparator across all 6 sort modes."""

    def test_name_asc(self):
        items = [
            _make_row("cherry.py", "/c.py"),
            _make_row("apple.py", "/a.py"),
            _make_row("banana.py", "/b.py"),
        ]
        result = _sort_items(items, "name_asc")
        assert [r.props.display_name for r in result] == ["apple.py", "banana.py", "cherry.py"]

    def test_name_desc(self):
        items = [
            _make_row("apple.py", "/a.py"),
            _make_row("banana.py", "/b.py"),
            _make_row("cherry.py", "/c.py"),
        ]
        result = _sort_items(items, "name_desc")
        assert [r.props.display_name for r in result] == ["cherry.py", "banana.py", "apple.py"]

    def test_dirs_before_files(self):
        items = [
            _make_row("file.py", "/f.py", is_dir=False),
            _make_row("src", "/src", is_dir=True),
            _make_row("another_dir", "/ad", is_dir=True),
        ]
        result = _sort_items(items, "name_asc")
        names = [r.props.display_name for r in result]
        assert names == ["another_dir", "src", "file.py"]

    def test_modified_desc(self):
        items = [
            _make_row("old.py", "/old.py", mtime=100),
            _make_row("new.py", "/new.py", mtime=300),
            _make_row("mid.py", "/mid.py", mtime=200),
        ]
        result = _sort_items(items, "modified_desc")
        assert [r.props.display_name for r in result] == ["new.py", "mid.py", "old.py"]

    def test_modified_asc(self):
        items = [
            _make_row("old.py", "/old.py", mtime=100),
            _make_row("new.py", "/new.py", mtime=300),
            _make_row("mid.py", "/mid.py", mtime=200),
        ]
        result = _sort_items(items, "modified_asc")
        assert [r.props.display_name for r in result] == ["old.py", "mid.py", "new.py"]

    def test_size_desc(self):
        items = [
            _make_row("small.py", "/s.py", size=100),
            _make_row("big.py", "/b.py", size=5000),
            _make_row("med.py", "/m.py", size=1000),
        ]
        result = _sort_items(items, "size_desc")
        assert [r.props.display_name for r in result] == ["big.py", "med.py", "small.py"]

    def test_size_asc(self):
        items = [
            _make_row("big.py", "/b.py", size=5000),
            _make_row("small.py", "/s.py", size=100),
            _make_row("med.py", "/m.py", size=1000),
        ]
        result = _sort_items(items, "size_asc")
        assert [r.props.display_name for r in result] == ["small.py", "med.py", "big.py"]


class TestTreeHierarchyPreserved:
    """Children must stay under their parent after sort."""

    def test_children_stay_under_parent(self):
        """Expanding src/ keeps its children grouped, not mixed with root items."""
        # Store order after expand (children inserted right after parent):
        items = [
            _make_row("src", "/proj/src", is_dir=True, depth=0, parent=""),
            _make_row("zzz.py", "/proj/src/zzz.py", depth=1, parent="/proj/src"),
            _make_row("aaa.py", "/proj/src/aaa.py", depth=1, parent="/proj/src"),
            _make_row("tests", "/proj/tests", is_dir=True, depth=0, parent=""),
            _make_row("main.py", "/proj/main.py", depth=0, parent=""),
        ]
        result = _sort_items(items, "name_asc")
        names = [(r.props.display_name, r.props.parent_full_path) for r in result]
        # Children of src must stay together, right after src
        assert names == [
            ("src", ""),
            ("aaa.py", "/proj/src"),
            ("zzz.py", "/proj/src"),
            ("tests", ""),
            ("main.py", ""),
        ]

    def test_nested_expansion_preserved(self):
        """Two expanded dirs — children don't mix."""
        items = [
            _make_row("mmm_dir", "/mmm", is_dir=True, depth=0, parent=""),
            _make_row("zzz_child.py", "/mmm/zzz.py", depth=1, parent="/mmm"),
            _make_row("zzz_dir", "/zzz", is_dir=True, depth=0, parent=""),
            _make_row("aaa_child.py", "/zzz/aaa.py", depth=1, parent="/zzz"),
        ]
        result = _sort_items(items, "name_asc")
        names = [r.props.display_name for r in result]
        # mmm_dir's children must not mix with zzz_dir's children
        assert names == ["mmm_dir", "zzz_child.py", "zzz_dir", "aaa_child.py"]


class TestDrawerSorting:
    """Drawers must stay adjacent to their parent file."""

    def test_drawer_stays_after_parent(self):
        items = [
            _make_row("apple.py", "/apple.py"),
            _make_row("", "", drawer=True, parent_fp="/apple.py"),
            _make_row("banana.py", "/banana.py"),
        ]
        result = _sort_items(items, "name_asc")
        names = [(r.props.display_name or "[drawer]", r.props.parent_full_path) for r in result]
        assert names == [
            ("apple.py", ""),
            ("[drawer]", "/apple.py"),
            ("banana.py", ""),
        ]

    def test_multiple_drawers_stay_adjacent(self):
        """Scrambled insertion — drawers must follow their parents."""
        items = [
            _make_row("cherry.py", "/cherry.py"),
            _make_row("", "", drawer=True, parent_fp="/banana.py"),
            _make_row("apple.py", "/apple.py"),
            _make_row("", "", drawer=True, parent_fp="/apple.py"),
            _make_row("banana.py", "/banana.py"),
        ]
        result = _sort_items(items, "name_asc")
        # Each drawer must be right after its parent
        for i, item in enumerate(result):
            if item.props.is_drawer:
                parent = item.props.parent_full_path
                assert i > 0, "drawer at position 0"
                assert result[i - 1].props.full_path == parent, \
                    f"drawer for {parent} not after parent"


class TestFilterFunc:
    """Test _filter_func directly."""

    def test_substring_match(self):
        row = _make_row("hello.py", "/src/hello.py")
        assert FileTree._filter_func(row, "hello") is True
        assert FileTree._filter_func(row, "HELLO") is True
        assert FileTree._filter_func(row, "src") is True
        assert FileTree._filter_func(row, "xyz") is False

    def test_none_returns_false(self):
        assert FileTree._filter_func(None, "query") is False

    def test_none_query_returns_false(self):
        row = _make_row("test.py", "/test.py")
        assert FileTree._filter_func(row, None) is False

    def test_empty_query_returns_true(self):
        row = _make_row("test.py", "/test.py")
        assert FileTree._filter_func(row, "") is True

    def test_drawer_matches_via_parent(self):
        row = _make_row("", "", drawer=True, parent_fp="/src/main.py")
        assert FileTree._filter_func(row, "main") is True
        assert FileTree._filter_func(row, "src") is True
        assert FileTree._filter_func(row, "other") is False

    def test_none_full_path_safe(self):
        """_filter_func must not crash on None full_path."""
        row = FileTreeRow(display_name="test", full_path=None)
        assert FileTree._filter_func(row, "test") is True
        assert FileTree._filter_func(row, "other") is False


class TestSignalBlockHelper:
    """Test _set_dropdown_silently exception safety."""

    def test_handler_block_and_unblock_called(self):
        from unittest.mock import MagicMock
        dd = MagicMock()
        FileTree._set_dropdown_silently(dd, 42, 2)
        dd.handler_block.assert_called_once_with(42)
        dd.set_selected.assert_called_once_with(2)
        dd.handler_unblock.assert_called_once_with(42)

    def test_unblock_on_exception(self):
        from unittest.mock import MagicMock
        dd = MagicMock()
        dd.set_selected.side_effect = RuntimeError("boom")
        try:
            FileTree._set_dropdown_silently(dd, 42, 2)
        except RuntimeError:
            pass
        dd.handler_block.assert_called_once_with(42)
        dd.handler_unblock.assert_called_once_with(42)
