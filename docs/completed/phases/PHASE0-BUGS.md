# PHASE0 BUGS — Pre-Existing Test Failures (June 2026)

Audit of 13 pre-existing test failures. Fixed 9 (root cause: provider validation compared IDs against display names). Remaining 4 deferred (Type B/C).

---

## Fixed in this phase

**Root cause:** `validate_agent_def()` in `utils/agent_defs.py` compared the `provider` field (e.g. `"minimax"`) against display names from `providers.yaml` (e.g. `"MiniMax M2.7"`). The provider ID `"minimax"` never matched any display name, so every test that saved an agent with `provider: "minimax"` failed validation.

**Fix:** Updated `validate_agent_def()` to accept provider IDs derived from `default_model` prefix (e.g. `"minimax/MiniMax-M2.7"` → `"minimax"`), mirroring the resolution logic in `AgentRuntime._resolve_caller_key()`. This is a one-location fix — no test data changes needed.

**File fixed:** `utils/agent_defs.py` — `validate_agent_def()` provider validation block

**Tests fixed (9):**
- `tests/test_agent_builder_handler.py` — 5 tests (save_valid_agent, save_fires_callback, load_existing, delete_existing, delete_fires_callback)
- `tests/test_bug_fixes.py` — 3 tests (preserved_si_on_edit, rename_deletes_old_file, same_name_no_cleanup)
- `tests/test_agent_defs.py` — 1 test (valid_agent_no_errors)

---

## Deferred bugs

### BUG-PHASE0-01: Debugger agent not seeded to user config

**File:** `tests/test_special_agents.py::TestRegistry`

**Severity:** bug

**Tests affected:**
- `test_loads_coder_and_debugger` — AssertionError: assert 'Debugger' in ['Coder']
- `test_debugger_no_write_tools` — assert None is not None (debugger is None)
- `test_debugger_si_context_only` — AttributeError: 'NoneType' object has no attribute

**Root cause:** `_seed_defaults()` in `utils/agent_defs.py` only copies default agents if the user's agents directory is **completely empty**. The user has `~/.config/crabcakes/agents/coder.yaml` but no `debugger.yaml`. The seeding logic skips entirely when any agent exists.

**Fix:** Either (a) change `_seed_defaults()` to seed individual missing files, or (b) fix the tests to mock `load_agent_defs` to include a Debugger entry.

---

### BUG-PHASE0-02: ActivityBubble wiring test expects direct callback pass-through

**File:** `tests/test_connection_sync_handler.py::TestActivityHandlerWiring::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer`

**Severity:** bug

**Test failure:**
```
Expected: set_on_activity_bubble(<MagicMock.append_event>)
Actual: set_on_activity_bubble(<function _bubble_to_row at 0x...>)
```

**Root cause:** The handler's `sync()` wraps the callback in `_bubble_to_row` before passing it to `set_on_activity_bubble`. The test asserts the raw `mock_drawer.append_event` was passed, but the handler passes a closure.

**Fix:** Update the test to verify the wiring was done without checking exact callback identity, or capture the callback and verify it invokes `append_event` when called.

---

## Summary

| Bug | File | Tests | Severity | Status |
|-----|------|-------|----------|--------|
| Provider validation mismatch | utils/agent_defs.py | 9 | bug | **FIXED** |
| BUG-PHASE0-01 | test_special_agents.py | 3 | bug | deferred |
| BUG-PHASE0-02 | test_connection_sync_handler.py | 1 | bug | deferred |

**Total pre-existing failures:** 13  
**Fixed this phase:** 9 (1 code fix in `validate_agent_def()`)  
**Remaining deferred:** 4 (all non-trivial, documented above)  
**Net result:** 1385 → 1394 passed (+9)