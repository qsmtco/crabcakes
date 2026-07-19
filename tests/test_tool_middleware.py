"""Tests for agent/tool_middleware.py.

Exercises EnforcementMiddleware, StuckDetectionMiddleware, and
ToolMiddlewareChain in isolation (no AgentRuntime instance required).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.config import EnforcementConfig
from agent.enforcement import EnforcementCheck, EnforcementResult
from agent.tool_middleware import (
    EnforcementMiddleware,
    StuckDetectionMiddleware,
    ToolContext,
    ToolMiddlewareChain,
)
from agent.tools import ToolResult


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_result(success: bool = True, output: str = "") -> ToolResult:
    return ToolResult(success=success, output=output)


def _make_context(
    session_key: str = "special:coder",
    project_path: str = "/tmp/test_project",
    iteration: int = 0,
    enforcement_config: EnforcementConfig | None = None,
    si_enforcement: bool | None = None,
) -> ToolContext:
    return ToolContext(
        session_key=session_key,
        project_path=project_path,
        iteration=iteration,
        bypass_approval=True,
        enforcement_config=enforcement_config,
        si_enforcement=si_enforcement,
    )


def _make_enf_config(enabled: bool = True) -> EnforcementConfig:
    return EnforcementConfig(enabled=enabled)


# ── EnforcementMiddleware tests ────────────────────────────────────────────────


class TestEnforcementMiddleware:
    """7 test cases: pass-through, append, gates, status dispatch, null safety."""

    def test_enforcement_passes_through_non_write_tool(self) -> None:
        """list_files passes through without enforcement check."""
        enf_check = MagicMock(return_value=EnforcementResult())
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(return_value=_make_result(output="file1.txt"))

        result = mw("list_files", {"path": "."}, _make_context(), executor)

        assert result.success is True
        assert result.output == "file1.txt"
        enf_check.assert_not_called()

    def test_enforcement_passes_through_failed_write(self) -> None:
        """write_file with success=False skips enforcement."""
        enf_check = MagicMock()
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(
            return_value=_make_result(success=False, output="error: permission denied")
        )

        result = mw("write_file", {"path": "test.py"}, _make_context(), executor)

        assert result.success is False
        enf_check.assert_not_called()

    def test_enforcement_appends_message_on_success(self) -> None:
        """Successful write with enforcement result appends message to output."""
        enf_check = MagicMock(
            return_value=EnforcementResult(
                checks=[],
                appended_message="Syntax: OK\nTests: 3 passed",
            )
        )
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(return_value=_make_result(output="wrote 42 bytes"))

        result = mw(
            "write_file",
            {"path": "src/test.py"},
            _make_context(enforcement_config=_make_enf_config()),
            executor,
        )

        assert result.success is True
        assert "wrote 42 bytes" in result.output
        assert "Syntax: OK" in result.output
        assert "Tests: 3 passed" in result.output

    def test_enforcement_skips_when_globally_disabled(self) -> None:
        """enforcement_config.enabled=False skips enforcement."""
        enf_check = MagicMock()
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(
            return_value=_make_result(output="wrote 42 bytes")
        )

        result = mw(
            "write_file",
            {"path": "src/test.py"},
            _make_context(enforcement_config=_make_enf_config(enabled=False)),
            executor,
        )

        assert result.success is True
        assert result.output == "wrote 42 bytes"
        enf_check.assert_not_called()

    def test_enforcement_skips_when_agent_disabled(self) -> None:
        """si_enforcement=False skips enforcement even when global config is on."""
        enf_check = MagicMock()
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(
            return_value=_make_result(output="wrote 42 bytes")
        )

        result = mw(
            "write_file",
            {"path": "src/test.py"},
            _make_context(
                enforcement_config=_make_enf_config(enabled=True),
                si_enforcement=False,
            ),
            executor,
        )

        assert result.success is True
        assert result.output == "wrote 42 bytes"
        enf_check.assert_not_called()

    def test_enforcement_dispatches_status_per_check(self) -> None:
        """on_status is called for each check in the enforcement result."""
        on_status = MagicMock()
        enf_check = MagicMock(
            return_value=EnforcementResult(
                checks=[
                    EnforcementCheck(
                        tier="syntax", tool="write_file", file="test.py",
                        passed=True, detail="Syntax OK", output="", duration_ms=5,
                    ),
                    EnforcementCheck(
                        tier="tests", tool="write_file", file="test.py",
                        passed=True, detail="3 passed", output="...", duration_ms=300,
                    ),
                ],
                appended_message="Syntax: OK\nTests: 3 passed",
            )
        )
        mw = EnforcementMiddleware(enf_check, on_status=on_status)
        executor = MagicMock(return_value=_make_result(output="wrote 42 bytes"))

        result = mw(
            "write_file",
            {"path": "test.py"},
            _make_context(enforcement_config=_make_enf_config()),
            executor,
        )

        assert result.success is True
        assert on_status.call_count == 2
        on_status.assert_any_call(
            "special:coder", "write_file",
            {"tier": "syntax", "file": "test.py", "passed": True, "detail": "Syntax OK"},
        )
        on_status.assert_any_call(
            "special:coder", "write_file",
            {"tier": "tests", "file": "test.py", "passed": True, "detail": "3 passed"},
        )

    def test_enforcement_no_status_callback_is_safe(self) -> None:
        """on_status=None does not crash when enforcement has checks."""
        enf_check = MagicMock(
            return_value=EnforcementResult(
                checks=[
                    EnforcementCheck(
                        tier="syntax", tool="write_file", file="test.py",
                        passed=True, detail="Syntax OK", output="", duration_ms=5,
                    ),
                ],
                appended_message="Syntax: OK",
            )
        )
        mw = EnforcementMiddleware(enf_check, on_status=None)
        executor = MagicMock(return_value=_make_result(output="wrote 42 bytes"))

        result = mw(
            "write_file",
            {"path": "test.py"},
            _make_context(enforcement_config=_make_enf_config()),
            executor,
        )

        assert result.success is True
        assert "Syntax: OK" in result.output


# ── StuckDetectionMiddleware tests ─────────────────────────────────────────────


class TestStuckDetectionMiddleware:
    """3 test cases: not stuck, stuck appended, correct session key."""

    def test_stuck_no_message_when_not_stuck(self) -> None:
        """When _check_stuck returns None, no pending message."""
        pending: dict[str, list[str]] = {}
        stuck_check = MagicMock(return_value=None)
        mw = StuckDetectionMiddleware(stuck_check, pending)
        executor = MagicMock(return_value=_make_result(output="done"))

        result = mw("list_files", {}, _make_context(), executor)

        assert result.success is True
        assert result.output == "done"
        assert pending == {}

    def test_stuck_appends_message_when_stuck(self) -> None:
        """When _check_stuck returns a message, it is appended to pending."""
        pending: dict[str, list[str]] = {}
        stuck_check = MagicMock(return_value="You're stuck in a loop")
        mw = StuckDetectionMiddleware(stuck_check, pending)
        executor = MagicMock(return_value=_make_result(output="done"))

        result = mw("read_file", {"path": "x.py"}, _make_context(), executor)

        assert result.success is True
        assert pending == {"special:coder": ["You're stuck in a loop"]}

    def test_stuck_uses_correct_session_key(self) -> None:
        """Pending messages are keyed to the correct session key."""
        pending: dict[str, list[str]] = {"other:agent": ["old"]}
        stuck_check = MagicMock(return_value="stuck detected")
        mw = StuckDetectionMiddleware(stuck_check, pending)
        ctx = _make_context(session_key="special:debugger")
        executor = MagicMock(return_value=_make_result(output="done"))

        result = mw("edit_file", {"path": "x.py"}, ctx, executor)

        assert result.success is True
        assert "special:debugger" in pending
        assert pending["special:debugger"] == ["stuck detected"]
        assert pending["other:agent"] == ["old"]


# ── ToolMiddlewareChain tests ──────────────────────────────────────────────────


class TestToolMiddlewareChain:
    """3 test cases: execution order, short-circuit, executor passthrough."""

    def test_chain_executes_in_order(self) -> None:
        """Middleware wrap each other in registration order."""
        call_order: list[str] = []

        def mw1(tool_name, args, ctx, next_fn):
            call_order.append("mw1_before")
            result = next_fn()
            call_order.append("mw1_after")
            return result

        def mw2(tool_name, args, ctx, next_fn):
            call_order.append("mw2_before")
            result = next_fn()
            call_order.append("mw2_after")
            return result

        chain = ToolMiddlewareChain([mw1, mw2])
        executor = MagicMock(return_value=_make_result(output="executed"))

        result = chain.run("echo", {}, _make_context(), executor)

        assert result.success is True
        assert result.output == "executed"
        assert call_order == [
            "mw1_before", "mw2_before", "mw2_after", "mw1_after",
        ]
        executor.assert_called_once()

    def test_chain_short_circuit_does_not_reach_executor(self) -> None:
        """Middleware that returns early prevents executor from running."""
        def short_circuit(tool_name, args, ctx, next_fn):
            return _make_result(success=False, output="blocked by mw")

        chain = ToolMiddlewareChain([short_circuit])
        executor = MagicMock()

        result = chain.run("exec_command", {}, _make_context(), executor)

        assert result.success is False
        assert result.output == "blocked by mw"
        executor.assert_not_called()

    def test_chain_executor_result_passes_through(self) -> None:
        """Without modifying middleware, executor result is returned unchanged."""
        chain = ToolMiddlewareChain([])
        executor = MagicMock(
            return_value=_make_result(success=True, output="hello world")
        )

        result = chain.run("list_files", {"path": "."}, _make_context(), executor)

        assert result.success is True
        assert result.output == "hello world"
        executor.assert_called_once()


# ── Sad-path tests ─────────────────────────────────────────────────────────────


class TestSadPath:
    """3 sad-path tests: enforcement crash, stuck crash, empty chain."""

    def test_enforcement_check_raises_does_not_crash_loop(self) -> None:
        """Exception in enforcement.check is caught; original result returned."""
        enf_check = MagicMock(side_effect=RuntimeError("enforcement crashed"))
        mw = EnforcementMiddleware(enf_check)
        executor = MagicMock(return_value=_make_result(output="wrote 42 bytes"))

        with patch("agent.tool_middleware.logger.exception") as mock_exc:
            result = mw(
                "write_file",
                {"path": "crash.py"},
                _make_context(enforcement_config=_make_enf_config()),
                executor,
            )

        assert result.success is True
        assert result.output == "wrote 42 bytes"
        mock_exc.assert_called_once()

    def test_stuck_check_raises_does_not_crash_loop(self) -> None:
        """Exception in stuck_check is caught; original result returned."""
        pending: dict[str, list[str]] = {}
        stuck_check = MagicMock(side_effect=ValueError("stuck check failed"))
        mw = StuckDetectionMiddleware(stuck_check, pending)
        executor = MagicMock(return_value=_make_result(output="done"))

        with patch("agent.tool_middleware.logger.exception") as mock_exc:
            result = mw("read_file", {"path": "x.py"}, _make_context(), executor)

        assert result.success is True
        assert result.output == "done"
        assert pending == {}
        mock_exc.assert_called_once()

    def test_chain_with_empty_middleware_list(self) -> None:
        """Empty middleware list results in executor being called directly."""
        chain = ToolMiddlewareChain([])
        executor = MagicMock(
            return_value=ToolResult(success=True, output="direct call")
        )

        result = chain.run("write_file", {"path": "f.py"}, _make_context(), executor)

        assert result.success is True
        assert result.output == "direct call"
        executor.assert_called_once()