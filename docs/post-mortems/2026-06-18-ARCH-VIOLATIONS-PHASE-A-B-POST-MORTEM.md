# ARCH Violations Phase A+B Post-Mortem

**Date:** 2026-06-18
**Supervisor:** Qaster
**Builder:** QTR
**Commits:** 0 (changes staged but not committed per scope; ready for commit)
**Phases:** 2 (Phase A: 5 edits in 5 files; Phase B: 2 edits in 2 files)
**Total bugs found:** 3 real ARCH violations (Phase A) + 1 HIGH regression (Phase B, introduced by Phase A) + 1 LOW pre-existing (flagged, not fixed)
**Process:** Adversarial audit of ARCHITECTURE.md compliance found 3 view→handler boundary violations; supervisor wrote Phase A instructions; QTR fixed all 3 but introduced a from-import gotcha regression in STREAMING_ENABLED; adversarialDebugger caught it; supervisor wrote Phase B instructions; QTR fixed the regression.

---

## 1. Code Quality Grade: A (90/100)

### Justification

Phase A correctly identified and fixed 3 architectural boundary violations: views importing handlers. The fixes were minimal — remove the offending imports, add `from __future__ import annotations` where needed, and extract shared mutable state to a neutral module. Phase B correctly fixed the HIGH-severity regression introduced by Phase A's `from X import Y` pattern, replacing it with `import X` module-reference form so runtime mutations propagate correctly.

The deduction (10 points) is for: (a) Phase A introduced a regression that made a user-facing feature non-functional (streaming toggle) — 4 points; (b) the related-bug scan in Phase A noted the mutable-state smell but missed that the fix made it worse (regression, not just smell) — 2 points; (c) Phase A's `related-bug scan: none` claim was factually wrong on two counts (return value is `""` not `None`; fallback path lacks guard) — 2 points; (d) the `STREAMING_ENABLED` mutable-state smell remains — 1 point; (e) the `read_file` empty-args pattern in multi-iteration tests remains fragile — 1 point.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 17/20 | All 3 ARCH violations fixed; regression introduced and fixed; one pre-existing issue flagged |
| Architecture compliance | 10/10 | All view→handler imports removed; shared state in neutral module; ARCH §8.6 R2/R7 now satisfied |
| Test coverage         | 9/10 | Existing tests preserved; no new tests added (out of scope for both phases) |
| Documentation         | 9/10 | ARCH §13 test count updated; docstrings preserved; one factual error in Phase A report |
| Maintainability       | 9/10 | Module-reference import pattern is correct; mutable-state smell remains (Tier 2+) |
| DX (Developer Exp.)   | 9/10 | Minimal edits; no cross-cutting refactors; from-import gotcha now a process lesson |
| **Total**             | **90/100** | **A** |

---

## 2. What's Good About the Code

1. **Minimal, surgical fixes:** All 5 Phase A edits were 1-2 line changes. The `PromptsHandler` and `SettingsHandler` imports were removed without touching any other code. The `STREAMING_ENABLED` extraction to `ui/constants.py` was a clean 16-line new file. Phase B's fix was 6 lines across 2 files. No scope creep.

2. **Module-reference import pattern (Phase B):** The fix uses `import ui.constants` in both consumers, so all reads/writes go through `ui.constants.STREAMING_ENABLED` — the module attribute is the single source of truth. When the toolbar mutates it, the chat handler sees the new value on the next read. This is the correct Python pattern for shared mutable state.

3. **`from __future__ import annotations` added to `left_panel.py`:** This was a necessary addition — without it, removing the `PromptsHandler` import would break any forward references. The spec correctly called for checking first and adding if missing.

4. **`task_store` added to `models/__init__.__all__`:** Small data fix that makes the singleton importable via `from models import task_store`. Consistent with the existing pattern of exporting both the class and the instance.

---

## 3. What's Bad About the Code

1. **`STREAMING_ENABLED` mutable-state smell remains:** The constant is a module-level `bool` that both `toolbar.py` and `chat_handler.py` mutate at runtime. This is a pre-existing condition that Phase A preserved and Phase B did not make worse, but it remains a design smell. A future refactor could replace it with a `StreamingState` class injected into both consumers via `ui/window.py`. Out of scope for both phases.

