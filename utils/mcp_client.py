# utils/mcp_client.py
# MCP client library for stdio transport with persistent event loop.
#
# Manifest: Persistent connection model with thread-safe access.
# Uses background thread with persistent event loop per (conversation, server).
#
# Architecture: utils/ is pure Python, no GTK.

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

from utils.mcp_config import (
    MCPServerConfig,
    get_server_config,
    MCPConfigError,
)

logger = logging.getLogger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class MCPToolDefinition:
    name: str
    description: str
    parameters: dict
    server_name: str


@dataclass
class MCPToolResult:
    success: bool
    output: str = ""
    error: str | None = None
    duration_ms: int = 0


# ── Connection State ────────────────────────────────────────────────────────


# Per-conversation, per-server sessions
# Key: (conversation_key, server_name) -> dict with 'session', 'stdio_cm', 'session_cm'
_conversations: dict[tuple[str, str], dict[str, Any]] = {}

# Tool definition cache: (conversation_key, server_name) -> list of tool dicts
_tools_cache: dict[tuple[str, str], list[dict]] = {}
_tools_cache_lock = threading.Lock()

# Lock for thread-safe access
_state_lock = threading.Lock()


def _make_conversation_key(conversation_key: str | None, server_name: str) -> tuple:
    """Make a conversation key."""
    return (conversation_key or "_default", server_name)


def is_connected(conversation_key: str | None, server_name: str) -> bool:
    """Check if server is fully connected (not still connecting) for a conversation."""
    key = _make_conversation_key(conversation_key, server_name)
    with _state_lock:
        if key not in _conversations:
            return False
        # Sentinel means connection is in progress — treat as not yet connected
        return not _is_connection_future(_conversations[key])


def get_connected_servers(conversation_key: str | None = None) -> list[str]:
    """Get list of connected server names for a conversation."""
    prefix = (conversation_key or "_default",)
    with _state_lock:
        return [name for (ck, name) in _conversations if ck == prefix[0]]


# ── Persistent Async Background ────────────────────────────────────────────────


