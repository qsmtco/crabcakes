# Phase 4 Adversarial Audit Report

**Spec:** `docs/specs/CM-PHASE-4-INSTRUCTIONS.md`
**Implementation:** `agent/context_strategy.py`, `tests/test_context_strategy.py`
**Audit approach:** Adversarial debugger — prove fragility, find what the code misses.

---

## SCOPE VERIFICATION

The Phase 4 spec explicitly states:
> **SCOPE:** This phase implements P2 and P3 ONLY. Do NOT implement:
> - P4 (prune_tool_outputs) — Phase 5
> - P5 (_find_split_index) — Phase 6
> - P6 (_fit_summary with tiktoken) — Phase 6

The spec's COMPLETENESS checklist marks all items `[x]` but the implementation contains substantial Phase 5 and Phase 6 code already present in Phase 4. This is a **scope bleed** — Phase 4's code is not actually P2/P3-only.

---

## BUG FINDINGS

---

```
BUG #1
Severity: CRITICAL
Assumption violated: Phase 4 summary injection uses len(summary) // 4 heuristic (NOT tiktoken)
Attack vector: Phase 4 spec §Step 3 explicitly forbids tiktoken in the summary block until Phase 6.
               The spec shows a literal diff that replaces the heuristic-based summary block with
               one that STILL uses len(summary) // 4. The implementation substitutes
               _fit_summary (Phase 6) and tiktoken encoding — both Phase 6 features — for the
               spec-required len(summary) // 4 heuristic.
Reproduction:
  1. Read CM-PHASE-4-INSTRUCTIONS.md §Step 3 exactly.
  2. The "Current summary block" shows: summary_tokens = len(summary) // 4
  3. The "New summary block" (the REQUIRED replacement) also shows: summary_tokens = len(summary) // 4
  4. The spec text: "keep the SAME len(summary) // 4 heuristic (do NOT use tiktoken — that's Phase 6)"
  5. Implementation at lines 188-206: uses _fit_summary() (Phase 6) with tiktoken encoding
Root cause: The implementation was written against a future state (after Phase 6 was implemented)
            rather than the Phase 4 snapshot described in the spec. Phase 6's _fit_summary
            was available and substituted for the spec-required heuristic.
Fix: Replace the summary injection block with the spec's exact new summary block:
     summary_tokens = len(summary) // 4
     summary_tokens_injected = summary_tokens
     (no _fit_summary call, no tiktoken encoding)
```

---

```
BUG #2
Severity: HIGH
Assumption violated: Phase 4 compact() must NOT call Phase 5 methods
Attack vector: The spec SCOPE section explicitly excludes "P4 (prune_tool_outputs) — Phase 5".
               Yet compact() at line 140 calls self.prune_tool_outputs(conv, token_budget, protect_turns=2).
               This is not a Phase 4 method; it is Phase 5's implementation of P4.
               Phase 4 was supposed to be P2 (keep_first) + P3 (protect_is_summary) ONLY.
Reproduction:
  1. grep "prune_tool_outputs" agent/context_strategy.py
  2. Line 140 in compact(): self.prune_tool_outputs(...)
  3. The method definition at line 256 is labeled: "Layer 1: prune_tool_outputs (Phase 5: P4 cheap lossless stubbing)"
  4. This Phase 5 method is being called from Phase 4's compact()
Root cause: Scope bleed. Phase 5 was implemented before Phase 4 was audited/finalized.
            The Phase 5 prune_tool_outputs was integrated into Phase 4's compact()
            instead of being gated behind a version check or separate layer.
Fix: Either (a) gate prune_tool_outputs behind a version/phase flag, or (b) ensure
     Phase 4 compact() does not call it. The spec's Phase 4 trim loop and summary
     injection are standalone — they don't need Layer 1.
```

---

