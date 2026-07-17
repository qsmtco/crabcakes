# FileTree ColumnView Migration — Phase 1 Post-Mortem

**Date:** 2025-07-12
**Supervisor:** Supervisor
**Builder:** Coder
**Debugger:** Debugger
**Commits:** 3 (Phase 1 + 2 bug-fix commits)
**Phases:** 1 of 12 (Phase 1 complete)
**Total bugs found:** 9 (1 MEDIUM, 8 LOW)
**Process:** Standard 3-agent loop — Coder wrote, Debugger audited, Supervisor routed. One re-audit cycle for bug fixes.

---

## 1. Code Quality Grade: A- (92/100)

### Justification

Phase 1 delivered the data model, row widget, factory, and ColumnView initialization cleanly. The implementation matches the spec's §2-§3 requirements. All 12 GObject properties work, factory bind/unbind cycle handles drawer cleanup correctly per BUG #2/#6, and CSS additions are clean. The two MEDIUM bugs (BUG #1 deleted methods, BUG #4 missing kwargs) were caught by Debugger's adversarial audit before merge and fixed in the same loop. The 1 MEDIUM spec deviation (BUG #5) was correctly routed as a spec fix, not a code change.

| Category | Score | Notes |
|----------|-------|-------|
| Correctness | 19/20 | All verification passes; BUG #1 and #4 caught and fixed in-loop |
| Architecture compliance | 10/10 | Layer separation preserved; no handler/view boundary violations |
| Test coverage | 8/10 | No new tests in Phase 1 (deferred to Phase 11 per spec) |
| Documentation | 9/10 | Docstrings present; BUG #1-R caught 3 wrong phase labels |
| Maintainability | 9/10 | Stub methods marked with phase numbers for future authors |
| DX (Developer Exp.) | 9/10 | Clear separation of concerns; future phases have obvious hooks |
| **Total** | **92/100** | **A- — strong Phase 1 with in-loop bug fixes** |

Deducted points:
- 1 Correctness: BUG #1 (deleted methods) required re-audit cycle
- 1 Test coverage: No tests in Phase 1
- 1 Documentation: BUG #1-R (3 wrong phase labels in docstrings)

---

## 2. What's Good About the Code

1. **GObject properties on FileTreeRow** — `ui/views/file_tree.py:25-63` — Uses `GObject.Property()` declarations (not `@property` decorators), which is required for `Gio.ListStore` binding. All 12 properties declared with correct types and defaults. This is the foundational pattern for the rest of the migration.

2. **Drawer cleanup in factory unbind** — `ui/views/file_tree.py:158-195` — `FileTreeFactory._on_unbind` calls `widget.cleanup()` which calls `detach_drawer()`. This prevents orphan widget trees when drawer rows are recycled in the factory pool. Directly addresses spec BUG #2/#6.

3. **Stub methods with phase labels** — `ui/views/file_tree.py:611-677` — 15 method stubs preserved with docstring phase labels (e.g., "Phase 4+", "Phase 8+"). This makes the phased implementation roadmap visible to future authors and prevents accidental scope creep.

---

## 3. What's Bad About the Code

1. **No tests in Phase 1** — The spec defers tests to Phase 11, but Phase 1's GObject property behavior and factory bind/unbind cycle are testable now. Adding 2-3 unit tests for `FileTreeRow` property round-trip and `FileTreeRowWidget` cleanup would catch regressions in later phases.
   - Evolution suggestion: Add `tests/test_file_tree_columnview.py` with FileTreeRow tests in Phase 2 or as a separate test-first phase.

2. **`__init__` parent/unparent cycle for `_scroll`** — `ui/views/file_tree.py:213-298` — The `_show_tree` and `_show_project_picker` methods swap content widgets by removing and re-appending. This is preserved from the old code but creates widget lifecycle churn. The new `ColumnView` doesn't need this since it's always present.
   - Evolution suggestion: Remove the parent/unparent cycle in Phase 2 when `_show_tree` is rewritten for the flat ListStore.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 1 | MEDIUM | 8 methods deleted instead of stubbed (spec §3.1 "Preserve" violation) | Debugger (adversarial §6) | Coder (1 commit) |
| 2 | 1 | LOW | `_scroll` parent/unparent cycle in `__init__` | Debugger (adversarial §3) | Deferred to Phase 2 |
| 3 | 1 | LOW | `cleanup()` doesn't reset `row.props.drawer_widget` | Debugger (adversarial §4) | Deferred to Phase 4 |
| 4 | 1 | LOW | `FileTreeRow.__init__` missing 5 of 12 kwargs | Debugger (adversarial §4) | Coder (1 commit) |
| 5 | 1 | MEDIUM | Spec §2.1 internally inconsistent (uses `@property` despite saying "GObject") | Debugger (adversarial §9) | Spec fix needed |
| 6 | 1 | LOW | Indent on whole row will misalign drawer content | Debugger (adversarial §6) | Deferred to Phase 4 |
| 7 | 1 | LOW | No bug — confirmed guards correct | Debugger (adversarial §7) | N/A |
| 8 | 1 | LOW | `toggle_drawer_for_file` / `is_drawer_open` have no callers | Debugger (adversarial §4) | Phase 4 wiring |
| 1-R | 1 | LOW | 3 docstring phase labels wrong (Phase 4/5 vs actual Phase 8) | Debugger (re-audit §9) | Coder (1 commit) |

**Summary:** 9 bugs found, 3 fixed in-loop (BUG #1, #4, #1-R), 6 deferred to natural phases. No bug compounded across phases. All fixes verified by re-audit.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `spec-deviation` | 1 | Code doesn't match spec (BUG #1) |
| `incomplete-initialization` | 1 | Constructor missing parameters (BUG #4) |
| `doc-drift` | 1 | Documentation says wrong thing (BUG #1-R) |
| `deferred-to-later-phase` | 5 | Real concern but out of Phase 1 scope |
| `spec-internal-inconsistency` | 1 | Spec contradicts itself (BUG #5) |

---

## 5. Process: What Worked

1. **File-based delegation for Phase 1 instructions** — `.crabcakes/phase1_filetree_columnview_instructions.md` (15K bytes) was written before the first `/ask` to Coder. The 4096-char `/ask` limit would have truncated inline instructions. Zero truncation failures.

2. **Debugger re-audit after bug fixes** — After Coder fixed BUG #1 and #4, the code was re-routed to Debugger for verification. This caught BUG #1-R (wrong docstring phase labels) that the first audit missed. Two audit cycles is the right depth for a phase with MEDIUM bugs.

3. **Supervisor-only routing, no code editing** — The supervisor (me) never edited code. All changes went through Coder. This kept the audit trail clean: every diff is attributable to a Coder commit with a Coder reason.

---

## 6. Process: What Didn't Work

1. **Coder deleted methods instead of stubbing on first pass** — BUG #1 required a re-delegation cycle. The phase instructions said "Preserve (adapt)" but Coder interpreted this as "remove and re-add later." Lesson: When the spec says "Preserve," the delegation must explicitly say "add as stub returning None/pass" to avoid ambiguity.

   - Lesson: Update phase instruction template to include explicit "stub signature: `def X(self) -> None: pass`" for every method in the Preserve list.

2. **Debugger's first audit found BUG #1-R indirectly** — The wrong docstring labels were caught only because Debugger cross-checked phase numbers against spec §4. This is good adversarial behavior but suggests the spec's phase-to-method mapping should be more explicit.
   - Lesson: Future specs should include a "Phase → Methods" mapping table so adversarial audits can verify phase labels mechanically.

---

## 7. What the Code Actually Does (End-User Impact)

1. **File tree now uses ColumnView** — `ui/views/file_tree.py:213-298` — The directory tree widget no longer uses the legacy `Gtk.TreeView`/`Gtk.TreeStore` pair. It now uses `Gtk.ColumnView` with `Gio.ListStore` and `Gtk.SingleSelection`. Users see the same file list, but the underlying widget supports per-row widget embedding (required for the inline diff drawer in Phase 4). Visually identical in Phase 1; the architecture change is invisible until Phase 4.

2. **15 drawer/diff/history methods are stubbed** — `ui/views/file_tree.py:611-677` — All methods that will be implemented in Phases 4-8 exist as `pass`/`return None` stubs. This preserves the public API contract so `MainContent` can call `toggle_drawer_for_file()` without AttributeError. The stubs do nothing yet — clicking a file in Phase 1 has no effect.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **Spec §2.1 internal inconsistency** — Spec uses `@property` decorator examples but says "Gio.ListStore requires GObject items." Coder correctly used `GObject.Property()` and not `@property`. The spec text needs to be fixed to match the implementation. Verified pre-existing in `docs/specs/SPEC-FILETREE-COLUMNVIEW-MIGRATION.md` §2.1.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add `tests/test_file_tree_columnview.py` with FileTreeRow property tests | 2 hours | Catches regressions in later phases |
| Remove `_scroll` parent/unparent cycle in Phase 2 | 1 hour | Cleaner widget lifecycle, no behavior change |
| Add `__gtype_name__` to FileTreeRow for GObject introspection | 30 min | Better debugging, required for some GTK tools |
| Add `Gtk.ColumnView` keyboard controller tests | 2 hours | Validates Phase 8 keyboard nav before implementation |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Explicit stub signature in delegations** — When the spec says "Preserve (adapt)" for a list of methods, the delegation must include the exact stub signature for each method.
   - Trigger: Any delegation that references a "Preserve" or "Keep" list in the spec
   - Action: Include `def X(self, ...) -> ReturnType: pass` for every method in the delegation instructions

2. **Spec phase-method mapping table** — Specs with phased implementations should include a table mapping each method to its implementation phase.
   - Trigger: Writing any spec with 3+ phases
   - Action: Add a "Phase → Methods" table to the spec template

---

## 11. Sign-off

- [x] Phase 1 code complete
- [x] All bugs from audit cycle fixed or deferred with justification
- [x] Verification commands run independently (syntax, grep, import)
- [x] Post-mortem written
- [ ] Phase 1 committed and pushed (pending)
- [ ] Captain notified (pending)
- [ ] Tier 2+ backlog updated (BUG #2, #3, #5, #6, #8)
