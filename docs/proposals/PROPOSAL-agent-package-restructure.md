# PROPOSAL: Agent Package Restructure — Decouple Runtime from Domain

**Date:** 2026-06-11
**Author:** QTR
**Status:** Draft — awaiting review
**Related:** `docs/ARCHITECTURE.md`, PHASE-11 post-mortem, PHASE-FOLLOWUP-2 (validate_agent_def provider mismatch)

> **Status (verified 2026-06-12):** ❌ **PENDING / NOT STARTED** — 
> **status:** `PENDING` — sortable tag for `ls | grep STATUS` The `agent/` package remains a 7-file god package (376K total). `agent/runtime.py` is **1,627 lines** (worse than the proposal's "1,575 lines" baseline). The proposed split into `llm/`, `domain/`, `policies/` packages was not done. The validation mismatch bug (PHASE-FOLLOWUP-2) was likely fixed by other means (the proposal notes it's related to Phase 11) but the structural cleanup did not happen. **Marked PENDING; would be a substantial refactor.**

---

## 0. Problem Statement

The `agent/` package is a 4,190-line god package that mixes three distinct concerns: **runtime orchestration** (the LLM call loop), **domain models** (provider config, agent definitions), and **policy enforcement** (post-write verification). This coupling has caused concrete problems:

1. **`runtime.py` is 1,575 lines** — the largest file in the codebase. It contains LLM provider callers (`_call_openai`, `_call_minimax`, `_call_anthropic`), streaming logic (`_PROVIDER_STREAMERS`, `SSEEvent`, `_call_llm_streaming`), response parsing (`_extract_tool_calls`, `_extract_text_content`, `_extract_usage`), cost tables, conversation management, and the tool dispatch loop. Adding a new provider or fixing a streaming bug requires navigating a 1,500-line file where cost tables sit next to tool-call extraction.

2. **Circular dependency smell.** `agent/special_agents.py` imports from `utils/agent_defs.py`, which imports from `utils/providers_store.py`, which imports from `models/providers.py`. Meanwhile `agent/config.py` also imports from `utils/providers_store.py`. The agent definition → provider → model chain crosses three packages (`agent/`, `utils/`, `models/`) with no clear ownership.

3. **Provider validation mismatch (PHASE-FOLLOWUP-2 bug).** `validate_agent_def()` in `utils/agent_defs.py` compared provider IDs (`"minimax"`) against display names from `providers.yaml` (`"MiniMax M2.7"`). This happened because provider identity is split across `agent/config.py` (hardcoded IDs), `utils/providers_store.py` (display names), and `agent/runtime.py` (caller resolution). No single location owns "what is a valid provider."

4. **Testing friction.** The `TestStreamingSignature` regression test (PHASE-11) had to verify parameter drift across three surfaces — method signature, production caller, and test patches — because `_call_llm_streaming` is a monolithic method on `AgentRuntime` rather than a focused class in a dedicated module.

---

## 1. Proposal Overview

Restructure `agent/` into four focused packages, each with a clear single responsibility and zero circular dependencies. The dependency graph becomes a clean DAG:

```
ui/  →  agent/  →  llm/  →  domain/
                  ↘  policies/
```

No upward imports. No cycles. `agent/runtime.py` shrinks from 1,575 lines to ~300 lines.

Key principles:

- **Extract, don't rewrite.** Every module is a move + rename of existing code. Zero logic changes. All 1,394 passing tests continue to pass.
- **One responsibility per package.** `llm/` owns provider callers and streaming. `domain/` owns config and agent definitions. `policies/` owns enforcement. `agent/` owns orchestration only.
- **Break the circular dependency.** `special_agents.py` and `agent_defs.py` merge into `domain/agents.py`. Provider config becomes `domain/providers.py`. No more `agent/` ↔ `utils/` cycles.
- **Incremental migration.** Each phase is independently shippable. The old import paths are re-exported from `agent/__init__.py` so no downstream code breaks.

