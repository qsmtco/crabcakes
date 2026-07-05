# Empty Assistant Message HTTP 400 (Cohere) Post-Mortem

**Date:** 2026-07-05
**Severity:** High (provider-specific failure blocking supervisor functionality)
**Trigger:** Supervisor agent → Cohere (north-mini-code:free) → HTTP 400 "messages.0: must have non-empty content or tool calls"
**Detection:** Audit by user; logged in `docs/audits/2026-07-05-EMPTY-ASSISTANT-COHERE-400-READ-ONLY.md`
**Status:** ✅ FIXED (Phases 1–3 shipped 2026-07-05)
**Commits:** `4d210bb5`, `0ed7afa9`, `654bc20`

---

## 1. Code Quality Grade: A (92/100)

### Justification

The implementation is a textbook defense-in-depth fix: two independent guards (read-side filter + write-side guard) backed by five targeted regression tests. The spec was authored before implementation using `steelFramedSpecWriter.md`, and each phase had explicit verification gates (V1–V8). The phase boundaries were respected exactly — each commit is independently revertable.

The main deduction is for spec drift: the spec's §2 File 1 referenced the ASSISTANT branch at lines 244–258, but the actual pre-Phase-1 location was lines 246–260 (+2 line drift). This was caught during Phase 1 implementation and worked around by anchoring to the identifier `elif msg.role == MessageRole.ASSISTANT` rather than line numbers. Phase 4 corrects the spec in place.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 20/20 | All 6 functional criteria met, all tests pass |
| Architecture compliance | 10/10 | Wire-boundary filter in `to_api_messages()`, write guard at create-site |
| Test coverage         | 9/10  | 5 regression tests; no E2E provider test (out of scope) |
| Documentation         | 9/10  | Spec, post-mortem, audit updated; spec drift corrected in Phase 4 |
| Maintainability       | 10/10 | Minimal edits, clear comment blocks, two-layer defense |
| DX (Developer Exp.)   | 8/10  | Two placeholder strings may confuse string-match searches; documented |
| Process               | 6/10  | Spec drift of +2 lines; related bug at line 2290 deferred not flagged in spec |
| **Total**             | **92/100** | A — "Ship without hesitation" |

Deducted points:
- 1 Test coverage: No E2E provider round-trip test (B2 acceptance criterion is operator-run, not automated).
- 1 Documentation: Spec drift not caught at spec authoring time.
- 2 DX: Two distinct placeholder strings require documentation to avoid confusion.
- 2 Process: Spec drift (+2 lines) and §5 class-name drift (`TestToApiMessagesEmptyAssistantGuard` vs actual `TestConversationToApiMessages`) indicate the spec was written against a slightly stale codebase snapshot.

---

## 2. Reproduction (provider matrix)

| Provider | Result | Why |
|----------|--------|-----|
| Cohere (north-mini-code:free) | ❌ HTTP 400 | Strict schema validation rejects `{"role":"assistant","content":""}` |
| OpenAI (gpt-4, mini) | ✅ Accepts (silently) | Tool calls path tolerates empty content; some models accept |
| Anthropic (Claude 3.x) | ⚠️ Strict mode rejects | Anthropic strict-tool-loop enforces "must have non-empty content or tool calls" |
| M-series (m2.7) | ✅ Accepts (silently) | Permissive, no schema validation |

**Conclusion:** A defect that affects 2 of 4 production providers (Cohere, Anthropic strict). The fix is provider-agnostic — the placeholder substitution fires regardless of which provider is configured.

---

## 3. Root Cause

### 3.1 Trigger path

The supervisor agent's conversation file (`~/.config/crabcakes/conversations/special:supervisor.json`) accumulated a corrupt message at index 262 with `timestamp: 2026-07-04T17:47:09` — approximately 15 hours before the fix work began. The corrupt message was `{"role": "assistant", "content": "", "tool_calls": []}`.

### 3.2 The bug

`agent/runtime.py:2214` (pre-fix) called `conv.add_assistant_message("", [])` whenever an LLM returned no `text_content` AND no `choices`. The empty string was persisted to disk via `_auto_save`. On subsequent calls, `Conversation.to_api_messages()` had no filter and emitted the corrupt `{"role":"assistant","content":""}` to the wire. Strict providers rejected this with HTTP 400.

### 3.3 Why it slipped through

