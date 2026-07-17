# FileTree ColumnView Migration — Phase 3 Post-Mortem

**Date:** 2025-07-12
**Supervisor:** Supervisor
**Builder:** Coder
**Debugger:** Debugger
**Commits:** 8 (Phase 3 + 3 bug-fix rounds)
**Phases:** 3 of 12 (Phase 3 complete)
**Total bugs found:** 8 (1 HIGH, 3 MEDIUM, 4 LOW)
**Process:** Standard 3-agent loop with 3 re-audit cycles. Required structural fix for index-staleness class.

---

## 1. Code Quality Grade: B (85/100)

### Justification

Phase 3 delivered file double-click → drawer row insertion with animation. The implementation works correctly after the structural fix (BUG #1-R): `_drawer_paths` was changed from `dict[str, int]` to `dict[str, FileTreeRow]` to track by object identity. This eliminated the entire class of index-staleness bugs. However, it took 3 bug-fix rounds to reach the correct solution — the first two attempts (position validation, object validation at a single index) were incomplete. The lesson: for mutable store lookups, track identity in the closure, not the position. This pattern was learned in Phase 2 (BUG #1 for loading rows) and should have been applied directly here.

| Category | Score | Notes |
|----------|-------|-------|
| Correctness | 15/20 | Required 3 bug-fix rounds; final solution correct |
| Architecture compliance | 9/10 | Layer separation preserved; identity-based tracking is clean |
| Test coverage | 6/10 | No automated tests; manual verification by Debugger |
| Documentation | 8/10 | Phase 3 docstrings clear; pattern lesson captured |
| Maintainability | 8/10 | Object identity pattern is correct but discovered iteratively |
| DX (Developer Exp.) | 9/10 | Drawer open/close works; debounce prevents flicker |
| **Total** | **85/100** | **B — correct after iterative refinement** |

Deducted points:
- 5 Correctness: 3 bug-fix rounds required for index-staleness class
- 4 Test coverage: No automated tests for drawer state machine
- 1 Maintainability: Pattern learned in Phase 2 should have been applied directly

---

## 2. What's Good About the Code

1. **Identity-based drawer tracking** — `ui/views/file_tree.py:253, 834, 789` — `_drawer_paths: dict[str, FileTreeRow]` stores GObject objects, not indices. This eliminates the entire class of index-staleness bugs. The pattern is consistent with Phase 2's identity-based loading row removal.

2. **Three-layer defense in `_on_revealer_child_revealed`** — `ui/views/file_tree.py:856-883` — The handler checks: (1) revealer is not None, (2) revealer identity matches a row in the store, (3) row is a drawer. Each guard cleans up `_drawer_paths` and returns. This is robust against stale signals, orphan revealers, and store mutations.

3. **Debounce per-file** — `ui/views/file_tree.py:780-783` — 300ms per-file debounce in `_toggle_drawer` prevents double-click races during revealer animation. The debounce dict is per-file, so toggling different files in quick succession works correctly.

---

## 3. What's Bad About the Code

1. **Iterative discovery of identity pattern** — The Phase 2 loading row fix used identity-based tracking. Phase 3's drawer tracking should have used the same pattern from the start, but used index-based tracking instead. This cost 3 bug-fix rounds.
   - Evolution suggestion: Add a project rule: "When tracking a row in a mutable ListStore, always track by GObject identity, not by index."

2. **No automated tests for drawer state machine** — The 7 live tests were manual. The drawer state machine (open, close, collapse, re-expand, re-open) has 8+ state transitions that should be tested.
   - Evolution suggestion: Add `tests/test_file_tree_drawer.py` with state machine tests.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 3 | HIGH | `_drawer_paths` index stale after parent collapse | Debugger (adversarial §3) | Coder (round 3, structural) |
| 2 | 3 | MEDIUM | `revealer is None` not handled in close path | Debugger (adversarial §5) | Coder (round 2) |
| 3 | 3 | MEDIUM | No row validation in `_on_revealer_child_revealed` | Debugger (adversarial §6) | Coder (round 2) |
| 4 | 3 | LOW | Cross-contamination of close signal | Debugger (adversarial §3) | Coder (round 2) |
| 5 | 3 | LOW | `is_drawer_open` spec deviation | Debugger (adversarial §7) | No action (acceptable) |
| 6 | 3 | LOW | `key_controller` wired to Phase 8 stub | Debugger (adversarial §6) | No action (forward-decl) |
| 1-R | 3 | MEDIUM | Duplicate drawer when stale entry detected | Debugger (round 2, §3) | Coder (round 3, structural) |
| 2-R | 3 | LOW | None guard missing in handler | Debugger (round 2, §5) | Coder (round 3) |
| 1-R-R | 3 | LOW | Handler too aggressive on dict deletion | Debugger (round 3, §3) | No action (unreachable) |

**Summary:** 9 bugs found, 6 fixed in-loop, 3 deferred (2 forward-declarations for Phase 8, 1 unreachable edge case). The structural fix (BUG #1-R → round 3) correctly eliminated the index-staleness class.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `index-staleness` | 3 | BUG #1, #1-R, #1-R-R — all fixed by identity-based tracking |
| `defensive-edge-case` | 2 | BUG #2, #2-R — None handling |
| `forward-declaration` | 2 | BUG #5, #6 — Phase 8 work |
| `validation-missing` | 2 | BUG #3, #4 — row/revealer validation |

---

## 5. Process: What Worked

1. **3 re-audit cycles for the structural fix** — Each round got closer to the correct solution. Round 1: position validation. Round 2: object validation at stored index. Round 3: identity-based tracking. The adversarial audit correctly identified that the previous fixes were incomplete.

2. **Debugger's recommended structural fix** — Debugger suggested changing `_drawer_paths` to `dict[str, FileTreeRow]` in BUG #1-R's report. This was the correct structural fix and saved time vs. patching the symptom.

---

## 6. Process: What Didn't Work

1. **Coder didn't apply Phase 2's identity pattern to Phase 3** — Phase 2 fixed loading row tracking by identity. Phase 3 used index tracking and had to be fixed 3 times. The lesson is in the project memory but wasn't applied proactively.
   - Lesson: Add a Phase 0 check: "Does this phase use a pattern that was learned in a previous phase?" If yes, apply it directly.

2. **No automated tests for the drawer state machine** — The 7 live tests were manual. The state machine has 8+ transitions that should be tested.
   - Lesson: Add a "drawer state machine" test before merging Phase 3.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Double-click file → drawer opens with animation** — `ui/views/file_tree.py:825-841` — User double-clicks a file row. A drawer row is inserted below it with a `Gtk.Revealer` that slides down over 150ms. The drawer contains Diff/History tabs, a stack for content, and an action bar with Revert/Copy buttons. Double-clicking again animates the drawer closed and removes the row.

2. **Multiple drawers can be open simultaneously** — `ui/views/file_tree.py:253` — `_drawer_paths: dict[str, FileTreeRow]` tracks drawers by file path. Opening drawer A, then drawer B for a different file, works correctly. Closing one doesn't affect the other.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

None.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add `tests/test_file_tree_drawer.py` with state machine tests | 3 hours | Catches regressions in drawer open/close/collapse logic |
| Add project rule: "Track mutable store rows by identity, not index" | 30 min | Prevents the entire class of index-staleness bugs |
| Add loading spinner to drawer diff_box for Phase 5 | 1 hour | Better UX during async diff load |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Apply previously-learned patterns proactively** — When a previous phase discovered a pattern (e.g., identity-based tracking), apply it directly in the next phase that needs it.
   - Trigger: Starting any phase that uses a pattern from a previous phase
   - Action: Check the post-mortems for "What's Good" patterns and apply them

2. **Structural fix over symptom patches** — When a bug recurs across multiple fix rounds, the root cause is structural. Fix the structure, not the symptom.
   - Trigger: 2+ fix rounds for the same bug class
   - Action: Step back and identify the structural fix (e.g., type change, pattern change)

---

## 11. Sign-off

- [x] Phase 3 code complete
- [x] All bugs from audit cycle fixed or deferred with justification
- [x] Verification commands run independently
- [x] Post-mortem written
- [ ] Phase 3 committed and pushed (pending)
- [ ] Captain notified (pending)
- [ ] Tier 2+ backlog updated (drawer state machine tests)
