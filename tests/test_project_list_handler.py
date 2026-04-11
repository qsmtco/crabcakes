# tests/test_project_list_handler.py
# Tests for ProjectListHandler — project card data and color assignment.

import pytest
from unittest.mock import patch


class MockProjectListHandler:
    """Minimal mock for standalone testing without GTK imports."""

    def __init__(self, *, on_project_opened=None):
        self._on_project_opened = on_project_opened
        self._project_colors = {}

        # Patch AGENT_COLORS so tests are deterministic
        self._colors = ["#111111", "#222222", "#333333"]

    def get_projects(self):
        return []  # stub — override in tests

    def get_project_color(self, path):
        if path not in self._project_colors:
            self._project_colors[path] = f"#{len(self._project_colors):06d}"
        return self._project_colors[path]

    def on_project_clicked(self, name, path):
        if self._on_project_opened:
            self._on_project_opened(name, path)


class TestProjectListHandlerImports:
    def test_import(self):
        from ui.handlers.project_list_handler import ProjectListHandler
        assert ProjectListHandler is not None

    def test_instantiation(self):
        from ui.handlers.project_list_handler import ProjectListHandler
        h = ProjectListHandler()
        assert h is not None


class TestColorAssignment:
    def test_assigns_colors_from_palette(self):
        from ui.handlers.project_list_handler import ProjectListHandler
        from models.colors import AGENT_COLORS

        h = ProjectListHandler()
        color = h.get_project_color("/tmp/test-project")
        assert color in AGENT_COLORS

    def test_same_path_returns_same_color(self):
        from ui.handlers.project_list_handler import ProjectListHandler

        h = ProjectListHandler()
        c1 = h.get_project_color("/tmp/path-a")
        c2 = h.get_project_color("/tmp/path-a")
        assert c1 == c2

    def test_different_paths_get_different_colors(self):
        from ui.handlers.project_list_handler import ProjectListHandler

        h = ProjectListHandler()
        colors = [h.get_project_color(f"/tmp/proj-{i}") for i in range(5)]
        # Round-robin may repeat, but at least 2 should differ in 5
        assert len(set(colors)) >= 2

    def test_round_robin_wraps_around(self):
        from ui.handlers.project_list_handler import ProjectListHandler
        from models.colors import AGENT_COLORS

        h = ProjectListHandler()
        # Fill the palette
        palette_size = len(AGENT_COLORS)
        first_colors = [h.get_project_color(f"/tmp/p{i}") for i in range(palette_size)]
        # The next project should loop back to the first color
        next_color = h.get_project_color(f"/tmp/p{palette_size}")
        assert next_color == first_colors[0]


class TestCallback:
    def test_callback_fires_on_click(self):
        from ui.handlers.project_list_handler import ProjectListHandler

        fired = []
        h = ProjectListHandler(on_project_opened=lambda n, p: fired.append((n, p)))
        h.on_project_clicked("MyProject", "/path/to/my")
        assert fired == [("MyProject", "/path/to/my")]

    def test_no_callback_is_silent(self):
        from ui.handlers.project_list_handler import ProjectListHandler

        h = ProjectListHandler(on_project_opened=None)
        h.on_project_clicked("Any", "/any")  # must not raise

    def test_callback_with_none_set(self):
        from ui.handlers.project_list_handler import ProjectListHandler

        h = ProjectListHandler()
        h._on_project_opened = None
        h.on_project_clicked("Any", "/any")  # must not raise


class TestGetProjects:
    @patch("ui.handlers.project_list_handler.load_projects")
    def test_returns_project_tuples(self, mock_load):
        from ui.handlers.project_list_handler import ProjectListHandler

        mock_load.return_value = [("Alpha", "/path/alpha"), ("Beta", "/path/beta")]
        h = ProjectListHandler()
        projects = h.get_projects()
        assert len(projects) == 2
        for name, path, color in projects:
            assert isinstance(name, str)
            assert isinstance(path, str)
            assert color.startswith("#")

    @patch("ui.handlers.project_list_handler.load_projects")
    def test_color_persists_across_calls(self, mock_load):
        from ui.handlers.project_list_handler import ProjectListHandler

        mock_load.return_value = [("X", "/x")]
        h = ProjectListHandler()
        p1 = h.get_projects()
        p2 = h.get_projects()
        assert p1[0][2] == p2[0][2]  # same color

    @patch("ui.handlers.project_list_handler.load_projects")
    def test_empty_project_list(self, mock_load):
        from ui.handlers.project_list_handler import ProjectListHandler

        mock_load.return_value = []
        h = ProjectListHandler()
        assert h.get_projects() == []