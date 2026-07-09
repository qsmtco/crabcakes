# SPEC: SSE Frame-Shape Hardening — Eliminate `IndexError` and Empty-Choice Crashes in Streaming

**Date:** 2026-07-09
**Author:** qtr (read-only audit)
**Status:** Draft — for implementation
**Implements:** none (root-cause audit triggered by incident `agent.runtime ERROR Error in tool loop for special:coder` on 2026-07-09 08:26 PDT)
**Depends on:** none
**Target branch:** main
**Companion spec:** `docs/specs/SPEC-SSL-RETRY-USAGE-FIDELITY.md` (out-of-scope bug #1, delivered alongside)

> Architecture compliance: this spec touches `agent/runtime.py` and one UI
> handler file, both within the SSE streaming layer owned by `AgentRuntime`
> (per `docs/ARCHITECTURE.md` §3 module responsibilities, §4 data flow). It
> does not change any public API. It is a hardening fix, not a feature.

---

## 0. Starting Spec Discovery — reading all referenced source files

> Per the Steel-Framed Spec Writer prompt, the discovery block is mandatory.
> All findings below were verified against the actual source, not memory.

```
DISCOVERY:
- Read agent/runtime.py (2965 lines): full SSE streaming layer, lines 480-1131
  - _sse_lines (480): line iterator over an HTTP response
  - _parse_sse_line (487): bytes → SSEEvent | None, returns None for [DONE] sentinel
    and lines without "data:" prefix — SILENTLY swallows JSONDecodeError and
    UnicodeDecodeError (addressed §2.1.7a)
  - _parse_sse_delta (506): shared OpenAI/MiniMax delta extractor — has the
    unguarded [0] on line 519 that caused the production crash
  - _stream_with_ssl_retry (750): mid-stream SSL/network retry wrapper — emits
    a warning when retrying but does not flag the partial-usage-loss risk
    (addressed §2.1.7c)
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

- Read tests/test_agent_runtime.py (lines 1185-1410): established pattern for
  exercising raw SSE bytes through the full streamer → accumulator pipeline
  by mocking _urlopen_with_ssl_retry. New tests MUST follow this pattern.

- Read tests/test_streaming.py: 8 tests, all passing, none cover SSE frame
  shape edge cases.

- Read docs/ARCHITECTURE.md §3 (module responsibilities), §4 (data flow),
  §11 (file inventory). The SSE streaming layer is owned by
  AgentRuntime._call_llm_streaming → _PROVIDER_STREAMERS → per-provider
  streamer → _parse_sse_delta. The error surface is _do_error in
  ui.handlers.agent_runtime_handler, which currently passes raw str(exc) to
  the chat bubble (addressed §2.1.7).

- Read ui/handlers/agent_runtime_handler.py (lines 1279-1310): _do_error
  renders "[Error] {message}" with no model/provider info. Has no access to
  the original exception, only the str(exc). Fix: thread the exception
  through _on_error so _do_error can read _crabcakes_context.

- Read docs/specs/SPEC-SSL-RETRY-FIX.md (parent spec for the SSL retry layer
  being touched in §2.1.7c). My change is purely additive — extending the
  warning text to mention partial-usage-loss — so it does not break the
  parent design.

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
sites** in the streaming layer (lines 519, 985, 1008), plus **three adjacent
diagnostic issues** that haven't bitten yet but share the same root cause class:

1. The non-streaming path is **already guarded** with `if not choices:`
   returns in `_extract_tool_calls` (1149), `_extract_text_content` (1187),
   `_extract_usage` (1206) — but the streaming path diverged and never
   adopted the same pattern.
2. The chat bubble error message is uninformative — even after we fix
   the crashes, an unrelated provider error will still surface as a
   bare Python exception string to the user.
3. The SSE line parser silently swallows JSON/UTF-8 decode errors —
   a regression in provider behavior would be invisible.

A fourth adjacent bug (SSL retry usage fidelity) is documented in
§7.1 and addressed in a companion spec.

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
4. **Improve chat-bubble error messages** — surface provider/model via
   `_crabcakes_context` attached to the streaming exception.
5. **Log malformed SSE frames** at DEBUG level with truncated bytes —
   zero behavior change, restores diagnostic visibility.
6. **Annotate SSL retry warnings** with a "partial usage may be lost"
   pointer so the next SSL-drop incident is debuggable. The actual
   usage-fidelity fix is in the companion spec.

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| `agent/runtime.py` lines 487-525, 800-845, 890-906, 950-1014, 2614-2725 | SSL retry semantic fix (partial usage preservation) — see `docs/specs/SPEC-SSL-RETRY-USAGE-FIDELITY.md` |
| Three `_parse_sse_delta` callers | New provider types |
| SSE line parser logging | UI bubble rendering (only the `_do_error` enrichment is in scope) |
| Tests covering the new frame shapes | Performance / throughput changes |
| One regression test per fixed code path | Provider-config UI changes |
| README-free docstring updates where existing comments misdescribe behavior | |

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
attribute via the small UI-side change in §2.1.7 below.

#### 2.1.7 Surface `e._crabcakes_context` in chat bubbles (UI-side, ~15 lines)

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

#### 2.1.7a Log malformed SSE frames instead of swallowing them silently

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

#### 2.1.7b Update docstring of `_parse_sse_delta` (line 506-518)

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
    (OpenAI: