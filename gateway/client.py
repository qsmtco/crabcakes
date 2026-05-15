# src/gateway/client.py
# WebSocket client for OpenClaw gateway — v3 device-auth protocol.
#
# Loads device identity from ~/.openclaw/identity/ and connects as a
# CLI client using Ed25519 device authentication.
#
# Public API:
#   - client.start()   — initiate gateway connection (background thread)
#   - client.stop()     — close connection
#   - client.is_connected() — True if connected
#   - client.get_snapshot() — hello-ok snapshot dict
#   - client.send_message(session_key, text, on_sent) — send chat message

import asyncio
import base64
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Optional

from gi.repository import GLib  # type: ignore[attr-defined]

from utils.config import get_identity_dir

_logger = logging.getLogger(__name__)

# Enable raw gateway WS dump via CRABCAKES_GATEWAY_DEBUG=1 — independent of CRABCAKES_DEBUG
if os.environ.get("CRABCAKES_GATEWAY_DEBUG"):
    _logger.setLevel(logging.DEBUG)

# ── Snapshot Schema ───────────────────────────────────────────────────────────────

class SnapshotValidationError(Exception):
    """Raised when the gateway hello-ok snapshot does not match the expected schema."""
    pass

_EXPECTED_SNAPSHOT_KEYS = {"health"}
_EXPECTED_HEALTH_KEYS = {"agents"}
_EXPECTED_AGENT_KEYS = {"agentId", "sessions"}


def _validate_snapshot(snapshot: Any) -> list:
    """Validate hello-ok snapshot and return the agents list. Raises on failure."""
    if not isinstance(snapshot, dict):
        raise SnapshotValidationError(f"snapshot is not a dict: {type(snapshot).__name__}")
    missing = _EXPECTED_SNAPSHOT_KEYS - set(snapshot.keys())
    if missing:
        raise SnapshotValidationError(f"snapshot missing keys: {missing}")
    health = snapshot["health"]
    if not isinstance(health, dict):
        raise SnapshotValidationError(f"snapshot.health is not a dict: {type(health).__name__}")
    missing_health = _EXPECTED_HEALTH_KEYS - set(health.keys())
    if missing_health:
        raise SnapshotValidationError(f"snapshot.health missing keys: {missing_health}")
    agents = health["agents"]
    if not isinstance(agents, list):
        raise SnapshotValidationError(f"snapshot.health.agents is not a list: {type(agents).__name__}")
    for i, agent in enumerate(agents):
        if not isinstance(agent, dict):
            raise SnapshotValidationError(f"snapshot.health.agents[{i}] is not a dict: {type(agent).__name__}")
        missing_agent = _EXPECTED_AGENT_KEYS - set(agent.keys())
        if missing_agent:
            raise SnapshotValidationError(f"snapshot.health.agents[{i}] missing keys: {missing_agent}")
    return agents

# ── Device Identity ──────────────────────────────────────────────────────────────

_IDENTITY_CACHE = None


