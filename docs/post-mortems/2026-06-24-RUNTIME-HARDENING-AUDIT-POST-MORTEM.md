# Runtime Hardening Audit Post-Mortem

**Date:** 2026-06-24
**Supervisor:** Qaster
**Builder:** QTR
**Commits:** 4 (dddabdc, 231e4e3, 758a2e4, 4988c8b)
**Phases:** 7 (helpers+blocking → streaming → tests → dead code → stuck-pop → SSE helper → list_conversations)
**Total bugs found:** 3 (2 CRITICAL, 1 MEDIUM)
**Process:** Pre-implemented phases audited by supervisor, QTR delegated for remaining phases, adversarial audit after every phase

---

## 1. Code Quality Grade: A- (92/100)

### Justification

The implementation is clean, minimal, and correct. The two CRITICAL bugs (system prompt duplication and system-as-user-role in streaming) were genuine production-breaking defects that would have caused every Anthropic streaming request with tool history to fail. The fixes are textbook single-source-of-truth refactors: extract the conversion logic into helpers, call them from both paths. Dead code cleanup removed 12 lines of cruft (Phase 4) and 15 lines of dead stuck-message handling (Phase 5). The MiniMax SSE helper extraction (Phase 6) is a clean DRY refactor. The `list_conversations` optimization (Phase 7) delivers a 5.2× speedup. QTR demonstrated excellent spec-drift detection, correctly anchoring to identifiers rather than stale line numbers in 5 out of 7 phases. Two minor spec items (W5 unused `dataclass`/`field` import, W6 unused `ToolCallStatus`) were correctly identified as out-of-scope for the phase instructions but remain in the codebase — deducted for completeness.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | All 7 phases pass adversarial audit. 2 critical bugs found and fixed in Phase 1. |
| Architecture compliance | 10/10 | No ARCHITECTURE.md violations. Single source of truth for Anthropic conversion. |
| Test coverage         | 9/10  | 70 tests pass. 3 new streaming regression tests. 1 test correctly deleted (dead code test). |
| Documentation         | 8/10  | Spec drift documented thoroughly. QTR's COMPLETENESS reports are exemplary. |
| Maintainability       | 9/10  | DRY helper extraction. Dead code removed. Variable naming improved. |
| DX (Developer Exp.)   | 9/10  | Clean diffs, minimal blast radius per phase, fast verification cycles. |
| **Total**             | **92/100** | **A- — Excellent** |

Deducted points:
- 1 Correctness: W5 (`from dataclasses import dataclass, field`) and W6 (`ToolCallStatus`) remain in codebase — correctly out of scope for phase instructions but listed in spec acceptance criteria
- 1 Test coverage: No direct test for `list_conversations` with on-disk files (QTR ran smoke tests but did not add a permanent regression test, per spec instruction "Do NOT add tests")
- 1 Documentation: Spec line numbers drifted significantly across phases; spec was not updated to reflect post-implementation line numbers
- 1 Maintainability: `_run_loop` remains a 335-line god-function (correctly out of scope, but noted)

---

## 2. What's Good About the Code

1. **Single source of truth for Anthropic conversion:** `_convert_messages_for_anthropic()` and `_convert_tools_for_anthropic()` are module-level helpers called from both `_call_anthropic` (line 384/394) and `_stream_anthropic_events` (line 718/729). Before this work, the streaming path had zero conversion — raw OpenAI-format messages went straight to Anthropic. Now both paths share identical conversion logic. (agent/runtime.py:284-394, 718-729)

2. **DRY SSE delta parsing:** `_parse_sse_delta()` (line 475) eliminates 22 lines of duplicated text/tool_call extraction across `_stream_openai_events` and `_stream_minimax_events`. The helper is narrowly scoped — it handles only text and tool_call deltas, leaving `finish_reason`/`usage` handling inline where it belongs (OpenAI and MiniMax signal completion differently). This is a textbook "extract the shared part, leave the divergent part" refactor. (agent/runtime.py:475-501)

3. **Defensive `list_conversations` lightweight read:** The new implementation (line 2270) catches three exception types (`JSONDecodeError`, `OSError`, `UnicodeDecodeError`), defaults to `"unknown"` on any failure, and avoids full Conversation deserialization. A corrupt file in the conversations directory no longer crashes the entire listing — it returns `"unknown"` for that file and continues. The 5.2× speedup (30ms → 6ms per call) is a real win for users with many saved conversations. (agent/runtime.py:2270-2289)

---

## 3. What's Bad About the Code

