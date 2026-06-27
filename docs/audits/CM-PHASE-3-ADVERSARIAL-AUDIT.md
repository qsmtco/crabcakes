# Phase 3 Context Management — Adversarial Audit Report

**Auditor:** adversarial debugger (subagent)
**Phase:** CM Phase 3 — Runtime Wiring
**Files audited:** `agent/runtime.py`, `agent/context_strategy.py`, `models/conversation.py`, `agent/config.py`, `models/providers.py`, `utils/prompt_loader.py`, `utils/providers_store.py`
**Test files:** `tests/test_runtime_compaction.py`, `tests/test_conversation.py`, `tests/test_phase4.py`
**Spec:** `docs/specs/CM-PHASE-3-INSTRUCTIONS.md`

---

## Summary

Phase 3 was implemented as a superset of the spec. The runtime was extended beyond what Phase 3 specified (added `hard_ceiling` to `_compute_compaction_threshold`, changed the return type to `tuple[int, int]` instead of `float`). All Phase 3 behavioral requirements are implemented correctly. However, the deviation from the spec's exact API creates two HIGH-severity incompatibilities, and the spec's own verification script would FAIL on the actual code due to incorrect return-type expectations.

---

## BUG #1

```
BUG #[1]
Severity: HIGH
Assumption violated: The spec assumes _compute_compaction_threshold() returns a float (the threshold fraction, e.g. 0.80).
Attack vector: The Phase 3 spec's own verification script calls `assert rt._compute_compaction_threshold(conv) == 0.80` and `assert t == 0.90`. With the actual tuple[int, int] return type, these comparisons are always False (tuple != float), and the assertion logic is reversed (comparing soft_ceiling to threshold fraction rather than threshold fraction to threshold fraction).
Reproduction:
    from agent.runtime import AgentRuntime
    from agent.config import AgentConfig, LLMProviderConfig
    from models.conversation import Conversation
    config2 = AgentConfig()
    config2.providers['testprov'] = LLMProviderConfig(
        name='testprov', base_url='x', api_key='***', default_model='testprov/x',
        compaction_threshold=0.90
    )
    rt2 = AgentRuntime(config2, GLib=None)
    conv2 = Conversation(agent_name='test', model='testprov/x')
    t = rt2._compute_compaction_threshold(conv2)
    assert t == 0.90  # FAILS — t is (115200, 128000), not 0.90
Root cause: The spec Step 2 describes the method returning a threshold float, but the implementation was changed to return (soft_ceiling, hard_ceiling) tuple — presumably to combine the two computations in one call. The spec verification script was never updated to match this change. Additionally, the test `test_custom_threshold_per_provider` in `test_runtime_compaction.py` passes a hard-coded 128000 max_tokens provider and expects soft_ceiling to be int(128000*0.90)=115200, not 0.90 — this test is correct and matches the implementation, but the spec verification script asserts the wrong comparison.
Fix: Update the spec verification script to use tuple comparison and extract the threshold fraction from the tuple, or revert _compute_compaction_threshold to return float and let the tool loop compute soft_ceiling inline as the spec intended. Option (a) is preferred since the tuple design is more efficient (single call to _compute_model_max instead of two).
```

---

## BUG #2

```
BUG #[2]
Severity: HIGH
Assumption violated: The spec (Step 3, inline comment) describes "soft_ceiling = model_max * compaction_threshold" computed inline at the call site. The implementation instead computes soft_ceiling inside _compute_compaction_threshold() as `int(hard_ceiling * threshold)`.
Attack vector: Any code reviewer or future developer who reads the spec comment at the tool loop call site (runtime.py:1688-1691) will see the formula "soft_ceiling = model_max * compaction_threshold" and expect that arithmetic to appear at the call site. Instead, the code does `soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)`. While structurally equivalent, the comment's formula is now embedded inside _compute_compaction_threshold rather than at the call site where the comment describes it.
Reproduction: Read the comment at runtime.py:1688-1691:
    # soft_ceiling = model_max * compaction_threshold
    # (e.g. 128000 * 0.80 = 102400 — compact when usage exceeds 80%.)
Then compare to actual code at line 1693:
    soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)
The formula is not visible at the call site; only the tuple unpacking is. A developer tracing the code would not see the computation of soft_ceiling inline — it happens inside _compute_compaction_threshold.
Root cause: The comment was updated to describe the intent, but the formula placement in the comment no longer matches the actual code layout. The implementation is correct; the documentation is misleading.
Fix: Update the comment at lines ~1688-1691 to reference the _compute_compaction_threshold method and its (soft_ceiling, hard_ceiling) return value, rather than showing an inline arithmetic formula that is not actually executed at that location.
```

