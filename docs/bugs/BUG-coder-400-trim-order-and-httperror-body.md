# BUG: Coder 400 Bad Request — Stale Messages + HTTPError Body Lost

**Date:** 2026-07-04
**File:** `agent/runtime.py`
**Symptom:** Coder fails with "HTTP Error 400: Bad Request" once the conversation exceeds the model's context window. Supervisor is unaffected (~40K tokens vs Coder's ~428K).

## Bug #1 — CRITICAL: API messages captured before compaction

`messages = conv.to_api_messages()` runs at **line 2043**, then `_context_strategy.compact()` trims `conv.messages` at **line 2055**, then `_prepare_kb_synthesis(...)` at **line 2116** builds `messages_for_call` from the **stale local `messages`**, and that stale list is what reaches `_call_llm` → API. Compaction has no effect on the wire payload.

```python
# line 2043
messages = conv.to_api_messages()
# line 2055 — compacts conv.messages in place
self._context_strategy.compact(conv, soft_ceiling)
# line 2116 — uses stale `messages`
messages_for_call, kb_context, _kb_cache_for_turn = self._prepare_kb_synthesis(
    conv, text, messages, _kb_cache_for_turn
)
response = self._call_llm(session_key, messages_for_call, tools)
```

**Fix:** rebuild after compact. Move `messages = conv.to_api_messages()` to immediately before `_prepare_kb_synthesis`, or re-assign: `messages = conv.to_api_messages()` after the compact block.

## Bug #2 — HIGH: HTTPError response body never read

`_stream_openai_events` (line 877) wraps `urlopen` with no HTTPError handling:

```python
# line 877
with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
    for line in _sse_lines(resp):
```

On a 4xx/5xx, `urllib.request.urlopen` raises `urllib.error.HTTPError` (a subclass of `URLError`). It propagates through `_stream_with_ssl_retry` → `_call_llm_streaming` → `_call_llm` → the bare `except Exception` at **line 2410**, which calls `_friendly_error_message(e)`. That helper (line 637) walks `exc.reason` and `exc.__cause__` — it never calls `exc.read()`, so the provider's actual error body (often containing the real reason: token-limit-exceeded, invalid tool id, etc.) is dropped and the user sees only `"HTTP Error 400: Bad Request"`.

**Fix:** in `_stream_openai_events` (and `_stream_minimax_events` at line 928 — same shape), read the body inside the `except HTTPError` handler before re-raising:

```python
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    logger.error("Provider HTTP %d from %s: %s", e.code, req.full_url, body[:500])
    raise
```

## Why supervisor doesn't hit this

Supervisor: ~160 messages ≈ 40K tokens — well under the 256K ceiling, so the compaction no-op path keeps things stable. Coder: ~1705 messages ≈ 428K tokens — exceeds the limit, and Bug #1 means the trim never reaches the API, so the request blows past `max_tokens` and the provider returns 400.

## Verification

- Bug #1: add a log of `len(messages_for_call)` before `_call_llm`; confirm it equals `len(conv.messages)` after compact when over the soft ceiling.
- Bug #2: force a 400 (e.g. temporarily set `model_max = 32` in a test session) and assert the log captures the provider body, not just `e.code`.