- `runtime.py:2214` was added as a defensive path for "LLM returned nothing" — the intent was to record SOMETHING so the conversation history preserved the error state.
- The empty-string + empty-list combination was chosen as "least surprise" — it represents "the assistant said nothing," which is literal truth but semantically corrupt for the API.
- `to_api_messages()` had no filtering logic — every message was serialized as-is.
- No test covered `Message(role=ASSISTANT, content="")` case — happy paths only.
- The bug was provider-specific: M-series and permissive OpenAI didn't catch it, so it slipped through developer testing. Production users using Cohere or Anthropic strict tripped immediately.

---

## 4. Fix (Phases 1–3)

### 4.1 Phase 1 — read-side filter

`models/conversation.py:to_api_messages()` ASSISTANT branch (line 250 post-fix). When `not msg.content and not msg.tool_calls`, substitute the placeholder string `"[assistant returned no content — placeholder]"` and emit a warning log. Defense-in-depth: catches any corrupt message regardless of source.

Commit: `4d210bb5fccea9fb47c694b0d70891cd98c2ba3e` ("Accept: models/conversation.py")
Δ: +37/-13 lines, file 452 → 476 lines (added `import logging`, `_logger`, new branch logic)

### 4.2 Phase 2 — write-side guard

`agent/runtime.py:2222` (was line 2214 pre-fix). Replace `conv.add_assistant_message("", [])` with `conv.add_assistant_message("[LLM returned no choices and no content — provider error or malformed response]", [])`. Persists a descriptive placeholder instead of empty string. Keeps `logger.warning(...)`, `self._dispatch(self._on_error, ...)`, `self._auto_save(...)`, and `return` unchanged.

Commit: `0ed7afa9c4465bb1df9b1ea62695439b5bf136a1` ("Accept: agent/runtime.py")
Δ: +11/-1 lines

### 4.3 Phase 3 — regression tests

`tests/test_conversation.py::TestConversationToApiMessages` gained 5 new tests (added to existing class, not a separate class):

1. `test_empty_assistant_message_substitutes_placeholder` — locks in placeholder substitution
2. `test_empty_assistant_message_logs_warning` — locks in WARNING log with idx info
3. `test_assistant_message_with_only_tool_calls_does_not_substitute` — regression guard (placeholder must NOT fire when tool_calls is non-empty)
4. `test_assistant_message_with_only_content_does_not_substitute` — regression guard (placeholder must NOT fire on normal text)
5. `test_corrupt_message_mid_sequence_uses_correct_index_in_warning` — locks in idx=2 for corrupt at mid-sequence position

Commit: `654bc2038d789d4086ffed49bff0432995386210` ("Accept: tests/test_conversation.py")
Δ: +77 lines, 0 deletions (zero modifications to existing tests)

---

## 5. Test Results

| Test | Before | After |
|------|--------|-------|
| Total `tests/test_conversation.py` | 60 pass | 65 pass |
| `TestConversationToApiMessages` tests | 7 | 12 (7 unchanged + 5 new) |
| `tests/test_agent_runtime.py -k "not approval"` | unknown | 94 passed, 3 deselected |
| Full project test suite (`tests/ -k "not approval"`) | unknown | 2407 passed, 12 pre-existing failures (`test_improve.py`, `test_mcp_config.py` — unrelated) |

---

## 6. What's Good About the Implementation

1. **Spec-driven, phased delivery:** Master spec at `SPEC-EMPTY-ASSISTANT-MESSAGE-FIX.md` defined 4 phases with testable acceptance criteria. Each phase was independently auditable (V1–V8 verifications), preventing scope creep and ensuring each commit could be reverted if needed.
2. **Defense in depth:** Two layers (read-side filter + write-side guard) catch the same bug from different angles. The read-side filter is the safety net for corrupt messages from any source (compaction, hand-edits, future bugs). The write-side guard is the primary prevention. Both work together.
3. **Distinct placeholders for creation vs transit:** Phase 2's placeholder ("LLM returned no choices...") says "we know why this happened." Phase 1's placeholder ("assistant returned no content...") says "we found this corrupt, don't know why." Distinguishing these in logs makes future debugging easier.
4. **Regression tests, not just new tests:** Phase 3 added tests that lock in behavior (replace placeholder string in code → test 1 fails). The two regression-guard tests (3, 4) ensure the read-side filter doesn't over-fire.
5. **No infrastructure for write-side tests:** Phase 2 was intentionally not tested in `tests/test_conversation.py` because it requires faking `AgentRuntime` + mocking the LLM provider. That's heavy infrastructure for a 1-line edit. The user's audit verifies the runtime path by switching provider to Cohere (B2 acceptance criterion).
6. **Spec drift caught and documented:** The spec referenced ASSISTANT branch at lines 244–258; actual was 246–260 (+2 line drift). Caught during Phase 1 implementation, documented in this post-mortem. The spec is corrected in Phase 4.

