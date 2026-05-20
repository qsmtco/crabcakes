# SPEC-2: Auto-Test Enforcement Layer

**Implements:** Self-Improvement Layer 3
**Estimated effort:** ~3 hours
**Depends on:** User-Defined Local Agents (agent YAML with `self_improvement.enforcement` flag), SPEC-1 (project rules provide test configuration)
**Enables:** SPEC-4 (dream consolidation uses test failure patterns)

---

## 1. Overview

The enforcement layer in `agent/enforcement.py` already has:
- Tier 1: Syntax guard (`_check_syntax()`) — runs `py_compile`, `node --check`, `bash -n`
- Tier 2: Test runner (`_check_tests()`) — auto-detects test framework, finds related test, runs it
- Tier 3: Lint check (`_check_lint()`) — detects ruff/mypy/eslint

**What already works:**
- Test framework detection (`_detect_test_framework()`) — finds pytest, jest, vitest, make
- Related test file discovery (`_find_related_test()`) — checks `tests/test_{basename}.py` and other conventions
- Per-project config via `.crabcakes/enforcement.json` with TTL cache
- Syntax gate (tests only run if syntax passes)
- Timeout protection
- Output formatting

**What needs to be added/enhanced:**
1. **Venv activation** — Current `_check_tests()` doesn't activate venv before running tests. Projects like crabwatch need `source .venv/bin/activate` first.
2. **Test-specific config in `.crabcakes/enforcement.json`** — Currently only supports top-level tier toggles. Need per-tier configuration (test command, test dir, naming pattern, venv path).
3. **Full suite mode** — Configurable option to run full suite instead of just the related test file.
4. **Configurable test file discovery** — Currently hardcoded to Python conventions. Need to support project-specific naming patterns.
5. **Agent gating** — Enforcement should only run for agents whose `self_improvement.enforcement` flag is `true` (default true for agents with write tools, false for read-only agents). This check happens in `agent/runtime.py` BEFORE calling `enforcement.check()` — the enforcement module itself is unaware of agent identity.

---

## 2. Current State Analysis

### 2.1 What `_check_tests()` already does (line-by-line)

```
1. Skip if syntax failed
2. Skip test files themselves (files with "test_" in name)
3. Skip files matching skip patterns
4. Detect test framework via _detect_test_framework()
5. Find related test via _find_related_test()
6. Run: {base_cmd} {abs_test} -x -q --tb=short (single file) or {base_cmd} -x -q --tb=short (full suite)
7. Parse return code (5 = no tests collected → pass)
8. Return EnforcementCheck with pass/fail + output
```

### 2.2 Gaps

| Gap | Current Behavior | Needed Behavior |
|-----|-----------------|-----------------|
| Venv activation | Runs `python3 -m pytest` directly | Should prepend `source .venv/bin/activate &&` when venv detected |
| Test config | Only tier on/off in enforcement.json | Per-tier settings (command template, test_dir, naming) |
| Test dir | Hardcoded `tests/` | Configurable via enforcement.json |
| Naming pattern | Hardcoded `test_{module}.py` | Configurable via enforcement.json |
| Full suite | Runs if no related test found | Configurable `run_full_suite: true/false` |
| Configurable command | Uses detected base_cmd only | Override via enforcement.json |

---

## 3. Detailed Implementation

### 3.1 Enhanced `.crabcakes/enforcement.json` Schema

**Current schema:**
```json
{
  "syntax_check": true,
  "test_run": true,
  "lint_check": true,
  "skip_patterns": ["*.md"]
}
```

**New schema (backwards-compatible — all new fields optional):**
```json
{
  "syntax_check": true,
  "test_run": true,
  "lint_check": true,
  "skip_patterns": ["*.md"],

  "test": {
    "command": "source .venv/bin/activate && python3 -m pytest {test_file} -v --tb=short",
    "full_suite_command": "source .venv/bin/activate && python3 -m pytest tests/ -v --tb=short",
    "test_dir": "tests",
    "naming_pattern": "test_{module}.py",
    "venv_path": ".venv",
    "run_full_suite": false,
    "timeout_seconds": 30,
    "extra_args": "-x -q"
  }
}
```

