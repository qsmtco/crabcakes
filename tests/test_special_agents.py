# tests/test_special_agents.py
# Tests for agent/special_agents.py — agent definition registry.
#
# Tests the YAML-loaded registry, self-improvement config resolution,
# and backward compatibility with programmatic SpecialAgentDef creation.

import pytest

from agent.special_agents import (
    SpecialAgentDef,
    get_special_agent,
    get_special_agents,
    reload_registry,
    _ensure_loaded,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Ensure a fresh registry for each test."""
    reload_registry()
    yield
    reload_registry()


class TestSpecialAgentDef:
    def test_create_with_old_fields(self):
        """Backward compat — creating with original 7 fields still works."""
        agent = SpecialAgentDef(
            conv_id_prefix="special:test",
            display_name="Test",
            role="test",
            emoji="🔬",
            color="#ff0000",
            tools=["read_file"],
            can_write=False,
        )
        assert agent.provider is None
        assert agent.model is None
        assert agent.self_improvement == {}

    def test_create_with_new_fields(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:custom",
            display_name="Custom",
            role="custom",
            emoji="🤖",
            color="#00ff00",
            tools=["read_file", "write_file"],
            can_write=True,
            provider="minimax",
            model="MiniMax-M2.7",
            self_improvement={"bug_journal": False},
        )
        assert agent.provider == "minimax"
        assert agent.model == "MiniMax-M2.7"
        assert agent.self_improvement["bug_journal"] is False


class TestGetSelfImprovementConfig:
    def test_writer_defaults(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:w",
            display_name="Writer",
            role="writer",
            emoji="✏️",
            color="#000",
            tools=["read_file", "write_file"],
            can_write=True,
        )
        cfg = agent.get_self_improvement_config()
        assert cfg["enforcement"] is True  # can_write=True
        assert cfg["bug_journal"] is True

    def test_reader_defaults(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:r",
            display_name="Reader",
            role="reader",
            emoji="📖",
            color="#000",
            tools=["read_file"],
            can_write=False,
        )
        cfg = agent.get_self_improvement_config()
        assert cfg["enforcement"] is False  # can_write=False

    def test_override_applies(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:o",
            display_name="Override",
            role="override",
            emoji="🔧",
            color="#000",
            tools=["read_file", "write_file"],
            can_write=True,
            self_improvement={"enforcement": False, "dream_consolidation": True},
        )
        cfg = agent.get_self_improvement_config()
        assert cfg["enforcement"] is False       # overridden
        assert cfg["dream_consolidation"] is True  # overridden
        assert cfg["bug_journal"] is True         # default


class TestRegistry:
    def test_loads_coder_and_debugger(self):
        agents = get_special_agents()
        names = [a.display_name for a in agents]
        assert "Coder" in names
        assert "Debugger" in names

    def test_coder_has_write_tools(self):
        coder = get_special_agent("special:coder")
        assert coder is not None
        assert "write_file" in coder.tools
        assert coder.can_write is True

    def test_debugger_no_write_tools(self):
        debugger = get_special_agent("special:debugger")
        assert debugger is not None
        assert "write_file" not in debugger.tools
        assert debugger.can_write is False

    def test_get_nonexistent_returns_none(self):
        assert get_special_agent("special:nonexistent") is None

    def test_coder_has_provider_model(self):
        coder = get_special_agent("special:coder")
        assert coder.provider == "minimax"
        assert coder.model == "MiniMax-M2.7"

    def test_coder_si_full_stack(self):
        coder = get_special_agent("special:coder")
        si = coder.get_self_improvement_config()
        assert si["bug_journal"] is True
        assert si["enforcement"] is True
        assert si["structured_feedback"] is True
        assert si["dream_consolidation"] is True

    def test_debugger_si_context_only(self):
        debugger = get_special_agent("special:debugger")
        si = debugger.get_self_improvement_config()
        assert si["enforcement"] is False
        assert si["structured_feedback"] is False
        assert si["dream_consolidation"] is False

    def test_reload_clears_and_reloads(self):
        agents1 = get_special_agents()
        reload_registry()
        agents2 = get_special_agents()
        # Should reload same agents
        assert len(agents1) == len(agents2)
        assert [a.display_name for a in agents1] == [a.display_name for a in agents2]
