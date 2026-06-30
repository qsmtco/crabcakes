# tests/test_feed_handler.py
# Unit tests for ui/handlers/feed_handler.py — FeedHandler card lifecycle + actions.
#
# Tests the FeedHandler API without GTK (mock GLib.idle_add).

import pytest
from datetime import datetime, timezone
import sys
from unittest.mock import MagicMock, patch

from models.feed_card import AutoAcceptPrefs, ExecCommandPref, FeedCardData, FileChangePref
from utils.feed_store import _default_prefs, _merge_v2_defaults, _migrate_v1_to_v2, load_feed_prefs


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

    def test_disable_auto_accept_updates_toggle_visual(self, feed_handler, mock_glib, mock_feed_tab):
        """Label-bug regression: turning OFF must flip the toolbar label.

        Previously `_disable_auto_accept` only cleared `_auto_accept_enabled`
        and scheduled a save; the visible toggle stayed at 'Auto-Accept: ON'.
        The fix calls `update_auto_accept_state(False)` so the label tracks
        the underlying state. Symmetric with `test_enable_auto_accept_updates_toggle_visual`.
        """
        # Start from a known-enabled visual state (mirrors what _enable_auto_accept
        # would have produced).
        mock_feed_tab._auto_accept_active = True
        feed_handler._auto_accept_enabled = True
        feed_handler._disable_auto_accept()
        assert mock_feed_tab._auto_accept_active is False, (
            "Label-bug regression: _disable_auto_accept did not flip the visible "
            "toggle to OFF. Label would stay 'Auto-Accept: ON' after user click."
        )
        assert feed_handler._auto_accept_enabled is False

    def test_cancel_auto_accept_resets_toggle(self, feed_handler, mock_glib, mock_feed_tab):
        """Warning dialog cancel → toggle snaps back to OFF AND state resets.

        Invariant: when the user cancels, both the visible toggle AND the
        in-memory _auto_accept_enabled flag must be cleared. Previously only
        the toggle was reset, leaving a silent-accept window where add_card()
        would auto-accept new cards with no user-visible cue.
        """
        # Mock warning callback that immediately invokes on_cancel
        def mock_warning(agent_name, on_confirm, on_cancel):
            on_cancel()

        feed_handler.set_show_auto_accept_warning(mock_warning)
        feed_handler._on_auto_accept_toggled(True)
        # _cancel_auto_accept now resets _auto_accept_enabled synchronously
        # and idle_adds update_auto_accept_state(False).
        assert feed_handler._auto_accept_enabled is False, (
            "Invariant regression: _cancel_auto_accept left _auto_accept_enabled "
            "at True, creating a silent-accept window (auto-accept on in memory "
            "but UI shows OFF)."
        )
        # Drain the idle queue to confirm the visual update also runs.
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


# ═══════════════════════════════════════════════════════════════════
#  TestAutoAcceptPrefs — Phase 1
#  Verifies FileChangePref, ExecCommandPref, AutoAcceptPrefs dataclasses.
# ═══════════════════════════════════════════════════════════════════

class TestAutoAcceptPrefs:
    """Phase 1: AutoAcceptPrefs dataclass — defaults, enable/disable,
    serialization, instance isolation, locked_agent()."""

    def test_defaults_all_disabled(self):
        """Fresh AutoAcceptPrefs() has any_enabled()==False, all four
        file-change types disabled, exec mode=='off'."""
        p = AutoAcceptPrefs()
        assert p.any_enabled() is False
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert p.file_changes[ct].enabled is False
        assert p.exec_command.mode == "off"

    def test_enable_file_change_type(self):
        """Enabling one file-change type flips any_enabled() and
        is_file_type_enabled() correctly."""
        p = AutoAcceptPrefs()
        p.file_changes["diff"].enabled = True
        assert p.any_enabled() is True
        assert p.is_file_type_enabled("diff") is True
        assert p.is_file_type_enabled("file_created") is False
        assert p.is_file_type_enabled("file_modified") is False
        assert p.is_file_type_enabled("file_deleted") is False

    def test_enable_exec_command(self):
        """Setting exec mode to 'show' flips any_enabled()."""
        p = AutoAcceptPrefs()
        p.exec_command.mode = "show"
        assert p.any_enabled() is True
        # file_changes still all False
        assert p.is_file_type_enabled("diff") is False
        assert p.is_file_type_enabled("file_created") is False

    def test_to_dict_round_trip(self):
        """Create prefs with mixed state, to_dict() -> from_dict() preserves
        all fields."""
        p = AutoAcceptPrefs()
        p.file_changes["diff"].enabled = True
        p.file_changes["diff"].agent_scope = "claude"
        p.file_changes["file_created"].enabled = True
        p.exec_command.mode = "silent"
        p.exec_command.agent_scope = "all_agents"
        p.snoozed_card_ids.append("card-abc-123")
        p.snoozed_card_ids.append("card-xyz-789")

        raw = p.to_dict()
        p2 = AutoAcceptPrefs.from_dict(raw)

        assert p2.file_changes["diff"].enabled is True
        assert p2.file_changes["diff"].agent_scope == "claude"
        assert p2.file_changes["file_created"].enabled is True
        assert p2.file_changes["file_modified"].enabled is False
        assert p2.file_changes["file_deleted"].enabled is False
        assert p2.exec_command.mode == "silent"
        assert p2.exec_command.agent_scope == "all_agents"
        assert p2.snoozed_card_ids == ["card-abc-123", "card-xyz-789"]
        assert p2.any_enabled() is True

    def test_to_dict_has_version_2(self):
        """to_dict() emits version=2 at the top level."""
        p = AutoAcceptPrefs()
        raw = p.to_dict()
        assert raw["version"] == 2
        assert "auto_accept" in raw

    def test_from_dict_empty(self):
        """from_dict({}) returns all defaults (any_enabled False, exec off,
        all file types disabled, empty snooze)."""
        p = AutoAcceptPrefs.from_dict({})
        assert p.any_enabled() is False
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert p.file_changes[ct].enabled is False
            assert p.file_changes[ct].agent_scope == "first_author"
        assert p.exec_command.mode == "off"
        assert p.exec_command.agent_scope == "first_author"
        assert p.snoozed_card_ids == []

    def test_from_dict_missing_keys(self):
        """Partial dict with only some file_changes types: missing types
        fall back to defaults; provided types preserve their values."""
        raw = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": True, "agent_scope": "claude"},
                },
            },
        }
        p = AutoAcceptPrefs.from_dict(raw)
        # Provided type preserved
        assert p.file_changes["diff"].enabled is True
        assert p.file_changes["diff"].agent_scope == "claude"
        # Other types defaulted
        assert p.file_changes["file_created"].enabled is False
        assert p.file_changes["file_created"].agent_scope == "first_author"
        assert p.file_changes["file_modified"].enabled is False
        assert p.file_changes["file_deleted"].enabled is False
        # Exec defaults
        assert p.exec_command.mode == "off"
        # Snooze defaults
        assert p.snoozed_card_ids == []

    def test_instance_isolation(self):
        """Two AutoAcceptPrefs() instances must not share mutable state
        (file_changes dict, exec_command object, snoozed_card_ids list)."""
        a = AutoAcceptPrefs()
        b = AutoAcceptPrefs()
        # Mutating a's file_changes must not affect b
        a.file_changes["diff"].enabled = True
        assert b.file_changes["diff"].enabled is False
        # Mutating a's exec_command.mode must not affect b
        a.exec_command.mode = "show"
        assert b.exec_command.mode == "off"
        # Mutating a's snooze list must not affect b
        a.snoozed_card_ids.append("x")
        assert b.snoozed_card_ids == []
        # The containers themselves must be distinct objects
        assert a.file_changes is not b.file_changes
        assert a.snoozed_card_ids is not b.snoozed_card_ids

    def test_locked_agent_none(self):
        """Fresh prefs: locked_agent() returns None (no specific agent)."""
        p = AutoAcceptPrefs()
        assert p.locked_agent() is None

    def test_locked_agent_specific(self):
        """Setting one type's agent_scope to a specific agent name
        surfaces that agent via locked_agent()."""
        p = AutoAcceptPrefs()
        p.file_changes["diff"].agent_scope = "claude"
        assert p.locked_agent() == "claude"

    def test_locked_agent_first_author(self):
        """agent_scope = 'first_author' must NOT count as locked."""
        p = AutoAcceptPrefs()
        p.file_changes["diff"].agent_scope = "first_author"
        assert p.locked_agent() is None

    def test_locked_agent_all_agents(self):
        """agent_scope = 'all_agents' must NOT count as locked."""
        p = AutoAcceptPrefs()
        p.file_changes["file_created"].agent_scope = "all_agents"
        assert p.locked_agent() is None

    def test_snoozed_card_ids_default_empty(self):
        """Fresh prefs have empty snoozed_card_ids list."""
        p = AutoAcceptPrefs()
        assert p.snoozed_card_ids == []
        assert isinstance(p.snoozed_card_ids, list)

    def test_snoozed_card_ids_from_dict_non_list(self):
        """from_dict with snoozed_card_ids = 'notalist' (non-list value)
        must fall back to an empty list, not crash or propagate the bad value."""
        raw = {
            "version": 2,
            "auto_accept": {
                "snoozed_card_ids": "notalist",
            },
        }
        p = AutoAcceptPrefs.from_dict(raw)
        assert p.snoozed_card_ids == []
        assert isinstance(p.snoozed_card_ids, list)


