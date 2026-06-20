# tests/test_low345_gateway_hardening.py
# Tests for Phase 4-2: gateway/client.py hardening (LOW-3, LOW-4, LOW-5).
#
# LOW-3: GatewayClient constructor accepts scopes= parameter; handshake uses it.
# LOW-4: Raw gateway frames are redacted before logging; malformed JSON warning truncated.
# LOW-5: on_event payloads are validated before dispatch; wrong types are dropped.

import pytest

import gateway.client as gc


# ═══════════════════════════════════════════════════════════════════
#  LOW-3 — scopes as constructor parameter
# ═══════════════════════════════════════════════════════════════════

class TestLow3EmptyScopes:
    """LOW-3 BUG #3: empty scopes list must raise ValueError."""

    def test_low3_empty_scopes_raises(self):
        """GatewayClient(scopes=[]) must raise ValueError."""
        with pytest.raises(ValueError, match="LOW-3: scopes must be non-empty"):
            gc.GatewayClient(
                url="ws://localhost:18789",
                on_connect=lambda: None,
                on_error=lambda e: None,
                on_event=lambda n, p: None,
                scopes=[],
            )


class TestLow3ScopesConstructor:
    """LOW-3: GatewayClient.__init__ accepts a scopes= parameter."""

    def test_low3_constructor_default_scopes(self):
        """With no scopes= argument, _scopes must default to DEFAULT_SCOPES."""
        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
        )
        assert client._scopes == gc.DEFAULT_SCOPES, (
            f"Expected {gc.DEFAULT_SCOPES}, got {client._scopes}"
        )
        assert client._scopes_str == ",".join(gc.DEFAULT_SCOPES)

    def test_low3_constructor_custom_scopes(self):
        """With scopes=["operator.pairing"], _scopes must contain only that."""
        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
            scopes=["operator.pairing"],
        )
        assert client._scopes == ["operator.pairing"]
        assert client._scopes_str == "operator.pairing"

    def test_low3_constructor_multiple_custom_scopes(self):
        """With scopes=["operator.admin","operator.pairing"], _scopes matches exactly."""
        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
            scopes=["operator.admin", "operator.pairing"],
        )
        assert client._scopes == ["operator.admin", "operator.pairing"]
        assert client._scopes_str == "operator.admin,operator.pairing"

    def test_low3_constructor_scopes_are_copied(self):
        """Passing scopes= list must be copied, not stored by reference."""
        original = ["operator.admin"]
        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
            scopes=original,
        )
        original.clear()
        assert client._scopes == ["operator.admin"], (
            "_scopes must be a copy, not a reference to the caller's list"
        )


# ═══════════════════════════════════════════════════════════════════
#  LOW-4 — log redaction
# ═══════════════════════════════════════════════════════════════════