class _MCPLoopThread(threading.Thread):
    """Background thread running a persistent asyncio event loop.
    
    One thread per conversation to avoid cross-talk.
    Tracks pending operations to prevent premature loop shutdown.
    """
    
    _instances: dict[str, "_MCPLoopThread"] = {}
    _lock = threading.Lock()
    
    @classmethod
    def get_thread(cls, conversation_key: str | None) -> "_MCPLoopThread":
        """Get or create the loop thread for a conversation."""
        key = conversation_key or "_default"
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(key)
                cls._instances[key].start()
            return cls._instances[key]
    
    @classmethod
    def stop_thread(cls, conversation_key: str | None) -> None:
        """Stop the loop thread for a conversation.
        
        Waits for all pending operations to complete before stopping.
        """
        key = conversation_key or "_default"
        with cls._lock:
            if key not in cls._instances:
                return
            instance = cls._instances.pop(key)
        # Wait outside class lock to avoid deadlock
        instance._drain_and_stop()
    
    def __init__(self, conversation_key: str):
        super().__init__(daemon=True, name=f"mcp-{conversation_key}")
        self._conversation_key = conversation_key
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._loop_started = False
        self._pending_count = 0
        self._pending_zero = threading.Event()
        self._pending_zero.set()  # Initially zero pending
        self._stopping = False
    
    def run(self):
        """Run the event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_started = True
        self._ready.set()
        self._loop.run_forever()
    
    def _drain_and_stop(self):
        """Wait for pending operations to complete, then stop the loop."""
        self._stopping = True
        # Wait up to 30s for pending operations to drain
        if not self._pending_zero.wait(timeout=30):
            logger.warning(
                f"MCP loop thread '{self._conversation_key}': "
                "timed out waiting for pending operations"
            )
        if self._loop and self._loop_started:
            self._loop.call_soon_threadsafe(self._loop.stop)
    
    def submit(self, coro) -> Any:
        """Submit a coroutine and wait for result.
        
        Tracks pending operation count to prevent premature shutdown.
        """
        if self._stopping:
            raise RuntimeError("MCP loop thread is shutting down")
        if not self._ready.wait(timeout=10):
            raise TimeoutError("MCP event loop not ready")
        
        self._pending_count += 1
        self._pending_zero.clear()
        
        async def _run_tracked():
            try:
                return await coro
            finally:
                self._pending_count -= 1
                if self._pending_count == 0:
                    self._pending_zero.set()
        
        future = asyncio.run_coroutine_threadsafe(_run_tracked(), self._loop)
        return future.result(timeout=60)


# ── Async Operations ──────────────────────────────────────────────────────────


async def _connect_async(config: MCPServerConfig) -> dict[str, Any]:
    """Connect to MCP server via stdio.
    
    Returns dict with 'session', 'stdio_cm', 'session_cm' so callers
    can clean up context managers on disconnect.
    
    Cleans up partially-entered context managers on failure (Bug #18).
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = config.to_stdio_params()
    stdio_cm = stdio_client(params)
    session_cm = None
    
    try:
        read, write = await stdio_cm.__aenter__()
        session_cm = ClientSession(read, write)
        await session_cm.__aenter__()
        await session_cm.initialize()
    except BaseException:
        # Clean up partially-entered context managers
        if session_cm is not None:
            try:
                await session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        try:
            await stdio_cm.__aexit__(None, None, None)
        except Exception:
            pass
        raise
    
    return {
        "session": session_cm,
        "stdio_cm": stdio_cm,
        "session_cm": session_cm,
    }


async def _disconnect_async(conn: dict[str, Any]) -> None:
    """Disconnect gracefully.
    
    Exits both the ClientSession and stdio_client context managers
    in the correct order (session first, then stdio transport).
    """
    session_cm = conn.get("session_cm")
    stdio_cm = conn.get("stdio_cm")
    
    if session_cm is not None:
        try:
            await session_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug(f"Error closing session: {exc}")
    
    if stdio_cm is not None:
        try:
            await stdio_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug(f"Error closing stdio transport: {exc}")


async def _discover_tools_async(conn: dict[str, Any], server_name: str) -> list[MCPToolDefinition]:
    """Discover tools from connected server."""
    session = conn["session"]
    result = await session.list_tools()
    return [
        MCPToolDefinition(
            name=t.name,
            description=t.description or "",
            parameters=t.inputSchema,
            server_name=server_name,
        )
        for t in result.tools
    ]


async def _call_tool_async(conn: dict[str, Any], tool_name: str, arguments: dict) -> MCPToolResult:
    """Call an MCP tool."""
    import time
    session = conn["session"]
    start = time.monotonic()
    try:
        result = await session.call_tool(tool_name, arguments)
        duration = int((time.monotonic() - start) * 1000)
        output = ""
        if hasattr(result, 'content') and result.content:
            for block in result.content:
                if hasattr(block, 'text'):
                    output += block.text
                elif isinstance(block, str):
                    output += block
        return MCPToolResult(success=True, output=output, duration_ms=duration)
    except Exception as e:
        duration = int((time.monotonic() - start) * 1000)
        return MCPToolResult(success=False, error=str(e), duration_ms=duration)


# ── Sync Wrappers ────────────────────────────────────────────────────────────────


def connect(
    server_name: str,
    conversation_key: str | None = None,
) -> None:
    """Connect to an MCP server for a conversation.

    BUG #28 Fix: Two-phase connect — lock only held for dict ops (μs), not for
    blocking MCP handshake (seconds). Uses "in-progress" sentinel pattern so that
    concurrent callers wait for the same connection rather than racing.
    """
    key = _make_conversation_key(conversation_key, server_name)
    
    config = get_server_config(server_name)
    if config is None:
        raise FileNotFoundError(f"Server not found: {server_name}")
    
    if not config.enabled:
        raise MCPConfigError(f"Server {server_name} is disabled")
    
    # ── Phase 1: Check/claim under lock (microseconds only) ─────────────────
    with _state_lock:
        # Already connected?
        if key in _conversations:
            existing = _conversations[key]
            # If it's a "connecting in progress" future — wait for it below
            if not _is_connection_future(existing):
                return  # Already fully connected
        
        # Mark as "connecting" sentinel so concurrent callers wait for this one
        connecting_future = _make_connecting_sentinel()
        _conversations[key] = connecting_future
    # Lock released — now do expensive MCP handshake outside lock
    
    # ── Phase 2: Establish connection (seconds, no lock held) ───────────────
    try:
        loop_thread = _MCPLoopThread.get_thread(conversation_key)
        real_future = loop_thread.submit(_connect_async(config))
        result = real_future  # Store the real future directly
    except Exception as e:
        # Connect failed — clean up placeholder under lock
        with _state_lock:
            if _conversations.get(key) is connecting_future:
                _conversations.pop(key, None)
        logger.warning(f"Failed to connect to {server_name}: {e}")
        raise RuntimeError(f"Failed to connect to {server_name}: {e}")
    
    # ── Phase 3: Commit result under lock (microseconds only) ──────────────
    with _state_lock:
        # Replace the connecting sentinel with the real connection
        if _conversations.get(key) is connecting_future:
            _conversations[key] = result
        # Invalidate tools cache for this server on new connection
        with _tools_cache_lock:
            _tools_cache.pop(key, None)


def _is_connection_future(value: Any) -> bool:
    """Return True if value is our sentinel marker meaning 'connecting in progress'."""
    return isinstance(value, tuple) and len(value) == 2 and value[0] == "connecting"


def _make_connecting_sentinel() -> tuple:
    """Sentinel placeholder stored in _conversations during connect handshake."""
    return ("connecting", threading.current_thread().name)


def disconnect(
    server_name: str,
    conversation_key: str | None = None,
) -> None:
    """Disconnect from an MCP server."""
    key = _make_conversation_key(conversation_key, server_name)
    
    conn = None
    with _state_lock:
        conn = _conversations.pop(key, None)
    
    if conn:
        try:
            loop_thread = _MCPLoopThread.get_thread(conversation_key)
            loop_thread.submit(_disconnect_async(conn))
        except Exception as e:
            logger.warning(f"Error disconnecting {server_name}: {e}")


def disconnect_all(conversation_key: str | None = None) -> None:
    """Disconnect all MCP servers for a conversation."""
    prefix = conversation_key or "_default"
    
    # Collect keys to disconnect
    keys_to_remove = []
    with _state_lock:
        for key in list(_conversations.keys()):
            if key[0] == prefix:
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        disconnect(key[1], key[0])
    
    # Stop the loop thread
    _MCPLoopThread.stop_thread(conversation_key)


def discover_tools(
    server_name: str,
    conversation_key: str | None = None,
) -> list[MCPToolDefinition]:
    """Discover tools from a connected server."""
    key = _make_conversation_key(conversation_key, server_name)
    
    conn = None
    with _state_lock:
        conn = _conversations.get(key)
    
    if conn is None:
        raise RuntimeError(f"Not connected to {server_name}")
    
    loop_thread = _MCPLoopThread.get_thread(conversation_key)
    return loop_thread.submit(_discover_tools_async(conn, server_name))


def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict,
    conversation_key: str | None = None,
) -> MCPToolResult:
    """Call an MCP tool."""
    key = _make_conversation_key(conversation_key, server_name)
    
    conn = None
    with _state_lock:
        conn = _conversations.get(key)
    
    if conn is None:
        raise RuntimeError(f"Not connected to {server_name}")
    
    loop_thread = _MCPLoopThread.get_thread(conversation_key)
    return loop_thread.submit(_call_tool_async(conn, tool_name, arguments))