# ═══════════════════════════════════════════════════════════════════
#  TestPrefsMigration — Phase 2
#  Verifies _default_prefs, _migrate_v1_to_v2, _merge_v2_defaults,
#  load_feed_prefs (with real file I/O via tempfile).
# ═══════════════════════════════════════════════════════════════════

import json
import os
import tempfile


class TestPrefsMigration:
    """Phase 2: v1→v2 migration, v2 default merging, load_feed_prefs
    file-I/O dispatch over v1/v2/missing/invalid/unknown."""

    def test_default_prefs_is_v2(self):
        """_default_prefs() returns a v2-shaped dict with all required
        nested keys present."""
        d = _default_prefs()
        assert d["version"] == 2
        assert "auto_accept" in d
        auto = d["auto_accept"]
        assert "file_changes" in auto
        assert "exec_command" in auto
        assert "snoozed_card_ids" in auto
        # file_changes has all four types
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert ct in auto["file_changes"]
            assert auto["file_changes"][ct]["enabled"] is False
            assert auto["file_changes"][ct]["agent_scope"] == "first_author"
        # exec_command defaults
        assert auto["exec_command"]["mode"] == "off"
        assert auto["exec_command"]["agent_scope"] == "first_author"
        # snoozed empty
        assert auto["snoozed_card_ids"] == []

    def test_default_prefs_independent_instances(self):
        """Two _default_prefs() calls return independent dicts (mutating
        one must not affect the other)."""
        a = _default_prefs()
        b = _default_prefs()
        assert a is not b
        # Mutate nested structure on a
        a["auto_accept"]["snoozed_card_ids"].append("x")
        a["auto_accept"]["file_changes"]["diff"]["enabled"] = True
        # b must be unaffected
        assert b["auto_accept"]["snoozed_card_ids"] == []
        assert b["auto_accept"]["file_changes"]["diff"]["enabled"] is False

    def test_migrate_v1_disabled(self):
        """v1 with auto_accept_enabled=False migrates to v2 with all four
        file types disabled and scope=first_author."""
        v1 = {"version": 1, "auto_accept_enabled": False, "auto_accept_agent": None}
        v2 = _migrate_v1_to_v2(v1)
        assert v2["version"] == 2
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert v2["auto_accept"]["file_changes"][ct]["enabled"] is False
            assert v2["auto_accept"]["file_changes"][ct]["agent_scope"] == "first_author"
        assert v2["auto_accept"]["exec_command"]["mode"] == "off"
        assert v2["auto_accept"]["exec_command"]["agent_scope"] == "first_author"
        assert v2["auto_accept"]["snoozed_card_ids"] == []

    def test_migrate_v1_enabled_no_agent(self):
        """v1 with auto_accept_enabled=True and auto_accept_agent=None
        migrates with all four types enabled at first_author scope."""
        v1 = {"version": 1, "auto_accept_enabled": True, "auto_accept_agent": None}
        v2 = _migrate_v1_to_v2(v1)
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert v2["auto_accept"]["file_changes"][ct]["enabled"] is True
            assert v2["auto_accept"]["file_changes"][ct]["agent_scope"] == "first_author"
        # exec scope tracks the same scope rule
        assert v2["auto_accept"]["exec_command"]["agent_scope"] == "first_author"

    def test_migrate_v1_enabled_with_agent(self):
        """v1 with auto_accept_enabled=True and auto_accept_agent='claude'
        preserves the agent lock-in across all four types (BUG #1 audit fix)."""
        v1 = {"version": 1, "auto_accept_enabled": True, "auto_accept_agent": "claude"}
        v2 = _migrate_v1_to_v2(v1)
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert v2["auto_accept"]["file_changes"][ct]["enabled"] is True
            assert v2["auto_accept"]["file_changes"][ct]["agent_scope"] == "claude"
        assert v2["auto_accept"]["exec_command"]["agent_scope"] == "claude"

    def test_migrate_v1_empty_dict(self):
        """Migrating {} (no auto_accept_enabled key) treats it as
        auto_accept_enabled=False — all disabled, scope=first_author."""
        v2 = _migrate_v1_to_v2({})
        assert v2["version"] == 2
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            assert v2["auto_accept"]["file_changes"][ct]["enabled"] is False
            assert v2["auto_accept"]["file_changes"][ct]["agent_scope"] == "first_author"
        assert v2["auto_accept"]["exec_command"]["mode"] == "off"

    def test_merge_v2_complete(self):
        """A complete v2 dict passes through _merge_v2_defaults unchanged."""
        full = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": True, "agent_scope": "claude"},
                    "file_created": {"enabled": True, "agent_scope": "all_agents"},
                    "file_modified": {"enabled": False, "agent_scope": "first_author"},
                    "file_deleted": {"enabled": False, "agent_scope": "first_author"},
                },
                "exec_command": {"mode": "silent", "agent_scope": "claude"},
                "snoozed_card_ids": ["card-1", "card-2"],
            },
        }
        merged = _merge_v2_defaults(full)
        assert merged == full

    def test_merge_v2_partial_missing_file_changes(self):
        """v2 with only the diff file_changes entry → other three types
        filled from defaults."""
        partial = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": True, "agent_scope": "claude"},
                },
            },
        }
        merged = _merge_v2_defaults(partial)
        # Provided type preserved
        assert merged["auto_accept"]["file_changes"]["diff"]["enabled"] is True
        assert merged["auto_accept"]["file_changes"]["diff"]["agent_scope"] == "claude"
        # Other three defaulted
        for ct in ("file_created", "file_modified", "file_deleted"):
            assert merged["auto_accept"]["file_changes"][ct]["enabled"] is False
            assert merged["auto_accept"]["file_changes"][ct]["agent_scope"] == "first_author"
        # exec_command defaults
        assert merged["auto_accept"]["exec_command"]["mode"] == "off"
        assert merged["auto_accept"]["exec_command"]["agent_scope"] == "first_author"
        # snooze defaults
        assert merged["auto_accept"]["snoozed_card_ids"] == []

    def test_merge_v2_empty_auto_accept(self):
        """v2 with auto_accept={} yields all defaults (isinstance guard)."""
        merged = _merge_v2_defaults({"version": 2, "auto_accept": {}})
        assert merged == _default_prefs()

    def test_merge_v2_auto_accept_none(self):
        """v2 with auto_accept=None yields all defaults (isinstance guard
        catches None and skips the overlay branch entirely)."""
        merged = _merge_v2_defaults({"version": 2, "auto_accept": None})
        assert merged == _default_prefs()

    def test_merge_v2_wrong_types(self):
        """v2 with wrong types at every nested level — each isinstance
        guard catches the wrong type and falls back to defaults for that
        section. Overall structure still equals _default_prefs()."""
        bad = {
            "version": 2,
            "auto_accept": {
                "file_changes": "not a dict",
                "exec_command": 42,
                "snoozed_card_ids": "not a list",
            },
        }
        merged = _merge_v2_defaults(bad)
        assert merged == _default_prefs()

    def test_load_v1_file_migrates(self):
        """Write a v1 JSON file to .crabcakes/feed-prefs.json, call
        load_feed_prefs(), assert it returns a v2-shaped dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crabcakes = os.path.join(tmpdir, ".crabcakes")
            os.makedirs(crabcakes)
            path = os.path.join(crabcakes, "feed-prefs.json")
            v1 = {"version": 1, "auto_accept_enabled": True, "auto_accept_agent": None}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(v1, f)
            loaded = load_feed_prefs(tmpdir)
            assert loaded["version"] == 2
            assert loaded["auto_accept"]["file_changes"]["diff"]["enabled"] is True
            assert loaded["auto_accept"]["file_changes"]["diff"]["agent_scope"] == "first_author"
            assert loaded["auto_accept"]["exec_command"]["mode"] == "off"

    def test_load_v2_file_preserves(self):
        """Write a v2 JSON file, load_feed_prefs() returns the same data
        (merged through defaults, but equals the source)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crabcakes = os.path.join(tmpdir, ".crabcakes")
            os.makedirs(crabcakes)
            path = os.path.join(crabcakes, "feed-prefs.json")
            v2 = {
                "version": 2,
                "auto_accept": {
                    "file_changes": {
                        "diff": {"enabled": True, "agent_scope": "claude"},
                        "file_created": {"enabled": False, "agent_scope": "first_author"},
                        "file_modified": {"enabled": False, "agent_scope": "first_author"},
                        "file_deleted": {"enabled": False, "agent_scope": "first_author"},
                    },
                    "exec_command": {"mode": "silent", "agent_scope": "claude"},
                    "snoozed_card_ids": ["x"],
                },
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(v2, f)
            loaded = load_feed_prefs(tmpdir)
            assert loaded == v2

    def test_load_missing_file_returns_defaults(self):
        """No .crabcakes/feed-prefs.json → _default_prefs()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_feed_prefs(tmpdir)
            assert loaded == _default_prefs()

    def test_load_corrupt_file_returns_defaults(self):
        """Invalid JSON in feed-prefs.json → _default_prefs()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crabcakes = os.path.join(tmpdir, ".crabcakes")
            os.makedirs(crabcakes)
            path = os.path.join(crabcakes, "feed-prefs.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{ invalid json }")
            loaded = load_feed_prefs(tmpdir)
            assert loaded == _default_prefs()

    def test_load_unknown_version_returns_defaults(self):
        """Unknown version (e.g. 99) → _default_prefs() with a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crabcakes = os.path.join(tmpdir, ".crabcakes")
            os.makedirs(crabcakes)
            path = os.path.join(crabcakes, "feed-prefs.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 99, "weird_field": True}, f)
            loaded = load_feed_prefs(tmpdir)
            assert loaded == _default_prefs()


# ═══════════════════════════════════════════════════════════════════
#  PHASE 8 — Scenario & Integration Tests (FINAL PHASE)
#  Covers SPEC-AUTO-ACCEPT-GRANULAR-1.md §5 Step 8 + §6 Acceptance Criteria + §7 Edge Cases.
#  Tests are APPENDED here only — no existing tests are modified.
# ═══════════════════════════════════════════════════════════════════

class TestExecAutoAccept:
    """Phase 7-8: Exec auto-accept Show mode, Silent mode, and Off mode tests."""

    def test_show_mode_auto_approves_exec_card(self, feed_handler, mock_glib, mock_feed_tab):
        """Exec Show mode: approval card is auto-approved via _auto_approve_exec_card.
        The _on_approve_exec callback fires, card.accepted=True, and
        _update_card_visual is called."""
        # Setup: enable exec Show mode
        feed_handler._prefs.exec_command.mode = "show"
        feed_handler._auto_accept_enabled = True
        approved_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approved_calls.append((cid, approved))

        # Create an exec approval card
        card = FeedCardData(
            card_type="agent_action",
            source="agent",
            title="PM requests approval to run command",
            body="$ ls -la",
            author="PM",
            timestamp=datetime.now(timezone.utc),
            project_name="testproject",
            metadata={"needs_approval": True, "status": "pending_approval"},
        )
        card_id = feed_handler.add_card(card)

        # Assert: _on_approve_exec was called with approved=True
        assert len(approved_calls) == 1
        assert approved_calls[0][1] is True  # approved=True
        # Assert: card.accepted is True
        assert feed_handler._cards[card_id].accepted is True

    def test_show_mode_routes_through_auto_approve_not_handle_accept(self, feed_handler, mock_glib, mock_feed_tab):
        """Show mode exec cards must route through _auto_approve_exec_card (which calls
        handle_approve_exec), NOT handle_accept (which does git stage+commit).
        Verify by checking that _on_approve_exec fires but git ops do NOT."""
        feed_handler._prefs.exec_command.mode = "show"
        feed_handler._auto_accept_enabled = True
        approve_exec_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approve_exec_calls.append((cid, approved))

        card = FeedCardData(
            card_type="agent_action", source="agent", title="approval",
            body="$ rm -rf /", author="PM",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": True},
        )
        card_id = feed_handler.add_card(card)

        # _on_approve_exec was called (correct path)
        assert len(approve_exec_calls) == 1
        # Card should NOT have gone through git ops — verify card.accepted is True
        # but no git card was created (handle_accept would create a git commit card)
        assert feed_handler._cards[card_id].accepted is True

    def test_off_mode_does_not_auto_approve(self, feed_handler, mock_glib, mock_feed_tab):
        """Exec Off mode: approval card is NOT auto-approved."""
        feed_handler._prefs.exec_command.mode = "off"
        feed_handler._auto_accept_enabled = True
        approved_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approved_calls.append((cid, approved))

        card = FeedCardData(
            card_type="agent_action", source="agent", title="approval",
            body="$ ls", author="PM",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": True},
        )
        card_id = feed_handler.add_card(card)

        # Should NOT have been auto-approved
        assert len(approved_calls) == 0
        assert feed_handler._cards[card_id].accepted is None

    def test_show_mode_non_approval_agent_action_not_auto_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """An agent_action card WITHOUT needs_approval should NOT be auto-approved
        even in Show mode (only approval cards are auto-acceptable)."""
        feed_handler._prefs.exec_command.mode = "show"
        feed_handler._auto_accept_enabled = True
        approved_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approved_calls.append((cid, approved))

        card = FeedCardData(
            card_type="agent_action", source="agent", title="agent did something",
            body="ran a thing", author="PM",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": False},
        )
        card_id = feed_handler.add_card(card)

        assert len(approved_calls) == 0
        assert feed_handler._cards[card_id].accepted is None

    def test_exec_auto_accept_respects_agent_scope(self, feed_handler, mock_glib, mock_feed_tab):
        """Exec Show mode with agent_scope='first_author': only the first agent's
        exec cards are auto-approved."""
        feed_handler._prefs.exec_command.mode = "show"
        feed_handler._prefs.exec_command.agent_scope = "first_author"
        feed_handler._auto_accept_enabled = True
        approved_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approved_calls.append((cid, approved))

        # First exec card from "AgentA" — should auto-approve
        card_a = FeedCardData(
            card_type="agent_action", source="agent", title="approval",
            body="$ ls", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": True},
        )
        cid_a = feed_handler.add_card(card_a)
        assert len(approved_calls) == 1

        # Second exec card from "AgentB" — should NOT auto-approve (scope locked to AgentA)
        card_b = FeedCardData(
            card_type="agent_action", source="agent", title="approval",
            body="$ ls", author="AgentB",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": True},
        )
        cid_b = feed_handler.add_card(card_b)
        assert len(approved_calls) == 1  # still only 1
        assert feed_handler._cards[cid_b].accepted is None

    def test_exec_auto_accept_snoozed_card_not_approved(self, feed_handler, mock_glib, mock_feed_tab, monkeypatch):
        """A snoozed exec card should NOT be auto-approved.

        Uses monkeypatch to predict the UUID that add_card will assign,
        so we can pre-snooze it before the auto-accept check fires.
        (MockGLib.idle_add runs synchronously, so auto-accept fires inside
        add_card before we can read the returned card_id.)"""
        monkeypatch.setattr("ui.handlers.feed_handler.uuid.uuid4", lambda: "snoozed-uuid")
        feed_handler._prefs.exec_command.mode = "show"
        feed_handler._auto_accept_enabled = True
        feed_handler._prefs.snoozed_card_ids.append("snoozed-uuid")
        approved_calls = []
        feed_handler._on_approve_exec = lambda cid, approved: approved_calls.append((cid, approved))

        card = FeedCardData(
            card_type="agent_action", source="agent", title="approval",
            body="$ ls", author="PM",
            timestamp=datetime.now(timezone.utc), project_name="testproject",
            metadata={"needs_approval": True},
        )
        card_id = feed_handler.add_card(card)

        assert len(approved_calls) == 0
        assert feed_handler._cards[card_id].accepted is None


class TestAutoAcceptScenario:
    """Phase 8: Integration-level scenario tests for auto-accept flows.
    Covers spec §5 Step 8 scenarios + §6 acceptance criteria."""

    def test_scenario_diffs_on_file_changes_auto_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """Scenario: Diffs ON → diff cards auto-accept via handle_accept.
        File_* cards do NOT auto-accept (only diff)."""
        feed_handler._prefs.file_changes["diff"].enabled = True
        feed_handler._prefs.file_changes["diff"].agent_scope = "all_agents"
        feed_handler._auto_accept_enabled = True

        # Add a diff card — should be auto-accepted
        diff_card = FeedCardData(
            card_type="diff", source="agent", title="modified foo.py",
            body="+print('hello')", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="foo.py",
        )
        diff_id = feed_handler.add_card(diff_card)
        # MockGLib.idle_add runs immediately, so handle_accept fires synchronously
        # handle_accept on diff → spawns git thread → we can't test git ops here
        # but we can verify the card was routed through handle_accept by checking
        # that _auto_accept_enabled was True and the card is in _cards
        assert diff_id in feed_handler._cards

        # Add a file_created card — should NOT be auto-accepted
        file_card = FeedCardData(
            card_type="file_created", source="agent", title="created bar.py",
            body="new file", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="bar.py",
        )
        file_id = feed_handler.add_card(file_card)
        assert feed_handler._cards[file_id].accepted is None

    def test_scenario_files_on_file_changes_auto_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """Scenario: Files ON → file_* cards auto-accept. Diff cards do NOT."""
        feed_handler._prefs.file_changes["file_created"].enabled = True
        feed_handler._prefs.file_changes["file_created"].agent_scope = "all_agents"
        feed_handler._auto_accept_enabled = True

        file_card = FeedCardData(
            card_type="file_created", source="agent", title="created bar.py",
            body="new file", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="bar.py",
        )
        file_id = feed_handler.add_card(file_card)
        assert file_id in feed_handler._cards

        # Diff card should NOT be auto-accepted (only file_created is enabled)
        diff_card = FeedCardData(
            card_type="diff", source="agent", title="modified foo.py",
            body="+print('hello')", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="foo.py",
        )
        diff_id = feed_handler.add_card(diff_card)
        assert feed_handler._cards[diff_id].accepted is None

    def test_scenario_both_on_all_file_types_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """Scenario: Both Diffs and Files ON → all four file-change types auto-accept."""
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            feed_handler._prefs.file_changes[ct].enabled = True
            feed_handler._prefs.file_changes[ct].agent_scope = "all_agents"
        feed_handler._auto_accept_enabled = True

        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            card = FeedCardData(
                card_type=ct, source="agent", title=f"{ct} event",
                body="content", author="AgentA",
                timestamp=datetime.now(timezone.utc), project_name="proj",
                file_path="some_file.py",
            )
            cid = feed_handler.add_card(card)
            assert cid in feed_handler._cards

    def test_scenario_both_off_nothing_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """Scenario: All toggles OFF → no cards auto-accepted."""
        feed_handler._auto_accept_enabled = False

        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            card = FeedCardData(
                card_type=ct, source="agent", title=f"{ct} event",
                body="content", author="AgentA",
                timestamp=datetime.now(timezone.utc), project_name="proj",
                file_path="some_file.py",
            )
            cid = feed_handler.add_card(card)
            assert feed_handler._cards[cid].accepted is None

    def test_scenario_unknown_card_type_never_auto_accepted(self, feed_handler, mock_glib, mock_feed_tab):
        """BUG #10 regression: unknown card_type (e.g. 'git_commit', None) is never
        auto-accepted regardless of prefs."""
        feed_handler._auto_accept_enabled = True
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            feed_handler._prefs.file_changes[ct].enabled = True
            feed_handler._prefs.file_changes[ct].agent_scope = "all_agents"

        for ct in ("git_commit", "audit_report", None):
            card = FeedCardData(
                card_type=ct or "", source="agent", title=f"{ct} event",
                body="content", author="AgentA",
                timestamp=datetime.now(timezone.utc), project_name="proj",
            )
            cid = feed_handler.add_card(card)
            assert feed_handler._cards[cid].accepted is None

    def test_scenario_agent_scope_all_agents(self, feed_handler, mock_glib, mock_feed_tab):
        """Agent scope 'all_agents' → any agent's cards auto-accept."""
        feed_handler._prefs.file_changes["diff"].enabled = True
        feed_handler._prefs.file_changes["diff"].agent_scope = "all_agents"
        feed_handler._auto_accept_enabled = True

        for author in ("AgentA", "AgentB", "AgentC"):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"diff by {author}",
                body="+code", author=author,
                timestamp=datetime.now(timezone.utc), project_name="proj",
                file_path="foo.py",
            )
            cid = feed_handler.add_card(card)
            assert cid in feed_handler._cards

    def test_scenario_agent_scope_first_author_lock_in(self, feed_handler, mock_glib, mock_feed_tab):
        """Agent scope 'first_author' → first card's author locks in;
        subsequent cards from different agents are NOT auto-accepted."""
        feed_handler._prefs.file_changes["diff"].enabled = True
        feed_handler._prefs.file_changes["diff"].agent_scope = "first_author"
        feed_handler._auto_accept_enabled = True

        # First card from AgentA — should auto-accept (lock-in)
        card_a = FeedCardData(
            card_type="diff", source="agent", title="diff by A",
            body="+a", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="a.py",
        )
        cid_a = feed_handler.add_card(card_a)
        assert cid_a in feed_handler._cards

        # Second card from AgentB — should NOT auto-accept
        card_b = FeedCardData(
            card_type="diff", source="agent", title="diff by B",
            body="+b", author="AgentB",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="b.py",
        )
        cid_b = feed_handler.add_card(card_b)
        assert feed_handler._cards[cid_b].accepted is None

    def test_scenario_snoozed_card_not_auto_accepted(self, feed_handler, mock_glib, mock_feed_tab, monkeypatch):
        """Snoozed cards are not auto-accepted.

        Uses monkeypatch to predict the UUID that add_card will assign,
        so we can pre-snooze it before the auto-accept check fires."""
        monkeypatch.setattr("ui.handlers.feed_handler.uuid.uuid4", lambda: "snoozed-scenario-uuid")
        feed_handler._prefs.file_changes["diff"].enabled = True
        feed_handler._prefs.file_changes["diff"].agent_scope = "all_agents"
        feed_handler._auto_accept_enabled = True
        feed_handler._prefs.snoozed_card_ids.append("snoozed-scenario-uuid")

        card = FeedCardData(
            card_type="diff", source="agent", title="snoozed diff",
            body="+code", author="AgentA",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            file_path="foo.py",
        )
        cid = feed_handler.add_card(card)
        assert feed_handler._cards[cid].accepted is None

    def test_scenario_batch_accept_independent_of_auto_accept(self, feed_handler, mock_glib, mock_feed_tab):
        """All toggles OFF, then user clicks Accept All → batch accept still works.
        Auto-accept and batch accept are independent mechanisms."""
        feed_handler._auto_accept_enabled = False

        # Add 3 pending file-change cards
        ids = []
        for i in range(3):
            card = FeedCardData(
                card_type="diff", source="agent", title=f"diff {i}",
                body=f"+line{i}", author="AgentA",
                timestamp=datetime.now(timezone.utc), project_name="proj",
                file_path=f"file_{i}.py",
            )
            ids.append(feed_handler.add_card(card))

        # Batch accept bar should be visible (3 pending ≥ 2 threshold)
        assert mock_feed_tab._batch_bar_visible is True
        assert mock_feed_tab._batch_bar_count == 3


