# Runtime Modular Extraction Phases 4–8 Post-Mortem

**Date:** 2026-07-20
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** ~20 (review-layer accept commits)
**Phases:** 4 (Phase 4 cost cleanup → Phase 5 AuditLog → Phase 6 Persistence → Phase 8 re-export cleanup)
**Total bugs found:** 6 (1 pre-existing regression exposed + 5 scope/partial-grep misses)
**Process:** Supervisor + Coder + Debugger trio per implementationLoop.md. Specs audited before implementation (30 spec-bugs found and fixed pre-implementation).

---

## 1. Code Quality Grade: A- (92/100)

### Justification

The extraction is clean and well-tested. runtime.py dropped from 2382 → 1995 lines (−16.2%) across 4 phases with zero functional regressions. The spec-audit-first approach (auditing specs before delegating to Coder) caught 30 spec inaccuracies pre-implementation, including a critical scope error in Phase 8 (the dispatch dicts are infrastructure, not aliases). The partial-grep pattern recurred twice (Phase 6 and Phase 8) — both times the supervisor missed references in `ui/handlers/` because greps were scoped to `tests/` and `agent/`. The pre-existing Phase B6 streaming regression (dead `_PROVIDER_STREAMERS` patches) was exposed and fixed as a side effect.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | All 112 affected tests pass. -1 for the 2 partial-grep misses that reached the auditor before the supervisor caught them. |
| Architecture compliance | 10/10 | New modules in agent/ layer, pure Python, no circular deps. ARCHITECTURE.md updated. |
| Test coverage         | 9/10 | 15 new tests (7 audit + 8 persistence). 10 streaming tests migrated from dead mocks to live mocks. -1 for the 3 TestStreamingUsageCapture tests that were silently broken since Phase B6. |
| Documentation         | 9/10 | ARCHITECTURE.md §3.21m updated. Specs written with full discovery blocks. -1 for stale docstring comments referencing old underscore names. |
| Maintainability       | 9/10 | Clean module boundaries. Direct imports replace alias chains. -1 for the retained `_PROVIDER_STREAMERS` dead dict (correctly deferred, but still dead code). |
| DX (Developer Exp.)   | 9/10 | runtime.py at 1995 lines is significantly more navigable. Each extracted module is independently testable. -1 for the spec-to-implementation gap that required audit revisions. |
| **Total**             | **92/100** | **A- — Strong execution, effective spec-first process, partial-grep is the recurring weakness.** |

---

## 2. What's Good About the Code

1. **Spec-audit-first approach.** Auditing all 4 specs BEFORE delegating to Coder caught 30 spec inaccuracies, including the critical Phase 8 scope error (dispatch dicts are infrastructure, not aliases). This saved at least 2 failed implementation rounds. The spec audit is now a mandatory step in the loop for multi-phase work.

2. **Verbatim-move discipline.** AuditLog (Phase 5) and Persistence (Phase 6) were moved character-for-character from runtime.py. The auditor verified line-by-line that no logic changed. Signatures match exactly. This is the safest extraction pattern — zero behavior change by construction.

3. **Repo-wide sweep lesson applied.** After Phase 6's partial-grep miss (production handler at `ui/handlers/agent_runtime_handler.py:565`), Phase 8's verification included a repo-wide `grep -rn` sweep that found 3 more missed references. The lesson was applied within the same loop — the supervisor learned and adapted mid-loop.

---

## 3. What's Bad About the Code

1. **`_PROVIDER_STREAMERS` is dead infrastructure.** The dict at runtime.py:185 is never read by production code (dispatch migrated to `_get_provider(caller_key).stream` in Phase B6). It exists only for `scripts/audit_*.py` backward compat. It should be removed in a future cleanup phase.
   - Evolution suggestion: Update the 2 audit scripts to use the registry directly, then remove the dict and its `__all__` entry.

2. **Partial-grep pattern recurred twice.** Phase 6 missed `ui/handlers/agent_runtime_handler.py` (production `/compact` path). Phase 8 missed the same handler (`_friendly_error_message`) plus 2 test files. Both times the supervisor's grep was scoped to `tests/` and `agent/` instead of the full repo.
   - Evolution suggestion: Add a mandatory "repo-wide grep sweep" verification step to the supervisor's checklist. The command is always `grep -rn "old_name" --include="*.py" . | grep -v __pycache__`.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| S1 | spec | CRITICAL | Phase 8 proposed removing `_PROVIDER_CALLERS` which is active dispatch infrastructure | Debugger (spec audit) | Supervisor (rescoped Phase 8 to defer) |
| S2 | spec | HIGH | Phase 4 missed `TestRuntimeReexport` in test_llm_cost.py | Debugger (spec audit) | Supervisor (added to spec) |
| S3 | spec | HIGH | Phase 6 missed test_low2_file_sandbox.py (24 refs) | Debugger (spec audit) | Supervisor (added to spec) |
| 1 | 6 | HIGH | Production handler `_save_conversation_to_disk` import → silent data loss on `/compact` | Debugger (code audit) | Supervisor (1-line fix) |
| 2 | 6 | MEDIUM | 12 tests in test_agent_runtime.py broken by stale imports | Debugger (code audit) | Supervisor (sed-based fix) |
| 3 | 8 | MEDIUM | Production handler `_friendly_error_message` import broken | Supervisor (repo-wide sweep) | Supervisor (1-line fix) |
| 4 | 8 | MEDIUM | test_runtime_fallback.py + test_llm_convert.py broken by stale imports | Supervisor (repo-wide sweep) | Supervisor (fixed) |
| 5 | 8 | MEDIUM | 7 TestStreaming tests silently broken since Phase B6 (dead `_PROVIDER_STREAMERS` patches → real HTTP 401) | Debugger (code audit) | Coder (4 tests) + Supervisor (3 tests) |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `partial-grep` | 4 | Supervisor scoped greps to tests/+agent/, missed ui/handlers/ and other test files |
| `pre-existing-regression` | 1 | Phase B6 left 7 streaming tests with dead mock patterns |
| `spec-scope-error` | 1 | Phase 8 initially proposed removing active dispatch infrastructure |

