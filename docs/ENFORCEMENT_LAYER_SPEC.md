# Enforcement Layer — Implementation Specification

**Date:** 2026-05-07
**Author:** QTR
**Status:** DRAFT — Single source of truth for the enforcement layer
**Depends on:** `ARCHITECTURE.md` (all identifiers must match exactly)

---

## 1. Purpose

The enforcement layer guarantees that code written by the Coder agent is verified before the agent can declare completion. It replaces blind trust ("Coder says it's done") with verified trust ("the system confirmed syntax passes, tests pass").

**Target user:** A project manager who is not a software engineer. They need to see green or red status signals they can trust, without reading code.

**Design principle:** The enforcement layer intercepts tool results in the runtime's tool loop, runs automatic verification checks, and injects the results back into the conversation — regardless of whether the model wants to verify or not.

---

## 2. Architecture Integration

### 2.1 Where It Lives

The enforcement layer is a new module: `agent/enforcement.py`. It has zero imports from `ui/` and zero GTK dependencies. It is pure logic.

```
agent/
├── __init__.py
├── config.py            # AgentConfig — unchanged
├── context.py           # System prompt builder — unchanged
├── enforcement.py       # NEW — enforcement layer (this spec)
├── runtime.py           # AgentRuntime — modified (see §3)
├── special_agents.py    # Special agent definitions — unchanged
└── tools.py             # Tool definitions — unchanged
```

### 2.2 How It Plugs In

The enforcement layer hooks into the tool loop in `agent/runtime.py` at a single point: **after each tool execution, before the tool result is appended to the conversation.**

Current flow (lines ~1010-1018 of `runtime.py`):
```
execute_tool(tool_name, args, project_path, session_key)
    → ToolResult
    → tc.mark_completed(result)
    → conv.add_tool_result(call_id, result)
    → dispatch(on_tool_call_result, ...)
```

New flow:
```
execute_tool(tool_name, args, project_path, session_key)
    → ToolResult
    → enforcement.check(tool_name, args, result, project_path)
    → (possibly) auto-exec verification commands → EnforcementResult
    → append EnforcementResult info to tool result output
    → tc.mark_completed(result)
    → conv.add_tool_result(call_id, result)
    → dispatch(on_tool_call_result, ...)
    → (possibly) dispatch(on_enforcement_status, ...) for PM status signals
```

The enforcement layer does NOT block the tool loop. It does NOT require LLM calls. It runs synchronous checks (subprocess calls with timeouts) and appends results to the existing tool result. The model sees the verification output as part of the tool result — it cannot skip it.

### 2.3 Callback Extension

`AgentRuntime.__init__` gains one optional callback:

```python
on_enforcement_status: Callable[[str, str, dict], None] | None = None
# Args: (session_key, tool_name, enforcement_dict)
# enforcement_dict: {"tier": "syntax"|"tests"|"lint",
#                    "file": str, "passed": bool, "detail": str}
```

This callback is dispatched via `GLib.idle_add()` to the UI layer, which can render PM-facing status signals (green checkmark / red warning). The UI rendering is a separate concern — this spec only defines the data contract.

---

## 3. Data Models

### 3.1 EnforcementResult

```python
# In agent/enforcement.py

from dataclasses import dataclass
from typing import Any

@dataclass
class EnforcementCheck:
    """Single verification check result."""
    tier: str               # "syntax" | "tests" | "lint"
    tool: str               # which tool triggered this ("write_file")
    file: str               # relative path of the file checked
    passed: bool            # True = green, False = red
    detail: str             # human-readable summary
    output: str             # raw command output (truncated to 2000 chars)
    duration_ms: int        # how long the check took

@dataclass
class EnforcementResult:
    """Aggregated result from all enforcement checks for one tool call."""
    checks: list[EnforcementCheck]
    appended_message: str   # formatted message to append to tool result
```

### 3.2 EnforcementConfig

Stored as a nested object in `AgentConfig` (agent/config.py):

