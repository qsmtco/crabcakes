# tests/test_agents.py
# Tests for models/agents.py — AgentManager.
#
# Principle: test the edge cases that could break callers.
# These are the cases that GLib callbacks, UI handlers, and routing code depend on.

import pytest
from models.agents import AgentManager


class TestGetSessions:
    """get_sessions is called by the session switch menu — an empty list or wrong type breaks it."""

    def test_unknown_agent_returns_empty_list(self):
        """Calling get_sessions on an agent that was never registered must return [], not None."""
        mgr = AgentManager()
        result = mgr.get_sessions("nobody-ever-registered-this")
        assert result == []
        assert isinstance(result, list)

    def test_empty_string_agent_returns_empty_list(self):
        """get_sessions('') must not raise — edge case if session_key is used as agent name."""
        mgr = AgentManager()
        result = mgr.get_sessions("")
        assert result == []

    def test_returns_list_not_tuple(self):
        """Return type must be list so callers can call .append() on it safely."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        result = mgr.get_sessions("alice")
        assert isinstance(result, list)
        # This would fail on a tuple: result.append("x")


class TestGetName:
    """get_name is called to display agent names in tabs and menus."""

    def test_unknown_session_returns_empty_string(self):
        """Never-registered session_key must return '', not None or raise."""
        mgr = AgentManager()
        result = mgr.get_name("no-such-session-key-exists")
        assert result == ""
        assert isinstance(result, str)

    def test_returns_string(self):
        """Return type must be str — UI code calls .upper(), .split() etc."""
        mgr = AgentManager()
        mgr.register("sk1", "Bob")
        name = mgr.get_name("sk1")
        assert isinstance(name, str)


class TestRegister:
    """register is called once per session from the gateway health snapshot."""

    def test_same_session_key_registered_twice_no_duplicate(self):
        """Registering the same session_key twice must not create duplicate entries."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.register("sk1", "alice")  # same key, same name

        # _agent_names should have one entry
        assert len(mgr.get_names_ref()) == 1
        # alice's sessions should have one entry, not two
        assert mgr.get_sessions("alice") == ["sk1"]

    def test_same_session_key_different_agent_name_ignored(self):
        """Same session_key registered twice with different names: first name wins.

        This is a design decision — it means the first registration is sticky.
        If the same session appears with a different name later, it is silently ignored.
        """
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.register("sk1", "bob")  # same key, different name — ignored

        # alice keeps the key
        assert mgr.get_name("sk1") == "alice"
        # bob's session list is unchanged
        assert mgr.get_sessions("alice") == ["sk1"]
        assert mgr.get_sessions("bob") == []

    def test_same_agent_different_sessions_groups_correctly(self):
        """Multiple sessions for the same agent are grouped together."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.register("sk2", "alice")
        mgr.register("sk3", "alice")

        assert mgr.get_sessions("alice") == ["sk1", "sk2", "sk3"]

    def test_empty_string_session_key_accepted(self):
        """Empty string session_key — should not crash, though it's invalid."""
        mgr = AgentManager()
        # This would crash if there's no guard — worth documenting behavior
        mgr.register("", "eve")
        assert mgr.get_sessions("eve") == [""]


class TestClear:
    """clear is called on gateway reconnect — must wipe state without leaving orphans."""

    def test_clear_removes_all_sessions(self):
        """After clear, get_sessions for any agent must return []."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.register("sk2", "bob")

        mgr.clear()

        assert mgr.get_sessions("alice") == []
        assert mgr.get_sessions("bob") == []
        assert mgr.get_name("sk1") == ""
        assert mgr.get_name("sk2") == ""

    def test_clear_then_reregister_works(self):
        """After clear, new registrations must work normally."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.clear()
        mgr.register("sk2", "alice")  # new key, same name

        assert mgr.get_sessions("alice") == ["sk2"]
        assert mgr.get_name("sk2") == "alice"

    def test_clear_twice_does_not_raise(self):
        """Calling clear() when already clear must not raise."""
        mgr = AgentManager()
        mgr.register("sk1", "alice")
        mgr.clear()
        mgr.clear()  # must not raise