---

## BUG #3

```
BUG #[3]
Severity: HIGH
Assumption violated: The spec (Step 4) lists exactly 8 fields that MUST appear in the compaction_event telemetry dispatch. The implementation correctly includes all 8 specified fields, but the CompactionEvent dataclass has 14 fields total — 6 of which are NOT forwarded to the breakdown telemetry dispatch.
Attack vector: CompactionEvent dataclass fields: ['turn', 'trigger', 'layer', 'messages_before', 'messages_after', 'messages_removed', 'tokens_before', 'tokens_after', 'tokens_freed', 'summary_tokens_injected', 'soft_ceiling', 'hard_ceiling', 'provider', 'model']. The runtime breakdown dispatch includes only: {trigger, layer, tokens_before, tokens_after, tokens_freed, soft_ceiling, hard_ceiling, summary_tokens_injected} — 8 fields. Missing from dispatch: 'turn', 'messages_before', 'messages_after', 'messages_removed', 'provider', 'model'. A future developer adding a new CompactionEvent field might assume it automatically appears in the breakdown dispatch; it does not.
Reproduction:
    from agent.context_strategy import CompactionEvent, DefaultContextStrategy
    import dataclasses
    fields = [f.name for f in dataclasses.fields(CompactionEvent)]
    # ['turn', 'trigger', 'layer', 'messages_before', 'messages_after',
    #  'messages_removed', 'tokens_before', 'tokens_after', 'tokens_freed',
    #  'summary_tokens_injected', 'soft_ceiling', 'hard_ceiling', 'provider', 'model']
    # But runtime breakdown["compaction_event"] only includes 8 of these.
Root cause: The breakdown dispatch is intentionally partial (per spec requirement), but there is no documentation of which CompactionEvent fields are forwarded and why the others are excluded. 'provider' and 'model' are in CompactionEvent but not forwarded; 'messages_removed' is redundant with the top-level breakdown field; 'turn' is available via the _compaction_events history but not in the per-call breakdown.
Fix: Add an inline comment in runtime.py near the breakdown["compaction_event"] block listing which CompactionEvent fields ARE forwarded and why. Alternatively, forward all fields from CompactionEvent to the breakdown for future-proofing and to avoid this partial-coverage confusion.
```

---

## BUG #4

```
BUG #[4]
Severity: MEDIUM
Assumption violated: The test `test_custom_threshold_per_provider` sets compaction_threshold via post-construction attribute assignment (`provider.compaction_threshold = 0.90`) rather than through the LLMProviderConfig constructor. This does not exercise the constructor path that a real YAML config loader would use when loading providers.yaml.
Attack vector: If a future developer modifies LLMProviderConfig to validate compaction_threshold in __init__ (e.g., type checking, range clamping, or making the field final), this test pattern would silently bypass the constructor validation. Similarly, if dataclasses.Frozen=True is ever added to prevent mutable attributes, this test would raise an error.
Reproduction:
    # test_runtime_compaction.py TestCompactionThreshold.test_custom_threshold_per_provider
    provider = LLMProviderConfig(
        name='minimax', base_url='x', api_key='***',
        default_model='minimax-m3', caller='minimax',
        max_tokens=1_048_576,
    )
    provider.compaction_threshold = 0.90  # post-construction, not via constructor
    # vs. constructor form:
    LLMProviderConfig(..., compaction_threshold=0.90)  # not used in this test
Root cause: The test was written to set the attribute directly after object construction rather than passing it as a constructor argument. This is a test smell — it doesn't exercise the same code path that production config loading uses.
Fix: Update the test to use the constructor argument: `LLMProviderConfig(..., compaction_threshold=0.90)`. Keep the post-construction assignment as a supplementary test if the direct attribute mutation behavior needs separate coverage.
```

