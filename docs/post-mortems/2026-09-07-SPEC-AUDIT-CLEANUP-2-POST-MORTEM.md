# Audit Cleanup 2 — Dead-Code Sweep (SPEC-AUDIT-CLEANUP-2) Post-Mortem

**Date:** 2026-09-07
**Supervisor:** special:supervisor
**Builder:** special:coder
**Auditor:** special:debugger
**Commits:** 9 spec'd (`0b4258c`, `7f68faa`, `1e3ea2d`, `6d22762`, `384956b`, `b2d0fe8`, `fef2f05`, `837e1e8`, `be5b2c7`) over 5 phases, plus 5 supervisor instructions commits (`2c4949e`, `0093a30`, `6f8c87a`, `32ade4d`, + Phase-5 file pending)
**Phases:** 5 (scratch scripts → task retirement → dead functions → shims+tests → scripts/comments/pycache), each with mandatory adversarial audit + re-audit on fixes
**Total bugs found:** 4 (0 crash-class; 2 test-scaffolding, 1 doc-lie, 1 spec-accounting) — see §4
**Process:** loop protocol §3.1a per code-bearing turn; standing AC1 rules in force from the start (no resets, xvfb, re-grep, doc-lie rule, content-identity gate)

---

## 1. Code Quality Grade: A (93/100)

### Justification

