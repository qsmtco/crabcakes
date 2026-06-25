# Proposal: Context Management Roadmap — Compaction, Protection, and Adaptive Budgets

**Author:** Qaster (supervisor)
**Date:** 2026-06-25
**Status:** Awaiting captain review
**Severity:** HIGH — CrabCakes trims at 100% of context window (no soft ceiling), uses delete-only compaction (no cheap lossless layer), and has no `keep_first` invariant protecting the original task.

**Source research:**
- `docs/research/CONTEXT-MANAGEMENT-SOURCE-OF-TRUTH.md` (synthesized single-source-of-truth)
- `docs/research/AGENT-CONTEXT-MANAGEMENT-REPORT.md` (deep survey of OpenCode, Claude Code, OpenHands, Cline, Aider)
- `docs/research/context-management-comparison.md` (head-to-head vs. hidden gems)
- `docs/research/crabcakes-deep-dive-report.md` (full architecture audit)
- `docs/research/hidden-gems-agent-context-management.md` (survey of 10 underrated projects)

**Related proposals:**
- `docs/proposals/PROPOSAL-context-bloat-fix.md` (2026-06-16, SHIPPED — CB-1 through CB-5)

**Architecture alignment:** This proposal modifies components documented in ARCHITECTURE.md §3.21l (`models/conversation.py`), §3.21m (`agent/runtime.py`), §3.21p (`agent/context.py`), and §4.4b (System Prompt Budget). All changes respect the layering rules in §2: `models/` has no UI dependencies, `agent/` has no UI dependencies, `utils/` has no GTK imports.

---

## 1. Executive Summary

The Context Bloat Fix (CB-1 through CB-5, shipped 2026-06-17 through 2026-06-19) established CrabCakes' context management foundation: `trim_to_token_limit()` is wired into the runtime, system prompts have a 15% budget, tiktoken provides accurate counts, and summary-on-trim preserves context fidelity.

**What remains unsolved:**

The current pipeline trims at **100% of the context window** — there is no soft ceiling. Every surveyed open-source agent (OpenCode, Claude Code, OpenHands, Cline, Aider) triggers compaction at **75–85%**. CrabCakes compacts only when already overflowing, which means every compaction event is an emergency: the model has already lost attention to early turns, and the summary-on-trim is a damage-control afterthought rather than a proactive measure.

Additionally, the current compaction is **delete-only**. When the budget is exceeded, entire messages are removed. There is no intermediate "cheap lossless" layer that stubs old tool outputs (which are typically the largest messages) without losing conversation fidelity. OpenCode's two-layer approach — cheap backward-walk stub first, expensive LLM summary only if needed — resolves the vast majority of compaction events with zero information loss and zero LLM cost.

Finally, there is no **`keep_first` invariant**. While the system prompt is stored separately and never trimmed, the first user message (the task description) has no such protection. On a long conversation with a tight budget, the original task can be trimmed away, leaving the agent amnesiac about what it was asked to do.

**This proposal recommends 7 changes** in priority order, delivered through the standard implementation loop (spec → phase instructions → builder → adversarial audit → commit). Priorities 1–3 are low-effort, high-impact changes that close the gap with the best open-source agents. Priority 4 is the architectural upgrade that makes most compaction events free and lossless.

---

## 2. Problem Statement

### 2.1 The Late-Trim Problem

**Current behavior** (`agent/runtime.py:1616-1618`):
```python
model_max = self._compute_model_max(conv)
conv.trim_to_token_limit(model_max)  # trims at 100% of context window
```

`_compute_model_max()` returns the model's full context window (e.g., 128,000 for OpenAI, 1,048,576 for MiniMax-M3). `trim_to_token_limit()` is called with this full value as the ceiling. Compaction only fires when `get_token_estimate() > model_max` — i.e., the conversation has already exceeded the entire context window.

**Why this is wrong:**
- The model's effective attention degrades before the hard limit. Claude Code users reported the model "forgetting" early turns at ~95% utilization (GitHub issue #28728), which is why Claude Code's threshold is 0.95 — and even that's considered too late by the community.
- Cline's 0.80 threshold (discussion #3248) is the consensus default across the surveyed projects.
- At 100%, every compaction is an emergency: the LLM call fails or the trim must succeed immediately. There's no headroom for the summary to be injected (the current code handles this by skipping the summary if it would exceed budget — line ~451 of `conversation.py`, which means the model gets NO context of what was removed).

**Impact:** The model loses attention to early turns before compaction fires. When compaction does fire, the summary-on-trim is often skipped because there's no budget headroom for it. The agent emerges from compaction with no memory of the task.

### 2.2 The Delete-Only Compaction Problem

