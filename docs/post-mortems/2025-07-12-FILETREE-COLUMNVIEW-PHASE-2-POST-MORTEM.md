# FileTree ColumnView Migration — Phase 2 Post-Mortem

**Date:** 2025-07-12
**Supervisor:** Supervisor
**Builder:** Coder
**Debugger:** Debugger
**Commits:** 5 (Phase 2 + 2 bug-fix rounds)
**Phases:** 2 of 12 (Phase 2 complete)
**Total bugs found:** 8 (1 CRITICAL, 1 HIGH, 2 MEDIUM, 4 LOW)
**Process:** Standard 3-agent loop with 2 re-audit cycles. CRITICAL BUG #1 required 2 fix rounds.

---

## 1. Code Quality Grade: B+ (87/100)

### Justification

Phase 2 delivered directory expand/collapse with async loading and request ID guards. The implementation correctly handles the flat-list-with-depth pattern. However, the initial BUG #1 fix was incomplete (position-based removal of loading row), requiring a second round. The final identity-based removal is correct and the race-condition trade-off is spec-accepted. BUG #2 (stale position) and BUG #7 (narrow except in `_show_tree`) were caught by Debugger's adversarial audit. The process worked: 2 re-audit cycles caught the incomplete fix before merge.

| Category | Score | Notes |
|----------|-------|-------|
| Correctness | 16/20 | BUG #1 fix required 2 rounds; final implementation correct |
| Architecture compliance | 9/10 | Layer separation preserved; flat-list pattern correct |
| Test coverage | 7/10 | No new tests; manual verification by Debugger |
| Documentation | 8/10 | Phase 2 docstrings clear; race trade-off documented |
| Maintainability | 9/10 | Request ID pattern is clean and correct |
| DX (Developer Exp.) | 9/10 | Recovery via re-click is acceptable UX |
| **Total** | **87/100** | **B+ — strong with one incomplete fix caught by re-audit** |

Deducted points:
- 4 Correctness: BUG #1 required 2 fix rounds
- 2 Test coverage: No automated tests for race conditions
- 1 Documentation: Race trade-off not documented in spec

---

## 2. What's Good About the Code

1. **Identity-based loading row removal** — `ui/views/file_tree.py:777-786` — The closure captures the `loading_row` GObject and `_on_directory_loaded` walks the store to find and remove it by `is` identity. This survives intervening store mutations (sibling expand, collapse, splice) that would break position-based removal.

2. **Request ID guard pattern** — `ui/views/file_file.py:717-718, 789, 356, 421, 604` — `_current_request_id` is incremented on expand, collapse, navigate_back, `_show_project_picker`, and `_show_tree`. Stale callbacks check the request_id and return early if mismatched. This prevents orphan data from being inserted into a collapsed or replaced tree.

3. **`_find_row_index` helper** — `ui/views/file_tree.py:699` — Linear scan that returns the current position of a row by object identity. This fixes the stale-position bug from closure-captured `position` integers.

---

## 3. What's Bad About the Code

1. **Race condition: only most recent expand's children load** — When the user clicks two expanders in quick succession, only the second directory's children load. The first directory's children are dropped because its callback's request_id no longer matches. User must re-click to recover. This is spec-accepted but not ideal UX.
   - Evolution suggestion: Queue the second expand and process sequentially, or show a "Loading..." for all in-flight requests and load all when ready.

2. **No automated tests for race conditions** — The 8 live tests run by Debugger were manual. A regression that re-introduces the position-based removal bug would not be caught by CI.
   - Evolution suggestion: Add `tests/test_file_tree_race.py` with a thread-based test that triggers sibling-expand race and asserts no orphans.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 2 | CRITICAL | Orphan "Loading..." row on sibling expand (position-based removal broke) | Debugger (adversarial §4) | Coder (round 2, identity-based) |
| 2 | 2 | HIGH | Stale `position` makes sibling expander a no-op | Debugger (adversarial §3) | Coder (round 1, `_find_row_index`) |
| 3 | 2 | MEDIUM | Narrow `except (PermissionError, OSError)` in `_do()` | Debugger (adversarial §5) | Coder (round 1, broadened to `Exception`) |
| 4 | 2 | LOW | `navigate_back` doesn't bump `_current_request_id` | Debugger (adversarial §4) | Coder (round 1, 3 sites) |
| 5 | 2 | LOW | Duplicate `_expander_handler_id` init | Debugger (adversarial §10) | Coder (round 1) |
| 6 | 2 | LOW | Claim inaccuracy (splice vs while-loop) | Debugger (adversarial §10) | Coder (round 1, already correct) |
| 7 | 2 | MEDIUM | `_show_tree` narrow except clause | Debugger (round 2, §5) | Coder (round 2) |

