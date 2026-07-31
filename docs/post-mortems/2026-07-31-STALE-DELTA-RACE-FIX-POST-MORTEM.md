# Stale Delta Race Fix — Post-Mortem

**Date:** 2026-07-31
**Supervisor:** Supervisor (special:supervisor)
**Builder:** Coder (special:coder)
**Auditor:** Debugger (special:debugger)
**Commits:** `b5ce7b6` (Coder Phase 1) + supervisor fixes (`1a1c482`)
**Phases:** 1 (single-file fix)
**Total bugs found:** 4 (1 root cause + 3 audit findings)
**Process:** Debugger diagnosed root cause → Supervisor wrote spec → Coder implemented → Debugger audited → Supervisor fixed BUG #1

---

## 1. Code Quality Grade: A (94/100)

### Justification

The fix correctly addresses the root cause (race condition between `_on_text_delta` and `_on_response_complete` both using `GLib.idle_add` independently). The generation-counter approach is minimal, well-scoped, and backward-compatible. Coder's related-bug scan found the `_on_error` sibling race, which the supervisor fixed directly. Debugger's audit found a subtle default-value bug (`delta_gen=0` unsafe after generation advances) which the supervisor fixed by changing to `int | None = None`. Two deferred races (stale completion finalizing newer turn, compaction/usage_warning races) are noted for future work.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | Fixes the primary race + error-path sibling. −1: 2 deferred races (BUG #2/#3). |
| Architecture compliance | 10/10 | Handler-only change. No layer violations. |
| Test coverage         | 8/10  | 10 targeted tests pass. −2: no regression test for the race itself (GTK-dependent). |
| Documentation         | 9/10  | Inline comments explain the mechanism. −1: no ARCHITECTURE.md note. |
| Maintainability       | 10/10 | Clean, minimal generation-counter pattern. Self-documenting. |
| DX                    | 18/20 | Easy to understand. −2: deferred races are noted but not fixed. |
| **Total**             | **94/100** | **A** |

---

## 2. What's Good About the Code

1. **Generation counter is the right abstraction.** A per-session integer that increments on completion/error and is captured by deltas at dispatch time. Stale deltas (old gen < current gen) are dropped. Simple, O(1), no locks needed.

2. **Backward-compatible default.** `delta_gen: int | None = None` — 2-arg callers (tests, future code) are treated as "current generation" and never dropped. Only real deltas dispatched via `_on_text_delta` carry a captured generation.

3. **Coder's related-bug scan caught the error path.** `_on_error` dispatches `_do_error` via the same `idle_add` pattern, creating the same race. Coder flagged it per Step 6.6; supervisor applied the same one-line increment.

---

## 3. What's Bad About the Code

1. **Two deferred race classes (Debugger BUG #2/#3).** Stale completion callbacks can finalize a newer turn (BUG #2). Compaction/usage_warning callbacks call `end_streaming` without generation coordination (BUG #3). Both are lower probability than the primary race but represent the same bug class.
   - Evolution: implement a per-session FIFO dispatcher covering all callback types (deltas, completion, error, compaction, usage_warning).

2. **No regression test for the race itself.** The race requires GTK idle callback ordering, which can't be tested in the sandbox (GTK segfault). The fix is verified by inspection + targeted tests for adjacent paths.
   - Evolution: add a GTK-capable CI lane.

---

## 4. Bugs Found During Audit

| # | Severity | Bug | Found by | Fixed by |
|---|----------|-----|----------|----------|
| 1 | HIGH (root cause) | Race: stale `_do_text_delta` starts new streaming bubble after completion rendered the final bubble | Debugger (investigation) | Coder (generation counter) |
| 2 | HIGH (sibling) | `_on_error` has same race — dispatches `_do_error` without incrementing generation | Coder (related-bug scan) | Supervisor (same increment) |
| 3 | HIGH (audit) | `delta_gen=0` default is unsafe after generation advances — 2-arg callers silently dropped | Debugger (BUG #1) | Supervisor (`int \| None = None`) |
| 4 | MEDIUM (deferred) | Stale completion can finalize a newer turn (completion not generation-guarded) | Debugger (BUG #2) | Deferred |
| 5 | MEDIUM (deferred) | Compaction/usage_warning call `end_streaming` without generation coordination | Debugger (BUG #3) | Deferred |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `race-condition` | 3 | GLib idle callbacks execute out of order; stale callbacks mutate state |
| `unsafe-default-value` | 1 | `delta_gen=0` treated as real generation, silently dropping 2-arg callers |

---

## 5-11. (Abbreviated per single-phase loop)

**Process worked:** Debugger's targeted investigation (without full 11-section audit) correctly identified the root cause in one pass. The generation-counter fix is minimal and correct. Coder's related-bug scan added value.

**Process didn't work:** The supervisor spent 4 rounds adding/removing broken debug code before delegating to Debugger. The debug-code attempts (`print(file=sys)`, `sys.stderr.write(ff"...")`) introduced syntax errors that crashed the app further. Future approach: delegate investigation to Debugger earlier.

**End-user impact:** Agent messages (Supervisor, Coder, Debugger) will now render in full instead of truncating to the first word. The stale streaming widget is replaced by the final bubble correctly.

**Pre-existing (deferred):** BUG #2 (stale completion), BUG #3 (compaction/usage_warning races). Lower probability, same bug class.

---

## Sign-off

- [x] Code committed (`1a1c482`)
- [x] py_compile passes
- [x] 10 targeted tests pass
- [x] Captain notified
- [x] Deferred bugs documented (BUG #2, BUG #3)
