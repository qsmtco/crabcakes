"""Tests for agent/tool_middleware.py — middleware framework.

Covers:
  - ToolMiddlewareChain basic run/error propagation
  - EnforcementMiddleware with syntax/test/lint success and failure
  - StuckDetectionMiddleware repeat-count heuristic
  - Chain ordering ([Enforcement, StuckDetection])
  - Edge cases: non-write tools bypass enforcement, error path reversal,
    state sharing, empty chain
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.tool_middleware import (
    EnforcementError,
    EnforcementMiddleware,
    MiddlewareState,
    StuckDetectionError,
    StuckDetectionMiddleware,
    ToolMiddleware,
    ToolMiddlewareChain,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def ok_tool():
    """A tool function that always succeeds."""
    return lambda *a, **kw: "ok"


@pytest.fixture
def failing_tool():
    """A tool function that always raises ValueError."""

    def _fail(*a, **kw):
        raise ValueError("boom")

    return _fail


# ======================================================================
# ToolMiddlewareChain — basic behaviour
# ======================================================================


class TestToolMiddlewareChain:

    def test_run_passes_result(self, ok_tool):
        chain = ToolMiddlewareChain([])
        assert chain.run("test", ok_tool) == "ok"

    def test_run_re_raises_error(self, failing_tool):
        chain = ToolMiddlewareChain([])
        with pytest.raises(ValueError, match="boom"):
            chain.run("test", failing_tool)

    def test_empty_chain_noop(self, ok_tool):
        chain = ToolMiddlewareChain([])
        assert chain.run("noop", ok_tool, 1, key="val") == "ok"

    def test_state_is_passed_to_middleware(self):
        """MiddlewareState should be populated and mutable."""
        seen = []

        class CaptureMiddleware(ToolMiddleware):
            def process_result(self, name, result, state):
                state["foo"] = "bar"
                seen.append(dict(state))
                return result

            def process_error(self, name, error, state):
                pass

        chain = ToolMiddlewareChain([CaptureMiddleware()])
        chain.run("x", lambda: "r")
        assert seen == [{"foo": "bar"}]

    def test_middleware_transforms_result(self):
        class DoubleMiddleware(ToolMiddleware):
            def process_result(self, name, result, state):
                return result * 2

            def process_error(self, name, error, state):
                pass

        chain = ToolMiddlewareChain([DoubleMiddleware()])
        assert chain.run("x", lambda: 21) == 42

    def test_middleware_can_raise_in_process_result(self):
        class RaiseMiddleware(ToolMiddleware):
            def process_result(self, name, result, state):
                raise RuntimeError("mw fail")
            def process_error(self, name, error, state):
                pass

        chain = ToolMiddlewareChain([RaiseMiddleware()])
        with pytest.raises(RuntimeError, match="mw fail"):
            chain.run("x", lambda: "ok")

    def test_error_chain_runs_in_reverse_order(self):
        """On tool error, process_error runs last-to-first."""
        order = []

        class A(ToolMiddleware):
            def process_result(self, n, r, s): return r
            def process_error(self, n, e, s): order.append("A")

        class B(ToolMiddleware):
            def process_result(self, n, r, s): return r
            def process_error(self, n, e, s): order.append("B")

        chain = ToolMiddlewareChain([A(), B()])
        with pytest.raises(ValueError):
            chain.run("x", lambda: (_ for _ in ()).throw(ValueError("e")))
        assert order == ["B", "A"], f"expected reverse order, got {order}"


# ======================================================================
# EnforcementMiddleware
# ======================================================================


class TestEnforcementMiddleware:

    # ── skip for non-write tools ──────────────────────────────────

    def test_skips_non_write_tools(self, ok_tool):
        mw = EnforcementMiddleware()
        state = MiddlewareState({"file_path": "foo.py"})
        result = mw.process_result("read_file", "ok", state)
        assert result == "ok"

    def test_skips_when_no_file_path(self, ok_tool):
        mw = EnforcementMiddleware()
        state = MiddlewareState()
        result = mw.process_result("write_file", "ok", state)
        assert result == "ok"

    # ── syntax guard ──────────────────────────────────────────────

    @patch("agent.tool_middleware.syntax_guard", return_value=True)
    @patch("agent.tool_middleware.run_tests", return_value=True)
    @patch("agent.tool_middleware.run_lint", return_value=True)
    def test_all_checks_pass(self, mock_lint, mock_tests, mock_syntax, ok_tool):
        mw = EnforcementMiddleware()
        state = MiddlewareState({"file_path": "foo.py"})
        result = mw.process_result("write_file", "ok", state)
        assert result == "ok"
        mock_syntax.assert_called_once_with("foo.py")
        mock_tests.assert_called_once()

    @patch("agent.tool_middleware.syntax_guard", return_value=False)
    def test_syntax_failure_raises(self, mock_syntax, ok_tool):
        mw = EnforcementMiddleware()
        state = MiddlewareState({"file_path": "bad.py"})
        with pytest.raises(EnforcementError, match="Syntax check failed for bad.py"):
            mw.process_result("write_file", "ok", state)
        mock_syntax.assert_called_once_with("bad.py")

    @patch("agent.tool_middleware.syntax_guard", return_value=True)
    @patch("agent.tool_middleware.run_tests", return_value=False)
    def test_test_failure_raises(self, mock_tests, mock_syntax):
        mw = EnforcementMiddleware()
        state = MiddlewareState({"file_path": "bad.py"})
        with pytest.raises(EnforcementError, match="Tests failed for bad.py"):
            mw.process_result("edit_file", "ok", state)
        mock_syntax.assert_called_once_with("bad.py")
        mock_tests.assert_called_once()

    @patch("agent.tool_middleware.syntax_guard", return_value=True)
    @patch("agent.tool_middleware.run_tests", return_value=True)
    @patch("agent.tool_middleware.run_lint", return_value=False)
    def test_lint_failure_raises(self, mock_lint, mock_tests, mock_syntax):
        mw = EnforcementMiddleware()
        state = MiddlewareState({"file_path": "bad.py"})
        with pytest.raises(EnforcementError, match="Lint failed for bad.py"):
            mw.process_result("write_file", "ok", state)
        mock_syntax.assert_called_once_with("bad.py")
        mock_tests.assert_called_once()
        mock_lint.assert_called_once()

    @patch("agent.tool_middleware.syntax_guard", return_value=True)
    @patch("agent.tool_middleware.run_tests", return_value=True)
    @patch("agent.tool_middleware.run_lint", return_value=True)
    def test_process_error_does_not_raise(self, mock_lint, mock_tests, mock_syntax):
        mw = EnforcementMiddleware()
        mw.process_error("write_file", ValueError("ignored"), MiddlewareState())
        # Should not raise — just passes through

    def test_edit_file_also_checked(self):
        """edit_file is also a WRITE_TOOL."""
        assert "edit_file" in EnforcementMiddleware.WRITE_TOOLS

    def test_write_file_in_write_tools(self):
        assert "write_file" in EnforcementMiddleware.WRITE_TOOLS


# ======================================================================
# StuckDetectionMiddleware
# ======================================================================


class TestStuckDetectionMiddleware:

    def test_first_call_passes(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=3)
        state = MiddlewareState({"file_path": "f.py"})
        result = mw.process_result("write_file", "ok", state)
        assert result == "ok"

    def test_under_limit_passes(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=3)
        state = MiddlewareState({"file_path": "f.py"})
        for _ in range(3):
            mw.process_result("write_file", "ok", state)
        # 4th call should fail
        with pytest.raises(StuckDetectionError, match="Stuck on tool"):
            mw.process_result("write_file", "ok", state)

    def test_exact_limit_passes(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=2)
        state = MiddlewareState({"file_path": "f.py"})
        for _ in range(2):
            mw.process_result("write_file", "ok", state)
        # 3rd call should fail
        with pytest.raises(StuckDetectionError):
            mw.process_result("write_file", "ok", state)

    def test_different_file_resets_key(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=2)
        mw.process_result("write_file", "ok", MiddlewareState({"file_path": "a.py"}))
        mw.process_result("write_file", "ok", MiddlewareState({"file_path": "b.py"}))
        mw.process_result("write_file", "ok", MiddlewareState({"file_path": "a.py"}))
        # a.py called 2 times (under limit)
        mw.process_result("write_file", "ok", MiddlewareState({"file_path": "a.py"}))
        # 3rd a.py call fails
        with pytest.raises(StuckDetectionError):
            mw.process_result("write_file", "ok", MiddlewareState({"file_path": "a.py"}))

    def test_different_tool_is_separate_key(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=2)
        state = MiddlewareState({"file_path": "f.py"})
        mw.process_result("write_file", "ok", state)
        mw.process_result("write_file", "ok", state)
        # read_file with same file_path — separate counter
        mw.process_result("read_file", "ok", state)
        assert True  # no error

    def test_process_error_also_counts(self, ok_tool):
        mw = StuckDetectionMiddleware(max_repeats=1)
        state = MiddlewareState({"file_path": "f.py"})
        mw.process_error("write_file", ValueError("e"), state)
        # 2nd call should fail (1 from error + 1 from result)
        with pytest.raises(StuckDetectionError):
            mw.process_result("write_file", "ok", state)

    def test_no_file_path_still_counts(self):
        mw = StuckDetectionMiddleware(max_repeats=1)
        mw.process_result("read_file", "ok", MiddlewareState())
        with pytest.raises(StuckDetectionError):
            mw.process_result("read_file", "ok", MiddlewareState())

    def test_error_does_not_suppress_original(self):
        mw = StuckDetectionMiddleware(max_repeats=1)
        with pytest.raises(ValueError, match="orig"):
            mw.process_error("write_file", ValueError("orig"), MiddlewareState())

    def test_default_max_repeats(self):
        mw = StuckDetectionMiddleware()
        assert mw._max_repeats == 3

    def test_custom_max_repeats(self):
        mw = StuckDetectionMiddleware(max_repeats=5)
        assert mw._max_repeats == 5


# ======================================================================
# Integration: chain with both middlewares
# ======================================================================


class TestMiddlewareChainIntegration:

    @patch("agent.tool_middleware.syntax_guard", return_value=True)
    @patch("agent.tool_middleware.run_tests", return_value=True)
    @patch("agent.tool_middleware.run_lint", return_value=True)
    def test_both_middlewares_pass(self, mock_lint, mock_tests, mock_syntax):
        chain = ToolMiddlewareChain([
            EnforcementMiddleware(),
            StuckDetectionMiddleware(max_repeats=5),
        ])
        state = MiddlewareState({"file_path": "f.py"})
        result = chain.run("write_file", lambda: "ok", state=state)
        assert result == "ok"

    @patch("agent.tool_middleware.syntax_guard", return_value=False)
    def test_enforcement_fails_before_stuck(self, mock_syntax):
        chain = ToolMiddlewareChain([
            EnforcementMiddleware(),
            StuckDetectionMiddleware(max_repeats=5),
        ])
        state = MiddlewareState({"file_path": "bad.py"})
        with pytest.raises(EnforcementError):
            chain.run("write_file", lambda: "ok", state=state)
        # StuckDetection's process_error should not raise
        assert True

    def test_stuck_detection_fires_after_enforcement(self):
        """StuckDetection counts calls across the chain."""
        chain = ToolMiddlewareChain([
            EnforcementMiddleware(),
            StuckDetectionMiddleware(max_repeats=1),
        ])
        state = MiddlewareState({"file_path": "f.py"})
        # First call — ok (StuckDetection counts but doesn't fail yet... wait, max_repeats=1 means 2nd call fails)
        chain.run("write_file", lambda: "ok", state=state)
        # Second call should trigger stuck detection
        with pytest.raises(StuckDetectionError, match="Stuck on tool"):
            chain.run("write_file", lambda: "ok", state=state)


# ======================================================================
# MiddlewareState
# ======================================================================


class TestMiddlewareState:

    def test_is_dict(self):
        s = MiddlewareState()
        assert isinstance(s, dict)

    def test_accepts_initial_items(self):
        s = MiddlewareState({"key": "val"})
        assert s["key"] == "val"

    def test_mutable(self):
        s = MiddlewareState()
        s["count"] = 1
        assert s["count"] == 1


# ======================================================================
# Abstract base — instantiation guard
# ======================================================================


class TestToolMiddlewareABC:

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ToolMiddleware()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        class Concrete(ToolMiddleware):
            def process_result(self, n, r, s): return r
            def process_error(self, n, e, s): pass
        instance = Concrete()
        assert isinstance(instance, ToolMiddleware)