**Field reference:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | string | auto-detected | Full command template. `{test_file}` replaced with the test file path. If set, overrides auto-detection |
| `full_suite_command` | string | auto-detected | Full suite command. If set, overrides auto-detection |
| `test_dir` | string | `"tests"` | Directory containing test files |
| `naming_pattern` | string | `"test_{module}.py"` | Pattern for finding related test. `{module}` replaced with source file basename |
| `venv_path` | string | `".venv"` | Path to virtual environment. If it exists, auto-prepends activation |
| `run_full_suite` | bool | `false` | If true, always run full suite instead of related test |
| `timeout_seconds` | int | `60` | Per-project test timeout override |
| `extra_args` | string | `"-x -q"` | Extra arguments appended to test command |

### 3.2 Modifications to `agent/enforcement.py`

#### 3.2.1 Add test config dataclass

After the existing dataclass definitions (around line 40), add:

```python
@dataclass
class TestConfig:
    """Per-project test configuration, loaded from .crabcakes/enforcement.json."""
    command: str | None = None           # Override test command template
    full_suite_command: str | None = None  # Override full suite command
    test_dir: str = "tests"              # Test directory
    naming_pattern: str = "test_{module}.py"  # Test file naming pattern
    venv_path: str = ".venv"             # Venv directory (relative to project)
    run_full_suite: bool = False         # Always run full suite
    timeout_seconds: int = 60            # Test timeout
    extra_args: str = "-x -q"            # Extra pytest arguments

    @classmethod
    def from_dict(cls, data: dict) -> TestConfig:
        """Create TestConfig from enforcement.json test section."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            command=data.get("command"),
            full_suite_command=data.get("full_suite_command"),
            test_dir=data.get("test_dir", "tests"),
            naming_pattern=data.get("naming_pattern", "test_{module}.py"),
            venv_path=data.get("venv_path", ".venv"),
            run_full_suite=data.get("run_full_suite", False),
            timeout_seconds=data.get("timeout_seconds", 60),
            extra_args=data.get("extra_args", "-x -q"),
        )
```

#### 3.2.2 Add venv detection helper

Add after `TestConfig`:

```python
def _detect_venv_prefix(project_path: str, venv_path: str = ".venv") -> str:
    """Detect if a project has a virtual environment and return activation prefix.

    Returns empty string if no venv detected, or the activation command prefix
    (e.g. "source .venv/bin/activate && ") if found.

    Args:
        project_path: Absolute path to the project root.
        venv_path: Relative path to venv directory from project root.
    """
    venv_abs = os.path.join(project_path, venv_path)
    activate_script = os.path.join(venv_abs, "bin", "activate")
    if os.path.isfile(activate_script):
        return f"source {os.path.join(venv_path, 'bin', 'activate')} && "
    return ""
```

#### 3.2.3 Modify `_load_project_enforcement_config()` to extract test config

Add a return of test config alongside the existing enforcement config. Modify the function to return a tuple or add a separate cache for test config:

```python
_TEST_CONFIG_CACHE: dict[str, tuple[float, TestConfig | None]] = {}

def _load_test_config(project_path: str) -> TestConfig | None:
    """Load per-project test configuration from .crabcakes/enforcement.json.

    Separately cached from the enforcement tier toggles so each can evolve
    independently. Shares the same TTL.

    Returns TestConfig or None if no test section in config.
    """
    now = time.monotonic()
    cached = _TEST_CONFIG_CACHE.get(project_path)
    if cached is not None:
        ts, data = cached
        if now - ts < _ENFORCEMENT_CONFIG_TTL:
            return data

    cfg_path = os.path.join(project_path, ".crabcakes", "enforcement.json")
    if not os.path.isfile(cfg_path):
        _TEST_CONFIG_CACHE[project_path] = (now, None)
        return None
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        test_section = data.get("test")
        if test_section and isinstance(test_section, dict):
            tc = TestConfig.from_dict(test_section)
            _TEST_CONFIG_CACHE[project_path] = (now, tc)
            return tc
        _TEST_CONFIG_CACHE[project_path] = (now, None)
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("[enforcement] test config unreadable: %s", e)
        _TEST_CONFIG_CACHE[project_path] = (now, None)
        return None
```

