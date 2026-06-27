# PROPOSAL: Pluggable Context Management Strategy — Extract Compaction Logic into a Swappable Module

**Date:** 2026-06-26
**Author:** Qaster (supervisor)
**Status:** Draft — awaiting captain review
**Severity:** MEDIUM — architectural refactor that enables rapid iteration on context management. Not urgent, but doing it now (before implementing the Context Management Roadmap) saves a painful extraction later and delivers pluggability from day one.

**Related proposals:**
- `docs/proposals/PROPOSAL-context-management-roadmap.md` (2026-06-25, awaiting review — P1-P7 compaction improvements)
- `docs/proposals/PROPOSAL-context-bloat-fix.md` (2026-06-16, SHIPPED — CB-1 through CB-5)

**Architecture alignment:** This proposal modifies components documented in ARCHITECTURE.md §3.21l (`models/conversation.py`), §3.21m (`agent/runtime.py`), and §3.21o (`agent/config.py`). All changes respect the layering rules in §2: `models/` has no UI dependencies, `agent/` has no UI dependencies, no new cross-layer imports are introduced. The new `agent/context_strategy.py` module lives in the `agent/` layer and imports from `models/` only.

---

## 1. Executive Summary

CrabCakes' context management logic — `trim_to_token_limit()`, `_last_exchange_summary()`, and the six new methods proposed by the Context Management Roadmap (P1-P7) — currently lives as instance methods on the `Conversation` dataclass in `models/conversation.py`. This creates two problems:

1. **Strategy logic is embedded inside the data structure it operates on.** `Conversation` is a pure-data dataclass (per ARCHITECTURE.md §3.21l: "no UI, no network, no LLM calls — stdlib imports only"). Compaction strategy — decisions about *what* to remove, *when* to summarize, *how* to prioritize messages — is policy logic, not data logic. The upcoming Context Management Roadmap would deepen this coupling by adding ~150 lines of strategy methods (`prune_tool_outputs()`, `_select_prune_candidate()`, `_fit_summary()`, `_find_split_index()`, `TrimPolicy`) directly onto the data model.

2. **Swapping strategies is impossible without surgery.** Context management is an actively evolving field. LangChain's Deep Agents SDK, Google ADK, Microsoft Agent Framework, and OpenHands all use different compaction approaches (filesystem offload, LLM summarization, sliding window, token-based triggers). If we want to experiment with an alternative strategy — say, LLM-based summarization instead of delete-and-stub — we would need to extract the logic from `Conversation` first, then reimplement. That's a high-friction rewrite, not a swap.

**This proposal recommends extracting context management into a pluggable strategy module** *before* implementing the Context Management Roadmap. The extraction is small (~60 lines of existing code move from `Conversation` to a new `DefaultContextStrategy` class), the call-site change is minimal (one line in `agent/runtime.py`), and the result is a clean `ContextStrategy` protocol that makes future strategy swaps trivial.

The Context Management Roadmap (P1-P7) would then be implemented *inside* `DefaultContextStrategy` rather than on `Conversation`, with the spec updated to reflect the new method signatures. The algorithms are identical; only the host class changes.

---

## 2. Problem Statement

### 2.1 The Coupling Problem

**Current architecture:**

```
models/conversation.py
├── Conversation (dataclass — pure data)
│   ├── messages: list[Message]          # data
│   ├── system_prompt: str               # data
│   ├── model: str                       # data
│   ├── _token_estimate_cache            # data
│   ├── add_user_message()               # data mutation (append)
│   ├── add_assistant_message()          # data mutation (append)
│   ├── add_tool_result()                # data mutation (append)
│   ├── to_api_messages()                # data serialization
│   ├── get_token_estimate()             # data computation
│   ├── get_token_breakdown()            # data computation
│   ├── trim_to_token_limit()            # ← STRATEGY LOGIC (policy decisions)
│   └── _last_exchange_summary()         # ← STRATEGY LOGIC (summary generation)
```

`Conversation` is defined in ARCHITECTURE.md §3.21l as "pure data — no UI, no network, no LLM calls." The trim and summary methods violate this contract in spirit: they make policy decisions about which messages to evict, what to summarize, and in what order. These are strategy decisions, not data operations.

The upcoming Context Management Roadmap proposal makes this worse. It adds six new methods to `Conversation`:

| Method | Purpose | Lines (est.) |
|--------|---------|-------------|
| `prune_tool_outputs()` | Backwards-walk tool output stubbing (P4) | ~40 |
| `_select_prune_candidate()` | Protected-message-aware eviction selection (P2/P3) | ~25 |
| `_fit_summary()` | Geometric-retry summary fitting (P6) | ~30 |
| `_find_split_index()` | Role-anchored head/tail split for summarization (P5) | ~20 |
| `TrimPolicy` (dataclass) | Bundles trim parameters | ~10 |
| Modified `trim_to_token_limit()` | Accepts `keep_first`, `TrimPolicy` | +~25 |

That's ~150 additional lines of strategy logic on a data class.

### 2.2 The Experimentation Problem

Context management is the most actively researched area in agent design. The landscape as of mid-2026:

| Framework | Strategy | Pluggable? |
|-----------|----------|------------|
| **Microsoft Agent Framework** | `CompactionStrategy` abstract class with `summarize()` — token-based or sliding-window | ✅ Explicit strategy pattern |
| **Google ADK** | `EventsCompactionConfig` — token-based or turn-based, configurable thresholds | ✅ Config-driven selection |
| **LangChain Deep Agents** | Three-layer pipeline: offload tool results → offload tool inputs → LLM summarize | ⚠️ Modular but not user-pluggable |
| **OpenHands** | `Condenser` protocol — multiple implementations (recent, observation, llm) | ✅ Protocol-based |
| **Aider** | Single hardcoded approach (repo-map + tag compression) | ❌ |
| **CrabCakes (current)** | Delete-oldest with summary injection, embedded in `Conversation` | ❌ |

If CrabCakes wants to try a different approach — say, OpenHands-style LLM summarization, or LangChain-style filesystem offload — the current architecture requires:

1. Writing the new strategy as methods on `Conversation` (or monkey-patching it)
2. Adding config flags to switch between strategies
3. Maintaining two code paths in the same data class

This is not "write a module and swap it in." This is "rearchitect the data class every time."

### 2.3 The "Why Now" Problem

The Context Management Roadmap is about to be implemented. If we implement it as-is:

- `Conversation` gains ~150 lines of strategy logic, deepening the coupling.
- Future extraction becomes a refactor of ~210 lines (60 existing + 150 new) instead of ~60 lines.
- The extraction must happen *simultaneously* with writing the new strategy — that's where bugs hide.
- Tests written against `Conversation.trim_to_token_limit()` (existing + new) must be rewritten to call `strategy.compact(conv, ...)`.

If we extract first:

- We move ~60 lines today, when the test suite is stable and the call-site is singular.
- The roadmap spec is updated to target `DefaultContextStrategy.compact()` instead of `Conversation.trim_to_token_limit()`. Algorithms don't change.
- Tests are written against the strategy interface from the start.
- When we want a new strategy, we implement the protocol and swap. No extraction needed.

**The cost of waiting is high; the cost of acting now is low.** See §6 (Cost-Benefit Analysis).

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. **Define a `ContextStrategy` protocol** with a single `compact()` entry point that any context management strategy can implement.
2. **Extract existing trim/summary logic** from `Conversation` into a `DefaultContextStrategy` class in a new `agent/context_strategy.py` module.
3. **Preserve backward compatibility** — `Conversation.trim_to_token_limit()` remains as a thin delegation shim so existing tests and any external callers continue to work without modification.
4. **Wire the strategy into `AgentRuntime`** via `AgentConfig` so the strategy can be configured per-agent or globally.
5. **Update the Context Management Roadmap spec** to target `DefaultContextStrategy` instead of `Conversation` methods, so P1-P7 are implemented in the strategy module from the start.
6. **Preserve all existing invariants**: CB-6 tool-call pairing, `is_summary` flag, system prompt separation, token cache invalidation.

### 3.2 Non-Goals

- **Implementing new strategies** (LLM summarization, filesystem offload, sliding window) — this proposal only creates the *plug*. New strategies are separate future work.
- **Implementing the Context Management Roadmap (P1-P7)** — that's the existing spec. This proposal only changes *where* P1-P7 are implemented (strategy module instead of data class).
- **Changing the compaction algorithm** — the `DefaultContextStrategy` behaves identically to the current `Conversation.trim_to_token_limit()`. Same logic, same outputs, same tests passing.
- **Async compaction** — the strategy protocol is synchronous. Async is a future enhancement.
- **Multi-strategy pipelines** (Layer 1 → Layer 2 → Layer 3) — the protocol supports this (a strategy can internally chain), but we're not building composition tooling now.

---

## 4. Proposed Architecture

### 4.1 New Module: `agent/context_strategy.py`

A new file in the `agent/` layer (no UI imports, imports from `models/` only):

```python
# agent/context_strategy.py
# Pluggable context management strategy.
#
# Architecture: lives in agent/ layer. Imports from models/ only.
# No UI, no network, no LLM calls.

from __future__ import annotations
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from models.conversation import Conversation


class ContextStrategy(Protocol):
    """Protocol for context management strategies.
    
    A strategy is responsible for compacting a conversation to fit
    within a token budget. The strategy mutates conv.messages in-place.
    
    Contract:
    - Must invalidate conv._token_estimate_cache after any mutation.
    - Must preserve CB-6 tool-call pairing invariant (TOOL_RESULT +
      ASSISTANT-with-tool_calls removed/stubbed as a unit).
    - Must be idempotent: calling compact() on an already-compacted
      conversation is a no-op.
    - Must not remove the system prompt (stored separately in
      conv.system_prompt, never in conv.messages).
    """

    def compact(self, conv: "Conversation", token_budget: int) -> None:
        """Compact conv to fit within token_budget tokens.
        
        Mutates conv.messages in-place. Called by the runtime before
        each LLM call when the conversation exceeds the budget.
        
        Args:
            conv: The conversation to compact.
            token_budget: Maximum token count for the conversation
                (excluding system prompt). The strategy should ensure
                conv.get_token_estimate() <= token_budget after return.
        """
        ...


class DefaultContextStrategy:
    """Default context management strategy.
    
    Implements the current CrabCakes compaction algorithm:
    1. Remove oldest messages (TOOL_RESULT + ASSISTANT pairs first,
       then individual messages) until under budget.
    2. Preserve the last 4 messages (tail_preserve).
    3. Inject a summary of removed user messages as an assistant
       message with is_summary=True, if budget allows.
    
    This is the existing logic from Conversation.trim_to_token_limit()
    and Conversation._last_exchange_summary(), extracted verbatim
    with `self` → `conv`.
    """

    def compact(self, conv: "Conversation", token_budget: int) -> None:
        conv.trim_to_token_limit(token_budget)  # delegation shim (Step 0)

    @property
    def last_result(self) -> "CompactionEvent | None":
        """Telemetry from the most recent compact() call.
        
        The strategy records what happened (messages removed, tokens freed,
        summary injected, etc.) and exposes it here. The runtime reads this
        after each call to update its event history (see §4.5).
        
        Returns None before the first compact() call.
        """
        return getattr(self, "_last_result", None)
```

