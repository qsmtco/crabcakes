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

**Update call sites:** grep for `_convert_messages_for_anthropic` and `_convert_tools_for_anthropic` in runtime.py (2 call sites), replace with the non-underscored names.

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

**Update call sites:** grep for each `_X` symbol in runtime.py (10+ call sites), replace with `X`.

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

**Update call sites:** grep for `_extract_tool_calls`, `_extract_text_content`, `_extract_usage` in runtime.py (16 call sites), replace with non-underscored names.

#### 3.1d: Update `__all__`

Remove these underscored aliases from `__all__`:
- `_extract_tool_calls`
- `_extract_text_content`
- `_extract_usage`
- `_is_retryable_ssl_error`
- `_stream_with_ssl_retry`
- `_friendly_error_message`

**Do NOT remove** from `__all__`: `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS` (still active dispatch infrastructure, deferred).

### 3.2 `tests/test_agent_runtime.py`

**Update patch targets** for the 3 in-scope blocks. Grep first:
```bash
grep -n 'patch("agent\.runtime\._extract_\|patch("agent\.runtime\._sse_\|patch("agent\.runtime\._parse_sse\|patch("agent\.runtime\._stream_with_ssl\|patch("agent\.runtime\._urlopen_with_ssl\|patch("agent\.runtime\._convert_messages\|patch("agent\.runtime\._convert_tools\|patch("agent\.runtime\._first_choice' tests/test_agent_runtime.py
```

Update each patch target from `agent.runtime._X` to the new location (`agent.llm.extractors.X`, `agent.llm.streaming.X`, `agent.llm.convert.X`).

**Do NOT touch** patches targeting `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS`, `_call_openai` — those are deferred.

### Files NOT changed

- `agent/llm/*` — all modules already correct
- `agent/audit.py` — handled in Phase 5
- `agent/persistence.py` — handled in Phase 6
- `scripts/audit_*.py` — these reference `_PROVIDER_CALLERS`/`_PROVIDER_STREAMERS` which are deferred. No changes needed in this phase.
- `utils/providers_store.py` — `_VALID_CALLERS` references `_PROVIDER_CALLERS` which is deferred. No changes.

---

## 4. Data Flow

No data flow change. The same functions are called at the same sites. The only change is import paths (direct from `agent.llm.*` instead of via re-export alias).

---

## 5. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `agent/runtime.py` | Edit (remove ~25 lines of re-exports, update ~28 call sites, update __all__) | -15 net | Medium |
| `tests/test_agent_runtime.py` | Edit (update patch targets for 3 blocks) | ±10 | Medium |

---

## 6. Acceptance Criteria

- [ ] `grep -c "Re-exported under legacy" agent/runtime.py` returns **0**
- [ ] `grep -c "_convert_messages_for_anthropic\|_convert_tools_for_anthropic" agent/runtime.py` returns **0**
- [ ] `grep -c "_extract_tool_calls\|_extract_text_content\|_extract_usage" agent/runtime.py` returns **0**
- [ ] `grep -c "_sse_lines\|_parse_sse_line\|_urlopen_with_ssl_retry\|_stream_with_ssl_retry" agent/runtime.py` returns **0**
- [ ] `_PROVIDER_CALLERS` and `_PROVIDER_STREAMERS` still present (DEFERRED — do NOT remove)
- [ ] `python3 -c "from agent.runtime import AgentRuntime; print('OK')"` succeeds
- [ ] `python3 -m pytest tests/test_agent_runtime.py -q` passes
- [ ] `python3 -m pytest tests/test_llm_providers.py tests/test_llm_streaming.py tests/test_llm_convert.py tests/test_llm_extractors.py -q` passes

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Test patches `agent.runtime._extract_tool_calls` | Updated to patch `agent.llm.extractors.extract_tool_calls` |
| Test patches `agent.runtime._PROVIDER_CALLERS` | NOT touched (deferred) |
| `_is_empty_content` referenced in runtime.py | Stays in runtime.py (not a re-export) |
| `_format_chunks_for_llm` referenced in runtime.py | Stays in runtime.py (KB synthesis helper) |

---

## 8. ARCHITECTURE.md Updates Required

- Update §3.21m: runtime.py line count after all phases; note pure re-export aliases removed
- Note: `_PROVIDER_CALLERS`/`_PROVIDER_STREAMERS` dispatch refactor DEFERRED to future phase

---

## 9. Implementation Order (across Phases 4-5-6-8)

The recommended order for the supervisor to phase this work:

1. **Phase 4 (Cost cleanup)** — smallest, validates the pattern. 1 file, ~7 lines removed.
2. **Phase 5 (AuditLog)** — self-contained, new file + tests. ~79 lines moved.
3. **Phase 6 (Persistence)** — largest, 6 functions moved. ~280 lines moved.
4. **Phase 8 (Re-export cleanup)** — remove 3 pure alias blocks. ~15 lines removed + test updates.

After all 4 phases: runtime.py drops from 2,382 → ~2,000 lines (estimated). The proposal's target of ~1,090 requires additional extractions (dispatch refactor, tool output policy §3.6, lifecycle hooks §3.7) that are out of scope for this round.

**Phase 7 note:** The proposal's Phase 7 (streaming contingency) was already covered in Phase B6 (per context.md). There is no separate Phase 7 spec — the numbering gap is intentional.