```python
@dataclass
class EnforcementConfig:
    """Configuration for the enforcement layer."""
    enabled: bool = True                    # master switch
    syntax_check: bool = True               # Tier 1: syntax guard
    test_run: bool = True                   # Tier 2: test runner
    lint_check: bool = True                 # Tier 3: lint check
    syntax_timeout_seconds: int = 10        # max time per syntax check
    test_timeout_seconds: int = 60          # max time per test run
    lint_timeout_seconds: int = 15          # max time per lint check
    max_output_chars: int = 2000            # truncate check output
    skip_patterns: list[str] = field(       # file patterns to skip
        default_factory=lambda: [
            "*.md", "*.txt", "*.json", "*.yaml", "*.yml",
            "*.toml", "*.cfg", "*.ini", "*.rst",
        ]
    )
```

In `agent.json`:
```json
{
  "enforcement": {
    "enabled": true,
    "syntax_check": true,
    "test_run": true,
    "lint_check": true
  }
}
```

`load_agent_config()` in `config.py` must parse the `"enforcement"` key into an `EnforcementConfig` field on `AgentConfig`:

```python
@dataclass
class AgentConfig:
    # ... existing fields ...
    enforcement: EnforcementConfig = field(default_factory=EnforcementConfig)
```

---

## 4. The Three Tiers

### 4.1 Tier 1: Syntax Guard

**Trigger:** After every `write_file` tool call where the file extension maps to a known syntax checker.

**What it does:** Runs a syntax-only check on the written file. No execution of the file's code. Pure parsing validation.

**Extension-to-command mapping:**

| Extension | Command | Notes |
|-----------|---------|-------|
| `.py` | `python3 -m py_compile {path}` | Std library, zero deps |
| `.js` | `node --check {path}` | Requires Node.js installed |
| `.ts` | `npx tsc --noEmit {path}` | Requires TypeScript |
| `.jsx` | `node --check {path}` | Same as JS (syntax level) |
| `.tsx` | `npx tsc --noEmit {path}` | Same as TS |
| `.sh` | `bash -n {path}` | Shell syntax check |
| `.json` | `python3 -c "import json; json.load(open('{path}'))"` | Validate JSON |
| `.yaml` / `.yml` | `python3 -c "import yaml; yaml.safe_load(open('{path}'))"` | Requires PyYAML |

**Skip conditions:**
- File matches a pattern in `enforcement.skip_patterns` (markdown, plain text, etc.)
- Extension not in the mapping above
- Syntax checker binary not found on system (log a debug message, skip silently)

**Implementation:**

```python
def _check_syntax(
    file_path: str,
    project_path: str,
    config: EnforcementConfig,
) -> EnforcementCheck | None:
    """Run syntax check on a file. Returns None if skipped."""

    # Skip if extension not mapped
    ext = os.path.splitext(file_path)[1].lower()
    checker = SYNTAX_CHECKERS.get(ext)
    if checker is None:
        return None

    # Skip if file matches skip patterns
    from fnmatch import fnmatch
    for pattern in config.skip_patterns:
        if fnmatch(os.path.basename(file_path), pattern):
            return None

    # Resolve absolute path
    abs_path = os.path.join(project_path, file_path)

    # Check if checker binary exists (for node/npx/tsc)
    binary = checker.split()[0]
    if binary not in ("python3", "bash") and not shutil.which(binary):
        return None  # silently skip if tool not installed

    # Run the syntax check
    command = checker.format(path=abs_path)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            timeout=config.syntax_timeout_seconds,
        )
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        passed = result.returncode == 0

        return EnforcementCheck(
            tier="syntax",
            tool="write_file",
            file=file_path,
            passed=passed,
            detail=f"Syntax check {'passed' if passed else 'FAILED'} for {file_path}",
            output=output[:config.max_output_chars],
            duration_ms=0,  # filled by caller
        )
    except subprocess.TimeoutExpired:
        return EnforcementCheck(
            tier="syntax", tool="write_file", file=file_path,
            passed=False, detail=f"Syntax check timed out for {file_path}",
            output="", duration_ms=config.syntax_timeout_seconds * 1000,
        )
    except Exception as e:
        return None  # don't block the agent loop on enforcement errors
```

