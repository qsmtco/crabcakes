# tests/test_agent_runtime.py
# Unit tests for agent/runtime.py
#
# NOTE: When patching instance methods via patch.object, the mock is a plain
# function — Python does NOT pass self. So mock signature is:
#   def mock(session_key, messages, tools)  — NOT (self, session_key, messages, tools)

import json
import os
import tempfile
import time
import unittest.mock
import uuid

import pytest

from agent.runtime import (
    AgentRuntime,
    _extract_tool_calls,
    _extract_text_content,
    _extract_usage,
    _cost_for_model,
)


def _uniq():
    return f"rt{uuid.uuid4().hex[:8]}"


def _resp(content="Done.", tool_calls=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }


def _make_streaming_lambda(rt):
    """
    Return a lambda suitable for patching `_call_llm` in streaming tests.

    The lambda receives `(session_key, messages, tools)` as positional args
    from `_call_llm`, and forwards them plus boilerplate values to
    `rt._call_llm_streaming`. This eliminates duplication across the
    5 TestStreaming test patches.

    Usage:
        with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
            rt._run_loop(sk, "prompt")
    """
    return lambda *a, **kw: rt._call_llm_streaming(
        session_key=a[0],
        base_url="https://api.openai.com/v1",
        api_key="test",
        model="openai/gpt-4o",
        caller_key="openai",  # PHASE-11: method on AgentRuntime
        messages=a[1],
        tools=a[2] if len(a) > 2 else None,
        timeout=30.0,
    )


# ═══════════════════════════════════════════════════════════════════
#  Cost computation
# ═══════════════════════════════════════════════════════════════════

class TestCostComputation:
    def test_openai_gpt4o(self):
        cost = _cost_for_model("openai/gpt-4o", 1000, 500)
        assert abs(cost - 0.0075) < 0.0001

    def test_minimax(self):
        cost = _cost_for_model("minimax/MiniMax-M2.5", 1000, 500)
        assert abs(cost - 0.001) < 0.0001

    def test_unknown_uses_openai_rates(self):
        assert _cost_for_model("unknown/model", 1000, 500) > 0


# ═══════════════════════════════════════════════════════════════════
#  API response extraction
# ═══════════════════════════════════════════════════════════════════

class TestExtractToolCalls:
    def test_openai_single(self):
        resp = {
            "choices": [{"message": {
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}},
                ]
            }}],
        }
        assert _extract_tool_calls(resp, "openai") == [("c1", "read_file", {"path": "a.py"})]

    def test_openai_empty(self):
        assert _extract_tool_calls({"choices": [{"message": {"content": "hi"}}]}, "openai") == []

    def test_anthropic_single(self):
        resp = {"content": [{"type": "tool_use", "id": "c2", "name": "list_files", "input": {"path": "."}}]}
        assert _extract_tool_calls(resp, "anthropic") == [("c2", "list_files", {"path": "."})]

    def test_anthropic_empty(self):
        assert _extract_tool_calls({"content": [{"type": "text", "text": "hi"}]}, "anthropic") == []


class TestExtractText:
    def test_openai(self):
        assert _extract_text_content({"choices": [{"message": {"content": "The answer is 42."}}]}, "openai") == "The answer is 42."

    def test_anthropic(self):
        assert _extract_text_content({"content": [{"type": "text", "text": "42 is the answer."}]}, "anthropic") == "42 is the answer."


class TestExtractUsage:
    def test_openai(self):
        assert _extract_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 50}}, "openai") == (100, 50)

    def test_anthropic(self):
        assert _extract_usage({"usage": {"input_tokens": 100, "output_tokens": 50}}, "anthropic") == (100, 50)

    def test_missing(self):
        assert _extract_usage({}, "openai") == (0, 0)


