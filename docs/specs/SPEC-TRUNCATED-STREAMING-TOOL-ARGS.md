# SPEC: Truncated Streaming Tool-Call Arguments Crash

**Date:** 2026-07-20
**Status:** Draft — for implementation
**Bug origin:** Coder terminal error (deepseek provider, stream cut mid-tool-call)
**Depends on:** None

> Architecture compliance statement: `agent/llm/extractors.py` is pure Python with no GTK imports. `agent/runtime.py`'s `_call_llm_streaming` is already in `agent/` (no cross-layer imports introduced). Both fixes respect layer separation.

---

## 1. Problem

When an OpenAI-compatible provider (deepseek, and potentially others) drops a streaming connection **without** sending a `[DONE]` sentinel or a `finish_reason` chunk, the SSE assembly loop in `_call_llm_streaming` falls through to the "no done event" fallback path. That fallback builds a response dict from the accumulated `tool_calls_partial` fragments — but it does **not** validate that the concatenated argument fragments form complete JSON.

The resulting response dict is passed to `extract_tool_calls` (`agent/llm/extractors.py:53`), which calls `json.loads(args_raw)` with **no try/except**. When the arguments are a truncated JSON fragment (e.g. `{"command": "git sta`), `json.loads` raises `json.decoder.JSONDecodeError: Unterminated string starting at...` which propagates up through `_run_loop` and kills the agent turn with an error bubble.

### Observed traceback (verified)

```
agent.runtime ERROR Error in tool loop for special:coder
Traceback (most recent call last):
  File ".../agent/runtime.py", line 1003, in _run_loop
    tool_calls_raw = extract_tool_calls(response, response_format=loop_fmt)
  File ".../agent/llm/extractors.py", line 53, in extract_tool_calls
    args = json.loads(args_raw)
  ...
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 13 (char 12)
```

The preceding log line `[stream-fallback] sk=special:coder text_len=134 tool_calls=1 (no done event)` confirms the fallback path was taken.

### Two vulnerable call sites for `extract_tool_calls`

1. `agent/runtime.py:1003` — primary tool-loop extraction (`_run_loop`)
2. `agent/runtime.py:1146` — fallback-LLM-call extraction

Both pass provider responses through `extract_tool_calls`; both crash on truncated arguments.

---

## 2. Fix — Two Layers

### Layer 1 (defensive chokepoint): `agent/llm/extractors.py`

Wrap `json.loads(args_raw)` in `extract_tool_calls` with try/except. On `json.JSONDecodeError`, log a warning and **skip** the malformed tool call (do not append to `calls`). This is the single chokepoint that protects both call sites.

**Behavior change:** A response containing one valid and one malformed tool call yields the single valid call; a response containing only malformed calls yields an empty list (the loop then treats the response as text-only, which is reasonable degraded behavior for a truncated stream).

### Layer 2 (source): `agent/runtime.py` `_call_llm_streaming` fallback

In the "no done event" fallback (the code path after the `for ev in stream_with_ssl_retry(...)` loop, ~lines 1653-1668), validate each accumulated tool call's `arguments` string with `json.loads` before appending it to the emitted `tool_calls` list. On `json.JSONDecodeError`, log a warning and **skip** the tool call. This catches the truncation at the source so downstream consumers never see malformed arguments.

The `done`-event path (~lines 1632-1648) is **structurally identical** to the fallback path and accumulates fragments the same way. For consistency and completeness, apply the same validation there. (A clean `[DONE]` is unlikely to produce truncated JSON, but the two paths share the accumulation logic and should share the validation — a single helper is preferable to divergent code.)

---

## 3. Test Impact

### `tests/test_llm_extractors.py`

The existing test `test_extract_tool_calls_malformed_json_args_raises` **explicitly asserts the current crash behavior**:

```python
def test_extract_tool_calls_malformed_json_args_raises(self):
    """Malformed JSON string arguments → json.loads raises (verbatim behavior)."""
    response = {...}
    with pytest.raises(json.JSONDecodeError):
        extract_tool_calls(response, response_format="openai")
```

This test MUST be updated to reflect the new graceful-degradation contract: malformed args are skipped, not raised. Rename and rewrite it to assert that:
- A malformed-only response yields an empty list (no raise)
- A mixed response (one valid + one malformed) yields only the valid call

### `tests/test_agent_runtime.py` (Layer 2)

Add tests covering the streaming-fallback validation:
- Fallback with one valid + one malformed tool call → only the valid call is emitted
- Fallback with only malformed tool calls → empty tool_calls list, with a warning logged

---

## 4. Acceptance Criteria

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | `extract_tool_calls` does not raise on malformed JSON arguments | `tests/test_llm_extractors.py` — updated test asserts empty/skipped, not raise |
| 2 | `extract_tool_calls` preserves valid tool calls alongside malformed ones | `tests/test_llm_extractors.py` — mixed-response test |
| 3 | `_call_llm_streaming` fallback skips tool calls with malformed accumulated arguments | `tests/test_agent_runtime.py` — fallback validation test |
| 4 | `_call_llm_streaming` done-event path applies the same validation | `tests/test_agent_runtime.py` — done-event validation test (or shared helper test) |
| 5 | No regressions in existing tests | `pytest tests/test_llm_extractors.py tests/test_agent_runtime.py` |

---

## 5. File Change Summary

| File | Change | Fix |
|------|--------|-----|
| `agent/llm/extractors.py` | try/except around `json.loads` in `extract_tool_calls` | Layer 1 |
| `tests/test_llm_extractors.py` | Rewrite `test_extract_tool_calls_malformed_json_args_raises` → graceful-degradation assertion; add mixed-response test | Layer 1 |
| `agent/runtime.py` | Validate accumulated arguments in `_call_llm_streaming` fallback + done paths (~lines 1632-1668) | Layer 2 |
| `tests/test_agent_runtime.py` | Add fallback/done validation tests | Layer 2 |
