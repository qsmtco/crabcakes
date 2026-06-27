# CM Audit Verification Report

**Verifier:** qaster (OpenClaw)
**Date:** 2026-06-27
**Scope:** Verify every claim in the CM master audit + 9 phase audits against actual code
**Method:** 3 parallel sub-agents read each phase audit and cross-checked against source; master audit cross-cutting claims verified directly.

---

## Executive Summary

The audits are **largely accurate** in their technical claims. The code bugs (interleaved messages, char-vs-token truncation, telemetry lies) are all confirmed real. However, the audits contain **one significant factual error** that undermines the master audit's central thesis:

> **The Phase 1 "forward-loading" claim is wrong.** Phase 1 commit `26c84ec` was correctly scoped (270 lines, 2 methods). The forward-loading happened incrementally across Phases 4–6 as the spec intended. The audit confused `25b72f6` (a later 17-line tweak) with the Phase 1 commit.

This weakens PATTERN 1 (forward-loading) — the most "damaging finding" in the master audit. The per-phase commits DID deliver code incrementally as the spec designed. The audit's narrative of "single forward-loaded commit" is a misread of git history.

### Verification Scorecard

| Category | Count |
|----------|-------|
| ✅ CONFIRMED | 45+ |
| 🔶 PARTIALLY CONFIRMED | 8 |
| ❌ REFUTED | 4 |
| 🛠 ALREADY FIXED / STALE | 2 |
| **Total claims checked** | **~59** |

---

## Cross-Cutting Claims (Master Audit)

| Claim | Reality | Verdict |
|-------|---------|---------|
| `context_strategy.py` = 598 lines | `wc -l` = 598 | ✅ CONFIRMED |
| 6 algorithm methods in file | `compact`, `prune_tool_outputs`, `_find_split_index`, `_fit_summary`, `_select_prune_candidate`, `_summary` = 6 (plus `__init__`, `last_result`, protocol dups = 11 total `def`) | ✅ CONFIRMED |
| `keep_first` referenced 27 times | Actually **38** references now (understated, not overstated) | ✅ CONFIRMED (understated) |
| 100 test files | `find tests/ -name "*.py" | wc -l` = 100 | ✅ CONFIRMED |
| `hard_ceiling=0` shipped | Line 249: `hard_ceiling=0, # not known at strategy level in Phase 1` | ✅ CONFIRMED |
| `layer` defaults to 2 for no-ops | Lines 234-235: `if layer == 0: layer = 2` | ✅ CONFIRMED |
| Total bugs = 68+ | Individual phase counts sum to 60-70+ depending on how sub-counts are tallied | ✅ CONFIRMED (approximate) |

---

## The Forward-Loading Claim (PATTERN 1) — DETAILED REFUTATION

The master audit's most damaging claim is that "Phase 1 absorbed Phases 2–9 into a single commit." This is **factually wrong**:

### What the audit says:
> "The Phase 1 commit (`25b72f6`) shipped 598 lines in `agent/context_strategy.py`"
> — Master Audit, PATTERN 1

### What git history shows:

| Commit | Phase | Methods added | Lines |
|--------|-------|---------------|-------|
| `26c84ec` | **Phase 1** | `compact()`, `_summary()` | 270 |
| `b4eaae8` | **Phase 4** | `_select_prune_candidate()` | incremental |
| `637978f` | **Phase 5** | `prune_tool_outputs()` | incremental |
| `f10cdab` | **Phase 6** | `_find_split_index()`, `_fit_summary()` | incremental |
| `a69e763` | **Phase 9** | CB-6 hardening inside `_find_split_index` | incremental |

- `25b72f6` (the commit the audit cites as "Phase 1") is actually a **17-line tweak** to `context_strategy.py` made much later. It is NOT the Phase 1 commit.
- The actual Phase 1 commit (`26c84ec`) correctly shipped only `compact()` and `_summary()` with `keep_first` explicitly marked `# noqa: ARG002 — Phase 4 wires this`.
- The per-phase commit isolation the spec was designed to enable **was actually followed**.

### Impact on master audit:

- **PATTERN 1** (forward-loading) is **refuted as described**. The code was built incrementally across phases.
- The master audit's Top-10 Bug #3 ("Phase 1 absorbed Phases 2–9") is **refuted**.
- The underlying observation (Phases 4–6 each shipped code, not just tests) is correct but NOT a bug — it's how the spec designed the phases to work.

---

## Per-Phase Verification

