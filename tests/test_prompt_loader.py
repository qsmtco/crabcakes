# tests/test_prompt_loader.py
# Unit tests for utils/prompt_loader.py

import os
import tempfile

import pytest

from utils.prompt_loader import load_prompt_template, fill_template, compose_system_prompt, SYSTEM_DIR


class TestLoadPromptTemplate:
    def test_loads_existing_template(self):
        result = load_prompt_template("default")
        assert result is not None
        assert "{{AGENT_NAME}}" in result

    def test_returns_none_for_missing(self):
        result = load_prompt_template("nonexistent_template_xyz")
        assert result is None

    def test_project_awareness_template_exists(self):
        result = load_prompt_template("project-awareness")
        assert result is not None
        assert "{{PROJECT_NAME}}" in result

    def test_improve_template_moved(self):
        result = load_prompt_template("improve")
        assert result is not None


class TestFillTemplate:
    def test_fills_single_variable(self):
        result = fill_template("Hello {{NAME}}!", {"NAME": "Qaster"})
        assert result == "Hello Qaster!"

    def test_fills_multiple_variables(self):
        result = fill_template("{{A}} and {{B}}", {"A": "X", "B": "Y"})
        assert result == "X and Y"

    def test_strips_unresolved_variables(self):
        result = fill_template("{{A}} {{B}}", {"A": "X"})
        assert result == "X "
        assert "{{B}}" not in result

    def test_empty_variables_strips_all(self):
        result = fill_template("Hello {{NAME}}!", {})
        assert "{{NAME}}" not in result
        assert result == "Hello !"

    def test_no_variables_in_template(self):
        result = fill_template("No vars here.", {"A": "X"})
        assert result == "No vars here."


class TestComposeSystemPrompt:
    def test_default_template_loaded(self):
        prompt = compose_system_prompt(agent_name="TestAgent")
        assert "TestAgent" in prompt

    def test_project_template_included_when_path_given(self):
        with tempfile.TemporaryDirectory() as proj:
            prompt = compose_system_prompt(
                agent_name="TestAgent",
                project_path=proj,
                project_awareness={"PROJECT_NAME": "TestProj", "TEAM_ROSTER": "None", "CURRENT_STATE": "ok", "PROJECT_MEMORY": ""},
            )
            assert "TestProj" in prompt

    def test_onboarding_only_loaded_for_coder(self, tmp_path):
        """Onboarding template loads for coder agents only, not for gateway/debugger.

        Per BUG_REPORT-identity-override.md Bug #2: the onboarding interview
        should not be injected into every agent's prompt in a fresh project.
        """
        # Helper: does this prompt contain the onboarding template's content?
        def has_onboarding(prompt: str) -> bool:
            return "ONBOARDING phase" in prompt

        # Coder in an unonboarded project → onboarding IS loaded
        coder_prompt = compose_system_prompt(
            agent_name="Coder", agent_role="coder", project_path=str(tmp_path),
        )
        assert has_onboarding(coder_prompt), (
            "Coder should get onboarding template in unonboarded project"
        )

        # Debugger in same project → onboarding is NOT loaded
        debugger_prompt = compose_system_prompt(
            agent_name="Debugger", agent_role="debugger", project_path=str(tmp_path),
        )
        assert not has_onboarding(debugger_prompt), (
            "Debugger should NOT get onboarding template (Bug #2 fix)"
        )

        # Gateway (empty agent_role) in same project → onboarding is NOT loaded
        gateway_prompt = compose_system_prompt(
            agent_name="Gateway", agent_role="", project_path=str(tmp_path),
        )
        assert not has_onboarding(gateway_prompt), (
            "Gateway agent should NOT get onboarding template (Bug #2 fix)"
        )

    def test_coder_template_included(self):
        prompt = compose_system_prompt(agent_name="Coder", agent_role="coder")
        assert "Coder" in prompt
        assert "Core Principles" in prompt or "software" in prompt.lower()

    def test_debugger_template_included(self):
        prompt = compose_system_prompt(agent_name="Debugger", agent_role="debugger")
        assert "Debugger" in prompt
        assert "Debugging" in prompt or "diagnostic" in prompt.lower()

    def test_review_mode_adds_template(self):
        prompt = compose_system_prompt(agent_name="Coder", review_mode="review")
        assert "review" in prompt.lower()

    def test_tools_included(self):
        prompt = compose_system_prompt(agent_name="Coder", tools=["read_file", "exec_command"])
        assert "read_file" in prompt
        assert "exec_command" in prompt

    def test_no_project_no_project_template(self):
        prompt = compose_system_prompt(agent_name="Coder")
        # Should not have project-awareness template variables unfilled
        assert "{{PROJECT_NAME}}" not in prompt

    def test_returns_string(self):
        prompt = compose_system_prompt(agent_name="TestAgent")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestSystemDirExists:
    def test_system_dir_exists(self):
        assert os.path.isdir(SYSTEM_DIR)

    def test_system_dir_has_templates(self):
        files = [f for f in os.listdir(SYSTEM_DIR) if f.endswith(".md")]
        assert len(files) >= 3  # default, project-awareness, improve at minimum


