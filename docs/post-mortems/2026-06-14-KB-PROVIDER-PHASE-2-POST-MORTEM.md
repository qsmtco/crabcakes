# KB Provider Phase 2 — Per-Agent Fallback Wiring + LLM Synthesis Post-Mortem

**Date:** 2026-06-14
**Supervisor:** Qaster
**Builder:** QTR
**Commits:** 7 (6 auto-accept + 1 manual)
**Phases:** 6 (dataclass fields → wire create_conversation → config + normalize → runtime fallback chain → synthesis + system prompt → full verification)
**Total bugs found:** 1 (test_kb_integration regression, fixed by supervisor)
**Process:** Standard implementation loop via /ask @QTR on crabcakes CLI. All 6 phases delegated sequentially with file-based instructions.

---

## 1. Code Quality Grade: A- (91/100)

### Justification

Clean implementation across 6 phases. QTR correctly scoped each phase, didn't leak changes across phase boundaries, and updated tests to match new behavior. The supervisor caught 1 regression (test_kb_integration) where the test created Conversation directly without fallback fields — a legitimate gap in the spec's test coverage. ARCHITECTURE.md was updated to reflect the new per-agent fallback architecture.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | 1 test regression caught and fixed in-phase |
| Architecture compliance | 10/10 | No boundary violations. kb_lookup imported in agent/ (allowed). |
| Test coverage         | 9/10  | test_kb_integration needed manual fix; all other tests updated by QTR |
| Documentation         | 9/10  | ARCHITECTURE.md updated; auxilium.md Phase 2 section added |
| Maintainability       | 10/10 | Clean separation: per-agent fallback, global default, synthesis layer |
| DX (Developer Exp.)   | 10/10 | 1593/1594 tests pass; clear error messages |
| **Total**             | **91/100** | **A-** |

Deducted points:
- 1 Correctness: test_kb_integration regression (test created Conversation without fallback fields)
- 1 Test coverage: spec didn't flag test_kb_integration as needing updates

---

## 2. What's Good About the Code

1. **Per-agent fallback architecture:** Fallback is now per-agent (conv.fallback_provider) instead of global (self._config.fallback_provider). Each agent YAML can specify its own fallback, and the global AgentConfig.fallback_provider serves as a default. This is a clean evolution of the architecture. `agent/runtime.py:1183-1192`

2. **Phase 2 synthesis with graceful degradation:** The kb_lookup pre-fetch in _run_loop() is wrapped in try/except and only fires when conv.fallback_provider is set. If kb_lookup fails (model not loaded, index missing), the fallback LLM still works without grounding. `agent/runtime.py:1120-1127`

3. **Simplified fallback_model derivation:** The old code derived fallback_model from provider name + default_model. The new code uses conv.fallback_model directly (the full model string from YAML), falling back to conv.fallback_provider. Simpler, more explicit. `agent/runtime.py:1192`

4. **Model restoration in finally block:** The fallback chain saves original_model before the try and restores it in finally, ensuring the conversation model is always restored even if the fallback call fails. `agent/runtime.py:1191,1215`

5. **Test helper updated correctly:** QTR updated test_runtime_fallback.py's _setup_conversation to propagate fallback fields from AgentConfig to Conversation, matching production wiring. `tests/test_runtime_fallback.py:82-91`

---

## 3. What's Bad About the Code

1. **kb_lookup import at module level in runtime.py:** The `from agent.kb_lookup import kb_lookup` import is at the top of runtime.py (line 32). kb_lookup lazy-loads the sentence-transformers model on first call, so the import itself is cheap, but it means runtime.py now has a hard dependency on sentence-transformers. Previously, only kb_server.py imported kb_lookup. This is architecturally acceptable (agent/ can import from agent/) but adds a dependency to the runtime module. If sentence-transformers is not installed, the import will fail at module load time, not at call time.
   - Evolution suggestion: Consider lazy-importing kb_lookup inside the _run_loop function instead of at module level, matching the pattern used for KB_OUT_OF_SCOPE.

2. **KB context injection modifies messages in-place:** The fallback chain creates `messages_with_context = list(messages)` (a shallow copy) and then modifies the dict entries. Since the messages list contains dicts, the shallow copy means the original dict objects are shared. If the fallback modifies a dict that's also referenced by the original `messages` list, it could affect subsequent iterations. In practice, the fallback is a one-shot operation (guarded by `_fallback_attempted`), so this doesn't cause bugs today. But it's fragile.
   - Evolution suggestion: Deep-copy the messages dicts when injecting KB context.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 6 | MEDIUM | test_kb_integration::test_fallback_chain_end_to_end fails — creates Conversation directly without fallback fields, so conv.fallback_provider is None and fallback chain never fires | Qaster (adversarial audit) | Qaster (1 line added to test) |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| test-data-drift | 1 | Test created Conversation directly, bypassing create_conversation() wiring, so new fields weren't populated |

