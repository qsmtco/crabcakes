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
        captured_reqs = []
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        def capture_urlopen(req, **kwargs):
            captured_reqs.append({
                "url": req.full_url,
                "data": req.data,
                "headers": dict(req.headers),
            })
            return _mock_response(body)

        with patch("utils.provider_test.urllib.request.urlopen", side_effect=capture_urlopen):
            test_connection(
                base_url="https://api.example.com/v1/",
                api_key="sk-test",
                model="openrouter/qwen/qwen3.7-max",
            )

        # First call is the POST to /chat/completions (trailing slash stripped)
        assert captured_reqs[0]["url"] == "https://api.example.com/v1/chat/completions"

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

        # First call is the POST — check Authorization header on the POST request
        # The /v1/models probe also sends Authorization; last-write-wins is fine
        # since both use the same key. The important check is that Bearer is present.
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


# ── TestModelsEndpointProbe ──────────────────────────────────────────────


class TestModelsEndpointProbe:
    def test_models_endpoint_returns_context_window(self):
        """Successful POST + GET /v1/models with matching model → context_window populated."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({
            "data": [
                {"id": "gpt-4o", "context_window": 128_000},
                {"id": "gpt-4o-mini", "context_window": 128_000},
            ],
        }).encode()

        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window == 128_000

    def test_models_endpoint_404_is_non_fatal(self):
        """Provider doesn't expose /v1/models → context_window is None, ok stays True."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        chat_resp = _mock_response(chat_body)
        err_404 = _http_error(404, "Not Found", "no /models here")
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, err_404]):
            result = test_connection(
                base_url="https://api.minimax.example.com/v1",
                api_key="sk-test",
                model="minimax/MiniMax-M2.7",
            )
        assert result.ok is True
        assert result.context_window is None

    def test_models_endpoint_malformed_json_is_non_fatal(self):
        """GET /v1/models returns invalid JSON → context_window is None, ok stays True."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        chat_resp = _mock_response(chat_body)
        bad_resp = _mock_response(b"not json")
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, bad_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None

    def test_models_endpoint_model_id_mismatch(self):
        """GET returns models but the tested model isn't in the list → context_window is None."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({
            "data": [{"id": "different-model", "context_window": 4096}],
        }).encode()
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None

    def test_models_endpoint_alternative_field_names(self):
        """Context window discovered via alternative field names (max_context_length, etc.)."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({
            "data": [{"id": "gpt-4o", "max_context_length": 200_000}],
        }).encode()
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window == 200_000

    def test_models_endpoint_empty_data_list(self):
        """GET /v1/models returns empty data list → context_window is None."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({"data": []}).encode()
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None

    def test_context_window_ignores_string_value(self):
        """If /v1/models returns context_window as string (not int), it's ignored."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        # Return context_window as a string — isinstance(str, int) is False
        models_body = json.dumps({
            "data": [{"id": "gpt-4o", "context_window": "128000"}],
        }).encode()
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None

    def test_models_endpoint_no_data_key(self):
        """GET /v1/models returns JSON without 'data' key → context_window is None."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({"models": [{"id": "gpt-4o"}]}).encode()
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None


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