#### 3.2.4 Modify `_find_related_test()` to use configurable naming pattern

Update the function signature and implementation:

```python
def _find_related_test(
    file_path: str,
    project_path: str,
    test_dir: str = "tests",
    naming_pattern: str = "test_{module}.py",
) -> str | None:
    """
    Find the test file corresponding to a source file.
    Uses configurable naming pattern. {module} is replaced with the source
    file's basename (without extension).
    """
    basename = os.path.splitext(os.path.basename(file_path))[0]
    pattern = naming_pattern.replace("{module}", basename)

    candidates = [
        os.path.join(project_path, test_dir, pattern),
        os.path.join(project_path, test_dir, f"{basename}_test.py"),  # Jest/Vitest convention
    ]

    # Also check if there's a mirror in the same directory
    src_dir = os.path.dirname(os.path.join(project_path, file_path))
    candidates.extend([
        os.path.join(src_dir, pattern),
        os.path.join(src_dir, "__tests__", f"{basename}.py"),
    ])

    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, project_path)

    return None
```

#### 3.2.5 Modify `_check_tests()` to use test config and venv activation

The key changes:
1. Load test config from `.crabcakes/enforcement.json`
2. Use venv prefix when running commands
3. Use configurable command template if provided
4. Use configurable naming pattern for finding related tests
5. Use configurable timeout

```python
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

    # Skip files matching skip patterns
    if _is_skipped(file_path, config.skip_patterns):
        return None

    # Load per-project test configuration
    test_config = _load_test_config(project_path) or TestConfig()

    # Detect venv and build activation prefix
    venv_prefix = _detect_venv_prefix(project_path, test_config.venv_path)

    # Determine test timeout (project override or config default)
    test_timeout = test_config.timeout_seconds or config.test_timeout_seconds

    # If a custom command template is provided, use it directly
    if test_config.command:
        related_test = _find_related_test(
            file_path, project_path,
            test_config.test_dir, test_config.naming_pattern,
        )
        if related_test is None and not test_config.run_full_suite:
            return None  # No related test and not running full suite

        if test_config.run_full_suite and test_config.full_suite_command:
            command = venv_prefix + test_config.full_suite_command
        elif related_test:
            abs_test = os.path.join(project_path, related_test)
            command = venv_prefix + test_config.command.replace("{test_file}", abs_test)
        elif test_config.full_suite_command:
            # No related test, no run_full_suite flag, but a full_suite_command is defined — use it
            command = venv_prefix + test_config.full_suite_command
        else:
            # No related test found and no full suite command — skip
            logger.debug("[enforcement] No related test and no full_suite_command — skipping")
            return None

    else:
        # Auto-detect test framework
        framework = _detect_test_framework(project_path)
        if framework is None:
            return None
        framework_name, base_cmd = framework

        related_test = _find_related_test(
            file_path, project_path,
            test_config.test_dir, test_config.naming_pattern,
        )

        if test_config.run_full_suite:
            command = f"{venv_prefix}{base_cmd} {test_config.extra_args} --tb=short"
        elif related_test:
            abs_test = os.path.join(project_path, related_test)
            command = f"{venv_prefix}{base_cmd} {abs_test} {test_config.extra_args} --tb=short"
        else:
            # No related test found — skip unless run_full_suite is true
            return None

    start = time.monotonic()
    try:
        result, duration_ms = _run_timed_command(command, project_path, test_timeout)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

        # pytest returns exit code 5 when no tests collected
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

        # Build detail message
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
            output=output[:config.max_output_chars],
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        return EnforcementCheck(
            tier="tests", tool="write_file", file=file_path,
            passed=False,
            detail=f"Test run timed out ({test_timeout}s) for {file_path}",
            output="", duration_ms=test_timeout * 1000,
        )
    except Exception as e:
        logger.debug("[enforcement] test check raised %s: %s", type(e).__name__, e)
        return None
```

### 3.3 Template `.crabcakes/enforcement.json`