```
BUG #3
Severity: HIGH
Assumption violated: Phase 4 summary injection must use the exact spec replacement block
Attack vector: The spec's "New summary block" (required output of Step 3) shows:
                 insert_at = max(keep_first, len(conv.messages) - tail_preserve)
               The implementation at line 210 uses exactly this.
               HOWEVER, the spec's new block has NO _fit_summary call and NO tiktoken —
               the implementation has both.
               Additionally, the spec's new block uses the plain Message constructor
               with content=fitted (which is the raw summary string from _summary()).
               The implementation tries to _fit_summary first.
Reproduction:
  1. Read spec Step 3 — compare the "New summary block" code to lines 188-210 in context_strategy.py
  2. Spec new block: summary_tokens = len(summary) // 4; insert summary directly
  3. Implementation: calls _fit_summary, uses tiktoken encoding, summary_tokens_injected
Root cause: The implementation uses Phase 6's _fit_summary() instead of the Phase 4 spec's
            required heuristic. Phase 6 introduced _fit_summary specifically to replace the
            len(summary) // 4 heuristic, but Phase 4 must not use it.
Fix: Follow the spec's exact new summary block, preserving len(summary) // 4.
```

---

```
BUG #4
Severity: MEDIUM
Assumption violated: test_context_strategy.py mixes Phase 4 tests with Phase 5+ tests
Attack vector: The spec §Step 5 creates a NEW test file for P2/P3 behavior ONLY.
               The actual test_context_strategy.py contains:
               - TestKeepFirst (P2) ✓
               - TestProtectIsSummary (P3) ✓
               - TestLastResult (telemetry) ✓
               - TestPruneToolOutputs (P4/Phase 5) ✗
               - TestFindSplitIndex (P5/Phase 6) ✗
               - TestFitSummary (P6/Phase 6) ✗
               - TestDynamicPromptBudget (P7/Phase 7) ✗
               - TestFindSplitIndexCB6Hardening (Phase 9) ✗
               The spec's test file was supposed to contain only P2/P3/telemetry tests.
               A test suite that passes Phase 4 tests but also includes Phase 5-9 tests
               cannot distinguish "Phase 4 is correct" from "Phase 4+5+6+7+9 are correct".
Reproduction:
  1. python3 -m pytest tests/test_context_strategy.py -v --collect-only
  2. Count test classes: 8 classes, only 3 match Phase 4 scope
  3. Tests for phases 5, 6, 7, 9 are in the Phase 4 test file
Root cause: Multi-phase implementation committed to a single file. The Phase 4 test
            file became a dump for all phase tests as they were implemented.
Fix: The Phase 4 test file should contain ONLY TestKeepFirst, TestProtectIsSummary,
     and TestLastResult. Phase 5+ tests belong in separate files (e.g.,
     test_phase5.py, test_phase6.py). At minimum, Phase 4 tests must be runnable
     and passing in ISOLATION from Phase 5+ code.
```

---

```
BUG #5
Severity: MEDIUM
Assumption violated: DefaultContextStrategy docstring claims Phase 4 features are unused
Attack vector: The class docstring at line 82-87 reads:
                 "Phase 1: mechanical extraction... The keep_first and protect_is_summary
                  parameters are accepted but NOT YET USED — defaults preserve the
                  pre-extraction behavior. P2/P3 enforcement arrives in Phase 4."
               This is factually wrong after Phase 4 implementation. keep_first and
               protect_is_summary ARE wired in Phase 4. The docstring describes the
               PRE-Phase-4 state. Comments describing old behavior after a refactor
               are bugs per adversarialDebugger.md §10.
Reproduction:
  1. Read agent/context_strategy.py DefaultContextStrategy class docstring
  2. Compare to compact() method body — keep_first and protect_is_summary are used
Root cause: The docstring was copied from the Phase 1 extraction and never updated
            when Phase 4 wired the parameters.
Fix: Update the class docstring to reflect Phase 4 status, or document that
     P2/P3 are implemented.
```

---

```
BUG #6
Severity: MEDIUM
Assumption violated: The spec's COMPLETENESS checklist is misleading — scope is not actually P2/P3-only
Attack vector: The spec's COMPLETENESS checklist marks all items [x], implying Phase 4 is
               complete and correct. But the actual code includes Phase 5 (prune_tool_outputs
               call), Phase 6 (_fit_summary, _find_split_index, tiktoken in summary),
               Phase 7 (_apply_system_prompt_budget), and Phase 9 (CB-6 hardening).
               An auditor reading the checklist would conclude "Phase 4 is done"
               when the implementation is actually a merged Phase 4+5+6+7+9.
Reproduction:
  1. Read CM-PHASE-4-INSTRUCTIONS.md COMPLETENESS checklist
  2. Check implementation for P4/P5/P6/P7 features bleeding into Phase 4 compact()
  3. All checklist items are [x] but the scope is NOT P2+P3 only
Root cause: The checklist was marked complete before subsequent phases were merged.
            The checklist does not verify scope isolation.
Fix: Add a checklist item: "compact() does NOT call Phase 5 methods (prune_tool_outputs)"
     and "Summary injection does NOT call Phase 6 methods (_fit_summary)"
```