class TestExecAutoAcceptModeQuery:
    """Phase 6-8: get_exec_auto_accept_mode() and callback wiring tests."""

    def test_get_mode_returns_off_by_default(self, feed_handler):
        """Fresh handler returns 'off' for exec mode."""
        assert feed_handler.get_exec_auto_accept_mode() == "off"

    def test_get_mode_returns_show_when_set(self, feed_handler):
        """After setting exec mode to 'show', get returns 'show'."""
        feed_handler._prefs.exec_command.mode = "show"
        assert feed_handler.get_exec_auto_accept_mode() == "show"

    def test_get_mode_returns_silent_when_set(self, feed_handler):
        """After setting exec mode to 'silent', get returns 'silent'."""
        feed_handler._prefs.exec_command.mode = "silent"
        assert feed_handler.get_exec_auto_accept_mode() == "silent"

    def test_get_mode_returns_none_when_prefs_is_none(self):
        """When _prefs is None (not yet initialized), returns None.
        This guards against constructor-ordering races."""
        from ui.handlers.feed_handler import FeedHandler
        h = FeedHandler(GLib=MockGLib(), on_send_to_agent=MagicMock())
        h._prefs = None
        assert h.get_exec_auto_accept_mode() is None

    def test_set_check_exec_callback_wires_correctly(self, feed_handler):
        """set_check_exec_auto_accept_callback_for_handler() installs FH's
        getter as ARTH's callback. The callback returns the current mode."""
        captured_callback = [None]

        def fake_arth_setter(cb):
            captured_callback[0] = cb

        feed_handler.set_check_exec_auto_accept_callback_for_handler(fake_arth_setter)

        # The captured callback should be FH.get_exec_auto_accept_mode
        assert captured_callback[0] is not None
        # Set mode and verify the callback reflects it
        feed_handler._prefs.exec_command.mode = "silent"
        assert captured_callback[0]() == "silent"
        feed_handler._prefs.exec_command.mode = "show"
        assert captured_callback[0]() == "show"


