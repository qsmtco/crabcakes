# Proposal: Context Bloat Crisis — Fix Six Bugs That Inflate LLM Token Usage

**Author:** Qaster (supervisor) — at the request of CaptJAQx
**Date:** 2026-06-16
**Status:** Awaiting captain review
**Source bug report:** `docs/bugs/BUG-high-input-token-context-bloat.md` (2026-06-16, "Adversarial Debugging Session")
**Severity:** PRODUCTION CRISIS — OpenRouter data shows 106K–160K input tokens per request, ~11K token growth per turn, agents looping with `tool_calls` finish reason and never reaching a final answer

---

## 1. Executive Summary

The crabcakes local agent runtime has six related bugs that compound to produce severe context bloat. Per-turn token growth averages 11K; cumulative input tokens per request have been observed at 106K–160K (the upper bound exceeds the context window of many models). The bugs are all in `agent/runtime.py`, `models/conversation.py`, and `utils/prompt_loader.py` — the prompt-construction and conversation-management code path.

**Root cause** (one-line summary): `Conversation.trim_to_token_limit()` exists, is unit-tested, and is **never called** by the production runtime. The system prompt, file context, awareness variables, and tool-result augmentation all add tokens with no budget enforcement anywhere in the pipeline.

**This proposal recommends four phases** delivered through the standard implementation loop (spec → phase instructions → builder → adversarial audit → commit). Estimated total: 6–10 hours of work, 5–6 new commits, 1500+ lines of test coverage. Every fix has an explicit safety net (test, smoke check, monitoring hook) so we can ship with confidence.

**Highest-impact, lowest-risk first step:** fix BUG #1 (call `trim_to_token_limit()`) in a single phase, ~1 hour, immediate 60–80% reduction in per-request token growth. This single fix should be applied first regardless of what we do with the other five.

---

## 2. The Crisis in Numbers

| Observation | Source | Implication |
|---|---|---|
| 106K–160K input tokens per request | OpenRouter dashboard | Exceeds context windows of many models; approaching limits of those that accept it |
| ~11K token growth per turn | OpenRouter dashboard | Conversation history accumulates without bound |
| Agents loop with `tool_calls` finish reason | Bug report | Never reach a final answer; cost accumulates |
| `Conversation.trim_to_token_limit()` exists, tested, never called | Code inspection | The cap mechanism is dead code |
| `build_file_context()` injects up to 50K chars of file context | `agent/context.py:242` | ~12.5K tokens of project context sent every call |
| `compose_system_prompt()` appends file context with no size check | `utils/prompt_loader.py:265-268` | The file-context overhead compounds across turns |
| Stuck interventions append ~250 chars to `conv.messages` per fire | `agent/runtime.py:1373-1374` | Each stuck event adds noise to history |
| Streaming calls return `usage: {}` | `agent/runtime.py:1632` | Token monitoring is blind to streaming calls |
| `chars // 4` used for token estimation | `models/conversation.py:222,239,240` | ~60% undercount for code-heavy content |
| `TEAM_ROSTER` and `CURRENT_STATE` have no size caps | `utils/project_awareness.py:531-580` | Unbounded growth as team grows |

---

## 3. The Six Bugs (Detailed)

### BUG #1 — CRITICAL: `trim_to_token_limit()` is dead code

