# Phase 8 Audit Report: §2.8 Telemetry Enrichment — CompactionEvent History + Signature Refactor

**Date:** 2026-06-27  
**Auditor:** Adversarial Debugger (subagent)  
**Scope:** `agent/runtime.py`, `tests/test_runtime_compaction.py`, `agent/context_strategy.py` (read-only), `agent/config.py`, `models/conversation.py`, `models/providers.py`, `utils/providers_store.py`, `utils/prompt_loader.py`  
**Methodology:** Spec-vs-code comparison, edge-case analysis, thread-safety audit, invariant verification  

---

## Executive Summary

The Phase 8 implementation passes all 8 new tests and 128 existing tests. However, the adversarial audit reveals **5 bugs** — 1 CRITICAL, 2 HIGH, 2 MEDIUM — and 3 additional LOW-severity issues. The most severe bug is a thread-safety flaw that causes cross-session data contamination in multi-session runtimes.

---

## BUG #1

**Severity:** CRITICAL  
**Assumption violated:** `_compaction_events` and `_compaction_this_iteration` are per-session state, but they are instance-level fields on `AgentRuntime`, which is shared across all sessions.  
**Attack vector:** Two sessions (A and B) run their tool loops concurrently on the same `AgentRuntime` instance. Both threads call `compact()`, append to `_compaction_events`, and read `_compaction_this_iteration` without any lock.  
**Reproduction:**
1. Create one `AgentRuntime` with two sessions (`session_a`, `session_b`).
2. Session A's tool loop compacts (trims 10 messages) → sets `_compaction_this_iteration = True`, appends event to `_compaction_events`.
3. Before session A's breakdown callback fires, session B's tool loop compacts (trims 3 messages) → overwrites `_compaction_this_iteration = True`, appends B's event.
4. Session A's breakdown callback reads `_last_trim_removed` → finds B's event (latest in list) → reports `messages_removed_this_turn = 3` instead of 10.
5. Session B's breakdown callback reads `_last_trim_removed` → also reads same event → reports 3 (correct for B but the event ordering is nondeterministic).

Additionally, `_compaction_this_iteration` is a single bool shared across all sessions:
- Session A compacts (sets True), session B does NOT compact (sets False). 
- Session A's breakdown reads `_compaction_this_iteration` → sees False (B just set it).
- `trimmed_this_turn` is False even though A trimmed messages.

**Root cause:** The old scalar `_last_trim_removed` had the same thread-safety issue, but Phase 8 made it worse by introducing `_compaction_this_iteration` (a second shared mutable flag) and `_compaction_events` (a shared list that mixes events from all sessions). The spec did not address thread safety, and the implementation did not add per-session isolation or locking.

**Fix:** Either:
- (a) Move `_compaction_events` and `_compaction_this_iteration` to per-session state (e.g., store on the `Conversation` object or a per-session dict keyed by `session_key`).
- (b) Guard all reads/writes of `_compaction_events` and `_compaction_this_iteration` with `self._lock` (which already exists at line 1262).
- (c) At minimum, make `_compaction_this_iteration` a per-session dict: `self._compaction_this_iteration: dict[str, bool] = {}`.

---

## BUG #2

