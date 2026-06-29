# tests/test_feed_handler.py
# Unit tests for ui/handlers/feed_handler.py — FeedHandler card lifecycle + actions.
#
# Tests the FeedHandler API without GTK (mock GLib.idle_add).

import pytest
from datetime import datetime, timezone
import sys
from unittest.mock import MagicMock, patch

from models.feed_card import FeedCardData


# ── Mock GLib that records calls instead of dispatching ──────────────────────

class MockGLib:
    """Mock GLib that captures idle_add callbacks for synchronous testing."""
    def __init__(self):
        self._pending = []

    def idle_add(self, fn, *args, **kwargs):
        # Record and also run immediately (simulates immediate GTK dispatch)
        self._pending.append((fn, args, kwargs))
        fn(*args, **kwargs)
        return 0


# ── Mock FeedTab ──────────────────────────────────────────────────────────────

class MockVadjustment:
    """Fake Gtk.Adjustment for smart scroll tests."""
    def __init__(self, value=0, upper=1000, page_size=600):
        self._value = value
        self._upper = upper
        self._page_size = page_size

    def get_value(self):
        return self._value

    def set_value(self, v):
        self._value = v

    def get_upper(self):
        return self._upper

    def get_page_size(self):
        return self._page_size


class MockFeedTab:
    def __init__(self):
        self.cards = []  # list of (card_id, widget)
        self.empty_shown = False
        # Fake scroll state for smart scroll tests
        self._vadjustment = MockVadjustment(value=0, upper=1000, page_size=600)
        # Fake batch bar state for Phase 5 tests
        self._batch_bar_visible = False
        self._batch_bar_count = 0
        self._batch_accept_callback = None
        # Phase 5 — Auto-accept toggle state (for new test class)
        self._auto_accept_active = False
        self._auto_accept_callback = None
        self._batch_button_label = ""
        self._batch_button_visible = True
        self.append_calls = []  # log of (widget, card_id) per append_card() call (for batch tests)

    def append_card(self, widget, card_id=None):
        self.cards.append((widget, card_id))
        self.append_calls.append((widget, card_id))

    prepend_card = append_card  # backward compat

    def remove_card(self, card_id):
        self.cards = [(cid, w) for cid, w in self.cards if cid != card_id]

    def show_empty_state(self):
        self.empty_shown = True

    def replace_card(self, card_id, new_widget):
        for i, (cid, w) in enumerate(self.cards):
            if cid == card_id:
                self.cards[i] = (card_id, new_widget)
                break

    def schedule_scroll_to_bottom(self):
        # Mirror the real FeedTab: scroll after a simulated layout pass.
        # The real implementation uses vadj.set_value(vadj.get_upper())
        # via the 'changed' signal; in tests we just set the value directly.
        if self._vadjustment is not None:
            self._vadjustment.set_value(self._vadjustment.get_upper())

    def schedule_smart_scroll_to_bottom(self):
        """Mirror of FeedTab.schedule_smart_scroll_to_bottom() for test.
        Proximity check + delegate to schedule_scroll_to_bottom."""
        if self._vadjustment is None:
            return
        vadj = self._vadjustment
        current = vadj.get_value()
        upper = vadj.get_upper()
        page_size = vadj.get_page_size()
        distance_from_bottom = upper - page_size - current
        if distance_from_bottom < 80:
            self.schedule_scroll_to_bottom()

    # Phase 5 batch bar mocks
    def update_batch_bar(self, pending_count: int):
        self._batch_bar_count = pending_count
        self._batch_bar_visible = pending_count >= 2
        # Phase 5-2 — New mock attrs (mirror real FeedTab.update_batch_bar)
        self._batch_button_label = f"Accept All ({pending_count})" if pending_count >= 2 else "Accept All"
        self._batch_button_visible = pending_count >= 2

    def set_batch_accept_callback(self, callback):
        self._batch_accept_callback = callback

    # Phase 5 — Auto-accept toggle mocks
    def update_auto_accept_state(self, active: bool):
        self._auto_accept_active = active

    def set_auto_accept_callback(self, callback):
        self._auto_accept_callback = callback


# ── Mock GitResult ───────────────────────────────────────────────────────────

class MockGitResult:
    def __init__(self, success=True, stdout="", sha="abc123def456", error=""):
        self.success = success
        self.stdout = stdout
        self.sha = sha
        self.error = error


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_glib():
    return MockGLib()


@pytest.fixture
def mock_feed_tab():
    return MockFeedTab()


@pytest.fixture
def feed_handler(mock_glib, mock_feed_tab):
    from ui.handlers.feed_handler import FeedHandler
    on_send = MagicMock()
    h = FeedHandler(
        GLib=mock_glib,
        on_send_to_agent=on_send,
    )
    h.set_feed_tab(mock_feed_tab)
    return h


# ── Tests: add_card ─────────────────────────────────────────────────────────

class TestAddCard:
    def test_add_card_returns_card_id(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Fix auth",
            body="+from auth import middleware", author="Qat",
            timestamp=ts, project_name="manopea",
        )
        card_id = feed_handler.add_card(card)
        assert card_id is not None
        assert isinstance(card_id, str)
        assert len(card_id) > 0

    def test_add_card_stores_card_data(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Fix auth",
            body="+from auth import middleware", author="Qat",
            timestamp=ts, project_name="manopea",
        )
        card_id = feed_handler.add_card(card)
        stored = feed_handler.get_card(card_id)
        assert stored is not None
        assert stored.card_id == card_id
        assert stored.title == "Fix auth"

    def test_add_card_indexes_under_project(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="git_commit", source="git", title="Init commit",
            body="", author="git", timestamp=ts, project_name="crabcakes",
        )
        card_id = feed_handler.add_card(card)
        cards = feed_handler.get_cards_for_project("crabcakes")
        assert len(cards) == 1
        assert cards[0].card_id == card_id

    def test_add_card_multiple_projects_isolated(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card1 = FeedCardData(
            card_type="diff", source="agent", title="A", body="",
            author="x", timestamp=ts, project_name="proj1",
        )
        card2 = FeedCardData(
            card_type="diff", source="agent", title="B", body="",
            author="x", timestamp=ts, project_name="proj2",
        )
        id1 = feed_handler.add_card(card1)
        id2 = feed_handler.add_card(card2)
        assert feed_handler.get_cards_for_project("proj1") == [feed_handler.get_card(id1)]
        assert feed_handler.get_cards_for_project("proj2") == [feed_handler.get_card(id2)]

    def test_add_card_calls_on_card_added(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="task", source="agent", title="Task 1", body="",
            author="x", timestamp=ts, project_name="p",
        )
        on_added = MagicMock()
        feed_handler._on_card_added = on_added
        card_id = feed_handler.add_card(card)
        on_added.assert_called_once_with(card_id)


# ── Tests: remove_card ──────────────────────────────────────────────────────

class TestRemoveCard:
    def test_remove_card_deletes_from_store(self, feed_handler):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="X", body="",
            author="x", timestamp=ts, project_name="p",
        )
        card_id = feed_handler.add_card(card)
        assert feed_handler.get_card(card_id) is not None
        feed_handler.remove_card(card_id)
        assert feed_handler.get_card(card_id) is None

    def test_remove_nonexistent_id_noop(self, feed_handler):
        feed_handler.remove_card("nonexistent-id")


# ── Tests: clear_project ─────────────────────────────────────────────────────

class TestClearProject:
    def test_clear_project_removes_all_cards(self, feed_handler):
        ts = datetime.now(timezone.utc)
        for i in range(3):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}", body="",
                author="x", timestamp=ts, project_name="clear-me",
            )
            feed_handler.add_card(card)
        assert len(feed_handler.get_cards_for_project("clear-me")) == 3
        feed_handler.clear_project("clear-me")
        assert len(feed_handler.get_cards_for_project("clear-me")) == 0


# ── Tests: get_cards_for_project ─────────────────────────────────────────────

class TestGetCardsForProject:
    def test_empty_project_returns_empty_list(self, feed_handler):
        assert feed_handler.get_cards_for_project("nonexistent") == []

    def test_cards_newest_first(self, feed_handler):
        ts = datetime.now(timezone.utc)
        for i in range(5):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}", body="",
                author="x", timestamp=ts, project_name="order-test",
            )
            feed_handler.add_card(card)
        cards = feed_handler.get_cards_for_project("order-test")
        # Newest first (card 4 should be first since it was added last)
        assert cards[0].title == "Card 4"
        assert cards[4].title == "Card 0"


# ── Tests: on_project_closed ─────────────────────────────────────────────────

