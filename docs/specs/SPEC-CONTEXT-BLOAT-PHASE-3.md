# SPEC: Context Bloat — Phase 3 (Stuck Messages, Streaming Usage, Awareness Caps)

**Date:** 2026-06-17
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-context-bloat-fix.md` §5 (Phase CB-3)
**Source bug report:** `docs/bugs/BUG-high-input-token-context-bloat.md` (BUG #3 HIGH, BUG #4 HIGH, BUG #6 MEDIUM)
**Depends on:** CB-1 (shipped commit `601067b`) and CB-2 (shipped commit `d43539e`) — the `AgentRuntime` changes from CB-1/2 are prerequisites for some of the streaming usage wiring.
**Target branch:** main

> **Architecture compliance statement.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§7 (Agent Runtime)** — All three fixes are local to `agent/runtime.py` and `utils/project_awareness.py`. No new modules, no new public API surface.
> - **§8.3 (Models are plain Python, no GTK)** — Preserved. The fixes touch only non-UI code.
> - **§8.5 (Tests)** — New test classes added to existing test files (`tests/test_agent_runtime.py`, `tests/test_project_awareness.py`). No new test files.
> - **§8.7 (No dead code)** — Every new code path is wired to a consumer.
> - **No new public API** — All three fixes are internal changes to existing functions. No new callback types, no new public methods.

---

## 1. Overview

### Problem (three distinct bugs, one phase)

**Bug 3a — Streaming usage is never captured (BUG #3, HIGH).**

`AgentRuntime._call_llm_streaming()` at `agent/runtime.py:1605-1696` iterates SSE events from `_stream_openai_events()` (and friends) and assembles the final response. When the stream completes, the function returns `{"choices": [...], "usage": {}}` — an explicitly empty usage dict. The comment on line 1689 says *"streaming responses omit usage; caller should use blocking call for accurate counts"*, but the caller (the non-streaming path at `agent/runtime.py:1254-1257` which calls `_extract_usage(response, ...)`) never gets accurate counts for streaming calls.

Result: `on_token_usage` fires with **zero tokens** for every streaming response. **~50% of LLM calls are streaming** (per the proposal), so half the agent's token usage is invisible to monitoring.

**The actual fix is upstream.** OpenAI-compatible SSE streams DO emit a `usage` chunk at the end (e.g., `data: {"choices": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 56}}`) before the `[DONE]` marker. Anthropic streams emit `message_delta` events with `usage`. The streamers at `agent/runtime.py:391-625` ignore this field. The fix is to (1) capture `usage` in the streamer, (2) yield a new event type `"usage"` with the usage dict, and (3) handle the `"usage"` event in `_call_llm_streaming` to populate the response's `usage` field.

**Bug 3b — Stuck messages bloat conversation history (BUG #4, HIGH).**

`AgentRuntime._check_stuck()` at `agent/runtime.py:1698-1736` returns an intervention message when the agent is detected as looping (same tool + same args 3+ times, or 8+ write ops with no verification). The caller at `agent/runtime.py:1428-1441` appends the intervention to the tool result text, then stores it via `conv.add_tool_result(call_id, tool_result_text)`. Each intervention adds ~250 chars to `conv.messages`. For a stuck agent that fires the intervention 10+ times, that's 2,500+ chars of repetitive warning text in the conversation history, sent with every subsequent API call.

**The fix (per proposal Q3, Option A — recommended):** Send the stuck intervention as a transient system-side signal to the LLM, NOT stored in `conv.messages`. Per the proposal's recommendation: "The message is meant to nudge the LLM, not be part of the conversation. Treating it as transient is the right model." Implementation: prepend the stuck message to the LLM request's `messages` list (or as a system message) for the next call only, without calling `add_tool_result` with the augmented text.

**Bug 3c — Awareness variables have no size caps (BUG #6, MEDIUM).**

`build_awareness_dict()` at `utils/project_awareness.py:531-580` constructs four awareness variables used in the system prompt: `PROJECT_NAME` (small), `TEAM_ROSTER`, `CURRENT_STATE`, `PROJECT_MEMORY`, `WORKFLOW_STATUS`. `PROJECT_MEMORY` is correctly truncated to 3,000 chars (line 574-578). But `TEAM_ROSTER` and `CURRENT_STATE` have NO size caps. For a project with 20+ team members or a long git history, these can grow unboundedly.

**The fix:** Apply the same truncation pattern as `PROJECT_MEMORY`: cap `TEAM_ROSTER` at ~500 chars, `CURRENT_STATE` at ~1,000 chars, with a `[... truncated ...]` marker. The cap values are conservative — well below what would actually cause context issues.

### Solution summary

1. **Streaming usage fix** — modify `_stream_openai_events`, `_stream_minimax_events`, and `_stream_anthropic_events` to capture and yield a `"usage"` SSE event. Modify `_call_llm_streaming` to handle the event and populate the response's `usage` field. ~25 production lines, ~3 tests.
2. **Stuck messages fix** — modify the stuck message injection at `agent/runtime.py:1428-1441` to send the intervention as a transient prefix on the NEXT LLM call, not as a stored message. Track per-session which intervention was last sent so the LLM doesn't see duplicates. ~15 production lines, ~2 tests.
3. **Awareness caps fix** — modify `build_awareness_dict` to truncate `TEAM_ROSTER` and `CURRENT_STATE` with the same pattern as `PROJECT_MEMORY`. ~10 production lines, ~2 tests.

### Scope

| In scope | Out of scope |
|---|---|
| Capture SSE `usage` chunks in the three streamers | Anthropic's exact event format may need additional work for non-message_delta usage; if too complex, defer |
| Populate `usage` field in `_call_llm_streaming` response | Tiktoken-based token estimation (Phase CB-4, BUG #5) |
| Send stuck message as transient prefix on next LLM call | Tracking full stuck history across sessions |
| Truncate `TEAM_ROSTER` and `CURRENT_STATE` | Re-architecting how awareness data flows |
| Tests for all three | Adding more awareness variables |
| Update `docs/ARCHITECTURE.md` with the changes | UI changes for stuck interventions |

### Design decisions (locked by this spec)

1. **Stuck message mechanism (Q3 from the proposal, Option A — recommended):** Transient prefix on the LLM request, not stored in `conv.messages`. Per the proposal: "The message is meant to nudge the LLM, not be part of the conversation. Treating it as transient is the right model."
2. **Streaming usage mechanism (Q4 from the proposal, Option A — recommended):** Parse usage from SSE events. OpenAI-compatible providers emit a usage chunk at the end. Anthropic emits `message_delta` events with usage. No fallback to blocking call.
3. **Awareness cap values:** `TEAM_ROSTER` ≤ 500 chars, `CURRENT_STATE` ≤ 1,000 chars. These are conservative and well below what would actually cause context issues. The exact values are NOT configurable in v1.
4. **Stuck intervention prefix format:** Prepended to the `messages` list as a synthetic user message (not system) with the stuck intervention text, tagged as transient. The next `_call_llm` removes it before the response is processed.
5. **Streaming usage event type:** New SSE event type `"usage"` with `data={"usage": {...}}`. All three streamers (`openai`, `minimax`, `anthropic`) MUST yield this event when the provider sends usage. The `data` dict MUST match the OpenAI format (`prompt_tokens`, `completion_tokens`) for OpenAI-compatible providers and the Anthropic format (`input_tokens`, `output_tokens`) for Anthropic. The downstream `_extract_usage` function already handles both formats (lines 713-731).

---

## 2. Changes by File

### 2.1 `agent/runtime.py` — capture SSE usage in streamers

**What changes:** Three streamer functions need to capture the `usage` field from the SSE event and yield a new event type `"usage"` with the usage dict.

#### 2.1.1 `_stream_openai_events` (lines 391-451)

**Find** at line 410 (the part that processes the SSE `raw` event):

```python
            if ev.type != "raw":
                continue
            d = ev.data
            delta = d.get("choices", [{}])[0].get("delta", {})
            # Text content delta (guard against null content from OpenRouter)
            content = delta.get("content")
            if content is not None:
                yield SSEEvent(type="text_delta", data={"content": content})
            # Tool call deltas
            tc_delta = delta.get("tool_calls", [])
            for tcd in tc_delta:
                idx = tcd.get("index", 0)
                if "function" in tcd:
                    fname = tcd["function"].get("name") or ""
                    fargs = tcd["function"].get("arguments", "") or ""
                    yield SSEEvent(type="tool_call_delta", data={
                        "index": idx, "name": fname, "arguments": fargs
                    })
