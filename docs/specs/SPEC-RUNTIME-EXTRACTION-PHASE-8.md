# SPEC: Runtime Modular Extraction — Phase 8 (Re-export Alias Cleanup)

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for implementation (REVISED after spec audit)
**Implements:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md` §5 (Phase 8)
**Depends on:** Phases 4–6 (cost, audit, persistence must be extracted first)
**Target branch:** main

> **Architecture compliance:** This phase removes PURE re-export alias blocks from `agent/runtime.py` and updates call sites to import directly from `agent/llm/*`. No new modules. No layer violations.
>
> **IMPORTANT SCOPE CORRECTION (post-audit):** The original Phase 8 draft proposed removing `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS`, and the bound-method shims (`_call_openai` etc.). **Spec audit found these are NOT pure re-exports** — they are active dispatch infrastructure: `_RESPONSE_FORMAT` is derived from `_PROVIDER_CALLERS` at module load (line 237-242), `utils/providers_store.py::_VALID_CALLERS` has a duplication invariant test, and the dispatch in `_call_llm`/`_call_llm_streaming` uses `_PROVIDER_CALLERS.get(caller_key)` directly. **Removing them is a dispatch-architecture refactor, not an alias cleanup.** That refactor is DEFERRED to a future phase. This phase only removes the pure alias re-exports.

---

## 1. Overview

### Problem statement

After Phases B1–B6 and Phases 4–6, `agent/runtime.py` carries **3 pure re-export blocks** that import symbols from `agent/llm/*` under legacy underscore names. These are pure aliases — the underscored names are used at call sites in runtime.py but serve no purpose beyond avoiding a rename. The real definitions live in `agent/llm/*`.

**What IS in scope (pure aliases — safe to remove):**
- Converters block: `_convert_messages_for_anthropic`, `_convert_tools_for_anthropic` (2 call sites)
- Streaming block: `_sse_lines`, `_parse_sse_line`, `_parse_sse_delta`, `_first_choice`, `_urlopen_with_ssl_retry`, `_stream_with_ssl_retry`, `_is_retryable_ssl_error`, `_friendly_error_message`, + 4 constants (10+ call sites)
- Extractors block: `_extract_tool_calls`, `_extract_text_content`, `_extract_usage` (16 call sites)

**What is NOT in scope (dispatch infrastructure — DEFERRED):**
- `_PROVIDER_CALLERS` dict (line 200) — used for runtime dispatch at lines 1843, 2352; `_RESPONSE_FORMAT` derived from it at 237-242
- `_PROVIDER_STREAMERS` dict (line 276) — used for runtime streaming dispatch
- Bound-method shims `_call_openai`, `_call_minimax`, `_call_anthropic` — referenced by `_PROVIDER_CALLERS`/`_PROVIDER_STREAMERS` dict values
- `get_valid_callers()` consumers in `utils/providers_store.py`
- `_RESPONSE_FORMAT` dict

### Solution summary

1. For each of the 3 pure re-export blocks, update call sites in runtime.py to use the public names.
2. Remove the re-export blocks.
3. Update `__all__` to remove the underscored aliases.
4. Update tests that patch these specific symbols.

### Scope (in/out table)

| In scope | Out of scope (DEFERRED) |
|----------|-------------|
| Remove 3 pure re-export blocks (converters, streaming, extractors) | `_PROVIDER_CALLERS` / `_PROVIDER_STREAMERS` dispatch dicts |
| Update ~28 call sites in runtime.py to non-underscored names | Bound-method shims `_call_openai` etc. |
| Update `__all__` | `_RESPONSE_FORMAT` derivation |
| Update test patch targets for the 3 blocks | `get_valid_callers()` / `_VALID_CALLERS` invariant |

---

## 2. Discovery (Steel-Framed Rule 1)

```
DISCOVERY:
- Read agent/runtime.py re-export blocks:
  Block 1 (converters, lines 177-182): 2 symbols from agent.llm.convert. 2 call sites.
  Block 2 (streaming, lines 245-262): 13 symbols from agent.llm.streaming. 10+ call sites.
  Block 3 (extractors, lines 264-270): 3 symbols from agent.llm.extractors. 16 call sites.
- NOT in scope: _PROVIDER_CALLERS (line 200), _PROVIDER_STREAMERS (line 276),
  _RESPONSE_FORMAT (line 237), bound-method shims (lines 192-196). These are
  dispatch infrastructure, not aliases. Spec audit BUG #15, #17, #18, #19, #20.
- Grep tests/ for patch targets on the 3 in-scope blocks.
- __all__ lists: _extract_tool_calls, _extract_text_content, _extract_usage,
  _is_retryable_ssl_error, _stream_with_ssl_retry, _friendly_error_message.
- _is_empty_content (lines 301-332) STAYS in runtime.py — not a re-export.
- _format_chunks_for_llm (lines 335-347) STAYS in runtime.py — KB synthesis helper,
  not an LLM/provider function. Out of scope for all phases.
- Architecture owner: agent/llm/* owns all LLM-related symbols.
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
