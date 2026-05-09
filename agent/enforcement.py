# agent/enforcement.py
# Enforcement Layer — post-write verification for the agent tool loop.
#
# This module provides a single entry point: check(), called after each
# tool execution in the runtime's tool loop. It runs applicable verification
# tiers (syntax, tests, lint) and returns results that are appended to the
# tool result output.
#
# No imports from ui/. No GTK. Pure logic + subprocess calls.

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Syntax checkers — extension → shell command template ────────────────────

SYNTAX_CHECKERS: dict[str, str] = {
    ".py": "python3 -m py_compile {path}",
    ".js": "node --check {path}",
    ".ts": "npx tsc --noEmit {path}",
    ".jsx": "node --check {path}",
    ".tsx": "npx tsc --noEmit {path}",
    ".sh": "bash -n {path}",
    ".bash": "bash -n {path}",
    ".zsh": "zsh -n {path}",
}

# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class EnforcementCheck:
    """Single verification check result."""
    tier: str               # "syntax" | "tests" | "lint"
    tool: str              # which tool triggered this ("write_file")
    file: str               # relative path of the file checked
    passed: bool           # True = green, False = red
    detail: str            # human-readable summary
    output: str             # raw command output (truncated)
    duration_ms: int       # how long the check took


@dataclass
class EnforcementResult:
    """Aggregated result from all enforcement checks for one tool call."""
    checks: list[EnforcementCheck] = field(default_factory=list)
    appended_message: str = ""    # formatted message to append to tool result


# ── Skip patterns — applied to basename, fnmatch-style ──────────────────────

DEFAULT_SKIP_PATTERNS: list[str] = [
    "*.md", "*.txt", "*.rst", "*.adoc",
    "*.json", "*.yaml", "*.yml", "*.toml",
    "*.cfg", "*.ini", "*.conf",
    "*.css", "*.scss", "*.less",
    "*.html", "*.htm", "*.xml", "*.svg",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.webp",
    "*.woff", "*.woff2", "*.ttf", "*.eot",
    "*.lock", "*.map",
    "LICENSE*", "README*",
]


def _is_skipped(file_path: str, skip_patterns: list[str]) -> bool:
    """Return True if the file matches any skip pattern."""
    basename = os.path.basename(file_path)
    for pattern in skip_patterns:
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


# ── Tier 1: Syntax Guard ──────────────────────────────────────────────────────


