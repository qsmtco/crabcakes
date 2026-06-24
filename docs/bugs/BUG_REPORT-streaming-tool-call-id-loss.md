# ADVERSARIAL DEBUG REPORT — Streaming Tool-Call ID Loss (MiniMax/OpenAI/OpenRouter/ZAI)

> **Status:** Report only — no code changes made
> **Severity:** HIGH
> **Date:** 2026-06-23
> **Investigator:** QTR (read-only audit of pre-existing report)
> **Related:** MiniMax API error `status_code=2013: invalid params, tool call result does not follow tool call`

---

## Executive Summary

When a special agent (Coder, Helper, etc.) uses the **streaming** LLM path, the runtime discards the real `tool_call.id` field that MiniMax/OpenAI assigns in the SSE stream and replaces it with a synthetic `call_{idx}` (e.g., `call_0`, `call_1`). On the next turn, the conversation history is sent back to the LLM with the synthetic ID, and the LLM rejects the request with `status_code=2013: invalid params, tool call result does not follow tool call` because the `tool_call_id` on the `tool` role message does not match any preceding `tool_calls[i].id` in the `assistant` message.

This affects **every streaming provider** in the codebase:
- `minimax` (uses `_stream_minimax_events`) — confirmed production trigger
- `openai` (uses `_stream_openai_events`) — same code path
- `openrouter` (uses `_stream_openai_events`) — same code path
- `zai` (uses `_stream_openai_events`) — same code path

The non-streaming path is correct: `_call_minimax` returns the raw API response with the real ID, and `_extract_tool_calls` reads it via `tc.get("id", fallback)` (line 774 in `agent/runtime.py`).

**Introduced in:** commit `7b8148a` (Apr 21 2026, "feat: agent runtime, convergence detection, adversarial audits, product vision") — the original streaming implementation. The synthetic `f"call_{idx}"` pattern has never been updated. The `85c2a41` follow-up fix ("MiniMax streaming tool calls + exec_command double card") addressed the missing `done` event but did NOT fix the ID loss.

---

## BUG #1 — Root cause: `id` field discarded in SSE streamer

**Severity:** HIGH

**Assumption violated:** When an LLM provider returns a streaming response that includes a `tool_call.id` in the SSE delta, the runtime will preserve that ID through the streaming assembly, the `_extract_tool_calls` consumer, the `ToolCall.call_id` storage, and the next-turn API request serialization. IDs are opaque to clients but providers (especially MiniMax) use them to correlate `assistant` tool_calls with subsequent `tool` role results.

**Attack vector — production reproduction:**

1. Open the crabCakes UI.
2. Ask the `special:coder` agent to read a file (any path).
3. The runtime routes through `_call_llm` → `use_streaming=True` (line 1969: `on_text_delta is not None and provider_cfg.supports_streaming`) → `_call_llm_streaming` (line 2010) → `_stream_minimax_events` (line 588) → SSE event stream from `https://api.minimax.chat/v1/text/chatcompletion_v2`.
4. MiniMax returns a tool_call delta with a real ID like `"id": "call_function_3679004591_1"`.
5. `_stream_minimax_events` (lines 612-614) yields `SSEEvent(type="tool_call_delta", data={"index": idx, "name": fname, "arguments": fargs})` — **the `id` field is dropped here**.
6. `_call_llm_streaming` (lines 2063-2068) accumulates the partial tool call in `tool_calls_partial[idx] = {"name": "", "arguments": ""}` — **no `id` field is initialized**.
7. On the `done` event (line 2082-2093), the assembler builds the final response: `{"id": f"call_{idx}", "function": {...}}` — **a synthetic ID is generated**.
8. `_extract_tool_calls` (line 774) reads `call_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")` — gets the synthetic `call_0`.
9. `ToolCall(call_id="call_0", tool_name="read_file", arguments={...})` is stored on the assistant message.
10. After the tool executes, the result is added as `conv.add_tool_result("call_0", "file content")` (line 1710).
11. On the **next** turn, `conv.to_api_messages()` (line 230 in `models/conversation.py`) serializes both:
    - Assistant message: `{"role": "assistant", "tool_calls": [{"id": "call_0", "type": "function", "function": {"name": "read_file", "arguments": "..."}}]}`
    - Tool result: `{"role": "tool", "tool_call_id": "call_0", "content": "file content"}`
