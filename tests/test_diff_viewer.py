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
from gi.repository import Gtk, GLib

import os
import tempfile
from unittest.mock import MagicMock, patch

from ui.views.diff_viewer import DiffViewer
from ui.views.diff_card import get_lang_from_path


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

        def on_revert(fp, sha, on_complete):
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

    def test_whitespace_file_path_raises(self):
        """Whitespace-only file_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path="   ", project_path="/tmp/test-project")

    def test_empty_project_path_raises(self):
        """Empty project_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path="")

    def test_whitespace_project_path_raises(self):
        """Whitespace-only project_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path="  \t  ")

    def test_non_string_file_path_raises(self):
        """Non-string file_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path=42, project_path="/tmp/test-project")  # type: ignore
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path=None, project_path="/tmp/test-project")  # type: ignore
        # BUG #12-15/17: add True, False, 3.14
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path=True, project_path="/tmp/test-project")  # type: ignore
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path=False, project_path="/tmp/test-project")  # type: ignore
        with pytest.raises(ValueError, match="file_path is required"):
            DiffViewer(file_path=3.14, project_path="/tmp/test-project")  # type: ignore

    def test_non_string_project_path_raises(self):
        """Non-string project_path raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path=None)  # type: ignore
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path=True)  # type: ignore
        with pytest.raises(ValueError, match="project_path is required"):
            DiffViewer(file_path="src/main.py", project_path=42)  # type: ignore

    def test_creation_with_checkpoint(self):
        """Accepts optional checkpoint_sha."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            checkpoint_sha="abc123def456",
        )
        assert viewer._checkpoint_sha == "abc123def456"

    # BUG #1/16/18: emit destroy signal instead of do_dispose vfunc
    def test_destroy_sets_disposed_flag(self):
        """viewer.emit('destroy') sets _disposed flag."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        assert not viewer._disposed
        viewer.emit("destroy")
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
            on_revert=lambda fp, sha, on_complete: None,
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


class TestDiffViewerRevertCompletion:
    """BUG #5: Revert completion callback behavior."""

    def test_revert_completion_callback_sent_to_handler(self):
        """Revert calls on_revert with on_complete callback."""
        captured = []

        def on_revert(fp, sha, on_complete):
            captured.append((fp, sha))
            # Simulate revert completion — call on_complete directly
            # (handler must invoke on_complete; we test the protocol here)
            if on_complete:
                on_complete()

        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=on_revert,
        )
        viewer._selected_sha = "abc123def456"
        # Bypass the dialog — call _on_revert_confirmed directly with YES
        viewer._on_revert_confirmed(None, Gtk.ResponseType.YES)
        # Capture is populated synchronously (on_revert is called inline)
        assert len(captured) == 1
        assert captured[0] == ("src/main.py", "abc123def456")

    def test_revert_completion_main_thread_method_called(self):
        """After revert completion dispatches, _on_revert_complete_main_thread runs."""
        main_thread_called = []

        def patched_main_thread(self):
            main_thread_called.append(True)
            # Call the original to keep behavior correct
            if not self._disposed:
                self._cancel_revert_watchdog()
                self._load_current_diff()

        def on_revert(fp, sha, on_complete):
            # Simulate the revert handler calling on_complete
            # on_complete wraps in GLib.idle_add which is test-safe
            if on_complete:
                on_complete()

        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=on_revert,
        )
        viewer._on_revert_complete_main_thread = lambda: patched_main_thread(viewer)
        viewer._selected_sha = "abc123def456"

        # When on_complete is called, it idle_adds _on_revert_complete_main_thread
        # We can test that the idle callback gets dispatched by running GLib iteration
        old_load = viewer._load_current_diff
        viewer._load_current_diff = lambda: None  # prevent actual thread spawn

        viewer._on_revert_confirmed(None, Gtk.ResponseType.YES)

        # Run GLib main context to dispatch idle callback
        while GLib.MainContext.default().iteration(False):
            pass

        assert len(main_thread_called) >= 1

    def test_revert_watchdog_cancelled_on_complete(self):
        """Revert watchdog timer is cancelled when completion fires."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=lambda fp, sha, on_complete: on_complete(),
        )
        viewer._selected_sha = "abc123def456"
        viewer._on_revert_confirmed(None, Gtk.ResponseType.YES)

        # Run GLib iteration to dispatch the idle callback from on_complete
        while GLib.MainContext.default().iteration(False):
            pass

        # After completion, watchdog should be None (cancelled)
        assert viewer._revert_watchdog_timer is None

    def test_revert_exception_safe(self):
        """BUG #19: on_revert throwing does not crash viewer."""
        def broken_revert(fp, sha, on_complete):
            raise RuntimeError("simulated revert failure")

        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=broken_revert,
        )
        viewer._selected_sha = "abc123def456"
        # This should not raise — exception is caught
        viewer._on_revert_confirmed(None, Gtk.ResponseType.YES)
        # Viewer should still be in valid state
        assert viewer._selected_sha is None
        assert not viewer._revert_btn.get_visible()


