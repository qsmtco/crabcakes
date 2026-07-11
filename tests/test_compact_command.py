# tests/test_compact_command.py
# Tests for Phase B — /compact slash command.

import pytest
from unittest.mock import MagicMock, patch
from models.command import Command, CommandResult


class TestCmdCompact:

    def test_project_tab_returns_hint(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = None
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body="", source_session_key="project:foo")
        result = handler.cmd_compact(cmd)
        assert result.handled is True
        assert "agent tab" in result.response_text

    def test_no_session_returns_hint(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = None
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body="", source_session_key=None)
        result = handler.cmd_compact(cmd)
        assert result.handled is True
        assert "No active session" in result.response_text

    def test_special_with_no_callback_returns_hint(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = None
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body="", source_session_key="special:coder")
        result = handler.cmd_compact(cmd)
        assert result.handled is True
        assert "unavailable" in result.response_text.lower()

    def test_special_with_callback_returns_result(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = lambda sk, focus: {
            "messages_removed": 5, "tokens_freed": 1000, "summary_chars": 50, "layer": 2
        }
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body="", source_session_key="special:coder")
        result = handler.cmd_compact(cmd)
        assert result.handled is True
        assert "5 message" in result.response_text
        assert "1,000" in result.response_text

    def test_focus_text_passed_through(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        captured = {}
        def capture_cb(sk, focus):
            captured["sk"] = sk
            captured["focus"] = focus
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}
        handler._compact_callback = capture_cb
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text='/compact "focus on auth"',
                      body="focus on auth", source_session_key="special:coder")
        result = handler.cmd_compact(cmd)
        assert captured["focus"] == "focus on auth"

    def test_none_body_handled(self):
        """BUG #5: cmd.body=None should not crash."""
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = lambda sk, focus: {
            "messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0
        }
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body=None, source_session_key="special:coder")
        result = handler.cmd_compact(cmd)
        assert result.handled is True

    def test_unknown_prefix_refused(self):
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        handler._compact_callback = None
        handler._compact_chat_callback = None
        cmd = Command(name="compact", args=[], flags={}, raw_text="/compact",
                      body="", source_session_key="agent:foo")
        result = handler.cmd_compact(cmd)
        assert result.handled is True
        assert "Cannot compact" in result.response_text


class TestCompactConversation:

    def test_rejects_non_special_session(self):
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        result = handler.compact_conversation("agent:foo", "")
        assert result["messages_removed"] == 0

    def test_rejects_none_session(self):
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        result = handler.compact_conversation(None, "")
        assert result["messages_removed"] == 0

    def test_rejects_non_string_session(self):
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        result = handler.compact_conversation(42, "")
        assert result["messages_removed"] == 0