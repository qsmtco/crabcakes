# tests/test_activity_bubbles.py
# Tests for Phase 2 of SPEC-smarter-chat-ux — Activity Bubbles.
#
# Architecture:
#   ActivityHandler.on_gateway_event() → fires _activity_bubble_callback(ActivityBubble)
#   ChatHandler._render_activity_bubble(bubble) → calls _render_activity_bubble_impl on main thread
#   ChatRenderHandler.render_sync("System", text, ...) → build_role_bubble("System", text)
#   build_role_bubble assigns .chat-bubble-System CSS class for activity bubble styling

import gi
gi.require_version('Gtk', '4.0')

import pytest
from unittest.mock import MagicMock


class TestActivityBubbleModel:
    """ActivityBubble dataclass — format_text() produces correct bubble text."""

    def test_lifecycle_start(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="lifecycle_start", session_key="sk-1")
        assert b.format_text() == "thinking..."

    def test_tool_start(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_start", session_key="sk-1", tool_name="web_search")
        assert b.format_text() == "search"

    def test_tool_end(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_end", session_key="sk-1", tool_name="web_search", duration_ms=1247)
        assert b.format_text() == "search  1,247ms"

    def test_tool_error(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_error", session_key="sk-1", tool_name="read_file")
        assert b.format_text() == "read file  failed"

    def test_plan(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="plan", session_key="sk-1", title="Refactor auth", steps=["Step 1", "Step 2", "Step 3"])
        text = b.format_text()
        assert "plan: Refactor auth" in text
        assert "3 steps" in text

    def test_approval_request(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="approval_request", session_key="sk-1", command="rm -rf /")
        assert b.format_text() == "approve: rm -rf /"

    def test_command_output(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="command_output", session_key="sk-1", tool_name="git diff", exit_code=0, duration_ms=4521)
        assert b.format_text() == "git diff  4,521ms"

    def test_patch(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="patch", session_key="sk-1", tool_name="edit_file", added=3, modified=7, deleted=1)
        text = b.format_text()
        assert "+3" in text
        assert "~7" in text
        assert "-1" in text

    def test_patch_partial(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="patch", session_key="sk-1", tool_name="edit_file", added=1, modified=0, deleted=0, icon="✏️")
        text = b.format_text()
        assert "+1" in text
        assert "~0" not in text
        assert "-0" not in text


class TestActivityHandlerActivityBubbles:
    """ActivityHandler fires _activity_bubble_callback for gateway events."""

    def test_lifecycle_start_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "startedAt": 12345}
        })

        cb.assert_called_once()
        bubble = cb.call_args[0][0]
        assert isinstance(bubble, ActivityBubble)
        assert bubble.type == "lifecycle_start"
        assert bubble.icon == "⏳"
        assert bubble.session_key == "sk-1"

    def test_tool_start_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "title": "web_search", "status": "running"}
        })

        cb.assert_called_once()
        bubble = cb.call_args[0][0]
        assert isinstance(bubble, ActivityBubble)
        assert bubble.type == "tool_start"
        assert bubble.tool_name == "web_search"
        assert bubble.icon == "🔧"

    def test_tool_end_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end", "kind": "tool", "name": "read_file", "title": "read_file", "status": "completed", "startedAt": 1000, "endedAt": 1083}
        })

        cb.assert_called_once()
        bubble = cb.call_args[0][0]
        assert bubble.type == "tool_end"
        assert bubble.tool_name == "read_file"
        assert bubble.duration_ms == 83
        assert bubble.icon == "✅"

    def test_tool_end_error_detected(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end", "kind": "tool", "name": "exec", "title": "exec", "status": "failed", "startedAt": 1000, "endedAt": 1500}
        })

        bubble = cb.call_args[0][0]
        assert bubble.type == "tool_error"
        assert bubble.icon == "❌"

    def test_plan_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "plan",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {
                "phase": "start",
                "title": "Refactor auth module",
                "steps": [{"title": "Extract login logic"}, {"title": "Add tests"}]
            }
        })

        bubble = cb.call_args[0][0]
        assert bubble.type == "plan"
        assert bubble.title == "Refactor auth module"
        assert len(bubble.steps) == 2
        assert bubble.icon == "📋"

    def test_approval_requested_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "approval",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "requested", "command": "rm -rf /", "reason": "cleanup", "approvalId": "ap-1"}
        })

        bubble = cb.call_args[0][0]
        assert bubble.type == "approval_request"
        assert bubble.command == "rm -rf /"
        assert bubble.reason == "cleanup"
        assert bubble.approval_id == "ap-1"
        assert bubble.icon == "🔒"

    def test_patch_end_fires_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        from models.activity import ActivityBubble
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        handler.on_gateway_event("agent", {
            "stream": "patch",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end", "name": "edit_file", "added": ["a.py"], "modified": ["b.py"], "deleted": []}
        })

        bubble = cb.call_args[0][0]
        assert bubble.type == "patch"
        assert bubble.tool_name == "edit_file"
        assert bubble.added == 1
        assert bubble.modified == 1
        assert bubble.deleted == 0
        assert bubble.icon == "✏️"

    def test_no_crash_when_callback_not_set(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        # Don't call set_on_activity_bubble — should not crash
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"}
        })

    def test_lifecycle_end_still_fires_lifecycle_callback(self, fake_glib):
        """lifecycle phase=end must still fire the lifecycle-completed callback."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        lc_cb = MagicMock()
        handler.set_on_lifecycle_completed(lc_cb)

        # Buffer some text first
        handler.on_gateway_event("agent", {
            "stream": "assistant",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"text": "Final response text"}
        })

        lc_cb.reset_mock()
        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end"}
        })

        lc_cb.assert_called_once_with("sk-1", "Final response text")

    def test_tool_start_bubble_has_agent_name(self, fake_glib):
        """Tool bubbles carry agent_name from the gateway payload (spec §2.4).

        Regression test for PHASE 4 — guards against removing the
        agent_name=_agent_name keyword arg from the tool_start ActivityBubble
        construction site. Without it, the drawer would show "[Agent]" instead
        of the actual agent name.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running", "agentName": "Coder"},
        })
        bubble = cb.call_args[0][0]
        assert bubble.agent_name == "Coder"

    def test_tool_end_bubble_has_agent_name(self, fake_glib):
        """Tool end bubbles also carry agent_name (spec §2.4).

        Companion to test_tool_start_bubble_has_agent_name — covers the second
        ActivityBubble construction site (tool_end/tool_error) added in PHASE 4.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {
                "phase": "end", "kind": "tool", "name": "web_search",
                "status": "ok", "startedAt": 1000, "endedAt": 2247,
                "agentName": "Debugger",
            },
        })
        bubble = cb.call_args[0][0]
        assert bubble.agent_name == "Debugger"
        # Sanity: duration_ms still works (regression check that we didn't break the line)
        assert bubble.duration_ms == 1247

    def test_tool_bubble_agent_name_defaults_to_empty(self, fake_glib):
        """When the gateway doesn't send agentName on tool events, agent_name defaults to ''.

        Defensive — per audit TODO, the gateway may not always send agentName
        on stream=item events. The drawer falls back to "[Agent]" for unknown
        agents, which is acceptable.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"},
            # Note: no agentName key
        })
        bubble = cb.call_args[0][0]
        assert bubble.agent_name == ""

    def test_tool_bubble_falls_back_to_agent_manager(self, fake_glib):
        """When data.agentName is empty, fall back to AgentManager.get_name(session_key)."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        # Mock AgentManager
        agent_mgr = MagicMock()
        agent_mgr.get_name = MagicMock(return_value="Coder")
        handler.set_agent_manager(agent_mgr)

        # Payload WITHOUT agentName — bug-trigger scenario
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "agent:coder",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"},
            # NO "agentName" key
        })

        bubble = cb.call_args[0][0]
        assert bubble.agent_name == "Coder", f"expected AgentManager fallback, got {bubble.agent_name!r}"
        agent_mgr.get_name.assert_called_once_with("agent:coder")

    def test_lifecycle_falls_back_to_agent_manager(self, fake_glib):
        """Lifecycle event without agentName also falls back to AgentManager.

        Mirror of test_tool_bubble_falls_back_to_agent_manager for the
        lifecycle branch — both extraction sites use the same helper.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        lifecycle_cb = MagicMock()
        handler.set_on_agent_lifecycle(lifecycle_cb)

        agent_mgr = MagicMock()
        agent_mgr.get_name = MagicMock(return_value="Debugger")
        handler.set_agent_manager(agent_mgr)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "agent:debugger",
            "runId": "run-1",
            "data": {"phase": "start"},  # no agentName
        })

        lifecycle_cb.assert_called_once_with("agent:debugger", "Debugger", "start")

    def test_agent_manager_exception_is_swallowed(self, fake_glib):
        """If AgentManager.get_name() raises, the resolution silently falls through to ''.

        Defensive — AgentManager may not be ready, may not have the session,
        may raise for any reason. The handler should not crash; the drawer
        will show "[Agent]" for the unknown agent.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        agent_mgr = MagicMock()
        agent_mgr.get_name = MagicMock(side_effect=RuntimeError("not ready"))
        handler.set_agent_manager(agent_mgr)

        # Should not raise
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "agent:coder",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"},
        })
        bubble = cb.call_args[0][0]
        assert bubble.agent_name == ""  # fallback chain exhausted

    def test_agent_manager_returns_empty_string(self, fake_glib):
        """If AgentManager.get_name() returns '', fall through to '' (drawer shows [Agent]).

        Edge case — AgentManager knows the session but has no display name
        (e.g., the agent hasn't been registered yet). agent_name stays "".
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        agent_mgr = MagicMock()
        agent_mgr.get_name = MagicMock(return_value="")
        handler.set_agent_manager(agent_mgr)

        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "agent:coder",
            "runId": "run-1",
            "data": {"phase": "start", "kind": "tool", "name": "web_search", "status": "running"},
        })
        bubble = cb.call_args[0][0]
        assert bubble.agent_name == ""

    def test_data_null_does_not_crash(self, fake_glib):
        """Gateway payload with data=None must not crash the handler (PHASE 7 Bug #4).

        Bug #4 root cause: payload.get('data', {}) returns the default {} only
        when the key is MISSING. When the key is present-but-null (data: None),
        the default is bypassed and downstream .get() crashes with AttributeError.
        _safe_data() helper coerces any non-dict to {} so all call sites are safe.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        # Should not raise for any stream type when data is None
        for stream in ("assistant", "lifecycle", "item", "plan", "approval", "patch"):
            try:
                handler.on_gateway_event("agent", {
                    "stream": stream,
                    "sessionKey": "sk-1",
                    "runId": "r-1",
                    "data": None,  # explicit null
                })
            except Exception as e:
                pytest.fail(f"handler crashed on data=None for stream={stream!r}: {e}")

    def test_data_missing_does_not_crash(self, fake_glib):
        """Gateway payload with data key MISSING must not crash the handler.

        Defensive complement to test_data_null_does_not_crash — covers the
        case where the gateway omits the 'data' key entirely.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        for stream in ("assistant", "lifecycle", "item", "plan", "approval", "patch"):
            try:
                handler.on_gateway_event("agent", {
                    "stream": stream,
                    "sessionKey": "sk-1",
                    "runId": "r-1",
                    # NO "data" key at all
                })
            except Exception as e:
                pytest.fail(f"handler crashed on missing-data for stream={stream!r}: {e}")

    def test_data_non_dict_does_not_crash(self, fake_glib):
        """Gateway payload with data=42 (or other non-dict) must not crash the handler.

        Defensive — _safe_data() coerces any non-dict value to {}.
        """
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_activity_bubble(cb)

        for bad_value in (42, "string-not-dict", [1, 2, 3], True, None):
            try:
                handler.on_gateway_event("agent", {
                    "stream": "item",
                    "sessionKey": "sk-1",
                    "runId": "r-1",
                    "data": bad_value,
                })
            except Exception as e:
                pytest.fail(f"handler crashed on data={bad_value!r}: {e}")

    def test_set_on_command_output_5_args(self, fake_glib):
        """AgentRuntimeHandler.set_on_command_output accepts 5 args (PHASE 7 Bug #7).

        Bug #7: spec §2.5 promised 5-arg signature
        (session_key, command, output, exit_code, duration_ms) but the
        implementation used 3 args, losing exit_code and duration_ms.
        """
        import inspect
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        src = inspect.getsource(AgentRuntimeHandler)
        # Type annotation: should declare Callable[[str, str, str, int, int], None]
        assert "Callable[[str, str, str, int, int]" in src, (
            "set_on_command_output signature should be 5 args per spec §2.5"
        )
        # Firing site: should call with 5 args
        assert "_on_command_output(session_key, cmd, tail, exit_code, duration_ms)" in src, (
            "firing site should pass 5 args (session_key, command, output, exit_code, duration_ms)"
        )