class TestLow4LogRedaction:
    """LOW-4: _redact_gateway_log_preview scrubs sensitive keys from raw frames."""

    def test_low4_redact_apikey(self):
        """apiKey value must be replaced with *** in the output."""
        raw = '{"apiKey":"secret123","other":"x"}'
        result = gc._redact_gateway_log_preview(raw)
        assert "secret123" not in result, f"apiKey value leaked: {result}"
        assert '"***"' in result or "***" in result

    def test_low4_redact_apikey_case_insensitive(self):
        """apiKey variants (apiKey, api_key, APIKEY) are all redacted."""
        for key in ("apiKey", "api_key", "apikey", "APIKEY"):
            raw = f'{{"{key}":"hunter42"}}'
            result = gc._redact_gateway_log_preview(raw)
            assert "hunter42" not in result, f"Failed for {key}: {result}"
            assert "***" in result

    def test_low4_redact_token(self):
        """token value must be replaced with ***."""
        raw = '{"token":"mysecret","data":"ok"}'
        result = gc._redact_gateway_log_preview(raw)
        assert "mysecret" not in result
        assert "***" in result

    def test_low4_redact_device_token(self):
        """deviceToken and device_token must be redacted."""
        for key in ("deviceToken", "device_token"):
            raw = f'{{"{key}":"dev_tok_xyz"}}'
            result = gc._redact_gateway_log_preview(raw)
            assert "dev_tok_xyz" not in result

    def test_low4_redact_password(self):
        """password field must be redacted."""
        raw = '{"username":"alice","password":"s3cr3t"}'
        result = gc._redact_gateway_log_preview(raw)
        assert "s3cr3t" not in result

    def test_low4_redact_secret(self):
        """secret field must be redacted."""
        raw = '{"algorithm":"HS256","secret":"my-shared-secret"}'
        result = gc._redact_gateway_log_preview(raw)
        assert "my-shared-secret" not in result

    def test_low4_redact_truncation_respected(self):
        """Output length must not exceed input length."""
        raw = "x" * 1000
        result = gc._redact_gateway_log_preview(raw)
        assert len(result) <= len(raw)

    def test_low4_redact_no_op_for_clean_input(self):
        """Input without sensitive keys is returned unchanged (minus redaction pass)."""
        raw = '{"type":"event","event":"chat.final","payload":{}}'
        result = gc._redact_gateway_log_preview(raw)
        # Only sensitive parts are redacted; structural JSON remains
        assert "chat.final" in result
        assert "event" in result

    def test_low4_redact_key_without_value(self):
        """A key with no value is handled gracefully."""
        raw = '{"apiKey"}'
        result = gc._redact_gateway_log_preview(raw)
        # Should not raise — returns a string
        assert isinstance(result, str)

    def test_low4_redact_url_query_apiKey(self):
        """apiKey=secret in URL query string must be redacted to apiKey=***."""
        raw = "GET /api/v1/foo?apiKey=secret123&limit=10 HTTP/1.1"
        result = gc._redact_gateway_log_preview(raw)
        assert "secret123" not in result, f"apiKey value leaked in query string: {result}"
        assert "apiKey=***" in result, f"Expected apiKey=*** in result: {result}"
        # limit=10 should NOT be redacted (not a sensitive key)
        assert "limit=10" in result, f"Non-sensitive param was incorrectly redacted: {result}"

    def test_low4_redact_bearer_token(self):
        """Authorization: Bearer <token> must be redacted to Authorization: Bearer ***."""
        raw = 'Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJhYmMifQ.sig'
        result = gc._redact_gateway_log_preview(raw)
        assert "eyJhbGciOiJSUzI1NiJ9" not in result, f"Bearer token leaked: {result}"
        assert "Bearer ***" in result, f"Expected 'Bearer ***' in result: {result}"

    def test_low4_malformed_json_warning_truncated(self):
        """Malformed JSON warning (via _redact_gateway_log_preview(raw[:80])) is ≤ 80 chars."""
        long_raw = '{"apiKey":"a_very_long_value_that_exceeds_eighty_chars","other":"x"}'
        preview = gc._redact_gateway_log_preview(long_raw[:80])
        assert len(preview) <= 80, (
            f"Malformed JSON preview exceeds 80 chars: {len(preview)} > 80: {preview!r}"
        )


# ═══════════════════════════════════════════════════════════════════
#  LOW-5 — event payload validation
# ═══════════════════════════════════════════════════════════════════

class TestLow5ValidateEvent:
    """LOW-5: _validate_event rejects wrong-type events before dispatch."""

    def test_low5_validate_event_string_name_valid_payload(self):
        """("chat.final", {"x":1}) is valid and returns True."""
        assert gc._validate_event("chat.final", {"x": 1}) is True

    def test_low5_validate_event_agent_start(self):
        """("agent.start", {}) is valid."""
        assert gc._validate_event("agent.start", {}) is True

    def test_low5_validate_event_agent_end(self):
        """("agent.end", {"reason":"complete"}) is valid."""
        assert gc._validate_event("agent.end", {"reason": "complete"}) is True

    def test_low5_validate_event_empty_name(self):
        """("", {"x":1}) must return False (empty name)."""
        assert gc._validate_event("", {"x": 1}) is False

    def test_low5_validate_event_none_name(self):
        """(None, {}) must return False (non-string name)."""
        assert gc._validate_event(None, {}) is False

    def test_low5_validate_event_int_name(self):
        """(123, {}) must return False (non-string name)."""
        assert gc._validate_event(123, {}) is False

    def test_low5_validate_event_non_dict_payload_string(self):
        """("chat.final", "not-a-dict") must return False."""
        assert gc._validate_event("chat.final", "not-a-dict") is False

    def test_low5_validate_event_non_dict_payload_list(self):
        """("chat.final", [1,2,3]) must return False."""
        assert gc._validate_event("chat.final", [1, 2, 3]) is False

    def test_low5_validate_event_non_dict_payload_none(self):
        """("chat.final", None) must return False."""
        assert gc._validate_event("chat.final", None) is False

    def test_low5_validate_event_unknown_name_passes(self):
        """("new.event.v2", {"x":1}) returns True (unknown names pass through)."""
        assert gc._validate_event("new.event.v2", {"x": 1}) is True

    def test_low5_validate_event_unknown_name_with_wrong_payload_type(self):
        """("new.event.v2", "bad") returns False (payload type still checked)."""
        assert gc._validate_event("new.event.v2", "bad") is False

    def test_low5_validate_event_tick(self):
        """("tick", {}) is valid."""
        assert gc._validate_event("tick", {}) is True

    def test_low5_validate_event_approve_required(self):
        """("approve.required", {"id":"abc"}) is valid."""
        assert gc._validate_event("approve.required", {"id": "abc"}) is True

    def test_low5_validate_event_message_received(self):
        """("message.received", {"text":"hi"}) is valid."""
        assert gc._validate_event("message.received", {"text": "hi"}) is True
