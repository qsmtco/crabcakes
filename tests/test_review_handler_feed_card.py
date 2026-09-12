# tests/test_review_handler_feed_card.py
# Tests for ReviewHandler feed-card emission (Tier 1.2 wiring).
# Verifies that accept_changes/reject_changes emit git_commit feed cards
# on success and emit nothing on failure.

import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from models.review_state import ReviewState


# ── Mock GLib (runs idle_add callbacks immediately) ──────────────────────────

class MockGLib:
    def idle_add(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return 0


class DeferredGLib:
    """GLib double that RECORDS idle_add callbacks without running them.

    Mirrors production timing: GLib.idle_add schedules the callback for the
    main loop, which runs it AFTER the scheduling frame (including any
    except block) has exited. Running recorded callbacks in the test body
    reproduces that timing — synchronously-run mocks mask deferred-callback
    bugs because the closure still sees in-scope variables.
    """

    def __init__(self):
        self.pending = []

    def idle_add(self, fn, *args, **kwargs):
        self.pending.append((fn, args, kwargs))
        return 0


def _wait_until(cond, timeout=5.0, poll=0.01):
    """Poll cond() until truthy or timeout. Returns True on success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(poll)
    return cond()


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

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_diff_read_failure_survives_deferred_callback(self, mock_git_ops):
        """T2-RL2 BUG #3 (A3): the error-report callback is scheduled via
        idle_add but references the bare except-variable `e`, which Python
        deletes when the except block exits. With production timing (callback
        runs on the main loop AFTER _do() returns), the error-report path
        itself raised NameError and the user never saw the failure.

        Regression test uses a deferring GLib double and runs the recorded
        callback after accept_changes() returns — exactly when production
        runs it. Must surface the error text, not raise NameError.
        """
        glib = DeferredGLib()
        handler = _make_handler()
        handler._GLib = glib
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
        # _do() runs on a daemon thread — wait for it to schedule the callback
        assert _wait_until(lambda: len(glib.pending) >= 2), (
            f"expected error-report + reset callbacks, got {len(glib.pending)} pending"
        )
        # Except block has exited by now — bare `e` is deleted. Running the
        # recorded callback must NOT raise NameError.
        for fn, args, kwargs in glib.pending:
            fn(*args, **kwargs)  # was: NameError: name 'e' is not defined

        text_calls = [str(c) for c in handler._on_display_text.call_args_list]
        assert any("Failed to read diff" in c and "corrupt index" in c
                   for c in text_calls), (
            f"Expected error text with exception details, got: {text_calls}"
        )


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

        # reject_changes runs git work on a daemon thread and emits via
        # idle_add from that thread — assert with a bounded wait, not
        # synchronously (audit find: 5/5 flaky at file scope, baseline-proven).
        assert _wait_until(lambda: len(captured) == 1), (
            "feed card was never emitted"
        )
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


class TestReviewBarResolutionPersist:
    """REVIEW-PERSIST-1 Edit B: accept_changes/reject_changes must persist the
    resolution back to the ORIGINAL tool-result cards (metadata needs_review),
    mirroring approve_exec's durable-record write. Red-first per instructions:
    on current code the review bar resolves the git session but never touches
    the cards, so the decisions vanish on reload.

    Hermeticity: real FeedHandler with the persist writer suppressed
    (_no_writer pattern from tests/test_feed_handler.py) — enqueue payloads
    are asserted directly out of _persist_queue, nothing touches disk.
    """

    def _make_fh_with_needs_review_card(self):
        """FeedHandler + one resolved-by-review tool-result card.

        Uses a MagicMock GLib so add_card's idle_add work (widget build,
        snapshot finalize) never runs — this file stays GTK-widget-free.
        The project path is registered AFTER add_card so add_card itself
        spawns no persist thread.
        """
        from models.feed_card import FeedCardData
        from ui.handlers.feed_handler import FeedHandler

        fh = FeedHandler(GLib=MagicMock(), on_send_to_agent=MagicMock())
        fh._ensure_persist_writer = lambda: None  # _no_writer pattern
        card = FeedCardData(
            card_type="agent_action", source="agent",
            title="Coder is writing src/main.py", body="done",
            author="Coder", timestamp=datetime.now(timezone.utc),
            project_name="testproject", file_path="src/main.py",
            metadata={"tool_name": "write_file", "status": "complete",
                      "needs_review": True},
        )
        card_id = fh.add_card(card)
        fh._project_paths["testproject"] = "/tmp/testproject"
        return fh, card_id, card

    def _enqueue_for(self, fh, project_path, card_id):
        """The enqueued update payload for (project_path, card_id), or None."""
        return fh._persist_queue.get((project_path, card_id))

    @patch("ui.handlers.review_handler.git_ops")
    def test_review_bar_resolution_persists_decision(self, mock_git_ops):
        """Review-bar accept → the ORIGINAL card's decision is enqueued.

        Debugger F1-audit BUG #1 suggested test. Asserts the enqueue payload
        itself (the durable record), not just the in-memory mutation.
        """
        handler = _make_handler()
        fh, card_id, card = self._make_fh_with_needs_review_card()
        handler.set_feed_handler(fh)
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] accepted", sha="abc123def456"
        )
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

        project_path = fh._project_paths["testproject"]
        assert _wait_until(
            lambda: self._enqueue_for(fh, project_path, card_id) is not None
        ), "review-bar accept never enqueued the decision on the original card"

        updates = self._enqueue_for(fh, project_path, card_id)
        assert updates.get("accepted") is True, (
            f"durable decision missing from enqueue payload: {updates!r}"
        )
        assert "needs_review" not in updates["metadata"], (
            f"resolved card still flagged needs_review in payload: {updates!r}"
        )
        assert updates["metadata"].get("status") == "approved", (
            f"resolution status not mirrored from approve_exec: {updates!r}"
        )
        # In-memory agreement (approve_exec parity). Read the STORE's card:
        # update_card replaces self._cards[card_id] with the resolved copy, and
        # the fix deliberately does not mutate the caller's original object
        # (audit BUG #1 — mutate-before-persist).
        stored = fh.get_card(card_id)
        assert stored.accepted is True
        assert stored.metadata.get("needs_review") is None

    @patch("ui.handlers.review_handler.git_ops")
    def test_review_bar_reject_clears_needs_review(self, mock_git_ops):
        """Review-bar reject → needs_review cleared AND persist enqueued."""
        handler = _make_handler()
        fh, card_id, card = self._make_fh_with_needs_review_card()
        handler.set_feed_handler(fh)
        _setup_active_session(handler)

        mock_git_ops.checkout_paths.return_value = MockGitResult(
            success=True, stdout="1 file changed", sha="abc123def456"
        )
        handler.reject_changes("testproject", "bad code")

        project_path = fh._project_paths["testproject"]
        assert _wait_until(
            lambda: self._enqueue_for(fh, project_path, card_id) is not None
        ), "review-bar reject never enqueued the decision on the original card"

        updates = self._enqueue_for(fh, project_path, card_id)
        assert updates.get("accepted") is False, (
            f"durable decision missing from enqueue payload: {updates!r}"
        )
        assert "needs_review" not in updates["metadata"]
        assert updates["metadata"].get("status") == "denied"
        stored = fh.get_card(card_id)
        assert stored.metadata.get("needs_review") is None, (
            "needs_review must be cleared from metadata after resolution"
        )
        assert stored.accepted is False

    @patch("ui.handlers.review_handler.git_ops")
    def test_accept_omits_accepted_when_undecided(self, mock_git_ops):
        """Review-bar accept must not stamp decisions on unrelated cards.

        The resolution sweep targets needs_review cards ONLY: a pending card
        with no decision keeps accepted=None, keeps its metadata, and is never
        enqueued (F1 parity: never write None — an undecided card is omitted
        from the sweep entirely, branch-independent of which persist path
        fires).
        """
        from models.feed_card import FeedCardData

        handler = _make_handler()
        fh, card_id, _card = self._make_fh_with_needs_review_card()
        undecided = FeedCardData(
            card_type="agent_action", source="agent",
            title="Coder is reading docs/x.md", body="ok",
            author="Coder", timestamp=datetime.now(timezone.utc),
            project_name="testproject", file_path="docs/x.md",
            metadata={"tool_name": "read_file", "status": "complete"},
        )
        undecided_id = fh.add_card(undecided)
        handler.set_feed_handler(fh)
        _setup_active_session(handler)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] accepted", sha="abc123def456"
        )
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

        project_path = fh._project_paths["testproject"]
        assert _wait_until(
            lambda: self._enqueue_for(fh, project_path, card_id) is not None
        ), "resolution card was never enqueued (fixture precondition)"

        assert undecided.accepted is None, (
            "review-bar accept must not decide undecided cards"
        )
        assert self._enqueue_for(fh, project_path, undecided_id) is None, (
            "undecided card must not be enqueued by the resolution sweep"
        )

    @patch("ui.handlers.review_handler.git_ops")
    def test_review_bar_resolution_silent_no_op_leaves_needs_review(self, mock_git_ops):
        """Silent-no-op safety: if update_card cannot persist, the in-memory
        card must NOT look resolved.

        update_card returns early (warning only) when the card is no longer in
        _cards. Before the audit fix, _persist_review_resolution cleared
        metadata["needs_review"] in place first, so a no-op persist left the
        card looking resolved in memory while disk still had needs_review=True
        — the UI would claim success and the flag would reappear on reload.
        (Audit BUG #1, pattern: mutate-before-persist.)
        """
        handler = _make_handler()
        fh, card_id, card = self._make_fh_with_needs_review_card()
        handler.set_feed_handler(fh)
        _setup_active_session(handler)

        # Simulate the card vanishing between the sweep's read and the persist
        # (compaction prune / user dismissal): update_card then silently no-ops.
        fh._cards.pop(card_id, None)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] accepted", sha="abc123def456"
        )
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

        # The original object must be untouched — no in-memory-only resolution.
        assert card.metadata.get("needs_review") is True, (
            "no-op persist must not clear needs_review in memory "
            "(that would make the UI claim a resolution disk never recorded)"
        )
        assert card.accepted is None, (
            "no-op persist must not stamp a decision in memory only"
        )


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
