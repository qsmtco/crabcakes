# tests/test_provider_test.py
# Tests for utils/provider_test.py — Test Connection network probe.
#
# Principle: mock at the boundary (urllib.request.urlopen), test behavior not internals.
# Do NOT mock the function being tested.

import io
import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from utils.provider_test import TestResult as TestResultData, test_connection


# ── Helpers ────────────────────────────────────────────────────────────────


def _mock_response(body: bytes, status: int = 200) -> MagicMock:
    """Create a mock urllib response object."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    return resp


def _http_error(code: int, reason: str, body: str = "") -> urllib.error.HTTPError:
    """Create an HTTPError with a readable body."""
    err = urllib.error.HTTPError(
        url="https://api.example.com",
        code=code,
        msg=reason,
        hdrs={},
        fp=None,
    )
    err.read = MagicMock(return_value=body.encode())
    return err


# ── TestOpenAICompatible ──────────────────────────────────────────────────


class TestOpenAICompatible:
    def test_success_returns_ok(self):
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4",
            )
        assert result.ok is True
        assert result.latency_ms >= 0
        assert result.error is None
        assert result.model_used == "openai/gpt-4"

    def test_401_returns_fail_with_body(self):
        err = _http_error(401, "Unauthorized", "invalid key")
        with patch("utils.provider_test.urllib.request.urlopen", side_effect=err):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-bad",
                model="openai/gpt-4",
            )
        assert result.ok is False
        assert "401" in result.error
        assert "invalid key" in result.error

    def test_request_uses_correct_url(self):
        """Verify the URL is constructed with rstrip('/') — trailing slash stripped."""
        captured_req = {}
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_req["url"] = req.full_url
            captured_req["data"] = req.data
            captured_req["headers"] = dict(req.headers)
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.example.com/v1/",
                api_key="sk-test",
                model="openrouter/qwen/qwen3.7-max",
            )

        # Trailing slash stripped, then /chat/completions appended
        assert captured_req["url"] == "https://api.example.com/v1/chat/completions"

    def test_request_uses_correct_bearer_header(self):
        captured_headers = {}
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_headers.update(dict(req.headers))
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.example.com/v1",
                api_key="sk-xxx",
                model="openrouter/qwen/qwen3.7-max",
            )

        assert captured_headers.get("Authorization") == "Bearer sk-xxx"

    def test_request_strips_provider_prefix_from_model(self):
        """Pass model='openrouter/qwen/qwen3.7-max' → body has model='qwen/qwen3.7-max'."""
        captured_body = {}
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_body["data"] = json.loads(req.data)
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.example.com/v1",
                api_key="sk-test",
                model="openrouter/qwen/qwen3.7-max",
            )

        assert captured_body["data"]["model"] == "qwen/qwen3.7-max"


# ── TestMinimaxBodyLevelError ─────────────────────────────────────────────


class TestMinimaxBodyLevelError:
    def test_body_status_code_nonzero_returns_fail(self):
        """MiniMax returns HTTP 200 with base_resp.status_code != 0 → failure."""
        body = json.dumps({
            "base_resp": {"status_code": 1004, "status_msg": "login fail..."},
            "choices": [],
        }).encode()
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.minimax.io/v1",
                api_key="sk-bad-minimax",
                model="minimax/MiniMax-M2.7",
            )
        assert result.ok is False
        assert "1004" in result.error
        assert "login fail" in result.error

    def test_body_status_code_zero_returns_ok(self):
        """MiniMax returns HTTP 200 with base_resp.status_code == 0 → success."""
        body = json.dumps({
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "choices": [{"message": {"content": "hi"}}],
        }).encode()
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.minimax.io/v1",
                api_key="sk-good-minimax",
                model="minimax/MiniMax-M2.7",
            )
        assert result.ok is True

    def test_body_missing_base_resp_returns_ok(self):
        """Response with no base_resp field → ok (defensive: do not assume field exists)."""
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.minimax.io/v1",
                api_key="sk-test",
                model="minimax/MiniMax-M2.7",
            )
        assert result.ok is True


# ── TestAnthropic ──────────────────────────────────────────────────────────


class TestAnthropic:
    def test_success_returns_ok(self):
        body = json.dumps({
            "content": [{"type": "text", "text": "hi"}],
        }).encode()
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.anthropic.com",
                api_key="sk-ant-xxx",
                model="anthropic/claude-sonnet-4-20250514",
            )
        assert result.ok is True
        assert result.model_used == "anthropic/claude-sonnet-4-20250514"

    def test_request_uses_x_api_key_not_bearer(self):
        captured_headers = {}
        body = json.dumps({"content": [{"type": "text", "text": "hi"}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_headers.update(dict(req.headers))
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.anthropic.com",
                api_key="sk-ant-xxx",
                model="anthropic/claude-sonnet-4-20250514",
            )

        # Anthropic uses x-api-key, NOT Authorization Bearer
        # urllib.request.Request normalizes headers to Title-Case
        assert any(k.lower() == "x-api-key" and v == "sk-ant-xxx" for k, v in captured_headers.items())
        assert not any(k.lower() == "authorization" and "Bearer" in v for k, v in captured_headers.items())

    def test_request_uses_anthropic_version(self):
        captured_headers = {}
        body = json.dumps({"content": [{"type": "text", "text": "hi"}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_headers.update(dict(req.headers))
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.anthropic.com",
                api_key="sk-ant-xxx",
                model="anthropic/claude-sonnet-4-20250514",
            )

        # urllib.request.Request normalizes headers to Title-Case
        assert any(k.lower() == "anthropic-version" and v == "2023-06-01" for k, v in captured_headers.items())


# ── TestNetworkErrors ─────────────────────────────────────────────────────


class TestNetworkErrors:
    def test_timeout_returns_fail(self):
        with patch("utils.provider_test.urllib.request.urlopen", side_effect=TimeoutError("connection timed out")):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4",
            )
        assert result.ok is False
        assert "timed out" in result.error.lower()

    def test_dns_failure_returns_fail(self):
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Name or service not known")):
            result = test_connection(
                base_url="https://api.nonexistent.example.com/v1",
                api_key="sk-test",
                model="openai/gpt-4",
            )
        assert result.ok is False
        assert "Name or service not known" in result.error

    def test_malformed_json_returns_fail(self):
        body = b"this is not json at all"
        with patch("utils.provider_test.urllib.request.urlopen", return_value=_mock_response(body)):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4",
            )
        assert result.ok is False
        assert "Invalid JSON" in result.error


# ── TestUnknownProvider ───────────────────────────────────────────────────


class TestUnknownProvider:
    def test_raises_value_error(self):
        with pytest.raises(ValueError, match="No adapter"):
            test_connection(
                base_url="https://api.unknown.com",
                api_key="sk-test",
                model="unknown-vendor/foo",
            )
