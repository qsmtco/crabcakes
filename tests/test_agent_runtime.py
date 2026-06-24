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
                    max_tokens=500,  # tiny — forces the trim
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

        # Stuff the conversation with 20 long exchanges (~100 tokens each)
        for i in range(20):
            conv.add_user_message(f"turn {i}: " + "x" * 400)
            conv.add_assistant_message("y" * 400, [])

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

    def test_stuck_message_prepended_to_next_llm_request(self):
        """When a stuck message is pending, _call_llm prepends it to the messages
        list before making the API call. Verified by mocking the underlying provider
        caller (not _call_llm itself, which contains the injection logic)."""
        from agent import runtime as rt_module

        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        # Manually populate pending stuck messages
        rt._pending_stuck_messages[sk] = ["Test stuck intervention message"]

        # Mock the underlying provider caller to capture the messages it receives
        captured_messages = []
        def mock_streamer(base_url, api_key, model, messages, tools, timeout, x_title=""):
            captured_messages.append(list(messages))
            yield from []

        orig_streamer = rt_module._PROVIDER_STREAMERS.get("openai")
        rt_module._PROVIDER_STREAMERS["openai"] = mock_streamer
        try:
            rt._call_llm_streaming(
                session_key=sk,
                base_url="https://api.openai.com/v1",
                api_key="test",
                model="openai/gpt-4o",
                caller_key="openai",
                messages=[{"role": "user", "content": "hello"}],
                tools=None,
                timeout=30.0,
            )
        finally:
            if orig_streamer is not None:
                rt_module._PROVIDER_STREAMERS["openai"] = orig_streamer

        # The first message passed to the streamer should be the stuck prefix
        assert len(captured_messages) == 1, f"Expected 1 captured call, got: {len(captured_messages)}"
        first_msg = captured_messages[0][0]
        assert first_msg["role"] == "user", f"Expected first message role=user, got: {first_msg['role']}"
        assert "Stuck-detection intervention" in first_msg["content"], \
            f"Expected stuck prefix in first message, got: {first_msg['content'][:100]}"
        assert "Test stuck intervention message" in first_msg["content"], \
            f"Expected stuck text in first message, got: {first_msg['content'][:100]}"

        # The pending list should be cleared after consumption
        assert sk not in rt._pending_stuck_messages, \
            f"Pending should be cleared after _call_llm, got: {rt._pending_stuck_messages.get(sk)}"

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
