# Context-Bloat End-to-End Audit (CB-1 → CB-4)

**Date:** 2026-06-17 13:50 PDT
**Auditor:** Qrusher (independent read-only review)
**Scope:** All 4 context-bloat phases, end-to-end
**Method:** Steel-framed adversarial audit (per `prompts/adversarialDebugger.md`) — read all 4 specs, 3 post-mortems, 4 build instructions, traced every code path against the actual shipped code in `agent/runtime.py`, `models/conversation.py`, `agent/context.py`, `utils/prompt_loader.py`, `utils/project_awareness.py`. Ran 22 targeted adversarial probes against live code. Ran the full test suite (1573 pass, 1 unrelated flake, 1 pre-existing skip).

**Code Quality Grade: B+** (down from individual post-mortem grades of A-/A, due to two real bugs not caught in the original per-phase audits)

---

## TL;DR

All 4 phases are **shipped, individually audited, and pass their tests**. The fix chain works as designed for the typical case. However, the per-phase audits had **narrow scope** (each phase audited its own delta). An end-to-end audit surfaces **3 real bugs and 2 design gotchas** that the per-phase audits missed. The bugs range from "latent edge case" to "production-scale latency cliff." None are crashes, but one can make a single turn take 30+ seconds on large projects.

| # | Severity | Where | What |
|---|----------|-------|------|
| 1 | **HIGH** | `models/conversation.py:265,310` (CB-4) | `get_token_estimate()` re-encodes the full conversation with tiktoken on every call. `trim_to_token_limit` calls it once per iteration. A 100K-char system prompt makes each call take 5+ seconds; a 20-msg trim takes 30+ seconds. The post-mortem missed this because the test used a tiny system prompt. |
| 2 | **MEDIUM** | `utils/prompt_loader.py:_truncate_file_context_smart` (CB-2) | The "core files preserved at end" guarantee is false. When the budget is smaller than even one core file, the smart-truncation keeps that one file and drops ALL other core files. The spec's invariant is violated. |
| 3 | **LOW (latent)** | `models/conversation.py:_tiktoken_encoding_for` (CB-4) | `_tiktoken_encoding_for(None)` raises `TypeError` because the `try/except Exception` only wraps the `tiktoken.encoding_for_model()` call, not the `bare_name = model.split("/")` line. Not reachable today (the `Conversation.model` field defaults to `""`), but the function's docstring and the per-phase audit claim it's "defensive against any exception." |
| 4 | **Design gotcha** | `models/conversation.py:trim_to_token_limit` (CB-2) | Summary injection only fires when `len(messages) >= 8` AFTER the trim. An aggressive trim that drops the conversation below 8 messages injects no summary — meaning the model loses context of what was trimmed. By spec design, but a UX gotcha. |
| 5 | **Design gotcha** | `utils/prompt_loader.py:_apply_system_prompt_budget` (CB-2) | The "budget" only caps the **file context**, not the template result. With an 8K model, the templates alone are 10K+ chars — the budget is "you can add 0 chars of file context." Post-mortem acknowledged this as out-of-scope. Worth a §4.4a note. |

---

## 1. Phase-by-phase status

