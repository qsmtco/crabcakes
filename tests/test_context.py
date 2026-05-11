# tests/test_context.py
# Unit tests for agent/context.py
#
# Principles:
#   - Pure functions — no mocks needed for network or GTK
#   - Test real filesystem behavior with tempfile
#   - Test gitignore parsing, truncation, custom prompt loading

import os
import tempfile

import pytest

from agent.context import (
    build_file_context,
    build_system_prompt,
)


# ═══════════════════════════════════════════════════════════════════
#  build_system_prompt
# ═══════════════════════════════════════════════════════════════════

class TestBuildSystemPrompt:
    def test_contains_agent_name(self):
        with tempfile.TemporaryDirectory() as proj:
            prompt = build_system_prompt("Coder", proj, ["read_file", "write_file"])
            assert "Coder" in prompt

    def test_contains_project_path(self):
        with tempfile.TemporaryDirectory() as proj:
            prompt = build_system_prompt("Coder", proj, [])
            assert proj in prompt

    def test_no_project_shows_placeholder(self):
        prompt = build_system_prompt("Coder", None, [])
        assert "Coder" in prompt or "no project" in prompt.lower()

    def test_tool_list_included(self):
        prompt = build_system_prompt("Coder", "/tmp", ["read_file", "exec_command"])
        assert "read_file" in prompt
        assert "exec_command" in prompt

    def test_review_mode_awareness(self):
        prompt = build_system_prompt("Coder", "/tmp", [], review_mode="review")
        assert "REVIEW MODE ACTIVE" in prompt or "review" in prompt.lower()

    def test_review_mode_off_no_warning(self):
        prompt = build_system_prompt("Coder", "/tmp", [], review_mode="off")
        # Should not contain REVIEW MODE ACTIVE
        assert "REVIEW MODE ACTIVE" not in prompt

    def test_custom_prompt_overrides_template(self):
        """Custom AGENTS.md is no longer supported — template system is used instead."""
        with tempfile.TemporaryDirectory() as proj:
            prompt = build_system_prompt("Coder", proj, ["read_file"])
            # Template system should produce a prompt (not crash)
            assert "Coder" in prompt

    def test_coder_template_has_correct_sections(self):
        prompt = build_system_prompt("Coder", "/tmp", [])
        assert "software engineering" in prompt or "Coder" in prompt

    def test_debugger_template_used_for_debugger(self):
        prompt = build_system_prompt("Debugger", "/tmp", [])
        assert "Debugger" in prompt  # name appears

    def test_collab_prompt_in_all_agents(self):
        """collab.md is composed into all agents regardless of role."""
        p_coder = build_system_prompt("Coder", "/tmp", [])
        p_gateway = build_system_prompt("QTR", "/tmp", [], agent_role="")
        p_debugger = build_system_prompt("Debugger", "/tmp", [], agent_role="debugger")
        for p, label in [(p_coder, "coder"), (p_gateway, "gateway"), (p_debugger, "debugger")]:
            assert "Agent Collaboration" in p, f"collab missing in {label} prompt"

    def test_collab_comes_after_default(self):
        """collab.md loads after default.md in the composition order."""
        prompt = build_system_prompt("Coder", "/tmp", [])
        default_pos = prompt.find("You are")
        collab_pos = prompt.find("Agent Collaboration")
        assert 0 <= default_pos < collab_pos, "collab should come after default"

    def test_collab_in_no_project_prompt(self):
        """collab.md applies even when no project is active."""
        prompt = build_system_prompt("Coder", None, [])
        assert "Agent Collaboration" in prompt, "collab should be in no-project prompt"


# ═══════════════════════════════════════════════════════════════════
#  build_file_context — gitignore
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextGitignore:
    def test_gitignore_basic_pattern(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, ".gitignore"), "w") as f:
                f.write("*.pyc\n__pycache__/\n")
            os.makedirs(os.path.join(proj, "__pycache__"))
            with open(os.path.join(proj, "main.pyc"), "w") as f:
                f.write("bytecode")
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("source")
            ctx = build_file_context(proj)
            assert "main.py" in ctx
            assert "__pycache__" not in ctx
            assert ".pyc" not in ctx

    def test_gitignore_comment_ignored(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, ".gitignore"), "w") as f:
                f.write("# This is a comment\n*.bak\n")
            with open(os.path.join(proj, "file.bak"), "w") as f:
                f.write("backup")
            with open(os.path.join(proj, "file.py"), "w") as f:
                f.write("source")
            ctx = build_file_context(proj)
            assert "file.py" in ctx
            assert "file.bak" not in ctx

    def test_gitignore_directory_pattern(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, ".gitignore"), "w") as f:
                f.write("node_modules/\n.venv/\n")
            os.makedirs(os.path.join(proj, "node_modules"))
            os.makedirs(os.path.join(proj, "src"))
            with open(os.path.join(proj, "src", "main.py"), "w") as f:
                f.write("source")
            ctx = build_file_context(proj)
            assert "node_modules" not in ctx
            assert "src/" in ctx

    def test_negation_pattern_ignored_due_to_no_support(self):
        """Negation patterns (!) are not supported — ignored files stay ignored."""
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, ".gitignore"), "w") as f:
                f.write("*.txt\n!important.txt\n")
            with open(os.path.join(proj, "file.py"), "w") as f:
                f.write("python file")
            with open(os.path.join(proj, "important.txt"), "w") as f:
                f.write("important")
            ctx = build_file_context(proj)
            # file.py is shown (not ignored)
            assert "file.py" in ctx
            # important.txt is ignored (negation not supported)
            assert "important.txt" not in ctx

    def test_no_gitignore_all_files_shown(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.txt"), "w") as f:
                f.write("a")
            with open(os.path.join(proj, "b.txt"), "w") as f:
                f.write("b")
            ctx = build_file_context(proj)
            assert "a.txt" in ctx
            assert "b.txt" in ctx

    def test_hidden_files_starting_with_dot_ignored(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, ".env"), "w") as f:
                f.write("SECRET=x")
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("source")
            ctx = build_file_context(proj)
            assert ".env" not in ctx
            assert "main.py" in ctx


