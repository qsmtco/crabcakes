# Master Phase Plan — Runtime Modular Extraction Phase 1

**Source spec:** `docs/specs/SPEC-RUNTIME-MODULAR-EXTRACTION-PHASE-1.md`
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Created:** 2026-07-17

This document decomposes the spec's 3 implementation sections (Track A, Track B Phase 2a, Track B Phase 2b) into supervisor-level phases for delegation. Each phase is 1-3 files (Phase B4 is larger — handled via detailed instructions file). Commit boundaries follow the spec: Track A = 1 commit, Phase 2a = 1 commit, Phase 2b = 1 commit.

## Authority reminder

`ARCHITECTURE.md` is the floor. The spec narrows it. Code conforms to both. When line numbers drift (they will), anchor to identifiers (function/class names), not line numbers.

## Phase inventory

| Phase | Track | Files | Commit |
|-------|-------|-------|--------|
| A1 | A | tool_middleware.py (NEW), test_tool_middleware.py (NEW) | Track A |
| A2 | A | runtime.py, test_tool_middleware.py | Track A |
| B1 | 2a | llm/cost.py (NEW), runtime.py, test_llm_cost.py (NEW) | 2a |
| B2 | 2a | llm/convert.py (NEW), runtime.py, test_llm_convert.py (NEW) | 2a |
| B3 | 2a | llm/extractors.py (NEW), runtime.py, test_llm_extractors.py (NEW) | 2a |
| B4 | 2a | llm/{__init__,protocol,openai_provider,minimax_provider,anthropic_provider,registry}.py (NEW), runtime.py, test_llm_providers.py + test_llm_registry.py (NEW) | 2a |
| B5 | 2b | llm/streaming.py (NEW), runtime.py, test_llm_streaming.py (NEW) | 2b |
| B6 | 2b | llm/{openai_provider,minimax_provider,anthropic_provider}.py, runtime.py, test_llm_providers.py | 2b |
| V | verify | (no edits — greps + tests + post-mortem) | — |

## Hard constraints (enforced every phase)

From spec §E:
1. Do NOT modify `agent/context_strategy.py`, `agent/enforcement.py`, `agent/tools.py`.
2. Do NOT modify `tests/test_agent_runtime.py` — existing tests pass unchanged.
3. Do NOT change `_call_llm_streaming` method signature (StreamingCallKwargs + TestStreamingSignature enforce this).
4. Re-exports in `runtime.py` must keep ALL existing test patches working.
5. Approval gating stays inline in `_run_loop` (temporal ordering constraint).
6. Anchor edits to identifiers, not line numbers.

## Per-phase entry/exit

Each phase:
- Entry: previous phase audited clean + supervisor independent verification passed.
- Exit: builder returns COMPLETENESS checklist + evidence; auditor adversarial probe clean; supervisor runs tests + greps independently.

## Audit handoff template

For every code-bearing phase, delegate to Debugger:
- Scope: exact files + identifiers in scope
- Load `prompts/adversarialDebugger.md` fresh
- Report in BUG #[N] format
- Explicit "no bugs found" if clean

## Stop conditions

Per `implementationLoop.md` §7.3:
- Spec fundamentally broken → abort, escalate to captain
- Coder fails same phase 3× → abort
- Debugger unreachable for full audit cycle → abort
- Pre-existing critical bug blocks work → abort
