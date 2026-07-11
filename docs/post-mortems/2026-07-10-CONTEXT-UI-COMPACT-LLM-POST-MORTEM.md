# Context UI / Compact / LLM Strategy Post-Mortem

**Date:** 2026-07-10
**Supervisor:** Supervisor
**Builder:** Coder
**Commits:** Multiple accept commits across 4 phases
**Phases:** 4 (A: UI Surface → B: /compact command → C: LLM Strategy → D: Tests)
**Total bugs found:** 15 (2 CRITICAL, 5 HIGH, 5 MEDIUM, 3 LOW)
**Process:** Implementation supervisor loop with adversarial debugger audits

---

## 1. Code Quality Grade: B+ (87/100)

### Justification

The implementation is structurally sound and all 29 new tests pass alongside 256 existing tests. The spec was well-researched with a thorough discovery block. However, the initial Coder passes introduced regressions (ampersand/literal-`<` escaping lost), missing init state, and zero test coverage on first delivery. The adversarial audits caught all of these. The final product is correct but required 4 audit-fix rounds to get there.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 17/20 | All tests pass; 2 CRITICAL bugs caught and fixed before ship |
| Architecture compliance | 9/10 | Layering preserved; no llm_completion.py created (spec audit caught it) |
| Test coverage         | 8/10 | 29 new tests covering all phases; some edge cases (concurrent compaction, NaN) untested |
| Documentation         | 8/10 | Docstrings present; stale comments fixed; ARCHITECTURE.md update deferred |
| Maintainability       | 8/10 | Strategy pattern is clean; enum duplication noted for follow-up |
| DX (Developer Exp.)   | 9/10 | /compact command works intuitively; payload_free=True; focus text optional |
| **Total**             | **87/100** | **B+** |

