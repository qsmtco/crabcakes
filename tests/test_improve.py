# tests/test_improve.py
# Tests for utils/improve.py — prompt improvement via MiniMax API.
#
# Principle: test the failure modes that would break callers.
# Mock urllib at the network layer to simulate API errors and malformed responses.

import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest
from utils.improve import improve_prompt


# ── Helpers ────────────────────────────────────────────────────────────────────

class FakeResponse:
    """Wraps a dict as a file-like HTTP response for urllib.urlopen."""

    def __init__(self, data: dict, status: int = 200):
        self._data = data
        self._status = status

    def read(self):
        return json.dumps(self._data).encode()

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def call_improve(raw_text: str, callback_store: list):
    """
    Call improve_prompt with GLib=None so callback fires synchronously.
    Stores (text, error) in callback_store for assertion.
    """
    def capture(text, error):
        callback_store.append((text, error))

    improve_prompt(raw_text, capture, GLib=None)


# ── API Key Tests ───────────────────────────────────────────────────────────────

class TestApiKeyValidation:
    """API key is required — missing key must call callback with error, not crash."""

    def test_missing_api_key_calls_callback_with_error(self, monkeypatch):
        """When config has no apiKey, callback receives an error string."""
        callback_store: list = []

        # Override config to have empty apiKey
        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": ""})

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        text, error = callback_store[0]
        assert error is not None
        assert "MINIMAX_API_KEY" in error

    def test_whitespace_only_api_key_calls_callback_with_error(self, monkeypatch):
        """apiKey that is all whitespace must be treated as missing."""
        callback_store: list = []

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "   "})

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None


# ── HTTP Error Tests ───────────────────────────────────────────────────────────

class TestHttpErrors:
    """Network errors and HTTP error responses must call callback with error string."""

    def test_connection_error_calls_callback_with_error(self, monkeypatch):
        """urllib error (connection refused, DNS fail) must be caught and reported."""
        callback_store: list = []

        def raise_urlerror(*args, **kwargs):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", raise_urlerror)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None
        assert "connection refused" in error

    def test_http_403_calls_callback_with_error(self, monkeypatch):
        """HTTP 403 Forbidden must not crash — must call callback with error."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", {}, None
            )

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None

    def test_http_500_calls_callback_with_error(self, monkeypatch):
        """HTTP 500 Internal Server Error must not crash."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", {}, None
            )

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None


# ── Malformed Response Tests ───────────────────────────────────────────────────

class TestMalformedResponses:
    """API responses that don't match the expected shape must call callback with error."""

    def test_missing_choices_key_calls_callback_with_error(self, monkeypatch):
        """Response with no 'choices' key must be caught and reported, not crash."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({"id": "abc", "choices": None})

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None
        assert "choices" in error.lower() or "api" in error.lower()

    def test_empty_choices_list_calls_callback_with_error(self, monkeypatch):
        """Response with choices=[] must report an error — nothing to extract."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({"id": "abc", "choices": []})

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None

    def test_missing_message_in_choice_calls_callback_with_error(self, monkeypatch):
        """choices[0] has no 'message' key must be caught, not crash."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({"id": "abc", "choices": [{"no": "message here"}]})

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None

    def test_missing_content_in_message_calls_callback_with_error(self, monkeypatch):
        """choices[0].message has no 'content' key — must call callback with error."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({
                "id": "abc",
                "choices": [{"message": {"role": "assistant"}}]
            })

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        _, error = callback_store[0]
        assert error is not None
        assert "content" in error.lower()

    def test_content_is_none_returns_empty_string(self, monkeypatch):
        """choices[0].message.content is None — must return '', not crash."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({
                "id": "abc",
                "choices": [{"message": {"content": None}}]
            })

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        text, error = callback_store[0]
        assert error is None
        assert text == ""

    def test_content_is_int_becomes_string(self, monkeypatch):
        """choices[0].message.content is an int — must become string."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({
                "id": "abc",
                "choices": [{"message": {"content": 12345}}]
            })

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("test prompt", callback_store)

        assert len(callback_store) == 1
        text, error = callback_store[0]
        assert error is None
        assert text == "12345"


# ── Happy Path ─────────────────────────────────────────────────────────────────

class TestHappyPath:
    """Confirm the API response parsing works when response is well-formed."""

    def test_valid_response_returns_improved_text(self, monkeypatch):
        """A valid API response must call callback with the improved text."""
        callback_store: list = []

        def fake_open(req, timeout=None):
            return FakeResponse({
                "id": "abc",
                "choices": [{"message": {"content": "This is the improved prompt."}}]
            })

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("improve this", callback_store)

        assert len(callback_store) == 1
        text, error = callback_store[0]
        assert error is None
        assert text == "This is the improved prompt."

    def test_multiline_improved_text_preserved(self, monkeypatch):
        """Multiline improved output must be preserved exactly."""
        callback_store: list = []

        multiline = "Line one.\nLine two.\nLine three."
        def fake_open(req, timeout=None):
            return FakeResponse({
                "id": "abc",
                "choices": [{"message": {"content": multiline}}]
            })

        monkeypatch.setattr("utils.improve._load_config", lambda: {"apiKey": "valid-key"})
        monkeypatch.setattr("utils.improve.urllib.request.urlopen", fake_open)

        call_improve("improve this", callback_store)

        text, _ = callback_store[0]
        assert text == multiline
