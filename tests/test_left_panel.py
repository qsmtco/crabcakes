import os
import tempfile
from unittest.mock import MagicMock, patch

# GTK4 must be importable for tests
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib, Gdk

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.views.left_panel import LeftPanel


class TestPromptRowRightClick:
    """Tests for the right-click copy menu on prompt rows."""

    def test_prompt_row_has_filepath_and_content_attrs(self):
        """Verify _build_prompt_row sets row._filepath and row._prompt_content from the prompt dict."""
        panel = LeftPanel()
        panel._prompts_handler = MagicMock()

        prompt = {
            'filepath': '/abs/path/to/prompt.md',
            'name': 'test-prompt',
            'content': 'This is the prompt content.',
            'is_favorite': False,
            'lines': 10,
            'size': 100,
            'last_used_str': 'today'
        }

        row = panel._build_prompt_row(prompt)

        assert hasattr(row, '_filepath'), "row should have _filepath attribute"
        assert hasattr(row, '_prompt_content'), "row should have _prompt_content attribute"
        assert row._filepath == '/abs/path/to/prompt.md'
        assert row._prompt_content == 'This is the prompt content.'

    def test_copy_path_calls_clipboard_with_filepath(self):
        """Patch Gdk.Display.get_default, call _on_copy_prompt_path, verify clipboard.set was called with filepath."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        row = Gtk.ListBoxRow()
        row._filepath = '/abs/path/to/prompt.md'

        with patch('gi.repository.Gdk.Display.get_default') as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            panel._on_copy_prompt_path(row)

            mock_clipboard.set.assert_called_once_with('/abs/path/to/prompt.md')

    def test_copy_prompt_calls_clipboard_with_content(self):
        """Patch Gdk.Display.get_default, call _on_copy_prompt_content, verify clipboard.set was called with content."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        row = Gtk.ListBoxRow()
        row._prompt_content = 'This is the prompt content.'

        with patch('gi.repository.Gdk.Display.get_default') as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            panel._on_copy_prompt_content(row)

            mock_clipboard.set.assert_called_once_with('This is the prompt content.')

    def test_copy_path_skips_when_filepath_missing(self):
        """Row with no _filepath attr -> no clipboard call, no exception."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        row = Gtk.ListBoxRow()
        # No _filepath attribute

        with patch('gi.repository.Gdk.Display.get_default') as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            panel._on_copy_prompt_path(row)

            mock_clipboard.set.assert_not_called()

    def test_copy_prompt_skips_when_content_missing(self):
        """Row with no _prompt_content attr -> no clipboard call, no exception."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        row = Gtk.ListBoxRow()
        # No _prompt_content attribute

        with patch('gi.repository.Gdk.Display.get_default') as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard

            panel._on_copy_prompt_content(row)

            mock_clipboard.set.assert_not_called()

    def test_copy_status_label_shows_and_clears(self):
        """Verify _show_prompt_copy_status sets label text AND the scheduled
        timeout callback actually clears the label."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        captured_callbacks = []
        def fake_timeout_add(ms, cb):
            captured_callbacks.append((ms, cb))
            return 12345

        with patch('gi.repository.GLib.timeout_add', side_effect=fake_timeout_add):
            panel._show_prompt_copy_status("Copied path")

            # 1. Label text is set
            assert panel._prompt_copy_status_label.get_text() == "Copied path"
            # 2. Timeout was scheduled with 2500ms
            assert len(captured_callbacks) == 1
            assert captured_callbacks[0][0] == 2500
            # 3. Invoke the scheduled callback and verify it clears the label
            captured_callbacks[0][1]()
            assert panel._prompt_copy_status_label.get_text() == ""

    def test_right_click_handler_ignores_multipress(self):
        """Call _on_prompt_row_right_click with n_press=2, verify no popover is created."""
        panel = LeftPanel()
        panel._prompt_copy_status_label = Gtk.Label()
        panel._prompt_copy_status_timeout_id = None

        row = Gtk.ListBoxRow()
        row._filepath = '/abs/path/to/prompt.md'

        with patch('gi.repository.Gtk.Popover') as mock_popover_class:
            mock_popover_class.return_value = MagicMock()

            panel._on_prompt_row_right_click(None, 2, 0, 0, row)

            mock_popover_class.assert_not_called()

    def test_prompt_row_has_right_click_gesture_attached(self):
        """Verify _build_prompt_row actually attaches a right-click GestureClick controller
        to the row. This tests the USER-FACING wiring (Edit 5), not just the helper.

        Per steelFramedCodeWriter Rule 4 + adversarialDebugger §11: a test that only calls
        the handler would pass even if the gesture were never attached, hiding a real
        regression in the right-click wiring.
        """
        panel = LeftPanel()
        panel._prompts_handler = MagicMock()

        prompt = {
            'filepath': '/abs/path/to/prompt.md',
            'name': 'test-prompt',
            'content': 'content',
            'is_favorite': False,
            'lines': 1,
            'size': 1,
            'last_used_str': ''
        }

        row = panel._build_prompt_row(prompt)

        # Inspect the row's controllers — at least one must be a GestureClick
        # configured for the secondary (right) mouse button.
        from gi.repository import Gdk
        observers = row.observe_controllers()
        found_right_click = False
        for ctrl in observers:
            # Gtk.EventController is the base class; Gtk.GestureClick is a subclass.
            if isinstance(ctrl, Gtk.GestureClick):
                if ctrl.get_button() == Gdk.BUTTON_SECONDARY:
                    found_right_click = True
                    break

        assert found_right_click, (
            "Prompt row must have a Gtk.GestureClick controller attached with "
            "button=Gdk.BUTTON_SECONDARY (right-click). If this test fails, the "
            "right-click gesture wiring was removed from _build_prompt_row."
        )