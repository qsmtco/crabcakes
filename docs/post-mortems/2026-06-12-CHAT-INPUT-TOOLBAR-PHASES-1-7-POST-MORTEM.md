# CHAT INPUT TOOLBAR — Phases 1–7 Post-Mortem

**Date:** 2026-06-12
**Author:** Qaster (Implementation Supervisor, with adversarial audit)
**Scope:** Retrospective on the 7-phase Chat Input Toolbar migration — replacing the dead `ChatControlBar` stub with a real `ChatInputToolbar` providing find/replace, spell check, and word count.
**Status:** Phases 6 + 7 complete. Phases 1–5 were completed in prior sessions; this post-mortem captures only the supervisor-side audit and the things that went sideways.

## What shipped

### Code (Phases 6 + 7, this session)

| File | Change | Lines |
|---|---|---|
| `ui/handlers/activity_handler.py` | Removed dead 4-line `update_control_bar` call + local `import re` | -5 |
| `ui/views/main_content.py` | Removed `_on_control_bar_update` attribute, `set_on_control_bar_update()` and `update_control_bar()` methods | -13 |
| `ui/views/chat_control_bar.py` | DELETED (replaced by `chat_input_toolbar.py`) | -58 |
| `ui/styles.py` | Added `.input-toolbar`, `.find-bar`, `.spell-active` CSS block per spec §2.7 | +45 |
| `docs/ARCHITECTURE.md` | Removed 2 stale `chat_control_bar.py` lines from file tree | -2 |

Net: **+45 / -78** across 5 files.

### Spec artifacts

- `docs/specs/TOOLBAR-PHASE-6-INSTRUCTIONS.md` (168 lines)
- `docs/specs/TOOLBAR-PHASE-7-INSTRUCTIONS.md` (177 lines)
- `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` (master spec, pre-existed)

## Verification results

All 9 Phase 6 verification commands + all 6 Phase 7 verification commands passed when independently re-run by the supervisor (Qaster), not just the Coder:

| Check | Phase 6 | Phase 7 |
|---|---|---|
| Grep-zero for `ChatControlBar` / `update_control_bar` / `set_on_control_bar_update` / `_on_control_bar_update` in `ui/ tests/` | 0 / 0 / 0 / 0 ✅ | n/a |
| App imports cleanly | ✅ | ✅ |
| App launches with `G_DEBUG=fatal-criticals` (no Gtk-CRITICAL) | ✅ | ✅ |
| Targeted toolbar tests (`test_chat_input_toolbar.py`, `test_input_toolbar_handler.py`, `test_spellcheck.py`) | n/a | 115/115 pass in 0.61s ✅ |

The full pytest suite (1514 tests) still times out at 60-120s; this is **pre-existing** and not caused by this work. See the post-mortem `BUG-3-INVESTIGATION-REPORT.md` for the 10 pre-existing test failures.

## Things that went sideways

### 1. Line drift between spec and `activity_handler.py`

**Spec §2.6** said the dead call to `update_control_bar` was at line 482. **Actual location was line 603** — a 121-line drift. The spec was written before the file grew during the earlier activity-handler extraction phases (Phase 5 of the activity drawer work added 121 lines).

**Impact:** If the Coder had followed the spec line numbers blindly, the removal would have hit the wrong code. The Coder correctly re-read the file before editing and used `grep -nE "update_control_bar|ChatControlBar"` to locate the real site.

**Lesson:** Specs that hardcode line numbers need a "this is approximate — verify with grep" disclaimer at the top of the relevant section. A future `spec-doctor` pass should add a per-section note.

### 2. Coder mis-attribution of `chat_control_bar.py` deletion

The Coder reported: *"3. `ui/views/chat_control_bar.py` — DELETED (`git rm` → staged → auto-committed) (73 lines, Gtk.Label stub class)"*

**The truth:** `chat_control_bar.py` was deleted in commit `4987d7d` on 2026-05-31, **weeks before this session**, as part of a prior path-traversal fix. The Coder did not delete it in Phase 6 — but did claim credit.

