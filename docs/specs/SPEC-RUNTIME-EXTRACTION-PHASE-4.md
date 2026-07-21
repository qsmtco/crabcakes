# SPEC: Runtime Modular Extraction — Phase 4 (Cost Model Cleanup)

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md` §3.3
**Depends on:** Phases B1–B6 (completed — `agent/llm/cost.py` already exists)
**Target branch:** main

> **Architecture compliance:** `agent/llm/cost.py` (pure Python, no UI deps) already exists from Phase B1. This phase removes the re-export shims from `agent/runtime.py`, updates call sites to import directly, and cleans up `__all__`. No layer violations.

---

## 1. Overview

### Problem statement

`agent/llm/cost.py` was already extracted in Phase B1 (per context.md entry 2026-07-19). However, `agent/runtime.py` still carries **9 lines of re-export aliases** that import the cost symbols under legacy underscore names (`_OPENAI_COST`, `_MINIMAX_COST`, etc.) purely for backward compatibility. The call sites inside runtime.py use these underscored names. This is dead weight: the real definitions live in `cost.py`, the aliases exist only to avoid updating call sites.

### Solution summary

1. Update the 2 call sites in `runtime.py` to import directly from `agent.llm.cost` (or use the already-imported public names).
2. Remove the 9-line re-export block.
3. Update `__all__` to remove `_cost_for_model` (it's already public in `agent.llm.cost` as `cost_for_model`).
4. Verify no test or script depends on `runtime._cost_for_model` (the underscored alias).

### Scope (in/out table)

| In scope | Out of scope |
|----------|-------------|
| `agent/runtime.py` — remove re-export block, update 2 call sites, update `__all__` | `agent/llm/cost.py` — already correct, no changes |
| `tests/test_llm_cost.py` — verify still passes (tests import from `agent.llm.cost` directly) | `models/providers.py` — no changes (cost stays in `agent/llm/`) |

### Architecture principles that apply

- §2 layering: `agent/llm/cost.py` is pure Python, no UI deps. ✓
- DRY: one definition per symbol. The re-export aliases violate DRY. ✓

---

## 2. Discovery (Steel-Framed Rule 1)

```
DISCOVERY:
- Read agent/llm/cost.py: Already extracted (Phase B1). Public symbols:
  OPENAI_COST, MINIMAX_COST, ANTHROPIC_COST, PROVIDER_COSTS (dict),
  model_id(model: str) -> str, cost_for_model(model, prompt, completion) -> float.
  48 lines. Pure functions, no state.
- Read agent/runtime.py lines 166-175: Re-export block imports 6 symbols under
  underscored aliases (_OPENAI_COST, _MINIMAX_COST, _ANTHROPIC_COST, _PROVIDER_COSTS,
  _model_id, _cost_for_model). 9 lines (including comment + blank line).
- Read agent/runtime.py __all__ (lines 70-82): Lists "_cost_for_model" as exported.
  Does NOT list _model_id or the cost constants.
- Grep call sites: _cost_for_model called at 2 sites (line 1332 in _call_llm cost
  tracking, line 1477 in fallback cost tracking). _model_id is NOT called directly
  in runtime.py (only via cost_for_model internally). _PROVIDER_COSTS not referenced
  directly. The cost constants (_OPENAI_COST etc.) not referenced directly.
- Grep tests: tests/test_llm_cost.py imports from agent.llm.cost directly (verified).
  tests/test_agent_runtime.py references _cost_for_model via runtime import —
  MUST verify whether it uses runtime._cost_for_model or agent.llm.cost.cost_for_model.
- Architecture owner: agent/llm/cost.py owns cost calculation (extracted Phase B1).
```

---

## 3. Changes by File

### 3.1 `agent/runtime.py`

#### 3.1a: Add direct import at top of file

At the top of `agent/runtime.py`, in the import block (after the existing `from agent.llm.streaming import ...` line, around line 33), add:

```python
from agent.llm.cost import cost_for_model
```

Do NOT add underscored aliases — use the public name directly.

#### 3.1b: Update call site 1 (line 1332)

Find (around line 1332):
```python
                    cost = _cost_for_model(conv.model, prompt_tok, comp_tok)
