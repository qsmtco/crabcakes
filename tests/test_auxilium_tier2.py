# tests/test_auxilium_tier2.py
# Tests for Auxilium Tier 2 — LLM Synthesis with KB Lookup.
#
# Locks in the agent_role field, the kb_lookup gate, the injection logic,
# multi-turn behavior, and the handler-side wiring.
#
# All tests are non-GTK. No xvfb-run needed.

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from agent.config import AgentConfig, LLMProviderConfig
from agent.runtime import AgentRuntime
from agent.kb_lookup import KBChunk
from models.conversation import Conversation


def _make_config() -> AgentConfig:
    """Build a minimal AgentConfig with one provider (no real API calls)."""
    providers = {
        "openai": LLMProviderConfig(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            default_model="gpt-4o",
            caller="openai",
        ),
    }
    return AgentConfig(
        providers=providers,
        default_provider="openai",
        default_model="openai/gpt-4o",
    )


def _make_runtime(agent_role: str = "helper") -> tuple[AgentRuntime, str]:
    """Build a runtime with one conversation registered. Returns (rt, session_key)."""
    cfg = _make_config()
    rt = AgentRuntime(cfg)
    rt.start()
    rt.create_conversation(
        session_key="test-session",
        agent_name="Auxilium",
        agent_role=agent_role,
    )
    return rt, "test-session"


def _fake_llm_response(content: str = "answer") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


# ── Test Class 1: Conversation.agent_role field ──────────────────────────────


class TestConversationAgentRole:
    """Verify Conversation has agent_role field."""

    def test_agent_role_field_exists(self):
        conv = Conversation(
            agent_name="Auxilium",
            model="openai/gpt-4o",
            agent_role="helper",
        )
        assert conv.agent_role == "helper"

    def test_agent_role_defaults_to_empty_string(self):
        conv = Conversation(agent_name="Test", model="openai/gpt-4o")
        assert conv.agent_role == ""


# ── Test Class 2: kb_lookup gate behavior ────────────────────────────────────


class TestKBLookupFiresForAuxilium:
    """KB lookup runs for every auxilium message (not just on KB_OUT_OF_SCOPE)."""

    def test_kb_lookup_called_for_helper_role(self):
        """kb_lookup fires when agent_role == 'helper'."""
        rt, sk = _make_runtime(agent_role="helper")
        captured = {}

        def fake_lookup(question, *, top_k, min_score):
            captured["question"] = question
            captured["top_k"] = top_k
            captured["min_score"] = min_score
            return []

        with patch("agent.kb_lookup.kb_lookup", side_effect=fake_lookup):
            with patch.object(rt, "_call_llm", return_value=_fake_llm_response()):
                rt._run_loop(sk, "how do I configure the gateway?")
        assert captured.get("question") == "how do I configure the gateway?"

    def test_kb_lookup_not_called_for_non_helper_role(self):
        """kb_lookup does NOT fire when agent_role != 'helper'."""
        rt, sk = _make_runtime(agent_role="coder")
        with patch("agent.kb_lookup.kb_lookup") as mock_kb:
            with patch.object(rt, "_call_llm", return_value=_fake_llm_response()):
                rt._run_loop(sk, "how do I configure the gateway?")
        mock_kb.assert_not_called()

    def test_kb_lookup_runs_every_message(self):
        """kb_lookup fires on every user message, not just the first."""
        rt, sk = _make_runtime(agent_role="helper")
        call_count = [0]

        def fake_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            return []

        with patch("agent.kb_lookup.kb_lookup", side_effect=fake_lookup):
            with patch.object(rt, "_call_llm", return_value=_fake_llm_response()):
                rt._run_loop(sk, "first question")
                rt._run_loop(sk, "second question")
                rt._run_loop(sk, "third question")
        assert call_count[0] == 3


# ── Test Class 3: KB context injection ───────────────────────────────────────


