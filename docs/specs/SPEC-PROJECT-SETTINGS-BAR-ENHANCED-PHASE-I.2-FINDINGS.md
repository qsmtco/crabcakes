# Phase I.2 Audit Findings — FeedHandler auto-accept level methods

**Code under audit:** `ui/handlers/feed_handler.py` (5 new pieces)
**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` §2.3
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ✅ **PASS — ready for Phase I.3.**

## Bug count & severity

**1 bug: 0 CRIT, 0 HIGH, 0 MED, 1 LOW** (defense-in-depth gap, unreachable in practice).

## Scope-deviation check

**Confirmed correct.** The 2 extra pieces (`_emit_auto_accept_level_changed` + `_on_auto_accept_level_changed` init field) are required for the spec's `set_auto_accept_level("off")` and `_commit_auto_accept_level` code paths to function. Without them, both paths would `AttributeError` at runtime. The deferred `set_on_auto_accept_level_changed` setter correctly belongs to Phase I.4 (window wiring).

## Test results — 16 ad-hoc tests, all PASS

| # | Test | Result |
|---:|---|---|
| 1 | Round-trip 4 levels (off/diffs/files/all) | ✅ all 4 round-trip |
| 2 | "off" path emits on_auto_accept_level_changed | ✅ |
| 3 | Enabling states route through warning gate | ✅ category="files" passed |
| 4 | Invalid level ("bogus") is no-op | ✅ |
| 5 | `_prefs is None` guard | ✅ all 4 levels no-op |
| 6 | exec_command untouched | ✅ |
| 7 | `_emit` guards None callback | ✅ no AttributeError |
| 8 | Warning category mapping (diffs/files/all → "diffs"/"files"/"files") | ✅ |
| 9 | Re-entrancy: `_commit` 3x same level | ✅ state stable |
| 10 | Re-entrancy: on_confirm then on_cancel | ✅ 1 emit, no second |
| 11 | `lambda lvl=level:` default-arg capture | ✅ no late binding |
| 12 | set("off") bypasses warning | ✅ |
| 13 | get() for non-standard intermediate state | ✅ |
| 14 | get() for orphaned diff state | ✅ |
| 15 | set("off") 3x when already off (no dedup) | ✅ 3 emits |
| 16 | set_on_auto_accept_level_changed setter (deferred to I.4) | ✅ correctly absent |
| 17 | get() for default (all-False) prefs | ✅ returns "off" |

## Spec compliance — verbatim match

All 4 method bodies match the spec's §2.3 character-for-character (verified by `diff`). Comments reference the spec section. `Callable` is already imported (line 14).

## BUG #1 — LOW (only bug found)

**Defense-in-depth gap in `_commit_auto_accept_level`:** it does not validate `level` even though `set_auto_accept_level` does. Direct calls with an invalid level would skip prefs mutation but still call `_refresh_auto_accept_state()` and `_emit_auto_accept_level_changed(level)`. **Unreachable in practice** — the only callers (lines 468, 472) guard the level. Fix is a 1-line guard. Not blocking.

**Supervisor note:** Applied as a 1-line fix per `implementationSupervisor.md` §6 (fix small things yourself).

## Known gap (out of scope for Phase I.2)

The spec's §5 Step 2 claims 3 unit tests should be added:
- Round-trip via `to_dict()`/`from_dict()` — not implemented
- Assert `_refresh_auto_accept_state` called after each commit — not implemented
- Assert warning wire + on_cancel doesn't emit — not implemented

**No automated regression tests exist in `tests/test_feed_handler.py` for the 5 new pieces.** The implementation works (16/16 ad-hoc tests pass) but lacks automated coverage. **Should be added in Phase I.5 (Tests).**

## Top 3 must-fix

1. **(NONE required)** — Phase I.2 is functionally correct. All 5 spec items present, all 16 ad-hoc tests pass, spec compliance is verbatim.
2. **(OPTIONAL, LOW — applied by supervisor)** — Added `level` validation to `_commit_auto_accept_level` for defense-in-depth.
3. **(FOLLOW-UP, OUT OF SCOPE)** — Add the spec's 3 claimed unit tests to `tests/test_feed_handler.py` in Phase I.5.

## Next step

**Proceed to Phase I.3 (MainContent widget refactor).**