```

Change to:
```python
                    cost = cost_for_model(conv.model, prompt_tok, comp_tok)
```

#### 3.1c: Update call site 2 (line 1477)

Find (around line 1477):
```python
                                fb_cost = _cost_for_model(fallback_model, fb_prompt, fb_comp)
```

Change to:
```python
                                fb_cost = cost_for_model(fallback_model, fb_prompt, fb_comp)
```

#### 3.1d: Remove the re-export block

Find the block starting around line 166:
```python
# ── Cost tables + functions (extracted to agent/llm/cost.py, Phase B1) ──────
# Re-exported under legacy underscore names for backward compatibility.
from agent.llm.cost import (
    OPENAI_COST as _OPENAI_COST,
    MINIMAX_COST as _MINIMAX_COST,
    ANTHROPIC_COST as _ANTHROPIC_COST,
    PROVIDER_COSTS as _PROVIDER_COSTS,
    model_id as _model_id,
    cost_for_model as _cost_for_model,
)
```

Delete the entire block (the comment + the import).

#### 3.1e: Update `__all__`

Find the `__all__` list (around line 70). Remove the line:
```python
    "_cost_for_model",
```

The public API for cost now lives in `agent.llm.cost`. The `__all__` in runtime.py should not re-export it.

### 3.2 `tests/test_agent_runtime.py` (if needed)

**First, check** whether `test_agent_runtime.py` imports `_cost_for_model` from `runtime`. Run:
```bash
grep -n "_cost_for_model\|cost_for_model" tests/test_agent_runtime.py
```

If the test imports `from agent.runtime import _cost_for_model`, change it to `from agent.llm.cost import cost_for_model` and update the call site in the test.

If the test already imports from `agent.llm.cost`, no change needed.

### Files NOT changed

- `agent/llm/cost.py` — already correct, no changes
- `models/providers.py` — cost stays in `agent/llm/`, not moved to `models/`
- `tests/test_llm_cost.py` — imports from `agent.llm.cost` directly, no changes

---

## 4. Data Flow

No data flow change. The same function (`cost_for_model`) is called at the same 2 sites with the same arguments. The only change is the import path (direct from `agent.llm.cost` instead of via re-export alias).

---

## 5. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `agent/runtime.py` | Edit (remove 9-line block, update 2 call sites, update __all__, add 1 import) | -7 net | Low |
| `tests/test_agent_runtime.py` | Edit (if it imports _cost_for_model from runtime) | ±2 | Low |

---

## 6. Acceptance Criteria

- [ ] `grep -c "_cost_for_model\|_OPENAI_COST\|_MINIMAX_COST\|_ANTHROPIC_COST\|_PROVIDER_COSTS\|_model_id" agent/runtime.py` returns **0**
- [ ] `grep -c "from agent.llm.cost import cost_for_model" agent/runtime.py` returns **1**
- [ ] `grep -c "cost_for_model(" agent/runtime.py` returns **2** (the 2 call sites)
- [ ] `_cost_for_model` is NOT in `__all__`
- [ ] `python3 -m pytest tests/test_llm_cost.py -q` passes
- [ ] `python3 -m pytest tests/test_agent_runtime.py -q -k "cost"` passes (if any cost-related tests)
- [ ] `python3 -c "from agent.runtime import AgentRuntime; print('OK')"` succeeds

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Test imports `runtime._cost_for_model` | Test updated to import from `agent.llm.cost` |
| Script imports `runtime._cost_for_model` | Grep `scripts/` — if found, update or add re-export back |
| `cost_for_model` called with unknown provider | Returns 0.0 (existing behavior in cost.py, unchanged) |

---

## 8. ARCHITECTURE.md Updates Required

- §3.21m (or wherever runtime.py is documented): note that cost re-exports removed; cost calculation lives solely in `agent/llm/cost.py`