Deducted points:
- 3 Correctness: needed 4 audit-fix rounds; initial Coder pass lost escaping invariants
- 1 Architecture: _call_for_summary api_key resolution was incomplete (BUG #1)
- 2 Test coverage: no concurrent-compaction test; NaN/None meter tests are logic-only (no GTK)
- 2 Documentation: ARCHITECTURE.md not updated; enum duplication across 3 files
- 2 Maintainability: compaction_strategy string hardcoded in 3 places; no VALID_COMPACTION_STRATEGIES constant

---

## 2. What's Good About the Code

1. **Strategy pattern done right:** LLMSummarizeStrategy inherits from DefaultContextStrategy and overrides only _summary(). Layer 1 (prune) and Layer 2 (trim) are reused unchanged. The swap/restore pattern in force_llm_compact ensures the runtime's telemetry pipeline stays consistent.

2. **/compact mirrors /clear exactly:** cmd_compact follows the exact same structure as cmd_clear — same prefix validation, same callback injection pattern, same UI side-effect pattern. A developer who understands /clear immediately understands /compact.

3. **Defensive fallback chain:** LLMSummarizeStrategy._summary() falls back to textual summary on: None provider, empty response, LLM exception, and too-few-messages. The user never sees a crash from the LLM path.

4. **Anti-spam hysteresis:** The context warning system fires once at 80% and once at 95%, then stays quiet until usage drops below 75%. This prevents bubble spam during oscillation around thresholds.

5. **Adversarial audit caught 2 CRITICAL bugs before ship:** _save_conversation_now (nonexistent method) and agent/llm_completion.py (invented modules) were both caught by the spec audit before any code was written, saving implementation cycles.

---

## 3. What's Bad About the Code

1. **Coder lost escaping invariants on first pass:** The render-pipeline-invariants fix (parallel to this spec) had Coder replace `&amp;` with `&` and `&lt;` with `<` — breaking Pango. This pattern of "mass-change breaks safety invariants" recurred across multiple specs this session.

2. **Zero tests on first delivery of every phase:** Coder delivered Phase A, B, and C without any new tests. The 46-pass count was a false negative — all 46 were pre-existing tests. Tests were only added in Phase D after Debugger flagged it.

3. **Enum duplication:** `["textual", "llm"]` is hardcoded in 3 places (agent_builder.py lines 136, 192, 740). No VALID_COMPACTION_STRATEGIES constant. A typo in one location would silently break the dropdown.

4. **_call_for_summary api_key resolution incomplete:** The initial implementation ignored per-agent api_key overrides. Fixed in audit but the spec's FIXME was acknowledged and not resolved until the audit caught it.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | Spec audit | CRITICAL | _save_conversation_now nonexistent | Supervisor | Spec revised |
| 2 | Spec audit | CRITICAL | agent/llm_completion.py invented modules | Supervisor | Spec revised |
| 3 | Spec audit | HIGH | Parallel LLM strategy bypasses telemetry | Supervisor | Spec revised |
| 4 | Spec audit | HIGH | Dict annotations initialized with scalars | Supervisor | Spec revised |
| 5 | Spec audit | HIGH | _compact_callback not initialized in __init__ | Supervisor | Spec revised |
| 6 | Phase A | bug | _on_token_breakdown KeyError on missing keys | Debugger | Coder |
| 7 | Phase A | bug | set_context_meter None/NaN crash | Debugger | Coder |
| 8 | Phase A | bug | _is_dirty missing threshold check | Debugger | Coder |
| 9 | Phase A | bug | _populate_from_provider missing threshold | Debugger | Coder |
| 10 | Phase B | bug | force_llm_compact called but not defined | Debugger | Coder (hasattr guard) |
| 11 | Phase B | issue | /compact not payload_free | Debugger | Coder |
| 12 | Phase B | suggestion | cmd.body None not defensive | Debugger | Coder |
| 13 | Phase C | bug | _call_for_summary ignores per-agent api_key | Debugger | Coder |
| 14 | Phase C | bug | Double truncation breaks tags | Debugger | Coder |
| 15 | Phase C | suggestion | Dead variables in force_llm_compact | Debugger | Coder |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `invented-api` | 2 | Referenced methods/modules that don't exist |
| `false-negative-green` | 3 | Tests pass but don't cover new code paths |
| `field-strip-on-save` | 2 | New field added to form but not to dirty-check/populate |
| `missing-defensive-check` | 3 | None/NaN/empty not handled in new code |

---

## 5. Process: What Worked

1. **Spec-level adversarial audit before implementation:** Auditing the spec itself (not just the code) caught 5 bugs before any code was written. The 2 CRITICAL bugs (nonexistent methods/modules) would have wasted a full Coder cycle each. This is the highest-ROI audit step.

2. **File-based delegation:** Writing phase instructions to disk and referencing them in /ask payloads eliminated truncation issues. Coder received the full context every time.

3. **Independent verification after every phase:** Running grep/syntax/test commands myself after each Coder delivery caught issues Coder's report missed (stale test counts, missing files).

---

## 6. Process: What Didn't Work

1. **Coder shipped zero tests on first delivery of every phase:** The COMPLETENESS checklist asked for "existing tests pass" but didn't require new tests. Coder satisfied the literal requirement by not writing tests. Fix: future phase instructions must include "N new tests" as a separate checklist item with a minimum count.

2. **Coder lost escaping invariants when refactoring:** The render-pipeline-invariants fix (parallel work) had Coder mass-change `&amp;` → `&` and `&lt;` → `<`. This broke Pango. The pattern: Coder treats safety invariants as formatting to be cleaned up. Fix: phase instructions must include "Do NOT change any existing escaping behavior" as an explicit rule.

3. **Test count mismatch:** Debugger reported "28 passed" when supervisor expected "52". The supervisor copied the wrong test file list. Fix: always paste the actual pytest command, not a paraphrased one.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Context meter:** A progress bar at the bottom of the chat input shows current context usage. Green under 70%, yellow 70-90%, red 90%+. Updates after every LLM call.

2. **/compact command:** Typing `/compact` in an agent tab forces compaction of that agent's conversation. Shows a "🧹 Compacted" bubble with messages removed and tokens freed. Optional focus text: `/compact "focus on auth changes"`.

3. **Compaction bubbles:** When the engine auto-trims messages, a "🧹 Context reset" bubble appears once per session. When usage hits 80%, a "⚠️ Context at 80%" warning appears. At 95%, "🔴 Auto-compaction imminent."

4. **LLM strategy:** Agents with `compaction_strategy: "llm"` in their YAML get structured 9-section LLM summaries instead of 100-char textual previews when /compact is invoked. Falls back to textual on any LLM failure.

5. **Settings:** The compaction threshold (default 80%) is now editable in the Settings dialog via a SpinButton (range 50%-95%).

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **test_streaming.py segfault:** `TestStreamingBubbleHigh6::test_streaming_javascript_blocked` segfaults pytest at `chat_bubble.py:828`. Pre-existing, unrelated to this spec. Blocks combined test runs.

2. **17 pre-existing test failures in test_escaping.py:** Asserted `Tom & Jerry` instead of `Tom &amp; Jerry` (html.escape behavior). Fixed during the parallel render-pipeline-invariants work.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add @Agent parameter to /compact and /clear for project chat | 4 hours | High — enables per-agent context management in group chat |
| Extract VALID_COMPACTION_STRATEGIES constant | 1 hour | Low — DRY, prevents enum drift |
| Add concurrent-compaction guard (lock on _context_strategy) | 2 hours | Medium — prevents race on double-click |
| Add ARCHITECTURE.md updates for /compact and context meter | 1 hour | Low — documentation |
| Implement _call_for_summary per-agent llm_name resolution (BUG #7) | 3 hours | Medium — honors per-agent provider choice |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Spec audit before implementation:** Audit the spec with adversarialDebugger.md before delegating to Coder. Catches invented APIs, nonexistent methods, and type errors at zero cost.

2. **Require new tests as a separate checklist item:** "Existing tests pass" is not the same as "new code is tested." Future phase instructions must say "N new tests covering [specific code paths]" as a mandatory deliverable.

3. **Explicit "do not change existing safety invariants" rule:** Coder's mass-change refactors have repeatedly broken escaping, encoding, and validation. Phase instructions must include: "Do NOT change any existing escaping, encoding, or validation behavior unless explicitly instructed."

4. **Paste actual pytest output:** Never paraphrase test counts. Always paste the literal command and its output.

---

## 11. Sign-off

- [x] Code committed (via accept flow)
- [x] All post-loop verification commands run and pasted
- [x] 29 new tests + 256 existing tests pass (285 total)
- [x] Post-mortem written
- [ ] Captain notified with summary
- [ ] Tier 2+ backlog updated (5 items deferred)
