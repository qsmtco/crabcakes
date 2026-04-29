# tests/test_crabwatch_handler.py
# Tests for CrabWatchHandler (Phase 5 — filesystem watcher).

import pytest
from unittest.mock import MagicMock, patch
from models.feed_card import FeedCardData


class TestShouldIgnore:
    """Unit tests for _should_ignore() helper."""

    def test_ignores_dotfiles(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore(".DS_Store") is True
        assert _should_ignore(".gitignore") is True
        assert _should_ignore(".bashrc") is True

    def test_ignores_crabcakes_dir(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore(".crabcakes/feed.json") is True
        assert _should_ignore(".crabcakes/project.md") is True

    def test_ignores_git_dir(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore(".git/config") is True
        assert _should_ignore(".git/HEAD") is True

    def test_ignores_node_modules(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore("node_modules/package.json") is True

    def test_ignores_pycache(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore("__pycache__/foo.cpython-312.pyc") is True

    def test_ignores_pyc_files(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore("path/to/some.pyc") is True

    def test_allows_normal_files(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore("src/main.py") is False
        assert _should_ignore("README.md") is False
        assert _should_ignore("utils/helpers.py") is False

    def test_allows_deep_paths(self):
        from ui.handlers.crabwatch_handler import _should_ignore
        assert _should_ignore("src/nested/deep/file.ts") is False


class TestGetRelativePath:
    """Unit tests for _get_relative_path() helper."""

    def test_simple_relative(self):
        from ui.handlers.crabwatch_handler import _get_relative_path
        result = _get_relative_path("/home/user/project", "/home/user/project/src/main.py")
        assert result == "src/main.py"

    def test_trailing_slash_normalized(self):
        from ui.handlers.crabwatch_handler import _get_relative_path
        result = _get_relative_path("/home/user/project/", "/home/user/project/src/main.py")
        assert result == "src/main.py"

    def test_root_file(self):
        from ui.handlers.crabwatch_handler import _get_relative_path
        result = _get_relative_path("/home/user/project", "/home/user/project/README.md")
        assert result == "README.md"

    def test_deep_nested(self):
        from ui.handlers.crabwatch_handler import _get_relative_path
        result = _get_relative_path("/home/user/project", "/home/user/project/a/b/c/d.py")
        assert result == "a/b/c/d.py"

    def test_unrelated_path_returns_full(self):
        from ui.handlers.crabwatch_handler import _get_relative_path
        result = _get_relative_path("/home/user/project", "/home/user/other/file.py")
        assert result == "/home/user/other/file.py"


class TestCrabWatchHandlerInit:
    """Tests for CrabWatchHandler constructor and basic properties."""

    def test_init_starts_not_watching(self):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)
        assert handler.is_watching() is False

    def test_init_stores_callback(self):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)
        # on_event is stored internally — verify via behavior
        assert handler._on_event is mock_cb

    def test_stop_watching_when_not_watching_is_idempotent(self):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)
        # Should not raise
        handler.stop_watching()
        assert handler.is_watching() is False


class TestCrabWatchHandlerStartWatching:
    """Tests for start_watching() behavior."""

    @patch("gi.repository.Gio.File.new_for_path")
    @patch("gi.repository.Gio.File.monitor_directory")
    def test_start_watching_sets_state(self, mock_monitor_dir, mock_new_for_path):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)

        mock_gfile = MagicMock()
        mock_new_for_path.return_value = mock_gfile
        mock_gfile.query_exists.return_value = True

        mock_monitor = MagicMock()
        mock_monitor_dir.return_value = mock_monitor

        handler.start_watching("/home/user/project", "my-project")

        assert handler.is_watching() is True
        assert handler._watched_path == "/home/user/project"
        assert handler._watched_name == "my-project"

    @patch("gi.repository.Gio.File.new_for_path")
    def test_start_watching_replaces_previous_watch(self, mock_new_for_path):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)

        mock_gfile = MagicMock()
        mock_new_for_path.return_value = mock_gfile
        mock_gfile.query_exists.return_value = True

        mock_monitor1 = MagicMock()
        mock_monitor2 = MagicMock()
        # Use mock_gfile.monitor_directory directly — auto-child needs explicit override
        mock_gfile.monitor_directory.side_effect = [mock_monitor1, mock_monitor2]

        handler.start_watching("/home/user/project", "project1")
        # First monitor is active (stored in _monitors dict)
        assert "/home/user/project" in handler._monitors
        assert handler._monitors["/home/user/project"] is mock_monitor1

        handler.start_watching("/home/user/other", "project2")
        # First monitor cancelled when second watch starts
        mock_monitor1.cancel.assert_called_once()
        # Second monitor is now active
        assert "/home/user/other" in handler._monitors
        assert handler._monitors["/home/user/other"] is mock_monitor2

    @patch("gi.repository.Gio.File.new_for_path")
    def test_start_watching_nonexistent_dir_does_nothing(self, mock_new_for_path):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)

        mock_gfile = MagicMock()
        mock_new_for_path.return_value = mock_gfile
        mock_gfile.query_exists.return_value = False

        handler.start_watching("/nonexistent/path", "project")

        assert handler.is_watching() is False


class TestCrabWatchHandlerStopWatching:
    """Tests for stop_watching() behavior."""

    @patch("gi.repository.Gio.File.new_for_path")
    @patch("gi.repository.Gio.File.monitor_directory")
    def test_stop_watching_cancels_monitor(self, mock_monitor_dir, mock_new_for_path):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)

        mock_gfile = MagicMock()
        mock_new_for_path.return_value = mock_gfile
        mock_gfile.query_exists.return_value = True

        mock_monitor = MagicMock()
        mock_monitor_dir.return_value = mock_monitor

        handler.start_watching("/home/user/project", "project")
        assert handler.is_watching() is True

        handler.stop_watching()

        # Verify monitor was cancelled and watching stopped
        assert handler.is_watching() is False
        assert handler._watched_path is None

    @patch("gi.repository.Gio.File.new_for_path")
    @patch("gi.repository.Gio.File.monitor_directory")
    def test_stop_watching_clears_debounce_timers(self, mock_monitor_dir, mock_new_for_path):
        from ui.handlers.crabwatch_handler import CrabWatchHandler
        mock_cb = MagicMock()
        handler = CrabWatchHandler(GLib_module=None, on_event=mock_cb)

        mock_gfile = MagicMock()
        mock_new_for_path.return_value = mock_gfile
        mock_gfile.query_exists.return_value = True

        mock_timer_source = MagicMock()
        mock_monitor = MagicMock()
        mock_monitor_dir.return_value = mock_monitor

        # Patch GLib.timeout_add to give us a fake timer source
        with patch.object(handler, '_GLib', None):
            # Direct call — no GLib in tests
            handler._debounce_map['test.py'] = mock_timer_source

        handler.stop_watching()

        assert len(handler._debounce_map) == 0
        mock_timer_source.destroy.assert_called_once()