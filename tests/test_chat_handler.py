# tests/test_chat_handler.py
# Tests for ui/handlers/chat_handler.py — ChatHandler.
#
# Principle: test the failure modes that could break callers.
# Mock GatewayClient and MainContent at the boundary.
# Do NOT mock internal state — test what the handler does, not how it does it.

import pytest
from unittest.mock import MagicMock, patch, call
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


# ── Helpers ────────────────────────────────────────────────────────────────────

class FakeTextIter:
    """Pretends to be a Gtk.TextIter."""
    def __init__(self, offset=0):
        self._offset = offset
    def get_offset(self):
        return self._offset


class FakeTextBuffer:
    """Pretends to be a Gtk.TextBuffer for input text access."""

    def __init__(self, text=""):
        self._text = text

    def get_text(self, start_iter, end_iter, include_hidden_chars=False):
        # start_iter/end_iter are FakeTextIters — we ignore them and return full text
        return self._text

    def get_start_iter(self):
        return FakeTextIter(0)

    def get_end_iter(self):
        return FakeTextIter(len(self._text))

    def set_text(self, text):
        self._text = text


class FakeMainContent:
    """Pretends to be MainContent — tracks what ChatHandler calls on it."""

    def __init__(self, session_key="agent:main", input_text=""):
        self._current_session_key = session_key
        self._input_buffer = FakeTextBuffer(input_text)
        # _tab_sessions: plain dict — matches MainContent._tab_sessions exactly
        self._tab_sessions = {}
        self._messages = []       # (role, text) appended to current tab

    def get_current_session_key(self):
        return self._current_session_key

    @property
    def user_input(self):
        # Returns something with a get_buffer method that returns our _input_buffer
        inp = MagicMock()
        inp.get_buffer.return_value = self._input_buffer
        return inp

    def get_buffer(self):
        return self._input_buffer

    def append_message_to_current_tab(self, role, text, session_key=None):
        self._messages.append((role, text))

    def set_current_session(self, key):
        self._current_session_key = key

    # ── Tab management for switch_to_tab tests ──────────────────────────────

    def __init__(self, session_key="agent:main", input_text=""):
        self._current_session_key = session_key
        self._input_buffer = FakeTextBuffer(input_text)
        # _tab_sessions: plain dict — matches MainContent._tab_sessions exactly
        self._tab_sessions = {}
        self._messages = []       # (role, text) appended to current tab
        # Cache notebook mock so get_n_pages and set_current_page share the same mock
        self._notebook_mock = MagicMock()
        self._notebook_mock.get_n_pages.return_value = 0

    @property
    def notebook(self):
        # Update page count to match current _tab_sessions state
        self._notebook_mock.get_n_pages.return_value = len(self._tab_sessions)
        return self._notebook_mock

    def set_tab_sessions(self, tab_sessions: dict):
        """Set up tabs: {page_idx: session_key}"""
        self._tab_sessions = tab_sessions

    def _get_page_for_session(self, session_key) -> int | None:
        for idx, sk in self._tab_sessions.items():
            if sk == session_key:
                return idx
        return None

    # ── Helpers for test assertions ──────────────────────────────────────────

    def get_messages(self):
        return list(self._messages)

    def clear_messages(self):
        self._messages = []


class FakeGatewayClient:
    """Pretends to be GatewayClient — tracks what ChatHandler calls on it."""

    def __init__(self, connected=True):
        self._connected = connected
        self._sent = []  # (session_key, text)

    def is_connected(self):
        return self._connected

    def send_message(self, session_key, text):
        self._sent.append((session_key, text))

    def get_sent(self):
        return list(self._sent)

    def clear_sent(self):
        self._sent = []


class FakeProjectsModule:
    """Pretends to be utils.projects module."""

    def __init__(self, members=None):
        # members: dict of project_name → [session_keys]
        self._members = members or {}

    def load_members(self, project_name):
        return self._members.get(project_name, [])


# ── Subject under test ───────────────────────────────────────────────────────────