**Current behavior:** `trim_to_token_limit()` removes entire messages from the conversation. The only intermediate step is `_last_exchange_summary()`, which generates a brief text recap of the removed messages. There is no way to partially compact a message — it's all or nothing.

**Why this matters:** In a typical agent session, tool results are the largest messages by far. A single `exec_command` output can be 100KB (`MAX_EXEC_OUTPUT`, `tools.py:101`). A `read_file` result can be 50KB. These are the messages that push the conversation over budget. But they're also the messages where most of the content is no longer relevant — the agent has already acted on the result.

OpenCode's approach: before the expensive LLM-based summarization, run a cheap pass that replaces old tool outputs with 2K-char stubs. The agent retains the knowledge that a tool was called and roughly what it returned, but the bulk of the output is discarded. This resolves the majority of compaction events with zero LLM cost and zero loss of conversation structure.

**Impact:** Every compaction event either deletes a full message (losing structure) or triggers LLM summarization (costing an API call). Most compaction events could be resolved for free.

### 2.3 The Missing `keep_first` Invariant

**Current behavior:** `trim_to_token_limit()` preserves the system prompt (stored separately in `Conversation.system_prompt`, never in `messages[]`) and the last `tail_preserve = 4` messages. Everything else is trimmable.

**Why this matters:** The first user message is the task description. "Write a REST API for the inventory system." "Fix the race condition in the checkout flow." If this message is trimmed, the agent loses its objective. OpenHands' `keep_first: 2` invariant (system + first user message) is the only protection against this failure mode across all surveyed projects.

**Impact:** Long conversations with tight budgets can trim away the original task. The agent continues operating but without knowledge of what it was asked to do.

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. **Trigger compaction at 80% of context window** (soft ceiling), reserving 20% headroom for summary injection and response space.
2. **Never trim the first N messages** (system prompt + first user message), even under extreme budget pressure.
3. **Add a cheap lossless compaction layer** that stubs old tool outputs before resorting to deletion or LLM summarization.
4. **Protect summary messages** from being the first candidates for eviction.
5. **Ensure LLM-based summarization produces a summary that fits the budget**, with a geometric-retry fallback for pathological cases.
6. **Adapt the system prompt budget** when templates (bug journals, rules) consume most of the 15% allocation.
7. **Preserve all existing invariants**: CB-6 tool-call pairing, `is_summary` flag, system prompt separation, token cache invalidation.

### 3.2 Non-Goals

- **Async summarization** (Aider pattern) — requires threading model changes; deferred.
- **Pluggable condenser protocol** (OpenHands pattern) — overkill for one strategy; build abstraction when we have two.
- **Semantic file partial reads** (Context-Engine-AI) — needs tree-sitter/MCP integration; separate epic.
- **Multi-agent context coordination** — unsolved across the industry; not actionable.
- **KV cache optimization** — provider-level concern; not actionable at the application layer.
- **Repo map / PageRank ranking** (Aider) — prompt enrichment, not context management.

---

## 4. Architecture Alignment

All changes in this proposal respect ARCHITECTURE.md layering and module rules:

| Component | File | ARCHITECTURE.md Section | Change Type |
|-----------|------|------------------------|-------------|
| Soft ceiling computation | `agent/runtime.py` | §3.21m | New helper method `_compute_compaction_threshold()` |
| `keep_first` parameter | `models/conversation.py` | §3.21l | New parameter on `trim_to_token_limit()` |
| Protected message types | `models/conversation.py` | §3.21l | New `TrimPolicy` dataclass |
| Tool output pruning | `models/conversation.py` | §3.21l | New method `prune_tool_outputs()` |
| Head/tail split | `models/conversation.py` | §3.21l | Refactor of `trim_to_token_limit()` + `_last_exchange_summary()` |
| Hard context reset | `models/conversation.py` | §3.21l | New retry loop in summary injection |
| Dynamic budget fraction | `utils/prompt_loader.py` | §4.4b | Modify `_apply_system_prompt_budget()` |

**Layering compliance:**
- `models/conversation.py`: No new imports. `TrimPolicy` is a pure dataclass. `prune_tool_outputs()` and `_find_split_index()` are pure data operations. ✓
- `agent/runtime.py`: New `_compute_compaction_threshold()` helper. No new imports. ✓
- `utils/prompt_loader.py`: Modify `_apply_system_prompt_budget()` arithmetic. No new imports. ✓
- No `ui/` imports in any changed file. ✓
- No `gateway/` imports in any changed file. ✓
- No `subprocess` in any changed file. ✓

**Existing invariants preserved:**
- CB-6 tool-call pairing: all removal logic continues to check `TOOL_RESULT` → `ASSISTANT with tool_calls` pairs. ✓
- `is_summary` flag: all injected summaries continue to set `is_summary=True`. ✓
- System prompt separation: system prompt stays in `Conversation.system_prompt`, never in `messages[]`. ✓
- Token cache invalidation: all new methods that mutate `self.messages` set `self._token_estimate_cache = None`. ✓

