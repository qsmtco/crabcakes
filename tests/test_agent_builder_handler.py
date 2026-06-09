# tests/test_agent_builder_handler.py
# Tests for ui/handlers/agent_builder_handler.py — agent builder form logic.
#
# Tests validation, save/load round-trip, and option retrieval.
# No GTK imports — pure handler logic.

import os
import tempfile
import shutil

import pytest

import utils.agent_defs as ad
from ui.handlers.agent_builder_handler import AgentBuilderHandler


@pytest.fixture
def tmp_agents_dir(monkeypatch, tmp_path):
    """Redirect agent defs to a temp directory."""
    agents_dir = str(tmp_path / "agents")
    monkeypatch.setattr(ad, "_get_agents_dir", lambda: agents_dir)
    # Also redirect default source so no seeding interferes
    monkeypatch.setattr(ad, "_get_default_agents_src", lambda: str(tmp_path / "no_defaults"))
    return agents_dir


@pytest.fixture
def handler():
    saved = []
    deleted = []
    h = AgentBuilderHandler(
        on_agent_saved=lambda name: saved.append(name),
        on_agent_deleted=lambda name: deleted.append(name),
    )
    return h, saved, deleted


class TestCreateNew:
    def test_returns_template(self, handler):
        h, _, _ = handler
        template = h.create_new()
        assert template["name"] == ""
        assert template["emoji"] == "🤖"
        assert "read_file" in template["tools"]
        assert template["self_improvement"]["bug_journal"] is True
        assert template["self_improvement"]["enforcement"] is False

    def test_template_is_fresh(self, handler):
        h, _, _ = handler
        t1 = h.create_new()
        t1["name"] = "modified"
        t2 = h.create_new()
        assert t2["name"] == ""


class TestSaveValidation:
    def test_save_valid_agent(self, handler, tmp_agents_dir):
        h, saved, _ = handler
        agent = {
            "name": "TestAgent",
            "emoji": "🔬",
            "role": "tester",
            "prompts": ["system/coder.md"],
            "tools": ["read_file", "list_files"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "api_key": "sk-test-123",
        }
        ok, errors = h.save(agent)
        assert ok
        assert errors == []
        assert "TestAgent" in saved

    def test_save_rejects_invalid(self, handler, tmp_agents_dir):
        h, _, _ = handler
        ok, errors = h.save({"name": ""})
        assert not ok
        assert len(errors) > 0

    def test_save_fires_callback(self, handler, tmp_agents_dir):
        h, saved, _ = handler
        h.save({
            "name": "CallbackTest",
            "prompts": ["system/coder.md"],
            "tools": ["read_file"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "api_key": "sk-test-123",
        })
        assert saved == ["CallbackTest"]


class TestLoadForEdit:
    def test_load_existing(self, handler, tmp_agents_dir):
        h, _, _ = handler
        h.save({
            "name": "Editable",
            "prompts": ["system/coder.md"],
            "tools": ["read_file"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "api_key": "sk-test-edit",
        })
        loaded = h.load_for_edit("Editable")
        assert loaded is not None
        assert loaded["name"] == "Editable"

    def test_load_nonexistent(self, handler, tmp_agents_dir):
        h, _, _ = handler
        assert h.load_for_edit("Ghost") is None


class TestDelete:
    def test_delete_existing(self, handler, tmp_agents_dir):
        h, _, deleted = handler
        h.save({
            "name": "Deletable",
            "prompts": ["system/coder.md"],
            "tools": ["read_file"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "api_key": "sk-test-del",
        })
        assert h.delete("Deletable") is True
        assert "Deletable" in deleted

    def test_delete_nonexistent(self, handler, tmp_agents_dir):
        h, _, _ = handler
        assert h.delete("Ghost") is False

    def test_delete_fires_callback(self, handler, tmp_agents_dir):
        h, _, deleted = handler
        h.save({
            "name": "ToDelete",
            "prompts": ["system/coder.md"],
            "tools": ["read_file"],
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "api_key": "sk-test-del2",
        })
        h.delete("ToDelete")
        assert deleted == ["ToDelete"]


class TestOptions:
    def test_tool_options(self, handler):
        h, _, _ = handler
        tools = h.get_tool_options()
        assert len(tools) > 0
        assert all("name" in t for t in tools)

    def test_prompt_options(self, handler):
        h, _, _ = handler
        prompts = h.get_prompt_options()
        assert len(prompts) > 0

    def test_provider_options(self, handler, monkeypatch, tmp_path):
        # get_provider_options reads from providers.yaml via get_available_providers
        config_dir = str(tmp_path / ".config" / "crabcakes")
        os.makedirs(config_dir, exist_ok=True)
        monkeypatch.setenv("HOME", str(tmp_path))
        from utils.providers_store import save_providers
        from models.providers import ProviderConfig
        save_providers([
            ProviderConfig(name="minimax", base_url="https://api.minimax.chat/v1",
                           api_key="sk-test", default_model="MiniMax-M2.7"),
        ])
        h, _, _ = handler
        providers = h.get_provider_options()
        assert len(providers) > 0
        assert all("name" in p for p in providers)
