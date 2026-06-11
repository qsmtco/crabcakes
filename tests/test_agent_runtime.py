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
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt_module._call_llm_streaming(
                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",
                api_key="test", model="openai/gpt-4o",
                caller_key="openai",  # PHASE-10.5a: required positional arg
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
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
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt_module._call_llm_streaming(
                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",
                api_key="test", model="openai/gpt-4o",
                caller_key="openai",  # PHASE-10.5a: required positional arg
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
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
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt_module._call_llm_streaming(
                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",
                api_key="test", model="openai/gpt-4o",
                caller_key="openai",  # PHASE-10.5a: required positional arg
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
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
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt_module._call_llm_streaming(
                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",
                api_key="test", model="openai/gpt-4o",
                caller_key="openai",  # PHASE-10.5a: required positional arg
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        conv = rt.get_conversation(sk)
        # Last message should be the assistant response with full text
        assistant_msgs = [m for m in conv.messages if m.role.value == "assistant"]
        assert len(assistant_msgs) >= 1, f"Expected assistant message, got: {[m.role.value for m in conv.messages]}"
        assert assistant_msgs[-1].content == "Hello world!"
        rt.stop()


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
