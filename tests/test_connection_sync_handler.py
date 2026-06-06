# tests/test_connection_sync_handler.py
# Tests for ui/handlers/connection_sync_handler.py — Phase 3a-1 extraction.
#
# What this tests:
#   ConnectionSyncHandler.sync(gw) wires live GatewayClient and AgentManager
#   into all dependent handlers after the gateway WebSocket handshake completes.
#   This test file verifies the wiring is correct (right targets, right args,
#   right order) without depending on real GTK, real gateways, or real
#   handler implementations.
#
# Principle: mock at the boundary, test behavior not internals.
# All dependencies are MagicMock instances. We assert on the public setter
# side effects (which handlers were called with which args) rather than on
# internal state. See ARCHITECTURE.md §8.6 (handler pattern: receive deps via
# setters, never import from ui/handlers/).

import pytest
from unittest.mock import MagicMock

from ui.handlers.connection_sync_handler import ConnectionSyncHandler


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def gw():
    """A MagicMock GatewayClient — represents the live client after connect."""
    return MagicMock(name="GatewayClient")


@pytest.fixture
def deps():
    """A bundle of MagicMock instances for all 16 ConnectionSyncHandler deps.

    Returned as a dict so individual tests can pick the dependencies they care
    about. All setters on the mock targets are no-ops by default; this lets
    the handler's sync() body run without raising, and lets tests assert
    exactly which setters were called with which args.
    """
    agent_mgr = MagicMock(name="AgentManager")
    agent_to_project = MagicMock(name="AgentRoutingTable")
    review_handler = MagicMock(name="ReviewHandler")

    # ChatHandler is a "wider" target — multiple setters, plus internal
    # attributes that sync() reads (e.g. chat_handler._awareness_sent,
    # chat_handler._handle_lifecycle_completed, etc.). Set these as real
    # sentinels so equality assertions are readable.
    chat_handler = MagicMock(name="ChatHandler")
    chat_handler._awareness_sent = MagicMock(name="awareness_sent_set")
    chat_handler._handle_lifecycle_completed = MagicMock(name="lifecycle_completed")
    chat_handler._buffer_assistant_text = MagicMock(name="buffer_assistant_text")
    chat_handler._clear_render_guard = MagicMock(name="clear_render_guard")
    chat_handler._render_activity_bubble = MagicMock(name="render_activity_bubble")

    # ActivityHandler is the second "wider" target — sync() reads
    # activity_handler.on_send_initiated and on_res_confirmed. Provide real
    # sentinel callables so equality assertions don't compare MagicMocks.
    activity_handler = MagicMock(name="ActivityHandler")
    activity_handler.on_send_initiated = MagicMock(name="on_send_initiated")
    activity_handler.on_res_confirmed = MagicMock(name="on_res_confirmed")

    # GatewayHandler — the source of agent_mgr. sync() reaches through
    # gateway_handler.agent_mgr, so that attribute must be a real sentinel.
    gateway_handler = MagicMock(name="GatewayHandler")
    gateway_handler.agent_mgr = agent_mgr

    # ProjectHandler — sync() calls get_active_project_name() (gates the
    # left_panel.refresh call) and get_active_project_path() (inside the
    # lambda passed to set_project_path_provider).
    project_handler = MagicMock(name="ProjectHandler")
    project_handler.get_active_project_name.return_value = "test-project"
    project_handler.get_active_project_path.return_value = "/tmp/test-project"

    return {
        "chat_handler": chat_handler,
        "main_content": MagicMock(name="MainContent"),
        "agent_list_handler": MagicMock(name="AgentListHandler"),
        "gateway_handler": gateway_handler,
        "project_handler": project_handler,
        "command_handler": MagicMock(name="CommandHandler"),
        "agent_command_handler": MagicMock(name="AgentCommandHandler"),
        "session_handler": MagicMock(name="SessionHandler"),
        "feed_handler": MagicMock(name="FeedHandler"),
        "left_panel": MagicMock(name="LeftPanel"),
        "review_handler": review_handler,
        "activity_handler": activity_handler,
        "agent_to_project": agent_to_project,
        "on_forward_clicked": MagicMock(name="on_forward_clicked"),
        "project_path_provider": lambda: "/tmp/test-project",
        # Extras for assertions:
        "agent_mgr": agent_mgr,
    }


