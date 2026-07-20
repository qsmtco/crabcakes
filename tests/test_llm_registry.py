"""Tests for LLM provider registry (Phase B4)."""

from __future__ import annotations

import pytest

from agent.llm.registry import get_provider, list_providers
from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider


class TestGetProvider:
    def test_get_provider_openai(self):
        p = get_provider("openai")
        assert isinstance(p, OpenAIProvider)
        assert p.provider_id == "openai"

    def test_get_provider_minimax(self):
        p = get_provider("minimax")
        assert isinstance(p, MiniMaxProvider)
        assert p.provider_id == "minimax"

    def test_get_provider_anthropic(self):
        p = get_provider("anthropic")
        assert isinstance(p, AnthropicProvider)
        assert p.provider_id == "anthropic"

    def test_get_provider_openrouter(self):
        """openrouter is an alias for OpenAIProvider."""
        p = get_provider("openrouter")
        assert isinstance(p, OpenAIProvider)
        assert p.provider_id == "openrouter"

    def test_get_provider_zai(self):
        """zai is an alias for OpenAIProvider."""
        p = get_provider("zai")
        assert isinstance(p, OpenAIProvider)
        assert p.provider_id == "zai"

    def test_get_provider_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="Unknown LLM provider"):
            get_provider("unknown_provider")


class TestListProviders:
    def test_list_providers_sorted(self):
        providers = list_providers()
        assert providers == sorted(providers), "must be sorted"
        assert "openai" in providers
        assert "minimax" in providers
        assert "anthropic" in providers
        assert "openrouter" in providers
        assert "zai" in providers
        assert len(providers) == 5