---

## 7. What's Bad About the Implementation

1. **Spec drift of +2 lines:** Should have been caught at spec-writing time. The audit doc was written the same day but line numbers had drifted between original spec and actual file. Future specs should run `wc -l` on each referenced file at write time and double-check anchors immediately before dispatching.
2. **Related bug at line 2290 left unfixed:** `agent/runtime.py:2290` still calls `conv.add_assistant_message(text_content, [])` where `text_content` could be empty (if `choices` is non-empty). The Phase 2 guard only catches `not text_content AND not choices`. Caught by builder during Step 6.6 related-bug scan. Deferred as spec §10 item 6. Defense-in-depth (Phase 1 read-side filter) catches it, so no production impact.
3. **Two placeholder strings may confuse downstream parsing:** If a future feature searches conversation history for "exact-empty-assistant messages" by string match, the two placeholders create ambiguity. Distinct placeholders are correct for log discrimination but break simple string-equality checks. Document the two strings' meanings somewhere visible to anyone iterating on conversation parsing logic.
4. **§5 class-name drift in spec:** Spec §5 said tests would go in `TestToApiMessagesEmptyAssistantGuard` class; actual delivery put them in `TestConversationToApiMessages`. Decision: keep in existing class — splitting 5 tests into a new class is artificial. Spec updated in Phase 4.

---

## 8. Behavioral Verification (operator-runs)

### B1 — Stopgap script result

⚠️ Operator has not yet run the stopgap against `~/.config/crabcakes/conversations/special:supervisor.json`. The stopgap script is documented in `docs/audits/2026-07-05-EMPTY-ASSISTANT-COHERE-400-READ-ONLY.md` §4.1. With Phase 1's read-side filter shipped, the stopgap is no longer strictly necessary — the filter sanitizes the corrupt message at serialization time. But running it would eliminate the WARNING log on every supervisor call.

### B2 — Cohere retry test

⚠️ Operator has not yet verified Cohere does not 400 on subsequent calls. With Phase 1's read-side filter, the empty-content message is replaced with a placeholder at the wire boundary, so Cohere should no longer see `{"role":"assistant","content":""}`. Verification requires switching the supervisor model to `cohere/north-mini-code:free` and sending a test message.

---

## 9. Backlog

- **B-1 (spec §10 item 6):** `agent/runtime.py:2290` write-side guard tightening — when `text_content` is empty but `choices` is non-empty, the guard doesn't fire. Deferred; Phase 1 read-side filter provides defense-in-depth.
- **B-2 (spec §10 item 7):** `add_assistant_message` `ValueError` validation — rejected. Would break intentional empty-content test cases. See spec §10 item 7 for full rationale.
- **B-3 (spec §10 item 8):** Two placeholder strings — kept distinct for log discrimination. Re-evaluate if user reports confusion. See spec §10 item 8.

---

## 10. Process Improvements

1. **Spec line-anchoring:** Add a step to `steelFramedSpecWriter.md` that runs `wc -l` and `grep -n` on each referenced file before dispatching, so line-number drift is caught at spec time, not implementation time. This spec had +2 line drift that was only caught because the builder anchored to the identifier `elif msg.role == MessageRole.ASSISTANT` instead of the line number.
2. **Related-bug-scan as standard:** Builder's Step 6.6 found the line 2290 bug. This step should be explicitly highlighted in the standard Coder/Debugger prompts so related bugs are surfaced in every report, not just the ones the builder happens to notice.
3. **Distinguish transit vs creation placeholders:** The two-placeholder-string pattern from this work should be a documented pattern. If two event types (creation vs discovery) need to be distinguishable in logs, use distinct strings. Documented in this post-mortem §7.3 and spec §10 item 8.

---

## End of post-mortem.
