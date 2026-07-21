"""Tests for agent/llm/cost.py — extracted from agent/runtime.py (Phase B1)."""

from agent.llm.cost import (
    ANTHROPIC_COST,
    MINIMAX_COST,
    OPENAI_COST,
    PROVIDER_COSTS,
    cost_for_model,
    model_id,
)


class TestModelId:
    def test_strips_provider_prefix(self):
        assert model_id("minimax/MiniMax-M2.7") == "MiniMax-M2.7"

    def test_no_prefix_returns_input(self):
        assert model_id("gpt-4o") == "gpt-4o"

    def test_empty_string_returns_empty(self):
        assert model_id("") == ""


class TestCostForModel:
    def test_openai(self):
        # prompt=1000, completion=500, OPENAI_COST: prompt=2.5, completion=10.0
        # cost = 1000/1e6 * 2.5 + 500/1e6 * 10.0 = 0.0025 + 0.005 = 0.0075
        cost = cost_for_model("openai/gpt-4o", 1000, 500)
        assert abs(cost - 0.0075) < 0.0001

    def test_unknown_provider_defaults_openai(self):
        assert cost_for_model("unknown/model", 1000, 500) > 0

    def test_zero_tokens(self):
        assert cost_for_model("openai/gpt-4o", 0, 0) == 0.0

    def test_empty_model_string(self):
        # empty string → split gives [""], provider = "" → not in
        # PROVIDER_COSTS → defaults to OPENAI_COST. No crash.
        cost = cost_for_model("", 1000, 500)
        assert cost > 0