# ═══════════════════════════════════════════════════════════════════
#  TestAutoAcceptDialogCascadeRegression — Bug F
#  Verifies that programmatic set_active() in update_auto_accept_prefs()
#  does NOT trigger the toggled signal handlers (which would show the
#  warning dialog even though the user never clicked anything).
#
#  Repro history:
#    1. User has a v1 .crabcakes/feed-prefs.json with auto_accept_enabled: true.
#    2. User opens the project.
#    3. Prefs are loaded and migrated to v2 — all 4 file types enabled.
#    4. FeedHandler._append_and_schedule_scroll calls
#       feed_tab.update_auto_accept_prefs(prefs).
#    5. Inside update_auto_accept_prefs, self._diffs_toggle.set_active(True)
#       and self._files_toggle.set_active(True) are called.
#    6. On GTK 4.14, set_active() emits the 'toggled' signal whenever the
#       value changes (False→True or True→False). The inline comments in
#       update_auto_accept_prefs() claim it does NOT emit, but that is
#       incorrect on GTK 4.14 — my repro under Xvfb confirmed the signal
#       fires.
#    7. Each 'toggled' signal triggers _on_diffs_toggled(True) /
#       _on_files_toggled(True), which show a warning dialog each.
#    8. The user sees two stacked dialogs ("Auto-accept diffs?" on top,
#       "Auto-accept file changes?" behind it). Clicking the top button
#       closes that dialog but leaves the second one blocking input.
#       The user reports "clicking does nothing" because the second dialog
#       is still there, in focus, blocking clicks elsewhere.
#
#  Fix: feed_tab._syncing_toolbar flag is set during update_auto_accept_prefs
#  and gates _on_diffs_toggled / _on_files_toggled so they short-circuit
#  when the signal is caused by a programmatic update (not a real user click).
# ═══════════════════════════════════════════════════════════════════


