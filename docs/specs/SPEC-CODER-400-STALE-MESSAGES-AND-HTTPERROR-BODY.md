# SPEC: Coder 400 Bad Request — Stale Messages After Compaction + HTTPError Body Lost

**Date:** 2026-07-04
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/bugs/BUG-coder-400-trim-order-and-httperror-body.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance: changes are limited to `agent/runtime.py` only.
> No UI, no gateway, no model changes. Two bugs in the `_run_loop` → `_call_llm`
> → streaming chain. Per ARCHITECTURE.md §3, `agent/runtime.py` is a 2,905-line
> module owning the local agent runtime tool loop. No cross-module imports needed.

---

## 1. Overview

**Problem:** Coder fails with "HTTP Error 400: Bad Request" when the conversation
exceeds the model's context window. Supervisor (smaller conversation) is unaffected.

Two bugs cause this:
1. **Bug #1 (CRITICAL):** `messages = conv.to_api_messages()` runs **before**
   `self._context_strategy.compact(conv, soft_ceiling)`. The compact trims
   `conv.messages` in place, but the captured `messages` list is never rebuilt.
   Compaction has **no effect** on the wire payload.
2. **Bug #2 (HIGH):** When the provider returns HTTP 4xx/5xx, the response body
   (containing the real error: token-limit-exceeded, invalid tool id, etc.) is
   never read. `_friendly_error_message` only handles SSL/network errors; for
   `HTTPError` it falls through to `str(exc)` → `"HTTP Error 400: Bad Request"`.

**Solution summary:**
- Bug #1: Move `messages = conv.to_api_messages()` to after the compact block
  (or re-assign after compact).
- Bug #2: In `_stream_openai_events` and `_stream_minimax_events`, wrap
  `_urlopen_with_ssl_retry` in a `try/except urllib.error.HTTPError` that
  reads `e.read()` and logs the body before re-raising.

**Scope:**
| In scope | Out of scope |
|---|---|
| Fix stale-messages capture order in `_run_loop` | Refactoring compaction strategy |
| Add HTTPError body logging in `_stream_openai_events` | Adding new error recovery paths |
| Add HTTPError body logging in `_stream_minimax_events` | Changing `_friendly_error_message` behavior |
| | Changing `_stream_with_ssl_retry` retry logic |

## 2. Changes by File

### 2.1 `agent/runtime.py` — Bug #1: Stale messages after compaction

**What changes:** In `_run_loop` (method of `AgentRuntime`), lines 2043-2116.
Move `messages = conv.to_api_messages()` from before the compact block to
immediately before the `_prepare_kb_synthesis` call.

**Current code (lines 2041-2116, annotated):**

```python
                iteration += 1
                logger.debug("[tool-loop] sk=%s iteration=%d/%d", session_key, iteration, max_iter)

                # Build API messages
                from models.conversation import MessageRole
                messages = conv.to_api_messages()          # ← line 2043: captured BEFORE compact

                # §0: Pluggable context strategy — compaction before each LLM call.
                ...
                soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)
                model_max = hard_ceiling
                self._context_strategy.compact(conv, soft_ceiling)  # ← line 2055: trims conv.messages
                ...  # telemetry block (lines 2057-2094)
                ...  # tool definitions (lines 2096-2106)
                ...  # MCP tools (lines 2108-2113)

                # KB synthesis — passes stale `messages`
                messages_for_call, kb_context, _kb_cache_for_turn = self._prepare_kb_synthesis(
                    conv, text, messages, _kb_cache_for_turn     # ← uses pre-compact messages
                )
                response = self._call_llm(session_key, messages_for_call, tools)
```

**New code:**

```python
                iteration += 1
                logger.debug("[tool-loop] sk=%s iteration=%d/%d", session_key, iteration, max_iter)

                # §0: Pluggable context strategy — compaction before each LLM call.
                ...
                soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)
                model_max = hard_ceiling
                self._context_strategy.compact(conv, soft_ceiling)
                ...  # telemetry block unchanged
                ...  # tool definitions unchanged
                ...  # MCP tools unchanged

                # Build API messages AFTER compact so the wire payload reflects
                # the trimmed conversation. Bug fix: was captured before compact().
                from models.conversation import MessageRole
                messages = conv.to_api_messages()

                # KB synthesis
                messages_for_call, kb_context, _kb_cache_for_turn = self._prepare_kb_synthesis(
                    conv, text, messages, _kb_cache_for_turn
                )
                response = self._call_llm(session_key, messages_for_call, tools)
```

**Imports required:** None new. `MessageRole` and `conv.to_api_messages()` already
exist in scope.

**Line count estimate:** ~5 lines moved, 2 comment lines changed.

**Verification:** Read `conv.to_api_messages()` (line 222 of `models/conversation.py`);
it iterates `self.messages` and serializes each to a dict. Calling it after `compact()`
means the serialized list reflects the trimmed conversation. Calling it before means
the compact has no effect. Trace confirmed.

---

### 2.2 `agent/runtime.py` — Bug #2: HTTPError response body lost in `_stream_openai_events`

