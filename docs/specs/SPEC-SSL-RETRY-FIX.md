# SPEC: Three-Layer SSL Mid-Stream Drop Recovery

**Date:** 2026-06-30
**Status:** Approved
**Scope:** `agent/runtime.py` only

## Problem

When a provider (notably MiniMax, but also OpenAI, Anthropic, OpenRouter, ZAI) drops
the TLS connection mid-response, the user sees a raw `SSLEOFError` traceback in chat
instead of a graceful error message. The existing retry logic in `_urlopen_with_ssl_retry`
only catches `ssl.SSLError` directly — but `urllib.request.do_open()` wraps `OSError`
(including `ssl.SSLError`) in `urllib.error.URLError` during the request-send phase.
`URLError(SSLEOFError)` sails through without retrying.

Additionally, there is zero retry coverage for mid-stream drops — SSL errors that happen
*after* `urlopen()` returns, during SSE body iteration.

Finally, the error path dumps raw exception text into chat (`<urlopen error EOF occurred
in violation of protocol (_ssl.c:2406)>`).

## Five Design Points

### Layer 1: `_urlopen_with_ssl_retry` (connection establishment)

1. Add `"EOF occurred in violation of protocol"` to `_RETRYABLE_SSL_ERRORS` frozenset.
   Also add `"UNEXPECTED_EOF_WHILE_READING"` as a forward-compatible token.
2. Add `except urllib.error.URLError` branch that unwraps `.reason` to check for SSL
   errors via `_is_retryable_ssl_error()`. This is the **key bug**: `do_open` wraps
   `OSError` in `URLError`, so the old `except ssl.SSLError` never fires.
3. Add `except _RETRYABLE_OSERROR_TYPES` branch for `ConnectionResetError` and
   `BrokenPipeError` (TCP-level resets that are NOT `ssl.SSLError` subclasses).
4. Add `_RETRYABLE_OSERROR_TYPES` as a tuple of types (NOT a list — must be a tuple
   for `isinstance` and `except` syntax).

### Layer 2: `_stream_with_ssl_retry` (mid-stream body iteration)

5. New generator wrapper that catches `(ssl.SSLError, ConnectionResetError,
   BrokenPipeError, urllib.error.URLError)` during SSE body iteration and retries
   the **entire** streaming call (new HTTP request + new SSE stream).
   - **Suppresses retry once any `text_delta` event has been yielded** — prevents
     garbled duplicate text in the UI (the user already saw partial text).
   - In that case, re-raise the error so the caller surfaces a message.
6. Wire into `_call_llm_streaming` by wrapping the `for ev in streamer(...)` loop:
   ```python
   for ev in _stream_with_ssl_retry(streamer, base_url=..., api_key=..., model=...,
                                     messages=..., tools=..., timeout=..., x_title=...):
   ```

### Layer 3: `_friendly_error_message` (user-facing error text)

7. New function that translates raw exceptions into user-facing messages:
   - SSL EOF → "Connection to the AI provider was lost mid-response. Please try
     sending your message again."
   - Connection reset → "Connection to the AI provider was reset. Please try
     sending your message again."
   - Non-network errors pass through unchanged as `str(exc)`.
8. Wire into the error handler in `_run_loop`:
   ```python
   msg = _friendly_error_message(e)
   self._dispatch(self._on_error, session_key, msg)
   ```

### Helpers

9. `_is_retryable_ssl_error(exc)` — walks the exception chain (`exc` → `.reason` →
   `.__cause__`) and returns `True` if any candidate is a retryable `ssl.SSLError`
   (token match against `_RETRYABLE_SSL_ERRORS`) or a `_RETRYABLE_OSERROR_TYPES`
   instance.

### Bookkeeping

10. Add `import urllib.error` at the top of the SSE section (near `import ssl`).
11. Append `"_stream_with_ssl_retry"`, `"_is_retryable_ssl_error"`,
    `"_friendly_error_message"` to `__all__`.

## Constraints

- `_RETRYABLE_OSERROR_TYPES` must remain a tuple (for `isinstance` and `except`).
- `_MAX_SSL_RETRIES = 3` and `_SSL_RETRY_BASE_MS = 500` are existing constants — do not change.
- `_PROVIDER_STREAMERS` maps `"openai"`, `"minimax"`, `"anthropic"`, `"openrouter"`, `"zai"` to their streaming generators.
- `_urlopen_with_ssl_retry` covers only the initial `urlopen()` call. Mid-stream drops
  are Layer 2's job.
- No mid-stream replay after partial text: once `text_delta` has been yielded, a retry
  would produce garbled output.

## Acceptance Criteria

1. `_is_retryable_ssl_error(ssl.SSLEOFError("EOF occurred in violation of protocol"))` returns `True`
2. `_is_retryable_ssl_error(urllib.error.URLError(ssl.SSLEOFError(...)))` returns `True`
3. `_is_retryable_ssl_error(urllib.error.URLError("DNS failure"))` returns `False`
4. `_is_retryable_ssl_error(ConnectionResetError("reset"))` returns `True`
5. `_is_retryable_ssl_error(ssl.SSLError("SSLV3_ALERT_CERTIFICATE_UNKNOWN"))` returns `False`
6. `_friendly_error_message(ssl.SSLEOFError(...))` contains "Connection to the AI provider was lost"
7. `_friendly_error_message(ValueError("bad"))` returns `"bad"`
8. `_stream_with_ssl_retry` retries when streamer raises SSL error before any `text_delta`
9. `_stream_with_ssl_retry` does NOT retry once `text_delta` has been yielded
10. All existing tests pass (79 in `test_agent_runtime.py`, 2358+ in full suite)
11. `python3 -c "import ast; ast.parse(open('agent/runtime.py').read())"` passes