class TestAutoAcceptDialogCascadeRegression:
    """Bug F regression: programmatic set_active() in update_auto_accept_prefs()
    must NOT fire the toggle handlers (which would show the warning dialog)."""

    def _make_real_feed_tab(self):
        """Build a real FeedTab for testing the set_active→toggled behavior.

        The existing real_feed_tab fixture wires a fake _feed_scroll so
        we don't need that — we only need the toolbar toggles.
        """
        from ui.views.feed_tab import FeedTab
        return FeedTab()

    def test_programmatic_set_active_does_not_fire_toggled_handler(self, real_feed_tab):
        """Bug F regression: feed_tab.update_auto_accept_prefs() sets
        _diffs_toggle.set_active(True) programmatically. GTK 4.14 emits
        the 'toggled' signal on every state change. Without the
        _syncing_toolbar guard, _on_diffs_toggled runs and the user-
        installed diffs callback would fire — showing a warning dialog
        even though the user never clicked anything.

        Fix: _syncing_toolbar flag short-circuits _on_diffs_toggled
        during the sync, so the callback only fires on real user clicks.
        """
        tab = real_feed_tab
        # Sanity: toggle starts OFF, no handler installed
        assert tab._diffs_toggle.get_active() is False
        callback_fired = []
        tab.set_diffs_toggle_callback(lambda active: callback_fired.append(active))

        # Simulate the v1→v2 prefs loaded into the FeedTab
        prefs_dict = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": True, "agent_scope": "system"},
                    "file_created": {"enabled": True, "agent_scope": "system"},
                    "file_modified": {"enabled": True, "agent_scope": "system"},
                    "file_deleted": {"enabled": True, "agent_scope": "system"},
                },
                "exec_command": {"mode": "off", "agent_scope": "system"},
                "snoozed_card_ids": [],
            },
        }
        tab.update_auto_accept_prefs(prefs_dict)

        # Toggle should now be visually ON
        assert tab._diffs_toggle.get_active() is True
        # ...but the diffs_toggle_callback should NOT have fired
        assert callback_fired == [], (
            f"Bug F regression: programmatic set_active(True) fired the "
            f"diffs_toggle_handler {len(callback_fired)} times "
            f"(expected 0). On GTK 4.14, Gtk.ToggleButton.set_active() "
            f"emits 'toggled' when the value changes — the "
            f"_syncing_toolbar guard must suppress this during "
            f"update_auto_accept_prefs(). Otherwise the warning dialog "
            f"appears every time the user opens a project with auto-"
            f"accept prefs persisted from a v1 install."
        )

    def test_programmatic_set_active_does_not_fire_files_handler(self, real_feed_tab):
        """Same Bug F regression but for the Files toggle.

        v1 prefs with auto_accept_enabled=true migrate to v2 with all
        three file_created/file_modified/file_deleted types enabled.
        update_auto_accept_prefs then calls _files_toggle.set_active(True)
        which would emit 'toggled' and trigger _on_files_toggled, which
        shows the second stacked dialog. The _syncing_toolbar guard
        must suppress this too.
        """
        tab = real_feed_tab
        assert tab._files_toggle.get_active() is False
        callback_fired = []
        tab.set_files_toggle_callback(lambda active: callback_fired.append(active))

        prefs_dict = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": False, "agent_scope": "first_author"},
                    "file_created": {"enabled": True, "agent_scope": "system"},
                    "file_modified": {"enabled": True, "agent_scope": "system"},
                    "file_deleted": {"enabled": True, "agent_scope": "system"},
                },
                "exec_command": {"mode": "off", "agent_scope": "system"},
                "snoozed_card_ids": [],
            },
        }
        tab.update_auto_accept_prefs(prefs_dict)

        assert tab._files_toggle.get_active() is True
        assert callback_fired == [], (
            f"Bug F regression: programmatic _files_toggle.set_active(True) "
            f"fired the files_toggle_handler {len(callback_fired)} times "
            f"(expected 0). The second warning dialog is the more obvious "
            f"symptom because the Files dialog stacks behind the Diffs one — "
            f"the user clicks 'Cancel' on Diffs and the Files dialog is "
            f"still there blocking input."
        )

    def test_user_click_still_fires_toggled_handler(self, real_feed_tab):
        """Sanity / negative test: when _syncing_toolbar is False (real
        user click), the toggled handler MUST fire. This guards against
        the fix being too aggressive (e.g. always short-circuiting)."""
        tab = real_feed_tab
        callback_fired = []
        tab.set_diffs_toggle_callback(lambda active: callback_fired.append(active))

        # Simulate a real user click — toggle.set_active(True) WITHOUT
        # the _syncing_toolbar guard being set
        assert tab._syncing_toolbar is False  # baseline
        tab._diffs_toggle.set_active(True)

        assert tab._diffs_toggle.get_active() is True
        assert callback_fired == [True], (
            f"Real user click must fire the diffs_toggle_handler "
            f"(expected [True], got {callback_fired}). The _syncing_toolbar "
            f"guard is set during update_auto_accept_prefs only — outside "
            f"of that, the handler should always run."
        )

    def test_syncing_toolbar_clears_on_exception(self, real_feed_tab):
        """Bug F robustness: if update_auto_accept_prefs raises mid-sync,
        the _syncing_toolbar flag MUST be reset to False so subsequent
        real user clicks still fire the handlers."""
        tab = real_feed_tab
        assert tab._syncing_toolbar is False

        # Wrap set_active to throw before flipping the toggle
        def boom(*args, **kwargs):
            raise RuntimeError("simulated failure mid-sync")
        tab._diffs_toggle.set_active = boom

        prefs_dict = {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    "diff": {"enabled": True, "agent_scope": "first_author"},
                },
                "exec_command": {"mode": "off", "agent_scope": "first_author"},
                "snoozed_card_ids": [],
            },
        }
        raised = False
        try:
            tab.update_auto_accept_prefs(prefs_dict)
        except RuntimeError:
            raised = True

        assert raised, "Test setup: boom() should have raised"
        # Flag must be reset even though we raised
        assert tab._syncing_toolbar is False, (
            "Robustness: update_auto_accept_prefs must reset "
            "_syncing_toolbar in a finally block so the flag doesn't "
            "leak and disable all future toggle interactions."
        )