---

## 5. The Priority List

Seven changes, ranked by impact × feasibility. Each has a concrete spec: what, why, where, risk, and tests.

---

### Priority 1: Trigger Percentage (Soft Ceiling)

**What:** Replace the implicit "trim at full max_tokens" with an explicit soft/hard ceiling:
- **Soft ceiling** at `0.80 × max_tokens` → triggers compaction
- **Hard ceiling** at `1.0 × max_tokens` → compaction must succeed or the call fails

**Why:** Every surveyed project converges on ~0.80. Claude Code's 0.95 is too late (users report the model losing attention to early turns before the trigger fires — issue #28728). Cline's 0.80 is the consensus default. We currently use 1.0 (the full window), which means compaction only fires when we're already overflowing.

**Where (codebase):**
- `agent/runtime.py:_compute_model_max()` (ARCHITECTURE.md §3.21m, line 1468) — currently returns `max_tokens`, used directly as the trim ceiling.
- `agent/runtime.py` tool loop (line 1616-1618) — `conv.trim_to_token_limit(model_max)` uses the hard ceiling.

**Concrete change:**
```python
# agent/runtime.py — new helper (§3.21m)
def _compute_compaction_threshold(self, conv: Conversation) -> tuple[int, int]:
    """Return (soft_ceiling, hard_ceiling) for context compaction."""
    model_max = self._compute_model_max(conv)
    soft = int(model_max * 0.80)
    hard = model_max
    return soft, hard

# agent/runtime.py:1616 — use soft ceiling as the trim trigger
soft, hard = self._compute_compaction_threshold(conv)
conv.trim_to_token_limit(soft)  # was: model_max (hard)
```

**Make it configurable:** Add `compaction_threshold: float = 0.80` to a provider-level or global config. Users with 1M-context models (MiniMax-M3) may want 0.90.

**Risk:** LOW. Changes a calculation, not control flow. User-visible effect: compaction happens earlier, which is the desired behavior.

**Tests:**
- Existing `TestConversationTrim` passes unchanged (tests trim against a passed limit, not against `_compute_model_max`).
- New test: verify `_compute_compaction_threshold()` returns `(0.80 × max, max)` for a known provider.
- New test: verify `send_message()` triggers trim at soft ceiling, not hard ceiling.

**Impact:** Compaction fires ~20% earlier. Summary injection has headroom (the 20% gap between soft and hard). The model never reaches the degraded-attention zone.

---

### Priority 2: `keep_first` Invariant

**What:** The first N messages (first user message + any immediate context) are never trimmed, even under extreme budget pressure. Default `keep_first = 2`.

Note: The system prompt is stored separately in `Conversation.system_prompt` and is never trimmed. This invariant protects the **first user message** specifically — the task description.

**Why:** OpenHands' `keep_first: 2` is the only invariant that prevents the agent from losing its objective. Without it, a long conversation could trim away the initial task description, leaving the agent amnesiac about what it was asked to do.

**Where (codebase):**
- `models/conversation.py:trim_to_token_limit()` (ARCHITECTURE.md §3.21l, line 365) — add `keep_first` parameter.
- The `tail_preserve = 4` logic (line 434) already protects the last 4 messages; this adds a symmetric protection for the first N.

**Concrete change:**
```python
# models/conversation.py §3.21l
def trim_to_token_limit(self, max_tokens: int, keep_first: int = 2) -> None:
    # ... existing logic ...
    # Outer loop guard changes:
    #   while ... and len(self.messages) > 4:
    # becomes:
    #   while ... and len(self.messages) > (keep_first + tail_preserve):
    #
    # Fallback pop(0) guard changes:
    #   if len(self.messages) > tail_preserve:
    # becomes:
    #   if len(self.messages) > (keep_first + tail_preserve):
```

**Risk:** LOW. Purely defensive — constrains the trim, never loosens it. Worst case: if the conversation is genuinely too large even with `keep_first`, the trim loop exits and the LLM call may fail with `context_length_exceeded`. That's the correct failure mode (better than silently dropping the task).

**Tests:**
- New test: tiny `max_tokens` with `keep_first=2` — verify first 2 messages survive.
- New test: `keep_first=0` — verify behavior matches current (backward-compatible default if explicitly disabled).
- Existing tests pass with `keep_first` defaulting to 2 (the guard only activates when `len <= keep_first + tail_preserve = 6`, and most tests use conversations longer than that).

**Impact:** The agent never loses its original task description. Zero negative effects on normal conversations.

---

### Priority 3: Protected Message Types

**What:** Add a `TrimPolicy` dataclass to bundle trim parameters. Messages matching protected criteria are pruned last, only if the budget demands it.