# ═══════════════════════════════════════════════════════════════════
#  Lifecycle
# ═══════════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_start_stop(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        assert not rt.is_running()
        rt.start()
        assert rt.is_running()
        rt.stop()
        assert not rt.is_running()

    def test_create_get(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = rt.create_conversation("Coder", _uniq(), "/tmp")
        conv = rt.get_conversation(sk)
        assert conv is not None
        assert conv.agent_name == "Coder"
        rt.stop()

    def test_get_unknown(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        assert rt.get_conversation("nosuch") is None
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Tool loop — test by calling _run_loop directly (synchronous)
#
#  IMPORTANT: When patching rt._call_llm, the mock is an unbound function.
#  Python does NOT pass self. Signature is:
#    def mock(session_key, messages, tools) -> dict
# ═══════════════════════════════════════════════════════════════════

def _make_cfg():
    from agent.config import AgentConfig, LLMProviderConfig
    return AgentConfig(
        providers={
            "openai": LLMProviderConfig(
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                default_model="gpt-4o",
            )
        },
        default_provider="openai",
        default_model="openai/gpt-4o",
        max_tool_iterations=5,
        tool_timeout_seconds=30,
        auto_save_conversations=False,
    )


class TestToolLoop:
    def test_user_plus_assistant_in_conversation(self):
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        # mock(session_key, messages, tools) — NO self
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: _resp("Hello, human.")):
            rt._run_loop(sk, "say hello")

        conv = rt.get_conversation(sk)
        roles = [m.role.value for m in conv.messages]
        assert "user" in roles
        assert "assistant" in roles
        rt.stop()

    def test_user_message_in_llm_context(self):
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        received = []
        def mock(sk, msgs, tools):
            received.append(msgs)
            return _resp("Done.")

        with unittest.mock.patch.object(rt, "_call_llm", mock):
            rt._run_loop(sk, "what is the meaning of life")

        assert len(received) >= 1, f"_call_llm never called: {received}"
        assert any(
            m.get("role") == "user" and "meaning of life" in m.get("content", "")
            for m in received[0]
        ), f"User message not in {received[0]}"
        rt.stop()

    def test_text_response_callback(self):
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        complete = []
        rt._on_response_complete = lambda sk2, t: complete.append(t)

        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: _resp("The result is 42.")):
            rt._run_loop(sk, "what is 6 * 7?")

        assert complete == ["The result is 42."], f"Got: {complete}"
        rt.stop()

    def test_tool_call_appends_result(self):
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        results = []
        rt._on_tool_call_result = lambda sk2, n, r: results.append((n, r))

        responses = [
            _resp(tool_calls=[{"id": "call_ls", "function": {"name": "list_files", "arguments": '{"path": "."}'}}]),
            _resp("Files listed."),
        ]
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: responses.pop(0)):
            rt._run_loop(sk, "list files")

        assert len(results) >= 1, f"Expected tool result, got: {results}"
        assert results[0][0] == "list_files"
        rt.stop()

    def test_tool_loop_two_iterations(self):
        """
        Verify: user → tool_result → assistant = 3 messages.
        The runtime updates the user message with tool_calls (rather than
        creating a separate assistant message with tool_calls), so the
        sequence is: user(with tool_calls), tool, assistant.
        """
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        call_num = [0]
        def mock_caller(sk, msgs, tools):
            call_num[0] += 1
            has_tool = any(m.get("role") == "tool" for m in msgs)
            if call_num[0] == 1:
                assert not has_tool, f"Call 1 should not have tool result. msgs={msgs}"
                return _resp(tool_calls=[{
                    "id": "c1",
                    "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}
                }])
            else:
                assert has_tool, f"Call 2 should have tool result. msgs={msgs}"
                return _resp("File contents.")

        with unittest.mock.patch.object(rt, "_call_llm", mock_caller):
            rt._run_loop(sk, "read a.py")

        conv = rt.get_conversation(sk)
        # user + assistant(with tool_calls) + tool_result + assistant(text) = 4 messages
        assert len(conv.messages) == 4, (
            f"Expected 4 messages, got {len(conv.messages)}: "
            f"{[(m.role.value, m.content[:30] if m.content else str(m.tool_calls)[:50]) for m in conv.messages]}"
        )
        # Verify tool_calls are on the assistant message, not user (Bug #4 fix)
        user_msg = conv.messages[0]
        assert user_msg.role.value == "user"
        assert len(user_msg.tool_calls) == 0, "User message should have no tool_calls"
        assistant_msg = conv.messages[1]
        assert assistant_msg.role.value == "assistant"
        assert len(assistant_msg.tool_calls) == 1
        assert assistant_msg.tool_calls[0].tool_name == "read_file"
        rt.stop()

    def test_max_iterations_enforced(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=2,      # ← hard-limit: stop after 2 calls
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        call_count = [0]
        def mock_caller(sk, msgs, tools):
            call_count[0] += 1
            return _resp(tool_calls=[{
                "id": f"c{call_count[0]}",
                "function": {"name": "list_files", "arguments": '{"path": "."}'}
            }])

        errors = []
        rt._on_error = lambda sk2, msg: errors.append(msg)

        with unittest.mock.patch.object(rt, "_call_llm", mock_caller):
            rt._run_loop(sk, "keep calling tools")

        # Should stop after max_tool_iterations (2)
        assert call_count[0] <= 2, f"Expected <= 2 calls, got {call_count[0]}"
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  _compute_model_max — provider max_tokens resolution (BUG #1 Phase CB-1)
# ═══════════════════════════════════════════════════════════════════

class TestComputeModelMax:
    """Helper that resolves the model's context window from the provider config."""

    def test_returns_provider_max_tokens(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openrouter": LLMProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test",
                    default_model="some-model",
                    max_tokens=200_000,
                )
            },
            default_provider="openrouter",
            default_model="openrouter/some-model",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "openrouter/some-model"
        assert rt._compute_model_max(conv) == 200_000
        rt.stop()

    def test_falls_back_to_128k_when_provider_unknown(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "unknown/model"  # provider not in config
        assert rt._compute_model_max(conv) == 128_000
        rt.stop()

    def test_falls_back_to_128k_when_max_tokens_is_zero(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openrouter": LLMProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test",
                    default_model="some-model",
                    max_tokens=0,
                )
            },
            default_provider="openrouter",
            default_model="openrouter/some-model",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "openrouter/some-model"
        assert rt._compute_model_max(conv) == 128_000
        rt.stop()

    def test_falls_back_to_128k_when_max_tokens_is_none(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openrouter": LLMProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test",
                    default_model="some-model",
                    max_tokens=None,
                )
            },
            default_provider="openrouter",
            default_model="openrouter/some-model",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "openrouter/some-model"
        assert rt._compute_model_max(conv) == 128_000
        rt.stop()

    def test_extracts_provider_name_from_slash_model(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openrouter": LLMProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test",
                    default_model="claude-3-opus",
                    max_tokens=200_000,
                )
            },
            default_provider="openai",  # different default
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "openrouter/claude-3-opus"  # extracts "openrouter", not default_provider
        assert rt._compute_model_max(conv) == 200_000
        rt.stop()

    # BUG #3 regression tests: when max_tokens is unset/zero AND the caller
    # is recognized, fall back to caller_default_max_tokens() instead of 128K.
    # Before the fix, MiniMax-M3 (1M context) and Claude (200K) both defaulted
    # to 128K — wasting 87% / 36% of the model's context window.

    def test_minimax_zero_max_tokens_falls_back_to_caller_default(self):
        """When provider.max_tokens=0 and caller='minimax', returns 1_048_576
        (NOT 128K). This is the headline BUG #3 fix."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "minimax": LLMProviderConfig(
                    name="minimax",
                    base_url="https://api.minimax.io/v1",
                    api_key="test",
                    default_model="MiniMax-M3",
                    caller="minimax",
                    max_tokens=0,
                )
            },
            default_provider="minimax",
            default_model="minimax/MiniMax-M3",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "minimax/MiniMax-M3"
        assert rt._compute_model_max(conv) == 1_048_576, (
            "BUG #3: MiniMax-M3 has 1M context but default falls back to 128K. "
            "Caller-specific default must be used."
        )
        rt.stop()

    def test_anthropic_zero_max_tokens_falls_back_to_caller_default(self):
        """When provider.max_tokens=0 and caller='anthropic', returns 200_000."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "anthropic": LLMProviderConfig(
                    name="anthropic",
                    base_url="https://api.anthropic.com",
                    api_key="test",
                    default_model="claude-sonnet-4-20250514",
                    caller="anthropic",
                    max_tokens=0,
                )
            },
            default_provider="anthropic",
            default_model="anthropic/claude-sonnet-4-20250514",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "anthropic/claude-sonnet-4-20250514"
        assert rt._compute_model_max(conv) == 200_000
        rt.stop()

    def test_unknown_caller_falls_back_to_global_128k(self):
        """When caller is empty/unknown, fall back to 128K global default."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test",
                    default_model="gpt-4o",
                    caller="unknown_caller_xyz",  # not in CALLER_DEFAULT_MAX_TOKENS
                    max_tokens=0,
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "openai/gpt-4o"
        assert rt._compute_model_max(conv) == 128_000
        rt.stop()

    def test_max_tokens_set_wins_over_caller_default(self):
        """When provider.max_tokens > 0, caller default is ignored."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "minimax": LLMProviderConfig(
                    name="minimax",
                    base_url="https://api.minimax.io/v1",
                    api_key="test",
                    default_model="MiniMax-M3",
                    caller="minimax",
                    max_tokens=64_000,  # user explicitly set 64K
                )
            },
            default_provider="minimax",
            default_model="minimax/MiniMax-M3",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.model = "minimax/MiniMax-M3"
        assert rt._compute_model_max(conv) == 64_000
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Context-bloat fix — _run_loop trims conversation (BUG #1 Phase CB-1)
# ═══════════════════════════════════════════════════════════════════

class TestRunLoopTrimsContext:
    """§4.15 + BUG #1 fix: _run_loop trims the conversation to model_max per iteration."""

    def test_long_conversation_is_trimmed(self):
        """A 20-exchange conversation that exceeds model_max gets trimmed before the LLM call."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    default_model="gpt-4o",
                    max_tokens=10000,  # large enough for 2K-token conv + 4096 response reserve
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.system_prompt = "Test"  # minimize for predictable trim behavior

        # Stuff the conversation with 20 exchanges (~100 tokens each)
        for i in range(20):
            conv.add_user_message(f"turn {i}: " + "x" * 200)
            conv.add_assistant_message("y" * 200, [])

        # Capture the breakdown callback output
        captured: list[dict] = []
        rt._on_token_breakdown = lambda session_key, bd: captured.append(bd)

        # Mock _call_llm to return a text-only response (no tool calls → loop exits)
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: _resp("Done.")):
            rt._run_loop(sk, "trigger the loop")

        # Post-conditions
        assert len(conv.messages) < 42, f"expected trim, got {len(conv.messages)} messages"
        assert captured, "on_token_breakdown never fired"
        last = captured[-1]
        assert last["trimmed_this_turn"] is True
        # messages_remaining is the count at trim time; conv grows after trim
        assert last["messages_removed_this_turn"] > 0
        assert isinstance(last["messages_remaining"], int)
        assert last["messages_remaining"] >= 1
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Cost + step limits
# ═══════════════════════════════════════════════════════════════════

class TestCostLimit:
    def test_cost_limit_stops(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
            cost_limit=0.0001,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        errors = []
        rt._on_error = lambda sk2, msg: errors.append(msg)

        def mock_caller(sk, msgs, tools):
            return {
                "choices": [{"message": {"content": "Done."}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            }

        with unittest.mock.patch.object(rt, "_call_llm", mock_caller):
            rt._run_loop(sk, "hello")

        assert len(errors) >= 1, f"Expected error, got: {errors}"
        assert "cost" in errors[0].lower(), f"Got: {errors[0]}"
        rt.stop()

    def test_step_limit_stops(self):
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai", base_url="https://api.openai.com/v1",
                    api_key="test", default_model="gpt-4o",
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
            step_limit=0,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        errors = []
        rt._on_error = lambda sk2, msg: errors.append(msg)

        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: _resp("Done.")):
            rt._run_loop(sk, "hello")

        assert len(errors) >= 1
        assert "step" in errors[0].lower(), f"Got: {errors[0]}"
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Approval callback
# ═══════════════════════════════════════════════════════════════════

class TestApproval:
    def test_exec_without_callback_denied(self):
        rt = AgentRuntime(_make_cfg())  # no approval callback
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        results = []
        rt._on_tool_call_result = lambda sk2, n, r: results.append((n, r))

        responses = [
            _resp(tool_calls=[{
                "id": "call_exec",
                "function": {"name": "exec_command", "arguments": '{"command": "ls"}'}
            }]),
            _resp("Done."),
        ]
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: responses.pop(0)):
            rt._run_loop(sk, "run ls")

        exec_results = [(n, r) for n, r in results if n == "exec_command"]
        assert len(exec_results) >= 1, f"Expected exec result, got: {results}"
        assert "approval" in exec_results[0][1].lower() or "denied" in exec_results[0][1].lower(), f"Got: {exec_results[0][1]}"
        rt.stop()

    def test_exec_with_approval_allow(self):
        approved = [False]
        rt = AgentRuntime(
            _make_cfg(),
            on_tool_call_approval_needed=lambda sk, tn, args: (approved.__setitem__(0, True) or True),
        )
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        responses = [
            _resp(tool_calls=[{
                "id": "call_exec",
                "function": {"name": "exec_command", "arguments": '{"command": "ls"}'}
            }]),
            _resp("Done."),
        ]
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: responses.pop(0)):
            rt._run_loop(sk, "run ls")

        assert approved[0], "Approval callback should have fired"
        rt.stop()

    def test_exec_with_approval_deny(self):
        rt = AgentRuntime(_make_cfg(), on_tool_call_approval_needed=lambda sk, tn, args: False)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        results = []
        rt._on_tool_call_result = lambda sk2, n, r: results.append((n, r))

        responses = [
            _resp(tool_calls=[{
                "id": "call_exec",
                "function": {"name": "exec_command", "arguments": '{"command": "ls"}'}
            }]),
            _resp("Done."),
        ]
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: responses.pop(0)):
            rt._run_loop(sk, "run ls")

        exec_results = [(n, r) for n, r in results if n == "exec_command"]
        assert len(exec_results) >= 1, f"Expected exec result, got: {results}"
        assert "denied" in exec_results[0][1].lower(), f"Got: {exec_results[0][1]}"
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Persistence — use per-test temp dir so sessions don't collide
# ═══════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_save_conversation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = AgentRuntime(_make_cfg())
            rt.start()
            sk = _uniq()
            rt.create_conversation("Coder", sk, tmpdir)
            rt.get_conversation(sk).add_user_message("hi")
            rt.get_conversation(sk).add_assistant_message("hello", [])

            path = rt.save_conversation(sk)
            assert os.path.isfile(path), f"Expected file at {path}"

            with open(path) as f:
                data = json.load(f)
            assert data["agent_name"] == "Coder"
            assert len(data["messages"]) == 2
            rt.stop()

    def test_load_conversation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = AgentRuntime(_make_cfg())
            rt.start()
            sk = _uniq()
            rt.create_conversation("Debugger", sk, tmpdir)
            rt.get_conversation(sk).add_user_message("debug this")
            rt.save_conversation(sk)
            rt.stop()

            rt2 = AgentRuntime(_make_cfg())
            rt2.start()
            ok = rt2.load_conversation(sk)
            assert ok is True
            conv = rt2.get_conversation(sk)
            assert conv is not None
            assert conv.agent_name == "Debugger"
            assert len(conv.messages) == 1
            rt2.stop()

    def test_list_conversations_contains_our_keys(self):
        """
        Verify sessions created in this runtime appear in its internal dict.
        Note: list_conversations() reads from the shared filesystem directory,
        so it includes sessions from all test runs. We test the in-memory
        _conversations dict directly for isolation.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = AgentRuntime(_make_cfg())
            rt.start()
            sk1 = rt.create_conversation("Coder", _uniq(), tmpdir)
            sk2 = rt.create_conversation("Debugger", _uniq(), tmpdir)

            # _conversations is the authoritative in-memory store
            assert sk1 in rt._conversations, f"{sk1} not in {list(rt._conversations.keys())}"
            assert sk2 in rt._conversations, f"{sk2} not in {list(rt._conversations.keys())}"
            rt.stop()


class TestListConversations:
    """Regression tests for list_conversations lightweight read (W13/W14).

    Uses XDG_CONFIG_HOME isolation so list_conversations reads from a
    dedicated temporary conversations directory, not the user's real one.
    """

    def _isolated_runtime(self, tmpdir):
        """Create an AgentRuntime with XDG_CONFIG_HOME pointing at tmpdir.

        Returns (rt, old_xdg) — caller must restore env in test cleanup.
        We do NOT auto-restore because list_conversations() calls
        _conversations_dir() lazily on each invocation.
        """
        old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = tmpdir
        rt = AgentRuntime(_make_cfg())
        rt.start()
        return rt, old_xdg

    @staticmethod
    def _restore_xdg(old_xdg):
        if old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = old_xdg

    def test_list_conversations_returns_agent_name_without_full_deserialization(self):
        """list_conversations reads only agent_name from each JSON file,
        not the full Conversation/Message deserialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rt, old_xdg = self._isolated_runtime(tmpdir)
            sk = _uniq()
            rt.create_conversation("Coder", sk, tmpdir)
            conv = rt.get_conversation(sk)
            conv.add_user_message("hi")
            conv.add_assistant_message("hello", [])
            rt.save_conversation(sk)

            result = rt.list_conversations()
            our_entry = [entry for entry in result if entry[0] == sk]
            assert len(our_entry) == 1, f"Expected 1 entry for {sk}, got {len(our_entry)}"
            assert our_entry[0][1] == "Coder", f"Expected agent_name='Coder', got '{our_entry[0][1]}'"
            rt.stop()
            self._restore_xdg(old_xdg)

    def test_list_conversations_returns_unknown_for_corrupt_file(self):
        """A corrupt JSON file returns 'unknown' instead of crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rt, old_xdg = self._isolated_runtime(tmpdir)

            # _conversations_dir() lives at <XDG>/crabcakes/conversations
            conv_dir = os.path.join(tmpdir, "crabcakes", "conversations")
            os.makedirs(conv_dir, exist_ok=True)
            corrupt_path = os.path.join(conv_dir, "corrupt-session.json")
            with open(corrupt_path, "w") as f:
                f.write("{not valid json")

            result = rt.list_conversations()
            corrupt_entries = [e for e in result if e[0] == "corrupt-session"]
            assert len(corrupt_entries) == 1
            assert corrupt_entries[0][1] == "unknown"
            rt.stop()
            self._restore_xdg(old_xdg)

    def test_list_conversations_returns_unknown_for_missing_agent_name(self):
        """A JSON file without agent_name field returns 'unknown'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rt, old_xdg = self._isolated_runtime(tmpdir)

            conv_dir = os.path.join(tmpdir, "crabcakes", "conversations")
            os.makedirs(conv_dir, exist_ok=True)
            path = os.path.join(conv_dir, "no-name-session.json")
            with open(path, "w") as f:
                json.dump({"messages": []}, f)

            result = rt.list_conversations()
            entries = [e for e in result if e[0] == "no-name-session"]
            assert len(entries) == 1
            assert entries[0][1] == "unknown"
            rt.stop()
            self._restore_xdg(old_xdg)

    def test_list_conversations_empty_directory(self):
        """An empty conversations directory returns an empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rt, old_xdg = self._isolated_runtime(tmpdir)
            result = rt.list_conversations()
            assert result == []
            rt.stop()
            self._restore_xdg(old_xdg)


# ═══════════════════════════════════════════════════════════════════
#  SSE Streaming (Phase 1.3b)
# ═══════════════════════════════════════════════════════════════════

def _mock_stream_openai_3_chunks():
    """
    Yield the equivalent of: "Hello world!" as 3 SSE events.
    Returns a generator compatible with _stream_openai_events signature.
    """
    from agent.runtime import SSEEvent
    # Chunk 1: "Hello"
    yield SSEEvent(type="text_delta", data={"content": "Hello"})
    # Chunk 2: " world"
    yield SSEEvent(type="text_delta", data={"content": " world"})
    # Chunk 3: "!"
    yield SSEEvent(type="text_delta", data={"content": "!"})
    # Done
    yield SSEEvent(type="done", data={})


def _mock_stream_with_tool_call():
    """
    Yield a text delta followed by a streaming tool call.
    Tool call: list_files on path "."

    NOTE: Each argument chunk must be a valid JSON fragment. Accumulates to
    the JSON object: {"path": "."}
    """
    from agent.runtime import SSEEvent
    # Text delta first
    yield SSEEvent(type="text_delta", data={"content": "Let me list the files:"})
    # Tool call delta (name)
    yield SSEEvent(type="tool_call_delta", data={"index": 0, "name": "list_files", "arguments": ""})
    # Tool call delta (partial arguments — each chunk is a valid JSON fragment)
    yield SSEEvent(type="tool_call_delta", data={"index": 0, "name": "", "arguments": '{"path": "."}'})
    # Done
    yield SSEEvent(type="done", data={})



class TestStreaming:
    """
    Test SSE streaming by mocking _PROVIDER_STREAMERS.
    When on_text_delta is set, _call_llm routes to _call_llm_streaming,
    which iterates the SSE generator and fires callbacks per event.
    """

    def test_text_delta_fires_incrementally(self):
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        deltas = []
        rt._on_text_delta = lambda sk, d: deltas.append(d)

        # Patch the streamers dict to use our mock
        from agent import runtime as rt_module
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: _mock_stream_openai_3_chunks()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        # on_text_delta fires for each chunk
        assert len(deltas) == 3, f"Expected 3 deltas, got {len(deltas)}: {deltas}"
        assert deltas[0] == "Hello"
        assert deltas[1] == " world"
        assert deltas[2] == "!"
        rt.stop()

    def test_response_complete_fires_after_stream(self):
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        complete = []
        rt._on_response_complete = lambda sk, t: complete.append(t)

        from agent import runtime as rt_module
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: _mock_stream_openai_3_chunks()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        # on_response_complete fires once with full accumulated text
        assert len(complete) == 1, f"Expected 1 complete, got {len(complete)}: {complete}"
        assert complete[0] == "Hello world!"
        rt.stop()

    def test_tool_call_start_fires_when_complete(self):
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        tool_starts = []
        rt._on_tool_call_start = lambda sk, name, args: tool_starts.append((name, args))

        from agent import runtime as rt_module
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: _mock_stream_with_tool_call()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                # Mock the tool execution to return immediately
                with unittest.mock.patch("agent.tools.execute_tool") as mock_exec:
                    from agent.tools import ToolResult
                    mock_exec.return_value = ToolResult(success=True, output="file1.txt\nfile2.txt", error="")
                    rt._run_loop(sk, "list files")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        # on_tool_call_start fires once when the full tool call is accumulated.
        # NOTE: Phase 1.3b integration — _call_llm_streaming fires on_tool_call_start
        # at the 'done' event, then _run_loop fires it again before execution.
        # Listeners receive 2 dispatches per tool call. Fix: consolidate to one.
        assert len(tool_starts) >= 1, f"Expected >=1 tool start dispatches, got: {tool_starts}"
        # The first dispatch fires when the streaming 'done' event is processed
        assert tool_starts[0][0] == "list_files"
        assert tool_starts[0][1] == {"path": "."}, f"Got: {tool_starts[0][1]}"
        rt.stop()

    def test_streaming_accumulates_text_in_response(self):
        """Verify that the final assistant message contains the full accumulated text."""
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        from agent import runtime as rt_module
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: _mock_stream_openai_3_chunks()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        conv = rt.get_conversation(sk)
        # Last message should be the assistant response with full text
        assistant_msgs = [m for m in conv.messages if m.role.value == "assistant"]
        assert len(assistant_msgs) >= 1, f"Expected assistant message, got: {[m.role.value for m in conv.messages]}"
        assert assistant_msgs[-1].content == "Hello world!"
        rt.stop()

    def test_tool_call_delta_without_index_defaults_to_zero(self):
        """PHASE-11.5 regression: streamer yields tool_call_delta without 'index' key
        should default to idx=0, not crash with KeyError. Anthropic's streaming
        format omits 'index' for single-tool responses.
        """
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        from agent import runtime as rt_module
        from agent.runtime import SSEEvent

        def streamer_no_index(*a, **kw):
            yield SSEEvent(type="tool_call_delta", data={"name": "list_files", "arguments": '{"path": "."}'})

        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = streamer_no_index
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "list files")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        # If the bug is unfixed, this test crashes with KeyError before reaching here
        conv = rt.get_conversation(sk)
        assistant_msgs = [m for m in conv.messages if m.role.value == "assistant"]
        assert len(assistant_msgs) >= 1, f"Expected assistant message, got: {[m.role.value for m in conv.messages]}"
        rt.stop()

    def test_streaming_preserves_provider_tool_call_id(self):
        """STREAM-ID-PRES: provider-assigned tool_call id flows from raw SSE
        bytes through the streamer, the accumulator, and the final response dict.

        Regression: the old test (pre-2026-06-23) patched
        _PROVIDER_STREAMERS["openai"] with a pre-built SSEEvent generator —
        that bypassed _sse_lines → _parse_sse_line → _stream_openai_events
        entirely, so the streamer layer was never tested.

        This test feeds raw SSE bytes through the full pipeline (mocking only
        _urlopen_with_ssl_retry so the streamer itself is exercised verbatim)
        and asserts the id survives every layer. Without the STREAM-ID-PRES
        fix, the streaming path synthesizes `f"call_{idx}"` and MiniMax/OpenAI
        reject the next-turn request with status_code=2013.
        See docs/bugs/BUG_REPORT-streaming-tool-call-id-loss.md.
        """
        from agent import runtime as rt_module
        from agent.runtime import _stream_openai_events

        # Provider-shape raw SSE bytes — real id in first delta, argument
        # fragments in subsequent deltas (OpenAI / MiniMax / OpenRouter / ZAI).
        REAL_ID = "call_function_3679004591_1"
        raw_sse = (
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"id":"' + REAL_ID.encode() + b'",'
            b'"function":{"name":"read_file","arguments":""}}'
            b']}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"function":{"arguments":"{\\"path\\":\\"/tmp/foo.py\\"}"}}'
            b']}}]}\n\n'
            b'data: {"choices":[{"finish_reason":"tool_calls"}]}\n\n'
            b'data: [DONE]\n\n'
        )

        # Fake response that yields line-bytes — must be a class so Python
        # can look up __iter__ on the _FakeResp type.
        class _FakeResp:
            def __init__(self, buf):
                self._buf = buf
            def __iter__(self):
                return iter(self._buf.splitlines(keepends=True))

        def _make_fake_urlopen(buf):
            """Return a context-manager that provides a fake response."""
            class _Ctx:
                def __enter__(self_ctx):
                    return _FakeResp(buf)
                def __exit__(self_ctx, *a):
                    pass
            return _Ctx()

        # Phase 1: Feed raw SSE bytes through the real _stream_openai_events
        # and verify the SSEEvent stream carries the id forward.
        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _make_fake_urlopen(raw_sse),
        ):
            events = list(_stream_openai_events(
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "read foo.py"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))
        deltas = [ev for ev in events if ev.type == "tool_call_delta"]
        assert deltas, "expected at least one tool_call_delta event"
        assert deltas[0].data.get("id") == REAL_ID, (
            f"streamer must forward provider-assigned id; got {deltas[0].data.get('id')!r}"
        )

        # Phase 2: Run the full _call_llm_streaming pipeline with the real
        # streamer and assert the assembled response carries the real id.
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _make_fake_urlopen(raw_sse),
        ):
            response = rt._call_llm_streaming(
                session_key=sk,
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                caller_key="openai",
                messages=[{"role": "user", "content": "read foo.py"}],
                tools=None,
                timeout=30.0,
            )
        rt._cleanup_tool_history(sk)
        rt.stop()

        tool_calls = response["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == REAL_ID, (
            f"final tool_call id must be the provider-assigned one; "
            f"got {tool_calls[0]['id']!r}"
        )
        assert tool_calls[0]["function"]["name"] == "read_file"
        assert tool_calls[0]["function"]["arguments"] == '{"path":"/tmp/foo.py"}'

        # Phase 3: Round-trip check — feed the response back into
        # _extract_tool_calls (the path used by _run_loop on the next turn).
        call_id, tool_name, args = _extract_tool_calls(response, "openai")[0]
        assert call_id == REAL_ID, (
            f"_extract_tool_calls must surface the real id; got {call_id!r}"
        )
        assert tool_name == "read_file"

    def test_anthropic_content_block_start_preserves_tool_use_id(self):
        """STREAM-ID-PRES (BUG #4): _stream_anthropic_events must forward the
        tool_use.id from the content_block_start event through to the SSE event
        stream, so the accumulator captures the provider-assigned id before
        the first content_block_delta arrives.

        Anthropic's protocol differs from OpenAI/MiniMax: the id arrives in
        content_block_start (not in content_block_delta). Without this handler,
        the first-write-wins accumulator never sees an id and falls back to
        synthetic `call_{idx}`.
        """
        from agent import runtime as rt_module
        from agent.runtime import _stream_anthropic_events

        ANTHROPIC_ID = "toolu_01A09qGhdummyExample"
        raw_sse = (
            b'event: content_block_start\n'
            b'data: {"type":"content_block_start","index":0,"content_block":'
            b'{"type":"tool_use","id":"' + ANTHROPIC_ID.encode() + b'"}}\n\n'
            b'event: content_block_delta\n'
            b'data: {"type":"content_block_delta","index":0,"delta":'
            b'{"type":"tool_use_delta","name":"read_file","input":""}}\n\n'
            b'event: content_block_delta\n'
            b'data: {"type":"content_block_delta","index":0,"delta":'
            b'{"type":"tool_use_delta","input":"{\\"path\\":\\"/tmp/bar.py\\"}"}}\n\n'
            b'event: message_stop\n'
            b'data: {"type":"message_stop"}\n\n'
        )

        class _FakeResp:
            def __init__(self, buf):
                self._buf = buf
            def __iter__(self):
                return iter(self._buf.splitlines(keepends=True))

        def _make_fake_urlopen(buf):
            class _Ctx:
                def __enter__(self_ctx):
                    return _FakeResp(buf)
                def __exit__(self_ctx, *a):
                    pass
            return _Ctx()

        # Phase 1: Verify the streamer forwards the id.
        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _make_fake_urlopen(raw_sse),
        ):
            events = list(_stream_anthropic_events(
                base_url="https://api.anthropic.com/v1",
                api_key="***",
                model="claude-3-5-sonnet",
                messages=[{"role": "user", "content": "read bar.py"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))
        deltas = [ev for ev in events if ev.type == "tool_call_delta"]
        assert deltas, "expected at least one tool_call_delta event"
        # First delta must carry the id from content_block_start.
        assert deltas[0].data.get("id") == ANTHROPIC_ID, (
            f"Anthropic content_block_start id not forwarded; "
            f"got {deltas[0].data.get('id')!r}"
        )

        # Phase 2: Run the full pipeline.
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _make_fake_urlopen(raw_sse),
        ):
            response = rt._call_llm_streaming(
                session_key=sk,
                base_url="https://api.anthropic.com/v1",
                api_key="***",
                model="claude-3-5-sonnet",
                caller_key="anthropic",
                messages=[{"role": "user", "content": "read bar.py"}],
                tools=None,
                timeout=30.0,
            )
        rt._cleanup_tool_history(sk)
        rt.stop()

        tool_calls = response["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == ANTHROPIC_ID, (
            f"final tool_call id must be Anthropic's tool_use.id; "
            f"got {tool_calls[0]['id']!r}"
        )
        assert tool_calls[0]["function"]["name"] == "read_file"
        assert tool_calls[0]["function"]["arguments"] == '{"path":"/tmp/bar.py"}'

        # Phase 3: Round-trip check — _extract_tool_calls must surface the
        # real id. The response is always in normalized OpenAI format regardless
        # of the actual provider, because _call_llm_streaming normalizes all
        # streaming responses to a uniform format.
        call_id, tool_name, args = _extract_tool_calls(response, "openai")[0]
        assert call_id == ANTHROPIC_ID, (
            f"_extract_tool_calls must surface Anthropic's id; got {call_id!r}"
        )
        assert tool_name == "read_file"



class TestStreamingSignature:
    """
    PHASE-11 regression test: ensures that the streaming test patches and the
    production caller use a parameter list that is compatible with the actual
    `_call_llm_streaming` method signature.

    Catches: future signature changes to `_call_llm_streaming` that would break
    either the production caller (`_call_llm` in agent/runtime.py) or the 4
    `TestStreaming` test patches.
    """

    def test_streaming_method_signature_matches_caller_interface(self):
        """
        The streaming method's parameter list (after `self`) should match the
        keyword arguments used by the production caller AND by the 4 TestStreaming
        test patches. If any of them drifts, this test fails with a clear
        "signature mismatch" message.
        """
        import inspect
        from agent.runtime import AgentRuntime

        # 1. Get the actual method signature
        sig = inspect.signature(AgentRuntime._call_llm_streaming)
        method_params = [name for name in sig.parameters.keys() if name != "self"]

        # 2. The expected parameter list — derived from the TypedDict so that
        # adding/removing a field in StreamingCallKwargs automatically updates
        # this test. Single source of truth (PHASE-FOLLOWUP-1).
        from agent.runtime import StreamingCallKwargs
        expected_params = list(StreamingCallKwargs.__annotations__.keys())

        assert method_params == expected_params, (
            f"_call_llm_streaming signature changed.\n"
            f"  Expected: {expected_params}\n"
            f"  Actual:   {method_params}\n"
            f"  If you changed the signature intentionally, update the production\n"
            f"  caller (agent/runtime.py:_call_llm) and the 4 TestStreaming test\n"
            f"  patches (tests/test_agent_runtime.py) to match."
        )

        # 3. Verify the production caller passes all required parameters
        with open("/home/q/projects/crabcakes/agent/runtime.py") as f:
            runtime_source = f.read()
        # Find the call site: `self._call_llm_streaming(`
        call_site_match = runtime_source.find("self._call_llm_streaming(")
        assert call_site_match != -1, "Production caller to self._call_llm_streaming not found"
        # Extract the call (rough — just check for key kwargs)
        call_chunk = runtime_source[call_site_match:call_site_match + 800]
        for required_kw in ["session_key=", "base_url=", "api_key=", "model=", "caller_key=", "messages=", "tools=", "timeout="]:
            assert required_kw in call_chunk, (
                f"Production caller is missing required kwarg {required_kw!r}.\n"
                f"Call site: {call_chunk[:200]}"
            )

        # 4. Verify the TestStreaming patches use _make_streaming_lambda fixture (PHASE-FOLLOWUP-4)
        with open("/home/q/projects/crabcakes/tests/test_agent_runtime.py") as f:
            test_source = f.read()
        # Verify no patches use old rt_module pattern
        rt_module_calls = test_source.count("rt_module._call_llm_streaming(") - 1  # -1 for the count line
        assert rt_module_calls == 0, (
            f"Found {rt_module_calls} test patches still calling rt_module._call_llm_streaming.\n"
            f"All TestStreaming patches should use _make_streaming_lambda(rt) instead (PHASE-11)."
        )
        # Verify patches use the fixture — count _make_streaming_lambda(rt) calls in TestStreaming
        fixture_calls = test_source.count("_make_streaming_lambda(rt)") - 1  # -1 for the helper def
        assert fixture_calls >= 5, (
            f"Expected at least 5 test patches using _make_streaming_lambda(rt), found {fixture_calls}."
        )


# ═══════════════════════════════════════════════════════════════════
#  Phase CB-3: Streaming usage capture (BUG #3 fix)
# ═══════════════════════════════════════════════════════════════════

class TestStreamingUsageCapture:
    """Phase CB-3 (BUG #3 fix): streaming responses now capture SSE usage chunks."""

    def test_streaming_captures_openai_usage_chunk(self):
        """An OpenAI-compatible stream that emits a usage chunk in the final frame
        must surface the usage in the response dict (not {})."""
        from agent import runtime as rt_module
        from agent.runtime import SSEEvent

        def mock_stream_with_usage():
            yield SSEEvent(type="text_delta", data={"content": "Hello"})
            yield SSEEvent(type="text_delta", data={"content": " world"})
            yield SSEEvent(type="usage", data={
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}
            })
            yield SSEEvent(type="done", data={})

        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        usage_calls = []
        rt._on_token_usage = lambda sk, tokens, cost: usage_calls.append((tokens, cost))

        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: mock_stream_with_usage()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig
        rt.stop()

        # on_token_usage should have fired with non-zero tokens
        assert len(usage_calls) >= 1, f"Expected at least 1 usage call, got: {usage_calls}"
        total_tokens = usage_calls[0][0]
        assert total_tokens > 0, f"Expected non-zero tokens, got: {total_tokens}. Usage calls: {usage_calls}"

    def test_streaming_without_usage_chunk_returns_empty_usage(self):
        """Streams that don't emit a usage chunk still return a valid response with usage={}."""
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        from agent import runtime as rt_module
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        # The existing _mock_stream_openai_3_chunks has no usage chunk
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: _mock_stream_openai_3_chunks()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig
        rt.stop()

        # The conversation should complete successfully (no crash)
        conv = rt.get_conversation(sk)
        assistant_msgs = [m for m in conv.messages if m.role.value == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[-1].content == "Hello world!"

    def test_streaming_captures_anthropic_usage_in_message_delta(self):
        """Anthropic streams emit usage in message_delta events; the fix must capture these too."""
        from agent import runtime as rt_module
        from agent.runtime import SSEEvent

        def mock_anthropic_stream_with_usage():
            yield SSEEvent(type="text_delta", data={"content": "Hello from Anthropic"})
            yield SSEEvent(type="usage", data={
                "usage": {"input_tokens": 200, "output_tokens": 80}
            })
            yield SSEEvent(type="done", data={})

        # Use _call_llm_streaming directly to test the usage capture in isolation
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        orig = rt_module._PROVIDER_STREAMERS.get("anthropic")
        rt_module._PROVIDER_STREAMERS["anthropic"] = lambda *a, **kw: mock_anthropic_stream_with_usage()
        try:
            response = rt._call_llm_streaming(
                session_key=sk,
                base_url="https://api.anthropic.com/v1",
                api_key="test",
                model="anthropic/claude-3-5-sonnet",
                caller_key="anthropic",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30.0,
            )
        finally:
            if orig is not None:
                rt_module._PROVIDER_STREAMERS["anthropic"] = orig
        rt.stop()

        assert response["usage"] == {"input_tokens": 200, "output_tokens": 80}, \
            f"Expected Anthropic usage dict, got: {response['usage']}"


class TestSSEParsing:
    """Unit tests for SSE parsing utilities (Phase 1.3b)."""

    def test_parse_sse_line_data(self):
        from agent.runtime import _parse_sse_line, SSEEvent
        ev = _parse_sse_line(b"data: {\"choices\": [{\"delta\": {\"content\": \"hi\"}}]}")
        assert ev is not None
        assert ev.type == "raw"
        assert ev.data["choices"][0]["delta"]["content"] == "hi"

    def test_parse_sse_line_done(self):
        from agent.runtime import _parse_sse_line, SSEEvent
        ev = _parse_sse_line(b"data: [DONE]")
        assert ev is not None
        assert ev.type == "done"

    def test_parse_sse_line_blank_ignored(self):
        from agent.runtime import _parse_sse_line
        assert _parse_sse_line(b"") is None
        assert _parse_sse_line(b": comment") is None
        assert _parse_sse_line(b"  ") is None

    def test_sse_event_namedtuple(self):
        from agent.runtime import SSEEvent
        ev = SSEEvent(type="text_delta", data={"content": "hi"})
        assert ev.type == "text_delta"
        assert ev.data["content"] == "hi"


class TestStuckDetection:
    """§E — Stuck detection tests.

    Verifies:
    - Same tool + same args 3+ times → intervention message
    - 8+ write_file calls with no exec_command → intervention message
    - Varied tools → no intervention
    - Tool history cleanup on conversation cancel
    """

    def _cfg(self, **overrides):
        """Minimal config for AgentRuntime."""
        from agent.config import AgentConfig
        cfg = AgentConfig()
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_stuck_repeated_same_tool_and_args(self):
        """3+ calls of same tool+args → stuck detection fires."""
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_stuck_repeated_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        tool = "read_file"
        args = {"path": "src/main.py"}

        # First 2 calls → no stuck
        for _ in range(2):
            msg = rt._check_stuck(sk, tool, args, iteration=1)
            assert msg is None, f"First 2 calls should not trigger stuck: {msg}"

        # 3rd call → stuck fires
        msg = rt._check_stuck(sk, tool, args, iteration=3)
        assert msg is not None
        assert "stuck-detection" in msg
        assert tool in msg

        rt._cleanup_tool_history(sk)
        rt.stop()

    def test_stuck_write_loop_no_exec(self):
        """8+ write operations with no exec_command → stuck detection fires."""
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_stuck_write_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        # Do 7 writes → no stuck yet
        for i in range(7):
            msg = rt._check_stuck(sk, "write_file", {"path": f"src/f{i}.py", "content": "x"}, iteration=i)
            assert msg is None, f"7 writes should not trigger: {msg}"

        # 8th write → stuck fires
        msg = rt._check_stuck(sk, "write_file", {"path": "src/f8.py", "content": "x"}, iteration=7)
        assert msg is not None
        assert "stuck-detection" in msg
        assert "write" in msg.lower() or "file" in msg.lower()

        rt._cleanup_tool_history(sk)
        rt.stop()

    def test_not_stuck_with_exec_between_writes(self):
        """Interleaving exec_command with writes prevents the write-loop stuck detection.

        The write-loop check fires at 8+ writes with no exec in the last 8.
        Varying exec args means the 'same tool+args' check never fires either.
        """
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_stuck_varied_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        # Alternate write/exec for 10 iterations — use different args each time
        # so 'same tool+args' check never triggers, and exec breaks write-loop count
        for i in range(10):
            if i % 2 == 0:
                msg = rt._check_stuck(sk, "write_file", {"path": f"src/f{i}.py", "content": "x"}, iteration=i)
            else:
                # Different command each time → no same-tool-same-args stuck
                msg = rt._check_stuck(sk, "exec_command", {"command": f"python3 -m py_compile src/f{i-1}.py"}, iteration=i)
            assert msg is None, f"Varied tools should not trigger stuck at iter {i}: {msg}"

        rt._cleanup_tool_history(sk)
        rt.stop()

    def test_not_stuck_different_args(self):
        """Same tool called with different args → not stuck."""
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_stuck_diff_args_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        # Same tool, different args, 5 times → no stuck
        for i in range(5):
            msg = rt._check_stuck(sk, "read_file", {"path": f"src/f{i}.py"}, iteration=i)
            assert msg is None, f"Different args should not trigger stuck: {msg}"

        rt._cleanup_tool_history(sk)
        rt.stop()

    def test_tool_history_cleans_up_on_cancel(self):
        """Cancelling a conversation removes its tool history."""
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_cleanup_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        # Add some history
        rt._check_stuck(sk, "read_file", {"path": "a.py"}, iteration=1)
        rt._check_stuck(sk, "read_file", {"path": "b.py"}, iteration=2)
        assert sk in rt._tool_history
        assert len(rt._tool_history[sk]) == 2

        # Cancel → cleanup
        rt.cancel(sk)
        # cancel() is async (threaded), give it a moment to process
        import time
        time.sleep(0.05)
        assert sk not in rt._tool_history, f"History should be gone after cancel: {rt._tool_history.get(sk)}"

        rt.stop()

    def test_history_pruned_at_20_entries(self):
        """History is kept to last 20 entries."""
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self._cfg())
        rt.start()

        sk = "test_prune_" + str(uuid.uuid4().hex[:8])
        rt.create_conversation("Coder", sk, "/tmp")

        # Add 25 entries
        for i in range(25):
            rt._check_stuck(sk, "read_file", {"path": f"f{i}.py"}, iteration=i)

        history = rt._tool_history[sk]
        assert len(history) == 20, f"Expected 20, got {len(history)}"
        # Last entry should be the 25th (index 24)
        assert history[-1]["iteration"] == 24

        rt._cleanup_tool_history(sk)
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Phase CB-3: Stuck message transient prefix (BUG #4 fix)
# ═══════════════════════════════════════════════════════════════════

class TestStuckMessageTransient:
    """Phase CB-3 (BUG #4 fix): stuck messages are transient prefixes, not stored."""

    def test_stuck_message_not_stored_in_conv_messages(self):
        """Stuck-detection text is NOT stored in conv.messages when stuck fires.

        Drives _run_loop 3 times with the same tool call to trigger stuck
        detection. Verifies that conv.messages has no 'stuck-detection' text
        in any message (tool result, assistant, or otherwise).
        """
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        from agent.tools import ToolResult

        # Mock LLM: first call → tool call, subsequent calls → text response
        responses = [_resp(tool_calls=[
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "test.py"}'}}
        ]), _resp("Done.")]
        call_idx = [0]
        def mock_call_llm(sk, msgs, tools):
            r = responses[min(call_idx[0], len(responses) - 1)]
            call_idx[0] += 1
            return r

        # Run the loop 3 times with the same tool call to trigger stuck detection
        for _ in range(3):
            call_idx[0] = 0
            with unittest.mock.patch.object(rt, "_call_llm", mock_call_llm):
                with unittest.mock.patch("agent.tools.execute_tool") as mock_exec:
                    mock_exec.return_value = ToolResult(success=True, output="file content", error="")
                    rt._run_loop(sk, "read the file")

        conv = rt.get_conversation(sk)
        # Check that no message in conv.messages contains stuck-detection text
        for m in conv.messages:
            assert m.content is None or "stuck-detection" not in (m.content or ""), \
                f"Stuck-detection text should NOT be in conv.messages, found in role={m.role.value}: {(m.content or '')[:100]}"

        rt._cleanup_tool_history(sk)
        rt.stop()