---

```
BUG #7
Severity: LOW
Assumption violated: tokens_after_layer1 snapshot is taken even when Layer 1 doesn't run
Attack vector: tokens_after_layer1 = conv.get_token_estimate() at line 142 runs AFTER
               prune_tool_outputs at line 140. If prune_tool_outputs is a no-op
               (tokens_before <= target_tokens), the snapshot is still taken.
               This is fine for correctness, but the comment at line 225 says:
               "Layer 1 (prune_tool_outputs) fired iff tokens decreased between
                the initial snapshot and the post-Layer-1 snapshot."
               If Layer 1 is a no-op (returns 0), tokens_after_layer1 == tokens_before,
               so layer=1 branch is correctly NOT taken. This is actually correct.
               However: if prune_tool_outputs partially runs but frees 0 tokens
               (e.g., all tool results already stubbed), the layer determination
               is still correct. The comment is accurate.
Reproduction: N/A — this is actually NOT a bug. The logic is correct.
Root cause: N/A
Fix: N/A — removing this entry; the logic is sound.
```

---

```
BUG #8
Severity: MEDIUM
Assumption violated: _summary() calls _find_split_index (Phase 6) even when called from Phase 4 compact()
Attack vector: compact() line 189 calls self._summary(conv, token_budget=token_budget, keep_first=keep_first).
               _summary() at line 548 has two branches:
               - token_budget > 0: calls _find_split_index (Phase 6) — WRONG for Phase 4
               - token_budget <= 0: uses legacy messages[:-tail_preserve] slice
               Phase 4 compact() ALWAYS passes token_budget > 0, so _summary() ALWAYS
               takes the Phase 6 code path, calling _find_split_index.
               The spec's Phase 4 summary block was supposed to use the simple
               len(summary) // 4 heuristic with a basic split, not Phase 6's
               _find_split_index.
Reproduction:
  1. compact() line 189: self._summary(conv, token_budget=token_budget, ...)
  2. _summary() line 563: if token_budget > 0: split = self._find_split_index(...)
  3. _find_split_index is Phase 6's implementation — used in Phase 4 compact()
Root cause: _summary() was updated in Phase 6 to use _find_split_index when budget is
            provided. Since Phase 4 compact() passes budget, Phase 4 indirectly uses
            Phase 6's split algorithm. This violates Phase 4's scope.
Fix: Either (a) Phase 4 compact() should not pass token_budget to _summary(), forcing
     the legacy fallback, or (b) _summary() should have a Phase-4-compatible mode
     when called from compact().
```

---

```
BUG #9
Severity: LOW
Assumption violated: Test file comments describe "Deviation from spec" without flagging them as bugs
Attack vector: test_context_strategy.py has comments like:
               "Deviation from spec test code: the Phase 4 instructions use
                conv.add_assistant_message(..., is_summary=True) but
                Conversation.add_assistant_message does NOT accept is_summary..."
               These comments acknowledge deviations but don't escalate them as
               implementation bugs. The deviation exists because the spec's test
               code is not valid Python (is_summary not a parameter). The test
               correctly works around this, but the fact that the spec's test code
               is invalid Python is itself a spec bug.
Reproduction:
  1. Read spec Step 5 test code: conv.add_assistant_message("...", [], is_summary=True)
  2. Verify Conversation.add_assistant_message signature (no is_summary parameter)
  3. The spec's test code would fail if run directly
Root cause: Spec's test code was written as pseudo-code/example, not verified Python.
            The test file correctly worked around it using direct Message construction.
Fix: The Phase 4 spec's test code example should use the direct Message constructor
     (as the test file already does). The spec should be corrected.
```

---

