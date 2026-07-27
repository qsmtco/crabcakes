# tests/test_file_tree_handler.py
# Tests for FileTreeHandler — pure Python, no GTK imports.

import os
import json
import pytest
from unittest.mock import patch

from ui.handlers.file_tree_handler import FileTreeHandler


class TestFileTreeHandler:
    """Test FileTreeHandler — prefs persistence, git status cache, sort modes."""

    def test_init_empty_path(self):
        """__init__ with empty path => sort_mode is 'name_asc', git_status_cache is {}."""
        h = FileTreeHandler()
        assert h.get_sort_mode() == "name_asc"
        assert h._git_status_cache == {}

    def test_init_with_prefs_path_valid(self, tmp_path):
        """__init__ with a tmp_path that has .crabcakes/file_tree_prefs.json with valid mode."""
        prefs_dir = tmp_path / ".crabcakes"
        prefs_dir.mkdir(parents=True)
        prefs_file = prefs_dir / "file_tree_prefs.json"
        prefs_file.write_text(json.dumps({"sort_mode": "size_desc"}))
        h = FileTreeHandler(str(tmp_path))
        assert h.get_sort_mode() == "size_desc"
        assert h._prefs_path == str(prefs_file)

    def test_load_prefs_invalid_mode_fallback(self, tmp_path):
        """_load_prefs with invalid mode in file => falls back to 'name_asc' (BUG #13)."""
        prefs_dir = tmp_path / ".crabcakes"
        prefs_dir.mkdir(parents=True)
        prefs_file = prefs_dir / "file_tree_prefs.json"
        prefs_file.write_text(json.dumps({"sort_mode": "bogus_mode"}))
        h = FileTreeHandler(str(tmp_path))
        assert h.get_sort_mode() == "name_asc"

    def test_load_prefs_missing_file(self, tmp_path):
        """_load_prefs with missing file => 'name_asc'."""
        h = FileTreeHandler(str(tmp_path))
        # No prefs file exists
        assert h.get_sort_mode() == "name_asc"

    def test_load_prefs_corrupt_json(self, tmp_path):
        """_load_prefs with corrupt JSON => 'name_asc'."""
        prefs_dir = tmp_path / ".crabcakes"
        prefs_dir.mkdir(parents=True)
        prefs_file = prefs_dir / "file_tree_prefs.json"
        prefs_file.write_text("not valid json {{{")
        h = FileTreeHandler(str(tmp_path))
        assert h.get_sort_mode() == "name_asc"

    def test_set_sort_mode_valid_updates_and_saves(self, tmp_path):
        """set_sort_mode with valid mode => updates sort_mode + saves to disk."""
        h = FileTreeHandler(str(tmp_path))
        h.set_sort_mode("name_desc")
        assert h.get_sort_mode() == "name_desc"
        # Verify saved to disk
        prefs_file = tmp_path / ".crabcakes" / "file_tree_prefs.json"
        assert prefs_file.exists()
        saved = json.loads(prefs_file.read_text())
        assert saved["sort_mode"] == "name_desc"

    def test_set_sort_mode_invalid_ignored(self, tmp_path):
        """set_sort_mode with invalid mode => ignored (BUG #13)."""
        h = FileTreeHandler(str(tmp_path))
        h.set_sort_mode("name_asc")  # valid, set default
        h.set_sort_mode("invalid_mode")
        assert h.get_sort_mode() == "name_asc"  # unchanged

    def test_set_sort_mode_same_mode_no_write(self, tmp_path):
        """set_sort_mode with same mode => no disk write (idempotent)."""
        h = FileTreeHandler(str(tmp_path))
        h.set_sort_mode("name_desc")  # first write
        prefs_file = tmp_path / ".crabcakes" / "file_tree_prefs.json"
        mtime_before = os.path.getmtime(prefs_file)
        h.set_sort_mode("name_desc")  # same mode, should not write
        mtime_after = os.path.getmtime(prefs_file)
        assert mtime_before == mtime_after

    def test_refresh_git_status_non_repo(self, tmp_path):
        """refresh_git_status on non-repo => {}."""
        h = FileTreeHandler(str(tmp_path))
        result = h.refresh_git_status()
        assert result == {}
        assert not h._git_status_dirty

    @patch("ui.handlers.file_tree_handler.status_porcelain")
    def test_refresh_git_status_caches(self, mock_status_porcelain):
        """refresh_git_status caches (calls status_porcelain once, returns cache on 2nd call)."""
        mock_status_porcelain.return_value = {"file.py": "M "}
        h = FileTreeHandler("/fake/repo")
        # First call
        result1 = h.refresh_git_status()
        assert result1 == {"file.py": "M "}
        assert mock_status_porcelain.call_count == 1
        # Second call returns cache
        result2 = h.refresh_git_status()
        assert result2 == {"file.py": "M "}
        assert mock_status_porcelain.call_count == 1  # still 1

    @patch("ui.handlers.file_tree_handler.status_porcelain")
    def test_invalidate_git_status(self, mock_status_porcelain):
        """invalidate_git_status marks dirty, forcing re-fetch on next refresh."""
        mock_status_porcelain.return_value = {"file.py": "M "}
        h = FileTreeHandler("/fake/repo")
        h.refresh_git_status()
        assert mock_status_porcelain.call_count == 1
        h.invalidate_git_status()
        h.refresh_git_status()
        assert mock_status_porcelain.call_count == 2  # re-fetched

    @patch("ui.handlers.file_tree_handler.status_porcelain")
    def test_set_project_path_new_path(self, mock_status_porcelain, tmp_path):
        """set_project_path with new path => invalidates git, loads prefs."""
        mock_status_porcelain.return_value = {}
        # Create prefs in tmp_path
        prefs_dir = tmp_path / ".crabcakes"
        prefs_dir.mkdir(parents=True)
        prefs_file = prefs_dir / "file_tree_prefs.json"
        prefs_file.write_text(json.dumps({"sort_mode": "modified_asc"}))

        h = FileTreeHandler()
        assert h.get_sort_mode() == "name_asc"  # default
        h.set_project_path(str(tmp_path))
        assert h.get_sort_mode() == "modified_asc"  # loaded from prefs
        assert h._git_status_dirty is True

    def test_set_project_path_empty_resets(self, tmp_path):
        """set_project_path('') => resets sort to 'name_asc' and clears prefs_path."""
        h = FileTreeHandler(str(tmp_path))
        h.set_sort_mode("size_desc")
        h.set_project_path("")
        assert h.get_sort_mode() == "name_asc"
        assert h._prefs_path == ""

    def test_save_prefs_creates_crabcakes_dir(self, tmp_path):
        """_save_prefs creates .crabcakes/ dir if missing."""
        h = FileTreeHandler(str(tmp_path))
        # Remove the prefs dir that was created during init
        prefs_dir = tmp_path / ".crabcakes"
        if prefs_dir.exists():
            import shutil
            shutil.rmtree(prefs_dir)
        assert not prefs_dir.exists()
        h.set_sort_mode("name_desc")  # triggers _save_prefs
        assert prefs_dir.exists()
        assert (prefs_dir / "file_tree_prefs.json").exists()

    # ── Phase 4 audit fix tests ────────────────────────────────────────

    @patch("ui.handlers.file_tree_handler.status_porcelain")
    def test_cache_not_mutated_by_caller(self, mock_status_porcelain):
        """refresh_git_status returns a copy, not the internal cache (BUG #15)."""
        mock_status_porcelain.return_value = {"file.py": "M "}
        h = FileTreeHandler("/fake/repo")
        r1 = h.refresh_git_status()
        r1["injected.py"] = "??"
        r2 = h.refresh_git_status()
        assert "injected.py" not in r2, "caller mutated internal cache"

    def test_set_sort_mode_unhashable_type(self):
        """set_sort_mode with unhashable type does not crash (BUG #18)."""
        h = FileTreeHandler()
        h.set_sort_mode([])   # should not raise
        h.set_sort_mode({})   # should not raise
        assert h.get_sort_mode() == "name_asc"

    @patch("ui.handlers.file_tree_handler.status_porcelain")
    def test_set_project_path_clears_cache(self, mock_status_porcelain):
        """set_project_path clears _git_status_cache (BUG #26)."""
        mock_status_porcelain.return_value = {}
        h = FileTreeHandler("/old/repo")
        h.refresh_git_status()
        h._git_status_cache["stale.py"] = "M "  # simulate stale data
        h.set_project_path("/new/repo")
        assert h._git_status_cache == {}, "cache not cleared on project switch"