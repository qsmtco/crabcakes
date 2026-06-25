# PHASE 3 — Add Streaming Regression Tests

## Objective
Add three new tests to `tests/test_agent_runtime.py` to prevent regression
of the W2 and W3 bugs in `_stream_anthropic_events`.

## Files to Read First
- `/home/q/projects/crabcakes/tests/test_agent_runtime.py`
- `/home/q/projects/crabcakes/agent/runtime.py` (lines 667–775)
- `/home/q/projects/crabcakes/docs/specs/SPEC-RUNTIME-HARDENING-AUDIT.md` (W2, W3)

## Step 1 — Read Existing Test File

Run: `wc -l /home/q/projects/crabcakes/tests/test_agent_runtime.py`
Then read it to understand existing patterns and imports.

## Step 2 — Add Three Tests

Add these tests at the end of the file (before any `if __name__` block):

```python
class TestStreamAnthropicEvents:
    """Regression tests for _stream_anthropic_events."""

    def test_no_stream_options_in_anthropic_payload(self):
        """Anthropic API does not support stream_options — must not be in payload."""
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            # Return a minimal streaming response
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                # Provide minimal args
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=[{"role": "user", "content": "hello"}],
                    tools=None,
                    system_prompt="you are a helpful assistant",
                    timeout=30.0,
                ))
        # Verify no stream_options in captured request data
        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        assert "stream_options" not in payload, (
            "stream_options must not be sent to Anthropic API"
        )

    def test_anthropic_messages_are_converted(self):
        """Messages must be converted to Anthropic format, not passed raw."""
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        raw_messages = [{"role": "user", "content": "hello"}]

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=raw_messages,  # raw dicts
                    tools=None,
                    system_prompt="you are a helpful assistant",
                    timeout=30.0,
                ))

        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        # After conversion, messages should be a list
        assert isinstance(payload["messages"], list)
        # Each message should have role + content (Anthropic format)
        for msg in payload["messages"]:
            assert "role" in msg
            assert "content" in msg

    def test_anthropic_tools_are_converted(self):
        """Tools must be converted to Anthropic format, not passed raw."""
        import json
        from unittest.mock import patch, MagicMock
        from agent.runtime import _stream_anthropic_events

        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            body = b'data: {"type": "message_stop"}\n\n'
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.iter_lines = MagicMock(return_value=iter([body]))
            return resp

        raw_tools = [{
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {}}
        }]

        with patch("agent.runtime._urlopen_with_ssl_retry", side_effect=fake_urlopen):
            with patch("agent.runtime._sse_lines", return_value=iter([
                b'data: {"type": "message_stop"}\n\n'
            ])):
                list(_stream_anthropic_events(
                    base_url="https://api.anthropic.com",
                    api_key="test-key",
                    model="claude-3-5-sonnet-20241022",
                    messages=[{"role": "user", "content": "hello"}],
                    tools=raw_tools,  # raw tool dicts
                    system_prompt="you are a helpful assistant",
                    timeout=30.0,
                ))

        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        # After conversion, tools should use input_schema (Anthropic format)
        assert "tools" in payload
        for tool in payload["tools"]:
            assert "input_schema" in tool, "Anthropic tools must have input_schema"
            assert "name" in tool
```

## Step 3 — Verify Tests Load

Run:
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_agent_runtime.py -v --collect-only 2>&1 | grep "TestStreamAnthropicEvents"
```

The three tests should be discovered. If import errors occur, fix them.

## What NOT to Change
- Do NOT modify `_call_anthropic` or any other runtime function
- Do NOT delete existing tests
