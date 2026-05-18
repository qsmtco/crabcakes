# tests/test_quoting.py
# Tests for utils/quoting.py — _parse_quoted_payload() per A2A_QUOTED_PAYLOAD_SPEC §7.1.
#
# Pure function tests — no GTK, no network, no agent dependencies.

import pytest

from utils.quoting import _parse_quoted_payload


class TestParseQuotedPayload:
    """12 test cases from A2A_QUOTED_PAYLOAD_SPEC §7.1."""

    def test_case1_simple_hello(self):
        payload, pos = _parse_quoted_payload('"hello"', 0)
        assert payload == "hello"
        assert pos == 7

    def test_case2_hello_world(self):
        payload, pos = _parse_quoted_payload('"hello world"', 0)
        assert payload == "hello world"
        assert pos == 13

    def test_case3_empty_payload(self):
        payload, pos = _parse_quoted_payload('""', 0)
        assert payload is None
        assert pos == 0

    def test_case4_em_dash_preserved(self):
        payload, pos = _parse_quoted_payload('"fix the \u2014 bug"', 0)
        assert payload == "fix the \u2014 bug"

    def test_case5_em_dash_phrase(self):
        payload, pos = _parse_quoted_payload('"use a dict \u2014 not a list"', 0)
        assert payload == "use a dict \u2014 not a list"

    def test_case7_escaped_quote(self):
        payload, pos = _parse_quoted_payload('"she said \\"use a dict\\""', 0)
        assert payload == 'she said "use a dict"'

    def test_case8_escaped_backslash(self):
        payload, pos = _parse_quoted_payload('"path\\\\to\\\\file"', 0)
        assert payload == "path\\to\\file"

    def test_case9_literal_backslash_n(self):
        payload, pos = _parse_quoted_payload('"\\n not a newline"', 0)
        assert payload == "\\n not a newline"

    def test_case10_payload_at_limit(self):
        big = "x" * 4096
        text = f'"{big}"'
        payload, pos = _parse_quoted_payload(text, 0)
        assert payload == big
        assert len(payload) == 4096

    def test_case11_payload_over_limit(self):
        big = "x" * 4097
        text = f'"{big}"'
        payload, pos = _parse_quoted_payload(text, 0)
        assert payload == big
        assert len(payload) == 4097
        # Note: truncation and ellipsis marker is the caller's job (spec §4.5)

    def test_case12_unclosed_quote(self):
        payload, pos = _parse_quoted_payload('"unclosed quote', 0)
        assert payload is None
        assert pos == 0

    def test_non_quote_start_returns_none(self):
        payload, pos = _parse_quoted_payload("hello", 0)
        assert payload is None
        assert pos == 0

    def test_offset_start(self):
        text = 'prefix "payload" suffix'
        payload, pos = _parse_quoted_payload(text, 7)
        assert payload == "payload"
        assert pos == 16