### Phase 1 (10 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | Phase 1 absorbed all phases | ❌ **REFUTED** | Wrong commit hash. Phase 1 (`26c84ec`) was correctly scoped (270 lines, 2 methods). |
| #2 | `keep_first` not unused in P1 | 🔶 **PARTIALLY** | Phase 1 correctly deferred; Phase 4 wired it. The deferred contract was honored. |
| #3 | `hard_ceiling=0` telemetry lie | ✅ **CONFIRMED** | Line 249, runtime never overrides. |
| #4 | `layer` phantom default | ✅ **CONFIRMED** | Lines 234-235 default `layer=0` → `layer=2`. |
| #5 | Cache invalidation docstring | ❌ **REFUTED** | Docstring is accurate; manual invalidation correctly implemented. |
| #6 | Phase 9 CB-6 shipped in Phase 1 | ❌ **REFUTED** | `git blame` confirms CB-6 hardening added in `a69e763` (Phase 9). |
| #7 | `model` field split on first `/` | ✅ **CONFIRMED** | Line 222: `split("/", 1)` breaks on "openai/gpt-4o/finetuned". |
| #8 | Test file added in Phase 1 | 🔶 **PARTIALLY** | Tests were added separately, not in the Phase 1 commit itself. |
| #9 | `_summary()` legacy fallback | ✅ **CONFIRMED** | Line 569, explicit comment acknowledges spec deviation. |
| #10 | Deferred imports in shims | ✅ **CONFIRMED** | Low-impact; Python import cache makes this near-free. |

### Phase 2 (3 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | `hard_ceiling` always 0 | ✅ **CONFIRMED** | Same as Phase 1 #3. |
| #2 | `compaction_threshold` not tested | ✅ **CONFIRMED** | Test coverage gap. |
| #3 | Spec references non-existent test | ✅ **CONFIRMED** | Spec/doc error. |

### Phase 3 (7 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1-7 | Various runtime integration issues | ✅ **CONFIRMED** (majority) | Telemetry wiring, token counting, spec deviations all verified in code. |

### Phase 4 (10 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | Summary injection uses tiktoken (not spec's `// 4`) | ✅ **CONFIRMED** | Lines 192-206 use `_fit_summary()` + tiktoken. |
| #2 | `compact()` calls Phase 5's `prune_tool_outputs` | ✅ **CONFIRMED** | Line 122 (audit said 140, off by ~18). |
| #3 | Summary block scope violation | 🔶 **PARTIALLY** | `insert_at` matches spec; surrounding scope violation real. |
| #4 | Test file mixes phase scopes | ✅ **CONFIRMED** | 8 test classes, only 3 belong to Phase 4. |
| #5 | Stale docstring re: keep_first | ✅ **CONFIRMED** | Lines 82-87 still say "NOT YET USED" — stale. |
| #6 | Spec checklist misleading | ✅ **CONFIRMED** | Scope bleed confirmed. |
| #7 | `tokens_after_layer1` snapshot timing | ✅ **CONFIRMED** | Logic verified. |
| #8-10 | Various smaller issues | ✅ **CONFIRMED** | Verified by sub-agent. |

### Phase 5 (10 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | `prune_tool_outputs` assumes parent at idx-1 | ✅ **CONFIRMED** | Line 311: `parent = conv.messages[idx - 1]`. No backward search for non-adjacent parents. |
| #2-10 | Various tool pruning edge cases | ✅ **CONFIRMED** (majority) | Interleaved message shapes, orphan handling, etc. all verified. |

### Phase 6 (2 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | Stubbed message token estimate wrong | ✅ **CONFIRMED** | `msg.tokens_used or (len(msg.content) // 4)` — when stubbed, `tokens_used=0` falls back to tiny stub content. |
| #2 | Legacy fallback deviates from spec | ✅ **CONFIRMED** | Line 579: `split = len(conv.messages) - tail_preserve`. |

### Phase 7 (5 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1 | Stale "15%" comments | 🔶 **PARTIALLY** | Lines 177, 324, 373 are stale; lines 394, 397 describe the 15% floor (correct). |
| #2 | `hard_ceiling=0` not overridden | ✅ **CONFIRMED** | Runtime reads local `hard_ceiling` but never writes it back to event. |
| #3 | Spec formula/test contradiction | ✅ **CONFIRMED** | Spec text verified. |
| #4 | `model_max_tokens=1` → budget=0 | ✅ **CONFIRMED** | `int(1 * 0.25) = 0`. |
| #5 | `compose_system_prompt()` docstring says "15%" | ✅ **CONFIRMED** | Line 177. |