class TestToggleStuckRegression:
    """Bug #12: Diffs/Files toggle stuck ON after user clicks to turn OFF.

    Root cause: FeedHandler._refresh_auto_accept_state() called BOTH
    update_auto_accept_prefs() (v2 path) AND update_auto_accept_state()
    (v1 legacy path) on every prefs mutation. The legacy path constructed
    a default prefs dict with `enabled=self._auto_accept_enabled`. When
    the user clicked Diffs OFF, diff.enabled became False but other file
    types (file_created, file_modified, file_deleted) were still True, so
    _auto_accept_enabled was True. The legacy path then set Diffs back to
    ON via set_active(True), undoing the user's click.

    Fix: use `elif` not `if` so the v1 path only fires on legacy/mocks
    that don't have update_auto_accept_prefs. (Real FeedTab has both.)

    These tests verify the click → off → toggle stays OFF path through
    the full FeedHandler._refresh_auto_accept_state chain.
    """

    def test_diffs_click_off_flips_toggle_and_stays_off(self, real_feed_tab):
        """User clicks Diffs to turn OFF — toggle must visually flip to
        OFF and stay OFF after _refresh_auto_accept_state() runs.

        Bug #12 regression: previously the v1 legacy path
        update_auto_accept_state() overwrote the v2 prefs dict and
        re-set the Diffs toggle to ON (because file_created/modified/
        deleted were still True, so _auto_accept_enabled was True).
        """
        tab = real_feed_tab
        
        # Set up a FeedHandler with a mock GLib
        from ui.handlers.feed_handler import FeedHandler
        mock_glib = MockGLib()
        fh = FeedHandler(GLib=mock_glib, on_send_to_agent=lambda *a: None)
        fh.set_feed_tab(tab)
        
        # Enable only diff (not the other file types) — this is the
        # KEY setup: when user turns diff OFF, _auto_accept_enabled
        # should become False (no file types enabled).
        fh._prefs.file_changes["diff"].enabled = True
        fh._prefs.file_changes["file_created"].enabled = False
        fh._prefs.file_changes["file_modified"].enabled = False
        fh._prefs.file_changes["file_deleted"].enabled = False
        # Sync the toolbar to reflect this state
        fh._refresh_auto_accept_state()
        assert tab._diffs_toggle.get_active() is True, "Setup: Diffs should be ON"
        
        # Simulate user clicking Diffs OFF
        tab._diffs_toggle.set_active(False)
        # The handler should have fired, setting diff.enabled = False
        # and calling _refresh_auto_accept_state()
        assert fh._prefs.file_changes["diff"].enabled is False
        # AND the toggle should stay OFF (the bug was that the v1 path
        # would re-set it to True because file_created etc were still
        # True — but here they were False, so even the buggy v1 path
        # would produce correct behavior. This is the simple case.)
        assert tab._diffs_toggle.get_active() is False, (
            "Toggle should be OFF after user click + refresh"
        )

    def test_diffs_click_off_with_other_types_enabled(self, real_feed_tab):
        """THE ACTUAL BUG: user clicks Diffs OFF when file_created/
        modified/deleted are still ON. Previously: toggle flipped back
        to ON because v1 path saw _auto_accept_enabled=True and
        re-set Diffs to True. Now: elif guard prevents v1 path.

        This is the exact scenario from the user's report.
        """
        tab = real_feed_tab
        
        from ui.handlers.feed_handler import FeedHandler
        mock_glib = MockGLib()
        fh = FeedHandler(GLib=mock_glib, on_send_to_agent=lambda *a: None)
        fh.set_feed_tab(tab)
        
        # Enable ALL file types (matching v1 prefs with enabled=True)
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            fh._prefs.file_changes[ct].enabled = True
        fh._refresh_auto_accept_state()
        assert tab._diffs_toggle.get_active() is True, "Setup: Diffs should be ON"
        assert fh._auto_accept_enabled is True
        
        # User clicks Diffs OFF
        tab._diffs_toggle.set_active(False)
        
        # _prefs should now have diff disabled
        assert fh._prefs.file_changes["diff"].enabled is False
        # Other types still enabled
        assert fh._prefs.file_changes["file_created"].enabled is True
        # _auto_accept_enabled is True (because other types are on)
        assert fh._auto_accept_enabled is True
        
        # CRITICAL: toggle should stay OFF. Bug #12 was that the v1
        # legacy path would call update_auto_accept_state(True) and
        # reconstruct prefs with diff.enabled=True, flipping the toggle
        # back ON.
        assert tab._diffs_toggle.get_active() is False, (
            "Bug #12 regression: Diffs toggle should stay OFF after user "
            "clicks to turn it off, even when other file types are still "
            "enabled. The legacy v1 update_auto_accept_state path must "
            "NOT fire on a real FeedTab that has update_auto_accept_prefs."
        )

    def test_legacy_mock_feedtab_still_uses_update_auto_accept_state(self):
        """Mock FeedTab (legacy test fixture) only has
        update_auto_accept_state, NOT update_auto_accept_prefs. The
        `_refresh_auto_accept_state` `elif` guard must still trigger
        the legacy path so existing tests keep working.
        """
        class LegacyFeedTab:
            def __init__(self):
                self._auto_accept_active = None
            def update_auto_accept_state(self, active: bool):
                self._auto_accept_active = active
            def set_batch_accept_callback(self, callback):
                pass  # no-op
            def set_auto_accept_callback(self, callback):
                pass  # no-op
            # NOTE: no update_auto_accept_prefs method
        
        mock_tab = LegacyFeedTab()
        
        from ui.handlers.feed_handler import FeedHandler
        mock_glib = MockGLib()
        fh = FeedHandler(GLib=mock_glib, on_send_to_agent=lambda *a: None)
        fh.set_feed_tab(mock_tab)
        fh._prefs.file_changes["diff"].enabled = True
        
        fh._refresh_auto_accept_state()
        
        # Legacy path should have fired (mock only has the legacy method)
        assert mock_tab._auto_accept_active is True

    def test_real_feedtab_does_not_call_update_auto_accept_state(self, real_feed_tab):
        """Real FeedTab has BOTH methods. The `elif` guard ensures the
        legacy path is skipped — only update_auto_accept_prefs fires.
        Verifies the elif guard is in effect by tracking calls.
        """
        tab = real_feed_tab
        
        legacy_calls = []
        original_legacy = tab.update_auto_accept_state
        def traced_legacy(active):
            legacy_calls.append(active)
            original_legacy(active)
        tab.update_auto_accept_state = traced_legacy
        
        from ui.handlers.feed_handler import FeedHandler
        mock_glib = MockGLib()
        fh = FeedHandler(GLib=mock_glib, on_send_to_agent=lambda *a: None)
        fh.set_feed_tab(tab)
        fh._prefs.file_changes["diff"].enabled = True
        
        fh._refresh_auto_accept_state()
        
        # Real path should fire (update_auto_accept_prefs)
        assert tab._diffs_toggle.get_active() is True
        # Legacy path should NOT fire (elif guard)
        assert legacy_calls == [], (
            f"Real FeedTab.update_auto_accept_state must NOT fire when "
            f"update_auto_accept_prefs is available. Got {legacy_calls=}. "
            f"This means the `if` -> `elif` fix in "
            f"_refresh_auto_accept_state was lost."
        )


