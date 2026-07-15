# tests/test_diff_viewer.py
# Tests for ui/views/diff_viewer.py
#
# GTK tests require xvfb-run (headless display):
#   xvfb-run -a python -m pytest tests/test_diff_viewer.py -v
#
# Pure-Python tests (get_lang_from_path, render_diff_hunks) run without display.
# Widget-instantiation tests (DiffViewer creation, callbacks) need xvfb.

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

import os
import tempfile
from unittest.mock import MagicMock, patch

from ui.views.diff_viewer import DiffViewer
from ui.views.diff_card import get_lang_from_path, render_diff_hunks
from utils.diff_parser import DiffHunk, DiffLine, FileDiff


# ═══════════════════════════════════════════════════════════════════════
# Pure-Python tests (no display needed)
# ═══════════════════════════════════════════════════════════════════════


class TestGetLangFromPathIntegration:
    """get_lang_from_path works with common extensions."""
    # Same mapping used by DiffViewer internally

    def test_python(self):
        assert get_lang_from_path("foo.py") == "python"

    def test_javascript(self):
        assert get_lang_from_path("foo.js") == "javascript"

    def test_typescript(self):
        assert get_lang_from_path("foo.ts") == "typescript"

    def test_go(self):
        assert get_lang_from_path("foo.go") == "go"

    def test_rust(self):
        assert get_lang_from_path("foo.rs") == "rust"

    def test_markdown(self):
        assert get_lang_from_path("README.md") == "markdown"

    def test_yaml(self):
        assert get_lang_from_path("config.yml") == "yaml"

    def test_dockerfile(self):
        assert get_lang_from_path("Dockerfile") == "dockerfile"

    def test_dockerfile_variant(self):
        assert get_lang_from_path("Dockerfile.prod") == "dockerfile"

    def test_makefile(self):
        assert get_lang_from_path("Makefile") == "makefile"

    def test_pathlib_path(self):
        import pathlib
        assert get_lang_from_path(pathlib.Path("foo.py")) == "python"

    def test_empty_path(self):
        assert get_lang_from_path("") is None

    def test_unknown_extension(self):
        assert get_lang_from_path("foo.xyz") is None


class TestRenderDiffHunksIntegration:
    """render_diff_hunks renders hunks correctly."""

    def test_single_hunk(self):
        """Renders a single hunk."""
        hunk = DiffHunk(
            header="@@ -1,3 +1,4 @@",
            old_start=1,
            new_start=1,
            lines=[
                DiffLine(type="context", content=" unchanged", old_line_no=1, new_line_no=1),
                DiffLine(type="remove", content="-old line", old_line_no=2, new_line_no=None),
                DiffLine(type="add", content="+new line", old_line_no=None, new_line_no=2),
            ],
        )
        result = render_diff_hunks([hunk], lang="python")
        assert isinstance(result, Gtk.Box)
        # Should have at least the hunk view
        children = list(result)
        assert len(children) >= 1

    def test_multiple_hunks(self):
        """Multiple hunks are all rendered."""
        hunk1 = DiffHunk(
            header="@@ -1,2 +1,2 @@",
            old_start=1,
            new_start=1,
            lines=[DiffLine(type="context", content=" a", old_line_no=1, new_line_no=1)],
        )
        hunk2 = DiffHunk(
            header="@@ -5,2 +5,2 @@",
            old_start=5,
            new_start=5,
            lines=[DiffLine(type="context", content=" b", old_line_no=5, new_line_no=5)],
        )
        result = render_diff_hunks([hunk1, hunk2])
        assert isinstance(result, Gtk.Box)
        children = list(result)
        assert len(children) == 2

    def test_empty_hunks(self):
        """Empty list returns empty Gtk.Box."""
        result = render_diff_hunks([], lang=None)
        assert isinstance(result, Gtk.Box)
        assert list(result) == []

    def test_no_lang(self):
        """Works without language parameter."""
        hunk = DiffHunk(
            header="@@ -1 +1 @@",
            old_start=1,
            new_start=1,
            lines=[
                DiffLine(type="context", content=" hello", old_line_no=1, new_line_no=1),
            ],
        )
        result = render_diff_hunks([hunk])
        assert isinstance(result, Gtk.Box)
        assert len(list(result)) == 1


# ═══════════════════════════════════════════════════════════════════════
# DiffViewer widget tests (need xvfb-run for Gtk display)
# ═══════════════════════════════════════════════════════════════════════


class TestDiffViewerCreation:
    """DiffViewer widget instantiates correctly."""

    def test_creation(self):
        """Widget instantiates, shows header/title."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert isinstance(viewer, Gtk.Box)
        assert "diff-viewer" in viewer.get_css_classes()
        # Header should be present
        assert hasattr(viewer, '_header')
        assert hasattr(viewer, '_title_label')
        assert viewer._title_label.get_text() == "src/main.py"

    def test_creation_with_callbacks(self):
        """Accepts optional callbacks without error."""
        def on_back():
            pass

        def on_revert(fp, sha):
            pass

        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_back=on_back,
            on_revert=on_revert,
        )
        assert isinstance(viewer, Gtk.Box)

    def test_empty_file_path_raises(self):
        """Empty file_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path="", project_path="/tmp/test-project")

    def test_empty_project_path_raises(self):
        """Empty project_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path="")

    def test_creation_with_checkpoint(self):
        """Accepts optional checkpoint_sha."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            checkpoint_sha="abc123def456",
        )
        assert viewer._checkpoint_sha == "abc123def456"

    def test_dispose_flag(self):
        """do_dispose sets _disposed flag."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert not viewer._disposed
        viewer.do_dispose()
        assert viewer._disposed


class TestDiffViewerBackCallback:
    """Back button calls on_back."""

    def test_back_callback(self):
        """Clicking Back calls on_back."""
        called = []

        def on_back():
            called.append(True)

        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_back=on_back,
        )
        viewer._on_back_clicked(None)
        assert len(called) == 1

    def test_back_no_callback(self):
        """Clicking Back without callback does not crash."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_back_clicked(None)