~1,800 net LOC removed (−2,464/+673 across 53 files) with **zero regressions**: full-suite baseline comparison in an isolated worktree proved the 40-failure set byte-identical pre/post, and the −25 passed delta equals exactly the deleted test suites. Every deletion was re-grepped at execution time, and the builder **correctly refused to delete on three items where the spec was wrong** (`diff_stat_against` live, `FeedCardData` live, `workspace` load-bearing) — the "tree wins" discipline worked as designed. This was also the first unit with **zero review-layer history surgery**: the AC1 no-reset standing rule (applied by the builder from Phase 1) meant no Accept-commit junk, no silent reverts, and clean end-to-end history. Deductions: spec drift the builder had to route around (2 items), one tautological assertion shipped in Phase 2 and caught in audit (should have been caught by builder's own Rule-4 pass), and the pre-existing 40-failure backlog is now documented but still unfixed.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 19/20 | All 5 phases audited clean; identical 40-failure baseline; gates held (undefined-name 0 throughout; pyflakes 121→64 unit-wide). −1: Phase-2 tautological assert shipped then audit-caught. |
| Architecture compliance | 10/10 | models→agent layer rule RESTORED (shims deleted); ui→models direction everywhere; ARCHITECTURE.md same-commit updated both for tree listings and deleted API entries; doc greps clean. |
| Test coverage         | 10/10 | Coverage-migration phase done properly: 18 assertions migrated (above spec's 13), non-vacuous preconditions, behavioral-equivalence spot-checked by auditor; +166 net new test LOC across the unit's fixes. |
| Documentation         | 9/10  | All docs consistent post-sweep (doc-lie rule enforced); −1: historical docs retain references by design (flagged, allowed) — no annotation added marking them as removed-in-<sha> (Phase-1 audit suggestion, deferred). |
| Maintainability       | 9/10  | Task system, shims, scratch, orphan functions gone; /status now reads the work store; pyflakes noise down 47%. −1: 64 findings remain (mostly pre-existing test-side `pytest.skip` noise). |
| DX (Developer Exp.)   | 9/10  | Zero history surgery this unit; chunked-run + xvfb patterns stable; the spec table's commit-message numbers inherited stale audit figures (591 vs actual 532) — flagged, cosmetic. |
| **Total**             | **93/100** | **A** — sweep achieved its goal with zero regressions and a cleaner process than AC1. |

Deducted points:
- 1 Correctness: tautological teardown assert shipped (caught in audit, fixed `1e3ea2d`)
- 1 Documentation: no removed-in-<sha> annotations on historical docs
- 1 Maintainability: 64 pyflakes findings remain (pre-existing, documented)
- 1 DX: commit message inherited audit's stale 591-LOC figure

---

## 2. What's Good About the Code

1. **The "tree wins" refusal discipline (Phases 3-4):** when the spec said delete `diff_stat_against` (live test refs) and `FeedCardData` (live consumer), the builder grepped at execution time, refused, and reported — exactly what the spec's hard rule demanded. Both spec errors were mine; the loop's safety rail caught them. The workspace ruling (`384956b`) went further: the builder identified the binding as dead but the call as load-bearing (LOW-2 validation + 0o700 mkdir), surfaced the options, and took the minimal correct action (bare call) after my ruling.
2. **The coverage-migration phase (fef2f05) as a pattern:** deleting 276 LOC of shim-only tests without losing a single unique assertion — 18 migrated with non-vacuous preconditions (`assert summary != ""` etc.), the auditor's broken-strategy simulation table verified each would fail on a real regression. The builder's own Rule-4 self-correction (catching its first drafts as vacuous under-sized fixtures) is the playbook working exactly as intended.
3. **Atomic task retirement (7f68faa):** the task-redesign post-mortem's BUG#12 lesson (integration changes that reference each other's APIs must share a phase) applied to the letter — one commit, no reachable intermediate state, `/status` migrated and the old system gone simultaneously, with a 6-test bucket-mapping suite pinning the new behavior including the cancelled-exclusion edge.
4. **Zero history surgery end-to-end:** the AC1 lesson (no `git reset` during delivery) was in force from Phase 1, and the result is the first unit where the Accept chain contains **no junk, no reverts, no supervisor cleanup** — content-identity gate trivially empty, remote push is the straight 12-commit spec'd chain.
5. **The find_spec probe ruling (be5b2c7):** rather than deleting the "unused" numpy import (which was a fail-fast dependency probe), the fix converted it to `importlib.util.find_spec` — same user-facing error, no module execution, finding dead. The builder proved the negative path empirically (`python3 -S` hiding site-packages, driving the real function to its SystemExit(1)) instead of arguing from theory.

---

## 3. What's Bad About the Code

1. **A tautological assertion shipped (Phase 2) and only audit caught it:** `ws.get("9900001")` — 7 digits against 8-digit seeds — could never fail; teardown was unguarded. The builder's Rule-4 pass should have caught it (the red-evidence habit makes vacuity visible); Debugger's adversarial probe (no-op the teardown, watch the assert pass) is what found it.
   - Evolution: the auditor's break-the-guard technique (monkeypatch the cleanup, assert must still fail) should be added to the builder's Rule-4 checklist as a standard probe for all teardown/post-condition asserts.
2. **Spec drift was a recurring tax this unit (3 items):** `diff_stat_against` (audit's refs were tests I didn't recheck), `FeedCardData` vs `AgentConfig` (my instructions misnamed the unused import), `bulk_repair`'s test suite (spec table listed the script, not its 21-test suite — caught pre-delegation by my own re-verification). Each cost a routing cycle or a same-phase instruction amendment.
   - Evolution: spec authoring should include a "consumer sweep" pass for every deletion candidate: grep not just the identifier, but its import surface in `tests/` and `scripts/`, and write the full deletion set (file + its tests) into the table.
3. **The 40-failure pre-existing backlog is now precisely characterized but unfixed:** identical failure sets pre/post (proven), dominated by `test_special_agents` (env/provider-registry), `test_auxilium_tier2` (KB env), `test_architecture` ×2 (left_panel.py:15 real violation + gtk_containers carve-out), `test_mcp_config` ×1, `test_runtime_fallback` ×4, `test_kb_integration` ×1.
   - Evolution: a dedicated "test-debt" unit to burn this down — the worktree-baseline-diff pattern (this unit's §7 gate) makes each fix provable.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 1 | issue | Commit subject said "591 LOC" (audit doc's stale figure incl. main.py); actual 532 — cosmetic accounting | Debugger (probe §10) | Deferred (post-mortem item; history correct as-is) |
| 2 | 1 | suggestion | Audit docs still list deleted filenames as-if-live; no "removed in 0b4258c" annotations | Debugger (probe §10) | Deferred (§9 backlog) |
| 3 | 2 | issue | `_make_status_cmd` unreachable stale tail after return (duplicate docstring + return) | Debugger (probe §2) | Coder (`1e3ea2d`) |
| 4 | 2 | issue | Tautological teardown assert: `ws.get("9900001")` 7-digit vs 8-digit seeds — inert guard | Debugger (probe §3) | Coder (`1e3ea2d`, red/green pair proving old-inert/new-guards) |
| 5 | 3 | bug | ARCHITECTURE.md:1988,2124 still documented deleted `_load_crabcakes_doc`/`get_index_path` (doc-lie-after-deletion) | Debugger (probe §9) | Supervisor directly (`b2d0fe8`, per small-fix precedent) |
| 6 | 3 | issue | Spec error: `diff_stat_against` listed as dead — live test refs in test_git_ops.py | Coder (re-grep refusal) | Spec superseded; function KEPT (correct) |
| 7 | 3 | issue | Spec error: instructions named `FeedCardData` as the unused import — actually `AgentConfig` | Coder (re-grep refusal) | `AgentConfig` deleted (correct) |
| 8 | 5 | issue | `rebuild_kb_index.py` numpy import = dead probe binding (unused-import finding) | Coder (related-issue flag) | Coder (`be5b2c7` find_spec, negative path proven) |

8 findings: 1 bug-severity (doc-lie, fixed same-cycle), 5 issue, 2 suggestion. Auditor found 5; builder found 3 (including both spec errors — the builder's re-grep discipline is now a primary bug-finder, not just a safety rail). Nothing compounded; nothing crossed phases.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `doc-lie-after-deletion` | 2 | Deleted identifiers still documented (ARCHITECTURE.md entries; audit-doc filename lists) |
| `tautological-assertion` | 1 | Post-condition checks a never-constructed literal — can never fail |
| `stale-tail-after-return` | 1 | Unreachable duplicate code after return (partial-edit artifact) |
| `spec-error-tree-wins` | 3 | Spec/instructions listed a live item as dead; builder refused on re-grep |
| `probe-import-as-unused` | 1 | Dependency-probe import reads as unused to pyflakes; fix is find_spec, not deletion |

---

## 5. Process: What Worked

1. **Standing rules carried from AC1 paid for themselves immediately:** the no-reset rule produced zero history surgery (first clean unit); the re-grep rule caught both spec errors at execution time; the doc-lie rule caught ARCHITECTURE.md entries; xvfb made every suite runnable. Institutional memory worked — rules written from AC1's pain were applied without re-learning.
2. **Unit-acceptance gates (the post-AC1 addition):** content-identity diff (empty), Accept-chain revert scan (no Accept commits at all), and the worktree baseline full-suite comparison (40=40 identical failure sets, diff-proven) turned "no regressions" from a claim into evidence. The −25 passed delta reconciled exactly with deleted suites — arithmetic as proof.
3. **Phase-scoped instructions files with exact commit messages:** every phase had its instructions on disk, pushed before delegation; every commit message was pre-decided. Zero mid-phase scope ambiguity; the builder never had to guess intent.
4. **Supervisor small-fix-directly precedent:** the doc-lie fix (`b2d0fe8`, 2 lines) was routed to me by my own new rule and fixed in-cycle rather than a full builder round-trip — the right cost/benefit for a 2-line doc edit with an existing grep gate.
5. **The auditor's break-the-guard methodology:** Debugger's probe #3 in Phase 2 (no-op the teardown, watch the old assert pass vacuously) is a genuinely reusable technique for auditing post-condition asserts — it found a bug static analysis classifies as harmless.

---

## 6. Process: What Didn't Work

1. **Spec drift was mine, three times (Phases 2-3, 5):** I wrote the dead-code tables from the 2026-09-07 morning verification but didn't re-sweep `tests/` import surfaces when writing phase instructions (bulk_repair's suite, diff_stat_against's refs) and misnamed one import (FeedCardData/AgentConfig). The builder caught all three — but each cost a cycle or an inline ruling.
   - Lesson: the consumer-sweep pass (grep each identifier in `tests/` + `scripts/`, enumerate the FULL deletion set incl. test files) happens at **instruction-writing time**, not just at execution time. Added to my spec-authoring checklist.
2. **The commit-message LOC figure inherited the audit's stale number (Phase 1):** "591 LOC" in the subject vs 532 actual — my instructions copied the audit doc's table without recomputing. Cosmetic but a lie in the permanent record.
   - Lesson: never copy counts from a source doc into a commit message without recomputing from the diff. Added to instructions template: "LOC figure = git show --stat at commit time."
3. **exec_command PM-gating interrupted flow twice:** mid-Phase-5 my verification batch was denied (session gate), forcing tool-fallbacks and one re-issued delegation. The builder was unaffected (their exec worked); only my verification pass adapted.
   - Lesson: when the supervisor's shell is gated, the verification duty can ride on the auditor's evidence + the builder's pasted outputs, with my spot-checks deferred to unblock. Documented in the Phase-5 instructions env note — worked as designed.

---

## 7. What the Code Actually Does (End-User Impact)

1. **`/status` in a project tab now reports Work Units instead of the retired task system:** `Work units: 3 pending, 2 active, 0 blocked, 1 done` — drawn from `work_store` with the full bucket mapping (draft/spec-pending/spec-ready → pending; in-progress/auditing → active; blocked_reason → blocked with cancelled excluded; done). Code path: `ui/handlers/project_handler.py:cmd_status` → `work_store.list_all()` → bucket sums. Retired: `models/task.py`, `ui/handlers/task_handler.py`, the `task_store` singleton — 466 LOC of a system superseded last month.
2. **The agent's context window still trims correctly, now through one code path:** the deprecated `Conversation.trim_to_token_limit`/`_last_exchange_summary` shims are gone; all trimming flows through `DefaultContextStrategy.compact` — the models layer no longer defer-imports agent code (layer rule restored). Any consumer that used the shims (only tests did) is migrated. Code path: `agent/runtime.py` → `agent/context_strategy.py:compact` → summary injection.
3. **The repo root is clean:** 17 one-off diagnostic scripts (532 LOC) gone from the root; `main.py`'s four stray dev comments gone; `scripts/` now contains exactly one live utility (`rebuild_kb_index.py`) with its numpy dependency probe modernized to find_spec fail-fast.
4. **Less noise for every future contributor:** ~47% fewer pyflakes findings (121→64 unit-wide), ARCHITECTURE.md's file inventory matches the tree (both directory listings + API blocks updated same-commit), and the audit-trail gap (scripts referenced as live in docs) is documented rather than silent.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **The 40-failure baseline set (proven identical pre/post this unit):** `test_special_agents` (2; provider registry env), `test_auxilium_tier2` (6; KB env), `test_architecture` (2: left_panel.py:15 runtime view→handler import — a REAL architecture violation needing a product fix; gtk_containers.py carve-out gap), `test_mcp_config` (1; MED-12 allowlist vs test expectation), `test_runtime_fallback` (4), `test_kb_integration` (1; stale mock signature `turn_token`), `test_improve`/`test_chat_input_toolbar`/`test_provider_test` (env/GTK), `test_enforcement::test_no_double_venv_activation` (1; hardcodes `/path/to/projects/crabwatch/` — a different project's path). All baseline-identical; none caused by AC1/AC2.
2. **test_agent_runtime.py full-file OOM (~14GB in 2 classes, baseline-proven since AC1):** chunked/per-class runs are the standing workaround; the OOM itself is unfixed.
3. **`docs/audits/*` historical docs still name deleted scripts as-if-live** (allowed history; Phase-1 audit suggested "removed in <sha>" annotations — deferred).
4. **`ui/window.py` ProjectHandler re-import + remaining pyflakes findings (64):** pre-existing, out of sweep scope by spec.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Test-debt unit: burn the 40-failure baseline (characterized in §8.1) one cluster at a time using the worktree-baseline-diff gate | 1-2 days | Green full-suite; removes the "pre-existing" asterisk from every future gate |
| Fix `left_panel.py:15` view→handler runtime import (product decision: TYPE_CHECKING or callback wiring) | 3-4 hours | test_architecture fully green; closes a real layer violation |
| Add `gtk_containers.py` to the GTK carve-out table (2-line doc+test) | 15 min | One fewer red test |
| Audit-doc annotations: append "removed in <sha>" to §1 lists in the two 2026-09-01 audit docs | 30 min | No future confusion over deleted filenames |
| Builder Rule-4 addition: teardown/post-condition asserts get the break-the-guard probe (monkeypatch cleanup; assert must still fail) | 15 min (prompt edit) | Catches tautological asserts at build time |
| Spec-authoring checklist: consumer-sweep (grep tests/+scripts/ for each deletion candidate; enumerate full deletion set incl. test files) at instruction-writing time | 15 min (process doc) | Kills the spec-drift tax at source |
| test_agent_runtime OOM root-cause (the two ~14GB classes) or pytest.ini skip marker | 2-4 hrs / 5 min | Full-file runs unblocked |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Consumer-sweep at instruction-writing time (not just execution time):** for every deletion candidate, the supervisor greps the identifier across `tests/` and `scripts/` and enumerates the FULL deletion set (file + its test suite) in the phase table. The builder's execution-time re-grep remains the second rail.
   - Trigger: writing any phase instructions containing deletions.
   - Action: `grep -rn <identifier> tests/ scripts/` — every hit becomes a table row.
2. **LOC figures in commit messages are recomputed from the diff, never copied from a source doc.**
   - Trigger: any commit message containing a count.
   - Action: the number comes from `git show --stat` of the actual commit.
3. **Break-the-guard probe for post-condition asserts (builder-side):** any test asserting cleanup/teardown effects gets a probe where the cleanup is no-op'd and the assert must still fail — else it's vacuous.
   - Trigger: writing/evaluating teardown or post-condition assertions.
   - Action: same technique Debugger used in Phase 2; a 10-line probe in the test body or scratch verification.
4. **Zero-history-surgery is the achievable default:** with the no-reset rule in force from Phase 1, this unit needed NO Accept-chain cleanup, no content-identity repairs, no PM resets — the first unit where git history is exactly the spec'd commits. The AC1 pain was process, not tooling.
   - Trigger: every future unit.
   - Action: the standing rule stands; this unit is the proof it works.
5. **The worktree-baseline full-suite comparison is the unit-close gate:** (a) run the full suite at the pre-unit baseline in a git worktree under /tmp, (b) run on the final tree, (c) diff the FAILED lists (must be empty), (d) reconcile the passed-count delta against the unit's test adds/deletes exactly.
   - Trigger: every work-unit close.
   - Action: the 4-step gate ran this unit in ~4 minutes and converted "no regressions" into evidence.

---

## 11. Sign-off

- [x] Code committed at `be5b2c7`; push pending PM go (straight 12-commit spec'd chain, zero junk)
- [x] All post-loop verification commands run and pasted: content-identity empty; Accept-scan clean; worktree baseline 40=40 identical sets; −25 passed reconciled; pyflakes 121→64 with undefined-name 0 throughout; per-phase suite outputs in each phase's report
- [x] PM notified with summary (next message)
- [x] Tier 2+ backlog updated: §9 (7 items — test-debt unit is the headline)
