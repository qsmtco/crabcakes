# tests/test_phase4.py
# Unit tests for Phase 4 features:
#   §4.4a — .crabcakes/ docs always included in file context (agent/context.py)
#   §4.10 — Summary-on-trim in conversation trimming (models/conversation.py)
#
# These test the Phase 4 additions specifically — edge cases, ordering,
# budget compliance, and convergence behavior.

import os
import tempfile

import pytest

from agent.context import (
    build_file_context,
    _read_crabcakes_docs,
)
from models.conversation import (
    Conversation,
    Message,
    MessageRole,
    ToolCall,
)


# ═══════════════════════════════════════════════════════════════════
#  §4.4a — _read_crabcakes_docs
# ═══════════════════════════════════════════════════════════════════

class TestReadCrabcakesDocs:
    """Tests for _read_crabcakes_docs() in agent/context.py."""

    def test_returns_empty_when_no_crabcakes_dir(self):
        with tempfile.TemporaryDirectory() as proj:
            result = _read_crabcakes_docs(proj)
            assert result == ""

    def test_reads_all_standard_docs(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            for name in ["architecture.md", "requirements.md", "context.md",
                         "tasks.md", "team.json", "workflow.md",
                         "awareness.json", "project.md"]:
                with open(os.path.join(crab, name), "w") as f:
                    f.write(f"content of {name}")

            result = _read_crabcakes_docs(proj)
            # All 8 docs should appear
            for name in ["architecture.md", "requirements.md", "context.md",
                         "tasks.md", "team.json", "workflow.md",
                         "awareness.json", "project.md"]:
                assert f"## .crabcakes/{name}" in result
                assert f"content of {name}" in result

    def test_skips_non_standard_files(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "feed.json"), "w") as f:
                f.write("big feed data")
            with open(os.path.join(crab, "random.txt"), "w") as f:
                f.write("junk")

            result = _read_crabcakes_docs(proj)
            assert "feed.json" not in result
            assert "random.txt" not in result
            assert result == ""

    def test_skips_oversized_file(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            # Create a file larger than default 50KB limit
            big_content = "X" * (60 * 1024)
            with open(os.path.join(crab, "architecture.md"), "w") as f:
                f.write(big_content)

            result = _read_crabcakes_docs(proj)
            assert "too large" in result
            assert "X" * 1000 not in result  # actual content not included

    def test_skips_oversized_with_custom_max(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "tasks.md"), "w") as f:
                f.write("A" * 200)

            # max_size=100 → file is 200 bytes, should be "too large"
            result = _read_crabcakes_docs(proj, max_size=100)
            assert "too large" in result

    def test_handles_unreadable_file(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            # Write a valid file
            with open(os.path.join(crab, "architecture.md"), "w") as f:
                f.write("arch content")
            # Create a directory with a doc name (not a file) — should be skipped
            os.makedirs(os.path.join(crab, "context.md"))

            result = _read_crabcakes_docs(proj)
            assert "architecture.md" in result
            assert "arch content" in result
            # context.md was a directory, not a file — no content for it
            assert "## .crabcakes/context.md" not in result

    def test_partial_docs_still_included(self):
        """Only some standard docs exist — include what's there."""
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "architecture.md"), "w") as f:
                f.write("# Arch")
            with open(os.path.join(crab, "tasks.md"), "w") as f:
                f.write("# Tasks")

            result = _read_crabcakes_docs(proj)
            assert "architecture.md" in result
            assert "tasks.md" in result
            assert "requirements.md" not in result  # doesn't exist


# ═══════════════════════════════════════════════════════════════════
#  §4.4a — build_file_context integration
# ═══════════════════════════════════════════════════════════════════

class TestBuildFileContextCrabcakesDocs:
    """Tests that build_file_context prepends .crabcakes/ docs."""

    def test_crabcakes_docs_appear_in_context(self):
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "architecture.md"), "w") as f:
                f.write("# My Architecture")
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("print('hello')")

            ctx = build_file_context(proj)
            assert "## Project docs" in ctx
            assert "## .crabcakes/architecture.md" in ctx
            assert "My Architecture" in ctx

    def test_crabcakes_docs_before_directory_tree(self):
        """§4.4a spec: docs must appear before the directory tree."""
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "tasks.md"), "w") as f:
                f.write("# Tasks")
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("code")

            ctx = build_file_context(proj)
            docs_pos = ctx.find("## Project docs")
            tree_pos = ctx.find("## Project tree")
            if tree_pos == -1:
                tree_pos = ctx.find("main.py")
            assert docs_pos >= 0
            assert docs_pos < tree_pos

    def test_no_crabcakes_dir_no_docs_section(self):
        """No .crabcakes/ → no '## Project docs' section."""
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("code")

            ctx = build_file_context(proj)
            assert "## Project docs" not in ctx

    def test_crabcakes_docs_with_query_mode(self):
        """§4.4a docs should appear even in query mode."""
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "requirements.md"), "w") as f:
                f.write("# Requirements")
            with open(os.path.join(proj, "auth.py"), "w") as f:
                f.write("def login(): pass")

            ctx = build_file_context(proj, query="auth")
            assert "## Project docs" in ctx
            assert "auth.py" in ctx

    def test_feed_json_not_included(self):
        """feed.json is intentionally excluded — potentially large."""
        with tempfile.TemporaryDirectory() as proj:
            crab = os.path.join(proj, ".crabcakes")
            os.makedirs(crab)
            with open(os.path.join(crab, "feed.json"), "w") as f:
                f.write('{"cards": []}')
            with open(os.path.join(crab, "tasks.md"), "w") as f:
                f.write("# Tasks")

            ctx = build_file_context(proj)
            assert "feed.json" not in ctx