Create a template at `docs/templates/enforcement-template.json`:

```json
{
  "_comment": "Per-project enforcement configuration for CrabCakes agents",
  "syntax_check": true,
  "test_run": true,
  "lint_check": false,

  "test": {
    "command": "source .venv/bin/activate && python3 -m pytest {test_file} -v --tb=short",
    "full_suite_command": "source .venv/bin/activate && python3 -m pytest tests/ -v --tb=short",
    "test_dir": "tests",
    "naming_pattern": "test_{module}.py",
    "venv_path": ".venv",
    "run_full_suite": false,
    "timeout_seconds": 30,
    "extra_args": "-x -q"
  },

  "skip_patterns": ["*.md", "*.txt", "*.json", "*.yaml", "*.yml", "*.toml"]
}
```

### 3.4 Crabwatch-specific `enforcement.json`

Create at `/home/q/projects/crabwatch/.crabcakes/enforcement.json`:

```json
{
  "syntax_check": true,
  "test_run": true,
  "lint_check": false,

  "test": {
    "command": "source .venv/bin/activate && python3 -m pytest {test_file} -v --tb=short",
    "full_suite_command": "source .venv/bin/activate && python3 -m pytest tests/ -v --tb=short",
    "test_dir": "tests",
    "naming_pattern": "test_{module}.py",
    "venv_path": ".venv",
    "run_full_suite": false,
    "timeout_seconds": 30,
    "extra_args": "-x -q"
  }
}
```

### 3.5 Agent Gating in `agent/runtime.py`

The enforcement module (`agent/enforcement.py`) is agent-agnostic — it runs whatever checks are configured. The gating by `self_improvement.enforcement` happens in the agent runtime BEFORE calling `enforcement.check()`. This is an **additional** gate on top of the existing global config gate.

**Two-level gating logic:**
1. **Global gate** (existing): `self._config.enforcement.enabled` — if enforcement is globally disabled in `agent.json`, skip entirely. This gate remains unchanged.
2. **Agent-specific gate** (new): `self_improvement.enforcement` from the agent's YAML definition — if the specific agent has opted out, skip for that agent even if globally enabled.

In `agent/runtime.py`, after `write_file`/`edit_file` tool execution:

```python
# After tool executes:
if tool_name in ("write_file", "edit_file") and tool_result.success:
    # Gate 1: Global enforcement config (existing gate, unchanged)
    if not self._config.enforcement.enabled:
        pass  # enforcement globally disabled — skip
    else:
        # Gate 2: Agent-specific self_improvement config (new)
        si_config = self._get_si_config_for_session(session_key)
        if si_config.get("enforcement", True):
            from agent.enforcement import check
            enforcement_result = check(tool_name, tool_args, tool_result, project_path, config)
            if enforcement_result and enforcement_result.appended_message:
                tool_result.output += "\n" + enforcement_result.appended_message
        else:
            logger.debug("[runtime] Enforcement skipped for %s (disabled in agent self_improvement config)", session_key)
```

The `_get_si_config_for_session()` method resolves the session key to a `SpecialAgentDef` (or agent YAML definition), calls `get_self_improvement_config()`, and returns the dict. This ensures only agents with `enforcement: true` in their self-improvement config trigger verification. The global gate must pass first — if enforcement is disabled globally, the agent-specific check is never reached.

---

## 4. Behavior Flow

### 4.1 Any writing agent writes `watcher.py` → Enforcement triggers

**Prerequisite:** The agent's `self_improvement.enforcement` must be `true` (default for agents with write tools).

```
1. Agent calls write_file("watcher.py", content)
2. Runtime checks: does this agent have self_improvement.enforcement enabled?
   → Yes (loaded from agent YAML via SpecialAgentDef.self_improvement)
3. Tool executes → success
4. enforcement.check() called with tool_name="write_file"
5. Syntax tier: py_compile watcher.py → PASS
6. Test tier:
   a. Load .crabcakes/enforcement.json → get test config
   b. Detect venv: .venv/bin/activate exists → venv_prefix = "source .venv/bin/activate && "
   c. Find related test: tests/test_watcher.py → exists
   d. Build command: "source .venv/bin/activate && python3 -m pytest /path/to/tests/test_watcher.py -x -q --tb=short"
   e. Run command with 30s timeout
   f. Parse output → 12/12 passed
   g. Return EnforcementCheck(passed=True)
7. Format result: "[enforcement:tests] ✅ tests/test_watcher.py: passed"
8. Append to tool result → Agent sees "✅ tests passed" in its write_file response
```