**Why:** OpenCode's `PRUNE_PROTECTED_TOOLS = ["skill"]` recognizes that some messages are more valuable than others. For CrabCakes:
- Messages with `is_summary=True` should be protected — they're already compressed; removing them loses both the original AND the summary.
- Messages containing agent skill outputs or KB injections are high-value context.

**Where (codebase):**
- `models/conversation.py` (ARCHITECTURE.md §3.21l) — new `TrimPolicy` dataclass, modify `trim_to_token_limit()` to accept it.

**Concrete change:**
```python
# models/conversation.py §3.21l
@dataclass
class TrimPolicy:
    max_tokens: int
    keep_first: int = 2
    tail_preserve: int = 4
    protected_is_summary: bool = True  # don't trim summary messages first

# In trim_to_token_limit, before the fallback pop(0):
#   Scan for non-protected messages in the trimmable region first.
#   Only touch protected messages if nothing else is left.
```

**Risk:** LOW. Changes the eviction order, not the eviction semantics. Messages that were previously trimmed might survive longer (better context fidelity).

**Tests:**
- New test: conversation with `is_summary=True` messages — verify they're trimmed last.
- New test: all messages are protected — verify the trim still succeeds (protection is best-effort, not absolute).
- New test: `TrimPolicy` defaults match current behavior (backward-compatible).

**Impact:** Summary messages survive longer. The agent retains compressed context from earlier compaction events instead of losing it every cycle.

---

### Priority 4: Backwards-Walk Tool Output Pruning (Cheap Lossless Layer)

**What:** Before the expensive LLM-based summarization, run a cheap pass that replaces old tool outputs with short stubs. Walk backward from the newest message, accumulate tool-output tokens, and stop when enough budget has been freed.

**Why:** OpenCode's two-layer approach is the best design in the survey:
1. **Layer 1 (cheap, no LLM):** Replace old tool outputs with stubs. A session of mostly tool calls stays 100% accurate in structure — no LLM cost, no fidelity loss for the conversation flow.
2. **Layer 2 (expensive, LLM):** Only runs when Layer 1 didn't free enough.

CrabCakes currently has only Layer 2 (delete + summarize). Adding Layer 1 means most compaction events become free and lossless.

**Where (codebase):**
- `models/conversation.py` (ARCHITECTURE.md §3.21l) — new method `prune_tool_outputs()`.
- `agent/runtime.py` (ARCHITECTURE.md §3.21m) — call `prune_tool_outputs()` before `trim_to_token_limit()` in the tool loop.

**Concrete change:**
```python
# models/conversation.py §3.21l
def prune_tool_outputs(self, target_tokens: int, protect_turns: int = 2) -> int:
    """Cheap pass: stub old tool results. Returns tokens freed.
    
    Walks backward from the end, skipping the protect_turns most recent
    user→assistant→tool_result→assistant exchanges. For each TOOL_RESULT
    older than that, replaces content with a stub:
    
      "[compacted — {N} chars removed]"
    
    Stops when get_token_estimate() <= target_tokens.
    Idempotent: already-stubbed messages are not re-processed.
    """
```

**Runtime integration:**
```python
# agent/runtime.py tool loop (before existing trim call)
soft, hard = self._compute_compaction_threshold(conv)
if conv.get_token_estimate() > soft:
    conv.prune_tool_outputs(soft)  # Layer 1: cheap lossless
    if conv.get_token_estimate() > soft:
        conv.trim_to_token_limit(soft)  # Layer 2: delete + summarize
```