2. **Phase A introduced a regression:** The `from ui.constants import STREAMING_ENABLED` pattern in Phase A created a stale local binding. This is a classic Python gotcha — `from X import Y` creates a new name in the importing module that points to the same object as `X.Y`, but when `X.Y` is reassigned (not mutated), the local binding doesn't update. The regression was caught by the adversarial audit, not by tests (the bug requires a real GTK event loop to exercise).

3. **Phase A's related-bug scan was incomplete:** The scan noted the mutable-state smell but failed to identify that the `from X import Y` pattern would make it worse (a regression, not just a smell). The scan also made factually incorrect claims about return values and fallback path guards.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | Pre-flight (2026-06-18) | HIGH | `left_panel.py` imports `PromptsHandler` from `ui.handlers` — violates ARCH §8.6 R2 | Qaster (adversarialDebugger) | QTR (Phase A, Edit 1) |
| 2 | Pre-flight (2026-06-18) | HIGH | `settings_dialog.py` imports `SettingsHandler` from `ui.handlers` — violates ARCH §8.6 R2 | Qaster (adversarialDebugger) | QTR (Phase A, Edit 2) |
| 3 | Pre-flight (2026-06-18) | HIGH | `toolbar.py` imports `STREAMING_ENABLED` from `chat_handler` — view imports from handler module | Qaster (adversarialDebugger) | QTR (Phase A, Edit 3) |
| 4 | Post-Phase-A (2026-06-18) | HIGH | `STREAMING_ENABLED` toggle non-functional: `from ui.constants import STREAMING_ENABLED` creates stale local binding in `chat_handler.py`; toolbar mutations don't propagate | Qaster (adversarialDebugger, from-import gotcha probe) | QTR (Phase B, Edit 1) |
| 5 | Post-Phase-A (2026-06-18) | LOW | Phase A completion report's "related-bug scan: none" claim was factually wrong (return value is `""` not `None`; fallback path at L1397 lacks `if kb_context:` guard) | Qaster (adversarialDebugger §10) | Not fixed (report is not code; flagged here) |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `view-imports-handler` | 3 | Views importing from `ui/handlers/` — violates ARCH §8.6 R2/R7 |
| `from-import-gotcha` | 1 | `from X import Y` creates stale binding when `X.Y` is reassigned; mutations to module attribute don't propagate to importing module |
| `report-claim-vs-code-reality` | 1 | Completion report's related-bug scan contained factual errors about return values and control flow |

---

## 5. Process: What Worked

1. **Adversarial audit caught the regression before commit:** The Phase A fix was audited before commit, and the from-import gotcha was caught by adversarialDebugger probing. This is exactly the process working as intended — the supervisor's audit caught a bug that the test suite couldn't (runtime UI issue requiring GTK event loop).

2. **File-based delegation with explicit code blocks:** Both phase-instructions files contained exact "current code" → "replacement code" blocks. QTR's diffs match the specs verbatim.

3. **Phase B was a clean, minimal fix:** 2 files, 6 lines changed, 4 verifications. The fix directly addressed the root cause (import style) without expanding scope.

4. **Independent verification:** All verification commands from both phases were re-run by the supervisor. The regression was confirmed with a Python REPL probe (`import ui.constants as c1; from ui.constants import STREAMING_ENABLED as ce; c1.STREAMING_ENABLED = True; ce is still False`).

---

## 6. Process: What Didn't Work

1. **Phase A's related-bug scan missed the regression it introduced:** The scan noted "STREAMING_ENABLED mutable-state smell" but didn't recognize that the `from X import Y` pattern would make it worse. The scan should have verified the import style's implications for mutable state, not just noted the smell.
   - Lesson: when a fix introduces a new import pattern for mutable state, the related-bug scan must verify that the import style correctly handles mutation propagation. `from X import Y` is wrong for mutable state that `X` reassigns; `import X` (module reference) is correct.

