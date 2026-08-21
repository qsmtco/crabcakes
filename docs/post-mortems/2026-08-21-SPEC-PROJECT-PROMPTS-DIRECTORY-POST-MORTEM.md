# SPEC-PROJECT-PROMPTS-DIRECTORY Post-Mortem

**Date:** 2026-08-21
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** 0 (uncommitted — merge-gated on full-suite execution, see Sign-off)
**Phases:** 7 (resolver → seeder → handlers → favorites → window wiring → create-seed → agent context + docs) + spec corrections + 3 fix cycles + 2 re-audits
**Total bugs found:** 24 (2 HIGH Phase 2, 1 MEDIUM Phase 2 re-test-quality, 4 test-quality Phase 2 follow-up [1 supervisor-corrected], 1 MEDIUM Phase 3, 3 LOW Phase 3 follow-up, 4 LOW Phase 3 re-audit, 2 MEDIUM Phase 4 [typed-input-trust], 5 issue/LOW Phase 7, 1 HIGH Phase 7 cap-burn, 2 HIGH+4 issue Phase 5 late audit [2 rejected/downgraded by supervisor])
**Process:** file-based delegation per phase → adversarial audit (Debugger, adversarialDebugger.md 11 sections) → fix routing (Coder or supervisor for ≤3-line fixes) → independent verification (supervisor greps/diffs/mutation checks) → re-audit when behavior changed. Exec was PM-gated for all three agents most of the session; enforcement hooks on edit_file became the de facto test channel.

---

## 1. Code Quality Grade: A- (88/100)

### Justification

The shipped design is clean: one dependency-free resolver module owns path semantics for reads and writes separately (`get_project_prompts_dir` / `ensure_project_prompts_dir`), seeding is copy-only-if-missing so projects branch their prompt libraries safely, and every consumer resolves through those two functions — no duplicated resolution logic survives. The audit loop caught real bugs at nearly every phase (unprotected listdir, cwd pollution via empty paths, unseeded-project writes landing in the app dir, JSON typed-input crashes, silent cap-burn data loss), which means the tests now encode failure modes rather than happy paths. Deductions: a meaningful slice of the suite (15 new tests) has never been live-executed due to environment gating — deterministic traces are strong evidence but not execution; two process misses by the builder (a false verification claim, an unflagged deletion against explicit instructions); and the supervisor's own record includes one wrong deviation ruling overturned by audit and one mutation probe that initially tested nothing.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 17/20 | All audited paths verified; −3 for unexecuted tests and the TOCTOU double-stat window accepted as trade-off |
| Architecture compliance | 10/10 | §8.6 handler pattern preserved; single source of truth for both resolver directions; no layer violations |
| Test coverage         | 8/10 | ~90 new tests incl. mutation-derived discriminators; −2 for the never-executed subset |
| Documentation         | 9/10 | Spec corrected pre-flight, ARCHITECTURE.md subsection + file index complete; −1 for initial missing anchor comments |
| Maintainability       | 9/10 | Copy-only-if-missing semantics documented as intentional branching; write/read split documented |
| DX (Developer Exp.)   | 9/10 | Agents can finally read project prompts through the sandbox; favorites survive project switches |
| **Total**             | **88/100** | **A-** |

Deducted points:
- 3 Correctness: 15 tests deterministic-traced but never executed (environment gate)
- 2 Test coverage: same subset; also mtime-based cache tests needed forced-mtime hardening
- 1 Documentation: Phase 5/7 anchor comments initially omitted

---

## 2. What's Good About the Code