```

**Append** at the end of the `if ev.type == "raw":` block, AFTER the tool call delta handling (i.e., as a sibling of the existing deltas, still inside the same `if`):

```python
            # OpenAI-compatible providers emit a usage chunk at the end of the stream,
            # typically in a frame with empty choices. Capture and forward it.
            # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.1.1 (BUG #3 fix).
            usage = d.get("usage")
            if usage:
                yield SSEEvent(type="usage", data={"usage": usage})
```

#### 2.1.2 `_stream_minimax_events` (lines 453-559)

**Find** the function — it has the same OpenAI-compatible SSE format. Apply the same change: after the tool call delta handling, add the same `usage` capture block. The format is identical to OpenAI (since MiniMax uses OpenAI-compatible SSE).

**Verify:** the existing test `test_streaming_minimax_body_error_raises` at `tests/test_agent_runtime.py:1344` should still pass.

#### 2.1.3 `_stream_anthropic_events` (lines 560-625)

**Find** the function. Anthropic uses a different SSE format. The usage info is typically in `message_delta` events:

```python
            etype = d.get("type", "")
            if etype == "content_block_delta":
                ...
```

**Append** (as a sibling, inside the `for line in _sse_lines(resp):` loop, after the `if etype == "content_block_delta":` block):

```python
            elif etype == "message_delta":
                # Anthropic emits usage in message_delta events at the end of the stream.
                # The data shape is: {"type": "message_delta", "usage": {"input_tokens": N, "output_tokens": M}, ...}
                usage = d.get("usage")
                if usage:
                    yield SSEEvent(type="usage", data={"usage": usage})
```

**Imports required:** None new. `SSEEvent` is already imported.

### 2.2 `agent/runtime.py` — handle the `"usage"` event in `_call_llm_streaming`

**What changes:** The stream handler at lines 1625-1696 needs to handle the new `"usage"` event type and populate the response's `usage` field.

**Find** at line 1662 (in the event-handling loop, after the `tool_call_delta` branch):

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
                logger.debug("[stream] sk=%s done: text_len=%d tool_calls=%d",
                             session_key, len(full_content), len(tool_calls))
                return {
                    "choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}],
                    "usage": {},  # streaming responses omit usage; caller should use blocking call for accurate counts
                }
```

**Replace** with (adds a `usage` accumulator, captures the `"usage"` event, returns it in the final response):

```python
            elif ev.type == "usage":
                # Provider sent a usage chunk (e.g., OpenAI's "final" frame).
                # Capture the most recent one; the final response uses it.
                # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.2 (BUG #3 fix).
                usage_data = ev.data.get("usage", {})
                if usage_data:
                    captured_usage = usage_data

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
                logger.debug("[stream] sk=%s done: text_len=%d tool_calls=%d usage_captured=%s",
                             session_key, len(full_content), len(tool_calls),
                             bool(captured_usage))
                return {
                    "choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}],
                    "usage": captured_usage,  # Phase CB-3: was {}; now captures SSE usage chunk
                }
```

**Also need to initialize `captured_usage`** at the start of the function, alongside `full_content` and `tool_calls_partial`. Find at line 1623-1625:

```python
        full_content = ""
        # tool_call_index → {name, arguments, done}
        tool_calls_partial: dict[int, dict] = {}
```

**Add** after `tool_calls_partial`:

```python
        # Phase CB-3: usage captured from SSE "usage" event (BUG #3 fix).
        # Most providers emit exactly one usage chunk at the end of the stream.
        # If none is emitted, this stays empty and the response's "usage" is {},
        # which is the same as the pre-CB-3 behavior (zero counts in on_token_usage).
        captured_usage: dict = {}
```

