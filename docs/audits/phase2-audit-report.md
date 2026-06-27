# Phase 2 Context Management — Adversarial Audit Report

**Scope:** `compaction_threshold: float = 0.80` config round-trip chain (4 files)
**Spec:** `docs/specs/CM-PHASE-2-INSTRUCTIONS.md`
**Phase:** 2 of Context Management Roadmap
**Auditor:** Adversarial debugging protocol per `prompts/adversarialDebugger.md`

---

## Summary

The Phase 2 `compaction_threshold` round-trip chain is **correctly implemented** end-to-end. All 4 required files were modified, and the value survives the full journey: `providers.yaml` → `_from_dict()` → `ProviderConfig` → `_to_llm_provider()` → `LLMProviderConfig` → runtime. The spec verification script passes all 3 assertions (custom value 0.90, default 0.80, backward-compat from old dict).

Three issues were found: one MEDIUM-severity telemetry bug (`CompactionEvent.hard_ceiling` always 0), one LOW-severity test coverage gap (`compaction_threshold` not asserted in `test_round_trip_preserves_all_fields`), and one LOW-severity documentation error (spec references a non-existent test file).

---

## BUG #[1]

**Severity:** MEDIUM

**Assumption violated:** The `CompactionEvent` dataclass `hard_ceiling` field (documented as "The hard_ceiling used for this cycle") will be populated with the actual computed hard ceiling when a compaction cycle runs.

**Attack vector:** Call `compact()` on a `DefaultContextStrategy` and inspect `last_result.hard_ceiling`. It will be `0` even though the runtime's `_compute_compaction_threshold()` computed the correct value.

**Reproduction:**
```python
from agent.context_strategy import DefaultContextStrategy
from models.conversation import Conversation, Message, MessageRole

strategy = DefaultContextStrategy()
conv = Conversation(agent_name="Coder", model="openai/gpt-4o")
for i in range(20):
    conv.add_user_message("x" * 5000)
    conv.add_assistant_message("y" * 5000, [])
strategy.compact(conv, 20000)  # soft_ceiling passed as token_budget
print(strategy.last_result.hard_ceiling)   # → 0  (wrong — should be 128000)
print(strategy.last_result.soft_ceiling)   # → 20000 (the token_budget arg)
```

**Root cause:** In `agent/context_strategy.py` `compact()`, the `CompactionEvent` is constructed with `hard_ceiling=0` hardcoded:

```python
self._last_result = CompactionEvent(
    ...
    soft_ceiling=token_budget,
    hard_ceiling=0,  # not known at strategy level in Phase 1
    ...
)
```

The runtime passes `soft_ceiling` as the `token_budget` argument, but `compact()` has no access to the `hard_ceiling` value — it is computed by the runtime before calling `compact()`, and the runtime only passes `soft_ceiling` (the trigger point), not `hard_ceiling` (the ceiling).

The telemetry docstring for `CompactionEvent.hard_ceiling` says: *"The hard_ceiling used for this cycle (in tokens)."* The field is populated with `0`, violating the documented meaning.

**Fix:** Either:
1. Pass `hard_ceiling` alongside `token_budget` in the `compact()` call in `runtime.py` (requires updating the `ContextStrategy` protocol), or
2. Update the `CompactionEvent` dataclass to accept `None` for `hard_ceiling` and document it as optional when unknown at strategy level, or
3. Have the strategy compute `hard_ceiling` independently (duplicating `_compute_compaction_threshold` logic, not recommended)

The cleanest fix is option 1: add `hard_ceiling: int` to the `compact()` signature and pass it through. Then populate `CompactionEvent.hard_ceiling` correctly.

---

## BUG #[2]

**Severity:** LOW

**Assumption violated:** All provider config fields are tested for round-trip preservation in `test_round_trip_preserves_all_fields`.

**Attack vector:** Add `compaction_threshold=0.90` to a provider, save → load → verify. The existing test passes (does not check this field), so a future refactor that accidentally drops `compaction_threshold` from `_to_dict()` would not be caught by the test suite.

**Reproduction:**
```python
# Add to test_round_trip_preserves_all_fields:
p = _make_provider("full", compaction_threshold=0.90, ...)
ps.save_providers([p])
loaded = ps.load_providers()
assert loaded[0].compaction_threshold == 0.90  # This assertion is missing
```
Currently this assertion does not exist in the test.

**Root cause:** The test was not updated to cover the new `compaction_threshold` and `default_max_tokens` fields when they were added. The spec verification script exercises the chain correctly, but the permanent test suite has a gap — a regression could slip through unnoticed.

**Fix:** Add `assert loaded[0].compaction_threshold == 0.90` (or whatever value was set) to `test_round_trip_preserves_all_fields`. Similarly add coverage for `default_max_tokens` if not already present.

---

## BUG #[3]

**Severity:** LOW

**Assumption violated:** The spec COMPLETENESS checklist is a reliable record of what was implemented and what files are in scope.

