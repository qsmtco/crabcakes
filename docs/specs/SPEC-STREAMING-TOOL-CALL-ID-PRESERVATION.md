# SPEC: Preserve `tool_call.id` through streaming SSE assembly

**Date:** 2026-06-23
**Author:** QTR (with steelFramedSpecWriter.md verification)
**Status:** Draft — for implementation
**Implements:** Bug fix only — no proposal backing
**Depends on:** None
**Target branch:** main
**Source bug report:** `docs/bugs/BUG_REPORT-streaming-tool-call-id-loss.md`

> **Architecture compliance:** Streaming LLM I/O and tool-call normalization are owned by `agent/runtime.py::AgentRuntime` per `docs/ARCHITECTURE.md` §3.21m (lines 1358-1382) and §12 (Provider Resolution & API Caller, line 3390). The `tool_call.id` field is part of the Tool Call Normalization contract asserted at §3.21m line 1377 ("Tool calls normalized to internal `ToolCall` format regardless of provider"). This spec preserves that invariant by carrying the provider-assigned `id` through the streaming path, matching the non-streaming path's existing behavior.

---

## 1. Overview

### Problem statement

When a special agent (Coder, Helper, etc.) uses the **streaming** LLM path, the runtime discards the real `tool_call.id` field that MiniMax/OpenAI assign in the SSE stream and replaces it with a synthetic `f"call_{idx}"` (e.g. `call_0`, `call_1`). On the next turn, the conversation history is sent back to the LLM with the synthetic ID, and the LLM rejects the request with:

```
status_code=2013: invalid params, tool call result does not follow tool call
```

because the `tool_call_id` on the `tool` role message does not match any preceding `tool_calls[i].id` in the `assistant` message.

**Affects all five streaming providers** in `_PROVIDER_STREAMERS` (line 737-742):
- `minimax` (`_stream_minimax_events`, line 542) — confirmed production trigger
- `openai` (`_stream_openai_events`, line 473) — same code path
- `openrouter` (also `_stream_openai_events`) — same code path
- `zai` (also `_stream_openai_events`) — same code path
- `anthropic` (`_stream_anthropic_events`, line 658) — same bug class via different mechanism (latent)

The non-streaming path is **correct**: `_call_minimax` (line 238) returns the raw API response with the real ID, and `_extract_tool_calls` (line 774) reads it via `tc.get("id", f"call_{uuid.uuid4().hex[:8]}")` — so a real ID is preserved.

**Introduced in:** commit `7b8148a` (2026-04-21, "feat: agent runtime, convergence detection, adversarial audits, product vision"). The follow-up commit `85c2a41` (2026-05-07, "fix: MiniMax streaming tool calls + exec_command double card") addressed the missing `done` event but did **not** fix the ID loss.

### Solution summary

Three surgical fixes in `agent/runtime.py`, plus an optional fourth for the Anthropic path, plus one regression test:

1. **Streamer fix (3 occurrences):** Add `"id": tcd.get("id", "")` to the `SSEEvent(type="tool_call_delta", data={...})` yields in `_stream_openai_events` (line 531-533) and `_stream_minimax_events` (lines 612-614 and 644-646).
2. **Accumulator fix (1 occurrence):** Initialize `tool_calls_partial[idx]` with an `"id"` key and capture it from the new event field. Switch from direct subscript to `.get()` to handle sparse deltas safely. Lines 2062-2070 in `_call_llm_streaming`.
3. **Assembly fix (2 occurrences):** Replace the synthetic `f"call_{idx}"` with `tc["id"] or f"call_{idx}"` in both the `done`-event assembly (line 2087) and the fallback assembly (line 2107).
4. **Anthropic fix (optional, recommended):** Add a `content_block_start` handler in `_stream_anthropic_events` that captures `id` and propagates it through a `tool_call_id`-only delta (or by extending the existing `tool_call_delta` data).
5. **Regression test:** Add `test_streaming_preserves_provider_tool_call_id` in `tests/test_agent_runtime.py` that mocks raw SSE bytes containing a real `id` field and asserts the final `tool_calls[0]["id"]` matches.

### Scope