**File:** `models/conversation.py` (defined, never called), `agent/runtime.py` (should call it, doesn't)

**Symptom:** Conversation history grows without bound. Each tool-call iteration adds at minimum two messages (assistant with `tool_calls`, tool with result). The conversation accumulates tokens indefinitely.

**Code evidence:**

```python
# models/conversation.py:251 — METHOD EXISTS
def trim_to_token_limit(self, max_tokens: int) -> None:
    """Trim oldest messages to fit under max_tokens budget."""
    ...

# agent/runtime.py:1685 — _check_and_stop_on_limit exists but only checks cost/step
def _check_and_stop_on_limit(self, session_key: str, conv: Any) -> bool:
    if self._config.cost_limit is not None and conv.total_cost > self._config.cost_limit:
        stopped = True; reason = ...
    elif self._config.step_limit is not None and conv.step_count > self._config.step_limit:
        stopped = True; reason = ...
    # NO TOKEN BUDGET CHECK

# agent/runtime.py:1283, 1380 — _check_and_stop_on_limit IS CALLED, but doesn't trim
self._check_and_stop_on_limit(session_key, conv)
```

**Why it's CRITICAL:** This is the root cause. The mechanism that should prevent unbounded growth is implemented, tested (`tests/test_phase4.py` covers it), and never wired into the hot path. The 11K/turn growth is direct evidence.

**Existing tests:** `tests/test_phase4.py` tests `trim_to_token_limit` in isolation. The tests pass because the method is correct; the bug is that the runtime doesn't call it.

**Fix approach:** Call `conv.trim_to_token_limit(model_max)` at the start of each `_run_loop` iteration, using the model's configured context window as the budget. The `model_max` should come from the provider config (per-model) with a 128K default fallback (matching the existing token-breakdown code at line 1211).

**Estimated impact:** 60–80% reduction in cumulative token growth. Tests with the existing `trim_to_token_limit` test suite should pass without modification (the method is correct; the wiring is the bug).

**Risk:** Medium. The method trims messages; trimming could theoretically remove important context. Mitigation: (a) keep system prompt (always preserve), (b) preserve at least the last 4 messages (existing implementation already does this — see line 269), (c) emit a `messages_trimmed` event so the UI can show "X old messages removed."

---

### BUG #2 — CRITICAL: System prompt has no budget enforcement

**File:** `utils/prompt_loader.py:265-268` (caller), `agent/context.py:239-298` (callee)

**Symptom:** `build_file_context()` defaults to 50,000 characters (~12,500 tokens). For large projects (200+ files), the full file context reaches this cap and is appended to the system prompt on every API call.

**Code evidence:**

```python
# utils/prompt_loader.py:265-268
file_context = build_file_context(project_path)
if file_context:
    result += f"\n\n## File context\n\n{file_context}"
# No size check on result before it's used as the system prompt

# agent/context.py:242 — default 50K chars
def build_file_context(
    project_path: str,
    max_chars: int = 50_000,  # ~12,500 tokens
    ...
```

**Why it's CRITICAL:** The system prompt is sent with every API call. 12.5K tokens × N turns = 12.5K × N cumulative cost. For a 30-turn conversation, that's 375K tokens of file context alone.

**Fix approach:** Add a system-prompt budget check in `compose_system_prompt()`. After composing, measure total length. If it exceeds a threshold (e.g., 8K tokens for a 128K model, or 15% of the model context window), truncate the file context section. The system prompt itself (without file context) should be capped at ~4K tokens; the file context gets whatever's left.

**Estimated impact:** 8–12K token reduction per call. For a 30-turn conversation, that's 240K–360K tokens saved.

**Risk:** Medium. Truncating file context could remove important project info. Mitigation: (a) prefer truncating the longest files first, (b) keep a "core" file list (e.g., README, AGENTS.md) that never gets truncated, (c) emit a `system_prompt_truncated` event so the user knows.

**Design questions to resolve in the spec:**
- What's the threshold? 8K? 15% of context window? Configurable?
- How do we decide which files to keep? Most-recently-modified? Most-frequently-referenced? Tagged "core"?
- Should the file context be cached and refreshed only on file change, or recomputed per call?

---

### BUG #3 — HIGH: Streaming usage is never tracked

**File:** `agent/runtime.py:1541-1632` (streaming path), `agent/runtime.py:1685-1708` (non-streaming check)

**Symptom:** Streaming calls return `"usage": {}` (empty dict). The runtime's token-tracking callbacks (`on_token_usage`, `on_token_breakdown`) fire with zero tokens for every streaming response. Token monitoring is blind to ~50% of calls (whichever path is used).

**Code evidence:**

```python
# agent/runtime.py:1632
return {"choices": [{"message": {"content": full_content, "tool_calls": tool_calls}}], "usage": {}}
#                                                                                       ^^^^^^^^
#                                                                                       empty

# agent/runtime.py:1615
"usage": {},  # streaming responses omit usage; caller should use blocking call for accurate counts
# The comment says the caller "should" switch to blocking — but the caller never does.
```

**Why it's HIGH:** The token monitoring is the user's visibility into cost. If 50% of calls are invisible, the cost dashboard understates real usage by ~50%. This is also the data source we used to discover BUG #1 — without it, the bug would have been silent.

**Fix approach:** Two options:
- **Option A (cheaper):** Parse usage from SSE events. Many providers (OpenAI, Anthropic, OpenRouter) emit a `usage` chunk at the end of the stream. Capture it.
- **Option B (more reliable):** After streaming completes, issue a blocking call purely for token counting. Costs an extra request but gives accurate data.

**Recommendation:** Option A. The OpenAI-compatible providers all emit usage chunks; the runtime just needs to capture them.

**Estimated impact:** Restores token monitoring for streaming calls. No direct cost reduction, but enables the cost dashboard to show real numbers.

**Risk:** Low. This is a monitoring improvement; the actual LLM call already happened.

---

### BUG #4 — HIGH: Stuck messages bloat history

**File:** `agent/runtime.py:1364-1374` (stuck detection), `agent/runtime.py:1634-1683` (`_check_stuck`)

**Symptom:** When the stuck detector fires, it appends ~250 characters of intervention text to the tool result, which is then stored in `conv.messages` via `add_tool_result()`. Each stuck event adds ~250 chars to the conversation history.

**Code evidence:**

```python
# agent/runtime.py:1364-1374
stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
if stuck_msg:
    logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)

# Inject stuck message AFTER tool result recording, with separator
if stuck_msg:
    tool_result_text = tool_result_text + "\n\n---\n⚠️ " + stuck_msg
# tool_result_text is then stored via conv.add_tool_result()
```

**Why it's HIGH:** A stuck agent can fire the intervention 10+ times. That's 2,500+ chars of repetitive warning text in the conversation history, sent with every subsequent API call. The intervention is a one-time signal but is stored as if it were user data.

**Fix approach:** Store the stuck intervention as a transient signal sent to the LLM, but NOT persisted in `conv.messages`. Two implementation options:
- **Option A (cleaner):** Modify the API call to inject the stuck message as a system-side prefix on the LLM request, without modifying the stored message list.
- **Option B (simpler):** Track which intervention has been sent in a per-session dict; don't re-send if already sent this session.

**Recommendation:** Option A. The message is meant to nudge the LLM, not be part of the conversation history. Treat it as request-only metadata.

**Estimated impact:** Variable. For unstuck agents, no change. For stuck agents, eliminates the compounding 250-char-per-fire growth.

**Risk:** Low. The intervention is a one-time signal; the LLM should react to it once and move on.

---

### BUG #5 — MEDIUM: `chars // 4` token estimation is ~60% undercount for code

**File:** `models/conversation.py:214-240` (the estimator), `models/conversation.py:269, 308` (consumers)

**Symptom:** `get_token_estimate()` and the related `get_token_breakdown()` use `chars // 4` as the token estimate. For English prose, this is roughly accurate. For code-heavy content (which tokenizes at ~3.5–4 chars per token for variable names but ~1–2 chars per token for keywords like `def`, `return`, `self`), the heuristic undercounts by ~60%.

**Code evidence:**

```python
# models/conversation.py:222
return (system_chars + conv_chars) // 4

# models/conversation.py:239-240
system_tokens = system_chars // 4
conversation_tokens = conv_chars // 4
```

**Why it's MEDIUM:** This estimate feeds into `trim_to_token_limit()`. If the estimate undercounts, the trim leaves the conversation at 1.6× the actual token count. The bug compounds with BUG #1 (the trim is not called anyway, but when it is, it'll trim less than needed).

