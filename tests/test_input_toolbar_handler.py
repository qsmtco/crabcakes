"""Tests for ui/handlers/input_toolbar_handler.py.

Test strategy: mock main_content (provides user_input → buffer) and GLib_module.
Mock utils.spellcheck at the boundary. Use real temp files for file I/O tests.
Never mock the handler's own methods — call them through real code paths.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ui.handlers.input_toolbar_handler import InputToolbarHandler


# ---------------------------------------------------------------------------
# Helpers — mock construction
# ---------------------------------------------------------------------------


def make_mock_buffer(text: str = "") -> MagicMock:
    """Create a mock Gtk.TextBuffer that returns *text* from get_text."""
    buf = MagicMock()
    start_iter = MagicMock()
    end_iter = MagicMock()
    buf.get_start_iter.return_value = start_iter
    buf.get_end_iter.return_value = end_iter
    buf.get_text.return_value = text
    # create_tag returns a new mock tag
    buf.create_tag.return_value = MagicMock()
    # tag_table.lookup returns None (no existing tags)
    tag_table = MagicMock()
    tag_table.lookup.return_value = None
    buf.get_tag_table.return_value = tag_table
    return buf


def make_mock_main_content(text: str = "") -> MagicMock:
    """Create a mock main_content with user_input → buffer returning *text*."""
    mc = MagicMock()
    buf = make_mock_buffer(text)
    mc.user_input.get_buffer.return_value = buf
    return mc


def make_mock_glib() -> MagicMock:
    """Create a mock GLib that executes callbacks immediately (no scheduling)."""
    glib = MagicMock()
    glib.idle_add.side_effect = lambda fn, *args: fn(*args)
    glib.timeout_add.side_effect = lambda ms, fn: 0  # return fake source ID
    glib.source_remove = MagicMock()
    return glib


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Handler with mocked main_content (empty buffer) and GLib."""
    mc = make_mock_main_content("")
    glib = make_mock_glib()
    return InputToolbarHandler(main_content=mc, GLib_module=glib)


@pytest.fixture
def handler_with_text():
    """Handler with 'hello world foo bar' in the buffer."""
    mc = make_mock_main_content("hello world foo bar")
    glib = make_mock_glib()
    return InputToolbarHandler(main_content=mc, GLib_module=glib)


# ---------------------------------------------------------------------------
# Spell check tests
# ---------------------------------------------------------------------------


class TestToggleSpellCheck:
    def test_toggle_spell_check_on(self, handler):
        """First toggle returns True (spell check enabled)."""
        result = handler.toggle_spell_check()
        assert result is True
        assert handler._spell_enabled is True

    def test_toggle_spell_check_off(self, handler):
        """Second toggle returns False (spell check disabled)."""
        handler.toggle_spell_check()  # on
        result = handler.toggle_spell_check()  # off
        assert result is False
        assert handler._spell_enabled is False


class TestBufferChanged:
    def test_on_buffer_changed_when_disabled(self, handler):
        """Does nothing when spell check is off — no timeout scheduled."""
        handler.on_buffer_changed()
        # GLib.timeout_add should NOT have been called
        handler._GLib.timeout_add.assert_not_called()

    def test_on_buffer_changed_when_enabled(self, handler):
        """Schedules spell check with debounce when enabled."""
        handler.toggle_spell_check()  # enable
        handler._GLib.timeout_add.reset_mock()
        handler.on_buffer_changed()
        handler._GLib.timeout_add.assert_called_once()
        # First arg should be 300 (ms)
        assert handler._GLib.timeout_add.call_args[0][0] == 300


class TestGetSuggestionsAtIter:
    def test_get_suggestions_at_iter(self, handler):
        """Returns suggestions for the word at the given TextIter."""
        # Build a mock TextIter that is inside the word "wrld"
        text_iter = MagicMock()
        word_start = MagicMock()
        word_end = MagicMock()
        text_iter.copy.side_effect = [word_start, word_end]
        text_iter.inside_word.return_value = True

        # word_start.backward_word_start() → no-op
        # word_end.forward_word_end() → no-op
        # buf.get_text(word_start, word_end, True) → "wrld"
        mock_buf = MagicMock()
        mock_buf.get_text.return_value = "wrld"
        text_iter.get_buffer.return_value = mock_buf

        with patch(
            "utils.spellcheck.get_suggestions",
            return_value=["world", "weird"],
        ) as mock_sug:
            result = handler.get_suggestions_at_iter(text_iter)

        assert result == ["world", "weird"]
        mock_sug.assert_called_once_with("wrld")

    def test_get_suggestions_at_iter_not_in_word(self, handler):
        """Returns [] when iter is not inside a word."""
        text_iter = MagicMock()
        text_iter.copy.side_effect = [MagicMock(), MagicMock()]
        text_iter.inside_word.return_value = False

        result = handler.get_suggestions_at_iter(text_iter)
        assert result == []


# ---------------------------------------------------------------------------
# Find / replace tests
# ---------------------------------------------------------------------------