def make_handler(main_content, gateway_client, agent_to_project=None, projects_module=None):
    """Create a ChatHandler with all dependencies injected."""
    from ui.handlers.chat_handler import ChatHandler

    if agent_to_project is None:
        agent_to_project = {}

    handler = ChatHandler(
        main_content=main_content,
        gateway_client=gateway_client,
        agent_to_project=agent_to_project,
        projects_module=projects_module,
    )
    return handler


# ── Tests: on_send_clicked ─────────────────────────────────────────────────────

class TestSendClicked:
    """on_send_clicked is the GTK signal handler — must not crash on None/empty."""

    def test_noop_when_no_gateway(self):
        """Gateway=None: must not crash."""
        mc = FakeMainContent(session_key="agent:main", input_text="hello")
        handler = make_handler(mc, None)
        handler.on_send_clicked()  # must not raise

    def test_noop_when_disconnected(self):
        """Gateway exists but not connected: must not crash, no message sent."""
        gw = FakeGatewayClient(connected=False)
        mc = FakeMainContent(session_key="agent:main", input_text="hello")
        handler = make_handler(mc, gw)
        handler.on_send_clicked()

        assert gw.get_sent() == []

    def test_noop_when_no_text(self):
        """Input is empty string: must not crash, no message sent."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main", input_text="  ")
        handler = make_handler(mc, gw)
        handler.on_send_clicked()

        assert gw.get_sent() == []

    def test_noop_when_no_session_key(self):
        """get_current_session_key returns None: must not crash."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key=None, input_text="hello")
        handler = make_handler(mc, gw)
        handler.on_send_clicked()  # must not raise

        assert gw.get_sent() == []


# ── Tests: on_send — DM (non-project) ─────────────────────────────────────────