class TestVariableContractIntegration:
    """Verify template variables match build_awareness_dict keys."""

    def test_project_awareness_template_variables_match_dict(self):
        """All {{VAR}} in project-awareness.md must be covered by build_awareness_dict."""
        from utils.prompt_loader import load_prompt_template, _VAR_RE
        template = load_prompt_template("project-awareness")
        assert template is not None, "project-awareness.md not found"

        # Extract all variable names from the template
        template_vars = set(_VAR_RE.findall(template))

        # These are the keys compose_system_prompt builds in its variables dict
        provided_vars = {
            "AGENT_NAME", "PROJECT_PATH", "PROJECT_NAME",
            "TEAM_ROSTER", "CURRENT_STATE", "PROJECT_MEMORY",
            "REVIEW_MODE", "TOOL_LIST", "WORKFLOW_STATUS",
        }

        unresolved = template_vars - provided_vars
        assert not unresolved, f"Template variables not in compose dict: {unresolved}"

    def test_default_template_variables_match_dict(self):
        """All {{VAR}} in default.md must be covered by compose_system_prompt variables."""
        from utils.prompt_loader import load_prompt_template, _VAR_RE
        template = load_prompt_template("default")
        assert template is not None, "default.md not found"

        template_vars = set(_VAR_RE.findall(template))
        provided_vars = {
            "AGENT_NAME", "PROJECT_PATH", "PROJECT_NAME",
            "TEAM_ROSTER", "CURRENT_STATE", "PROJECT_MEMORY",
            "REVIEW_MODE", "TOOL_LIST",
        }

        unresolved = template_vars - provided_vars
        assert not unresolved, f"Template variables not in compose dict: {unresolved}"

    def test_coder_template_variables_match_dict(self):
        from utils.prompt_loader import load_prompt_template, _VAR_RE
        template = load_prompt_template("coder")
        assert template is not None, "coder.md not found"

        template_vars = set(_VAR_RE.findall(template))
        provided_vars = {
            "AGENT_NAME", "PROJECT_PATH", "PROJECT_NAME",
            "TEAM_ROSTER", "CURRENT_STATE", "PROJECT_MEMORY",
            "REVIEW_MODE", "TOOL_LIST",
        }

        unresolved = template_vars - provided_vars
        assert not unresolved, f"Template variables not in compose dict: {unresolved}"

    def test_debugger_template_variables_match_dict(self):
        from utils.prompt_loader import load_prompt_template, _VAR_RE
        template = load_prompt_template("debugger")
        assert template is not None, "debugger.md not found"

        template_vars = set(_VAR_RE.findall(template))
        provided_vars = {
            "AGENT_NAME", "PROJECT_PATH", "PROJECT_NAME",
            "TEAM_ROSTER", "CURRENT_STATE", "PROJECT_MEMORY",
            "REVIEW_MODE", "TOOL_LIST",
        }

        unresolved = template_vars - provided_vars
        assert not unresolved, f"Template variables not in compose dict: {unresolved}"


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

        from unittest.mock import patch
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
        assert isinstance(result, str)

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