class TestFind:
    def test_find_no_match(self, handler_with_text):
        """Returns (-1, 0) when search text is not in buffer."""
        result = handler_with_text.find("xyz")
        assert result == (-1, 0)

    def test_find_one_match(self, handler_with_text):
        """Returns (0, 1) for a single match."""
        result = handler_with_text.find("hello")
        assert result == (0, 1)

    def test_find_multiple_matches(self, handler_with_text):
        """Returns (0, N) for multiple matches, first highlighted."""
        # "hello world foo bar" — 'o' appears in "hello" and "world" and "foo"
        result = handler_with_text.find("o")
        assert result[0] == 0
        assert result[1] >= 2  # at least 2 matches for 'o'

    def test_find_empty_search(self, handler_with_text):
        """Empty search text returns (-1, 0)."""
        result = handler_with_text.find("")
        assert result == (-1, 0)


class TestFindNavigation:
    def test_find_next_wraps(self, handler_with_text):
        """find_next wraps from last match back to first."""
        handler_with_text.find("o")  # find 'o' — multiple matches
        total = handler_with_text._find_matches.__len__()
        assert total >= 2

        # Advance to last match
        for _ in range(total - 1):
            handler_with_text.find_next()

        # One more should wrap to index 0
        idx, _ = handler_with_text.find_next()
        assert idx == 0

    def test_find_prev_wraps(self, handler_with_text):
        """find_prev wraps from first match back to last."""
        handler_with_text.find("o")  # find 'o' — multiple matches
        total = len(handler_with_text._find_matches)
        assert total >= 2

        # At index 0, prev should wrap to last
        idx, _ = handler_with_text.find_prev()
        assert idx == total - 1


class TestReplace:
    def test_replace_current(self, handler_with_text):
        """Replaces the current match and re-finds."""
        handler_with_text.find("hello")
        assert handler_with_text._find_current == 0

        # Replace "hello" with "greetings"
        idx, total = handler_with_text.replace_current("greetings")

        # replace_current calls buf.delete + buf.insert, then re-runs find()
        # The mock buffer still returns old text, so find() re-finds "hello"
        # This is a mock limitation — verify the method called delete+insert
        buf = handler_with_text._mc.user_input.get_buffer()
        buf.delete.assert_called_once()
        buf.insert.assert_called_once()

    def test_replace_all(self, handler_with_text):
        """Replace all matches, returns count."""
        handler_with_text.find("o")
        total = len(handler_with_text._find_matches)
        assert total >= 2

        count = handler_with_text.replace_all("X")
        assert count == total

        # Buffer should have been updated
        buf = handler_with_text._mc.user_input.get_buffer()
        buf.set_text.assert_called_once()

        # State should be cleared
        assert handler_with_text._find_matches == []
        assert handler_with_text._find_current == -1

    def test_replace_all_no_matches(self, handler_with_text):
        """Replace all with no matches returns 0."""
        count = handler_with_text.replace_all("X")
        assert count == 0


class TestClearFind:
    def test_clear_find(self, handler_with_text):
        """Clears all find state."""
        handler_with_text.find("hello")
        assert handler_with_text._find_current == 0

        handler_with_text.clear_find()
        assert handler_with_text._find_matches == []
        assert handler_with_text._find_current == -1
        assert handler_with_text._find_text == ""


# ---------------------------------------------------------------------------
# File I/O tests — use real temp files
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_save_to_file(self, handler, tmp_path):
        """Saves buffer text to a real file."""
        # Set buffer text
        buf = handler._mc.user_input.get_buffer()
        buf.get_text.return_value = "hello world"

        out_file = str(tmp_path / "test_output.txt")
        result = handler.save_to_file(out_file)

        assert result is True
        with open(out_file, "r") as f:
            assert f.read() == "hello world"

    def test_save_to_file_permission_error(self, handler):
        """Returns False on PermissionError."""
        buf = handler._mc.user_input.get_buffer()
        buf.get_text.return_value = "hello"

        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = handler.save_to_file("/fake/path.txt")
        assert result is False

    def test_load_file(self, handler, tmp_path):
        """Loads file contents into buffer via append_stt_text."""
        in_file = tmp_path / "input.txt"
        in_file.write_text("file contents here", encoding="utf-8")

        result = handler.load_file(str(in_file))
        assert result is True
        handler._mc.append_stt_text.assert_called_once_with("file contents here")

    def test_load_file_not_found(self, handler):
        """Returns False when file doesn't exist."""
        result = handler.load_file("/nonexistent/file.txt")
        assert result is False

    def test_load_file_binary(self, handler, tmp_path):
        """Returns False when file can't be decoded as UTF-8."""
        bin_file = tmp_path / "binary.bin"
        bin_file.write_bytes(b"\x80\x81\x82\xff\xfe")

        result = handler.load_file(str(bin_file))
        assert result is False


# ---------------------------------------------------------------------------
# Word count tests
# ---------------------------------------------------------------------------


class TestWordCount:
    def test_get_word_count_empty(self, handler):
        """Empty buffer returns (0, 0, 0)."""
        result = handler.get_word_count()
        assert result == (0, 0, 0)

    def test_get_word_count_text(self, handler):
        """Returns correct (words, chars, approx_tokens)."""
        buf = handler._mc.user_input.get_buffer()
        buf.get_text.return_value = "hello world foo bar"

        words, chars, tokens = handler.get_word_count()
        assert words == 4
        assert chars == len("hello world foo bar")
        assert tokens == int(4 * 1.3)  # rough estimate
