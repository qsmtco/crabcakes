# tests/test_mcp_tool_naming.py
# Tests for MCP tool name sanitization (wire-safe namespacing).
#
# Verifies that:
# 1. _to_wire_name / _from_wire_name produce provider-safe names
# 2. get_tools_for_api emits no "/" in tool names
# 3. execute_tool routes wire-format names correctly
# 4. execute_tool rejects legacy "/" format (clean cut)

import pytest
from unittest.mock import patch, MagicMock

from utils.mcp_client import _to_wire_name, _from_wire_name, MCPToolDefinition


class TestToWireName:

    def test_basic(self):
        assert _to_wire_name("memory", "create_entities") == "memory__create_entities"

    def test_no_slash_in_output(self):
        result = _to_wire_name("fetch", "fetch_url")
        assert "/" not in result

    def test_matches_provider_pattern(self):
        import re
        result = _to_wire_name("memory", "search_nodes")
        # Must match ^[a-zA-Z0-9_-]{1,128}$
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", result), (
            f"Wire name {result!r} does not match provider pattern"
        )

    def test_empty_server(self):
        # Edge case — produces "__tool" (defensive; server names always non-empty)
        assert _to_wire_name("", "tool") == "__tool"

    def test_empty_tool(self):
        assert _to_wire_name("memory", "") == "memory__"


class TestFromWireName:

    def test_basic(self):
        assert _from_wire_name("memory__create_entities") == ("memory", "create_entities")

    def test_built_in_tool_returns_none(self):
        assert _from_wire_name("read_file") is None

    def test_empty_string_returns_none(self):
        assert _from_wire_name("") is None

    def test_double_underscore_in_tool_name(self):
        # Split on FIRST "__" only — tool name preserved intact
        assert _from_wire_name("memory__create__entities") == ("memory", "create__entities")

    def test_empty_server_returns_none(self):
        assert _from_wire_name("__tool") is None

    def test_empty_tool_returns_none(self):
        assert _from_wire_name("memory__") is None

    def test_no_separator_returns_none(self):
        assert _from_wire_name("justaname") is None

    def test_round_trip(self):
        wire = _to_wire_name("memory", "search_nodes")
        assert _from_wire_name(wire) == ("memory", "search_nodes")


class TestGetToolsForApiWireNames:
    """Verify get_tools_for_api produces provider-safe tool names."""

    def test_no_slash_in_tool_names(self):
        """get_tools_for_api must not emit "/" in any tool name."""
        from utils.mcp_client import get_tools_for_api, _conversations, _tools_cache, _MCPLoopThread

        # Mock discover_tools to return fake tool defs without actual MCP connection
        fake_tools = [
            MCPToolDefinition(
                name="create_entities",
                description="Create entities in the knowledge graph",
                parameters={"type": "object", "properties": {}},
                server_name="memory",
            ),
            MCPToolDefinition(
                name="search_nodes",
                description="Search nodes in the knowledge graph",
                parameters={"type": "object", "properties": {}},
                server_name="memory",
            ),
        ]

        # Clear state to avoid interference
        _conversations.clear()
        _tools_cache.clear()
        for k in list(_MCPLoopThread._instances.keys()):
            inst = _MCPLoopThread._instances.pop(k)
            try:
                inst.stop()
            except Exception:
                pass

        with patch("utils.mcp_client.connect"), \
             patch("utils.mcp_client.discover_tools", return_value=fake_tools):
            tools = get_tools_for_api(["memory"])

        assert len(tools) == 2
        for t in tools:
            name = t["function"]["name"]
            assert "/" not in name, f"Tool name {name!r} contains '/'"
            assert "__" in name, f"Tool name {name!r} missing wire separator"

    def test_wire_names_match_provider_pattern(self):
        """All emitted tool names must match ^[a-zA-Z0-9_-]{1,128}$."""
        import re
        from utils.mcp_client import get_tools_for_api, _conversations, _tools_cache, _MCPLoopThread

        fake_tools = [
            MCPToolDefinition(
                name="create_entities",
                description="Create entities",
                parameters={"type": "object", "properties": {}},
                server_name="memory",
            ),
        ]

        _conversations.clear()
        _tools_cache.clear()
        for k in list(_MCPLoopThread._instances.keys()):
            inst = _MCPLoopThread._instances.pop(k)
            try:
                inst.stop()
            except Exception:
                pass

        with patch("utils.mcp_client.connect"), \
             patch("utils.mcp_client.discover_tools", return_value=fake_tools):
            tools = get_tools_for_api(["memory"])

        for t in tools:
            name = t["function"]["name"]
            assert re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name), (
                f"Tool name {name!r} does not match provider pattern"
            )


class TestExecuteToolRouting:
    """Verify execute_tool routes wire-format names and rejects legacy format."""

    def test_wire_name_routes_to_mcp(self):
        """execute_tool('memory__search_nodes', ...) should route to MCP."""
        from agent.tools import execute_tool

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "search results"
        mock_result.error = None
        mock_result.duration_ms = 5

        with patch("utils.mcp_client.is_connected", return_value=True), \
             patch("utils.mcp_client.call_tool", return_value=mock_result):
            result = execute_tool(
                "memory__search_nodes",
                {"query": "test"},
                project_path="/tmp",
            )

        assert result.success is True
        assert result.output == "search results"

    def test_legacy_slash_format_rejected(self):
        """execute_tool('memory/search_nodes', ...) must return Unknown tool."""
        from agent.tools import execute_tool

        result = execute_tool(
            "memory/search_nodes",
            {"query": "test"},
            project_path="/tmp",
        )
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_built_in_tool_still_works(self):
        """execute_tool('read_file', ...) must NOT be affected by MCP routing."""
        from agent.tools import execute_tool

        # read_file on a nonexistent path returns failure but NOT "Unknown tool"
        result = execute_tool(
            "read_file",
            {"path": "/nonexistent/path/that/does/not/exist.py"},
            project_path="/tmp",
        )
        assert result.success is False
        assert "Unknown tool" not in (result.error or "")