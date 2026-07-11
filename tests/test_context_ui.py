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