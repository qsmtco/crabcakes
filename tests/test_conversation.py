# tests/test_conversation.py
# Unit tests for models/conversation.py
#
# Tests the contract — each public method's documented behavior.
# Edge cases that could break callers (AgentRuntime, context.py) are covered.

import pytest
from models.conversation import (
    Conversation,
    Message,
    ToolCall,
    MessageRole,
    ToolCallStatus,
)


# ═══════════════════════════════════════════════════════════════════
#  ToolCall dataclass
# ═══════════════════════════════════════════════════════════════════

class TestToolCallDefaults:
    def test_default_status_is_pending(self):
        tc = ToolCall(call_id="call_1", tool_name="read_file", arguments={"path": "a.py"})
        assert tc.status == ToolCallStatus.PENDING
        assert tc.result is None
        assert tc.started_at is None
        assert tc.completed_at is None

    def test_mark_executing_sets_status_and_time(self):
        tc = ToolCall(call_id="call_1", tool_name="read_file", arguments={})
        tc.mark_executing()
        assert tc.status == ToolCallStatus.EXECUTING
        assert tc.started_at is not None

    def test_mark_completed_sets_result_and_time(self):
        tc = ToolCall(call_id="call_1", tool_name="read_file", arguments={})
        tc.mark_completed("file contents")
        assert tc.status == ToolCallStatus.COMPLETED
        assert tc.result == "file contents"
        assert tc.completed_at is not None

    def test_mark_failed_sets_error(self):
        tc = ToolCall(call_id="call_1", tool_name="read_file", arguments={})
        tc.mark_failed("Permission denied")
        assert tc.status == ToolCallStatus.FAILED
        assert tc.result == "Permission denied"
        assert tc.completed_at is not None


# ═══════════════════════════════════════════════════════════════════
#  Message dataclass
# ═══════════════════════════════════════════════════════════════════

class TestMessageDefaults:
    def test_default_timestamp_is_set(self):
        msg = Message(role=MessageRole.USER, content="hello")
        assert msg.timestamp is not None

    def test_default_tokens_used_is_zero(self):
        msg = Message(role=MessageRole.USER, content="hello")
        assert msg.tokens_used == 0

    def test_default_tool_calls_is_empty_list(self):
        msg = Message(role=MessageRole.USER, content="hello")
        assert msg.tool_calls == []
        assert isinstance(msg.tool_calls, list)

    def test_is_tool_call_true_for_assistant_with_tools(self):
        tc = ToolCall(call_id="c1", tool_name="read", arguments={})
        msg = Message(role=MessageRole.ASSISTANT, content="", tool_calls=[tc])
        assert msg.is_tool_call is True

    def test_is_tool_call_false_for_assistant_without_tools(self):
        msg = Message(role=MessageRole.ASSISTANT, content="hello", tool_calls=[])
        assert msg.is_tool_call is False

    def test_is_tool_result_true_for_tool_result_role(self):
        msg = Message(role=MessageRole.TOOL_RESULT, content="result", tool_call_id="c1")
        assert msg.is_tool_result is True

    def test_is_tool_result_false_for_other_roles(self):
        msg = Message(role=MessageRole.USER, content="hello")
        assert msg.is_tool_result is False


# ═══════════════════════════════════════════════════════════════════
#  Conversation dataclass
# ═══════════════════════════════════════════════════════════════════

class TestConversationDefaults:
    def test_project_path_defaults_to_none(self):
        c = Conversation(agent_name="Coder")
        assert c.project_path is None

    def test_system_prompt_defaults_to_empty(self):
        c = Conversation(agent_name="Coder")
        assert c.system_prompt == ""

    def test_messages_defaults_to_empty_list(self):
        c = Conversation(agent_name="Coder")
        assert c.messages == []
        assert isinstance(c.messages, list)

    def test_model_defaults_to_empty_string(self):
        c = Conversation(agent_name="Coder")
        assert c.model == ""

    def test_total_cost_defaults_to_zero(self):
        c = Conversation(agent_name="Coder")
        assert c.total_cost == 0.0

    def test_step_count_defaults_to_zero(self):
        c = Conversation(agent_name="Coder")
        assert c.step_count == 0

    def test_created_at_is_set(self):
        c = Conversation(agent_name="Coder")
        assert c.created_at is not None