**Fix approach:** Use a proper tokenizer. Options:
- **Option A (most accurate):** `tiktoken` library, encoder for the model family.
- **Option B (good enough):** `transformers` tokenizer for the model (heavy dependency).
- **Option C (heuristic, no dep):** Calibrate the divisor based on content type — code gets `// 3`, prose gets `// 4`, mixed gets `// 3.5`.

**Recommendation:** Option A. `tiktoken` is a small, well-maintained library; OpenAI publishes encoders. The model family determines the right encoder.

**Estimated impact:** Better trim accuracy. BUG #1's fix becomes more reliable. Also helps `get_token_breakdown()` return useful monitoring data.

**Risk:** Low. The estimator is only used for monitoring and trim triggering; the actual LLM call sends the real messages and the real provider returns the real usage. The estimate is for the runtime's own decisions, not for the API.

---

### BUG #6 — MEDIUM: Awareness variables have no size caps

**File:** `utils/project_awareness.py:531-580` (`build_awareness_dict`)

**Symptom:** `TEAM_ROSTER` and `CURRENT_STATE` are constructed without size limits. `PROJECT_MEMORY` is truncated to 3000 chars (good). For a project with 20+ team members, `TEAM_ROSTER` could exceed 1000 chars. For a project with a long git history, `CURRENT_STATE` could exceed 1500 chars. These are embedded in the system prompt on every call.

