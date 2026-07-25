"""Tests for agent/llm/streaming.py — SSE helpers and SSL retry infrastructure.

Extracted from agent/runtime.py (Phase B5).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from agent.llm.streaming import (
    SSEEvent,
    first_choice,
    friendly_error_message,
    is_retryable_ssl_error,
    parse_sse_delta,
    parse_sse_line,
    sse_lines,
    stream_with_ssl_retry,
    urlopen_with_ssl_retry,
)


# ── SSE parsing tests ───────────────────────────────────────────────────────

def test_sse_lines_strips_whitespace():
    """sse_lines strips each line of whitespace."""
    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = [b"  data: hello  ", b"\t", b"data: world"]
    result = list(sse_lines(mock_resp))
    assert result == [b"data: hello", b"", b"data: world"]


def test_parse_sse_line_data_prefix():
    """'data: {...}' → SSEEvent with parsed JSON."""
    payload = {"choices": [{"delta": {"content": "hi"}}]}
    ev = parse_sse_line(b"data: " + json.dumps(payload).encode())
    assert ev is not None
    assert ev.type == "raw"
    assert ev.data == payload


def test_parse_sse_line_done():
    """'data: [DONE]' → done event."""
    ev = parse_sse_line(b"data: [DONE]")
    assert ev is not None
    assert ev.type == "done"
    assert ev.data == {}


def test_parse_sse_line_comment():
    """':comment' → None."""
    assert parse_sse_line(b":comment") is None


def test_parse_sse_delta_text_content():
    """delta.content → text_delta event."""
    d = {"choices": [{"delta": {"content": "Hello"}}]}
    events = parse_sse_delta(d)
    assert len(events) == 1
    assert events[0].type == "text_delta"
    assert events[0].data["content"] == "Hello"


def test_parse_sse_delta_tool_call():
    """delta.tool_calls → tool_call_delta event."""
    d = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc123",
                    "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}
                }]
            }
        }]
    }
    events = parse_sse_delta(d)
    assert len(events) == 1
    assert events[0].type == "tool_call_delta"
    assert events[0].data["index"] == 0
    assert events[0].data["name"] == "read_file"
    assert events[0].data["arguments"] == '{"path": "x.py"}'
    assert events[0].data["id"] == "call_abc123"


def test_parse_sse_delta_handles_none_delta():
    """delta: None → no crash, returns empty events list."""
    d = {"choices": [{"delta": None, "finish_reason": "stop"}]}
    events = parse_sse_delta(d)
    assert events == []


def test_parse_sse_delta_handles_missing_choices():
    """Empty or missing choices → returns empty events list."""
    d = {}
    events = parse_sse_delta(d)
    assert events == []

    d2 = {"choices": []}
    events = parse_sse_delta(d2)
    assert events == []


# ── Sad-path tests ──────────────────────────────────────────────────────────

def test_parse_sse_line_malformed_json():
    """Bad JSON → None, not crash."""
    ev = parse_sse_line(b"data: {not json}")
    assert ev is None


def test_urlopen_ssl_retry_transient_error():
    """Retryable URLError → retried then succeeds."""
    import urllib.request as _urllib_request

    trans_sslerr = ssl.SSLError(1, "[SSL: SSLV3_ALERT_BAD_RECORD_MAC] sslv3 alert bad record mac")
    retryable_e = urllib.error.URLError(trans_sslerr)

    call_count = [0]

    def _patched_urlopen(req, timeout=None):
        call_count[0] += 1
        if call_count[0] < 2:
            # Wrap as do_open would — URLError wrapping ssl.SSLError
            raise retryable_e
        return MagicMock()

    with patch.object(_urllib_request, "urlopen", _patched_urlopen):
        req = MagicMock()
        req.full_url = "https://api.example.com/v1/chat/completions"
        result = urlopen_with_ssl_retry(req, timeout=30)
        assert call_count[0] == 2  # 1 fail + 1 success
        assert result is not None


def test_urlopen_ssl_retry_non_retryable_raises():
    """Non-retryable error → raised immediately, no retries."""
    import urllib.request as _urllib_request

    dns_err = urllib.error.URLError("getaddrinfo failed")

    call_count = [0]

    def _patched_urlopen(req, timeout=None):
        call_count[0] += 1
        raise dns_err

    with patch.object(_urllib_request, "urlopen", _patched_urlopen):
        req = MagicMock()
        req.full_url = "https://nonexistent.example.com"
        with pytest.raises(urllib.error.URLError):
            urlopen_with_ssl_retry(req, timeout=30)
        assert call_count[0] == 1  # No retry


def test_urlopen_ssl_retry_max_attempts():
    """Exhausts retries → raises last exception."""
    import urllib.request as _urllib_request

    trans_sslerr = ssl.SSLError(1, "EOF occurred in violation of protocol")
    retryable_e = urllib.error.URLError(trans_sslerr)

    call_count = [0]

    def _patched_urlopen(req, timeout=None):
        call_count[0] += 1
        raise retryable_e

    with patch.object(_urllib_request, "urlopen", _patched_urlopen):
        req = MagicMock()
        req.full_url = "https://api.example.com/v1/chat/completions"
        with pytest.raises(urllib.error.URLError):
            urlopen_with_ssl_retry(req, timeout=30, max_retries=2)
        assert call_count[0] == 3  # initial + 2 retries = 3 attempts


# ── Backward-compat tests ───────────────────────────────────────────────────

def test_runtime_reexport_sse_event():
    """from agent.runtime import SSEEvent works."""
    from agent.runtime import SSEEvent as RuntimeSSEEvent
    from agent.llm.streaming import SSEEvent as StreamingSSEEvent
    assert RuntimeSSEEvent is StreamingSSEEvent


def test_runtime_reexport_stream_with_ssl_retry():
    # Re-export test removed in Phase 8 — _stream_with_ssl_retry no longer
    # exists in agent.runtime. The canonical function is agent.llm.streaming.stream_with_ssl_retry.
    pass


# ── TimeoutError tests ──────────────────────────────────────────────────────

def test_friendly_error_message_timeout():
    """TimeoutError produces a user-friendly message, not raw 'read operation timed out'."""
    from agent.llm.streaming import friendly_error_message
    exc = TimeoutError("The read operation timed out")
    msg = friendly_error_message(exc)
    assert "timed out" in msg.lower()
    assert "try" in msg.lower() or "again" in msg.lower()
    assert "read operation timed out" not in msg  # raw message should NOT be shown


def test_stream_with_ssl_retry_retries_on_timeout():
    """TimeoutError during streaming triggers a retry (not an immediate raise)."""
    import socket
    from agent.llm.streaming import stream_with_ssl_retry

    call_count = 0
    def flaky_streamer(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("The read operation timed out")
        yield from []  # succeed on retry

    events = list(stream_with_ssl_retry(
        flaky_streamer,
        base_url="", api_key="", model="",
        messages=[], tools=None, timeout=1.0, x_title="",
    ))
    assert call_count == 2, f"Expected 2 attempts (1 fail + 1 succeed), got {call_count}"


def test_stream_with_ssl_retry_raises_after_timeout_retries_exhausted():
    """TimeoutError persists across all retries → raises to caller."""
    from agent.llm.streaming import stream_with_ssl_retry, MAX_SSL_RETRIES

    def always_timeout(**kwargs):
        raise TimeoutError("The read operation timed out")

    with pytest.raises(TimeoutError):
        list(stream_with_ssl_retry(
            always_timeout,
            base_url="", api_key="", model="",
            messages=[], tools=None, timeout=1.0, x_title="",
        ))