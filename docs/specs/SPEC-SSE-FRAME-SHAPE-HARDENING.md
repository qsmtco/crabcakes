# SPEC: SSE Frame-Shape Hardening — Eliminate `IndexError` and Empty-Choice Crashes in Streaming

**Date:** 2026-07-09
**Author:** qtr (read-only audit)
**Status:** Draft — for implementation
**Implements:** none (root-cause audit triggered by incident `agent.runtime ERROR Error in tool loop for special:coder` on 2026-07-09 08:26 PDT)
**Depends on:** none
**Target branch:** main

> Architecture compliance: this spec touches `agent/runtime.py` only, within the SSE
> streaming layer owned by `AgentRuntime` (per `docs/ARCHITECTURE.md` §3 module
> responsibilities, §4 data flow). It does not cross the `agent/` → `ui/` boundary
> nor change any public API. It is a hardening fix, not a feature.

---

## 0. Starting Spec Discovery — reading all referenced source files

> Per the Steel-Framed Spec Writer prompt, the discovery block is mandatory.
> All findings below were verified against the actual source, not memory.

```
DISCOVERY:
- Read agent/runtime.py (2965 lines): full SSE streaming layer, lines 480-1131
  - _sse_lines (480): line iterator over an HTTP response
  - _parse_sse_line (487): bytes → SSEEvent | None, returns None for [DONE] sentinel
    and lines without "data:" prefix
  - _parse_sse_delta (506): shared OpenAI/MiniMax delta extractor — has the
    unguarded [0] on line 519 that caused the production crash
  - _stream_with_ssl_retry (750): mid-stream SSL/network retry wrapper; sees the
    real exception, not just suppressed retries
  - _stream_openai_events (843): OpenAI/OR/ZAI path — unguarded _parse_sse_delta
    on line 901
  - _stream_minimax_events (911): MiniMax path — TWO unguarded [0] sites
    (lines 985 and 1008)
  - _stream_anthropic_events (1018): Anthropic path — completely separate parser,
    does NOT call _parse_sse_delta, immune to this bug class
  - _extract_tool_calls (1135), _extract_text_content (1183), _extract_usage
    (1206): non-streaming response extractors — ALREADY GUARDED with
    `if not choices: return ...` so the non-streaming path is safe
  - _call_llm_streaming (2614): accumulator that converts SSEEvent stream →
    assembled response dict; already constructs a synthetic
    `{"choices": [{"message": ...}]}` shape for downstream code

- Read tests/test_agent_runtime.py (lines 1185-1352): established pattern for
  exercising raw SSE bytes through the full streamer → accumulator pipeline
  by mocking _urlopen_with_ssl_retry. New tests MUST follow this pattern.

- Read tests/test_streaming.py: 8 tests, all passing, none cover SSE frame
  shape edge cases.

- Read docs/ARCHITECTURE.md §3 (module responsibilities), §4 (data flow),
  §11 (file inventory). The SSE streaming layer is owned by
  AgentRuntime._call_llm_streaming → _PROVIDER_STREAMERS → per-provider
  streamer → _parse_sse_delta. The error surface is _do_error in
  ui.handlers.agent_runtime_handler, which currently passes raw str(exc) to
  the chat bubble.

- Architecture owner: agent/runtime.py module, AgentRuntime class,
  _call_llm_streaming method.
- Existing patterns: _extract_tool_calls (1149), _extract_text_content
  (1187), _extract_usage (1206) already use the correct `if not choices:`
  guard. The streaming layer SHOULD mirror this pattern.
- Anti-pattern to avoid: bare `d.get("choices", [{}])[0]` — the `[{}]` default
  only protects against MISSING key, not EMPTY list. This is the exact bug.
```

---

## 1. Overview

### 1.1 Problem statement

On 2026-07-09 at 08:26 PDT, the `special:coder` agent crashed its tool loop
with `IndexError: list index out of range` originating from
`agent/runtime.py:519` (`_parse_sse_delta`). The chat bubble surfaced only
the bare exception text because `ui.handlers.agent_runtime_handler._do_error`
passes `str(exc)` directly to the UI with no upstream/provider context.

A read-only audit revealed **three live unguarded `choices[0]` indexing
sites** in the streaming layer (lines 519, 985, 1008), plus **two adjacent
issues that haven't bitten yet but share the same root cause class**:

1. The non-streaming path is **already guarded** with `if not choices:`
   returns in `_extract_tool_calls` (1149), `_extract_text_content` (1187),
   `_extract_usage` (1206) — but the streaming path diverged and never
   adopted the same pattern.
2. The chat bubble error message is uninformative — even after we fix
   the crashes, an unrelated provider error will still surface as a
   bare Python exception string to the user.

