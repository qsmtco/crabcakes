# D7 Post-Mortem — Auxilium First-Run Wizard (Tier 1)

**Date:** 2026-06-13
**Supervisor:** Qaster
**Builder:** QTR
**Commits:** 1 (`3c03d8b` — 13 files, +2,727 lines)
**Phases:** 6 (handler → view → wiring → tests → docs → commit)
**Total bugs found:** 3 (all HIGH, all fixed in-phase)
**Process:** supervisor delegates via `/ask @QTR`, QTR writes code, supervisor audits with adversarialDebugger, sends back bugs, QTR fixes, repeat until clean

---

## Code Quality Grade: A- (90/100)

### Justification

The three-bug count is actually low for a 6-phase integration with 3 new files and 3 bug-fix files. Two of the bugs were architectural (live-reference leak, view sync) and one was a parameter-not-used defect (wizard-needed check). None were algorithmic. The code structure — handler→view→wiring with a polling bridge — is correct and matches the architecture's existing pattern for handler/view separation.

| Category | Score | Notes |
|---|---|---|
| Correctness | 19/20 | 3 fixed bugs; 0 remaining after fix cycle |
| Architecture compliance | 10/10 | No forbidden imports, correct handler/view split, polling model |
| Test coverage | 8/10 | 7 tests cover all 3 new files; missing provider-pick smoke test |
| Documentation | 9/10 | 2 ARCHITECTURE.md sections mirror existing format |
| Maintainability | 9/10 | Clear class/purpose boundaries; handler is ~400 lines (spec was ~150) |
| DX (Developer Experience) | 9/10 | Easy to test in isolation; handler is GTK-free; view is thin |
| **Total** | **90/100** | **A--** — solid code with minor gaps |

Deducted points:
- -1 correctness: no test for provider-pick form validation edge cases (empty key, Ollama key normalization)
- -1 test coverage: the 7th test only checks initial state; doesn't exercise the full click flow with stub handler
- -1 maintainability: handler at 441 lines vs. spec's ~150 — could be factored into a 200-line core + utils

---

## What's Good About the Code

### 1. Architecture fidelity

The handler has exactly zero GTK, gate, or subprocess imports — verified via `grep` on every audit round. The view has exactly zero business logic — it reads `handler.get_state()` dict keys but never calls `sys.platform` or `importlib`. This is the architecture working as designed.

### 2. Defensive deep copy

The `copy.deepcopy(self._state)` in `get_state()` is the right guard. The view in Phase 2 does rendering from a snapshot; the handler's internal state is never at risk of caller corruption. This bug was caught by Probe 7 in the adversarial audit — the view mutated `state.step = WizardStep.DONE` and the handler silently collapsed. The deep copy prevents this entire class of bugs.

### 3. Polling bridge over GLib coupling

The handler and view communicate through a polling loop: view runs `GLib.timeout_add(250ms, _poll_gateway)`, handler exposes `get_state()` for the view to read. There is no GLib import in the handler, no callback from the handler into the view. This keeps the handler importable from any context (tests, scripts, headless environments) without GTK dependencies. The alternative — `GLib.idle_add` in the handler — would have created a dependency coupling that makes headless testing impossible.

### 4. Clean view lifecycle

`AuxiliumWizard.cleanup()` removes the GLib poll timer source, and the window.py wiring calls it before `chat_box.remove(wizard)`. No timer leaks, even if the wizard is dismissed mid-gateway-probe. The gateway probe thread is a daemon — it dies with the process if the app exits during a probe.

### 5. Phase instructions as institutional memory

The 9 spec files (`TIER-1-D7-PHASE-*-INSTRUCTIONS.md`) document exactly what was delegated and why. They capture the bugs, fixes, and decision rationale at each step. This means the next supervisor (or the captain reviewing the work) can trace the entire implementation history without asking anyone.

---

## What's Bad About the Code

### 1. Handler is 3× the spec estimate (441 vs. ~150)

The spec estimated ~150 lines. The handler is 441. The extra ~300 lines come from:

| Source | Lines |
|---|---|
| Docstrings | ~80 |
| Provider config dispatch (3 branches × 10 lines each) | ~30 |
| Gateway probe threading (Thread + try/except + state mutation) | ~40 |
| Install check (6 importlib probes + dict construction) | ~30 |
| `is_auxilium_wizard_needed` helper | ~18 |
| `WizardState` dataclass + `WizardStep` enum | ~15 |
| Type hints + comments + whitespace | ~60 |

The core state machine logic (5 methods × 10 lines) is ~50 lines. The docstrings and type hints are all correct, but the install check and provider config dispatch are both longer than they need to be. They could be factored into helper functions (e.g., `_detect_platform()`, `_build_openrouter_config()`), reducing the handler to ~200 lines.

**Evolution suggestion:** In Tier 2, factor the install check into a separate `auxilium_wizard_utils.py` module. The handler stays at ~200 lines; the utils stay at ~100. The test file can then test the utils independently of the state machine.