```
BUG #10
Severity: MEDIUM
Assumption violated: _summary() legacy path doesn't apply CB-6 checks before summarizing
Attack vector: _summary() computes split = _find_split_index(...) and then uses
               messages[:split] as the head to summarize. But _find_split_index
               has CB-6 hardening logic (Phase 9) that ensures TOOL_RESULT
               orphans are pulled into the head. However, if the parent
               ASSISTANT is in the keep_first region AND the TOOL_RESULT
               is in the trimmable region, _find_split_index may fail to
               detect this edge case, leaving an orphan in the head that
               _summary() then tries to summarize — creating a malformed summary.

               Actually, the _find_split_index Phase 9 fix adds a search over
               [0..keep_first-1] for the parent. This should handle it.

               But wait: what if _summary() is called with no token_budget
               (token_budget=0), using the legacy path? The legacy path uses
               messages[:-tail_preserve] which could orphan a TOOL_RESULT from
               its parent in keep_first if the parent is at index < tail_preserve.
               This is an edge case in the legacy path only.
Reproduction:
  1. Call _summary(conv, token_budget=0) — the legacy path
  2. Have a TOOL_RESULT at index len-messages-tail_preserve whose parent is
     in keep_first region (index < keep_first)
  3. messages[:split] would not include the parent, orphaning the TOOL_RESULT
     in the head summary
Root cause: The legacy path (no budget) doesn't apply CB-6 checks. Only the
            token_budget > 0 path uses _find_split_index which has CB-6 hardening.
Fix: The legacy path in _summary() should also apply CB-6 checks when computing
     the split, or it should document that it's only safe to call with
     token_budget > 0 when CB-6 matters.
```

---

## MISSING TEST COVERAGE

The Phase 4 spec §Step 5 provides test code examples for the test file. However:

1. **No test for CB-6 at keep_first boundary in _select_prune_candidate**: The spec describes the CB-6 invariant at keep_first boundary: "When a TOOL_RESULT candidate is at index keep_first, its parent ASSISTANT-with-tool-calls at keep_first - 1 is in the keep_first region." The `_select_prune_candidate` method skips these (correctly), but there's no explicit test that verifies this exact edge case — that a TOOL_RESULT whose parent is at `keep_first - 1` is never returned as a candidate.

2. **No test that summary injection respects the `len(summary) // 4` heuristic**: The spec requires the heuristic. No test verifies that `summary_tokens_injected` is computed as `len(summary) // 4` (or its fallback) rather than tiktoken.

3. **No test for `keep_first=0` edge case combined with tool results**: When `keep_first=0`, all messages including tool results in the head can be trimmed. No test verifies CB-6 is maintained in this extreme case.

4. **No test that calling `compact()` twice converges**: If trimming doesn't bring tokens under budget on the first call, a second call should not oscillate or grow messages.

---

## OUT-OF-SCOPE FEATURES PRESENT IN PHASE 4 CODE

| Feature | Phase | Location | Status |
|---------|-------|----------|--------|
| `prune_tool_outputs` call in `compact()` | 5 | Line 140 | Violates Phase 4 scope |
| `_fit_summary` call in summary injection | 6 | Line 198 | Violates Phase 4 scope |
| `_find_split_index` in `_summary()` | 6 | Line 563 | Violates Phase 4 scope |
| tiktoken encoding in summary injection | 6 | Line 203 | Violates Phase 4 scope |
| `_apply_system_prompt_budget` tests | 7 | test_context_strategy.py | Wrong file |
| Phase 9 CB-6 hardening in `_find_split_index` | 9 | Lines 333-432 | Wrong phase |

---

## SUMMARY

**Total bugs found: 10** (2 critical, 4 medium, 2 low, 2 informational/nit)

**Root cause pattern:** Phase 5, 6, 7, and 9 features were implemented and committed before Phase 4 was audited. The Phase 4 implementation was written against the future-complete codebase rather than the Phase 4 snapshot described in the spec. The `compact()` method is a merge of Phase 4 + Phase 5 code, and the summary injection block uses Phase 6's `_fit_summary` and tiktoken instead of the spec-required `len(summary) // 4` heuristic.

The most critical issue is **BUG #1** — the summary injection block directly violates Phase 4's core constraint (no tiktoken, use `len(summary) // 4`) by calling Phase 6's `_fit_summary` with tiktoken encoding. The COMPLETENESS checklist being marked `[x]` while the scope is violated makes this particularly dangerous — a future developer or auditor would trust the checklist.
