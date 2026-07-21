# SPEC: Runtime Modular Extraction — Phase 8 (Final Reduction)

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md` §5 (Phase 8)
**Depends on:** Phases 4–6 (cost, audit, persistence must be extracted first)
**Target branch:** main

> **Architecture compliance:** This phase removes re-export shims from `agent/runtime.py` and updates call sites to import directly from `agent/llm/*`. No new modules. No layer violations. The re-exports exist only for backward compatibility with tests that patch `agent.runtime._call_openai` etc.

---

## 1. Overview

### Problem statement

After Phases B1–B6 and Phases 4–6, `agent/runtime.py` still carries **~60 lines of re-export blocks** that import symbols from `agent/llm/*` under legacy underscore names (`_cost_for_model`, `_extract_tool_calls`, `_call_openai`, etc.). These exist purely so tests that do `patch("agent.runtime._call_openai")` continue to work. The real definitions live in `agent/llm/*`; the shims are dead weight.

Additionally, there are **bound-method shims** for test-patch compatibility:
```python
_call_openai = OpenAIProvider("openai").call
_call_minimax = MiniMaxProvider().call
```
These create bound methods at import time so tests can patch them. They should be replaced with direct imports from the provider registry.

### Solution summary

1. For each re-export block, update the call sites in runtime.py to use the public (non-underscored) names imported directly from `agent/llm/*`.
2. Remove the re-export blocks.
3. For test-patch compatibility: either (a) update tests to patch the new locations, or (b) keep a minimal compatibility shim. **Decision: update tests** — the re-exports are the debt; keeping them perpetuates it.
4. Update `__all__` to remove underscored aliases.

**This phase depends on Phases 4–6 being complete** (cost re-exports removed in Phase 4; the others removed here).

### Scope (in/out table)

| In scope | Out of scope |
|----------|-------------|
| `agent/runtime.py` — remove 4 remaining re-export blocks, update call sites, update `__all__` | `agent/llm/*` — no changes (already correct) |
| `tests/test_agent_runtime.py` — update patch targets from `agent.runtime._X` to `agent.llm.X` | `agent/audit.py`, `agent/persistence.py` — handled in Phases 5–6 |
| `scripts/audit_*.py` — update imports if they reference `runtime._PROVIDER_*` | New features — none |

### Architecture principles that apply

- DRY: one definition per symbol. Re-exports violate DRY. ✓
- Test isolation: tests should patch the real location, not a shim. ✓

---

## 2. Discovery (Steel-Framed Rule 1)

```
DISCOVERY:
- Read agent/runtime.py re-export blocks (lines 166-270):
  Block 1 (cost, lines 166-175): 6 symbols from agent.llm.cost — REMOVED in Phase 4.
  Block 2 (convert, lines 177-182): 2 symbols from agent.llm.convert
    (_convert_messages_for_anthropic, _convert_tools_for_anthropic).
  Block 3 (providers, lines 184-196): OpenAIProvider, MiniMaxProvider, AnthropicProvider
    imports + _get_provider + bound-method shims (_call_openai, _call_minimax,
    _call_anthropic as bound .call methods).
  Block 4 (streaming, lines 245-262): 13 symbols from agent.llm.streaming.
  Block 5 (extractors, lines 264-270): 3 symbols from agent.llm.extractors.
- Grep call sites for each underscored symbol in runtime.py (must update all).
- Grep tests/ and scripts/ for patch("agent.runtime._X") patterns.
- __all__ lists: _extract_tool_calls, _extract_text_content, _extract_usage,
  _cost_for_model, _PROVIDER_CALLERS, _PROVIDER_STREAMERS, _is_retryable_ssl_error,
  _stream_with_ssl_retry, _friendly_error_message.
- Architecture owner: agent/llm/* owns all LLM-related symbols. runtime.py should
  import and use them directly, not re-export under aliases.
```

---

## 3. Changes by File

### 3.1 `agent/runtime.py`

This is a multi-edit phase. Each re-export block is removed and its call sites updated. **Process one block at a time, verify after each.**

#### 3.1a: Converters block (lines 177-182)

**Remove:**
```python
# ── Anthropic converters (extracted to agent/llm/convert.py, Phase B2) ──────
# Re-exported under legacy underscore names for backward compatibility.
from agent.llm.convert import (
    convert_messages_for_anthropic as _convert_messages_for_anthropic,
    convert_tools_for_anthropic as _convert_tools_for_anthropic,
)
```

**Replace with** (direct import at top of file, in the import block):
```python
from agent.llm.convert import convert_messages_for_anthropic, convert_tools_for_anthropic
```

**Update call sites:** grep for `_convert_messages_for_anthropic` and `_convert_tools_for_anthropic` in runtime.py, replace with the non-underscored names.

#### 3.1b: Streaming block (lines 245-262)

**Remove** the entire 13-symbol re-export block.

**Replace with** (direct import at top of file):
```python
from agent.llm.streaming import (
    SSEEvent,
    sse_lines,
    parse_sse_line,
    parse_sse_delta,
    first_choice,
    urlopen_with_ssl_retry,
    stream_with_ssl_retry,
    is_retryable_ssl_error,
    friendly_error_message,
    RETRYABLE_SSL_ERRORS,
    RETRYABLE_OSERROR_TYPES,
    MAX_SSL_RETRIES,
    SSL_RETRY_BASE_MS,
)
```

**Update call sites:** grep for each `_X` symbol in runtime.py, replace with `X`.

#### 3.1c: Extractors block (lines 264-270)

**Remove:**
```python
from agent.llm.extractors import (
    extract_tool_calls as _extract_tool_calls,
    extract_text_content as _extract_text_content,
    extract_usage as _extract_usage,
)
```

**Replace with:**
```python
from agent.llm.extractors import extract_tool_calls, extract_text_content, extract_usage
```

**Update call sites:** grep for `_extract_tool_calls`, `_extract_text_content`, `_extract_usage`, replace with non-underscored names.

#### 3.1d: Provider block + bound-method shims (lines 184-196)

This is the most complex. The current block has:
```python
from agent.llm.openai_provider import OpenAIProvider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.anthropic_provider import AnthropicProvider
from agent.llm.registry import get_provider as _get_provider

# Bound methods for test-patch compatibility
_call_openai = OpenAIProvider("openai").call
_call_minimax = MiniMaxProvider().call
_call_anthropic = AnthropicProvider().call
```

**Remove** the bound-method shims entirely. Keep the provider class imports if they're used directly in runtime.py (check with grep). Replace `_get_provider` with direct `get_provider` import.

**Update call sites:** grep for `_call_openai`, `_call_minimax`, `_call_anthropic`, `_get_provider` in runtime.py. If any remain (beyond the re-export block), they must be updated to use the provider registry pattern (`get_provider(key).call(...)` / `get_provider(key).stream(...)`).

**Check `_PROVIDER_CALLERS` and `_PROVIDER_STREAMERS`:** these may still exist as dispatch dicts. Grep for them. If they exist only for test-patch compatibility and are not used in the actual dispatch logic (which now uses `get_provider()`), remove them and update tests.

#### 3.1e: Update `__all__`

Remove all underscored aliases from `__all__`. The public API of runtime.py is `AgentRuntime` (and possibly `SSEEvent`, `StreamingCallKwargs` if they're used externally). Everything else lives in `agent/llm/*`.

### 3.2 `tests/test_agent_runtime.py`

**Update patch targets.** Find all `patch("agent.runtime._X")` calls and update to `patch("agent.llm.X")` or `patch("agent.llm.module.X")`.

Grep first:
```bash
grep -n 'patch("agent\.runtime\._\|patch("agent\.runtime\._PROVIDER' tests/test_agent_runtime.py
```

Common patterns to update:
- `patch("agent.runtime._call_openai")` → `patch("agent.llm.openai_provider.OpenAIProvider.call")` or equivalent
- `patch("agent.runtime._extract_tool_calls")` → `patch("agent.llm.extractors.extract_tool_calls")`
- `patch("agent.runtime._PROVIDER_CALLERS")` → may need restructuring

**This is the riskiest part of Phase 8.** Test patches that target specific import locations must be updated carefully. If a test patches `agent.runtime._call_openai` and the call site now does `from agent.llm.openai_provider import OpenAIProvider`, the patch target must change to where the name is looked up.

### 3.3 `scripts/audit_*.py`

Check if scripts reference `runtime._PROVIDER_CALLERS` or `runtime._PROVIDER_STREAMERS`:
```bash
grep -rn "_PROVIDER_CALLERS\|_PROVIDER_STREAMERS\|_call_openai\|_call_minimax" scripts/
```

Update any references to import from `agent.llm.*` directly.

### Files NOT changed

- `agent/llm/*` — all modules are already correct
- `agent/audit.py` — handled in Phase 5
- `agent/persistence.py` — handled in Phase 6

---

## 4. Data Flow

No data flow change. The same functions are called at the same sites. The only change is import paths (direct from `agent.llm.*` instead of via re-export alias) and test patch targets.

---

## 5. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `agent/runtime.py` | Edit (remove ~60 lines of re-exports, update ~30 call sites, update __all__) | -50 net | Medium-High |
| `tests/test_agent_runtime.py` | Edit (update patch targets) | ±20 | Medium-High |
| `scripts/audit_*.py` | Edit (update imports, if needed) | ±5 | Low |

---

## 6. Acceptance Criteria

- [ ] `grep -c "Re-exported under legacy" agent/runtime.py` returns **0**
- [ ] `grep -c "_call_openai\|_call_minimax\|_call_anthropic" agent/runtime.py` returns **0** (unless used in a comment)
- [ ] `grep -c "_convert_messages_for_anthropic\|_convert_tools_for_anthropic" agent/runtime.py` returns **0**
- [ ] `grep -c "_extract_tool_calls\|_extract_text_content\|_extract_usage" agent/runtime.py` returns **0**
- [ ] `grep -c "_sse_lines\|_parse_sse_line\|_urlopen_with_ssl_retry\|_stream_with_ssl_retry" agent/runtime.py` returns **0**
- [ ] `__all__` in runtime.py contains only `AgentRuntime` and legitimate runtime-owned symbols (no LLM aliases)
- [ ] `python3 -c "from agent.runtime import AgentRuntime; print('OK')"` succeeds
- [ ] `python3 -m pytest tests/test_agent_runtime.py -q` passes (all patch targets updated)
- [ ] `python3 -m pytest tests/test_llm_providers.py tests/test_llm_streaming.py tests/test_llm_cost.py tests/test_llm_convert.py tests/test_llm_extractors.py -q` passes
- [ ] runtime.py line count is reduced (target: ~2,250 or lower after Phases 4+5+6+8 combined)

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Test patches `agent.runtime._call_openai` | Updated to patch the provider class method directly |
| Script imports `runtime._PROVIDER_CALLERS` | Updated to import from `agent.llm.registry` or removed |
| `_is_empty_content` referenced in runtime.py | Stays in runtime.py (per Phase B3 note: "stays here, used at non-extractor sites") |
| Provider class used directly in runtime.py | Import kept (e.g., `from agent.llm.registry import get_provider`) |

---

## 8. ARCHITECTURE.md Updates Required

- Update §3.21m: runtime.py line count after all phases; note all re-exports removed
- Update agent/ module listing: `agent/audit.py` and `agent/persistence.py` added
- Note: runtime.py now imports from `agent/llm/*` directly, no re-export layer

---

## 9. Implementation Order (across Phases 4-6-5-8)

The recommended order for the supervisor to phase this work:

1. **Phase 4 (Cost cleanup)** — smallest, validates the pattern. 1 file, ~7 lines removed.
2. **Phase 5 (AuditLog)** — self-contained, new file + tests. ~79 lines moved.
3. **Phase 6 (Persistence)** — largest, 6 functions moved. ~280 lines moved.
4. **Phase 8 (Final reduction)** — remove all remaining re-exports. ~60 lines removed + test updates.

After all 4 phases: runtime.py should drop from 2,382 → ~1,950 lines (estimated). The proposal's target of ~1,090 requires additional extractions (tool output policy §3.6, lifecycle hooks §3.7) that are out of scope for this round.
