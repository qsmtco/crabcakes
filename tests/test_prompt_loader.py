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

    def test_coder_template_included(self):
        prompt = compose_system_prompt(agent_name="Coder", agent_role="coder")
        assert "Coder" in prompt
        assert "Coding" in prompt or "software" in prompt.lower()

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
            "REVIEW_MODE", "TOOL_LIST",
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
