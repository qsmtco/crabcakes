# tests/test_mcp_client.py
# Tests for utils/mcp_client.py — MCP client library.
#
# Tests mock at the SDK boundary (stdio_client, ClientSession) but exercise
# the real _MCPLoopThread, real event loop, and real submit() path.

import asyncio
import pytest
import threading
import time
from unittest.mock import patch, MagicMock, AsyncMock
from utils.mcp_client import (
    MCPToolDefinition,
    MCPToolResult,
    is_connected,
    get_connected_servers,
    connect,
    disconnect,
    disconnect_all,
    discover_tools,
    call_tool,
    connect_servers,
    get_tools_for_api,
    _conversations,
    _state_lock,
    _MCPLoopThread,
)
from utils.mcp_config import _clear_cache


class TestState:
    """Base class: clears all state between tests."""
    def setup_method(self):
        with _state_lock:
            _conversations.clear()
        _MCPLoopThread._instances.clear()
        _clear_cache()

    def teardown_method(self):
        with _state_lock:
            _conversations.clear()
        # Stop any running loop threads
        for key in list(_MCPLoopThread._instances.keys()):
            instance = _MCPLoopThread._instances.pop(key)
            instance._stopping = True
            instance._drain_and_stop()


# ── Unit Tests (no async bridge) ─────────────────────────────────────────────


class TestIsConnected(TestState):
    def test_false_when_not_connected(self):
        assert is_connected(None, "fetch") is False

    def test_true_when_connected(self):
        with _state_lock:
            _conversations[("_default", "fetch")] = {"session": MagicMock()}
        assert is_connected(None, "fetch") is True


class TestGetConnectedServers(TestState):
    def test_empty_when_not_connected(self):
        assert get_connected_servers() == []

    def test_returns_server_names(self):
        with _state_lock:
            _conversations[("_default", "one")] = {"session": MagicMock()}
            _conversations[("_default", "two")] = {"session": MagicMock()}
        result = get_connected_servers()
        assert "one" in result
        assert "two" in result

    def test_filters_by_conversation(self):
        with _state_lock:
            _conversations[("_default", "a")] = {"session": MagicMock()}
            _conversations[("conv-1", "b")] = {"session": MagicMock()}
        assert get_connected_servers() == ["a"]
        assert get_connected_servers("conv-1") == ["b"]


class TestDisconnect(TestState):
    def test_no_op_if_not_connected(self):
        disconnect("fetch")  # Should not raise

    def test_no_op_for_unknown_conversation(self):
        disconnect("fetch", "conv-123")

    def test_removes_connection(self):
        mock_conn = {"session": MagicMock(), "stdio_cm": None, "session_cm": None}
        with _state_lock:
            _conversations[("_default", "fetch")] = mock_conn
        disconnect("fetch")
        assert is_connected(None, "fetch") is False


class TestDisconnectAll(TestState):
    def test_no_op_when_empty(self):
        disconnect_all()

    def test_disconnects_all_for_conversation(self):
        with _state_lock:
            _conversations[("_default", "one")] = {"session": MagicMock()}
            _conversations[("_default", "two")] = {"session": MagicMock()}
            _conversations[("other", "three")] = {"session": MagicMock()}
        disconnect_all()
        assert is_connected(None, "one") is False
        assert is_connected(None, "two") is False
        assert is_connected("other", "three") is True