### 4.2 Agent writes file with a bug → Test fails

```
1-2. Same as above
3-4. Tool executes, enforcement.check() called
5. Test tier:
   a-d. Same as above
   e. Run → 8/12 passed (4 failures)
   f. Parse output → FAILED
   g. Return EnforcementCheck(passed=False, output="FAILED tests...")
6. Format result: "[enforcement:tests] ❌ tests/test_watcher.py: FAILED\nFAILED test_moved_events..."
7. Agent sees the failures and can fix them before reporting done
```

### 4.3 Agent writes non-Python file → Test tier skipped

```
1. Agent calls write_file("install.sh", content)
2. Runtime checks enforcement flag → enabled
3. Tool executes → success
4. enforcement.check() → syntax tier runs (bash -n)
5. Test tier: _find_related_test("install.sh") → no test_install.py → returns None → skip
6. No test result appended
```

### 4.4 Project without tests → Silent skip

```
1. Agent writes a file in a project with no .crabcakes/enforcement.json
2. Runtime checks enforcement flag → enabled
3. _load_test_config() → None
4. TestConfig() defaults used
5. _detect_test_framework() → None (no pytest, no jest, no makefile)
6. _check_tests() returns None
7. No test result
```

### 4.5 Read-only agent writes nothing → Enforcement never triggers

```
1. Debugger agent (no write_file in tools) runs analysis
2. Debugger never calls write_file or edit_file
3. enforcement.check() is never called for this agent
4. No enforcement overhead
```

### 4.6 Agent with enforcement disabled → Skipped

```
1. Custom "Researcher" agent has self_improvement.enforcement: false in YAML
2. Researcher calls write_file("notes.md", content)
3. Runtime checks enforcement flag → false
4. enforcement.check() is NOT called
5. No enforcement overhead
```

---

## 5. Edge Cases

| Case | Behavior |
|------|----------|
| Venv exists but no `bin/activate` | `_detect_venv_prefix()` returns empty string — run without activation |
| `command` template has no `{test_file}` | Used as-is (full suite command) |
| Test file found but test framework not detected | Skip (no framework → no command) |
| Test hangs past timeout | `TimeoutExpired` caught → return fail with timeout message |
| `run_full_suite: true` but no tests dir | `_detect_test_framework()` returns None → skip |
| `.crabcakes/enforcement.json` is malformed JSON | Caught by `json.JSONDecodeError` → logged, defaults used |
| Test exits with code 5 (no tests collected) | Treated as pass — nothing to verify |
| Coder writes a test file itself | Skipped (basename contains "test_") |

---

## 6. Testing Plan

### 6.1 Unit Tests — `tests/test_enforcement.py` (extend existing)