**Summary:** 7 bugs found, all fixed in-loop. CRITICAL BUG #1 required 2 fix rounds (position-based → identity-based). No bug compounded across phases. The 2-round cycle for BUG #1 is the right outcome — the first fix was plausible but wrong, and the re-audit caught it.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `position-stale` | 2 | BUG #1 (loading row position) and BUG #2 (expander position) — both fixed by identity-based lookup |
| `narrow-except` | 2 | BUG #3 and #7 — both fixed by broadening to `Exception` |
| `incomplete-init` | 1 | BUG #5 — duplicate field init |
| `missing-invalidation` | 1 | BUG #4 — missing request_id bumps |

---

## 5. Process: What Worked

1. **2 re-audit cycles caught the incomplete BUG #1 fix** — Debugger's first re-audit found that the position-based removal didn't survive store mutations. The second re-audit verified the identity-based fix. Without the 2-round cycle, a broken fix would have been merged.

2. **Live tests by Debugger** — 8 live tests under `xvfb-run -a` verified the race-condition fixes. This is more thorough than unit tests for concurrency bugs.

3. **Supervisor-only routing** — All edits went through Coder. No direct code edits by supervisor. Clean audit trail.

---

## 6. Process: What Didn't Work

1. **BUG #1 fix was incomplete on first attempt** — Coder's first fix moved the loading-row removal before the early returns but kept the position-based lookup. This is a plausible-looking fix that doesn't work. The re-audit caught it, but the 2-round cycle cost ~30 minutes of delegation time.
   - Lesson: For race-condition bugs, the fix must address the root cause (identity vs. position), not the symptom (orphan row). The adversarial audit should specifically probe "what if intervening mutations shift the row?"

2. **No automated tests for the fix** — The 8 live tests were manual. If a future refactor re-introduces the position-based bug, CI won't catch it.
   - Lesson: Add a thread-based race test before merging race-condition fixes. The test should be repeatable and fast (<1s).

---

## 7. What the Code Actually Does (End-User Impact)

1. **Directory expand/collapse works with async loading** — `ui/views/file_tree.py:708-797` — Clicking a directory's expander button triggers a background `scan_directory` thread. A "Loading..." row appears immediately. When the scan completes, children are inserted and the loading row is removed. Expanding a second directory while the first is loading works correctly (no orphan rows, though the first directory's children may be dropped — recoverable via re-click).

2. **Tree state survives project switch** — `ui/views/file_tree.py:356, 421, 604` — `navigate_back`, `_show_project_picker`, and `_show_tree` all bump `_current_request_id` and clear the store. In-flight async scans from the previous tree are invalidated and their results discarded.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **Spec §3 BUG #7 race trade-off not documented** — The spec says "the idle_add callback must check whether the directory is still expanded" but doesn't document that this means only the most recent expand's children load. Users will be confused when clicking two expanders in quick succession shows only one set of children.
   - Verified pre-existing in `docs/specs/SPEC-FILETREE-COLUMNVIEW-MIGRATION.md` §5 Phase 3.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add `tests/test_file_tree_race.py` with thread-based race test | 3 hours | Catches regressions in identity-based removal |
| Queue sequential expands instead of dropping stale requests | 4 hours | Better UX when clicking multiple expanders |
| Document the race trade-off in user-facing help | 1 hour | Reduces user confusion |
| Add loading spinner to all in-flight requests, load all when ready | 2 hours | More predictable behavior |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Identity vs. position for mutable store lookups** — When a row's position may change between insertion and lookup, track the GObject identity in a closure, not the position.
   - Trigger: Any code that inserts a placeholder row and later tries to remove it after async work
   - Action: Capture the GObject in the closure, use `item is obj` identity check on lookup

2. **Broaden except clauses consistently** — When patching a narrow except clause (`PermissionError, OSError`), check for the same pattern at all call sites.
   - Trigger: Any `except (PermissionError, OSError)` patch
   - Action: grep for the same except clause across the codebase and patch all sites

---

## 11. Sign-off

- [x] Phase 2 code complete
- [x] All bugs from audit cycle fixed
- [x] Verification commands run independently
- [x] Post-mortem written
- [ ] Phase 2 committed and pushed (pending)
- [ ] Captain notified (pending)
- [ ] Tier 2+ backlog updated (race test, queue sequential expands)