# ── High-Level API ────────────────────────────────────────────────────


def connect_servers(
    server_names: list[str],
    conversation_key: str | None = None,
) -> dict[str, str]:
    """Connect to multiple servers. Returns name->error dict."""
    results = {}
    for name in server_names:
        try:
            connect(name, conversation_key)
            results[name] = ""
        except Exception as e:
            logger.warning(f"Failed to connect to {name}: {e}")
            results[name] = str(e)
    return results


def get_tools_for_api(
    server_names: list[str],
    conversation_key: str | None = None,
) -> list[dict]:
    """Get MCP tool definitions in OpenAI function-calling format.
    
    BUG #24 Fix: Caches tool definitions per server to avoid repeated MCP calls.
    """
    tools = []
    for server_name in server_names:
        key = _make_conversation_key(conversation_key, server_name)
        
        # Check cache first
        with _tools_cache_lock:
            cached = _tools_cache.get(key)
            if cached is not None:
                tools.extend(cached)
                continue
        
        # Ensure connected (idempotent)
        try:
            connect(server_name, conversation_key)
        except Exception as e:
            logger.warning(f"Skipping {server_name}: {e}")
            continue
        
        try:
            server_tools = discover_tools(server_name, conversation_key)
            server_tool_dicts = []
            for tool in server_tools:
                namespaced = f"{server_name}/{tool.name}"
                func_dict = {
                    "type": "function",
                    "function": {
                        "name": namespaced,
                        "description": tool.description or f"MCP: {tool.name}",
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
                tools.append(func_dict)
                server_tool_dicts.append(func_dict)
            
            # Cache the results
            with _tools_cache_lock:
                _tools_cache[key] = server_tool_dicts
                
        except Exception as e:
            logger.warning(f"Failed to discover tools from {server_name}: {e}")
            continue
    
    return tools