---

## 5. Process: What Worked

1. **Spec auditing before implementation.** Debugger's spec audit found 30 issues across the 4 specs. The most critical (Phase 8 scope error) would have caused a runtime NameError if implemented as written. Fixing specs before delegating to Coder saved 2+ failed implementation rounds.

2. **Repo-wide grep sweep.** After Phase 6's miss, adding `grep -rn "old_name" --include="*.py" .` to the verification checklist caught 3 more missed references in Phase 8 before the auditor had to find them.

3. **Verbatim-move verification.** For each extraction, the auditor verified the moved code was character-identical to the original. This is the strongest guarantee against silent logic changes during refactoring.

---

## 6. Process: What Didn't Work

1. **Partial-grep scope.** The supervisor consistently scoped greps to "likely" directories (tests/, agent/) instead of the full repo. This missed ui/handlers/ twice. The lesson was learned mid-loop (Phase 6) but the fix (repo-wide sweep) wasn't applied until Phase 8's verification.
   - Lesson: ALWAYS grep the full repo after any rename. `grep -rn "old_name" --include="*.py" .` is non-negotiable.

2. **Pre-existing test regressions hidden by selective test runs.** The 7 broken TestStreaming tests were silently failing since Phase B6 (~24 hours) because nobody ran `pytest tests/test_agent_runtime.py::TestStreaming` after the B6 streaming dispatch migration. The "tests pass" claim was always scoped to a subset.
   - Lesson: after any dispatch-mechanism change, run the FULL test class that exercises that dispatch, not just the subset that was modified.

---

## 7. What the Code Actually Does (End-User Impact)

1. **runtime.py is 1995 lines (was 2382).** The file is more navigable, with clear import boundaries to `agent/audit.py`, `agent/persistence.py`, and `agent/llm/*`. Developers can find and modify persistence logic without scrolling through 280 lines of disk I/O embedded in the runtime.

2. **`/compact` no longer silently loses data.** The Phase 6 production bug (agent_runtime_handler.py imported `_save_conversation_to_disk` from the wrong module after extraction) would have caused compacted conversations to not persist. Fixed before it reached users.

3. **Streaming tests actually test streaming.** The 7 tests that were silently making real HTTPS calls (and passing only in environments with valid API keys) now use proper mocks. CI will catch streaming regressions regardless of API key availability.

---

## 8. Pre-Existing Issues Flagged

1. **`_PROVIDER_STREAMERS` dict is dead code.** Defined at runtime.py:185, never read by production code since Phase B6. Retained for `scripts/audit_*.py` backward compat. Not caused by this work — exposed by it.
2. **`TestLocalAgentDrawerEmissions` BUG #14.** 1 pre-existing test failure unrelated to this work (drawer emissions).

---

## 9. Evolution Suggestions

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Remove `_PROVIDER_STREAMERS` dead dict (update 2 audit scripts first) | 2 hours | Eliminates dead code, removes confusion about dispatch path |
| Remove `_PROVIDER_CALLERS` dispatch dict, replace with registry-only validation | 4 hours | Completes the provider-abstraction migration started in Phase B4 |
| Add a CI check that runs `TestStreaming` + `TestStreamingUsageCapture` on every PR | 1 hour | Prevents silent streaming regressions |
| Extract `_is_empty_content` + `_format_chunks_for_llm` to agent/llm/ or agent/context.py | 2 hours | Further reduces runtime.py toward the ~1,090 target |

---

## 10. Lessons Learned

1. **Repo-wide grep is non-negotiable after any rename.**
   - Trigger: any function/variable rename or extraction
   - Action: `grep -rn "old_name" --include="*.py" . | grep -v __pycache__`

2. **Spec-audit before implementation saves failed rounds.**
   - Trigger: writing a spec for a multi-file extraction
   - Action: delegate the spec to the auditor for a spec-only probe before delegating to the builder

3. **Run the FULL test class after dispatch changes, not just the modified subset.**
   - Trigger: any change to how providers/streamers are dispatched
   - Action: `pytest tests/test_agent_runtime.py::TestStreaming tests/test_agent_runtime.py::TestStreamingUsageCapture`

---

## 11. Sign-off

- [x] Code committed (via review layer accept commits)
- [ ] Pushed to remote (deferred — PM to push)
- [x] All post-loop verification commands run (112/112 affected tests pass)
- [x] Captain notified with summary (this post-mortem)
- [x] Tier 2+ backlog updated (§9 Evolution Suggestions)
- [x] ARCHITECTURE.md §3.21m updated with new modules and line count
- [x] `.crabcakes/context.md` updated with loop status
