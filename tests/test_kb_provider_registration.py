# tests/test_kb_provider_registration.py
# Unit tests for utils/providers_store.ensure_kb_provider().
#
# Tests cover:
#   - Seeding local-kb when providers.yaml is empty
#   - Idempotency (calling twice doesn't duplicate)
#   - Preserving existing providers when seeding

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from models.providers import ProviderConfig
from utils.providers_store import ensure_kb_provider, load_providers


@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    """Redirect utils.config.get_config_dir() to a temp directory."""
    config_dir = tmp_path / "crabcakes-config"
    config_dir.mkdir()

    def mock_get_config_dir():
        return str(config_dir)

    monkeypatch.setattr("utils.config.get_config_dir", mock_get_config_dir)
    return config_dir


class TestEnsureKbProvider:
    def test_ensure_kb_provider_seeds_when_empty(self, temp_config_dir):
        """Empty providers.yaml → ensure_kb_provider() adds local-kb entry."""
        # Verify starting empty
        assert load_providers() == []

        ensure_kb_provider()

        providers = load_providers()
        assert len(providers) == 1
        kb = providers[0]
        assert kb.name == "local-kb"
        assert kb.base_url == "http://localhost:18790/v1"
        assert kb.api_key == "***"
        assert kb.default_model == "local-kb"
        assert kb.caller == "openai"
        assert kb.supports_tools is False
        assert kb.supports_streaming is False
        assert kb.max_tokens == 4096

    def test_ensure_kb_provider_idempotent(self, temp_config_dir):
        """Calling ensure_kb_provider() twice → still one local-kb entry."""
        ensure_kb_provider()
        ensure_kb_provider()

        providers = load_providers()
        kb_entries = [p for p in providers if p.name == "local-kb"]
        assert len(kb_entries) == 1

    def test_ensure_kb_provider_preserves_existing(self, temp_config_dir):
        """providers.yaml with an existing provider → local-kb added without removing it."""
        # Seed an existing provider first
        from utils.providers_store import save_providers
        existing = ProviderConfig(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            default_model="openrouter/owl-alpha",
            caller="openrouter",
        )
        save_providers([existing])

        ensure_kb_provider()

        providers = load_providers()
        assert len(providers) == 2

        names = {p.name for p in providers}
        assert "openrouter" in names
        assert "local-kb" in names

        # Verify the existing provider is unchanged
        or_provider = next(p for p in providers if p.name == "openrouter")
        assert or_provider.base_url == "https://openrouter.ai/api/v1"
        assert or_provider.api_key == "sk-or-test"
        assert or_provider.default_model == "openrouter/owl-alpha"

    def test_ensure_kb_provider_does_not_overwrite_existing_kb(self, temp_config_dir):
        """If local-kb already exists with custom settings, don't overwrite."""
        from utils.providers_store import save_providers
        custom_kb = ProviderConfig(
            name="local-kb",
            base_url="http://localhost:9999/v1",  # different port
            api_key="custom-key",
            default_model="custom-model",
            caller="openai",
        )
        save_providers([custom_kb])

        ensure_kb_provider()

        providers = load_providers()
        assert len(providers) == 1
        kb = providers[0]
        assert kb.base_url == "http://localhost:9999/v1"
        assert kb.api_key == "custom-key"
        assert kb.default_model == "custom-model"


    def test_ensure_kb_provider_patches_auxilium_no_provider(self, temp_config_dir):
        """Helper agent with empty llm_name → patched to use local-kb."""
        from utils.agent_defs import save_agent_def, load_agent_def_by_role

        # Create helper agent with no provider
        save_agent_def({
            "name": "Auxilium",
            "emoji": "🦀",
            "role": "helper",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file"],
            "llm_name": "",
            "self_improvement": {},
        })

        ensure_kb_provider()

        patched = load_agent_def_by_role("helper")
        assert patched is not None
        assert patched["llm_name"] == "local-kb"

    def test_ensure_kb_provider_does_not_override_existing_provider(self, temp_config_dir):
        """Helper agent with a provider set → not overridden."""
        from utils.agent_defs import save_agent_def, load_agent_def_by_role

        save_agent_def({
            "name": "Auxilium",
            "emoji": "🦀",
            "role": "helper",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file"],
            "llm_name": "openrouter",
            "self_improvement": {},
        })

        ensure_kb_provider()

        patched = load_agent_def_by_role("helper")
        assert patched is not None
        assert patched["llm_name"] == "openrouter"  # unchanged

    def test_ensure_kb_provider_no_helper_agent_is_safe(self, temp_config_dir):
        """No helper agent defined → ensure_kb_provider() is safe, still seeds provider."""
        ensure_kb_provider()

        providers = load_providers()
        assert len(providers) == 1
        assert providers[0].name == "local-kb"
