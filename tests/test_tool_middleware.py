"""Tests for agent/tool_middleware.py — spec-compliant middleware tests.

Covers spec §A.5 test cases:
  - EnforcementMiddleware (7): non-write, failed-write, append-message,
    globally-disabled, agent-disabled, dispatch-status, no-status-callback
  - StuckDetectionMiddleware (3): not-stuck, appends-message, correct-session-key
  - ToolMiddlewareChain (3): executes-in-order, short-circuit, pass-through
  - Sad-path (3): enforcement raises, stuck raises, empty-chain
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.tool_middleware import (
    EnforcementMiddleware,
    StuckDetectionMiddleware,
    ToolContext,
    ToolMiddleware,
    ToolMiddlewareChain,
)
from agent.tools import ToolResult


# ======================================================================
# Helpers
# ======================================================================


def _make_context(**overrides) -> ToolContext:
    """Create a ToolContext with sensible test defaults."""
    return ToolContext(
        session_key="test-session",
        project_path="/tmp/test",
        iteration=0,
        **overrides,
    )


def _make_result(
    success: bool = True,
    output: str = "",
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        success=success,
        output=output,
        error=error,
        duration_ms=0,
        stdout="",
        stderr="",
        exit_code=0,
    )


def _ok_executor(*args, **kwargs) -> ToolResult:
    """Executor that always succeeds."""
    return _make_result(success=True, output="done")


def _fail_executor(*args, **kwargs) -> ToolResult:
    """Executor that always fails."""
    return _make_result(success=False, error="fail")


# ======================================================================
# EnforcementMiddleware (7 tests)
# ======================================================================


class TestEnforcementMiddleware:

    def test_passes_through_non_write_tool(self):
        """Non-write tools bypass enforcement check entirely."""
        check_fn = MagicMock()
        mw = EnforcementMiddleware(check_fn)
        result = mw("read_file", {"path": "x.py"}, _make_context(), _ok_executor)
        assert result.success is True
        check_fn.assert_not_called()

    def test_passes_through_failed_write(self):
        """Failed writes bypass enforcement check."""
        check_fn = MagicMock()
        mw = EnforcementMiddleware(check_fn)
        result = mw("write_file", {"path": "x.py"}, _make_context(), _fail_executor)
        assert result.success is False
        check_fn.assert_not_called()

    def test_appends_message_on_success(self):
        """Successful write appends enforcement result to output."""
        enf_result = MagicMock()
        enf_result.appended_message = "[enforcement:syntax] ✅ OK"
        enf_result.checks = []
        check_fn = MagicMock(return_value=enf_result)
        mw = EnforcementMiddleware(check_fn)

        ctx = _make_context(
            enforcement_config=MagicMock(enabled=True),
        )
        result = mw("write_file", {"path": "f.py"}, ctx, _ok_executor)

        check_fn.assert_called_once()
        assert "[enforcement:syntax] ✅ OK" in result.output

    def test_skips_when_globally_disabled(self):
        """enforcement_config=None skips enforcement."""
        check_fn = MagicMock()
        mw = EnforcementMiddleware(check_fn)
        ctx = _make_context(enforcement_config=None)
        result = mw("edit_file", {"path": "f.py"}, ctx, _ok_executor)
        assert result.success is True
        check_fn.assert_not_called()

    def test_skips_when_agent_disabled(self):
        """si_enforcement=False skips enforcement."""
        check_fn = MagicMock()
        mw = EnforcementMiddleware(check_fn)
        ctx = _make_context(
            enforcement_config=MagicMock(enabled=True),
            si_enforcement=False,
        )
        result = mw("write_file", {"path": "f.py"}, ctx, _ok_executor)
        assert result.success is True
        check_fn.assert_not_called()

    def test_dispatches_status_per_check(self):
        """on_status callback invoked for each check record."""
        enf_result = MagicMock()
        enf_result.appended_message = "syntax+lint checked"
        check1 = MagicMock(tier="syntax", file="f.py", passed=True, detail="OK")
        check2 = MagicMock(tier="lint", file="f.py", passed=True, detail="OK")
        enf_result.checks = [check1, check2]
        check_fn = MagicMock(return_value=enf_result)

        on_status = MagicMock()
        mw = EnforcementMiddleware(check_fn, on_status=on_status)
        ctx = _make_context(
            session_key="sk",
            enforcement_config=MagicMock(enabled=True),
        )
        mw("write_file", {"path": "f.py"}, ctx, _ok_executor)

        assert on_status.call_count == 2

    def test_no_status_callback_is_safe(self):
        """on_status=None does not crash."""
        enf_result = MagicMock()
        enf_result.appended_message = "checked"
        enf_result.checks = []
        check_fn = MagicMock(return_value=enf_result)
        mw = EnforcementMiddleware(check_fn, on_status=None)
        ctx = _make_context(
            enforcement_config=MagicMock(enabled=True),
        )
        result = mw("write_file", {"path": "f.py"}, ctx, _ok_executor)
        assert result.success is True


# ======================================================================
# StuckDetectionMiddleware (3 tests)
# ======================================================================


class TestStuckDetectionMiddleware:

    def test_no_message_when_not_stuck(self):
        """stuck_check_fn returning None → no pending message."""
        pending: dict[str, list[str]] = {}
        stuck_fn = MagicMock(return_value=None)
        mw = StuckDetectionMiddleware(stuck_fn, pending)
        ctx = _make_context(session_key="sk")
        result = mw("write_file", {"path": "f.py"}, ctx, _ok_executor)
        assert result.success is True
        assert pending == {}
        stuck_fn.assert_called_once_with("sk", "write_file", {"path": "f.py"}, 0)

    def test_appends_message_when_stuck(self):
        """stuck_check_fn returning a message → appended to pending."""
        pending: dict[str, list[str]] = {}
        stuck_fn = MagicMock(return_value="You are stuck on write_file")
        mw = StuckDetectionMiddleware(stuck_fn, pending)
        ctx = _make_context(session_key="sk")
        result = mw("write_file", {"path": "f.py"}, ctx, _ok_executor)
        assert result.success is True
        assert pending["sk"] == ["You are stuck on write_file"]

    def test_uses_correct_session_key(self):
        """Message keyed to the correct session."""
        pending: dict[str, list[str]] = {}
        stuck_fn = MagicMock(return_value="stuck msg")
        mw = StuckDetectionMiddleware(stuck_fn, pending)
        ctx = _make_context(session_key="special:coder")
        mw("write_file", {"path": "f.py"}, ctx, _ok_executor)
        assert "special:coder" in pending
        assert "test-session" not in pending


# ======================================================================
# ToolMiddlewareChain (3 tests)
# ======================================================================


class TestToolMiddlewareChain:

    def test_executes_in_order(self):
        """Middlewares execute in registration order."""
        order: list[str] = []

        class MW1:
            def __call__(self, tool_name, args, ctx, next):
                order.append("mw1")
                return next()

        class MW2:
            def __call__(self, tool_name, args, ctx, next):
                order.append("mw2")
                return next()

        chain = ToolMiddlewareChain([MW1(), MW2()])
        result = chain.run("read_file", {}, _make_context(), _ok_executor)
        assert result.success is True
        assert order == ["mw1", "mw2"]

    def test_short_circuit_does_not_reach_executor(self):
        """Middleware returning early prevents executor from running."""
        executor = MagicMock(wraps=_ok_executor)

        class ShortCircuit:
            def __call__(self, tool_name, args, ctx, next):
                return _make_result(success=True, output="short-circuited")

        chain = ToolMiddlewareChain([ShortCircuit()])
        result = chain.run("exec_command", {}, _make_context(), executor)
        assert result.output == "short-circuited"
        executor.assert_not_called()

    def test_executor_result_passes_through(self):
        """No-middleware chain passes executor result unchanged."""
        chain = ToolMiddlewareChain([])
        result = chain.run("read_file", {}, _make_context(), _ok_executor)
        assert result.success is True
        assert result.output == "done"


# ======================================================================
# Sad-path (3 tests)
# ======================================================================


class TestSadPath:

    def test_enforcement_check_raises_does_not_crash_loop(self):
        """Exception in enforcement_check is caught; original result returned."""
        def crash_check(*args, **kwargs):
            raise RuntimeError("enforcement check exploded")

        mw = EnforcementMiddleware(crash_check)
        ctx = _make_context(
            enforcement_config=MagicMock(enabled=True),
        )
        result = mw("write_file", {"path": "crash.py"}, ctx, _ok_executor)
        assert result.success is True
        assert result.output == "done"

    def test_stuck_check_raises_does_not_crash_loop(self):
        """Exception in stuck_check is caught; original result returned."""
        def crash_stuck(*args, **kwargs):
            raise RuntimeError("stuck check exploded")

        pending: dict[str, list[str]] = {}
        mw = StuckDetectionMiddleware(crash_stuck, pending)
        ctx = _make_context(session_key="sk")
        result = mw("read_file", {"path": "x.py"}, ctx, _ok_executor)
        assert result.success is True
        assert pending == {}

    def test_chain_with_empty_middleware_list(self):
        """Empty middleware list → executor called directly."""
        executor = MagicMock(return_value=_make_result(success=True, output="direct"))
        chain = ToolMiddlewareChain([])
        result = chain.run("write_file", {}, _make_context(), executor)
        assert result.success is True
        assert result.output == "direct"
        executor.assert_called_once()


# ======================================================================
# ToolContext dataclass
# ======================================================================


class TestToolContext:

    def test_default_fields(self):
        """Defaults match spec §A.2.1."""
        ctx = ToolContext(session_key="sk", project_path="/p", iteration=0)
        assert ctx.bypass_approval is False
        assert ctx.audit_log is None
        assert ctx.user_id == ""
        assert ctx.enforcement_config is None
        assert ctx.si_enforcement is None

    def test_all_fields(self):
        """All fields settable via constructor."""
        audit_log = object()
        enf_cfg = object()
        ctx = ToolContext(
            session_key="sk",
            project_path="/p",
            iteration=5,
            bypass_approval=True,
            audit_log=audit_log,
            user_id="alice",
            enforcement_config=enf_cfg,
            si_enforcement=False,
        )
        assert ctx.session_key == "sk"
        assert ctx.project_path == "/p"
        assert ctx.iteration == 5
        assert ctx.bypass_approval is True
        assert ctx.audit_log is audit_log
        assert ctx.user_id == "alice"
        assert ctx.enforcement_config is enf_cfg
        assert ctx.si_enforcement is False


# ======================================================================
# ToolMiddleware Protocol — instantiation guard
# ======================================================================


class TestToolMiddlewareProtocol:

    def test_cannot_instantiate_protocol(self):
        """Plain Protocol class has no __init__."""
        # ToolMiddleware is a Protocol — no instantiation expected
        with pytest.raises(TypeError):
            ToolMiddleware()  # type: ignore[abstract]

    def test_concrete_class_works(self):
        """A callable that matches the protocol works as ToolMiddleware."""
        class Concrete:
            def __call__(self, tool_name, args, ctx, next):
                return _make_result(success=True, output="concrete")

        instance = Concrete()
        assert callable(instance)