**What changes:** Add `try/except urllib.error.HTTPError` around the
`_urlopen_with_ssl_retry` context manager at line 877. Read the response body
from the exception object, log it, then re-raise.

**Current code (lines 876-894):**

```python
    with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
        for line in _sse_lines(resp):
            ev = _parse_sse_line(line)
            ...
```

**New code:**

```python
    try:
        resp = _urlopen_with_ssl_retry(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "(could not read body)"
        logger.error(
            "Provider HTTP %d from %s (model=%s): %s",
            e.code, req.full_url, model, body[:500],
        )
        raise
    with resp:
        for line in _sse_lines(resp):
            ev = _parse_sse_line(line)
            ...
```

**Imports required:** `urllib` is already imported at module level (line 25:
`import urllib.error`). No new imports.

**Line count estimate:** +10 lines.

**Exception trace verified:** `_urlopen_with_ssl_retry` (line 683) catches
`urllib.error.URLError`, checks `_is_retryable_ssl_error`, and re-raises on
False. `HTTPError` is a subclass of `URLError` with a non-SSL `.reason` →
`_is_retryable_ssl_error` returns False → exception propagates. The existing
`except urllib.error.URLError` in `_stream_with_ssl_retry` (line 811) also
re-raises HTTPError (non-SSL, not retryable). The new `except urllib.error.HTTPError`
in `_stream_openai_events` catches it BEFORE `_stream_with_ssl_retry` can wrap it,
logs the body, and re-raises — preserving the existing error flow through
`_call_llm_streaming` → `_call_llm` → `except Exception` at line 2410 →
`_friendly_error_message(e)`. The user-friendliness of the error message is
unchanged (still `str(exc)` for HTTPError), but the log now contains the provider's
actual error body for debugging.

---

### 2.3 `agent/runtime.py` — Bug #2: HTTPError response body lost in `_stream_minimax_events`

**What changes:** Same as §2.2, applied to the `_stream_minimax_events` function
at line 928. Identical pattern — `_urlopen_with_ssl_retry(req, timeout=timeout) as resp:`
with no HTTPError handling.

**Current code (lines 927-928):**

```python
    with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
        # MiniMax may return a body-level error with HTTP 200 (not SSE).
```

**New code:**

```python
    try:
        resp = _urlopen_with_ssl_retry(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "(could not read body)"
        logger.error(
            "Provider HTTP %d from %s (model=%s): %s",
            e.code, req.full_url, model, body[:500],
        )
        raise
    with resp:
        # MiniMax may return a body-level error with HTTP 200 (not SSE).
```

**Imports required:** None new.

**Line count estimate:** +10 lines.

### 2.4 `docs/bugs/BUG-coder-400-trim-order-and-httperror-body.md` — Mark resolved

**What changes:** Update status to RESOLVED, add resolution date and commit SHA
(placeholder, to be filled post-commit).

### Files NOT changed (already correct)

- `agent/context_strategy.py` — `compact()` is correct; trims `conv.messages` in place. No changes needed.
- `models/conversation.py` — `to_api_messages()` is correct; iterates `self.messages`. No changes needed.
- `agent/runtime.py:_friendly_error_message` (line 637) — handles SSL/network errors correctly. HTTPError body logging is done at the streamer level (closer to the source). No changes needed.
- `agent/runtime.py:_stream_with_ssl_retry` (line 750) — correctly re-raises non-SSL URLErrors. No changes needed.
- `agent/runtime.py:_urlopen_with_ssl_retry` (line 683) — correctly re-raises non-retryable URLErrors. No changes needed.
- `agent/runtime.py:_call_llm` (line 2444) — correctly delegates to `_call_llm_streaming` and propagates exceptions to `_run_loop`. No changes needed.
- `agent/runtime.py:_call_llm_streaming` (line 2570) — correctly iterates the streaming generator. No changes needed.

## 3. Data Flow

### Bug #1: Before fix (broken)

```
user message → _run_loop
  → conv.to_api_messages()          # captures 428K-token list
  → _context_strategy.compact()      # trims conv.messages to 204K tokens
  → _prepare_kb_synthesis(..., stale_messages)  # passes 428K list
  → _call_llm(..., 428K_msg_list)    # API receives OVER-limit request
  → provider returns HTTP 400
  → except Exception (line 2410) → "HTTP Error 400: Bad Request"
```

### Bug #1: After fix (correct)

```
user message → _run_loop
  → _context_strategy.compact()     # trims conv.messages to 204K tokens
  → conv.to_api_messages()          # captures 204K-token list
  → _prepare_kb_synthesis(..., fresh_messages)  # passes 204K list
  → _call_llm(..., 204K_msg_list)   # API receives UNDER-limit request
  → provider returns 200 with streaming response
```

### Bug #2: After fix

```
_stream_openai_events / _stream_minimax_events
  → try: _urlopen_with_ssl_retry()
  → except HTTPError as e:
      body = e.read().decode()      # reads provider error body
      logger.error("Provider HTTP %d: %s", e.code, body)  # logs real reason
      raise                         # preserves existing error chain
  → response body diagnostic logged, not lost
```