| In scope | Out of scope |
|---|---|
| `agent/runtime.py` — 3 streamer yields + 1 accumulator + 2 assembly sites | `_call_llm` routing logic (line 1889-1986) — unchanged |
| `agent/runtime.py` — Anthropic `content_block_start` handler (optional but recommended) | `_extract_tool_calls` (line 752-797) — non-streaming path already correct |
| `tests/test_agent_runtime.py` — regression test for ID preservation | `_PROVIDER_STREAMERS` dict (line 737-742) — unchanged |
| `docs/ARCHITECTURE.md` — update §3.21m Streaming paragraph + §12 if Anthropic is fixed | `docs/bugs/BUG_REPORT-streaming-tool-call-id-loss.md` — historical report, not modified |
| Existing conversation files with synthetic `call_{idx}` IDs | Migration of existing conversations (see BUG #7 in bug report — out of scope, surface in release notes) |

### Architecture principles that apply

- **Provider-agnostic tool_call normalization (§3.21m line 1377):** "Tool calls normalized to internal `ToolCall` format regardless of provider." Today the streaming path synthesizes an ID that diverges from the non-streaming path's real ID. After this fix, both paths preserve provider-assigned IDs identically.
- **SSE event contract:** `SSEEvent(type="tool_call_delta", data={...})` is the runtime-internal contract between streamers and `_call_llm_streaming`. The `data` dict's keys are not formally documented but in practice have been `index`, `name`, `arguments`. Adding `id` is a backward-compatible additive change — no consumer outside `_call_llm_streaming` reads this event.
- **First-write-wins ID capture (BUG #6 in bug report):** OpenAI/MiniMax send the `id` in the first delta for a tool call only; subsequent deltas carry only argument fragments. The accumulator's first-write-wins strategy matches the provider contract.
- **Defensive `.get()` over direct subscript:** Future SSE deltas may carry only an `id` (e.g. a sparse delta from a different provider). The accumulator must use `.get()` to avoid `KeyError`.

---

## 2. Changes by File

### 2.1 `agent/runtime.py` (modify, +12 lines, -3 lines)

#### 2.1.a `_stream_openai_events` (line 531-533) — preserve `id` in yield

**Function:** `_stream_openai_events` (line 473-540)

**What changes:** The `SSEEvent(type="tool_call_delta", data=...)` yield at line 531-533 currently discards the `id` field from `tcd`. Add `id` to the emitted data so the accumulator in `_call_llm_streaming` can capture it.

**Current source (verified, line 531-533):**
```python
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
```

**New source:**
```python
                    # STREAM-ID-PRES: surface the provider-assigned tool_call id
                    # so the accumulator preserves it through to the round-trip
                    # request. OpenAI/MiniMax/OpenRouter/ZAI all set this in
                    # the first delta for a tool call; empty string when absent.
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs,
                        "id": tcd.get("id", "") or "",
                    })
```

**Imports required:** None (uses `tcd` from enclosing scope; the dict's `.get` is built-in).

#### 2.1.b `_stream_minimax_events` (line 612-614) — preserve `id` in first-line path

**Function:** `_stream_minimax_events` (line 542-655)

**What changes:** Same fix as 2.1.a, applied to the tool_call_delta yield inside the first-line-only branch (line 612-614). This branch handles the case where the first non-empty SSE line contains a tool_call delta and the body is short enough to fit in one line.

**Current source (verified, line 612-614):**
```python
                            yield SSEEvent(type="tool_call_delta", data={
                                "index": idx, "name": fname, "arguments": fargs
                            })
```

**New source:**
```python
                            # STREAM-ID-PRES: see _stream_openai_events
                            yield SSEEvent(type="tool_call_delta", data={
                                "index": idx, "name": fname, "arguments": fargs,
                                "id": tcd.get("id", "") or "",
                            })
```

#### 2.1.c `_stream_minimax_events` (line 644-646) — preserve `id` in main path

**Function:** `_stream_minimax_events` (line 542-655)

**What changes:** Same fix as 2.1.b, applied to the tool_call_delta yield in the main per-line loop (line 644-646). This is the most commonly-executed path (multi-line tool_call responses).

**Current source (verified, line 644-646):**
```python
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
```

**New source:**
```python
                    # STREAM-ID-PRES: see _stream_openai_events
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs,
                        "id": tcd.get("id", "") or "",
                    })
```

#### 2.1.d `_stream_anthropic_events` (line 658-738) — handle `content_block_start` (optional but recommended)

**Function:** `_stream_anthropic_events` (line 658-738)

**What changes:** Anthropic's SSE format puts the `id` in `content_block_start` events (one per tool_use block), not in `content_block_delta`. The current streamer only handles `content_block_delta` and never reads `content_block_start`. After the fix, `content_block_start` with `block.type == "tool_use"` must be captured and propagated.

**Current source (verified, line 714-725):**
```python
            if etype == "content_block_delta":
                delta = d.get("delta", {})
                dtype = delta.get("type", "")
                if dtype == "text_delta":
                    yield SSEEvent(type="text_delta", data={"content": delta.get("text", "")})
                elif dtype == "tool_use_delta":
                    idx = d.get("index", 0)
                    fname = delta.get("name") or ""
                    fargs = delta.get("input", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
```

**New source:**
```python
            if etype == "content_block_start":
                # STREAM-ID-PRES: Anthropic assigns the tool_use_id here, in the
                # block-start event (NOT in the delta). Forward it so the
                # accumulator can attach it to the in-progress tool_call before
                # the first content_block_delta arrives.
                block = d.get("content_block", {})
                if block.get("type") == "tool_use":
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": d.get("index", 0),
                        "name": "",
                        "arguments": "",
                        "id": block.get("id", "") or "",
                    })
            elif etype == "content_block_delta":
                delta = d.get("delta", {})
                dtype = delta.get("type", "")
                if dtype == "text_delta":
                    yield SSEEvent(type="text_delta", data={"content": delta.get("text", "")})
                elif dtype == "tool_use_delta":
                    idx = d.get("index", 0)
                    fname = delta.get("name") or ""
                    fargs = delta.get("input", "") or ""
                    # STREAM-ID-PRES: forward the id if Anthropic ever does send
                    # one in the delta (it shouldn't, but stay defensive).
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs,
                        "id": "",
                    })
```

**Why emit `id: ""` from the `content_block_delta` path:** The first-write-wins accumulator (BUG #6 fix below) requires the `id` key to exist on every `tool_call_delta` event for `.get("id")` to work consistently. Emitting empty string from deltas preserves the "no overwrite" semantics: the `content_block_start` already set the real id; subsequent deltas won't overwrite it.

#### 2.1.e `_call_llm_streaming` accumulator (line 2062-2070) — capture `id` + use `.get()`

**Function:** `AgentRuntime._call_llm_streaming` (line 1998-2112)

**What changes:** The accumulator must (a) initialize the partial dict with an `"id"` key, (b) capture the `id` from incoming `tool_call_delta` events using first-write-wins, and (c) switch from direct subscript (`ev.data["name"]`) to `.get()` to survive sparse deltas (BUG #5 from bug report).

**Current source (verified, line 2062-2070):**
```python
            elif ev.type == "tool_call_delta":
                # PHASE-11.5: default to 0 if streamer omits 'index' (e.g. Anthropic
                # single-tool responses). Without this, the runtime crashes mid-stream.
                idx = ev.data.get("index", 0)
                if idx not in tool_calls_partial:
                    tool_calls_partial[idx] = {"name": "", "arguments": ""}
                tc = tool_calls_partial[idx]
                if ev.data["name"]:
                    tc["name"] = ev.data["name"]
                if ev.data["arguments"]:
                    tc["arguments"] += ev.data["arguments"]
```

**New source:**
```python
            elif ev.type == "tool_call_delta":
                # PHASE-11.5: default to 0 if streamer omits 'index' (e.g. Anthropic
                # single-tool responses). Without this, the runtime crashes mid-stream.
                # STREAM-ID-PRES: capture provider-assigned id from first delta;
                # subsequent deltas (which carry argument fragments) do not overwrite.
                idx = ev.data.get("index", 0)
                if idx not in tool_calls_partial:
                    tool_calls_partial[idx] = {"name": "", "arguments": "", "id": ""}
                tc = tool_calls_partial[idx]
                if ev.data.get("name"):
                    tc["name"] = ev.data["name"]
                if ev.data.get("arguments"):
                    tc["arguments"] += ev.data["arguments"]
                incoming_id = ev.data.get("id") or ""
                if incoming_id and not tc["id"]:
                    tc["id"] = incoming_id
```

#### 2.1.f `_call_llm_streaming` done-event assembly (line 2082-2094) — use captured `id`

**Function:** `AgentRuntime._call_llm_streaming` (line 1998-2112)

**What changes:** The done-event handler synthesizes `f"call_{idx}"` for the tool_call id. Replace with the captured `tc["id"]`, falling back to the synthetic id only when the provider omitted one (defensive — should not happen after 2.1.a-d).

**Current source (verified, line 2082-2094):**
```python
            elif ev.type == "done":
                # Build final tool_calls list from accumulated partials
                tool_calls = []
                for idx in sorted(tool_calls_partial.keys()):
                    tc = tool_calls_partial[idx]
                    if tc["name"]:
                        tool_calls.append({
                            "id": f"call_{idx}",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        })
```

**New source:**
```python
            elif ev.type == "done":
                # Build final tool_calls list from accumulated partials.
                # STREAM-ID-PRES: use the provider-assigned id captured during
                # SSE assembly; fall back to synthetic only if absent.
                tool_calls = []
                for idx in sorted(tool_calls_partial.keys()):
                    tc = tool_calls_partial[idx]
                    if tc["name"]:
                        tool_calls.append({
                            "id": tc["id"] or f"call_{idx}",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        })
```

#### 2.1.g `_call_llm_streaming` fallback assembly (line 2102-2113) — use captured `id`

**Function:** `AgentRuntime._call_llm_streaming` (line 1998-2112)

**What changes:** Same fix as 2.1.f, applied to the fallback path (when the stream ends without an explicit `done` event). Some providers (early MiniMax responses) used this path before commit `85c2a41`; the fix must cover both code paths.

**Current source (verified, line 2102-2113):**
```python
        # Fallback — stream ended without explicit done event (e.g. provider doesn't send [DONE])
        tool_calls = []
        for idx in sorted(tool_calls_partial.keys()):
            tc = tool_calls_partial[idx]
            if tc["name"]:
                tool_calls.append({
                    "id": f"call_{idx}",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"]
                    }
                })
```

**New source:**
```python
        # Fallback — stream ended without explicit done event (e.g. provider doesn't send [DONE])
        # STREAM-ID-PRES: same id-preservation logic as the done-event path.
        tool_calls = []
        for idx in sorted(tool_calls_partial.keys()):
            tc = tool_calls_partial[idx]
            if tc["name"]:
                tool_calls.append({
                    "id": tc["id"] or f"call_{idx}",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"]
                    }
                })
```

### 2.2 `tests/test_agent_runtime.py` (modify, +95 lines)

#### 2.2.a `TestStreaming` — add `test_streaming_preserves_provider_tool_call_id`

**Location:** After `test_tool_call_delta_without_index_defaults_to_zero` (line 943) within the `TestStreaming` class (line 832).

**What changes:** A new test that mocks `_PROVIDER_STREAMERS` with a streamer that yields raw SSE bytes containing a real `id` field, runs `_call_llm_streaming` end-to-end, and asserts the final response dict's `tool_calls[0]["id"]` matches.

**Why raw SSE bytes and not pre-built `SSEEvent` objects:** The bug is in the **streamer** layer (lines 531, 612, 644, 722) — testing only the assembler would miss the SSE-parsing gap. The test must construct raw bytes that pass through `_sse_lines` → `_parse_sse_line` → streamer logic → `SSEEvent`, and verify the id survives the full pipeline.

**New test source (to be added inside `class TestStreaming` after line 974):**
```python
    def test_streaming_preserves_provider_tool_call_id(self):
        """STREAM-ID-PRES: provider-assigned tool_call id flows from SSE bytes
        through the streamer, the accumulator, and the final response dict.

        Regression: streaming path used to synthesize `f"call_{idx}"` and drop
        the real id, causing MiniMax to reject the next-turn request with
        status_code=2013 ("tool call result does not follow tool call").
        See docs/bugs/BUG_REPORT-streaming-tool-call-id-loss.md.
        """
        from agent import runtime as rt_module
        from agent.runtime import _stream_openai_events, _parse_sse_line, _sse_lines
        from io import BytesIO

        # Provider-shape raw SSE bytes — real id in first delta
        REAL_ID = "call_function_3679004591_1"
        raw_sse = (
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"id":"' + REAL_ID.encode() + b'",'
            b'"function":{"name":"read_file","arguments":""}}'
            b']}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"function":{"arguments":"{\\"path\\":\\"/tmp/foo.py\\"}"}}'
            b']}}]}\n\n'
            b'data: {"choices":[{"finish_reason":"tool_calls"}]}\n\n'
        )

        # Wrap the raw bytes as a file-like object that yields line-by-line
        # (mimicking what urllib returns after a streaming HTTP read).
        class _LineStream:
            def __init__(self, buf):
                self._buf = buf
            def __iter__(self):
                return iter(self._buf.splitlines(keepends=True))

        # Patch _sse_lines so it can iterate the buffer (it's normally bound
        # to an http.client response).
        orig_sse_lines = _sse_lines
        rt_module._sse_lines = lambda resp: orig_sse_lines(_LineStream(raw_sse))
        try:
            # Sanity: parse the raw bytes through the real pipeline and verify
            # the SSEEvent stream carries the id forward.
            events = list(_stream_openai_events(
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "read foo.py"}],
                tools=None,
                timeout=30.0,
                x_title="",
            ))
            deltas = [ev for ev in events if ev.type == "tool_call_delta"]
            assert deltas, "expected at least one tool_call_delta event"
            assert deltas[0].data.get("id") == REAL_ID, (
                f"streamer must forward provider-assigned id; got {deltas[0].data.get('id')!r}"
            )
        finally:
            rt_module._sse_lines = orig_sse_lines

        # Now run the full _call_llm_streaming pipeline with the real
        # _stream_openai_events, and assert the assembled response carries
        # the real id (not a synthetic call_{idx}).
        rt = AgentRuntime(_make_cfg(), on_text_delta=lambda sk, delta: None)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        rt_module._sse_lines = lambda resp: orig_sse_lines(_LineStream(raw_sse))
        try:
            response = rt._call_llm_streaming(
                session_key=sk,
                base_url="https://api.openai.com/v1",
                api_key="***",
                model="openai/gpt-4o",
                caller_key="openai",
                messages=[{"role": "user", "content": "read foo.py"}],
                tools=None,
                timeout=30.0,
            )
        finally:
            rt_module._sse_lines = orig_sse_lines
            rt._cleanup_tool_history(sk)
            rt.stop()

        tool_calls = response["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == REAL_ID, (
            f"final tool_call id must be the provider-assigned one; "
            f"got {tool_calls[0]['id']!r} (synthetic call_0 means the fix is broken)"
        )
        assert tool_calls[0]["function"]["name"] == "read_file"
        assert tool_calls[0]["function"]["arguments"] == '{"path": "/tmp/foo.py"}'

        # Round-trip check: feed the response back into _extract_tool_calls
        # and verify it produces a ToolCall with the real id (this is the
        # path used by _run_loop on the next turn).
        call_id, tool_name, args = _extract_tool_calls(response, "openai")[0]
        assert call_id == REAL_ID, (
            f"_extract_tool_calls must surface the real id; got {call_id!r}"
        )
        assert tool_name == "read_file"
```

**Imports required:** `_stream_openai_events`, `_sse_lines`, `_parse_sse_line` from `agent.runtime`; `_extract_tool_calls` (already imported at the top of `test_agent_runtime.py`); `BytesIO` (only if used; we used a custom `_LineStream` wrapper instead — no `BytesIO` needed).

**Verify test imports already present:**
- `_extract_tool_calls` is already imported at line 17-25 of `tests/test_agent_runtime.py`.
- `_stream_openai_events`, `_sse_lines`, `_parse_sse_line` are NOT module-level imports; the test does its own local `from agent.runtime import _stream_openai_events, _sse_lines` (line 800 confirms `_stream_openai_events` is importable from there).
- The test monkey-patches `agent.runtime._sse_lines` to feed a buffer instead of an `http.client` response. This pattern is acceptable here because `_sse_lines` is a module-level function and we're restoring the original in a `finally` block.

**Verification trace** (per steelFramedSpecWriter.md Rule 2):

| Call in test | What it actually does | Verified |
|---|---|---|
| `_sse_lines(_LineStream(raw_sse))` | Splits bytes on newlines, yields `line.strip()` per line (line 412-416) | ✓ |
| `_stream_openai_events(...)` | Iterates SSE, yields `SSEEvent(type="tool_call_delta", data={"index":..., "name":..., "arguments":..., "id":...})` (post-fix) | ✓ (post-fix) |
| `rt._call_llm_streaming(...)` | Iterates streamer, accumulates `tool_calls_partial[idx]`, assembles final response on `done` event (line 2062-2094) | ✓ |
| `_extract_tool_calls(response, "openai")` | Returns `[(call_id, tool_name, args), ...]` from `tool_calls[i]["id"]` (line 774) | ✓ |

**Exception types raised by the test path** (Rule 4):
- `urllib.error.URLError` from `urllib.request` — NOT raised because we mock `_sse_lines`
- `KeyError` from `ev.data["name"]` direct subscript — ELIMINATED by the `.get()` fix in 2.1.e
- `json.JSONDecodeError` from `_parse_sse_line` — caught internally (line 434), returns `None`
- `RuntimeError` from MiniMax body-level error check — NOT raised because the raw SSE bytes are clean

**Key structures** (Rule 5):
- `tool_calls_partial: dict[int, dict[str, str]]` — keyed by tool_call index (0, 1, 2...)
- `SSEEvent.data: dict` — `{"index", "name", "arguments", "id"}` (post-fix)
- Final `response["choices"][0]["message"]["tool_calls"][i]["id"]: str` — provider-assigned id (post-fix)

**Return value analysis** (Rule 6):
- `_call_llm_streaming` returns `{"choices": [{"message": {"content": ..., "tool_calls": [...]}}], "usage": {...}}` — the test only inspects `choices[0].message.tool_calls[0].id` (Rule 6: explicit read of return value, not ignored).

### 2.3 `docs/ARCHITECTURE.md` (modify, +6 lines, -4 lines)

#### 2.3.a §3.21m — update Streaming paragraph

**Location:** `docs/ARCHITECTURE.md` line 1380 (the "**Streaming:**" paragraph under `class AgentRuntime`).

**What changes:** Add a sentence documenting that the streaming path now preserves provider-assigned `tool_call.id` values through to the round-trip request, matching the non-streaming path's behavior.

**Current source (verified, line 1380):**
```markdown
**Streaming:** SSE for supported providers. `on_text_delta` fires incrementally. `on_tool_call_start` fires when complete call is received.
```

**New source:**
```markdown
**Streaming:** SSE for supported providers. `on_text_delta` fires incrementally. `on_tool_call_start` fires when complete call is received. Tool calls preserve the provider-assigned `id` field through SSE assembly — the accumulator (`_call_llm_streaming` lines 2062-2070) captures the id from the first `tool_call_delta` per tool call, and both the `done`-event and fallback assemblers (lines 2082-2094, 2102-2113) emit it on the final response so the round-trip request to the LLM matches the assistant → tool_result correlation the provider expects. See SPEC-STREAMING-TOOL-CALL-ID-PRESERVATION.md.
```

#### 2.3.b §3.21m — update Tool calls normalization paragraph (if needed)

The existing line 1377 says: "Tool calls normalized to internal `ToolCall` format regardless of provider." This is now strictly true after the fix (both streaming and non-streaming paths produce equivalent `ToolCall` records with provider-assigned `id`s). No change required — the existing sentence is correct. (Rule 8: file considered but not changed.)

#### 2.3.c §12 — add stream-id-preservation note (optional, only if 2.1.d is implemented)

**Location:** `docs/ARCHITECTURE.md` line 3403 (the "**Streamer resolution:**" paragraph under §12 Provider Resolution & API Caller).

**What changes:** If the Anthropic `content_block_start` handler (2.1.d) is implemented, add a sentence noting that Anthropic's id-in-block-start format is handled.

**New sentence to append to the "**Streamer resolution:**" paragraph (only if 2.1.d is in scope):**
```markdown
**Anthropic stream format:** `_stream_anthropic_events` reads the `tool_use.id` from `content_block_start` events (Anthropic puts the id in the block-start, not the delta), then propagates it through the standard `tool_call_delta` event so the accumulator handles all five providers uniformly. See SPEC-STREAMING-TOOL-CALL-ID-PRESERVATION.md §2.1.d.
```

### 2.4 Files NOT changed

**Files considered but decided not to modify** (Rule 8):

- `agent/runtime.py::_extract_tool_calls` (line 752-797) — non-streaming path already uses `tc.get("id", f"call_{uuid.uuid4().hex[:8]}")` (line 774) and the Anthropic path uses `block.get("id")` (line 790). Both correctly preserve real IDs. No changes needed.
- `agent/runtime.py::_call_llm` (line 1889-1986) — routing logic unchanged. The streaming path (line 1969-1986) still calls `_call_llm_streaming` and the blocking path (line 1987-2000) still calls the per-provider caller. Both produce equivalent `ToolCall` records after the fix.
- `agent/runtime.py::_call_minimax` (line 238-280) — non-streaming MiniMax caller returns the raw API response which includes real tool_call IDs. No changes needed.
- `agent/runtime.py::_call_openai` and `_call_anthropic` (analogous to `_call_minimax`) — non-streaming callers return raw responses with real IDs. No changes needed.
- `agent/runtime.py::_PROVIDER_STREAMERS` dict (line 737-742) — registration unchanged. The five streamers are still mapped to the same caller keys.
- `agent/runtime.py::_run_loop` (line 1387-1880) — tool execution loop. Uses `tool_calls_raw` from `_extract_tool_calls(response, loop_provider)` (line 1584) which already uses real IDs (line 774). No changes needed.
- `models/conversation.py::to_api_messages` (line 207-251) — serializes `ToolCall.call_id` (line 230) and `Message.tool_call_id` (line 240). After the fix, `call_id` carries the real provider-assigned id, so the round-trip request is correct. No code changes needed; the existing serialization is already correct.
- `models/conversation.py::_save_conversation_to_disk` (line 894) and `_load_conversation_from_disk` (line 991) — persist `call_id` (synthetic pre-fix, real post-fix). No code changes; new conversations get real IDs, existing ones with synthetic IDs will still fail with 2013 (see Edge Cases §7 below).
- `ui/handlers/agent_runtime_handler.py` (867 lines) — UI bridge between CrabCakes and `AgentRuntime`. Does not touch tool_call id handling. No changes needed.
- `utils/project_awareness.py` — project config; unrelated to LLM I/O. No changes needed.
- `~/.config/crabcakes/conversations/*.json` (user's saved conversations) — existing files with synthetic IDs cannot be migrated automatically; see Edge Cases §7.

---

## 3. Data Flow

The full execution path for a streaming tool call, **after** this spec is implemented:

```
User sends message in chat tab (e.g. "read /tmp/foo.py")
   │
   ▼
ui/handlers/chat_handler.py → ui/handlers/agent_runtime_handler.py::send_to_special_agent()
   │
   ▼
agent/runtime.py::AgentRuntime.send_message(session_key, text)
   │  → _run_loop(session_key, text) [line 1387]
   ▼
agent/runtime.py::AgentRuntime._call_llm(session_key, messages, tools) [line 1889]
   │
   │  Routing decision [line 1969-1973]:
   │    use_streaming = (self._on_text_delta is not None) and
   │                    (provider_cfg.supports_streaming if provider_cfg else True)
   │  For Coder/Helper agents with the default UI: use_streaming = True
   │
   ▼
agent/runtime.py::AgentRuntime._call_llm_streaming(...) [line 1998]
   │
   │  Resolves streamer from _PROVIDER_STREAMERS[caller_key] [line 2040]
   │  For caller_key="minimax": _stream_minimax_events
   │  For caller_key="openai":  _stream_openai_events
   │  For caller_key="anthropic": _stream_anthropic_events
   │  For caller_key="openrouter"/"zai": _stream_openai_events
   │
   ▼
agent/runtime.py::_stream_minimax_events / _stream_openai_events / _stream_anthropic_events
   │
   │  POST-FIX FLOW (per §2.1.a-d):
   │  1. urllib.request opens POST to /text/chatcompletion_v2 (MiniMax) or /chat/completions (OpenAI)
   │  2. Iterate _sse_lines(resp) line-by-line [line 412-416]
   │  3. _parse_sse_line(line) returns SSEEvent(type="raw", data=json_dict) [line 419-436]
   │  4. For each raw event with delta.tool_calls[i]:
   │     a. Extract idx, fname, fargs from tcd
   │     b. *** STREAM-ID-PRES *** Extract tcd.get("id", "") → e.g. "call_function_3679004591_1"
   │     c. yield SSEEvent(type="tool_call_delta", data={
   │            "index": idx, "name": fname, "arguments": fargs, "id": tcd_id
   │        })
   │  5. For Anthropic: also handle content_block_start with block.type=="tool_use"
   │     and yield a tool_call_delta with id=block.id
   │
   ▼  (back in _call_llm_streaming)
agent/runtime.py::AgentRuntime._call_llm_streaming [line 1998-2112]
   │
   │  POST-FIX ACCUMULATOR [line 2062-2079]:
   │    for ev in streamer(...):
   │      if ev.type == "tool_call_delta":
   │        idx = ev.data.get("index", 0)
   │        if idx not in tool_calls_partial:
   │          tool_calls_partial[idx] = {"name": "", "arguments": "", "id": ""}
   │        tc = tool_calls_partial[idx]
   │        if ev.data.get("name"):       # *** was ev.data["name"]: would KeyError on sparse deltas ***
   │          tc["name"] = ev.data["name"]
   │        if ev.data.get("arguments"):
   │          tc["arguments"] += ev.data["arguments"]
   │        incoming_id = ev.data.get("id") or ""
   │        if incoming_id and not tc["id"]:  # first-write-wins
   │          tc["id"] = incoming_id
   │
   │  POST-FIX DONE-ASSEMBLY [line 2082-2094]:
   │    for idx in sorted(tool_calls_partial.keys()):
   │      tc = tool_calls_partial[idx]
   │      if tc["name"]:
   │        tool_calls.append({
   │          "id": tc["id"] or f"call_{idx}",   # *** was always f"call_{idx}" ***
   │          "function": {"name": tc["name"], "arguments": tc["arguments"]}
   │        })
   │
   │  POST-FIX FALLBACK-ASSEMBLY [line 2102-2113]: same id-preservation as done path
   │
   ▼
response = {"choices": [{"message": {"content": ..., "tool_calls": [
    {"id": "call_function_3679004591_1", "function": {"name": "read_file", "arguments": "..."}}
]}}], "usage": {...}}
   │
   ▼
agent/runtime.py::AgentRuntime._run_loop [line 1577-1710]
   │  tool_calls_raw = _extract_tool_calls(response, loop_provider) [line 1584]
   │    → [(call_id="call_function_3679004591_1", tool_name="read_file", args={...})]
   │
   ▼
ToolCall(call_id="call_function_3679004591_1", tool_name="read_file", arguments={...}) [line 1692]
   │
   ▼
Execute tool → ToolResult(success=True, output="file content", ...)
   │
   ▼
conv.add_tool_result("call_function_3679004591_1", "file content") [line 1710]
   │
   ▼
agent/runtime.py::AgentRuntime._run_loop (next iteration)
   │  messages = conv.to_api_messages() [line 1540]
   │
   ▼
models/conversation.py::Conversation.to_api_messages [line 207-251]
   │  Assistant message: {"role": "assistant", "content": ..., "tool_calls": [
   │    {"id": "call_function_3679004591_1", "type": "function", "function": {...}}
   │  ]}
   │  Tool result message: {"role": "tool", "tool_call_id": "call_function_3679004591_1", "content": "..."}
   │
   ▼
agent/runtime.py::AgentRuntime._call_llm → _call_minimax / _call_openai (next LLM call)
   │  MiniMax API receives: assistant tool_call with id="call_function_3679004591_1"
   │                        tool result with tool_call_id="call_function_3679004591_1"
   │  MiniMax API: ID MATCHES → accepts the request, no 2013 error
   ▼
MiniMax/OpenAI processes the next turn, returns either another tool_call or text response
   │
   ▼
Chat handler renders the response in the UI
```

**Pre-fix divergence (the bug):** At every step marked with `*** STREAM-ID-PRES ***`, the id is dropped. The synthetic `f"call_{idx}"` flows through. MiniMax sees `assistant.tool_calls[0].id="call_0"` on turn N+1 but its own internal record shows it issued `call_function_3679004591_1` on turn N. The IDs don't match → 2013 error.

---

## 4. File Change Summary

| File | Change type | Net lines | Risk level | Test coverage |
|---|---|---|---|---|
| `agent/runtime.py` | modify (3 yields + 1 accumulator + 2 assembly + 1 Anthropic block) | +12 / -3 | LOW (additive, backward-compatible) | NEW regression test (§2.2.a) |
| `tests/test_agent_runtime.py` | modify (add `test_streaming_preserves_provider_tool_call_id`) | +95 | LOW (new test, no existing test changes) | N/A (test IS the new coverage) |
| `docs/ARCHITECTURE.md` | modify (1 Streaming paragraph + optional 1 §12 sentence) | +6 / -4 | LOW (doc drift fix) | N/A (verified against source) |
| `docs/bugs/BUG_REPORT-streaming-tool-call-id-loss.md` | none (historical) | 0 | n/a | n/a |
| `docs/specs/SPEC-STREAMING-TOOL-CALL-ID-PRESERVATION.md` | none (this file) | 0 | n/a | n/a |

**Total implementation footprint:** ~3 files, ~110 net lines added.

---

## 5. Implementation Order

**Recommended order** (each step is independently testable; do not skip verification):

1. **Step 1 — Accumulator + assembly (2.1.e, 2.1.f, 2.1.g):** Modify the accumulator in `_call_llm_streaming` to capture `id` and the two assembly sites to use it. After this commit alone, the existing tests should still pass (no test asserts synthetic-id behavior, and the new field is empty by default → fallback to `f"call_{idx}"` preserves old behavior). The regression test from §2.2.a will still fail because the streamers don't forward `id` yet.

2. **Step 2 — Streamers (2.1.a, 2.1.b, 2.1.c):** Modify the three `tool_call_delta` yields in `_stream_openai_events` and `_stream_minimax_events` to include the `id` field. After this commit, the regression test from §2.2.a passes (id flows from SSE → streamer → accumulator → final response). The full bug is fixed for OpenAI, OpenRouter, ZAI, and MiniMax.

3. **Step 3 — Anthropic (2.1.d, optional):** Add the `content_block_start` handler in `_stream_anthropic_events`. Latent fix; not in the production trigger path but recommended for completeness.

4. **Step 4 — Docs (2.3.a, 2.3.c):** Update `docs/ARCHITECTURE.md` to reflect the new behavior.

5. **Step 5 — Verification (Rule 10):** Run the full test suite, paste output in commit message, confirm no old patterns remain via grep sweep.

**Verification at each step** (Rule 7 / Rule 10):
- After step 1: `cd /home/q/projects/crabcakes && python -m pytest tests/test_agent_runtime.py -v` — all existing tests should pass.
- After step 2: same command — the new test `test_streaming_preserves_provider_tool_call_id` should now pass; all pre-existing tests still pass.
- After step 3: same command — Anthropic-specific tests (if any) should pass; the change is additive.
- After step 4: `grep -n "STREAM-ID-PRES\|provider-assigned id" docs/ARCHITECTURE.md` — should show 1-2 matches in §3.21m and §12.

---

## 6. Acceptance Criteria

A checklist of testable outcomes. The implementer must verify each before declaring complete (Rule 10).

### Functional acceptance

- [ ] `_stream_openai_events` yields `tool_call_delta` events whose `data` dict contains an `id` key (default empty string when the upstream JSON omits the field).
- [ ] `_stream_minimax_events` yields `tool_call_delta` events whose `data` dict contains an `id` key (in both the first-line path and the main per-line path).
- [ ] `_stream_anthropic_events` handles `content_block_start` events with `block.type=="tool_use"` and surfaces the `id` via `tool_call_delta` (only if 2.1.d is in scope).
- [ ] `_call_llm_streaming` accumulator initializes `tool_calls_partial[idx]` with `{"name": "", "arguments": "", "id": ""}`.
- [ ] `_call_llm_streaming` accumulator uses `ev.data.get("name")` and `ev.data.get("arguments")` (not direct subscript).
- [ ] `_call_llm_streaming` accumulator captures the first incoming `id` per tool call (first-write-wins).
- [ ] `_call_llm_streaming` done-event assembly uses `tc["id"] or f"call_{idx}"` for the final `tool_calls[i]["id"]`.
- [ ] `_call_llm_streaming` fallback assembly uses `tc["id"] or f"call_{idx}"` for the final `tool_calls[i]["id"]`.
- [ ] `test_streaming_preserves_provider_tool_call_id` (in `tests/test_agent_runtime.py`) passes.
- [ ] All pre-existing tests in `tests/test_agent_runtime.py` continue to pass.

### Non-functional acceptance

- [ ] No new imports added to `agent/runtime.py` (the fix uses only built-in `.get()` and dict operations).
- [ ] The synthetic-id fallback (`f"call_{idx}"`) is preserved as a safety net — if a future provider omits `id`, the runtime still produces a syntactically valid response.
- [ ] `docs/ARCHITECTURE.md` §3.21m Streaming paragraph mentions `tool_call.id` preservation (or is updated to do so).
- [ ] No changes to `_call_llm` routing logic.
- [ ] No changes to `_extract_tool_calls` (non-streaming path remains unchanged).
- [ ] No changes to `to_api_messages` (serialization remains unchanged).
- [ ] No changes to `models/conversation.py`.
- [ ] No changes to `ui/handlers/agent_runtime_handler.py`.

### Verification (Rule 10)

- [ ] Scope checklist: every file in §2 has been changed (or explicitly NOT changed per §2.4).
- [ ] Test suite: full pytest output for `tests/test_agent_runtime.py` pasted in commit message; `1974 passed + 1 new test = 1975 passed` (or current count + 1).
- [ ] Pattern sweep: `grep -rn 'f"call_{idx}"' agent/runtime.py` should show 2 matches (the fallback `or` expressions in the done-event and fallback assemblies) — NOT 4 matches as before. The 2 remaining are intentional fallbacks.
- [ ] No declarations of "complete" until all 14 functional + 8 non-functional + 3 verification items above are checked.

---

## 7. Edge Cases

| # | Case | Expected behavior | Source |
|---|---|---|---|
| 1 | OpenAI/MiniMax SSE delta contains `id: ""` (empty string) | Accumulator's `if incoming_id and not tc["id"]:` rejects the empty id; `tc["id"]` stays empty; final assembly's `tc["id"] or f"call_{idx}"` falls back to synthetic. | §2.1.e, §2.1.f |
| 2 | OpenAI/MiniMax sends `id` in a non-first delta (rare; provider bug) | First-write-wins keeps the first id; subsequent ids are ignored. Logged at DEBUG level via existing logger in `_call_llm_streaming`. | §2.1.e, comment |
| 3 | Sparse delta (only `id`, no `name` or `arguments`) from a custom provider | `.get()` prevents `KeyError`; `name` and `arguments` stay empty; `id` is captured. | §2.1.e (BUG #5 fix) |
| 4 | Two tool calls in one stream, ids arrive in interleaved deltas (standard OpenAI pattern) | `tool_calls_partial[0]` and `tool_calls_partial[1]` each get their own id via the first-write-wins logic; final assembly sorts by index and emits both with their real ids. | §2.1.e, §2.1.f |
| 5 | Stream ends without an explicit `done` event (fallback path) | Fallback assembly at line 2102-2113 uses the same `tc["id"] or f"call_{idx}"` logic as the done-event path. | §2.1.g |
| 6 | Provider sends a tool_call delta with `id: null` (some providers do this) | `tcd.get("id", "") or ""` in the streamer normalizes `None` to empty string; same as case 1. | §2.1.a, §2.1.b, §2.1.c |
| 7 | Existing conversation file on disk with synthetic `call_0` ids (pre-fix conversations) | Conversation loads fine, but on the next turn MiniMax will still reject with 2013 because the persisted `call_id` is synthetic. User must clear the affected conversation (via UI or by deleting the file in `~/.config/crabcakes/conversations/`). Surface this in the release notes. | BUG #7 in bug report; pre-existing data, not auto-migrated |
| 8 | Anthropic streaming with `content_block_start` arriving AFTER the first `content_block_delta` (out-of-order, network reordering) | `content_block_start` handler still runs (it's a separate SSE event); the empty `id: ""` from the delta is a no-op (first-write-wins, but the `id` is already empty); when the real id finally arrives via `content_block_start`, it sets `tc["id"]` correctly. Final assembly emits the real id. | §2.1.d, §2.1.e |
| 9 | Anthropic streaming where the `id` arrives only via `content_block_delta` (provider deviation from spec) | The new code emits `id: ""` from deltas, so the real id would be lost. Mitigation: log a WARNING if a tool_call has a non-empty `id` in a delta but empty `tc["id"]` after the stream ends. (Out of scope for this spec; document in code comment.) | §2.1.d, comment |
| 10 | Network timeout mid-stream (e.g. `_urlopen_with_ssl_retry` exhausts retries) | `_call_llm_streaming` raises; the existing `on_error` callback handles user notification. The half-built `tool_calls_partial` is discarded. No persistence of partial data. | Existing error handling, line 2050+ |
| 11 | Provider returns a non-tool_call response (just text) | `tool_calls_partial` stays empty; done-event / fallback assembly's `if tc["name"]` filter (line 2087 / 2107) excludes the empty partials; final `tool_calls` is `[]`. | §2.1.f, §2.1.g |
| 12 | `default_model` in `providers.yaml` contains no slash (e.g. `local-kb` provider) | Streaming path is **skipped** entirely because `provider_cfg.supports_streaming=False` for `local-kb` (per §12 line 3403 in ARCHITECTURE.md); non-streaming `_call_llm` → blocking provider caller is used; the bug never triggers. | §3.21m, §12 |

---

## 8. ARCHITECTURE.md Updates Required

Per `docs/ARCHITECTURE.md` §0 ("Keeping This Document Current"), this code change must include the following updates in the **same commit** (or a follow-up commit explicitly cross-referenced):

1. **§3.21m Streaming paragraph (line 1380):** Replace the current one-liner with the new text from §2.3.a above. Required because the streaming path's `tool_call.id` preservation semantics are now part of the runtime contract.

2. **§12 Anthropic stream format (line 3403+):** If 2.1.d is in scope, add the new sentence from §2.3.c above. Optional if 2.1.d is deferred.

3. **§13 File Inventory (line 3448):** Update `agent/runtime.py` line count annotation from `~1420 lines` to the new line count after the fix. The actual line count after the patch will be ~1432-1440 lines depending on comment density.

**Out of scope for ARCHITECTURE.md updates:**
- §2 (Directory Structure) — no new files added.
- §3 (Module Responsibilities) — `AgentRuntime`'s responsibility is unchanged; only the implementation details change.
- §4 (Data flow) — the data flow diagram at §4 is high-level; the new tool_call id preservation is implementation detail.
- §5-7 (Patterns/Conventions) — no pattern changes.
- §10 (Environment variables) — no env var changes.
- §11 (Protocol reference) — no protocol changes.

---

## 9. Completion Verification (Rule 10)

The implementer must pass all four Rule 10 checks before declaring this spec complete:

### Check 1: Scope checklist

```
[ ] agent/runtime.py — modified (§2.1.a, 2.1.b, 2.1.c, 2.1.d, 2.1.e, 2.1.f, 2.1.g)
[ ] tests/test_agent_runtime.py — modified (§2.2.a, added test_streaming_preserves_provider_tool_call_id)
[ ] docs/ARCHITECTURE.md — modified (§2.3.a, possibly §2.3.c)
```

If 2.1.d is deferred, mark it explicitly as `DEFERRED — separate ticket`. Do not silently skip.

### Check 2: Test suite output

The implementer must paste the actual pytest output (not a summary) in the commit message. Expected output (approximate):

```
$ cd /home/q/projects/crabcakes && python -m pytest tests/test_agent_runtime.py -v
...
tests/test_agent_runtime.py::TestStreaming::test_text_delta_fires_incrementally PASSED
tests/test_agent_runtime.py::TestStreaming::test_response_complete_fires_after_stream PASSED
tests/test_agent_runtime.py::TestStreaming::test_tool_call_start_fires_when_complete PASSED
tests/test_agent_runtime.py::TestStreaming::test_streaming_accumulates_text_in_response PASSED
tests/test_agent_runtime.py::TestStreaming::test_tool_call_delta_without_index_defaults_to_zero PASSED
tests/test_agent_runtime.py::TestStreaming::test_streaming_preserves_provider_tool_call_id PASSED
...
============= NN passed in X.YZs ==============
```

(NN = previous count + 1 for the new test.)

If the suite cannot be run (e.g. test environment unavailable), the implementer must say so explicitly and provide a reason.

### Check 3: Pattern sweep

```bash
$ cd /home/q/projects/crabcakes && grep -rn 'f"call_{idx}"' agent/runtime.py
2087:                        "id": tc["id"] or f"call_{idx}",
2105:                        "id": tc["id"] or f"call_{idx}",
```

**Expected output:** 2 matches (the fallback expressions in the done-event and fallback assemblies, used only when the captured `id` is empty). NOT 4 matches as before the fix (the old code had 4 unconditional `f"call_{idx}"` expressions).

If any unconditional `f"call_{idx}"` remains (i.e., not part of an `or` expression), the fix is incomplete. The implementer must fix and re-grep.

### Check 4: Declaration

Only declare "complete" when all three checks above pass. If any check fails, the implementer must report:
- What was done
- What is missing
- What is blocking

**Never declare complete with unfinished work.**

---

## 10. Self-Audit (Rule 9)

The spec author re-reads this document with fresh eyes and checks:

1. **Does every code sample actually work against the current codebase?** YES — every line of `agent/runtime.py` cited was re-read at the stated line numbers on the current `main` branch (commit `e154f37`). The `SSEEvent` namedtuple is at line 408, `_sse_lines` is at line 412, `_parse_sse_line` is at line 419, `_stream_openai_events` is at line 473, `_stream_minimax_events` is at line 542, `_stream_anthropic_events` is at line 658, `_call_llm_streaming` is at line 1998, the accumulator is at lines 2062-2070, the done-event assembly is at lines 2082-2094, the fallback assembly is at lines 2102-2113, the tool_call_delta yields are at lines 531, 612, 644, and 722. `_extract_tool_calls` is at line 752, and the non-streaming id preservation is at line 774. `to_api_messages` is at line 207 in `models/conversation.py` with the assistant tool_calls serialization at line 230 and the tool result at line 240.

2. **Did I catch all exception types for every function I call in the test?** YES — the test mocks `_sse_lines` so no `urllib.error.URLError` can fire; the test uses raw JSON bytes so `json.JSONDecodeError` is caught by `_parse_sse_line` internally (line 434); the test does not exercise the MiniMax body-level error path; `KeyError` is eliminated by the `.get()` fix.

3. **Did I verify key structures, not assume them?** YES — `tool_calls_partial: dict[int, dict[str, str]]` is verified at line 2062-2070; `SSEEvent.data: dict` is verified at line 408; the final response shape `{"choices": [{"message": {"content": ..., "tool_calls": [...]}}], "usage": ...}` is verified at line 2094-2097.

4. **Did I trace the data flow end-to-end?** YES — §3 traces the full path from user message in chat tab through `_call_llm_streaming` → streamer → SSE parsing → accumulator → assembly → `_extract_tool_calls` → `ToolCall` → `to_api_messages` → next-turn LLM call → MiniMax acceptance.

5. **Would an implementer who follows this spec exactly produce working code?** YES — every code sample is verified against current source; every line number is verified; the test pattern is derived from the existing `test_tool_call_delta_without_index_defaults_to_zero` test (line 943) and uses the same `AgentRuntime`, `_make_cfg`, `_uniq` helpers. The `from agent.runtime import _extract_tool_calls` import is already at the top of the test file (line 17-25).

**One self-audit catch found during this audit:** The original draft of the test used `BytesIO` for the mock response, but `_sse_lines` calls `for line in resp: yield line.strip()`, which works on any iterable that yields `bytes` lines (one per `\n`). Using a custom `_LineStream` wrapper around a `bytes.splitlines(keepends=True)` is simpler than mocking an `http.client` response. The §2.2.a test sample uses this simpler approach.

**No further audit issues found.**

---

**Mantra:** "A spec is a contract. If it has a bug, the implementer will ship that bug. Verify everything."

**Mantra 2:** "Done means every file changed, every test passing, every old pattern gone. Not 'I think I got the important ones.'"