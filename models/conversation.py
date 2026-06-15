import json
# models/conversation.py
# Conversation and Message data models for the agent runtime.
#
# Manifest: reads nothing, writes nothing, no network.
# Architecture: pure data — no GTK, no network, no LLM calls.
# All imports are stdlib only (dataclasses, datetime, enum, typing).
#
# Files that import these:
#   - agent/runtime.py (owns Conversation instances)
#   - agent/context.py (reads Conversation for context building)
#   - tests/test_conversation.py (unit tests)

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable


# ── Enums ─────────────────────────────────────────────────────────────────────


class MessageRole(str, Enum):
    """Role of a message in a conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool"


class ToolCallStatus(str, Enum):
    """Lifecycle stage of a tool call."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A single tool invocation from an assistant message."""
    call_id: str                          # unique identifier (e.g. "call_abc123")
    tool_name: str                        # e.g. "read_file", "exec_command"
    arguments: dict                       # parsed JSON arguments as dict
    result: str | None = None            # tool execution result text
    status: ToolCallStatus = ToolCallStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_executing(self) -> None:
        self.status = ToolCallStatus.EXECUTING
        self.started_at = datetime.now()

    def mark_completed(self, result: str) -> None:
        self.status = ToolCallStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now()

    def mark_failed(self, error: str) -> None:
        self.status = ToolCallStatus.FAILED
        self.result = error
        self.completed_at = datetime.now()


@dataclass
class Message:
    """A single turn in a conversation."""
    role: MessageRole
    content: str                          # empty string for tool-call messages
    tool_calls: list[ToolCall] = field(default_factory=list)   # non-empty only for assistant messages
    tool_call_id: str | None = None      # non-None only for tool-result messages
    timestamp: datetime = field(default_factory=datetime.now)
    tokens_used: int = 0                 # tokens consumed by this message
    is_summary: bool = False             # True for injected summary-on-trim messages

    @property
    def is_tool_call(self) -> bool:
        """True if this is an assistant message that triggered tool calls."""
        return self.role == MessageRole.ASSISTANT and bool(self.tool_calls)

    @property
    def is_tool_result(self) -> bool:
        """True if this is a tool-result message."""
        return self.role == MessageRole.TOOL_RESULT


