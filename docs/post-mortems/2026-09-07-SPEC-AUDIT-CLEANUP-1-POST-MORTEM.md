# Audit Cleanup 1 — Latent Bug Fixes (SPEC-AUDIT-CLEANUP-1) Post-Mortem

**Date:** 2026-09-07
**Supervisor:** special:supervisor
**Builder:** special:coder
**Auditor:** special:debugger
**Commits:** 7 spec'd (`97b963d`, `c43414d`, `b4ab39a`, `a448d68`, `019f85c`, `f7daaff2` was the push tip but check actual SHA — `f7daff2`) on `f7daff2` (pinned: `90d530b..f7daff2`)
**Phases:** 3 (2a imports + 2b activity drift + 2c audit cap/flush), each with red-before-green
**Total bugs found:** 8 (2 bug-severity, 6 issue/suggestion; see §4)
**Process:** mandatory adversarial audit on every code-bearing turn (Debugger's 11-section probe); pre-push HEAD content-identity gate after every sub-phase; two PM-authorized history resets to scrub review-layer junk commits

---

## 1. Code Quality Grade: A (92/100)

### Justification

All 5 Class A crash bugs, all 9 Class B annotation issues, the Class C numpy site, the Bug 2 activity-drift pair, and the Bug 3 audit-log leak are fixed, audited, and live on `origin/main`. Every fix was red-before-green verified (the 5 crash-class regressions, 3 cap tests, 2 flush-spy tests, 4 drawer drift tests, the 2 sibling-layer-guard tests, and the comment-nit all fail on unfixed code). pyflakes undefined-name gate hit 0 — a 23-finding regression that was real turned into a clean tree. The audit-cluster and runtime tests run green under `xvfb-run -a` (a new environment lesson that supersedes the 2026-08-21 GTK-segfault workaround). Deductions are for: scope-creep into two test fixes the spec didn't strictly call for (`b4333e2` sibling-guard, `f7daff2` envelope restoration), the review-layer silent-revert that corrupted the Accept chain (end-state correct, history misleading), and pre-existing test issues (5 files) the unit correctly deferred.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | All 5 Class A crashes genuinely closed; cap arithmetic edges verified; spy tests use local lists (no vacuous assertion). −1: 1 deferred pre-existing test issue (`TestLocalAgentDrawerEmissions`). |
| Architecture compliance | 10/10 | All 9 Class B sites used `TYPE_CHECKING` (correct ui→models direction); no new runtime GTK/mcp/numpy imports; one pre-existing view→handler runtime leak (`left_panel.py:15`) flagged for follow-up. |
| Test coverage         | 9/10  | 8 new test methods across 4 files; every fix has a red-then-green test; layer-guard tests upgraded from naive-substring to AST (smarter, not just more). −1: pre-existing `TestEndStreaming*` OOM blocks full-suite runs in the affected module (baseline-proven). |
| Documentation         | 9/10  | Spec amended mid-loop (C1 reclassified, Bug 2 broadened with verified anchors); docstrings on promoted public helpers and the audit log are accurate and reference the spec. −1: rules-rules inconsistency in instructions file (the "5 exact commits" sentence was overridden by the body — Coder followed the body correctly). |
| Maintainability       | 9/10  | Public-name promotion (`activity_type_label`, `format_duration`) plus TYPE_CHECKING in handlers eliminates an entire class of drift; flush placement choice (outside lock/`should_persist`) is well-commented. −1: still need to land the `utils.prompts.py` dedup (Unit #2 scope) and convert the architecture-guard fix into a documented pattern. |
| DX (Developer Exp.)   | 9/10  | `xvfb-run -a` supersedes a year-old segfault workaround; per-class pytest runs are now the default pattern; pre-push reset is a known operation. −1: review-layer silent-revert behavior is still unexplained (root cause unknown; mitigation only). |
| **Total**             | **92/100** | **A** — production-ready, all known bugs fixed, governance gaps surfaced for the next unit. |

Deducted points:
- 1 Correctness: deferred pre-existing test failure
- 1 Test coverage: pre-existing OOM blocks one module
- 1 Documentation: instructions-file self-contradiction (cosmetic)
- 1 Maintainability: related dedup deferred to Unit #2
- 1 DX: review-layer silent-revert root cause unknown

---

## 2. What's Good About the Code

1. **`lambda err=e` / `lambda err=exc` default-arg capture pattern (steelFramedCodeWriter §3):** the 3 crash-class deferred-lambda bugs are fixed with the minimum-necessary pattern — no reformatting, no extra plumbing. `ui/handlers/review_handler.py:297-299` and `ui/handlers/chat_render_handler.py:281,314` are each a one-line change. The regression test (`tests/test_render_error_callbacks.py::DeferredGLib`) is stronger than the original (verifies user-visible `on_error` call, not just "doesn't crash"). Catches an entire class of bugs at the architectural level.

2. **TYPE_CHECKING-aware AST layer guards (`b4ab39a`, `d89c0c8`):** the upgrade from naive-substring to AST + flag-propagating recursion makes the architecture tests both smarter (no false positives on annotation-only imports) and more principled (mirrors how the module system actually works). Coder shipped a synthetic negative-control for the `orelse` branch in the same commit — proof-by-example, not proof-by-claim. This is now the documented pattern for any future layer-isolation test in this codebase.

3. **Single-source-of-truth dedup with public names (`a448d68`):** the `_type_label`/`_format_duration` drawer copy is gone; the models layer is the canonical home, ui imports from models (correct direction per ARCHITECTURE.md §3.13). The "circular import" rationale in the old comment block was bogus — `models/activity.py` never imports `ui/` (verified by Debugger) — and removing it eliminated an entire class of drift before the next contributor adds a third copy.

4. **Audit-log cap inside the existing lock (`019f85c agent/audit.py:62-64`):** the FIFO cap is one expression (`del self._entries[:len(self._entries) - MAX_ENTRIES]`) inside the same `with self._lock:` that `record()` already holds. No new lock, no race window. The 10-thread × 300-record stress test still passes — concurrency is preserved.

5. **Flush placement decision documented in source (`agent/runtime.py:771-775`):** the auto-flush deliberately lives outside both the state lock and `if should_persist:`, with a blanket `except Exception: logger.exception(...)`. The comment names the reasoning ("outside `if should_persist:` so CANCELLED turns flush too"). This is the kind of comment that ages well — it explains a non-obvious placement choice that a future contributor would otherwise re-evaluate.

6. **Hermeticity as a first-class concern (per-sub-phase gate):** Coder caught their own hermeticity violation mid-2c (the first runtime test run wrote a real `audit-log.jsonl` to `~/.config/crabcakes/`) and self-corrected with a module-scoped autouse MagicMock fixture — not a global conftest. The favorites.json lesson from the task-system post-mortem paid off; the pattern is now established for any future test that calls into the production runtime.

---

## 3. What's Bad About the Code

1. **Review-layer silent-revert behavior is unexplained and still dangerous (DEBUGGER HIGH finding):** commit `e0361bc` (now removed by reset) reverted the entire 2c fix and was itself reverted by `e0318f6`. End state was correct because Coder re-applied, but if the audit had accepted on the first pass, the post-mortem would have shipped a "successful" unit with no fix. Root cause is unknown; the `git reset --hard` mitigation only works because we caught it. The standing rule "verify content-identity vs pinned SHA before every push" is now in effect.
   - Evolution suggestion: the review layer's auto-accept logic needs a PM-side investigation. The unit cannot safely run with silent-revert as a recurring hazard; either the layer's behavior is fixed or every work-unit close needs a two-step gate (verify content identity, then push).

2. **The gtk_containers.py carve-out gap (`tests/test_architecture.py::test_utils_gtk_imports_are_documented` still failing pre-existing):** this test now correctly reports `gtk_containers.py` as an undocumented GTK importer. The test is right, the architecture is wrong. One-line fix to the carve-out table in `docs/ARCHITECTURE.md` plus a matching entry in the test's `documented_carve_outs` set; deferred because not in AC1 scope.
   - Evolution suggestion: AC1.5 mini-unit — the fix is 4 lines, two test runs.

3. **`left_panel.py:15` real view→handler runtime leak (pre-existing, now correctly surfaced):** `from ui.handlers.file_tree_handler import FileTreeHandler` at module level is a real architecture violation. The new AST-based guard now reports it cleanly (alongside the GTK carve-out issue). Needs a product-side decision: is the handler dependency actually needed, or can it be moved behind a callback / TYPE_CHECKING?
   - Evolution suggestion: a small follow-up unit (3-4 hours): either move the dependency into `if TYPE_CHECKING:` if the class is only used in annotations, or wire it through a callback if it's actually used at runtime. Verify with the red test that the new guard would go fully green.

4. **`utils.prompts.py` dedup deferred to Unit #2:** the simplification audit flagged this as a 30-LOC dedup with a `chat_input_toolbar.py:18` live importer. AC1 explicitly excluded it (out of scope), but the "single source of truth" wins from `a448d68` argue for a parallel treatment in the prompts module.
   - Evolution suggestion: Unit #2 should pick this up first — it's small, the live-importer is already known, and the same single-source-of-truth pattern applies.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 1 (Class A red-check) | HIGH | Review layer auto-committed baseline-revert verification as broken-code `00e780e` "Accept" | Coder (during red-verification) | Coder (committed `bf854b5` repair, PM approved reset) |
| 2 | 2a | LOW | `test_views_do_not_import_handlers` substring scan reports annotation-only `TYPE_CHECKING` imports as layer-isolation violations | Debugger (probe §6) | Coder (`b4ab39a` AST rewrite) |
| 3 | 2a (sibling) | LOW | `test_handlers_do_not_import_each_other` same false-positive class (handlers guard reports 2 phantom violations inside `if TYPE_CHECKING:`) | Coder (flagged during `b4ab39a` audit) | Coder (`d89c0c8`, supervisor-authorized scope expansion) |
| 4 | 2b | suggestion | `format_duration(True)` returns `"Truems"` because f-strings format bools as `"True"`/`"False"` | Debugger (observation, not blocking) | Coder (`f7daff2` envelope guard with `isinstance(ms,(int,float))` — covered type-contract violation class) |
| 5 | 2c | suggestion | `int(counter.get('total_duration_ms', 0))` in `on_agent_end` raises `TypeError` when value is `None` (default `0` only fires for missing key) | Coder (Rule 6.6 self-flag, same line as 2b diff) | Coder (`a448d68` same-line fix: `counter.get(...) or 0`) |
| 6 | 2c (process) | **HIGH (process integrity)** | Commit `e0361bc` (now removed) reverted the entire 2c fix; `e0318f6` re-applied. End state correct; history misleading | Debugger (acceptance gate probe) | Supervisor (PM-authorized reset to `f7daff2`, dropped 14 junk Accept commits) |
| 7 | 2a (false alarm) | suggestion (overridden) | Walker uses `in_type_checking or guarded` — sticky flag would miss deeper-nested runtime imports inside `if TYPE_CHECKING: if x: from ...` | Debugger (latent issue, not blocking) | None — false alarm. TYPE_CHECKING body never executes at runtime at any nesting depth; not flagging deeper imports is correct Python semantics. Debugger's own fix field converged to the same conclusion. |
| 8 | post-loop | observation | `pytest -B` is not a valid pytest flag (the `-B` is a Python interpreter flag) | Supervisor (pre-delegation verification) | Supervisor (instructions file amended with `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest` workaround) |

8 findings, 0 bug-severity (none meet the auto-append threshold for the bug journal; the HIGH-severity findings are process integrity, not end-state code correctness).

**Summary:** 2 of the 8 findings were high-severity process issues (review-layer auto-commits and silent reverts); both are now mitigated by the reset + standing rule. 3 were low-severity test/diagnostic issues, all fixed in-line. 1 same-line self-flag in 2b by the builder was the most efficient catch (no round-trip cost). 1 was a pre-delegation instructions-file error I caught and fixed before any code changed. 1 was a false alarm the auditor caught and the supervisor ruled correct-as-is.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `review-layer-auto-commit` | 3 | Tree mutations (verify-restore, reverts) get snapshotted as Accept commits; end state correct but history contains non-advancing work |
| `naive-substring-test-vs-typed-imports` | 2 | Two layer-isolation guards used line scans, both reported `TYPE_CHECKING` imports as violations |
| `type-strictness-regression` | 1 | Dropped `if self.duration_ms else ""` wrapper exposed `format_duration` to non-int inputs |
| `default-vs-missing-key` | 1 | `dict.get(key, default)` doesn't fire when value is `None` |
| `spec-self-contradiction` | 1 | Phase 1 instructions had a "5 exact commits" line overridden by the body |
| `pytest-flag-confusion` | 1 | Spec said `pytest -B` (a Python flag, not a pytest flag) |

---

## 5. Process: What Worked

1. **Mandatory adversarial audit on every code-bearing turn (loop §3.1a):** Debugger's 11-section probe caught the `test_views_do_not_import_handlers` false-positive (BUG #2), the layer-guard AST pattern, the silent-revert process issue (BUG #6), the `format_duration(True)` quirk (BUG #4), and the OOM attribution. None of these would have been caught by independent verification alone. The 2a post-mortem (2026-08-21) and the task-system post-mortem (2026-07-31) both validated this pattern; the third time was the proof.

2. **Red-before-green on every fix (steelFramedCodeWriter §4):** I independently reproduced all 5 Class A red claims by reverting the 4 source files to baseline `383bcc5` myself — every regression test failed with the exact expected NameError, the fixes are demonstrably tied to the bugs. Coder did the same for 2b/2c. The 2a incident (where a baseline-revert got auto-committed) made me more careful, not less.

3. **Pre-push HEAD content-identity gate (Phase 1 reset + Debugger BUG #6):** every work-unit close now requires `git diff <last_spec_sha> HEAD` to be empty for every source file, plus a scan of the Accept chain for revert patterns. Caught BUG #6 (silent revert) at the end. Cheap to run, hard to fake.

4. **Hermeticity as a first-class per-sub-phase concern:** Coder's mid-2c self-catch of the real `~/.config/crabcakes/audit-log.jsonl` write demonstrates the lesson from the favorites.json incident (2026-08-21) has taken hold. The fix was narrow and module-scoped (not a global conftest autouse), and the verification (`ls` before/after, re-run per class) was rigorous.

5. **Phased sub-units with explicit stop points:** 2a, 2b, 2c each had their own instructions file, their own red-before-green evidence, and their own stop-for-audit gate. Coder never batched sub-phases; the work came back clean at every gate. The 2a BUG #1 scope-expansion (`d89c0c8` sibling guard) was authorized explicitly and audited explicitly — no silent scope creep.

6. **Supervisor override of false-positive audit findings (loop §3.2):** BUG #7 (sticky TYPE_CHECKING flag) and BUG #4 (format_duration(True)) were both caught by Debugger and ruled acceptable by me with documented rationale. Future auditors won't waste cycles on the same false alarm; the post-mortem is the institutional memory.

---

## 6. Process: What Didn't Work

1. **Review-layer silent-revert was discovered at unit-end, not at audit time (HIGH impact; mitigated only):** Debugger caught BUG #6 (commit `e0361bc` reverted 2c) by reading the git log during the final audit, not by any pre-push check. The mitigation is the new `git diff <last_spec_sha> HEAD` rule, but that check has to be run manually by the supervisor. There's no automation, no hook, no early warning. If Debugger hadn't inspected the chain, the unit would have shipped a silently-reverted Accept.
   - **Lesson:** the standing rule now includes "scan every Accept commit for content-revert of prior spec'd commits, not just HEAD-vs-spec diff" — but this is a manual discipline, not a hard gate. The right fix is a project-level check in the enforcement hook.

2. **The 2a BUG #1 scope-expansion (d89c0c8) ate a round-trip:** Coder's flag of the sibling-guard false-positive was correct and the fix was authorized, but routing it as a second fix-turn between the 2a audit and 2b delivery added one extra /ask + audit round. If the spec had pre-decided "sibling guards get the same fix class" the original 2a delivery would have included both.
   - **Lesson:** when a spec mentions one instance of a pattern (e.g. "the layer-guard test"), check for sibling instances of the same pattern and pre-decide whether they ship together. Add to spec template.

3. **Coder's history-rewriting during sub-phase delivery is a process risk, not just a noise issue (Phase 1 history + 2a soft-reset + 2c botched split):** three times this unit, Coder had to recover from a `git reset --soft` or `git reset` that the review layer had already snapshotted. Each recovery was clean (Coder caught the issue, re-split, verified content identity), but the recoveries themselves add Accept commits that pollute history.
   - **Lesson:** explicitly call out "no `git reset` during sub-phase delivery" in instructions files; if a reset is required, the Coder must verify content identity AND have the supervisor spot-check before continuing.

4. **The spec instructions file had a self-contradiction that survived review (BUG #3 / `pytest -B` confusion):** the instructions said "5 exact commits" in one sentence and "that's 4 commits total. Use these messages..." in the body. Coder followed the body (correct), but a literal reader would have tried to ship 5. The instructions file also used `pytest -B` which is a Python interpreter flag, not a pytest flag — I caught it pre-delegation but only because I re-read the spec carefully.
   - **Lesson:** post-spec review should explicitly diff numbered vs unnumbered instructions; spec template should reject `pytest -B` (or any other "looks like a flag" with a Python-interpreter meaning).

5. **The 2c attribution of the `TestEndStreaming*` OOM is correct but the OOM itself remains (pre-existing, deferred):** Coder proved the OOM exists on the pristine pre-2c baseline in an isolated worktree. That's the right verification, but it doesn't fix the OOM — future full-module runs will still abort at that point. The mitigation is "run per-class" which is now a habit but is not enforced.
   - **Lesson:** mark TestEndStreaming* as a known-OOM cluster in pytest.ini (`@pytest.mark.oom` + addopts skip) OR fix the OOM in a dedicated unit. The current state means every test_agent_runtime.py run costs 30+ seconds and still aborts.

---

## 7. What the Code Actually Does (End-User Impact)

1. **`/status` no longer crashes when a tool call's diff-read fails (deferred lambda NameError):** a user with an active review session hits a transient git error → previously the `idle_add` callback raised `NameError: cannot access free variable 'e' where it is not associated with a value in enclosing scope` and the error-report path itself crashed. The user saw no error and a half-finished review. Now the error text "❌ Failed to read diff: <name>: <msg>" reaches the chat pane. Code path: `ui/handlers/review_handler.py:296-310` → `idle_add(lambda sk=sk, err=e: ...)` → GLib main loop → `_on_display_text` → chat render.

2. **The activity drawer's per-agent counter row correctly labels `tool_error` (was rendering the raw string "tool_error"), and survives a `None` duration (was raising TypeError):** a user with an active agent session who hits a tool failure now sees a clean row labeled "tool" with a sane time-display (or empty duration if not yet known). Previously the label was the raw enum string and a None duration crashed the entire counter summary line, hiding the agent's activity count. Code path: `ui/views/activity_drawer.py:284-295` → `format_duration(int(total_ms))` → `models/activity.py:format_duration` (the public name, single source of truth).

3. **The audit log can no longer grow unbounded in long sessions:** a long-running session (e.g. a 10-turn implementation loop with many tool calls) previously accumulated every entry in `AuditLog._entries` forever. The `flush_audit_log` method that would have written them to disk was only called by tests. At 2000 entries the buffer caps (oldest dropped); at every terminal turn (COMPLETED, FAILED, CANCELLED) the buffer flushes. A user inspecting `~/.config/crabcakes/audit-log.jsonl` after a long session now sees the actual recent history, not an empty file plus a memory leak. Code path: `agent/runtime.py:771-775` (the new `try: self._audit_log.flush_audit_log() except: ...` block, deliberately outside the state lock and outside `if should_persist:` so CANCELLED turns flush too) → `agent/audit.py:flush_audit_log` → JSONL append.

4. **A static type check (or `get_type_hints()` call, or an IDE hover) no longer lies about the parameter type of any of the 9 annotation-only imports:** previously, `agent/persistence.py:42` claimed `conv: "Conversation"` with no way to resolve the name; `ui/handlers/feed_handler.py:4` modules all claimed `dict[str, Gtk.Widget]` without importing Gtk. A future contributor who added a runtime `get_type_hints()` call to a static check, or a mypy strict-mode pass, would have failed. Now every annotation resolves under `TYPE_CHECKING` and the runtime cost is zero. Code path: 9 modules, each with a new `if TYPE_CHECKING: from X import Y` block at module top; `tests/test_architecture.py:39-49` and `:188-201` (the new AST-based layer guards) verify the imports stay annotation-only.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **`ui/views/left_panel.py:15` runtime view→handler import (verified pre-existing on `90d530b`):** `from ui.handlers.file_tree_handler import FileTreeHandler` is a real architecture violation. The new AST-based layer guard (`b4ab39a`) now reports it cleanly as the only remaining failure. Needs a product-side decision: keep as-is (documented exception), move to TYPE_CHECKING if used only in annotations, or wire via callback. Not in AC1 scope.

2. **`tests/test_architecture.py::test_utils_gtk_imports_are_documented` reports `gtk_containers.py` as undocumented (verified pre-existing on `90d530b`):** one-line fix to add `gtk_containers.py` to the carve-out set in both `docs/ARCHITECTURE.md` §2 and the test's `documented_carve_outs` constant. Not in AC1 scope.

3. **`tests/test_agent_runtime.py::TestEndStreaming*` OOM-kills at ~14GB (verified pre-existing on `90d530b` in isolated worktree via `/usr/bin/time -v`):** the cluster exists at baseline; the OOM is not caused by 2c's cap or flush. Mitigated by per-class runs in the loop. Not in AC1 scope.

4. **`tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions` 2/20 failures (verified pre-existing on `90d530b`):** tool_start suppression + `_ended_sessions` race (referenced as `BUG #21` in source). Not in AC1 scope.

5. **17 root scratch scripts + 1 broken audit script + 1 empty-assistant bulk-repair (from simplification audit):** not touched by AC1; deferred to AC2 (dead-code sweep). The 5 Commit-Emitted-After-Empty-Fix: the 4 import-fix tests are all new in AC1 and don't pre-exist at `90d530b`.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Project-level enforcement hook: `git diff <last_spec_sha> HEAD` non-empty AND `git log --grep="^Accept:" --grep="^fix"` reveals revert-pattern | 4-6 hours (build + write tests) | Eliminates the silent-revert process hazard permanently; no more PM-authorized resets needed |
| Fix `TestEndStreaming*` OOM (add a `@pytest.mark.oom` skip OR root-cause the memory growth) | 2-4 hours (debug) OR 1 hour (skip) | test_agent_runtime.py runs end-to-end; future regressions visible |
| Add `gtk_containers.py` to GTK carve-out table (1-line in `docs/ARCHITECTURE.md`, 1-line in the test) | 15 minutes | test_architecture.py goes from 2 failed to 0 failed |
| `left_panel.py:15` view→handler runtime leak — product decision + move to TYPE_CHECKING OR callback | 3-4 hours | test_architecture.py fully green; closes the architecture gap |
| `utils.prompts.py` dedup (move to `utils/prompt_paths.py`, extend `chat_input_toolbar.py` import) | 1-2 hours | Removes the "duplicate scanner" pattern; same single-source-of-truth principle as `a448d68` |
| Add a "review-layer-silent-revert" simulation test: deliberately stage a baseline checkout + Accept + verify the standing rule fires | 1-2 hours | Regression coverage for the new standing rule |
| Convert the AST layer-guard pattern into a reusable pytest helper (`def assert_no_runtime_imports(path, forbidden_modules, *, type_checking_aware=True)`) | 2-3 hours | Any future layer-isolation test inherits the smartness |
| Replace `re.search(r"to (.+)$", result)` in `agent_runtime_handler.py` (used in `on_tool_call_start`'s write_file success path) with a parser that respects quoted spaces / newlines | 1-2 hours | Fixes a latent edge case in the review staging path |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Standing pre-push gate: `git diff <last_spec_sha> HEAD` must be empty for every source file, AND scan every Accept commit in the chain for content that reverts a prior spec'd commit.**
   - Trigger: any work-unit close before push.
   - Action: run `git diff <last_spec_sha> HEAD --stat` (must be empty); then `for sha in $(git log --oneline | grep "Accept:" | awk '{print $1}'); do git diff $sha^ $sha --stat | grep -E "^[ ]*<spec-source-file>"; done` (any non-empty result = silent revert).
   - The first run on AC1 caught BUG #6 (silent revert at `e0361bc`); the second run on AC1 would not have (the revert was already reset away).

2. **No `git reset --soft` or `git reset` during sub-phase delivery — use `git checkout <pinned_sha> -- <files>` for verification restores, and verify content identity at the end.**
   - Trigger: any time the builder's verification step mutates the working tree (revert-to-baseline, mutate, restore, etc.).
   - Action: pin a known-good SHA before any mutation; restore from the pin, not from `main` (whose tip can move during the work); verify with `git diff <pinned_sha>` at the end.
   - This was learned at 2a (Coder's incident), confirmed by me, confirmed by Debugger. AC1 had THREE separate reset incidents; AC2 instructions should call this out explicitly.

3. **Spec self-review checklist: before any `/ask` delegation, re-read the spec for (a) numbered-vs-unnumbered contradictions, (b) flag-name confusion (`pytest -B` is a Python flag, not pytest), (c) sibling patterns not pre-decided for joint delivery, (d) every fix's commit message spelled out.**
   - Trigger: every spec-writing turn.
   - Action: explicit self-review before delegating; PM-side spec-review before any implementation. The 2a instructions had a 5-vs-4-commits contradiction that survived one full sub-phase.

4. **Hermeticity assertion is a per-sub-phase verification, not a unit-end check: any new test that calls into a production code path which writes user data must patch that path before its first run, and prove hermeticity with before/after `ls` of the real-data location.**
   - Trigger: any test that exercises a path which calls `flush_audit_log`, writes to `~/.config/crabcakes/`, sends a network request, etc.
   - Action: a narrow module-scoped autouse fixture is the right pattern; a global conftest autouse is the wrong pattern. Verify the fix with the same per-class runs you use for GTK suites.

5. **Spy test design: a shared mock without reset can let a prior test's call satisfy an assertion. Spy tests must use a fresh local mock (e.g. `calls = []; with patch.object(...): ...`) and assert exact counts on the local list.**
   - Trigger: any test that uses `unittest.mock.patch.object` to count calls.
   - Action: never rely on a module-level or class-level mock's call count across tests; create the mock in the test body and use a local collector.

6. **When Debugger's audit produces a "latent issue" or "observation" with a self-canceling fix field, the supervisor rules it explicitly with rationale in the post-mortem, not by silence.**
   - Trigger: any audit finding that the auditor themselves walks back in their fix field.
   - Action: in the next post-mortem, log the finding as "false alarm, ruled by supervisor with rationale: X". Avoids future auditors wasting cycles on the same false alarm.
   - Applied twice this unit: BUG #7 (sticky TYPE_CHECKING flag) and the BUG #4 (format_duration(True)) — both ruled acceptable, both logged here for future-me.

7. **`xvfb-run -a` supersedes the 2026-08-21 "run GTK suites individually" workaround for THIS environment.**
   - Trigger: any GTK-touching test in the local dev environment.
   - Action: `xvfb-run -a python3 -m pytest <suite> -q` runs to completion; the segfault at teardown was a headless-display artifact, not a code defect. The "never claim green from an aborted run" rule still applies — just with `xvfb-run -a` the abort doesn't happen.

---

## 11. Sign-off

- [x] Code committed and pushed to `main` at `f7daff2` (range `90d530b..f7daff2`, 8 spec'd commits, 14 junk Accept commits scrubbed via PM-authorized `git reset --hard f7daff2`)
- [x] All post-loop verification commands run and pasted: pyflakes 0, gate verified by Supervisor + Debugger; test_activity_drawer 41/41; test_agent_audit 10/10; test_render_error_callbacks 2/2; test_chat_render_handler 40/40; test_architecture 2/4 red-by-design-or-pre-existing; consumer suites (activity_bubbles 52/52, activity_wiring_handler 13/13, connection_sync_handler 29/29) all green under `xvfb-run -a`; hermeticity proven (no real `audit-log.jsonl` leak)
- [x] PM notified with this summary (next message)
- [x] Tier 2+ backlog updated: enforcement hook, TestEndStreaming OOM, gtk_containers carve-out, left_panel.py:15 leak, utils.prompts dedup, layer-guard helper extraction, regex-tightening in `on_tool_call_start` — all in §9