def _check_syntax(
    file_path: str,
    project_path: str,
    config: Any,
) -> EnforcementCheck | None:
    """
    Run Tier 1 syntax guard on a file.
    Returns None if skipped (unknown extension, binary, not installed).
    """
    ext = os.path.splitext(file_path)[1].lower()
    checker = SYNTAX_CHECKERS.get(ext)
    if checker is None:
        return None

    if _is_skipped(file_path, config.skip_patterns):
        return None

    abs_path = os.path.join(project_path, file_path)
    if not os.path.isfile(abs_path):
        return None

    # Check if required binary is available (skip if not)
    binary = checker.split()[0]
    if binary not in ("python3", "bash") and not shutil.which(binary):
        logger.debug("[enforcement] syntax checker not available: %s", binary)
        return None

    command = checker.format(path=abs_path)
    start = time.monotonic()
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            timeout=config.syntax_timeout_seconds,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        passed = result.returncode == 0

        return EnforcementCheck(
            tier="syntax",
            tool="write_file",
            file=file_path,
            passed=passed,
            detail=f"Syntax check {'passed' if passed else 'FAILED'} for {file_path}",
            output=output[: config.max_output_chars],
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        return EnforcementCheck(
            tier="syntax", tool="write_file", file=file_path,
            passed=False,
            detail=f"Syntax check timed out for {file_path}",
            output="", duration_ms=config.syntax_timeout_seconds * 1000,
        )
    except Exception as e:
        logger.debug("[enforcement] syntax check raised %s: %s", type(e).__name__, e)
        return None


# ── Tier 2: Test Runner ────────────────────────────────────────────────────────


def _detect_test_framework(project_path: str) -> tuple[str, str] | None:
    """
    Detect test framework for a project.
    Returns (framework_name, base_command) or None.
    """
    # pytest — pyproject.toml with [tool.pytest] or pytest in dependencies
    pyproject = os.path.join(project_path, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            import tomllib
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            if "tool" in data and "pytest" in data["tool"]:
                return ("pytest", "python3 -m pytest")
            deps = data.get("project", {}).get("dependencies", [])
            if any("pytest" in str(d) for d in deps):
                return ("pytest", "python3 -m pytest")
            opt_deps = data.get("project", {}).get("optional-dependencies", {})
            for extra, deps_list in opt_deps.items():
                if any("pytest" in str(d) for d in deps_list):
                    return ("pytest", "python3 -m pytest")
        except Exception:
            pass

    # pytest.ini
    if os.path.isfile(os.path.join(project_path, "pytest.ini")):
        return ("pytest", "python3 -m pytest")

    # setup.cfg with [tool:pytest]
    setup_cfg = os.path.join(project_path, "setup.cfg")
    if os.path.isfile(setup_cfg):
        try:
            with open(setup_cfg, "r", encoding="utf-8") as f:
                content = f.read()
            if "[tool:pytest]" in content or "[pytest]" in content:
                return ("pytest", "python3 -m pytest")
        except Exception:
            pass

    # Jest — package.json with "jest" in devDependencies
    pkg_json = os.path.join(project_path, "package.json")
    if os.path.isfile(pkg_json):
        try:
            import json
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            dev_deps = data.get("devDependencies", {}) or data.get("dependencies", {})
            if "jest" in dev_deps:
                return ("jest", "npx jest --no-coverage")
            if "vitest" in dev_deps:
                return ("vitest", "npx vitest run")
        except Exception:
            pass

    # Makefile with test target
    makefile = os.path.join(project_path, "Makefile")
    if os.path.isfile(makefile):
        try:
            with open(makefile, "r", encoding="utf-8") as f:
                content = f.read()
            if "\ntest:" in content or "\ntest :\n" in content:
                return ("make", "make test")
        except Exception:
            pass

    return None


def _find_related_test(file_path: str, project_path: str) -> str | None:
    """
    Find the test file corresponding to a source file.
    Checks Python convention: tests/test_{basename}.py first.
    """
    basename = os.path.splitext(os.path.basename(file_path))[0]

    candidates = [
        os.path.join(project_path, "tests", f"test_{basename}.py"),
        os.path.join(project_path, "tests", f"{basename}_test.py"),
    ]

    # Also check if there's a mirror in the same directory
    src_dir = os.path.dirname(os.path.join(project_path, file_path))
    candidates.extend([
        os.path.join(src_dir, f"test_{basename}.py"),
        os.path.join(src_dir, "__tests__", f"{basename}.py"),
    ])

    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, project_path)

    return None


def _check_tests(
    file_path: str,
    project_path: str,
    config: Any,
    syntax_passed: bool,
) -> EnforcementCheck | None:
    """
    Run Tier 2 test runner.
    Returns None if skipped.
    """
    # Skip if syntax failed — no point running tests on broken code
    if not syntax_passed:
        return None

    # Skip test files themselves
    basename = os.path.basename(file_path)
    if "test_" in basename or basename.endswith("_test.py"):
        return None

    # Skip files matching skip patterns (markdown, configs, etc.)
    if _is_skipped(file_path, config.skip_patterns):
        return None

    # Detect test framework
    framework = _detect_test_framework(project_path)
    if framework is None:
        return None

    framework_name, base_cmd = framework

    # Find related test
    related_test = _find_related_test(file_path, project_path)

    start = time.monotonic()
    try:
        if related_test:
            # Run related test file
            abs_test = os.path.join(project_path, related_test)
            command = f"{base_cmd} {abs_test} -x -q --tb=short"
        else:
            # Run full suite (no related test found)
            command = f"{base_cmd} -x -q --tb=short"

        result, duration_ms = _run_timed_command(command, project_path, config.test_timeout_seconds)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        # pytest returns exit code 5 when no tests collected — treat as "nothing to run"
        if result.returncode == 5:
            return EnforcementCheck(
                tier="tests",
                tool="write_file",
                file=file_path,
                passed=True,
                detail=f"⏭ No tests collected for {file_path}",
                output="",
                duration_ms=duration_ms,
            )
        passed = result.returncode == 0

        if related_test:
            detail = f"{related_test}: {'passed' if passed else 'FAILED'}"
        else:
            detail = f"Full test suite: {'passed' if passed else 'FAILED'}"

        return EnforcementCheck(
            tier="tests",
            tool="write_file",
            file=file_path,
            passed=passed,
            detail=detail,
            output=output[: config.max_output_chars],
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        return EnforcementCheck(
            tier="tests", tool="write_file", file=file_path,
            passed=False,
            detail=f"Test run timed out for {file_path}",
            output="", duration_ms=config.test_timeout_seconds * 1000,
        )
    except Exception as e:
        logger.debug("[enforcement] test check raised %s: %s", type(e).__name__, e)
        return None


# ── Tier 3: Lint Check ─────────────────────────────────────────────────────────


def _detect_linter(file_path: str, project_path: str) -> tuple[str, str] | None:
    """
    Detect linter for this file type.
    Returns (linter_name, command) or None.
    """
    ext = os.path.splitext(file_path)[1].lower()

    # ruff — works for Python
    ruff_config = os.path.join(project_path, "ruff.toml")
    ruff_pyproject = os.path.join(project_path, "pyproject.toml")
    if ext == ".py":
        if os.path.isfile(ruff_config) or os.path.isfile(ruff_pyproject):
            # Check if ruff is referenced in pyproject.toml
            if os.path.isfile(ruff_pyproject):
                try:
                    import tomllib
                    with open(ruff_pyproject, "rb") as f:
                        data = tomllib.load(f)
                    if "tool" in data and "ruff" in data["tool"]:
                        return ("ruff", f"ruff check {file_path} --output-format=concise")
                except Exception:
                    pass
            return ("ruff", f"ruff check {file_path} --output-format=concise")

    # mypy — Python type checking
    if ext == ".py":
        pyproject = os.path.join(project_path, "pyproject.toml")
        if os.path.isfile(pyproject):
            try:
                import tomllib
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                if "tool" in data and "mypy" in data["tool"]:
                    return ("mypy", f"mypy {file_path} --no-error-summary")
            except Exception:
                pass

    # eslint — JS/TS
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        eslintrc = os.path.join(project_path, ".eslintrc")
        eslint_config = os.path.join(project_path, "eslint.config.js")
        if os.path.isfile(eslintrc) or os.path.isfile(eslint_config):
            if shutil.which("npx"):
                return ("eslint", f"npx eslint {file_path}")

    return None


def _run_timed_command(command: str, project_path: str, timeout: int) -> tuple[subprocess.CompletedProcess, int]:
    """Run a subprocess command. Returns (result, duration_ms). Raises on timeout."""
    start = time.monotonic()
    result = subprocess.run(
        command, shell=True, capture_output=True,
        cwd=project_path, timeout=timeout,
    )
    return result, int((time.monotonic() - start) * 1000)


def _check_lint(
    file_path: str,
    project_path: str,
    config: Any,
    syntax_passed: bool,
) -> EnforcementCheck | None:
    """
    Run Tier 3 lint check.
    Returns None if skipped.
    """
    if not syntax_passed:
        return None

    if _is_skipped(file_path, config.skip_patterns):
        return None

    linter = _detect_linter(file_path, project_path)
    if linter is None:
        return None

    linter_name, command = linter

    # Check if the linter binary is available
    binary = linter_name.split()[0]
    if not shutil.which(binary):
        return None

    start = time.monotonic()
    try:
        result, duration_ms = _run_timed_command(command, project_path, config.lint_timeout_seconds)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        passed = result.returncode == 0

        return EnforcementCheck(
            tier="lint",
            tool="write_file",
            file=file_path,
            passed=passed,
            detail=f"Lint check {'passed' if passed else 'FAILED'} ({linter_name}, {duration_ms / 1000:.1f}s)",
            output=output[: config.max_output_chars],
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        return EnforcementCheck(
            tier="lint", tool="write_file", file=file_path,
            passed=False,
            detail=f"Lint check timed out for {file_path}",
            output="", duration_ms=config.lint_timeout_seconds * 1000,
        )
    except Exception as e:
        logger.debug("[enforcement] lint check raised %s: %s", type(e).__name__, e)
        return None


# ── Formatter ─────────────────────────────────────────────────────────────────


def _format_result(checks: list[EnforcementCheck], max_output: int) -> str:
    """Format enforcement checks into a message to append to tool result."""
    if not checks:
        return ""

    lines = []
    for check in checks:
        if check.passed:
            icon = "✅"
        else:
            icon = "❌"

        if check.output:
            # Truncate output to max_output chars total
            output_preview = check.output.strip()[:max_output]
            if len(check.output) > max_output:
                output_preview += f"\n[... truncated ...]"
            lines.append(f"[enforcement:{check.tier}] {icon} {check.detail}\n{output_preview}")
        else:
            lines.append(f"[enforcement:{check.tier}] {icon} {check.detail}")

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────


def check(
    tool_name: str,
    tool_args: dict,
    tool_result,       # ToolResult from the original tool execution
    project_path: str,
    config: Any,        # EnforcementConfig
) -> EnforcementResult:
    """
    Main entry point. Called after each tool execution in the tool loop.

    Only acts on write_file calls where the file was successfully written.
    Returns empty result for all other tools.

    Returns:
        EnforcementResult with checks and formatted message to append.
    """
    # Only trigger on file-writing tools that succeeded
    if tool_name not in ("write_file", "edit_file"):
        return EnforcementResult()

    # Only run if the write itself succeeded
    if not tool_result.success:
        return EnforcementResult()

    file_path = tool_args.get("path", "")
    if not file_path:
        return EnforcementResult()

    checks: list[EnforcementCheck] = []

    # Tier 1: Syntax guard
    if config.syntax_check:
        syntax_result = _check_syntax(file_path, project_path, config)
        if syntax_result is not None:
            checks.append(syntax_result)

    # Determine if syntax passed (for gating Tier 2/Tier 3)
    syntax_passed = all(c.tier == "syntax" and c.passed for c in checks)
    # If no syntax check ran, default to True (don't gate)
    no_syntax_check = all(c.tier != "syntax" for c in checks)
    syntax_gate = syntax_passed or no_syntax_check

    # Tier 2: Test runner
    if config.test_run and syntax_gate:
        tests_result = _check_tests(file_path, project_path, config, syntax_passed)
        if tests_result is not None:
            checks.append(tests_result)

    # Tier 3: Lint check
    if config.lint_check and syntax_gate:
        lint_result = _check_lint(file_path, project_path, config, syntax_passed)
        if lint_result is not None:
            checks.append(lint_result)

    if not checks:
        return EnforcementResult()

    appended_message = _format_result(checks, config.max_output_chars)
    return EnforcementResult(checks=checks, appended_message=appended_message)