class TestOnProjectClosed:
    def test_on_project_closed_clears_and_shows_empty(self, feed_handler, mock_feed_tab):
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="X", body="",
            author="x", timestamp=ts, project_name="closing",
        )
        feed_handler.add_card(card)
        feed_handler.on_project_closed("closing")
        assert len(feed_handler.get_cards_for_project("closing")) == 0
        assert mock_feed_tab.empty_shown


# ── Tests: handle_accept ───────────────────────────────────────────────────

class TestHandleAccept:
    """handle_accept should commit the actual staged files, not the card title."""

    @patch("ui.handlers.feed_handler.git_ops")
    @patch("ui.handlers.feed_handler.feed_store")
    def test_handle_accept_uses_staged_files_for_commit_message(
        self, mock_feed_store, mock_git_ops, feed_handler
    ):
        """When accepting a feed card, the commit message should be derived
        from the actual staged files, not from card.title.

        Regression test for review-layer fix T2-RL3.
        """
        # Set up a feed card
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="file_modified", source="agent",
            title="Modified src/main.py", body="",
            author="x", timestamp=ts, project_name="testproject",
            file_path="src/main.py", metadata={},
        )
        card_id = feed_handler.add_card(card)

        # Mock git_ops: stage succeeds, commit succeeds
        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] Accept: src/main.py", sha="abc123def456"
        )

        # Mock gitpython import to return a staged list with a different file
        import sys
        mock_git_module = MagicMock()
        mock_diff = MagicMock()
        mock_diff.a_path = "src/other.py"  # different from card.title
        mock_diff.b_path = None
        mock_repo = MagicMock()
        mock_repo.index.diff.return_value = [mock_diff]
        mock_git_module.Repo.return_value = mock_repo

        project_path = "/tmp/testproject"
        feed_handler._project_paths["testproject"] = project_path

        with patch.dict(sys.modules, {"git": mock_git_module}):
            feed_handler.handle_accept(card_id)

        # Verify commit was called with the ACTUAL file, not card.title
        commit_call = mock_git_ops.commit.call_args
        assert commit_call is not None
        commit_msg = commit_call[0][1]  # second positional arg
        assert "src/other.py" in commit_msg
        assert "Modified" not in commit_msg  # the user-facing title is NOT in the message

    @patch("ui.handlers.feed_handler.git_ops")
    @patch("ui.handlers.feed_handler.feed_store")
    def test_handle_accept_empty_tree_silently_noops(
        self, mock_feed_store, mock_git_ops, feed_handler
    ):
        """When the working tree is clean (no staged files), handle_accept
        should be a silent no-op. The card is not marked accepted and no
        empty commit is created.
        """
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="file_modified", source="agent",
            title="Modified src/main.py", body="",
            author="x", timestamp=ts, project_name="testproject",
            file_path="src/main.py", metadata={},
        )
        card_id = feed_handler.add_card(card)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(success=True)

        # Mock gitpython to return empty staged list (clean working tree)
        import sys
        mock_git_module = MagicMock()
        mock_repo = MagicMock()
        mock_repo.index.diff.return_value = []  # empty
        mock_git_module.Repo.return_value = mock_repo
        project_path = "/tmp/testproject"
        feed_handler._project_paths["testproject"] = project_path

        with patch.dict(sys.modules, {"git": mock_git_module}):
            feed_handler.handle_accept(card_id)

        # commit() should NOT have been called (no staged changes)
        mock_git_ops.commit.assert_not_called()
        # The card should NOT be marked accepted
        assert card.accepted is not True

    @patch("ui.handlers.feed_handler.git_ops")
    @patch("ui.handlers.feed_handler.feed_store")
    def test_handle_accept_multi_file_message(
        self, mock_feed_store, mock_git_ops, feed_handler
    ):
        """When multiple files are staged, the commit message should list
        all of them (up to 3 inline, then '...' for more).
        """
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="file_modified", source="agent",
            title="Modified src/main.py", body="",
            author="x", timestamp=ts, project_name="testproject",
            file_path="src/main.py", metadata={},
        )
        card_id = feed_handler.add_card(card)

        mock_git_ops.stage_all.return_value = MockGitResult(success=True)
        mock_git_ops.commit.return_value = MockGitResult(
            success=True, stdout="[main abc123d] multi", sha="abc123"
        )

        # Mock gitpython to return multiple staged files
        import sys
        mock_git_module = MagicMock()
        mock_diffs = []
        for fname in ["src/main.py", "src/utils.py", "tests/test_main.py"]:
            mock_diff = MagicMock()
            mock_diff.a_path = fname
            mock_diff.b_path = None
            mock_diffs.append(mock_diff)
        mock_repo = MagicMock()
        mock_repo.index.diff.return_value = mock_diffs
        mock_git_module.Repo.return_value = mock_repo
        project_path = "/tmp/testproject"
        feed_handler._project_paths["testproject"] = project_path

        with patch.dict(sys.modules, {"git": mock_git_module}):
            feed_handler.handle_accept(card_id)

        # Verify commit was called with a message that lists multiple files
        commit_call = mock_git_ops.commit.call_args
        commit_msg = commit_call[0][1]
        assert "3 files" in commit_msg
        assert "src/main.py" in commit_msg
        assert "src/utils.py" in commit_msg
        assert "tests/test_main.py" in commit_msg


# ── Tests: handle_copy ───────────────────────────────────────────────────────

class TestHandleCopy:
    def test_handle_copy_calls_clipboard(self, feed_handler):
        with patch('gi.repository.Gdk.Display.get_default') as mock_display:
            mock_clipboard = MagicMock()
            mock_display.return_value.get_clipboard.return_value = mock_clipboard
            feed_handler.handle_copy("test text")
            mock_clipboard.set.assert_called_once_with("test text")

# ═══════════════════════════════════════════════════════════════════
#  TestPersistentBadges — Phase 2
#  Verifies that git_commit and approval cards show decision badges.
# ═══════════════════════════════════════════════════════════════════

class TestPersistentBadges:
    """Phase 2: git_commit and approval cards must show decision badges after accept/reject."""

    def test_git_commit_card_has_accepted_true(self, feed_handler):
        """After accepting a file-change card, the git_commit card created must have accepted=True."""
        # Create a file-change card that will be accepted
        ts = datetime.now(timezone.utc)
        original = FeedCardData(
            card_type="diff",
            source="agent",
            title="Fix auth bug",
            body="+from auth import middleware",
            author="Qat",
            timestamp=ts,
            project_name="testproject",
        )
        card_id = feed_handler.add_card(original)

        # Mock _add_git_card: create a result and call _add_git_card directly
        # We intercept by mocking add_card to capture the git_card
        captured_git_cards = []

        original_add_card = feed_handler.add_card
        def capturing_add_card(card_data):
            captured_git_cards.append(card_data)
            # Actually add it
            return original_add_card(card_data)
        feed_handler.add_card = capturing_add_card

        # Call _add_git_card directly with a successful result
        from unittest.mock import MagicMock
        result = MagicMock()
        result.success = True
        result.stdout = "[main abc123d] Fix auth bug"
        result.sha = "abc123def456"
        original.accepted = True  # Simulate the card was accepted

        feed_handler._add_git_card(original, result)

        # Verify the git_commit card has accepted=True
        assert len(captured_git_cards) == 1
        git_card = captured_git_cards[0]
        assert git_card.card_type == "git_commit"
        assert git_card.accepted is True

    def test_git_commit_card_has_accepted_false(self, feed_handler):
        """After rejecting a file-change card, the git_commit card created must have accepted=False."""
        ts = datetime.now(timezone.utc)
        original = FeedCardData(
            card_type="diff",
            source="agent",
            title="Fix auth bug",
            body="+from auth import middleware",
            author="Qat",
            timestamp=ts,
            project_name="testproject",
        )
        card_id = feed_handler.add_card(original)

        captured_git_cards = []
        original_add_card = feed_handler.add_card
        def capturing_add_card(card_data):
            captured_git_cards.append(card_data)
            return original_add_card(card_data)
        feed_handler.add_card = capturing_add_card

        from unittest.mock import MagicMock
        result = MagicMock()
        result.success = True
        result.stdout = "[main abc123d] Rejected"
        result.sha = "abc123def456"
        original.accepted = False  # Simulate rejected

        feed_handler._add_git_card(original, result)

        assert len(captured_git_cards) == 1
        git_card = captured_git_cards[0]
        assert git_card.card_type == "git_commit"
        assert git_card.accepted is False

    def test_approval_card_has_accepted_true_after_approve(self, feed_handler, mock_glib):
        """After approving a pending approval card, card.accepted must be True."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler

        # Create a mock agent runtime handler
        mock_mc = MagicMock()
        mock_chat_rh = MagicMock()
        agent_rt_handler = AgentRuntimeHandler(mock_mc, mock_chat_rh, GLib_module=mock_glib)
        agent_rt_handler._fh = feed_handler

        # Create an approval card in the feed handler
        ts = datetime.now(timezone.utc)
        approval_card = FeedCardData(
            card_type="agent_action",
            source="agent",
            title="PM requests approval to run command",
            body="$ ls -la",
            author="PM",
            timestamp=ts,
            project_name="testproject",
            metadata={
                "needs_approval": True,
                "status": "pending_approval",
            },
        )
        card_id = feed_handler.add_card(approval_card)

        # Register pending approval
        approval_id = card_id
        agent_rt_handler._pending_approvals[approval_id] = {
            "session_key": "test-session",
            "tool_name": "exec_command",
            "args": {"command": "ls -la"},
        }

        # Mock the runtime's get_conversation to return something truthy
        mock_runtime = MagicMock()
        mock_runtime.get_conversation.return_value = True
        agent_rt_handler._runtimes["test-agent"] = mock_runtime

        # Mock feed_store.update_feed_card to avoid file I/O
        with patch('ui.handlers.feed_handler.feed_store'):
            agent_rt_handler.approve_exec(approval_id, True)

        # Verify card.accepted is True
        card = feed_handler.get_card(approval_id)
        assert card is not None
        assert card.accepted is True

    def test_approval_card_has_accepted_false_after_deny(self, feed_handler, mock_glib):
        """After denying a pending approval card, card.accepted must be False."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler

        mock_mc = MagicMock()
        mock_chat_rh = MagicMock()
        agent_rt_handler = AgentRuntimeHandler(mock_mc, mock_chat_rh, GLib_module=mock_glib)
        agent_rt_handler._fh = feed_handler

        ts = datetime.now(timezone.utc)
        approval_card = FeedCardData(
            card_type="agent_action",
            source="agent",
            title="PM requests approval to run command",
            body="$ rm -rf /",
            author="PM",
            timestamp=ts,
            project_name="testproject",
            metadata={
                "needs_approval": True,
                "status": "pending_approval",
            },
        )
        card_id = feed_handler.add_card(approval_card)

        approval_id = card_id
        agent_rt_handler._pending_approvals[approval_id] = {
            "session_key": "test-session",
            "tool_name": "exec_command",
            "args": {"command": "rm -rf /"},
        }

        mock_runtime = MagicMock()
        mock_runtime.get_conversation.return_value = True
        agent_rt_handler._runtimes["test-agent"] = mock_runtime

        with patch('ui.handlers.feed_handler.feed_store'):
            agent_rt_handler.approve_exec(approval_id, False)

        card = feed_handler.get_card(approval_id)
        assert card is not None
        assert card.accepted is False