class TestPerProjectEnforcement:
    """§F — Per-project enforcement config tests.

    Verifies:
    - .crabcakes/enforcement.json is loaded when present
    - Project-level skip patterns are merged additively
    - Per-tier enable/disable overrides are respected
    - Missing file → returns None (uses global config)
    """

    def test_load_project_config_success(self, tmp_path):
        """Valid JSON file is parsed and returned."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text(
            json.dumps({"syntax_check": False, "skip_patterns": ["*.generated.py"]})
        )
        from agent.enforcement import _load_project_enforcement_config
        result = _load_project_enforcement_config(str(tmp_path))
        assert result is not None
        assert result["syntax_check"] is False
        assert result["skip_patterns"] == ["*.generated.py"]

    def test_load_project_config_missing(self, tmp_path):
        """No .crabcakes/enforcement.json → returns None."""
        from agent.enforcement import _load_project_enforcement_config
        result = _load_project_enforcement_config(str(tmp_path))
        assert result is None

    def test_load_project_config_invalid_json(self, tmp_path):
        """Malformed JSON → returns None."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text("not valid json")
        from agent.enforcement import _load_project_enforcement_config
        result = _load_project_enforcement_config(str(tmp_path))
        assert result is None

    def test_project_config_merge_skip_patterns(self, tmp_path):
        """Project skip patterns are additive to global defaults."""
        from agent.enforcement import check
        from agent.config import EnforcementConfig
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text(
            json.dumps({"skip_patterns": ["*.custom.py", "*.generated.py"]})
        )
        # Create a test file and a global skip that would skip it
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        # Global config skips *.md but not *.py, project config adds *.generated.py
        cfg = EnforcementConfig(syntax_check=True, skip_patterns=["*.md"])
        # Create ToolResult
        from agent.tools import ToolResult
        tr = ToolResult(success=True, output="wrote", error=None)
        result = check("write_file", {"path": "test.py"}, tr, str(tmp_path), cfg)
        # Should have run the check (not skipped)
        syntax_check = next((c for c in result.checks if c.tier == "syntax"), None)
        assert syntax_check is not None, "Syntax check should run for .py with global skip of *.md only"

    def test_project_config_disable_tier(self, tmp_path):
        """Project config can disable individual enforcement tiers."""
        from agent.enforcement import check
        from agent.config import EnforcementConfig
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "enforcement.json").write_text(
            json.dumps({"test_run": False, "lint_check": False})
        )
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        cfg = EnforcementConfig(syntax_check=True, test_run=True, lint_check=True)
        from agent.tools import ToolResult
        tr = ToolResult(success=True, output="wrote", error=None)
        result = check("write_file", {"path": "test.py"}, tr, str(tmp_path), cfg)
        tiers_run = {c.tier for c in result.checks}
        assert "syntax" in tiers_run, "Syntax should still run"
        assert "tests" not in tiers_run, "Tests should be disabled by project config"
        assert "lint" not in tiers_run, "Lint should be disabled by project config"


