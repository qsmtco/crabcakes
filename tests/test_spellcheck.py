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


def test_check_words_unicode_text():
    """Text with unicode characters doesn't crash."""
    mock = _mock_result("")
    with patch("utils.spellcheck.subprocess.run", return_value=mock):
        result = check_words("Héllo wörld café")
    assert isinstance(result, list)


def test_get_suggestions_empty_response():
    """enchant-2 returns empty stdout → returns []."""
    mock = _mock_result("")
    with patch("utils.spellcheck.subprocess.run", return_value=mock):
        result = get_suggestions("wrld")
    assert result == []