def _load_identity():
    """Load device credentials from the OpenClaw identity directory."""
    identity_dir = get_identity_dir()

    auth_path = os.path.join(identity_dir, "device-auth.json")
    try:
        with open(auth_path) as f:
            auth = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"OpenClaw identity not found.\n"
            f"  Missing: {auth_path}\n"
            f"  Run 'openclaw login' or 'openclaw device register' to set up identity."
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"OpenClaw identity file is corrupted (invalid JSON): {auth_path}\n"
            f"  Error: {e}\n"
            f"  Run 'openclaw login' to regenerate."
        )

    device_id = auth.get("deviceId")
    if not device_id:
        raise RuntimeError(
            f"Missing 'deviceId' in {auth_path}.\n"
            f"  Run 'openclaw login' to regenerate."
        )

    tokens = auth.get("tokens", {})
    if not tokens:
        raise RuntimeError(
            f"No authentication tokens found in {auth_path}.\n"
            f"  Run 'openclaw login' to regenerate."
        )
    operator_tok = tokens.get("operator", {})
    device_token = operator_tok.get("token")
    if not device_token:
        fallback = list(tokens.values())
        if fallback:
            device_token = fallback[0].get("token")
        if not device_token:
            raise RuntimeError(
                f"No valid operator token found in {auth_path}.\n"
                f"  Run 'openclaw login' to regenerate."
            )

    dev_path = os.path.join(identity_dir, "device.json")
    try:
        with open(dev_path) as f:
            dev = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"OpenClaw device key not found.\n"
            f"  Missing: {dev_path}\n"
            f"  Run 'openclaw device register' to generate a device identity."
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"OpenClaw device key file is corrupted (invalid JSON): {dev_path}\n"
            f"  Error: {e}\n"
            f"  Run 'openclaw device register' to regenerate."
        )

    priv_pem = dev.get("privateKeyPem")
    if not priv_pem:
        raise RuntimeError(
            f"Missing 'privateKeyPem' in {dev_path}.\n"
            f"  Run 'openclaw device register' to regenerate."
        )

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    try:
        priv = serialization.load_pem_private_key(
            priv_pem.encode(), password=None, backend=default_backend()
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to load Ed25519 private key from {dev_path}.\n"
            f"  Error: {e}\n"
            f"  Run 'openclaw device register' to regenerate a device identity."
        )

    pub_der = priv.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    raw_key = pub_der[-32:]
    raw_key_b64 = base64.b64encode(raw_key).decode()

    identity = {
        "device_id": device_id,
        "device_token": device_token,
        "private_key": priv,
        "raw_key_b64": raw_key_b64,
    }

    global _IDENTITY_CACHE
    _IDENTITY_CACHE = identity
    return identity


def _reload_identity():
    """Force-reload device identity from disk."""
    global _IDENTITY_CACHE
    _IDENTITY_CACHE = None
    return _load_identity()


# Preload identity on module import (catches errors immediately)
_load_identity()

# Auth scopes
ALL_SCOPES = "operator.admin,operator.approvals,operator.pairing"


# ── Gateway Client ─────────────────────────────────────────────────────────────