---

## 5. Process: What Worked

1. **File-based delegation:** Writing all 6 phases to SPEC-KB-PROVIDER-PHASES.md upfront meant QTR had full context for each phase without truncation. Zero garbled messages.

2. **Sequential phase verification:** Each phase was independently verified before the next was delegated. The Phase 4 fallback chain change was verified to not break the Phase 3 config defaults.

3. **QTR's test updates:** QTR proactively updated test_runtime_fallback.py's _setup_conversation helper to match the new per-agent wiring. This caught the architectural shift early.

4. **Adversarial audit caught the gap:** The supervisor's post-implementation audit found the test_kb_integration regression that QTR's own tests didn't cover (because it's in a different test file).

---

## 6. Process: What Didn't Work

1. **Spec didn't flag test_kb_integration for updates:** The SPEC's test coverage section listed which test files to update but didn't include test_kb_integration.py. This is because the test creates Conversation directly (bypassing create_conversation), which is a pattern the spec didn't account for.
   - Lesson: When adding fields to Conversation, grep for ALL places that construct Conversation directly, not just create_conversation().

2. **Auto-accept layer didn't commit Phase 5-6 changes:** The review layer auto-accepted Phases 1-4 but the Phase 5-6 changes (kb_lookup import, _format_chunks_for_llm, auxilium.md update, test fixes) remained in the working tree and needed a manual commit.
   - Lesson: Verify the working tree is clean after all phases complete. Don't assume auto-accept committed everything.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Per-agent fallback:** When a user configures `fallback_provider: openrouter` in an agent's YAML, that agent will automatically retry with the OpenRouter provider when the KB can't answer a question. Previously, this required global config and was never wired correctly. Code path: `agent/special_agents.py:_load_registry()` → `agent/runtime.py:create_conversation()` → `Conversation.fallback_provider` → `_run_loop()` fallback chain at line 1183.

2. **LLM synthesis with KB grounding:** When the fallback fires, the runtime pre-fetches KB chunks via kb_lookup() and injects them as context into the fallback LLM's messages. The LLM synthesizes a conversational answer grounded in the KB content instead of answering from scratch. Code path: `agent/runtime.py:_run_loop()` lines 1120-1127 (pre-fetch) → lines 1198-1210 (injection).

3. **Graceful degradation:** If kb_lookup fails (no model, no index), the fallback LLM still works — it just answers without KB grounding. If the fallback provider is not configured, the user sees the raw KB_OUT_OF_SCOPE sentinel. No crashes.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **test_connection_sync_handler.py::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer** — Pre-existing failure confirmed on d04c6ee (before KB provider work). Not in scope.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Lazy-import kb_lookup inside _run_loop instead of module level | 1 hour | Removes hard dependency on sentence-transformers from runtime.py |
| Deep-copy messages dicts when injecting KB context | 30 min | Prevents potential mutation of shared dict objects |
| Add integration test for per-agent fallback with real agent YAML | 2 hours | Covers the full path: YAML → SpecialAgentDef → Conversation → fallback chain |
| Expand KB content (Tier 2: features.md, configuration.md, agents.md) | 2-3 days | More KB chunks = better synthesis quality |

---

## 10. Lessons Learned (Process Rules to Carry Forward)

1. **Grep for all Conversation constructions when adding fields:** When a dataclass gains new fields, grep the entire codebase for `Conversation(` — not just create_conversation(). Tests and helper functions that construct the dataclass directly also need updating.
   - Trigger: Adding fields to any dataclass that's constructed in multiple places
   - Action: `grep -rn "Conversation(" tests/ agent/ ui/` before delegating

2. **Verify working tree after auto-accept phases:** The review layer may not auto-commit all changes. Always check `git status` after the last phase.
   - Trigger: After final phase delegation completes
   - Action: `git status --short` and `git diff --stat HEAD` before writing post-mortem

---

## 11. Sign-off

- [x] Code committed and pushed to main
- [x] All post-loop verification commands run and pasted
- [x] Captain notified with summary
- [x] Tier 2+ backlog updated (4 items deferred)
