# tests/test_project_search.py
# Tests for ProjectListHandler.search() — project filtering.

import pytest

from ui.handlers.project_list_handler import ProjectListHandler


class TestProjectListSearch:

    def test_search_filters_by_name(self):
        """search() returns only projects matching the query."""
        h = ProjectListHandler()
        all_projects = h.get_projects()
        if not all_projects:
            pytest.skip("No projects in ~/projects")

        # Pick a name fragment that should match at least one
        name = all_projects[0][0]
        fragment = name[:3].lower()
        result = h.search(fragment)
        assert len(result) >= 1
        for n, _, _ in result:
            assert fragment in n.lower()

    def test_search_case_insensitive(self):
        """Search is case-insensitive."""
        h = ProjectListHandler()
        all_projects = h.get_projects()
        if not all_projects:
            pytest.skip("No projects in ~/projects")

        name = all_projects[0][0]
        result_lower = h.search(name.lower())
        result_upper = h.search(name.upper())
        assert len(result_lower) == len(result_upper)

    def test_empty_query_returns_all(self):
        """Empty search query returns all projects."""
        h = ProjectListHandler()
        all_projects = h.get_projects()
        result = h.search("")
        assert len(result) == len(all_projects)

    def test_nonsense_query_returns_empty(self):
        """Query matching nothing returns empty list."""
        h = ProjectListHandler()
        result = h.search("zzzzz_nonexistent_project_xyz")
        assert result == []

    def test_clear_search_resets_filter(self):
        """clear_search() resets the filter."""
        h = ProjectListHandler()
        h.search("zzz")
        assert h._search_query == "zzz"
        h.clear_search()
        assert h._search_query == ""
        all_projects = h.get_projects()
        filtered = h._filtered_projects()
        assert len(filtered) == len(all_projects)

    def test_search_preserves_colors(self):
        """Filtered results keep their assigned colors."""
        h = ProjectListHandler()
        all_projects = h.get_projects()
        if not all_projects:
            pytest.skip("No projects in ~/projects")

        name = all_projects[0][0]
        _, _, color_all = all_projects[0]
        result = h.search(name)
        _, _, color_filtered = result[0]
        assert color_all == color_filtered

    def test_filtered_projects_matches_search(self):
        """_filtered_projects() returns same as search()."""
        h = ProjectListHandler()
        all_projects = h.get_projects()
        if not all_projects:
            pytest.skip("No projects in ~/projects")

        search_result = h.search(all_projects[0][0][:3])
        filtered_result = h._filtered_projects()
        assert search_result == filtered_result