**Code evidence:**

```python
# utils/project_awareness.py — TEAM_ROSTER has no cap
parts["TEAM_ROSTER"] = "\n".join(lines)
# If team has 20 members, lines is 20 entries × ~50 chars = ~1000 chars

# utils/project_awareness.py — CURRENT_STATE has no cap
state_lines.append(f"Git: {git.get('head_sha', '?')[:7]} ({'dirty' if git.get('dirty') else 'clean'})")
# Currently 1 line, but if extended to include recent commits, could grow

# utils/project_awareness.py:574-578 — PROJECT_MEMORY has a cap (good example)
truncated = context[:3000]
if len(context) > 3000:
    truncated += "\n[... context memory truncated ...]"
parts["PROJECT_MEMORY"] = truncated
```

**Why it's MEDIUM:** Bounded by user behavior (team size, git history length). A 20-member team is rare in crabcakes currently, but the cap should be enforced regardless.

**Fix approach:** Add size caps to `TEAM_ROSTER` (~500 chars), `CURRENT_STATE` (~1000 chars), and `PROJECT_MEMORY` (~3000 chars, already there). Truncate with a marker.

**Estimated impact:** Small. 200–500 chars saved per call for projects with large teams. The bigger value is consistency — every awareness var has the same cap-and-truncate pattern.

**Risk:** Low. Truncation with marker text is a standard pattern. The cap values are conservative (way under what would actually cause context issues).

---

## 4. Why These Bugs Coexist

All six bugs are in the prompt-construction pipeline:

```
[File system] → build_file_context (BUG #2)
             → load_team + build_awareness_dict (BUG #6)
                  ↓
[System prompt] → compose_system_prompt (BUG #2, BUG #6)
                  ↓
[User message + tool results] → _check_stuck (BUG #4)
                            → add_tool_result
                            → conv.messages
                  ↓
[Conversation] → trim_to_token_limit (BUG #1, defined but not called)
              → chars // 4 estimate (BUG #5)
                  ↓
[_call_llm] → _call_llm_streaming (BUG #3, usage = {})
                  ↓
[OpenRouter / LLM provider]
```

The pattern: each stage adds tokens with no budget enforcement, and the only mechanism that COULD cap the total (`trim_to_token_limit`) is never called. The streaming path is also blind, so monitoring doesn't catch it.

A complete fix needs to address the budget at every stage, not just add one more cap somewhere. The fix is multi-stage but composable — each stage can be addressed independently and contributes to the total reduction.

---

## 5. Proposed Phases

Four phases. Each phase is a separate implementation loop (spec → phase instructions → builder → adversarial audit → commit). Phases are ordered by impact-to-risk ratio: highest impact, lowest risk first.

### Phase CB-1: Wire up `trim_to_token_limit()` (BUG #1)

**Scope:** Single-line fix in `_run_loop` plus tests.

**What gets changed:**
- `agent/runtime.py:_run_loop` — call `conv.trim_to_token_limit(model_max)` per iteration, with `model_max` from the provider config (default 128K).
- `tests/test_runtime.py` (or new test file) — add a test that asserts a long conversation gets trimmed.
- `agent/runtime.py` — emit a `messages_trimmed` event for observability.

**Files:** 1 production, 1 test.

**Lines:** ~15 production, ~50 test.