1. **Two unused imports remain in the codebase:** `from dataclasses import dataclass, field` (line 25) and `ToolCallStatus` (line 1747) are imported but never used. These are listed in the spec (W5, W6) and appear in the acceptance criteria, but were not included in the Phase 4 instructions. QTR correctly flagged them as out-of-scope. They should be removed in a follow-up.
   - Evolution suggestion: Remove both unused imports in a trivial cleanup commit. Estimated: 2 minutes.

2. **Spec line number drift:** The spec (SPEC-RUNTIME-HARDENING-AUDIT.md) hardcodes line numbers that drifted significantly across 7 phases of edits. QTR encountered spec drift in 5 of 7 phases, requiring identifier-based anchoring instead. The spec was not updated post-implementation to reflect final line numbers, making it a stale reference for future work.
   - Evolution suggestion: Add a "Post-Implementation Line Index" appendix to the spec after each loop, or reference identifiers only in spec text. Estimated: 30 minutes.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | Phase 1 | CRITICAL | `_call_anthropic` sends system prompt TWICE — once via `payload["system"]`, once as a user-role message in `api_messages` | Qaster (adversarial audit) | QTR (1 commit) |
| 2 | Phase 1 | CRITICAL | `_stream_anthropic_events` sends system prompt as USER role message instead of extracting it to `payload["system"]` | Qaster (adversarial audit) | QTR (1 commit) |
| 3 | Phase 1 | MEDIUM | `_convert_tools_for_anthropic` accesses `t["function"]["parameters"]` without `.get()`, causing KeyError on tools without parameters | Qaster (adversarial audit) | QTR (1 commit) |