class TestKBContextInjection:
    """KB context is injected into the primary LLM call for auxilium."""

    def test_kb_context_injected_into_primary_call(self):
        """When kb_lookup returns chunks, they are prepended to the user message."""
        rt, sk = _make_runtime(agent_role="helper")
        fake_chunks = [
            KBChunk(
                id="c1",
                source="configuration.md",
                section="Gateway",
                text="Gateway config is in ~/.config/crabcakes/",
                score=0.8,
            ),
        ]
        captured_messages = []

        def fake_call(sk_arg, messages, tools):
            captured_messages.extend(messages)
            return _fake_llm_response("Here is the answer.")

        with patch("agent.kb_lookup.kb_lookup", return_value=fake_chunks):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "how do I configure the gateway?")
        user_msgs = [m for m in captured_messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        last_user = user_msgs[-1]
        assert "Gateway config" in last_user.get("content", "")
        assert "how do I configure" in last_user.get("content", "")

    def test_primary_call_without_kb_context_when_lookup_returns_empty(self):
        """When kb_lookup returns [], the primary call has no KB context."""
        rt, sk = _make_runtime(agent_role="helper")
        captured_messages = []

        def fake_call(sk_arg, messages, tools):
            captured_messages.extend(messages)
            return _fake_llm_response("I don't have specific docs on this.")

        with patch("agent.kb_lookup.kb_lookup", return_value=[]):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "what is the meaning of life?")
        user_msgs = [m for m in captured_messages if m.get("role") == "user"]
        last_user = user_msgs[-1]
        assert "meaning of life" in last_user.get("content", "")
        # No KB marker when chunks are empty
        assert "KB Context" not in last_user.get("content", "")

    def test_kb_lookup_exception_does_not_break_llm_call(self):
        """Sad path: kb_lookup raises → _call_llm still receives clean messages."""
        rt, sk = _make_runtime(agent_role="helper")
        captured_messages = []

        def fake_call(sk_arg, messages, tools):
            captured_messages.extend(messages)
            return _fake_llm_response("answer")

        with patch("agent.kb_lookup.kb_lookup", side_effect=RuntimeError("KB offline")):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "how do I configure?")
        # LLM was still called
        assert len(captured_messages) >= 1
        user_msgs = [m for m in captured_messages if m.get("role") == "user"]
        last_user = user_msgs[-1]
        # No KB context injected — just the raw question
        assert "KB Context" not in last_user.get("content", "")
        assert "how do I configure" in last_user.get("content", "")


# ── Test Class 4: Multi-turn synthesis ────────────────────────────────────────


class TestMultiTurnSynthesis:
    """KB lookup runs fresh on every message in a multi-turn conversation."""

    def test_followup_question_uses_current_question_as_query(self):
        """A follow-up ('and on Windows?') queries KB with the follow-up text."""
        rt, sk = _make_runtime(agent_role="helper")
        queries = []

        def fake_lookup(question, *, top_k, min_score):
            queries.append(question)
            return []

        with patch("agent.kb_lookup.kb_lookup", side_effect=fake_lookup):
            with patch.object(rt, "_call_llm", return_value=_fake_llm_response()):
                rt._run_loop(sk, "how do I configure the gateway on Linux?")
                rt._run_loop(sk, "and on Windows?")
        assert len(queries) == 2
        assert "Linux" in queries[0]
        assert "Windows" in queries[1]


# ── Test Class 5: Handler passes agent_role ──────────────────────────────────


class TestAgentRuntimeHandlerPassesRole:
    """AgentRuntimeHandler passes agent_role to create_conversation."""

    def test_create_conversation_receives_agent_role(self):
        """send_to_special_agent passes agent_role=agent_def.role to create_conversation."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler

        config = MagicMock()
        config.providers = {}
        config.default_provider = "openai"
        config.default_model = "openai/gpt-4o"
        config.tool_timeout_seconds = 120
        config.enforcement.enabled = False
        config.fallback_provider = None
        config.fallback_model = None

        main_content = MagicMock()
        chat_render_handler = MagicMock()

        handler = AgentRuntimeHandler(main_content, chat_render_handler)

        # Mock the runtime so create_conversation is a MagicMock
        mock_rt = MagicMock()
        mock_rt.get_conversation.return_value = None
        mock_rt.start = MagicMock()
        handler._runtimes["Auxilium"] = mock_rt

        # Register the agent
        agent_def = MagicMock()
        agent_def.display_name = "Auxilium"
        agent_def.role = "helper"
        agent_def.fallback_provider = None
        agent_def.fallback_model = None
        agent_def.system_prompt = "You are Auxilium."
        agent_def.tools = []
        agent_def.mcp_servers = []
        agent_def.app_title = ""
        agent_def.api_key = None
        agent_def.model = None
        agent_def.get_self_improvement_config = MagicMock(return_value={})
        handler._agents["auxilium"] = agent_def

        # Set active project to None (helper doesn't require it)
        handler._active_project = None

        # Call send_to_special_agent — this triggers create_conversation
        handler.send_to_special_agent("auxilium", "hello")

        call_kwargs = mock_rt.create_conversation.call_args
        assert call_kwargs is not None, "create_conversation was not called"
        assert call_kwargs.kwargs.get("agent_role") == "helper", \
            f"agent_role not passed: {call_kwargs.kwargs}"