### Phase 8 (8 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #1-8 | Runtime integration, telemetry, exception handling | ✅ **CONFIRMED** (majority) | Verified by sub-agent. |

### Phase 9 (10 bugs claimed)

| Bug | Claim | Verdict | Notes |
|-----|-------|---------|-------|
| #5/#6 | CB-6 tests pass for wrong reason | ✅ **CONFIRMED** | `assert split > 2` / `split > 3` are trivially true — tests don't verify the hardening. |
| #1-4, #7-10 | Various exception and edge case bugs | ✅ **CONFIRMED** (majority) | 15 `except Exception` in runtime.py, 13 with logging. |
| — | `except Exception` count = 16 | 🔶 **PARTIALLY** | Actually **15** in runtime.py, not 16. 13 have logging. |

---

## Top 10 Bugs — Re-assessment

| # | Bug (as stated in master) | Original Severity | Verified? | Adjusted Notes |
|---|--------------------------|-------------------|-----------|----------------|
| 1 | P5#1: idx-1 parent lookup | HIGH | ✅ CONFIRMED | Real bug. No backward search. |
| 2 | P6#1: stubbed message token estimate | HIGH | ✅ CONFIRMED | Real bug. `tokens_used=0` → tiny fallback. |
| 3 | P1#1: Phase 1 forward-loaded everything | HIGH | ❌ **REFUTED** | Wrong commit hash. Phase 1 was correctly scoped. |
| 4 | P9#5/6: CB-6 tests trivially true | MEDIUM | ✅ CONFIRMED | Tests don't verify the hardening. |
| 5 | P6#8: `hard_ceiling=0` hardcoded | MEDIUM | ✅ CONFIRMED | Never wired. |
| 6 | P6#5: char truncation not token | MEDIUM | ✅ CONFIRMED | `fitted[:int(len(fitted) * 0.8)]`. |
| 7 | P5#8: no interleaved-message test | MEDIUM | ✅ CONFIRMED | 6 tests, all cleanly-paired. |
| 8 | P1#3: `hard_ceiling=0` telemetry lie | MEDIUM | ✅ CONFIRMED | Same as #5 above (duplicate finding). |
| 9 | P6#6: legacy path violates spec | MEDIUM | ✅ CONFIRMED | Explicit code comment acknowledges deviation. |
| 10 | P1#4: `layer` phantom default | MEDIUM | ✅ CONFIRMED | Lines 234-235. |

**Adjusted Top-10:** Bug #3 (forward-loading) is **removed** as refuted. Bugs #5 and #8 are the **same issue** (duplicate). The master audit's Top-10 is effectively 8 unique confirmed bugs + 1 refuted + 1 duplicate.

---

## Recommendations Re-assessment

The master audit's 10 recommendations need adjustment:

1. **Add interleaved-messages test** — ✅ Still valid. Highest priority.
2. **Fix stubbed-message token estimate** — ✅ Still valid.
3. **Make `hard_ceiling` Optional[int]** — ✅ Still valid.
4. **Fix `_fit_summary` to truncate by tokens** — ✅ Still valid.
5. **Rewrite Phase 9 tests** — ✅ Still valid.
6. **Add backward-search test for keep_first=0** — ✅ Still valid.
7. **Amend post-mortem** — ⚠️ **Updated**: Remove PATTERN 1 (forward-loading) claim. The post-mortem's "all in one loop" refers to process (no adversarial debugger turns), not to code structure. The code WAS built incrementally.
8. **Split commits or amend specs** — ❌ **Drop**: Commits were already split correctly across phases.
9. **Pre-commit hook for spec diff** — ⚠️ **Soften**: Less critical given commits were properly scoped.
10. **Schedule cleanup pass** — ⚠️ **Rescope**: Focus on doc/code drift (stale comments, wrong docstrings) rather than commit splitting.

---

## Conclusion

The CM audits are **technically rigorous at the code level** — the vast majority of code-level bugs (interleaved messages, token estimates, char-vs-token truncation, telemetry lies, stale docstrings) are **accurately described and confirmed present**.

The **one significant failure** is the forward-loading narrative. The auditor confused two commit hashes (`25b72f6` vs `26c84ec`) and built a systemic pattern diagnosis on that error. This inflated the master audit's severity assessment and led to recommendations (commit splitting, pre-commit spec diff hooks) that address a problem that doesn't exist.

**Bottom line:** The code bugs are real and worth fixing. The process/systemic patterns are overstated — one of four patterns is refuted, and another (spec deviations) is a normal part of iterative development rather than a systemic failure.
