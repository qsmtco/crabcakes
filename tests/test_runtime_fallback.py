# tests/test_runtime_fallback.py
# Tests for the KB provider fallback chain in agent/runtime.py.
#
# Tests cover:
#   - Fallback triggered when primary returns KB_OUT_OF_SCOPE
#   - No fallback when fallback_provider is not configured
#   - One-shot guard (fallback only fires once per message)
#   - Reset of _fallback_attempted on new send_message()

from __future__ import annotations

import threading
from unittest import mock

import pytest

from agent.config import AgentConfig, LLMProviderConfig
from agent.runtime import AgentRuntime, KB_OUT_OF_SCOPE, _extract_text_content


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_provider_cfg(name="openrouter", api_key="sk-test"):
    return LLMProviderConfig(
        name=name,
        base_url=f"https://example.com/v1",
        api_key=api_key,
        default_model=f"{name}/test-model",
        caller="openai",
    )


def _make_kb_provider_cfg():
    return LLMProviderConfig(
        name="local-kb",
        base_url="http://localhost:18790/v1",
        api_key="local",
        default_model="local-kb",
        caller="openai",
        supports_tools=False,
        supports_streaming=False,
    )


def _make_oob_response():
    """Simulate a KB server out-of-scope response."""
    return {
        "choices": [{"message": {"content": KB_OUT_OF_SCOPE, "tool_calls": []}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _make_normal_response(text="Here is your answer."):
    """Simulate a normal LLM response."""
    return {
        "choices": [{"message": {"content": text, "tool_calls": []}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }


def _make_runtime(fallback_provider=None):
    """Create an AgentRuntime with KB + fallback config.

    fallback_model parameter removed in 2026-06-15 — runtime derives from
    the provider card's default_model. See SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md.
    """
    providers = {
        "local-kb": _make_kb_provider_cfg(),
        "openrouter": _make_provider_cfg(),
    }
    config = AgentConfig(
        providers=providers,
        default_provider="local-kb",
        default_model="local-kb/local-kb",
        fallback_provider=fallback_provider,
    )
    rt = AgentRuntime(config)
    rt.start()
    return rt


def _setup_conversation(rt, session_key="test-session"):
    """Create a conversation in the runtime and return it.

    Propagates fallback_provider from the runtime's AgentConfig onto the
    Conversation, matching how create_conversation() wires it in production
    (Phase 3: fallback_provider or self._config.fallback_provider).

    fallback_model parameter removed in 2026-06-15 — runtime derives from
    the provider card's default_model.
    """
    from models.conversation import Conversation

    conv = Conversation(
        agent_name="TestAgent",
        model="local-kb/local-kb",
        system_prompt="You are a test agent.",
        fallback_provider=rt._config.fallback_provider,
    )
    rt._conversations[session_key] = conv
    return conv


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestFallbackOnOutOfScope:
    def test_fallback_on_out_of_scope(self):
        """When primary returns KB_OUT_OF_SCOPE and fallback is configured,
        the runtime retries with the fallback provider."""
        rt = _make_runtime(fallback_provider="openrouter")
        conv = _setup_conversation(rt)

        call_count = {"n": 0}

        def mock_call_llm(session_key, messages, tools):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _make_oob_response()
            return _make_normal_response("Fallback answer from real LLM.")

        with mock.patch.object(rt, "_call_llm", side_effect=mock_call_llm):
            responses = []
            rt._on_response_complete = lambda sk, text: responses.append(text)
            rt._run_loop("test-session", "What is quantum computing?")

        assert call_count["n"] == 2  # primary + fallback
        assert len(responses) == 1
        assert "Fallback answer" in responses[0]
        assert KB_OUT_OF_SCOPE not in responses[0]


class TestNoFallbackWithoutConfig:
    def test_no_fallback_without_config(self):
        """When fallback_provider is None, KB_OUT_OF_SCOPE is returned as-is."""
        rt = _make_runtime(fallback_provider=None)
        conv = _setup_conversation(rt)

        call_count = {"n": 0}

        def mock_call_llm(session_key, messages, tools):
            call_count["n"] += 1
            return _make_oob_response()

        with mock.patch.object(rt, "_call_llm", side_effect=mock_call_llm):
            responses = []
            rt._on_response_complete = lambda sk, text: responses.append(text)
            rt._run_loop("test-session", "What is quantum computing?")

        assert call_count["n"] == 1  # no fallback
        assert len(responses) == 1
        assert responses[0] == KB_OUT_OF_SCOPE


class TestFallbackOneShot:
    def test_fallback_one_shot(self):
        """If fallback provider also returns KB_OUT_OF_SCOPE, no third call."""
        rt = _make_runtime(fallback_provider="openrouter")
        conv = _setup_conversation(rt)

        call_count = {"n": 0}

        def mock_call_llm(session_key, messages, tools):
            call_count["n"] += 1
            # Always return out-of-scope
            return _make_oob_response()

        with mock.patch.object(rt, "_call_llm", side_effect=mock_call_llm):
            responses = []
            rt._on_response_complete = lambda sk, text: responses.append(text)
            rt._run_loop("test-session", "What is quantum computing?")

        assert call_count["n"] == 2  # primary + one fallback, no third
        assert len(responses) == 1
        # The sentinel is shown since fallback also returned OOB
        assert responses[0] == KB_OUT_OF_SCOPE


class TestFallbackResetOnNewMessage:
    def test_fallback_reset_on_new_message(self):
        """_fallback_attempted is reset when send_message is called again,
        so the second message can also trigger fallback."""
        rt = _make_runtime(fallback_provider="openrouter")
        conv = _setup_conversation(rt)

        # First message: set _fallback_attempted
        conv._fallback_attempted = True
        assert conv._fallback_attempted is True

        # Patch _run_loop to prevent actual execution (we just test the reset)
        with mock.patch.object(rt, "_run_loop"):
            rt.send_message("test-session", "second question")

        assert conv._fallback_attempted is False


# ── Derivation test ─────────────────────────────────────────────────────────────


class TestFallbackModelDerivation:
    """The runtime derives the fallback model from the provider card's default_model."""

    def test_derives_from_provider_default_model(self):
        """When fallback_provider is set, the runtime uses that provider's default_model.

        The openrouter provider card has default_model='openrouter/test-model'
        (see _make_provider_cfg). The runtime should set conv.model to
        'openrouter/test-model' for the fallback call — not a hard-coded string.
        """
        rt = _make_runtime(fallback_provider="openrouter")
        conv = _setup_conversation(rt)

        captured_models = []

        def mock_call_llm(session_key, messages, tools):
            # Capture conv.model at the moment of the call
            captured_models.append(conv.model)
            if len(captured_models) == 1:
                return _make_oob_response()
            return _make_normal_response("Derived fallback answer.")

        responses = []
        rt._on_response_complete = lambda sk, text: responses.append(text)

        with mock.patch.object(rt, "_call_llm", side_effect=mock_call_llm):
            rt._run_loop("test-session", "What is quantum computing?")

        # Primary call uses local-kb model
        assert captured_models[0] == "local-kb/local-kb"
        # Fallback call uses the provider card's default_model (derived, not stored)
        assert captured_models[1] == "openrouter/test-model"
        # Model was restored after fallback
        assert conv.model == "local-kb/local-kb"
