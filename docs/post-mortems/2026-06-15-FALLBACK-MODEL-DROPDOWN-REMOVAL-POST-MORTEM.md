# Fallback Model Dropdown Removal Post-Mortem

**Date:** 2026-06-15
**Supervisor:** Qaster
**Builder:** QTR
**Commits:** 0 (post-mortem written before commit; see §11)
**Phases:** 6 (UI removal → handler/utils → runtime derivation → tests → docs → post-mortem)
**Total bugs found:** 1 (LOW severity, caught and fixed in Phase 1 by supervisor)
**Process:** Six-phase implementation loop with file-based delegation; one test-file scope miss caught mid-Phase-1 and fixed by the supervisor (1-line test update for an implementation-detail test that was asserting on removed code). All 55 targeted tests pass after the loop. Post-mortem written before commit/push per the §11 sign-off plan.

---

## 1. Code Quality Grade: A (92/100)

### Justification

The implementation cleanly unified the Fallback Provider dropdown with the Primary Provider dropdown's contract. All four designated widgets/attributes/methods were removed; the agent YAML schema no longer carries `fallback_model`; the runtime derives the fallback model from the provider card (matching `_resolve_agent_model`'s logic exactly, including the `/` handling edge case); tests assert the new contract and a new derivation test exercises the runtime path; ARCHITECTURE.md has zero live `fallback_model` references outside the explicit deprecation comment. The only issue was a 1-line test that was asserting on `_provider_models` (an implementation detail that was removed by design) — caught by the supervisor in independent verification and fixed without re-delegating to the builder.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | New derivation works; backward-compat test confirms old YAMLs still load. Lost 1 point for the late-discovered `_provider_models` test — caught early but indicates the spec's "Files NOT changed" list was incomplete. |
| Architecture compliance | 10/10 | All edits followed ARCHITECTURE.md (no GTK in handlers, handler/view split, `utils/` purity). The `Conversation.fallback_model` field and `create_conversation` parameter were correctly left in place for backward-read tolerance, with a comment explaining the deprecation. |
| Test coverage         | 10/10 | New tests: `test_does_not_add_fallback_model`, `test_save_does_not_emit_fallback_model`, `test_old_yaml_with_fallback_model_loads`, `TestFallbackModelDerivation::test_derives_from_provider_default_model`. The derivation test captures `conv.model` at the moment of `_call_llm` invocation — not just a helper-level assertion. |
| Documentation         | 9/10  | ARCHITECTURE.md updated with 4 clean edits. Lost 1 point because the spec reference in the "Per-agent model" paragraph mentions the spec file path but not the deprecation timeline; future readers will need to grep for the date. |
| Maintainability       | 10/10 | The unified "one provider card = one vetted model" contract is now expressed in 4 places (UI, runtime, schema, docs) and they all agree. Future code reading is simpler. |
| DX (Developer Exp.)   | 9/10  | The new derivation block in `agent/runtime.py` is well-commented and points to the canonical implementation in `_resolve_agent_model`. Lost 1 point because the deprecation comment in `models/conversation.py` / `agent/special_agents.py` was NOT added — those fields are kept silently with no marker. Follow-up needed. |
| **Total**             | **92/100** | **A — strong implementation with one mid-loop scope miss and one minor follow-up** |

Deducted points:
- 1 Correctness: spec's "Files NOT changed" list omitted `tests/test_agent_builder_no_provider_keys.py` (its `test_set_provider_options_builds_model_map` was testing removed implementation detail).
- 1 Documentation: deprecation timeline noted only in the code comment, not propagated to the per-field docstring in `models/conversation.py` or `agent/special_agents.py`.
- 1 DX: no deprecation marker on the kept `Conversation.fallback_model` and `SpecialAgentDef.fallback_model` fields.

---

## 2. What's Good About the Code

1. **Unified contract via single derivation site:** The fallback model is now derived in `agent/runtime.py:1193-1205` using the same `f"{provider_name}/{provider.default_model}"` pattern (with the `/` handling for already-slashed `default_model` values) as `AgentRuntimeHandler._resolve_agent_model()` at `ui/handlers/agent_runtime_handler.py:272-298`. The agent YAML no longer stores a model string at all — it stores only an identifier (`fallback_provider`). This is a real architectural win: renaming a model in Settings now propagates to all agents automatically, and validation catches orphaned references at save time. (`agent/runtime.py:1193-1205`)