# ═══════════════════════════════════════════════════════════════════
#  TestSeqNumHandler — Phase 3
#  Verifies seq_num assignment in add_card, per-project isolation,
#  and reconstruction on project open.
# ═══════════════════════════════════════════════════════════════════

class TestSeqNumHandler:
    """Phase 3: seq_num is assigned per-project and persists."""

    def test_seq_num_assigned_on_add(self, feed_handler):
        """add_card() must assign an incrementing seq_num to each new card."""
        ts = datetime.now(timezone.utc)
        cards = []
        for i in range(3):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="foo",
            )
            feed_handler.add_card(card)
            cards.append(card)

        assert cards[0].seq_num == 1
        assert cards[1].seq_num == 2
        assert cards[2].seq_num == 3

    def test_seq_num_per_project(self, feed_handler):
        """seq_num is per-project, not global."""
        ts = datetime.now(timezone.utc)

        # Add 2 cards to project foo
        c1 = FeedCardData(
            card_type="diff", source="agent", title="A",
            body="", author="x", timestamp=ts, project_name="foo",
        )
        c2 = FeedCardData(
            card_type="diff", source="agent", title="B",
            body="", author="x", timestamp=ts, project_name="foo",
        )
        feed_handler.add_card(c1)
        feed_handler.add_card(c2)

        # Add 1 card to project bar
        c3 = FeedCardData(
            card_type="diff", source="agent", title="C",
            body="", author="x", timestamp=ts, project_name="bar",
        )
        feed_handler.add_card(c3)

        # foo should have 1, 2 and bar should have 1
        assert c1.seq_num == 1
        assert c2.seq_num == 2
        assert c3.seq_num == 1

    def test_seq_num_increments_on_project_switch(self, feed_handler):
        """Switching back to a project resumes its sequence, not restart from 1."""
        ts = datetime.now(timezone.utc)

        # Project foo gets 2 cards
        c1 = FeedCardData(
            card_type="diff", source="agent", title="Foo-1",
            body="", author="x", timestamp=ts, project_name="foo",
        )
        c2 = FeedCardData(
            card_type="diff", source="agent", title="Foo-2",
            body="", author="x", timestamp=ts, project_name="foo",
        )
        feed_handler.add_card(c1)
        feed_handler.add_card(c2)

        # Project bar gets 1 card
        c3 = FeedCardData(
            card_type="diff", source="agent", title="Bar-1",
            body="", author="x", timestamp=ts, project_name="bar",
        )
        feed_handler.add_card(c3)

        # Back to foo — should continue from 3
        c4 = FeedCardData(
            card_type="diff", source="agent", title="Foo-3",
            body="", author="x", timestamp=ts, project_name="foo",
        )
        feed_handler.add_card(c4)

        assert c1.seq_num == 1
        assert c2.seq_num == 2
        assert c3.seq_num == 1
        assert c4.seq_num == 3

    def test_seq_num_not_reset_on_clear_project(self, feed_handler):
        """After clear_project, the counter for that project is gone but new cards still work."""
        ts = datetime.now(timezone.utc)

        c1 = FeedCardData(
            card_type="diff", source="agent", title="Card 1",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(c1)
        assert c1.seq_num == 1

        feed_handler.clear_project("testproj")

        # New cards for the same project should start fresh (counter was removed)
        c2 = FeedCardData(
            card_type="diff", source="agent", title="Card 2",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(c2)
        assert c2.seq_num == 1  # fresh start after clear

    def test_seq_num_on_project_open_reconstruction(self, feed_handler, mock_glib):
        """On project open, _project_seq is rebuilt from max(loaded seq_nums)."""
        ts = datetime.now(timezone.utc)

        # Simulate loading pre-existing cards with seq_nums 1, 2, 3
        existing_cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Old {i}",
                body="", author="x",
                timestamp=ts.replace(second=i),  # oldest=0, newest=3
                project_name="restore-project",
                card_id=f"old-{i}",
                seq_num=i + 1,  # seq_nums 1, 2, 3
            )
            for i in range(3)
        ]

        with patch('ui.handlers.feed_handler.feed_store') as mock_fs:
            mock_fs.load_feed.return_value = existing_cards

            # Mock _project_paths so the handler knows where to look
            feed_handler._project_paths["restore-project"] = "/tmp/restore-project"

            feed_handler.on_project_opened("restore-project", "/tmp/restore-project")

        # After on_project_opened, _project_seq should be 3 (max of loaded)
        assert feed_handler._project_seq.get("restore-project") == 3

    def test_seq_num_migration_assigns_to_cards_without_it(self, feed_handler, mock_glib):
        """Cards loaded without seq_num get assigned seq_nums on project open."""
        ts = datetime.now(timezone.utc)

        # Cards from old feed.json — no seq_num field
        old_cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Old {i}",
                body="", author="x",
                timestamp=ts.replace(second=i * 10),
                project_name="migration-project",
                card_id=f"old-{i}",
                # seq_num intentionally None
            )
            for i in range(3)
        ]

        with patch('ui.handlers.feed_handler.feed_store') as mock_fs:
            mock_fs.load_feed.return_value = old_cards
            feed_handler._project_paths["migration-project"] = "/tmp/migration-project"

            feed_handler.on_project_opened("migration-project", "/tmp/migration-project")

        # All old cards should have been assigned seq_nums in timestamp order
        assert old_cards[0].seq_num == 1  # oldest
        assert old_cards[1].seq_num == 2
        assert old_cards[2].seq_num == 3  # newest


# ═══════════════════════════════════════════════════════════════════
#  TestSmartScroll — Phase 4 (consolidated: only schedule_smart_scroll_to_bottom
#  and schedule_scroll_to_bottom remain in the public API; the old synchronous
#  scroll_to_bottom() and smart_scroll_to_bottom() were removed during the
#  4-scroll-sites → 1-funnel refactor).
# ═══════════════════════════════════════════════════════════════════