class TestConversationMessageHelpers:
    def test_add_user_message_returns_message(self):
        c = Conversation(agent_name="Coder")
        msg = c.add_user_message("hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "hello"
        assert len(c.messages) == 1

    def test_add_assistant_message_returns_message(self):
        c = Conversation(agent_name="Coder")
        msg = c.add_assistant_message("thinking...", [])
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "thinking..."
        assert len(c.messages) == 1

    def test_add_assistant_message_increments_step_count(self):
        c = Conversation(agent_name="Coder")
        assert c.step_count == 0
        c.add_assistant_message("turn 1", [])
        assert c.step_count == 1
        c.add_assistant_message("turn 2", [])
        assert c.step_count == 2

    def test_add_assistant_message_with_tool_calls(self):
        c = Conversation(agent_name="Coder")
        tc = ToolCall(call_id="c1", tool_name="read_file", arguments={"path": "a.py"})
        msg = c.add_assistant_message("", [tc])
        assert msg.tool_calls == [tc]
        assert msg.is_tool_call is True

    def test_add_tool_result_returns_message(self):
        c = Conversation(agent_name="Coder")
        msg = c.add_tool_result("c1", "file contents here")
        assert msg.role == MessageRole.TOOL_RESULT
        assert msg.content == "file contents here"
        assert msg.tool_call_id == "c1"

    def test_tool_result_does_not_increment_step_count(self):
        c = Conversation(agent_name="Coder")
        c.add_assistant_message("I will read the file", [])
        assert c.step_count == 1
        c.add_tool_result("c1", "file contents")
        assert c.step_count == 1  # still 1


class TestConversationToApiMessages:
    def test_empty_conversation_returns_nothing(self):
        c = Conversation(agent_name="Coder")
        assert c.to_api_messages() == []

    def test_system_prompt_becomes_first_system_message(self):
        c = Conversation(agent_name="Coder", system_prompt="You are helpful.")
        msgs = c.to_api_messages()
        assert msgs[0] == {"role": "system", "content": "You are helpful."}

    def test_user_message_format(self):
        c = Conversation(agent_name="Coder")
        c.add_user_message("hello world")
        msgs = c.to_api_messages()
        assert msgs[0] == {"role": "user", "content": "hello world"}

    def test_assistant_message_with_text(self):
        c = Conversation(agent_name="Coder")
        c.add_assistant_message("Here is the answer", [])
        msgs = c.to_api_messages()
        assert msgs[0] == {"role": "assistant", "content": "Here is the answer"}

    def test_assistant_message_with_tool_calls(self):
        c = Conversation(agent_name="Coder")
        tc = ToolCall(call_id="call_abc", tool_name="read_file", arguments={"path": "a.py"})
        c.add_assistant_message("", [tc])
        msgs = c.to_api_messages()
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"][0]["id"] == "call_abc"
        assert msgs[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"path": "a.py"}'

    def test_tool_result_format(self):
        c = Conversation(agent_name="Coder")
        c.add_tool_result("call_abc", "file contents")
        msgs = c.to_api_messages()
        assert msgs[0] == {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": "file contents",
        }

    def test_full_conversation_sequence(self):
        c = Conversation(agent_name="Coder", system_prompt="You are Coder.")
        c.add_user_message("Implement auth")
        tc = ToolCall(call_id="c1", tool_name="write_file", arguments={"path": "auth.py", "content": ""})
        c.add_assistant_message("", [tc])
        c.add_tool_result("c1", "OK — wrote 100 bytes")
        c.add_assistant_message("Done.", [])
        msgs = c.to_api_messages()
        assert len(msgs) == 5  # system, user, assistant+tool, tool-result, assistant
        assert msgs[0] == {"role": "system", "content": "You are Coder."}
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"
        assert msgs[2]["tool_calls"][0]["function"]["name"] == "write_file"
        assert msgs[3]["role"] == "tool"
        assert msgs[4]["role"] == "assistant"


class TestConversationTokenEstimate:
    """Phase CB-4: tests use tolerance-based assertions because tiktoken counts differ from chars // 4.

    The conv.model defaults to "" (empty string), which is not a known model name.
    So _tiktoken_encoding_for("") falls back to the cl100k_base default encoding.
    """

    def test_empty_conversation_is_zero(self):
        c = Conversation(agent_name="Coder")
        # system_prompt is empty, no messages → 0 tokens
        assert c.get_token_estimate() == 0

    def test_system_prompt_counted(self):
        # Use realistic text (not "x" * 40, which tokenizes to 1 token with tiktoken
        # but 10 tokens with chars // 4). The system_prompt is the agent's
        # general instructions, which contains normal English words.
        prompt = "You are a helpful assistant that writes Python code."  # 11 words
        c = Conversation(agent_name="Coder", system_prompt=prompt, model="gpt-4o")
        # With tiktoken (cl100k_base for gpt-4o), this prompt is ~10-11 tokens.
        # With chars // 4 fallback, it would be ~14 tokens.
        # We assert a tolerance: actual is within ±30% of the tiktoken ground truth.
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected = len(enc.encode(prompt))
        actual = c.get_token_estimate()
        assert abs(actual - expected) <= 1, f"expected ~{expected} tokens, got {actual}"

    def test_messages_counted(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("hello world")  # 11 chars
        # tiktoken says: "hello world" = 2 tokens (cl100k_base).
        # chars // 4 says: 11 // 4 = 2.
        # Both agree on this case.
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected_msg = len(enc.encode("hello world"))
        actual = c.get_token_estimate()
        assert actual == expected_msg, f"expected {expected_msg} tokens, got {actual}"

    def test_tool_call_args_and_result_counted(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        tc = ToolCall(call_id="c1", tool_name="read_file", arguments={"path": "a.py", "content": "xyzt"})
        c.add_tool_result("c1", "result here")
        # tokens counted from tool_calls arguments + result
        estimate = c.get_token_estimate()
        assert estimate > 0
        # Sanity: at least the "result here" + serialized arguments
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        min_expected = len(enc.encode("result here"))
        assert estimate >= min_expected, f"expected >= {min_expected} tokens, got {estimate}"


class TestTiktokenAccurate:
    """Phase CB-4 (BUG #5 fix): tiktoken-based accurate token estimation."""

    def test_known_openai_model_uses_tiktoken(self):
        """conv.model='gpt-4o' should use tiktoken.encoding_for_model('gpt-4o')."""
        c = Conversation(agent_name="Coder", system_prompt="hello", model="gpt-4o")
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected = len(enc.encode("hello"))
        assert c.get_token_estimate() == expected

    def test_provider_prefix_is_stripped(self):
        """conv.model='openai/gpt-4o' should strip 'openai/' prefix and use 'gpt-4o'."""
        c = Conversation(agent_name="Coder", system_prompt="hello", model="openai/gpt-4o")
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected = len(enc.encode("hello"))
        assert c.get_token_estimate() == expected

    def test_unknown_model_falls_back_to_default_encoding(self):
        """conv.model='unknown-xyz' should fall back to cl100k_base (not chars // 4)."""
        c = Conversation(agent_name="Coder", system_prompt="hello world", model="unknown-xyz")
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("hello world"))
        actual = c.get_token_estimate()
        assert actual == expected, f"expected {expected} tokens, got {actual} (chars//4 would be {len('hello world') // 4})"

    def test_tiktoken_import_error_falls_back_to_chars(self, monkeypatch):
        """If tiktoken is not importable, fall back to chars // 4 (no crash)."""
        import sys
        monkeypatch.setitem(sys.modules, "tiktoken", None)
        from models import conversation as conv_module
        monkeypatch.setattr(conv_module, "_tiktoken_encoding_for", lambda m: None)
        c = Conversation(agent_name="Coder", system_prompt="x" * 40)
        assert c.get_token_estimate() == 10  # 40 // 4 = 10

    def test_breakdown_uses_tiktoken(self):
        """get_token_breakdown should return tiktoken-accurate counts for known models."""
        c = Conversation(agent_name="Coder", system_prompt="x" * 40, model="gpt-4o")
        c.add_user_message("hello")
        breakdown = c.get_token_breakdown(model_max_tokens=1000)
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected_system = len(enc.encode("x" * 40))
        expected_conv = len(enc.encode("hello"))
        assert breakdown["system_prompt_tokens"] == expected_system
        assert breakdown["conversation_tokens"] == expected_conv
        assert breakdown["total_used_tokens"] == expected_system + expected_conv


class TestConversationTrim:
    def test_trim_does_nothing_when_under_limit(self):
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi")
        c.add_assistant_message("hello", [])
        c.trim_to_token_limit(max_tokens=100)
        assert len(c.messages) == 2

    def test_trim_removes_oldest_messages(self):
        c = Conversation(agent_name="Coder")
        for i in range(10):
            c.add_user_message("x" * 200)  # ~50 tokens each
        c.add_assistant_message("done", [])
        initial = len(c.messages)
        c.trim_to_token_limit(max_tokens=20)
        assert len(c.messages) < initial

    def test_trim_never_removes_most_recent_user_message(self):
        c = Conversation(agent_name="Coder")
        for i in range(5):
            c.add_user_message("x" * 200)
        most_recent = c.messages[-1]
        c.trim_to_token_limit(max_tokens=10)
        assert c.messages[-1] == most_recent

    def test_trim_keeps_system_prompt(self):
        c = Conversation(agent_name="Coder", system_prompt="x" * 400)
        c.add_user_message("x" * 400)
        c.trim_to_token_limit(max_tokens=50)
        assert c.system_prompt == "x" * 400  # never removed


class TestConversationCostTracking:
    def test_record_usage_updates_totals(self):
        c = Conversation(agent_name="Coder")
        c.record_usage(tokens=1000, cost=0.02)
        assert c.total_tokens == 1000
        assert c.total_cost == 0.02

    def test_record_usage_is_cumulative(self):
        c = Conversation(agent_name="Coder")
        c.record_usage(tokens=1000, cost=0.02)
        c.record_usage(tokens=500, cost=0.01)
        assert c.total_tokens == 1500
        assert c.total_cost == 0.03

    def test_record_usage_sets_last_message_tokens(self):
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi")
        c.add_assistant_message("hello", [])
        c.record_usage(tokens=200, cost=0.004)
        assert c.messages[-1].tokens_used == 200


# ═══════════════════════════════════════════════════════════════════
#  Phase CB-2: trim fallback includes oldest message (BUG #2 fix)
# ═══════════════════════════════════════════════════════════════════

class TestTrimFallbackIncludesOldest:
    """Phase CB-2 fix: trim fallback pops index 0 (oldest message) unconditionally.

    The previous code used range(1, len-1) looking for USER messages to
    remove. When the middle of the conversation was full of consecutive
    ASSISTANT messages (e.g., after a 20-exchange USER/ASSISTANT history),
    the trim stalled at ~21 messages instead of reaching the 4-5 message
    target. The new fallback pops the oldest message in the trimmable
    region (index 0) regardless of role, so the trim always makes
    progress. See QTR's Phase CB-1 audit (2026-06-17) for the empirical
    trace; see SPEC-CONTEXT-BLOAT-PHASE-2.md §2.1 for the fix rationale.
    """

    def test_fallback_removes_oldest_when_middle_is_all_assistant(self):
        """40 alternating USER/ASSISTANT messages trim down to <8 messages, not 21."""
        c = Conversation(agent_name="Coder")
        for i in range(20):
            c.add_user_message(f"turn {i}: " + "x" * 400)
            c.add_assistant_message("y" * 400, [])
        assert len(c.messages) == 40
        c.trim_to_token_limit(500)
        assert len(c.messages) < 8, (
            f"trim stalled at {len(c.messages)} messages; expected <8"
        )

    def test_fallback_still_protects_preserved_tail(self):
        """The last 4 messages are never removed."""
        c = Conversation(agent_name="Coder")
        c.add_assistant_message("oldest assistant " + "x" * 400, [])
        for i in range(15):
            c.add_user_message(f"middle user {i} " + "x" * 400)
            c.add_assistant_message(f"middle assistant {i} " + "y" * 400)
        tail_before = [m.content[:30] for m in c.messages[-4:]]
        c.trim_to_token_limit(500)
        tail_after = [m.content[:30] for m in c.messages[-4:]]
        assert tail_before == tail_after, (
            f"preserved tail was modified:\n  before: {tail_before}\n  after:  {tail_after}"
        )

    def test_fallback_does_not_remove_most_recent(self):
        """The most recent message (index -1) is never removed by the fallback."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("OLD USER 1 " + "x" * 400)
        c.add_assistant_message("OLD ASSISTANT " + "y" * 400, [])
        c.add_user_message("MOST RECENT USER " + "z" * 400)
        c.add_assistant_message("MOST RECENT ASSISTANT " + "w" * 400, [])
        c.trim_to_token_limit(500)
        most_recent_user = c.messages[-2]
        assert "MOST RECENT USER" in most_recent_user.content