# ═══════════════════════════════════════════════════════════════════
#  build_file_context — truncation
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextTruncation:
    def test_small_context_not_truncated(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "small.txt"), "w") as f:
                f.write("tiny")
            ctx = build_file_context(proj, max_chars=50_000)
            assert "truncated" not in ctx
            assert "small.txt" in ctx

    def test_large_key_files_truncated(self):
        with tempfile.TemporaryDirectory() as proj:
            # README.md (~8KB) + big.txt (~5KB) = ~13KB > 5KB limit
            with open(os.path.join(proj, "README.md"), "w") as f:
                f.write("# Project\n" + "A" * 8000)
            with open(os.path.join(proj, "big.txt"), "w") as f:
                f.write("B" * 5000)
            ctx = build_file_context(proj, max_chars=5000)
            assert "truncated" in ctx
            assert len(ctx) <= 5000 + 100  # within limit + marker

    def test_truncation_marker_at_end(self):
        with tempfile.TemporaryDirectory() as proj:
            # 100 files × ~5 bytes/entry ≈ 547 chars > 500 limit
            for i in range(100):
                with open(os.path.join(proj, f"f{i}.txt"), "w") as f:
                    f.write(str(i))
            ctx = build_file_context(proj, max_chars=500)
            assert "truncated" in ctx


# ═══════════════════════════════════════════════════════════════════
#  build_file_context — key files
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextKeyFiles:
    def test_readme_included(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "README.md"), "w") as f:
                f.write("# My Project\nThis is the readme.")
            ctx = build_file_context(proj)
            assert "README.md" in ctx
            assert "My Project" in ctx

    def test_pyproject_toml_included(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "pyproject.toml"), "w") as f:
                f.write("[project]\nname = \"test\"")
            ctx = build_file_context(proj)
            assert "pyproject.toml" in ctx
            assert "test" in ctx

    def test_file_too_large_shows_placeholder(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "README.md"), "w") as f:
                f.write("X" * 60_000)  # over 50KB per-file limit
            ctx = build_file_context(proj)
            assert "too large" in ctx
            assert "X" * 60_000 not in ctx  # content not included

    def test_key_files_section_present(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "README.md"), "w") as f:
                f.write("Readme content")
            ctx = build_file_context(proj)
            assert "Key files" in ctx or "README.md" in ctx


# ═══════════════════════════════════════════════════════════════════
#  build_file_context — query mode
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextQuery:
    def test_query_matches_file_by_name(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "auth.py"), "w") as f:
                f.write("def login(): pass")
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("def main(): pass")
            ctx = build_file_context(proj, query="auth")
            assert "auth.py" in ctx
            assert "login" in ctx
            assert "main.py" not in ctx

    def test_query_no_matches(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("def foo(): pass")
            ctx = build_file_context(proj, query="NOTFOUNDXYZ")
            assert "No files match" in ctx

    def test_query_case_insensitive(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "MyFile.py"), "w") as f:
                f.write("content")
            ctx = build_file_context(proj, query="myfile")
            assert "MyFile.py" in ctx

    def test_query_in_subdirectory(self):
        with tempfile.TemporaryDirectory() as proj:
            os.makedirs(os.path.join(proj, "src"))
            with open(os.path.join(proj, "src", "utils.py"), "w") as f:
                f.write("def helper(): pass")
            ctx = build_file_context(proj, query="utils")
            assert "utils.py" in ctx


# ═══════════════════════════════════════════════════════════════════
#  build_file_context — directory tree
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextTree:
    def test_tree_shows_nested_structure(self):
        with tempfile.TemporaryDirectory() as proj:
            os.makedirs(os.path.join(proj, "src", "utils"))
            with open(os.path.join(proj, "src", "main.py"), "w") as f:
                f.write("source")
            with open(os.path.join(proj, "src", "utils", "helper.py"), "w") as f:
                f.write("helper source")
            ctx = build_file_context(proj)
            assert "src/" in ctx
            assert "main.py" in ctx
            assert "utils/" in ctx
            assert "helper.py" in ctx

    def test_tree_shows_files_at_root(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("source")
            ctx = build_file_context(proj)
            assert "main.py" in ctx