class TestChatHandlerActivityBubbleRender:
    """ChatHandler integration tests for activity/lifecycle routing (Phase 2 SPEC-smarter-chat-ux).

    The 4 _render_activity_bubble tests were REMOVED in SPEC-activity-drawer Phase 1
    (those methods are deleted; activity now flows to ActivityDrawer, not chat).
    """

    def test_lifecycle_fallback_routes_to_project_tab(self, fake_glib):
        """Lifecycle fallback resolves to project tab when agent has no direct tab."""
        from ui.handlers.chat_handler import ChatHandler

        class FakeRouting:
            def get_project(self, sk):
                return "crabwatch" if sk == "agent:qaster" else None
        
        routing = FakeRouting()
        mock_project_chat_box = MagicMock()
        mock_mc = MagicMock()
        mock_mc.get_chat_box_for_session = lambda sk: (
            mock_project_chat_box if sk == "project:crabwatch" else None
        )
        mock_mc.get_current_session_key = MagicMock(return_value="project:crabwatch")

        handler = ChatHandler(
            main_content=mock_mc,
            gateway_client=MagicMock(),
            agent_to_project=routing,
            projects_module=MagicMock(),
            GLib_module=fake_glib,
        )

        fake_render = MagicMock()
        fake_render.is_streaming.return_value = False
        fake_render.render_sync.return_value = MagicMock()
        handler._chat_render_handler = fake_render

        # Fire lifecycle fallback: agent key "agent:qaster" has project "crabwatch"
        handler._handle_lifecycle_completed("agent:qaster", "Response text from fallback")

        # Should have called _handle_final_response with project:crabwatch tab
        fake_render.render_sync.assert_called_once()
        mock_project_chat_box.append.assert_called_once()

    def test_is_ui_active_resolves_project_tab_for_agent(self, fake_glib):
        """_is_ui_active returns True when active tab is the project tab for the agent."""
        from ui.handlers.activity_handler import ActivityHandler

        class FakeRouting:
            def get_project(self, sk):
                return "crabwatch" if sk == "agent:qaster" else None
        
        routing = FakeRouting()
        mc = MagicMock()
        mc.get_current_session_key = MagicMock(return_value="project:crabwatch")

        ah = ActivityHandler(feedbar=MagicMock(), main_content=mc, GLib_module=fake_glib)
        ah.set_agent_routing(routing)

        # Agent key belongs to active project tab → considered active
        assert ah._is_ui_active("agent:qaster") is True
        # Agent key has no project routing → not active
        assert ah._is_ui_active("agent:unknown") is False
        # Direct tab match still works
        assert ah._is_ui_active("project:crabwatch") is True
        # None is always active
        assert ah._is_ui_active(None) is True

    def test_is_ui_active_no_routing_table(self, fake_glib):
        """Without routing table, _is_ui_active falls back to direct key comparison."""
        from ui.handlers.activity_handler import ActivityHandler

        mc = MagicMock()
        mc.get_current_session_key = MagicMock(return_value="project:crabwatch")

        ah = ActivityHandler(feedbar=MagicMock(), main_content=mc, GLib_module=fake_glib)
        # No routing table set
        ah._agent_to_project = None

        # Agent key → project tab (no routing table to resolve it)
        assert ah._is_ui_active("agent:qaster") is False
        # Direct match still works
        assert ah._is_ui_active("project:crabwatch") is True