**What the model sees (appended to write_file tool result):**

On pass:
```
OK — wrote 1234 bytes to src/auth.py
[enforcement:syntax] ✅ Syntax check passed for src/auth.py
```

On fail:
```
OK — wrote 1234 bytes to src/auth.py
[enforcement:syntax] ❌ Syntax check FAILED for src/auth.py
  File "src/auth.py", line 42
    def login(user:
                   ^
SyntaxError: invalid syntax
```

**Critical:** The syntax failure is appended as information. It does NOT change `ToolResult.success` — the file was still written. The model sees the error in its tool result and can choose to fix it immediately. The next LLM call gets this context.

### 4.2 Tier 2: Test Runner

**Trigger:** After every `write_file` tool call where:
1. The file is a source code file (not a test file itself — see detection below)
2. The project has a detectable test framework

**Test framework detection** (checked in order, first match wins):

| Signal | Detected Framework | Test Command |
|--------|--------------------|--------------|
| `pyproject.toml` contains `[tool.pytest` or `pytest` in dependencies | pytest | `python3 -m pytest {related_test_file} -x -q --tb=short` |
| `pytest.ini` or `setup.cfg` with `[tool:pytest]` | pytest | same |
| `package.json` with `"jest"` in devDependencies | Jest | `npx jest {related_test_file} --no-coverage` |
| `package.json` with `"vitest"` in devDependencies | Vitest | `npx vitest run {related_test_file}` |
| `Makefile` with `test` target | make | `make test` |
| No match | — | **Skip Tier 2** (no test framework detected) |

**Finding the related test file:**

Given a source file path, look for corresponding test files using these conventions in order:

1. `{project_path}/tests/test_{basename}.py` (e.g., `src/auth.py` → `tests/test_auth.py`)
2. `{project_path}/tests/{basename}_test.py` (e.g., `src/auth.py` → `tests/auth_test.py`)
3. `{source_dir}/test_{basename}.py` (e.g., `src/auth.py` → `src/test_auth.py`)
4. `{source_dir}/__tests__/{basename}.test.{ext}` (JS convention)

If no related test file is found, fall back to running the full test suite with a shorter timeout. If the full suite is not detectable, skip.

**Skip conditions:**
- File being written IS a test file (matches `test_*.py` or `*_test.py` pattern)
- No test framework detected
- Related test file doesn't exist and no full-suite fallback available
- `enforcement.test_run` is False
- Tier 1 (syntax) failed — no point running tests on broken syntax

**What the model sees:**

On pass:
```
OK — wrote 1234 bytes to src/auth.py
[enforcement:syntax] ✅ Syntax check passed for src/auth.py
[enforcement:tests] ✅ 3 tests passed (pytest, 0.8s)
```

On fail:
```
OK — wrote 1234 bytes to src/auth.py
[enforcement:syntax] ✅ Syntax check passed for src/auth.py
[enforcement:tests] ❌ 1 test failed (pytest, 1.2s)
FAILED tests/test_auth.py::test_login - AssertionError: expected 200, got 401
```

On no tests found:
```
OK — wrote 1234 bytes to src/auth.py
[enforcement:syntax] ✅ Syntax check passed for src/auth.py
[enforcement:tests] ⏭ No related tests found for src/auth.py
```

### 4.3 Tier 3: Lint Check

**Trigger:** After every `write_file` where:
1. Tier 1 (syntax) passed
2. A linting tool is detected for the file type

**Linter detection:**