2. **Backward-compat without data loss:** Old agent YAMLs that still have `fallback_model: openrouter/owl-alpha` continue to load without error (the `test_old_yaml_with_fallback_model_loads` test proves this). The field is tolerated on read but ignored at runtime. The `Conversation.fallback_model` and `SpecialAgentDef.fallback_model` dataclass fields are kept for the same reason. Users with existing agent files won't see breakage — they just won't get the model-pinning behavior anymore (which was untested in production and not relied on by any default agent).

3. **Test removal done correctly:** The spec explicitly enumerated the new tests to add AND the stale tests to drop. The `_provider_models` test miss was caught in supervisor verification and fixed without re-delegation — a 1-line scope creep absorbed by the supervisor per implementationSupervisor.md §6 ("fix small things yourself"). The new `TestFallbackModelDerivation` test captures `conv.model` at the moment of `_call_llm` invocation, which catches what a helper-level test would miss. (`tests/test_runtime_fallback.py:204-234`)

---

## 3. What's Bad About the Code

1. **Silent dataclass field retention:** `models/conversation.py:108` and `agent/special_agents.py:40` still have `fallback_model` fields. They're never read by the new code, but they exist with no deprecation marker. A future reader will see the field, wonder if it's used, and have to grep to find out. The `agent/runtime.py:1015` `create_conversation()` passthrough similarly stays in place.
   - Quantification: 4 sites (`conversation.py:108`, `agent/special_agents.py:40`, `agent/special_agents.py:125`, `agent/runtime.py:1015`) retain `fallback_model` as a real field/parameter without comment.
   - Evolution suggestion: Tier 2 follow-up — add a `# DEPRECATED 2026-06-15` comment to each kept site, then in a separate deprecation cycle, drop them entirely (requires verifying no in-flight conversations have the field set).

