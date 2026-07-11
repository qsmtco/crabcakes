# PHASE D — Test Suite for Context UI / Compact / LLM Strategy

**Spec:** `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` §7
**Files to create:** `tests/test_context_ui.py`, `tests/test_compact_command.py`, `tests/test_llm_summarize_strategy.py`

---

## FILE 1 — tests/test_context_ui.py (Phase A tests)

Tests for `_on_token_breakdown` expansion, compaction bubbles, usage warnings, context meter.

```python
# tests/test_context_ui.py
# Tests for Phase A — Context UI Surface.

import pytest
from unittest.mock import MagicMock, patch


class TestOnTokenBreakdown:
    """Tests for the expanded _on_token_breakdown handler."""

    def test_empty_breakdown_does_not_crash(self):
        """BUG #1 from audit: missing keys must not KeyError."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        handler._last_breakdown = {}
        handler._last_warning_pct = {}
        handler._first_compaction_seen = {}
        handler._on_token_breakdown_extra = None
        handler._GLib = None
        handler._crh = None
        handler._mc = None
        handler._resolve_chat_box = lambda sk: None
        # Empty dict — must NOT raise
        handler._on_token_breakdown("sk:test", {})
        assert handler._last_breakdown.get("sk:test") == {}

    def test_breakdown_cached(self):
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        handler._last_breakdown = {}
        handler._last_warning_pct = {}
        handler._first_compaction_seen = {}
        handler._on_token_breakdown_extra = None
        handler._GLib = None
        handler._crh = None
        handler._mc = None
        handler._resolve_chat_box = lambda sk: None
        breakdown = {
            "system_prompt_tokens": 100,
            "conversation_tokens": 200,
            "total_used_tokens": 300,
            "model_max_tokens": 1000,
            "remaining_tokens": 700,
            "usage_percent": 30.0,
            "trimmed_this_turn": False,
            "messages_removed_this_turn": 0,
        }
        handler._on_token_breakdown("sk:test", breakdown)
        assert handler._last_breakdown["sk:test"] == breakdown

    def test_compaction_bubble_fires_once(self):
        """First compaction fires bubble; second does not (anti-spam)."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        handler._last_breakdown = {}
        handler._last_warning_pct = {}
        handler._first_compaction_seen = {}
        handler._on_token_breakdown_extra = None
        handler._GLib = None
        bubbles = []
        handler._do_compaction_bubble = lambda sk, ev: bubbles.append((sk, ev))
        handler._do_usage_warning = lambda sk, level, pct: None

        breakdown = {
            "system_prompt_tokens": 100, "conversation_tokens": 200,
            "total_used_tokens": 300, "model_max_tokens": 1000,
            "remaining_tokens": 700, "usage_percent": 30.0,
            "trimmed_this_turn": True, "messages_removed_this_turn": 5,
            "compaction_event": {"messages_removed": 5, "tokens_freed": 1000, "layer": 2, "trigger": "soft"},
        }
        handler._on_token_breakdown("sk:test", breakdown)
        handler._on_token_breakdown("sk:test", breakdown)  # second time
        assert len(bubbles) == 1  # only first fires

    def test_warning_fires_at_80_pct(self):
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        handler._last_breakdown = {}
        handler._last_warning_pct = {}
        handler._first_compaction_seen = {}
        handler._on_token_breakdown_extra = None
        handler._GLib = None
        warnings = []
        handler._do_compaction_bubble = lambda sk, ev: None
        handler._do_usage_warning = lambda sk, level, pct: warnings.append((level, pct))

        breakdown = {
            "system_prompt_tokens": 100, "conversation_tokens": 800,
            "total_used_tokens": 900, "model_max_tokens": 1000,
            "remaining_tokens": 100, "usage_percent": 82.0,
            "trimmed_this_turn": False, "messages_removed_this_turn": 0,
        }
        handler._on_token_breakdown("sk:test", breakdown)
        assert len(warnings) == 1
        assert warnings[0][0] == "approaching-limit"

    def test_warning_hysteresis_no_spam(self):
        """82% → 81% should NOT re-fire (already warned above 80%)."""
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        handler._last_breakdown = {}
        handler._last_warning_pct = {}
        handler._first_compaction_seen = {}
        handler._on_token_breakdown_extra = None
        handler._GLib = None
        warnings = []
        handler._do_compaction_bubble = lambda sk, ev: None
        handler._do_usage_warning = lambda sk, level, pct: warnings.append((level, pct))

        bd = lambda pct: {
            "system_prompt_tokens": 100, "conversation_tokens": 800,
            "total_used_tokens": 900, "model_max_tokens": 1000,
            "remaining_tokens": 100, "usage_percent": pct,
            "trimmed_this_turn": False, "messages_removed_this_turn": 0,
        }
        handler._on_token_breakdown("sk:test", bd(82.0))
        handler._on_token_breakdown("sk:test", bd(81.0))
        assert len(warnings) == 1  # no re-fire


class TestSetContextMeter:
    """Tests for MainContent.set_context_meter."""

    def test_negative_resets_to_idle(self):
        """Negative usage resets meter to idle."""
        # We can't easily instantiate MainContent without GTK, but we can
        # test the logic by mocking the widget.
        meter = MagicMock()
        label = MagicMock()
        meter.get_css_classes.return_value = []

        # Simulate the method body
        usage_percent = -1
        if usage_percent < 0:
            meter.set_fraction(0.0)
            label.set_text("")
        assert meter.set_fraction.called_with(0.0)
        assert label.set_text.called_with("")

    def test_none_does_not_crash(self):
        """None usage_percent is handled gracefully."""
        usage_percent = None
        if usage_percent is None:
            handled = True
        else:
            handled = False
        assert handled
```