**Why a Protocol, not an ABC?** Python's `Protocol` (PEP 544) supports structural typing — any class with a matching `compact()` method satisfies the protocol, no inheritance required. This means third-party strategies don't need to import our base class. An ABC would require explicit inheritance, adding a coupling point for no benefit. We follow the same pattern CrabCakes uses for tool result callbacks (structural `Callable` typing, not ABC inheritance).

**Why not a dataclass method?** The strategy holds no per-instance state — it's pure behavior parameterized by the conversation it receives. A free-standing class (or even module-level functions) is the simplest representation. Making it a class (rather than bare functions) allows future strategies to hold configuration (e.g., an LLM summarization strategy might hold an API client).

### 4.2 Conversation Changes (Minimal)

`models/conversation.py` keeps all data operations. The strategy methods remain as **delegation shims** for backward compatibility:

```python
# models/conversation.py — unchanged data operations
class Conversation:
    # ... data fields unchanged ...
    
    def add_user_message(self, content) -> Message: ...      # unchanged
    def add_assistant_message(self, ...) -> Message: ...      # unchanged
    def add_tool_result(self, ...) -> Message: ...            # unchanged
    def to_api_messages(self) -> list[dict]: ...              # unchanged
    def get_token_estimate(self) -> int: ...                  # unchanged
    def get_token_breakdown(self, ...) -> dict: ...           # unchanged
    
    # --- Strategy delegation shims (backward compatibility) ---
    
    def trim_to_token_limit(self, max_tokens: int) -> None:
        """DEPRECATED: Use ContextStrategy.compact() instead.
        
        Delegates to DefaultContextStrategy for backward compatibility.
        Will be removed in a future version.
        """
        from agent.context_strategy import DefaultContextStrategy
        DefaultContextStrategy().compact(self, max_tokens)
    
    def _last_exchange_summary(self) -> str:
        """DEPRECATED: Moved to DefaultContextStrategy._summary()."""
        from agent.context_strategy import DefaultContextStrategy
        return DefaultContextStrategy._summary(self)
```

**After the roadmap spec is implemented**, the shim's body is replaced with a call to the full P1-P7 strategy. Eventually the shim is removed and all callers use the strategy directly.

### 4.3 Runtime Changes (One Line)

`agent/runtime.py` line 1618 changes from:

```python
conv.trim_to_token_limit(model_max)
```

to:

```python
self._context_strategy.compact(conv, soft_ceiling)
```

where `self._context_strategy` is set in `AgentRuntime.__init__()` from `AgentConfig`.

### 4.4 Config Wiring (AgentConfig AND ProviderConfig)

`AgentConfig` (in `agent/config.py`) **and** `ProviderConfig` (in `models/providers.py`) both gain the field, with full YAML round-trip persistence via `utils/providers_store.py`:

```python
# agent/config.py
@dataclass
class AgentConfig:
    # ... existing fields ...
    context_strategy: str = "default"  # strategy name or dotted class path

# models/providers.py
@dataclass
class ProviderConfig:
    # ... existing fields (incl. compaction_threshold from P1) ...
    context_strategy: str = "default"
```

```python
# utils/providers_store.py — round-trip additions
def _to_dict(config: ProviderConfig) -> dict:
    return {
        # ... existing fields ...
        "context_strategy": config.context_strategy,
    }

def _from_dict(data: dict) -> ProviderConfig:
    return ProviderConfig(
        # ... existing fields ...
        context_strategy=data.get("context_strategy", "default"),
    )
```

`AgentRuntime.__init__()` resolves the strategy:

```python
# agent/runtime.py — in __init__
from agent.context_strategy import DefaultContextStrategy

strategy_map = {
    "default": DefaultContextStrategy,
    # Future: "llm-summarize": LLMSummaryStrategy,
    # Future: "sliding-window": SlidingWindowStrategy,
}
self._context_strategy = strategy_map.get(
    config.context_strategy, DefaultContextStrategy
)()
```

**Why both configs (not AgentConfig only):** `ProviderConfig` already round-trips through `_to_dict/_from_dict` for `compaction_threshold` (added by P1). Adding `context_strategy` to `AgentConfig` only would create config-drift — operators couldn't `grep providers.yaml` for it, and any future YAML-exposed knob would need a third config layer. Putting the persistence plumbing in now means exposing it in YAML later is a one-PR change, not three.

**YAML exposure is a follow-up decision.** The field defaults to `"default"` and is optional. When we add alternative strategies, we can document the knob in providers.yaml — but the storage path is in place from day one.

### 4.5 Telemetry: `last_result: CompactionEvent`

The Context Management Roadmap spec (`SPEC-CONTEXT-MANAGEMENT-ROADMAP.md` §2.8) introduces a 14-field `CompactionEvent` dataclass for SPEC-4 dream consolidation and operator debugging. The runtime currently tracks a scalar `self._last_trim_removed: int` (`agent/runtime.py:1232`, set at `:1620`, read at `:1664-1666`) — insufficient for the rich telemetry §2.8 requires.

