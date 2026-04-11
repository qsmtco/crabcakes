# tests/test_projects.py
# Tests for utils/projects.py — file I/O helpers.
#
# Principle: test the failure modes — missing files, empty dirs,
# invalid JSON, permissions — not the happy path.

import json
import os
import pytest
from utils.projects import (
    load_projects,
    scan_directory,
    load_members,
    save_members,
)


class TestLoadProjects:
    """load_projects reads _PROJECTS_DIR_REF — must handle missing/empty gracefully."""

    def test_missing_projects_dir_returns_empty_list(self, tmp_config_dir, monkeypatch):
        """Non-existent projects directory must return [], not raise."""
        from utils import projects as proj_mod
        fake_projects = tmp_config_dir.parent / "non_existent_projects"
        monkeypatch.setattr(proj_mod, "_PROJECTS_DIR_REF", [str(fake_projects)])

        result = load_projects()
        assert result == []

    def test_empty_projects_dir_returns_empty_list(self, tmp_config_dir, monkeypatch):
        """Empty directory must return [], not [].  """
        from utils import projects as proj_mod
        empty_dir = tmp_config_dir / "empty_projects"
        empty_dir.mkdir()
        monkeypatch.setattr(proj_mod, "_PROJECTS_DIR_REF", [str(empty_dir)])

        result = load_projects()
        assert result == []

    def test_returns_only_directories_not_files(self, tmp_config_dir, monkeypatch):
        """Files in projects dir must be filtered out — only dirs are projects."""
        from utils import projects as proj_mod
        projects_dir = tmp_config_dir / "projects"
        projects_dir.mkdir()
        (projects_dir / "real_project").mkdir()  # dir
        (projects_dir / "not_a_project.txt").write_text("")  # file

        monkeypatch.setattr(proj_mod, "_PROJECTS_DIR_REF", [str(projects_dir)])

        result = load_projects()
        assert len(result) == 1
        assert result[0][0] == "real_project"
        assert result[0][1] == str(projects_dir / "real_project")


class TestScanDirectory:
    """scan_directory is called by TreeView for lazy-loading — must be robust."""

    def test_missing_directory_returns_empty_list(self):
        """Non-existent path must return [], not raise."""
        result = scan_directory("/this/path/does/not/exist/anywhere")
        assert result == []

    def test_empty_directory_returns_empty_list(self, tmp_path):
        """Empty directory returns [].  """
        result = scan_directory(str(tmp_path))
        assert result == []

    def test_skips_pycache(self, tmp_path):
        """__pycache__ directories must not appear in results."""
        (tmp_path / "good_dir").mkdir()
        (tmp_path / "__pycache__").mkdir()

        result = scan_directory(str(tmp_path))
        names = [n for n, _, _ in result]
        assert "__pycache__" not in names

    def test_skips_dotfiles(self, tmp_path):
        """.git, .hidden, dot-prefixed dirs must all be skipped."""
        (tmp_path / "visible").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".env").mkdir()

        result = scan_directory(str(tmp_path))
        names = [n for n, _, _ in result]
        assert ".git" not in names
        assert ".hidden" not in names
        assert ".env" not in names
        assert "visible" in names

    def test_returns_tuples_with_three_elements(self, tmp_path):
        """Each result must be (name, full_path, is_dir) — callers unpack all three."""
        (tmp_path / "myfile.txt").write_text("")
        (tmp_path / "mydir").mkdir()

        result = scan_directory(str(tmp_path))
        for name, full_path, is_dir in result:
            assert isinstance(name, str)
            assert isinstance(full_path, str)
            assert isinstance(is_dir, bool)
            assert full_path.endswith(name)


class TestLoadMembers:
    """load_members reads members.json — must handle corruption and absence."""

    def test_missing_file_returns_empty_list(self, tmp_config_dir):
        """members.json not found must return [], not raise."""
        result = load_members("nonexistent_project")
        assert result == []

    def test_empty_json_array_returns_empty_list(self, tmp_config_dir):
        """members.json containing [] must return [], not [None] or None."""
        project_dir = tmp_config_dir / "projects" / "empty_project"
        project_dir.mkdir(parents=True)
        (project_dir / "members.json").write_text("[]\n")

        result = load_members("empty_project")
        assert result == []

    def test_invalid_json_returns_empty_list(self, tmp_config_dir):
        """Corrupt JSON must not raise — caller gets [] and can handle gracefully."""
        project_dir = tmp_config_dir / "projects" / "corrupt_project"
        project_dir.mkdir(parents=True)
        (project_dir / "members.json").write_text("{ this is not json }")

        result = load_members("corrupt_project")
        assert result == []

    def test_whitespace_only_json_returns_empty_list(self, tmp_config_dir):
        """Whitespace-only file must be handled."""
        project_dir = tmp_config_dir / "projects" / "blank_project"
        project_dir.mkdir(parents=True)
        (project_dir / "members.json").write_text("   \n  ")

        result = load_members("blank_project")
        assert result == []


class TestSaveMembers:
    """save_members writes members.json — must handle directory creation."""

    def test_creates_intermediate_directories(self, tmp_config_dir):
        """Saving members for a new project must create the full directory path."""
        project_name = "brand_new_project_xyz"

        save_members(project_name, ["sk1", "sk2"])

        project_dir = tmp_config_dir / "projects" / project_name
        assert project_dir.exists()
        assert (project_dir / "members.json").exists()

    def test_overwrites_existing_file(self, tmp_config_dir):
        """Calling save_members twice on same project must overwrite, not append."""
        project_name = "overwrite_test"

        save_members(project_name, ["sk1"])
        save_members(project_name, ["sk2", "sk3"])

        result = load_members(project_name)
        assert result == ["sk2", "sk3"]

    def test_empty_list_saves_valid_json(self, tmp_config_dir):
        """Saving empty member list must produce valid JSON [].  """
        project_name = "empty_members"

        save_members(project_name, [])

        project_dir = tmp_config_dir / "projects" / project_name
        content = (project_dir / "members.json").read_text()
        parsed = json.loads(content)
        assert parsed == []

    def test_roundtrip_single_member(self, tmp_config_dir):
        """save then load must return identical data."""
        project_name = "roundtrip"
        original = ["agent:qaster:telegram:direct:7478874934"]

        save_members(project_name, original)
        result = load_members(project_name)

        assert result == original

    def test_roundtrip_multiple_members(self, tmp_config_dir):
        """Multiple members must survive save/load cycle."""
        project_name = "multi_roundtrip"
        original = [
            "agent:qaster:telegram:direct:7478874934",
            "agent:main:cron:575df3a8:run:e203c5ae",
            "agent:qtr:telegram:direct:7478874934",
        ]

        save_members(project_name, original)
        result = load_members(project_name)

        assert result == original

    def test_special_characters_in_session_keys_preserved(self, tmp_config_dir):
        """Session keys with colons, dashes, underscores must not be corrupted."""
        project_name = "special_chars"
        original = ["agent:qaster:telegram:direct:7478874934:run:abc-123_x"]

        save_members(project_name, original)
        result = load_members(project_name)

        assert result == original