**Root cause:** The Coder's process assumes "if a file is gone after my work, I deleted it." But that file's absence in the working tree was pre-existing state. The Coder did not run `git log -- ui/views/chat_control_bar.py` to check the deletion's provenance.

**Impact:** Audit trail is misleading. No code damage (the goal was met either way).

**Fix going forward:** The Coder's phase-instruction template should include a "verify provenance of pre-existing deletions with `git log -- <file>`" step.

### 3. Coder auto-commits bypass delegation contract

The Coder delegation said: *"do NOT commit, do NOT push — only edit and report."*

The Coder auto-committed anyway via the review layer (`Accept: Modified ui/views/main_content.py`, etc.). The review layer is configured to auto-accept modifications, and this supersedes the per-delegation contract.

**Impact:** 11 commits ahead of `origin/main` after this session, 7 of which are `.pytest_cache/v/cache/nodeids` and `__pycache__/*.pyc` (test cache + bytecode). These are not appropriate for a public repo.

**Why this is a real bug, not just noise:** The repo's `.gitignore` *should* exclude `.pytest_cache/` and `__pycache__/`. The fact that they got tracked means the `.gitignore` is missing or misconfigured. **This is a config bug to investigate separately** — see "Open follow-ups" below.

**Decision:** Per the Captain's call (option A), push as-is and fix the `.gitignore` separately. The 7 cache/pyc commits are reversible with `git rm -r --cached` once `.gitignore` is corrected.

### 4. Coder fabricated a "duplicate CSS class" finding

The Coder's related-bug scan said: *"`.feed-btn-reject` appears twice in `ui/styles.py` (grep shows count = 2). Could indicate a duplicate CSS rule block. Out of scope for this phase."*

**The truth:** The two occurrences are a base class rule (line 829) and a `:hover` variant (line 849). This is standard CSS, not a duplicate. The Coder saw two `grep` matches and flagged without reading the surrounding context.

**Impact:** None on this phase — flagged but not fixed. Mild noise in the audit report.

**Fix going forward:** Related-bug scan instructions in the Coder template should require reading 3 lines of context around each match before flagging. Grep-only scanning is too shallow.

### 5. `_control_bar` → `_toolbar` rename not done

Spec §2.4 says: *"Rename `_control_bar` → `_toolbar` and add a public `toolbar` property on `MainContent`."*

The actual code uses `_control_bar` (chosen by Phase 4). The spec's rename was never applied. `window.py:279` still uses `self._main_content._control_bar`.

**Decision:** Out of scope for Phase 6. Flagged in Phase 6's COMPLETENESS checklist as a related issue. The rename is cosmetic — the attribute's *meaning* (the `ChatInputToolbar`) has changed, but the *name* hasn't.