class TestDiscoverToolsNotConnected(TestState):
    def test_raises_if_not_connected(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            discover_tools("fetch")


class TestCallToolNotConnected(TestState):
    def test_raises_if_not_connected(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            call_tool("fetch", "fetch", {"url": "http://example.com"})


class TestGetToolsForApi(TestState):
    def test_returns_empty_list_when_no_servers(self):
        result = get_tools_for_api([])
        assert result == []


class TestConnectServers(TestState):
    def test_returns_error_for_bad_server(self):
        result = connect_servers(["nonexistent"])
        assert "nonexistent" in result
        assert result["nonexistent"] != ""


# ── Loop Thread Tests (real async bridge) ─────────────────────────────────────


class TestMCPLoopThread(TestState):
    """Tests that exercise the real _MCPLoopThread with a real event loop."""

    def test_starts_and_stops(self):
        thread = _MCPLoopThread("test-start-stop")
        thread.start()
        assert thread._ready.wait(timeout=5)
        assert thread._loop is not None
        thread._drain_and_stop()
        thread.join(timeout=5)
        assert not thread.is_alive()

    def test_submit_runs_coroutine(self):
        thread = _MCPLoopThread("test-submit")
        thread.start()

        async def simple():
            return 42

        result = thread.submit(simple())
        assert result == 42
        thread._drain_and_stop()
        thread.join(timeout=5)

    def test_submit_tracks_pending(self):
        thread = _MCPLoopThread("test-pending")
        thread.start()

        # Verify initial state
        assert thread._pending_count == 0
        assert thread._pending_zero.is_set()

        async def slow():
            await asyncio.sleep(0.1)
            return "done"

        # submit increments pending, then decrements when done
        result = thread.submit(slow())
        assert result == "done"
        assert thread._pending_count == 0
        assert thread._pending_zero.is_set()
        thread._drain_and_stop()
        thread.join(timeout=5)

    def test_submit_raises_on_shutdown(self):
        thread = _MCPLoopThread("test-shutdown-reject")
        thread.start()
        thread._stopping = True
        with pytest.raises(RuntimeError, match="shutting down"):
            thread.submit(asyncio.sleep(0))
        thread._drain_and_stop()
        thread.join(timeout=5)

    def test_drain_waits_for_pending(self):
        thread = _MCPLoopThread("test-drain")
        thread.start()

        completed = threading.Event()
        async def slow_op():
            await asyncio.sleep(0.3)
            completed.set()
            return "done"

        # Submit a slow operation
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(thread.submit, slow_op())
            # Start drain while operation is running
            time.sleep(0.05)
            thread._stopping = True
            # _pending_zero should NOT be set yet
            assert not thread._pending_zero.is_set()
        # Now call drain_and_stop - should wait for the slow op
        thread._drain_and_stop()
        thread.join(timeout=5)
        assert completed.is_set()


class TestConnectWithMockedSDK(TestState):
    """Tests that mock at the SDK boundary but use real _MCPLoopThread."""

    def _mock_connect_async(self, config):
        """Fake _connect_async that returns a conn dict without real SDK."""
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(
            tools=[MagicMock(description="Fetch URL", inputSchema={"type": "object"})]
        ))
        mock_session.list_tools.return_value.tools[0].name = "fetch"
        mock_session.call_tool = AsyncMock(return_value=MagicMock(
            content=[MagicMock(text="# Hello")]
        ))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_stdio_cm = MagicMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)

        return {
            "session": mock_session,
            "stdio_cm": mock_stdio_cm,
            "session_cm": mock_session,
        }

    @patch("utils.mcp_client.get_server_config")
    def test_connect_stores_conn_dict(self, mock_get_config):
        mock_get_config.return_value = MagicMock(enabled=True)
        with patch("utils.mcp_client._connect_async", side_effect=self._mock_connect_async):
            connect("fetch")
        assert is_connected(None, "fetch") is True
        with _state_lock:
            conn = _conversations[("_default", "fetch")]
        assert "session" in conn
        assert "stdio_cm" in conn
        assert "session_cm" in conn
        disconnect("fetch")

    @patch("utils.mcp_client.get_server_config")
    def test_discover_tools_returns_definitions(self, mock_get_config):
        mock_get_config.return_value = MagicMock(enabled=True)
        with patch("utils.mcp_client._connect_async", side_effect=self._mock_connect_async):
            connect("fetch")
            tools = discover_tools("fetch")
        assert len(tools) == 1
        assert tools[0].name == "fetch"
        assert tools[0].server_name == "fetch"
        disconnect("fetch")

    @patch("utils.mcp_client.get_server_config")
    def test_call_tool_returns_result(self, mock_get_config):
        mock_get_config.return_value = MagicMock(enabled=True)
        with patch("utils.mcp_client._connect_async", side_effect=self._mock_connect_async):
            connect("fetch")
            result = call_tool("fetch", "fetch", {"url": "http://example.com"})
        assert result.success is True
        assert result.output == "# Hello"
        disconnect("fetch")

    @patch("utils.mcp_client.get_server_config")
    def test_full_lifecycle(self, mock_get_config):
        """Connect → discover → call → disconnect — full path."""
        mock_get_config.return_value = MagicMock(enabled=True)
        with patch("utils.mcp_client._connect_async", side_effect=self._mock_connect_async):
            connect("fetch")
            tools = discover_tools("fetch")
            assert len(tools) == 1
            result = call_tool("fetch", "fetch", {"url": "http://example.com"})
            assert result.success
            disconnect("fetch")
        assert is_connected(None, "fetch") is False

    @patch("utils.mcp_client.get_server_config")
    def test_connect_rejects_duplicate(self, mock_get_config):
        mock_get_config.return_value = MagicMock(enabled=True)
        with patch("utils.mcp_client._connect_async", side_effect=self._mock_connect_async):
            connect("fetch")
            with pytest.raises(RuntimeError, match="Already connected"):
                connect("fetch")
            disconnect("fetch")

    def test_connect_raises_if_server_not_found(self):
        with pytest.raises(FileNotFoundError):
            connect("nonexistent")