**Also update the fallback return** at line 1691 (the path where the stream ends without an explicit `done` event):

```python
        return {"choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}], "usage": captured_usage}
```

(The `usage: {}` literal becomes `usage: captured_usage`.)

### 2.3 `agent/runtime.py` — stuck messages as transient prefix

**What changes:** The stuck message injection at lines 1428-1441 needs to (1) not store the intervention in `conv.messages` and (2) instead send it as a transient prefix on the next LLM call.

**Find** at line 1428-1441:

```python
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)

                    # Record tool result — ToolResult dataclass stays clean
                    tc.mark_completed(result.output if result.success else result.error or "")
                    tool_result_text = tc.result or ""

                    # Inject stuck message AFTER tool result recording, with separator
                    if stuck_msg:
                        tool_result_text = tool_result_text + "\n\n---\n⚠️ " + stuck_msg

                    conv.add_tool_result(call_id, tool_result_text)
                    self._dispatch(self._on_tool_call_result, session_key, tool_name, tool_result_text)
```

**Replace** with (the stuck message is recorded as a transient signal on the runtime, NOT appended to the tool result text):

```python
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
                        # Phase CB-3: store as transient signal, NOT in conv.messages.
                        # The next LLM call will prepend it to the request's messages list.
                        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
                        self._pending_stuck_messages.setdefault(session_key, []).append(stuck_msg)

                    # Record tool result — ToolResult dataclass stays clean
                    tc.mark_completed(result.output if result.success else result.error or "")
                    tool_result_text = tc.result or ""

                    # No more: `if stuck_msg: tool_result_text += "\n\n---\n⚠️ " + stuck_msg`
                    # The stuck message is now sent as a transient prefix, not stored.

                    conv.add_tool_result(call_id, tool_result_text)
                    self._dispatch(self._on_tool_call_result, session_key, tool_name, tool_result_text)
```

**Initialize `_pending_stuck_messages` in `AgentRuntime.__init__`.** Find the init block (search for `self._on_enforcement_status = on_enforcement_status`):

**Add** (just before or after, in the same initialization block):

```python
        # Phase CB-3: per-session list of pending stuck messages to send as
        # transient prefixes on the next LLM call. See SPEC-CONTEXT-BLOAT-PHASE-3.md
        # §2.3 (BUG #4 fix). Populated by _run_loop when _check_stuck fires;
        # consumed by _call_llm before the LLM request; cleared after the request.
        self._pending_stuck_messages: dict[str, list[str]] = {}
```

**Consume the pending messages in `_call_llm` (or wherever the messages list is built).** Per `implementationSupervisor.md` §2-3: "Track the count of 'accepted work on substance over format' in the post-mortem" — the exact consumption point is open. The proposal recommends a transient prefix on the request.

**Implementation note:** The cleanest consumption point is inside `_call_llm` (or the streaming equivalent) BEFORE the request is built. The pending messages are prepended to the `messages` list as a synthetic user message (not system, to keep them after the system prompt). After the request, the pending messages for the session are cleared.

**Find `_call_llm` at line 1510.** The function takes a `messages: list[dict]` parameter. Add (at the top of the function, after any logger.debug calls):

```python
        # Phase CB-3: prepend pending stuck messages as transient prefixes.
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        pending = self._pending_stuck_messages.pop(session_key, [])
        if pending:
            stuck_prefix = {
                "role": "user",
                "content": (
                    "[Stuck-detection intervention — please consider a different approach]\n\n"
                    + "\n\n---\n\n".join(pending)
                ),
            }
            messages = [stuck_prefix] + messages
            logger.debug("[stuck-injection] sk=%s: prepended %d stuck message(s)", session_key, len(pending))
```

**Important:** The same fix MUST apply to `_call_llm_streaming` (line 1605) for streaming responses. The stuck message is a property of the request, not the response style.

**Add the same block** at the top of `_call_llm_streaming`:

```python
        # Phase CB-3: prepend pending stuck messages as transient prefixes.
        # (Same fix as _call_llm; streaming path needs it too.)
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.3 (BUG #4 fix).
        pending = self._pending_stuck_messages.pop(session_key, [])
        if pending:
            stuck_prefix = {
                "role": "user",
                "content": (
                    "[Stuck-detection intervention — please consider a different approach]\n\n"
                    + "\n\n---\n\n".join(pending)
                ),
            }
            messages = [stuck_prefix] + messages
            logger.debug("[stuck-injection] sk=%s (streaming): prepended %d stuck message(s)", session_key, len(pending))
```

**Also clean up `_pending_stuck_messages` when conversations end** (in `_cleanup_tool_history` or similar). Find `_cleanup_tool_history` at line 1748:

```python
    def _cleanup_tool_history(self, session_key: str) -> None:
        """Remove tool history for a session when conversation ends."""
        with self._tool_history_lock:
            self._tool_history.pop(session_key, None)
```

**Replace** with:

```python
    def _cleanup_tool_history(self, session_key: str) -> None:
        """Remove tool history and pending stuck messages for a session when conversation ends."""
        with self._tool_history_lock:
            self._tool_history.pop(session_key, None)
        # Phase CB-3: also clean up pending stuck messages
        self._pending_stuck_messages.pop(session_key, None)
```

### 2.4 `utils/project_awareness.py` — add awareness caps

**What changes:** Add size caps to `TEAM_ROSTER` and `CURRENT_STATE` in `build_awareness_dict()`, matching the existing `PROJECT_MEMORY` pattern at lines 574-578.

**Find** the `TEAM_ROSTER` block (around lines 545-558):

```python
    # Team roster
    team = load_team(project_path)
    if team.members:
        lines = []
        if team.pm_name:
            lines.append(f"PM: {team.pm_name}")
        for m in team.members:
            role_str = f" — {m.role}" if m.role else ""
            write_str = " [write]" if m.can_write else ""
            lines.append(f"- {m.name} ({m.session_key}){role_str}{write_str}")
        parts["TEAM_ROSTER"] = "\n".join(lines)
    else:
        parts["TEAM_ROSTER"] = "No team members yet."
```

