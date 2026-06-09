# BUG #3 — Investigation Report: 10 Pre-Existing Test Failures

**Date:** 2026-06-09
**Investigator:** QTR (with supervisor audit)
**Scope:** Audit of 10 test failures in the full suite that pre-date the settings dialog lifecycle work
**Status:** Investigation complete, no fixes applied (captain's standing rule: audit only)

## Context

During the settings dialog lifecycle fix (commits `7021621` and `f807254`), the full test suite showed 10 failures across 4 files. QTR's initial report undercounted (said "1 failed") — the captain flagged this as BUG #3. The failures were verified pre-existing (they reproduce on unmodified `main` via `git stash`), so the settings work did not introduce them. This investigation characterizes the failures so a future fix phase can be planned.

## Failures by file

| # | Test | Pattern | Classification | Complexity |
|---|------|---------|----------------|------------|
| 1 | test_agent_builder_handler.py::TestSaveValidation::test_save_valid_agent | unpatched-config-leak | test bug | small |
| 2 | test_agent_builder_handler.py::TestSaveValidation::test_save_fires_callback | unpatched-config-leak (cascades from #1) | test bug | small |
| 3 | test_agent_builder_handler.py::TestLoadForEdit::test_load_existing | unpatched-config-leak (cascades from #1) | test bug | small |
| 4 | test_agent_builder_handler.py::TestDelete::test_delete_existing | unpatched-config-leak (cascades from #1) | test bug | small |
| 5 | test_agent_builder_handler.py::TestDelete::test_delete_fires_callback | unpatched-config-leak (cascades from #1) | test bug | small |
| 6 | test_agent_defs.py::TestValidateAgentDef::test_valid_agent_no_errors | unpatched-config-leak | test bug | small |
| 7 | test_bug_fixes.py::TestSIOverridesPreserved::test_preserved_si_on_edit | unpatched-config-leak (cascades from #1) | test bug | small |
| 8 | test_bug_fixes.py::TestRenameCleanup::test_rename_deletes_old_file | unpatched-config-leak (cascades from #1) | test bug | small |
| 9 | test_bug_fixes.py::TestRenameCleanup::test_same_name_no_cleanup | unpatched-config-leak (cascades from #1) | test bug | small |
| 10 | test_connection_sync_handler.py::TestActivityHandlerWiring::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer | stale-test-after-refactor | test bug | small |

## Summary

- **Total failures:** 10
- **By pattern:** 9 unpatched-config-leak (all cascading from a single root cause), 1 stale-test-after-refactor
- **By classification:** 10 test bugs, 0 code bugs
- **By complexity:** 10 small (single shared fixture addition + 1 assertion update)
- **Source files implicated as "code bugs":** None
- **Recommended fix phase scope:** A single fix phase that:
  1. Creates a shared `providers_yaml` fixture in `conftest.py` that seeds `providers.yaml` with a "minimax" provider entry (and any other test-required providers)
  2. Adds the fixture to the 9 failing test methods across 3 test files
  3. Updates the one assertion in `test_connection_sync_handler.py` to match the `_bubble_to_row` adapter pattern

## Root cause details

### Pattern 1: unpatched-config-leak (9 failures)

`utils/agent_defs.py:368-373` calls `get_available_providers()` to validate the `provider` field on an agent definition. This reads the real `~/.config/crabcakes/providers.yaml` because the failing tests do not patch `HOME` to an isolated temp directory.

The 9 failing tests all pass `provider: "minimax"`. The real `providers.yaml` (left over from the manual testing in step 3) contains only `name: test`. Validation fails with:

```
Unknown provider: minimax. Available: test
```

This causes `save()` to return `(False, errors)`, which cascades:
- Tests that assert `save()` returned True fail directly (#1)
- Tests that check a callback fired after `save()` fail because the callback never runs (#2, #5)
- Tests that load or delete after `save()` fail because the file was never written (#3, #4, #7, #8, #9)
- The validation test that calls `validate_agent_def()` directly fails with the same error (#6)

A `tmp_config_dir` fixture **already exists** in `tests/conftest.py:14-25` and patches `HOME` to an isolated temp directory. The failing tests simply don't use it. They use `tmp_agents_dir` (which patches the agents dir, not the config dir), so the validation code reads the real `providers.yaml` and fails.

**Proposed fix (for the future fix phase, not this audit):**

Add a `providers_yaml` fixture to `tests/conftest.py`:

```python
@pytest.fixture
def providers_yaml(tmp_config_dir):
    """Seed providers.yaml in the isolated config dir with the providers
    that the existing tests expect (minimax, zai, openrouter)."""
    providers_yaml = tmp_config_dir / "providers.yaml"
    providers_yaml.write_text(yaml.dump([
        {"name": "minimax", "base_url": "https://api.minimax.io/v1",
         "api_key": "*** "test-key", "default_model": "MiniMax-M2.7",
         "enabled": True, "supports_tools": True, "supports_streaming": True,
         "max_tokens": 128000},
        # ... zai, openrouter as needed
    ]))
    return providers_yaml
```

Then add `providers_yaml` to the test signatures of the 9 failing methods.

### Pattern 2: stale-test-after-refactor (1 failure)

The SPEC-activity-drawer Phase 1 refactor wrapped `drawer.append_event` in an adapter closure `_bubble_to_row` (in `ui/handlers/connection_sync_handler.py:184-187`). The adapter converts `ActivityBubble` → `drawer.append_event(bubble.to_drawer_row())` to handle the data shape mismatch.

The test at `tests/test_connection_sync_handler.py::TestActivityHandlerWiring::test_sync_with_drawer_routes_set_on_activity_bubble_to_drawer` was written before the adapter was added and asserts:

```python
activity_handler.set_on_activity_bubble.assert_called_once_with(mock_drawer.append_event)
```

But the production code now passes the closure:

```python
self._activity_handler.set_on_activity_bubble(_bubble_to_row)
```

The closure is **not** the raw `mock_drawer.append_event` — it's a wrapper that invokes it after calling `bubble.to_drawer_row()`. The assertion fails.

**Proposed fix:**

Replace the raw-callable assertion with a behavioral assertion that:
1. `set_on_activity_bubble` was called once with some callable
2. Invoking that callable with a fake `ActivityBubble` results in `mock_drawer.append_event` being called with `bubble.to_drawer_row()`

Example:

```python
activity_handler.set_on_activity_bubble.assert_called_once()
adapter = activity_handler.set_on_activity_bubble.call_args[0][0]
assert callable(adapter)

# Now invoke the adapter with a fake bubble
class FakeBubble:
    def to_drawer_row(self): return {"type": "test", "data": 42}

adapter(FakeBubble())
mock_drawer.append_event.assert_called_once_with({"type": "test", "data": 42})
```

This verifies the **behavior** (the adapter calls `append_event` with the right shape) rather than the **identity** (a specific callable object). The behavioral assertion survives future refactors that change the adapter's closure shape.

## Verification (this audit only)

- All 10 failures reproduce on current `main` (commit `7021621` + `f807254`).
- All 10 failures reproduce on unmodified `main` (commit `021829b` via `git stash`).
- Confirmed pre-existing — not regressions from the settings work.
- Confirmed root cause for pattern 1 by reading `utils/agent_defs.py:368-373` and the current state of `~/.config/crabcakes/providers.yaml`.
- Confirmed root cause for pattern 2 by reading `ui/handlers/connection_sync_handler.py:184-187` and the test traceback.

## Estimated effort for the fix phase (not this audit)

- 1 hour: create `providers_yaml` fixture in `conftest.py` and add it to 9 test signatures.
- 30 minutes: update the 1 assertion in `test_connection_sync_handler.py` to be behavioral.
- 30 minutes: run full suite, confirm 0 failures, write a post-mortem.

Total: ~2 hours of careful test editing. No production code changes.

## Out of scope for this audit

- The `refreshing_cards_on_unsaved_edit` (BUG #4) and `silently_swallowed_exceptions` (BUG #5) issues from the original adversarial audit are separate and remain unaddressed. Both are pre-existing design trade-offs, not bugs introduced by the settings work.

**End of report.**