**Severity:** HIGH  
**Assumption violated:** `_compaction_this_iteration` is set to `True` only when actual compaction (message removal) occurs.  
**Attack vector:** `DefaultContextStrategy.compact()` ALWAYS sets `self._last_result` to a `CompactionEvent` — even on a no-op where 0 messages were removed and 0 tokens were freed. The runtime checks `if self._context_strategy.last_result is not None:` (line 1697), which is ALWAYS True after the first `compact()` call. So `_compaction_this_iteration` is always set to `True`, and a no-op CompactionEvent is appended to `_compaction_events` on every single tool-loop iteration.  
**Reproduction:**
1. Create a conversation with a short message (well under the token budget).
2. Run one tool-loop iteration.
3. `compact()` is called → no messages removed → `last_result` is a CompactionEvent with `messages_removed=0`, `layer=2`.
4. Runtime code: `last_result is not None` → True → sets `_compaction_this_iteration = True`.
5. Breakdown callback: `trimmed_this_turn = True` even though nothing was trimmed.
6. `messages_removed_this_turn = 0` (because `_last_trim_removed` reads the no-op event's `messages_removed=0`).

The UI/observer sees `trimmed_this_turn=True` with `messages_removed_this_turn=0` — contradictory telemetry.

**Root cause:** The strategy sets `_last_result` unconditionally (line 246 of context_strategy.py), and the runtime uses `last_result is not None` as the signal for "compaction happened." But `last_result` being non-None means "compact() was called," not "messages were removed."

**Fix:** The runtime should check `self._context_strategy.last_result.messages_removed > 0` instead of `self._context_strategy.last_result is not None`:
```python
if self._context_strategy.last_result is not None:
    ev = self._context_strategy.last_result
    if ev.messages_removed > 0 or ev.tokens_freed > 0:
        self._compaction_events.append(ev)
        self._compaction_this_iteration = True
    else:
        self._compaction_this_iteration = False
```

---

## BUG #3

**Severity:** HIGH  
**Assumption violated:** The `compaction_event` dict in the breakdown includes a correct `hard_ceiling` value.  
**Attack vector:** The breakdown callback at line 1758 reads `strategy_result.hard_ceiling` and includes it in the telemetry dict. But `DefaultContextStrategy.compact()` ALWAYS sets `hard_ceiling=0` in its CompactionEvent (line 249 of context_strategy.py: `hard_ceiling=0, # not known at strategy level in Phase 1`). The runtime HAS the correct hard_ceiling in the local variable `hard_ceiling`/`model_max` but never injects it into the telemetry.  
**Reproduction:**
1. Run any tool-loop iteration where the breakdown callback fires.
2. Observe `breakdown["compaction_event"]["hard_ceiling"]` is always `0`.
3. Meanwhile `breakdown["model_max_tokens"]` (from `get_token_breakdown(model_max)`) has the correct value.

**Root cause:** The strategy doesn't know the hard ceiling (it only receives `soft_ceiling` as `token_budget`). The runtime knows `hard_ceiling` but passes only `soft_ceiling` to `compact()`. The breakdown reads from the strategy's event, which has no way to know the hard ceiling. The spec's Step 5 breakdown code does not override `strategy_result.hard_ceiling` with the runtime's known value.

**Fix:** In the breakdown callback, override `hard_ceiling` with the runtime's local variable:
```python
breakdown["compaction_event"] = {
    ...
    "hard_ceiling": hard_ceiling,  # from _compute_compaction_threshold, not strategy_result
    ...
}
```

---

## BUG #4

**Severity:** MEDIUM  
**Assumption violated:** The `_last_trim_removed` property returns the count from the CURRENT iteration's trim, not a stale value from a previous iteration.  
**Attack vector:** The property scans `reversed(self._compaction_events)` for the latest `layer==2` event. Due to BUG #2, every iteration appends a `layer==2` event (even no-ops). After a real trim in iteration N (removed=5), iteration N+1 appends a no-op event (removed=0). The property returns 0 from N+1's event, which is correct for N+1. But if iteration N+1 does NOT call `compact()` (e.g., the loop breaks early or an exception occurs between compact() and breakdown), the property still returns 5 from iteration N's event — stale data.  
**Reproduction:**
1. Iteration 1: compact trims 5 messages → event appended with removed=5.
2. Iteration 2: `_call_llm()` raises an exception before the breakdown callback fires.
3. No new event is appended for iteration 2.
4. Iteration 3: compact does nothing (no-op) → event appended with removed=0.
5. Breakdown reads `_last_trim_removed` → returns 0 (from iteration 3's no-op). This is correct.
6. BUT: if iteration 3's breakdown is NOT called (`_on_token_breakdown is None`), then `_compaction_this_iteration` stays True from iteration 3.
7. On iteration 4: compact does nothing → `_compaction_this_iteration = True` again.
8. If iteration 4's breakdown IS called: `trimmed_this_turn = True`, `_last_trim_removed = 0`. This is semantically wrong — trimmed_this_turn should be False.

**Root cause:** The property was designed assuming events are only appended when real trims occur. Combined with BUG #2 (no-op events appended every iteration), the property's semantics drift.

**Fix:** Fix BUG #2 first (don't append no-op events or don't set `_compaction_this_iteration` for no-ops). Then the property correctly returns the latest REAL trim count.

---

## BUG #5

**Severity:** MEDIUM  
**Assumption violated:** The `compaction_event` breakdown dict is only included when actual compaction occurred.  
**Attack vector:** Due to BUG #2, `strategy_result` is never None after `compact()`, so the `if strategy_result is not None:` check at line 1754 is always True. The breakdown dict always includes `compaction_event` telemetry, even on no-op iterations. This creates noisy telemetry — observers see compaction data on every turn even when nothing happened.  
**Reproduction:**
1. Run a conversation where the token count never exceeds the soft ceiling.
2. Every tool-loop iteration: breakdown includes `compaction_event` dict with `tokens_freed=0`, `messages_removed=0`, `trigger="trim"`.
3. UI/log consumers can't distinguish "compaction happened and freed nothing" from "compaction didn't happen."

**Root cause:** Same as BUG #2 — the runtime doesn't distinguish between "compact() was called" and "compaction actually occurred."

**Fix:** Only include `compaction_event` in the breakdown when `strategy_result.messages_removed > 0 or strategy_result.tokens_freed > 0`. Alternatively, include a `compaction_occurred: bool` flag.

---

## BUG #6

**Severity:** LOW  
**Assumption violated:** The `on_token_breakdown` docstring accurately describes the breakdown fields.  
**Attack vector:** The docstring at line 1206 says `trimmed_this_turn (bool): True if messages were removed this iteration`. Due to BUG #2, this field is True even when no messages were removed.  
**Reproduction:** Read the docstring. Run the code. Observe `trimmed_this_turn=True` with `messages_removed_this_turn=0`.  
**Root cause:** Docstring was not updated to reflect the Phase 8 behavior change.  
**Fix:** Either fix BUG #2 so the docstring becomes accurate, or update the docstring to say "True if compact() was called this iteration (may be True even when 0 messages were removed on no-op iterations)."

---

## BUG #7

**Severity:** LOW  
**Assumption violated:** The test `test_event_has_correct_layer` asserts `layer in (0, 1, 2)`, implying layer 0 is a possible value. The test docstring says "0=no-op."  
**Attack vector:** The strategy's code at line 246 (`if layer == 0: layer = 2`) guarantees `layer` is NEVER 0. The assertion `layer in (0, 1, 2)` passes trivially because 0 is never produced — the test gives false confidence that layer 0 is tested.  
**Reproduction:** Read `agent/context_strategy.py` line 246. The `if layer == 0: layer = 2` reassignment means the test never exercises layer 0.  
**Root cause:** The test was copied from the spec verbatim without verifying that the strategy code can actually produce layer 0.  
**Fix:** Either:
- (a) Remove 0 from the assertion: `assert strategy.last_result.layer in (1, 2)`.
- (b) Change the strategy to NOT force layer to 2 on no-op, and instead return layer=0 for true no-ops.

---

## BUG #8

**Severity:** LOW  
**Assumption violated:** The `_compaction_events` list cap operation (`self._compaction_events = self._compaction_events[-100:]`) is thread-safe.  
**Attack vector:** The slice creates a NEW list object and rebinds `self._compaction_events`. If another thread is concurrently appending to the OLD list (via `self._compaction_events.append(...)`), that append is lost — the thread holds a stale reference.  
**Reproduction:**
1. Thread A: `_compaction_events` has 100 items. Calls `self._compaction_events[-100:]` → creates new list, rebinds attribute.
2. Thread B: Concurrently calls `self._compaction_events.append(event)` on the OLD list object (now orphaned). The event is lost.
3. Thread B then checks `len(self._compaction_events)` — sees the new list (100 items), not the old list it just appended to (101 items).

**Root cause:** List rebinding is not atomic with respect to concurrent appends. The code should use `del self._compaction_events[:-100]` which mutates in place, or use a lock.  
**Fix:** Use in-place deletion: `del self._compaction_events[:-100]` instead of rebinding.

---

## Missing Tests / Coverage Gaps

### GAP #1: No test for `_compaction_this_iteration` reset behavior
The spec describes a per-iteration reset cycle (set True on compaction, reset to False after breakdown). No test verifies this cycle. Specifically:
- No test that `_compaction_this_iteration` is False after the breakdown fires.
- No test that a no-op iteration sets it to False (because the current code always sets it True — BUG #2).

### GAP #2: No test for the breakdown callback integration
The tests exercise `_compute_compaction_threshold` and `_last_trim_removed` in isolation, but no test verifies that the breakdown dict is correctly populated in the tool loop. This is where BUG #2, #3, and #5 manifest.

### GAP #3: No test for multi-iteration event history
No test verifies that `_compaction_events` correctly accumulates events across multiple tool-loop iterations (only the cap-at-100 test exists, which manually simulates the accumulation).

### GAP #4: No test for `hard_ceiling` correctness in telemetry
No test verifies that the breakdown's `compaction_event.hard_ceiling` matches the runtime's resolved hard ceiling. BUG #3 would be caught by such a test.

### GAP #5: No test for `_last_trim_removed` with mixed layer events
The property test only has a single layer==2 event. No test verifies behavior when multiple layer==2 events exist alongside layer==1 events — the "latest layer==2" selection logic is untested.

---

## Scope Coverage Verification

| Spec Requirement | Status |
|---|---|
| `_compute_compaction_threshold` returns `tuple[int, int]` | ✅ Implemented |
| Call site updated to unpack tuple | ✅ Implemented |
| Scalar `_last_trim_removed` replaced with `_compaction_events` list | ✅ Implemented |
| `_last_trim_removed` `@property` reads latest layer==2 event | ✅ Implemented |
| `_compaction_this_iteration` flag for per-iteration reset | ✅ Implemented (but buggy — BUG #2) |
| Breakdown callback updated to use flag + property | ✅ Implemented (but telemetry is wrong — BUG #2, #3, #5) |
| History capped at 100 events at call site | ✅ Implemented (but not thread-safe — BUG #8) |
| `tests/test_runtime_compaction.py` with 3 + 5 tests | ✅ Created |
| `agent/context_strategy.py` NOT changed | ✅ Verified (git diff clean) |
| `models/conversation.py` NOT changed | ✅ Verified (git diff clean) |
| `utils/prompt_loader.py` NOT changed | ✅ Verified (git diff clean) |

---

## Verification Output

```
tests/test_runtime_compaction.py: 8/8 passed (17.87s)
tests/test_context_strategy.py + test_conversation.py + test_phase4.py: 128/128 passed (1.98s)
Full suite (excluding test_improve.py pre-existing failure): 1117 passed
```

---

## Summary Table

| # | Severity | Category | One-liner |
|---|---|---|---|
| 1 | CRITICAL | Thread Safety | `_compaction_events` and `_compaction_this_iteration` are shared across sessions without locks — cross-session data contamination |
| 2 | HIGH | Logic | `_compaction_this_iteration` is always True because `last_result` is never None after `compact()` — no-op iterations report `trimmed_this_turn=True` |
| 3 | HIGH | Telemetry | `compaction_event.hard_ceiling` is always 0 in breakdown — strategy sets it to 0, runtime never overrides |
| 4 | MEDIUM | State | `_last_trim_removed` property returns stale data when iterations are skipped or breakdown not called |
| 5 | MEDIUM | Telemetry | `compaction_event` dict included in breakdown on every iteration even when no compaction occurred |
| 6 | LOW | Docs | `on_token_breakdown` docstring claims `trimmed_this_turn` means "messages removed" but it doesn't |
| 7 | LOW | Test | `test_event_has_correct_layer` asserts `layer in (0,1,2)` but layer 0 is impossible — false confidence |
| 8 | LOW | Thread Safety | History cap rebinds list (`= [-100:]`) losing concurrent appends from other threads |