| Signal | Linter | Command |
|--------|--------|---------|
| `ruff` in pyproject.toml or `ruff.toml` exists | ruff | `ruff check {path} --output-format=concise` |
| `.flake8` exists or `flake8` in dependencies | flake8 | `flake8 {path}` |
| `.eslintrc*` or `eslint.config.*` exists | eslint | `npx eslint {path}` |
| `pyproject.toml` with `[tool.mypy` | mypy | `mypy {path} --no-error-summary` |

**Skip conditions:**
- No linter detected for this project
- File extension doesn't match any linter
- Tier 1 failed (linting broken syntax is pointless)
- `enforcement.lint_check` is False

**What the model sees:**

On pass:
```
[enforcement:lint] ✅ Lint check passed (ruff, 0.3s)
```

On fail:
```
[enforcement:lint] ⚠️ 2 lint warnings (ruff, 0.3s)
src/auth.py:15:89 E501 line too long (112 > 88 characters)
src/auth.py:23:5 F841 local variable 'token' is assigned to but never used
```

---

## 5. Public API — `agent/enforcement.py`

```python
"""
Enforcement Layer — post-write verification for the agent tool loop.

This module provides a single entry point: `check()`, called after each
tool execution in the runtime's tool loop. It runs applicable verification
tiers (syntax, tests, lint) and returns results that are appended to the
tool result output.

No imports from ui/. No GTK. Pure logic + subprocess calls.
"""

from dataclasses import dataclass
from typing import Any

@dataclass
class EnforcementCheck:
    tier: str       # "syntax" | "tests" | "lint"
    tool: str       # tool that triggered this
    file: str       # relative path
    passed: bool
    detail: str
    output: str
    duration_ms: int

@dataclass
class EnforcementResult:
    checks: list[EnforcementCheck]
    appended_message: str  # formatted message to append to tool result

def check(
    tool_name: str,
    tool_args: dict,
    tool_result,       # ToolResult from the original tool execution
    project_path: str,
    config: Any,       # EnforcementConfig
) -> EnforcementResult:
    """
    Main entry point. Called after each tool execution in the tool loop.

    Only acts on write_file calls. Returns empty result for all other tools.

    Args:
        tool_name: Name of the tool that just executed (e.g. "write_file")
        tool_args: Arguments dict passed to the tool
        tool_result: ToolResult from the tool execution
        project_path: Absolute path to the project directory
        config: EnforcementConfig instance

    Returns:
        EnforcementResult with checks and formatted message.
        If tool is not write_file, returns result with empty checks and empty message.
    """

def _should_run(tool_name: str, tool_result, config: Any) -> bool:
    """Return True if enforcement should run for this tool call."""

def _check_syntax(file_path: str, project_path: str, config: Any) -> EnforcementCheck | None:
    """Run Tier 1: syntax guard."""

def _detect_test_framework(project_path: str) -> tuple[str, str] | None:
    """Detect test framework. Returns (framework_name, test_command) or None."""

def _find_related_test(file_path: str, project_path: str) -> str | None:
    """Find the test file corresponding to a source file."""

def _check_tests(
    file_path: str, project_path: str, config: Any,
    syntax_passed: bool,
) -> EnforcementCheck | None:
    """Run Tier 2: test runner."""

def _detect_linter(file_path: str, project_path: str) -> tuple[str, str] | None:
    """Detect linter for this file type. Returns (linter_name, command) or None."""

def _check_lint(
    file_path: str, project_path: str, config: Any,
    syntax_passed: bool,
) -> EnforcementCheck | None:
    """Run Tier 3: lint check."""

def _format_result(checks: list[EnforcementCheck], max_output: int) -> str:
    """Format enforcement checks into a message to append to tool result."""
```

---

## 6. Runtime Integration — Changes to `agent/runtime.py`

### 6.1 Import

Add at top of file:
```python
from agent.enforcement import check as enforcement_check
```

### 6.2 Constructor

Add to `AgentRuntime.__init__` parameter list (after `on_token_usage`):
```python
on_enforcement_status: Callable | None = None,
```