class GatewayClient:
    """
    Threaded async WebSocket client for the OpenClaw gateway.

    Arguments to __init__:
      url           — WebSocket URL, e.g. "ws://localhost:18789"
      on_connect    — callable(): connection established successfully
      on_error      — callable(str): connection/error state changed
      on_event      — callable(event_name, payload): gateway event received
      on_tick       — callable(): called every ~15s while connected (keepalive heartbeat)
    """

    def __init__(
        self,
        url: str,
        on_connect: Callable[[], None],
        on_error: Callable[[str], None],
        on_event: Callable[[str, dict[str, Any]], None],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        self.url: str = url
        self.on_connect: Callable[[], None] = on_connect
        self.on_error: Callable[[str], None] = on_error
        self.on_event: Callable[[str, dict[str, Any]], None] = on_event
        self.on_tick: Callable[[], None] = on_tick if on_tick is not None else lambda: None
        self._running: bool = False
        self._stopping: bool = False
        self._tick_task: Optional[asyncio.Task] = None
        self._thread: Optional[threading.Thread] = None
        self._connected: threading.Event = threading.Event()
        self._ws: Optional[Any] = None  # websockets.WebSocketServerProtocol
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # set in _run()
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_lock: threading.Lock = threading.Lock()
        self._hello_snapshot: Optional[dict[str, Any]] = None
        self._id: dict[str, Any] = _IDENTITY_CACHE if _IDENTITY_CACHE is not None else _load_identity()
        self._RPC_TIMEOUT_SEC: float = 30.0
        self._on_res: Callable[[str, dict[str, Any]], None] | None = None  # res correlation callback

    def set_on_res(self, cb: Callable[[str, dict[str, Any]], None]):
        """Set callback for incoming res events (main thread). cb(session_key, payload)."""
        self._on_res = cb

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background thread (reconnecting). Safe to call multiple times."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping = False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop retrying and close the WebSocket."""
        if self._stopping:
            return
        self._stopping = True
        self._running = False
        self._connected.clear()
        self._drain_pending("connection closed")
        if self._ws is not None:
            try:
                if self._loop is not None:
                    asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            except Exception as e:
                _logger.debug("Error closing WebSocket during stop: %s", e)

    def is_connected(self) -> bool:
        """Return True if the WebSocket is currently connected."""
        return self._connected.is_set()

    def get_snapshot(self) -> Optional[dict[str, Any]]:
        """Return the hello-ok snapshot dict (or None before first successful connect)."""
        return self._hello_snapshot

    def send_message(
        self,
        session_key: str,
        text: str,
        on_sent: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    ) -> None:
        """Send a text message into a session."""
        if not isinstance(session_key, str) or not isinstance(text, str):
            self.on_error(f"send_message: expected str, got {type(session_key).__name__}/{type(text).__name__}")
            return
        if not session_key or not text:
            _logger.warning("send_message called with empty session_key=%r or text=%r", session_key, text)
            if on_sent:
                on_sent(None)
            return
        if not self._connected or self._ws is None:
            self.on_error("Not connected to gateway")
            return

        def on_send_response(payload, _req_id=None):
            run_id = payload.get("runId")
            if not run_id:
                err = payload.get("error", {})
                err_msg = err.get("message") if err else "unknown"
                _logger.debug("[gateway] send FAILED: %s", err_msg)
                self.on_error(f"Message failed: {err_msg}")
            else:
                _logger.debug("[gateway] send OK, runId=%s", run_id)
                if on_sent:
                    on_sent(run_id, req_id)

        req_id = str(uuid.uuid4())
        # Embed req_id in the closure so it's available when res fires
        stored_cb = lambda p: on_send_response(p, req_id)
        self._send({
            "type": "req",
            "id": req_id,
            "method": "chat.send",
            "params": {
                "idempotencyKey": str(uuid.uuid4()),
                "message": text,
                "sessionKey": session_key,
            },
        }, on_response=stored_cb)

    # ── Internals ────────────────────────────────────────────────────────────

    def _send(self, payload, on_response=None):
        """Send a JSON payload on the WebSocket (thread-safe)."""
        self._expire_pending()
        req_id = payload.get("id")
        if req_id and on_response:
            with self._pending_lock:
                self._pending[req_id] = {
                    "callback": on_response,
                    "deadline": time.monotonic() + self._RPC_TIMEOUT_SEC,
                }
        if self._ws is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        """Reconnecting connection loop — runs until self._running is False."""
        import websockets
        retry_delay = 1.0
        max_delay = 30.0
        while self._running:
            try:
                try:
                    self._id = _reload_identity()
                except Exception as e:
                    GLib.idle_add(self.on_error, f"Identity error: {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_delay)
                    continue
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    self._connected.set()
                    retry_delay = 1.0
                    await self._handshake()
                    GLib.idle_add(self.on_connect)
                    self._tick_task = self._loop.create_task(self._tick_loop())
                    await self._listen()
            except websockets.exceptions.ConnectionClosed as e:
                self._connected.clear()
                self._drain_pending(f"Connection closed: {e}")
                GLib.idle_add(self.on_error, f"Connection closed: {e}")
            except Exception as e:
                self._connected.clear()
                self._drain_pending(str(e))
                GLib.idle_add(self.on_error, f"Reconnecting in {int(retry_delay)}s…")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)

    async def _handshake(self) -> None:
        """Perform the v3 device-auth handshake with the gateway."""
        assert self._ws is not None, "_ws must be set before _handshake"
        raw = await self._ws.recv()
        msg = json.loads(raw)
        nonce = msg.get("payload", {}).get("nonce", "")
        ts = int(time.time() * 1000)

        # 2. Build v3 auth payload
        v3_payload = (
            f"v3|{self._id['device_id']}"
            f"|cli|cli"
            f"|operator"
            f"|{ALL_SCOPES}"
            f"|{ts}"
            f"|{self._id['device_token']}"
            f"|{nonce}"
            f"|linux|"
        )

        # 3. Sign with Ed25519 private key
        sig = self._id["private_key"].sign(v3_payload.encode())
        sig_b64 = base64.b64encode(sig).decode()

        # 4. Send connect request
        await self._ws.send(json.dumps({
            "type": "req",
            "id": "connect",
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 4,
                "client": {
                    "id": "cli",
                    "version": "2026.5.14",
                    "platform": "linux",
                    "mode": "ui",
                    "displayName": "crabcakes",
                },
                "role": "operator",
                "scopes": ALL_SCOPES.split(","),
                "auth": {"token": self._id["device_token"]},
                "locale": "en-US",
                "userAgent": "crabcakes/1.0",
                "device": {
                    "id": self._id["device_id"],
                    "nonce": nonce,
                    "publicKey": self._id["raw_key_b64"],
                    "signature": sig_b64,
                    "signedAt": ts,
                },
            },
        }))

        # 5. Wait for hello-ok or error
        raw = await self._ws.recv()
        resp = json.loads(raw)
        if not resp.get("ok"):
            err = resp.get("error", {})
            raise Exception(
                f"connect failed [{err.get('code', '?')}]: {err.get('message', 'unknown error')}"
            )
        raw_snapshot = resp.get("payload", {}).get("snapshot")
        _validate_snapshot(raw_snapshot)  # raises SnapshotValidationError on failure
        self._hello_snapshot = raw_snapshot

    async def _tick_loop(self):
        """Fire on_tick every 15 seconds while connected."""
        while self._running and not self._stopping:
            await asyncio.sleep(15)
            if self._connected.is_set() and not self._stopping:
                GLib.idle_add(self.on_tick)

    async def _listen(self) -> None:
        """Pump the WebSocket — dispatch events and responses to GTK main thread."""
        assert self._ws is not None, "_ws must be set before _listen"
        async for raw in self._ws:
            self._expire_pending()
            _logger.debug("[gateway>>] %s", raw[:300])
            self._expire_pending()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    evt_name = msg.get("event", "")
                    GLib.idle_add(self.on_event, evt_name, msg.get("payload", {}))
                elif msg.get("type") == "res":
                    req_id = msg.get("id")
                    with self._pending_lock:
                        entry = self._pending.pop(req_id, None)
                    if entry:
                        GLib.idle_add(entry["callback"], msg.get("payload", {}))
                    # Fire global res correlation callback (pre-flight confirmation)
                    if self._on_res:
                        GLib.idle_add(self._on_res, req_id, msg.get("payload", {}))
            except json.JSONDecodeError:
                _logger.warning("Gateway sent malformed JSON: %r", raw[:200])
            except Exception as exc:
                _logger.error("Unexpected error processing gateway message: %s", exc)

    def _expire_pending(self):
        """Fire timeout callbacks for expired pending requests."""
        now = time.monotonic()
        with self._pending_lock:
            expired = [req_id for req_id, entry in list(self._pending.items()) if entry.get("deadline", 0) <= now]
            entries_to_fire = []
            for req_id in expired:
                entry = self._pending.pop(req_id)
                entries_to_fire.append(entry)
        for entry in entries_to_fire:
            GLib.idle_add(entry["callback"], {"ok": False, "error": {"message": "gateway request timed out"}})

    def _drain_pending(self, reason):
        """Fire all remaining pending callbacks with an error payload."""
        with self._pending_lock:
            entries_to_fire = list(self._pending.items())
            self._pending.clear()
        for _, entry in entries_to_fire:
            GLib.idle_add(entry["callback"], {"ok": False, "error": {"message": f"request cancelled: {reason}"}})