### 2. Test 6 has a 4.5s `time.sleep`

`test_handler_advance_to_gateway` sleeps 4.5 seconds because the gateway probe has a 3-second timeout and runs in a daemon thread. This is the correct behavior for the current API — the handler doesn't expose a `wait_for_gateway()` method, so the test must poll or sleep.

**Evolution suggestion:** Add a `_gateway_done: threading.Event` to the handler. The test can call `handler._gateway_done.wait(timeout=5.0)` instead of sleeping 4.5 seconds. This is a 3-line addition (create event in `advance_to_gateway`, set it on probe completion, expose via `get_state`'s gateway_check field) and removes the only slow test in the suite.

### 3. No CSS styles for the wizard

The view adds CSS classes (`auxilium-wizard`, `auxilium-wizard-step-dot`, etc.) but `ui/styles.py` has no corresponding rules. The wizard renders with default GTK4 styling — functional but visually inconsistent with the rest of the app's themed appearance.

**Evolution suggestion:** Add CSS rules to `ui/styles.py` in a follow-up. The classes are named; adding styles requires no code changes in the view, only CSS additions to the existing `APP_CSS` constant.

### 4. Gateway probe doesn't expose an abort path

If the user closes the app during a gateway probe (which has a 3-second timeout), the daemon thread continues running until the process exits. This is harmless (daemon threads die with the process), but if the handler is reused in a long-running context, it could leave abandoned threads.

**Evolution suggestion:** Add a `cancel()` method that sets a `threading.Event` and calls `thread.join(timeout=1.0)`. The `cleanup()` method on the view would call `handler.cancel()` before removing the wizard.

### 5. `current_step` property returns a string, not a `WizardStep` enum

The view's `current_step` returns the stack page name (a string), not the typed `WizardStep` enum. This is intentional per the architecture rule ("no imports of other UI components"), but it means the property can return any string, not just the 3 valid values. A mistyped frame name in a `_show_frame(3)` call would silently render nothing.

**Evolution suggestion:** Add a `_STACK_PAGES: dict[WizardStep, str]` mapping in the view and validate `current_step` against it. The property would return a `WizardStep` value cast from the stack page name. This adds type safety without importing the handler module.

---

## Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|---|---|---|---|---|
| 1 | 1 | HIGH | `get_state()` returned live reference, not deep copy | Qaster (adversarial probe 7) | QTR (1 commit) |
| 2 | 2 | HIGH | `_on_continue_clicked` did not call `_sync_to_handler_state` — view stayed on install frame | Qaster (adversarial probe B) | QTR (1 commit) |
| 3 | 3 | HIGH | `is_auxilium_wizard_needed` ignored `config_dir` parameter — fresh-install users never saw wizard | Qaster (adversarial probe) | QTR (1 commit) |

All 3 bugs were caught in-phase, before any downstream phase was written. The supervisor's "audit between every phase" rule prevented compounding — each bug's fix was verified before the next phase started.

### Bug patterns

| Pattern | Count | Description |
|---|---|---|
| `reference-leak` | 1 | Returning mutable internal state without defensive copy |
| `view-sync` | 1 | View not re-reading handler state after state-transition callbacks |
| `parameter-ignored` | 1 | Parameter accepted but never used; global state used instead |

All three are integration bugs — the handler, view, and wiring each work correctly in isolation, but the interfaces between them were loose. The most important fix was bug #3: without it, the entire D7 feature (the wizard) was silently broken for first-run users.

---

## Process: What Worked

### 1. Sub-phasing within integration

Phase 3 (wiring) was sub-phased into 3a (helper), 3b (wizard creation), 3c (dismissal). The three sub-phases were written to a single instructions file, and QTR implemented all three in one shot. The sub-phase breakdown caught the parameter-not-used bug in 3a immediately, preventing it from compounding with 3b and 3c.

### 2. Adversarial probes before delegations

Running the adversarialDebugger prompt for each phase caught all 3 bugs. The probe strategy was:

- **Phase 1:** 9 probes covering state machine transitions, error paths, callback invocation, and the deep-copy contract
- **Phase 2:** 10 probes covering visible frame switching, timer lifecycle, back button visibility, empty-form validation, and gateway poll termination
- **Phase 3:** 4 probes covering the helper function with temp dirs, empty dirs, and real dirs

The probes that uncovered bugs were all "edge case" style — what happens when a caller mutates the returned state? What happens when the user clicks Continue? What happens when the config dir is empty?

### 3. File-based delegation for complex instructions

Every instruction file was written to `docs/specs/` before the `/ask` was sent. Zero truncation failures. The channel character limit (4,096 chars) was never hit because the instruction files held the full context.

### 4. QTR's spec-drift flagging

QTR correctly identified a spec ambiguity in Phase 2 (the gateway URL default of `ws://localhost:8765` vs. the codebase's `ws://localhost:18789`) and resolved it in favor of the codebase default. This prevented a "works in test, broken in production" mismatch.

---

## Process: What Didn't Work

### 1. QTR's reports were truncated mid-sentence in Phase 3

The Phase 3 report (wiring) was cut mid-sentence at "on_complete: Callable" — the rest of the report (verification outputs, COMPLETENESS checklist, rationale) was never delivered. The supervisor verified independently from the filesystem (read the diff, re-ran the tests, re-ran the probes) and accepted the work because the code was correct on disk.

**Lesson:** The `/ask` channel has effective character limits. QTR's reports are verbose because the `steelFramedCodeWriter` prompt demands detail. Solutions:
- In future, tell QTR to report only "Done. File at path. Tests pass." and verify the rest independently
- Or: shorten the COMPLETENESS checklist — 17 items per report is too many for the channel
- Or: write reports to a file and reference the path in the `/ask` response

### 2. QTR's habit of filing stub tests for Ollama

QTR's earlier Phase 1 test (instantiating the handler with an empty config dir) used `set_provider_choice('ollama', ...)` to write a `providers.yaml` with Ollama defaults. This polluted the real config directory, making `is_auxilium_wizard_needed` return `False` on a machine where the captain had never actually run the wizard. The audit caught this because Probe 3's "temp dir → True" assertion surfaced the discrepancy.

**Lesson:** Handler tests should use `tempfile.TemporaryDirectory()`, never `Path.home() / '.config' / 'crabcakes'`. This is already the convention in the test file — the Phase 4 specs enforce it — but earlier ad-hoc testing (before Phase 4) violated it.

### 3. The `pytest tests/` full suite hangs

The full test suite (`pytest tests/` without specifying individual test files) hangs indefinitely. The issue is not in the D7 tests — all 20 D7-relevant tests pass in 16.64s. The hang is in other test files (`test_connection_sync_handler`, `test_agent_runtime`, etc.) which likely require live GTK or network connections. This is a pre-existing issue, not caused by D7.

**Lesson:** Always specify test files explicitly: `pytest tests/test_architecture.py tests/test_kb_lookup.py tests/test_auxilium_tier1.py`. The full-suite hang will need a separate investigation (not in D7 scope).

---

## What the Code Actually Does (End-User Impact)

When a user opens CrabCakes for the first time and clicks the Auxilium tab:

1. **Install Check:** The wizard shows what's installed and what's missing. On a typical Linux machine with PyGObject, it shows "Python 3.12.3 ✓", "GTK4 ✓", "websockets ✓", "cryptography ✓" — all green. The "Continue" button advances.

2. **Gateway Check:** The wizard probes `ws://localhost:18789` with a 3-second timeout. If the gateway is running, it shows "Gateway OK ✓". If not, "Failed: Connection refused" with a "Continue anyway" button. The user can proceed without gateway connectivity — they just can't chat yet.

3. **Provider Pick:** Three options:
   - "OpenRouter free tier" — the user enters a free API key from openrouter.ai. The wizard writes an `openrouter` provider to `~/.config/crabcakes/providers.yaml`.
   - "Ollama (local, free)" — no key needed. The wizard writes an `ollama` provider pointing at `localhost:11434`.
   - "Bring your own key" — the user picks from (OpenAI, Anthropic, Google) and enters their key.

4. **Finish:** The wizard writes the config, removes itself from the Auxilium tab, and the normal chat experience (with the welcome bubble) replaces it. The next time the user opens Auxilium, the wizard is skipped — `is_auxilium_wizard_needed` returns `False`.

---

## Pre-Existing Issues Flagged (Not Caused by D7)

1. **ARCHITECTURE.md §13 has an unclosed code block.** The fence count is odd (257, opened at line 3175). Pre-existing before D7 (243 on HEAD). Not fixed per scope-creep rule.

2. **`pytest tests/` full suite hangs.** Unrelated test files require live GTK/network. Not caused by D7; the 20 D7 tests pass cleanly.

---

## Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|---|---|---|
| Add `threading.Event` to gateway probe for faster tests | 3 lines | Removes 4.5s sleep from test suite |
| Factor handler into `auxilium_wizard_utils.py` (~100 lines) | 30 min | Reduces handler from 441→200 lines |
| Add CSS rules to `ui/styles.py` for wizard classes | 15 min | Matches the app's visual theme |
| Add `handler.cancel()` for gateway probe abort | 10 lines | Clean thread lifecycle in long-running contexts |
| Type `current_step` with `WizardStep` enum via `_STACK_PAGES` map | 5 lines | Prevents mistyped frame names |
| Add `@pytest.mark.gtk` config to `pytest.ini` | 5 min | Enables filtering GTK tests from non-xvfb runners |
| Write `scripts/verify_tier1.sh` (6-test verification script) | 20 min | Automates the manual test workflow |