Store as:
```python
self._on_enforcement_status = on_enforcement_status
```

### 6.3 Tool Loop Hook

In the tool loop, after `execute_tool()` returns and before `tc.mark_completed()`, insert the enforcement check. The insertion point is between the current lines ~1015 and ~1017 in `runtime.py`:

```python
                    # Execute tool
                    # ... (existing code: execute_tool call) ...
                    result = execute_tool(tool_name, args, conv.project_path or "/tmp", session_key)

                    # === ENFORCEMENT LAYER HOOK ===
                    if tool_name == "write_file" and self._config.enforcement.enabled:
                        enf_result = enforcement_check(
                            tool_name, args, result,
                            conv.project_path or "/tmp",
                            self._config.enforcement,
                        )
                        if enf_result.appended_message:
                            # Append enforcement output to the tool result
                            result = dataclasses.replace(
                                result,
                                output=(result.output or "") + "\n" + enf_result.appended_message,
                            )
                            # Notify UI for PM status signals
                            for check in enf_result.checks:
                                self._dispatch(
                                    self._on_enforcement_status,
                                    session_key, tool_name,
                                    {
                                        "tier": check.tier,
                                        "file": check.file,
                                        "passed": check.passed,
                                        "detail": check.detail,
                                    },
                                )
                    # === END ENFORCEMENT HOOK ===

                    tc.mark_completed(result.output if result.success else result.error or "")
```

**Important:** The enforcement output is appended to `result.output`, NOT to `result.error`. Even if syntax/tests fail, the write itself succeeded. The model sees both the success and the enforcement failures in the same tool result.

### 6.4 Cost Tracking

Enforcement subprocess calls do NOT count against the conversation's token cost. They run locally with no LLM involved. They DO consume real time — the `duration_ms` field in `EnforcementCheck` tracks this.

---

## 7. Stuck Detection

Stuck detection is a separate feature from the three verification tiers. It monitors the tool loop's iteration history and intervenes when the agent is going in circles.

### 7.1 Data Structure

In `AgentRuntime`, add per-session tracking:

```python
self._tool_history: dict[str, list[dict]] = {}  # session_key → [{tool, args_hash, iteration}]
```

Each entry records:
```python
{
    "tool": tool_name,
    "args_hash": hashlib.md5(str(sorted(args.items())).encode()).hexdigest()[:8],
    "iteration": iteration,
}
```

### 7.2 Detection Logic

After each tool call, append to history and check:

```python
def _check_stuck(self, session_key: str, tool_name: str, args: dict, iteration: int) -> str | None:
    """Return an intervention message if the agent appears stuck, else None."""
    history = self._tool_history.setdefault(session_key, [])
    args_hash = hashlib.md5(str(sorted(args.items())).encode()).hexdigest()[:8]
    history.append({"tool": tool_name, "args_hash": args_hash, "iteration": iteration})

    # Keep only last 20 entries
    if len(history) > 20:
        history[:] = history[-20:]

    # Check: same tool + same args hash repeated 3+ times in last 10 entries
    recent = history[-10:]
    same_count = sum(1 for e in recent if e["tool"] == tool_name and e["args_hash"] == args_hash)
    if same_count >= 3:
        return (
            f"[stuck-detection] You've called {tool_name} with the same arguments "
            f"{same_count} times in recent iterations. You appear to be stuck. "
            f"Consider: re-reading the file, checking the error message carefully, "
            f"or trying a completely different approach. "
            f"If you've tried 3+ approaches without progress, report as blocked."
        )

    # Check: more than 8 write_file calls without any exec_command (tests/lint) in between
    recent_tools = [e["tool"] for e in recent]
    if recent_tools.count("write_file") >= 8 and "exec_command" not in recent_tools[-8:]:
        return (
            "[stuck-detection] You've written files 8+ times without running any "
            "commands to verify. Run tests or check syntax before continuing."
        )

    return None
```

### 7.3 Integration Point

