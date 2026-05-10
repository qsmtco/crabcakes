# MiniMax Tool Calling Investigation

> **Status: FIXED** — Root cause was MiniMax not sending `[DONE]` sentinel. Fix applied: `_stream_minimax_events()` in `agent/runtime.py` now yields `SSEEvent(type="done")` when `finish_reason` is detected (line ~379).

**Date:** 2026-05-07
**Issue:** CrabCakes Coder/Debugger agents receive no tool calls from MiniMax-M2.7
**Status:** ROOT CAUSE IDENTIFIED

---

## TL;DR

MiniMax's streaming API does **not** send the `data: [DONE]` sentinel that OpenAI sends at the end of its SSE streams. CrabCakes' `_call_llm_streaming()` only assembles tool calls when it receives a `done` SSE event — which is triggered by `[DONE]`. When MiniMax's stream ends naturally (HTTP connection closes), the code falls through to a fallback return that **discards all accumulated tool calls** and returns `tool_calls: []`.

Result: MiniMax correctly generates tool calls, they arrive in the SSE stream, CrabCakes accumulates them in `tool_calls_partial`, and then **throws them all away**.

---

## Root Cause

### File: `agent/runtime.py`

### Bug Location 1: `_stream_minimax_events()` (line ~353)

The MiniMax streamer only yields `SSEEvent(type="done")` when it sees `[DONE]`:

```python
if data == b"[DONE]" or data == b"DONE":
    return SSEEvent(type="done", data={})
```

MiniMax never sends `[DONE]`. It signals stream completion via `finish_reason` in the JSON payload of the last few chunks instead.

### Bug Location 2: `_call_llm_streaming()` (line ~517)

The streaming caller only assembles `tool_calls_partial` into the response dict inside the `elif ev.type == "done":` branch:

```python
elif ev.type == "done":
    # Build final tool_calls list from accumulated partials
    tool_calls = []
    for idx in sorted(tool_calls_partial.keys()):
        ...
    return {"choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}], "usage": {}}
```

When `done` never fires (MiniMax case), execution falls through to:

```python
# Should not reach here — done event should always fire
return {"choices": [{"message": {"content": full_content, "tool_calls": []}}]}
```

This returns the accumulated text (including thinking tags) but **zero tool calls**.

### Evidence

**Direct API test (blocking):** MiniMax returns tool calls correctly:
```json
{
  "choices": [{
    "finish_reason": "tool_calls",
    "message": {
      "tool_calls": [{
        "id": "call_function_259b4qo83ucg_1",
        "function": {"name": "read_file", "arguments": "{\"path\": \"pyproject.toml\"}"}
      }]
    }
  }]
}
```

**Direct API test (streaming):** MiniMax sends 6 SSE chunks, the last 2 with `finish_reason: "tool_calls"`, but **no `data: [DONE]`**:
```
data: {"choices":[{"delta":{"content":"💡...","role":"assistant"}}]}
data: {"choices":[{"delta":{"content":" wants me to read..."}}]}
data: {"choices":[{"delta":{"tool_calls":[{"id":"...","function":{"name":"read_file","arguments":""}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"function":{"arguments":"{\"path\": \"pyproject.toml\"}"}}]}}]}
data: {"choices":[{"finish_reason":"tool_calls","delta":{"content":"\n"}}]}
data: {"choices":[{"finish_reason":"tool_calls","delta":{"content":""}}]}
(NO [DONE])
```

**User's debug log:** `text_len=101, tool_calls=0, tokens=0, cost=0.0000` — the 101 chars is the thinking content (`💡The user wants me to read...`), tool_calls is 0 because they were discarded.

---

## Fix

### Option A (Minimal Fix): Detect `finish_reason` in `_stream_minimax_events`

Add `finish_reason` detection in the MiniMax streamer to yield `done`:

```python
def _stream_minimax_events(...):
    ...
    for line in _sse_lines(resp):
        ev = _parse_sse_line(line)
        if ev is None:
            continue
        if ev.type == "done":
            yield SSEEvent(type="done", data={})
            return
        if ev.type != "raw":
            continue
        d = ev.data
        delta = d.get("choices", [{}])[0].get("delta", {})
        finish_reason = d.get("choices", [{}])[0].get("finish_reason")

        if "content" in delta:
            yield SSEEvent(type="text_delta", data={"content": delta["content"]})
        tc_delta = delta.get("tool_calls", [])
        for tcd in tc_delta:
            idx = tcd.get("index", 0)
            if "function" in tcd:
                fname = tcd["function"].get("name") or ""
                fargs = tcd["function"].get("arguments", "") or ""
                yield SSEEvent(type="tool_call_delta", data={
                    "index": idx, "name": fname, "arguments": fargs
                })
        # MiniMax signals end via finish_reason, not [DONE]
        if finish_reason in ("stop", "tool_calls", "length"):
            yield SSEEvent(type="done", data={})
            return
```