class TestSystemBubbleCSS:
    """System bubbles get the .chat-bubble-System CSS class."""

    def _walk_css_classes(self, widget):
        """Walk all CSS classes from widget and its descendants (GTK4 compatible)."""
        classes = []
        if hasattr(widget, 'get_css_classes'):
            classes.extend(widget.get_css_classes())
        if hasattr(widget, 'get_first_child'):
            child = widget.get_first_child()
            while child is not None:
                classes.extend(self._walk_css_classes(child))
                sibling = child.get_next_sibling() if hasattr(child, 'get_next_sibling') else None
                child = sibling
        return classes

    def test_system_role_uses_system_css_class(self):
        from ui.views.chat_bubble import build_role_bubble
        widget = build_role_bubble("System", "test activity bubble")
        classes = self._walk_css_classes(widget)
        assert "chat-bubble-System" in classes

    def test_agent_role_uses_agent_css_class(self):
        from ui.views.chat_bubble import build_role_bubble
        widget = build_role_bubble("Agent", "hello")
        classes = self._walk_css_classes(widget)
        assert "chat-bubble-agent" in classes
        assert "chat-bubble-System" not in classes

    def test_you_role_uses_you_css_class(self):
        from ui.views.chat_bubble import build_role_bubble
        widget = build_role_bubble("You", "hello")
        classes = self._walk_css_classes(widget)
        assert "chat-bubble-you" in classes
        assert "chat-bubble-System" not in classes