**Stub format:** Messages are replaced in-place. The original content is not preserved in the conversation (it could be logged separately for debugging). The stub must include:
- The tool name (from the parent ASSISTANT message's `tool_calls`).
- The original content length.
- A clear marker that this is compacted.

Example stub:
```
[compacted — exec_command output, 98734 chars removed]
```

**Risk:** MEDIUM. We're mutating message content, which affects the conversation transcript. Must preserve:
- CB-6 pairing invariant (don't stub a tool result without considering its parent assistant message).
- Token cache invalidation (`_token_estimate_cache = None` before and after).
- Idempotence (detect already-stubbed messages by their `[compacted —` prefix).

**Tests:**
- Tool outputs are stubbed in order (oldest first).
- The protected recent turns are untouched.
- Token estimate drops below target after pruning.
- Re-run is a no-op (idempotence).
- CB-6 pairing is preserved (parent assistant message's `tool_calls` still references the same `tool_call_id`).
- Token cache is invalidated after pruning.

**Impact:** Most compaction events resolved with zero LLM cost. A 50-turn conversation with large tool outputs (the common case for Coder agent) stays structurally intact even when the raw outputs are stubbed.

---

### Priority 5: Head/Tail Split with Role Anchoring

**What:** When the cheap prune (P4) isn't enough and we need LLM summarization, use Aider's head/tail split:
1. Walk backward from the end, accumulating tokens, until you've used half the budget → that's the **tail** (kept verbatim).
2. Everything before that is the **head** (summarized).
3. Ensure the split point falls on an assistant message boundary (not a user message).

**Why:** Aider's `while messages[split_index - 1]["role"] != "assistant"` is a small detail with a large effect: it prevents the LLM from being asked to "continue" a conversation that ends on a user turn, which confuses the model and produces poor summaries.

**Where (codebase):**
- `models/conversation.py` (ARCHITECTURE.md §3.21l) — new `_find_split_index()`, refactor of `trim_to_token_limit()` + `_last_exchange_summary()` to coordinate.

**Concrete change:**
```python
# models/conversation.py §3.21l
def _find_split_index(self, budget_tokens: int) -> int:
    """Walk backward to find where head ends and tail begins."""
    half_budget = budget_tokens // 2
    tail_tokens = 0
    split = len(self.messages)
    for i in range(len(self.messages) - 1, -1, -1):
        msg_tokens = self.messages[i].tokens_used or len(self.messages[i].content) // 4
        if tail_tokens + msg_tokens >= half_budget:
            break
        tail_tokens += msg_tokens
        split = i
    # Role-anchor: walk back until we're at an assistant boundary
    while split > 1 and self.messages[split - 1].role != MessageRole.ASSISTANT:
        split -= 1
    return max(split, 1)
```

The refactored `trim_to_token_limit()` coordinates:
1. Try cheap prune (P4) — already called from runtime.
2. If still over budget, find the split point.
3. Summarize the head via `_last_exchange_summary()` (enhanced to cover the full head, not just the last exchange).
4. Glue: `[head_summary as is_summary=True] + [tail_verbatim]`.

**Risk:** MEDIUM. Changes the structure of the message list after trim. Must preserve:
- CB-6 pairing invariant (don't split an assistant+tool_call from its tool_result — walk the split point forward past any orphaned tool_results).
- The `is_summary=True` flag on the injected summary message.
- `keep_first` — the split point must not be before `keep_first`.

**Tests:**
- Split index lands on an assistant message boundary.
- Tool_call/tool_result pairs are never split across the boundary.
- Summary + tail fits within budget.
- Head/tail compaction is idempotent on re-run.
- `keep_first` is respected (split >= `keep_first`).

**Impact:** Higher-quality summaries that don't confuse the model. The agent gets a clean head-summary + verbatim tail, which is the pattern used by Aider's most stable compaction mode.

---

### Priority 6: Hard Context Reset Fallback

**What:** When the LLM summarization (P5) produces a summary that itself exceeds the budget, retry with progressively smaller head sizes. Each retry drops the largest 20% of events from the head (geometric scaling, factor 0.8). After 5 retries, return a minimal stub.

**Why:** OpenHands' `hard_context_reset` with `context_scaling = 0.8` handles pathological conversations — one giant tool result that makes the head un-summarizable. Without this fallback, CrabCakes silently skips the summary (current behavior: `return` at line ~451 if `summary_tokens + current_tokens > max_tokens`), leaving the model with no context of what was removed.

**Where (codebase):**
- `models/conversation.py:trim_to_token_limit()` (ARCHITECTURE.md §3.21l) — the budget-check after summary generation (line ~451).

**Concrete change:**
```python
# Current (line ~451):
#   if current_tokens + summary_tokens > max_tokens:
#       return  # skip injection — model gets no context
# New:
if current_tokens + summary_tokens > max_tokens:
    for attempt in range(5):
        scale = 0.8 ** (attempt + 1)
        head = self._scale_head_messages(scale)  # drop largest 20% each iteration
        summary = self._summarize_head(head)
        if len(summary) // 4 + current_tokens <= max_tokens:
            break
    else:
        summary = "[Context reset — earlier conversation was too large to summarize]"
    # Inject whatever summary we got (even the stub)
```

**Risk:** LOW. The fallback is bounded (max 5 retries) and only fires when the current code would have given up entirely. Worst case: the stub message, which is strictly better than no message.

**Tests:**
- Synthetic 500K-char tool result that can't be summarized in one pass — verify retry loop reduces the head each iteration.
- Final fallback stub is injected when all retries fail.
- Normal conversations (summary fits first try) — no retries, no behavior change.

**Impact:** Pathological conversations get a graceful degradation path instead of silent context loss. Rare but critical when it fires.

---

### Priority 7: Dynamic Budget Fraction

**What:** After template composition, measure the actual template size. If templates (bug journal + rules + role prompts) already consume most of the 15% budget, increase the file-context budget fraction dynamically.

**Why:** The fixed 15% budget (ARCHITECTURE.md §4.4b, `SYSTEM_PROMPT_BUDGET_FRACTION = 0.15`) only caps file context. If templates consume 14% of a 128K window, only 1% remains for file context — the agent gets almost no project context. The system should adapt.

**Where (codebase):**
- `utils/prompt_loader.py:_apply_system_prompt_budget()` (ARCHITECTURE.md §4.4b, line 392).

**Concrete change:**
```python
# Current:
budget_tokens = int(model_max_tokens * SYSTEM_PROMPT_BUDGET_FRACTION)

# New:
template_tokens = measure_template_tokens(...)
template_fraction = template_tokens / model_max_tokens
budget_fraction = max(SYSTEM_PROMPT_BUDGET_FRACTION, 0.25 - template_fraction)
budget_tokens = int(model_max_tokens * budget_fraction)
```

**Risk:** LOW. The change gives *more* room for file context, never less. The cap at 0.25 prevents the system prompt from eating the entire conversation budget.

**Tests:**
- Large template (bug journal with 50 entries) triggers a higher budget fraction.
- Small template (fresh agent, no bug journal) — budget fraction stays at 0.15.
- Budget fraction never exceeds 0.25.

**Impact:** Agents with large self-improvement journals retain meaningful file context. Prevents the self-improvement system from inadvertently starving the project context.

---

## 6. Dependencies and Ordering

```
P1 (Trigger %) ──────────────────────────────┐
P2 (keep_first) ──────────────────────────────┤
P3 (Protected types) ──────────────┐          │
                                   ↓          ↓
P4 (Backwards-walk prune) ──→ P5 (Head/tail split) ──→ P6 (Hard reset)
                                   │
P7 (Dynamic budget) ──────────────┘ (independent, can ship anytime)
```

- **P1, P2, P3** are independent of each other and can be developed in parallel.
- **P4** must come before **P5** (the head/tail split coordinates with the cheap prune).
- **P5** must come before **P6** (the hard reset is a fallback within the head/tail summarization).
- **P7** is independent and can ship anytime.

**Recommended delivery:** Two batches.
- **Batch A (P1 + P2 + P3):** Low-effort, high-impact. Closes the gap with the best open-source agents. ~3 hours.
- **Batch B (P4 + P5 + P6):** Architectural upgrade. Adds the cheap lossless layer and improves summary quality. ~6 hours.
- **P7:** Ships when convenient. ~1 hour.

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Soft ceiling triggers too early for large-context models (MiniMax 1M) | Medium | Compaction happens unnecessarily | Make threshold configurable (`compaction_threshold: float = 0.80`); MiniMax users can set 0.90 |
| `keep_first` prevents trimming when conversation is genuinely too large | Low | `context_length_exceeded` error from provider | This is the correct failure mode. The error message is clear and the user can start a new conversation. |
| Tool output stubbing loses critical information | Medium | Agent can't reference old command output | Stub preserves tool name and original size. Agent can re-run the command if needed. Original output can be logged to audit file for debugging. |
| Head/tail split breaks CB-6 pairing | Low | Provider rejects tool result (mismatched `tool_call_id`) | Split-point validation walks forward past orphaned tool_results. Test suite covers this invariant. |
| Hard reset stub message confuses the model | Low | Agent behaves erratically after context reset | Stub message is clearly marked. The model understands "context reset" from training. Strictly better than silent context loss (current behavior). |
| Dynamic budget fraction consumes too much context | Low | Conversation has less room for messages | Capped at 0.25 (25% of context window). The conversation always retains ≥75% for messages. |

---

## 8. Success Criteria

| Metric | Before | After (target) | How to measure |
|--------|--------|----------------|----------------|
| Compaction trigger point | 100% of context window | 80% of context window | `get_token_breakdown().usage_percent` at trim time |
| `context_length_exceeded` errors / 100 turns | (track) | 0 | Provider error logs |
| `tool_call_id` pairing violations / 100 turns | 0 (enforced) | 0 (maintained) | CB-6 test suite |
| Compaction events resolved by cheap prune (P4) | 0% (doesn't exist) | >70% | Counter in `prune_tool_outputs()` vs `trim_to_token_limit()` |
| Summary injection success rate | ~50% (skipped when no headroom) | >95% (headroom from soft ceiling) | Counter in summary injection code |
| First user message survival rate | <100% (can be trimmed) | 100% (keep_first invariant) | `keep_first` test suite |
| API cost per task | (baseline) | -30% to -50% | OpenRouter dashboard |

---

## 9. Testing Strategy

Each priority follows the standard adversarial audit loop (per `docs/research/AGENT-CONTEXT-MANAGEMENT-REPORT.md` recommendations and the existing CB-1 through CB-5 pattern):

### 9.1 Unit Tests

| Priority | New tests | Key scenarios |
|----------|-----------|---------------|
| P1 | 3 | Soft/hard ceiling computation, trim at soft not hard, configurable threshold |
| P2 | 3 | First 2 messages survive tiny budget, `keep_first=0` backward compat, existing tests pass |
| P3 | 3 | Summary messages protected, all-protected still trims, `TrimPolicy` defaults |
| P4 | 6 | Oldest-first stubbing, protected turns, idempotence, CB-6 preservation, cache invalidation, token reduction |
| P5 | 5 | Assistant-boundary split, CB-6 no-split, budget fit, idempotence, `keep_first` respected |
| P6 | 3 | Giant tool result retry loop, stub fallback, normal conversation unaffected |
| P7 | 3 | Large template → higher fraction, small template → 0.15, cap at 0.25 |

### 9.2 Integration Tests

- **Smoke test:** 50-turn conversation with large tool outputs (simulating Coder agent on a real project). Verify: (a) compaction fires at ~80%, (b) first user message survives, (c) no `context_length_exceeded` errors, (d) summary injection succeeds.
- **Multi-provider test:** Run the same conversation against OpenAI (128K), MiniMax (1M), and Anthropic (200K) provider configs. Verify the soft ceiling scales proportionally.
- **Pathological test:** Single 500KB tool result. Verify the hard reset fallback fires and produces a valid stub message.

### 9.3 Adversarial Audit

Each priority gets a full adversarial audit before commit, covering:
- Challenge every assumption (what if `model_max` is 0? `None`? negative?)
- Trace failure backwards (what if the trim happens after the LLM call instead of before?)
- Find hidden assumptions (what if the conversation has only system messages?)
- Test weakest links (what if `keep_first` > `len(messages)`?)
- Be mean to error handling (what if `tiktoken` is unavailable?)
- Break the external contract (what if the provider returns 0 tokens?)
- Simulate the weirdest user (what if a user types 100K chars as one message?)
- Verify scope coverage (did we update ARCHITECTURE.md?)
- Audit documentation and comments
- Verify tests match the change

---

## 10. Timeline and Effort Estimate

| Batch | Priority | Time | Cumulative |
|-------|----------|------|------------|
| **A** | P1: Trigger percentage | 45 min | 45 min |
| **A** | P2: `keep_first` invariant | 30 min | 1.25 hr |
| **A** | P3: Protected message types | 45 min | 2.1 hr |
| **A** | Adversarial audit (3 × 30 min) | 1.5 hr | 3.6 hr |
| **B** | P4: Backwards-walk prune | 2 hr | 5.6 hr |
| **B** | P5: Head/tail split | 2 hr | 7.6 hr |
| **B** | P6: Hard context reset | 1 hr | 8.6 hr |
| **B** | Adversarial audit (3 × 30 min) | 1.5 hr | 10.1 hr |
| **—** | P7: Dynamic budget fraction | 45 min | 10.9 hr |
| **—** | ARCHITECTURE.md updates | 30 min | 11.4 hr |
| **—** | Post-mortem | 30 min | 12 hr |
| **Total** | | **~12 hours** | |

**Calendar estimate:** Batch A in half a day. Batch B over 1–2 days. P7 whenever convenient.

---

## 11. Alternatives Considered

### Alternative A: Just lower the `model_max` in provider config

**What:** Set `max_tokens` in providers.yaml to 80% of the real value.

**Why not:** This confuses two concerns: the model's actual context window (needed for `_compute_model_max` resolution chain, KB fallback, etc.) and the compaction trigger. The model_max should reflect reality; the soft ceiling is a separate policy. Also doesn't help with P2-P7.

### Alternative B: KV cache optimization (prompt caching)

**What:** Use provider-side prompt caching (Anthropic, OpenAI) to avoid re-encoding the static prefix.

**Why not:** This is an API-level optimization, not a context management strategy. It reduces cost but doesn't solve the fundamental "trim too late, too destructively" problem. Compatible with this proposal but orthogonal.

### Alternative C: Sliding window (no summarization)

**What:** Keep only the last N messages, discard everything else. No summary injection.

**Why not:** The model loses all context of what was accomplished. We already have summary-on-trim (§4.10) which is strictly better. This proposal makes the summary better (P5) and ensures it actually fits (P6).

### Alternative D: External memory store (vector DB)

**What:** Store old conversation turns in a vector database, retrieve relevant ones on each turn.

**Why not:** Adds a major dependency (embedding model, vector store), increases latency, and the retrieval quality is unproven for code agent workflows. CrabCakes already has the KB system for persistent knowledge; conversation compaction should stay in-process. Could be a future enhancement on top of this proposal.

---

## 12. ARCHITECTURE.md Updates Required

When this proposal is implemented, the following ARCHITECTURE.md sections must be updated (per §0 rule):

| Section | Change |
|---------|--------|
| §3.21l (`models/conversation.py`) | Add `TrimPolicy` dataclass, `keep_first` parameter, `prune_tool_outputs()` method, `_find_split_index()` method. Update `trim_to_token_limit()` signature. |
| §3.21m (`agent/runtime.py`) | Add `_compute_compaction_threshold()` helper. Update tool loop to call `prune_tool_outputs()` before `trim_to_token_limit()`. |
| §4.4b (System Prompt Budget) | Update `_apply_system_prompt_budget()` to describe dynamic fraction. |
| §11 (Test Inventory) | Add new test files / test classes for each priority. |
| §2 (Directory Structure) | No changes (no new files). |

---

## 13. File Organization

**Proposal:** `docs/proposals/PROPOSAL-context-management-roadmap.md` (this file)
**Source research:** `docs/research/CONTEXT-MANAGEMENT-SOURCE-OF-TRUTH.md`
**Spec (when approved):** `docs/specs/SPEC-context-management-roadmap.md`
**Phase instructions:** `docs/specs/CONTEXT-MGMT-PHASE-{1..7}-INSTRUCTIONS.md`
**Post-mortem:** `docs/post-mortems/2026-06-XX-CONTEXT-MANAGEMENT-ROADMAP-POST-MORTEM.md`

---

## 14. Open Questions for Captain Review

### Q1: Soft ceiling value

Default at 0.80? Make it configurable? Per-provider or global?

**Recommendation:** 0.80 default, configurable per-provider in `providers.yaml` as `compaction_threshold: float`. MiniMax (1M context) users may want 0.90.

### Q2: `keep_first` value

Default at 2? Should it be configurable?

**Recommendation:** 2 (system prompt is separate; this protects the first user message + the first assistant response). Not configurable in v1 — the value 2 is the industry consensus (OpenHands).

### Q3: Tool output stub format

Should stubs preserve any content from the original output (e.g., first/last N chars)?

**Recommendation:** No. The stub should be minimal: `[compacted — {tool_name} output, {N} chars removed]`. Preserving partial content creates a false sense of completeness. The agent can re-run the command if it needs the output.

### Q4: Should P4 (cheap prune) log original outputs?

Storing the original tool output in an audit file (not in the conversation) allows debugging.

**Recommendation:** Yes, log to `~/.config/crabcakes/logs/pruned-outputs.log` with a rotating file handler. This is debugging-only, not loaded back into the conversation.

### Q5: Batch delivery or all-at-once?

Ship Batch A (P1-P3) first and evaluate, or ship everything?

**Recommendation:** Ship Batch A first. After validation (confirm compaction fires at 80%, summaries inject successfully, first message survives), proceed to Batch B. P7 can ship anytime.

---

## 15. Recommendation

**Ship Batch A (P1 + P2 + P3) first.** Three low-effort, high-impact changes that close the most critical gaps:

1. Compaction fires at 80% instead of 100% (P1) — eliminates the "emergency compaction" failure mode.
2. The original task description is never trimmed (P2) — eliminates the "amnesiac agent" failure mode.
3. Summary messages are protected from early eviction (P3) — preserves compressed context.

Combined effort: ~3 hours including adversarial audit. No architectural changes — these are parameter additions and eviction-order tweaks to existing functions.

After Batch A validation, **proceed to Batch B (P4 + P5 + P6)** to add the cheap lossless compaction layer. This is the architectural upgrade that makes most compaction events free and lossless, reducing API costs by 30-50% for tool-heavy sessions.

**P7 ships when convenient** — it's independent of the other priorities and addresses a narrow case (large self-improvement journals).

---

## 16. Author Notes

This proposal synthesizes findings from four research documents produced by a multi-agent research session (Qaster + QTR, 2026-06-25). The research surveyed 15 open-source projects across two categories (leading coding agents and underrated context management tools) and produced concrete recommendations with code references.

The proposal format follows the established CrabCakes pattern: `PROPOSAL-context-bloat-fix.md` (the predecessor, shipped 2026-06-17 through 2026-06-19) for structure, and `PROPOSAL-security-remediation-roadmap.md` for the phased delivery pattern.

All code references (file names, line numbers, function signatures) were verified against the current codebase at commit `9834263` (2026-06-25). The ARCHITECTURE.md references were verified against the version current at the same commit.

The seven priorities represent the consensus best practices across the surveyed projects, filtered for CrabCakes' specific architecture (GTK4 desktop agent, local runtime, multi-provider, self-improvement stack). Items explicitly deferred (async summarization, pluggable condenser, semantic partial reads, multi-agent coordination) are listed in §3.2 with rationale.

---

**Status:** Awaiting captain review.
