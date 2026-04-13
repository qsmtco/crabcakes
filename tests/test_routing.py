# tests/test_routing.py
# Tests for models/routing.py — AgentRoutingTable.
#
# Principle: test the contract — each public method's documented behavior.

import pytest
from models import AgentRoutingTable


@pytest.fixture
def rt():
    return AgentRoutingTable()


# ── add ───────────────────────────────────────────────────────────────────────

class TestAdd:
    def test_add_then_get_project_returns_correct_name(self, rt):
        rt.add("agent:qaster:1", "myproj")
        assert rt.get_project("agent:qaster:1") == "myproj"

    def test_add_overwrites_existing_project(self, rt):
        rt.add("agent:qaster:1", "projA")
        rt.add("agent:qaster:1", "projB")
        assert rt.get_project("agent:qaster:1") == "projB"

    def test_add_multiple_agents_same_project(self, rt):
        rt.add("agent:a", "proj1")
        rt.add("agent:b", "proj1")
        assert rt.get_project("agent:a") == "proj1"
        assert rt.get_project("agent:b") == "proj1"


# ── remove ─────────────────────────────────────────────────────────────────────

class TestRemove:
    def test_remove_clears_entry(self, rt):
        rt.add("agent:qaster:1", "myproj")
        rt.remove("agent:qaster:1")
        assert rt.get_project("agent:qaster:1") is None

    def test_remove_missing_key_is_noop(self, rt):
        rt.add("agent:a", "proj")
        rt.remove("agent:does_not_exist")  # must not raise
        assert rt.get_project("agent:a") == "proj"


# ── remove_project ─────────────────────────────────────────────────────────────

class TestRemoveProject:
    def test_remove_project_clears_all_its_members(self, rt):
        rt.add("agent:a", "proj1")
        rt.add("agent:b", "proj1")
        rt.add("agent:c", "proj2")
        rt.remove_project("proj1")
        assert rt.get_project("agent:a") is None
        assert rt.get_project("agent:b") is None
        assert rt.get_project("agent:c") == "proj2"

    def test_remove_project_missing_is_noop(self, rt):
        rt.add("agent:a", "proj1")
        rt.remove_project("nonexistent")  # must not raise
        assert rt.get_project("agent:a") == "proj1"


# ── is_routed ──────────────────────────────────────────────────────────────────

class TestIsRouted:
    def test_true_after_add(self, rt):
        rt.add("agent:qaster:1", "myproj")
        assert rt.is_routed("agent:qaster:1") is True

    def test_false_for_unknown_key(self, rt):
        assert rt.is_routed("agent:unknown") is False

    def test_false_after_remove(self, rt):
        rt.add("agent:qaster:1", "myproj")
        rt.remove("agent:qaster:1")
        assert rt.is_routed("agent:qaster:1") is False


# ── get_project ────────────────────────────────────────────────────────────────

class TestGetProject:
    def test_returns_project_name(self, rt):
        rt.add("agent:qaster:1", "myproj")
        assert rt.get_project("agent:qaster:1") == "myproj"

    def test_returns_none_for_unknown_key(self, rt):
        assert rt.get_project("agent:unknown") is None


# ── clear ─────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_removes_all_entries(self, rt):
        rt.add("agent:a", "proj1")
        rt.add("agent:b", "proj2")
        rt.clear()
        assert rt.is_routed("agent:a") is False
        assert rt.is_routed("agent:b") is False
