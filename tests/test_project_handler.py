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
def handler(lp, fake_projects, fake_glib):
    from ui.handlers.project_handler import ProjectHandler
    from models import AgentRoutingTable
    agent_to_project = AgentRoutingTable()
    return ProjectHandler(
        left_panel=lp,
        projects_module=fake_projects,
        agent_to_project=agent_to_project,
        GLib_module=fake_glib,
    )


# ── open_project ─────────────────────────────────────────────────────────────

class TestOpenProject:
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


# ── Session Switching ────────────────────────────────────────────────────────

class FakeAgentManager:
    """Minimal AgentManager mock for session switching tests."""
    def __init__(self, sessions_by_name=None):
        # sessions_by_name: {agent_name: [session_keys]}
        self._sessions = sessions_by_name or {}
        self._names = {}  # session_key -> name
        for name, keys in self._sessions.items():
            for sk in keys:
                self._names[sk] = name

    def get_sessions(self, agent_name):
        return self._sessions.get(agent_name, [])

    def get_name(self, session_key):
        return self._names.get(session_key, "")


class TestGetAgentSessionInProject:
    def test_returns_matching_session(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:qaster:main"])
        handler.open_project("proj", "/p")
        handler.set_agent_manager(FakeAgentManager(
            sessions_by_name={"qaster": ["agent:qaster:main", "agent:qaster:telegram:123"]}
        ))
        result = handler.get_agent_session_in_project("proj", "qaster")
        assert result == "agent:qaster:main"

    def test_returns_none_if_agent_not_member(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:other:main"])
        handler.open_project("proj", "/p")
        handler.set_agent_manager(FakeAgentManager(
            sessions_by_name={"qaster": ["agent:qaster:main"]}
        ))
        result = handler.get_agent_session_in_project("proj", "qaster")
        assert result is None

    def test_returns_none_if_no_agent_manager(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:qaster:main"])
        handler.open_project("proj", "/p")
        # agent_mgr not set
        result = handler.get_agent_session_in_project("proj", "qaster")
        assert result is None


class TestUpdateAgentSession:
    def test_replaces_session_in_members(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:qaster:main", "agent:qrusher:main"])
        handler.open_project("proj", "/p")
        handler.update_agent_session("proj", "agent:qaster:main", "agent:qaster:telegram:123")
        members = fake_projects.load_members("proj")
        assert "agent:qaster:main" not in members
        assert "agent:qaster:telegram:123" in members
        assert "agent:qrusher:main" in members

    def test_updates_routing_table(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:qaster:main"])
        handler.open_project("proj", "/p")
        handler.update_agent_session("proj", "agent:qaster:main", "agent:qaster:telegram:123")
        assert handler.is_project_session("agent:qaster:telegram:123")
        assert not handler.is_project_session("agent:qaster:main")

    def test_migrates_solo_target(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:qaster:main"])
        handler.open_project("proj", "/p")
        handler.set_solo_target("proj", "agent:qaster:main")
        handler.update_agent_session("proj", "agent:qaster:main", "agent:qaster:telegram:123")
        assert handler.get_solo_target("proj") == "agent:qaster:telegram:123"

    def test_noop_if_old_key_not_member(self, handler, fake_projects):
        fake_projects.save_members("proj", ["agent:other:main"])
        handler.open_project("proj", "/p")
        handler.update_agent_session("proj", "agent:qaster:main", "agent:qaster:telegram:123")
        # No change
        members = fake_projects.load_members("proj")
        assert members == ["agent:other:main"]


# ── /cost command (Phase 2 — token tracking) ────────────────────────────────

class TestCmdCost:
    """Spec: docs/specs/SPEC-token-tracking-fix.md AC-1/2/3/5.

    cmd_cost reads each member's (tokens, cost) from a persisted
    conversation file (special:*) or the injected in-memory cache
    (agent:*) and formats a table. Falls back to (0, 0.0) when neither
    source is available.
    """

    def _make_cmd(self, project_name: str):
        from models.command import Command
        return Command(name="cost", source_session_key=f"project:{project_name}")

    def test_reads_total_tokens_and_cost_from_conversation_file(
        self, handler, fake_projects, tmp_path, monkeypatch
    ):
        """AC-1/AC-2: special agent conversation file with real usage data."""
        import json
        import os
        from utils.config import get_config_dir

        # Arrange: configure to use tmp config dir, write a conversation file
        config_dir = tmp_path / "crabcakes"
        (config_dir / "conversations").mkdir(parents=True)
        monkeypatch.setattr(
            "utils.config.get_config_dir", lambda: str(config_dir)
        )
        # Also patch where the handler imports from (deferred import inside the
        # function pulls the live `get_config_dir` symbol each call).
        monkeypatch.setattr(
            "ui.handlers.project_handler.get_config_dir", lambda: str(config_dir),
            raising=False,
        )

        # Write a realistic conversation file
        conv_data = {
            "session_key": "special:coder",
            "agent_name": "coder",
            "total_tokens": 5000,
            "total_cost": 0.15,
            "step_count": 3,
            "messages": [],
            "system_prompt": "",
        }
        (config_dir / "conversations" / "special:coder.json").write_text(
            json.dumps(conv_data)
        )

        # Project has one special member
        fake_projects.save_members("myproj", ["special:coder"])
        handler.open_project("myproj", "/p")

        # Act
        result = handler.cmd_cost(self._make_cmd("myproj"))

        # Assert: real numbers, not zeros
        assert result.handled is True
        text = result.response_text
        assert "5,000 tokens" in text, f"expected 5,000 tokens in output, got: {text!r}"
        assert "$0.1500" in text, f"expected $0.1500 in output, got: {text!r}"
        # Old stub text must be gone
        assert "contact gateway" not in text
        assert "usage API" not in text

    def test_missing_conversation_file_shows_zeros(
        self, handler, fake_projects, tmp_path, monkeypatch
    ):
        """AC-3: no file, no cache → 0 tokens / $0.0000."""
        from utils.config import get_config_dir
        config_dir = tmp_path / "crabcakes"
        (config_dir / "conversations").mkdir(parents=True)
        monkeypatch.setattr(
            "utils.config.get_config_dir", lambda: str(config_dir)
        )
        monkeypatch.setattr(
            "ui.handlers.project_handler.get_config_dir", lambda: str(config_dir),
            raising=False,
        )

        # No conversation file written. _runtime_usage_fn is None (default).
        fake_projects.save_members("myproj", ["special:coder"])
        handler.open_project("myproj", "/p")

        result = handler.cmd_cost(self._make_cmd("myproj"))

        assert result.handled is True
        text = result.response_text
        assert "0 tokens" in text, f"expected 0 tokens in output, got: {text!r}"
        assert "$0.0000" in text, f"expected $0.0000 in output, got: {text!r}"
        assert "contact gateway" not in text

    def test_corrupted_conversation_file_falls_back_to_zeros(
        self, handler, fake_projects, tmp_path, monkeypatch
    ):
        """Sad path: malformed JSON must NOT crash — return (0, 0.0)."""
        from utils.config import get_config_dir
        config_dir = tmp_path / "crabcakes"
        (config_dir / "conversations").mkdir(parents=True)
        monkeypatch.setattr(
            "utils.config.get_config_dir", lambda: str(config_dir)
        )
        monkeypatch.setattr(
            "ui.handlers.project_handler.get_config_dir", lambda: str(config_dir),
            raising=False,
        )

        # Write a corrupted conversation file
        (config_dir / "conversations" / "special:coder.json").write_text(
            "{this is not valid json"
        )

        fake_projects.save_members("myproj", ["special:coder"])
        handler.open_project("myproj", "/p")

        # Must not raise
        result = handler.cmd_cost(self._make_cmd("myproj"))

        assert result.handled is True
        text = result.response_text
        assert "0 tokens" in text, f"expected graceful 0 tokens fallback, got: {text!r}"
        assert "$0.0000" in text, f"expected graceful $0.0000 fallback, got: {text!r}"

    def test_in_memory_cache_used_for_gateway_agents(
        self, handler, fake_projects
    ):
        """AC-5: gateway agent (agent:*) uses injected in-memory cache."""
        # Gateway agent — no conversation file path
        fake_projects.save_members("myproj", ["agent:qtr:telegram:1"])
        handler.open_project("myproj", "/p")

        # Wire the runtime usage callback with cached data
        handler.set_runtime_usage_fn(
            lambda: {"agent:qtr:telegram:1": (12345, 0.0234)}
        )

        result = handler.cmd_cost(self._make_cmd("myproj"))

        assert result.handled is True
        text = result.response_text
        assert "12,345 tokens" in text, f"expected 12,345 tokens, got: {text!r}"
        assert "$0.0234" in text, f"expected $0.0234, got: {text!r}"

    def test_runtime_usage_fn_exception_falls_back_gracefully(
        self, handler, fake_projects
    ):
        """Sad path: misbehaving callback must not crash cmd_cost."""
        fake_projects.save_members("myproj", ["agent:qtr:telegram:1"])
        handler.open_project("myproj", "/p")

        def boom():
            raise RuntimeError("runtime handler exploded")
        handler.set_runtime_usage_fn(boom)

        # Must not raise
        result = handler.cmd_cost(self._make_cmd("myproj"))
        assert result.handled is True
        # No file + broken cache → zeros
        assert "0 tokens" in result.response_text
        assert "$0.0000" in result.response_text

    def test_non_project_session_returns_hint(self, handler, fake_projects):
        """Guard: /cost outside a project tab returns the hint message."""
        from models.command import Command
        fake_projects.save_members("myproj", ["special:coder"])
        handler.open_project("myproj", "/p")

        # Simulate /cost in an agent tab (not a project tab)
        cmd = Command(name="cost", source_session_key="special:coder")
        result = handler.cmd_cost(cmd)
        assert result.handled is True
        assert "Open a project tab" in result.response_text