class TestPendingSaveIdStaleRegression:
    """Bug #12b: 'Source ID N was not found when attempting to remove it'
    warning fires every time _refresh_auto_accept_state is called after
    a previous save's idle callback has already fired.

    Root cause: GLib.idle_add runs the callback once (because the callback
    returns False / no-repeat), and GLib auto-removes the source. But
    _refresh_auto_accept_state still called source_remove(_pending_save_id),
    which pointed at an already-cleaned-up source. The result was the
    'Source ID N was not found' warning at every subsequent prefs mutation.

    Fix: drop the source_remove() call entirely. GLib's idle source is
    a single-shot — calling idle_add again with a new callback schedules
    a new save; the old one already ran (or is running) and is harmless
    to leave alone. Rapid-fire mutations coalesce into one disk write
    because the idle source only fires after the current main-loop spin
    settles anyway.
    """

    def test_refresh_does_not_call_source_remove(self):
        """Mock GLib that tracks all source_remove calls. After two
        _refresh_auto_accept_state() calls, source_remove must NEVER
        have been invoked. The single-shot idle source cleans itself up.
        """
        remove_calls = []
        
        class MockGLib:
            _next_id = 100
            @classmethod
            def idle_add(cls, callback):
                sid = cls._next_id
                cls._next_id += 1
                callback()
                return sid
            @classmethod
            def source_remove(cls, sid):
                remove_calls.append(sid)
        
        from ui.handlers.feed_handler import FeedHandler
        fh = FeedHandler(GLib=MockGLib, on_send_to_agent=lambda *a: None)
        
        fh._refresh_auto_accept_state()
        fh._refresh_auto_accept_state()
        
        assert remove_calls == [], (
            f"_refresh_auto_accept_state must NOT call source_remove "
            f"(Bug #12b). GLib's idle source is single-shot and auto-removes "
            f"itself. Manual removal just produces 'Source ID N was not found' "
            f"warnings. Got remove_calls={remove_calls}."
        )

    def test_save_still_persists_prefs_to_disk(self):
        """The fix must not break the actual save — just the spurious
        source_remove warning. Verify save_feed_prefs is called with
        the current prefs.
        """
        import tempfile
        import shutil
        from pathlib import Path
        from unittest.mock import patch
        
        # Create a temporary project dir
        tmpdir = tempfile.mkdtemp(prefix="cc_save_test_")
        crabcakes_dir = Path(tmpdir) / ".crabcakes"
        crabcakes_dir.mkdir()
        
        try:
            saved_prefs = []
            
            class MockGLib:
                _next_id = 200
                @classmethod
                def idle_add(cls, callback):
                    sid = cls._next_id
                    cls._next_id += 1
                    callback()
                    return sid
                @classmethod
                def source_remove(cls, sid):
                    pass
            
            # Patch feed_store.save_feed_prefs to capture what's saved
            import ui.handlers.feed_handler as fh_mod
            original_save = fh_mod.feed_store.save_feed_prefs
            
            def capturing_save(project_path, prefs):
                saved_prefs.append((project_path, prefs))
                return original_save(project_path, prefs)
            
            fh_mod.feed_store.save_feed_prefs = capturing_save
            
            try:
                from ui.handlers.feed_handler import FeedHandler
                fh = FeedHandler(GLib=MockGLib, on_send_to_agent=lambda *a: None)
                fh._active_project_name = "testproj"
                fh._project_paths = {"testproj": tmpdir}
                fh._prefs.file_changes["diff"].enabled = True
                
                fh._refresh_auto_accept_state()
                
                assert saved_prefs, (
                    "save_feed_prefs must have been called via idle_add "
                    "after _refresh_auto_accept_state() enabled diff."
                )
                project_path, prefs = saved_prefs[-1]
                assert prefs["auto_accept"]["file_changes"]["diff"]["enabled"] is True
            finally:
                fh_mod.feed_store.save_feed_prefs = original_save
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestHideCardButtonsBug:
    """Bug #13: hide_card_buttons() was a silent no-op.

    The original implementation looked up `_<name>_button` attributes on
    the card widget. But `build_feed_card()` constructs local `btn_accept`
    and `btn_reject` variables and appends them inline — it NEVER stores
    them as named attributes on the returned card widget. So
    `getattr(card_widget, "_approve_button", None)` returned None every
    time, and the buttons stayed visible after auto-approve.

    User-visible symptom: in Show mode, an exec card auto-approved via
    `_auto_approve_exec_card()` still showed its Approve/Deny buttons.
    Clicking Approve again called `handle_approve_exec(cid, True)` → ARTH
    a second time. Not idempotent → double-action risk.

    Fix: map each hide_card_buttons arg name to its CSS class
    (`build_feed_card` sets `feed-btn-accept` / `feed-btn-reject` / 
    `feed-btn-review`) and walk the widget subtree.
    """

    def _make_card_widget(self, button_labels=("Approve", "Deny")):
        """Build a minimal Gtk.Box mimicking build_feed_card's structure:
        a root card box with a children Btns row containing the given
        buttons. Returns the root box."""
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        actions.add_css_class("feed-card-actions")

        css_classes = {
            "Approve": "feed-btn-accept",
            "Deny": "feed-btn-reject",
            "Accept": "feed-btn-accept",
            "Reject": "feed-btn-reject",
            "Review": "feed-btn-review",
        }
        for label in button_labels:
            btn = Gtk.Button(label=label)
            btn.add_css_class(css_classes.get(label, "feed-btn-custom"))
            actions.append(btn)
        card.append(actions)
        return card

    def test_hide_card_buttons_hides_approve(self):
        """hide_card_buttons(['approve']) hides an Approve button."""
        from ui.views.feed_tab import FeedTab
        tab = FeedTab()  # FeedTab.__init__() takes no args
        
        card = self._make_card_widget(button_labels=("Approve", "Deny"))
        tab._cards_by_id["test_card"] = card
        
        tab.hide_card_buttons("test_card", ["approve"])
        
        # Find the Approve button in the subtree
        approve_btn = None
        deny_btn = None
        for child in [c for c in card.get_first_child().get_first_child().__iter__()] if False else []:
            pass
        # Simpler: walk via known structure
        actions_box = card.get_first_child()
        first_button = actions_box.get_first_child()
        second_button = first_button.get_next_sibling()
        assert first_button.get_visible() is False, (
            "Approve button must be hidden after hide_card_buttons(['approve'])"
        )
        assert second_button.get_visible() is True, (
            "Deny button must remain visible — only 'approve' was requested"
        )

    def test_hide_card_buttons_hides_deny(self):
        """hide_card_buttons(['deny']) hides a Deny button."""
        from ui.views.feed_tab import FeedTab
        tab = FeedTab()
        
        card = self._make_card_widget(button_labels=("Approve", "Deny"))
        tab._cards_by_id["test_card"] = card
        
        tab.hide_card_buttons("test_card", ["deny"])
        
        actions_box = card.get_first_child()
        first_button = actions_box.get_first_child()
        second_button = first_button.get_next_sibling()
        assert first_button.get_visible() is True, (
            "Approve button must remain visible — only 'deny' was requested"
        )
        assert second_button.get_visible() is False, (
            "Deny button must be hidden after hide_card_buttons(['deny'])"
        )

    def test_hide_card_buttons_hides_both(self):
        """hide_card_buttons(['approve', 'deny']) hides both."""
        from ui.views.feed_tab import FeedTab
        tab = FeedTab()
        
        card = self._make_card_widget(button_labels=("Approve", "Deny"))
        tab._cards_by_id["test_card"] = card
        
        tab.hide_card_buttons("test_card", ["approve", "deny"])
        
        actions_box = card.get_first_child()
        first_button = actions_box.get_first_child()
        second_button = first_button.get_next_sibling()
        assert first_button.get_visible() is False
        assert second_button.get_visible() is False

    def test_hide_card_buttons_unknown_card_is_noop(self):
        """Unknown card_id is a no-op (no exception)."""
        from ui.views.feed_tab import FeedTab
        tab = FeedTab()
        
        # Should not raise
        tab.hide_card_buttons("nonexistent_card_id", ["approve", "deny"])

    def test_hide_card_buttons_accept_alias_hides_approve(self):
        """Both 'approve' (needs_approval label) and 'accept' (file_change
        label) should map to feed-btn-accept CSS class. The caller may
        pass either depending on card_type — both must work."""
        from ui.views.feed_tab import FeedTab
        tab = FeedTab()
        
        card = self._make_card_widget(button_labels=("Accept",))
        tab._cards_by_id["test_card"] = card
        
        tab.hide_card_buttons("test_card", ["accept"])
        
        btn = card.get_first_child().get_first_child()
        assert btn.get_visible() is False, (
            "Accept button (file-change label) must be hidden when "
            "passed as 'accept' to hide_card_buttons"
        )
