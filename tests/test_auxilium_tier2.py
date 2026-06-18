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

    def test_kb_lookup_called_once_per_run_loop_invocation(self):
        """kb_lookup should run once per _run_loop call, NOT once per
        tool-loop iteration. The helper is called inside the while loop,
        but the per-turn cache prevents repeated kb_lookup calls.
        """
        rt, sk = _make_runtime(agent_role="helper")

        call_count = [0]
        llm_call_count = [0]

        def counting_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            if call_count[0] == 1:
                return [KBChunk(id="c1", source="test.md", section="S", text="hello", score=0.9)]
            return []

        def fake_call(sk, messages, tools):
            llm_call_count[0] += 1
            if llm_call_count[0] == 1:
                # First call: trigger the tool loop with a tool_calls response
                return {
                    "choices": [{"message": {
                        "content": "",
                        "tool_calls": [{"id": "t1", "type": "function",
                                        "function": {"name": "read_file", "arguments": "{}"}}],
                    }}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            # Second call: normal answer
            return {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        with patch("agent.kb_lookup.kb_lookup", side_effect=counting_lookup):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "how do I configure?")

        # _call_llm was called twice (tool loop fired), but kb_lookup was called only once
        assert llm_call_count[0] >= 2, f"expected >= 2 LLM calls, got {llm_call_count[0]}"
        assert call_count[0] == 1, f"expected 1 kb_lookup call, got {call_count[0]}"

    def test_kb_lookup_cached_when_returns_empty_chunks(self):
        """Regression: HIGH bug from 2026-06-18 adversarial audit.

        The per-turn cache must engage even when kb_lookup returns [].
        Previously, new_cache stayed None when chunks was empty, causing
        kb_lookup to be re-invoked on every tool-loop iteration — the
        exact problem the cache was meant to solve.

        This test verifies that an off-topic user message (KB has no
        coverage) does NOT trigger repeated kb_lookup calls during a
        tool-loop.
        """
        rt, sk = _make_runtime(agent_role="helper")

        call_count = [0]
        llm_call_count = [0]

        def empty_lookup(question, *, top_k, min_score):
            """Always returns [] — simulates a KB index with no matches."""
            call_count[0] += 1
            return []

        def fake_call(sk, messages, tools):
            llm_call_count[0] += 1
            if llm_call_count[0] == 1:
                # First call: trigger the tool loop with a tool_calls response
                return {
                    "choices": [{"message": {
                        "content": "",
                        "tool_calls": [{"id": "t1", "type": "function",
                                        "function": {"name": "read_file", "arguments": "{}"}}],
                    }}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            # Second call: normal answer
            return {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        with patch("agent.kb_lookup.kb_lookup", side_effect=empty_lookup):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "an obscure question with no KB matches")

        # Tool loop fired (2 LLM calls), but kb_lookup was called only once
        # (gated by the cache; the empty result sets new_cache="" and
        # prevents re-querying on iter 2).
        assert llm_call_count[0] >= 2, f"expected >= 2 LLM calls, got {llm_call_count[0]}"
        assert call_count[0] == 1, (
            f"expected 1 kb_lookup call (cache should engage even on empty result), "
            f"got {call_count[0]}"
        )

    def test_kb_lookup_cached_when_raises(self):
        """Regression: HIGH bug from 2026-06-18 adversarial audit.

        The per-turn cache must engage even when kb_lookup raises an
        exception. Previously, the except clause left new_cache as None,
        causing kb_lookup to be re-invoked on every tool-loop iteration —
        hammering a failing backend N times for one user message.
        """
        rt, sk = _make_runtime(agent_role="helper")

        call_count = [0]
        llm_call_count = [0]

        def raising_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            raise RuntimeError("simulated KB backend down")

        def fake_call(sk, messages, tools):
            llm_call_count[0] += 1
            if llm_call_count[0] == 1:
                return {
                    "choices": [{"message": {
                        "content": "",
                        "tool_calls": [{"id": "t1", "type": "function",
                                        "function": {"name": "read_file", "arguments": "{}"}}],
                    }}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            return {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        with patch("agent.kb_lookup.kb_lookup", side_effect=raising_lookup):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop(sk, "any question")

        # kb_lookup was called only once even though it raised. A failing
        # backend must not be retried on every iteration.
        assert llm_call_count[0] >= 2, f"expected >= 2 LLM calls, got {llm_call_count[0]}"
        assert call_count[0] == 1, (
            f"expected 1 kb_lookup call (exception should not bypass cache), "
            f"got {call_count[0]}"
        )

    def test_kb_lookup_called_for_case_insensitive_helper_role(self):
        """The Tier 2 gate matches role values case-insensitively, ignoring whitespace.

        Regression test for adversarialDebugger LOW bug (2026-06-16): a user
        who types 'Helper' or ' helper ' in agent_def.role would silently miss
        KB synthesis due to strict string equality.
        """
        from agent.config import AgentConfig
        from agent.runtime import AgentRuntime
        from unittest.mock import patch

        cfg = AgentConfig(providers={}, default_provider='openai', default_model='openai/gpt-4o')
        rt = AgentRuntime(cfg)
        rt.start()

        for weird_role in ["Helper", "HELPER", "helper ", " helper", "  HELPER  ", "HeLpEr"]:
            rt.create_conversation(
                session_key=f"k-{weird_role!r}",
                agent_name="Aux",
                agent_role=weird_role,
            )
            with patch("agent.kb_lookup.kb_lookup") as mock_kb:
                with patch.object(rt, "_call_llm") as mock_call:
                    mock_call.return_value = {
                        "choices": [{"message": {"content": "a"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                    rt._run_loop(f"k-{weird_role!r}", "how do I configure?")
            assert mock_kb.called, (
                f"role={weird_role!r} should trigger KB synthesis (case-insensitive match)"
            )

        # None must not crash — treated as empty string, KB synthesis does NOT fire
        rt.create_conversation(
            session_key="k-None",
            agent_name="Aux",
            agent_role=None,
        )
        with patch("agent.kb_lookup.kb_lookup") as mock_kb:
            with patch.object(rt, "_call_llm") as mock_call:
                mock_call.return_value = {
                    "choices": [{"message": {"content": "a"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
                rt._run_loop("k-None", "how do I configure?")
        assert not mock_kb.called, (
            "role=None should NOT trigger KB synthesis and must not crash"
        )

        # Non-string types must not crash — treated as non-helper
        for bad_role in [["helper"], {"role": "helper"}, True, 42]:
            rt.create_conversation(
                session_key=f"k-{bad_role!r}",
                agent_name="Aux",
                agent_role=bad_role,
            )
            with patch("agent.kb_lookup.kb_lookup") as mock_kb:
                with patch.object(rt, "_call_llm") as mock_call:
                    mock_call.return_value = {
                        "choices": [{"message": {"content": "a"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                    rt._run_loop(f"k-{bad_role!r}", "how do I configure?")
            assert not mock_kb.called, (
                f"role={bad_role!r} should NOT trigger KB synthesis and must not crash"
            )


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

    def test_inject_kb_context_used_by_fallback_path(self):
        """The KB fallback chain uses the same _inject_kb_context helper as Tier 2."""
        rt, sk = _make_runtime(agent_role="helper")
        messages = [
            {"role": "system", "content": "You are Auxilium."},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ]
        kb_context = "[KB Context]\nSource: knowledge/install.md\nGTK4 install on Ubuntu..."
        current_text = "second question"
        out = rt._inject_kb_context(messages, kb_context, current_text)
        # The output is a new list (defensive copy)
        assert out is not messages
        # The system message is the same object (no mutation)
        assert out[0] is messages[0]
        # The first user message is the same object (only the last is modified)
        assert out[1] is messages[1]
        # The assistant message is the same object
        assert out[2] is messages[2]
        # The last user message is a new dict with KB context prepended
        assert out[3] is not messages[3]
        assert "GTK4 install on Ubuntu" in out[3]["content"]
        assert "second question" in out[3]["content"]
        # Specifically, the format is "{kb_context}\n\nUser question: {original}"
        assert out[3]["content"].startswith("[KB Context]")
        assert "User question: second question" in out[3]["content"]


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

    def test_agent_role_synced_on_agent_edit(self):
        """When agent_def.role changes, the existing conversation's agent_role is updated.

        Regression test for adversarialDebugger BUG #1 (2026-06-16): the edit-sync
        path in send_to_special_agent did not propagate agent_role changes, so a
        user who edited an agent from coder to helper would silently miss KB synthesis.
        """
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler

        handler = AgentRuntimeHandler(MagicMock(), MagicMock())
        mock_rt = MagicMock()
        # Conversation already exists with agent_role="coder" (i.e., not helper)
        existing_conv = MagicMock()
        existing_conv.agent_role = "coder"
        existing_conv.api_key = None
        existing_conv.model = None
        existing_conv.app_title = ""
        existing_conv.fallback_provider = None
        mock_rt.get_conversation.return_value = existing_conv
        handler._runtimes["Auxilium"] = mock_rt

        # Agent definition now has role="helper" (the user's edit)
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
        handler._agents["X"] = agent_def
        handler._active_project = None

        # Trigger the edit-sync path
        handler.send_to_special_agent("X", "hello")

        # The conversation's agent_role should now be "helper"
        assert existing_conv.agent_role == "helper", \
            f"agent_role not synced: {existing_conv.agent_role!r}"

    def test_mcp_servers_and_si_enforcement_synced_on_agent_edit(self):
        """When agent_def's mcp_servers or self_improvement changes, the existing
        conversation's mcp_servers and si_enforcement are updated.

        Regression test for adversarialDebugger related-bug follow-up to T2-F1:
        same edit-sync pattern as agent_role, but for mcp_servers and si_enforcement.
        """
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        from unittest.mock import MagicMock

        handler = AgentRuntimeHandler(MagicMock(), MagicMock())
        mock_rt = MagicMock()
        existing_conv = MagicMock()
        existing_conv.agent_role = "helper"
        existing_conv.api_key = None
        existing_conv.model = None
        existing_conv.app_title = ""
        existing_conv.fallback_provider = None
        # Stale values that should be overwritten
        existing_conv.mcp_servers = ["old-server"]
        existing_conv.si_enforcement = False
        mock_rt.get_conversation.return_value = existing_conv
        handler._runtimes["X"] = mock_rt

        agent_def = MagicMock()
        agent_def.display_name = "X"
        agent_def.role = "helper"
        agent_def.fallback_provider = None
        agent_def.fallback_model = None
        agent_def.system_prompt = "sys"
        agent_def.tools = []
        agent_def.mcp_servers = ["new-server-1", "new-server-2"]
        agent_def.app_title = ""
        agent_def.api_key = None
        agent_def.model = None
        agent_def.get_self_improvement_config = MagicMock(return_value={"enforcement": True})
        handler._agents["X"] = agent_def
        handler._active_project = None

        handler.send_to_special_agent("X", "hello")

        # mcp_servers should be updated to the new list
        assert existing_conv.mcp_servers == ["new-server-1", "new-server-2"], \
            f"mcp_servers not synced: {existing_conv.mcp_servers!r}"
        # si_enforcement should be True (from get_self_improvement_config)
        assert existing_conv.si_enforcement is True, \
            f"si_enforcement not synced: {existing_conv.si_enforcement!r}"
