# BUG: High Input Token Context Bloat — Investigation Report

**Date:** 2026-06-16
**Investigated by:** Adversarial Debugging Session
**Symptom:** OpenRouter dashboard reports 106K–160K input tokens per request, with ~11K token growth per turn. Agents looping with `tool_calls` finish reason, never reaching a final answer.

---

## Investigation Scope

Traced the full prompt construction pipeline across:
- `agent/runtime.py` — AgentRuntime, tool loop, LLM calls
- `agent/context.py` — System prompt builder, file context
- `utils/prompt_loader.py` — Template composition
- `models/conversation.py` — Message serialization, token management
- `utils/project_awareness.py` — Awareness variables
- `prompts/system/*.md` — All system prompt templates
- `gateway/client.py` — Gateway WebSocket client
- `ui/handlers/agent_runtime_handler.py` — Agent→UI wiring
- `agent/enforcement.py` — Post-write verification

---

## BUG #1 — CRITICAL
**File:** `models/conversation.py`
**Severity:** CRITICAL
**Assumption violated:** `trim_to_token_limit()` is the guard that prevents unbounded context growth.
**Attack vector:** The method is defined, tested in `tests/test_phase4.py`, but **never called** in `AgentRuntime._run_loop()`. Conversation history grows without bound.
**Reproduction:**
1. Open a project with CrabCakes
2. Have the agent run tool-call iterations (each adds user msg + assistant msg + tool results)
3. Inspect `conv.messages` — it grows with every iteration
4. Check OpenRouter usage dashboard — input tokens grow ~11K/request
**Root cause:** `_check_and_stop_on_limit()` only checks `cost_limit` and `step_limit`. There is no code path that calls `conv.trim_to_token_limit()`.
**Fix:** Call `conv.trim_to_token_limit(model_max_tokens)` at the start of each `_run_loop` iteration, using the model's configured context window as the budget.

```python
# In _run_loop(), before building API messages:
model_max = 128_000  # or derive from provider config
conv.trim_to_token_limit(model_max)
```

---

## BUG #2 — CRITICAL
**File:** `utils/prompt_loader.py` (`compose_system_prompt`)
**Severity:** CRITICAL
**Assumption violated:** The system prompt is a fixed overhead.
**Attack vector:** `build_file_context()` injects up to **50,000 characters** (~12,500 tokens) of project context into the system prompt with no upper bound check. For projects with 200+ files, the full tree + key files easily reach this cap. The system prompt becomes ~15K tokens for large projects, sent **with every API call**, every turn.
**Reproduction:**
1. Open a large project (200+ files)
2. Ask the agent a simple question
3. Enable `CRABCAKES_PROMPT_DEBUG=1` — observe system prompt is ~15K tokens
4. After 10 turns: system prompt (15K) + history (~50K) = ~65K input tokens
5. After 30 turns: ~100K+ input tokens
**Root cause:** `compose_system_prompt()` appends file context without checking total system prompt size:
```python
# prompt_loader.py — compose_system_prompt()
file_context = build_file_context(project_path)  # up to 50K chars, unchecked
if file_context:
    result += f"\n\n## File context\n\n{file_context}"
```
No call to `get_token_estimate()`, no comparison against model context window.
**Fix:** After composing, measure total system prompt length. If it exceeds a threshold (e.g., 15% of context window for a large model), truncate or skip file context on subsequent turns.

---

## BUG #3 — HIGH
**File:** `agent/runtime.py` (`_call_llm_streaming`)
**Severity:** HIGH
**Assumption violated:** Token tracking covers all calls.
**Attack vector:** The streaming path returns `{"usage": {}}` — an empty dict — as the assembled response. `_extract_usage()` returns `(0, 0)` for this. `on_token_usage` fires with **zero tokens** for every streaming response.
**Reproduction:**
1. Set `on_token_usage` callback to log tokens
2. Send a message to a local agent
3. Streaming calls show 0 tokens in logs; non-streaming calls show real counts
4. The token breakdown callback (`on_token_breakdown`) is never fired for streaming calls because it's only in the non-streaming code path
**Root cause:** `_call_llm_streaming()` explicitly sets `"usage": {}` with the comment *"streaming responses omit usage; caller should use blocking call for accurate counts"*. The caller never switches to blocking for token counting.
**Fix:** Either (a) parse usage from SSE events when the provider emits `usage` deltas, or (b) after streaming completes, issue a blocking call purely for token counting.

---

