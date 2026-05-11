# tests/test_collab_manager.py
# Unit tests for ui/handlers/collab_manager.py
#
# Principles:
#   - Pure Python — mock GLib, feed_handler, agent_runtime_handler, gw, agent_mgr
#   - Test thread lifecycle, convergence, routing, edge cases
#   - No GTK, no network — fake objects instead

import pytest
import sys
sys.path.insert(0, '.')

from ui.handlers.collab_manager import CollabManager, A2AThread


# ═══════════════════════════════════════════════════════════════════
#  Fake Collaborators
# ═══════════════════════════════════════════════════════════════════

class FakeGLib:
    """Fake GLib that just calls the function immediately (no idle_add)."""
    @staticmethod
    def idle_add(fn, *args, **kwargs):
        fn(*args, **kwargs)


class FakeGW:
    def __init__(self, connected: bool = True):
        self._connected = connected
        self.sent: list[tuple[str, str]] = []

    def is_connected(self) -> bool:
        return self._connected

    def send_message(self, sk: str, text: str) -> None:
        self.sent.append((sk, text))


class FakeAgentMgr:
    def __init__(self, key_to_name: dict[str, str] = None):
        self._k2n = key_to_name or {}

    def get_name(self, sk: str) -> str:
        return self._k2n.get(sk, "")


class FakeAgentRuntimeHandler:
    def __init__(self, special_agents: dict[str, str] = None):
        self._special = special_agents or {}
        self.sent: list[tuple[str, str]] = []

    def get_special_agents(self) -> dict[str, str]:
        return dict(self._special)

    def send_to_special_agent(self, sk: str, text: str) -> None:
        self.sent.append((sk, text))


class FakeFeedHandler:
    """Fake FeedHandler that records cards instead of rendering them."""
    def __init__(self):
        self.cards = []

    def add_card(self, card) -> None:
        self.cards.append(card)


class FakeMentionResolution:
    """Fake MentionResolution for detect_a2a_mention tests."""
    def __init__(self, target_sk: str | None = None, is_broadcast: bool = False,
                 error: str | None = None):
        self.target_session_key = target_sk
        self.is_broadcast = is_broadcast
        self.error = error


class FakeCommandHandler:
    """Fake CommandHandler for detect_a2a_mention static method."""
    def __init__(self, resolution):
        self._resolution = resolution

    def resolve_inline_mention(self, text: str, sk: str = ""):
        return self._resolution


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def empty_manager():
    """CollabManager with no collaborators wired."""
    return CollabManager(GLib=FakeGLib, feed_handler=None)


@pytest.fixture
def fully_wired():
    """CollabManager with all collaborators wired."""
    gw = FakeGW()
    am = FakeAgentMgr({"agent:qtr:1": "QTR", "agent:debugger:1": "Debugger"})
    arh = FakeAgentRuntimeHandler({"special:coder": "Coder", "special:debugger": "Debugger"})
    fh = FakeFeedHandler()
    mgr = CollabManager(
        GLib=FakeGLib,
        feed_handler=fh,
        agent_runtime_handler=arh,
        gw=gw,
        agent_mgr=am,
    )
    return {"manager": mgr, "gw": gw, "am": am, "arh": arh, "fh": fh}


# ═══════════════════════════════════════════════════════════════════
#  Thread ID Construction
# ═══════════════════════════════════════════════════════════════════

class TestThreadIdConstruction:
    def test_deterministic_thread_id(self):
        tid1 = CollabManager._build_thread_id("proj", "sk1", "sk2")
        tid2 = CollabManager._build_thread_id("proj", "sk1", "sk2")
        assert tid1 == tid2
        assert tid1 == "a2a:proj:sk1:sk2"

    def test_order_matters(self):
        tid1 = CollabManager._build_thread_id("proj", "sk1", "sk2")
        tid2 = CollabManager._build_thread_id("proj", "sk2", "sk1")
        assert tid1 != tid2
        assert tid1 == "a2a:proj:sk1:sk2"
        assert tid2 == "a2a:proj:sk2:sk1"

    def test_different_projects_different_ids(self):
        tid1 = CollabManager._build_thread_id("proj1", "sk1", "sk2")
        tid2 = CollabManager._build_thread_id("proj2", "sk1", "sk2")
        assert tid1 != tid2


# ═══════════════════════════════════════════════════════════════════
#  start_relay — core lifecycle
# ═══════════════════════════════════════════════════════════════════