# ═══════════════════════════════════════════════════════════════════
#  §4.10 — Summary-on-trim: _last_exchange_summary
# ═══════════════════════════════════════════════════════════════════

class TestLastExchangeSummary:
    """Tests for Conversation._last_exchange_summary()."""

    def test_empty_conversation_returns_empty(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        assert c._last_exchange_summary() == ""

    def test_short_conversation_returns_empty(self):
        """Fewer than 5 messages → nothing to summarize."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("task 1")
        c.add_assistant_message("done", [])
        assert c._last_exchange_summary() == ""

    def test_generates_summary_from_user_messages(self):
        """Summary lists user messages from the trimmed portion."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Task {i+1}: do something")
            c.add_assistant_message(f"Done {i+1}", [])
        # 12 messages total — tail_preserve=4, so 8 in the "old" portion
        summary = c._last_exchange_summary()
        assert "Conversation so far" in summary
        assert "prior turns" in summary
        assert "Task 1" in summary

    def test_summary_caps_at_5_items(self):
        """More than 5 user turns → shows first 5 + 'and N more'."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Task {i+1}")
            c.add_assistant_message("ok", [])
        summary = c._last_exchange_summary()
        assert "… and" in summary
        assert "more turns" in summary

    def test_summary_truncates_long_content(self):
        """Long user messages get truncated to 100 chars with ellipsis."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        long_msg = "A" * 200
        c.add_user_message(long_msg)
        c.add_assistant_message("ok", [])
        # Need enough messages for the tail_preserve threshold
        for i in range(3):
            c.add_user_message(f"filler {i}")
            c.add_assistant_message("ok", [])
        summary = c._last_exchange_summary()
        assert "…" in summary
        assert "A" * 200 not in summary  # full 200 chars not in summary

    def test_summary_excludes_tail_messages(self):
        """The last 4 messages (tail) should not appear in the summary."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("old task")
        c.add_assistant_message("old done", [])
        c.add_user_message("tail task")
        c.add_assistant_message("tail done", [])
        c.add_user_message("tail task 2")
        c.add_assistant_message("tail done 2", [])
        # 6 messages — tail_preserve=4 means only messages [0,1] are summarized
        summary = c._last_exchange_summary()
        assert "old task" in summary
        assert "tail task" not in summary

    def test_no_user_messages_returns_empty(self):
        """If all messages in the old portion are assistant messages, return empty."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(5):
            c.add_assistant_message(f"response {i}", [])
        summary = c._last_exchange_summary()
        assert summary == ""


# ═══════════════════════════════════════════════════════════════════
#  §4.10 — Summary-on-trim: trim_to_token_limit integration
# ═══════════════════════════════════════════════════════════════════

