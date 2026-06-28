"""Tests for utils/spellcheck.py — enchant-2 subprocess wrapper.

Tests are split into three groups:
- Happy path: require real enchant-2 binary (skipped if not installed)
- Sad path: mock subprocess to simulate errors
- Edge cases: mock or real depending on what's being tested

Mocking rule: patch subprocess.run at utils.spellcheck.subprocess.run (the
external boundary). Never mock check_words or get_suggestions themselves.
"""

from __future__ import annotations

import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from utils.spellcheck import check_words, get_suggestions

ENCHANT_AVAILABLE = shutil.which("enchant-2") is not None


# ---------------------------------------------------------------------------
# Happy path tests (require real enchant-2 — skip if not installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_finds_misspelled():
    """Known misspelled word 'wrld' should be detected."""
    result = check_words("hello wrld")
    assert "wrld" in result


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_clean_text():
    """All-correct text should return empty list."""
    result = check_words("hello world this is correct")
    assert result == []


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_deduplicates():
    """Same misspelled word appearing twice should appear once in results."""
    result = check_words("wrld wrld wrld")
    assert result.count("wrld") == 1
    assert "wrld" in result


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_preserves_order():
    """Multiple misspellings returned in order of first occurrence."""
    result = check_words("hello wrld tset")
    # Both 'wrld' and 'tset' should be present
    assert "wrld" in result
    assert "tset" in result
    # 'wrld' appeared before 'tset' → lower index
    assert result.index("wrld") < result.index("tset")


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_get_suggestions_returns_list():
    """Suggestions for 'wrld' should include common corrections."""
    suggestions = get_suggestions("wrld")
    assert isinstance(suggestions, list)
    assert len(suggestions) > 0
    # 'world' is a very common suggestion for 'wrld'
    lower = [s.lower() for s in suggestions]
    assert "world" in lower


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_get_suggestions_max_8():
    """Verify truncation to at most 8 suggestions."""
    suggestions = get_suggestions("wrld")
    assert len(suggestions) <= 8


# ---------------------------------------------------------------------------
# Sad path tests (always use mocks — simulate errors)
# ---------------------------------------------------------------------------


def _mock_result(stdout: str) -> MagicMock:
    """Build a fake subprocess.CompletedProcess with given stdout."""
    m = MagicMock()
    m.stdout = stdout
    m.returncode = 0
    return m


def test_check_words_empty_string():
    """Empty string input returns empty list (no subprocess call)."""
    assert check_words("") == []


def test_check_words_whitespace_only():
    """Whitespace-only input returns empty list (no subprocess call)."""
    assert check_words("   \n\t  ") == []


def test_get_suggestions_empty_string():
    """Empty string input returns empty list (no subprocess call)."""
    assert get_suggestions("") == []


def test_check_words_enchant_not_found():
    """FileNotFoundError from subprocess → returns []."""
    with patch("utils.spellcheck.subprocess.run", side_effect=FileNotFoundError):
        result = check_words("some text")
    assert result == []


def test_check_words_timeout():
    """TimeoutExpired from subprocess → returns []."""
    with patch(
        "utils.spellcheck.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="enchant-2", timeout=5),
    ):
        result = check_words("some text")
    assert result == []


def test_get_suggestions_enchant_not_found():
    """FileNotFoundError from subprocess → returns []."""
    with patch("utils.spellcheck.subprocess.run", side_effect=FileNotFoundError):
        result = get_suggestions("wrld")
    assert result == []


def test_get_suggestions_timeout():
    """TimeoutExpired from subprocess → returns []."""
    with patch(
        "utils.spellcheck.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="enchant-2", timeout=5),
    ):
        result = get_suggestions("wrld")
    assert result == []


def test_check_words_unexpected_exception():
    """Any other exception from subprocess → returns []."""
    with patch(
        "utils.spellcheck.subprocess.run",
        side_effect=RuntimeError("something broke"),
    ):
        result = check_words("some text")
    assert result == []


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_single_word_correct():
    """Single correctly spelled word returns empty list."""
    assert check_words("hello") == []


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_get_suggestions_correct_word():
    """Correctly spelled word returns [] (enchant-2 returns '*' line, not '&')."""
    suggestions = get_suggestions("hello")
    assert suggestions == []


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_unicode_text():
    """Text with unicode characters doesn't crash."""
    result = check_words("Héllo wörld café résumé")
    assert isinstance(result, list)


def test_check_words_unicode_stdout():
    """enchant-2 returns unicode words in stdout — handled correctly."""
    mock = _mock_result("café\nrésumé\n")
    with patch("utils.spellcheck.subprocess.run", return_value=mock):
        result = check_words("some text")
    assert result == ["café", "résumé"]


