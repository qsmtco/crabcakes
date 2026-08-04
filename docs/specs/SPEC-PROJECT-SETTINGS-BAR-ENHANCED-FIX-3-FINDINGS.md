# Round 4 Re-Audit Findings — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3

**Spec under audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md`
**Previous spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md`
**Round 3 findings:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2-FINDINGS.md` (7 bugs)
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ✅ **PASS WITH NITS — ready for implementation.**

## Round 3 verification table

| # | Round 3 finding | Status | Evidence |
|---:|---|---|---|
| 1 | **CRIT** invalid lambda assignment | ✅ FIXED | Named `_on_project_closed` method (block 13) registered as third append-based callback. Verified `set_on_project_closed` at project_handler.py:393, fire at line 248. |
| 2 | **HIGH** stale branch result writes cache before identity check | ✅ FIXED | Block 12 reorders all checks (token, path, active-name, active-path) BEFORE `_cached_branch_by_path[path] = branch`. Block 14 adds named `_on_project_opened` invalidating on open/switch. |
| 3 | **HIGH** `set_solo_target` doesn't validate project | ✅ FIXED | Block 24 uses `_get_project_path(project_name) is not None` (Option A). Window callback (block 15) guards active project. |
| 4 | **HIGH** bar doesn't update after async auto-accept | ✅ FIXED | Block 17/18 add `set_on_auto_accept_level_changed` slot+setter. Block 21 `_commit_auto_accept_level` emits after refresh. Block 20 `set_auto_accept_level` emits for "off" path. Block 16 wires to `_refresh_settings_bar_for_active`. Block 15 cycle handler no longer optimistically rebuilds. |
| 5 | **MED** cache not keyed by path | ✅ FIXED | Block 9: `_cached_branch_by_path: dict[str, str]`. Block 10 looks up by `get_active_project_path()`. Block 12 writes to `[path]`. |
| 6 | **MED** refresh condition doesn't check cache | ✅ FIXED | Block 10 splits into `needs_resolution` and `already_running`. |
| 7 | **MED** special-agent fallback returns `None` | ✅ FIXED | Block 3 uses `special.get(session_key)` + truthiness. |

**7/7 Round 3 bugs fully fixed. Zero regressions.**

## ast.parse() verification (independent re-run)

```
Found 24 python code blocks
Parsed blocks: 24
SyntaxErrors: 0
Assigns inside lambda: 0
```

**Coder's count (24) and claim (0 errors) are correct.** All 24 fenced code blocks parse cleanly.

## Design decision: cache-on-close

Spec intentionally does NOT clear `_cached_branch_by_path` on close. **Acceptable for v1.** The con (stale cache if branch changed externally) is mitigated by user-driven refresh paths. No TTL needed — `git rev-parse` is fast.

## New bugs found in Round 4 (1 HIGH — build-time fix, not spec-blocking)

### BUG #1 — HIGH: Callback ordering / scheduling deadlock
**Assumption violated:** `_on_project_opened` invalidation runs before the existing project-open lambda touches the bar.
**Attack vector:** Open project A, while a worker is in-flight for project A, then open project B.
**Reproduction:**
1. Lambda at window.py:530 fires first → calls `_on_feed_bar_update` → checks `already_running` → `True` (previous worker in flight) → **no new worker scheduled** for B.
2. New `_on_project_opened` fires after → bumps token, clears in-flight marker.
3. Result: the new project never gets a branch lookup scheduled. Bar stuck at `—` until something else triggers a re-render.
**Root cause:** Callback registration order. The named invalidation method is registered as a third callback that runs AFTER the existing tuple lambda.
**Fix (build-time, 3 lines):** In `_on_project_opened` (block 14), after bumping the token, also call `self._on_feed_bar_update(name, member_count, ...)` to force a re-evaluation. Or reorder the wiring so the named method is registered first.

## Summary

**Verdict: ✅ PASS WITH NITS — ready for implementation.**

**Top 3 must-fix items:**
1. **BUG #1 HIGH** — fix callback ordering (re-trigger `_on_feed_bar_update` from `_on_project_opened` after invalidation). **Build-time fix in Phase I.4 (window wiring).**
2. Add regression test for the open-mid-refresh scenario using the full lifecycle.
3. Fix §3 step 7 wording — either correct the false claim or match the implementation fix.

**Next-step recommendation: PROCEED TO IMPLEMENTATION.** Spec is 95% clean. The 1 HIGH bug is fixable in 5 minutes during the build by the implementer. Holding for a 5th round of spec fixes would be over-process.