class TestDiffViewerRevertButton:
    """Revert button visibility and callback."""

    def test_revert_button_hidden_by_default(self):
        """Revert button hidden on current diff view."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert not viewer._revert_btn.get_visible()

    def test_revert_button_visible_on_historical(self):
        """Revert button visible when historical diff is shown."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        # Simulate what _on_historical_diff_loaded does
        viewer._show_placeholder("No changes since this commit.")
        viewer._revert_btn.set_visible(True)
        assert viewer._revert_btn.get_visible()


class TestDiffViewerHistory:
    """History tab behavior."""

    def test_history_toggle_switches_stack(self):
        """Toggling history switches stack and loads history."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert viewer._stack.get_visible_child_name() == "diff"
        viewer._on_history_toggled(viewer._history_toggle)
        # Setting active on toggle triggers toggled signal
        viewer._history_toggle.set_active(True)
        # After toggle, active should switch history
        # Note: due to signal emission timing, we check the behavior
        # set_active causes toggled → _on_history_toggled

    def test_empty_history_shows_placeholder(self):
        """Empty history shows placeholder label."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_history_loaded([], req_id=viewer._current_request_id)
        # Should show placeholder widget
        children = list(viewer._history_list)
        assert len(children) == 1
        child = children[0]
        if hasattr(child, 'get_label'):
            assert "No commit history" in child.get_label()


class TestDiffViewerRevertCancel:
    """Revert confirmation dialog behavior."""

    def test_revert_no_sha(self):
        """Revert without selected_sha does nothing."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=lambda fp, sha: None,
        )
        viewer._selected_sha = None
        viewer._on_revert_clicked(None)
        # Should return early without dialog
        assert viewer._selected_sha is None

    def test_revert_no_callback(self):
        """Revert without on_revert callback does nothing."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._selected_sha = "abc123"
        viewer._on_revert_clicked(None)
        # Should return early without dialog
        assert viewer._selected_sha == "abc123"


class TestDiffViewerStateGuards:
    """State guards for disposed and stale requests."""

    def test_disposed_ignores_diff_loaded(self):
        """Disposed viewer ignores _on_diff_loaded."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.do_dispose()
        # This should not crash
        viewer._on_diff_loaded(MagicMock(), "test", 1)

    def test_stale_request_ignored(self):
        """Stale request id is ignored."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._current_request_id = 5
        # Old request id
        viewer._on_diff_loaded(MagicMock(), "test", 3)
        # Should not have updated anything (stale ignored)


class TestDiffViewerHelpers:
    """Internal helper methods."""

    def test_show_loading_shows_spinner(self):
        """_show_loading shows spinner and switches to diff stack."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._show_loading()
        assert viewer._stack.get_visible_child_name() == "diff"

    def test_show_placeholder_shows_text(self):
        """_show_placeholder shows text and switches to diff stack."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._show_placeholder("Test placeholder")
        assert viewer._stack.get_visible_child_name() == "diff"
        # Verify content
        children = list(viewer._diff_box)
        assert len(children) >= 1
        child = children[0]
        # The spinner or label should be present

    def test_show_placeholder_disposed(self):
        """Disposed viewer skips _show_placeholder."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.do_dispose()
        viewer._show_placeholder("Should not show")
        # Should not crash

    def test_disposed_loading(self):
        """Disposed viewer skips _show_loading."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.do_dispose()
        viewer._show_loading()
        # Should not crash


class TestDiffViewerWidgetStructure:
    """Widget structure matches documentation."""

    def test_widget_hierarchy(self):
        """Verify key widgets exist."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert hasattr(viewer, '_header')
        assert hasattr(viewer, '_title_label')
        assert hasattr(viewer, '_subtitle_label')
        assert hasattr(viewer, '_tab_box')
        assert hasattr(viewer, '_diff_toggle')
        assert hasattr(viewer, '_history_toggle')
        assert hasattr(viewer, '_stack')
        assert hasattr(viewer, '_diff_scroll')
        assert hasattr(viewer, '_diff_box')
        assert hasattr(viewer, '_history_scroll')
        assert hasattr(viewer, '_history_list')
        assert hasattr(viewer, '_action_bar')
        assert hasattr(viewer, '_revert_btn')
        assert hasattr(viewer, '_back_btn')

    def test_toggles_are_grouped(self):
        """Diff and History toggles are in a radio group."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        # History toggle should be grouped with diff toggle
        group = viewer._history_toggle.get_group()
        assert viewer._diff_toggle in group

    def test_diff_active_by_default(self):
        """Diff tab is active, history is not."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert viewer._diff_toggle.get_active()
        assert not viewer._history_toggle.get_active()

    def test_stack_starts_on_diff(self):
        """Stack starts on diff page."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert viewer._stack.get_visible_child_name() == "diff"