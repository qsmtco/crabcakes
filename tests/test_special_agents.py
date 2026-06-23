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
    def test_create_with_minimal_fields(self):
        """Creating with the required fields works; llm_name defaults to None."""
        agent = SpecialAgentDef(
            conv_id_prefix="special:test",
            display_name="Test",
            role="test",
            emoji="🔬",
            tools=["read_file"],
            can_write=False,
        )
        assert agent.llm_name is None
        assert agent.self_improvement == {}

    def test_create_with_llm_name(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:custom",
            display_name="Custom",
            role="custom",
            emoji="🤖",
            tools=["read_file", "write_file"],
            can_write=True,
            llm_name="minimax",
            self_improvement={"bug_journal": False},
        )
        assert agent.llm_name == "minimax"
        assert agent.self_improvement["bug_journal"] is False


class TestGetSelfImprovementConfig:
    def test_writer_defaults(self):
        agent = SpecialAgentDef(
            conv_id_prefix="special:w",
            display_name="Writer",
            role="writer",
            emoji="✏️",
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
        from unittest.mock import patch
        coder_def = {
            "role": "coder",
            "name": "Coder",
            "emoji": "🛠️",
            "tools": ["read_file", "write_file", "edit_file", "exec_command",
                      "list_files", "search_files", "web_search", "web_fetch"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
        }
        with patch("utils.agent_defs.load_agent_defs", return_value=[coder_def]):
            reload_registry()
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

    def test_coder_has_llm_name(self):
        from unittest.mock import patch
        coder_def = {
            "role": "coder",
            "name": "Coder",
            "emoji": "🛠️",
            "tools": ["read_file", "write_file"],
            "llm_name": "minimax",
        }
        with patch("utils.agent_defs.load_agent_defs", return_value=[coder_def]):
            reload_registry()
            coder = get_special_agent("special:coder")
            assert coder.llm_name == "minimax"

    def test_coder_si_full_stack(self):
        from unittest.mock import patch
        coder_def = {
            "role": "coder",
            "name": "Coder",
            "emoji": "🛠️",
            "tools": ["read_file", "write_file"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "self_improvement": {
                "bug_journal": True,
                "project_rules": True,
                "enforcement": True,
                "structured_feedback": True,
                "dream_consolidation": True,
            },
        }
        with patch("utils.agent_defs.load_agent_defs", return_value=[coder_def]):
            reload_registry()
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


class TestSpecialAgentColorStability:
    """Tests for models/colors.color_for_special_agent() — the stable
    per-role color cache introduced in Phase 1 of SPEC-AGENT-COLOR-STABILITY.

    These tests verify:
      - Same role returns the same color across reload_registry() calls.
      - Empty role returns the deterministic default.
      - Gateway reconnect (reset_color_indices) does not reset special-agent
        colors.
    """

    @pytest.fixture(autouse=True)
    def reset_color_cache(self):
        """Reset the module-level _SPECIAL_AGENT_COLORS cache and the
        _agent_color_next counter before each test in this class, so test
        order does not affect results."""
        from models.colors import _SPECIAL_AGENT_COLORS, _agent_color_next
        _SPECIAL_AGENT_COLORS.clear()
        # Save and restore _agent_color_next so other tests aren't disturbed.
        import models.colors as colors_mod
        saved_next = colors_mod._agent_color_next
        colors_mod._agent_color_next = 0
        yield
        _SPECIAL_AGENT_COLORS.clear()
        colors_mod._agent_color_next = saved_next

    def test_color_stable_across_reload(self):
        """Reload registry; same roles get the same color."""
        from models.colors import color_for_special_agent
        reload_registry()
        first_colors = {a.role: color_for_special_agent(a.role) for a in get_special_agents()}
        reload_registry()
        second_colors = {a.role: color_for_special_agent(a.role) for a in get_special_agents()}
        assert first_colors == second_colors
        # At least one role should be assigned a real color
        assert all(c.startswith("#") for c in first_colors.values())
        # At least one role must have been assigned (sanity check that
        # the YAML registry is not empty).
        assert len(first_colors) >= 1

    def test_color_deterministic_for_empty_role(self):
        """Empty role returns the deterministic default without touching the cache."""
        from models.colors import color_for_special_agent, _SPECIAL_AGENT_COLORS
        assert color_for_special_agent("") == "#6366f1"
        assert color_for_special_agent("") == "#6366f1"  # idempotent
        # Empty role must NOT pollute the cache
        assert "" not in _SPECIAL_AGENT_COLORS

    def test_color_persists_across_reset_color_indices(self):
        """Gateway reconnect (reset_color_indices) does not reset special-agent colors."""
        from models.colors import color_for_special_agent, reset_color_indices
        # First call assigns from palette
        c1 = color_for_special_agent("test_role_x")
        # Simulate gateway reconnect
        reset_color_indices()
        # Same role returns the same color
        c2 = color_for_special_agent("test_role_x")
        assert c1 == c2
        # Color is a real palette entry, not the empty-role default
        assert c1.startswith("#")
        assert len(c1) == 7  # "#RRGGBB"