**Replace** with (adds a 500-char cap with truncation marker, matching `PROJECT_MEMORY`'s pattern):

```python
    # Team roster
    team = load_team(project_path)
    if team.members:
        lines = []
        if team.pm_name:
            lines.append(f"PM: {team.pm_name}")
        for m in team.members:
            role_str = f" — {m.role}" if m.role else ""
            write_str = " [write]" if m.can_write else ""
            lines.append(f"- {m.name} ({m.session_key}){role_str}{write_str}")
        roster = "\n".join(lines)
        # Phase CB-3: cap TEAM_ROSTER at 500 chars (BUG #6 fix).
        # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.4.
        if len(roster) > 500:
            roster = roster[:500] + "\n[... team roster truncated ...]"
        parts["TEAM_ROSTER"] = roster
    else:
        parts["TEAM_ROSTER"] = "No team members yet."
```

**Find** the `CURRENT_STATE` block (around lines 561-569):

```python
    # Current state
    snapshot = build_awareness_snapshot(project_path)
    state_lines = [f"Project: {snapshot.get('project_name', 'unknown')}"]
    state_lines.append(f"Path: {snapshot.get('project_path', '')}")
    git = snapshot.get("git", {})
    if git.get("available"):
        state_lines.append(f"Git: {git.get('head_sha', '?')[:7]} ({'dirty' if git.get('dirty') else 'clean'})")
    else:
        state_lines.append("Git: not available")
    state_lines.append(f"Review mode: {snapshot.get('review_mode', 'off')}")
    parts["CURRENT_STATE"] = "\n".join(state_lines)
```

**Replace** with (adds a 1,000-char cap):

```python
    # Current state
    snapshot = build_awareness_snapshot(project_path)
    state_lines = [f"Project: {snapshot.get('project_name', 'unknown')}"]
    state_lines.append(f"Path: {snapshot.get('project_path', '')}")
    git = snapshot.get("git", {})
    if git.get("available"):
        state_lines.append(f"Git: {git.get('head_sha', '?')[:7]} ({'dirty' if git.get('dirty') else 'clean'})")
    else:
        state_lines.append("Git: not available")
    state_lines.append(f"Review mode: {snapshot.get('review_mode', 'off')}")
    state = "\n".join(state_lines)
    # Phase CB-3: cap CURRENT_STATE at 1,000 chars (BUG #6 fix).
    # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.4.
    if len(state) > 1000:
        state = state[:1000] + "\n[... current state truncated ...]"
    parts["CURRENT_STATE"] = state
```

**Add** module-level constants near the top of the file (after the imports, before any function definitions). Find the section after the last import and before the first function:

```python
# Phase CB-3: size caps for awareness variables (BUG #6 fix).
# See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.4.
TEAM_ROSTER_MAX_CHARS = 500
CURRENT_STATE_MAX_CHARS = 1000
```

(Use the constants in the truncated code above by replacing the literal `500` and `1000` with the constant names. This makes the caps easy to find and adjust.)

### 2.5 `tests/test_agent_runtime.py` — streaming usage tests

**What changes:** New test class `TestStreamingUsageCapture` placed alongside the existing `TestStreaming` class (line 832). At least 3 tests.

**Exact test class:**

```python
class TestStreamingUsageCapture:
    """Phase CB-3 (BUG #3 fix): streaming responses now capture SSE usage chunks."""

    def test_streaming_captures_openai_usage_chunk(self):
        """An OpenAI-compatible stream that emits a usage chunk in the final frame
        must surface the usage in the response dict (not {})."""
        from agent import runtime as rt_module

        def mock_stream_with_usage():
            # Simulate a 3-chunk OpenAI stream + a usage chunk + done
            yield rt_module.SSEEvent(type="text_delta", data={"content": "Hello"})
            yield rt_module.SSEEvent(type="text_delta", data={"content": " world"})
            yield rt_module.SSEEvent(type="text_delta", data={"content": "!"})
            yield rt_module.SSEEvent(type="usage", data={
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}
            })
            yield rt_module.SSEEvent(type="done", data={})

        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        # Mock the streamer to emit our test stream
        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = lambda *a, **kw: mock_stream_with_usage()
        try:
            with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt)):
                rt._run_loop(sk, "say hello")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig
        rt.stop()

        # The on_token_usage callback should have fired with non-zero tokens
        # (this is a behavior test — checks the end-to-end effect of the fix)

    def test_streaming_without_usage_chunk_returns_empty_usage(self):
        """Streams that don't emit a usage chunk (some providers) still return
        a response dict, just with usage={} (backward-compatible)."""
        # Use the existing _mock_stream_openai_3_chunks (no usage chunk)
        # Verify the response is returned and usage is {}.
        ...

    def test_streaming_captures_anthropic_usage_in_message_delta(self):
        """Anthropic streams emit usage in message_delta events; the fix must
        capture these too."""
        # Mock the Anthropic streamer; emit a message_delta with usage
        ...
```

**Note on test #1 (the behavior test):** the test should verify that `on_token_usage` fires with non-zero tokens. The existing `TestStuckDetection` tests at line 1074 are a good reference for the test pattern (mock the streamer, drive `_run_loop`, assert callback fired).

### 2.6 `tests/test_agent_runtime.py` — stuck message transient prefix tests

**What changes:** New test class `TestStuckMessageTransient` placed alongside the existing `TestStuckDetection` class (line 1074). At least 2 tests.

**Exact test class:**

```python
class TestStuckMessageTransient:
    """Phase CB-3 (BUG #4 fix): stuck messages are transient prefixes, not stored."""

    def test_stuck_message_not_stored_in_conv_messages(self):
        """A stuck message fired during a tool call is NOT appended to the
        tool result text. conv.messages contains only the clean tool result."""
        # Drive _run_loop with a mock that triggers _check_stuck (3+ identical
        # tool calls). After the loop, inspect conv.messages and assert no
        # "stuck-detection" text is present in the tool result.
        ...

    def test_stuck_message_prepended_to_next_llm_request(self):
        """When a stuck message is pending, the next LLM request's messages
        list contains the stuck message as the first user message."""
        # Manually populate rt._pending_stuck_messages[sk] = ["test stuck msg"]
        # Call _call_llm directly (or _call_llm_streaming) and capture the
        # messages argument. Assert the first message is the stuck prefix.
        ...
```

### 2.7 `tests/test_project_awareness.py` — awareness cap tests

**What changes:** New test class `TestAwarenessCaps` placed alongside the existing `TestBuildAwarenessBlock` class (line 129). At least 2 tests.

**Exact test class:**

```python
class TestAwarenessCaps:
    """Phase CB-3 (BUG #6 fix): TEAM_ROSTER ≤ 500 chars, CURRENT_STATE ≤ 1,000 chars."""

    def test_team_roster_capped_at_500_chars(self):
        """A team with 20+ members produces a TEAM_ROSTER ≤ 500 chars with a truncation marker."""
        from utils.project_awareness import (
            init_project_config, save_team, ProjectTeam, TeamMember,
            build_awareness_dict, TEAM_ROSTER_MAX_CHARS,
        )
        with tempfile.TemporaryDirectory() as proj:
            init_project_config(proj, "testproj")
            # 30 members × ~50 chars/entry = ~1,500 chars before cap
            members = [
                TeamMember(f"sk{i}", f"Member{i:02d}", role="agent", can_write=False)
                for i in range(30)
            ]
            save_team(proj, ProjectTeam(members=members, pm_name="PM"))
            d = build_awareness_dict(proj)
            assert len(d["TEAM_ROSTER"]) <= TEAM_ROSTER_MAX_CHARS + len("\n[... team roster truncated ...]")
            assert "[... team roster truncated ...]" in d["TEAM_ROSTER"]

    def test_current_state_capped_at_1000_chars(self):
        """A CURRENT_STATE with long content is truncated to ≤ 1,000 chars."""
        # CURRENT_STATE is built from snapshot data, not user input.
        # To force it to be > 1000 chars, we'd need to extend build_awareness_snapshot
        # to return long content. Since the existing snapshot is short, this test
        # verifies the cap is enforced when the snapshot IS long:
        #   - Set project_name to a very long string
        #   - Set project_path to a very long string
        #   - Verify CURRENT_STATE is ≤ CURRENT_STATE_MAX_CHARS + marker
        ...
```

### 2.8 `docs/ARCHITECTURE.md` — update §7 and add §3.21q.6

**What changes:** Add a one-line note to the §7 Agent Runtime section about the new `_pending_stuck_messages` attribute. Optionally add a brief note about the streaming usage fix in the same section.

**Find** the §7 Agent Runtime section in `docs/ARCHITECTURE.md`. The CB-1/CB-2 audit added `[trim to model_max]` to the `send_message` comment; the CB-3 audit should add `[stuck-detection]` and `[streaming usage capture]` notes.

**Update** the `send_message` signature comment at the §7 Agent Runtime section (around line 1263, which was the location after CB-1's edit):

```markdown
    def send_message(session_key, text)         # tool loop: user msg → [trim to model_max] → LLM → [stuck-detection] → tool calls → results → LLM → response
```

**Note:** The streaming usage capture is automatic (driven by the SSE event); it doesn't appear in the `send_message` flow directly. The awareness caps don't appear in the runtime at all. So only `[stuck-detection]` is added to the `send_message` comment.

**Files NOT changed in this section:**

- `prompts/system/*.md` — the prompt templates themselves. Out of scope.
- `utils/prompt_loader.py` — the awareness caps apply at the `build_awareness_dict` level; the system prompt composition is unchanged.
- `agent/runtime.py:_check_stuck` itself — unchanged. Only the CALLER of `_check_stuck` (the injection site) changes.
- `tests/test_agent_runtime.py:TestStuckDetection` (lines 1074-1167) — existing 4 tests. No changes; they verify the detector still fires, not how the message is delivered.
- `tests/test_agent_runtime.py:TestStreaming` (lines 832-832+) — existing tests. They mock the streamer without a usage chunk, so they should still pass (the new `captured_usage` defaults to `{}` and the response's `usage` is `{}`).
- `tests/test_project_awareness.py:TestBuildAwarenessBlock` (line 129) — existing tests. The default team size (1-2 members) is well under the 500-char cap, so existing tests pass.

---

## 3. Data Flow

### 3.1 Streaming usage capture flow

```
LLM API (OpenAI-compatible) → SSE events
  │
  ├─ data: {"choices": [...]}  → _stream_openai_events
  │                              yields SSEEvent("text_delta"/"tool_call_delta")
  │
  ├─ data: {"choices": [], "usage": {...}}  → _stream_openai_events
  │                              yields SSEEvent("usage", data={"usage": {...}})  # NEW in CB-3
  │
  └─ data: [DONE]               → _stream_openai_events
                                 yields SSEEvent("done")
                                   │
                                   └─ _call_llm_streaming handles "usage" event:
                                        captured_usage = ev.data["usage"]
                                        ...
                                        return {"choices": [...], "usage": captured_usage}
                                          │
                                          └─ _run_loop calls _extract_usage(response)
                                               → returns non-zero (prompt_tokens, completion_tokens)
                                               → on_token_usage fires with real counts
```

### 3.2 Stuck message transient prefix flow

```
_run_loop (iteration N)
  │
  ├─ tool call fires (e.g., write_file with same args as before)
  │   │
  │   ├─ _check_stuck returns intervention message
  │   │   │
  │   │   └─ (NEW in CB-3) self._pending_stuck_messages[sk].append(stuck_msg)
  │   │
  │   └─ tool_result_text = tc.result (CLEAN — no stuck prefix appended)
  │       conv.add_tool_result(call_id, tool_result_text)
  │
  └─ next iteration (N+1): top of loop, conv.trim_to_token_limit, then build messages
      │
      └─ _call_llm(session_key, base_url, api_key, model, messages, tools, timeout, ...)
          │
          ├─ (NEW in CB-3) pending = self._pending_stuck_messages.pop(session_key, [])
          │   if pending:
          │       stuck_prefix = {"role": "user", "content": "[Stuck-detection...]\n\n" + ...}
          │       messages = [stuck_prefix] + messages
          │
          └─ LLM request is made with the stuck prefix
              The LLM sees the intervention and (hopefully) changes its behavior
              The intervention is NOT in conv.messages; subsequent calls don't see it
```

### 3.3 Awareness caps flow

```
build_awareness_dict(project_path)
  │
  ├─ load_team(project_path) → Team (members: [...])
  │   │
  │   └─ if members:
  │       roster = "\n".join(lines)  # up to ~50 chars/member
  │       if len(roster) > 500:     # NEW in CB-3
  │           roster = roster[:500] + "\n[... team roster truncated ...]"
  │       parts["TEAM_ROSTER"] = roster
  │
  ├─ build_awareness_snapshot(project_path) → Snapshot
  │   │
  │   └─ state = "\n".join(state_lines)  # typically < 200 chars
  │       if len(state) > 1000:          # NEW in CB-3
  │           state = state[:1000] + "\n[... current state truncated ...]"
  │       parts["CURRENT_STATE"] = state
  │
  ├─ load_project_context(project_path) → context (already capped at 3000 chars)
  │   parts["PROJECT_MEMORY"] = truncated
  │
  └─ returns parts dict → used by build_system_prompt → embedded in system prompt
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `agent/runtime.py` | Capture usage in 3 streamers (openai, minimax, anthropic); handle "usage" event in `_call_llm_streaming`; initialize `_pending_stuck_messages`; consume pending in `_call_llm` and `_call_llm_streaming`; clean up in `_cleanup_tool_history`; change stuck injection at line 1428-1441 | +50, -10 | LOW (additive changes, fallback to old behavior) |
| `utils/project_awareness.py` | Add 2 module-level constants; truncate TEAM_ROSTER and CURRENT_STATE | +15, -2 | LOW (defensive caps) |
| `tests/test_agent_runtime.py` | Add `TestStreamingUsageCapture` (3 tests) and `TestStuckMessageTransient` (2 tests) | +120 | LOW |
| `tests/test_project_awareness.py` | Add `TestAwarenessCaps` (2 tests) | +40 | LOW |
| `docs/ARCHITECTURE.md` | Update §7 send_message comment with `[stuck-detection]` step | +1, -1 | NONE (doc) |

**Total: ~230 lines, 2 production files, 2 test files, 1 doc file.**

---

## 5. Implementation Order

Numbered steps. The implementer must complete each step and verify before moving to the next. No batching.

1. **Capture SSE usage in the three streamers (`agent/runtime.py:391-625`).** Add the `usage` capture blocks to `_stream_openai_events`, `_stream_minimax_events`, and `_stream_anthropic_events`. The three changes are independent; do them in one commit step.
   - **Verify:** `grep -n 'ev.type == "usage"' agent/runtime.py` → at least 3 matches (one per streamer).

2. **Handle the `"usage"` event in `_call_llm_streaming` (`agent/runtime.py:1605-1696`).** Add `captured_usage` accumulator, handle the `"usage"` event, return the captured usage in the response dict (replacing the hardcoded `usage: {}`).
   - **Verify:** `grep -n "captured_usage" agent/runtime.py` → at least 4 matches (init, event handler, return in success path, return in fallback path).

3. **Initialize `_pending_stuck_messages` in `AgentRuntime.__init__`** (alongside `_tool_history`).
   - **Verify:** `grep -n "_pending_stuck_messages" agent/runtime.py` → at least 5 matches (init, two consumption sites in `_call_llm`/`_call_llm_streaming`, the producer in `_run_loop`, the cleanup in `_cleanup_tool_history`).

4. **Modify the stuck injection at `agent/runtime.py:1428-1441`** to use the transient pattern (queue to `_pending_stuck_messages`, don't append to `tool_result_text`).

5. **Consume the pending stuck messages in `_call_llm` and `_call_llm_streaming`** (prepend to the `messages` list, then clear the pending list).

6. **Clean up pending stuck messages in `_cleanup_tool_history`** when the conversation ends.

7. **Write `TestStreamingUsageCapture` tests** (3 tests, see §2.5).
   - **Verify:** `pytest tests/test_agent_runtime.py::TestStreamingUsageCapture -v` → all 3 pass.

8. **Write `TestStuckMessageTransient` tests** (2 tests, see §2.6).
   - **Verify:** `pytest tests/test_agent_runtime.py::TestStuckMessageTransient -v` → both pass.

9. **Add awareness caps to `utils/project_awareness.py:build_awareness_dict`** (modify TEAM_ROSTER and CURRENT_STATE blocks, add module-level constants).
   - **Verify:** `grep -n "TEAM_ROSTER_MAX_CHARS\|CURRENT_STATE_MAX_CHARS" utils/project_awareness.py` → at least 4 matches (2 constant definitions + 2 usage sites).

10. **Write `TestAwarenessCaps` tests** (2 tests, see §2.7).
    - **Verify:** `pytest tests/test_project_awareness.py::TestAwarenessCaps -v` → both pass.

11. **Run the full test suite.**
    - **Verify:** `pytest tests/ -q` → all tests pass.
    - **Verify:** The existing `TestStuckDetection` (4 tests at `tests/test_agent_runtime.py:1074`) continues to pass — the detector still fires; only the delivery mechanism changes.
    - **Verify:** The existing `TestStreaming` (~5 tests at `tests/test_agent_runtime.py:832+`) continues to pass — the streamers' existing event yield behavior is unchanged; only a NEW event type is added.
    - **Verify:** The existing `TestBuildAwarenessBlock` (4 tests at `tests/test_project_awareness.py:129+`) continues to pass — the default team (1-2 members) is well under the 500-char cap.

12. **Update `docs/ARCHITECTURE.md`** — add `[stuck-detection]` to the `send_message` comment at §7.
    - **Verify:** `grep -n "stuck-detection" docs/ARCHITECTURE.md` → at least 1 match.

13. **Adversarial audit** (per `prompts/adversarialDebugger.md` and the project's implementation loop) before commit.

---

## 6. Acceptance Criteria

The implementer has succeeded when ALL of the following are true:

- [ ] All 3 streamer functions (`_stream_openai_events`, `_stream_minimax_events`, `_stream_anthropic_events`) yield a `SSEEvent(type="usage", data=...)` when the underlying SSE event contains a `usage` field.
- [ ] `_call_llm_streaming` returns a response dict with `usage: <captured>` (not `usage: {}`) when the stream emits a usage chunk.
- [ ] When the stream does NOT emit a usage chunk (backward compat), the response dict has `usage: {}` (same as pre-CB-3).
- [ ] `AgentRuntime._pending_stuck_messages` is initialized in `__init__`, populated in `_run_loop` when `_check_stuck` fires, consumed in `_call_llm` and `_call_llm_streaming`, and cleaned up in `_cleanup_tool_history`.
- [ ] When a stuck message is fired, `conv.messages` does NOT contain the stuck message text. The clean tool result is stored, not the augmented text.
- [ ] When a stuck message is pending, the next `_call_llm` (or `_call_llm_streaming`) call's `messages` argument is prepended with a synthetic user message containing the stuck text.
- [ ] The synthetic user message is removed after the call (the pending list is `.pop()`'d, not just read).
- [ ] `TEAM_ROSTER` is truncated to ≤ `TEAM_ROSTER_MAX_CHARS + len(marker)` when the unsliced value would exceed it.
- [ ] `CURRENT_STATE` is truncated to ≤ `CURRENT_STATE_MAX_CHARS + len(marker)` when the unsliced value would exceed it.
- [ ] When `TEAM_ROSTER` and `CURRENT_STATE` are short (no truncation needed), the values are returned unchanged.
- [ ] All 7 new tests pass (3 streaming usage + 2 stuck transient + 2 awareness caps).
- [ ] All existing tests still pass (full suite green, no regressions).
- [ ] No new public API surface (only one new private attribute `_pending_stuck_messages` and one new internal SSE event type `"usage"`).
- [ ] `docs/ARCHITECTURE.md` §7 `send_message` comment mentions `[stuck-detection]`.
- [ ] Adversarial audit produces zero CRITICAL or HIGH findings.

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Stream emits multiple usage chunks (rare, but possible) | The LAST one wins (overwrites the accumulator). Acceptable. |
| Stream emits a usage chunk with `prompt_tokens=0, completion_tokens=0` (provider bug) | `captured_usage` is set, `_extract_usage` returns `(0, 0)`, `on_token_usage` fires with 0. Same as no-usage. Acceptable. |
| Stream emits a usage chunk with `input_tokens`/`output_tokens` instead of `prompt_tokens`/`completion_tokens` (Anthropic format) | `_extract_usage` already handles both formats based on the `provider` argument (line 718-727). The data is passed through unchanged. ✓ |
| Stream has no usage chunk at all (some providers) | `captured_usage` stays `{}`, response has `usage: {}`, `on_token_usage` fires with `(0, 0)`. Backward-compatible. ✓ |
| `_check_stuck` returns `None` (not stuck) | No pending message queued. The next `_call_llm` doesn't prepend anything. ✓ |
| `_check_stuck` returns the SAME message twice in a row (stuck for 6 calls, fires at 3 and 6) | Both are queued. The next `_call_llm` prepends BOTH as a single synthetic user message (joined with `\n\n---\n\n`). The LLM sees both interventions. The pending list is cleared after. ✓ |
| Conversation ends with pending stuck messages (user cancels) | `_cleanup_tool_history` clears them. No memory leak. ✓ |
| Two sessions fire stuck messages simultaneously | Each session has its own list under `_pending_stuck_messages[session_key]`. No cross-session leak. ✓ |
| Stuck message is very long (e.g., `_check_stuck` returns a 1000-char string) | The prepended synthetic user message is large (~1KB). Cost: 1KB of input tokens per stuck call. Acceptable — this only happens for stuck agents, which is rare. |
| Team has 100 members (way over the 500-char cap) | TEAM_ROSTER is truncated to 500 chars + marker. ~10-20 members fit in 500 chars. The marker indicates truncation. |
| Team has 1 member (no truncation needed) | TEAM_ROSTER is returned as-is (no marker). ✓ |
| CURRENT_STATE is exactly 1000 chars | Truncation is `if len > 1000`, so 1000 chars is NOT truncated. Exactly at the cap is OK. |
| CURRENT_STATE is 1001 chars | Truncated to 1000 + marker. The marker is the `(N - 1000)` chars cut off. |
| `_call_llm` is called for a session that has no pending stuck messages | The `pending` variable is `[]`, the `if pending:` block is skipped, `messages` is unchanged. ✓ |
| The new `_pending_stuck_messages` is accessed by a test that doesn't init `AgentRuntime` properly | It's a plain dict; missing-attribute access would crash. All tests that use `AgentRuntime` go through `__init__`, so this is a non-issue. ✓ |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the implementer must update `docs/ARCHITECTURE.md` as follows:

### §7 — Agent Runtime (one-line change)

Update the `send_message` signature comment to mention `[stuck-detection]`:

```markdown
    def send_message(session_key, text)         # tool loop: user msg → [trim to model_max] → LLM → [stuck-detection] → tool calls → results → LLM → response
```

### §3.21q.6 (optional) — Streaming Usage Capture

If the team wants a dedicated section, add a brief note about the streaming usage capture:

```markdown
**Streaming usage capture (Phase CB-3).** `_stream_openai_events` and friends
capture the provider's SSE `usage` chunk and yield a `SSEEvent(type="usage")`.
`_call_llm_streaming` accumulates the usage and includes it in the response dict,
so `on_token_usage` fires with real token counts even for streaming calls.
```

(Adding this section is optional; the §7 change is the minimum.)

---

## 9. Files NOT changed (already correct or out of scope)

- `prompts/system/*.md` — the prompt templates themselves. Out of scope.
- `utils/prompt_loader.py` — the awareness caps apply at the `build_awareness_dict` level; the system prompt composition is unchanged.
- `agent/runtime.py:_check_stuck` itself — the detector is unchanged. Only the CALLER (line 1428-1441) and the CONSUMER (`_call_llm`, `_call_llm_streaming`) change.
- `agent/runtime.py:_call_llm` and `_call_llm_streaming` callers in `_run_loop` — the `messages` argument is prepended with the stuck prefix INSIDE these functions; the caller doesn't need to know.
- `agent/runtime.py:_extract_usage` — unchanged. Already handles both `prompt_tokens`/`completion_tokens` (OpenAI format) and `input_tokens`/`output_tokens` (Anthropic format) at lines 718-727.
- `tests/test_agent_runtime.py:TestStuckDetection` (4 tests) — existing tests. They verify the detector still fires. The new `TestStuckMessageTransient` class tests the delivery.
- `tests/test_agent_runtime.py:TestStreaming` (existing tests) — they mock streamers without a usage chunk, so `captured_usage` stays `{}` and the response's `usage` is `{}`. Backward-compatible.
- `tests/test_project_awareness.py:TestBuildAwarenessBlock` (4 tests) — existing tests. The default team (1-2 members) is well under the 500-char cap.
- `utils/project_awareness.py:load_team`, `build_awareness_snapshot`, `load_project_context` — unchanged. The truncation happens in `build_awareness_dict` after these return.

---

## 10. Risk and Rollback

**Risk:** LOW per fix.

- **Streaming usage fix** is additive: the new `"usage"` event type is yielded in addition to the existing events. If the capture is buggy, `captured_usage` stays `{}` (backward-compatible).
- **Stuck message fix** is a behavioral change: the stuck text is no longer in `conv.messages`. If the LLM no longer reacts to stuck interventions, the agent might continue looping. **Mitigation:** the stuck message is still prepended to the next LLM request, so the LLM still sees it. The only change is that subsequent LLM calls (after the next one) don't see the stuck text in their input. This is the correct behavior per the proposal.
- **Awareness caps** are purely defensive: if the truncated value is buggy, `build_awareness_dict` returns a shorter string. No behavioral change for the typical case (small team, small CURRENT_STATE).

**Failure modes:**

- Streaming usage capture: if the `usage` field is in an unexpected format (e.g., not a dict), `ev.data.get("usage", {})` returns `{}` and the response's usage is `{}`. No crash.
- Stuck message transient: if the synthetic user message is malformed, the LLM provider rejects the request with a 400. The runtime dispatches `on_error`. The agent's user sees the error. Acceptable.
- Awareness caps: if the marker text contains characters that break the system prompt template (e.g., `{{`), the template render fails. The current marker is `\n[... team roster truncated ...]` which is safe.

**Rollback:**

This phase is one commit. To roll back: `git revert <commit-hash>`. The runtime goes back to the pre-CB-3 state:
- `_stream_openai_events` and friends no longer yield `"usage"` events. The response's usage is `{}` (the old behavior).
- `_call_llm_streaming` doesn't handle the `"usage"` event. The hardcoded `usage: {}` returns.
- `_pending_stuck_messages` is removed. Stuck messages are appended to `tool_result_text` again (the old behavior).
- `TEAM_ROSTER` and `CURRENT_STATE` are returned without truncation (the old behavior).

No consumer breaks because the changes are additive (new event type, new attribute, new constants) and the broken behavior is the same as the pre-CB-3 behavior (zero usage, stuck messages in history, no awareness caps).

---

## 11. Post-Mortem

After the commit, a short post-mortem goes at `docs/post-mortems/2026-06-17-CONTEXT-BLOAT-PHASE-3-POST-MORTEM.md` using the §6 format from `prompts/implementationLoop.md`. The post-mortem MUST include the 11 sections (Code Quality Grade, What's Good, What's Bad, Bugs Found, Process Worked, Process Didn't Work, End-User Impact, Pre-Existing Issues, Evolution Suggestions, Lessons Learned, Sign-off).

The post-mortem should specifically address:
- Whether the streaming usage fix is forward-compatible with providers that emit usage in unusual formats (e.g., Gemini, Cohere).
- Whether the stuck message transient prefix is correctly cleared after consumption (no double-send, no missed-send).
- Whether the awareness caps interact correctly with the existing `PROJECT_MEMORY` cap (they should — each is independent).

---

## 12. Author Notes

This spec bundles three independent sub-fixes (streaming usage, stuck messages, awareness caps) into one phase because they're all small, all LOW risk, and all unrelated. Per the proposal's recommendation, "Batched because they're all small and unrelated to each other."

**The streaming usage fix is the most algorithmically interesting** because it requires understanding the SSE event flow across three different providers. The fix is upstream of the runtime (in the streamers) and downstream of the response assembly (in `_call_llm_streaming`). Both ends must be correct.

**The stuck message fix is the most behaviorally subtle** because the stuck intervention is now delivered differently — as a transient prefix instead of as a stored tool result. The LLM's behavior might change in edge cases (e.g., the LLM might "echo" the stuck text back). The fix must include a log line so the supervisor can verify the prefix is being prepended.

**The awareness caps fix is the most defensive** — it can only reduce token usage, never increase it. The cap values are conservative (500 and 1000 chars) and the marker text is short.

**Risk is bounded by the existing test coverage.** The existing `TestStuckDetection` (4 tests) and `TestStreaming` (~5 tests) continue to pass. The new tests add 7 more (3 streaming usage + 2 stuck transient + 2 awareness caps). Total test coverage for the affected code paths goes from ~9 to ~16 tests.

**The spec is identifier-anchored (no line numbers) per Rule 6.8**, except for the stuck injection site (`agent/runtime.py:1428-1441`) which is the only call site and is unambiguous. If the line numbers drift, the implementer should use `grep -n` to find the real location.