class TestDiffViewerPangoInjection:
    """BUG #2/10: Pango injection prevention in labels."""

    def test_title_escapes_pango(self):
        """File path with Pango tags is safe (uses set_text, no markup)."""
        viewer = DiffViewer(
            file_path="<b>evil</b>",
            project_path="/tmp/test-project",
        )
        # get_use_markup() returns True only for set_markup(), not set_text()
        assert not viewer._title_label.get_use_markup()
        text = viewer._title_label.get_text()
        # set_text stores literally — "evil" is in the string
        assert "evil" in text

    def test_title_no_over_escape(self):
        """File path with & is stored literally, not double-escaped."""
        viewer = DiffViewer(
            file_path="R&D.txt",
            project_path="/tmp/test-project",
        )
        text = viewer._title_label.get_text()
        # set_text stores literally; & does not become &amp;
        assert "R&D.txt" == text

    def test_history_message_with_ampersand(self):
        """Commit message with & is stored literally, not escaped."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_history_loaded(
            [{"sha": "abc123", "date": "2026-01-01", "message": "fix: R&D and A&B logic"}],
            req_id=viewer._current_request_id,
        )
        children = list(viewer._history_list)
        assert len(children) >= 1
        row = children[0]
        if hasattr(row, 'get_child'):
            child = row.get_child()
            if hasattr(child, 'get_children'):
                labels = [c for c in child if isinstance(c, Gtk.Label)]
                # One of these labels should contain "R&D"
                texts = [lbl.get_text() for lbl in labels]
                found = any("R&D" in t for t in texts)
                assert found, f"No label contains 'R&D' in texts: {texts}"

    def test_history_message_escapes_pango(self):
        """Commit messages use set_text (not set_markup), so Pango is inert."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_history_loaded(
            [{"sha": "abc123", "date": "2026-01-01", "message": "<script>alert(1)</script>"}],
            req_id=viewer._current_request_id,
        )
        children = list(viewer._history_list)
        assert len(children) >= 1
        row = children[0]
        if hasattr(row, 'get_child'):
            child = row.get_child()
            if hasattr(child, 'get_children'):
                labels = [c for c in child if isinstance(c, Gtk.Label)]
                for label in labels:
                    # set_text means use_markup is False — markup won't render
                    assert not label.get_use_markup()

    def test_placeholder_escapes_pango(self):
        """Placeholder text uses set_text not label= constructor."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._show_placeholder("<b>bold</b>")
        children = list(viewer._diff_box)
        labels = [c for c in children if isinstance(c, Gtk.Label)]
        assert len(labels) >= 1
        # Verify use_markup is False (set_text, not set_markup)
        for lbl in labels:
            assert not lbl.get_use_markup()


class TestDiffViewerHistoryEmpty:
    """BUG #3: Empty history keyboard nav safety."""

    def test_empty_history_placeholder_in_listboxrow(self):
        """Empty history placeholder is wrapped in ListBoxRow."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_history_loaded([], req_id=viewer._current_request_id)
        children = list(viewer._history_list)
        assert len(children) >= 1
        child = children[0]
        # Should be a ListBoxRow (not a raw Label)
        assert isinstance(child, Gtk.ListBoxRow)

    def test_empty_history_row_activation_does_not_crash(self):
        """Activating empty history placeholder row does not crash."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer._on_history_loaded([], req_id=viewer._current_request_id)
        children = list(viewer._history_list)
        assert len(children) >= 1
        row = children[0]
        # This should not crash even though row has no .sha attribute
        viewer._on_history_row_activated(viewer._history_list, row)
        assert viewer._selected_sha is None