---

## BUG #5

```
BUG #[5]
Severity: MEDIUM
Assumption violated: The spec's COMPLETENESS checklist and verification steps reference "tests/test_prompt_loader_budget.py" as a test file that exists and should pass. This file does not exist in the repository.
Attack vector: If a developer follows the spec literally and runs `python3 -m pytest tests/test_prompt_loader_budget.py`, they get FileNotFoundError. This is not a regression in the code, but the spec references a test file that was never created, which creates a documentation-implementation gap.
Reproduction:
    cd /home/q/projects/crabcakes
    python3 -m pytest tests/test_prompt_loader_budget.py
    # ENOENT: no such file or directory
Root cause: The spec references a test file for the prompt_loader budget feature (Phase CB-2), but this file was never created. The budget feature itself is implemented in utils/prompt_loader.py and is tested indirectly by other test files, but there are no direct unit tests for the budget enforcement logic.
Fix: Either create `tests/test_prompt_loader_budget.py` with tests for the budget enforcement logic in `utils/prompt_loader.py` (_apply_system_prompt_budget, _truncate_file_context_smart), or remove the reference from the spec and the COMPLETENESS checklist.
```

---

## BUG #6

```
BUG #[6]
Severity: MEDIUM
Assumption violated: The spec says "The _compute_compaction_threshold() method follows the SAME provider resolution pattern as _compute_model_max() for consistency." The _compute_model_max() docstring says "Returns 128_000 when: conv.model is None and self._config.default_provider is not configured". The _compute_compaction_threshold() docstring says the same words but should say "Returns (102400, 128000) when..." — the docstring was copy-pasted from _compute_model_max and not updated for the tuple return type.
Attack vector: A developer reading the _compute_compaction_threshold docstring (lines ~1542-1555) sees:
    Returns (int(128_000 * 0.80), 128_000) = (102_400, 128_000) when:
      - conv.model is None and self._config.default_provider is not configured
But the docstring actually says "Returns 128_000 when:" — this is misleading because the return type is tuple, not int. The docstring's "Returns 128_000" refers to hard_ceiling, but without clarifying that the method returns a tuple.
Reproduction:
    t = rt._compute_compaction_threshold(conv)
    # t is (102400, 128000) — a tuple
    # But docstring says "Returns 128_000 when..." implying int
Root cause: The docstring was partially updated (the docstring body describes the tuple computation) but the "Returns 128_000" line in the docstring was not updated to reflect the tuple return type. This is a copy-paste error from _compute_model_max.
Fix: Update the docstring to accurately say "Returns (soft_ceiling, hard_ceiling) = (int(threshold * max_tokens), max_tokens) tuple when..." and update the "Returns 128_000" bullet to say "Returns (102400, 128000) default when...".
```

---

## BUG #7

