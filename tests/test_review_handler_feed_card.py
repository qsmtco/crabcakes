# tests/test_review_handler_feed_card.py
# Tests for ReviewHandler feed-card emission (Tier 1.2 wiring).
# Verifies that accept_changes/reject_changes emit git_commit feed cards
# on success and emit nothing on failure.

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from models.review_state import ReviewState


# ── Mock GLib (runs idle_add callbacks immediately) ──────────────────────────

class MockGLib:
    def idle_add(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return 0


# ── Mock git result ──────────────────────────────────────────────────────────

class MockGitResult:
    def __init__(self, success=True, stdout="", sha="abc123def456", error=""):
        self.success = success
        self.stdout = stdout
        self.sha = sha
        self.error = error


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_handler(on_feed_card=None):
    """Create a ReviewHandler with all dependencies mocked."""
    from ui.handlers.review_handler import ReviewHandler
    if on_feed_card is None:
        on_feed_card = MagicMock()
    handler = ReviewHandler(
        GLib=MockGLib(),
        main_content=MagicMock(),
        project_handler=MagicMock(),
        on_review_started=MagicMock(),
        on_review_ended=MagicMock(),
        on_display_card=MagicMock(),
        on_display_text=MagicMock(),
        on_feed_card=on_feed_card,
    )
    return handler


def _setup_active_session(handler, project_name="testproject"):
    """Insert an active review state so accept/reject have something to work with."""
    handler._states[project_name] = ReviewState(
        project_path="/tmp/testproject",
        review_mode="review",
        checkpoint_sha="abc123def456",
        is_dirty=True,
    )
    # Mock get_review_bar on main_content
    handler._mc.get_review_bar.return_value = MagicMock()
    return handler


# ── Tests ────────────────────────────────────────────────────────────────────

class TestAcceptChangesFeedCard:
    """accept_changes should emit a git_commit feed card on success."""

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_changes_emits_git_commit_card(self, mock_git_ops):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] accepted", sha="abc123def456"
        )

        # Mock git.Repo so repo.index.diff("HEAD") returns staged files.
        # The handler lazily does `import git as gitpython`, so we use
        # sys.modules patching to intercept the import.
        import sys
        mock_git_module = MagicMock()
        mock_diff = MagicMock()
        mock_diff.a_path = "src/main.py"
        mock_diff.b_path = None
        mock_repo = MagicMock()
        mock_repo.index.diff.return_value = [mock_diff]
        mock_git_module.Repo.return_value = mock_repo
        with patch.dict(sys.modules, {"git": mock_git_module}):
            handler.accept_changes("testproject", "approved")

        assert len(captured) == 1
        card = captured[0]
        assert card.card_type == "git_commit"
        assert card.source == "git"
        assert "Accepted" in card.title
        assert "Modified src/main.py" in card.title
        assert card.project_name == "testproject"
        assert card.commit_sha == "abc123def456"
        assert card.author == "PM"

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_no_card_when_stage_fails(self, mock_git_ops):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=False, error="stage failed")

        handler.accept_changes("testproject", "approved")

        assert len(captured) == 0

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_no_card_when_commit_fails(self, mock_git_ops):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(success=False, error="commit failed")

        handler.accept_changes("testproject", "approved")

        assert len(captured) == 0

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_no_card_when_diff_read_fails(self, mock_git_ops):
        """When repo.index.diff() raises (e.g., corrupt git repo, missing git
        binary), the accept flow should report the real error to the user
        and NOT silently treat it as 'nothing to commit'. Regression test for
        adversarialDebugger BUG #1 in T2-RL2 (2026-06-16).
        """
        handler = _make_handler()
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(success=True)  # shouldn't be called

        # Mock git.Repo to raise when index.diff() is called
        import sys
        mock_git_module = MagicMock()
        mock_repo = MagicMock()
        mock_repo.index.diff.side_effect = Exception("corrupt index")
        mock_git_module.Repo.return_value = mock_repo
        with patch.dict(sys.modules, {"git": mock_git_module}):
            handler.accept_changes("testproject", "approved")

        # The diff read error should be reported to the user
        text_calls = [str(c) for c in handler._on_display_text.call_args_list]
        any_error = any("Failed to read diff" in c or "corrupt index" in c for c in text_calls)
        assert any_error, f"Expected diff-read error in display_text, got: {text_calls}"
        # commit() should NOT have been called
        mock_git_ops.commit.assert_not_called()


class TestRejectChangesFeedCard:
    """reject_changes should emit a git_commit feed card on success."""

    @patch("ui.handlers.review_handler.git_ops")
    def test_reject_changes_emits_git_commit_card(self, mock_git_ops):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        _setup_active_session(handler)

        mock_git_ops.checkout_paths.return_value = MockGitResult(
            success=True, stdout="2 files changed", sha="abc123def456"
        )

        handler.reject_changes("testproject", "bad code")

        assert len(captured) == 1
        card = captured[0]
        assert card.card_type == "git_commit"
        assert card.source == "git"
        assert "Rejected" in card.title
        assert "bad code" in card.title
        assert card.project_name == "testproject"
        assert card.commit_sha == "abc123def456"
        assert card.author == "PM"

    @patch("ui.handlers.review_handler.git_ops")
    def test_reject_no_card_when_checkout_fails(self, mock_git_ops):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        _setup_active_session(handler)

        mock_git_ops.checkout_paths.return_value = MockGitResult(success=False, error="checkout failed")

        handler.reject_changes("testproject", "bad code")

        assert len(captured) == 0


class TestNoSession:
    """No card when no active review session exists."""

    def test_accept_no_card_when_no_active_session(self):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))
        # No state set up — empty _states dict

        handler.accept_changes("nonexistent", "approved")

        assert len(captured) == 0

    def test_reject_no_card_when_no_active_session(self):
        captured = []
        handler = _make_handler(on_feed_card=lambda card: captured.append(card))

        handler.reject_changes("nonexistent", "bad code")

        assert len(captured) == 0


class TestNoCallbackWired:
    """No crash when on_feed_card is None (backward compat)."""

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_no_crash_without_callback(self, mock_git_ops):
        handler = _make_handler(on_feed_card=None)
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(success=True, sha="abc123")

        # Should not raise
        handler.accept_changes("testproject", "approved")

    @patch("ui.handlers.review_handler.git_ops")
    def test_reject_no_crash_without_callback(self, mock_git_ops):
        handler = _make_handler(on_feed_card=None)
        _setup_active_session(handler)

        mock_git_ops.checkout_paths.return_value = MockGitResult(success=True)

        # Should not raise
        handler.reject_changes("testproject", "bad code")