All three bugs were found during the Phase 1 adversarial audit, before any code was committed. No bugs compounded downstream — they were caught and fixed in-phase. The streaming path bugs (#1, #2) would have caused every Anthropic streaming request with a system prompt to behave incorrectly. Bug #3 would have crashed on any tool definition missing a `parameters` key. All three were fixed immediately and verified with the full test suite.

Phases 2-7 produced zero bugs. QTR's implementations were clean on first delivery for every subsequent phase, and the supervisor's independent adversarial audit confirmed this each time.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `system-prompt-mishandling` | 2 | System prompt sent twice / sent as wrong role — both in Anthropic path |
| `missing-defensive-access` | 1 | Dict key access without `.get()` on optional field |

---

## 5. Process: What Worked

1. **Phase-by-phase adversarial audit with independent verification:** The supervisor independently verified every QTR claim using grep, py_compile, pytest, and functional smoke tests. This caught that Phase 1's implementation had two critical bugs that QTR's initial delivery missed. After the fix, the supervisor re-verified with payload parity tests (blocking vs streaming key comparison) to confirm behavioral equivalence.

2. **Identifier-anchored spec drift handling:** QTR consistently anchored edits to function names and identifiers rather than spec line numbers, which had drifted by 20-50 lines across phases. This prevented wrong-line edits in every phase from 4 onward. The supervisor's audit confirmed this approach worked — no edits were applied to wrong locations.

3. **Narrow helper scope in Phase 6:** QTR chose the narrower `_parse_sse_delta(d)` helper (text + tool_call only) over the spec's broader `_process_openai_compatible_sse(ev)` helper (which would have included finish_reason/usage). The narrower scope was correct because OpenAI and MiniMax handle completion signaling differently. The supervisor's audit confirmed this was the right call — forcing both functions into identical post-parse control flow would have introduced bugs.

---

## 6. Process: What Didn't Work

1. **Spec acceptance criteria included items not in phase instructions:** The spec's §10.3 pattern sweep includes W5 (unused `dataclass`/`field`) and W6 (unused `ToolCallStatus`) as acceptance criteria, but the Phase 4 instructions did not include these items in their 5-step scope. QTR correctly flagged them as out-of-scope, but this created a gap between "spec says done" and "phase instructions say done." The supervisor had to manually verify these remained unfixed and note them as follow-up work.
   - Lesson: The spec author should ensure that every acceptance criterion item maps to at least one phase instruction. Or: the phase instructions should explicitly state which acceptance criteria items are deferred and why.

2. **Spec line numbers became stale across 7 phases:** The spec hardcoded line numbers from the pre-implementation codebase. After 7 phases of edits (net -33 lines), every line number in the spec was wrong by 20-60 lines. QTR handled this correctly (5 of 7 phases had spec drift notes), but it added overhead to every delegation.
   - Lesson: Specs should reference identifiers (function names, variable names) instead of line numbers. When line numbers are unavoidable, add a "line numbers are approximate — anchor to identifiers" disclaimer at the top of the spec.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Anthropic streaming with tool history now works:** Before this work, any streaming request to Anthropic that included tool call history (assistant messages with `tool_calls`, or `tool` role messages) would be rejected by the API — the messages were in OpenAI format, not Anthropic format. Now, both the streaming and blocking paths convert messages and tools to Anthropic format via shared helpers. A user having a tool-using conversation with Claude in streaming mode will see correct responses instead of API errors. Code path: `_run_loop` → `_call_llm` → `_call_llm_streaming` → `_stream_anthropic_events` → `_convert_messages_for_anthropic` / `_convert_tools_for_anthropic` (agent/runtime.py:718-729).

2. **`list_conversations` is 5.2× faster:** Users with many saved conversations will notice snappier conversation listing. The function now reads only the `agent_name` field from each JSON file instead of fully deserializing every Conversation object with all messages, tool calls, and API key resolution. Code path: `list_conversations` → `json.load(f)` → `data.get("agent_name")` (agent/runtime.py:2270-2289).

3. **Corrupt conversation files no longer crash listing:** If a conversation JSON file is corrupt, malformed, or non-UTF8, `list_conversations` returns `"unknown"` for that file and continues listing the rest. Before this work, the behavior depended on `_load_conversation_from_disk`'s exception handling, which caught `JSONDecodeError` and `OSError` but not `UnicodeDecodeError`. Now all three are caught explicitly.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **`_run_loop` is a 335-line god-function:** The spec explicitly lists refactoring this as P3 out-of-scope work (§8). It was pre-existing before this audit and was not modified in any phase except for the dead code removal (empty `finally:pass`, duplicate import). Not in scope. Will be addressed in a future spec.

2. **Unused imports `dataclass`, `field` (line 25) and `ToolCallStatus` (line 1747):** Pre-existing on HEAD before this work. Listed in spec acceptance criteria (§10.3) but not included in any phase instructions. Correctly deferred by QTR. Should be removed in a trivial follow-up commit.

3. **No permanent regression test for `list_conversations` with on-disk files:** The spec says "Do NOT add tests" for Phase 7. QTR ran functional smoke tests (7 cases) but these are not permanent. A follow-up test should be added to prevent regression of the lightweight-read optimization.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Remove unused `dataclass`/`field` and `ToolCallStatus` imports | 2 min | Cleaner imports, passes spec acceptance criteria |
| Add permanent regression test for `list_conversations` lightweight read | 30 min | Prevents regression of W13 optimization |
| Refactor `_run_loop` into sub-methods (`_execute_tool_calls`, `_handle_text_response`, `_handle_fallback`) | 1-2 days | Maintainability — 335-line function is hard to read and test |
| Update spec with post-implementation line numbers or identifier-only references | 30 min | Prevents spec drift in future loops |
| Consolidate `_call_openai`/`_call_minimax`/`_call_anthropic` into generic `_call_provider(payload_builder)` | 1 day | Reduces code duplication across provider callers |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Spec acceptance criteria must map to phase instructions:**
   - Trigger: Writing a multi-phase spec where acceptance criteria span all phases
   - Action: Before starting Phase 1, verify every §10.3 acceptance criterion item appears in at least one phase instruction file. If an item is intentionally deferred, state so explicitly in the phase instructions.

2. **Specs should use identifiers, not line numbers:**
   - Trigger: Writing any spec that references code locations
   - Action: Reference function names, class names, and variable names instead of line numbers. When line numbers are unavoidable, prefix with "approximately" and add a spec-level note that line numbers drift across phases.

3. **Dead code tests must be deleted with their code (Rule 5a enforcement):**
   - Trigger: Removing production code that has dedicated tests
   - Action: Delete the test in the same phase. Document the deletion in the COMPLETENESS report with the rationale (which Rule 5a clause applies). The supervisor's audit must verify the test count change is correct.

4. **Payload parity testing catches conversion bugs:**
   - Trigger: Auditing a refactor that extracts shared logic from two divergent code paths
   - Action: Write a functional test that captures the actual HTTP payload from both paths and compares them field-by-field. This is more powerful than unit tests on individual helpers because it verifies the wiring is correct end-to-end.

---

## 11. Sign-off

- [x] All 7 phases implemented and audited clean
- [x] All verification commands run independently by supervisor (py_compile, pytest, grep pattern sweep, functional smoke tests)
- [x] 70 tests pass, 3 deselected (pre-existing TestApproval hang)
- [x] Post-mortem written and committed
- [ ] Captain notified with summary
- [ ] Follow-up: remove W5/W6 unused imports (2 min)
- [ ] Follow-up: add permanent `list_conversations` regression test (30 min)