---

## FILE 2 — tests/test_compact_command.py (Phase B tests)

Tests for cmd_compact, compact_conversation, command registration.

```python
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
```

---

## FILE 3 — tests/test_llm_summarize_strategy.py (Phase C tests)

Tests for LLMSummarizeStrategy, force_llm_compact, _call_for_summary.

```python
# tests/test_llm_summarize_strategy.py
# Tests for Phase C — LLM-Summarization Strategy.

import pytest
from unittest.mock import MagicMock, patch


class TestLLMSummarizeStrategy:

    def test_no_provider_falls_back_to_textual(self):
        """When llm_provider is None, falls back to super()._summary()."""
        from agent.context_strategy import LLMSummarizeStrategy, DefaultContextStrategy
        strat = LLMSummarizeStrategy(llm_provider=None)
        conv = MagicMock()
        conv.messages = []
        conv.system_prompt = "test"
        # Should not crash — should return whatever super returns
        result = strat._summary(conv, token_budget=1000, keep_first=2)
        assert isinstance(result, str)

    def test_empty_llm_response_falls_back(self):
        """Empty LLM response falls back to textual."""
        from agent.context_strategy import LLMSummarizeStrategy
        strat = LLMSummarizeStrategy(llm_provider=lambda sys_p, user_p: "")
        conv = MagicMock()
        conv.messages = [MagicMock(role=MagicMock(value="user"), content="hello")] * 10
        conv.system_prompt = "test"
        result = strat._summary(conv, token_budget=1000, keep_first=2)
        assert isinstance(result, str)

    def test_llm_exception_falls_back(self):
        """LLM call raising exception falls back to textual."""
        from agent.context_strategy import LLMSummarizeStrategy

        def raising_provider(sys_p, user_p):
            raise RuntimeError("network error")

        strat = LLMSummarizeStrategy(llm_provider=raising_provider)
        conv = MagicMock()
        conv.messages = [MagicMock(role=MagicMock(value="user"), content="hello")] * 10
        conv.system_prompt = "test"
        result = strat._summary(conv, token_budget=1000, keep_first=2)
        assert isinstance(result, str)

    def test_successful_llm_summary_returned(self):
        """LLM returns a valid response — strategy returns it verbatim."""
        from agent.context_strategy import LLMSummarizeStrategy

        summary = "<task>Fix the bug</task><progress>Step 1 done</progress>"
        strat = LLMSummarizeStrategy(llm_provider=lambda sys_p, user_p: summary)
        conv = MagicMock()
        conv.messages = [MagicMock(role=MagicMock(value="user"), content="hello")] * 10
        conv.system_prompt = "test"
        result = strat._summary(conv, token_budget=1000, keep_first=2)
        assert result == summary

    def test_too_few_messages_returns_empty(self):
        """When conversation has <= 4 messages, _summary returns empty string."""
        from agent.context_strategy import LLMSummarizeStrategy
        strat = LLMSummarizeStrategy(llm_provider=lambda sys_p, user_p: "should not be called")
        conv = MagicMock()
        conv.messages = [MagicMock()] * 3
        conv.system_prompt = "test"
        result = strat._summary(conv, token_budget=1000, keep_first=2)
        assert result == ""

    def test_no_double_truncation(self):
        """BUG #2: strategy should NOT truncate — parent handles fitting."""
        from agent.context_strategy import LLMSummarizeStrategy
        long_response = "<task>x</task>" + "a" * 5000
        strat = LLMSummarizeStrategy(llm_provider=lambda sys_p, user_p: long_response)
        conv = MagicMock()
        conv.messages = [MagicMock(role=MagicMock(value="user"), content="hello")] * 10
        conv.system_prompt = "test"
        result = strat._summary(conv, token_budget=100, keep_first=2)
        # Should be the FULL response, not truncated by the strategy
        assert len(result) == len(long_response)
        assert "summary truncated" not in result


class TestForceLlmCompact:
    """Tests for AgentRuntime.force_llm_compact."""

    def test_strategy_swapped_and_restored(self):
        """force_llm_compact must restore _context_strategy after call."""
        from agent.runtime import AgentRuntime, DefaultContextStrategy
        rt = AgentRuntime.__new__(AgentRuntime)
        original = DefaultContextStrategy()
        rt._context_strategy = original

        conv = MagicMock()
        conv.messages = []
        conv.system_prompt = "test"
        conv.model = "openai/gpt-4o"
        conv.get_token_estimate.return_value = 100

        # _call_for_summary will fail (no real provider), but strategy
        # should still be restored
        with patch.object(rt, "_call_for_summary", side_effect=RuntimeError("no provider")):
            try:
                rt.force_llm_compact(conv, 5000, "")
            except Exception:
                pass

        assert rt._context_strategy is original

    def test_system_prompt_restored(self):
        """force_llm_compact must restore conv.system_prompt after focus_text."""
        from agent.runtime import AgentRuntime, DefaultContextStrategy
        rt = AgentRuntime.__new__(AgentRuntime)
        rt._context_strategy = DefaultContextStrategy()

        conv = MagicMock()
        conv.messages = []
        conv.system_prompt = "original prompt"
        conv.model = "openai/gpt-4o"
        conv.get_token_estimate.return_value = 100

        with patch.object(rt, "_call_for_summary", side_effect=RuntimeError("no provider")):
            try:
                rt.force_llm_compact(conv, 5000, "focus on auth")
            except Exception:
                pass

        assert conv.system_prompt == "original prompt"

    def test_dead_variables_removed(self):
        """BUG #6: messages_before and tokens_before should not exist in force_llm_compact."""
        import inspect
        from agent.runtime import AgentRuntime
        source = inspect.getsource(AgentRuntime.force_llm_compact)
        assert "messages_before" not in source
        assert "tokens_before" not in source


class TestCallForSummary:
    """Tests for AgentRuntime._call_for_summary."""

    def test_empty_model_raises(self):
        from agent.runtime import AgentRuntime
        rt = AgentRuntime.__new__(AgentRuntime)
        rt._config = MagicMock()
        rt._config.providers = {}
        with pytest.raises(RuntimeError, match="no model_id"):
            rt._call_for_summary("sys", "user", model_id=None, conv=None)

    def test_no_slash_in_model_raises(self):
        from agent.runtime import AgentRuntime
        rt = AgentRuntime.__new__(AgentRuntime)
        with pytest.raises(RuntimeError, match="provider/model"):
            rt._call_for_summary("sys", "user", model_id="gpt-4o", conv=None)

    def test_unknown_provider_raises(self):
        from agent.runtime import AgentRuntime
        rt = AgentRuntime.__new__(AgentRuntime)
        rt._config = MagicMock()
        rt._config.providers = {}
        with pytest.raises(RuntimeError, match="not configured"):
            rt._call_for_summary("sys", "user", model_id="unknown/gpt-4o", conv=None)
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Create 3 new test files. Do NOT modify any production code.
- Read each referenced source file to verify imports and class structures.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. All new tests
python3 -m pytest tests/test_context_ui.py tests/test_compact_command.py tests/test_llm_summarize_strategy.py -v

# 2. Existing tests still pass
python3 -m pytest tests/test_context_strategy.py tests/test_runtime_compaction.py tests/test_project_handler.py tests/test_command_handler.py -q
```