**Approach:** the strategy exposes its result via a `last_result` attribute rather than a return value. The runtime reads it after each `compact()` call:

```python
# agent/context_strategy.py
from dataclasses import dataclass, field

@dataclass
class CompactionEvent:
    turn: int
    trigger: str  # "prune" | "trim" | "summary_injected" | "output_byte_truncated" | "reset"
    layer: int    # 1=prune_tool_outputs (P4), 2=trim (P2/P3/P6), 3=manual, 4=hard_reset
    messages_before: int
    messages_after: int
    messages_removed: int
    tokens_before: int
    tokens_after: int
    tokens_freed: int
    summary_tokens_injected: int
    soft_ceiling: int
    hard_ceiling: int
    provider: str
    model: str

class DefaultContextStrategy:
    def __init__(self) -> None:
        self._last_result: CompactionEvent | None = None
    
    def compact(self, conv: "Conversation", token_budget: int) -> None:
        # ... existing logic, but at the end:
        self._last_result = CompactionEvent(
            turn=conv.current_turn,
            trigger="trim",
            layer="trim",
            messages_before=before_count,
            messages_after=after_count,
            messages_removed=before_count - after_count,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            tokens_freed=before_tokens - after_tokens,
            summary_tokens_injected=summary_tokens,
            soft_ceiling=token_budget,
            hard_ceiling=token_budget,  # P1 distinguishes these; for now equal
            provider=conv.provider,
            model=conv.model,
        )
        # ... then delegate to conv.trim_to_token_limit for Step 0.
    
    @property
    def last_result(self) -> CompactionEvent | None:
        return self._last_result
```

**Runtime integration (`agent/runtime.py:1618`):**

```python
# Before (current):
conv.trim_to_token_limit(model_max)
self._last_trim_removed = before - len(conv.messages)

# After (this proposal + spec §2.8):
self._context_strategy.compact(conv, soft_ceiling)
if self._context_strategy.last_result is not None:
    self._compaction_events.append(self._context_strategy.last_result)
    if len(self._compaction_events) > 100:
        self._compaction_events = self._compaction_events[-100:]
```

**Why `last_result` (not a return value):** keeps the `ContextStrategy` protocol stable as telemetry evolves. New fields can be added to `CompactionEvent` without changing the `compact()` signature. Strategies that don't care about telemetry (e.g., a future no-op passthrough strategy) can leave `last_result` as None.

**Why the strategy records telemetry (not the runtime):** the strategy already has all the data — `before_count`, `after_count`, `summary_tokens`. Reconstructing them at the runtime call site means duplicating logic and risking drift. The strategy is the single source of truth for what happened during compaction.

### 4.6 Wiring: P1↔P7 Dependency

The runtime computes the token budget using TWO spec features and passes the result to `strategy.compact()`:

```python
# agent/runtime.py — in the tool loop, around line 1618

# P7: dynamic system-prompt budget (utils/prompt_loader.py)
prompt_budget = _apply_system_prompt_budget(
    template_tokens=template_tokens,
    model_max_tokens=model_max,
)

# P1: soft ceiling at 80% of remaining context
remaining = model_max - prompt_budget
soft_ceiling = int(remaining * 0.80)
hard_ceiling = remaining

# Hand the result to the strategy. The strategy doesn't need to
# know about P7 or the 80% rule — it just receives a number.
self._context_strategy.compact(conv, soft_ceiling)
```

**Why this wiring matters for the spec:** the roadmap spec's §2.4 (P7) and §2.2.1 (P1) are written independently. The strategy protocol receives a single `token_budget` argument — it has no knowledge of how that number was derived. This means:

- A future LLM-summarization strategy doesn't need to reimplement the 80% rule.
- A future sliding-window strategy doesn't need to reimplement the prompt budget.
- Strategies are composable: changing the budget policy (P7) doesn't require changing the strategy.

**Dependency direction:** `agent/runtime.py` → `utils/prompt_loader.py` (P7) → `models/conversation.py` (data) → `agent/context_strategy.py` (strategy). No cycles. The strategy is a leaf node.

### 4.7 File Inventory

| File | Change Type | Lines Changed (est.) |
|------|------------|---------------------|
| `agent/context_strategy.py` | **NEW** | ~80 (protocol + DefaultContextStrategy) |
| `models/conversation.py` | Modify — replace method bodies with delegation shims | ~15 (two method bodies shrink to 2-line shims) |
| `agent/runtime.py` | Modify — one call site + one init line | ~5 |
| `agent/config.py` | Modify — add one field | ~2 |
| `models/providers.py` | Modify — add one field | ~2 |
| `utils/providers_store.py` | Modify — round-trip the new field | ~4 (two `_to_dict`/`_from_dict` additions) |
| `tests/test_conversation.py` | No change needed (tests call `conv.trim_to_token_limit()` which still works via shim) | 0 |
| `tests/test_providers_store.py` | Add round-trip test for the new field | ~10 |
| `docs/ARCHITECTURE.md` | Add §3.21q for `agent/context_strategy.py` | ~20 |

**Total: ~125 lines of change, of which ~80 are new code.** No logic changes — pure structural refactor.

---

## 5. Implementation Plan

### Step 0: Extract Strategy from Conversation

**Scope:** Move `trim_to_token_limit()` AND `_last_exchange_summary()` logic from `Conversation` to `DefaultContextStrategy` **in a single extraction**.

**Prerequisite:** None. This is the first step.

