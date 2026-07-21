"""Tests for agent/persistence.py — conversation disk I/O.

Extracted from agent/runtime.py Phase 6. Tests exercise persistence
WITHOUT instantiating AgentRuntime — pure module-level function tests.
"""

import json
import os

import pytest
from unittest.mock import patch

from agent.persistence import (
    conversations_dir,
    load_conversation_from_disk,
    migrate_conversation_files,
    resolve_api_key_for_conversation,
    resolve_session_workspace,
    save_conversation_to_disk,
)
from models.conversation import Conversation, Message, MessageRole


class TestConversationsDir:
    """conversations_dir() creates and returns the conversations directory."""

    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        d = conversations_dir()
        assert os.path.isdir(d)


class TestSaveLoadRoundtrip:
    """save_conversation_to_disk + load_conversation_from_disk roundtrip."""

    def test_save_and_load_preserves_messages(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        conv = Conversation(
            agent_name="Coder",
            model="openai/gpt-4o",
            system_prompt="You are Coder",
            messages=[Message(role=MessageRole.USER, content="hello")],
        )
        path = save_conversation_to_disk(conv, "special:coder")
        assert os.path.isfile(path)
        result = load_conversation_from_disk("special:coder")
        assert result is not None
        loaded_conv, _data = result
        assert loaded_conv.agent_name == "Coder"
        assert len(loaded_conv.messages) == 1
        assert loaded_conv.messages[0].content == "hello"

    def test_saved_file_does_not_contain_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        conv = Conversation(
            agent_name="Coder",
            model="openai/gpt-4o",
            provider="openai",
            system_prompt="",
            messages=[],
            api_key="sk-secret-12345",
        )
        path = save_conversation_to_disk(conv, "special:coder")
        with open(path) as f:
            data = json.load(f)
        assert "api_key" not in data  # HIGH-3


class TestResolveSessionWorkspace:
    """resolve_session_workspace() per-session secure workspace."""

    def test_valid_session_key(self, tmp_path):
        ws = resolve_session_workspace(str(tmp_path), "special:coder")
        assert os.path.isdir(ws)

    def test_empty_project_path_raises(self):
        with pytest.raises(ValueError, match="LOW-2"):
            resolve_session_workspace("", "special:coder")

    def test_path_escape_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="LOW-2"):
            resolve_session_workspace(str(tmp_path), "../escape")

    def test_colon_sanitized(self, tmp_path):
        ws = resolve_session_workspace(str(tmp_path), "special:coder")
        assert "special-coder" in ws  # colon → hyphen


class TestMigrateConversationFiles:
    """migrate_conversation_files() ONE-TIME migration HIGH-3."""

    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        # First call may "migrate"; second must be no-op
        migrate_conversation_files()
        assert migrate_conversation_files() == 0