**Attack vector:** A developer reading the Phase 2 spec COMPLETENESS checklist sees `test_prompt_loader_budget.py` referenced as one of the files in scope. This file does not exist. The developer might search for it and conclude something is broken, or might miss that the actual Phase 2 scope is only the 3 config files + `_to_llm_provider()`.

**Reproduction:**
```bash
ls /home/q/projects/crabcakes/tests/test_prompt_loader_budget.py
# → No such file or directory
```

**Root cause:** The spec references a test file (`test_prompt_loader_budget.py`) that belongs to a different phase (the prompt loader budget feature from Phase CB-2/CB-5). The Phase 2 spec incorrectly includes it in the COMPLETENESS checklist context. The Phase 2 scope is correctly described in the opening "Files to change" section (4 files, ~6 one-line edits) but the checklist misleads by mentioning a non-existent test file.

**Fix:** Remove `test_prompt_loader_budget.py` from the Phase 2 COMPLETENESS checklist, or clarify that it belongs to a different phase.

---

## VERIFIED: What Is Correct

| Component | Status |
|---|---|
| `LLMProviderConfig.compaction_threshold` field (agent/config.py:39) | ✅ Correct |
| `_to_llm_provider()` backward-compat `getattr` (agent/config.py:143) | ✅ Correct |
| `ProviderConfig.compaction_threshold` field (models/providers.py:52) | ✅ Correct |
| `_to_dict()` serialization (utils/providers_store.py:48) | ✅ Correct |
| `_from_dict()` backward-compat default 0.80 (utils/providers_store.py:67) | ✅ Correct |
| `_compute_compaction_threshold()` return `(soft, hard)` tuple (runtime.py:1526) | ✅ Correct |
| `_compute_compaction_threshold()` threshold validation `0 < x <= 1` | ✅ Correct |
| `_compute_compaction_threshold()` fallback to 0.80 on invalid values | ✅ Correct |
| `_load_providers_from_yaml()` → `_to_llm_provider()` chain | ✅ Correct |
| Spec verification script: custom value 0.90 survives round-trip | ✅ PASSED |
| Spec verification script: default 0.80 survives round-trip | ✅ PASSED |
| Spec verification script: backward-compat old dict → 0.80 default | ✅ PASSED |
| Test suite (`test_providers_store.py`, `test_runtime_compaction.py`, `test_context_strategy.py`) | ✅ 73 passed, 1 skipped |

---

## COMPLETENESS Checklist (Phase 2)

```
COMPLETENESS:
- [x] Added compaction_threshold to LLMProviderConfig — evidence (agent/config.py:39)
- [x] Added compaction_threshold to _to_llm_provider() — evidence (agent/config.py:143)
- [x] Added compaction_threshold to ProviderConfig — evidence (models/providers.py:52)
- [x] Added compaction_threshold to _to_dict() — evidence (utils/providers_store.py:48)
- [x] Added compaction_threshold to _from_dict() — evidence (utils/providers_store.py:67)
- [x] Round-trip test passes (custom value 0.90 survives full chain) — verified
- [x] Default value test passes (0.80 when not set) — verified
- [x] Backward-compat test passes (old dict without field gets 0.80) — verified
- [~] Full test suite has no regressions — 73 passed, 1 skipped (partial suite run: test_providers_store, test_runtime_compaction, test_context_strategy)
```

**Note on test suite:** The full suite was not run to completion (timeouts on the complete `tests/` directory). The targeted Phase 2-adjacent tests (73 tests across `test_providers_store.py`, `test_runtime_compaction.py`, `test_context_strategy.py`) all pass with no regressions.

---

## Audit Metadata

- **Audit performed against spec:** `docs/specs/CM-PHASE-2-INSTRUCTIONS.md`
- **Adversarial protocol:** `prompts/adversarialDebugger.md`
- **Files examined:**
  - `agent/config.py` (full read, 200 lines)
  - `agent/context_strategy.py` (full read, ~500 lines)
  - `agent/context.py` (full read, ~400 lines)
  - `agent/runtime.py` (partial read, lines 1–100, 1526–1760)
  - `models/providers.py` (full read)
  - `models/conversation.py` (via grep)
  - `utils/providers_store.py` (full read)
  - `utils/prompt_loader.py` (full read)
  - `tests/test_providers_store.py` (full read)
  - `tests/test_runtime_compaction.py` (full read)
  - `tests/test_context_strategy.py` (via test run)
  - `tests/test_phase4.py` (partial read, lines 1–180)
  - `tests/conftest.py` (via grep)
- **Verification commands run:**
  - Spec verification script (3/3 assertions passed)
  - `python3 -m pytest tests/test_providers_store.py tests/test_runtime_compaction.py tests/test_context_strategy.py -v` (73 passed, 1 skipped)
- **Bugs found:** 3 (1 MEDIUM, 2 LOW)
- **Critical bugs found:** 0