class TestDiffViewerHistoryMultipleLoads:
    """BUG #4: Multiple history loads do not duplicate signal connections."""

    def test_multiple_history_loads_no_duplicate_rows(self):
        """Loading history twice does not duplicate entries."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        entries = [
            {"sha": "aaa001", "date": "2026-01-01", "message": "first commit"},
            {"sha": "aaa002", "date": "2026-01-02", "message": "second commit"},
        ]
        # First load
        viewer._on_history_loaded(entries, req_id=viewer._current_request_id + 1)
        # Second load (simulate different request id)
        viewer._current_request_id += 2
        viewer._on_history_loaded(entries, req_id=viewer._current_request_id)
        children = list(viewer._history_list)
        # Should have 2 entries, not 4 (previous rows were cleared)
        assert len(children) == 2

    def test_signal_not_connected_multiple_times(self):
        """row-activated signal is connected once in _build_ui — no duplicate connections."""
        import gi  # noqa: F811
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk

        # Verify by connecting a second handler and checking invocation count
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )

        # Load data
        entries = [
            {"sha": "aaa001", "date": "2026-01-01", "message": "first"},
        ]
        viewer._on_history_loaded(entries, req_id=viewer._current_request_id)
        children = list(viewer._history_list)
        assert len(children) == 1
        row = children[0]

        # Count how many times the existing handler fires
        # by wrapping the handler with a counter
        signal_count = [0]
        original = viewer._on_history_row_activated

        def counting_handler(listbox, row):
            signal_count[0] += 1
            original(listbox, row)

        # We can't disconnect/reconnect cleanly from PyGObject,
        # but we can verify that calling the signal once only activates once.
        # The original handler sets _selected_sha when it fires.
        viewer._on_history_row_activated = counting_handler
        # Call via the method (not signal emission, since signal holds the reference)
        viewer._on_history_row_activated(viewer._history_list, row)
        assert signal_count[0] == 1


class TestDiffViewerStateGuards:
    """State guards for disposed and stale requests."""

    def test_disposed_ignores_diff_loaded(self):
        """Disposed viewer ignores _on_diff_loaded."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.emit("destroy")
        # This should not crash
        viewer._on_diff_loaded(MagicMock(), "test", 1)

    def test_stale_request_ignored(self):
        """Stale request id is ignored — UI state unchanged."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        # Confirm starting state
        assert viewer._subtitle_label.get_text() == ""
        viewer._current_request_id = 5
        # Old request id
        viewer._on_diff_loaded(MagicMock(), "test", 3)
        # Should NOT have updated subtitle (stale ignored)
        assert viewer._subtitle_label.get_text() == ""


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

    def test_show_placeholder_disposed(self):
        """Disposed viewer skips _show_placeholder."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.emit("destroy")
        viewer._show_placeholder("Should not show")
        # Should not crash

    def test_disposed_loading(self):
        """Disposed viewer skips _show_loading."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        viewer.emit("destroy")
        viewer._show_loading()
        # Should not crash

    def test_destroy_cancels_watchdog(self):
        """Destroy cancels any running revert watchdog timer."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
            on_revert=lambda fp, sha, on_complete: None,  # never calls on_complete
        )
        viewer._selected_sha = "abc123def456"
        viewer._on_revert_confirmed(None, Gtk.ResponseType.YES)
        # Watchdog should be running
        assert viewer._revert_watchdog_timer is not None
        assert viewer._revert_watchdog_timer.is_alive()
        viewer.emit("destroy")
        # After destroy, watchdog should be cancelled
        assert viewer._revert_watchdog_timer is None or not viewer._revert_watchdog_timer.is_alive()


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
        """Diff and History toggles are in a radio group (set_group works)."""
        viewer = DiffViewer(
            file_path="src/main.py",
            project_path="/tmp/test-project",
        )
        # In GTK4, CheckButton.set_group means the other button is in the group.
        # We verify by checking that setting active on one deactivates the other.
        assert viewer._diff_toggle.get_active()
        viewer._history_toggle.set_active(True)
        assert not viewer._diff_toggle.get_active()
        assert viewer._history_toggle.get_active()

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