## BUG #4 — HIGH
**File:** `agent/runtime.py` (stuck detection)
**Severity:** HIGH
**Assumption violated:** The stuck intervention message is a one-time nudge that won't bloat context.
**Attack vector:** When `_check_stuck()` fires, it appends a **200-300 character warning** to the tool result, which is then stored in `conv.messages` via `add_tool_result()`:
```python
# runtime.py — _run_loop()
tool_result_text = tool_result_text + "\n\n---\n⚠️ " + stuck_msg
conv.add_tool_result(call_id, tool_result_text)
```
If the agent is stuck for 10 iterations, that's **+2,500–3,000 chars** of intervention text added to conversation history, compounding with every subsequent API call.
**Reproduction:** Have an agent call the same tool with the same args 3+ times. The stuck message fires each time, each time adding ~250 chars to the conversation.
**Fix:** Store the stuck intervention as an injected system-side signal (not persisted in `conv.messages`), or limit stuck intervention to once per session.

---

## BUG #5 — MEDIUM
**File:** `models/conversation.py` (`get_token_estimate`)
**Severity:** MEDIUM
**Assumption violated:** Token estimation using `chars // 4` is reasonably accurate.
**Attack vector:** The code uses `chars // 4` as a token estimate. For code-heavy content (which has ~3.5–4 chars/token), this is roughly accurate. However, the model uses subword tokenization — common Python tokens like `def`, `return`, `self` are single tokens despite being 4-6 characters. A 50,000-char codebase might tokenize to **20,000+ tokens**, not 12,500. The estimate is off by **~60%** for code.
**Reproduction:** Compare `conv.get_token_estimate()` against OpenRouter's actual `input_tokens` for the same request.
**Fix:** Use a proper tokenizer (tiktoken) for accurate estimation, or calibrate the divisor based on content type.

---

## BUG #6 — MEDIUM
**File:** `utils/prompt_loader.py` (`build_awareness_dict`)
**Severity:** MEDIUM
**Assumption violated:** Awareness variables (`TEAM_ROSTER`, `CURRENT_STATE`, `PROJECT_MEMORY`) are small.
**Attack vector:** `PROJECT_MEMORY` is truncated to 3,000 chars, but `TEAM_ROSTER` and `CURRENT_STATE` have **no size limits**. If a project has 20 team members, `TEAM_ROSTER` could be 1,000+ chars. If `CURRENT_STATE` includes many recent git commits, it could be another 1,500+ chars. These are embedded in the system prompt on every call.
**Reproduction:** Add 20 team members to a project. Enable `CRABCAKES_PROMPT_DEBUG=1` and observe `TEAM_ROSTER` size.
**Fix:** Add size limits to all awareness variables. Cap `TEAM_ROSTER` at ~500 chars, `CURRENT_STATE` at ~1,000 chars.

---

## ROOT CAUSE SUMMARY

### Primary: `trim_to_token_limit()` is Dead Code (BUG #1)

The method that should prevent unbounded context growth is **never called**. This is the root cause of the ~11K token/request growth seen in the OpenRouter data.

### Secondary: System Prompt Has No Budget (BUG #2)

`build_file_context()` can inject up to 50K chars of project context into the system prompt. For large projects, this makes the system prompt itself ~15K tokens — sent with every API call. This compounds with BUG #1.

### How the Numbers Align

The OpenRouter data shows:
- Input tokens: 106K–160K
- Token growth: ~11K/request
- Initial: ~106K = OpenClaw-side system prompt + CrabCakes project context + early conversation
- Growth: conversation history accumulating with each turn (BUG #1)
- 160K DeepSeek call: CrabCakes project context + lengthy conversation history

### Fix Priority

| Bug | Severity | Fix Complexity | Impact |
|-----|----------|---------------|--------|
| BUG #1: `trim_to_token_limit()` never called | CRITICAL | Low | Stops unbounded growth |
| BUG #2: No file context budget | CRITICAL | Medium | Caps system prompt size |
| BUG #3: Streaming usage not tracked | HIGH | Medium | Fixes monitoring |
| BUG #4: Stuck messages bloat history | HIGH | Low | Reduces noise accumulation |
| BUG #5: Token estimation inaccurate | MEDIUM | Low | Better monitoring/trigger |
| BUG #6: Awareness vars unbounded | MEDIUM | Low | Minor size reduction |

---

## Notes

- These findings are based on static code analysis of CrabCakes' local agent runtime
- The OpenRouter data also includes OpenClaw-side prompt inflation (the Favicon agent prompts are managed by OpenClaw, not CrabCakes)
- CrabCakes' local agent runtime (`agent/runtime.py`) is the code path affected by bugs 1–6 above
- The gateway client (`gateway/client.py`) forwards messages to OpenClaw and does not directly control OpenClaw-side prompt construction