## 4. File Change Summary

| File | Change type | Lines | Risk |
|---|---|---|---|
| `agent/runtime.py` | Move `messages = conv.to_api_messages()` after compact | ~5 moved | LOW — reorder only, no logic change |
| `agent/runtime.py` | Add HTTPError catch in `_stream_openai_events` | +10 | LOW — catch-log-reraise, preserves error flow |
| `agent/runtime.py` | Add HTTPError catch in `_stream_minimax_events` | +10 | LOW — identical pattern |
| `docs/bugs/BUG-coder-400-...` | Mark resolved | ~3 | NONE — documentation only |

## 5. Implementation Order

1. **Bug #1:** Move `messages = conv.to_api_messages()` in `_run_loop` (lines ~2043 → after line ~2113).
2. **Bug #2:** Add HTTPError catch in `_stream_openai_events` (line ~877).
3. **Bug #2:** Add HTTPError catch in `_stream_minimax_events` (line ~928).
4. **Verify:** Run `pytest tests/test_agent_runtime.py -q` and paste actual output.
5. **Mark bug doc resolved.**

## 6. Acceptance Criteria

- [ ] After compaction trims messages, the wire payload to `_call_llm` reflects the trimmed count (not the pre-compact count).
- [ ] HTTP 4xx/5xx responses log the provider's error body (not just status code) at ERROR level.
- [ ] Existing error flow is unchanged: HTTPError still reaches `_run_loop`'s `except Exception` → `_friendly_error_message` → dispatched to user.
- [ ] No regression in existing tests (`pytest tests/test_agent_runtime.py` — paste output).
- [ ] `_stream_openai_events` and `_stream_minimax_events` have identical HTTPError handling.
- [ ] Coder with large conversation no longer hits HTTP 400 from context overflow.

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| HTTPError body is binary/garbled | `errors="replace"` in decode, body[:500] truncation — safe |
| HTTPError.read() itself raises | Inner `try/except Exception` catches it → "(could not read body)" |
| Compaction is a no-op (conversation under budget) | `to_api_messages()` after compact returns same list as before — no regression |
| Multiple compactions in one tool loop iteration | Only one `to_api_messages()` call per iteration — always after the single compact() call |
| Non-streaming path | Unaffected — the non-streaming `_call_*` functions are not generators and don't use `_urlopen_with_ssl_retry` in the same way |

## 8. ARCHITECTURE.md Updates Required

None. These are bug fixes within `agent/runtime.py`'s existing responsibility.
No new public functions, no module restructuring, no new imports.

---

## Rule 9 — Spec Self-Audit

1. **Does every code sample work against the current codebase?**
   - Bug #1: `conv.to_api_messages()` exists at line 222 of `models/conversation.py`, iterates `self.messages`. Compacting `conv.messages` in place then calling `to_api_messages()` produces the trimmed list. ✅
   - Bug #2: `_urlopen_with_ssl_retry` at line 683 raises `HTTPError` (subclass of `URLError`) when `_is_retryable_ssl_error` returns False. `_is_retryable_ssl_error` (line 566) returns False for HTTPError (not SSL, not in `_RETRYABLE_OSERROR_TYPES`). `e.read()` on HTTPError reads the response body. ✅
   - Both streamers use `urllib.error.HTTPError` which is importable (module-level `import urllib.error` at line 25). ✅

2. **Did I catch all exception types?**
   - `_urlopen_with_ssl_retry` can raise: `ssl.SSLError`, `urllib.error.URLError` (includes `HTTPError`), `ConnectionResetError`, `BrokenPipeError`. We only catch `HTTPError` (subclass of `URLError`); other exceptions continue to propagate unchanged. ✅
   - The inner `e.read()` try/except catches `Exception` as a safety net. ✅

3. **Did I verify key structures?**
   - `conv.messages` is `list[Message]` — confirmed by reading `models/conversation.py`. ✅
   - `_context_strategy.compact()` mutates `conv.messages` in place — confirmed by reading `agent/context_strategy.py:121-200`. ✅
   - `_prepare_kb_synthesis` returns `(messages_for_call, kb_context, new_cache)` — for non-helper agents returns `(messages, None, None)`. ✅

4. **Did I trace the data flow end-to-end?**
   - Traced: user message → `_run_loop` → `to_api_messages` → `compact` → `_prepare_kb_synthesis` → `_call_llm` → `_call_llm_streaming` → `_stream_with_ssl_retry` → `_stream_openai_events` → `_urlopen_with_ssl_retry` → HTTPError → `except Exception` in `_run_loop` → `_friendly_error_message`. ✅

5. **Would an implementer produce working code?**
   - Bug #1: exact line numbers, exact before/after, exact variable names. The implementer moves 3 lines and changes 1 comment. ✅
   - Bug #2: exact line numbers, exact try/except shape, exact log format. The implementer adds 10 lines to each streamer. ✅