**Time:** 30 min – 1 hour.

**Risk:** LOW. The `trim_to_token_limit` method is already tested. The new code just calls it.

**Expected impact:** 60–80% reduction in cumulative token growth. Single most impactful fix.

**Why first:** This is the root cause. Even if we never fix the other five, BUG #1 alone caps the damage. The other bugs become less critical once the conversation is bounded.

---

### Phase CB-2: System prompt budget (BUG #2)

**Scope:** Add a size budget for the system prompt composition. Truncate file context if needed.

**What gets changed:**
- `utils/prompt_loader.py:compose_system_prompt` — measure system prompt length, truncate file context section if it exceeds threshold.
- `agent/context.py:build_file_context` — add a "core files" concept (files that never get truncated, e.g., README, AGENTS.md).
- New helper: `_truncate_file_context_to_budget(context, available_chars)`.
- `agent/runtime.py` — pass `model_max` to `compose_system_prompt` so the budget is context-window-aware.
- Tests: large-project fixture, budget enforcement, core-files preservation.

**Files:** 2 production, 1 test.

**Lines:** ~80 production, ~150 test.

**Time:** 1.5 – 2 hours.

**Risk:** MEDIUM. Truncation could remove important context. Mitigation: (a) configurable threshold, (b) core files, (c) event for observability.

**Expected impact:** 8–12K tokens per call saved.

**Design questions for the spec:**
- Threshold: 8K? 15% of model context? Configurable per-model?
- Core files: hard-coded list, or in a config file? Same for all projects or per-project?
- Truncation strategy: longest-first? Most-recently-modified? Most-frequently-referenced?

---

### Phase CB-3: Stuck messages, streaming usage, awareness caps (BUG #3, BUG #4, BUG #6)

**Scope:** Three small fixes, batched because they're all small and unrelated to each other.

**What gets changed:**
- **BUG #4 (stuck messages):** modify `agent/runtime.py:1364-1374` to send the stuck message as a transient system-side signal on the LLM request, not as a stored message in `conv.messages`.
- **BUG #3 (streaming usage):** modify `agent/runtime.py:_call_llm_streaming` to capture the `usage` chunk from SSE events (OpenAI-compatible providers emit one at the end of the stream).
- **BUG #6 (awareness caps):** modify `utils/project_awareness.py:build_awareness_dict` to truncate `TEAM_ROSTER` to ~500 chars, `CURRENT_STATE` to ~1000 chars, with markers.

**Files:** 2 production, 1 test.

**Lines:** ~60 production, ~120 test.

**Time:** 1.5 – 2 hours.

**Risk:** LOW per fix. BUG #4 is a behavior change for stuck agents but the LLM's response to the intervention should be the same. BUG #3 is a monitoring improvement. BUG #6 is a cap that aligns with the existing `PROJECT_MEMORY` cap.

**Expected impact:**
- BUG #4: eliminates the compounding 250-char-per-fire growth for stuck agents
- BUG #3: restores token monitoring for streaming calls (~50% of calls previously invisible)
- BUG #6: small but consistent cap enforcement

---

### Phase CB-4: Token estimation with `tiktoken` (BUG #5)

**Scope:** Replace the `chars // 4` heuristic with a proper tokenizer.

**What gets changed:**
- Add `tiktoken` to `pyproject.toml` / `requirements.txt`.
- `models/conversation.py` — add `get_token_count_accurate()` using `tiktoken.encoding_for_model(...)`.
- `models/conversation.py:get_token_estimate` and `get_token_breakdown` — use the new accurate count when the model's encoding is available, fall back to the heuristic for unknown models.
- Tests: compare against actual LLM token counts (use a known test case from the existing test suite).

**Files:** 1 production, 1 test, 1 dep.

**Lines:** ~40 production, ~100 test.

**Time:** 1 hour.

**Risk:** LOW. `tiktoken` is a small, well-maintained dependency. The fallback to `chars // 4` for unknown models preserves existing behavior.

**Expected impact:** Better trim accuracy. BUG #1's fix becomes more reliable.

---

## 6. Why This Order

The phases are ordered by **impact-to-risk ratio**:

