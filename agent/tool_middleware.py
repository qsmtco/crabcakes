"""
Tool middleware framework for the agent runtime.

Provides an extensible middleware pipeline (ToolMiddlewareChain) that wraps
tool execution with pre/post hooks. Each middleware can inspect or transform
tool results and errors without modifying the tool functions themselves.

Chain order (Phase 1): [EnforcementMiddleware, StuckDetectionMiddleware]
"""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from typing import Any

from agent.enforcement import run_lint, run_tests, syntax_guard


# ── Middleware state ──────────────────────────────────────────────────


class MiddlewareState(dict):
    """Mutable dict shared across the middleware chain for a single tool call.

    Middleware authors can store per-call metadata here (timestamps, retry
    counts, accumulators).  The same dict is passed to every middleware in
    the chain and is discarded after the chain completes.
    """


# ── Abstract base ────────────────────────────────────────────────────


class ToolMiddleware(ABC):
    """Abstract base for a single middleware in the tool chain.

    Subclasses override ``process_result`` and/or ``process_error`` to
    add behaviour after a tool returns or raises.
    """

    @abstractmethod
    def process_result(
        self,
        name: str,
        result: Any,
        state: MiddlewareState,
    ) -> Any:
        """Inspect or transform a tool result.

        *name* — tool function name (e.g. ``\"write_file\"``).
        *result* — the raw return value of the tool function.
        *state* — mutable ``MiddlewareState`` for the current call.

        Return the (possibly modified) result, or raise an exception to
        trigger the error path.
        """

    @abstractmethod
    def process_error(
        self,
        name: str,
        error: Exception,
        state: MiddlewareState,
    ) -> None:
        """Handle a tool error.

        *name* — tool function name.
        *error* — the exception raised by the tool or a previous middleware.
        *state* — mutable ``MiddlewareState`` for the current call.

        May itself raise to propagate/replace the error, or return
        ``None`` to swallow it.
        """


# ── Chain ────────────────────────────────────────────────────────────


class ToolMiddlewareChain:
    """Ordered chain of ``ToolMiddleware`` instances.

    Usage::

        chain = ToolMiddlewareChain([EnforcementMiddleware(), ...])
        result = chain.run("write_file", tool_func, "/tmp/x.txt", state)
    """

    def __init__(self, middlewares: list[ToolMiddleware]) -> None:
        self._middlewares = list(middlewares)

    # ── public API ────────────────────────────────────────────────

    def run(
        self,
        name: str,
        tool_func: callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *tool_func(*args, **kwargs)* through the middleware chain.

        1. Extract an optional ``MiddlewareState`` from *kwargs*.
        2. Call the tool function with remaining args.
        3. On success, pass the result through every middleware's
           ``process_result`` in chain order.
        4. On error, pass the exception through every middleware's
           ``process_error`` **in reverse order** (last-to-first).

        Returns the final (possibly transformed) result.
        Raises the final (possibly transformed) error.
        """
        state: MiddlewareState = kwargs.pop("state", MiddlewareState())

        try:
            result = tool_func(*args, **kwargs)
        except Exception as exc:
            self._run_error_chain(name, exc, state)
            raise

        return self._run_result_chain(name, result, state)

    # ── internals ─────────────────────────────────────────────────

    def _run_result_chain(self, name: str, result: Any, state: MiddlewareState) -> Any:
        for mw in self._middlewares:
            try:
                result = mw.process_result(name, result, state)
            except Exception as exc:
                self._run_error_chain(name, exc, state)
                raise
        return result

    def _run_error_chain(self, name: str, error: Exception, state: MiddlewareState) -> None:
        for mw in reversed(self._middlewares):
            try:
                mw.process_error(name, error, state)
            except Exception:
                # The middleware raised a *different* error — that becomes
                # the new canonical error for the remaining chain.
                error = sys.exc_info()[1]


# ── Concrete middleware: Enforcement ────────────────────────────────


class EnforcementMiddleware(ToolMiddleware):
    """Post-write enforcement: syntax check → test run → lint.

    Delegates to ``agent.enforcement.{syntax_guard, run_tests, run_lint}``.
    Only activates for write-type tools (``write_file``, ``edit_file``).
    """

    WRITE_TOOLS = frozenset({"write_file", "edit_file"})

    def __init__(self, project_path: str = ".") -> None:
        self._project_path = project_path

    def process_result(self, name: str, result: Any, state: MiddlewareState) -> Any:
        if name not in self.WRITE_TOOLS:
            return result

        # Collect the file path from the tool arguments stored in state.
        # Tool functions are called BEFORE middleware, so the file has
        # already been written.  We rely on the caller (or a pre-hook)
        # to put the file path in state["file_path"].
        file_path: str | None = state.get("file_path")
        if not file_path:
            return result  # nothing to enforce

        # Tier 1 – syntax
        syntax_ok = syntax_guard(file_path)
        if not syntax_ok:
            raise EnforcementError(f"Syntax check failed for {file_path}")

        # Tier 2 – tests
        test_ok = run_tests(file_path, project_path=self._project_path)
        if not test_ok:
            raise EnforcementError(f"Tests failed for {file_path}")

        # Tier 3 – lint
        lint_ok = run_lint(file_path, project_path=self._project_path)
        if not lint_ok:
            raise EnforcementError(f"Lint failed for {file_path}")

        return result

    def process_error(self, name: str, error: Exception, state: MiddlewareState) -> None:
        """On error, do nothing special — let the error propagate."""
        return


class EnforcementError(RuntimeError):
    """Raised when a post-write enforcement check fails."""


# ── Concrete middleware: Stuck Detection ────────────────────────────


class StuckDetectionMiddleware(ToolMiddleware):
    """Detects when the agent is stuck on the same tool call.

    Heuristic: if the same ``(name, file_path)`` pair is called more than
    ``max_repeats`` times within the chain's lifetime, raises
    ``StuckDetectionError``.

    The middleware maintains a simple counter per session key.
    """

    def __init__(self, max_repeats: int = 3) -> None:
        self._max_repeats = max_repeats
        self._call_counter: dict[tuple[str, str | None], int] = {}

    def process_result(self, name: str, result: Any, state: MiddlewareState) -> Any:
        self._count_call(name, state.get("file_path"))
        return result

    def process_error(self, name: str, error: Exception, state: MiddlewareState) -> None:
        self._count_call(name, state.get("file_path"))
        # Don't suppress — let the original error propagate.

    def _count_call(self, name: str, file_path: str | None) -> None:
        key = (name, file_path)
        count = self._call_counter.get(key, 0) + 1
        self._call_counter[key] = count
        if count > self._max_repeats:
            raise StuckDetectionError(
                f"Stuck on tool '{name}' for file '{file_path}' "
                f"(called {count} times)"
            )


class StuckDetectionError(RuntimeError):
    """Raised when the stuck-detection heuristic fires."""