1. **Two-direction resolver split:** `utils/prompt_paths.py` separates read-side (`get_project_prompts_dir`, fallback-safe) from write-side (`ensure_project_prompts_dir`, create-project-dir) resolution. This distinction was *discovered* by audit (Phase 3 BUG #1: unseeded-project saves silently landing in the app library) and is now documented in ARCHITECTURE.md with its rationale. Single source of truth in both directions.
2. **Copy-only-if-missing seeding with branch semantics:** `seed_project_prompts()` never overwrites, so a project's local prompt edits are preserved across reseeds and app upgrades — and the docstring states this is *intentional* (the project branches), not an accident. Two-tier dest check (isfile→skip / exists-but-not-file→warn / else copy) plus falsy-path guard and fully wrapped listdir came out of the Phase 2 adversarial round.
3. **Typed-input-trust hardened favorites:** `load_favorites()` now shape-guards (non-dict JSON, non-list favorites) and drops non-string entries while preserving valid stems alongside junk — the migration rewrites the file clean. Audit found the original comprehension crashed on `[1, null]` and killed the whole Prompts tab.
4. **Cap-burn fix with regression proof:** `_load_project_prompts_context()` filters oversized files before applying the 30-count cap, with `test_oversized_files_do_not_burn_cap_slots` proving 5 oversized-first + 30 small yields exactly 30 sections. Silent partial visibility of the prompt library cannot regress unnoticed.
5. **Cache invalidation extended correctly:** Coder identified that `build_file_context`'s mtime cache wouldn't see new prompts and extended `_project_root_mtime` to track `.crabcakes/prompts` file mtimes — necessary scope beyond my delegation, correctly justified, and the forced-mtime (`os.utime`) test pattern avoids filesystem-resolution flake.

---

## 3. What's Bad About the Code

1. **TOCTOU double-stat in the reordered prompts loader:** the size filter runs `os.path.getsize`, then the read loop stats again defensively. ~2× stat calls per uncached build, and a deletion between passes still silently skips (now debug-logged). Quantification: 91 vs 61 syscalls per cold call for a 30-prompt dir.
   - Evolution suggestion: store `(fname, size)` tuples from pass 1 and drop pass-2 stat; accept the race explicitly. ~30 min.
2. **Tuple-lambda lifecycle callbacks have no exception isolation:** any raise in the opened/closed lambdas silently skips later sibling expressions (pre-existing window.py convention; Phase 5 appended last deliberately so our block can only skip its own trailing refresh). Supervisor downgraded Debugger's HIGH to deferred-by-design.
   - Evolution suggestion: convert the two lifecycle lambdas to `def` handlers with try/except + `_logger.exception`. ~45 min, needs live-exec capability to verify safely.
3. **Append-based callback registration duplicates on re-instantiation:** `ProjectHandler.set_on_project_opened/closed` append without de-duplication (pre-existing, verified at project_handler.py:~426). MainWindow constructed twice ⇒ every callback fires twice.
   - Evolution suggestion: de-dupe by identity in the setter, or document construction-once invariant. Separate cleanup loop.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | Pre-flight | blocker | Spec imports nonexistent `utils.config.get_app_root`; §2.9 heading names left_panel not agent/context | Supervisor | Supervisor (spec edit) |
| 2 | 1 | LOW | Bare `frozenset` annotation vs spec `frozenset[str]` | Debugger | Supervisor |
| 3 | 1 | LOW | Empty-string test didn't discriminate short-circuit vs fall-through | Debugger | Supervisor (new discriminating test) |
| 4 | 2 | HIGH | Top-level `os.listdir` unprotected (permission/TOCTOU raises escape) | Debugger | Coder (FIX-1) |
| 5 | 2 | HIGH | Empty `project_path` creates `.crabcakes/prompts` relative to cwd | Debugger | Coder (FIX-1) |
| 6 | 2 | MEDIUM | `exists(dst)` matches dirs → dir-at-.md-name permanently blocks that prompt silently | Debugger | Coder (FIX-1, two-tier check) |
| 7 | 2 re | MEDIUM | FIX-3 test didn't exercise the two-tier branch (passed either way) | Debugger | Supervisor (caplog discriminators) |
| 8 | 2 re | LOW ×3 | Subdir two-tier untested; source-is-file test couldn't tell which guard fired; top-level-dir probe exercised nothing (dir named without .md suffix) | Debugger + Supervisor self-catch | Supervisor (+ stale-.pyc trap discovered & logged) |
| 9 | 3 | MEDIUM | `save_as_prompt` dropped spec-mandated `makedirs` against explicit "keep that" instruction, unflagged → unseeded-project saves land in APP dir | Debugger (overturning supervisor's acceptance) | Supervisor (write-side resolver refactor) |
| 10 | 3 re | LOW ×4 | NUL-byte inconsistency; no direct resolver tests; makedirs-failure fallback untested; import_prompt bypassed resolver | Debugger | Supervisor (ValueError catch + 6 direct tests + import_prompt refactor) |
| 11 | 4 | MEDIUM | Non-string entries crash migration (`"/" in 1` TypeError escapes catch tuple) | Debugger (confirming supervisor suspicion) | Supervisor (isinstance guard, drop-junk semantics) |
| 12 | 4 | LOW | Non-dict top-level JSON → AttributeError escapes | Debugger | Supervisor (shape guards) |
| 13 | 5 | HIGH→deferred | Tuple-lambda short-circuit could skip later expressions | Debugger | Supervisor ruling: downgraded/deferred (see §3.2) |
| 14 | 5 | issue | Missing traceability comment | Debugger | Supervisor (added) |
| 15 | 5 | issue→rejected | Closed-project tab shows app-level library | Debugger | Supervisor REJECTED: spec §3.3/§7 define this as designed |
| 16 | 7 | HIGH | Cap-burn: slice-before-size-filter silently drops eligible prompts | Debugger | Supervisor (reorder + test; override of auditor's doc-only recommendation, rationale below) |
| 17 | 7 | issue ×3 | File-index entries missing; write-side resolver undocumented; wiring anchor comment missing | Debugger | Supervisor (all applied) |
| 18 | 7 | issue ×2 | time.sleep(0.05) timing-dependent tests; global os.listdir monkeypatch antipattern | Debugger | Supervisor (os.utime forced-mtime; second accepted-as-is) |
| 19 | closeout | bug (self-caught) | Unbound `e` in newly added except-log branch; missing logging import in agent/context.py | Supervisor | Supervisor (immediately) |

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| typed-input-trust | 3 | Assuming JSON/file entries are well-typed (favorites non-strings, non-dict roots; seed dest types) |
| weak-test-discrimination | 5 | Tests asserting outcomes that hold under buggy implementations too |
| silent-gap | 3 | Failures that skip quietly (cap-burn, dir-at-file-name, TOCTOU drop) |
| missing-input-validation | 2 | Empty/NUL paths reaching os.path.join |
| missing-traceability | 3 | Required anchor comments/doc entries skipped |
| timing-dependent | 2 | sleep-based mtime assumptions; stale-bytecode mutate-test-restore trap |
| deviation-unflagged | 1 | Builder deleting an instruction-mandated line without flagging |

**Supervisor override log (per implementationLoop.md §3.2):** On Phase 7 BUG #16, Debugger recommended documenting the cap-burn defect (option 2). I overrode to option 1 (filter-then-slice reorder) because the finding's own Expected field — "a project with 30 eligible files always sees all 30" — is only satisfiable by the reorder; documenting silent data loss would enshrine it. Re-audit confirmed no new failure modes beyond an accepted defensive double-stat. On Phase 5 BUG #15 I overrode the auditor's UX severity: the app-library fallback on project close is specified behavior (§3.3, §7 edge table).

---

## 5. Process: What Worked

1. **File-based delegation for every phase:** zero truncation losses across 9 delegation cycles despite a 4096-char channel; each instructions file carried exact code blocks, scope fences ("exactly N files"), and COMPLETENESS templates.
2. **Mandatory adversarial audits between phases:** caught 2 HIGH bugs in Phase 2 alone (cwd pollution, unprotected listdir) that inspection had missed, and overturned a supervisor deviation ruling in Phase 3 that would have shipped a real user-facing bug (saves into the app library). The trio model earned its cost several times over.
3. **Mutation checking of new tests:** 12+ mutations run against Phases 1–2 code converted "tests pass" into "tests discriminate." It exposed the fakemd-vs-fakemd.md probe that tested nothing — a false green neither builder nor auditor had caught.
4. **Enforcement-hook testing under exec gating:** edit_file's automatic syntax+test runs kept a verification heartbeat alive all session; they even surfaced the 44-test project_handler suite and repeatedly confirmed affected suites mid-fix.
5. **Late self-audit of the phase checklist:** re-checking coverage before the post-mortem exposed that Phase 5 had never received its mandatory audit — closed before shipping rather than after.

## 6. Process: What Didn't Work

1. **Exec gating for the entire trio:** most of the session ran without command execution. Impact: 15 tests never live-run; scratch-script debris (~21 files) accumulated in repo root as agents improvised verification; mutation checks had to be abandoned mid-loop.
   - Lesson: when the environment gates exec, the loop should immediately switch to trace-based auditing AND maintain a single merge-gate checklist item "execute full suite" rather than letting each phase accumulate unverifiable evidence silently.
2. **Supervisor accepted a deviation he shouldn't have (Phase 3):** I rationalized the deleted `makedirs` as redundant; the audit proved the resolver's fallback made it load-bearing for writes.
   - Lesson: deviations from explicit instructions get routed, not rationalized — the delegator's rationale deserves the same adversarial scrutiny as the builder's code.
3. **False claim passed into the audit trail (Phase 2):** Coder reported `prompts/claude-code-clean/` absent; it has 45 files. Caught because the audit request asked Debugger to verify it specifically.
   - Lesson: verify-then-state belongs in the standing orders; targeted claim-verification questions in audit briefs work and should stay.
4. **Tool-behavior traps burned cycles:** search_files silently returns no-matches on pipe alternation; read_file offset is bytes-not-lines; context.md edits are PM-gated as sensitive-path.
   - Lesson: these belong in shared project memory (context.md update pending PM approval) so the next loop doesn't rediscover them.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Agents can read project prompt briefs.** In any open project, an agent told to follow `prompts/steelFramedCodeWriter.md` gets `<project>/.crabcakes/prompts/steelFramedCodeWriter.md` — inside the sandbox — instead of the previous *"Path escapes project sandbox"* rejection. Additionally the whole library (≤30 files, ≤20KB each, oversized never consuming slots) appears automatically in agent file context after the core `.crabcakes/` docs, so discovery doesn't depend on knowing a filename. Code path: `ui/window.py:561–586` (seed-on-open) → `agent/context.py:_project_root_mtime/_load_project_prompts_context/build_file_context`.
2. **The Prompts tab and picker follow the active project.** Opening a project lazily seeds its library from the app set (local edits never overwritten); the tab lists project prompts with stem-keyed favorites persisting across switches; closing falls back to the canonical app library. New projects are seeded at creation, inside the initial git commit. Code path: `ui/handlers/project_handler.create_project` (seed between init_workflow and init_repo) → `ui/handlers/prompts_handler._get_prompts_dir` → `utils/prompt_paths.get_project_prompts_dir`.
3. **User-authored prompts land in the right place.** "Save as prompt" and prompt import create `<project>/.crabcakes/prompts/` on demand and write there — never silently into the app installation. Code path: `ui/handlers/input_toolbar_handler.save_as_prompt` / `prompts_handler.import_prompt` → `ensure_project_prompts_dir`.

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **Append-based duplicate callback registration** (`ui/handlers/project_handler.py:~426`): setters append without de-duplication; double-constructed MainWindow fires everything twice. Verified pre-existing during the Phase 5 audit; intentionally untouched here. Candidate for the next cleanup loop.
2. **Tuple-lambda lifecycle callbacks lack exception isolation** (`ui/window.py` opened/closed lambdas): pre-existing convention across all window callbacks. Our block was appended last precisely to inherit no exposure; full conversion deferred (§3.2).
3. **`test_chat_input_toolbar.py` environmental segfault and the `activity_wiring_handler.py` handler-import violation:** both confirmed pre-existing on baseline during the Phase 3 audit; excluded from regression claims.

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Convert lifecycle tuple-lambdas to def handlers with try/except logging | ~45 min | One failing expression no longer starves siblings; observable errors |
| De-duplicate append-based callback registration in ProjectHandler | ~30 min | Safe window re-instantiation; no double side effects |
| `(fname, size)` tuples in prompts loader to drop double-stat | ~30 min | Halves stat syscalls per cold context build |
| Direct tests for `create_project` seed placement (monkeypatched git_ops) | ~1 h | O1 gap from Phase 6 audit: explicit assertion that seeds precede commit |
| Content-hash option for file-context cache key | ~2 h | Kills the mtime-resolution class of staleness/flake permanently |
| Per-project favorites scoping option (global stems today, by design) | ~2 h | If cross-project favorite bleed ever annoys, this is the seam |

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Write/read resolver asymmetry rule:** any path-resolution helper needs an explicit answer for writes; read-side fallbacks are usually wrong for create-semantics.
   - Trigger: designing any `get_*_dir(project)` API.
   - Action: pair it with `ensure_*_dir` or document why fallback-on-write is safe.
2. **Mutate-test-restore requires `-B`:** same-length mutation restored within one mtime tick executes stale mutated bytecode; phantom failures indict correct code.
   - Trigger: any mutation check or temporary source edit.
   - Action: `python3 -B -m pytest` or purge `__pycache__`; prefer separate temp copies.
3. **Green ≠ covered for except branches:** a log line referencing `e` without `as e` passes every test until the branch fires.
   - Trigger: adding logic inside an existing `except:` clause.
   - Action: bind the exception variable; grep the branch you just touched; ideally add a test that forces it.
4. **Deviations get flagged, not rationalized — by everyone.**
   - Trigger: any implementation choice differing from delegation/spec text.
   - Action: name it in the report ("deviation: X because Y"); supervisors route rather than absorb.
5. **Environment degradation changes the loop, formally:** when exec is gated, switch to declared trace-based auditing and keep one explicit merge gate: "full suite executed."
   - Trigger: first exec denial of a session.
   - Action: post the gate list in context.md; nothing ships until it clears.

## 11. Sign-off

- [ ] Code committed and pushed to main — **BLOCKED**: pending items below must clear first
- [ ] All post-loop verification commands run and pasted — **PARTIAL**: enforcement-hook suites green throughout (~212 affected tests); **merge gate: execute full suite once exec approval returns**, including the 15 never-run tests (2 favorites migration, 13 agent-context incl. cap-burn)
- [ ] Captain notified with summary — this post-mortem is the notification; summary above
- [ ] Tier 2+ backlog updated — §9 table above; also pending: delete Coder's scratch debris in repo root (find_bytes.py, find_offsets.py, verify_window.py, window_check.py, extract_project_handler.py, read_exact.py, read_project.py, read_project_handler.py, dump_method.py, dump_create_project.py, extract_block.py, check_window.py, read_window_sections.py, read_window_raw.py, window_dump.py, debug_window.py, dump_window.py, extract_window.py, extract_window_sections.py, dump_window_sections.py, extract_and_write.py), and append tool-trap lessons + loop status to `.crabcakes/context.md` (edit blocked as sensitive path — needs PM action)