| Phase | Bug(s) | Impact | Risk | Why first/last |
|---|---|---|---|---|
| **CB-1** | BUG #1 (CRITICAL) | 60–80% reduction | LOW | Root cause; cap everything else |
| **CB-2** | BUG #2 (CRITICAL) | 8–12K/call | MEDIUM | Largest remaining impact, but design questions need answering |
| **CB-3** | BUG #3, BUG #4, BUG #6 (HIGH, HIGH, MEDIUM) | Small to medium | LOW | Batched because small; not blocking the other phases |
| **CB-4** | BUG #5 (MEDIUM) | Better accuracy | LOW | Dependency on BUG #1 being fixed first (so we can validate the new estimator) |

If we had to ship ONE fix, it would be CB-1. If we had to ship TWO, it would be CB-1 + CB-2. The other two phases are incremental improvements that depend on the first two being in place.

---

## 7. Dependencies and Prerequisites

**External dependencies:**
- `tiktoken` (CB-4 only) — small, MIT-licensed, no transitive deps.

**Internal dependencies:**
- CB-1 must come first.
- CB-2, CB-3, CB-4 can run in parallel after CB-1.
- CB-4 is more valuable after CB-1 (validates the new estimator against the trim behavior).

**Testing prerequisites:**
- A real project with 200+ files to test BUG #2. The crabcakes repo itself works (it has 100+ files in tests/).
- A test for stuck detection (the existing `_check_stuck` test should be extended).
- A test for streaming responses with usage chunks. May need to mock SSE events.

**Infrastructure prerequisites:**
- None. All fixes are local to the crabcakes repo.

---

## 8. Open Questions for Captain Review

These are decisions the captain should make BEFORE the spec is written. Each has implications for the fix:

### Q1: Token budget for system prompt (BUG #2)

**What's the threshold?** Three options:
- **A:** Hard cap at 8K tokens. Simple, predictable.
- **B:** 15% of model context window. Adapts to model capability.
- **C:** Configurable per-model. Most flexible, most code.

**My recommendation:** B (15% of context window). Adapts to small models (8B class) and large models (400B class) without configuration. Falls back to a 16K hard cap for unknown model sizes.

### Q2: Core files list (BUG #2)

**Which files are never truncated?** Options:
- **A:** Hard-coded: `README.md`, `AGENTS.md`, `CONVENTIONS.md`.
- **B:** Configurable per-project (a `core_files` list in `.crabcakes/config.yaml`).
- **C:** Auto-detected: files mentioned in the user's first message get priority.

**My recommendation:** A (hard-coded) for v1. Simple, predictable, covers the common case. B can come later if needed.

### Q3: Stuck message mechanism (BUG #4)

**How should the stuck intervention be delivered?** Options:
- **A:** Transient prefix on the LLM request (not stored in `conv.messages`).
- **B:** Per-session flag (one intervention per session, no re-sends).
- **C:** Count threshold (intervention fires at most N times per session).

**My recommendation:** A. The intervention is a signal to nudge the LLM, not part of the conversation. Treating it as transient is the right model.

### Q4: Streaming usage capture (BUG #3)

**Which approach for streaming usage?** Options:
- **A:** Parse usage from SSE events (most providers emit one).
- **B:** After streaming, issue a blocking call for usage.
- **C:** Skip — accept that streaming usage is approximate.

**My recommendation:** A. SSE events are standard, all major providers emit them, no extra API cost. B doubles the cost of streaming calls.

### Q5: Phasing

**Should we ship all four phases in one loop, or space them out?** Options:
- **A:** All four in one loop, 6-10 hours total.
- **B:** Phase CB-1 alone (1 hour), then re-evaluate.
- **C:** Phases CB-1 + CB-2 (3 hours), then re-evaluate.

**My recommendation:** B. CB-1 is the highest-impact, lowest-risk fix and addresses the immediate crisis. After CB-1, we can see the actual remaining impact (with monitoring restored for streaming) and decide whether CB-2 is needed or if the cap is enough. Spacing phases lets us validate each before the next.

---

## 9. Risks and Rollback

