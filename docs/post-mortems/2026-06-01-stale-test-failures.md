# Post-Mortem: Fix 25 Stale Test Failures

**Date:** 2026-06-01
**Commits:** `bc260ff` (test fixes) + `85da7d4` (overlay crash fix from earlier session)
**Files changed:** 8 test files, 1 prompt file, 4 spec/instruction files
**Test results:** 30 failures → 0 failures, 1165 passes → 1194 passes

---

## Executive Summary

Fixed all 25 stale test failures plus the overlay crash fix resolved 4 additional failures, bringing the suite from 30 failures to 0. No production code was modified. The failures were caused by test fixtures drifting out of sync with API changes over approximately 2 weeks (since ~May 19).

---

## Root Cause Analysis by Category

### Category 1: Constructor Signature Drift (11 tests)
**Files:** `tests/test_create_project.py`
**Root cause:** `ProjectHandler.__init__()` removed the `main_content` parameter during the Phase 3 extraction. The test helper `_make_handler()` still passed it.
**Fix:** Removed `main_content=MagicMock()` from constructor call.

### Category 2: Missing Method on Test Double (6 tests)
**Files:** `tests/test_chat_handler.py`
**Root cause:** `MainContent` gained `get_chat_box_for_session()` at some point, but the `FakeMainContent` test double was never updated. Additionally, the fake never populated `_tab_sessions` for the session it was initialized with.
**Fix:** Added `get_chat_box_for_session()` to `FakeMainContent`, plus `set_tab_sessions()` calls in the 6 failing tests.

### Category 3: User Config Leaking Into Tests (3 tests)
**Files:** `tests/test_special_agents.py`
**Root cause:** Tests asserted against default agent YAML values, but `~/.config/crabcakes/agents/coder.yaml` overrides them with a stripped-down config (no `write_file`, different model format, enforcement disabled). The agent registry loads user config on top of defaults.
**Fix:** Mocked `load_agent_defs` to return controlled definitions, isolating tests from user environment.

### Category 4: Deleted Function Reference (1 test)
**Files:** `tests/test_mcp_integration.py`
**Root cause:** `_seed_defaults_if_empty` was removed from `utils/agent_defs.py` during a refactor. The test monkeypatched it.
**Fix:** Removed the monkeypatch line.

### Category 5: Behavior Change in Default Resolution (2 tests)
**Files:** `tests/test_agent_command_handler.py`
**Root cause:** `resolve_default_target_role()` now finds the `crabcakes` agent as a writing agent (its YAML has `write_file` in tools) and returns `"crabcakes"` instead of `"unknown"`.
**Fix:** Patched `resolve_default_target_role` to return `"unknown"` in the 2 affected tests.

### Category 6: GLib Mock Pattern Mismatch (1 test)
**Files:** `tests/test_crabwatch_handler.py`
**Root cause:** Test stored a `MagicMock` in `_debounce_map` and asserted `.destroy()`. Production code stores int source IDs and calls `GLib.Source.remove()`.
**Fix:** Rewrote test to use int source ID and patch `gi.repository.GLib.Source.remove`.

### Category 7: Dead Behavior Test (1 test)
**Files:** `tests/test_project_handler.py`
**Root cause:** Test verified that `open_project()` creates a chat tab, but that behavior was intentionally removed (project view lives in LeftPanel).
**Fix:** Deleted the test.

---

## Process Metrics

| Metric | Value |
|--------|-------|
| Phases | 6 (5 fix phases + 1 verification) |
| Builder deviations | 3 (all improvements over spec) |
| Spec bugs found by builder | 3 |
| Supervisory fixes (trivial) | 1 (trailing newline) |
| Full suite runs | 4 (baseline, per-phase verification, final) |
| Total wall time | ~90 minutes |

---

## Spec Bugs Found During Implementation

The spec (`SPEC-fix-stale-test-failures.md`) contained 3 bugs that the builder (QTR) caught during implementation:

### Spec Bug 1: Wrong patch target (Phase 3)
- **I wrote:** `patch("agent.special_agents.load_agent_defs")`
- **Problem:** `load_agent_defs` is imported inside `_load_registry()`, not as a module-level attribute
- **QTR fixed to:** `patch("utils.agent_defs.load_agent_defs")`
- **Lesson:** Verify patch targets by checking WHERE the function is imported, not where it's defined

### Spec Bug 2: Wrong return type (Phase 3)
- **I wrote:** `return_value=[SpecialAgentDef(...)]`
- **Problem:** `_load_registry()` calls `agent_def.get("role", "")` — expects dicts, not dataclass instances
- **QTR fixed to:** `return_value=[{"role": "coder", ...}]`
- **Lesson:** Trace the data flow PAST the mock boundary to verify return types match consumer expectations

### Spec Bug 3: Wrong GLib dispatch target (Phase 4)
- **I wrote:** Pass `mock_GLib` as `GLib_module`, assert on `mock_GLib.Source.remove`
- **Problem:** `crabwatch_handler.py:350` uses module-level `GLib.Source.remove()` from `from gi.repository import GLib`, not the injected `self._GLib`
- **QTR fixed to:** `patch("gi.repository.GLib.Source.remove")`
- **Lesson:** Don't assume all GLib calls go through the injected module — check the actual call site

