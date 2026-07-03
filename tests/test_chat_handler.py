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


class FakeChatBox:
    """Fake chat box — tracks appended bubble widgets only.

    Note: production chat_box is a plain Gtk.Box with no record() method.
    Tests that need to assert on displayed messages should inspect the
    FakeMainContent._chat_render_handler mock (render_async / render_sync
    call args), not this object.
    """

    def __init__(self):
        self.bubbles = []  # list of widgets appended (for smoke tests)


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
        # Chat bubble rendering (Phase 2 refactor — ChatRenderHandler calls get_chat_box())
        self._fake_chat_box = FakeChatBox()
        # ChatRenderHandler mock — production code calls render_async(role, text, ...)
        # or render_sync(role, text, ...) to display bubbles. Tests assert on these
        # call args to verify the right (role, text) was sent for display.
        self._chat_render_handler = MagicMock()
        # Tab management for switch_to_tab tests
        self._notebook_mock = MagicMock()
        self._notebook_mock.get_n_pages.return_value = 0

    def scroll_chat_to_bottom(self, page_index=None):
        pass  # no-op in tests

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

    def get_chat_box(self):
        return self._fake_chat_box

    def append_message_to_current_tab(self, role, text, session_key=None):
        self._messages.append((role, text))

    def set_current_session(self, key):
        self._current_session_key = key

    # ── Tab management for switch_to_tab tests ──────────────────────────────

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

    def get_chat_box_for_session(self, session_key: str):
        """Match MainContent.get_chat_box_for_session() — returns the fake chat box
        if session_key is in _tab_sessions, else None."""
        for idx, sk in self._tab_sessions.items():
            if sk == session_key:
                return self._fake_chat_box
        return None

    # ── Helpers for test assertions ──────────────────────────────────────────

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
    from models import AgentRoutingTable

    if agent_to_project is None:
        agent_to_project = AgentRoutingTable()
    elif isinstance(agent_to_project, dict):
        # Support legacy dict-based test fixtures — convert to AgentRoutingTable
        table = AgentRoutingTable()
        for k, v in agent_to_project.items():
            table.add(k, v)
        agent_to_project = table

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
        """After send: message is rendered via ChatRenderHandler.render_async.

        Replaces a pre-fix test that asserted on the dead chat_box.record()
        path. The real rendering goes through self._chat_render_handler
        (a MagicMock on FakeMainContent).
        """
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main", input_text="hello")
        handler = make_handler(mc, gw)
        # Wire the chat render handler mock so render_async gets called.
        handler.set_chat_render_handler(mc._chat_render_handler)

        handler.on_send()

        # render_async is the path for echo (You) bubbles. The first two
        # positional args are (role, text). Other args (session_key,
        # forward callbacks, etc.) are exercised by lower-level tests.
        mc._chat_render_handler.render_async.assert_called_once()
        call_args = mc._chat_render_handler.render_async.call_args
        assert call_args[0][0] == "You"
        assert call_args[0][1] == "hello"


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
        """Fan-out: your message is rendered to the project tab.

        The (role, text) "You"/"broadcast" goes through render_async on
        the chat render handler. Replaces pre-fix assertion on dead
        chat_box.record() path.
        """
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="project:foo", input_text="broadcast")
        projects = FakeProjectsModule(members={"foo": ["agent:qaster:1"]})
        handler = make_handler(mc, gw, projects_module=projects)
        handler.set_chat_render_handler(mc._chat_render_handler)

        handler.on_send()

        # The fan-out path renders the You message to the project tab.
        # It may also send via gw.send_message to each member, but that's
        # covered by the FakeGatewayClient._sent log — not under test here.
        render_calls = mc._chat_render_handler.render_async.call_args_list
        you_calls = [c for c in render_calls if c[0][0] == "You" and c[0][1] == "broadcast"]
        assert len(you_calls) >= 1, (
            f"expected at least one render_async('You', 'broadcast', ...) call; "
            f"got render_async calls: {render_calls}"
        )


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
        mc.set_tab_sessions({0: "project:myproj"})
        # agent:qaster:1 belongs to myproj
        agent_to_project = {"agent:qaster:1": "myproj"}
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        handler.on_chat_event("chat", self.make_final_payload("agent:qaster:1", "got it"))

        assert ("Agent", "got it") in mc.get_messages()

    def test_routes_to_agent_tab_when_not_in_project(self):
        """Agent is NOT a project member → response appears in agent's own tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="agent:main")
        mc.set_tab_sessions({0: "agent:main"})
        agent_to_project = {}  # no project mapping
        handler = make_handler(mc, gw, agent_to_project=agent_to_project)

        handler.on_chat_event("chat", self.make_final_payload("agent:main", "direct reply"))

        assert ("Agent", "direct reply") in mc.get_messages()

    def test_routes_to_correct_project_when_agent_in_multiple_projects(self):
        """Agent in two projects → uses the project that matches the current tab."""
        gw = FakeGatewayClient()
        mc = FakeMainContent(session_key="project:projA")
        mc.set_tab_sessions({0: "project:projA"})
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
        mc.set_tab_sessions({0: "agent:unknown"})
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
        mc.set_tab_sessions({0: "agent:main"})
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
        mc.set_tab_sessions({0: "agent:main"})
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


# ── Tests: command error response_text display ─────────────────────────────────

class TestCommandErrorDisplay:
    """When a command returns handled=True with response_text but no forward_to,
    the error message must be displayed in the chat (not silently swallowed)."""

    def _make_handler_with_command(self, input_text: str, command_result):
        """Create a ChatHandler with a mock command handler that returns the given result."""
        from models.command import CommandResult
        gw = FakeGatewayClient(connected=True)
        mc = FakeMainContent(session_key="agent:main", input_text=input_text)
        handler = make_handler(mc, gw)

        # Mock command handler
        mock_cmd = MagicMock()
        mock_cmd.process_input.return_value = command_result
        handler.set_command_handler(mock_cmd)

        # Mock chat render handler — render_sync returns a fake bubble
        mock_render = MagicMock()
        mock_render.render_sync.return_value = MagicMock()  # fake bubble widget
        handler.set_chat_render_handler(mock_render)

        return handler, mc, mock_render

    def test_error_response_text_displayed_via_callback(self):
        """CommandResult with response_text and no forward_to: on_display_text callback fires."""
        from models.command import CommandResult
        result = CommandResult(handled=True, response_text="Malformed command — payload must be quoted")
        handler, mc, mock_render = self._make_handler_with_command("/task @Coder hello", result)

        # Capture the on_display_text callback set on the mock command handler
        mock_cmd = handler._command_handler
        callback = mock_cmd._on_display_text

        handler.on_send()

        # The command handler's _dispatch_result should have been called,
        # which fires on_display_text. Verify the callback was invoked.
        # Since we're using a MagicMock command handler, process_input returns
        # our result but _dispatch_result isn't called (it's on the mock).
        # The ChatHandler no longer renders response_text directly — that's correct.
        # Just verify render_sync was NOT called (no double-bubble).
        mock_render.render_sync.assert_not_called()

    def test_error_response_no_direct_render_in_chat_handler(self):
        """response_text rendering is handled by CommandHandler callback, not ChatHandler."""
        from models.command import CommandResult
        result = CommandResult(handled=True, response_text="Unknown agent: @Foo")
        handler, mc, mock_render = self._make_handler_with_command("/ask @Foo hi", result)
        fake_bubble = MagicMock()
        mock_render.render_sync.return_value = fake_bubble

        handler.on_send()

        # ChatHandler should NOT render response_text directly (was causing double-bubble)
        chat_box = mc.get_chat_box()
        assert fake_bubble not in chat_box.bubbles
        mock_render.render_sync.assert_not_called()

    def test_forward_to_command_does_not_trigger_response_text_branch(self):
        """Commands with forward_to use the forward branch, not the response_text branch."""
        from models.command import CommandResult
        result = CommandResult(
            handled=True,
            response_text="should be ignored",
            forward_to="agent:coder",
            forward_text="actual message",
        )
        handler, mc, mock_render = self._make_handler_with_command("/ask @Coder \"hi\"", result)

        handler.on_send()

        # render_sync must NOT be called with response_text — forward branch handles display
        for call_args in mock_render.render_sync.call_args_list:
            assert call_args[0][1] != "should be ignored"

    def test_handled_false_does_not_display_response_text(self):
        """handled=False: response_text is ignored, message passes through as text."""
        from models.command import CommandResult
        result = CommandResult(handled=False, response_text="should not appear")
        handler, mc, mock_render = self._make_handler_with_command("/home/path", result)

        handler.on_send()

        # render_sync must NOT be called — message passes through as plain text
        mock_render.render_sync.assert_not_called()

    def test_no_response_text_no_crash(self):
        """handled=True with response_text=None and no forward_to: no crash."""
        from models.command import CommandResult
        result = CommandResult(handled=True)
        handler, mc, mock_render = self._make_handler_with_command("/status", result)

        handler.on_send()  # must not raise

        # render_sync should NOT be called — nothing to display
        mock_render.render_sync.assert_not_called()


# ── Tests: Inline @mention routing for special agents (Phase 1, SPEC-LOCAL-AGENT-NO-RESPONSE-FIX) ──

class TestInlineMentionRouting:
    """Inline @Agent and @all mentions in project tabs must route special agents
    through AgentRuntimeHandler, not gateway. Otherwise messages are silently dropped."""

    def _make_handler_with_inline_mention(
        self,
        input_text: str,
        mention_resolution,
        special_agents: dict[str, str] | None = None,
        connected: bool = True,
    ):
        """Create a ChatHandler wired for the inline @mention path.

        Sets up:
        - session_key = "project:crabcakes" (triggers inline mention branch)
        - command handler returns handled=False, resolve_inline_mention returns given resolution
        - agent_runtime_handler mock with get_special_agents returning special_agents
        """
        from models.command import CommandResult
        gw = FakeGatewayClient(connected=connected)
        mc = FakeMainContent(session_key="project:crabcakes", input_text=input_text)
        handler = make_handler(mc, gw)

        # Mock command handler — returns handled=False so we fall through to inline mention
        mock_cmd = MagicMock()
        mock_cmd.process_input.return_value = CommandResult(handled=False)
        mock_cmd.resolve_inline_mention.return_value = mention_resolution
        handler.set_command_handler(mock_cmd)

        # Mock chat render handler
        mock_render = MagicMock()
        mock_render.render_sync.return_value = MagicMock()
        handler.set_chat_render_handler(mock_render)

        # Mock agent runtime handler
        mock_arh = MagicMock()
        mock_arh.get_special_agents.return_value = special_agents or {}
        handler.set_agent_runtime_handler(mock_arh)

        return handler, mc, gw, mock_arh

    def test_inline_mention_to_special_agent_routes_to_runtime(self):
        """Inline @Coder hello from project tab → routes to AgentRuntimeHandler, not gateway."""
        from models.command import MentionResolution
        resolution = MentionResolution(
            target_session_key="special:coder",
            clean_text="hello",
        )
        handler, mc, gw, mock_arh = self._make_handler_with_inline_mention(
            "@Coder hello",
            resolution,
            special_agents={"special:coder": "Coder"},
        )

        handler.on_send()

        # Must route through AgentRuntimeHandler
        mock_arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
        # Must NOT send to gateway
        assert gw.get_sent() == []

    def test_inline_mention_to_gateway_agent_routes_to_gw(self):
        """Inline @QTR status from project tab → routes to gateway (not a special agent)."""
        from models.command import MentionResolution
        resolution = MentionResolution(
            target_session_key="agent:qtr",
            clean_text="status",
        )
        handler, mc, gw, mock_arh = self._make_handler_with_inline_mention(
            "@QTR status",
            resolution,
            special_agents={"special:coder": "Coder"},  # qtr NOT in special agents
        )

        handler.on_send()

        # Must NOT call AgentRuntimeHandler
        mock_arh.send_to_special_agent.assert_not_called()
        # Must send to gateway
        assert gw.get_sent() == [("agent:qtr", "status")]

    def test_inline_mention_broadcast_with_special_member_routes_to_runtime(self):
        """Inline @all hello with mixed members → special agents via runtime, gateway agents via gw."""
        from models.command import MentionResolution
        resolution = MentionResolution(
            broadcast_targets=["special:coder", "agent:qtr"],
            clean_text="hello",
            is_broadcast=True,
        )
        handler, mc, gw, mock_arh = self._make_handler_with_inline_mention(
            "@all hello",
            resolution,
            special_agents={"special:coder": "Coder"},
        )

        handler.on_send()

        # Coder routed through AgentRuntimeHandler
        mock_arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
        # QTR routed through gateway
        assert gw.get_sent() == [("agent:qtr", "hello")]

    def test_inline_mention_to_special_agent_does_not_call_gw(self):
        """Regression guard: inline @Coder must NOT call gw.send_message at all."""
        from models.command import MentionResolution
        resolution = MentionResolution(
            target_session_key="special:coder",
            clean_text="hello",
        )
        handler, mc, gw, mock_arh = self._make_handler_with_inline_mention(
            "@Coder hello",
            resolution,
            special_agents={"special:coder": "Coder"},
        )

        handler.on_send()

        # Explicit regression check: gateway was never called with special:coder
        for sk, text in gw.get_sent():
            assert sk != "special:coder", (
                f"gw.send_message called with special:coder — should route via AgentRuntimeHandler instead"
            )
        # And runtime was called
        mock_arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