**Risks of the overall plan:**

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `trim_to_token_limit` removes important context | Medium | User experience degrades | Preserve system prompt + last 4 messages; emit `messages_trimmed` event for visibility |
| System prompt truncation removes project info | Medium | Agent gives wrong answers | Core files never truncated; truncation marker visible to user |
| Stuck intervention change breaks stuck detection | Low | Stuck agents no longer get nudged | Add a test that asserts the intervention is delivered to the LLM (just not stored) |
| `tiktoken` adds a new dep | Low | Build / install changes | Small dep, no transitive; fallback to `chars // 4` for unknown models |
| Phase CB-2 design questions unanswerable | Medium | Spec is incomplete, can't proceed | Captain should answer Q1–Q2 before spec is written |

**Rollback strategy:**

Each phase is a separate commit. If a phase causes problems, `git revert` the commit. CB-1 is the easiest to roll back (one method call) and is also the lowest-risk phase. CB-2 has the most design risk; if it doesn't work, the rollback is straightforward but the user experience may degrade during the failure.

**If we have to abort the entire plan:**

The current code (before any fix) is at commit `cf628ae` on main. `git checkout cf628ae -- agent/ models/ utils/ tests/` restores the pre-fix state. The bug report documents the crisis; no data is lost.

---

## 10. Success Criteria

How we know the fix worked:

| Metric | Before | After (target) | How to measure |
|---|---|---|---|
| Input tokens per request (OpenRouter dashboard) | 106K–160K | <20K typical, <50K worst case | OpenRouter dashboard |
| Token growth per turn | ~11K | <1K typical | OpenRouter dashboard + crabcakes' own token breakdown |
| Agents reaching final answer | Rare (looping) | Common | Smoke test, real usage |
| Test count | 1554 | 1600+ (50+ new) | `pytest tests/ -q` |
| Crabcakes cost per typical session | High | <25% of current | OpenRouter dashboard |

**Smoke test plan (post-CB-1):**

Re-run the Auxilium Tier 2 smoke test (already documented in the post-mortem at `docs/post-mortems/2026-06-16-AUXILIUM-TIER-2-KB-SYNTHESIS-POST-MORTEM.md`):
1. Launch with `G_DEBUG=fatal-criticals xvfb-run -a python3 main.py`
2. Open Auxilium tab
3. Ask factual question → assert grounded response, count input tokens
4. Ask 5 follow-up questions in sequence → assert token count stays bounded
5. Verify no `messages_trimmed` event on short conversations
6. Verify `messages_trimmed` event on long conversations (synthetic 50-turn test)

**Adversarial audit per phase (per implementationLoop.md §3.1a):**

Each phase gets a full adversarial audit before commit. The audit covers all 11 sections of `prompts/adversarialDebugger.md`:
- Challenge every assumption (e.g., "what if the model has no `max_tokens` config?")
- Trace failure backwards (e.g., "what if the trim happens after the LLM call instead of before?")
- Find hidden assumptions (e.g., "what if the conversation has only system messages?")
- Test weakest links (e.g., "what if the trim removes the last user message?")
- Be mean to error handling (e.g., "what if `model_max` is `None`?")
- Exploit the type system (e.g., "what if `model_max` is a string?")
- Break the external contract (e.g., "what if the provider returns 0 tokens?")
- Simulate the weirdest user (e.g., "what if a user types 100K chars as one message?")
- Verify scope coverage (e.g., "did we update all 3 test files?")
- Audit documentation and comments (e.g., "is the new method documented?")
- Verify tests match the change (e.g., "do the new tests cover the new behavior?")

---

## 11. Timeline and Effort Estimate

| Phase | Time | Cumulative |
|---|---|---|
| CB-1: `trim_to_token_limit` wiring | 1 hour | 1 hour |
| CB-2: System prompt budget | 2 hours | 3 hours |
| CB-3: Stuck + streaming + awareness | 2 hours | 5 hours |
| CB-4: `tiktoken` estimator | 1 hour | 6 hours |
| Adversarial audit per phase | 30 min × 4 = 2 hours | 8 hours |
| Post-mortem | 30 min | 8.5 hours |
| **Total** | **8.5 hours** | |

