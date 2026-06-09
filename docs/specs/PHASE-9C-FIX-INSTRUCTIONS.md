# PHASE 9C — Item 2: `get_api_key()` side-effect fix

## Master context
Phase 8 audit Finding 1: `get_api_key()` in `agent/config.py` creates an empty `providers.yaml` as a side effect of a read operation. This is a dormant bug — `get_api_key` is not currently called anywhere, but it's a footgun for future code.

## Files to change

1. `agent/config.py` — REVISED. Remove the `ensure_providers_yaml_exists(config_path)` call from `load_agent_config()`. Move it to a more appropriate place where the file-creation side effect is justified: when the Settings UI is being initialized.

2. `ui/handlers/settings_handler.py` — REVISED. Add a call to `ensure_providers_yaml_exists` in `__init__` (or, alternatively, in the first call to a public method). This puts the file creation in the right place: when the UI is being prepared to manage providers.

3. `tests/test_get_api_key_no_side_effect.py` — NEW. A test that verifies `get_api_key()` does NOT create `providers.yaml`.

4. **Optional:** update `tests/test_agent_config_yaml_fallback.py` to remove the assertion that `load_agent_config()` creates the yaml — since we're moving that responsibility to `SettingsHandler.__init__`.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `proceed` is in this delegation.
- **Do NOT modify the `get_api_key()` function itself** — it stays the same. We're just moving when the file is created, not what `get_api_key` does.
- **Do NOT modify `ensure_providers_yaml_exists()`** — it stays the same.
- **Do NOT break the existing test `test_creates_yaml_on_first_run` in `test_agent_config_yaml_fallback.py`** unless you also update that test. See SUB-PHASE 9C.4 for details.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `agent/config.py` lines 187-260 (`load_agent_config` and `_create_default_config` and the `ensure_providers_yaml_exists` call)
2. `agent/config.py` lines 340-360 (`get_api_key` — verify it's not called anywhere)
3. `ui/handlers/settings_handler.py` full file (find the right place to add the call)
4. `tests/test_agent_config_yaml_fallback.py` (existing test that asserts yaml creation in `load_agent_config`)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 9C.1: Remove the call from `load_agent_config()`

In `agent/config.py`, find the lines added in Phase 8 (around line 244-246):

```python
    # Phase 8: if no providers were loaded from either source, ensure
    # providers.yaml exists so the Settings dialog has a place to write.
    if not providers:
        ensure_providers_yaml_exists(config_path)
```

**Remove these 3 lines.** The `load_agent_config()` function should be a pure read with no side effects beyond `_create_default_config` (which is a separate concern — pre-existing behavior).

**Important:** The existing test `test_creates_yaml_on_first_run` in `test_agent_config_yaml_fallback.py` will start failing after this change. Address this in SUB-PHASE 9C.4.

## SUB-PHASE 9C.2: Add the call to `SettingsHandler.__init__`

In `ui/handlers/settings_handler.py`, find the `__init__` method and add the call at the end (after all the existing initialization). The exact location depends on the current state of the file. The pattern:

```python
def __init__(self, *, GLib_module=None, parent_window=None, on_providers_changed=None, on_status_changed=None):
    # ... existing code ...
    
    # Ensure providers.yaml exists when the Settings UI is constructed.
    # This puts the file-creation side effect in the right place — the UI
    # that actually writes to it — rather than in agent.config.load_agent_config
    # (which is a read operation).
    try:
        from agent.config import ensure_providers_yaml_exists
        from utils.config import get_config_dir
        import os
        config_path = os.path.join(get_config_dir(), "agent.json")
        ensure_providers_yaml_exists(config_path)
    except Exception as e:
        logger.warning("Could not ensure providers.yaml exists: %s", e)
```

**Note:** `logger` may not be imported in `settings_handler.py`. If not, add `import logging; logger = logging.getLogger(__name__)` near the top.

**Note:** `get_config_dir` lives in `utils/config.py` per the existing pattern (Phase 3). Confirm via grep.

**Alternative placement:** If you'd rather put the call in `SettingsDialog.show()` instead of `SettingsHandler.__init__`, that's also acceptable. The key requirement is that the file is created **before the dialog opens for the first time**, not on every read of the agent config. Your call — document the choice.

## SUB-PHASE 9C.3: Add `tests/test_get_api_key_no_side_effect.py`

A small focused test that verifies `get_api_key` doesn't create `providers.yaml` as a side effect:

```python
# tests/test_get_api_key_no_side_effect.py
# Verifies that get_api_key() is a pure read — does NOT create providers.yaml
# as a side effect. The file-creation responsibility belongs to SettingsHandler,
# not to the config loader.

import os
import pytest
import pathlib

from agent.config import get_api_key


def test_get_api_key_does_not_create_providers_yaml(tmp_config_dir):
    """get_api_key on a fresh config must not create providers.yaml."""
    # Fresh config: agent.json exists with empty providers, no providers.yaml
    config_dir = pathlib.Path(os.environ['HOME']) / ".config" / "crabcakes"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agent.json").write_text('{"providers": {}}')
    yaml_path = config_dir / "providers.yaml"
    # Pre-condition: no providers.yaml
    assert not yaml_path.exists()
    # Call get_api_key
    result = get_api_key("nonexistent")
    # Post-condition: still no providers.yaml
    assert not yaml_path.exists(), \
        f"get_api_key created providers.yaml as side effect! result={result}"
    assert result is None
```

## SUB-PHASE 9C.4: Update `tests/test_agent_config_yaml_fallback.py`

The existing test `test_creates_yaml_on_first_run` in `tests/test_agent_config_yaml_fallback.py` will start failing after SUB-PHASE 9C.1. You have two options:

**Option A (preferred): Move the assertion.** Edit the test to assert that **`SettingsHandler.__init__` creates the yaml**, not `load_agent_config()`. This keeps the test coverage but at the right layer.

**Option B: Delete the test.** The new `test_get_api_key_no_side_effect.py` covers the regression-prevention angle (no side effect from reads). The yaml-creation behavior is now covered by tests of `SettingsHandler.__init__`.

**Recommended: Option A.** The yaml creation is a real behavior that should be tested. Just move the test to the right layer.

Concretely, replace `test_creates_yaml_on_first_run` with:

```python
def test_settings_handler_init_creates_yaml(self, tmp_config_dir):
    """SettingsHandler.__init__ creates providers.yaml if neither source has providers."""
    # No agent.json, no providers.yaml
    from ui.handlers.settings_handler import SettingsHandler
    SettingsHandler()
    # providers.yaml should now exist (empty)
    from utils.providers_store import load_providers
    assert load_providers() == []
```

This test lives in the same file but tests a different layer. You may also want to add a similar test to a new file `tests/test_settings_handler_init_creates_yaml.py` — your call.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# 9C.1: import still works
python3 -c "from agent.config import get_api_key, load_agent_config, ensure_providers_yaml_exists; print('imports ok')"
echo "---"

# 9C.1: ensure_providers_yaml_exists removed from load_agent_config
echo "=== verify removed from load_agent_config ==="
grep -B2 -A2 "ensure_providers_yaml_exists" agent/config.py | head -20
echo "---"

# 9C.2: ensure_providers_yaml_exists called from settings_handler
echo "=== verify called from settings_handler ==="
grep -B1 -A1 "ensure_providers_yaml_exists" ui/handlers/settings_handler.py
echo "---"

# 9C.3: new test passes
python3 -m pytest tests/test_get_api_key_no_side_effect.py -v --tb=short 2>&1 | tail -10
echo "---"

# 9C.4: updated yaml-fallback test passes
python3 -m pytest tests/test_agent_config_yaml_fallback.py -v --tb=short 2>&1 | tail -20
echo "---"

# Full suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

## Acceptance criteria for this phase

- [ ] `ensure_providers_yaml_exists(config_path)` is no longer called from `load_agent_config()`
- [ ] `ensure_providers_yaml_exists(config_path)` IS called from `SettingsHandler.__init__` (or `SettingsDialog.show()` — your documented choice)
- [ ] New test `tests/test_get_api_key_no_side_effect.py` exists and passes
- [ ] Updated test in `tests/test_agent_config_yaml_fallback.py` (or equivalent) covers yaml creation at the new layer
- [ ] All existing tests still pass
- [ ] Full test suite: 1365+ passed (one more than Phase 8 due to the new test)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 9C (Item 2) — COMPLETE

Files changed:
- agent/config.py — REVISED, +N / -M lines (paste git diff --stat)
- ui/handlers/settings_handler.py — REVISED, +N / -M lines (paste git diff --stat)
- tests/test_get_api_key_no_side_effect.py — NEW, +N lines (paste wc -l)
- tests/test_agent_config_yaml_fallback.py — REVISED, +N / -M lines (paste git diff --stat)

Verification (paste outputs of every command listed above):
- imports ok: ...
- removed from load_agent_config: ...
- added to settings_handler: ...
- new test passes: ...
- yaml-fallback test passes: ...
- full suite: ...

**COMPLETENESS:**
- [x] 9C.1 removed from load_agent_config — evidence: <grep>
- [x] 9C.2 added to settings_handler (or settings_dialog) — evidence: <grep>
- [x] 9C.3 new test exists and passes — evidence: <pytest tail>
- [x] 9C.4 yaml-fallback test updated — evidence: <pytest tail>
- [x] full suite passes — evidence: <paste test summary line>

**Implementation choices made:**
- (e.g. "put the call in SettingsHandler.__init__ because it's a one-time init, not a per-show action")
- (list other choices)

When done, please write: `Item 2 complete — ready for Phase C.`
```

When done, please write: `Item 2 complete — ready for Phase C.`