---

## 2. Target Structure

```
agent/
  __init__.py           # Re-exports for backward compatibility
  runtime.py            # ~300 lines — orchestration loop, dispatch, error handling
  conversation.py       # Session management, context tracking, prune logic
  tools.py              # Unchanged — already clean
  context.py            # Unchanged — already clean

llm/
  __init__.py
  callers.py            # _PROVIDER_CALLERS, _call_openai, _call_minimax, _call_anthropic
  streaming.py          # _PROVIDER_STREAMERS, SSEEvent, _call_llm_streaming, StreamingCallKwargs
  response.py           # _extract_tool_calls, _extract_text_content, _extract_usage
  costs.py              # _PROVIDER_COSTS, _OPENAI_COST, _MINIMAX_COST, _cost_for_model
  resolve.py            # _resolve_caller_key, _model_id, provider resolution logic

domain/
  __init__.py
  config.py             # agent.json → providers.yaml loading (from agent/config.py)
  providers.py          # Provider registry, defaults, validation (from utils/providers_store.py)
  agents.py             # Agent definitions, registry, seeding (merge of utils/agent_defs.py + agent/special_agents.py)
  validation.py         # validate_agent_def, provider ID resolution (from utils/agent_defs.py)

policies/
  __init__.py
  enforcement.py        # Post-write verification (from agent/enforcement.py, unchanged)
```

### 2.1 Module mapping (where does each function go?)

| Current location | Target location | Lines |
|---|---|---|
| `agent/runtime.py` — `_PROVIDER_CALLERS`, `_call_openai/minimax/anthropic` | `llm/callers.py` | ~200 |
| `agent/runtime.py` — `_PROVIDER_STREAMERS`, `_stream_*`, `SSEEvent`, `_call_llm_streaming`, `StreamingCallKwargs` | `llm/streaming.py` | ~250 |
| `agent/runtime.py` — `_extract_tool_calls/text_content/usage` | `llm/response.py` | ~80 |
| `agent/runtime.py` — cost tables, `_cost_for_model`, `_model_id` | `llm/costs.py` | ~60 |
| `agent/runtime.py` — `_resolve_caller_key` | `llm/resolve.py` | ~30 |
| `agent/runtime.py` — `AgentRuntime._run_loop`, `_call_llm` | `agent/runtime.py` (stays) | ~300 |
| `agent/runtime.py` — conversation management, prune | `agent/conversation.py` | ~200 |
| `agent/config.py` | `domain/config.py` | ~342 |
| `agent/special_agents.py` + `utils/agent_defs.py` | `domain/agents.py` | ~500 |
| `utils/agent_defs.py` — `validate_agent_def` | `domain/validation.py` | ~100 |
| `utils/providers_store.py` | `domain/providers.py` | ~200 |
| `agent/enforcement.py` | `policies/enforcement.py` | ~761 |
| `agent/tools.py` | `agent/tools.py` (unchanged) | ~892 |
| `agent/context.py` | `agent/context.py` (unchanged) | ~437 |

### 2.2 Dependency graph

```
agent/runtime.py     →  llm/callers.py, llm/streaming.py, llm/response.py
                     →  domain/config.py, domain/agents.py
                     →  policies/enforcement.py
                     →  agent/tools.py, agent/context.py

llm/callers.py       →  llm/resolve.py, llm/response.py
llm/streaming.py     →  llm/resolve.py, llm/response.py, llm/costs.py

domain/agents.py     →  domain/providers.py, domain/validation.py
domain/config.py     →  domain/providers.py
domain/validation.py →  domain/providers.py

policies/            →  (no imports from agent/, llm/, or domain/ — subprocess only)

ui/                  →  agent/ (unchanged — already correct)
```

No cycles. No upward imports. Each arrow goes one direction.

---

## 3. Backward Compatibility

`agent/__init__.py` re-exports everything so existing code keeps working:

```python
# agent/__init__.py — backward-compatible re-exports
from agent.runtime import AgentRuntime          # main class — stays
from domain.config import (AgentConfig, LLMProviderConfig,
                            load_agent_config, get_api_key)
from domain.agents import (SpecialAgentDef, SPECIAL_AGENTS,
                            get_special_agents, get_special_agent,
                            reload_registry)
from agent.tools import ToolDefinition, ToolResult
from agent.context import build_system_prompt, build_file_context
from policies.enforcement import check
```

Scripts and tests that import from `agent.runtime` (e.g. `from agent.runtime import SSEEvent, StreamingCallKwargs`) continue to work via re-exports. A deprecation warning can be added later for the old paths.

`utils/agent_defs.py` and `utils/providers_store.py` become thin wrappers that re-export from `domain/`:

```python
# utils/agent_defs.py — backward-compatible shim
from domain.agents import *        # noqa: F401,F403
from domain.validation import *    # noqa: F401,F403
```

---

## 4. What This Fixes

| Problem | Before | After |
|---|---|---|
| `runtime.py` size | 1,575 lines | ~300 lines |
| Provider identity ownership | Split across `agent/config.py`, `utils/providers_store.py`, `agent/runtime.py` | Single owner: `domain/providers.py` + `llm/resolve.py` |
| Circular dependency | `agent/` ↔ `utils/` (4 imports each direction) | Clean DAG: `agent/` → `domain/`, no cycles |
| Provider validation bug (PHASE-FOLLOWUP-2) | `validate_agent_def` compared IDs vs display names | `domain/validation.py` uses `llm/resolve.py` resolution — same logic as runtime |
| Adding a new provider | Edit `runtime.py` (find callers, streamers, costs, response parsers) | Edit `llm/callers.py` + `llm/streaming.py` — focused, ~50 lines total |
| Testing streaming signature | Test spans method, production caller, test patches | `llm/streaming.py` is independently testable |
| Enforcement coupling | `agent/enforcement.py` sits next to runtime | `policies/enforcement.py` — clearly a policy, not runtime |

---

## 5. Migration Phases

Each phase is independently shippable with zero regressions. Tests run after every phase.

### Phase 1: Extract `llm/` package (highest value, ~500 lines moved)

1. Create `llm/` package
2. Move cost tables + `_cost_for_model` + `_model_id` → `llm/costs.py`
3. Move `_extract_tool_calls`, `_extract_text_content`, `_extract_usage` → `llm/response.py`
4. Move `_resolve_caller_key` → `llm/resolve.py`
5. Move `_PROVIDER_CALLERS` + `_call_openai/minimax/anthropic` → `llm/callers.py`
6. Move `_PROVIDER_STREAMERS` + `_stream_*` + `SSEEvent` + `_call_llm_streaming` + `StreamingCallKwargs` → `llm/streaming.py`
7. Add re-exports in `agent/runtime.py`
8. Run full suite — zero regressions

**Estimated size:** ~500 lines moved, `runtime.py` drops from 1,575 → ~1,075 lines.

### Phase 2: Extract `domain/` package (breaks circular dependency, ~1,000 lines moved)

1. Create `domain/` package
2. Move `agent/config.py` → `domain/config.py`
3. Move `utils/providers_store.py` → `domain/providers.py`
4. Merge `agent/special_agents.py` + `utils/agent_defs.py` → `domain/agents.py`
5. Extract `validate_agent_def` → `domain/validation.py`
6. Fix provider validation to use `llm/resolve.py` resolution logic
7. Add re-exports in `agent/__init__.py` and `utils/agent_defs.py`
8. Run full suite — zero regressions

**Estimated size:** ~1,000 lines moved. Circular dependency eliminated.

### Phase 3: Extract `policies/` package (~761 lines moved)

1. Move `agent/enforcement.py` → `policies/enforcement.py`
2. Update imports in `agent/runtime.py`
3. Add re-exports
4. Run full suite — zero regressions

