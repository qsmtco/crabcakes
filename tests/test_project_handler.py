# tests/test_project_handler.py
# Tests for ui/handlers/project_handler.py — ProjectHandler.
#
# Principle: test the failure modes that would break callers.
# Mock MainContent, LeftPanel, projects module at the boundary.
# Do NOT mock internal state.

import pytest
from unittest.mock import MagicMock


class FakeGLib:
    """Simulates GLib.idle_add — stores callbacks but does NOT run them."""

    def __init__(self):
        self._pending = []

    def idle_add(self, fn, *args, **kwargs):
        self._pending.append((fn, args, kwargs))
        return len(self._pending)

    def dispatch_all(self):
        """Run all pending callbacks — simulates GTK main loop."""
        results = []
        while self._pending:
            fn, args, kwargs = self._pending.pop(0)
            result = fn(*args, **kwargs)
            results.append(result)
        return results


class FakeProjects:
    def __init__(self):
        self._members = {}

    def load_members(self, project_name):
        return self._members.get(project_name, [])

    def save_members(self, project_name, members):
        self._members[project_name] = list(members)


@pytest.fixture
def fake_glib():
    return FakeGLib()


@pytest.fixture
def fake_projects():
    return FakeProjects()


@pytest.fixture
def mc():
    return MagicMock(name="main_content")


@pytest.fixture
def lp():
    return MagicMock(name="left_panel")


@pytest.fixture
def handler(mc, lp, fake_projects, fake_glib):
    from ui.handlers.project_handler import ProjectHandler
    agent_to_project = {}  # shared dict (same pattern as ChatHandler in window)
    return ProjectHandler(
        main_content=mc,
        left_panel=lp,
        projects_module=fake_projects,
        agent_to_project=agent_to_project,
        GLib_module=fake_glib,
    )


# ── open_project ─────────────────────────────────────────────────────────────

class TestOpenProject:
    def test_creates_project_tab(self, handler, mc, fake_glib):
        handler.open_project("my-project", "/path/to/my-project")
        fake_glib.dispatch_all()
        mc.create_chat_tab.assert_called_once_with("project:my-project", "Project: my-project")

    def test_refreshes_agents_list(self, handler, lp, fake_glib):
        handler.open_project("my-project", "/path/to/my-project")
        fake_glib.dispatch_all()
        lp.refresh_agents_with_project.assert_called_once_with("my-project")

    def test_populates_agent_to_project_lookup(self, handler, fake_projects):
        fake_projects.save_members("my-project", ["agent:a", "agent:b"])
        handler.open_project("my-project", "/path/to/my-project")
        assert handler.get_project_for_agent("agent:a") == "my-project"
        assert handler.get_project_for_agent("agent:b") == "my-project"

    def test_calls_on_project_opened_callback(self, handler, fake_glib):
        cb = MagicMock()
        handler.set_on_project_opened(cb)
        handler.open_project("my-project", "/path/to/my-project")
        fake_glib.dispatch_all()
        cb.assert_called_once_with("my-project", "/path/to/my-project")


# ── toggle_agent ─────────────────────────────────────────────────────────────

class TestToggleAgent:
    def test_adds_new_agent(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:1"])
        handler.open_project("proj", "/p")
        handler.toggle_agent("agent:2")
        assert fake_projects.load_members("proj") == ["agent:1", "agent:2"]

    def test_removes_existing_agent(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:1", "agent:2"])
        handler.open_project("proj", "/p")
        handler.toggle_agent("agent:1")
        assert fake_projects.load_members("proj") == ["agent:2"]

    def test_refreshes_agents_list_after_toggle(self, handler, lp, fake_projects, fake_glib):
        fake_projects.save_members("proj", ["agent:1"])
        handler.open_project("proj", "/p")
        lp.reset_mock()
        handler.toggle_agent("agent:2")
        fake_glib.dispatch_all()
        lp.refresh_agents_with_project.assert_called_with("proj")

    def test_calls_on_members_changed_callback(self, handler, fake_projects, fake_glib):
        fake_projects.save_members("proj", ["agent:1"])
        handler.open_project("proj", "/p")
        cb = MagicMock()
        handler.set_on_members_changed(cb)
        handler.toggle_agent("agent:2")
        fake_glib.dispatch_all()
        cb.assert_called_once_with("proj", ["agent:1", "agent:2"])

    def test_noop_when_no_active_project(self, handler, fake_projects):
        handler.toggle_agent("agent:1")  # no project open
        # no crash — just a no-op


# ── Routing API ───────────────────────────────────────────────────────────────

class TestRoutingApi:
    def test_is_project_session_true_for_member(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:a"])
        handler.open_project("proj", "/p")
        assert handler.is_project_session("agent:a") is True

    def test_is_project_session_false_for_unknown(self, handler):
        assert handler.is_project_session("agent:unknown") is False

    def test_get_project_for_agent_returns_correct_project(self, handler, fake_projects):
        fake_projects.save_members("proj-a", ["agent:x"])
        fake_projects.save_members("proj-b", ["agent:y"])
        handler.open_project("proj-a", "/a")
        handler.open_project("proj-b", "/b")
        assert handler.get_project_for_agent("agent:x") == "proj-a"
        assert handler.get_project_for_agent("agent:y") == "proj-b"

    def test_get_project_members_returns_list(self, handler, fake_projects):
        fake_projects.save_members("proj", ["a", "b", "c"])
        handler.open_project("proj", "/p")
        members = handler.get_project_members("proj")
        assert set(members) == {"a", "b", "c"}

    def test_get_active_project_name_returns_none_initially(self, handler):
        assert handler.get_active_project_name() is None

    def test_get_active_project_name_returns_name_after_open(self, handler):
        handler.open_project("my-proj", "/p")
        assert handler.get_active_project_name() == "my-proj"