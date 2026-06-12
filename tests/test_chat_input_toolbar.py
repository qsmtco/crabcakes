# tests/test_chat_input_toolbar.py
# Tests for ui/views/chat_input_toolbar.py — Pure view verification.
#
# Architecture:
#   ChatInputToolbar is a pure view — widgets only, no business logic.
#   All logic lives in InputToolbarHandler (tested separately).
#
# Test strategy:
#   - Construction + widget existence: create the view, verify key widgets exist.
#   - Callback wiring: connect mock callbacks, simulate clicks, verify they fire.
#   - Public methods: call set_find_count, set_spell_active, etc. verify state.
#   - Import check: verify the view never imports from ui/handlers/.
#   - GTK3 check: verify no ModelButton or set_keynav_wrapper usage.
#
# GTK initialization: GDK_BACKEND=headless for headless test environments.
# Widget construction is real (not mocked) — we test the actual view.

from __future__ import annotations

import ast
from unittest.mock import MagicMock, patch

import pytest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ui.views.chat_input_toolbar import ChatInputToolbar


# ── Class 1: Construction ─────────────────────────────────────────


class TestConstruction:
    """View instantiates without crash and has the expected widget tree."""

    def test_construction(self):
        """ChatInputToolbar() does not raise."""
        toolbar = ChatInputToolbar()
        assert toolbar is not None
        assert isinstance(toolbar, Gtk.Box)

    def test_has_expected_widgets(self):
        """Key internal widgets exist after construction."""
        toolbar = ChatInputToolbar()
        # Spell toggle button
        assert hasattr(toolbar, "_spell_btn")
        assert isinstance(toolbar._spell_btn, Gtk.ToggleButton)
        # Match label in find bar
        assert hasattr(toolbar, "_match_label")
        assert isinstance(toolbar._match_label, Gtk.Label)
        # Count label (word/char count)
        assert hasattr(toolbar, "_count_label")
        assert isinstance(toolbar._count_label, Gtk.Label)
        # Find entry
        assert hasattr(toolbar, "_find_entry")
        assert isinstance(toolbar._find_entry, Gtk.Entry)
        # Replace entry
        assert hasattr(toolbar, "_replace_entry")
        assert isinstance(toolbar._replace_entry, Gtk.Entry)
        # Find bar container
        assert hasattr(toolbar, "_find_bar")
        assert isinstance(toolbar._find_bar, Gtk.Box)
        # Replace row
        assert hasattr(toolbar, "_replace_row")
        assert isinstance(toolbar._replace_row, Gtk.Box)

    def test_no_handler_imports(self):
        """The view module must NOT import from ui/handlers/ (architecture rule)."""
        import ui.views.chat_input_toolbar as mod

        source = inspect_source(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "ui.handlers" in node.module:
                    pytest.fail(
                        f"View imports from ui/handlers: {node.module} "
                        f"(line {node.lineno}) — violates architecture"
                    )


# ── Class 2: Callback Wiring ──────────────────────────────────────


class TestCallbacks:
    """Callbacks are stored and fire when signals are emitted."""

    def test_on_find_toggled(self):
        """set_on_find stores callback; find_btn click triggers it."""
        toolbar = ChatInputToolbar()
        # The view doesn't expose set_on_find as the callback name.
        # Looking at the code, the find button click calls show_find_bar()
        # which then calls self._on_find. Let's verify _on_find fires.
        calls = []
        toolbar.set_on_find(lambda text: calls.append(text))
        # Simulate find button click
        toolbar._on_find_clicked()
        assert len(calls) == 1

    def test_on_spell_toggled(self):
        """set_on_spell_toggle stores callback; spell toggle triggers it."""
        toolbar = ChatInputToolbar()
        calls = []
        toolbar.set_on_spell_toggle(lambda: calls.append(True))
        # Simulate "toggled" signal: passes toggle button as arg + extra data
        toolbar._on_spell_toggled(toolbar._spell_btn, toolbar._spell_btn)
        assert calls == [True]

    def test_on_open_file(self):
        """set_on_open_file stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_open_file(cb)
        assert toolbar._on_open_file is cb

    def test_on_save_file(self):
        """set_on_save_file stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_save_file(cb)
        assert toolbar._on_save_file is cb

    def test_on_find_closed(self):
        """Close find bar callback fires and clears find state."""
        toolbar = ChatInputToolbar()
        calls = []
        toolbar.set_on_find(lambda text: calls.append(text))
        # Show then close
        toolbar.show_find_bar()
        toolbar._on_find_close_clicked()
        # The close callback passes "" to clear
        assert calls == [""]

    def test_set_on_save_prompt(self):
        """set_on_save_prompt stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_save_prompt(cb)
        assert toolbar._on_save_prompt is cb

    def test_set_on_open_prompt(self):
        """set_on_open_prompt stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_open_prompt(cb)
        assert toolbar._on_open_prompt is cb

    def test_set_on_replace(self):
        """set_on_replace stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_replace(cb)
        assert toolbar._on_replace is cb

    def test_set_on_buffer_changed(self):
        """set_on_buffer_changed stores callback."""
        toolbar = ChatInputToolbar()
        cb = MagicMock()
        toolbar.set_on_buffer_changed(cb)
        assert toolbar._on_buffer_changed is cb


# ── Class 3: Public Methods ───────────────────────────────────────


class TestPublicMethods:
    """Public update methods work correctly."""

    def test_set_find_count_zero(self):
        """update_match_count(0, 0) → 'No matches'."""
        toolbar = ChatInputToolbar()
        toolbar.update_match_count(0, 0)
        text = toolbar._match_label.get_text()
        assert text == "No matches"

    def test_set_find_count_with_matches(self):
        """update_match_count(2, 7) → '3 of 7' (current is 0-indexed, display is 1-indexed)."""
        toolbar = ChatInputToolbar()
        toolbar.update_match_count(2, 7)
        text = toolbar._match_label.get_text()
        assert text == "3 of 7"

    def test_set_find_count_first_match(self):
        """update_match_count(0, 5) → '1 of 5'."""
        toolbar = ChatInputToolbar()
        toolbar.update_match_count(0, 5)
        text = toolbar._match_label.get_text()
        assert text == "1 of 5"

    def test_set_spell_active_true(self):
        """set_spell_active(True) sets button active and adds CSS class."""
        toolbar = ChatInputToolbar()
        toolbar.set_spell_active(True)
        assert toolbar._spell_btn.get_active() is True
        assert "spell-active" in toolbar._spell_btn.get_css_classes()

    def test_set_spell_active_false(self):
        """set_spell_active(False) deactivates button and removes CSS class."""
        toolbar = ChatInputToolbar()
        toolbar.set_spell_active(True)  # first activate
        toolbar.set_spell_active(False)
        assert toolbar._spell_btn.get_active() is False
        assert "spell-active" not in toolbar._spell_btn.get_css_classes()

    def test_show_find_bar(self):
        """show_find_bar() makes find bar visible."""
        toolbar = ChatInputToolbar()
        toolbar.show_find_bar()
        assert toolbar._find_bar.get_visible() is True

    def test_show_find_bar_with_replace(self):
        """show_find_bar(show_replace=True) shows find bar AND replace row."""
        toolbar = ChatInputToolbar()
        toolbar.show_find_bar(show_replace=True)
        assert toolbar._find_bar.get_visible() is True
        assert toolbar._replace_row.get_visible() is True

    def test_show_find_bar_without_replace(self):
        """show_find_bar(show_replace=False) hides replace row."""
        toolbar = ChatInputToolbar()
        toolbar.show_find_bar(show_replace=False)
        assert toolbar._replace_row.get_visible() is False

    def test_hide_find_bar(self):
        """hide_find_bar() hides find bar and clears entries."""
        toolbar = ChatInputToolbar()
        toolbar.show_find_bar()
        toolbar._find_entry.set_text("test")
        toolbar._replace_entry.set_text("replacement")
        toolbar.hide_find_bar()
        assert toolbar._find_bar.get_visible() is False
        assert toolbar._find_entry.get_text() == ""
        assert toolbar._replace_entry.get_text() == ""

    def test_update_word_count(self):
        """update_word_count() updates the count label markup."""
        toolbar = ChatInputToolbar()
        toolbar.update_word_count(10, 50, 13)
        text = toolbar._count_label.get_label()
        assert "10" in text
        assert "50" in text
        assert "13" in text


# ── Class 4: Edge Cases ──────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and initial state."""

    def test_find_bar_initially_hidden(self):
        """Find bar is not visible at construction time."""
        toolbar = ChatInputToolbar()
        assert toolbar._find_bar.get_visible() is False

    def test_replace_row_initially_hidden(self):
        """Replace row is not visible at construction time."""
        toolbar = ChatInputToolbar()
        assert toolbar._replace_row.get_visible() is False

    def test_callbacks_default_none(self):
        """Callbacks default to None — no crash if invoked before being set."""
        toolbar = ChatInputToolbar()
        # Find toggle: _on_find_clicked calls show_find_bar then _on_find
        # _on_find is None by default — must not crash
        toolbar._on_find_clicked()
        assert toolbar._find_bar.get_visible() is True  # show_find_bar still worked

    def test_spell_toggled_without_callback(self):
        """Spell toggle without callback set must not crash."""
        toolbar = ChatInputToolbar()
        toolbar._on_spell_toggled(toolbar._spell_btn, toolbar._spell_btn)
        assert True  # no crash

    def test_set_find_count_single_match(self):
        """update_match_count(0, 1) → '1 of 1'."""
        toolbar = ChatInputToolbar()
        toolbar.update_match_count(0, 1)
        text = toolbar._match_label.get_text()
        assert text == "1 of 1"

    def test_hide_find_bar_when_already_hidden(self):
        """Hiding an already-hidden find bar must not crash."""
        toolbar = ChatInputToolbar()
        toolbar.hide_find_bar()  # already hidden
        assert toolbar._find_bar.get_visible() is False

    def test_no_gtk3_modelbutton(self):
        """View must not use Gtk.ModelButton (GTK3-only)."""
        import ui.views.chat_input_toolbar as mod
        import inspect

        source = inspect.getsource(mod)
        assert "ModelButton" not in source, (
            "Gtk.ModelButton is GTK3-only and must not be used in GTK4 views"
        )

    def test_no_set_keynav_wrapper(self):
        """View must not call set_keynav_wrapper (GTK3-only on Gtk.Entry)."""
        import ui.views.chat_input_toolbar as mod
        import inspect

        source = inspect.getsource(mod)
        # The fix replaces set_keynav_wrapper with a comment — verify neither
        # the call nor an uncommented usage remains.
        assert "set_keynav_wrapper(" not in source, (
            "set_keynav_wrapper is GTK3-only and must not be called in GTK4 views"
        )


# ── Helpers ──────────────────────────────────────────────────────


def inspect_source(module) -> str:
    """Read the source file for the given module."""
    import inspect

    return inspect.getsource(module)