2. **Tests didn't catch the regression:** The streaming toggle bug is invisible to the test suite because it requires a real GTK event loop to exercise. The existing tests pass because they don't test the runtime mutation path.
   - Lesson: for shared mutable state, consider adding a minimal runtime probe test (e.g., `ui.constants.STREAMING_ENABLED = True; assert ui.constants.STREAMING_ENABLED is True`) even if the full UI path can't be tested headlessly. This is a process improvement for the test strategy, not a code fix.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Streaming toggle button now works correctly:** Before Phase A, the toggle worked but violated architecture (view imported from handler). After Phase A alone, the toggle was broken (button label changed but chat handler never saw the new value). After Phase B, the toggle works correctly — clicking the button updates `ui.constants.STREAMING_ENABLED`, and the chat handler reads the updated value on the next streaming event.
   - Code path: `toolbar.py` → `ui.constants.STREAMING_ENABLED = button.get_active()` → `chat_handler.py` → `if not ui.constants.STREAMING_ENABLED: return`

2. **Views no longer import handlers:** The architectural boundary is enforced. `left_panel.py` and `settings_dialog.py` no longer have `from ui.handlers` imports. Type annotations use string form or `from __future__ import annotations`. The composition root (`ui/window.py`) wires handlers into views via setters.

3. **`task_store` is now importable from `models`:** `from models import task_store` works consistently with the existing pattern of exporting both classes and singleton instances.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **`STREAMING_ENABLED` mutable-state smell:** Module-level `bool` mutated at runtime by two consumers. Pre-existing before Phase A, preserved through both phases. Tier 2+ evolution suggestion: replace with `StreamingState` class injected via `ui/window.py`.

2. **Fallback path at `agent/runtime.py:1397` calls `_inject_kb_context` without `if kb_context:` guard:** Pre-existing, flagged in the KB cache fix post-mortem (same day). Out of scope for both Phase A and B.

3. **`read_file` empty-args pattern in multi-iteration tests:** Relies on `execute_tool` swallowing `TypeError`. Pre-existing, flagged in the KB cache fix post-mortem. Out of scope.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Replace `STREAMING_ENABLED` module-level bool with `StreamingState` class injected via `ui/window.py` | 1 hour | Eliminates mutable global state; enables testability |
| Add `if kb_context:` guard before `_inject_kb_context` at `agent/runtime.py:1397` | 15 minutes | Fixes pre-existing cosmetic issue in fallback path |
| Stub `execute_tool` directly in multi-iteration tests instead of relying on `read_file` failing gracefully | 30 minutes | Decouples tests from `execute_tool`'s exception-handling behavior |
| Add a runtime probe test for `STREAMING_ENABLED` mutation propagation | 15 minutes | Catches from-import gotcha regressions in CI |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **`from X import Y` is wrong for mutable state that `X` reassigns.** Use `import X` (module reference) when the imported name may be reassigned in the source module. `from X import Y` creates a new binding in the importing module that goes stale when `X.Y` is reassigned. This is Python 101, but it's easy to miss when the import is for a "constant" that happens to be mutable.
   - Trigger: importing a name from a module where the name may be reassigned at runtime
   - Action: use `import X` and reference as `X.Y`, never `from X import Y` for mutable shared state

2. **Related-bug scans must verify import patterns for mutable state.** When a fix introduces a new import pattern, the scan must check whether the import style correctly handles mutation propagation. Noting a "mutable-state smell" is not enough — the scan must verify the fix doesn't make the smell worse.
   - Trigger: a fix introduces a new `from X import Y` or `import X` for a name that is mutated at runtime
   - Action: verify the import style with a REPL probe (`X.Y = new_value; assert importing_module.Y == new_value`)

3. **The adversarialDebugger audit is catching regressions that tests can't.** Both the KB cache fix (earlier today) and Phase A+B (today) had bugs caught by adversarial audit that the test suite didn't catch. The test suite is necessary but not sufficient for mutable state and runtime UI issues.
   - Trigger: any fix involving shared mutable state, import patterns, or UI event handling
   - Action: adversarialDebugger audit is mandatory, not optional, for these categories

---

## 11. Sign-off

- [x] Code committed and pushed to `main` (NOT YET — staged, awaiting commit per the implementationSupervisor's authority rule)
- [x] All verification commands run and pasted (Phase A: V1-V6; Phase B: V1-V4)
- [x] Captain notified with summary (this post-mortem IS the summary)
- [x] Tier 2+ backlog updated (4 items in §9 Evolution Suggestions)

**Status:** Work accepted. All 3 ARCH violations fixed. The from-import regression introduced by Phase A was caught and fixed in Phase B. The streaming toggle now works correctly. The `related-bug scan` process lesson (verify import patterns for mutable state) is codified in §10 lesson 2.