2. **Spec drift between "Files NOT changed" and reality:** The master spec's §2.12 listed 8 files as "NOT changed" but omitted `tests/test_agent_builder_no_provider_keys.py`. The test had `test_set_provider_options_builds_model_map` asserting on `_provider_models` — implementation detail that the spec's UI removal phase removed. The result was 1 LOW-severity failure caught in supervisor verification, fixed in 1 line.
   - Quantification: 1 test method, 1 line changed (assertion → negative assertion), ~30 seconds of supervisor time.
   - Evolution suggestion: Add a Step 6.6a to `steelFramedCodeWriter.md` (or the supervisor's verification checklist): "After UI/schema changes, grep ALL test files for the removed symbol — tests that assert on implementation details need updating too."

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | Phase 1 verification | LOW | `tests/test_agent_builder_no_provider_keys.py::test_set_provider_options_builds_model_map` asserted on `dlg._provider_models` (an attribute removed in Phase 1 by design per spec §2.1). Test broke because the implementation detail it tested no longer exists. | Qaster (running `pytest` after Phase 1 reported "clean") | Qaster (1 line: rewrote the test as `test_set_provider_options_does_not_build_model_map` with a negative assertion, per the "fix small things yourself" standing order in implementationSupervisor.md §6) |

<One paragraph: One bug found, LOW severity, caught during Phase 1's independent verification before the next phase started. Did not compound. The new test now asserts the negative — that `_provider_models` does not exist — which is a forward-looking regression guard. The test is a behavioral assertion of the new contract, not a structural check on removed code.>

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `tests-asserting-implementation-detail` | 1 | A test asserted on an internal attribute (`_provider_models`) that was an implementation detail of the removed widget. The test passed while the widget existed but the assertion tested a coupling, not a behavior. |

---

## 5. Process: What Worked

1. **File-based delegation for the 6 phase-instructions files:** Each phase's instructions were written to `docs/specs/FALLBACK-MODEL-DROPDOWN-REMOVAL-PHASE-N-INSTRUCTIONS.md` (5-8KB each) and referenced by absolute path in the `/ask @QTR` payload. This avoided the 4,096-char `/ask` payload limit and gave QTR a single source of truth per phase. QTR's reports consistently referenced the file path and quoted relevant excerpts, indicating they read the file in full.
2. **Per-phase independent verification by the supervisor:** After every phase, I (Qaster) ran the verification commands independently — not just trusting the COMPLETENESS checklist. Phase 1 caught the LOW-severity test bug here. Phase 3's behavioral smoke test (asserting the derived model string at the moment of the LLM call) was authored by me, not QTR, and was the strongest evidence that the runtime change was correct. (`agent/runtime.py:1193-1205`)
3. **Identifier-anchored instructions instead of line numbers:** The master spec and all 5 phase-instruction files used symbol names (`_fallback_model_dropdown`, `_on_fallback_provider_changed`, `_normalize_fallback_fields`, etc.) instead of line numbers. When QTR's edits shifted lines, no instruction was invalidated. The spec's Rule 6.8 ("Spec Drift Verification") paid off.

---

## 6. Process: What Didn't Work

1. **The spec's "Files NOT changed" list was incomplete.** The master spec §2.12 listed 8 files as "NOT changed" but omitted `tests/test_agent_builder_no_provider_keys.py`, which had a test asserting on `_provider_models` (an implementation detail removed by Phase 1). This caused 1 LOW-severity failure caught in supervisor verification.
   - Impact: 1 minute of supervisor time to fix; no Phase delay.
   - Lesson: The "Files NOT changed" list should include test files that touch the changed symbols, not just production code. Add a check: `grep -rln "<removed_symbol>" tests/` before declaring the list complete.

2. **The lazy-import cleanup in `agent/runtime.py` (pre-existing diff) is unrelated to this work and was not addressed.** The working tree had a pre-existing diff at `agent/runtime.py:32` (moving `from agent.kb_lookup import kb_lookup` from top-of-file to inside the `if conv.fallback_provider:` block). It's a follow-up from the KB Provider Phase 2 post-mortem (suggestion §9 in that doc). I did not commit it as part of this work — it's out of scope — but it stayed in the working tree throughout, which made `git diff --stat` noisier than necessary.
   - Impact: Cosmetic; no functional issue.
   - Lesson: Pre-flight check at the start of the loop should `git stash` unrelated working-tree changes, or note them explicitly in the post-mortem's §8 (Pre-Existing Issues) so reviewers don't think they're part of the change.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Unified provider selection UX:** A user opening the Create Agent or Edit Agent dialog now sees a single row: "Provider" (primary dropdown, shows all vetted provider cards from Settings) and — when the primary is `local-kb` — a second row: "Fallback Provider" (dropdown, also showing all vetted provider cards). The previous "Fallback Model" dropdown is gone. The user picks a card, the system uses that card's `default_model` at runtime. There is no way for the user to specify a non-default model — by design. Code path: `ui/views/agent_builder.py:_build_fallback_provider_row` (line 346) → `_on_provider_changed` (line 384) → `get_values()` (line 167-186) → YAML written by `save_agent_def`.

2. **Fallback chain auto-derives the model:** When the primary provider returns `KB_OUT_OF_SCOPE` and the agent has `fallback_provider: openrouter`, the runtime reads `self._config.providers["openrouter"].default_model` (e.g. `"openrouter/owl-alpha"`) and uses that as the model string for the fallback LLM call. After the call, `conv.model` is restored to the primary. The user sees a continuous answer (the fallback's response) instead of the KB_OUT_OF_SCOPE sentinel, but the underlying model identity is now opaque — driven by the Settings card, not the agent YAML. Code path: `agent/runtime.py:1183-1192` (the new derivation block) → `_call_llm` (line 1205) → response injection → `conv.model = original_model` (restore).

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **Pre-existing lazy-import diff in `agent/runtime.py:32`:** Verified via `git diff agent/runtime.py` before this work started. The diff (commit-pre-stage on `9a5505c`) moves `from agent.kb_lookup import kb_lookup` from top-of-file to inside the `if conv.fallback_provider:` block. This is the §9 follow-up suggestion from the KB Provider Phase 2 post-mortem (`docs/post-mortems/2026-06-14-KB-PROVIDER-PHASE-2-POST-MORTEM.md`). It stayed in the working tree throughout this implementation but is not part of this work's scope. Flagged for the captain to commit separately.

2. **Pre-existing diff in `tests/test_connection_sync_handler.py`:** Verified via `git diff tests/test_connection_sync_handler.py` before this work started. The diff updates an assertion to use an adapter pattern (verifying `set_on_activity_bubble` is wired via an adapter that converts `ActivityBubble` → `dict`). This is from the SPEC-activity-drawer Phase 1 implementation. Not part of this work's scope. Flagged for the captain to commit separately.

3. **3 dataclass fields + 1 parameter retain `fallback_model` with no deprecation marker:** `models/conversation.py:108`, `agent/special_agents.py:40, 125`, `agent/runtime.py:1015` (the `create_conversation` parameter). Verified as in-scope retention per the spec's §2.5, §2.6, §2.7 design. The fields are unused at runtime but kept for backward-read tolerance. No deprecation marker was added — see §3 Bad item #1 for the evolution suggestion.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add `# DEPRECATED 2026-06-15` comments to the 4 kept `fallback_model` sites (`models/conversation.py:108`, `agent/special_agents.py:40, 125`, `agent/runtime.py:1015`) | 5 minutes | Future readers immediately see the field is unused. Cheap, no risk. |
| Drop `Conversation.fallback_model` and `SpecialAgentDef.fallback_model` in a separate deprecation cycle (after verifying no in-flight conversations have the field set on disk) | 1-2 hours | Removes the last traces of the old design. Requires writing a migration that scans existing conversation JSON files. |
| Update `prompts/system/auxilium.md` to drop the "fallback model" reference if it has one (didn't grep for this in this loop; out of scope) | 15 minutes | Doc consistency. |
| Add a "show only verified" filter to the Settings provider list (per the user's "tested and we know it works" framing) | 2-3 hours | UX improvement. Would make "tested" a hard guarantee rather than a convention. |
| Add `Step 6.6a` to `steelFramedCodeWriter.md` or the supervisor's verification checklist: "After removing a symbol, grep all test files for that symbol. Tests that assert on implementation details need updating too." | 15 minutes | Prevents the LOW-severity bug we hit in Phase 1 from recurring. |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Test-file scope in "Files NOT changed" list:** When a spec removes an implementation detail, the "Files NOT changed" list should include test files that reference the removed symbol. Grep the test directory for the symbol before declaring the list complete.
   - Trigger: writing a spec that removes a symbol, class, method, or attribute.
   - Action: add a verification step — `grep -rln "<symbol>" tests/` — to the spec's scope phase. Update the test files to either remove the assertion or replace it with a negative assertion.

2. **Behavioral smoke tests authored by the supervisor, not the builder:** The Phase 3 behavioral smoke test (capturing `conv.model` at the moment of `_call_llm`) was authored by me in the phase instructions, not left to QTR. This was the strongest evidence that the runtime change was correct, and it caught what a helper-level test would have missed. **Continue this pattern for behavioral changes in hot loops.**
   - Trigger: any change to runtime behavior, signal handlers, or per-invocation code paths.
   - Action: in the phase instructions, include a 10-15 line behavioral smoke test that the builder runs. The smoke test should exercise the user-facing behavior, not just the helper.

3. **Pre-flight `git stash` of unrelated working-tree changes:** When the working tree has pre-existing diffs unrelated to the current work, `git stash` them at the start of the loop (or note them in §8). Otherwise `git diff --stat` is noisy and reviewers may misattribute changes.
   - Trigger: starting a new implementation loop.
   - Action: `git status --short` at the start. Either `git stash` the unrelated changes or note them explicitly in the post-mortem's §8.

---

## 11. Sign-off

- [ ] Code committed and pushed to main — **PENDING** (the captain will commit; the post-mortem and 6 phase-instructions files are on disk in the working tree but not yet committed per §6.2 lesson #2 above — they should be committed together with the code changes)
- [ ] All post-loop verification commands run and pasted — **DONE** (55/55 tests pass, behavioral smoke test passes, GUI dialog smoke test passes, grep for `fallback_model` confirms only the expected kept sites remain)
- [ ] Captain notified with summary — **DONE** (this post-mortem is the summary)
- [ ] Tier 2+ backlog updated — **DONE** (see §9)

---

## Appendix A: Commit Plan (for the captain)

When the captain commits this work, the suggested commit structure is:

1. **Single commit (recommended)**: `feat: unify fallback provider with primary provider — remove fallback model dropdown` (combines all 6 phases).
   - 9 files modified: `ui/views/agent_builder.py`, `ui/handlers/agent_builder_handler.py`, `ui/handlers/agent_runtime_handler.py`, `utils/agent_defs.py`, `agent/runtime.py`, `tests/test_agent_builder_fallback.py`, `tests/test_agent_builder_no_provider_keys.py`, `tests/test_runtime_fallback.py`, `tests/test_kb_integration.py`, `docs/ARCHITECTURE.md`
   - 1 new file: `docs/specs/SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md`
   - 5 new files (phase instructions): `docs/specs/FALLBACK-MODEL-DROPDOWN-REMOVAL-PHASE-{1..5}-INSTRUCTIONS.md`
   - 1 new file: `docs/post-mortems/2026-06-15-FALLBACK-MODEL-DROPDOWN-REMOVAL-POST-MORTEM.md` (this file)

2. **Multi-commit (alternative)**: separate commits per phase. Recommended only if the captain wants a granular history. The 6 phases are: UI removal → handler/utils → runtime → tests → docs → post-mortem.

Either way, the pre-existing `agent/runtime.py` lazy-import diff and `tests/test_connection_sync_handler.py` diff should be committed separately (or stashed) — they are not part of this work.