class TestSmartScroll:
    """Phase 4 + refactor: schedule_smart_scroll_to_bottom only scrolls when
    the user is near the bottom (within 80px). If the user has scrolled up to
    read older cards, the scroll is skipped so their reading position is
    preserved. schedule_scroll_to_bottom is the unconditional variant."""

    def test_smart_scroll_when_near_bottom(self):
        """If user is within 80px of bottom, smart_scroll scrolls to bottom."""
        mock_tab = MockFeedTab()
        # Set user at upper-50 (50px from bottom, since page_size=600, upper=1000)
        mock_tab._vadjustment = MockVadjustment(value=950, upper=1000, page_size=600)
        # distance_from_bottom = 1000 - 600 - 950 = -450 → < 80, scrolls
        mock_tab.schedule_smart_scroll_to_bottom()
        assert mock_tab._vadjustment.get_value() == 1000

    def test_smart_scroll_when_exactly_80px_from_bottom(self):
        """If user is exactly 80px from bottom, smart_scroll DOES NOT scroll (boundary: <80)."""
        mock_tab = MockFeedTab()
        # upper=1000, page_size=600, so being 80px from bottom means value=1000-600-80=320
        mock_tab._vadjustment = MockVadjustment(value=320, upper=1000, page_size=600)
        # distance_from_bottom = 1000 - 600 - 320 = 80 → NOT < 80, no scroll
        mock_tab.schedule_smart_scroll_to_bottom()
        assert mock_tab._vadjustment.get_value() == 320  # unchanged

    def test_smart_scroll_when_far_from_bottom(self):
        """If user is >80px from bottom, smart_scroll does nothing."""
        mock_tab = MockFeedTab()
        # User scrolled to top: value=0
        mock_tab._vadjustment = MockVadjustment(value=0, upper=1000, page_size=600)
        # distance_from_bottom = 1000 - 600 - 0 = 400 → > 80, no scroll
        mock_tab.schedule_smart_scroll_to_bottom()
        assert mock_tab._vadjustment.get_value() == 0  # unchanged

    def test_smart_scroll_when_mid_feed(self):
        """If user is mid-feed and >80px from bottom, smart_scroll does nothing."""
        mock_tab = MockFeedTab()
        # User scrolled halfway: value=200
        mock_tab._vadjustment = MockVadjustment(value=200, upper=1000, page_size=600)
        # distance_from_bottom = 1000 - 600 - 200 = 200 → > 80, no scroll
        mock_tab.schedule_smart_scroll_to_bottom()
        assert mock_tab._vadjustment.get_value() == 200  # unchanged

    def test_schedule_scroll_to_bottom_always_scrolls(self):
        """The unconditional schedule_scroll_to_bottom() always scrolls."""
        mock_tab = MockFeedTab()
        # User scrolled to top
        mock_tab._vadjustment = MockVadjustment(value=0, upper=1000, page_size=600)
        mock_tab.schedule_scroll_to_bottom()
        assert mock_tab._vadjustment.get_value() == 1000

    def test_smart_scroll_no_vadjustment_is_noop(self):
        """If _vadjustment is None, smart_scroll is a no-op (graceful)."""
        mock_tab = MockFeedTab()
        mock_tab._vadjustment = None
        # Should not raise
        mock_tab.schedule_smart_scroll_to_bottom()

    def test_add_card_uses_smart_scroll_only(self, feed_handler, mock_feed_tab):
        """add_card() calls schedule_smart_scroll_to_bottom exactly once.

        This is the consolidation contract: all append paths funnel through
        a single helper (_schedule_smart_scroll) which calls this one method.
        """
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Test card",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        original_smart = mock_feed_tab.schedule_smart_scroll_to_bottom
        called = []
        def tracking_smart():
            called.append(True)
            return original_smart()
        mock_feed_tab.schedule_smart_scroll_to_bottom = tracking_smart

        feed_handler.add_card(card)

        assert len(called) == 1, "schedule_smart_scroll_to_bottom should be called exactly once in add_card"


