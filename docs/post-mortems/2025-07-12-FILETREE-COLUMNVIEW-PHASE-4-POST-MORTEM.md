# FileTree ColumnView Migration — Phase 4 Post-Mortem

**Date:** 2025-07-12
**Supervisor:** Supervisor
**Builder:** Coder
**Debugger:** Debugger
**Commits:** 5 (Phase 4 + 1 bug-fix round)
**Phases:** 4 of 12 (Phase 4 complete)
**Total bugs found:** 5 (2 MEDIUM, 3 LOW)
**Process:** Standard 3-agent loop with 1 re-audit cycle. BUG #2 (re-open spinner) was the critical fix.

---

## 1. Code Quality Grade: B+ (88/100)

### Justification

Phase 4 delivered the Diff tab content with background loading, error handling, and binary file detection. The implementation correctly handles the happy path (modified file → diff renders) and edge cases (no changes, binary file, git error). The critical BUG #2 (re-open shows permanent spinner) was caught by Debugger's adversarial audit and fixed in one round. BUG #1 (binary detection) was fixed with an extension-based check that covers 50+ common cases. One MEDIUM bug was skipped with justification (BUG #5 used the correct API). The Phase 1-3 regression suite passes.

| Category | Score | Notes |
|----------|-------|-------|
| Correctness | 17/20 | 1 bug-fix round; all critical bugs resolved |
| Architecture compliance | 10/10 | Layer separation preserved; lazy import for ReviewState |
| Test coverage | 7/10 | No automated tests; manual verification by Debugger |
| Documentation | 9/10 | Comments clear; binary limitation documented |
| Maintainability | 9/10 | Extension-based check is simple and extensible |
| DX (Developer Exp.) | 9/10 | Diff loads correctly; error messages are clear |
| **Total** | **88/100** | **B+ — strong with 1 critical bug caught in audit** |

Deducted points:
- 3 Correctness: BUG #2 (re-open spinner) was a common user action
- 3 Test coverage: No automated tests for diff loading
- 1 Documentation: Binary limitation not documented in user-facing help

---

## 2. What's Good About the Code

1. **`_loaded_drawers` cleanup on close** — `ui/views/file_tree.py:888` — The discard in `_on_revealer_child_revealed` ensures that re-opening a drawer triggers a fresh diff load. This is a critical fix for the common user workflow.

2. **Extension-based binary detection** — `ui/views/file_tree.py:911-930` — `_BINARY_EXTENSIONS` frozenset (50+ entries) + `_is_binary_path()` static method provides fast, reliable binary file detection without needing git's `--numstat` output. Covers common cases (images, archives, compiled files).

3. **Drawer_box identity check in `_on_drawer_diff_loaded`** — `ui/views/file_tree.py:960-967` — The handler verifies that the current drawer's `drawer_widget.get_child()` matches the `drawer_box` passed in the closure. This prevents stale callbacks from populating orphaned widgets when a drawer is closed and re-opened quickly.

---

## 3. What's Bad About the Code

1. **Binary files without extensions are not detected** — Files like `Makefile`, `LICENSE`, `Dockerfile` with binary content will show garbled diffs. The extension-based check can't handle these.
   - Evolution suggestion: Add content-based detection (check for null bytes in the first N bytes of the file) or use `git diff --numstat` to detect binary files (`-` `-` in output means binary).

2. **No automated tests for diff loading** — The 6 live tests were manual. The diff loading has 8+ state transitions (loading, success, error, no changes, binary, stale, etc.) that should be tested.
   - Evolution suggestion: Add `tests/test_file_tree_diff.py` with mocked git results.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | 4 | MEDIUM | Binary file detection doesn't work (parse_diff only checks "Binary files differ" string) | Debugger (adversarial §1) | Coder (extension check) |
| 2 | 4 | MEDIUM | Re-opening drawer shows permanent spinner (`_loaded_drawers` never cleared) | Debugger (adversarial §4) | Coder (discard on close) |
| 3 | 4 | LOW | Stale drawer_box in `_on_drawer_diff_loaded` callback | Debugger (adversarial §3) | Coder (identity check) |
| 4 | 4 | LOW | `FakeResult` duck-typing is fragile | Debugger (adversarial §6) | Coder (GitResult) |
| 5 | 4 | LOW | `_project_name` consistency in `_load_current_diff` | Debugger (adversarial §3) | Coder (justified skip) |

**Summary:** 5 bugs found, 4 fixed in-loop, 1 justified skip. BUG #2 was the most critical (common user action broken). No bug compounded across phases.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `state-not-cleared` | 1 | BUG #2 — `_loaded_drawers` never cleared on close |
| `detection-incomplete` | 1 | BUG #1 — extension-based misses no-extension binaries |
| `stale-closure` | 1 | BUG #3 — drawer_box identity not validated |
| `fragile-duck-typing` | 1 | BUG #4 — FakeResult should be real type |

---

## 5. Process: What Worked

1. **1 re-audit cycle caught the critical BUG #2** — Re-opening a drawer is a common user action. Without the re-audit, this would have been merged and users would have seen permanent spinners. The adversarial audit's "weirdest user" probe caught it.

2. **Debugger's justified skip for BUG #5** — Debugger correctly identified that BUG #5 was not a bug (the API uses `project_name`). Coder accepted the skip. This avoided unnecessary code changes.

---

## 6. Process: What Didn't Work

1. **No automated tests for the common re-open workflow** — The 6 live tests were manual. A test that opens+closes+reopens a drawer would have caught BUG #2 immediately.
   - Lesson: Add a "drawer lifecycle" test before merging Phase 4.

---

## 7. What the Code Actually Does (End-User Impact)

1. **Diff tab shows working-tree diff for modified files** — `ui/views/file_tree.py:933-993` — When the user double-clicks a modified file, the diff loads on a background thread and renders in the Diff tab. Unmodified files show "No changes to this file." Binary files (by extension) show "Binary file — not shown". Git errors show an error message.

2. **Re-opening a drawer reloads the diff** — `ui/views/file_tree.py:888` — Closing a drawer discards the `_loaded_drawers` entry. Re-opening triggers a fresh diff load. This ensures the user always sees the current state of the file.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

None.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Add `tests/test_file_tree_diff.py` with mocked git results | 3 hours | Catches regressions in diff loading |
| Add content-based binary detection (null byte check) | 2 hours | Detects binary files without extensions |
| Add "last loaded" timestamp to drawer state | 1 hour | Could show stale diff warnings |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Test the re-open workflow for any cached state** — When caching loaded data with a "loaded once" flag, test that the cache is invalidated on the natural close cycle.
   - Trigger: Any code that uses a "loaded" set/dict
   - Action: Add a test that closes and re-opens the resource, verifying the cache is cleared

---

## 11. Sign-off

- [x] Phase 4 code complete
- [x] All bugs from audit cycle fixed or justified
- [x] Verification commands run independently
- [x] Post-mortem written
- [ ] Phase 4 committed and pushed (pending)
- [ ] Captain notified (pending)
- [ ] Tier 2+ backlog updated (diff loading tests)