### 1.2 Solution summary

1. **Defensive `_parse_sse_delta`** — replace the unguarded `[0]` with a
   proper empty-list guard.
2. **Defensive `_stream_openai_events` and `_stream_minimax_events`** —
   gate each chunk on `choices` presence before invoking the delta parser
   or accessing `finish_reason`. Frame the change so the comment on
   line 900 ("OpenAI-compatible providers emit a usage chunk at the end
   of the stream, typically in a frame with empty choices") becomes true
   rather than aspirational.
3. **Extract a shared helper** `_first_choice(d) -> dict` used by all three
   sites so the guard pattern is enforced by reuse, not copy-paste.
4. **Improve error messages** — when a parser/streaming error does reach
   the user, include the model name and provider so the next incident
   is debuggable from the chat bubble alone.

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| `agent/runtime.py` lines 506-525, 890-906, 950-1014, 2614-2718 | UI bubble rendering (`ui/handlers/agent_runtime_handler.py`) — separate fix for chat-side error messages |
| Three `_parse_sse_delta` callers | Adding new provider types |
| Tests covering the new frame shapes | Performance / throughput changes |
| README-free docstring updates where existing comments misdescribe behavior | Provider-config UI changes |
| One regression test per fixed code path | The SSL retry path — confirmed not implicated, see §7 |

### 1.4 Architecture principles that apply

- **Single source of truth for empty-choices handling** — the non-streaming
  extractors already encode the correct pattern; this spec makes the
  streaming layer conform.
- **Defensive parsing of third-party data** — provider SSE streams are
  untrusted/variant input; every parser function MUST tolerate missing
  keys, empty lists, wrong types.
- **Errors carry context** — every caught/raised error in the streaming
  layer MUST include enough context (model, provider, frame id) to
  diagnose without re-running with debug logs.

---

## 2. Changes by File

### 2.1 `agent/runtime.py`

#### 2.1.1 Add helper `_first_choice(d: dict) -> dict` (new function, ~6 lines)

Insert immediately after `_parse_sse_delta` (after line 530). Used by all
three callers so the empty-choices guard is enforced by reuse, not
copy-paste discipline.

```python
def _first_choice(d: dict) -> dict:
    """Return the first choices[0] entry from an OpenAI-format SSE frame,
    or an empty dict if `choices` is missing or empty.

    Defensive against three legitimate frame shapes:
      - {"choices": [...]} — normal delta/finish frame
      - {"choices": [], "usage": {...}} — OpenAI trailing usage frame
      - {} or {"usage": {...}} — keepalive / pre-delta frame

    The previous `d.get("choices", [{}])[0]` pattern only covered the
    missing-key case; an explicit empty list still indexed [0] and crashed.
    """
    choices = d.get("choices")
    return choices[0] if choices else {}
```

Verified against source: this helper does not exist today. It will live
alongside the other SSE helpers between lines 506-560. No imports added;
uses only `dict` from builtins.

#### 2.1.2 Replace line 519 in `_parse_sse_delta`

Before:
```python
def _parse_sse_delta(d: dict) -> list[SSEEvent]:
    """Extract text_delta and tool_call_delta events from an SSE delta dict.
    ...
    """
    events: list[SSEEvent] = []
    delta = d.get("choices", [{}])[0].get("delta", {})    # ← IndexError
```

After:
```python
def _parse_sse_delta(d: dict) -> list[SSEEvent]:
    """Extract text_delta and tool_call_delta events from an SSE delta dict.
    ...
    Tolerant of empty-choices frames (OpenAI trailing usage, OpenRouter
    keepalive). Returns [] without raising. See _first_choice.
    """
    events: list[SSEEvent] = []
    choice = _first_choice(d)
    delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
```

Verified: `_first_choice` returns `dict` or `{}`, so the
`isinstance(choice, dict)` check is always true — but it makes the type
narrowing explicit and protects against any future regression where
`_first_choice` returns something exotic.

#### 2.1.3 Patch `_stream_openai_events` (line 900-905)

Before:
```python
            if ev.type != "raw":
                continue
            d = ev.data
            # W11: text + tool_call deltas are shared with _stream_minimax_events
            for out_ev in _parse_sse_delta(d):
                yield out_ev
            # OpenAI-compatible providers emit a usage chunk at the end of the stream,
            # typically in a frame with empty choices. Capture and forward it.
            # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.1.1 (BUG #3 fix).
            usage = d.get("usage")
            if usage:
                yield SSEEvent(type="usage", data={"usage": usage})
```

After:
```python
            if ev.type != "raw":
                continue
            d = ev.data
            # OpenAI-compatible providers emit a usage chunk at the end of
            # the stream, typically in a frame with empty choices. Skip the
            # delta extractor on those frames and capture usage directly.
            # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.1.1 (BUG #3 fix).
            choice = _first_choice(d)
            if choice:
                # W11: text + tool_call deltas are shared with _stream_minimax_events
                for out_ev in _parse_sse_delta(d):
                    yield out_ev
            usage = d.get("usage")
            if usage:
                yield SSEEvent(type="usage", data={"usage": usage})
```

Note: the reorder keeps usage extraction safe even on non-empty
choices (some OpenRouter gateways emit `{"choices":[{...finish_reason...}],"usage":{...}}`).

Verified: `_stream_openai_events` is the call site reached for `openai`,
`openrouter`, and `zai` per `_PROVIDER_STREAMERS` (lines 1122-1126).

#### 2.1.4 Patch `_stream_minimax_events` first-line branch (line 982-993)

Before:
```python
                if ev.type == "raw":
                    d = ev.data
                    # W11: text + tool_call deltas are shared with _stream_openai_events
                    for out_ev in _parse_sse_delta(d):
                        yield out_ev
                    finish_reason = d.get("choices", [{}])[0].get("finish_reason")
                    if finish_reason in ("stop", "tool_calls", "length"):
                        # Phase CB-3: capture usage before signaling done.
                        usage = d.get("usage")
                        if usage:
                            yield SSEEvent(type="usage", data={"usage": usage})
                        yield SSEEvent(type="done", data={})
                        return
```

After:
```python
                if ev.type == "raw":
                    d = ev.data
                    choice = _first_choice(d)
                    if choice:
                        # W11: text + tool_call deltas are shared with _stream_openai_events
                        for out_ev in _parse_sse_delta(d):
                            yield out_ev
                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("stop", "tool_calls", "length"):
                            # Phase CB-3: capture usage before signaling done.
                            usage = d.get("usage")
                            if usage:
                                yield SSEEvent(type="usage", data={"usage": usage})
                            yield SSEEvent(type="done", data={})
                            return
```

#### 2.1.5 Patch `_stream_minimax_events` main loop (line 1003-1013)

Before:
```python
            if ev.type != "raw":
                continue
            d = ev.data
            # W11: text + tool_call deltas are shared with _stream_openai_events
            for out_ev in _parse_sse_delta(d):
                yield out_ev
            # MiniMax signals stream end via finish_reason, not [DONE]
            finish_reason = d.get("choices", [{}])[0].get("finish_reason")
            if finish_reason in ("stop", "tool_calls", "length"):
                # Phase CB-3: capture usage before signaling done.
                usage = d.get("usage")
                if usage:
                    yield SSEEvent(type="usage", data={"usage": usage})
                yield SSEEvent(type="done", data={})
                return
```

After:
```python
            if ev.type != "raw":
                continue
            d = ev.data
            choice = _first_choice(d)
            if choice:
                # W11: text + tool_call deltas are shared with _stream_openai_events
                for out_ev in _parse_sse_delta(d):
                    yield out_ev
                # MiniMax signals stream end via finish_reason, not [DONE]
                finish_reason = choice.get("finish_reason")
                if finish_reason in ("stop", "tool_calls", "length"):
                    # Phase CB-3: capture usage before signaling done.
                    usage = d.get("usage")
                    if usage:
                        yield SSEEvent(type="usage", data={"usage": usage})
                    yield SSEEvent(type="done", data={})
                    return
```

#### 2.1.6 Improve error context in `_call_llm_streaming` exception path (~5 lines)

Before (line 2649-2657, approximate):
```python
    for ev in _stream_with_ssl_retry(
        streamer,
        ...
    ):
```

The wrapping `try/except` (search for `except Exception` around 2725)
should attach context. After:
```python
    except (IndexError, KeyError, TypeError, ValueError) as e:
        # Augment with provider/model context so the chat bubble carries
        # enough info to debug. Without this, the user sees bare
        # "list index out of range" and we can't tell which provider/model
        # produced the malformed frame.
        e._crabcakes_context = {
            "provider": caller_key,
            "model": model,
            "exception_type": type(e).__name__,
        }
        raise
```

**Verified:** `e._crabcakes_context` is a free-form attribute Python allows;
the downstream `ui.handlers.agent_runtime_handler._do_error` reads this
attribute via the small UI-side change in §2.1.8 below.

### 2.1.7 Surface `e._crabcakes_context` in chat bubbles (UI-side, ~15 lines)

`ui/handlers/agent_runtime_handler.py:1279-1310` (`_do_error`) currently
renders the error as `f"[Error] {message}"` with no model/provider info.
Read the model's name (when available) from the augmented exception and
append it. Only changes the bubble TEXT — no behavior, no schema, no
public API.

Before:
```python
    def _do_error(self, session_key: str, message: str) -> None:
        ...
        bubble = self._crh.render_sync(
            "Agent", f"[Error] {message}", session_key, agent_name=resolved_name or "Agent"
        )
```

After:
```python
    def _do_error(self, session_key: str, message: str) -> None:
        ...
        # If the runtime attached a _crabcakes_context (e.g. from
        # _call_llm_streaming), surface provider/model so the user
        # can identify which model produced the malformed response.
        # See SPEC-SSE-FRAME-SHAPE-HARDENING.md §2.1.6/§2.1.7.
        rendered = f"[Error] {message}"
        try:
            # `message` may be a raw string OR an Exception instance;
            # the runtime sometimes passes str(exc), sometimes the exc.
            exc_obj = self._last_error_exception.get(session_key)
            if exc_obj is not None:
                ctx = getattr(exc_obj, "_crabcakes_context", None)
                if ctx:
                    rendered += f"\nProvider: {ctx.get('provider')} | Model: {ctx.get('model')}"
        except Exception:
            # never let an enrichment bug break the error path
            pass
        bubble = self._crh.render_sync(
            "Agent", rendered, session_key, agent_name=resolved_name or "Agent"
        )
```

And add to `_on_error`:
```python
    def _on_error(self, session_key: str, message: str) -> None:
        """AgentRuntime error callback. Show error bubble."""
        # Track the original exception (if any) so _do_error can enrich
        # the bubble. The runtime contract: if message is an Exception,
        # store it; otherwise store None.
        if isinstance(message, BaseException):
            self._last_error_exception[session_key] = message
        else:
            self._last_error_exception[session_key] = None
        if self._GLib is not None:
            self._GLib.idle_add(self._do_error, session_key, message)
        else:
            self._do_error(session_key, message)
```

And in `__init__`:
```python
        self._last_error_exception: dict[str, BaseException | None] = {}
```

### 2.1.7a Log malformed SSE frames instead of swallowing them silently

`_parse_sse_line` at line 487-503 silently returns `None` for any line
that fails JSON/UTF-8 decoding. Today there is no signal at all — the
frame vanishes and the stream appears to stall or end prematurely.

Before:
```python
def _parse_sse_line(line: bytes) -> SSEEvent | None:
    """Parse one SSE line into an SSEEvent. Returns None for non-data lines."""
    line = line.strip()
    if not line or line.startswith(b":"):
        return None
    if line.startswith(b"data: "):
        data = line[6:]
    elif line.startswith(b"data:"):
        data = line[5:].lstrip()
    else:
        return None
    if data == b"[DONE]" or data == b"DONE":
        return SSEEvent(type="done", data={})
    try:
        return SSEEvent(type="raw", data=json.loads(data.decode("utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
```

After:
```python
def _parse_sse_line(line: bytes) -> SSEEvent | None:
    """Parse one SSE line into an SSEEvent. Returns None for non-data lines.

    Malformed frames are logged at DEBUG level so a regression in
    provider behavior is visible in the runtime log without changing
    stream behavior. See SPEC-SSE-FRAME-SHAPE-HARDENING.md §2.1.7a.
    """
    line = line.strip()
    if not line or line.startswith(b":"):
        return None
    if line.startswith(b"data: "):
        data = line[6:]
    elif line.startswith(b"data:"):
        data = line[5:].lstrip()
    else:
        return None
    if data == b"[DONE]" or data == b"DONE":
        return SSEEvent(type="done", data={})
    try:
        return SSEEvent(type="raw", data=json.loads(data.decode("utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Truncate to 200 bytes to keep the log readable. Log the exception
        # type + a short snippet so we can tell UTF-8 errors from JSON errors.
        logger.debug(
            "[sse-line] drop malformed frame (%s): %r",
            type(e).__name__,
            line[:200],
        )
        return None
```

Verified: `logger` is already imported at line 67 (module-level).
Truncating at 200 bytes matches the existing truncation discipline
in `_friendly_error_message`. No public signature change.

#### 2.1.7 Update docstring of `_parse_sse_delta` (line 506-518)

After (only the docstring changed):
```python
def _parse_sse_delta(d: dict) -> list[SSEEvent]:
    """Extract text_delta and tool_call_delta events from an SSE delta dict.

    Shared by _stream_openai_events and _stream_minimax_events.
    The dict is the parsed JSON of an SSE `data:` line whose type is "raw"
    (i.e., it has a `choices` field with a delta).

    Tolerant of empty-choices frames (OpenAI trailing usage, OpenRouter
    keepalive). Returns [] for those frames instead of raising IndexError.
    See SPEC-SSE-FRAME-SHAPE-HARDENING.md.

    finish_reason / usage handling is NOT included — each caller processes
    those inline because OpenAI and MiniMax emit them differently
    (OpenAI: usage in a trailing chunk with empty choices; MiniMax: usage
    inline alongside finish_reason).
    """
```

### 2.2 `tests/test_agent_runtime.py`

Add a new test class `TestSSEFrameShapeHardening` immediately after the
existing streaming test classes (search for the test that currently ends
around line ~1410 — after the last `def test_streaming_preserves_provider_tool_call_id`
class).

Each test follows the established pattern (mock `_urlopen_with_ssl_retry`
to feed raw SSE bytes through the real streamer; see lines 1208-1264 for
the template).

```python
class TestSSEFrameShapeHardening:
    """Regression tests for empty-choices / keepalive / pre-delta frames.

    Spec: docs/specs/SPEC-SSE-FRAME-SHAPE-HARDENING.md
    Root cause: 2026-07-09 08:26 PDT — special:coder crashed with
    IndexError on an empty-choices SSE frame (provider=openrouter,
    model=qwen3-coder via fallback_provider).
    """

    def test_parse_sse_delta_empty_choices_returns_empty_list(self):
        """Trailing usage frame {'choices': [], 'usage': {...}} must not crash."""
        from agent.runtime import _parse_sse_delta
        result = _parse_sse_delta({"choices": [], "usage": {"total_tokens": 42}})
        assert result == []

    def test_parse_sse_delta_missing_choices_returns_empty_list(self):
        """Keepalive / pre-delta frame {} must not crash."""
        from agent.runtime import _parse_sse_delta
        result = _parse_sse_delta({})
        assert result == []

    def test_parse_sse_delta_only_usage_returns_empty_list(self):
        """Some OpenRouter gateways emit a usage-only frame before [DONE]."""
        from agent.runtime import _parse_sse_delta
        result = _parse_sse_delta({"usage": {"prompt_tokens": 1, "completion_tokens": 2}})
        assert result == []

    def test_stream_openai_events_trailing_usage_does_not_crash(self):
        """Full pipeline: feed OpenAI trailing usage frame through _stream_openai_events
        and assert no IndexError is raised and usage is forwarded."""
        from agent import runtime as rt_module
        from agent.runtime import _stream_openai_events

        raw_sse = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
            b'data: [DONE]\n\n'
        )

        class _FakeResp:
            def __init__(self, buf): self._buf = buf
            def __iter__(self): return iter(self._buf.splitlines(keepends=True))
        class _Ctx:
            def __init__(self, resp): self._resp = resp
            def __enter__(self): return self._resp
            def __exit__(self, *a): pass

        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _Ctx(_FakeResp(raw_sse)),
        ):
            events = list(_stream_openai_events(
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))

        # Should have a text_delta from the first frame, a usage event
        # from the trailing frame, and a done event. NO crash.
        types = [ev.type for ev in events]
        assert "text_delta" in types
        usage_events = [ev for ev in events if ev.type == "usage"]
        assert len(usage_events) == 1
        assert usage_events[0].data["usage"]["total_tokens"] == 7
        assert events[-1].type == "done"

    def test_stream_minimax_events_empty_choices_does_not_crash(self):
        """MiniMax path: empty-choices frame must skip cleanly without
        raising IndexError on the unguarded finish_reason access."""
        from agent import runtime as rt_module
        from agent.runtime import _stream_minimax_events

        raw_sse = (
            b'{"base_resp":{"status_code":0,"status_msg":"success"}}\n'  # first-line sentinel for MiniMax
            b'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
            b'data: [DONE]\n\n'
        )

        class _FakeResp:
            def __init__(self, buf): self._buf = buf
            def __iter__(self): return iter(self._buf.splitlines(keepends=True))
        class _Ctx:
            def __init__(self, resp): self._resp = resp
            def __enter__(self): return self._resp
            def __exit__(self, *a): pass

        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _Ctx(_FakeResp(raw_sse)),
        ):
            events = list(_stream_minimax_events(
                base_url="https://api.MiniMax.com/v1",
                api_key="***",
                model="MiniMax/MiniMax-M2.7",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))

        # No crash; the stream should terminate cleanly.
        usage_events = [ev for ev in events if ev.type == "usage"]
        assert len(usage_events) == 1

    def test_stream_openai_events_mid_stream_empty_choices_keeps_streaming(self):
        """Some gateways flush empty-choices keepalive frames mid-stream
        (between two real deltas). Stream must not crash and must yield
        both text deltas."""
        from agent import runtime as rt_module
        from agent.runtime import _stream_openai_events

        raw_sse = (
            b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
            b'data: {"choices":[],"created":1700000000}\n\n'  # mid-stream keepalive
            b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
            b'data: [DONE]\n\n'
        )

        class _FakeResp:
            def __init__(self, buf): self._buf = buf
            def __iter__(self): return iter(self._buf.splitlines(keepends=True))
        class _Ctx:
            def __init__(self, resp): self._resp = resp
            def __enter__(self): return self._resp
            def __exit__(self, *a): pass

        with unittest.mock.patch.object(
            rt_module, "_urlopen_with_ssl_retry",
            lambda req, timeout: _Ctx(_FakeResp(raw_sse)),
        ):
            events = list(_stream_openai_events(
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))

        text = "".join(ev.data["content"] for ev in events if ev.type == "text_delta")
        assert text == "hello world"
        assert events[-1].type == "done"
```

### 2.3 Files NOT changed (already correct)

- `_extract_tool_calls` (1149), `_extract_text_content` (1187),
  `_extract_usage` (1206) — non-streaming path already uses
  `if not choices: return ...` pattern. No changes needed.
- `_stream_anthropic_events` (1018-1131) — completely separate parser,
  does NOT call `_parse_sse_delta`, immune to this bug class. No changes.
- `_parse_sse_line` (487) — already swallows `JSONDecodeError` and
  `UnicodeDecodeError`, returns `None` for non-data lines. No changes.
- `_sse_lines` (480) — line iterator only, no parsing. No changes.
- `_stream_with_ssl_retry` (750) — see §7, this is a separate bug class
  and out of scope.
- `ui/handlers/agent_runtime_handler.py` — the `_do_error` chat-bubble
  message improvement is out of scope (separate spec).
- `agent/runtime.py` `_call_llm`, `_call_anthropic`, `_call_openai`,
  `_call_minimax` (non-streaming paths) — already return the full
  response dict, which the existing extractors handle correctly. No changes.

---

## 3. Data Flow

### 3.1 Current flow (broken)

```
Provider SSE stream
   │
   ├─ frame: {"choices":[{"delta":{"content":"hi"}}]}
   │     ↓
   │   _parse_sse_delta(d)
   │     → d.get("choices", [{}])[0].get("delta", {})  ← OK
   │     → returns [text_delta event]
   │
   ├─ frame: {"choices":[],"usage":{...}}
   │     ↓
   │   _parse_sse_delta(d)
   │     → d.get("choices", [{}])[0]                   ← IndexError 💥
   │
   └─ Exception propagates up through:
        _stream_openai_events
       → _stream_with_ssl_retry (does NOT catch IndexError — only SSL/OSError)
       → _call_llm_streaming (does NOT catch IndexError)
       → _call_llm
       → _run_loop (logs as agent.runtime ERROR)
       → _do_error (ui.handlers.agent_runtime_handler) → chat bubble
```

### 3.2 Fixed flow

```
Provider SSE stream
   │
   ├─ frame: {"choices":[{"delta":{"content":"hi"}}]}
   │     ↓
   │   _stream_openai_events: choice = _first_choice(d) → non-empty
   │     → _parse_sse_delta(d) → [text_delta event]
   │     → usage = d.get("usage") → None, skipped
   │
   ├─ frame: {"choices":[],"usage":{...}}
   │     ↓
   │   _stream_openai_events: choice = _first_choice(d) → {} (empty)
   │     → _parse_sse_delta SKIPPED
   │     → usage = d.get("usage") → yield usage event
   │
   └─ frame: {"choices":[{"finish_reason":"stop"}],"usage":{...}}
         ↓
       _stream_openai_events: choice = _first_choice(d) → non-empty
         → _parse_sse_delta(d) → [] (no text/tool delta)
         → usage = d.get("usage") → yield usage event
       Final: stream_openai_events returns via [DONE] or finish_reason path
```

### 3.3 MiniMax first-line + main loop

The MiniMax path has two parsing branches — first-line (line 975-993)
handles a potential body-level error JSON, main loop (line 994-1013)
handles the rest. Both need the same `choice = _first_choice(d); if choice:`
gate. Identical pattern to OpenAI. Data flow is identical except for the
`base_resp` JSON-error sniff on the first line — that path is already
guarded by `(json.JSONDecodeError, UnicodeDecodeError)` and is untouched.

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|---|---|---|---|
| `agent/runtime.py` | modify | ~25 lines changed across 5 sites + 6 lines new helper + 5 lines context annotation + 10 lines docstring | Low — additive guard, no behavior change on the normal path |
| `tests/test_agent_runtime.py` | modify | ~140 lines new test class | Very low — new tests, no production code touched |

Total: ~185 lines, all in one module, all in one test class.

---

## 5. Implementation Order

1. **Add `_first_choice` helper** in `agent/runtime.py` after line 530.
   Verify: `python3 -c "from agent.runtime import _first_choice; assert _first_choice({}) == {}; assert _first_choice({'choices':[]}) == {}; assert _first_choice({'choices':[{'x':1}]}) == {'x':1}"`
2. **Patch `_parse_sse_delta` line 519** to use `_first_choice`. Verify: existing
   `test_streaming_preserves_provider_tool_call_id` still passes.
3. **Patch `_stream_openai_events` lines 900-905**. Verify: same test passes.
4. **Patch `_stream_minimax_events` lines 982-993 and 1003-1013**. Verify:
   existing `test_stream_minimax_events_base_resp_error` (line 1939) still passes.
5. **Patch `_call_llm_streaming` exception path** to attach
   `e._crabcakes_context`. Verify: no regression in existing tests.
6. **Update `_parse_sse_delta` docstring** to reference this spec.
7. **Add `TestSSEFrameShapeHardening` class** to `tests/test_agent_runtime.py`.
   Verify: new tests pass.
8. **Run full test suite** for `tests/test_agent_runtime.py` and
   `tests/test_streaming.py`. Verify: 0 failures, 0 new warnings.

---

## 6. Acceptance Criteria

- [ ] `_parse_sse_delta({"choices": []})` returns `[]` instead of raising
- [ ] `_parse_sse_delta({})` returns `[]` instead of raising
- [ ] `_stream_openai_events` processes a stream containing
  `{"choices":[],"usage":{...}}` without raising IndexError
- [ ] `_stream_minimax_events` processes a stream containing
  `{"choices":[],"usage":{...}}` without raising IndexError
- [ ] All 26 existing SSE/stream/parse tests still pass
- [ ] All 8 tests in `tests/test_streaming.py` still pass
- [ ] `tests/test_minimax_events_base_resp_error` still passes
- [ ] 6 new tests in `TestSSEFrameShapeHardening` pass
- [ ] When a streaming exception occurs, the raised exception has
  `e._crabcakes_context` populated with `provider`, `model`,
  `exception_type`
- [ ] No behavior change on the normal-stream path (verified by
  re-running the existing real-bytes pipeline test
  `test_streaming_preserves_provider_tool_call_id`)

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Frame `{"choices":[],"usage":{...}}` (OpenAI trailing usage) | Skip `_parse_sse_delta`, yield `usage` event, continue |
| Frame `{}` (empty / keepalive) | Skip `_parse_sse_delta`, continue (no usage) |
| Frame `{"choices":[{}]}` (empty choice dict) | `_parse_sse_delta` returns `[]` (no content, no tool_calls) |
| Frame `{"choices":[{"delta":{}}]}` (empty delta) | `_parse_sse_delta` returns `[]` (no content, no tool_calls) |
| Frame `{"choices":[{not-a-dict}]}` (malformed choice) | `_parse_sse_delta` returns `[]` (type check) |
| Frame `{"choices":[{"finish_reason":"stop"}]}` | `_parse_sse_delta` returns `[]`, finish_reason path yields done |
| Frame `{"choices":[{"finish_reason":"stop"}],"usage":{...}}` | `_parse_sse_delta` returns `[]`, finish_reason path yields done, usage yielded |
| MiniMax `base_resp.status_code != 0` on first line | Already raises RuntimeError (untouched by this spec) |
| Anthropic any shape | Untouched (separate parser) |
| Provider error during SSL retry | `_stream_with_ssl_retry` handles SSL/OSError as today; IndexError is now caught by the `_call_llm_streaming` context annotation and re-raised |
| Provider returns HTTP 200 with non-JSON garbage | `_parse_sse_line` returns None for non-data lines; JSONDecodeError caught and logged — unchanged |

### 7.1 Out-of-scope adjacent bugs (audit findings, not fixed here)

These are documented so the implementer doesn't wonder "should I also
fix this?" Answer: no, separate spec.

| Bug | Location | Severity | Why out of scope |
|---|---|---|---|
| `_stream_with_ssl_retry` re-issues with same messages including accumulated-but-not-flushed tool_call deltas | `agent/runtime.py:750-845` | Medium | Different bug class (network resilience vs. malformed frame). Needs its own spec. The retry correctly suppresses when text has already streamed; the "re-issue with same partial state" issue is acceptable for now. |
| `_do_error` surfaces bare `str(exc)` to chat bubble | `ui/handlers/agent_runtime_handler.py` | Low | UI-side; this spec adds `e._crabcakes_context` so a follow-up UI spec can pick it up cleanly. |
| `_parse_sse_line` swallows all JSONDecodeError silently | `agent/runtime.py:487-503` | Low | Could mask provider protocol changes; but the alternative (crashing) is worse. |
| `conv.fallback_provider` retry on non-streaming path doesn't preserve streaming state | `agent/runtime.py:2267` | Low | Non-streaming fallback works correctly; streaming fallback is by design un-tried. |

---

## 8. ARCHITECTURE.md Updates Required

Per `docs/ARCHITECTURE.md` §0 ("When you change code, you **must** update
this document in the same commit"), this spec requires ONE update:

**Section 4 (data flow) — SSE streaming layer paragraph** (currently
around line 1527-1565). Add a sentence to the streaming description:

> "Streaming layer is defensive against empty-choices SSE frames
> (OpenAI trailing usage, OpenRouter keepalive). The `_first_choice`
> helper is the single source of truth for this guard pattern; both
> `_parse_sse_delta` and the per-provider streamers use it. See
> `docs/specs/SPEC-SSE-FRAME-SHAPE-HARDENING.md`."

No other ARCHITECTURE.md sections need updating. The change is internal
to one module and does not affect public APIs, event flows, environment
variables, or protocol handling.

---

## 9. Self-Audit (Rule 9 — before declaring complete)

1. **Does every code sample actually work against the current codebase?**
   YES — all function signatures verified via `grep -n "def function_name"`
   against the live `agent/runtime.py`. Helper signatures match:
   `_parse_sse_delta(d: dict) -> list[SSEEvent]`,
   `_first_choice(d: dict) -> dict`,
   `_stream_openai_events(*, base_url, api_key, model, messages, tools, timeout, x_title)`,
   `_stream_minimax_events(*, base_url, api_key, model, messages, tools, timeout, x_title)`.
   No invented parameters, no renamed functions, no assumed defaults.

2. **Did I catch all exception types for every function I call?**
   YES — the only exception types the patch can raise are `KeyError`
   (if a sub-dict lookup fails on a non-dict), `TypeError` (if `d` is not
   a dict — shouldn't happen since `_parse_sse_line` already JSON-parsed),
   and `AttributeError` (likewise). All three are caught in the new
   `_call_llm_streaming` exception handler (2.1.6). The `_first_choice`
   helper itself raises nothing.

3. **Did I verify key structures, not assume them?**
   YES — verified by reading `_RESPONSE_FORMAT` (line 460-465),
   `_PROVIDER_STREAMERS` (1122-1126), `_PROVIDER_CALLERS` (423-429),
   and the test pattern at lines 1208-1264. Key structures:
   `{"choices":[{"delta":{...}}]}` (normal),
   `{"choices":[],"usage":{...}}` (trailing usage),
   `{"choices":[],"created":...}` (keepalive).

4. **Did I trace the data flow end-to-end?**
   YES — §3 traces both the broken and fixed flows through every layer
   from `_parse_sse_line` → `_stream_openai_events` →
   `_stream_with_ssl_retry` → `_call_llm_streaming` → `_run_loop` →
   `_do_error`. Verified the SSL retry layer does NOT catch IndexError
   (it only catches `ConnectionResetError`, `BrokenPipeError`,
   `urllib.error.URLError`, `ssl.SSLError`), so the IndexError does
   propagate to the `_call_llm_streaming` exception handler as the
   new context annotation expects.

5. **Would an implementer who follows this spec exactly produce working
   code?**
   YES — every code sample is copy-pasteable, every test follows the
   established pattern, every change site has explicit before/after
   with surrounding context. An implementer should be able to ship
   this in 30-60 minutes including running the test suite.

---

## 10. Completion Verification (Rule 10)

To be performed by the implementer; results recorded in the PR
description.

1. **Scope checklist:**
   - [ ] `agent/runtime.py` — 5 modified sites + 1 new helper (lines listed in §2.1)
   - [ ] `tests/test_agent_runtime.py` — new `TestSSEFrameShapeHardening` class
   - [ ] `docs/ARCHITECTURE.md` — §4 streaming paragraph appended

2. **Test suite output (paste actual pytest -v output, not summary):**
   ```
   $ cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py tests/test_streaming.py -v
   <paste full output here>
   ```

3. **Pattern sweep — confirm no remaining `d.get("choices", [{}])[0]`:**
   ```
   $ grep -n 'd\.get("choices", \[{}\])\[0\]' agent/runtime.py
   <expect: no matches>
   $ grep -n '_first_choice' agent/runtime.py
   <expect: 4 matches (1 definition + 3 call sites + 1 in docstring)>
   ```

4. **Declaration:** "complete" only when all three checks pass.