class TestAddCardsBatch:
    """Refactor: add_cards_batch() runs multiple cards through ONE idle
    callback and ONE smart-scroll. Previously each add_card() enqueued its
    own callback, racing the vadjustment when batches arrived faster than
    GTK could lay them out."""

    def test_add_cards_batch_returns_ids_in_input_order(self, feed_handler):
        """Returns card_ids in the same order as the input cards list."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="batchproj",
            )
            for i in range(5)
        ]
        ids = feed_handler.add_cards_batch(cards)
        assert len(ids) == 5
        # Each id must match the corresponding card's assigned card_id
        for i, cid in enumerate(ids):
            assert cards[i].card_id == cid

    def test_add_cards_batch_single_smart_scroll(self, feed_handler, mock_feed_tab):
        """Batched cards trigger schedule_smart_scroll_to_bottom exactly once."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="batchproj",
            )
            for i in range(3)
        ]
        original = mock_feed_tab.schedule_smart_scroll_to_bottom
        called = []
        def tracking():
            called.append(True)
            return original()
        mock_feed_tab.schedule_smart_scroll_to_bottom = tracking

        feed_handler.add_cards_batch(cards)

        assert len(called) == 1, (
            f"add_cards_batch must call schedule_smart_scroll_to_bottom "
            f"exactly once, got {len(called)} calls"
        )

    def test_add_cards_batch_assigns_monotonic_sequence_numbers(self, feed_handler):
        """Each card in the batch gets a unique, increasing seq_num."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="seqproj",
            )
            for i in range(4)
        ]
        feed_handler.add_cards_batch(cards)
        seqs = [c.seq_num for c in cards]
        # Strictly increasing
        assert seqs == sorted(set(seqs))
        assert len(seqs) == 4

    def test_add_cards_batch_empty_input_is_noop(self, feed_handler, mock_feed_tab):
        """Empty list returns [] and does not call schedule_smart_scroll_to_bottom."""
        called = []
        original = mock_feed_tab.schedule_smart_scroll_to_bottom
        def tracking():
            called.append(True)
            return original()
        mock_feed_tab.schedule_smart_scroll_to_bottom = tracking

        result = feed_handler.add_cards_batch([])
        assert result == []
        assert len(called) == 0

    def test_add_cards_batch_indexes_all_under_project(self, feed_handler):
        """All batched cards show up in get_cards_for_project."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="indexproj",
            )
            for i in range(3)
        ]
        feed_handler.add_cards_batch(cards)
        listed = feed_handler.get_cards_for_project("indexproj")
        assert len(listed) == 3

    def test_add_cards_batch_widgets_appended_in_one_idle(self, feed_handler, mock_feed_tab):
        """All batched cards are appended to feed_tab in a single idle callback."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="idleproj",
            )
            for i in range(3)
        ]
        # Snapshot append_card call count before batch
        before = len(mock_feed_tab.append_calls)

        feed_handler.add_cards_batch(cards)

        # MockGLib.idle_add runs callbacks synchronously, so by the time
        # add_cards_batch returns, the bulk _append_all callback has already
        # fired and appended all 3 cards. No drain needed.
        appended = len(mock_feed_tab.append_calls) - before
        assert appended == 3, (
            f"add_cards_batch should append all cards in one idle callback "
            f"(3 append_card calls total), got {appended}"
        )

    def test_add_cards_batch_mixed_approval_and_normal(self, feed_handler):
        """Approval cards and normal cards can be batched together."""
        ts = datetime.now(timezone.utc)
        cards = [
            FeedCardData(
                card_type="diff", source="agent", title="Normal",
                body="", author="x", timestamp=ts, project_name="mixedproj",
            ),
            FeedCardData(
                card_type="exec_approval", source="agent", title="Needs approval",
                body="", author="x", timestamp=ts, project_name="mixedproj",
                metadata={"needs_approval": True},
            ),
            FeedCardData(
                card_type="diff", source="agent", title="Also normal",
                body="", author="x", timestamp=ts, project_name="mixedproj",
            ),
        ]
        ids = feed_handler.add_cards_batch(cards)
        assert len(ids) == 3
        # All three cards (normal + approval) should have widgets stored
        for cid in ids:
            assert cid in feed_handler._card_widgets


# ═══════════════════════════════════════════════════════════════════
#  TestBatchAccept — Phase 5
#  Verifies batch accept bar appears when ≥2 pending file-change cards,
#  and that Accept All resolves them all.
# ═══════════════════════════════════════════════════════════════════

class TestBatchAccept:
    """Phase 5: batch accept bar + handle_batch_accept()."""

    def test_update_batch_bar_0_hides_bar(self, feed_handler, mock_feed_tab):
        """update_batch_bar(0) hides the batch bar."""
        feed_handler._active_project_name = "testproj"
        feed_handler._update_batch_bar_for_active_project()
        assert mock_feed_tab._batch_bar_visible is False

    def test_update_batch_bar_1_hides_bar(self, feed_handler, mock_feed_tab):
        """update_batch_bar(1) hides the bar (threshold is ≥2)."""
        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Card 1",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card)
        feed_handler._update_batch_bar_for_active_project()
        assert mock_feed_tab._batch_bar_visible is False

    def test_update_batch_bar_2_shows_bar(self, feed_handler, mock_feed_tab):
        """update_batch_bar(2) shows the bar."""
        ts = datetime.now(timezone.utc)
        for i in range(2):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="testproj",
            )
            feed_handler.add_card(card)
        feed_handler._update_batch_bar_for_active_project()
        assert mock_feed_tab._batch_bar_visible is True
        assert mock_feed_tab._batch_bar_count == 2

    def test_update_batch_bar_3_shows_bar(self, feed_handler, mock_feed_tab):
        """update_batch_bar(3) shows the bar with count 3."""
        ts = datetime.now(timezone.utc)
        for i in range(3):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="testproj",
            )
            feed_handler.add_card(card)
        feed_handler._update_batch_bar_for_active_project()
        assert mock_feed_tab._batch_bar_visible is True
        assert mock_feed_tab._batch_bar_count == 3

    def test_trailing_run_only_counts_consecutive_pending(self, feed_handler, mock_feed_tab):
        """If a non-pending or non-file-change card breaks the sequence, only trailing run counts."""
        ts = datetime.now(timezone.utc)
        # Card 0: accepted diff → breaks the run
        c0 = FeedCardData(
            card_type="diff", source="agent", title="Accepted",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        c0.accepted = True
        feed_handler.add_card(c0)
        # Card 1: system card → also breaks the run
        c1 = FeedCardData(
            card_type="system", source="agent", title="System",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(c1)
        # Cards 2, 3: pending diffs (newest)
        for i in [3, 2]:
            c = FeedCardData(
                card_type="diff", source="agent", title=f"Pending {i}",
                body="", author="x", timestamp=ts, project_name="testproj",
            )
            feed_handler.add_card(c)
        feed_handler._update_batch_bar_for_active_project()
        # Only the trailing 2 pending diffs count
        assert mock_feed_tab._batch_bar_visible is True
        assert mock_feed_tab._batch_bar_count == 2

    def test_handle_batch_accept_calls_handle_accept_per_card(
        self, feed_handler, mock_feed_tab
    ):
        """handle_batch_accept iterates through card_ids and calls handle_accept for each."""
        ts = datetime.now(timezone.utc)
        cards = []
        for i in range(3):
            c = FeedCardData(
                card_type="diff", source="agent", title=f"Card {i}",
                body="", author="x", timestamp=ts, project_name="testproj",
            )
            feed_handler.add_card(c)
            cards.append(c)
        # Patch handle_accept to track calls
        original = feed_handler.handle_accept
        calls = []
        def tracking_accept(cid):
            calls.append(cid)
            return original(cid)
        feed_handler.handle_accept = tracking_accept

        card_ids = [c.card_id for c in cards]
        feed_handler.handle_batch_accept(card_ids)

        assert len(calls) == 3
        assert calls == card_ids

    def test_batch_accept_resolves_all_pending(
        self, feed_handler, mock_feed_tab
    ):
        """Batch bar hides once all pending actionable cards are accepted."""
        # Use file_created type (actionable, no git thread complexity)
        ts = datetime.now(timezone.utc)
        cards = []
        for i in range(3):
            c = FeedCardData(
                card_type="file_created", source="agent",
                title=f"New file {i}", body="", author="x",
                timestamp=ts, project_name="testproj",
            )
            feed_handler.add_card(c)
            cards.append(c)

        # Verify bar is showing with 3 pending
        assert mock_feed_tab._batch_bar_count == 3
        assert mock_feed_tab._batch_bar_visible is True

        # Simulate each card being accepted (directly, bypassing git ops)
        for card in cards:
            card.accepted = True
        # Update bar — count drops to 0, bar hides
        feed_handler._update_batch_bar_for_active_project("testproj")

        assert mock_feed_tab._batch_bar_visible is False

    def test_callback_is_wired_on_set_feed_tab(self, feed_handler, mock_feed_tab):
        """set_feed_tab() installs the batch accept callback on the FeedTab."""
        assert mock_feed_tab._batch_accept_callback is not None
        assert callable(mock_feed_tab._batch_accept_callback)

    def test_add_card_updates_batch_bar(self, feed_handler, mock_feed_tab):
        """add_card() for a 2nd file-change card triggers batch bar to show."""
        ts = datetime.now(timezone.utc)
        feed_handler._active_project_name = "testproj"
        # First card — bar hidden
        c1 = FeedCardData(
            card_type="diff", source="agent", title="Card 1",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(c1)
        assert mock_feed_tab._batch_bar_visible is False
        # Second card — bar shows
        c2 = FeedCardData(
            card_type="diff", source="agent", title="Card 2",
            body="", author="x", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(c2)
        assert mock_feed_tab._batch_bar_visible is True
        assert mock_feed_tab._batch_bar_count == 2


# ═══════════════════════════════════════════════════════════════════
#  TestScheduleScrollToBottom — Phase 4D-1
#  Tests the real schedule_scroll_to_bottom mechanism on FeedTab.
#  Uses _FakeAdjustment (not MockFeedTab) to exercise the actual
#  connect/disconnect/emit/timeout logic in feed_tab.py.
# ═══════════════════════════════════════════════════════════════════

import gi
gi.require_version('Gtk', '4.0')


class _FakeAdjustment:
    """
    Duck-typed replacement for Gtk.Adjustment that does NOT auto-emit
    'changed' when properties change. Tests manually call emit_changed()
    to control exactly when the 'changed' signal fires, and set_upper()
    to control what get_upper() returns.

    This is necessary because Gtk.Adjustment.set_upper() emits 'changed'
    internally — making it impossible to test the 'changed never fires'
    timeout-fallback path with a real Adjustment.
    """

    def __init__(self, upper=0.0, page_size=600.0):
        self._upper = upper
        self._value = 0.0
        self._page_size = page_size
        self._handlers: dict[int, callable] = {}
        self._next_id = 1
        self.set_value_calls: list[float] = []
        self.disconnect_calls: list[int] = []

    def connect(self, signal: str, callback) -> int:
        assert signal == "changed", (
            f"_FakeAdjustment.connect: unexpected signal {signal!r}"
        )
        handler_id = self._next_id
        self._next_id += 1
        self._handlers[handler_id] = callback
        return handler_id

    def disconnect(self, handler_id: int):
        self.disconnect_calls.append(handler_id)
        self._handlers.pop(handler_id, None)

    def emit_changed(self):
        """Manually fire the 'changed' signal to all connected handlers."""
        # Copy the list because handlers may disconnect during iteration
        for cb in list(self._handlers.values()):
            cb(self)

    def get_upper(self) -> float:
        return self._upper

    def set_upper(self, upper: float):
        """Set upper WITHOUT emitting 'changed' (unlike real Gtk.Adjustment)."""
        self._upper = upper

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float):
        self._value = value
        self.set_value_calls.append(value)

    def get_page_size(self) -> float:
        return self._page_size


class _FakeScrolledWindow:
    """Minimal stand-in for Gtk.ScrolledWindow holding a _FakeAdjustment."""

    def __init__(self, vadj: _FakeAdjustment):
        self._vadj = vadj

    def get_vadjustment(self) -> _FakeAdjustment:
        return self._vadj


@pytest.fixture
def real_feed_tab():
    """Create a real FeedTab instance for testing schedule_scroll_to_bottom.

    FeedTab constructs a Gtk.ScrolledWindow in __init__, but we replace
    _feed_scroll with a _FakeScrolledWindow holding a _FakeAdjustment so
    we can control when 'changed' fires.
    """
    from ui.views.feed_tab import FeedTab
    tab = FeedTab()
    # Replace the real scrolled window with our fake
    adj = _FakeAdjustment(upper=0.0)
    tab._feed_scroll = _FakeScrolledWindow(adj)
    return tab


class TestScheduleScrollToBottom:
    """
    Phase 4D-1: Test the real schedule_scroll_to_bottom mechanism.

    These tests exercise the actual FeedTab.schedule_scroll_to_bottom code,
    NOT the MockFeedTab stub. They use _FakeAdjustment to control when the
    'changed' signal fires and what upper returns.
    """

    def test_schedule_scroll_does_not_scroll_immediately_when_upper_is_stale(
        self, real_feed_tab
    ):
        """Bug A regression: when upper is stale (0) at connect time, the scroll
        must NOT happen synchronously. It must wait for 'changed' to fire after
        GTK updates upper during the layout pass.

        Steps:
        1. FakeAdjustment starts with upper=0 (stale, pre-layout).
        2. Call schedule_scroll_to_bottom().
        3. Assert set_value was NOT called yet (stale upper would scroll to top).
        4. Simulate layout pass: set upper to 1000, then emit 'changed'.
        5. Assert set_value(1000) was called.
        """
        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        tab.schedule_scroll_to_bottom()

        # set_value must NOT have been called synchronously
        assert adj.set_value_calls == [], (
            f"Expected no set_value call before 'changed', got {adj.set_value_calls}"
        )

        # Simulate layout pass updating upper
        adj.set_upper(1000.0)
        adj.emit_changed()

        assert adj.set_value_calls == [1000.0], (
            f"Expected set_value(1000.0) after 'changed', got {adj.set_value_calls}"
        )

    def test_schedule_scroll_fires_via_timeout_fallback_when_changed_never_fires(
        self, real_feed_tab, monkeypatch
    ):
        """Safety net: if 'changed' never fires, the 150ms timeout must scroll.

        We monkeypatch GLib.timeout_add to capture the callback and timeout
        so we can invoke it manually without waiting 150ms.
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        captured_timeouts = []

        def fake_timeout_add(ms, callback):
            source_id = 42  # deterministic fake source ID
            captured_timeouts.append((source_id, ms, callback))
            return source_id

        monkeypatch.setattr(GLib, "timeout_add", fake_timeout_add)

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        tab.schedule_scroll_to_bottom()

        # A timeout must have been registered
        assert len(captured_timeouts) == 1, (
            f"Expected 1 timeout registered, got {len(captured_timeouts)}"
        )
        source_id, ms, callback = captured_timeouts[0]
        assert ms == 150, f"Expected 150ms timeout, got {ms}ms"

        # Set upper to simulate content being present
        adj.set_upper(800.0)

        # 'changed' never fires — invoke the timeout callback directly
        result = callback()

        assert result == GLib.SOURCE_REMOVE, (
            f"Expected SOURCE_REMOVE, got {result}"
        )
        assert adj.set_value_calls == [800.0], (
            f"Expected set_value(800.0) from timeout, got {adj.set_value_calls}"
        )

    def test_schedule_scroll_disconnects_changed_handler_after_fire(
        self, real_feed_tab, monkeypatch
    ):
        """One-shot verification: after 'changed' fires, the handler must be
        disconnected. A second emit of 'changed' must NOT trigger another scroll.
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        # Monkeypatch timeout_add and source_remove to avoid real GLib timers
        monkeypatch.setattr(GLib, "timeout_add", lambda ms, cb: 99)
        monkeypatch.setattr(GLib, "source_remove", lambda sid: None)

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        tab.schedule_scroll_to_bottom()

        # First emit — should scroll
        adj.set_upper(1000.0)
        adj.emit_changed()
        assert len(adj.set_value_calls) == 1, (
            f"Expected 1 set_value after first 'changed', got {len(adj.set_value_calls)}"
        )

        # Second emit — should NOT scroll (handler was disconnected)
        adj.set_upper(2000.0)
        adj.emit_changed()
        assert len(adj.set_value_calls) == 1, (
            f"Expected still 1 set_value after second 'changed', got {len(adj.set_value_calls)}"
        )

    def test_schedule_scroll_disarms_timeout_after_changed_fires(
        self, real_feed_tab, monkeypatch
    ):
        """4D-3 cleanup-race regression test.

        When 'changed' fires (success path), the timeout must be disarmed via
        GLib.source_remove. This prevents the timeout from firing 150ms later
        and re-scrolling the feed if the user has already scrolled away.

        Without the 4D-3 fix, the success path did NOT call source_remove —
        the timeout fired unconditionally and could re-scroll.
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        captured_timeouts = []
        removed_sources = []

        def fake_timeout_add(ms, callback):
            source_id = 77
            captured_timeouts.append((source_id, ms, callback))
            return source_id

        monkeypatch.setattr(GLib, "timeout_add", fake_timeout_add)
        monkeypatch.setattr(
            GLib,
            "source_remove",
            lambda sid: removed_sources.append(sid),
        )

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        tab.schedule_scroll_to_bottom()

        assert len(captured_timeouts) == 1
        timeout_source_id, _, timeout_callback = captured_timeouts[0]

        # Verify _scroll_timeout_id was set
        assert tab._scroll_timeout_id == timeout_source_id, (
            f"Expected _scroll_timeout_id={timeout_source_id}, "
            f"got {tab._scroll_timeout_id}"
        )

        # 'changed' fires — success path should disarm the timeout
        adj.set_upper(1000.0)
        adj.emit_changed()

        # Timeout must have been disarmed via source_remove
        assert timeout_source_id in removed_sources, (
            f"Expected source_remove({timeout_source_id}), "
            f"got removed_sources={removed_sources}"
        )
        assert tab._scroll_timeout_id is None, (
            f"Expected _scroll_timeout_id=None after 'changed', "
            f"got {tab._scroll_timeout_id}"
        )

        # Invoke the timeout callback manually — it should NOT scroll again
        # because _scroll_handler_id is None (already cleared by success path)
        adj.set_upper(5000.0)  # different value to detect re-scroll
        result = timeout_callback()

        # set_value_calls should still be [1000.0] from the 'changed' path
        assert adj.set_value_calls == [1000.0], (
            f"Timeout re-scrolled after disarm! set_value_calls={adj.set_value_calls}"
        )

    def test_schedule_scroll_handles_disconnect_exception(
        self, real_feed_tab, monkeypatch
    ):
        """Defensive cleanup test: if disconnect() raises during the 'changed'
        handler (e.g., adjustment disposed during teardown), the handler must
        not propagate the exception and must still clean up state.

        This documents the try/except behavior in the production code.
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        monkeypatch.setattr(GLib, "timeout_add", lambda ms, cb: 88)
        monkeypatch.setattr(GLib, "source_remove", lambda sid: None)

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        # Make disconnect raise
        original_disconnect = adj.disconnect
        adj.disconnect = lambda hid: (_ for _ in ()).throw(
            RuntimeError("simulated dispose")
        )

        tab.schedule_scroll_to_bottom()

        # 'changed' fires — disconnect will raise, but the try/except must catch it
        adj.set_upper(1000.0)
        adj.emit_changed()  # must not propagate

        # set_value must still have been called (scroll happened before disconnect)
        assert 1000.0 in adj.set_value_calls, (
            f"Expected set_value(1000.0) despite disconnect exception, "
            f"got {adj.set_value_calls}"
        )

        # Restore disconnect for cleanup
        adj.disconnect = original_disconnect


# ═══════════════════════════════════════════════════════════════════
#  TestClearWidgetStateRecursive — Phase 4D-2
#  Tests _clear_widget_state_recursive on real Gtk.Box/Button/Label trees.
#  Verifies the recursive walk clears PRELIGHT/ACTIVE/SELECTED on self +
#  all descendants.
# ═══════════════════════════════════════════════════════════════════

class TestClearWidgetStateRecursive:
    """
    Phase 4D-2: Test _clear_widget_state_recursive against real GTK4 widgets.

    Uses Gtk.Box + Gtk.Button + Gtk.Label trees because these are the exact
    widget types used in feed cards.
    """

    def test_clear_widget_state_visits_self_and_all_descendants(self):
        """Build a real widget tree: Box → [Button(label=A, child=Label), Button(label=B)].
        Set PRELIGHT on box + both buttons + label. Call _clear_widget_state_recursive.
        Assert PRELIGHT is cleared on all 4 widgets.
        """
        from ui.views.feed_tab import FeedTab
        from gi.repository import Gtk

        # Build tree
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        btn_a = Gtk.Button(label="A")
        lbl = Gtk.Label(label="nested")
        btn_a.set_child(lbl)  # btn_a has a child Label
        btn_b = Gtk.Button(label="B")
        outer.append(btn_a)
        outer.append(btn_b)

        # Set PRELIGHT on all 4 widgets
        outer.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        btn_a.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        btn_b.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        lbl.set_state_flags(Gtk.StateFlags.PRELIGHT, False)

        # Verify PRELIGHT is set before clearing
        assert bool(outer.get_state_flags() & Gtk.StateFlags.PRELIGHT)
        assert bool(btn_a.get_state_flags() & Gtk.StateFlags.PRELIGHT)
        assert bool(btn_b.get_state_flags() & Gtk.StateFlags.PRELIGHT)
        assert bool(lbl.get_state_flags() & Gtk.StateFlags.PRELIGHT)

        # Call the method via a FeedTab instance (it's a method on FeedTab)
        # But we don't need the full FeedTab — we can call the unbound method
        # Actually, _clear_widget_state_recursive uses self only for dispatch,
        # not for any instance state. But it's a method, so we need an instance.
        # Create a minimal FeedTab.
        tab = FeedTab()
        tab._clear_widget_state_recursive(outer)

        # Assert PRELIGHT is cleared on all 4 widgets
        assert not bool(outer.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"outer still has PRELIGHT: {outer.get_state_flags()}"
        )
        assert not bool(btn_a.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"btn_a still has PRELIGHT: {btn_a.get_state_flags()}"
        )
        assert not bool(btn_b.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"btn_b still has PRELIGHT: {btn_b.get_state_flags()}"
        )
        assert not bool(lbl.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"lbl still has PRELIGHT: {lbl.get_state_flags()}"
        )

    def test_clear_widget_state_handles_widget_without_state_safely(self):
        """Call _clear_widget_state_recursive on a fresh Gtk.Box that has never
        had any state flags set. Must not raise.
        """
        from ui.views.feed_tab import FeedTab
        from gi.repository import Gtk

        box = Gtk.Box()  # never had flags set

        # Verify it starts clean (only DIR_LTR is default)
        flags_before = box.get_state_flags()
        assert not bool(flags_before & Gtk.StateFlags.PRELIGHT)
        assert not bool(flags_before & Gtk.StateFlags.ACTIVE)
        assert not bool(flags_before & Gtk.StateFlags.SELECTED)

        tab = FeedTab()
        # Must not raise
        tab._clear_widget_state_recursive(box)

        # Still clean
        flags_after = box.get_state_flags()
        assert not bool(flags_after & Gtk.StateFlags.PRELIGHT)
        assert not bool(flags_after & Gtk.StateFlags.ACTIVE)
        assert not bool(flags_after & Gtk.StateFlags.SELECTED)

    def test_clear_widget_state_handles_unset_exception_gracefully(self):
        """If unset_state_flags raises on a widget, the recursion must continue
        to siblings and children. This documents the try/except in the production
        code.

        We build a real tree and monkey-patch unset_state_flags on ONE widget
        to raise. Then verify its child and sibling are still processed.
        """
        from ui.views.feed_tab import FeedTab
        from gi.repository import Gtk

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        btn_problem = Gtk.Button(label="problem")
        lbl_inside_problem = Gtk.Label(label="inside")
        btn_problem.set_child(lbl_inside_problem)
        btn_ok = Gtk.Button(label="ok")
        outer.append(btn_problem)
        outer.append(btn_ok)

        # Set PRELIGHT on all
        outer.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        btn_problem.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        lbl_inside_problem.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        btn_ok.set_state_flags(Gtk.StateFlags.PRELIGHT, False)

        # Monkey-patch unset_state_flags on btn_problem to raise
        original_unset = btn_problem.unset_state_flags

        def raising_unset(flags):
            raise RuntimeError("simulated widget disposal")

        btn_problem.unset_state_flags = raising_unset

        tab = FeedTab()
        # Must not propagate the exception
        tab._clear_widget_state_recursive(outer)

        # btn_problem: exception was caught, but PRELIGHT might still be set
        # because unset_state_flags raised. That's acceptable — the production
        # code uses try/except Exception: pass.
        # Restore original to verify
        btn_problem.unset_state_flags = original_unset
        # btn_problem may still have PRELIGHT (the exception prevented clearing)
        # This is documented behavior — the recursive walker continues despite errors.

        # CRITICAL assertions: sibling and child must be cleared
        assert not bool(btn_ok.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"btn_ok should have been cleared but still has PRELIGHT: "
            f"{btn_ok.get_state_flags()}"
        )
        assert not bool(lbl_inside_problem.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"lbl_inside_problem should have been cleared (recursion continued "
            f"past the exception) but still has PRELIGHT: "
            f"{lbl_inside_problem.get_state_flags()}"
        )
        assert not bool(outer.get_state_flags() & Gtk.StateFlags.PRELIGHT), (
            f"outer should have been cleared but still has PRELIGHT: "
            f"{outer.get_state_flags()}"
        )


# ═══════════════════════════════════════════════════════════════════
#  TestScheduleSmartScrollToBottom — Deferred Smart Scroll with Proximity
#  Tests the real schedule_smart_scroll_to_bottom method on FeedTab.
#  Uses _FakeAdjustment (not MockFeedTab) to exercise the real code path
#  with full control over when 'changed' fires and what upper returns.
# ═══════════════════════════════════════════════════════════════════

class TestScheduleSmartScrollToBottom:
    """
    Tests schedule_smart_scroll_to_bottom: proximity check + deferred scroll.

    These tests exercise the actual FeedTab.schedule_smart_scroll_to_bottom
    code, NOT the MockFeedTab stub. They use _FakeAdjustment to control
    vadjustment values and signal timing.
    """

    def test_schedule_smart_scrolls_when_user_near_bottom(
        self, real_feed_tab, monkeypatch
    ):
        """When the user is within 80px of the bottom, the method must delegate
        to schedule_scroll_to_bottom so the scroll fires after the layout pass.

        Setup: upper=1000, page_size=600, value=350.
        distance_from_bottom = 1000 - 600 - 350 = 50px (< 80 → near bottom).

        After calling schedule_smart_scroll_to_bottom:
        - The 'changed' handler must be connected (proof delegation happened)
        - When we simulate layout (set upper to 1500, emit 'changed'), the
          scroll must fire to 1500 (the post-layout upper, not the stale 1000)
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        monkeypatch.setattr(GLib, "timeout_add", lambda ms, cb: 42)
        monkeypatch.setattr(GLib, "source_remove", lambda sid: None)

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        # User is near the bottom: distance = 1000 - 600 - 350 = 50px
        adj.set_upper(1000.0)
        adj._value = 350.0
        adj._page_size = 600.0

        tab.schedule_smart_scroll_to_bottom()

        # Proof that delegation to schedule_scroll_to_bottom happened:
        # the 'changed' handler must be connected.
        assert tab._scroll_handler_id is not None, (
            "Expected _scroll_handler_id to be set (delegation to "
            "schedule_scroll_to_bottom), got None"
        )

        # No scroll should have happened yet (waiting for 'changed')
        assert adj.set_value_calls == [], (
            f"Expected no set_value before 'changed', got {adj.set_value_calls}"
        )

        # Simulate layout pass: upper grows to 1500 (new card appended)
        adj.set_upper(1500.0)
        adj.emit_changed()

        # Scroll must fire to the post-layout upper, not the stale 1000
        assert adj.set_value_calls == [1500.0], (
            f"Expected set_value(1500.0) after layout, got {adj.set_value_calls}"
        )

    def test_schedule_smart_does_not_scroll_when_user_scrolled_up(
        self, real_feed_tab, monkeypatch
    ):
        """When the user has scrolled up more than 80px from the bottom, the
        method must NOT scroll at all — preserve the user's reading position.

        Setup: upper=2000, page_size=600, value=200.
        distance_from_bottom = 2000 - 600 - 200 = 1200px (>> 80 → scrolled up).

        After calling schedule_smart_scroll_to_bottom:
        - No 'changed' handler connected (no delegation)
        - No timeout installed
        - No set_value calls
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        timeout_calls = []
        monkeypatch.setattr(
            GLib, "timeout_add",
            lambda ms, cb: timeout_calls.append((ms, cb)) or 99,
        )

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        # User has scrolled way up: distance = 2000 - 600 - 200 = 1200px
        adj.set_upper(2000.0)
        adj._value = 200.0
        adj._page_size = 600.0

        tab.schedule_smart_scroll_to_bottom()

        # No handler must be connected
        assert tab._scroll_handler_id is None, (
            f"Expected _scroll_handler_id=None (user scrolled up, no scroll), "
            f"got {tab._scroll_handler_id}"
        )
        # No timeout must be installed
        assert tab._scroll_timeout_id is None, (
            f"Expected _scroll_timeout_id=None (no delegation), "
            f"got {tab._scroll_timeout_id}"
        )
        assert timeout_calls == [], (
            f"Expected no timeout_add call, got {timeout_calls}"
        )
        # No scroll
        assert adj.set_value_calls == [], (
            f"Expected no set_value calls, got {adj.set_value_calls}"
        )

    def test_schedule_smart_uses_stale_upper_for_proximity_not_future(
        self, real_feed_tab, monkeypatch
    ):
        """Pins the design decision: the proximity check intentionally uses the
        pre-append (stale) upper because it measures the user's reading position,
        not the future content height.

        Setup: upper=800, page_size=600, value=180.
        distance_from_bottom = 800 - 600 - 180 = 20px (< 80 → near bottom).

        If the method used some hypothetical post-layout upper (say 1500),
        the distance would be 1500 - 600 - 180 = 720px (>> 80 → would NOT scroll).
        The test proves the stale upper is used by asserting the scroll fires.

        This test would FAIL if someone tried to be 'smart' and wait for the
        post-layout upper before doing the proximity check.
        """
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib

        monkeypatch.setattr(GLib, "timeout_add", lambda ms, cb: 55)
        monkeypatch.setattr(GLib, "source_remove", lambda sid: None)

        tab = real_feed_tab
        adj = tab._feed_scroll.get_vadjustment()

        # Stale upper = 800. User at value=180, page=600.
        # Stale distance = 800 - 600 - 180 = 20px (< 80 → near bottom).
        adj.set_upper(800.0)
        adj._value = 180.0
        adj._page_size = 600.0

        tab.schedule_smart_scroll_to_bottom()

        # Delegation must have happened because stale distance < 80
        assert tab._scroll_handler_id is not None, (
            "Expected delegation to schedule_scroll_to_bottom because "
            "stale distance (20px) < 80px threshold. "
            "If _scroll_handler_id is None, the method used a post-layout "
            "upper for the proximity check, which is the wrong design."
        )

        # Now simulate layout: upper grows to 1500 (card was appended)
        adj.set_upper(1500.0)
        adj.emit_changed()

        # Scroll fires to post-layout upper
        assert adj.set_value_calls == [1500.0], (
            f"Expected set_value(1500.0) after layout, got {adj.set_value_calls}"
        )


# ═══════════════════════════════════════════════════════════════════
#  TestFeedToolbarAutoAccept — Phase 5
#  Tests the auto-accept toggle, warning dialog, and auto-accept card hook.
#  Uses mock_glib + mock_feed_tab fixtures (defined at top of file).
# ═══════════════════════════════════════════════════════════════════

class TestFeedToolbarAutoAccept:
    """Phase 5: auto-accept toggle state, warning dialog, and card hook."""

    def test_default_auto_accept_is_off(self, feed_handler, mock_feed_tab):
        """Fresh handler — auto-accept toggle is OFF."""
        assert mock_feed_tab._auto_accept_active is False

    def test_set_feed_tab_wires_auto_accept_callback(self, feed_handler, mock_feed_tab):
        """set_feed_tab() installs the auto-accept toggle callback on FeedTab."""
        assert mock_feed_tab._auto_accept_callback is not None
        assert callable(mock_feed_tab._auto_accept_callback)

    def test_enable_auto_accept_sets_state(self, feed_handler, mock_glib, mock_feed_tab):
        """Toggling ON without warning callback → _auto_accept_enabled = True."""
        # No set_show_auto_accept_warning wired → falls through to enable path
        feed_handler._on_auto_accept_toggled(True)
        assert feed_handler._auto_accept_enabled is True

    def test_enable_auto_accept_updates_toggle_visual(self, feed_handler, mock_glib, mock_feed_tab):
        """Bug B regression: enabling auto-accept must update the visible toggle.

        Previously _enable_auto_accept only set _auto_accept_enabled and
        scheduled a save; the toolbar toggle's label stayed at
        'Auto-Accept: OFF' because Gtk.ToggleButton.set_active() does not
        change set_label() text. The fix calls update_auto_accept_state(True)
        so the toggle reflects the actual state.
        """
        assert mock_feed_tab._auto_accept_active is False
        feed_handler._enable_auto_accept()
        assert mock_feed_tab._auto_accept_active is True, (
            "Bug B regression: _enable_auto_accept did not flip the visible "
            "toggle to ON. Label would stay 'Auto-Accept: OFF' even though "
            "state is enabled."
        )

    def test_disable_auto_accept_sets_state(self, feed_handler, mock_feed_tab):
        """Toggling OFF → _auto_accept_enabled = False."""
        feed_handler._auto_accept_enabled = True
        feed_handler._on_auto_accept_toggled(False)
        assert feed_handler._auto_accept_enabled is False

    def test_cancel_auto_accept_resets_toggle(self, feed_handler, mock_glib, mock_feed_tab):
        """Warning dialog cancel → toggle snaps back to OFF."""
        # Mock warning callback that immediately invokes on_cancel
        def mock_warning(agent_name, on_confirm, on_cancel):
            on_cancel()

        feed_handler.set_show_auto_accept_warning(mock_warning)
        feed_handler._on_auto_accept_toggled(True)
        # _cancel_auto_accept idle_adds update_auto_accept_state(False)
        # Drain the idle queue
        for fn, args, kwargs in mock_glib._pending:
            fn(*args, **kwargs)
        assert mock_feed_tab._auto_accept_active is False

    def test_add_card_with_auto_accept_on_invokes_handle_accept(
        self, feed_handler, mock_glib, mock_feed_tab, monkeypatch
    ):
        """Auto-accept ON + actionable diff card → handle_accept called via idle_add."""
        feed_handler._auto_accept_enabled = True
        feed_handler._auto_accept_agent = None  # match any author
        feed_handler._active_project_name = "testproj"

        # Track handle_accept calls
        accepted_ids = []
        def mock_handle_accept(card_id):
            accepted_ids.append(card_id)
        monkeypatch.setattr(feed_handler, "handle_accept", mock_handle_accept)

        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Auto card",
            body="", author="coder", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card)

        # The auto-accept check runs inside _append (idle_add). MockGLib
        # runs callbacks synchronously, so by the time add_card() returns
        # the auto-accept lambda has already fired handle_accept exactly once.
        # We clear _pending so any re-processing during a drain loop doesn't
        # duplicate the accept call.
        mock_glib._pending.clear()

        assert len(accepted_ids) == 1, f"Expected 1 accept, got {len(accepted_ids)}"

    def test_auto_accept_only_for_actionable_cards(
        self, feed_handler, mock_glib, mock_feed_tab, monkeypatch
    ):
        """Auto-accept ON + tool_result card → handle_accept NOT called."""
        feed_handler._auto_accept_enabled = True
        feed_handler._auto_accept_agent = None
        feed_handler._active_project_name = "testproj"

        accepted_ids = []
        def mock_handle_accept(card_id):
            accepted_ids.append(card_id)
        monkeypatch.setattr(feed_handler, "handle_accept", mock_handle_accept)

        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="tool_result", source="agent", title="Tool result",
            body="", author="coder", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card)

        mock_glib._pending.clear()

        assert len(accepted_ids) == 0, f"Expected 0 accepts for tool_result, got {len(accepted_ids)}"

    def test_auto_accept_only_for_matching_author_when_persisted(
        self, feed_handler, mock_glib, mock_feed_tab, monkeypatch
    ):
        """Auto-accept ON with agent='coder' → only coder cards auto-accepted."""
        feed_handler._auto_accept_enabled = True
        feed_handler._auto_accept_agent = "coder"
        feed_handler._active_project_name = "testproj"

        accepted_ids = []
        def mock_handle_accept(card_id):
            accepted_ids.append(card_id)
        monkeypatch.setattr(feed_handler, "handle_accept", mock_handle_accept)

        ts = datetime.now(timezone.utc)
        # Card from wrong author → NOT auto-accepted
        card_qa = FeedCardData(
            card_type="diff", source="agent", title="QA card",
            body="", author="qa", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card_qa)

        # Card from matching author → auto-accepted
        card_coder = FeedCardData(
            card_type="diff", source="agent", title="Coder card",
            body="", author="coder", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card_coder)

        mock_glib._pending.clear()

        assert len(accepted_ids) == 1, f"Expected 1 accept (coder only), got {len(accepted_ids)}"

    def test_add_card_without_auto_accept_is_passive(
        self, feed_handler, mock_glib, mock_feed_tab, monkeypatch
    ):
        """Auto-accept OFF + actionable diff card → handle_accept NOT called (regression guard)."""
        # _auto_accept_enabled defaults to False
        feed_handler._active_project_name = "testproj"

        accepted_ids = []
        def mock_handle_accept(card_id):
            accepted_ids.append(card_id)
        monkeypatch.setattr(feed_handler, "handle_accept", mock_handle_accept)

        ts = datetime.now(timezone.utc)
        card = FeedCardData(
            card_type="diff", source="agent", title="Normal card",
            body="", author="coder", timestamp=ts, project_name="testproj",
        )
        feed_handler.add_card(card)

        mock_glib._pending.clear()

        assert len(accepted_ids) == 0, f"Expected 0 accepts (auto-accept OFF), got {len(accepted_ids)}"