class TestStartRelay:
    def test_creates_thread_and_returns_id(self, fully_wired):
        mgr = fully_wired["manager"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "How do I parse this?")
        assert tid is not None
        assert tid.startswith("a2a:proj:")

    def test_posts_intent_card(self, fully_wired):
        mgr = fully_wired["manager"]
        fh = fully_wired["fh"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Token validation question")
        assert len(fh.cards) == 1
        assert fh.cards[0].card_type == "agent_action"
        assert "Consulting @Coder" in fh.cards[0].title
        assert "Initiated by @QTR" in fh.cards[0].body

    def test_sends_relay_to_special_agent(self, fully_wired):
        mgr = fully_wired["manager"]
        arh = fully_wired["arh"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Token format?")
        assert len(arh.sent) == 1
        sk, text = arh.sent[0]
        assert sk == "special:coder"
        assert "[A2A relay from QTR in proj]" in text

    def test_sends_relay_to_gateway_agent(self, fully_wired):
        mgr = fully_wired["manager"]
        gw = fully_wired["gw"]
        mgr.start_relay("proj", "special:coder", "agent:qtr:1", "Question for QTR")
        assert len(gw.sent) == 1
        sk, text = gw.sent[0]
        assert sk == "agent:qtr:1"
        assert "[A2A relay from Coder in proj]" in text

    def test_adds_target_to_pending_relays(self, fully_wired):
        mgr = fully_wired["manager"]
        assert not mgr.is_pending_relay("special:coder")
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Question")
        assert mgr.is_pending_relay("special:coder")

    def test_duplicate_thread_returns_none(self, fully_wired):
        mgr = fully_wired["manager"]
        tid1 = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q1")
        tid2 = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q2")
        assert tid1 is not None
        assert tid2 is None  # thread already active


# ═══════════════════════════════════════════════════════════════════
#  start_relay — offline gateway
# ═══════════════════════════════════════════════════════════════════

class TestStartRelayOfflineGateway:
    def test_offline_gateway_silently_skips_send(self):
        gw = FakeGW(connected=False)
        arh = FakeAgentRuntimeHandler({"special:coder": "Coder"})
        fh = FakeFeedHandler()
        mgr = CollabManager(
            GLib=FakeGLib,
            feed_handler=fh,
            agent_runtime_handler=arh,
            gw=gw,
        )
        # Target is gateway agent but gateway is offline
        tid = mgr.start_relay("proj", "agent:qtr:1", "agent:offline:99", "Offline question")
        # Thread created, intent card posted, but relay silently skipped
        assert tid is not None
        assert len(fh.cards) == 1
        assert len(gw.sent) == 0


# ═══════════════════════════════════════════════════════════════════
#  capture_response
# ═══════════════════════════════════════════════════════════════════

class TestCaptureResponse:
    def test_appends_to_responses_and_increments_turn(self, fully_wired):
        mgr = fully_wired["manager"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert len(mgr._threads) == 1

        mgr.capture_response("special:coder", "Answer from Coder")
        thread = list(mgr._threads.values())[0]
        assert len(thread.responses) == 1
        assert thread.turn == 1
        assert thread.responses[0]["text"] == "Answer from Coder"

    def test_ignores_unknown_session_key(self, empty_manager):
        # Should not raise — unknown session key is silently ignored
        empty_manager.capture_response("unknown:sk", "some text")

    def test_ignores_inactive_thread(self, fully_wired):
        mgr = fully_wired["manager"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        mgr.close_thread(tid)
        # Thread is now inactive — capture should be no-op
        mgr.capture_response("special:coder", "Should be ignored")


# ═══════════════════════════════════════════════════════════════════
#  capture_response — convergence (hard wall at turn >= 15)
# ═══════════════════════════════════════════════════════════════════

class TestCaptureResponseConvergence:
    def test_turn_15_always_closes(self, fully_wired):
        mgr = fully_wired["manager"]
        fh = fully_wired["fh"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")

        # Simulate 15 turns — hard wall must close regardless of should_stop
        for i in range(15):
            mgr.capture_response("special:coder", f"Response {i+1}")

        # Verify closed
        thread = list(mgr._threads.values())[0]
        assert not thread.active
        # Closing card posted (intent + close = 2 cards)
        assert len(fh.cards) == 2
        assert fh.cards[1].title == "Consultation complete"


# ═══════════════════════════════════════════════════════════════════
#  capture_response — relay back to initiator
# ═══════════════════════════════════════════════════════════════════

class TestCaptureResponseRelayBack:
    def test_relays_response_back_to_initiator_when_not_converged(self, fully_wired):
        mgr = fully_wired["manager"]
        arh = fully_wired["arh"]
        gw = fully_wired["gw"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")

        # Clear sent from start_relay
        arh.sent.clear()
        gw.sent.clear()

        # Capture target's first response (turn 1 — should relay back to initiator)
        mgr.capture_response("special:coder", "Coder's answer")

        # Initiator is a gateway agent (agent:qtr:1) → relay goes via gw, not arh
        assert len(gw.sent) == 1
        sk, text = gw.sent[0]
        assert sk == "agent:qtr:1"  # relayed back to initiator (gateway)
        assert "Coder's answer" in text
        # arh.sent is empty — routing is correct (gateway not special)
        assert len(arh.sent) == 0

    def test_initiator_added_to_pending_relays_after_first_response(self, fully_wired):
        mgr = fully_wired["manager"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert not mgr.is_pending_relay("agent:qtr:1")
        mgr.capture_response("special:coder", "Answer")
        assert mgr.is_pending_relay("agent:qtr:1")


# ═══════════════════════════════════════════════════════════════════
#  close_thread
# ═══════════════════════════════════════════════════════════════════

class TestCloseThread:
    def test_sets_active_false(self, fully_wired):
        mgr = fully_wired["manager"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert mgr._threads[tid].active is True
        mgr.close_thread(tid)
        assert mgr._threads[tid].active is False

    def test_cleans_up_pending_relays(self, fully_wired):
        mgr = fully_wired["manager"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert mgr.is_pending_relay("special:coder")
        mgr.close_thread(tid)
        assert not mgr.is_pending_relay("special:coder")

    def test_posts_closing_card(self, fully_wired):
        mgr = fully_wired["manager"]
        fh = fully_wired["fh"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert len(fh.cards) == 1  # intent card only
        mgr.close_thread(list(mgr._threads.keys())[0])
        assert len(fh.cards) == 2
        closing = fh.cards[1]
        assert closing.card_type == "agent_action"
        assert closing.title == "Consultation complete"
        assert "QTR" in closing.body
        assert "Coder" in closing.body


# ═══════════════════════════════════════════════════════════════════
#  clear_project
# ═══════════════════════════════════════════════════════════════════

class TestClearProject:
    def test_closes_all_threads_for_project(self, fully_wired):
        mgr = fully_wired["manager"]
        fh = fully_wired["fh"]
        # Start two threads in same project
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q1")
        mgr.start_relay("proj", "agent:qtr:1", "special:debugger", "Q2")
        # And one in a different project
        mgr.start_relay("other", "agent:qtr:1", "special:coder", "Q3")

        assert len(mgr._threads) == 3

        mgr.clear_project("proj")

        # proj threads closed
        proj_threads = [t for t in mgr._threads.values() if t.project_name == "proj"]
        assert all(not t.active for t in proj_threads)
        # other project threads still active
        other_threads = [t for t in mgr._threads.values() if t.project_name == "other"]
        assert all(t.active for t in other_threads)

    def test_clear_nonexistent_project_noops(self, fully_wired):
        mgr = fully_wired["manager"]
        mgr.clear_project("nonexistent")  # should not raise


# ═══════════════════════════════════════════════════════════════════
#  is_pending_relay
# ═══════════════════════════════════════════════════════════════════

class TestIsPendingRelay:
    def test_returns_false_for_unknown_key(self, empty_manager):
        assert empty_manager.is_pending_relay("not:registered") is False

    def test_returns_true_after_start_relay(self, fully_wired):
        mgr = fully_wired["manager"]
        mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        assert mgr.is_pending_relay("special:coder") is True

    def test_returns_false_after_close(self, fully_wired):
        mgr = fully_wired["manager"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        mgr.close_thread(tid)
        assert mgr.is_pending_relay("special:coder") is False


# ═══════════════════════════════════════════════════════════════════
#  _send_relay — routing
# ═══════════════════════════════════════════════════════════════════

class TestSendRelayRouting:
    def test_routes_to_special_agent_via_ARH(self, fully_wired):
        mgr = fully_wired["manager"]
        arh = fully_wired["arh"]
        mgr._send_relay("special:coder", "Question for Coder")
        assert len(arh.sent) == 1
        assert arh.sent[0][0] == "special:coder"

    def test_routes_to_gateway_via_GW(self, fully_wired):
        mgr = fully_wired["manager"]
        gw = fully_wired["gw"]
        mgr._send_relay("agent:qtr:1", "Question for QTR")
        assert len(gw.sent) == 1
        assert gw.sent[0][0] == "agent:qtr:1"

    def test_offline_gateway_silently_skips(self, fully_wired):
        mgr = fully_wired["manager"]
        gw = fully_wired["gw"]
        gw._connected = False
        # Should not raise
        mgr._send_relay("agent:qtr:1", "Should silently skip")


# ═══════════════════════════════════════════════════════════════════
#  detect_a2a_mention (static method)
# ═══════════════════════════════════════════════════════════════════

class TestDetectA2AMention:
    def test_detects_at_mention_and_resolves(self):
        mgr = CollabManager
        handler = FakeCommandHandler(FakeMentionResolution(target_sk="special:coder"))
        result = mgr.detect_a2a_mention("@Coder how do I parse this?", "agent:qtr:1", "proj", handler)
        assert result is not None
        assert result["target_sk"] == "special:coder"
        assert "how do I parse this?" in result["question"]

    def test_no_mention_returns_none(self):
        mgr = CollabManager
        handler = FakeCommandHandler(FakeMentionResolution())
        result = mgr.detect_a2a_mention("Hello world, no mention here", "agent:qtr:1", "proj", handler)
        assert result is None

    def test_self_mention_returns_none(self):
        mgr = CollabManager
        handler = FakeCommandHandler(FakeMentionResolution(target_sk="agent:qtr:1"))
        # Source and target are the same — should be ignored
        result = mgr.detect_a2a_mention("@QTR can you help?", "agent:qtr:1", "proj", handler)
        assert result is None

    def test_broadcast_returns_none(self):
        mgr = CollabManager
        handler = FakeCommandHandler(FakeMentionResolution(is_broadcast=True))
        result = mgr.detect_a2a_mention("@ help everyone", "agent:qtr:1", "proj", handler)
        assert result is None

    def test_unknown_agent_returns_none(self):
        mgr = CollabManager
        handler = FakeCommandHandler(FakeMentionResolution(error="Unknown agent"))
        result = mgr.detect_a2a_mention("@NotAnAgent hello", "agent:qtr:1", "proj", handler)
        assert result is None

    def test_none_command_handler_returns_none(self):
        mgr = CollabManager
        result = mgr.detect_a2a_mention("@Coder question", "agent:qtr:1", "proj", None)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_close_nonexistent_thread_noops(self, empty_manager):
        empty_manager.close_thread("nonexistent:tid")  # should not raise

    def test_already_closed_thread_no_double_close(self, fully_wired):
        mgr = fully_wired["manager"]
        fh = fully_wired["fh"]
        tid = mgr.start_relay("proj", "agent:qtr:1", "special:coder", "Q")
        mgr.close_thread(tid)
        assert len(fh.cards) == 2  # intent + close
        mgr.close_thread(tid)  # double close — should not add another card
        assert len(fh.cards) == 2

    def test_set_special_agents_after_construct(self, empty_manager):
        arh = FakeAgentRuntimeHandler({"special:coder": "Coder"})
        empty_manager.set_agent_runtime_handler(arh)
        # Verify routing works
        empty_manager._send_relay("special:coder", "Test")  # should route via arh


# ═══════════════════════════════════════════════════════════════════
#  A2AThread Dataclass
# ═══════════════════════════════════════════════════════════════════

class TestA2AThreadDataclass:
    def test_default_values(self):
        thread = A2AThread(
            thread_id="a2a:proj:sk1:sk2",
            project_name="proj",
            initiator_sk="sk1",
            target_sk="sk2",
        )
        assert thread.responses == []
        assert thread.turn == 0
        assert thread.active is True

    def test_initiator_and_target_names_stored(self):
        thread = A2AThread(
            thread_id="a2a:proj:sk1:sk2",
            project_name="proj",
            initiator_sk="sk1",
            target_sk="sk2",
            initiator_name="QTR",
            target_name="Coder",
        )
        assert thread.initiator_name == "QTR"
        assert thread.target_name == "Coder"