# src/gateway/__init__.py
# Gateway package — WebSocket client for OpenClaw gateway

from .client import GatewayClient, SnapshotValidationError

__all__ = ["GatewayClient", "SnapshotValidationError"]