In the tool loop, after the enforcement hook and after `tc.mark_completed()` / `conv.add_tool_result()`, check for stuckness:

```python
                    # ... after appending tool result to conversation ...

                    # Stuck detection
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        # Inject as a system message — the model sees this on its next turn
                        conv.add_tool_result(call_id, tc.result + "\n" + stuck_msg)
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
```

### 7.4 Cleanup

When a conversation is cancelled or completed, clean up:
```python
self._tool_history.pop(session_key, None)
```

---

## 8. UI Status Signals (Data Contract Only)

The enforcement layer defines what data it emits. The UI layer decides how to render it. This spec only defines the contract.

### 8.1 Callback Signature

```python
on_enforcement_status(session_key: str, tool_name: str, status: dict) -> None
```

### 8.2 Status Dict

```python
{
    "tier": "syntax" | "tests" | "lint",
    "file": "src/auth.py",          # relative path
    "passed": True | False,
    "detail": "Syntax check passed for src/auth.py",
}
```

### 8.3 Rendering Suggestions (Non-Normative)

The UI layer SHOULD render enforcement results in a way the PM can understand at a glance:

- ✅ green checkmark — syntax/tests/lint all passed
- ❌ red X — one or more checks failed
- ⏭️ skip indicator — no checks applicable
- ⚠️ warning — lint warnings (passed but with issues)

Example feed card text:
```
✏️ Coder wrote src/auth.py
✅ Syntax passed · ✅ 3/3 tests passed · ✅ Lint clean
```

```
✏️ Coder wrote src/auth.py
✅ Syntax passed · ❌ 1 test failed · ⚠️ 2 lint warnings
→ Coder is fixing...
```

---

## 9. Configuration

### 9.1 Default Behavior

Enforcement is **enabled by default** for all projects. All three tiers are on. No per-project configuration required.

### 9.2 Disabling

In `agent.json`:
```json
{
  "enforcement": {
    "enabled": false
  }
}
```

Or disable individual tiers:
```json
{
  "enforcement": {
    "enabled": true,
    "syntax_check": true,
    "test_run": false,
    "lint_check": false
  }
}
```

### 9.3 Project-Level Override

If `.crabcakes/enforcement.json` exists in the project directory, it overrides the global config:

```json
{
  "enabled": true,
  "skip_patterns": ["*.generated.*", "vendor/**"],
  "test_run": false
}
```

Priority: `.crabcakes/enforcement.json` > `agent.json` enforcement section > defaults.

---

## 10. Error Handling Rules

1. **Enforcement failures must never break the tool loop.** If an enforcement check raises an exception, log it and return an empty result. The agent continues working.

2. **Timeouts are hard limits.** If a syntax/test/lint check exceeds its timeout, it returns a "timed out" result. It does NOT hang the tool loop.

3. **Missing tools are silently skipped.** If `node` is not installed, JS/TS syntax checks are skipped. If `ruff` is not installed, ruff lint checks are skipped. Log at debug level.

4. **The enforcement layer does NOT modify `ToolResult.success`.** The write_file succeeded even if syntax check fails. Enforcement output is appended to `ToolResult.output`, never changes the success boolean.

5. **Enforcement does NOT count against `max_tool_iterations`.** The subprocess calls made by enforcement are not LLM turns. They are local operations.

---

## 11. File Extension Mappings (Complete)

### 11.1 Syntax Checkers

```python
SYNTAX_CHECKERS: dict[str, str] = {
    ".py": "python3 -m py_compile {path}",
    ".js": "node --check {path}",
    ".ts": "npx tsc --noEmit {path}",
    ".jsx": "node --check {path}",
    ".tsx": "npx tsc --noEmit {path}",
    ".sh": "bash -n {path}",
    ".bash": "bash -n {path}",
    ".zsh": "zsh -n {path}",
    ".json": "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" {path}",
    ".yaml": "python3 -c \"import yaml,sys; yaml.safe_load(open(sys.argv[1]))\" {path}",
    ".yml": "python3 -c \"import yaml,sys; yaml.safe_load(open(sys.argv[1]))\" {path}",
}
```

