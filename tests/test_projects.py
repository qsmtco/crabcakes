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
    """load_members reads team.json via project_awareness — must handle absence gracefully."""

    def test_missing_project_returns_empty_list(self, tmp_config_dir):
        """Project not found must return [], not raise."""
        result = load_members("nonexistent_project")
        assert result == []

    def test_empty_team_returns_empty_list(self, tmp_path, tmp_config_dir, monkeypatch):
        """team.json with no members must return []."""
        import utils.projects as proj_mod
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_dir = projects_dir / "empty_project"
        project_dir.mkdir()
        proj_mod._PROJECTS_DIR_REF[0] = str(projects_dir)
        try:
            # Initialize .crabcakes with empty team
            from utils.project_awareness import init_project_config
            init_project_config(str(project_dir), "empty_project")
            result = load_members("empty_project")
            assert result == []
        finally:
            proj_mod._PROJECTS_DIR_REF[0] = proj_mod.get_projects_dir()


class TestSaveMembers:
    """save_members writes team.json via project_awareness."""

    def test_creates_crabcakes_dir(self, tmp_path, tmp_config_dir, monkeypatch):
        """Saving members must create .crabcakes/team.json in the project directory."""
        import utils.projects as proj_mod
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_dir = projects_dir / "brand_new_project_xyz"
        project_dir.mkdir()
        proj_mod._PROJECTS_DIR_REF[0] = str(projects_dir)
        try:
            from utils.project_awareness import init_project_config
            init_project_config(str(project_dir), "brand_new_project_xyz")
            save_members("brand_new_project_xyz", ["sk1", "sk2"])
            assert (project_dir / ".crabcakes" / "team.json").exists()
        finally:
            proj_mod._PROJECTS_DIR_REF[0] = proj_mod.get_projects_dir()

    def test_overwrites_existing_file(self, tmp_path, tmp_config_dir, monkeypatch):
        """Calling save_members twice on same project must overwrite, not append."""
        import utils.projects as proj_mod
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_dir = projects_dir / "overwrite_test"
        project_dir.mkdir()
        proj_mod._PROJECTS_DIR_REF[0] = str(projects_dir)
        try:
            from utils.project_awareness import init_project_config
            init_project_config(str(project_dir), "overwrite_test")
            save_members("overwrite_test", ["sk1"])
            save_members("overwrite_test", ["sk2", "sk3"])
            result = load_members("overwrite_test")
            assert result == ["sk2", "sk3"]
        finally:
            proj_mod._PROJECTS_DIR_REF[0] = proj_mod.get_projects_dir()

    def _setup_project(self, tmp_path, monkeypatch, project_name):
        """Helper: create a temp projects dir with one project, patch _PROJECTS_DIR_REF."""
        import utils.projects as proj_mod
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_dir = projects_dir / project_name
        project_dir.mkdir()
        proj_mod._PROJECTS_DIR_REF[0] = str(projects_dir)
        from utils.project_awareness import init_project_config
        init_project_config(str(project_dir), project_name)
        return proj_mod, project_dir

    def _teardown(self, proj_mod):
        import utils.projects as pm
        proj_mod._PROJECTS_DIR_REF[0] = pm.get_projects_dir()

    def test_empty_list_saves_valid_json(self, tmp_path, tmp_config_dir, monkeypatch):
        """Saving empty member list must produce valid team.json."""
        proj_mod, project_dir = self._setup_project(tmp_path, monkeypatch, "empty_members")
        try:
            save_members("empty_members", [])
            result = load_members("empty_members")
            assert result == []
        finally:
            self._teardown(proj_mod)

    def test_roundtrip_single_member(self, tmp_path, tmp_config_dir, monkeypatch):
        """save then load must return identical data."""
        proj_mod, project_dir = self._setup_project(tmp_path, monkeypatch, "roundtrip")
        try:
            original = ["agent:qaster:telegram:direct:7478874934"]
            save_members("roundtrip", original)
            result = load_members("roundtrip")
            assert result == original
        finally:
            self._teardown(proj_mod)

    def test_roundtrip_multiple_members(self, tmp_path, tmp_config_dir, monkeypatch):
        """Multiple members must survive save/load cycle."""
        proj_mod, project_dir = self._setup_project(tmp_path, monkeypatch, "multi_roundtrip")
        try:
            original = [
                "agent:qaster:telegram:direct:7478874934",
                "agent:main:cron:575df3a8:run:e203c5ae",
                "agent:qtr:telegram:direct:7478874934",
            ]
            save_members("multi_roundtrip", original)
            result = load_members("multi_roundtrip")
            assert result == original
        finally:
            self._teardown(proj_mod)

    def test_special_characters_in_session_keys_preserved(self, tmp_path, tmp_config_dir, monkeypatch):
        """Session keys with colons, dashes, underscores must not be corrupted."""
        proj_mod, project_dir = self._setup_project(tmp_path, monkeypatch, "special_chars")
        try:
            original = ["agent:qaster:telegram:direct:7478874934:run:abc-123_x"]
            save_members("special_chars", original)
            result = load_members("special_chars")
            assert result == original
        finally:
            self._teardown(proj_mod)