@dataclass
class Conversation:
    """Full conversation state for a single agent tab.

    The session_key (not stored here) is the lookup key used by AgentRuntime.
    This dataclass holds everything that persists across turns.
    """
    agent_name: str
    project_path: str | None = None
    allowed_tools: list[str] | None = None  # filtered tool set — None means all tools
    mcp_servers: list[str] = field(default_factory=list)  # MCP servers for this conversation
    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    model: str = ""                      # e.g. "openai/gpt-4o"
    api_key: str | None = None           # per-agent API key override (from agent def)
    si_enforcement: bool | None = None     # per-agent enforcement override (None → use global)
    app_title: str = ""                   # OpenRouter X-Title header value (e.g. "Coder:Crabcakes")
    fallback_provider: str | None = None   # KB fallback provider (from agent def)
    fallback_model: str | None = None      # KB fallback model (from agent def)
    created_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    total_cost: float = 0.0              # cumulative USD cost
    step_count: int = 0                  # number of complete agent turns

    # ── Message helpers ───────────────────────────────────────────────────────

    def add_user_message(self, content: str) -> Message:
        """Add a user (PM) message and return it."""
        msg = Message(role=MessageRole.USER, content=content)
        self.messages.append(msg)
        return msg

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> Message:
        """Add an assistant message and return it."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls or [],
        )
        self.messages.append(msg)
        self.step_count += 1
        return msg

    def add_tool_result(self, call_id: str, result: str) -> Message:
        """Add a tool-result message and return it."""
        msg = Message(
            role=MessageRole.TOOL_RESULT,
            content=result,
            tool_call_id=call_id,
        )
        self.messages.append(msg)
        return msg

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_api_messages(self) -> list[dict]:
        """
        Serialize conversation to LLM API format.

        Returns:
            [{"role": "system", "content": "..."},
             {"role": "user", "content": "..."},
             {"role": "assistant", "content": "text", "tool_calls": [...]},
             {"role": "tool", "tool_call_id": "...", "content": "..."},
             ...]

        Rules:
        - System prompt becomes the first system message
        - Tool calls from assistant messages are serialized as OpenAI-style dicts
        - Tool results use tool_call_id to link back
        """
        result: list[dict] = []

        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})

        for msg in self.messages:
            if msg.role == MessageRole.USER:
                result.append({"role": "user", "content": msg.content})

            elif msg.role == MessageRole.ASSISTANT:
                entry: dict = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)

            elif msg.role == MessageRole.TOOL_RESULT:
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })

        return result

    # ── Token management ───────────────────────────────────────────────────────

    def _count_char_tokens(self) -> tuple[int, int]:
        """Return (system_prompt_chars, conversation_chars) for token estimation."""
        system_chars = len(self.system_prompt)
        conv_chars = 0
        for msg in self.messages:
            conv_chars += len(msg.content)
            for tc in msg.tool_calls:
                conv_chars += len(str(tc.arguments))
                if tc.result:
                    conv_chars += len(tc.result)
        return system_chars, conv_chars

    def get_token_estimate(self) -> int:
        """
        Rough token count estimate (~4 chars per token).

        Used for context-window management. Not accurate — overestimates
        for non-English text and underestimates for code-heavy content.
        """
        system_chars, conv_chars = self._count_char_tokens()
        return (system_chars + conv_chars) // 4

    def get_token_breakdown(self, model_max_tokens: int) -> dict:
        """
        §4.15 — Per-turn token budget breakdown.

        Returns a dict with token allocation info for observability:
        - system_prompt_tokens: chars in system_prompt // 4
        - conversation_tokens: chars in all messages // 4
        - total_used_tokens: system + conversation
        - model_max_tokens: total available context window
        - remaining_tokens: model_max - total_used
        - usage_percent: (total_used / model_max_tokens) * 100

        This helps identify context bloat before hitting the limit.
        """
        system_chars, conv_chars = self._count_char_tokens()
        system_tokens = system_chars // 4
        conversation_tokens = conv_chars // 4
        total_used = system_tokens + conversation_tokens
        return {
            "system_prompt_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "total_used_tokens": total_used,
            "model_max_tokens": model_max_tokens,
            "remaining_tokens": max(0, model_max_tokens - total_used),
            "usage_percent": round(total_used / model_max_tokens * 100, 1) if model_max_tokens > 0 else 0,
        }

    def trim_to_token_limit(self, max_tokens: int) -> None:
        """
        Trim oldest messages to stay under token limit.

        Keeps:
        - The system prompt (never removed — stored separately in Conversation)
        - The most recent exchange intact (user + assistant + optional tool_result
          + final assistant)

        Tool call/result pairs are removed together as a unit. Only removes when
        at least one full user→assistant exchange can be preserved.

        §4.10 (Summary on trim): After trimming, if the conversation is long
        enough (8+ messages remaining), a compact summary of the trimmed user
        messages is injected as an assistant message before the preserved tail.
        This prevents the model from losing context of what was accomplished in
        the removed exchanges.
        """
        while self.get_token_estimate() > max_tokens and len(self.messages) > 4:
            removed = False
            # Iterate backwards to avoid index shift issues when popping
            for i in range(len(self.messages) - 1, 0, -1):
                msg = self.messages[i]
                # If this is a TOOL_RESULT, also remove the preceding ASSISTANT with tool_calls
                if msg.role == MessageRole.TOOL_RESULT:
                    if i > 0 and self.messages[i-1].role == MessageRole.ASSISTANT and self.messages[i-1].tool_calls:
                        # Remove TOOL_RESULT (i) first, then ASSISTANT (i-1)
                        self.messages.pop(i)
                        self.messages.pop(i - 1)
                        removed = True
                        break
                # If this is an ASSISTANT with tool_calls, also remove the following TOOL_RESULT
                elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                    if i + 1 < len(self.messages) and self.messages[i+1].role == MessageRole.TOOL_RESULT:
                        # Remove TOOL_RESULT (i+1) first, then ASSISTANT (i)
                        self.messages.pop(i + 1)
                        self.messages.pop(i)
                        removed = True
                        break
            if not removed:
                # Fallback: remove oldest user message + its following assistant
                for i in range(1, len(self.messages) - 1):
                    if self.messages[i].role == MessageRole.USER:
                        self.messages.pop(i)
                        break
                else:
                    break

        # §4.10: Inject summary when old messages are removed so the model
        # doesn't lose context of what was accomplished in the trimmed turns.
        # Only fires when the conversation is long enough that meaningful work
        # was trimmed (8+ messages, enough room for both a summary and a tail).
        if len(self.messages) >= 8:
            summary = self._last_exchange_summary()
            if summary:
                # Bug 1 fix: skip injection if it would push us back over the budget.
                summary_tokens = len(summary) // 4
                current_tokens = self.get_token_estimate()
                if current_tokens + summary_tokens > max_tokens:
                    return  # skip — injecting would exceed budget
                # Inject summary as an assistant message right before the preserved tail
                # (at index len-4, before the "always keep" last-4 messages).
                summary_msg = Message(role=MessageRole.ASSISTANT, content=summary, is_summary=True)
                insert_at = max(1, len(self.messages) - 4)
                self.messages.insert(insert_at, summary_msg)

    def _last_exchange_summary(self) -> str:
        """
        Generate a summary of the oldest trimmed user messages.

        Called after trim_to_token_limit removes old exchanges.
        The summary is injected as an assistant message before the preserved
        tail so the model doesn't lose context of what was accomplished.

        Returns empty string when the conversation is too short to summarize
        meaningfully (< 4 messages) or when no user messages remain to capture.
        """
        if not self.messages:
            return ""

        # Collect user message content from the trimmed portion of the conversation.
        # The ``tail_preserve`` messages (last 4: user + assistant + tool_result + assistant)
        # are excluded so the summary only covers the part that was actually removed.
        tail_preserve = 4
        if len(self.messages) <= tail_preserve:
            return ""

        user_contents: list[str] = []
        for msg in self.messages[:-tail_preserve]:
            if msg.role == MessageRole.USER:
                user_contents.append(msg.content.strip())

        if not user_contents:
            return ""

        lines = [f"Conversation so far ({len(user_contents)} prior turns):"]
        for i, content in enumerate(user_contents[:5], 1):
            preview = content[:100] + ("…" if len(content) > 100 else "")
            lines.append(f"  {i}. {preview}")
        if len(user_contents) > 5:
            lines.append(f"  … and {len(user_contents) - 5} more turns")

        return "\n".join(lines)

    # ── Cost tracking ─────────────────────────────────────────────────────────

    def record_usage(self, tokens: int, cost: float) -> None:
        """Record tokens used and cost for a single LLM call."""
        self.total_tokens += tokens
        self.total_cost += cost
        if self.messages:
            self.messages[-1].tokens_used = tokens