@pytest.fixture
def handler(deps):
    """A ConnectionSyncHandler wired with all 16 mock dependencies."""
    return ConnectionSyncHandler(
        chat_handler=deps["chat_handler"],
        main_content=deps["main_content"],
        agent_list_handler=deps["agent_list_handler"],
        gateway_handler=deps["gateway_handler"],
        project_handler=deps["project_handler"],
        command_handler=deps["command_handler"],
        agent_command_handler=deps["agent_command_handler"],
        session_handler=deps["session_handler"],
        feed_handler=deps["feed_handler"],
        left_panel=deps["left_panel"],
        review_handler=deps["review_handler"],
        activity_handler=deps["activity_handler"],
        agent_to_project=deps["agent_to_project"],
        on_forward_clicked=deps["on_forward_clicked"],
        project_path_provider=deps["project_path_provider"],
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestChatHandlerWiring:
    """sync() injects the live GatewayClient and AgentManager into ChatHandler."""

    def test_sync_calls_chat_handler_set_gateway_client_with_gw(self, handler, deps, gw):
        handler.sync(gw)
        deps["chat_handler"].set_gateway_client.assert_called_once_with(gw)

    def test_sync_calls_chat_handler_set_agent_manager_once(
        self, handler, deps, gw
    ):
        """chat_handler.set_agent_manager is called once with the live agent_mgr
        (line 142 of handler body). It is NOT called twice — only the broader
        set_agent_manager setter pattern across all handlers totals 6 calls."""
        handler.sync(gw)
        assert deps["chat_handler"].set_agent_manager.call_count == 1
        deps["chat_handler"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )

    def test_sync_calls_chat_handler_set_on_forward_message_with_callback(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["chat_handler"].set_on_forward_message.assert_called_once_with(
            deps["on_forward_clicked"]
        )

    def test_sync_calls_chat_handler_set_on_send_initiated_with_activity_callback(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["chat_handler"].set_on_send_initiated.assert_called_once_with(
            deps["activity_handler"].on_send_initiated
        )

    def test_sync_calls_chat_handler_set_on_res_confirmed_with_activity_callback(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["chat_handler"].set_on_res_confirmed.assert_called_once_with(
            deps["activity_handler"].on_res_confirmed
        )


class TestMainContentAndAgentListWiring:
    """sync() wires AgentManager into MainContent and AgentListHandler."""

    def test_sync_calls_main_content_set_agent_manager(self, handler, deps, gw):
        handler.sync(gw)
        deps["main_content"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )

    def test_sync_calls_agent_list_handler_set_agent_mgr(self, handler, deps, gw):
        handler.sync(gw)
        deps["agent_list_handler"].set_agent_mgr.assert_called_once_with(
            deps["agent_mgr"]
        )


class TestCommandHandlerWiring:
    """sync() wires GatewayClient and AgentManager into CommandHandler."""

    def test_sync_calls_command_handler_set_gateway_client(self, handler, deps, gw):
        handler.sync(gw)
        deps["command_handler"].set_gateway_client.assert_called_once_with(gw)

    def test_sync_calls_command_handler_set_agent_manager(self, handler, deps, gw):
        handler.sync(gw)
        deps["command_handler"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )


class TestProjectHandlerWiring:
    """sync() wires AgentManager and ReviewHandler into ProjectHandler."""

    def test_sync_calls_project_handler_set_agent_manager(self, handler, deps, gw):
        handler.sync(gw)
        deps["project_handler"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )

    def test_sync_calls_project_handler_set_review_handler_with_self_review(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["project_handler"].set_review_handler.assert_called_once_with(
            deps["review_handler"]
        )


class TestAgentCommandHandlerWiring:
    """sync() wires the most state into AgentCommandHandler — see the bug
    where set_awareness_sent was the missing piece during spec development."""

    def test_sync_calls_agent_command_handler_set_gateway_client(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["agent_command_handler"].set_gateway_client.assert_called_once_with(gw)

    def test_sync_calls_agent_command_handler_set_agent_manager(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["agent_command_handler"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )

    def test_sync_calls_agent_command_handler_set_agent_routing_with_table(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["agent_command_handler"].set_agent_routing.assert_called_once_with(
            deps["agent_to_project"]
        )

    def test_sync_calls_agent_command_handler_set_awareness_sent_from_chat(
        self, handler, deps, gw
    ):
        """The bug we just hit in the spec: awareness_sent must come from
        chat_handler._awareness_sent (the live set, not a fresh mock)."""
        handler.sync(gw)
        deps["agent_command_handler"].set_awareness_sent.assert_called_once_with(
            deps["chat_handler"]._awareness_sent
        )

    def test_sync_calls_agent_command_handler_set_project_handler(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["agent_command_handler"].set_project_handler.assert_called_once_with(
            deps["project_handler"]
        )

    def test_sync_calls_agent_command_handler_set_project_path_provider_with_lambda(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        # The exact lambda shape is preserved: returns project_handler's
        # active path if project_handler is truthy, else None.
        deps["agent_command_handler"].set_project_path_provider.assert_called_once()
        # Capture the lambda and invoke it to verify behavior
        passed_lambda = deps[
            "agent_command_handler"
        ].set_project_path_provider.call_args.args[0]
        assert callable(passed_lambda)
        assert passed_lambda() == "/tmp/test-project"


class TestAgentDefsLoaderImport:
    """The try/except around `from utils.agent_defs import load_agent_defs` is
    intentional — agent_defs is optional at startup. Verify both branches."""

    def test_sync_calls_set_agent_defs_loader_when_import_succeeds(
        self, handler, deps, gw, monkeypatch
    ):
        """If utils.agent_defs imports cleanly (current state), the loader
        IS passed to set_agent_defs_loader."""
        # utils.agent_defs is already importable in the test env (verified
        # in Phase 3a-1). We just confirm set_agent_defs_loader is called.
        handler.sync(gw)
        deps["agent_command_handler"].set_agent_defs_loader.assert_called_once()

    def test_sync_silently_skips_set_agent_defs_loader_when_import_fails(
        self, handler, deps, gw, monkeypatch
    ):
        """If the import raises, sync() must not raise, and set_agent_defs_loader
        must NOT be called. This is the bare-except preservation rule."""
        # Force the import inside sync() to fail by patching the module so
        # the import statement raises ImportError.
        import sys
        # Simulate the import failure by removing the module from sys.modules
        # and inserting a stub that raises on attribute access. Cleanest:
        # patch utils.agent_defs to be a MagicMock that raises on the
        # specific attribute.
        saved = sys.modules.get("utils.agent_defs")
        fake_mod = MagicMock()
        # Make the `from utils.agent_defs import load_agent_defs` succeed at
        # first (so the module loads), but raise on accessing load_agent_defs.
        # Actually, `from X import Y` first imports X, then accesses Y. So
        # we want X import to fail. We do that by setting X to None in
        # sys.modules, which makes `from X import Y` raise ImportError.
        sys.modules["utils.agent_defs"] = None  # forces ImportError on import
        try:
            handler.sync(gw)  # must NOT raise
        finally:
            # Restore
            if saved is not None:
                sys.modules["utils.agent_defs"] = saved
            else:
                sys.modules.pop("utils.agent_defs", None)

        deps["agent_command_handler"].set_agent_defs_loader.assert_not_called()


class TestAuditReportWiring:
    """sync() wires the audit-report → feed-card callback into AgentCommandHandler."""

    def test_sync_calls_set_on_audit_report_with_lambda_calling_feed_handler(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["agent_command_handler"].set_on_audit_report.assert_called_once()
        # Invoke the lambda with a fake report and verify it calls
        # feed_handler.add_audit_report_card with the report + project name.
        passed_lambda = deps[
            "agent_command_handler"
        ].set_on_audit_report.call_args.args[0]
        fake_report = {"summary": "all good"}
        passed_lambda(fake_report)
        deps["feed_handler"].add_audit_report_card.assert_called_once_with(
            fake_report, project_name="test-project"
        )


class TestSessionAndRefreshWiring:
    """sync() wires AgentManager into SessionHandler and refreshes the left
    panel if a project is currently open."""

    def test_sync_calls_session_handler_set_agent_manager(self, handler, deps, gw):
        handler.sync(gw)
        deps["session_handler"].set_agent_manager.assert_called_once_with(
            deps["agent_mgr"]
        )

    def test_sync_calls_left_panel_refresh_when_project_active(
        self, handler, deps, gw
    ):
        """If project_handler.get_active_project_name() returns a name, sync()
        calls left_panel.refresh_agents_with_project with that name."""
        deps["project_handler"].get_active_project_name.return_value = "my-project"
        handler.sync(gw)
        deps["left_panel"].refresh_agents_with_project.assert_called_once_with(
            "my-project"
        )

    def test_sync_skips_left_panel_refresh_when_no_active_project(
        self, handler, deps, gw
    ):
        """If project_handler.get_active_project_name() returns None, sync()
        does NOT call left_panel.refresh_agents_with_project."""
        deps["project_handler"].get_active_project_name.return_value = None
        handler.sync(gw)
        deps["left_panel"].refresh_agents_with_project.assert_not_called()


class TestActivityHandlerWiring:
    """sync() wires 4 lifecycle callbacks from ChatHandler into ActivityHandler."""

    def test_sync_calls_activity_handler_set_on_lifecycle_completed(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps[
            "activity_handler"
        ].set_on_lifecycle_completed.assert_called_once_with(
            deps["chat_handler"]._handle_lifecycle_completed
        )

    def test_sync_calls_activity_handler_set_on_assistant_buffer(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["activity_handler"].set_on_assistant_buffer.assert_called_once_with(
            deps["chat_handler"]._buffer_assistant_text
        )

    def test_sync_calls_activity_handler_set_on_agent_start(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        deps["activity_handler"].set_on_agent_start.assert_called_once_with(
            deps["chat_handler"]._clear_render_guard
        )

    def test_sync_calls_activity_handler_set_on_activity_bubble(
        self, handler, deps, gw
    ):
        # SPEC-activity-drawer Phase 1: set_on_activity_bubble is only called
        # when an ActivityDrawer has been provided via set_activity_drawer().
        # Without a drawer, no wiring happens (drawer is None by default).
        handler.sync(gw)
        # No drawer was set in this test, so set_on_activity_bubble should not have been called.
        deps["activity_handler"].set_on_activity_bubble.assert_not_called()

    def test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer(
        self, handler, deps, gw
    ):
        # SPEC-activity-drawer Phase 1: when an ActivityDrawer is set,
        # set_on_activity_bubble is wired to drawer.append_event (not the
        # removed _render_activity_bubble).
        mock_drawer = MagicMock()
        handler.set_activity_drawer(mock_drawer)
        handler.sync(gw)
        deps["activity_handler"].set_on_activity_bubble.assert_called_once_with(
            mock_drawer.append_event
        )


class TestOrder:
    """sync() is documented to perform wiring in a specific order — verify the
    setters that depend on gateway_handler.agent_mgr being live (i.e. setters
    that read it) get the same value. This protects against a regression
    where someone reorders the body and accidentally reads agent_mgr before
    it's been populated."""

    def test_all_set_agent_manager_calls_receive_the_same_agent_mgr(
        self, handler, deps, gw
    ):
        handler.sync(gw)
        # set_agent_manager is called on: main_content, command_handler,
        # project_handler, agent_command_handler, session_handler, chat_handler.
        # Total = 6 calls (one per handler). All should receive deps["agent_mgr"].
        all_callers = [
            deps["main_content"],
            deps["command_handler"],
            deps["project_handler"],
            deps["agent_command_handler"],
            deps["session_handler"],
            deps["chat_handler"],
        ]
        for caller in all_callers:
            assert caller.set_agent_manager.call_count == 1, (
                f"{caller._mock_name or 'mock'} received set_agent_manager "
                f"{caller.set_agent_manager.call_count} times, expected 1"
            )
            for call in caller.set_agent_manager.call_args_list:
                assert call.args == (deps["agent_mgr"],), (
                    f"{caller._mock_name} got {call.args!r}, expected ({deps['agent_mgr']!r},)"
                )

        # Aggregate count: 6 distinct callers × 1 call each = 6
        total = sum(
            caller.set_agent_manager.call_count for caller in all_callers
        )
        assert total == 6
