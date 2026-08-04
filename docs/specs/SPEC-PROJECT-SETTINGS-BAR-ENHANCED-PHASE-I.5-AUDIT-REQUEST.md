# Phase I.5 Audit Request — Tests

**Code to audit:** 3 test files
- `tests/test_feed_handler.py` — appended `TestAutoAcceptLevel` (10 tests)
- `tests/test_main_content_settings_bar.py` — NEW (14 tests)
- `tests/test_window_settings_bar.py` — NEW (13 tests)

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` §5
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

## Mission

This is a test phase. The tests are the deliverable. Audit them for **quality and coverage**, not just pass/fail. A test that passes but doesn't actually exercise the invariant is worse than no test (false confidence). Load `prompts/adversarialDebugger.md` fresh.

## Adversarial focus areas (test quality)

1. **Do the tests actually break the code?** For each test, ask: if I reverted the Phase I.2/I.3/I.4 code, would this test FAIL? If not, the test is not testing the change. A passing test suite that doesn't catch regressions is a false negative.

2. **Fake/mock fidelity.** The tests use fake Gtk classes and mocked handlers. Do the fakes accurately model the real behavior? Specifically:
   - Does the fake `_FakeGtk.Box` support `get_first_child`/`remove`/`append` correctly?
   - Do the mocked handlers return realistic values (not just `MagicMock()` defaults that happen to be truthy)?
   - Does the window test's fake `threading.Thread` actually simulate the async completion (calling the target synchronously or via a controlled callback)?

3. **Assertion strength.** Are assertions checking the RIGHT thing?
   - FeedHandler: does `test_round_trip_all_four_levels` actually verify distinct states (not just "no exception")? Does it check `file_changes["diff"].enabled` AND `file_changes["file_created"].enabled` separately?
   - MainContent: does `test_xml_escape_for_project_name` check that the markup contains `&lt;b&gt;` (escaped), NOT `<b>` (raw)?
   - Window: does `test_branch_result_discarded_on_token_mismatch` assert the cache was NOT written (not just that no exception occurred)?

4. **Missing edge cases.** The spec's §5 Step 2/3/5 lists specific scenarios. Are any missing?
   - FeedHandler: is the `on_confirm` lambda's default-arg capture (`lambda lvl=level:`) tested?
   - MainContent: is the empty-value fallback in `_resolve_agent_display_name` (Round 3 BUG #7 — `{"special:x": ""}` → returns `"special:x"`) tested?
   - Window: is the "close mid-refresh" scenario tested (worker returns after close → discarded)?

5. **GTK segfault avoidance.** Confirm NO test constructs a real GTK widget. Run `grep -n "Gtk.Label()\|Gtk.Button()\|Gtk.Box()\|Gtk.Window()" tests/test_main_content_settings_bar.py tests/test_window_settings_bar.py` — should be 0.

6. **Test isolation.** Are tests independent? No shared mutable state across tests? Each test constructs its own fixtures?

7. **Test naming.** Do test names describe the behavior being tested (not just the method)?

## Independent verification (run yourself)

- `python3 -m pytest tests/test_feed_handler.py::TestAutoAcceptLevel -v` — confirm 10 pass.
- `python3 -m pytest tests/test_main_content_settings_bar.py -v` — confirm 14 pass.
- `python3 -m pytest tests/test_window_settings_bar.py -v` — confirm 13 pass.
- `python3 -m pytest tests/test_project_handler.py -q` — confirm 35 still pass.
- **Mutation test (optional but valuable):** temporarily break one invariant in the implementation (e.g., comment out the gear re-append in `set_project_settings_text`), run the relevant test, confirm it FAILS. Then revert. This proves the test actually catches regressions.

## Output format

BUG #[N] format. Sort by severity. End with:
- Pass/fail verdict (tests are adequate, or need strengthening)
- Top 3 must-fix items
- Coverage assessment: are the Phase I.2/I.3/I.4 invariants now protected by automated tests?

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-PHASE-I.5-FINDINGS.md` AND report back here.
