# tests/test_project_awareness.py
# Tests for utils/project_awareness.py — project config directory management.
#
# Covers: init, load/save team, load/save context, awareness block building,
# tech stack detection, legacy migration.

import json
import os
import pytest

from models.team import ProjectTeam, TeamMember
from utils.project_awareness import (
    CRABCAKES_DIR_NAME,
    append_project_context,
    build_awareness_block,
    build_awareness_snapshot,
    detect_tech_stack,
    get_crabcakes_dir,
    init_project_config,
    load_project_context,
    load_project_manifest,
    load_team,
    save_awareness_snapshot,
    save_project_context,
    save_team,
)


class TestGetCrabcakesDir:
    def test_returns_correct_path(self, tmp_path):
        result = get_crabcakes_dir(str(tmp_path))
        assert result == str(tmp_path / ".crabcakes")


class TestInitProjectConfig:
    def test_creates_crabcakes_directory(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes").is_dir()

    def test_creates_project_md(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "project.md").is_file()

    def test_creates_team_json(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "team.json").is_file()

    def test_creates_context_md(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "context.md").is_file()

    def test_creates_awareness_json(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "awareness.json").is_file()

    def test_idempotent_double_init(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        # Second init should not overwrite existing team.json
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Agent1"),
        ]))
        init_project_config(str(tmp_path), "testproject")
        team = load_team(str(tmp_path))
        assert len(team.members) == 1
        assert team.members[0].name == "Agent1"

    def test_migrates_root_crabcakes_md(self, tmp_path):
        old_content = "# My Project\nOld manifest content"
        (tmp_path / "crabcakes.md").write_text(old_content)
        init_project_config(str(tmp_path), "myproject")
        manifest = load_project_manifest(str(tmp_path))
        assert manifest == old_content


class TestLoadSaveTeam:
    def test_load_empty_returns_empty_team(self, tmp_path):
        team = load_team(str(tmp_path))
        assert len(team.members) == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        team = ProjectTeam(
            members=[
                TeamMember("sk1", "Agent1", "implementation", True),
                TeamMember("sk2", "Agent2", "review", False),
            ],
            pm_name="Captain",
            pm_id="cli",
        )
        save_team(str(tmp_path), team)
        loaded = load_team(str(tmp_path))
        assert len(loaded.members) == 2
        assert loaded.members[0].session_key == "sk1"
        assert loaded.members[0].can_write is True
        assert loaded.members[1].name == "Agent2"
        assert loaded.pm_name == "Captain"

    def test_corrupt_json_returns_empty_team(self, tmp_path):
        init_project_config(str(tmp_path), "test")
        team_path = tmp_path / ".crabcakes" / "team.json"
        team_path.write_text("{ this is not json }")
        team = load_team(str(tmp_path))
        assert len(team.members) == 0


class TestLoadSaveContext:
    def test_load_empty_returns_empty_string(self, tmp_path):
        assert load_project_context(str(tmp_path)) == ""

    def test_save_and_load_roundtrip(self, tmp_path):
        content = "## Notes\nWorking on the project"
        save_project_context(str(tmp_path), content)
        assert load_project_context(str(tmp_path)) == content

    def test_enforces_50kb_cap(self, tmp_path):
        big_content = "x" * (60 * 1024)
        save_project_context(str(tmp_path), big_content)
        loaded = load_project_context(str(tmp_path))
        assert len(loaded) <= 50 * 1024

    def test_append_adds_separator(self, tmp_path):
        save_project_context(str(tmp_path), "First entry")
        append_project_context(str(tmp_path), "Second entry")
        loaded = load_project_context(str(tmp_path))
        assert "First entry" in loaded
        assert "Second entry" in loaded
        assert loaded.index("First") < loaded.index("Second")


class TestBuildAwarenessBlock:
    def test_includes_manifest(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        block = build_awareness_block(str(tmp_path))
        assert "testproj" in block

    def test_includes_team_members(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Coder", "impl", True),
        ]))
        block = build_awareness_block(str(tmp_path))
        assert "Coder" in block
        assert "sk1" in block

    def test_includes_context_memory(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_project_context(str(tmp_path), "## Active notes\nWorking on auth")
        block = build_awareness_block(str(tmp_path))
        assert "Working on auth" in block

    def test_truncates_large_manifest(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        manifest_path = tmp_path / ".crabcakes" / "project.md"
        manifest_path.write_text("x" * 5000)
        block = build_awareness_block(str(tmp_path))
        assert "truncated" in block


class TestBuildAwarenessSnapshot:
    def test_includes_project_name(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["project_name"] == os.path.basename(str(tmp_path))

    def test_includes_team_size(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Agent1"),
            TeamMember("sk2", "Agent2"),
        ]))
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["team_size"] == 2

    def test_default_tasks_zero(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["tasks"]["total"] == 0


class TestDetectTechStack:
    def test_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        stack = detect_tech_stack(str(tmp_path))
        assert "python" in stack

    def test_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        stack = detect_tech_stack(str(tmp_path))
        assert "javascript" in stack
        assert "node" in stack

    def test_empty_dir_returns_empty(self, tmp_path):
        stack = detect_tech_stack(str(tmp_path))
        assert stack == []

    def test_deduplicates(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "requirements.txt").write_text("")
        stack = detect_tech_stack(str(tmp_path))
        assert stack.count("python") == 1