**Estimated size:** ~761 lines moved, pure file move.

### Phase 4: Extract `agent/conversation.py` (~200 lines moved)

1. Extract conversation management methods from `AgentRuntime` → `agent/conversation.py`
2. `AgentRuntime` delegates to `ConversationManager`
3. Run full suite — zero regressions

**Estimated size:** ~200 lines moved. `agent/runtime.py` is now ~300 lines.

---

## 6. What This Does NOT Change

- **Zero logic changes.** Every line of code is a move + import update. No refactoring, no renaming, no behavioral changes.
- **`agent/tools.py` and `agent/context.py` stay in `agent/`.** They're already clean and have no reason to move.
- **No UI changes.** The `ui/` package imports from `agent/` the same way it always has.
- **No config file changes.** `providers.yaml`, `agents/*.yaml`, `agent.json` — all unchanged.
- **No new dependencies.** This is pure reorganization using existing stdlib imports.

---

## 7. Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Import path breakage for scripts/tests | Medium | Re-exports in `agent/__init__.py` and `utils/agent_defs.py` maintain all old paths |
| Circular import at load time | Low | Phase 2 explicitly breaks the cycle; `domain/` has no upward imports |
| Merge conflicts with concurrent work | Medium | Each phase is small and can be merged independently |
| Hidden runtime coupling discovered late | Low | Full test suite (1,394 tests) runs after every phase |
| `from agent.runtime import X` still used widely | Low | Re-exports + deprecation warnings; full grep before each phase |

---

## 8. Success Criteria

- [ ] `agent/runtime.py` is under 350 lines
- [ ] No circular imports between any package (`agent/`, `llm/`, `domain/`, `policies/`, `utils/`)
- [ ] All 1,394+ tests pass with zero regressions
- [ ] Adding a new LLM provider requires changes to exactly 2 files (`llm/callers.py`, `llm/streaming.py`)
- [ ] Provider identity has a single owner (`domain/providers.py` + `llm/resolve.py`)
- [ ] Old import paths (`from agent.runtime import SSEEvent`, etc.) still work via re-exports

---

## 9. Alternatives Considered

### 9a. Status quo — do nothing

**Pros:** No work, no risk.
**Cons:** `runtime.py` continues to grow. Next provider addition or streaming fix will add more code to an already-unwieldy file. The circular dependency between `agent/` and `utils/` will cause more bugs like PHASE-FOLLOWUP-2. The longer we wait, the harder the refactor.

### 9b. Flatten everything into `agent/` (more files, no new packages)

**Pros:** Simpler import paths. No new top-level directories.
**Cons:** Doesn't solve the circular dependency with `utils/`. `agent/` becomes a dumping ground. Provider validation still crosses package boundaries.

### 9c. Full hexagonal/ports-and-adapters architecture

**Pros:** Maximum decoupling. Provider callers become pluggable adapters. Runtime knows nothing about specific APIs.
**Cons:** Massive over-engineering for a desktop app with 3-5 providers. Would require interface classes, dependency injection, and a config-driven caller registry. The current approach (dict-based `_PROVIDER_CALLERS`) is simpler and sufficient.

**Recommendation:** This proposal (9 = the middle ground). Package-level separation is enough. No interfaces, no DI, no frameworks. Just move code to where it belongs.

---

## 10. Timeline Estimate

| Phase | Lines moved | Effort | Risk |
|---|---|---|---|
| Phase 1: `llm/` | ~500 | 1-2 hours | Low (pure extraction) |
| Phase 2: `domain/` | ~1,000 | 2-3 hours | Medium (merge + circular dep fix) |
| Phase 3: `policies/` | ~761 | 30 min | Low (pure move) |
| Phase 4: `conversation.py` | ~200 | 1 hour | Medium (behavioral extraction) |
| **Total** | **~2,461** | **~5-6 hours** | — |

Can be done incrementally over multiple sessions. Each phase is independently reviewable and shippable.