# ═══════════════════════════════════════════════════════════════════
#  Phase 2: MiniMax body-level error surfacing (SPEC-LOCAL-AGENT-NO-RESPONSE-FIX)
# ═══════════════════════════════════════════════════════════════════

class TestMinimaxBodyLevelError:
    """MiniMax returns body-level errors with HTTP 200 (base_resp.status_code != 0).
    The runtime must raise RuntimeError so the error surfaces to the user."""

    def test_minimax_body_level_error_raises(self):
        """_call_minimax with base_resp.status_code=1004 raises RuntimeError."""
        from agent.runtime import _call_minimax
        error_body = json.dumps({
            "base_resp": {
                "status_code": 1004,
                "status_msg": "login fail: Please carry the API secret key"
            }
        }).encode()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = error_body
        mock_resp.__enter__ = unittest.mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="status_code=1004"):
                _call_minimax(
                    base_url="https://api.minimax.chat/v1",
                    api_key="invalid-key",
                    model="minimax/MiniMax-M2.7",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=None,
                    timeout=30,
                )

    def test_streaming_minimax_body_error_raises(self):
        """_stream_minimax_events with base_resp.status_code=1004 raises RuntimeError."""
        from agent.runtime import _stream_minimax_events
        error_body = json.dumps({
            "base_resp": {
                "status_code": 1004,
                "status_msg": "login fail: Please carry the API secret key"
            }
        }).encode()

        # Simulate HTTP response whose lines yield the error JSON
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__iter__ = unittest.mock.MagicMock(return_value=iter([error_body]))
        mock_resp.__enter__ = unittest.mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="status_code=1004"):
                # Must consume the generator to trigger the error
                list(_stream_minimax_events(
                    base_url="https://api.minimax.chat/v1",
                    api_key="invalid-key",
                    model="minimax/MiniMax-M2.7",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=None,
                    timeout=30,
                ))