**Why both at once:** `_last_exchange_summary()` will be replaced by P5 (head/tail split with role anchoring), but waiting to extract it then means a second extraction during P5. The shim is cheap; double-extraction is not.

**What moves:**

| Source (`models/conversation.py`) | Destination (`agent/context_strategy.py`) |
|-----------------------------------|------------------------------------------|
| `trim_to_token_limit()` body (lines 365-456) | `DefaultContextStrategy.compact()` body |
| `_last_exchange_summary()` body (lines 458-498) | `DefaultContextStrategy._summary()` static method |

**What stays on `Conversation`:**
- `messages`, `system_prompt`, `model`, `_token_estimate_cache` — data fields
- `add_user_message()`, `add_assistant_message()`, `add_tool_result()` — data mutation
- `to_api_messages()` — serialization
- `get_token_estimate()`, `_count_char_tokens()`, `get_token_breakdown()` — computation

**Transform:** Every `self.messages` → `conv.messages`, every `self._token_estimate_cache` → `conv._token_estimate_cache`, every `self.get_token_estimate()` → `conv.get_token_estimate()`. Mechanical search-and-replace.

**Verification:**
- All existing tests pass unchanged (they call `conv.trim_to_token_limit()` which delegates to the strategy).
- `TestConversationTrim` (4 tests), `TestTrimFallbackIncludesOldest` (3 tests), `TestTrimSummaryInjection` (7 tests) — all green.
- No new test files needed for Step 0 (the existing tests validate the extraction).

**Risk:** VERY LOW. The extracted code is identical to the original. The delegation shim ensures zero behavioral change. If the shim is wrong, existing tests catch it immediately.

### Step 1: Wire Strategy into Runtime and Config

**Scope:** Add `context_strategy` field to both `AgentConfig` and `ProviderConfig` (with `_to_dict`/`_from_dict` round-trip), resolve it in `AgentRuntime.__init__()`, use it in the tool loop.

**Changes:**
- `agent/config.py`: Add `context_strategy: str = "default"` to `AgentConfig`.
- `models/providers.py`: Add `context_strategy: str = "default"` to `ProviderConfig`.
- `utils/providers_store.py`: Update `_to_dict` and `_from_dict` to round-trip the field.
- `agent/runtime.py:__init__()`: Resolve strategy from config, store as `self._context_strategy`.
- `agent/runtime.py:1618`: Replace `conv.trim_to_token_limit(model_max)` with `self._context_strategy.compact(conv, soft_ceiling)` (where `soft_ceiling` comes from the roadmap's P1; for now it's `model_max` — the current behavior).

**Verification:**
- All runtime tests pass.
- Integration test: `send_message()` triggers compaction via the strategy, not via the conversation method.
- ProviderConfig round-trip test: load a YAML with a non-default `context_strategy`, verify it survives save+reload.

### Step 2: Update Context Management Roadmap Spec

**Scope:** Rewrite the spec's code samples to target `DefaultContextStrategy` instead of `Conversation`.

**What changes in the spec:**
- **New §0 (Strategy Architecture):** Define the `ContextStrategy` protocol, `DefaultContextStrategy` class, and the config registration mechanism. ~30-40 lines.
- **P1-P6 code samples:** Every method definition shifts from `Conversation.method(self, ...)` to `DefaultContextStrategy.method(self, conv, ...)`. Add `conv` as first parameter after `self`. Logic is identical.
- **P7 (prompt budget):** Unchanged — it touches `utils/prompt_loader.py`, not the strategy.
- **Implementation order:** Add "Step 0: Extract strategy from Conversation" (already done). The existing Batch A becomes Step 1.
- **Test plan:** New tests target `strategy.compact(conv, ...)` instead of `conv.trim_to_token_limit(...)`. Existing tests continue to validate via the delegation shim.
- **Scope table:** Add `agent/context_strategy.py` as a modified file. Remove `models/conversation.py` from the P4-P6 method additions (it only gains delegation shims, which already exist from Step 0).

**What does NOT change in the spec:**
- The P1-P7 algorithms, invariants, and audit findings.
- The test cases (same assertions, different call convention).
- The DISCOVERY section (line numbers still reference the current `Conversation` methods — the spec verifies against the codebase, and the shim preserves the API).

**Parameter rename — `max_tokens` → `token_budget`:** The protocol's `compact(conv, token_budget)` uses a different parameter name than `Conversation.trim_to_token_limit(max_tokens)`. The spec should rename for consistency:

- `trim_to_token_limit(max_tokens=N)` → `compact(conv, token_budget=N)`
- `get_token_breakdown(max_tokens=N)` stays unchanged (different method, different scope)
- New tests targeting the strategy use `token_budget`; existing tests using `max_tokens` via the shim continue to work

This is a mechanical rename in the spec's code samples. No test assertions change.

### Step 3: Update ARCHITECTURE.md

**Scope:** Add §3.21q for `agent/context_strategy.py` and update §3.21l to note the delegation shims.

**New §3.21q:**
```markdown
### 3.21q `agent/context_strategy.py` — Context Management Strategy (Phase CB-6)

**Responsibility:** Pluggable context compaction. Receives a Conversation
and a token budget, mutates the conversation in-place to fit.

**Public API:**
```python
class ContextStrategy(Protocol):
    def compact(self, conv: Conversation, token_budget: int) -> None: ...

class DefaultContextStrategy:
    def compact(self, conv: Conversation, token_budget: int) -> None: ...