12. The `_call_llm` method sends this to MiniMax on the next iteration of the tool loop (line 1577).
13. MiniMax rejects the request: `status_code=2013: invalid params, tool call result does not follow tool call`.

The error matches the upstream public report: [anomalyco/opencode#32608](https://github.com/anomalyco/opencode/issues/32608) — "OpenCode Go: minimax-m3 fails with 'tool call result does not follow tool call' (2013)". Same model, same error code, same root cause class (corrupted history due to ID mismatch).

**Root cause:** The streaming SSE handler discards `id` from `tool_call_delta` events. The accumulator does not track it. The final assembly synthesizes a fake ID. The fake ID propagates through `_extract_tool_calls` → `ToolCall.call_id` → conversation JSON → next-turn API request → MiniMax rejection.

**Fix:**

**(a) `_stream_minimax_events` (line 612-614) and `_stream_openai_events` (line 531-533):**

```python
# Before:
yield SSEEvent(type="tool_call_delta", data={
    "index": idx, "name": fname, "arguments": fargs
})
# After:
yield SSEEvent(type="tool_call_delta", data={
    "index": idx, "name": fname, "arguments": fargs,
    "id": tcd.get("id", ""),  # PRESERVE — MiniMax/OpenAI-assigned tool_call ID
})
```

**(b) `_call_llm_streaming` accumulator (lines 2063-2068):**

```python
# Before:
elif ev.type == "tool_call_delta":
    idx = ev.data.get("index", 0)
    if idx not in tool_calls_partial:
        tool_calls_partial[idx] = {"name": "", "arguments": ""}
    tc = tool_calls_partial[idx]
    if ev.data["name"]:
        tc["name"] = ev.data["name"]
    if ev.data["arguments"]:
        tc["arguments"] += ev.data["arguments"]
# After:
elif ev.type == "tool_call_delta":
    idx = ev.data.get("index", 0)
    if idx not in tool_calls_partial:
        tool_calls_partial[idx] = {"name": "", "arguments": "", "id": ""}
    tc = tool_calls_partial[idx]
    if ev.data.get("name"):
        tc["name"] = ev.data["name"]
    if ev.data.get("arguments"):
        tc["arguments"] += ev.data["arguments"]
    if ev.data.get("id"):
        tc["id"] = ev.data["id"]  # PRESERVE — providers send ID in first delta per tool call
```

**(c) `_call_llm_streaming` final assembly (line 2087 and line 2104, the fallback path):**

```python
# Before:
tool_calls.append({
    "id": f"call_{idx}",
    "function": {"name": tc["name"], "arguments": tc["arguments"]}
})
# After:
tool_calls.append({
    "id": tc["id"] or f"call_{idx}",  # Use real provider ID; fallback only if missing
    "function": {"name": tc["name"], "arguments": tc["arguments"]}
})
```

---

## BUG #2 — Anthropic streamer also loses IDs (latent)

**Severity:** MEDIUM (latent — only affects Anthropic streaming, which the codebase may or may not exercise)

**Assumption violated:** Anthropic's streaming tool_calls preserve the `tool_use_id` that Anthropic assigns in `content_block_start` events.

**Attack vector:** Anthropic's SSE format is structurally different from OpenAI/MiniMax. Anthropic sends the `id` in `content_block_start` (one event per tool_use block), not in `content_block_delta`. The Anthropic streamer at lines 717-725 only handles `content_block_delta` and discards `content_block_start` entirely (or at least does not propagate its `id`).

```python
# _stream_anthropic_events, lines 717-725 — id is never captured
elif dtype == "tool_use_delta":
    idx = d.get("index", 0)
    fname = delta.get("name") or ""
    fargs = delta.get("input", "") or ""
    yield SSEEvent(type="tool_call_delta", data={
        "index": idx, "name": fname, "arguments": fargs
    })
```

`grep` confirms there is no handler for `content_block_start` in `_stream_anthropic_events` (line 658-738). On the Anthropic path, the `id` would have to come from a captured `content_block_start` event, but no such event is yielded to the consumer. Therefore the accumulator at line 2063 would also see no `id`, and the final assembly would synthesize `call_{idx}` for Anthropic too.

**Why this is latent, not active:** The conversion in `_call_anthropic` (line 320-325) maps `tc["id"]` from the OpenAI-format tool_call → `id` field in Anthropic's `tool_use` content block. So the round-trip request includes the right field, but if the value is `call_{idx}` (synthetic), Anthropic's `tool_use_id` matching would fail on its side too. However, the conversion is done client-side and the synthetic value is consistent across the assistant message and the `tool_result` message in the same conversation turn, so Anthropic might accept it (its own IDs are internal; the client-side value is what it echoes back as `tool_use_id`). The risk is provider-specific.

**Root cause:** Anthropic SSE format separates `id` (in `content_block_start`) from `name`/`input` (in `content_block_delta`). The current streamer handles only the delta.

**Fix:** Capture `content_block_start` events with `block.type == "tool_use"`, store the `id` keyed by `index`, and propagate it via a new event type (e.g., `tool_call_id` with just `{"index": idx, "id": block.get("id")}`) or by extending `tool_call_delta` data. The accumulator and assembler changes in BUG #1 will then work for Anthropic too.

**Recommendation:** Fix this proactively as part of BUG #1, even though the production trigger is MiniMax. The codebase already has a `_RESPONSE_FORMAT["anthropic"]` branch in `_extract_tool_calls` (line 781-793), and the Anthropic streaming path is registered in `_PROVIDER_STREAMERS` (line 740). If anyone configures Anthropic, they will hit the same class of bug.

---

## BUG #3 — Inconsistent ID strategy between streaming and non-streaming paths (latent inconsistency)

**Severity:** LOW (latent)

**Assumption violated:** The streaming and non-streaming paths produce equivalent conversation histories, so switching between them mid-session is safe.

**Attack vector:** Two ID-generation strategies exist side by side:

- **Non-streaming** (`_extract_tool_calls` line 774): `tc.get("id", f"call_{uuid.uuid4().hex[:8]}")` — uses real ID if present, else a 16-char UUID hex prefix.
- **Streaming** (`_call_llm_streaming` line 2087): `"id": f"call_{idx}"` — always synthetic on the streaming path (since the real ID is dropped in the SSE handler), integer-indexed.

If a conversation ever switched from streaming to non-streaming mid-session, the IDs would not be compatible (UUID hex vs integer index). This is unlikely in practice because `_call_llm` chooses one path per call based on `on_text_delta` registration (line 1969), and the registration is stable for the lifetime of the runtime. But the inconsistency is a smell.

**Root cause:** Two separate ID-generation strategies, not centralized.

**Fix:** After BUG #1, the streaming path will use real provider IDs, matching the non-streaming path. The synthetic fallback (`call_{idx}` vs `call_{uuid}`) only triggers if the provider omits the ID, which is a degenerate case. No additional change needed, but a comment in `_call_llm_streaming` would be helpful.

---

## BUG #4 — Existing tests do not exercise the ID-preservation path

**Severity:** MEDIUM (test coverage gap that allowed BUG #1 to ship)

**Assumption violated:** Tests in `tests/test_agent_runtime.py` exercise the streaming tool_call assembly with realistic SSE delta shapes (including `id` fields), so a regression in ID preservation would be caught.

**Attack vector:** The test fixture for streaming tool_calls (`tests/test_agent_runtime.py` line 812-826) is:

```python
def _mock_stream_with_tool_call():
    ...
    yield SSEEvent(type="tool_call_delta", data={"index": 0, "name": "list_files", "arguments": ""})
    yield SSEEvent(type="tool_call_delta", data={"index": 0, "name": "", "arguments": '{"path": "."}'})
```

**No `id` field is emitted.** The test asserts that `tool_calls[0].function.name == "list_files"` and `tool_calls[0].function.arguments == '{"path": "."}'` (line 911 onwards), but it does NOT assert that the final response dict's `tool_calls[0].id` matches any particular value. So the synthetic `call_0` ID was never questioned.

A second test at line 943 (`test_tool_call_delta_without_index_defaults_to_zero`) also omits the `id` field.

A third test at line 1554 (`_stream_minimax_events with base_resp.status_code=1004`) tests the error path but not the tool_call_delta path with real IDs.

**Root cause:** Test fixtures mirror the production code's broken behavior. The original author implemented the streamer to drop the `id` field, and the test mocks matched the streamer, so both shipped the bug together.

**Fix:** Add a regression test that:
1. Mocks a MiniMax SSE stream with a known real ID (e.g., `"call_function_3679004591_1"`).
2. Runs `_call_llm_streaming` end-to-end.
3. Asserts the final response dict's `tool_calls[0]["id"] == "call_function_3679004591_1"`.

Mirror this for the OpenAI path. The test must construct the mock as raw SSE bytes that pass through `_sse_lines` and `_parse_sse_line`, not just yield pre-built `SSEEvent` objects (the bug is in the streamer, not the assembler — testing only the assembler would miss the SSE parsing gap).

The fixture should look like:
```python
def _mock_sse_stream_with_real_id():
    yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_function_3679004591_1","function":{"name":"read_file","arguments":""}}]}}]}\n\n'
    yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\":\\"foo.py\\"}"}}]}}]}\n\n'
    yield b'data: {"choices":[{"finish_reason":"tool_calls"}]}\n\n'
```

Drive this through `_stream_minimax_events` (or `_stream_openai_events`) and then through `_call_llm_streaming`, asserting the final `tool_calls[0]["id"]`.

---

## BUG #5 — `ev.data["name"]` and `ev.data["arguments"]` use direct subscript (would crash on a delta with only `id`)

**Severity:** LOW (would crash, but never triggered today)

**Assumption violated:** Every `tool_call_delta` event has a `name` and `arguments` key in its data dict (even if the value is empty string).

**Attack vector:** The accumulator at lines 2066-2068 does `if ev.data["name"]:` and `if ev.data["arguments"]:`. If a future SSE delta has only an `id` (no `name`, no `arguments`), this would `KeyError`. Today's stream never produces such a delta — OpenAI/MiniMax always send `name` in the first delta and `arguments` (possibly empty) in subsequent deltas. But the BUG #1 fix introduces the case where a delta may carry only `id` (e.g., a follow-up delta after `id` is set is a no-op for `name`/`arguments`).

**Root cause:** Defensive coding missing. The accumulator assumes all keys are present.

**Fix:** Use `.get()` in the BUG #1 fix:
```python
if ev.data.get("name"):
    tc["name"] = ev.data["name"]
if ev.data.get("arguments"):
    tc["arguments"] += ev.data["arguments"]
```

Already shown in the BUG #1 proposed fix.

---

## BUG #6 — First-write-wins `id` capture; later `id` deltas are silently dropped

**Severity:** LOW (no observed failure, defensive concern)

**Assumption violated:** If a provider sends the `id` field in the first delta for a tool call and never repeats it, the runtime's first-write-wins strategy is correct. If a provider ever sends multiple `id` deltas (or a corrected `id`), the runtime would silently keep the first one.

**Attack vector:** The BUG #1 fix uses `if ev.data.get("id"): tc["id"] = ev.data["id"]`. This is first-write-wins (because the dict already has `tc["id"]` set from a prior delta, and a later delta with a different `id` would overwrite it only if both are truthy). In OpenAI/MiniMax's actual streaming format, the `id` is sent in the first delta only, so this is fine. But the choice should be documented.

**Root cause:** No explicit policy.

**Fix:** Add a one-line comment near the BUG #1 fix:
```python
# OpenAI/MiniMax send the ID in the first delta for a tool call; subsequent deltas
# carry only argument deltas. First-write-wins matches the provider contract.
if ev.data.get("id") and not tc["id"]:
    tc["id"] = ev.data["id"]
```

This makes the assumption explicit and prevents a future maintainer from "fixing" it to last-write-wins without considering the implications.

---

## BUG #7 — Conversation JSON persists synthetic IDs across restarts

**Severity:** MEDIUM (data persistence of bad data)

**Assumption violated:** A conversation that has been written to disk and reloaded will have the same `tool_call_id`s as it had at runtime. The `call_id` is part of the persisted state.

**Attack vector:** `_save_conversation` (line 894) writes `call_id` for every tool_call in every assistant message. `_load_conversation_from_disk` (line 991) reads it back. So once a synthetic `call_0` is written to disk, it stays `call_0` forever — even if the user restarts the app, the conversation is reloaded, and the next LLM call still uses the synthetic ID. There is no migration path. The bug compounds: every fresh conversation that uses streaming will accumulate synthetic IDs in its disk file, and every subsequent LLM call against that conversation will fail with 2013.

**Root cause:** The synthetic ID is persisted as if it were authoritative. There is no way to "rebind" it to a real provider ID.

**Fix:** This is mitigated by the BUG #1 fix going forward — new conversations will have real IDs. For existing conversations with synthetic IDs:
1. On reload, the runtime could detect the synthetic pattern (`call_{idx}`) and either:
   a. Reject the conversation with a clear error ("This conversation was saved with corrupted tool_call IDs; please start a new one"), or
   b. Attempt to recover by reassigning IDs in a way the provider accepts (unlikely to work; providers don't accept reassignment).
2. Realistically, the user must clear or recreate the affected conversation. Document this in the bug fix.

The persisted state is the same shape either way; the question is whether the runtime detects and surfaces the corruption.

---

## Verification — what I checked

I verified the following against `agent/runtime.py` (commit `e154f37` working tree, branch `main`):

| Check | Result |
|---|---|
| `_stream_openai_events` discards `id` (lines 531-533) | ✅ Confirmed |
| `_stream_minimax_events` discards `id` (lines 612-614) | ✅ Confirmed (two duplicated yield blocks at 612 and 644, both broken) |
| `_stream_anthropic_events` discards `id` (lines 717-725) | ✅ Confirmed — does not even read `content_block_start` events |
| `_call_llm_streaming` accumulator does not capture `id` (lines 2063-2068) | ✅ Confirmed |
| `_call_llm_streaming` final assembly uses `f"call_{idx}"` (line 2087) | ✅ Confirmed |
| `_call_llm_streaming` fallback assembly also uses `f"call_{idx}"` (line 2104) | ✅ Confirmed |
| `_extract_tool_calls` non-streaming path preserves real ID (line 774) | ✅ Confirmed (`tc.get("id", f"call_{uuid.uuid4().hex[:8]}")` returns real ID when present) |
| `_extract_tool_calls` Anthropic path also preserves real ID (line 790) | ✅ Confirmed |
| `to_api_messages` emits `id: tc.call_id` (line 230 in `models/conversation.py`) | ✅ Confirmed |
| `_save_conversation` persists `call_id` (line 894) | ✅ Confirmed |
| `_load_conversation_from_disk` restores `call_id` (line 991) | ✅ Confirmed |
| MiniMax API error `2013` matches the upstream public report | ✅ Confirmed ([anomalyco/opencode#32608](https://github.com/anomalyco/opencode/issues/32608), [MiniMax-M2#43](https://github.com/MiniMax-AI/MiniMax-M2/issues/43)) |
| Bug introduced in commit `7b8148a` (Apr 21 2026) | ✅ Confirmed via `git log -S "f\"call_{"` |
| Bug NOT fixed in follow-up commit `85c2a41` ("MiniMax streaming tool calls + exec_command double card") | ✅ Confirmed via `git show 85c2a41` |
| Test fixtures omit `id` field (lines 824-826 in `tests/test_agent_runtime.py`) | ✅ Confirmed — coverage gap |
| Routing decision `use_streaming = on_text_delta is not None and provider_cfg.supports_streaming` (line 1969) | ✅ Confirmed — streaming is the default for any agent with text-delta UI |

---

## Adversarial findings not present in the original report

The original report focused on BUG #1 (root cause) and noted that `_stream_openai_events` has the same pattern. The adversarial audit surfaced:

1. **BUG #2** — Anthropic streaming has the same bug class but with a different mechanism (id in `content_block_start`, not `content_block_delta`). Latent because the Anthropic streaming path may not be exercised in production, but the code is registered in `_PROVIDER_STREAMERS`.
2. **BUG #4** — Test fixtures in `tests/test_agent_runtime.py` are complicit in the bug: they emit `tool_call_delta` events without `id` fields, so the bug was never caught in CI. The same code paths must be tested with real-shaped deltas.
3. **BUG #5** — The accumulator's direct subscript (`ev.data["name"]`) would crash on a delta with only `id` — this becomes reachable after the BUG #1 fix if a provider ever sends a sparse delta. The fix must use `.get()`.
4. **BUG #6** — The first-write-wins strategy for `id` should be made explicit in a comment so a future maintainer doesn't change it without considering the provider contract.
5. **BUG #7** — The synthetic ID is persisted to disk and reloaded on restart, so affected conversations cannot recover. This is data-persistence impact, not just a runtime bug. Existing conversations with synthetic IDs will continue to fail with 2013 forever unless cleared.

The original report correctly identified BUG #3 (latent inconsistency between streaming and non-streaming ID strategies) by implication but did not call it out separately.

---

## Severity assessment

**Production impact:** HIGH. Every streaming conversation with tool calls will fail with 2013 on the second turn (i.e., immediately after the first tool executes and its result is sent back). The error is recoverable in the sense that the conversation does not crash — the runtime handles the error and surfaces it to the user — but the user is stuck: any retry starts a new conversation, which fails again on the second turn.

**Fix complexity:** LOW. Three small edits to one file (`agent/runtime.py`): two yield statements (one in each of `_stream_openai_events` and `_stream_minimax_events` — note `_stream_minimax_events` has two duplicated yield blocks that both need fixing), and one accumulator + assembly pair in `_call_llm_streaming`. A fourth edit for the Anthropic streamer is recommended but optional. Plus a regression test.

**Risk of fix:** LOW. The fix is purely additive — the synthetic-ID fallback is preserved for any provider that omits the `id` field. No existing tests should break (none assert that the synthetic ID is used). The persistence path is unchanged.

**Recommendation:** Fix BUG #1 + BUG #4 (regression test) in one commit. Fix BUG #2 (Anthropic) in a follow-up commit. Address BUG #7 (existing corrupted conversations) in the fix's release notes.

---

## Out of scope

- The runtime fallback tier behavior (tried-multiple-providers case) is not exercised by this bug; the 2013 error fires on the first MiniMax call, so the fallback does not have a chance to engage. The recently-fixed `caller`-preservation bug (`ui/handlers/settings_handler.py`, commit `c30cd6b`) is in a different code path and not related.
- The MiniMax-specific `base_resp.status_code` error handling (lines 567-578) is correct and unrelated.
- The `done` event handling (the fix in commit `85c2a41`) is correct and unrelated.

---

## Cross-references

- Upstream public report: [anomalyco/opencode#32608](https://github.com/anomalyco/opencode/issues/32608) — same model, same error, same root cause class
- MiniMax-side issue: [MiniMax-M2#43](https://github.com/MiniMax-AI/MiniMax-M2/issues/43)
- `_PROVIDER_STREAMERS` registration: `agent/runtime.py:737-742`
- `_extract_tool_calls` (non-streaming preservation): `agent/runtime.py:752-797`
- `to_api_messages` (round-trip serialization): `models/conversation.py:207-251`
- `_call_llm` routing decision: `agent/runtime.py:1969-1973`
- Test fixture (gap): `tests/test_agent_runtime.py:812-826`
- Bug introduction: commit `7b8148a` (Apr 21 2026)
- Related fix that did NOT address this: commit `85c2a41` (May 7 2026)
