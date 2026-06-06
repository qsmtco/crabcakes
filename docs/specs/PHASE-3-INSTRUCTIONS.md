# PHASE 3 — Create `tests/test_activity_drawer.py`

**Date:** 2026-06-05
**Supervisor:** Qaster
**Builder:** QTR
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.10
**Audit context:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` P0 #3
**Predecessor:** PHASE 1 + 2 complete (24/24 tests pass in test_activity_bubbles.py, working tree clean)

## Goal

The spec mandates a new test file `tests/test_activity_drawer.py` with ~15 tests. ARCHITECTURE.md §12 already references this file. The spec's own Verification Cheat Sheet instructs running `pytest tests/test_activity_drawer.py -v` — but the file doesn't exist. PHASE 3 creates it.

## Files to change (1 file, 1 sub-phase)

### 1. `tests/test_activity_drawer.py` — NEW FILE

**Discovery first.** Read these files in full before writing any code:
- `ui/views/activity_drawer.py` (680 lines) — the view under test
- `models/activity.py` (250 lines) — the `ActivityBubble` dataclass
- `ui/handlers/activity_handler.py` (637 lines) — the lifecycle callback firings
- `tests/test_activity_bubbles.py` (read the imports/fixture patterns) — for style consistency
- `tests/conftest.py` — to understand the `fake_glib` fixture

**Test classes to write** (per spec §2.10 + audit P0 #3):

#### Class 1: `TestToDrawerRow` (~5 tests)
Tests the `ActivityBubble.to_drawer_row()` method.

- `test_basic_fields_present` — construct a minimal ActivityBubble, call `to_drawer_row()`, assert all 12 spec-required keys exist in the returned dict
- `test_agent_name_default_is_Agent` — when `agent_name=""`, the dict's `agent` key is `"Agent"`
- `test_timestamp_format` — the `timestamp` field is `HH:MM:SS` (3 colon-separated 2-digit groups)
- `test_duration_formatting` — for `duration_ms=1247`, dict's `duration` is `"1.2s"`; for `duration_ms=60000`, it's `"1m 0s"`; for `duration_ms=0`, it's `""`
- `test_exit_code_only_for_command_output` — for non-command_output types, `exit_code` is `None`; for command_output, it's the bubble's value

#### Class 2: `TestActivityDrawer` (~6 tests)
Tests the `ActivityDrawer` view itself.

Use `MagicMock` for all GTK widget dependencies. Don't construct real `Gtk.Box`/`Gtk.ListBox` instances in unit tests — they're complex GTK objects that need a running main loop. Test the drawer's LOGIC (state dicts, filter checks, counter-collapse decisions) by inspecting internal state, not by rendering widgets.

- `test_append_event_new_row` — fresh drawer, `append_event({"agent": "Coder", "activity_type": "tool_start", ...})` → 1 row in `_last_row_key`, total_count=1
- `test_append_event_counter_collapse` — two `append_event` calls with same `(agent, activity_type)` → counter collapsed, count=N, but only 1 row in the list
- `test_append_event_different_type_new_row` — same agent, different activity_type → 2 rows, counter chain broken
- `test_filter_drop_unmatched` — set `_visible_agents = {"Coder"}` then `append_event` with `agent="Debugger"` → row is dropped (not appended), but total_count still increments
- `test_filter_pass_matched` — same setup, `append_event` with `agent="Coder"` → row is appended
- `test_clear_events_resets_state` — `append_event` twice, then `clear_events` → total_count=0, `_last_row_key is None`, `_agent_counters` empty

To inspect the row list, use `self._list.get_row_at_index(0)` (real Gtk.ListBox method that works without a main loop for the first call). To count rows, walk via `get_row_at_index(i)` until it returns `None`.

**GTK4 testing caveat:** `ActivityDrawer.__init__` calls `Gtk.Box.__init__` and creates real `Gtk.Button`/`Gtk.MenuButton`/`Gtk.ScrolledWindow`/`Gtk.ListBox` widgets. This will work in a test environment if GTK is initialized; it will FAIL in a headless test runner that doesn't have a display. Mitigation:
- Use `pytest.skip("requires GTK display")` if `Gtk.init` fails
- Or, use `unittest.mock` to patch `ActivityDrawer._build_header` and `_build_list` to no-ops, then test only the data-state methods. This is the preferred approach for headless CI.

**Recommended approach:** in `setUp` (or pytest fixture), patch `ui.views.activity_drawer.Gtk.Box.__init__` to a no-op, then call `ActivityDrawer.__init__` with mocked widget creation. The drawer's state-mutation methods (`append_event`, `clear_events`, `on_agent_start`, `on_agent_end`, `_passes_filter`) should work without actual GTK widgets IF the GTK-dependent helpers (`_build_row_widget`, `_trim_old_rows_if_needed`, `_update_count_label`, `_auto_scroll_to_bottom`) are also mocked.

This is more complex than the other phases. If full GTK mocking is too much, QTR may write SIMPLER tests that just exercise `to_drawer_row()` (Class 1) and direct state mutation (Class 2 with heavy Gtk mocks). Minimum bar: 6 tests across the two classes.

#### Class 3: `TestActivityHandlerLifecycleCallback` (~3 tests)
Tests that `ActivityHandler` fires `set_on_agent_lifecycle` for lifecycle events.

- `test_lifecycle_start_fires_callback` — set up handler with mocked lifecycle callback, fire `stream=lifecycle phase=start` event, assert callback called with `(session_key, agent_name, "start")`
- `test_lifecycle_end_fires_callback` — same with `phase=end`, assert `(session_key, agent_name, "end")`
- `test_lifecycle_end_without_agent_name` — gateway payload has no `agentName`, assert callback called with `(session_key, "", "end")` (empty string, drawer defaults to "Agent")

**Use the existing `fake_glib` fixture from `conftest.py`** — same pattern as `TestActivityHandlerActivityBubbles` in `test_activity_bubbles.py`.

## Rules for the builder

- **Use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`** — word for word, no deviation. Start with: "Starting Discovery Phase — reading all relevant files before writing any code."
- Discovery is mandatory: read all 5 files listed above COMPLETELY before writing any code.
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT modify any other file in this phase. Do NOT modify activity_drawer.py itself.
- 30% minimum sad-path tests (the spec's iron rule from the steelFramedCodeWriter prompt).
- If full GTK mocking is impossible, prefer simpler tests over no tests. Minimum 6 tests.

## Verification (run yourself, paste output in your report)

```bash
# 1. New file exists
ls -la tests/test_activity_drawer.py
# Expected: file present

# 2. New tests pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_drawer.py -v
# Expected: 6+ tests pass (target 15, minimum 6)

# 3. Existing tests still pass (no regressions)
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py -q
# Expected: 24 passed

# 4. Combined run
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -q
# Expected: 30+ tests pass (24 + 6+)

# 5. AST parse the new file
python3 -c "import ast; ast.parse(open('tests/test_activity_drawer.py').read()); print('PARSE OK')"
```

## Report format

At the end, include the COMPLETENESS checklist:

```
COMPLETENESS:
- [x/not done] Edit 1: created tests/test_activity_drawer.py with N tests across M classes
 Evidence: ls -la output, test count, pytest output
- [x/not done] Edit 2: TestToDrawerRow class — N tests covering [list what each tests]
 Evidence: pytest -v output for those tests
- [x/not done] Edit 3: TestActivityDrawer class — N tests covering [list what each tests]
 Evidence: pytest -v output for those tests
- [x/not done] Edit 4: TestActivityHandlerLifecycleCallback class — N tests covering [list what each tests]
 Evidence: pytest -v output for those tests
- [x/not done] Test result: pytest tests/test_activity_bubbles.py — paste full output
- [x/not done] Test result: pytest tests/test_activity_drawer.py — paste full output
- [x/not done] Combined: pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py — paste full output
```

If you cannot include this checklist, your response is INCOMPLETE. Do not expect acceptance.

## Post-phase commit

**The Captain has authorized Qaster to commit when the code is clean.** After QTR reports done, Qaster will:
1. Verify the file independently (run the same checks above)
2. If clean, `git add` and `git commit` with a descriptive message
3. Report the commit SHA back to the Captain
