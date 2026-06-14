# tests/test_agent_builder_fallback.py
# Tests for the fallback provider fields in the agent builder.
#
# Tests cover:
#   - Handler create_new() includes fallback fields
#   - Handler save/load round-trips fallback fields through YAML
#   - get_values() includes fallback_provider and fallback_model
#   - _normalize_fallback_fields ensures keys exist after parsing

from __future__ import annotations

import os
from unittest import mock

import pytest

from ui.handlers.agent_builder_handler import AgentBuilderHandler
from utils.agent_defs import (
    _normalize_fallback_fields,
    _parse_agent_file,
    save_agent_def,
    load_agent_def,
)


@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    """Redirect config dir to temp."""
    config_dir = tmp_path / "crabcakes-config"
    config_dir.mkdir()

    def mock_get_config_dir():
        return str(config_dir)

    monkeypatch.setattr("utils.config.get_config_dir", mock_get_config_dir)
    return config_dir


class TestHandlerCreateNew:
    def test_create_new_includes_fallback_fields(self):
        """create_new() returns dict with fallback_provider and fallback_model."""
        handler = AgentBuilderHandler()
        template = handler.create_new()
        assert "fallback_provider" in template
        assert "fallback_model" in template
        assert template["fallback_provider"] is None
        assert template["fallback_model"] is None


class TestNormalizeFallbackFields:
    def test_adds_missing_keys(self):
        """_normalize_fallback_fields adds keys if missing."""
        d = {"name": "TestAgent"}
        _normalize_fallback_fields(d)
        assert "fallback_provider" in d
        assert "fallback_model" in d

    def test_preserves_existing_keys(self):
        """_normalize_fallback_fields preserves existing values."""
        d = {"name": "TestAgent", "fallback_provider": "openrouter", "fallback_model": "openrouter/owl-alpha"}
        _normalize_fallback_fields(d)
        assert d["fallback_provider"] == "openrouter"
        assert d["fallback_model"] == "openrouter/owl-alpha"


class TestYamlRoundTrip:
    def test_save_load_fallback_fields(self, temp_config_dir):
        """Agent YAML with fallback fields survives save → load round-trip."""
        agent_def = {
            "name": "TestAgent",
            "emoji": "🤖",
            "role": "test",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file", "list_files"],
            "llm_name": "local-kb",
            "fallback_provider": "openrouter",
            "fallback_model": "openrouter/owl-alpha",
            "self_improvement": {},
        }

        save_agent_def(agent_def)

        loaded = load_agent_def("TestAgent")
        assert loaded is not None
        assert loaded.get("fallback_provider") == "openrouter"
        assert loaded.get("fallback_model") == "openrouter/owl-alpha"

    def test_save_load_without_fallback_fields(self, temp_config_dir):
        """Agent YAML without fallback fields loads with None defaults."""
        agent_def = {
            "name": "SimpleAgent",
            "emoji": "🤖",
            "role": "simple",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file"],
            "llm_name": "openrouter",
            "self_improvement": {},
        }

        save_agent_def(agent_def)

        loaded = load_agent_def("SimpleAgent")
        assert loaded is not None
        assert loaded.get("fallback_provider") is None
        assert loaded.get("fallback_model") is None

    def test_save_load_fallback_none(self, temp_config_dir):
        """Explicitly None fallback fields are saved and loaded correctly."""
        agent_def = {
            "name": "KBOnly",
            "emoji": "🤖",
            "role": "kb",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file"],
            "llm_name": "local-kb",
            "fallback_provider": None,
            "fallback_model": None,
            "self_improvement": {},
        }

        save_agent_def(agent_def)

        loaded = load_agent_def("KBOnly")
        assert loaded is not None
        assert loaded.get("fallback_provider") is None
        assert loaded.get("fallback_model") is None


class TestHandlerSaveLoad:
    def test_handler_save_load_round_trip(self, temp_config_dir):
        """Handler.save() and load_for_edit() round-trip fallback fields."""
        handler = AgentBuilderHandler()

        agent_def = {
            "name": "RoundTrip",
            "emoji": "🤖",
            "role": "roundtrip",
            "prompts": ["system/auxilium.md"],
            "tools": ["read_file", "list_files", "search_files"],
            "llm_name": "local-kb",
            "fallback_provider": "openrouter",
            "fallback_model": "openrouter/owl-alpha",
            "self_improvement": {},
        }

        ok, errors = handler.save(agent_def)
        assert ok, f"Save failed: {errors}"

        loaded = handler.load_for_edit("RoundTrip")
        assert loaded is not None
        assert loaded.get("fallback_provider") == "openrouter"
        assert loaded.get("fallback_model") == "openrouter/owl-alpha"