```
BUG #[7]
Severity: LOW
Assumption violated: The spec's comment at the tool loop call site (spec Step 3) says "Conversation.trim_to_token_limit() is unit-tested at tests/test_conversation.py:249 (TestConversationTrim) and tests/test_phase4.py:280 (summary-on-trim)." After Phase 3, the tool loop no longer calls trim_to_token_limit — it calls self._context_strategy.compact(). The referenced tests exercise the delegation shim (conv.trim_to_token_limit), not the actual runtime call path.
Attack vector: When a future developer reads the runtime.py comment and follows the reference to tests/test_conversation.py:249, they find tests for the shim (conv.trim_to_token_limit), not tests for the actual strategy call. This creates a false sense of coverage — the shim tests are valid but they don't directly verify the _context_strategy.compact() call in the tool loop.
Reproduction: Read the comment at runtime.py:1688-1691:
    # Conversation.trim_to_token_limit() is unit-tested at
    # tests/test_conversation.py:249 (TestConversationTrim) and
    # tests/test_phase4.py:280 (summary-on-trim).
But the tool loop calls `self._context_strategy.compact(conv, soft_ceiling)` — not `conv.trim_to_token_limit()`. The referenced tests cover the shim, which delegates to the same strategy method, but the comment implies the test file directly covers the tool loop call site.
Root cause: The comment at the call site was retained from the old code (which called conv.trim_to_token_limit directly). It was partially updated ("The strategy lives in agent/context_strategy.py and replaces the old conv.trim_to_token_limit() call") but the test file reference was left unchanged.
Fix: Update the comment to reference the actual test files that cover the strategy: tests/test_context_strategy.py (which tests DefaultContextStrategy.compact directly) and tests/test_runtime_compaction.py (which tests the _compute_compaction_threshold and compaction event telemetry). Remove the reference to tests/test_phase4.py:280 if it is no longer directly relevant to the tool loop.
```

---

## Observations (Not Bugs — Informational)

1. **Strategy wiring is correct.** `self._context_strategy = DefaultContextStrategy()` is in `__init__()` after the audit log, exactly where spec Step 1 requires it. Verified: `isinstance(rt._context_strategy, DefaultContextStrategy)` passes.

2. **Compaction threshold computation is correct.** The `soft_ceiling = int(hard_ceiling * threshold)` computation uses `int()` for floor, matching `_compute_model_max`'s return type semantics. Boundary values verified: threshold=0.0 → default 0.80 used; threshold=1.0 → exactly 1.0 accepted; threshold=1.5 → default used.

3. **Telemetry pipeline is correct end-to-end.** `_compaction_events` list, `_compaction_this_iteration` flag, `_last_trim_removed` property, and `breakdown["compaction_event"]` all wire together properly. The history cap at 100 events is correctly implemented.

4. **`_token_estimate_cache` invalidation is correct throughout.** Every mutation path (pop, insert, content stubbing in prune_tool_outputs) invalidates the cache. The `prune_tool_outputs` method has explicit `conv._token_estimate_cache = None` after each stub mutation.

5. **CB-6 invariant is maintained.** The `_select_prune_candidate` and `compact` methods in `context_strategy.py` handle TOOL_RESULT + ASSISTANT-with-tool_calls pairs correctly, including the keep_first boundary case where the parent ASSISTANT is in the protected region.

6. **Test suite is clean.** 76 tests pass (68 in test_conversation.py, 8 in test_runtime_compaction.py). No regressions detected.

7. **Partial scope coverage in spec.** The spec references `utils/prompt_loader.py` and `utils/providers_store.py` as files to read, but neither is modified by Phase 3. They are read-only references for context. This is correctly handled.

---

## Verdict

The Phase 3 implementation is **functionally correct** — it wires the strategy, computes the threshold, and dispatches telemetry as required. However, it **deviates from the spec's exact API description** (`float` return type vs `tuple[int, int]`) in a way that would cause the spec's own verification script to fail on its assertions. The implementation is a superset and improvement over the spec's described API (returning both ceilings in one tuple is more efficient), but the spec was not updated to match. The spec needs to be updated to match the implementation, not the other way around.

The most critical actionable items are:
1. **Update the spec verification script** to use tuple comparison (BUG #1)
2. **Update the call-site comment** to reference the actual formula location (BUG #2)
3. **Document which CompactionEvent fields are forwarded** in the breakdown telemetry (BUG #3)
4. **Create tests/test_prompt_loader_budget.py** or remove the reference from the spec (BUG #5)
5. **Update _compute_compaction_threshold docstring** to reflect tuple return type (BUG #6)