```

**Rules:** Imports from `models/` only. No UI, no network, no LLM calls.
The default strategy replicates the pre-CB-6 `trim_to_token_limit()` behavior.
Alternative strategies are registered via `AgentConfig.context_strategy`.

**Existing invariants preserved:** CB-6 tool-call pairing, `is_summary` flag,
system prompt separation, token cache invalidation.
```

**Updated §3.21l note:**
```markdown
**CB-6 (strategy extraction):** `trim_to_token_limit()` and
`_last_exchange_summary()` are delegation shims that forward to
`DefaultContextStrategy` in `agent/context_strategy.py`. New context
management logic is implemented in the strategy module, not on
`Conversation`. The shims exist for backward compatibility with tests
and will be removed in a future version.
```

---

## 6. Cost-Benefit Analysis

### 6.1 Cost of Doing This Now (Before Roadmap Implementation)

| Item | Effort | Risk |
|------|--------|------|
| Create `agent/context_strategy.py` (~80 lines, mostly copy-paste) | 1 hour | Very low — identical logic |
| Add delegation shims to `Conversation` (~10 lines, both trim AND summary) | 15 min | Very low — one-line forwards |
| Wire `AgentConfig` + `ProviderConfig` + `providers_store.py` round-trip (~14 lines) | 45 min | Low — two new fields, one round-trip, one test |
| Wire `AgentRuntime` to use `self._context_strategy.compact()` | 15 min | Low — one call-site change |
| Run existing test suite to verify zero regressions | 15 min | None |
| Update roadmap spec code samples (mechanical `self` → `conv` transform + parameter rename + §0 Strategy Architecture section + `last_result` wiring) | 1.5 hours | Low — documentation only |
| Update ARCHITECTURE.md | 30 min | None |
| **Total** | **~4.5 hours** | **Very low** |

### 6.2 Cost of Doing This Later (After Roadmap Implementation)

| Item | Effort | Risk |
|------|--------|------|
| Extract ~210 lines (60 existing + 150 roadmap) from `Conversation` | 3 hours | Medium — more code to move, more test surface to update |
| Update ~20 test methods from `conv.trim_to_token_limit()` to `strategy.compact()` | 2 hours | Medium — risk of test breakage in the same PR as the refactor |
| Simultaneously write the new alternative strategy | 4+ hours | High — writing new logic + refactoring old logic in the same change |
| **Total** | **9+ hours** | **Medium-high** |

### 6.3 Cost of NOT Doing This At All

- Every future context management experiment requires either:
  - Monkey-patching `Conversation` methods (fragile, untestable)
  - Adding `if strategy == "X"` branches inside `Conversation` (god class growth)
  - Full rewrite of `Conversation` (high risk, high effort)
- CrabCakes falls behind Microsoft Agent Framework, Google ADK, and OpenHands — all of which have pluggable compaction as of 2026-Q1.
- The "pure data" contract on `Conversation` is permanently violated.

### 6.4 Benefit Summary

| Benefit | Impact |
|---------|--------|
| **Write a new strategy = write one class** | High — enables rapid experimentation |
| **Strategy logic is testable in isolation** | High — mock `Conversation`, test strategy decisions |
| **`Conversation` returns to pure data** | Medium — architectural cleanliness, easier onboarding |
| **Spec roadmap code samples are cleaner** | Medium — explicit boundaries between data and strategy |
| **Ahead of Aider, on par with MS/Google/OpenHands** | Low (cosmetic) — but signals engineering maturity |

---

## 7. Design Decisions

### 7.1 Why a Protocol, Not an ABC?

Python's `Protocol` (PEP 544) provides structural subtyping: any class with a compatible `compact()` method satisfies `ContextStrategy`, no inheritance required. This means:

- **Third-party strategies** don't need to import `agent.context_strategy` — they just implement `compact()`.
- **Testing** is easier — a mock with a `compact` attribute satisfies the protocol.
- **No `ABC` metaclass conflicts** — CrabCakes uses dataclasses extensively, and mixing `ABCMeta` with `@dataclass` can cause ordering issues.

An ABC would require explicit inheritance (`class MyStrategy(ContextStrategyBase):`), adding a dependency on our module for no functional benefit. The Protocol pattern is used elsewhere in the Python ecosystem for this exact use case (e.g., `collections.abc` → `typing.Protocol` migration in the standard library).

### 7.2 Why Not a Module-Level Function?

A bare function `def compact(conv, budget)` would work for the default strategy. But future strategies need configuration:

- **LLM summarization strategy** needs an API client (model, API key, prompt template).
- **Sliding window strategy** needs `window_size` and `overlap` parameters.
- **Hybrid strategy** needs references to sub-strategies.

A class with an `__init__` accommodates this naturally. A module-level function would require `functools.partial` or a config dict — both worse than a class for this use case.

### 7.3 Why `agent/` Layer and Not `models/`?

`ContextStrategy` imports `Conversation` from `models/`. If the strategy lived in `models/`, it would create a same-layer reference — not a cycle, but a tight coupling within the same module. Placing it in `agent/` follows the existing dependency direction (`agent/` → `models/`) and keeps `models/` pure data, as ARCHITECTURE.md §2 prescribes.

### 7.4 Why Not `utils/`?

`utils/` is for generic utilities (config paths, prompt loading, git wrappers). Context management strategy is core agent behavior — it decides what the agent remembers and forgets. It belongs in `agent/` alongside the runtime that invokes it.

### 7.5 Why Keep the Delegation Shims at All?

Three reasons:

1. **Test compatibility:** ~14 existing test methods call `conv.trim_to_token_limit()` directly. The shim lets them pass unchanged. Rewriting them all in the same PR as the extraction adds risk and review burden for zero behavioral benefit.
2. **External callers:** Any code outside CrabCakes that imports `Conversation` (unlikely but possible — shared libraries, notebooks) continues to work.
3. **Rollback safety:** If the strategy module has a bug, reverting to `conv.trim_to_token_limit()` (which calls the strategy) doesn't help — but reverting the *extraction* (removing the strategy module and restoring the original method bodies) is a clean `git revert` because the `Conversation` API never changed.

The shims are marked `# DEPRECATED` and will be removed once all internal callers use the strategy directly (after the roadmap spec is implemented and tests are migrated).

### 7.6 Why Not Implement the Roadmap Inside Conversation First, Then Extract?

This is the "implement first, refactor later" path. It's tempting because it doesn't require updating the spec. But:

1. **You're doing the extraction anyway.** The roadmap adds ~150 lines of strategy logic to `Conversation`. If you ever want pluggability (and you do — that's why we're having this conversation), you must extract those 150 lines later. Doing it now means extracting 60 lines. Doing it later means extracting 210 lines.

2. **Tests written against `Conversation` must be rewritten.** The roadmap spec defines ~14 new test methods (TestKeepFirst, TestProtectedSummary, TestTrimPolicyDataclass, TestCompactionThreshold, TestFitSummary, etc.) targeting `conv.trim_to_token_limit(...)`. If these are written against `Conversation` first, they must all be rewritten when the strategy is extracted. If they're written against `DefaultContextStrategy.compact()` from the start, no rewrite is needed.

3. **The spec update is mechanical.** Changing `self.messages` to `conv.messages` in code samples is a find-and-replace, not a design change. The algorithms, invariants, and audit findings are unaffected.

4. **"Later" means "never."** In practice, refactors that are deferred until "after the feature ships" rarely happen. The feature works, the tests pass, and the coupling becomes the status quo. Extracting now ensures the architecture is right from the start.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Extraction introduces a subtle bug (e.g., `self` vs `conv` miss) | Medium | Very low | Existing test suite (14 trim tests) catches any behavioral difference. The transform is mechanical. |
| Delegation shim adds import cycle (`conversation.py` → `agent/context_strategy.py` → `conversation.py`) | Medium | Low | Shim uses deferred import (`from agent.context_strategy import ...` inside the method body, not at module top). `context_strategy.py` uses `TYPE_CHECKING` for the `Conversation` type hint — no runtime import. |
| Future strategy needs access to private `Conversation` state not exposed publicly | Low | Low | `_token_estimate_cache` is already accessed by name in existing trim logic. Strategies operate on the public `messages` list and the semi-private cache. No new private access needed. |
| Protocol provides no enforcement — a strategy could violate CB-6 or forget cache invalidation | Medium | Medium | Document the contract clearly in the protocol docstring. Provide `validate_invariants()` as a future defensive measure. For now, the default strategy enforces all invariants, and any new strategy author must read the contract. |
| Spec update delays roadmap implementation | Low | Low | The spec update is ~1 hour of mechanical editing. It does not change algorithms or test cases. |

---

## 9. Relationship to the Context Management Roadmap

This proposal is a **prerequisite** to `PROPOSAL-context-management-roadmap.md`. It does not replace or compete with it. The relationship is:

```
This proposal (pluggable strategy)
    ↓ enables
Roadmap proposal (P1-P7 improvements)
    ↓ implemented inside
DefaultContextStrategy (the plug)
    ↓ replaceable by
Future strategies (LLM summarize, sliding window, etc.)
```

**If this proposal is approved:**
1. Steps 0-1 are implemented first (strategy extraction + config wiring).
2. The roadmap spec is updated (Step 2) to target `DefaultContextStrategy`.
3. Roadmap implementation (P1-P7) proceeds as described in the roadmap spec, with code going into `agent/context_strategy.py` instead of `models/conversation.py`.

**If this proposal is NOT approved:**
- The roadmap spec is implemented as-is (P1-P7 methods on `Conversation`).
- Pluggability is deferred to a future refactor (§6.2 quantifies the cost).

---

## 10. Success Criteria

1. `agent/context_strategy.py` exists with a `ContextStrategy` protocol, `DefaultContextStrategy` class, and `last_result: CompactionEvent` attribute.
2. `Conversation.trim_to_token_limit()` AND `Conversation._last_exchange_summary()` delegate to `DefaultContextStrategy` via thin shims.
3. All 14 existing trim/summary tests pass without modification.
4. `AgentConfig.context_strategy` AND `ProviderConfig.context_strategy` fields exist, both default to `"default"`, and round-trip through `utils/providers_store.py::_to_dict/_from_dict`.
5. `agent/runtime.py` calls `self._context_strategy.compact(conv, soft_ceiling)` instead of `conv.trim_to_token_limit(model_max)` directly, and appends `strategy.last_result` to its event history.
6. `ARCHITECTURE.md` includes §3.21q for the new module.
7. The Context Management Roadmap spec is updated with §0 "Strategy Architecture" and references `DefaultContextStrategy` in all P1-P6 code samples.
8. A developer can write a new strategy by creating a class with a `compact(self, conv, token_budget)` method and registering it in the strategy map — no changes to `Conversation` or `runtime.py` required.
9. `CompactionEvent` events flow through the strategy's `last_result` to the runtime's event history (per spec §2.8).

