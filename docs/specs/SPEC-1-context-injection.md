# SPEC-1: Context Injection Layer (Bug Journal + Project Rules)

**Implements:** Self-Improvement Layers 1 + 2
**Estimated effort:** ~2 hours
**Depends on:** User-Defined Local Agents (agent YAML definitions with `role` and `self_improvement` fields)
**Enables:** SPEC-2, SPEC-3, SPEC-4

---

## 1. Overview

This specification adds two per-project context file types that are automatically injected into **any local agent's** system prompt when that agent is working on a project:

1. **Bug Journal** (`.crabcakes/{role}-bugs.md`) — A growing log of the agent's past mistakes on this project, with structured entries documenting the bug, root cause, fix, and lesson.
2. **Project Rules** (`.crabcakes/{role}-rules.md`) — Per-codebase conventions, environment setup, test commands, and known gotchas (like Claude Code's `CLAUDE.md`).

The `{role}` placeholder comes from the agent's YAML definition. Examples:
- Coder agent (`role: coder`) → `coder-bugs.md`, `coder-rules.md`
- Debugger agent (`role: debugger`) → `debugger-bugs.md`, `debugger-rules.md`
- Security Auditor (`role: security-auditor`) → `security-auditor-bugs.md`, `security-auditor-rules.md`

Both files are loaded by `utils/prompt_loader.py` during `compose_system_prompt()` and appended as sections in the agent's system prompt. They are per-project (stored in `.crabcakes/`), git-tracked, and optional — if the files don't exist, the system silently skips them.

**Gating:** Injection only happens if the agent's `self_improvement` config has `bug_journal: true` and/or `project_rules: true` (both default `true`).

---

## 2. Files to Modify

### 2.1 `utils/prompt_loader.py` — Primary modification target

**Current state:** `compose_system_prompt()` loads templates from `prompts/system/`, fills `{{VARIABLES}}`, and appends file context. It already has a step that loads `.crabcakes/` docs via `agent/context.py` → `build_file_context()`.

**What to change:**
- Add `_load_project_context_file()` helper
- Add `agent_role` parameter usage to derive `{role}-bugs.md` and `{role}-rules.md` filenames
- Add injection logic gated by agent's `self_improvement` config

### 2.2 Agent system prompts (e.g. `prompts/system/coder.md`) — Minor update per agent

**What to change:** For agents that have a Bug Fix Protocol or similar, add a reference to the bug journal telling the agent to check its bug journal for past patterns before attempting a fix. Each agent prompt that wants this gets its own "Step 1a: Check Your Bug Journal" section.

---

## 3. Files to Create

### 3.1 Templates in `docs/templates/`

- `docs/templates/agent-bugs-template.md` — Generic bug journal template (not agent-specific)
- `docs/templates/agent-rules-template.md` — Generic project rules template

These templates use `{role}` (the agent's role field) and `{project_name}` as placeholders that get replaced when creating a new agent's context files for a project. The `{role}` placeholder is replaced by the agent's role identifier (e.g., "coder", "debugger"), and `{project_name}` is replaced by the project directory name.

---

## 4. Detailed Implementation

### 4.1 Bug Journal File Format

**Location:** `<project_path>/.crabcakes/{role}-bugs.md`

Where `{role}` is the agent's `role` field from its YAML definition (e.g., `coder`, `debugger`, `security-auditor`).

**Format:**
```markdown
# {Agent Name} Bug Journal — [project-name]

> Auto-maintained by the Agent Self-Improvement System.
> Entries are added during adversarial review or by the Dream Consolidation layer.

---

## Bug #1 — YYYY-MM-DD — [filename]

**Task:** [task description]
**Mistake:** [what the agent did wrong]
**Expected:** [correct behavior]
**Actual:** [what actually happened]
**Fix:** [what was changed to fix it]
**Lesson:** [general principle to remember]
**Pattern:** [tag — e.g. mock-truthiness, partial-test-run, type-confusion, sed-overmatch]

---
```

**Rules:**
- Each entry starts with `## Bug #N` and is separated by `---`
- Entries are numbered sequentially
- The `Pattern` tag is a single lowercase kebab-case word or phrase
- Maximum 50 entries in the active journal (pruning handled by SPEC-4)
- File must be valid UTF-8 markdown

### 4.2 Project Rules File Format

**Location:** `<project_path>/.crabcakes/{role}-rules.md`

**Format:**
```markdown
# {Agent Name} Rules — [project-name]

> Per-project rules injected into {agent name}'s context. Edit manually or auto-generated.

## Environment
- Language/runtime version
- Virtual environment location
- Required activation command
- Package manager

## Architecture
- Key modules and their responsibilities
- Entry points
- Important design patterns

## Known Gotchas
- Project-specific pitfalls
- Things that look correct but aren't
- Files/directories that must not be modified

## Commands
- How to run tests
- How to run linter
- How to build
```

**Rules:**
- Sections are optional — include only what's relevant to this agent role
- Keep total size under ~4KB (roughly 100 lines)
- File must be valid UTF-8 markdown

### 4.3 `utils/prompt_loader.py` Modifications

#### 4.3.1 Add helper function to load project context files

Add this function after the existing `fill_template()` function and before `compose_system_prompt()`:

```python
def _load_project_context_file(project_path: str, filename: str, max_size: int = 10_000) -> str | None:
    """Load a per-project context file from .crabcakes/ directory.

    Args:
        project_path: Absolute path to the project root.
        filename: Name of the file in .crabcakes/ (e.g. "coder-bugs.md").
        max_size: Maximum file size in bytes. Skip larger files.

    Returns:
        File content as string, or None if file doesn't exist / too large / unreadable.
    """
    filepath = os.path.join(project_path, ".crabcakes", filename)
    if not os.path.isfile(filepath):
        return None
    try:
        size = os.path.getsize(filepath)
        if size > max_size:
            _logger.warning(
                "Project context file %s is too large (%d bytes, max %d) — skipping",
                filename, size, max_size
            )
            return None
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        return content if content else None
    except OSError as e:
        _logger.debug("Failed to read project context file %s: %s", filename, e)
        return None
```

#### 4.3.2 Add agent self-improvement config lookup

```python
def _get_agent_self_improvement_config(agent_role: str) -> dict:
    """Get the self_improvement config for an agent from its YAML definition.

    Delegates to utils.agent_defs.get_default_si_config() for the base defaults,
    then merges with the agent's YAML-defined overrides. This makes utils/agent_defs
    the single source of truth for self-improvement defaults.

    SpecialAgentDef.get_self_improvement_config() (in agent/special_agents.py) also
    delegates to get_default_si_config(can_write=...) — keeping both in sync.
    """
    from utils.agent_defs import load_agent_def_by_role, get_default_si_config
    try:
        agent_def = load_agent_def_by_role(agent_role)
        if agent_def:
            can_write = "write_file" in agent_def.get("tools", [])
            defaults = get_default_si_config(can_write=can_write)
            config = agent_def.get("self_improvement", {})
            return {**defaults, **config}
    except Exception:
        pass
    # Fallback — can't determine can_write, use safe defaults
    return get_default_si_config(can_write=False)
```

#### 4.3.3 Add injection logic to `compose_system_prompt()`

After the existing step 6 (agent-specific templates) and before the variable filling block, add:

```python
    # 7. Per-agent self-improvement context files (bug journal + project rules)
    if project_path and agent_role:
        si_config = _get_agent_self_improvement_config(agent_role)

        if si_config.get("bug_journal", True):
            bugs_file = f"{agent_role}-bugs.md"
            bug_journal = _load_project_context_file(project_path, bugs_file)
            if bug_journal:
                parts.append(bug_journal)

        if si_config.get("project_rules", True):
            rules_file = f"{agent_role}-rules.md"
            project_rules = _load_project_context_file(project_path, rules_file)
            if project_rules:
                parts.append(project_rules)
```

**Exact insertion point:** After the `if agent_role == "coder":` / `elif agent_role == "debugger":` block (step 6), before the `if not parts:` check.

**Ordering in the composed prompt:**
1. Generic rules (`default.md`) → baseline behavior
2. Collaboration protocol (`collab.md`) → A2A rules
3. Project awareness (`project-awareness.md`) → project context
3b. CrabCakes commands (`crabcakes-commands.md`) → command reference (when project active)
4. Project onboarding (`project-onboarding.md`) → initial setup (when project not yet onboarded)
5. Code review mode (`code-review.md`) → review rules (if active)
6. Agent-specific template (`coder.md`, `debugger.md`, etc.) → role-specific rules
7. **Bug journal (`{role}-bugs.md`)** → this agent's past mistakes on this project
8. **Project rules (`{role}-rules.md`)** → project conventions for this agent role
9. File context → actual codebase files

### 4.4 Agent System Prompt Modifications

For each agent prompt that has a fix/debug protocol, add a bug journal reference. This is per-agent, not global:

**In `prompts/system/coder.md`**, add after "### Step 1: Read the failing test FIRST":

```markdown
### Step 1a: Check Your Bug Journal
- If your context includes a Bug Journal section, read it before starting any fix
- Look for patterns matching the current bug (check the **Pattern:** tag)
- If you've made this exact mistake before on this project, DON'T repeat it
- Example: if Bug #3 has Pattern: mock-truthiness and you're about to check `if value is not None` on a mock, stop and use `isinstance()` instead
```

**In `prompts/system/debugger.md`** (if it exists and has a similar protocol), add an analogous section.

### 4.5 Template Files

#### 4.5.1 `docs/templates/agent-bugs-template.md`

```markdown
# {Agent Name} Bug Journal — [project-name]

> Auto-maintained by the Agent Self-Improvement System.
> Entries are added during adversarial review (Layer 4) or Dream Consolidation (Layer 5).
> To add an entry manually, follow the format below and increment the bug number.

---

## Bug #1 — YYYY-MM-DD — [filename.ext]

**Task:** [What task was being worked on]
**Mistake:** [What the agent did wrong — be specific about the code]
**Expected:** [What should have happened]
**Actual:** [What actually happened]
**Fix:** [What was changed to resolve it]
**Lesson:** [General principle — one sentence]
**Pattern:** [kebab-case tag — e.g. mock-truthiness, partial-test-run, type-confusion]

---
```

#### 4.5.2 `docs/templates/agent-rules-template.md`

```markdown
# {Agent Name} Rules — [project-name]

> Per-project rules injected into {agent name}'s context.
> Create this file at `.crabcakes/{role}-rules.md` in the project root.
> Include only sections relevant to this agent's work on the project.

## Environment
- Language/runtime version:
- Virtual environment:
- Required activation:
- Package manager:

## Architecture
- Entry points:
- Key modules:
- Design patterns:

## Known Gotchas
- [Project-specific pitfall 1]
- [Project-specific pitfall 2]

## Commands
- Run tests:
- Run linter:
- Build:
```

### 4.6 Crabwatch Initial Data

Populate the crabwatch project's `.crabcakes/coder-bugs.md` with the 3 real bugs from task 5:

**File:** `/home/q/projects/crabwatch/.crabcakes/coder-bugs.md`

```markdown
# Coder Bug Journal — crabwatch

> Auto-maintained by the Agent Self-Improvement System.

---

## Bug #1 — 2026-05-18 — watcher.py

**Task:** Fix moved event detection in DebouncedHandler
**Mistake:** Used `if dest_path is not None:` to check if a moved event occurred — MagicMock objects are always truthy, so this condition was always True
**Expected:** Only real moved events (where dest_path is a real string) should be detected
**Actual:** Every event was treated as a moved event because MagicMock's `__getattr__` returns a truthy MagicMock for any attribute access
**Fix:** Changed to `isinstance(dest_path, str) and dest_path` — check type first, then truthiness
**Lesson:** Mock objects are always truthy for all attribute access — always check type, not just truthiness, when working with mock-based tests
**Pattern:** mock-truthiness

---

## Bug #2 — 2026-05-18 — watcher.py

**Task:** Fix moved event detection — second attempt
**Mistake:** Changed moved event check but broke moved events entirely — the fix was too aggressive and filtered out legitimate moved events
**Expected:** Moved events with real dest_path strings should still be detected
**Actual:** The detection logic was modified in a way that broke the moved event path for real events too
**Fix:** Used `isinstance(dest_path, str)` which correctly distinguishes MagicMock (returns False) from actual string paths (returns True)
**Lesson:** When fixing a mock-related bug, make sure the fix doesn't break the real code path. Test against both mock and real values.
**Pattern:** over-fixing

---

## Bug #3 — 2026-05-18 — watcher.py

**Task:** Fix moved event detection — third attempt (final)
**Mistake:** Initial fix attempt didn't run the full test suite — only checked the specific failing test, missing that the fix broke 4 other tests
**Expected:** All 12 watcher tests pass
**Actual:** First fix passed the moved event tests but broke 4 other event type tests
**Fix:** Used the correct `isinstance` check that handles both MagicMock and real string paths correctly
**Lesson:** ALWAYS run the full test suite after a fix. A fix that passes its own test but breaks others is a bad fix.
**Pattern:** partial-test-run

---
```

**File:** `/home/q/projects/crabwatch/.crabcakes/coder-rules.md`

```markdown
# Coder Rules — crabwatch

## Environment
- Python 3.12.3, venv at `.venv/`
- Always activate: `source .venv/bin/activate`
- Test runner: `python3 -m pytest tests/ -v`
- Package manager: pip (pyproject.toml)

## Test Conventions
- Tests in `tests/test_{module}.py`
- Uses pytest with MagicMock fixtures
- Test framework: pytest 9.0.3, pluggy 1.6.0
- Tests mock filesystem events — be aware of MagicMock truthiness (see Bug Journal)

## Architecture
- `crabwatch/watcher.py` — File watcher daemon using watchdog DebouncedHandler
- `crabwatch/writer.py` — Context.md I/O handler
- `crabwatch/diary.py` — Git diary entry point
- `crabwatch/__main__.py` — Module entry point (`python3 -m crabwatch`)
- Entry points: `python3 -m crabwatch.watcher`, `python3 -m crabwatch.diary`

## Known Gotchas
- `.crabcakes/` directory MUST be filtered in the filesystem watcher — infinite loop risk
- `crabwatch.service` already has correct venv python paths — do NOT sed-replace `python3` in it
- Diary entry point uses `python3 -m crabwatch.diary` (module form), NOT `crabwatch-diary` (console script name)
- `install.sh` already committed with correct paths — verify before modifying

## Commands
- Run tests: `source .venv/bin/activate && python3 -m pytest tests/ -v`
- Run single test: `source .venv/bin/activate && python3 -m pytest tests/test_watcher.py -v`
- Run watcher: `source .venv/bin/activate && python3 -m crabwatch.watcher`
- Syntax check: `bash -n install.sh` (for shell scripts)
```

---

## 5. Token Budget Analysis

**Current agent prompt size:** ~14K chars / ~3.5K tokens (per prompt_loader.py comment)

**Added by this spec per agent:**
- Bug journal (3 entries): ~1.5KB / ~375 tokens
- Project rules: ~1.2KB / ~300 tokens
- Template injection code: ~200 chars overhead

**Total impact per agent:** +~2.7KB / ~675 tokens → new total ~16.7KB / ~4.2K tokens

For a 128K context model: **3.3%** of context. Negligible.

If the bug journal grows to 50 entries (~25KB), it would be ~6.25K tokens → 4.9% of context. Still fine but worth monitoring. The 10KB file size cap in `_load_project_context_file()` provides a hard limit.

---

## 6. Testing Plan

### 6.1 Unit Tests — `tests/test_prompt_loader.py` (new or extend existing)

```python
class TestProjectContextInjection:
    """Test bug journal and project rules injection into system prompts."""

    def test_bug_journal_injected_by_role(self, tmp_path):
        """When project has {role}-bugs.md and agent has that role, it appears in prompt."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("## Bug #1 — test bug\n\nMistake: test")

        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )

        assert "Bug #1" in result
        assert "test bug" in result

    def test_project_rules_injected_by_role(self, tmp_path):
        """When project has {role}-rules.md, it appears in prompt."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-rules.md").write_text("# Coder Rules\ntest rule")

        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )

        assert "Coder Rules" in result
        assert "test rule" in result

    def test_different_roles_get_different_files(self, tmp_path):
        """Debugger gets debugger-bugs.md, not coder-bugs.md."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("CODER_BUG_MARKER")
        (crab_dir / "debugger-bugs.md").write_text("DEBUGGER_BUG_MARKER")

        coder_result = compose_system_prompt(
            agent_name="Coder", agent_role="coder", project_path=str(tmp_path),
        )
        debugger_result = compose_system_prompt(
            agent_name="Debugger", agent_role="debugger", project_path=str(tmp_path),
        )

        assert "CODER_BUG_MARKER" in coder_result
        assert "DEBUGGER_BUG_MARKER" not in coder_result
        assert "DEBUGGER_BUG_MARKER" in debugger_result
        assert "CODER_BUG_MARKER" not in debugger_result

    def test_custom_agent_gets_own_files(self, tmp_path):
        """A custom agent with role 'security-auditor' gets security-auditor-bugs.md."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "security-auditor-bugs.md").write_text("AUDIT_BUG_MARKER")

        result = compose_system_prompt(
            agent_name="Security Auditor",
            agent_role="security-auditor",
            project_path=str(tmp_path),
        )

        assert "AUDIT_BUG_MARKER" in result

    def test_no_crabcakes_dir_silent_skip(self, tmp_path):
        """When .crabcakes/ doesn't exist, prompt is still generated."""
        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )
        assert result  # non-empty
        assert "Coder" in result

    def test_empty_files_skipped(self, tmp_path):
        """Empty {role}-bugs.md and {role}-rules.md are skipped."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("")
        (crab_dir / "coder-rules.md").write_text("   \n  ")

        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )
        assert result  # non-empty, no crash

    def test_large_file_skipped_with_warning(self, tmp_path, caplog):
        """Files exceeding max_size are skipped and logged."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("x" * 20_000)

        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )
        assert result  # non-empty, no crash

    def test_self_improvement_bug_journal_false_skips_injection(self, tmp_path):
        """When agent's self_improvement.bug_journal is false, no bug journal injected."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("SHOULD_NOT_APPEAR")

        # This test requires mocking _get_agent_self_improvement_config
        # or having a test agent definition with bug_journal: false
        # Implementation detail: mock the config lookup
        with patch("utils.prompt_loader._get_agent_self_improvement_config",
                   return_value={"bug_journal": False, "project_rules": True,
                                 "enforcement": True, "structured_feedback": False,
                                 "dream_consolidation": False}):
            result = compose_system_prompt(
                agent_name="Coder",
                agent_role="coder",
                project_path=str(tmp_path),
            )
            assert "SHOULD_NOT_APPEAR" not in result

    def test_no_project_path_no_injection(self):
        """Without project_path, no context files are loaded."""
        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=None,
        )
        # Just verify it doesn't crash

    def test_ordering_bug_journal_after_agent_template(self, tmp_path):
        """Bug journal appears AFTER the agent-specific template in the prompt."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("BUG_JOURNAL_MARKER")

        result = compose_system_prompt(
            agent_name="Coder",
            agent_role="coder",
            project_path=str(tmp_path),
        )

        # coder.md content should appear before the bug journal
        coder_pos = result.find("Common Pitfalls")
        journal_pos = result.find("BUG_JOURNAL_MARKER")
        assert coder_pos > 0  # coder.md loaded
        assert journal_pos > 0  # journal loaded
        assert coder_pos < journal_pos  # correct order

    def test_load_project_context_file_function(self, tmp_path):
        """Direct test of the _load_project_context_file helper."""
        from utils.prompt_loader import _load_project_context_file

        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text("test content")

        result = _load_project_context_file(str(tmp_path), "coder-bugs.md")
        assert result == "test content"

        # Non-existent file
        assert _load_project_context_file(str(tmp_path), "nonexistent.md") is None

        # Missing .crabcakes dir
        empty = tmp_path / "empty_project"
        empty.mkdir()
        assert _load_project_context_file(str(empty), "coder-bugs.md") is None
```

### 6.2 Integration Test

**Manual test procedure:**
1. Create `.crabcakes/coder-bugs.md` in a test project
2. Open the project in CrabCakes
3. Send Coder a task
4. Verify the bug journal content appears in Coder's context (set `CRABCAKES_PROMPT_DEBUG=1` to dump the composed prompt)
5. Repeat with Debugger — verify `debugger-bugs.md` is loaded instead

### 6.3 Behavioral Test

After populating crabwatch's bug journal, send Coder a task that involves MagicMock. Observe whether Coder references the bug journal pattern and avoids the mock-truthiness pitfall without being told.

---

## 7. Acceptance Criteria

- [ ] `_load_project_context_file()` function added to `utils/prompt_loader.py`
- [ ] `_get_agent_self_improvement_config()` function added to `utils/prompt_loader.py`
- [ ] `compose_system_prompt()` injects `{role}-bugs.md` when agent's `self_improvement.bug_journal` is true
- [ ] `compose_system_prompt()` injects `{role}-rules.md` when agent's `self_improvement.project_rules` is true
- [ ] Different agent roles get different context files (coder→coder-bugs.md, debugger→debugger-bugs.md)
- [ ] Context files appear AFTER the agent-specific template in the prompt
- [ ] Missing files are silently skipped (no crash, no error log)
- [ ] Oversized files (>10KB) are skipped with a warning log
- [ ] `self_improvement.bug_journal: false` skips bug journal injection
- [ ] `self_improvement.project_rules: false` skips project rules injection
- [ ] `prompts/system/coder.md` updated with Bug Journal check in Step 1a
- [ ] Template files created in `docs/templates/` (agent-agnostic names)
- [ ] Crabwatch project populated with initial coder bug journal (3 entries) and coder rules
- [ ] All existing tests pass
- [ ] New tests in `tests/test_prompt_loader.py` pass
- [ ] `CRABCAKES_PROMPT_DEBUG=1` shows correct prompt composition with role-specific context files
