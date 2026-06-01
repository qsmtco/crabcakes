# tests/test_create_project.py
# Tests for ProjectHandler.create_project() — new project creation.
#
# Covers: success path, duplicate rejection, empty name,
# directory already exists, .crabcakes/ initialization.

import os
import tempfile

import pytest

from models.routing import AgentRoutingTable
from ui.handlers.project_handler import ProjectHandler
from unittest.mock import MagicMock

import utils.project_awareness as pa


def _make_handler(projects_dir: str) -> ProjectHandler:
    """Create a ProjectHandler with mocked deps and a real projects dir."""
    projects_mod = MagicMock()
    projects_mod._PROJECTS_DIR_REF = [projects_dir]
    projects_mod.load_projects.return_value = []

    ph = ProjectHandler(
        left_panel=MagicMock(),
        projects_module=projects_mod,
        agent_to_project=AgentRoutingTable(),
        awareness_module=pa,
    )
    return ph


class TestCreateProject:

    def test_creates_directory(self, tmp_path):
        """create_project creates the project directory."""
        ph = _make_handler(str(tmp_path))
        result = ph.create_project("myproject")
        assert result is not None
        assert os.path.isdir(result)

    def test_creates_crabcakes_dir(self, tmp_path):
        """create_project initializes .crabcakes/ with all artifacts."""
        ph = _make_handler(str(tmp_path))
        result = ph.create_project("myproject")
        crab_dir = os.path.join(result, ".crabcakes")
        assert os.path.isdir(crab_dir)
        assert os.path.isfile(os.path.join(crab_dir, "project.md"))
        assert os.path.isfile(os.path.join(crab_dir, "team.json"))
        assert os.path.isfile(os.path.join(crab_dir, "context.md"))
        assert os.path.isfile(os.path.join(crab_dir, "awareness.json"))

    def test_default_path_is_under_projects_dir(self, tmp_path):
        """Without explicit path, project is created in projects dir."""
        ph = _make_handler(str(tmp_path))
        result = ph.create_project("myproject")
        assert result == os.path.join(str(tmp_path), "myproject")

    def test_custom_path(self, tmp_path):
        """Explicit path overrides default location."""
        ph = _make_handler(str(tmp_path))
        custom = os.path.join(str(tmp_path), "custom-location")
        result = ph.create_project("myproject", path=custom)
        assert result == custom
        assert os.path.isdir(custom)

    def test_rejects_empty_name(self, tmp_path):
        """Empty name returns None."""
        ph = _make_handler(str(tmp_path))
        assert ph.create_project("") is None

    def test_rejects_whitespace_name(self, tmp_path):
        """Whitespace-only name returns None."""
        ph = _make_handler(str(tmp_path))
        assert ph.create_project("   ") is None

    def test_rejects_duplicate(self, tmp_path):
        """Creating a project with the same name twice fails on second call."""
        ph = _make_handler(str(tmp_path))
        result1 = ph.create_project("myproject")
        assert result1 is not None
        result2 = ph.create_project("myproject")
        assert result2 is None

    def test_rejects_existing_directory(self, tmp_path):
        """Returns None if directory already exists (even if not a crabcakes project)."""
        ph = _make_handler(str(tmp_path))
        os.makedirs(os.path.join(str(tmp_path), "existing"))
        assert ph.create_project("existing") is None

    def test_strips_name_whitespace(self, tmp_path):
        """Leading/trailing whitespace is stripped from name."""
        ph = _make_handler(str(tmp_path))
        result = ph.create_project("  myproject  ")
        assert result is not None
        assert "myproject" in result

    def test_calls_open_project(self, tmp_path):
        """create_project calls open_project after creating directory."""
        ph = _make_handler(str(tmp_path))
        ph.open_project = MagicMock()
        result = ph.create_project("myproject")
        assert result is not None
        ph.open_project.assert_called_once()
        call_args = ph.open_project.call_args
        assert call_args[0][0] == "myproject"

    def test_sets_active_project(self, tmp_path):
        """After create, active project name and path are set."""
        ph = _make_handler(str(tmp_path))
        result = ph.create_project("myproject")
        assert ph.get_active_project_name() == "myproject"
        assert ph.get_active_project_path() == result