class TestSendDm:
    """Sending to a single agent — no fan-out."""

    def test_sends_to_single_agent(self):
        """Direct message to agent: sends once to that session_key."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main:session:abc", input_text="hello")
        handler = make_handler(mc, gw)
        handler.on_send()

        assert gw.get_sent() == [("agent:main:session:abc", "hello")]

    def test_sends_and_clears_input(self):
        """After send: input buffer is cleared."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main", input_text="hello world")
        handler = make_handler(mc, gw)
        handler.on_send()

        assert mc.get_buffer()._text == ""

    def test_sends_and_displays_message(self):
        """After send: message appears in chat tab."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main", input_text="hello")
        handler = make_handler(mc, gw)
        handler.on_send()

        assert ("You", "hello") in mc.get_messages()


# ── Tests: on_send — Project fan-out ───────────────────────────────────────────

class TestSendProjectFanOut:
    """Sending in a project tab: message goes to ALL project members."""

    def test_fan_out_sends_to_all_members(self):
        """project:foo tab: message sent to each member, not to project tab."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="project:foo", input_text="hello group")
        projects = FakeProjectsModule(members={"foo": ["agent:qaster:1", "agent:qaster:2"]})
        handler = make_handler(mc, gw, projects_module=projects)

        handler.on_send()

        assert gw.get_sent() == [
            ("agent:qaster:1", "hello group"),
            ("agent:qaster:2", "hello group"),
        ]

    def test_fan_out_to_empty_project_sends_nothing(self):
        """project:foo tab with no members: no messages sent."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="project:empty", input_text="hello")
        projects = FakeProjectsModule(members={"empty": []})
        handler = make_handler(mc, gw, projects_module=projects)

        handler.on_send()

        assert gw.get_sent() == []

    def test_fan_out_sends_your_message_to_tab(self):
        """Fan-out: your message still appears in the project tab."""
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="project:foo", input_text="broadcast")
        projects = FakeProjectsModule(members={"foo": ["agent:qaster:1"]})
        handler = make_handler(mc, gw, projects_module=projects)

        handler.on_send()

        assert ("You", "broadcast") in mc.get_messages()


# ── Tests: on_chat_event — routing ─────────────────────────────────────────────

class TestChatEventRouting:
    """chat.final events must be routed to the correct tab."""

    def make_final_payload(self, session_key, text):
        return {
            "state": "final",
            "sessionKey": session_key,
            "message": {"content": text},
        }

    def test_routes_to_project_tab_when_agent_in_project(self):
        """Agent is a project member → response appears in project tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="project:myproj")
        # agent:qaster:1 belongs to myproj
        agent_to_project = {"agent:qaster:1": "myproj"}
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        handler.on_chat_event("chat", self.make_final_payload("agent:qaster:1", "got it"))

        assert ("Agent", "got it") in mc.get_messages()

    def test_routes_to_agent_tab_when_not_in_project(self):
        """Agent is NOT a project member → response appears in agent's own tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        agent_to_project = {}  # no project mapping
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        handler.on_chat_event("chat", self.make_final_payload("agent:main", "direct reply"))

        assert ("Agent", "direct reply") in mc.get_messages()

    def test_routes_to_correct_project_when_agent_in_multiple_projects(self):
        """Agent in two projects → uses the project that matches the current tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="project:projA")
        # agent is in both projA and projB
        agent_to_project = {
            "agent:shared:1": "projA",
            "agent:shared:2": "projB",
        }
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        handler.on_chat_event("chat", self.make_final_payload("agent:shared:1", "reply"))

        assert ("Agent", "reply") in mc.get_messages()

    def test_unknown_agent_routes_to_agent_tab(self):
        """Agent session_key not in _agent_to_project: routes to agent tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:unknown")
        agent_to_project = {}  # completely empty
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        # Must not crash — routing falls back to agent tab
        handler.on_chat_event("chat", self.make_final_payload("agent:unknown", "who?"))

        assert ("Agent", "who?") in mc.get_messages()

    def test_empty_content_does_not_appear(self):
        """chat.final with empty content: must not add empty message."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        handler = make_handler(mc, gw)

        handler.on_chat_event("chat", self.make_final_payload("agent:main", ""))

        assert mc.get_messages() == []

    def test_non_final_state_ignored(self):
        """state != "final": event is ignored, no message added."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        handler = make_handler(mc, gw)

        handler.on_chat_event("chat", {
            "state": "partial",
            "sessionKey": "agent:main",
            "message": {"content": "partial text"},
        })

        assert mc.get_messages() == []

    def test_content_as_list_text_blocks_extracted(self):
        """content is a list of text blocks: joined together."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        handler = make_handler(mc, gw)

        handler.on_chat_event("chat", {
            "state": "final",
            "sessionKey": "agent:main",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello "},
                    {"type": "text", "text": "world"},
                ]
            },
        })

        assert ("Agent", "Hello world") in mc.get_messages()

    def test_content_wrong_type_does_not_crash(self):
        """content is a number or object instead of str/list: no crash, no message."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        handler = make_handler(mc, gw)

        # Must not raise — falls back to str() or empty
        handler.on_chat_event("chat", {
            "state": "final",
            "sessionKey": "agent:main",
            "message": {"content": 12345},
        })

        # 12345 is truthy → str(12345) = "12345"
        assert ("Agent", "12345") in mc.get_messages()


# ── Tests: switch_to_tab ───────────────────────────────────────────────────────

class TestSwitchToTab:
    """switch_to_tab: finds the tab with matching session_key and switches to it."""

    def test_switches_to_existing_tab(self):
        """Tab exists: notebook.set_current_page is called with correct index."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        mc.set_tab_sessions({0: "agent:main", 1: "agent:other", 2: "project:foo"})
        handler = make_handler(mc, gw)

        handler.switch_to_tab("agent:other")

        mc.notebook.set_current_page.assert_called_once_with(1)

    def test_noop_when_tab_not_found(self):
        """No matching tab: set_current_page is NOT called."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        mc.set_tab_sessions({0: "agent:main"})
        handler = make_handler(mc, gw)

        handler.switch_to_tab("agent:nonexistent")  # no crash

        mc.notebook.set_current_page.assert_not_called()

    def test_noop_when_no_tabs(self):
        """Empty notebook: no crash."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key=None)
        mc.set_tab_sessions({})
        handler = make_handler(mc, gw)

        handler.switch_to_tab("agent:main")  # no crash

        mc.notebook.set_current_page.assert_not_called()
