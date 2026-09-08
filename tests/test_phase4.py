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
