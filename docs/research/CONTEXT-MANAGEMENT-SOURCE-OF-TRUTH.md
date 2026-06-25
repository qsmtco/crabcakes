# CrabCakes Context Management — Source of Truth

> **One file to rule them all.** This is the single authoritative reference for
> CrabCakes' context management: what we have, what we're missing, what we're
> building, and in what order.
>
> **Synthesized from:**
> - `context-management-comparison.md` — head-to-head vs. hidden gems
> - `crabcakes-deep-dive-report.md` — full architecture audit
> - `hidden-gems-agent-context-management.md` — survey of 10 underrated projects
> - `AGENT-CONTEXT-MANAGEMENT-REPORT.md` — deep survey of top 5 open-source agents
>
> **Last updated:** 2026-06-25

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [What We're Good At](#2-what-were-good-at)
3. [What We're Missing](#3-what-were-missing)
4. [The Priority List](#4-the-priority-list)
5. [Cross-Cutting Invariants](#5-cross-cutting-invariants)
6. [What We Explicitly Won't Do](#6-what-we-explicitly-wont-do)
7. [Metrics](#7-metrics)
8. [Appendix: Code References](#8-appendix-code-references)

---

## 1. Current Architecture

The context pipeline has three stages, executed in order before every LLM call:

```
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: SYSTEM PROMPT COMPOSITION                                │
│  utils/prompt_loader.py (477 lines)                                │
│                                                                     │
│  compose_system_prompt() layers:                                    │
│    1. default.md           — role, tools, format                   │
│    2. collab.md            — agent-to-agent protocol               │
│    3. crabcakes-context.md — platform identity                     │
│    4. project-awareness.md — if project active                     │
│    5. crabcakes-commands.md — if project active                    │
│    6. project-onboarding.md — if project NOT yet onboarded         │
│    7. coder.md / debugger.md / auxilium.md — by agent role         │
│    8. {role}-bugs.md       — self-improvement bug journal          │
│    9. {role}-rules.md      — self-improvement project rules        │
│                                                                     │
│  Budget: 15% of context window (SYSTEM_PROMPT_BUDGET_FRACTION=0.15)│
│  Hard cap: 16K tokens (~64K chars) when model_max unknown          │
│  Smart truncation: core files (README, AGENTS, CONVENTIONS,         │
│    ARCHITECTURE) always preserved; non-core trimmed oldest-first    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: FILE CONTEXT                                             │
│  agent/context.py (541 lines)                                      │
│                                                                     │
│  build_file_context_with_core_files():                              │
│    1. .crabcakes/ project docs (always first, always included)      │
│    2. Directory tree (gitignore-respected)                          │
│    3. Key files: README.md, ARCHITECTURE.md, pyproject.toml, etc.   │
│    4. CORE FILES at END (README, AGENTS, CONVENTIONS, ARCHITECTURE) │
│                                                                     │
│  File read cap: 50KB per file                                      │
│  Total file context cap: 50K chars                                  │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: CONVERSATION TRIM                                        │
│  models/conversation.py (503 lines)                                │
│                                                                     │
│  Runtime calls (agent/runtime.py:1616-1618):                        │
│    model_max = self._compute_model_max(conv)                        │
│    conv.trim_to_token_limit(model_max)                              │
│                                                                     │
│  trim_to_token_limit(max_tokens):                                   │
│    - Iterates while token estimate > max_tokens and len > 4         │
│    - Removes tool_call/tool_result pairs together (CB-6 invariant)  │
│    - Fallback: pop oldest message in trimmable region               │
│    - Preserves last 4 messages (tail_preserve=4)                    │
│    - After trim: injects is_summary=True message with brief recap   │
│                                                                     │
│  Token estimation:                                                  │
│    - tiktoken when available (CB-4)                                 │
│    - chars÷4 fallback                                               │
│    - Cached on (len(messages), hash(system_prompt)) (CB-5)          │
│                                                                     │
│  _compute_model_max():                                              │
│    - Resolution: provider.max_tokens → caller_default → 128K        │
│    - No trigger percentage — uses full max_tokens as the ceiling     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Constants (current values)

| Constant | Value | Location |
|----------|-------|----------|
| `SYSTEM_PROMPT_BUDGET_FRACTION` | 0.15 | `prompt_loader.py:352` |
| `DEFAULT_SYSTEM_PROMPT_BUDGET_CHARS` | 64,000 (16K × 4) | `prompt_loader.py:349` |
| `MAX_EXEC_OUTPUT` | 100 KB | `tools.py:101` |
| `MAX_READ_SIZE` | (in tools.py) | `tools.py` |
| `FALLBACK` (model max) | 128,000 | `runtime.py:1484` |
| `tail_preserve` | 4 messages | `conversation.py:434,475` |
| File context hard cap | 50,000 chars | `context.py` |

---

## 2. What We're Good At

These are capabilities CrabCakes already has that most other projects don't:

| # | Capability | What It Does | Source |
|---|-----------|--------------|--------|
| 1 | **5-layer self-improvement stack** | Bug journal → project rules → enforcement → structured feedback → dream consolidation. No other project has a learning system. | SPEC-1 through SPEC-4 |
| 2 | **Untrusted-data fences** | `<untrusted-project-data>` wrappers prevent prompt injection from cloned repos. | `prompt_loader.py` |
| 3 | **Budget-aware system prompt** | System prompt capped at 15% of context window, not a fixed char count. | `prompt_loader.py:352` |
| 4 | **Smart truncation with invariants** | Core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) always preserved during truncation. Non-core trimmed oldest-first. | `prompt_loader.py` |
| 5 | **Tiktoken-accurate counting with cache** | Real tokenizer accuracy without re-encoding on every iteration. Cache keyed on `(len(messages), hash(system_prompt))`. | `conversation.py:271-299` |
| 6 | **Summary-on-trim injection** | When messages are trimmed, a compact summary is injected as `is_summary=True` so the model doesn't lose context. Budget-aware: skipped if injection would exceed budget. | `conversation.py:454` |
| 7 | **Per-turn token breakdown** | `get_token_breakdown()` reports system/conversation/remaining/usage% on every turn. | `conversation.py:323` |
| 8 | **Byte-cap tool output** | `MAX_EXEC_OUTPUT = 100KB` — already using byte-cap, not line-cap. (The hidden gems report flagged this as missing; it's not.) | `tools.py:101` |
| 9 | **Model context auto-discovery** | `/v1/models` probe auto-fills context window. Just shipped 2026-06-24. | `provider_test.py` |
| 10 | **Security enforcement** | Trust gate, CRIT-1/2 subprocess hardening, audit log. No other project has this level. | Throughout |

---

## 3. What We're Missing

From the research, here are the gaps — sorted by impact, with the source project that does it best:

| # | Gap | Who Does It Best | Impact | Effort |
|---|-----|-----------------|--------|--------|
| 1 | **No trigger percentage** — trim uses full max_tokens as ceiling, not 80% | Cline (0.80), OpenCode (0.75) | 🔴 Critical | Low |
| 2 | **No mid-conversation compaction** — we only delete old messages, never rewrite/consolidate | OpenCode (prune+summarize), OpenHands (LLM condenser) | 🔴 Critical | High |
| 3 | **No `keep_first` invariant** — nothing prevents trimming the system prompt or first user message | OpenHands (`keep_first: 2`) | 🔴 High | Low |
| 4 | **No per-message-type weighting** — tool results, user messages, and assistant text are equally evictable | OpenCode (`PRUNE_PROTECTED_TOOLS`) | 🟡 Medium | Low |
| 5 | **No backwards-walk prune** — trim walks forward; OpenCode walks backward and stops early | OpenCode (`prune()`) | 🟡 Medium | Medium |
| 6 | **No head/tail split with role anchoring** — trim doesn't ensure the split ends at an assistant message | Aider (`summarize_real()`) | 🟡 Medium | Medium |
| 7 | **No hard fallback when summary exceeds budget** — if summary is oversized, we just skip it | OpenHands (`hard_context_reset`, geometric scaling) | 🟡 Medium | Low |
| 8 | **Dynamic budget fraction** — 15% is fixed; large bug journals + rules can consume it all | Novel (our own analysis) | 🟡 Medium | Low |
| 9 | **No context pressure signal** — no persistent tracking or alerting at >80% utilization | Novel | 🟢 Low | Medium |
| 10 | **No semantic file partial reads** — we read entire files, not individual symbols | Context-Engine-AI (MCP) | 🟢 Low (big effort) | High |
| 11 | **No multi-agent context coordination** — each agent independently loads the same files | ContextOptimizer | 🟢 Low | High |
| 12 | **Dream consolidation (SPEC-4) is partial** — nightly analysis layer not fully implemented | Internal spec | 🟢 Low | Medium |

---

## 4. The Priority List

Seven changes, ranked by impact × feasibility. Each has a concrete spec: what, why, where, risk.

### ━━━ Priority 1: Trigger Percentage ━━━

**What:** Replace the implicit "trim at full max_tokens" with an explicit soft/hard ceiling:
- **Soft ceiling** at 0.80 × `max_tokens` → triggers compaction
- **Hard ceiling** at 1.0 × `max_tokens` → compaction must succeed or the call fails

**Why:** Every surveyed project converges on ~0.80. Claude Code's 0.95 is too late (users report the model losing attention to early turns before the trigger fires — issue #28728). Cline's 0.80 is the consensus default. We currently use 1.0 (the full window), which means compaction only fires when we're already overflowing.

**Where:**
- `agent/runtime.py:_compute_model_max()` (line 1468) — return both soft and hard ceilings
- `agent/runtime.py:1616-1618` — trigger trim at soft ceiling, not hard

**Concrete change:**
```python
# runtime.py — new helper
def _compute_compaction_threshold(self, conv: Conversation) -> tuple[int, int]:
    """Return (soft_ceiling, hard_ceiling) for context compaction."""
    model_max = self._compute_model_max(conv)
    soft = int(model_max * 0.80)
    hard = model_max
    return soft, hard

# runtime.py:1616 — use soft ceiling as the trim trigger
soft, hard = self._compute_compaction_threshold(conv)
conv.trim_to_token_limit(soft)  # was: model_max (hard)
```

**Risk:** Low. Changes a calculation, not control flow. User-visible effect: compaction happens earlier, which is the desired behavior.

**Tests:** Existing `TestConversationTrim` should pass unchanged (it tests trim against a passed limit, not against `_compute_model_max`). Add a new test verifying the 0.80 multiplier.

**Make it configurable:** Add `compaction_threshold: float = 0.80` to provider config or a global setting. Users with 1M-context models may want 0.90.

---

### ━━━ Priority 2: `keep_first` Invariant ━━━

**What:** The first N messages (system prompt + first user message) are never trimmed, even if the budget demands it. Default `keep_first = 2`.

**Why:** OpenHands' `keep_first: 2` is the only invariant that prevents the agent from losing its identity or the user's original request. Without it, a long conversation could trim away the initial task description, leaving the agent amnesiac about what it was asked to do.

**Where:**
- `models/conversation.py:trim_to_token_limit()` (line 365) — add `keep_first` parameter
- The function already preserves the system prompt (stored separately), so this protects the *first user message* specifically.

**Concrete change:**
```python
def trim_to_token_limit(self, max_tokens: int, keep_first: int = 2) -> None:
    # ... existing logic ...
    # In the trim loop, never pop index < keep_first
    while self.get_token_estimate() > max_tokens and len(self.messages) > keep_first + tail_preserve:
        # ... existing removal logic, but guarded ...
        # Fallback: only pop(0) if len > keep_first + tail_preserve
```

**Risk:** Low. This is purely defensive — it constrains the trim, never loosens it. Worst case: if the conversation is genuinely too large even with `keep_first`, the trim loop exits and the LLM call may fail with `context_length_exceeded`. That's the correct failure mode (better than silently dropping the task).

**Tests:** Add a test with a tiny max_tokens and verify the first 2 messages survive.

---

### ━━━ Priority 3: Protected Message Types ━━━

**What:** Add a `protected_types` set to the trim policy. Messages matching these types are pruned last, only if the budget demands it.

**Why:** OpenCode's `PRUNE_PROTECTED_TOOLS = ["skill"]` recognizes that some messages are more valuable than others. For CrabCakes:
- Messages with `is_summary=True` should be protected (they're already compressed; removing them loses both the original AND the summary)
- Messages containing agent capability descriptions (skill outputs) should be protected

**Where:**
- `models/conversation.py:trim_to_token_limit()` — add protected-type logic
- Define a `TrimPolicy` dataclass to bundle `keep_first`, `tail_preserve`, and `protected_types`

**Concrete change:**
```python
@dataclass
class TrimPolicy:
    max_tokens: int
    keep_first: int = 2
    tail_preserve: int = 4
    protected_is_summary: bool = True  # don't trim summary messages first

# In trim_to_token_limit, before the fallback pop(0):
#   Try non-protected messages first; only touch protected if nothing else is left
```

**Risk:** Low. Changes the eviction order, not the eviction semantics. Messages that were previously trimmed might survive longer (better context fidelity).

**Tests:** Add a test with summary messages and verify they're trimmed last.

---

### ━━━ Priority 4: Backwards-Walk Tool Output Pruning ━━━

**What:** Before the expensive LLM-based summarization, run a cheap pass that marks old tool outputs as compacted (replaced with a short stub). Walk backward from the newest message, accumulate tool-output tokens, and stop when you've freed enough budget.

**Why:** OpenCode's two-layer approach is the best design in the survey:
1. **Layer 1 (cheap, no LLM):** Replace old tool outputs with 2K-char stubs. A session of mostly tool calls stays 100% accurate forever — no LLM cost, no fidelity loss.
2. **Layer 2 (expensive, LLM):** Only runs when Layer 1 didn't free enough.

CrabCakes currently has only Layer 2 (delete + summarize). Adding Layer 1 means most compaction events become free and lossless.

**Where:**
- New method: `Conversation.prune_tool_outputs(max_tokens, protect_recent_turns=2)`
- Called *before* `trim_to_token_limit()` in the runtime loop
- Tool result messages older than the protected turns get their content truncated to a stub: `"[tool result compacted — {N} chars removed]"`

**Concrete change:**
```python
def prune_tool_outputs(self, target_tokens: int, protect_turns: int = 2) -> int:
    """Cheap pass: stub old tool results. Returns tokens freed."""
    if self.get_token_estimate() <= target_tokens:
        return 0
    freed = 0
    # Walk backward from end, skipping protect_turns most recent turns
    # For each TOOL_RESULT older than that:
    #   Save original content (for potential restore)
    #   Replace with stub
    #   Accumulate freed tokens
    # Stop when get_token_estimate() <= target_tokens
    return freed
```

**Risk:** Medium. We're mutating message content, which affects the conversation transcript. Need to:
- Store original content for audit/debugging (not in the message — in a side log)
- Ensure the stub is clearly marked so the model knows data was removed
- Respect the CB-6 pairing invariant (don't stub a tool result without also considering its parent assistant message)

**Tests:**
- Test that tool outputs are stubbed in order (oldest first)
- Test that the protected recent turns are untouched
- Test that token estimate drops below target after pruning
- Test that a re-run is a no-op (idempotence — already-stubbed messages aren't re-processed)

---

### ━━━ Priority 5: Head/Tail Split with Role Anchoring ━━━

**What:** When the cheap prune (P4) isn't enough and we need LLM summarization, use Aider's head/tail split:
1. Walk backward from the end, accumulating tokens, until you've used half the budget → that's the **tail** (kept verbatim)
2. Everything before that is the **head** (summarized)
3. Ensure the split point falls on an assistant message boundary (not a user message)

**Why:** Aider's `while messages[split_index - 1]["role"] != "assistant"` is a small detail with a large effect: it prevents the LLM from being asked to "continue" a conversation that ends on a user turn, which confuses the model.

**Where:**
- `models/conversation.py` — refactor `trim_to_token_limit()` + `_last_exchange_summary()` to coordinate:
  1. Try cheap prune (P4)
  2. If still over budget, find the split point
  3. Summarize the head
  4. Glue: `[head_summary] + [tail_verbatim]`

**Concrete change:**
```python
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

**Risk:** Medium. Changes the structure of the message list after trim. Must preserve:
- CB-6 pairing invariant (don't split an assistant+tool_call from its tool_result)
- The `is_summary=True` flag on the injected summary message

**Tests:**
- Test that split index lands on an assistant message boundary
- Test that tool_call/tool_result pairs are never split
- Test that the summary + tail fits within budget
- Test that head/tail compaction is idempotent on re-run

---

### ━━━ Priority 6: Hard Context Reset Fallback ━━━

**What:** When the LLM summarization (P5) produces a summary that itself exceeds the budget, retry with progressively smaller event sizes. Each retry drops the largest 20% of events from the head. After 5 retries, return a minimal stub.

**Why:** OpenHands' `hard_context_reset` with `context_scaling = 0.8` handles pathological conversations — one giant tool result that makes the head un-summarizable. Without this fallback, CrabCakes silently skips the summary (current behavior: `return` if `summary_tokens + current_tokens > max_tokens`), leaving the model with no context of what was removed.

**Where:**
- `models/conversation.py:trim_to_token_limit()` — the budget-check after summary generation (line ~451)
- Replace the current `return` (skip injection) with a retry loop

**Concrete change:**
```python
# Current (line ~451):
#   if current_tokens + summary_tokens > max_tokens:
#       return  # skip injection
# New:
if current_tokens + summary_tokens > max_tokens:
    # Hard reset: progressively truncate the head before summarizing
    for attempt in range(5):
        head = self._scale_head_messages(0.8 ** attempt)
        summary = self._summarize_head(head)
        if len(summary) // 4 + current_tokens <= max_tokens:
            break
    else:
        summary = "[Context reset — earlier conversation was too large to summarize]"
    # Inject whatever summary we got (even the stub)
```

**Risk:** Low. The fallback is bounded (max 5 retries) and only fires when the current code would have given up entirely. Worst case: the stub message, which is strictly better than no message.

**Tests:**
- Test with a synthetic 500K-char tool result that can't be summarized in one pass
- Verify the retry loop reduces the head each iteration
- Verify the final fallback stub is injected

---

### ━━━ Priority 7: Dynamic Budget Fraction ━━━

**What:** After template composition, measure the actual template size. If templates + bug journal + rules already consume most of the 15% budget, increase the budget fraction dynamically.

**Why:** The fixed 15% budget only caps file context. If templates + bug journal + rules consume 14% of a 128K window, only 1% remains for file context. The system should adapt: `budget_fraction = max(0.15, 0.25 - template_fraction)`.

**Where:**
- `utils/prompt_loader.py:_apply_system_prompt_budget()` (line 392)
- After measuring template tokens, compute the dynamic fraction

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

**Risk:** Low. The change gives *more* room for file context, never less. The cap at 0.25 prevents the system prompt from eating the entire conversation budget.

**Tests:** Test that a large template (bug journal with 50 entries) triggers a higher budget fraction.

---

### Deferred / Out of Scope

| Item | Why Deferred |
|------|-------------|
| **Async summarization** (Aider pattern) | High risk — requires changing the runtime's threading model. Defer until P1-P6 are stable. |
| **Pluggable condenser protocol** (OpenHands pattern) | Overkill for now. We have one strategy; build the abstraction when users request alternatives. |
| **KV cache for static prompts** | Requires provider-level support. Not actionable at the application layer yet. |
| **Semantic file partial reads** (Context-Engine-AI) | Needs tree-sitter or MCP integration. High effort, separate epic. |
| **Multi-agent context coordination** | Only matters when N agents work simultaneously. Un solved problem across the industry. |
| **Repo map / PageRank** (Aider) | Prompt-enrichment feature, not context management. Separate concern. |
| **Dream consolidation completion** (SPEC-4) | Process improvement, not context engineering. Track separately. |

---

## 5. Cross-Cutting Invariants

These must be preserved across ALL priorities. Violating any of them is a correctness bug.

### 5.1 The CB-6 Pairing Invariant

Every `TOOL_RESULT` message's `tool_call_id` must appear in some `ASSISTANT` message's `tool_calls[].id`. If you remove an assistant message with tool_calls, you MUST also remove the corresponding tool_result messages. If you stub a tool_result, the parent assistant message's tool_calls must still reference the same ID.

**Affected priorities:** P3, P4, P5

### 5.2 The `is_summary` Flag

`ChatMessage.is_summary: bool = False` (conversation.py:124) marks injected summaries. This is CrabCakes-specific — none of the surveyed projects have it. Preserve it: any injected summary from P5 or P6 must set `is_summary=True`.

**Affected priorities:** P5, P6

### 5.3 System Prompt Separation

The system prompt is stored separately from `messages[]` in `Conversation`. It is never trimmed. The `trim_to_token_limit()` function only operates on `self.messages`. This must remain true — the system prompt is the agent's identity and must survive all compaction.

**Affected priorities:** All

### 5.4 Token Cache Invalidation

The `_token_estimate_cache` on `Conversation` is keyed on `(len(messages), hash(system_prompt))`. Any mutation to `self.messages` (add, remove, reorder, stub) MUST invalidate this cache by setting `self._token_estimate_cache = None`. The existing code does this at the top of `trim_to_token_limit()` — any new methods that mutate messages must do the same.

**Affected priorities:** P4, P5

---

## 6. What We Explicitly Won't Do

| Pattern | Source | Why Not |
|---------|--------|---------|
| Summary injected as user turn | Claude Code | Loses ability to distinguish real user turns from summary turns. We have `is_summary=True` — preserve it. |
| PageRank-based repo map | Aider | Prompt enrichment, not context management. Separate concern. |
| Hardcoded prune constants | OpenCode (`PRUNE_PROTECT=40000`) | Issue #21208 shows these are wrong for 1M-context models. Make everything config-driven. |
| Same-model summarization | Claude Code | Using the session's expensive model (e.g., Opus) for "what happened so far?" is wasteful. Use a cheaper model or local LLM. |
| Per-model token windows doc page | Cline | Useful but a docs task, not a code task. |

---

## 7. Metrics

Track these when the changes ship:

| Metric | Why | Target |
|--------|-----|--------|
| API cost per task | Headline win from compaction | -30% to -50% |
| Tokens per LLM call | Direct measure of context reduction | 50% reduction at 80% trigger |
| `context_length_exceeded` errors / 100 turns | Reliability | 0 |
| `tool_call_id` pairing violations / 100 turns | CB-6 correctness | 0 (already enforced) |
| Compaction events that use cheap prune (P4) vs LLM (P5) | Layer-1 effectiveness | >70% resolved by cheap prune |
| User-visible "context used" percentage | UX transparency | Always shown in conversation UI |

---

## 8. Appendix: Code References

### Current Implementation

| Component | File | Line(s) | Notes |
|-----------|------|---------|-------|
| System prompt composition | `utils/prompt_loader.py` | 349-395 | Budget fraction, smart truncation |
| File context builder | `agent/context.py` | 289-343 | 50K char cap, core files at end |
| Token estimation (tiktoken) | `models/conversation.py` | 20-60, 271-299 | Cached on (len, hash) |
| Token breakdown | `models/conversation.py` | 323-360 | Per-turn observability |
| Trim function | `models/conversation.py` | 365-456 | Forward walk, tail_preserve=4 |
| Summary-on-trim | `models/conversation.py` | 454-456 | `is_summary=True`, budget-aware |
| `_last_exchange_summary()` | `models/conversation.py` | 458-503 | Brief recap of trimmed messages |
| `_compute_model_max()` | `agent/runtime.py` | 1468-1506 | No trigger percentage |
| Trim call site | `agent/runtime.py` | 1616-1618 | `conv.trim_to_token_limit(model_max)` |
| `MAX_EXEC_OUTPUT` | `agent/tools.py` | 101 | 100KB byte-cap (already correct) |
| `ChatMessage.is_summary` | `models/conversation.py` | 124 | CrabCakes-specific |
| `_token_estimate_cache` | `models/conversation.py` | 166 | Must invalidate on any mutation |

### External Project References

| Project | Best Pattern to Adopt | Reference |
|---------|----------------------|-----------|
| **OpenCode** | Backwards-walk prune + LLM summarize (two layers) | `compaction.ts`, `PRUNE_PROTECT=40000` |
| **OpenHands** | `keep_first` invariant, `hard_context_reset` fallback, pluggable condenser | `llm_summarizing_condenser.py`, `condenser/base.py` |
| **Aider** | Head/tail split with role anchoring, async summarization | `history.py:33` (`summarize_real()`) |
| **Cline** | 0.80 trigger, comprehensive summary prompt | `auto-compact` docs, discussion #3248 |
| **Claude Code** | Manual `/compact` command UX | Issue #28728 (threshold too late at 0.95) |

---

**Bottom line:** CrabCakes has a strong foundation — budget-aware prompting, tiktoken caching, smart truncation, and the `is_summary` flag are things most projects don't have. The critical gap is that we trim too late (at 1.0, not 0.80) and too destructively (delete, not compact). Priorities 1-3 are low-effort, high-impact changes that close the gap with the best open-source agents. Priority 4 (backwards-walk prune) is the architectural upgrade that makes most compaction events free and lossless.