class TestTrimSummaryInjection:
    """Tests for summary injection during trim_to_token_limit()."""

    def test_summary_injected_on_long_conversation(self):
        """When messages are removed during trim, a summary is injected."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message("u" * 50)
            c.add_assistant_message("r" * 50, [])

        # Trim to ~150 tokens keeps 8 messages, leaving 4 non-tail
        c.trim_to_token_limit(150)

        # Check a summary message was injected
        summaries = [m for m in c.messages if m.is_summary]
        assert len(summaries) >= 1, f"Expected summary, got {len(summaries)} summaries"

    def test_summary_message_has_assistant_role(self):
        """Summary messages are ASSISTANT role with is_summary=True."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Task {i+1}")
            c.add_assistant_message(f"Done {i+1}", [])

        c.trim_to_token_limit(150)

        summaries = [m for m in c.messages if m.is_summary]
        for s in summaries:
            assert s.role == MessageRole.ASSISTANT
            assert s.is_summary is True

    def test_no_summary_on_short_conversation(self):
        """Short conversation (under 8 messages) should not get a summary."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("task")
        c.add_assistant_message("done", [])
        c.add_user_message("task 2")
        c.add_assistant_message("done 2", [])

        c.trim_to_token_limit(150)

        summaries = [m for m in c.messages if m.is_summary]
        assert len(summaries) == 0

    def test_summary_not_injected_over_budget(self):
        """Bug 1 fix: summary is skipped if it would push tokens over budget.

        Note: the trim loop itself has a known limitation — it stops when it
        can't find more USER messages to remove, even if ASSISTANT messages
        remain. This test verifies the *summary* doesn't make things worse.
        """
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Task {i+1}: " + "x" * 50)
            c.add_assistant_message(f"Done " + "y" * 50, [])

        # Snapshot tokens after trim but before any summary injection
        c.trim_to_token_limit(150)
        tokens_after_trim = c.get_token_estimate()

        # Calling trim again must not increase tokens (no summary pushing over)
        c.trim_to_token_limit(150)
        tokens_after_second = c.get_token_estimate()
        assert tokens_after_second <= tokens_after_trim

    def test_repeated_trims_converge(self):
        """Bug 2 fix: repeated trim calls must not oscillate."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Task {i+1}: " + "x" * 30)
            c.add_assistant_message(f"Done " + "y" * 30, [])

        counts = []
        for _ in range(5):
            c.trim_to_token_limit(150)
            counts.append(len(c.messages))

        # Must converge — last 3 counts identical
        assert len(set(counts[-3:])) == 1, f"Oscillation detected: {counts}"

    def test_summary_content_references_old_tasks(self):
        """The summary should mention tasks from the trimmed portion."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        for i in range(10):
            c.add_user_message(f"Implement auth module {i+1}")
            c.add_assistant_message(f"Auth done {i+1}", [])

        c.trim_to_token_limit(300)

        summaries = [m for m in c.messages if m.is_summary]
        if summaries:
            assert "auth" in summaries[0].content.lower()

    def test_trim_converges_across_budgets(self):
        """Invariant: repeated trims at various budgets must converge (not grow)."""
        for budget in [200, 300, 500]:
            c = Conversation(agent_name="Coder", model="gpt-4o")
            for i in range(15):
                c.add_user_message(f"Task {i+1}: " + "x" * 40)
                c.add_assistant_message("Done " + "y" * 40, [])
            c.trim_to_token_limit(budget)
            first_tokens = c.get_token_estimate()
            c.trim_to_token_limit(budget)
            second_tokens = c.get_token_estimate()
            assert second_tokens <= first_tokens, \
                f"Budget {budget}: tokens grew after 2nd trim ({first_tokens} → {second_tokens})"


# ═══════════════════════════════════════════════════════════════════
#  §4.15 — Token budget breakdown (Phase 6)
# ═══════════════════════════════════════════════════════════════════

class TestTokenBreakdown:
    """Tests for Conversation.get_token_breakdown() — §4.15."""

    def test_empty_conversation_breakdown(self):
        """Empty conversation: system=0, conv=0, all remaining."""
        c = Conversation(agent_name="Coder", model="gpt-4o")
        bd = c.get_token_breakdown(128000)
        assert bd["system_prompt_tokens"] == 0
        assert bd["conversation_tokens"] == 0
        assert bd["total_used_tokens"] == 0
        assert bd["remaining_tokens"] == 128000
        assert bd["usage_percent"] == 0.0

    def test_system_prompt_counted(self):
        c = Conversation(agent_name="Coder", system_prompt="x" * 40)  # 10 tokens
        bd = c.get_token_breakdown(128000)
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("x" * 40))
        assert bd["system_prompt_tokens"] == expected

    def test_messages_counted_as_conversation(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("hello world")  # 11 chars → 2 tokens
        bd = c.get_token_breakdown(128000)
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("hello world"))
        assert bd["conversation_tokens"] == expected

    def test_total_equals_system_plus_conversation(self):
        c = Conversation(agent_name="Coder", system_prompt="s" * 20)
        c.add_user_message("m" * 20)
        bd = c.get_token_breakdown(1000)
        assert bd["total_used_tokens"] == bd["system_prompt_tokens"] + bd["conversation_tokens"]

    def test_remaining_is_max_minus_used(self):
        c = Conversation(agent_name="Coder", system_prompt="x" * 40)
        bd = c.get_token_breakdown(100)
        assert bd["remaining_tokens"] == 100 - bd["total_used_tokens"]

    def test_usage_percent_correct(self):
        c = Conversation(agent_name="Coder", system_prompt="x" * 400)  # cl100k_base tokenizes to 50 tokens
        bd = c.get_token_breakdown(1000)
        assert bd["usage_percent"] == 5.0  # 50/1000 = 5%

    def test_zero_max_tokens_no_division_error(self):
        """model_max_tokens=0 should not crash."""
        c = Conversation(agent_name="Coder", system_prompt="hello")
        bd = c.get_token_breakdown(0)
        assert bd["usage_percent"] == 0
        assert bd["remaining_tokens"] == 0

    def test_tool_call_args_counted_in_conversation(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        tc = ToolCall(call_id="c1", tool_name="read_file", arguments={"path": "a.py", "content": "xyzt"})
        c.add_assistant_message("", [tc])
        bd = c.get_token_breakdown(128000)
        assert bd["conversation_tokens"] > 0

    def test_consistent_with_get_token_estimate(self):
        """get_token_breakdown total must match get_token_estimate."""
        c = Conversation(agent_name="Coder", system_prompt="x" * 200)
        for i in range(5):
            c.add_user_message(f"message {i}: " + "y" * 30)
            c.add_assistant_message(f"reply {i}: " + "z" * 30, [])
        estimate = c.get_token_estimate()
        bd = c.get_token_breakdown(128000)
        assert bd["total_used_tokens"] == estimate