def test_get_suggestions_unexpected_exception():
    """Any other exception from subprocess → returns []."""
    with patch(
        "utils.spellcheck.subprocess.run",
        side_effect=RuntimeError("something broke"),
    ):
        result = get_suggestions("wrld")
    assert result == []


def test_check_words_non_string_input():
    """Non-string input (int) returns [] instead of crashing."""
    assert check_words(123) == []


def test_check_words_none_input():
    """None input returns [] instead of crashing."""
    assert check_words(None) == []


def test_get_suggestions_non_string_input():
    """Non-string input (int) returns [] instead of crashing."""
    assert get_suggestions(123) == []


def test_check_words_non_zero_exit():
    """enchant-2 returns non-zero exit code — still parses stdout."""
    mock = _mock_result("wrld\n")
    mock.returncode = 1
    with patch("utils.spellcheck.subprocess.run", return_value=mock):
        result = check_words("some text")
    assert result == ["wrld"]


def test_get_suggestions_empty_response():
    """enchant-2 returns empty stdout → returns []."""
    mock = _mock_result("")
    with patch("utils.spellcheck.subprocess.run", return_value=mock):
        result = get_suggestions("wrld")
    assert result == []


# ---------------------------------------------------------------------------
# Custom dictionary tests (.crabcakes/dictionary.txt via -p)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_custom_dict_excludes_word(tmp_path):
    """A word listed in the custom dictionary is treated as correct."""
    d = tmp_path / "dictionary.txt"
    d.write_text("# project jargon\ncrabcakes\nqontinuum\n")
    result = check_words("hello crabcakes world", dictionary_path=str(d))
    assert "crabcakes" not in result


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_custom_dict_still_flags_other_words(tmp_path):
    """Custom dictionary only adds words — other misspellings still flagged."""
    d = tmp_path / "dictionary.txt"
    d.write_text("crabcakes\n")
    result = check_words("crabcakes wrld", dictionary_path=str(d))
    assert "wrld" in result
    assert "crabcakes" not in result


@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_get_suggestions_custom_dict_marks_word_correct(tmp_path):
    """A word in the custom dictionary returns [] (correct)."""
    d = tmp_path / "dictionary.txt"
    d.write_text("crabcakes\n")
    # enchant -a returns '*' for a correct word, which get_suggestions ignores
    suggestions = get_suggestions("crabcakes", dictionary_path=str(d))
    assert suggestions == []


def test_check_words_missing_dict_file_falls_back(tmp_path):
    """Nonexistent dictionary path → no -p arg, no error."""
    missing = tmp_path / "does_not_exist.txt"
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("wrld\n")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = check_words("some text", dictionary_path=str(missing))
    assert result == ["wrld"]
    # -p flag MUST NOT be present when the file doesn't exist
    assert "-p" not in captured["cmd"]


def test_get_suggestions_missing_dict_file_falls_back(tmp_path):
    """Nonexistent dictionary path → no -p arg, no error."""
    missing = tmp_path / "does_not_exist.txt"
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = get_suggestions("wrld", dictionary_path=str(missing))
    assert result == []
    assert "-p" not in captured["cmd"]


def test_check_words_none_dict_path_preserves_legacy_behavior():
    """dictionary_path=None → current behavior (no -p arg)."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = check_words("some text")
    assert result == []
    assert "-p" not in captured["cmd"]


def test_check_words_directory_as_dict_path_falls_back(tmp_path):
    """A directory path (not a file) → no -p arg, no error."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = check_words("some text", dictionary_path=str(tmp_path))
    assert result == []
    assert "-p" not in captured["cmd"]


def test_check_words_valid_dict_passes_path(tmp_path):
    """Valid dictionary file → -p <path> appears in cmd."""
    d = tmp_path / "dictionary.txt"
    d.write_text("crabcakes\n")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = check_words("some text", dictionary_path=str(d))
    assert result == []
    assert "-p" in captured["cmd"]
    # The path should appear immediately after -p
    p_idx = captured["cmd"].index("-p")
    assert captured["cmd"][p_idx + 1] == str(d)


def test_get_suggestions_valid_dict_passes_path(tmp_path):
    """Valid dictionary file → -p <path> appears in cmd for suggestions too."""
    d = tmp_path / "dictionary.txt"
    d.write_text("crabcakes\n")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_result("")

    with patch("utils.spellcheck.subprocess.run", side_effect=fake_run):
        result = get_suggestions("wrld", dictionary_path=str(d))
    assert result == []
    assert "-p" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-p") + 1] == str(d)