### Spec Bug Pattern
All 3 spec bugs share the same root cause: **I wrote instructions based on reasonable assumptions instead of tracing the actual code.** The steelFramedCodeWriter prompt's Rule 2 ("trace every code path") and Rule 3 ("verify every function signature") would have caught all three if I'd applied them rigorously to my own spec.

---

## Builder Performance Assessment

**QTR (MiniMax M3):** Grade A

Strengths:
- Caught all 3 spec bugs by reading actual source code before implementing
- Deviated from instructions when the instructions would have produced failing tests, with clear explanations
- Consistent COMPLETENESS checklists with grep evidence
- Zero collateral edits across 6 phases
- Used Discovery Phase (steelFramedCodeWriter) consistently

Notable judgment calls (all correct):
1. Used `widget.unparent()` instead of `old_parent.remove_overlay()` (Phase 0, overlay fix)
2. Added `set_tab_sessions()` to individual tests instead of auto-populating in `__init__` (Phase 2)
3. Used dicts instead of `SpecialAgentDef` instances for mock return values (Phase 3)
4. Patched `gi.repository.GLib.Source.remove` instead of injected `GLib_module` (Phase 4)

---

## Recommendations for CrabCakes

### 1. Test Fixture Drift Detection (HIGH PRIORITY)
**Problem:** 25 tests were broken for ~2 weeks without anyone noticing.
**Recommendation:** Add a CI gate or pre-push hook that runs the full test suite and blocks on any failure. The current workflow allows pushing with a red suite.

### 2. User Config Isolation for Tests (MEDIUM PRIORITY)
**Problem:** Tests that load the agent registry pick up `~/.config/crabcakes/agents/*.yaml`, making test results environment-dependent.
**Recommendation:** Add a `conftest.py` fixture that monkeypatches the agents directory to a temp directory for all tests that touch the registry. This would prevent an entire class of failures.

### 3. Test Double Maintenance (MEDIUM PRIORITY)
**Problem:** `FakeMainContent` in `test_chat_handler.py` drifts from the real `MainContent` API whenever new methods are added.
**Recommendation:** Either:
- Add a test that validates `FakeMainContent` has all public methods of `MainContent` (interface contract test), or
- Use a real `MainContent` with GTK initialized in a test harness (heavier but guarantees sync)

### 4. Dead Test Deletion Protocol (LOW PRIORITY)
**Problem:** `test_creates_project_tab` tested behavior that was intentionally removed.
**Recommendation:** When removing a feature, grep the test suite for tests of that feature and delete them in the same commit. Add to the project's `ARCHITECTURE.md` §8.5 as a checklist item.

### 5. Spec Quality — Supervisor Self-Improvement (PROCESS)
**Problem:** 3 of my 5 fix phases had spec bugs that the builder had to correct.
**Root cause:** I wrote spec instructions from reasonable assumptions instead of tracing actual code paths.
**Fix:** Apply the steelFramedCodeWriter prompt's verification rules to my OWN specs before delegating:
- Rule 2: Trace every code path in code samples
- Rule 3: Verify every function signature with `grep`/`inspect`
- Rule 5: Verify key structures, don't assume

### 6. Overlay.remove() Crash — Broader GTK4 Audit (SUGGESTION)
**Problem:** The overlay crash was a GTK3→GTK4 migration bug that existed since commit `51f6e55`.
**Recommendation:** Audit the codebase for other GTK3-era patterns:
```bash
grep -rn '\.remove(' ui/ | grep -v 'remove_css_class\|remove_overlay\|remove_controller\|remove_mnemonic\|remove_tick\|unparent\|remove_child'
```
Any remaining `.remove()` calls on GTK4 widgets should be verified.

### 7. Provider Adapter Triplication (QTR's ORANGE Item)
**Problem:** `agent/runtime.py` has 6 nearly-identical provider adapter functions (3 sync + 3 streaming) with only minor differences in endpoint URLs, headers, and message format.
**Recommendation:** Extract a base provider adapter with the common HTTP/streaming logic, with provider-specific overrides for differences. This would reduce ~400 lines to ~150 and make adding new providers trivial.

---

## Test Suite Trend

| Date | Passed | Failed | Delta |
|------|--------|--------|-------|
| 2026-05-19 (approx) | 1165 | 30 | Baseline |
| 2026-06-01 (overlay fix) | 1169 | 26 | -4 failures |
| 2026-06-01 (stale fix) | 1194 | 0 | -26 failures |

**Net improvement:** +29 tests passing, -30 failures.

---

## Implementation Team

- **Supervisor:** Qaster (implementation supervisor, spec author, adversarial auditor)
- **Builder:** QTR (code implementation, spec bug corrections)
- **Model:** MiniMax M3 (QTR's first production task on the new model)