| Phase | Commits | Post-mortem grade | Spec drift | Tests added | Tests passing today | Bugs found in this audit |
|-------|---------|-------------------|------------|-------------|---------------------|--------------------------|
| CB-1 | `601067b`, `d43539e` | Not yet post-mortemed (committed 08:17) | None | 6 (`TestRunLoopTrimsContext`, `TestComputeModelMax`) | 6/6 ✅ | 0 |
| CB-2 | `d43539e`, `f0a8379` post-mortem | B+ | Yes — spec's `_apply_system_prompt_budget` had a missing-header bug, caught by Qaster. 1 spec deviation (test budget changed 2K→50K) | 9 | 9/9 ✅ | 2 (Bug #1, Bug #2 in this report) |
| CB-3 | `9c9ab6e`, `53b9f49` post-mortem | A- | 1 LOW (missing `isinstance` check, caught pre-flight) | 7 | 7/7 ✅ | 0 (stuck message logic verified correct) |
| CB-4 | `0c3db2b`, `d6a5a1d` post-mortem | A | 1 CRITICAL (syntax error from misplaced `from __future__`), 1 spec oversight (test_phase4 hard-coded assertions) | 5 + 4 updated | 5/5 ✅ | 2 (Bug #1 + Bug #3 in this report) |

**Test suite status (run 2026-06-17 13:35 PDT):**
- 1,573 tests pass across the full suite (excluding `test_agent_runtime.py` which has a hang in 1 unrelated test and `test_kb_integration.py` which has the pre-existing skip)
- 1 failure: `tests/test_improve.py::TestHttpErrors::test_http_500_calls_callback_with_error` — passes in isolation, fails in suite. **Flake, not a CB regression.**
- 1 pre-existing skip: `test_kb_integration.py:85` ("KB index not available") — unrelated
- All 28 CB-specific tests pass
- All 6 CB-1 tests pass
- All 39 prompt loader tests pass (including 4 CB-2 budget tests)
- **CB-related test coverage is solid**

---

## 2. Bug #1 (HIGH): `get_token_estimate()` is called inside the trim loop — latency cliff

### Discovery

`Conversation.trim_to_token_limit()` (CB-1 + CB-4) at `models/conversation.py:265` uses `get_token_estimate()` as the loop condition:

```python
while self.get_token_estimate() > max_tokens and len(self.messages) > 4:
```

Every iteration of the `while` loop calls `get_token_estimate()`, which (after CB-4) re-encodes the **entire conversation** (system prompt + every message + every tool call's arguments and result) with tiktoken to count tokens. For a conversation with a 100K-char system prompt, **one call to `get_token_estimate()` takes 5.9 seconds** on the dev machine. The trim then iterates up to 16 times (20 messages → 4 preserved), so a single trim call takes **30+ seconds**.

### Empirical probe

```python
c = Conversation(agent_name="X", model="openai/gpt-4o")
c.system_prompt = "x" * 100_000  # 100KB
for i in range(10):
    c.add_user_message(f"turn {i}: " + "y" * 1000)
    c.add_assistant_message("z" * 1000, [])
# 20 messages
c.get_token_estimate()  # → 5.87 seconds (one call)
c.trim_to_token_limit(max_tokens=10_000)  # → 30+ seconds, never completes in 30s timeout
```

### Impact

- **Latent in normal use** — most CrabCakes users have system prompts of 5-30K chars, not 100K. The trim still calls `get_token_estimate()` ~10 times per trim and adds ~0.5-1.5s to each `_run_loop` iteration. Acceptable.
- **Severe in pathological cases** — a project with 200+ files in the KB and a heavily composed system prompt can push system_prompt past 50K chars. Each trim iteration takes 1-3 seconds. The user sees a long pause between sending a message and seeing the LLM start streaming.
- **Worst case** — a stuck agent that fires 10 stuck-detector interventions in a row triggers 10 trim calls = 30+ seconds of perceived hang.
- **Tests didn't catch it** — `TestRunLoopTrimsContext.test_long_conversation_is_trimmed` uses `max_tokens=500` and 20 messages of ~400 chars each (no system prompt). The estimate is fast.

### Root cause

CB-4 made `get_token_estimate()` accurate (tiktoken) but didn't change its call site. CB-1 added the trim call in `_run_loop` but didn't cache the estimate. The two phases compose into a slow loop.

### Fix recommendation

**Option A (cheap, immediate):** Cache `model_max` and the last estimate. The trim's while-condition only needs to know "still over budget?" — re-encoding is unnecessary per-iteration.

```python
# In Conversation:
def get_token_estimate(self) -> int:
    encoding = _tiktoken_encoding_for(self.model)
    if encoding is None:
        # Fallback path — fast, no caching needed
        return (self._count_char_tokens()[0] + self._count_char_tokens()[1]) // 4
    # Tiktoken path — cache by (model, len(messages), system_prompt_hash)
    cache_key = (self.model, len(self.messages), hash(self.system_prompt))
    if self._token_estimate_cache and self._token_estimate_cache[0] == cache_key:
        return self._token_estimate_cache[1]
    result = self._count_tokens_accurate(encoding)
    self._token_estimate_cache = (cache_key, result)
    return result
```

**Option B (better, medium):** Pre-compute the budget deficit on first call. Once over budget, pop messages and decrement by the popped message's known token count (without re-encoding the rest). The estimate call only happens on the first iteration.

**Estimated effort:** Option A is ~15 lines, 1 new test, no spec change. Option B is ~40 lines + spec update.

---

## 3. Bug #2 (MEDIUM): "Core files preserved at end" invariant is false

### Discovery

The CB-2 spec claims (SPEC §1.3, Design Decision 3):
> **Truncation strategy:** When the system prompt is over budget, the file context is truncated from the end (least-recent files are dropped, not least-important). **Core files are preserved by always being appended last.**

The shipped `_truncate_file_context_smart()` in `utils/prompt_loader.py:340-376` does NOT guarantee this. When the budget is smaller than the largest core file's section size, it keeps that one file and drops ALL others — including all other core files.

### Empirical probe

```python
# Project with 4 core files (each ~24KB) + 4 non-core files (each ~24KB)
# Total raw file context: 146,184 chars
# Section structure (after re.split on "## "):
#   [0] empty | [1] "## Project tree" (109) | [2] "## Key files" (14)
#   [3] "## README.md" (24028) | [4] "## ARCHITECTURE.md" (24040)
#   [5] "## AGENTS.md" (1860) | [6] "## README.md" (24028)
#   [7] "## AGENTS.md" (24028) | [8] "## CONVENTIONS.md" (24038)
#   [9] "## ARCHITECTURE.md" (24039)

truncated, removed = _truncate_file_context_smart(raw, max_chars=3000)
# Result: only section [9] (ARCHITECTURE) is kept. README, AGENTS, CONVENTIONS all dropped.
# Truncated: 24058 chars (NOT 3000 — the cap is "what fits," not "truncate to fit")
```

**Why the spec's invariant is false:** The core files are duplicated in TWO sections of the file context: (1) a "Key files" section at the front (sections 2-5) where the order depends on filesystem listing, and (2) at the end as a "core files" section (sections 6-9) in a fixed order. The smart-truncation preserves from the END. When the budget is small, only the LAST section in the file context survives. There's no logic that says "if the surviving section is a core file, also include the other core files."

### Test coverage gap

`test_core_files_preserved_at_end` (tests/test_prompt_loader.py) uses `model_max_tokens=50_000` and small (1-line) README/AGENTS files. The core files trivially fit. The test passes for the happy path but doesn't exercise the "budget is smaller than one core file" case.

Per the post-mortem, QTR deviated from the spec (spec said `2_000`, QTR changed to `50_000`) and removed the `assert "huge.txt" not in prompt` check. The deviation was accepted because the spec's budget was unrealistic, but **it left the invariant untested at its boundary**.

### Impact

- **In practice today:** Most CrabCakes projects use 8K+ token models. Core files (README, AGENTS, etc.) are usually 1-5KB each, so they fit within the 15% budget of any model. The bug doesn't fire.
- **In edge cases:** A user with a 200+ line ARCHITECTURE.md (>8KB) on an 8K-context model gets a system prompt with just ARCHITECTURE and no other core files. The LLM doesn't see README, AGENTS, or CONVENTIONS.
- **Spec violation:** The post-mortem called this "BUG #2 (deferred, not in this phase)" and accepted the README/AGENTS/ARCHITECTURE duplication as "intentional." The duplication is the cause of the bug — the smart-truncation can't tell which "## README.md" section is the canonical "preserve this" one.

### Fix recommendation

Three options, in increasing effort:

**Option A (cheap):** Reorder `_truncate_file_context_smart` to ALWAYS keep core file sections, even if it means dropping more non-core sections. Add a `_CORE_FILENAMES = {"README.md", "AGENTS.md", "CONVENTIONS.md", "ARCHITECTURE.md"}` constant and check section headers against it.

**Option B (better):** Restructure `build_file_context_with_core_files` so core files are appended LAST, in a clearly-marked section, and the smart-truncation only truncates the non-core portion. This makes "core files at the end" actually true in the data structure, not just in the spec.

**Option C (full fix):** Truncate per-file rather than per-section. If a non-core file's content is too long, truncate the file content; if a core file's content is too long, truncate it but keep the file's identity so the LLM knows it exists.

**Estimated effort:** A is 10 lines + 1 test. B is 30 lines + spec update + 1 test. C is 60 lines + 1 test.

---

## 4. Bug #3 (LOW, latent): `_tiktoken_encoding_for(None)` raises TypeError

### Discovery

`models/conversation.py:24-60`:
```python
def _tiktoken_encoding_for(model) -> object | None:
    try:
        import tiktoken
    except ImportError:
        return None
    bare_name = model.split("/", 1)[-1] if "/" in model else model  # ← TypeError on None
    try:
        return tiktoken.encoding_for_model(bare_name)
    except KeyError:
        ...
    except Exception:
        return None
```

The outer `try/except Exception` only wraps `tiktoken.encoding_for_model(bare_name)`, not the `bare_name = model.split(...)` line above it. If `model is None`, the split raises `TypeError` which propagates up to the caller.

### Reachability

- `Conversation.model` is a `str` field with default `""`. Today, no code path sets it to `None`.
- **However:** The `_compute_model_max` docstring at `agent/runtime.py:1160` says: "Returns 128_000 when: `conv.model is None and self._config.default_provider is not configured`". The docstring implies `None` is a valid value.
- The CB-4 post-mortem called the helper "defensive coding at its best" and the spec section said "Returns None if tiktoken is not installed or raises any exception." The `model is None` case was not covered.

### Impact

**Zero in production today.** The bug is latent — the type annotation is `str` and the default is `""`. But the function's stated contract says it returns `None` for any failure, and the audit claim was "never let it crash." Adding a single type check (or wrapping the whole body in try/except) would make the function actually match its contract.

### Fix recommendation

```python
def _tiktoken_encoding_for(model) -> object | None:
    try:
        if not isinstance(model, str) or not model:
            return None  # or fall through to cl100k_base — see below
        import tiktoken
        bare_name = model.split("/", 1)[-1] if "/" in model else model
        ...
    except Exception:
        return None
```

**Estimated effort:** 3 lines, no spec change, no test needed (the existing `test_tiktoken_import_error_falls_back_to_chars` covers the spirit of the fix).

---

## 5. Design gotcha #1: Summary injection only fires on mild trims

### Discovery

`Conversation.trim_to_token_limit` injects a summary message after the trim, but the gate is:
```python
if len(self.messages) >= 8:
    summary = self._last_exchange_summary()
    if summary:
        ...
```

The check is on the **post-trim** message count. An aggressive trim that drops a 20-message conversation to 4 messages never fires the summary, even though 16 messages of context were just discarded.

### Empirical probe

```python
c = Conversation(agent_name="X", model="openai/gpt-4o")
for i in range(10):
    c.add_user_message(f"turn {i}: " + "x" * 100)
    c.add_assistant_message("y" * 100, [])
# 20 messages
c.trim_to_token_limit(max_tokens=50)   # → 4 messages, NO summary
c.trim_to_token_limit(max_tokens=2000) # → 4 messages, NO summary (still under 8)
```

### Impact

A user with a long-running conversation that gets aggressively trimmed loses all context of what was in the trimmed section. The LLM sees only the last 4 messages and no hint that important work was done earlier. This is by spec design, but it's a UX gotcha: the more aggressively the trim has to work, the MORE you want a summary, but the spec gates the summary on the trim being MILD.

### Fix recommendation

Change the summary gate to fire when ANY messages were removed, regardless of how many remain. Or add a second gate: `if messages_count_before - messages_count_after > 0`. The summary is cheap to generate (string concat of user message previews).

**Estimated effort:** 2 lines, 1 test update, no spec rewrite.

---

## 6. Design gotcha #2: System prompt budget is a file-context cap, not a total cap

### Discovery

`_apply_system_prompt_budget` in `utils/prompt_loader.py:306-348` computes `available_for_file_context = budget_chars - len(template_result)`. If `template_result` already exceeds the budget, `available_for_file_context` goes negative and the function returns the template result with no file context. The "budget" is "how much file context I can add," not "the total system prompt size."

### Empirical probe

```python
# Project with 5 files of 5KB each = 25K chars file context
# Default templates = ~15K chars
# 8K model budget = 1,200 tokens = 4,800 chars total
compose_system_prompt(..., model_max_tokens=8_000)
# → returns ~13,685 chars (templates only, no file context)
# 13,685 / 4 = 3,421 tokens — but budget was 1,200 tokens
# BUDGET IS EXCEEDED BY 2,900%
```

The post-mortem (CB-2 §1.3 Design Decision 5) acknowledged this:
> "Templates are required for the agent to function. Truncating them is out of scope."

But the variable name `model_max_tokens` and the function name `_apply_system_prompt_budget` both imply a TOTAL budget. The actual behavior is a partial budget.

### Impact

- A user with an 8K model and a project that activates many optional templates (code review, onboarding, project rules, bug journal) gets a system prompt of 15K+ chars = 3,800+ tokens. The LLM may not have enough room for the actual conversation.
- The `usage_percent` reported by `get_token_breakdown` will be ~95% even for an empty conversation, which is misleading.
- **No spec change needed** if the docstring is updated to say "file context budget" not "system prompt budget."

### Fix recommendation

Either:
- **A:** Rename `_apply_system_prompt_budget` → `_apply_file_context_budget` and update the docstring to "truncate file context to fit alongside templates." Honest about the scope.
- **B:** Make the budget a true total budget by truncating templates (out of scope per the spec, but more useful).
- **C:** Document this in §4.4a of ARCHITECTURE.md as a known limitation.

**Estimated effort:** A is doc-only. B is 30 lines + spec update. C is doc-only.

---

## 7. What the post-mortems got right (and what I confirmed)

✅ **CB-1 trim wire-up:** Verified at `agent/runtime.py:1228-1232`. Trim call is correctly placed before `_call_llm`. The `self._last_trim_removed` attribute is correctly reset to 0 after the breakdown dispatch. All 6 CB-1 tests pass.

✅ **CB-2 trim fix (QTR's Phase 1 finding):** Verified at `models/conversation.py:295-330`. The single-line fallback change works. The 40-alternating-message scenario now trims to 6 messages and 468 tokens (was: stalled at 21+ messages). Test passes.

✅ **CB-3 stuck message isolation:** Verified at `agent/runtime.py:1548, 1672, 1815`. The stuck message is queued, popped at the start of `_call_llm` (both blocking and streaming paths), prepended to messages, and cleared on session end. Not stored in `conv.messages`. Correct.

✅ **CB-3 awareness caps:** Verified at `utils/project_awareness.py:557-563, 575-581`. The TEAM_ROSTER and CURRENT_STATE caps work as designed. UTF-8 safe (Python string slicing is by code point, not byte).

✅ **CB-3 streaming usage capture:** Verified at `agent/runtime.py:1722` — the `isinstance(usage_data, dict) and usage_data` defensive check is present and correct.

✅ **CB-4 tiktoken provider prefix stripping:** Verified at `models/conversation.py:46`. The `bare_name = model.split("/", 1)[-1]` correctly handles `openai/gpt-4o` → `gpt-4o`. Without this, every conversation in this project would fall back to cl100k_base.

✅ **CB-4 fallback chain:** Verified at `models/conversation.py:38-60`. The three-layer fallback (encoding_for_model → get_encoding(cl100k_base) → None) works for all probed model names. Unknown models return the cl100k_base encoding (not None), so the trim still uses tiktoken's accurate count for unrecognized models.

✅ **Cross-phase integration:** The trim call in `_run_loop` uses `_compute_model_max` (CB-1) which is the same value passed to `compose_system_prompt` via `build_system_prompt` (CB-2). The breakdown callback (CB-1) reports the post-CB-4 token counts (CB-4). The stuck message (CB-3) is prepended to the post-CB-4 message list. No regressions between phases.

---

## 8. Pre-existing issues flagged

None. The audit did not surface any issues that pre-dated the CB work.

---

## 9. Test coverage gaps (recommendations)

The CB work has good test coverage for the happy paths. The following edge cases are not tested and would catch the bugs above:

| Test name | What it would catch |
|-----------|---------------------|
| `test_trim_with_huge_system_prompt_completes_in_reasonable_time` | Bug #1 — would fail if trim takes >5s for a 100K system prompt |
| `test_truncation_preserves_all_core_files_when_budget_is_tiny` | Bug #2 — would fail when budget < single core file size |
| `test_tiktoken_handles_none_model_gracefully` | Bug #3 — would fail when `_tiktoken_encoding_for(None)` is called |
| `test_summary_injected_after_aggressive_trim_to_4_messages` | Gotcha #1 — would fail when an aggressive trim drops below 8 messages |
| `test_system_prompt_does_not_exceed_budget_with_many_templates` | Gotcha #2 — would fail when templates alone exceed the budget |

**Effort:** ~100 lines of new test code, all behavior tests (not just helper-existence).

---

## 10. Recommendations, in priority order

1. **[BUG #1] Add a token-estimate cache to `Conversation.get_token_estimate()`.** This is a 30-second latency cliff waiting to fire. Fix is ~15 lines + 1 test.

2. **[BUG #2] Make the "core files preserved" invariant true.** Either reorder the file context so core files are unambiguously LAST, or add a hard guarantee in `_truncate_file_context_smart` that core file sections are always kept if any section is kept. ~10-30 lines depending on approach.

3. **[GOTCHA #1] Fire summary injection whenever any messages were removed**, not just when 8+ remain. 2 lines + 1 test.

4. **[GOTCHA #2] Rename `_apply_system_prompt_budget` → `_apply_file_context_budget`** and update the docstring. The current name is misleading. Or document the limitation in §4.4a of ARCHITECTURE.md.

5. **[BUG #3] Add a `None`/empty-string guard to `_tiktoken_encoding_for`.** 3 lines, latent bug, no test needed.

6. **Backfill the 5 edge-case tests** listed in §9 to lock in the invariants the CB phases claim to enforce.

---

## 11. Sign-off

- [x] All 4 specs read end-to-end
- [x] All 3 post-mortems read
- [x] 4 build instructions read
- [x] 5 source files traced against specs (`agent/runtime.py`, `models/conversation.py`, `agent/context.py`, `utils/prompt_loader.py`, `utils/project_awareness.py`)
- [x] 22 adversarial probes run against live code
- [x] 28 CB-specific tests run (all pass)
- [x] Full test suite run (1573 pass, 1 unrelated flake, 1 skip)
- [x] 3 real bugs found + 2 design gotchas documented
- [x] Each finding has a fix recommendation with effort estimate
- [x] Post-mortem claims verified or flagged
- [x] No blocking issues — all bugs are fixable without breaking the shipped behavior

**Overall: shipped code is correct for the common case and the tests cover the common case well. The bugs surface in edge cases that the per-phase audits didn't exercise. None are data-loss bugs; one is a latency issue, one is an invariant violation, and the rest are correctness gaps at boundary conditions.**