### 11.2 Default Skip Patterns

```python
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
```

Wait — `.json` and `.yaml` are in both the syntax checkers map AND the skip patterns. The skip patterns take priority. JSON and YAML syntax validation is handled by removing them from skip patterns if the user wants validation. Default: skip them (they're usually config files, not source code).

Corrected: remove `.json`, `.yaml`, `.yml` from `SYNTAX_CHECKERS` since they're in skip patterns by default. If a user wants JSON/YAML validation, they remove the skip pattern and add the checker back.

Actually no — keep them in both. The `_should_run` check evaluates skip patterns first. If someone removes `"*.json"` from skip patterns, the syntax checker activates. Clean design. Keep as-is.

---

## 12. Implementation Order

### Phase A: Core Infrastructure (1-2 days)
1. Create `agent/enforcement.py` with `EnforcementCheck`, `EnforcementResult`, `check()` stub
2. Add `EnforcementConfig` to `agent/config.py` — parsing from `agent.json`
3. Wire the enforcement hook into `agent/runtime.py` tool loop
4. Verify: existing 63 tests still pass, enforcement does nothing yet (stub returns empty)

### Phase B: Tier 1 — Syntax Guard (1 day)
5. Implement `_check_syntax()` with Python (`py_compile`) support
6. Test: write a `.py` file with a syntax error, verify the model sees the error
7. Test: write a valid `.py` file, verify the model sees the pass
8. Add remaining syntax checkers (JS, TS, shell, JSON, YAML)

### Phase C: Tier 2 — Test Runner (2-3 days)
9. Implement `_detect_test_framework()` — pytest detection first
10. Implement `_find_related_test()` — Python conventions first
11. Implement `_check_tests()` with pytest
12. Test against crabwatch project (has pytest configured)
13. Add Jest/Vitest detection for JS projects

### Phase D: Tier 3 — Lint Check (1 day)
14. Implement `_detect_linter()` — ruff detection first
15. Implement `_check_lint()` with ruff
16. Test against crabwatch project (has ruff configured)

### Phase E: Stuck Detection (1 day)
17. Add `_tool_history` tracking to `AgentRuntime`
18. Implement `_check_stuck()` logic
19. Test: simulate repeated tool calls, verify intervention messages

### Phase F: UI Integration (1-2 days)
20. Wire `on_enforcement_status` callback in `AgentRuntimeHandler`
21. Render enforcement status in feed cards (separate spec for UI changes)

---

## 13. Testing Strategy

### 13.1 Unit Tests — `tests/test_enforcement.py`

```python
# Test Tier 1: Syntax guard
def test_syntax_pass_python(tmp_path):
    """Valid Python file → syntax check passes."""

def test_syntax_fail_python(tmp_path):
    """Invalid Python file → syntax check fails with error detail."""

def test_syntax_skip_markdown(tmp_path):
    """Markdown file → syntax check skipped."""

def test_syntax_skip_unknown_extension(tmp_path):
    """Unknown extension → syntax check skipped."""

def test_syntax_checker_not_installed(tmp_path):
    """JS syntax check when node not installed → skipped silently."""

# Test Tier 2: Test runner
def test_detect_pytest(pytest_project):
    """pyproject.toml with pytest dependency → detected."""

def test_find_related_test_python(tmp_path):
    """src/auth.py → tests/test_auth.py mapping."""

def test_find_related_test_not_found(tmp_path):
    """Source file with no test file → None."""

def test_test_run_after_write(tmp_path):
    """Write source file → related tests auto-executed."""

def test_test_run_skip_when_syntax_fails(tmp_path):
    """Syntax fails → test run skipped."""

# Test Tier 3: Lint check
def test_detect_ruff(ruff_project):
    """pyproject.toml with ruff → detected."""

def test_lint_pass(ruff_project):
    """Clean file → lint passes."""

def test_lint_fail(ruff_project):
    """File with violations → lint reports them."""

# Test main check() function
def test_check_non_write_file():
    """Non-write_file tool → empty result."""

def test_check_disabled():
    """Enforcement disabled → empty result."""

def test_check_full_pipeline(tmp_path):
    """Write Python file → syntax + tests + lint all run."""

# Test stuck detection
def test_stuck_repeated_tool():
    """Same tool+args 3 times → stuck message."""

def test_stuck_many_writes_no_exec():
    """8+ writes without exec → stuck message."""

def test_not_stuck_varied_tools():
    """Varied tool calls → no stuck message."""
```

### 13.2 Integration Tests

Run crabwatch's existing test suite through crabCakes Coder with enforcement enabled:
1. Assign a task to Coder (e.g., "implement a new function in git_ops.py")
2. Verify enforcement checks fire automatically
3. Verify the model sees syntax/test results in tool output
4. Verify the model self-corrects when enforcement reports failures

---

## 14. Relationship to Research Findings

### 14.1 What We're Building vs. What Exists

| Concept | Source | What We're Doing |
|---------|--------|-----------------|
| AgentSpec rule engine | arXiv 2503.18666 | Simplified: no DSL, just Python functions triggered by tool name |
| Observations close the loop | OpenHands | Exactly this — enforcement output feeds back to the model |
| Stuck detection | OpenHands | Same pattern, simplified threshold logic |
| Post-write system message | CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL §4.6 | Evolved from suggestion to runtime-enforced |
| Environmental richness | Devin | We provide it: tests exist, linters exist, enforcement runs them automatically |

### 14.2 What We're NOT Building

- **No DSL.** AgentSpec's rule language is overengineered for our needs. Python functions with clear triggers are sufficient.
- **No sandbox.** Enforcement runs in the same project context as the agent. We're not adding Docker isolation.
- **No multi-model verification.** We're not using a second model to review the first model's output. Pure subprocess-based checks.
- **No forced test-writing.** If no tests exist, we skip Tier 2. We don't auto-generate tests. That's the model's job.

---

## 15. Open Questions

1. **Should enforcement block on syntax failure?** Current design: no. Syntax failure is appended as information. The model can choose to fix it or ignore it. Alternative: make syntax failure block the tool loop until the model fixes it. Pro: catches syntax errors immediately. Con: could annoy the model in edge cases (writing partial files, scaffolding).

2. **How to handle slow test suites?** Some projects have test suites that take minutes. The 60-second default timeout helps, but the agent is blocked during that time. Future: run tests in background, inject results asynchronously.

3. **Should enforcement fire on edit_file (when added)?** Yes. When `edit_file` is implemented (see proposal §4.11), enforcement should trigger on it identically to `write_file`. The trigger condition is "file was written/modified," not "specific tool was called."

4. **PM approval for enforcement subprocess calls?** Currently, enforcement runs subprocess commands directly, bypassing the exec_command approval gate. This is safe because the commands are hardcoded (py_compile, pytest, ruff) — the model cannot influence them. But the PM should be aware they're running. The status callback handles this.

---

## 16. Glossary

| Term | Definition |
|------|-----------|
| **Enforcement layer** | The system that automatically verifies code after writes |
| **Tier 1** | Syntax guard — parsing validation after every write |
| **Tier 2** | Test runner — execute related tests after every source write |
| **Tier 3** | Lint check — run configured linter after every source write |
| **Stuck detection** | Monitoring tool call patterns for circular behavior |
| **PM status signal** | Visual indicator shown to the PM (✅❌⚠️⏭️) |
| **Tool loop** | The iteration cycle in AgentRuntime: LLM → tool call → result → LLM |
| **ToolResult** | Dataclass returned by tool execution (success, output, error, duration_ms) |
| **EnforcementResult** | Dataclass returned by enforcement check (checks, appended_message) |