---

## 11. Open Questions

### Q1: Should the strategy receive the *soft* ceiling or the *hard* ceiling?

**Context:** The roadmap's P1 introduces a soft ceiling at 80% and a hard ceiling at 100%. The strategy is called when the soft ceiling is exceeded. But should it also know about the hard ceiling (for fallback behavior)?

**Recommendation:** The strategy receives the soft ceiling as `token_budget`. The hard ceiling is an internal detail of the strategy (it can compute `hard = int(budget / 0.80)` if needed). This keeps the protocol simple — one budget, one job. The runtime is responsible for deciding *when* to call the strategy; the strategy is responsible for *how* to compact.

**Parameter naming:** the protocol argument is `token_budget` (not `max_tokens`). This aligns with the roadmap spec's renaming convention and makes the soft/hard distinction explicit at the call site (`strategy.compact(conv, soft_ceiling)` vs the old `conv.trim_to_token_limit(model_max)` which conflated the two).

### Q2: Should the strategy return a result (messages removed, method used) for telemetry?

**Context:** The runtime currently tracks `_last_trim_removed` (line 1620) and reports it via `on_token_breakdown`. If the strategy replaces the trim call, how does the runtime know what happened?

**Recommendation:** The strategy exposes a `last_result: CompactionEvent` attribute (see §4.5). The runtime reads it after each call and appends to its rolling history (`_compaction_events`, capped at 100 events per spec §2.8).

**Why attribute (not return value):** keeps the `ContextStrategy` protocol stable as `CompactionEvent` grows new fields. The protocol stays a single `compact()` method; telemetry is a side concern.

**Why the strategy owns the recording (not the runtime):** the strategy already has all the data — `before_count`, `after_count`, `summary_tokens_injected`, `soft_ceiling`, `hard_ceiling`, `provider`, `model`. Reconstructing them at the runtime call site means duplicating logic and risking drift. The strategy is the single source of truth for what happened during compaction.

**Compatibility with §11 Q3 (no P7 absorption):** `CompactionEvent` captures conversation-level metrics only. Prompt-budget metrics (P7) live in `utils/prompt_loader.py` and are reported through a separate channel (the existing `_apply_system_prompt_budget` return value). The two telemetry streams are coordinated by the runtime but produced by different components — same separation-of-concerns argument as the rest of this proposal.

### Q3: Should the strategy module eventually absorb the P7 dynamic budget logic from `prompt_loader.py`?

**Context:** P7 (dynamic system prompt budget) operates on the prompt, not the conversation. It's a different concern.

**Recommendation:** No. P7 stays in `utils/prompt_loader.py`. The strategy manages *conversation* compaction; the prompt loader manages *prompt* sizing. They're coordinated by the runtime (which calls both) but they're separate concerns in separate modules. A future "full context strategy" that encompasses both prompt budgeting and conversation compaction would be a separate, larger abstraction — not this one.

---

## 12. Alternatives Considered

### Alternative A: Strategy as Methods on a Separate Mixin

**Idea:** Make `Conversation` inherit from a `CompactionMixin` that provides trim/summary methods. Different mixins for different strategies.

**Rejected because:** Python dataclass + mixin is fragile (MRO issues, field ordering problems, `__init__` conflicts). It also doesn't solve the real problem — the strategy is still coupled to the `Conversation` class hierarchy. You can't swap a strategy without changing the class hierarchy.

### Alternative B: Strategy as Free Functions in a Module

**Idea:** `agent/compaction.py` with module-level functions: `compact_default(conv, budget)`, `compact_llm(conv, budget)`, etc. Runtime selects the function by name.

**Rejected because:** Functions don't hold state well. An LLM summarization strategy needs an API client and prompt template. A sliding-window strategy needs configuration. Encoding this as module-level functions requires either global state (bad) or `functools.partial` (ugly). Classes are the natural Python pattern for "behavior + configuration."

### Alternative C: Plugin System with Entry Points

**Idea:** Use `importlib.metadata` entry points so strategies are discovered automatically from installed packages.

**Rejected because:** Overkill for a single application. CrabCakes is not a framework — it's an application. The strategy map (a dict in `runtime.py`) is sufficient. If CrabCakes ever becomes a framework, entry points can be added later without changing the `ContextStrategy` protocol.

### Alternative D: Defer Until We Have Two Strategies

**Idea:** The OpenHands team's advice was "build abstraction when you have two implementations." Build the default strategy on `Conversation`, then extract when we write the second one.

**Rejected because:** This ignores the cost asymmetry (§6). Extracting 60 lines now is 3.5 hours. Extracting 210 lines later is 9+ hours. And the spec update is trivial (mechanical transform). The "wait for two implementations" rule applies when the abstraction is uncertain — but we already know the protocol shape (one method, one budget, one conversation). There's no design risk in committing to it now.

---

## 13. Summary

Extract context management strategy from `Conversation` into a pluggable `ContextStrategy` module **before** implementing the Context Management Roadmap. The extraction is ~3.5 hours of low-risk, mechanical work. The result is:

- A clean protocol that makes future strategy swaps trivial
- `Conversation` restored to pure data (its ARCHITECTURE.md contract)
- The roadmap spec implemented in the right place from the start
- CrabCakes on par with the best-in-class agent frameworks for context management extensibility

The cost of waiting is 2-3× the effort and a medium-risk refactor in the same PR as new feature work. The cost of not doing it at all is permanent coupling and an inability to experiment with the fastest-moving area of agent design.