### Option B (Robust Fix): Fix the fallback in `_call_llm_streaming`

Also fix the fallback return to include accumulated tool calls:

```python
    # Fallback — stream ended without explicit done event (e.g. MiniMax)
    tool_calls = []
    for idx in sorted(tool_calls_partial.keys()):
        tc = tool_calls_partial[idx]
        if tc["name"]:
            tool_calls.append({
                "id": f"call_{idx}",
                "function": {"name": tc["name"], "arguments": tc["arguments"]}
            })
    return {"choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}], "usage": {}}
```

**Recommendation: Apply both Option A and Option B.** Option A fixes MiniMax specifically; Option B is a safety net for any provider that doesn't send `[DONE]`.

---

## Secondary Issue: Usage Tracking

MiniMax streaming does not include `usage` data in SSE chunks (all chunks show `"usage": null`). This means `tokens=0, cost=0.0000` for every streaming call. MiniMax only returns usage in the blocking response. Possible fixes:

1. Make a blocking warmup call to get prompt_tokens, then add completion_tokens from streamed output
2. Estimate tokens client-side (4 chars/token rough)
3. Accept zero usage for streaming (current behavior — acceptable for MVP)

This is a **known limitation**, not a bug. The MiniMax blocking API does return usage correctly.

---

## Secondary Issue: Thinking Content in `full_content`

MiniMax-M2.7 includes `<think...</thinkable>` reasoning tags in the `content` field. These get accumulated in `full_content` and returned as the "text response." When tool calls are properly detected, this is fine — the tool loop uses tool_calls and ignores text. But if tool_calls are lost (the bug above), the thinking text gets dispatched as a regular text response, showing the user raw reasoning tags.

This is a **consequence of the primary bug**, not an independent issue. Once tool calls are properly detected, the thinking content is harmless.

---

## Verification: OpenAI Comparison

OpenAI's streaming SSE format:
```
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: {"choices":[{"delta":{"content":" world"}}]}
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]                                    ← OpenAI always sends this
```

MiniMax's streaming SSE format:
```
data: {"choices":[{"delta":{"content":"💭..."}}]}
data: {"choices":[{"delta":{"tool_calls":[...]}}]}
data: {"choices":[{"finish_reason":"tool_calls","delta":{}}]}
                                                  ← MiniMax stops here, no [DONE]
```

The OpenAI streamer (`_stream_openai_events`) has the same `[DONE]`-dependent logic but works because OpenAI actually sends `[DONE]`.

---

## API Endpoints

CrabCakes currently uses MiniMax's **proprietary** endpoint:
```
POST {base_url}/text/chatcompletion_v2
```

MiniMax also provides an **OpenAI-compatible** endpoint:
```
POST {base_url}/chat/completions
```

Both endpoints exhibit the same behavior (no `[DONE]` in streams). The fix should work for both.

For future consideration: switching to `/v1/chat/completions` would improve compatibility with OpenAI SDKs and tooling.

---

## MiniMax Tool Calling Reference

### Correct Request Format (OpenAI-compatible)
```json
{
  "model": "MiniMax-M2.7",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {
          "type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]
        }
      }
    }
  ],
  "stream": true
}
```

### Key Parameters
- `tools`: Array of function definitions (same format as OpenAI)
- `tool_choice`: Optional, defaults to `"auto"` (implicit)
- `temperature`: Range (0.0, 1.0], recommended 1.0
- `reasoning_split`: Set to `true` for separated thinking output

### Multi-turn Tool Conversations
MiniMax docs emphasize: **always append the full assistant response** (including `tool_calls` and thinking content) to the message history. CrabCakes' `to_api_messages()` does this correctly.

---

## Sources

1. MiniMax Tool Calling Guide: https://github.com/MiniMax-AI/MiniMax-M2.7/blob/main/docs/tool_calling_guide.md
2. MiniMax OpenAI-Compatible API: https://platform.minimax.io/docs/api-reference/text-openai-api
3. MiniMax Tool Use & Interleaved Thinking: https://platform.minimax.io/docs/guides/text-m2-function-call
4. MiniMax M2.7 for AI Coding Tools: https://platform.minimax.io/docs/guides/text-ai-coding-tools
5. Direct API tests performed 2026-05-07 (blocking + streaming, both endpoints)

---

## Next Steps

1. Apply Option A fix to `_stream_minimax_events()` — detect `finish_reason`
2. Apply Option B fix to `_call_llm_streaming()` fallback — include accumulated tool_calls
3. Test with `CRABCAKES_DEBUG=1` against crabwatch project
4. Verify tool calls flow through: Coder reads file → shows content → responds
5. Commit and push