# ═══════════════════════════════════════════════════════════════════
#  Phase 3: Empty-choices response handling (SPEC-LOCAL-AGENT-NO-RESPONSE-FIX)
# ═══════════════════════════════════════════════════════════════════

class TestEmptyChoicesResponse:
    """When the LLM returns a response with no choices and empty content,
    _run_loop must dispatch _on_error instead of _on_response_complete."""

    def test_empty_choices_response_dispatches_on_error(self):
        """Response with no choices key and empty content → _on_error fires."""
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        errors = []
        rt._on_error = lambda sk2, msg: errors.append(msg)

        # Response with no choices key — mimics a body-level error that
        # slipped through (e.g. MiniMax returning {"base_resp":{...}} with status_code 0
        # but still no choices)
        empty_response = {"usage": {}}

        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: empty_response):
            rt._run_loop(sk, "hello")

        assert len(errors) == 1, f"Expected 1 error, got: {errors}"
        assert "no content" in errors[0].lower() or "configuration error" in errors[0].lower(), \
            f"Error message should mention the issue, got: {errors[0]}"
        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Phase 4: Defensive empty-response bubble (SPEC-LOCAL-AGENT-NO-RESPONSE-FIX)
# ═══════════════════════════════════════════════════════════════════

class TestEmptyResponseFallbackBubble:
    """When _do_response_complete is called with empty text and no streaming
    was active, a fallback bubble must be rendered so the user sees feedback."""

    def _make_handler(self):
        """Create a minimal AgentRuntimeHandler with mocked deps."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        mc = unittest.mock.MagicMock()
        crh = unittest.mock.MagicMock()
        crh.is_streaming.return_value = False
        crh.render_sync.return_value = unittest.mock.MagicMock()  # fake bubble widget
        handler = AgentRuntimeHandler(
            main_content=mc,
            chat_render_handler=crh,
            GLib_module=None,  # no GLib in tests — runs synchronously
        )
        return handler, mc, crh

    def test_empty_response_renders_fallback_bubble(self):
        """_do_response_complete with empty text + not streaming → fallback bubble rendered."""
        handler, mc, crh = self._make_handler()
        chat_box = unittest.mock.MagicMock()
        handler._resolve_chat_box = unittest.mock.MagicMock(return_value=chat_box)

        handler._do_response_complete("special:coder", "")

        # render_sync must have been called with a fallback message
        crh.render_sync.assert_called_once()
        call_args = crh.render_sync.call_args
        assert call_args[0][0] == "System"  # role
        assert "no content" in call_args[0][1].lower() or "configuration error" in call_args[0][1].lower()
        # Bubble was appended to chat_box
        chat_box.append.assert_called_once()

    def test_empty_response_with_streaming_does_not_render_extra_bubble(self):
        """_do_response_complete with empty text + streaming active → no extra fallback bubble.
        The streaming bubble finalization handles display."""
        handler, mc, crh = self._make_handler()
        crh.is_streaming.return_value = True  # streaming WAS active
        chat_box = unittest.mock.MagicMock()
        handler._resolve_chat_box = unittest.mock.MagicMock(return_value=chat_box)

        handler._do_response_complete("special:coder", "")

        # render_sync should NOT have been called for fallback (streaming handles it)
        # Note: end_streaming IS called (that's fine), but no additional render
        # The key assertion: render_sync was never called with the fallback text
        for call_args in crh.render_sync.call_args_list:
            text = call_args[0][1]
            assert "no content" not in text.lower() and "Agent returned" not in text, \
                f"Fallback bubble should not render during streaming, got: {text}"


# ═══════════════════════════════════════════════════════════════════
#  Streaming regression tests for _stream_anthropic_events (W2/W3/W4)
# ═══════════════════════════════════════════════════════════════════

class TestStreamAnthropicEvents:
    """Regression tests for _stream_anthropic_events.

    Locks in the W2 (tool conversion), W3 (message conversion), and W4
    (no stream_options in Anthropic payload) fixes from
    SPEC-RUNTIME-HARDENING-AUDIT.md §2.2 and §10.3.
    """

    def test_no_stream_options_in_anthropic_payload(self):
        """Anthropic API does not support stream_options — must not be in payload."""
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            # Return a minimal streaming response
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                # Provide minimal args
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=[{"role": "user", "content": "hello"}],
                    tools=None,
                    timeout=30.0,
                ))
        # Verify no stream_options in captured request data
        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        assert "stream_options" not in payload, (
            "stream_options must not be sent to Anthropic API"
        )

    def test_anthropic_messages_are_converted(self):
        """Messages must be converted to Anthropic format, not passed raw.

        Includes assistant with tool_calls and tool role messages so the test
        would FAIL if _convert_messages_for_anthropic were bypassed (a plain
        user message passes through either way).
        """
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        raw_messages = [
            {"role": "user", "content": "read foo.py"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        ]

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=raw_messages,  # raw OpenAI-format dicts
                    tools=None,
                    timeout=30.0,
                ))

        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        api_msgs = payload["messages"]
        # Messages should be a list (Anthropic format)
        assert isinstance(api_msgs, list)
        # 3 input messages → 3 output messages (no system, no drops)
        assert len(api_msgs) == 3
        # assistant with tool_calls → content blocks with tool_use
        assert api_msgs[1]["role"] == "assistant"
        assert isinstance(api_msgs[1]["content"], list)
        assert any(
            b.get("type") == "tool_use" for b in api_msgs[1]["content"]
        ), f"assistant tool_calls must convert to tool_use blocks, got: {api_msgs[1]}"
        # tool role → user role with tool_result content
        assert api_msgs[2]["role"] == "user"
        assert isinstance(api_msgs[2]["content"], list)
        assert api_msgs[2]["content"][0]["type"] == "tool_result", (
            f"tool role must convert to user role with tool_result, got: {api_msgs[2]}"
        )

    def test_anthropic_tools_are_converted(self):
        """Tools must be converted to Anthropic format, not passed raw."""
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        raw_tools = [{
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {"type": "object", "properties": {}}
            }
        }]

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=[{"role": "user", "content": "hello"}],
                    tools=raw_tools,  # raw tool dicts
                    timeout=30.0,
                ))

        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        # After conversion, tools should use input_schema (Anthropic format)
        assert "tools" in payload
        for tool in payload["tools"]:
            assert "input_schema" in tool, "Anthropic tools must have input_schema"
            assert "name" in tool


# ═══════════════════════════════════════════════════════════════════
#  Phase 1 audit regression tests — system prompt placement
# ═══════════════════════════════════════════════════════════════════

class TestSystemPromptPlacement:
    """Regression tests for Phase 1 audit findings.

    Locks in fixes for:
    - BUG #1: _call_anthropic was sending the system prompt TWICE
              (payload['system'] AND as first user message via helper)
    - BUG #2: _stream_anthropic_events was sending the system prompt
              as a USER message (wrong role, loses Anthropic system priority)
    - BUG #3: _convert_tools_for_anthropic raised KeyError on missing parameters
    """

    def test_non_streaming_system_not_duplicated_as_user(self):
        """_call_anthropic must put system prompt ONLY in payload['system'],
        NOT also as the first user message in payload['messages'].
        """
        from unittest.mock import patch, MagicMock
        from agent.runtime import _call_anthropic

        captured = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            body = b'{"id": "msg_1", "content": [{"type": "text", "text": "hi"}]}'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.read = MagicMock(return_value=body)
            return resp

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            _call_anthropic(
                base_url="https://api.anthropic.com",
                api_key="test",
                model="claude-3-5-sonnet-20241022",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello"},
                ],
                tools=None,
                timeout=30.0,
            )

        import json
        assert len(captured) == 1
        payload = json.loads(captured[0].data)
        # System goes to payload['system']
        assert payload.get("system") == "You are a helpful assistant.", (
            f"system prompt must be in payload['system'], got: {payload.get('system')!r}"
        )
        # System must NOT be duplicated as a user message
        msg_contents = [m.get("content", "") for m in payload["messages"]]
        assert "You are a helpful assistant." not in msg_contents, (
            f"system prompt leaked into messages as user content: {payload['messages']}"
        )
        # Only the real user message should remain
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "Hello"

    def test_streaming_system_goes_to_payload_system_not_user(self):
        """_stream_anthropic_events must put system prompt in payload['system'],
        NOT as a user-role message (Anthropic system has higher priority).
        """
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test",
                    model="claude-3-5-sonnet-20241022",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Hello"},
                    ],
                    tools=None,
                    timeout=30.0,
                ))

        import json
        assert len(captured) == 1
        payload = json.loads(captured[0].data)
        # System goes to payload['system']
        assert payload.get("system") == "You are a helpful assistant.", (
            f"streaming system prompt must be in payload['system'], got: {payload.get('system')!r}"
        )
        # System must NOT appear as a user message
        msg_contents = [m.get("content", "") for m in payload["messages"]]
        assert "You are a helpful assistant." not in msg_contents, (
            f"streaming system prompt leaked into messages as user content: {payload['messages']}"
        )

    def test_convert_tools_handles_missing_parameters(self):
        """_convert_tools_for_anthropic must NOT raise KeyError when a tool
        dict lacks 'parameters'. It should default input_schema to {}.
        """
        from agent.runtime import _convert_tools_for_anthropic

        # Missing 'parameters' key entirely
        result = _convert_tools_for_anthropic([{"function": {"name": "f", "description": "d"}}])
        assert result == [{"name": "f", "description": "d", "input_schema": {}}], result

        # parameters=None
        result = _convert_tools_for_anthropic([{"function": {"name": "f", "parameters": None}}])
        assert result == [{"name": "f", "description": "", "input_schema": {}}], result

        # parameters not a dict (string)
        result = _convert_tools_for_anthropic([{"function": {"name": "f", "parameters": "bad"}}])
        assert result == [{"name": "f", "description": "", "input_schema": {}}], result


# ═══════════════════════════════════════════════════════════════════
#  Stale project context reconciliation (Option C+)
# ═══════════════════════════════════════════════════════════════════
#
# The original bug: a special agent conversation persisted to disk carries
# the `project_path` and `system_prompt` snapshot from the session that
# last wrote it. If the user opens a different project in a future
# session, the conversation loads with the STALE project_path — the
# agent's tools are sandboxed to the wrong directory and the system
# prompt is the wrong project's docs.
#
# Fix: the runtime rebuilds the project context on every load + every
# send. _load_conversation_from_disk always sets project_path=None and
# system_prompt="" (the persisted values are kept on disk for audit but
# are not trusted). _rebuild_conversation_context re-applies the active
# project and rebuilds the system prompt against it.
#
# These tests pin the new contract: load() returns a stale-tolerant
# Conversation, and _rebuild_conversation_context correctly re-applies
# the active project.

import json as _json
import os as _os
import tempfile as _tempfile


def _make_runtime():
    """Build a minimal AgentRuntime for testing the reconciliation helpers.

    Mirrors the construction in TestLifecycle above (which is the
    canonical pattern in this file). Returns (rt, sk, tmp_conv_dir).
    """
    from agent.config import AgentConfig, LLMProviderConfig
    from agent.runtime import _conversations_dir
    cfg = AgentConfig(
        providers={
            "openai": LLMProviderConfig(
                name="openai", base_url="https://api.openai.com/v1",
                api_key="test", default_model="gpt-4o",
            )
        },
        default_provider="openai",
        default_model="openai/gpt-4o",
        max_tool_iterations=5,
        tool_timeout_seconds=30,
        auto_save_conversations=False,
    )
    rt = AgentRuntime(cfg)
    rt.start()
    return rt


class TestLoadConversationStaleTolerance:
    """Option C+ load contract: persisted project_path/system_prompt are
    never trusted. They are kept on disk for audit, but load() always
    returns a Conversation with project_path=None and system_prompt="".
    The lazy reconciliation in _rebuild_conversation_context re-applies
    the active project on first send.
    """

    def test_loaded_conversation_has_no_project_path(self, tmp_path, monkeypatch):
        """A conversation persisted under project A loads with project_path=None
        even if the file on disk says project_path=/A. This is the failure-case
        reproduction for the original bug: the old load() copied the stale value
        verbatim and the agent saw project A's docs and tools.
        """
        # Arrange: write a conversation file as if the user had project A open.
        # _conversations_dir() does `from utils.config import get_config_dir`
        # at call time, so we patch the symbol in its source module.
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        # The file says project_path=/old/project and the system_prompt is the
        # one that was rendered against /old/project. New load() must ignore both.
        persisted = {
            "session_key": "special:debugger",
            "agent_name": "Debugger",
            "project_path": "/old/project",
            "model": "openai/gpt-4o",
            "provider": "openai",
            "messages": [],
            "system_prompt": "<rendered against /old/project, contains 'You are working on /old/project'>",
            "total_tokens": 0,
            "total_cost": 0.0,
            "step_count": 0,
        }
        (d / "special:debugger.json").write_text(_json.dumps(persisted))

        # Act
        from agent.runtime import _load_conversation_from_disk
        result = _load_conversation_from_disk("special:debugger")
        assert result is not None, "load() should still find the file"
        conv, _ = result

        # Assert: stale values are NOT applied
        assert conv.project_path is None, (
            f"FAILURE-CASE REPRO: loaded conv.project_path={conv.project_path!r}; "
            "expected None so the active project is applied on first send"
        )
        assert conv.system_prompt == "", (
            f"FAILURE-CASE REPRO: loaded conv.system_prompt={conv.system_prompt!r}; "
            "expected empty so the active project's prompt is rebuilt"
        )

    def test_loaded_conversation_preserves_other_fields(self, tmp_path, monkeypatch):
        """Loading with the new contract must still restore messages, model,
        total_tokens, total_cost, step_count, agent_role, fallback_provider,
        etc. — only project_path and system_prompt are zeroed.
        """
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        persisted = {
            "session_key": "special:debugger",
            "agent_name": "Debugger",
            "agent_role": "debugger",
            "project_path": "/old/project",
            "model": "openai/gpt-4o",
            "provider": "openai",
            "messages": [{"role": "user", "content": "old question", "tool_calls": [], "tool_call_id": None, "tokens_used": 0}],
            "system_prompt": "stale prompt",
            "total_tokens": 80069,
            "total_cost": 1.23,
            "step_count": 18,
            "agent_role": "debugger",
            "fallback_provider": "openrouter",
            "fallback_model": "openrouter/owl-alpha",
        }
        (d / "special:debugger.json").write_text(_json.dumps(persisted))

        from agent.runtime import _load_conversation_from_disk
        conv, _ = _load_conversation_from_disk("special:debugger")

        assert conv is not None
        assert conv.agent_name == "Debugger"
        assert conv.agent_role == "debugger"
        assert conv.model == "openai/gpt-4o"
        assert conv.total_tokens == 80069
        assert conv.total_cost == 1.23
        assert conv.step_count == 18
        assert conv.fallback_provider == "openrouter"
        assert conv.fallback_model == "openrouter/owl-alpha"
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "old question"


class TestRebuildConversationContext:
    """Option C+ rebuild contract: _rebuild_conversation_context re-applies
    the active project and rebuilds the system prompt. The method must be
    idempotent, safe to call on partially-initialized conversations, and
    never raise.
    """

    def test_rebuild_updates_project_path_and_system_prompt(self):
        """Happy path: cold agent's stale conversation has project_path=None
        after load; after rebuild, it matches the active project.
        """
        rt = _make_runtime()
        sk = rt.create_conversation(
            agent_name="Debugger", session_key="special:debugger",
            project_path=None,  # simulates load() — no project applied yet
        )
        conv = rt.get_conversation(sk)
        assert conv.project_path is None
        # NOTE: create_conversation() always calls build_system_prompt and
        # produces a non-empty prompt — even with project_path=None. The
        # empty-prompt case is specific to load_conversation() (the load
        # path zeros it). This test exercises the rebuild path, so the
        # prompt starts non-empty and rebuild must change it.
        assert conv.system_prompt != ""
        original_prompt = conv.system_prompt

        # Act
        rt._rebuild_conversation_context(sk, "/home/q/projects/new", "debugger")

        conv = rt.get_conversation(sk)
        assert conv.project_path == "/home/q/projects/new"
        # The rebuild must produce a new prompt (not no-op). With a different
        # project_path, the awareness block changes → prompt changes.
        # build_awareness_dict puts the project basename into PROJECT_NAME
        # and the path into the snapshot's Path: line.
        assert conv.system_prompt != original_prompt, (
            "rebuild must produce a different prompt when project_path changes"
        )
        rt.stop()

    def test_rebuild_is_idempotent_noop_when_already_in_sync(self):
        """If conv.project_path already matches the active project AND
        system_prompt is non-empty, rebuild is a no-op (cheap short-circuit).
        """
        rt = _make_runtime()
        sk = rt.create_conversation(
            agent_name="Debugger", session_key="special:debugger",
            project_path="/home/q/projects/active",
        )
        # Snapshot the current system_prompt — rebuild should leave it untouched
        original_prompt = rt.get_conversation(sk).system_prompt

        rt._rebuild_conversation_context(sk, "/home/q/projects/active", "debugger")
        assert rt.get_conversation(sk).system_prompt == original_prompt, (
            "idempotent rebuild must not touch system_prompt when already in sync"
        )
        rt.stop()

    def test_rebuild_clears_project_when_active_is_none(self):
        """Passing project_path=None clears the conversation's project
        context. This happens when the user closes the active project.
        """
        rt = _make_runtime()
        sk = rt.create_conversation(
            agent_name="Debugger", session_key="special:debugger",
            project_path="/home/q/projects/old",
        )
        assert rt.get_conversation(sk).project_path == "/home/q/projects/old"

        rt._rebuild_conversation_context(sk, None, "debugger")
        assert rt.get_conversation(sk).project_path is None
        rt.stop()

    def test_rebuild_unknown_session_key_is_silent_noop(self):
        """If the session_key isn't loaded in memory, rebuild is a no-op
        (the cold path handles it on next load). This is critical because
        the eager reconciliation in set_active_project calls rebuild for
        every registered agent, including those that have never been
        instantiated.
        """
        rt = _make_runtime()
        # Should not raise
        rt._rebuild_conversation_context("special:never-instantiated", "/x", "")
        rt.stop()

    def test_rebuild_falls_back_to_persisted_prompt_on_build_failure(self):
        """If build_system_prompt raises (e.g. project path is gone,
        awareness_dict fails), the conversation keeps the OLD persisted
        system_prompt and the agent still works — just with a stale prompt.
        The bug is logged but never crashes the runtime.
        """
        rt = _make_runtime()
        sk = rt.create_conversation(
            agent_name="Debugger", session_key="special:debugger",
            project_path=None,
        )
        conv = rt.get_conversation(sk)
        conv.system_prompt = "the OLD prompt (do not lose this)"

        # Force build_system_prompt to raise by patching it
        from unittest.mock import patch
        with patch("agent.context.build_system_prompt", side_effect=RuntimeError("boom")):
            rt._rebuild_conversation_context(sk, "/some/path", "debugger")

        # Assert: the old prompt is preserved (fallback), and project_path
        # was NOT updated (because the rebuild failed atomically — we don't
        # half-apply).
        conv = rt.get_conversation(sk)
        assert conv.system_prompt == "the OLD prompt (do not lose this)", (
            f"on rebuild failure, the persisted prompt must be preserved; got: {conv.system_prompt!r}"
        )
        rt.stop()

    def test_rebuild_replaces_stale_project_path_with_active(self):
        """FAILURE-CASE REPRO for the original bug: conversation was
        persisted under project A; user opens project B; rebuild must
        replace project_path with B, not keep A.
        """
        rt = _make_runtime()
        sk = rt.create_conversation(
            agent_name="Debugger", session_key="special:debugger",
            project_path="/A",
        )
        # Simulate the original bug state: conversation was just loaded from
        # disk, project_path is still /A (the load() method's old behavior).
        assert rt.get_conversation(sk).project_path == "/A"

        # Act: rebuild against the actually-open project B
        rt._rebuild_conversation_context(sk, "/B", "debugger")

        # Assert: project_path is now B
        conv = rt.get_conversation(sk)
        assert conv.project_path == "/B", (
            f"FAILURE-CASE REPRO: rebuild did not replace stale /A with active /B; "
            f"got project_path={conv.project_path!r}"
        )
        # Assert: system_prompt mentions B, not A
        # (The prompt's awareness block includes the project path; if A is
        # still in the prompt, the rebuild didn't actually rebuild.)
        assert "/A" not in conv.system_prompt or "/B" in conv.system_prompt, (
            f"rebuilt prompt should reflect /B, not /A; got: {conv.system_prompt[:300]!r}"
        )
        rt.stop()


class TestAgentRuntimeContextReconciliationFullPath:
    """Integration test for the full load → rebuild → send path. This is
    the end-to-end behavior the original bug violated: a cold agent
    conversation must reconcile against the active project before any
    send.
    """

    def test_loaded_conversation_reconciles_to_active_project(self, tmp_path, monkeypatch):
        """End-to-end: write a conversation file as if the user had project A
        open. Then "open" project B (call _rebuild_conversation_context with
        /B). The conversation's project_path and system_prompt must reflect
        /B, not /A. This is the exact scenario the user hit with the
        debugger agent in production.
        """
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        persisted = {
            "session_key": "special:debugger",
            "agent_name": "Debugger",
            "project_path": "/A",
            "model": "openai/gpt-4o",
            "provider": "openai",
            "messages": [
                {"role": "user", "content": "old question from /A session",
                 "tool_calls": [], "tool_call_id": None, "tokens_used": 0},
                {"role": "assistant", "content": "old answer",
                 "tool_calls": [], "tool_call_id": None, "tokens_used": 0},
            ],
            "system_prompt": "STALE PROMPT for /A",
            "total_tokens": 0,
            "total_cost": 0.0,
            "step_count": 0,
            "agent_role": "debugger",
        }
        (d / "special:debugger.json").write_text(_json.dumps(persisted))

        rt = _make_runtime()
        # Simulate the production path: load() restores the conversation,
        # then the handler (or build_system_prompt) calls rebuild with the
        # active project.
        ok = rt.load_conversation("special:debugger")
        assert ok
        conv = rt.get_conversation("special:debugger")
        assert conv is not None

        # After load: project_path is None, system_prompt is empty
        # (Option C+ load contract)
        assert conv.project_path is None
        assert conv.system_prompt == ""

        # Conversation history is preserved
        assert len(conv.messages) == 2
        assert conv.messages[0].content == "old question from /A session"
        assert conv.messages[1].content == "old answer"

        # Now reconcile against the active project /B
        rt._rebuild_conversation_context("special:debugger", "/B", "debugger")

        # After rebuild: project_path is /B, system_prompt is freshly built
        assert conv.project_path == "/B"
        assert conv.system_prompt != "STALE PROMPT for /A"
        assert conv.system_prompt != "", "rebuild must produce a real prompt"
        # The old messages are STILL there (rebuild doesn't touch history)
        assert len(conv.messages) == 2

        rt.stop()


# ═══════════════════════════════════════════════════════════════════
#  Local agent chat-bubble header (Bug #8)
# ═══════════════════════════════════════════════════════════════════
#
# Regression tests for the missing-name/dot/timestamp header on local
# special-agent bubbles. The fix threads the display name from
# AgentRuntimeHandler into end_streaming/render_sync as an optional
# parameter so build_role_bubble's header condition is satisfied for
# local agents (which are NOT in AgentManager).

from unittest.mock import MagicMock, patch
from agent.special_agents import SpecialAgentDef


def _make_handler():
    """Build a minimal AgentRuntimeHandler with mock ChatRenderHandler
    and MainContent. The crh is a MagicMock so we can assert call args
    and stub is_streaming without instantiating real GTK widgets.
    """
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    crh = MagicMock()
    mc = MagicMock()
    return AgentRuntimeHandler(main_content=mc, chat_render_handler=crh, GLib_module=None), crh, mc


def _register_coder(handler):
    """Register a Coder special agent and return its conv_id_prefix."""
    coder = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file", "edit_file", "exec_command",
               "list_files", "search_files", "web_search", "web_fetch"],
        can_write=True,
        llm_name="minimax",
    )
    handler.add_special_agent(coder)
    return coder


class TestLocalAgentHeaderStreaming:
    """Test A: _do_response_complete streaming path passes real display name."""

    def test_streaming_passes_display_name_to_end_streaming(self):
        handler, crh, _mc = _make_handler()
        _register_coder(handler)

        crh.is_streaming.return_value = True
        # _do_response_complete writes to self._crh — call directly
        handler._do_response_complete("special:coder", "hello world")

        crh.end_streaming.assert_called_once()
        # The new fix: agent_name kwarg is the display name, not None
        call_kwargs = crh.end_streaming.call_args.kwargs
        call_args = crh.end_streaming.call_args.args
        # Signature is end_streaming(session_key, agent_name=None)
        # — verify agent_name kwarg or positional[1] is "Coder"
        if "agent_name" in call_kwargs:
            assert call_kwargs["agent_name"] == "Coder", (
                f"FAILURE-CASE REPRO: end_streaming was called with "
                f"agent_name={call_kwargs['agent_name']!r}; expected 'Coder' "
                "so the local-agent header renders"
            )
        else:
            assert len(call_args) >= 2 and call_args[1] == "Coder", (
                f"FAILURE-CASE REPRO: end_streaming positional args were "
                f"{call_args!r}; expected ('special:coder', 'Coder')"
            )


class TestLocalAgentHeaderNonStreaming:
    """Test B: _do_response_complete non-streaming path uses real name, not hardcoded 'Agent'."""

    def test_non_streaming_passes_display_name_to_render_sync(self):
        handler, crh, _mc = _make_handler()
        _register_coder(handler)

        crh.is_streaming.return_value = False
        handler._do_response_complete("special:coder", "hello world")

        crh.render_sync.assert_called_once()
        call_kwargs = crh.render_sync.call_args.kwargs
        call_args = crh.render_sync.call_args.args
        # render_sync(role, text, session_key, agent_name=...)
        if "agent_name" in call_kwargs:
            assert call_kwargs["agent_name"] == "Coder", (
                f"FAILURE-CASE REPRO: render_sync was called with "
                f"agent_name={call_kwargs['agent_name']!r}; expected 'Coder' "
                "instead of the hardcoded 'Agent' that the bug shipped with"
            )
        else:
            assert len(call_args) >= 4 and call_args[3] == "Coder", (
                f"FAILURE-CASE REPRO: render_sync positional args were "
                f"{call_args!r}; expected (..., 'Coder')"
            )


class TestEndStreamingExplicitNameTakesPriority:
    """Test C: end_streaming honors an explicitly passed agent_name
    over the agent_mgr lookup path (which returns '' for special: keys).

    Patches build_role_bubble so the test does not need a working GTK
    display. The real build_role_bubble (chat_bubble.py:240) is GTK-dependent
    and segfaults in headless test environments.
    """

    def test_explicit_agent_name_reaches_build_role_bubble(self):
        """Patch build_role_bubble and assert it received agent_name='Coder'.
        This is the unit-level check that the priority logic is correct.
        """
        from ui.handlers.chat_render_handler import ChatRenderHandler
        from models.streaming import StreamingBubble

        with patch("ui.handlers.chat_render_handler.Gtk"):
            crh = ChatRenderHandler(GLib_module=None)
        # mock main_content with empty _agent_mgr (simulates AgentManager miss
        # for a special: key — the original bug condition)
        mc = MagicMock()
        mc._agent_mgr.get_name.return_value = ""
        crh._main_content = mc
        # dispatch is a no-op without GLib, so _finalize runs synchronously
        crh._dispatch = lambda fn: fn()

        sb = StreamingBubble(container=MagicMock(), label=MagicMock(),
                             role="Agent", bubble=MagicMock())
        sb.plain_text = "hello"
        sb.container.__contains__.return_value = False
        crh._streaming_bubbles["special:coder"] = sb

        with patch("ui.handlers.chat_render_handler.build_role_bubble") as brb:
            brb.return_value = MagicMock(name="bubble")
            crh.end_streaming("special:coder", agent_name="Coder")

        # build_role_bubble was called once; agent_name is the 8th positional
        # arg or the agent_name kwarg.
        assert brb.call_count == 1
        call_kwargs = brb.call_args.kwargs
        call_args = brb.call_args.args
        # Signature: build_role_bubble(role, text, on_forward_click=..., tight=...,
        # forwarded_from=..., session_key=..., agent_name=...)
        if "agent_name" in call_kwargs:
            actual = call_kwargs["agent_name"]
        else:
            actual = call_args[7] if len(call_args) >= 8 else None
        assert actual == "Coder", (
            f"FAILURE-CASE REPRO: build_role_bubble received agent_name={actual!r}; "
            "expected 'Coder' so the header (name+dot+timestamp) renders"
        )


class TestEndStreamingFallbackForGatewayAgents:
    """Test D: end_streaming with no agent_name arg falls back to agent_mgr
    (gateway compatibility — gateway agents ARE in AgentManager).
    """

    def test_no_agent_name_falls_back_to_agent_mgr(self):
        from ui.handlers.chat_render_handler import ChatRenderHandler
        from models.streaming import StreamingBubble

        with patch("ui.handlers.chat_render_handler.Gtk"):
            crh = ChatRenderHandler(GLib_module=None)
        mc = MagicMock()
        mc._agent_mgr.get_name.return_value = "Qaster"  # gateway agent registered
        crh._main_content = mc
        crh._dispatch = lambda fn: fn()

        sb = StreamingBubble(container=MagicMock(), label=MagicMock(),
                             role="Agent", bubble=MagicMock())
        sb.plain_text = "hello"
        sb.container.__contains__.return_value = False
        crh._streaming_bubbles["agent:qaster:main"] = sb

        with patch("ui.handlers.chat_render_handler.build_role_bubble") as brb:
            brb.return_value = MagicMock(name="bubble")
            crh.end_streaming("agent:qaster:main")  # NO agent_name arg

        # agent_mgr.get_name was called for the session key
        mc._agent_mgr.get_name.assert_called_with("agent:qaster:main")
        # build_role_bubble received "Qaster" (the gateway name)
        call_kwargs = brb.call_args.kwargs
        call_args = brb.call_args.args
        if "agent_name" in call_kwargs:
            actual = call_kwargs["agent_name"]
        else:
            actual = call_args[7] if len(call_args) >= 8 else None
        assert actual == "Qaster", (
            f"FAILURE-CASE REPRO: end_streaming fallback should have resolved "
            f"'Qaster' via agent_mgr; got {actual!r}"
        )


# ═══════════════════════════════════════════════════════════════════
#  allowed_tools fallback (allowed-tools-fallback-spec.md)
# ═══════════════════════════════════════════════════════════════════
#
# Regression tests for the stale-state bug: pre-fix conversations had
# allowed_tools: null on disk, which bypassed the execute_tool gate
# entirely. The fix: in _load_conversation_from_disk, if persisted
# allowed_tools is None, fall back to the live agent definition's
# tools list via get_special_agent(). Mirrors the HIGH-3 api_key
# re-resolution pattern and the Option C+ project_path pattern.


class TestAllowedToolsFallback:
    """Spec: allowed-tools-fallback-spec.md (Edit 2).

    The persisted allowed_tools field may be None for conversations
    created before the execute_tool gate shipped. The fallback fires
    at load time and re-populates conv.allowed_tools from the live
    SpecialAgentDef so the gate is a no-op ONLY when the live config
    also has no allow-list.
    """

    def test_persisted_none_falls_back_to_live_agent_definition(
        self, tmp_path, monkeypatch
    ):
        """A conversation persisted with allowed_tools: null gets the
        live agent's tools list. Failure-case reproduction: without
        this, the Debugger agent's pre-fix conversation has no
        allow-list and the gate is a no-op.
        """
        # Arrange: write a conversation with allowed_tools: null
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        persisted = {
            "session_key": "special:debugger",
            "agent_name": "Debugger",
            "agent_role": "debugger",
            "project_path": None,
            "model": "openai/gpt-4o",
            "provider": "openai",
            "messages": [],
            "system_prompt": "",
            "total_tokens": 0,
            "total_cost": 0.0,
            "step_count": 0,
            # KEY: allowed_tools: null — the bug condition.
            "allowed_tools": None,
        }
        (d / "special:debugger.json").write_text(_json.dumps(persisted))

        # Patch get_special_agent to return a read-only Debugger def.
        # Mirrors the production Debugger YAML (read-only).
        debugger_def = SpecialAgentDef(
            conv_id_prefix="special:debugger",
            display_name="Debugger",
            role="debugger",
            emoji="🐛",
            tools=["read_file", "list_files", "search_files"],
            can_write=False,
        )
        monkeypatch.setattr(
            "agent.special_agents.get_special_agent",
            lambda sk: debugger_def if sk == "special:debugger" else None,
        )

        # Act
        from agent.runtime import _load_conversation_from_disk
        result = _load_conversation_from_disk("special:debugger")
        assert result is not None
        conv, _ = result

        # Assert: fallback fired — conv.allowed_tools is the live list,
        # not None. The execute_tool gate will now deny write_file /
        # edit_file for this conversation.
        assert conv.allowed_tools == ["read_file", "list_files", "search_files"], (
            f"FAILURE-CASE REPRO: conv.allowed_tools={conv.allowed_tools!r}; "
            "expected live fallback list. The Debugger agent's pre-fix "
            "conversation would have allowed_tools=None, and the gate "
            "would be a no-op — letting write_file/edit_file through."
        )

    def test_persisted_list_wins_over_fallback(
        self, tmp_path, monkeypatch
    ):
        """Happy path: persisted allowed_tools is a real list — fallback
        does NOT override it. The persisted list is the source of
        truth when present (e.g., the Coder agent's conversation has
        the correct list persisted).
        """
        # Arrange: write a conversation with a real list
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        persisted_tools = ["read_file", "write_file"]
        persisted = {
            "session_key": "special:coder",
            "agent_name": "Coder",
            "agent_role": "coder",
            "project_path": None,
            "model": "openai/gpt-4o",
            "provider": "openai",
            "messages": [],
            "system_prompt": "",
            "total_tokens": 100,
            "total_cost": 0.01,
            "step_count": 1,
            "allowed_tools": persisted_tools,  # real list, not None
        }
        (d / "special:coder.json").write_text(_json.dumps(persisted))

        # Patch get_special_agent to return a DIFFERENT live list.
        # If the fallback fires, conv.allowed_tools would be overwritten
        # with this list. The persisted list must win.
        live_def = SpecialAgentDef(
            conv_id_prefix="special:coder",
            display_name="Coder",
            role="coder",
            emoji="🛠️",
            tools=["read_file"],  # different from persisted
            can_write=True,
        )
        fallback_called = MagicMock(return_value=live_def)
        monkeypatch.setattr(
            "agent.special_agents.get_special_agent", fallback_called
        )

        # Act
        from agent.runtime import _load_conversation_from_disk
        result = _load_conversation_from_disk("special:coder")
        assert result is not None
        conv, _ = result

        # Assert: persisted list is preserved
        assert conv.allowed_tools == persisted_tools, (
            f"persisted allowed_tools was overwritten by fallback: "
            f"got {conv.allowed_tools!r}, expected {persisted_tools!r}"
        )
        # The fallback lookup was NOT called (the early return at
        # `if conv.allowed_tools is None:` skipped it).
        fallback_called.assert_not_called()

    def test_persisted_none_with_unregistered_agent_leaves_none(
        self, tmp_path, monkeypatch
    ):
        """Edge case: persisted None + agent not in registry → stays None.

        This is the "agent no longer registered" case (e.g., the YAML
        was deleted between sessions). The fallback is best-effort;
        leaving None means the gate is skipped — same as today.
        """
        d = tmp_path / "conversations"
        d.mkdir()
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        persisted = {
            "session_key": "special:deleted_agent",
            "agent_name": "DeletedAgent",
            "project_path": None,
            "model": "openai/gpt-4o",
            "messages": [],
            "system_prompt": "",
            "total_tokens": 0,
            "total_cost": 0.0,
            "step_count": 0,
            "allowed_tools": None,
        }
        (d / "special:deleted_agent.json").write_text(_json.dumps(persisted))

        # Agent not in registry
        monkeypatch.setattr(
            "agent.special_agents.get_special_agent", lambda sk: None
        )

        from agent.runtime import _load_conversation_from_disk
        result = _load_conversation_from_disk("special:deleted_agent")
        assert result is not None
        conv, _ = result

        # Stays None — the gate is skipped, same as before the fallback
        assert conv.allowed_tools is None


# ═══════════════════════════════════════════════════════════════════
#  Pre-Call Budget Guard
# ═══════════════════════════════════════════════════════════════════

class TestPreCallBudgetGuard:
    """Tests for the pre-call RuntimeError guard in _run_loop."""

    def test_guard_fires_when_post_trim_exceeds_budget(self):
        """Guard raises RuntimeError when conversation exceeds model_max minus response reserve."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    default_model="gpt-4o",
                    max_tokens=100,
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=1,
            tool_timeout_seconds=5,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.system_prompt = "Test"
        conv.add_user_message("hello")

        errors = []
        rt._on_error = lambda session_key, msg: errors.append(str(msg))
        rt._run_loop(sk, "test")
        assert errors, "guard should have fired"
        assert "exceeds model context window" in errors[0]

    def test_guard_message_includes_usage_percent_and_hint(self):
        """Error message must include usage percent and remediation hint."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    default_model="gpt-4o",
                    max_tokens=50,
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=1,
            tool_timeout_seconds=5,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)
        conv.system_prompt = "Test"
        conv.add_user_message("hello")

        errors = []
        rt._on_error = lambda session_key, msg: errors.append(str(msg))
        rt._run_loop(sk, "test")
        assert errors, "guard should have fired"
        msg = errors[0]
        assert "%" in msg, f"missing percent: {msg}"
        assert "/clear" in msg, f"missing /clear hint: {msg}"
        assert "/compact" in msg, f"missing /compact hint: {msg}"


# ═══════════════════════════════════════════════════════════════════
#  SSE Frame-Shape Hardening (Phase 1)
# ═══════════════════════════════════════════════════════════════════

class TestSSEFrameShapeHardening:
    """Phase 1 hardening: _first_choice helper + _parse_sse_delta safety
    against empty-choices frames (OpenAI trailing usage, keepalive, etc.)."""

    def test_first_choice_normal_frame(self):
        """Normal delta frame: choices[0] is returned."""
        from agent.runtime import _first_choice
        result = _first_choice({"choices": [{"delta": {"content": "hi"}}]})
        assert result == {"delta": {"content": "hi"}}

    def test_first_choice_empty_choices_with_usage(self):
        """OpenAI trailing usage frame: choices is [], should return {}."""
        from agent.runtime import _first_choice
        result = _first_choice({"choices": [], "usage": {"total_tokens": 42}})
        assert result == {}

    def test_first_choice_no_choices_key(self):
        """Keepalive frame: no choices key at all, should return {}."""
        from agent.runtime import _first_choice
        assert _first_choice({}) == {}

    def test_first_choice_only_usage(self):
        """Usage-only frame: {"usage": {...}}, no choices."""
        from agent.runtime import _first_choice
        assert _first_choice({"usage": {"prompt_tokens": 10}}) == {}

    def test_parse_sse_delta_empty_choices_no_crash(self):
        """_parse_sse_delta must not crash on empty choices (the original bug)."""
        from agent.runtime import _parse_sse_delta
        result = _parse_sse_delta({"choices": [], "usage": {"total_tokens": 42}})
        assert result == []

    def test_parse_sse_delta_no_choices_key_no_crash(self):
        """_parse_sse_delta must not crash when choices key is absent."""
        from agent.runtime import _parse_sse_delta
        assert _parse_sse_delta({}) == []

    def test_parse_sse_delta_normal_text_delta(self):
        """Normal text delta still works after hardening."""
        from agent.runtime import _parse_sse_delta
        events = _parse_sse_delta(
            {"choices": [{"delta": {"content": "hello"}}]}
        )
        assert len(events) == 1
        assert events[0].type == "text_delta"
        assert events[0].data["content"] == "hello"

    def test_parse_sse_delta_tool_call_delta(self):
        """Tool call deltas still work after hardening."""
        from agent.runtime import _parse_sse_delta
        events = _parse_sse_delta(
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1",
                 "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}
            ]}}]}
        )
        assert len(events) == 1
        assert events[0].type == "tool_call_delta"
        assert events[0].data["name"] == "read_file"
        assert events[0].data["id"] == "call_1"

    def test_no_unguarded_choices_zero_indexing(self):
        """Regression: no remaining d.get('choices', [{}])[0] patterns."""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", 'd\.get("choices", [{}])[0]', "agent/runtime.py"],
            capture_output=True, text=True, cwd="/home/q/projects/crabcakes",
        )
        assert result.stdout == "", (
            f"Unguarded [0] indexing found:\n{result.stdout}"
        )

    def test_first_choice_used_at_all_three_sites(self):
        """_first_choice should appear 4 times: 1 def + 3 call sites."""
        import subprocess
        result = subprocess.run(
            ["grep", "-c", "_first_choice", "agent/runtime.py"],
            capture_output=True, text=True, cwd="/home/q/projects/crabcakes",
        )
        count = int(result.stdout.strip())
        assert count >= 4, f"Expected >= 4 _first_choice references, got {count}"
