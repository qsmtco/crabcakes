# PHASE 3 FIXES — Address PHASE 3 audit findings

**Date:** 2026-06-05
**Supervisor:** Qaster (using the `implementationSupervisor` prompt at `prompts/implementationSupervisor.md` exactly)
**Builder:** QTR (using the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md` exactly)
**Auditor:** Qaster (using the `adversarialDebugger` prompt at `prompts/adversarialDebugger.md` exactly)
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.10
**Audit context:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` P0 #3
**Predecessor:** PHASE 1+2+3 complete (3 commits, 45/45 tests pass, pushed to origin/main)

## Goal

Address the 3 audit findings I caught in PHASE 3 of `tests/test_activity_drawer.py`. The current file has:
- 21 tests passing
- 6 public methods on `ActivityDrawer`, 3 untested
- 1 weak assertion that wouldn't catch a regression in `clear_events()`
- 1 dead-code line in the test fixture

PHASE 3 FIXES closes the coverage gaps and cleans the test code. **No production code changes** — only the test file.

## Files to change (1 file, 1 sub-phase)

### `tests/test_activity_drawer.py` — 3 fixes

#### Fix 1 (issue, audit finding #2): Add 3 tests for untested public methods

QTR's PHASE 3 test class "TestActivityDrawer" tested 3 of 6 public methods on `ActivityDrawer`: `append_event`, `_passes_filter`, `clear_events`. The other 3 are untested:

- `on_agent_start(self, session_key: str, agent_name: str) -> None` — inserts a separator row, breaks the per-agent counter chain
- `on_agent_end(self, session_key: str, agent_name: str) -> None` — pops the per-agent counter, inserts a summary row
- `toggle(self) -> None` — flips `_expanded` and calls `_apply_expanded_state()`

Add 3 tests to `TestActivityDrawer`:

1. `test_on_agent_start_inserts_separator` — call `drawer.on_agent_start("sk-1", "Coder")` and assert:
   - `drawer._list.append.call_count == 1` (the separator was appended)
   - `drawer._last_separator_agent == ("Coder", "start")` (state tracked)
   - `drawer._last_row_key is None` (counter chain broken)

2. `test_on_agent_end_inserts_summary` — call `drawer.on_agent_end("sk-1", "Coder")` and assert:
   - `drawer._list.append.call_count == 1` (the summary was appended)
   - `drawer._last_separator_agent == ("Coder", "end")`

3. `test_toggle_flips_state` — directly test the `_expanded` state field. This is a bit tricky because `toggle()` calls `_apply_expanded_state()` which is patched to no-op in the fixture. So either:
   - Test the internal state directly: `drawer._expanded = False; drawer.toggle(); assert drawer._expanded is True`
   - Or skip this one and just document why (toggle's visible effect is via _apply_expanded_state, which is GTK-dependent)

QTR's call which approach.

#### Fix 2 (issue, audit finding #4): Strengthen `test_clear_events_resets_state`

The current test (line ~235-244) sets `drawer._list.get_row_at_index.return_value = None` as a precondition, then calls `clear_events()`. The test would pass even if `clear_events()` were a no-op that just reset state dicts. Strengthen it:

```python
def test_clear_events_resets_state(self, drawer):
    """clear_events() empties _total_count, _last_row_key, _agent_counters AND iterates the list."""
    row = {
        "agent": "Coder", "activity_type": "tool_start", "type_label": "tool", "icon": "🔧",
    }
    drawer.append_event(row)
    drawer.append_event(row)
    assert drawer._total_count == 2
    assert drawer._last_row_key is not None
    # Mock get_row_at_index to return a real-looking row, then None to terminate the loop
    fake_row = MagicMock()
    drawer._list.get_row_at_index.side_effect = [fake_row, fake_row, None]
    drawer.clear_events()
    # NEW: assert the list was actually iterated
    assert drawer._list.remove.call_count == 2, \
        f"expected clear_events to call .remove() 2 times, got {drawer._list.remove.call_count}"
    # Existing state assertions
    assert drawer._total_count == 0
    assert drawer._last_row_key is None
    assert drawer._agent_counters == {}
```

#### Fix 3 (issue, audit finding #5): Remove dead code

Line 187 in the `drawer` fixture has:
```python
d._listbox = fake_list  # backward-compat alias in case
```

The drawer's actual code reads `self._list`, not `self._listbox`. This line is dead code that misleads future readers. Remove it and the comment.

## Rules for the builder

- **You MUST use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md` exactly as written — no deviation.** Begin your response with: "Starting Discovery Phase — reading all relevant files before writing any code." Then output the discovery block, then proceed.
- Discovery is mandatory: re-read `tests/test_activity_drawer.py` and `ui/views/activity_drawer.py` (focus on lines 171-300 for the 3 untested public methods) before writing.
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT modify any other file. This phase is `tests/test_activity_drawer.py` ONLY.
- Do NOT add new dependencies. Stick to `unittest.mock`, `pytest`, and what's already imported.

## Verification (run yourself, paste output in your report)

```bash
# 1. New tests present
grep -nE "def test_on_agent_start|def test_on_agent_end|def test_toggle" tests/test_activity_drawer.py
# Expected: 3 matches (the 3 new tests, or however many you wrote)

# 2. Strengthened clear_events test has the new remove assertion
grep -n "drawer._list.remove.call_count" tests/test_activity_drawer.py
# Expected: 1+ match

# 3. Dead code line is gone
grep -n "d._listbox = fake_list" tests/test_activity_drawer.py
# Expected: 0 matches

# 4. New tests pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_drawer.py -v
# Expected: 24 passed (was 21, +3 new)

# 5. No regression in test_activity_bubbles.py
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py -q
# Expected: 24 passed

# 6. Combined run
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -q
# Expected: 48 passed (24 + 24)

# 7. AST parse
python3 -c "import ast; ast.parse(open('tests/test_activity_drawer.py').read()); print('PARSE OK')"
```

## Report format

At the end, include the COMPLETENESS checklist:

```
COMPLETENESS:
- [x/not done] Fix 1: added tests for on_agent_start, on_agent_end, toggle (or documented why toggle was skipped) — evidence (test names, line numbers, pytest output)
- [x/not done] Fix 2: strengthened test_clear_events_resets_state with .remove() iteration assertion — evidence (grep, pytest output)
- [x/not done] Fix 3: removed dead _listbox alias line — evidence (grep showing 0 matches)
- [x/not done] Test result: pytest tests/test_activity_drawer.py — paste full output
- [x/not done] Test result: pytest tests/test_activity_bubbles.py — paste full output
- [x/not done] Combined: pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py — paste full output
```

If you cannot include this checklist, your response is INCOMPLETE. Do not expect acceptance.

## After QTR reports done

Qaster will:
1. Re-run the verification commands above (independent of QTR's report)
2. Run a fresh adversarialDebugger audit on the new code
3. Commit if clean (using Qaster author per Captain's authorization)
4. Push to origin/main
5. Write a post-mortem to `~/.openclaw/workspace-Qaster/memory/2026-06-05-PHASE-3-FIXES-RESULT.md` and report back to the Captain