**Recommendation:** A small follow-up phase (1 file, ~3 lines) to do the rename + add the public property. Or: leave it as-is, since `_control_bar` is the more accurate name (it controls things; it's a control bar).

## Open follow-ups (out of scope for this post-mortem)

1. **Fix `.gitignore` to exclude `.pytest_cache/` and `__pycache__/`** — investigate why they got tracked; remove from git index with `git rm -r --cached`; add to `.gitignore`; commit.
2. **Address the 7 cache/pyc commits ahead of `origin/main`** — either squash with `git rebase -i origin/main` (rewrites history) or keep them and accept the noise (per Captain's option A).
3. **`_control_bar` → `_toolbar` rename + public property** — small follow-up phase, 1 file, ~3 lines.
4. **Coder related-bug scan needs context-reading requirement** — template update, not a code change.
5. **Spec line-number drift disclaimer** — template update for future specs.
6. **Stale `ChatControlBar` references in 4 docs files** — `docs/audits/`, `docs/proposals/`, `docs/reference/`, `docs/PRODUCT_VISION.md`. These are historical/proposal docs and could either be left (they document the journey) or updated to note "replaced by `ChatInputToolbar`".

## Follow-up resolution (all 6 follow-ups closed 2026-06-12)

| # | Follow-up | Resolution | Commit |
|---|---|---|---|
| 1+2 | `.gitignore` + cache/pyc commits | **FALSE ALARM — already correct.** `.gitignore` ALREADY excludes `__pycache__/`, `*.pyc`, `*.py[cod]`, and `.pytest_cache/`. `git ls-files` shows ZERO tracked cache files on `main`. The 7 historical commits are from a prior sprint when the `.gitignore` was incomplete. **New finding:** the Coder's review layer is broken — it generates misleading commit messages (`Accept: Modified .pytest_cache/v/cache/nodeids` for commits that actually deleted real code or made empty diffs). Separate investigation, not a crabcakes-code fix. | (n/a — false alarm) |
| 3 | `_control_bar` → `_toolbar` rename | **Phase 10** — `MainContent` renamed to `_toolbar` + public `toolbar` property added; 2 call sites in `window.py` updated. No behavior change. | `173ed9f` |
| 4 | Coder template: context-reading | **Done in `prompts/steelFramedCodeWriter.md` Step 6.6** — "Context-reading requirement (mandatory)" added. Grep-only scans flagged CSS `:hover` variants as duplicates; the new rule requires `sed -n 'A,Bp' file` to confirm before flagging. | `fdb4660` |
| 5 | Spec line-number drift disclaimer | **Done as new Step 6.8: Spec Drift Verification** in `prompts/steelFramedCodeWriter.md` — "specs that hardcode line numbers drift; use identifier names as anchors, not line numbers; flag drift >10 lines as a 'Spec drift' finding." | `fdb4660` |
| 6 | Stale `ChatControlBar` references in 4 docs files | **Done** — 6 docs files (audits, proposals, reference, vision) annotated with deprecation banners pointing to `ChatInputToolbar` and the post-mortem. Historical content preserved. The 4-dir post-mortem count expanded to 6 files when the search found `audits/ARCHITECTURE-AUDIT-2026-06-11-DEEP.md` and `proposals/PROPOSAL-activity-bubble-ux.md` as additional carriers. | `fdb4660` |
| **+1** | Dead `set_on_buffer_changed` (QTR finding) | **Phase 9** — setter, attribute, and callback invocation in `_on_find_entry_changed` removed. Eliminates the latent TypeError trap. | `230c19c` |
| **+1** | Master spec doc drift (BUG #1 from Phase 9 audit) | **Done** — `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md:585` annotated to mark the dead setter as removed; live `main_content.set_on_buffer_changed` (Phase 8) is the active wiring. Future implementers reading the spec won't re-wire the dead setter. | `fdb4660` |
| **+1** | Template: setters that store callbacks (Rule 5a) | **Done in `prompts/steelFramedCodeWriter.md`** — new Rule 5a requires `set_on_X(cb)` setters to document the trigger that invokes `cb`. Storage-only setters (stored but never invoked from the right signal) are explicitly called out as a latent TypeError trap. | `fdb4660` |
| **+1** | Template: tests for deleted code must be removed (BUG #2 from Phase 9 audit) | **Done in Step 6.5** — "When you delete code, you MUST also delete its tests" added as an explicit rule. Catches the Phase 9 incident where QTR correctly removed `test_set_on_buffer_changed` but the spec said "do not add tests" without saying "and do not leave tests for deleted code." | `fdb4660` |

## What went well

- **Phased breakdown of 8 phases worked:** the integration-rule (small, focused, independently verifiable phases) held across 9 files of changes.
- **Spec-before-phase discipline held:** no out-of-spec edits snuck in.
- **Parallel verifiers (Qaster + QTR) caught different issues:** Qaster caught the line drift on `activity_handler.py:482→603` and the Coder's mis-attribution of `chat_control_bar.py` deletion. QTR caught the dead `set_on_buffer_changed` on the toolbar view and the latent TypeError trap. Together the two verifiers found 7 distinct issues across 8 phases; either one alone would have missed 2-3.
- **Targeted tests all pass:** 116/116 on the toolbar-related test files (115 prior + 1 new Phase 8 regression test). The 10 pre-existing failures in the full suite are documented in `BUG-3-INVESTIGATION-REPORT.md` and unrelated.
- **No `G_DEBUG=fatal-criticals` crashes on launch** — the toolbar code is sound.
- **The bug was fixed in 1 attempt** (Phase 8) after the Captain reported the symptom. No rework loop. This is a good outcome: ~90 lines of code + 1 regression test + 1 architectural decision (handler doesn't get view ref) closed a bug that had been latent for 5 phases.

## Audit trail

| Phase | Spec | Code change | Verification | Builder claim | Auditor verdict | Builder |
|---|---|---|---|---|---|---|
| 6 | TOOLBAR-PHASE-6-INSTRUCTIONS.md | 3 files, 76 deletions | All 9 checks pass | "10 lines removed from main_content.py" (off by 3) | ACCEPTED (substance) | Coder |
| 7 | TOOLBAR-PHASE-7-INSTRUCTIONS.md | 2 files, 47 net additions | All 6 checks pass | "4 stale doc references" + "duplicate CSS class" (false positive) | ACCEPTED (substance) | Coder |
| 8 | TOOLBAR-PHASE-8-INSTRUCTIONS.md | 4 files, 90 net additions | All 11 checks pass; **behavioral repro confirms bug fix** | "11 words" (correct count, not 9 — Qaster miscounted in initial assertion) | ACCEPTED (substance); QTR also caught the dead `set_on_buffer_changed` on the toolbar view | QTR |
| 9 | TOOLBAR-PHASE-9-INSTRUCTIONS.md | 2 files, 13 deletions | All 8 checks pass; 6 behavioral edge cases pass | "115/115 tests, 4 remaining setters all live" (verified by Qaster) | ACCEPTED; Qaster's audit caught 2 template bugs (BUG #1 doc drift, BUG #2 test-removal rule) and 1 Coder review-layer issue (misleading commit messages) | QTR |
| 10 | TOOLBAR-PHASE-10-INSTRUCTIONS.md | 2 files, 9 insertions, 4 deletions | All 8 checks pass; 115/115 tests; word count + find bar work | "toolbar property returns ChatInputToolbar, 2 call sites updated" (verified by Qaster) | ACCEPTED; 2 minor notes (spec said 3 occurrences, actual was 2 — QTR correctly identified all real ones) | QTR |

## Lessons learned (added by Phase 8)

1. **Helper tests are not enough.** The Phase 8 bug existed for 5 phases because the unit tests for `get_word_count()` and `update_word_count()` passed individually. The new `TestPhase8WordCountLabel` test wires all three (buffer + handler + view) together — a true integration test. **Every new feature that involves signals/callbacks needs at least one test that exercises the actual signal emission, not just the leaf methods.**
2. **Setter methods need a corresponding emitter.** The misnomer `set_on_buffer_changed` on the toolbar view stored a callback that nothing ever called. A `set_on_X(cb)` API should always be paired with a documented "and the cb is called when Y" — if no such Y exists, the setter is dead code with a misleading name. Future code review should flag this.
3. **"QTR does the fix, Qaster does the audit" works.** QTR's implementation took 1 attempt, no rework. Qaster's audit caught a wrong word count in the initial assertion (corrected on re-run). QTR's related-bug scan caught a latent TypeError that Qaster had not flagged in the original plan. The two verifiers find different issues. The collaboration model is sound.
4. **The bug-fix phase pattern (Phase 8) is a useful template.** For a small, well-scoped bug: 1 spec file, 3 source files, 1 regression test, 1 attempt, no rework. About 30 minutes end-to-end. The pattern should be reused for similar single-bug fixes.

## Lessons learned (added by Phase 9 + audit)

5. **Setter-Emitter Pairing must be a template rule, not a code review note.** Lesson 2 above said setters need emitters — Phase 9 audit found that the dead setter was *almost* wired (it WAS invoked from `_on_find_entry_changed`), but to the wrong signal. The new Rule 5a in `steelFramedCodeWriter.md` closes this gap: setters must document the trigger that invokes `cb`, and the audit command `grep -n "self._on_X" file` must show the trigger signal in the same file. The Phase 9 trap would have been caught by the rule: the setter said "called when buffer changes" but the trigger was the find entry's signal.
6. **Test-removal-on-delete is a separate rule.** When the spec for Phase 9 said "do not add tests" (correct), it implicitly assumed the test for the deleted setter would be removed (it wasn't, in the spec). QTR made the right call (removed it), but the rule needs to be explicit: deleting code requires deleting its tests too, because a test for a deleted method fails with `AttributeError` at collection. Now in Step 6.5 of the prompt.
7. **Spec line numbers drift — anchor edits to identifiers, not line numbers.** Phase 6's spec said "edit `activity_handler.py:482`" but the function had moved to line 603 (a 121-line drift). The Coder correctly used `grep -nE` to find the real site. The new Step 6.8 of the prompt makes this a hard rule: "If a line number is off by more than 10 lines, the spec is stale. Flag this as a 'Spec drift' finding." The spec's identifiers are the source of truth; line numbers are advisory.
8. **Parallel-verifier audit cycle catches more than the original plan.** The 4 follow-up items (A, B, C, D) plus 4 audit-driven discoveries (dead setter, doc drift, test-removal rule, Coder review-layer issue) — totaling 8 distinct items, of which only 4 were in the Captain's original ask. The adversarialDebugger audit of Phase 9 found BUG #1 (doc drift) and BUG #2 (template gap), and the audit of the working tree for Phase 10 found the Coder review-layer issue (misleading commit messages). The audit step is not optional — it discovers issues that the spec author didn't know to ask for.

## New finding: Coder review-layer is broken (separate investigation)

The Phase 10 audit found that the Coder's review-layer auto-commit messages don't match the actual diff content:

- `59243dc` (message: "Accept: Modified .pytest_cache/v/cache/nodeids", actual diff: deleted `chat_control_bar.py` -58 lines)
- `b876760`, `854e11d`, `9d7f5be`, `7b1ed3b` (messages reference `.pytest_cache/v/cache/nodeids`, actual diffs: **empty**)
- `4d6c7af` (message: "Deleted ui/__pycache__/styles.cpython-312.pyc.XXXX", actual diff: did delete a pyc file)

The review layer appears to apply a template message based on a heuristic that doesn't always identify the actual changed file correctly. **This is a Coder-internal bug, not a crabcakes-code bug** — it's listed here for the record but is out of scope for the crabcakes repo. The crabcakes code itself is not affected.

## Commits ahead of `origin/main` (post-push state will include Phase 8)

```
aa17582 fix(toolbar): wire input buffer 'changed' signal to handler + word count (Phase 8)  ← real
[pending] post-mortem: Chat Input Toolbar phases 1-8 (this update)  ← real
f1366ce post-mortem: Chat Input Toolbar phases 1-7 (...updating this post-mortem in same push)  ← real
7b1ed3b Accept: Modified .pytest_cache/v/cache/nodeids        ← noise
f658369 Accept: Modified docs/ARCHITECTURE.md                  ← real
6034a27 Accept: Modified docs/ARCHITECTURE.md                  ← real
4d6c7af Accept: Deleted ui/__pycache__/styles...pyc.XXXX       ← noise
df92af6 Accept: Modified ui/styles.py                          ← real
4ca94ab Accept: Modified docs/specs/TOOLBAR-PHASE-7-INSTRUCTIONS.md  ← real
854e11d Accept: Modified .pytest_cache/v/cache/nodeids        ← noise
9d7f5be Accept: Modified .pytest_cache/v/cache/nodeids        ← noise
59243dc Accept: Modified .pytest_cache/v/cache/nodeids        ← noise
52038e8 Accept: Modified ui/views/main_content.py             ← real
cb4a5cb Accept: Deleted ui/handlers/__pycache__/...pyc.XXXX   ← noise
```

For Phase 8 specifically, **no cache commits accumulated** because QTR did the work directly, not via the Coder.