If we ship only CB-1 (the recommended starting point): 1.5 hours total (1 hour implementation + 30 min audit + minimal post-mortem update).

**Calendar estimate:** Half a day for CB-1 alone. 1.5 days for the full plan, assuming no major surprises.

---

## 12. Alternatives Considered

### Alternative A: Just add a max iteration cap

**What:** Add a hard cap on `_run_loop` iterations (e.g., 10 instead of the current `max_tool_iterations`).

**Why not:** Doesn't address the token growth. An agent that makes 10 successful tool calls still gets all the tool results stored in history. The conversation still grows. The agent might still loop, just shorter.

### Alternative B: Switch to a model with a 1M-token context window

**What:** Use Claude or Gemini with massive context.

**Why not:** Doesn't fix the cost issue. 1M-token context × 100 turns = 100M tokens = $$$$$$. The user still pays for the growth.

### Alternative C: Compress old messages instead of trimming

**What:** Use a separate LLM to summarize old messages into a shorter form.

**Why not:** Adds a dependency on the LLM provider, costs more (extra calls), and has correctness risks (the summary might miss important context). Trimming is simpler, cheaper, and the existing `trim_to_token_limit` is already designed for this.

### Alternative D: Switch the conversation storage to a database with row-level limits

**What:** Move conversation storage to SQLite or similar with a per-conversation row cap.

**Why not:** Doesn't fix the in-flight token growth. The conversation in memory still grows. The persistence layer is already there; the bug is in the runtime, not storage.

---

## 13. Recommendation

**Ship CB-1 first, alone.** One hour, 60–80% impact, lowest risk. After CB-1 is deployed and we see the actual remaining impact, decide whether to proceed with CB-2, CB-3, CB-4 or stop there.

If CB-1 alone brings per-request tokens under 30K, we may not need CB-2 (system prompt budget). The system prompt overhead is bounded by 12.5K (the file-context cap), which is acceptable for most models.

If CB-1 alone brings per-request tokens to 30K–60K, we should proceed with CB-2 (system prompt budget) to bring it under 20K.

If CB-1 alone doesn't move the needle (still 100K+), we have a deeper architectural problem and should investigate before continuing.

**Phases CB-3 and CB-4 are always worth doing** because they fix correctness/monitoring issues that are independent of the token count.

---

## 14. File Organization

The proposal is at: `docs/proposals/PROPOSAL-context-bloat-fix.md`

When approved, the spec will be at: `docs/specs/SPEC-context-bloat-fix.md`

Phase instructions will be at: `docs/specs/CONTEXT-BLOAT-PHASE-{1,2,3,4}-INSTRUCTIONS.md`

Post-mortem will be at: `docs/post-mortems/2026-06-16-CONTEXT-BLOAT-FIX-POST-MORTEM.md` (or appended to the Auxilium Tier 2 post-mortem if CB-1 is the only phase shipped)

Source bug report: `docs/bugs/BUG-high-input-token-context-bloat.md`

---

## 15. Author Notes

This proposal was written after a deep-dive investigation of the bug report at `docs/bugs/BUG-high-input-token-context-bloat.md`. All six bugs were independently verified by reading the crabcakes source code (`agent/runtime.py`, `models/conversation.py`, `utils/prompt_loader.py`, `utils/project_awareness.py`, `agent/context.py`). The verification included line-number citations for each bug's existence.

The proposal structure follows the format of the existing proposal at `docs/proposals/AGENT_COMMAND_HOOK_PROPOSAL.md` (the project's reference proposal template) with adaptations for this specific crisis.

The five questions in §8 are the decisions the captain should make before the spec is written. They're not blocking the proposal itself — they're blocking the spec's design choices.

The phased approach (§5) is designed to be reversible: each phase is a separate commit that can be reverted independently. This lets us stop at any phase if the impact isn't what we expected.

The "ship CB-1 first" recommendation (§13) is the safest path. CB-1 alone addresses the root cause; the other phases are incremental improvements. If we had to ship tomorrow, CB-1 is what we ship.

---

**Status:** Awaiting captain review. QTR is currently offline (provider 503); the proposal can be reviewed and approved without QTR. When QTR returns, the spec can be written and the implementation loop started.
