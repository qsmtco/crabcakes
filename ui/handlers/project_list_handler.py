# ui/handlers/project_list_handler.py
# Project list handler — owns project card data, colors, and scan logic.
#
# Owns: project color assignment (path → hex color), project scan results.
# Does NOT own: UI widgets, other handlers.
#
# Architecture rule: does NOT import other handlers. Window wires callbacks.
# Does NOT import GTK — purely logic and data.

from typing import Callable

from models.colors import AGENT_COLORS, next_project_color
from utils.projects import load_projects


class ProjectListHandler:
    """
    Owns project card data: color assignment, project scan, and open events.

    Per Section 8.6: all new UI logic lives in a handler, not in views or window.

    Args:
        on_project_opened: Callable[[str, str], None] — fires when a project card is clicked.
                           Receives (name, path). Window wires this to ProjectHandler.open_project.
    """

    def __init__(self, *, on_project_opened: Callable | None = None):
        self._on_project_opened = on_project_opened
        # Round-robin project color assignment
        self._project_colors: dict[str, str] = {}  # path → hex color
        self._search_query: str = ""  # active search filter

    # ── Public API ───────────────────────────────────────────────────────────

    def get_projects(self) -> list[tuple[str, str, str]]:
        """
        Return all projects as (name, path, color).
        Loads project list and assigns colors on first access.
        Colors persist across calls — same path always gets same color.
        """
        raw = load_projects()
        result: list[tuple[str, str, str]] = []
        for name, path in raw:
            if path not in self._project_colors:
                self._project_colors[path] = next_project_color()
            result.append((name, path, self._project_colors[path]))
        return result

    def get_project_color(self, path: str) -> str:
        """
        Return the assigned color for a path, assigning one if not yet known.
        """
        if path not in self._project_colors:
            self._project_colors[path] = next_project_color()
        return self._project_colors[path]

    def on_project_clicked(self, name: str, path: str):
        """
        Handle a project card click. Fires the callback if set.
        """
        if self._on_project_opened:
            self._on_project_opened(name, path)

    def search(self, query: str) -> list[tuple[str, str, str]]:
        """
        Set search filter and return filtered projects.
        Follows the same pattern as PromptsHandler.search().
        """
        self._search_query = query.strip().lower()
        return self._filtered_projects()

    def clear_search(self) -> None:
        """Reset search filter."""
        self._search_query = ""

    # ── Private ──────────────────────────────────────────────────────────────

    def _filtered_projects(self) -> list[tuple[str, str, str]]:
        """Return projects filtered by current search query."""
        all_projects = self.get_projects()
        if not self._search_query:
            return all_projects
        return [
            (name, path, color)
            for name, path, color in all_projects
            if self._search_query in name.lower()
        ]