```python
class TestVenvDetection:
    def test_venv_detected(self, tmp_path):
        """Returns activation prefix when venv exists."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "activate").write_text("# activation script")
        result = _detect_venv_prefix(str(tmp_path), ".venv")
        assert "source .venv/bin/activate &&" in result

    def test_no_venv(self, tmp_path):
        """Returns empty string when no venv exists."""
        result = _detect_venv_prefix(str(tmp_path), ".venv")
        assert result == ""

    def test_custom_venv_path(self, tmp_path):
        """Detects venv at custom path."""
        venv = tmp_path / "env" / "bin"
        venv.mkdir(parents=True)
        (venv / "activate").write_text("# activation script")
        result = _detect_venv_prefix(str(tmp_path), "env")
        assert "source env/bin/activate &&" in result


class TestTestConfig:
    def test_from_dict_full(self):
        tc = TestConfig.from_dict({
            "command": "pytest {test_file}",
            "test_dir": "spec",
            "naming_pattern": "{module}_spec.py",
            "venv_path": ".virtualenv",
            "run_full_suite": True,
            "timeout_seconds": 45,
        })
        assert tc.command == "pytest {test_file}"
        assert tc.test_dir == "spec"
        assert tc.naming_pattern == "{module}_spec.py"
        assert tc.venv_path == ".virtualenv"
        assert tc.run_full_suite is True
        assert tc.timeout_seconds == 45

    def test_from_dict_empty(self):
        tc = TestConfig.from_dict({})
        assert tc.command is None
        assert tc.test_dir == "tests"

    def test_from_dict_non_dict(self):
        tc = TestConfig.from_dict("not a dict")
        assert tc.command is None


class TestFindRelatedTestConfigurable:
    def test_custom_naming_pattern(self, tmp_path):
        """Finds test file using custom naming pattern."""
        test_dir = tmp_path / "spec"
        test_dir.mkdir()
        (test_dir / "watcher_spec.py").write_text("# test")

        result = _find_related_test(
            "src/watcher.py", str(tmp_path),
            test_dir="spec", naming_pattern="{module}_spec.py",
        )
        assert result is not None
        assert "watcher_spec.py" in result

    def test_custom_test_dir(self, tmp_path):
        """Finds test file in custom test directory."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "test_watcher.py").write_text("# test")

        result = _find_related_test(
            "watcher.py", str(tmp_path),
            test_dir="test",
        )
        assert result is not None
        assert "test_watcher.py" in result


class TestCheckTestsWithVenv:
    def test_venv_activated_before_test(self, tmp_path):
        """When venv exists, activation prefix is prepended to test command."""
        # This would require mocking subprocess.run to verify the command
        # or creating a real venv with pytest installed
        pass  # Integration test — see below

    def test_custom_command_template(self, tmp_path):
        """Custom command from enforcement.json is used."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text(json.dumps({
            "test": {
                "command": "custom-runner {test_file} --verbose",
                "test_dir": "tests",
                "naming_pattern": "test_{module}.py",
            }
        }))
        # Verify the config is loaded correctly
        tc = _load_test_config(str(tmp_path))
        assert tc is not None
        assert tc.command == "custom-runner {test_file} --verbose"


class TestTestConfigCache:
    def test_cache_ttl(self, tmp_path):
        """Test config is cached and reused within TTL."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text(json.dumps({
            "test": {"timeout_seconds": 20}
        }))

        tc1 = _load_test_config(str(tmp_path))
        assert tc1.timeout_seconds == 20

        # Update file — should still return cached value
        (crab_dir / "enforcement.json").write_text(json.dumps({
            "test": {"timeout_seconds": 40}
        }))
        tc2 = _load_test_config(str(tmp_path))
        assert tc2.timeout_seconds == 20  # Still cached

    def test_cache_miss_returns_none(self, tmp_path):
        """Returns None for project without enforcement.json."""
        assert _load_test_config(str(tmp_path)) is None
```

### 6.2 Integration Test

**Manual test procedure:**
1. Create a test project with `.venv/`, `tests/test_example.py`, and `example.py`
2. Create `.crabcakes/enforcement.json` with test config
3. Have Coder write `example.py` with an intentional bug
4. Verify the enforcement output shows test failure with venv activation
5. Have Coder fix the bug
6. Verify the enforcement output shows test pass

---

## 7. Acceptance Criteria

- [ ] `TestConfig` dataclass added to `agent/enforcement.py`
- [ ] `_detect_venv_prefix()` function added
- [ ] `_load_test_config()` function added with TTL cache
- [ ] `_find_related_test()` updated to accept configurable naming pattern and test dir
- [ ] `_check_tests()` updated to use TestConfig, venv prefix, and configurable timeout
- [ ] `.crabcakes/enforcement.json` template created in `docs/templates/`
- [ ] Crabwatch project has `enforcement.json` with correct venv/test config
- [ ] All existing enforcement tests pass
- [ ] New tests for TestConfig, venv detection, and configurable patterns pass
- [ ] End-to-end test: any writing agent writes Python file → related test runs with venv activation
