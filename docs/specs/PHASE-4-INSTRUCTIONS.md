# Phase 4 Instructions — Fix 3 Independent Tests

3 files, 3 tests, 3 independent fixes.

## Fix 1: test_mcp_integration.py (1 test)

### File: `tests/test_mcp_integration.py`
### Test: `test_mcp_servers_coerced_in_load_registry` (around line 154)
### Root cause: References `_seed_defaults_if_empty` which was removed from `utils/agent_defs.py`

**Fix:** Remove the monkeypatch line that references the deleted function:
```python
# DELETE THIS LINE:
monkeypatch.setattr(ad_mod, "_seed_defaults_if_empty", lambda: None)
```

Before removing, verify:
1. `grep -n '_seed_defaults_if_empty' utils/agent_defs.py` — should return 0 matches (confirms function doesn't exist)
2. Read the test to understand what the monkeypatch was guarding — it was preventing default agent seeding during test setup
3. After removing the line, run the test. If it still passes, the monkeypatch was no longer needed. If it fails, a replacement mechanism exists — investigate.

## Fix 2: test_crabwatch_handler.py (1 test)

### File: `tests/test_crabwatch_handler.py`
### Test: `test_stop_watching_clears_debounce_timers` (around line 195)
### Root cause: Test stores a MagicMock in `_debounce_map` and asserts `.destroy()` was called, but production code stores int source IDs and calls `GLib.Source.remove(source_id)`.

**Fix:** Rewrite the test to match production behavior:

```python
@patch("gi.repository.Gio.File.new_for_path")
@patch("gi.repository.Gio.File.monitor_directory")
def test_stop_watching_clears_debounce_timers(self, mock_monitor_dir, mock_new_for_path):
    from ui.handlers.crabwatch_handler import CrabWatchHandler
    from unittest.mock import MagicMock

    mock_cb = MagicMock()
    mock_GLib = MagicMock()
    handler = CrabWatchHandler(GLib_module=mock_GLib, on_event=mock_cb)

    mock_gfile = MagicMock()
    mock_new_for_path.return_value = mock_gfile
    mock_gfile.query_exists.return_value = True

    mock_monitor = MagicMock()
    mock_monitor_dir.return_value = mock_monitor

    # Store an int source ID like production code does
    handler._debounce_map['test.py'] = 42

    handler.stop_watching()

    assert len(handler._debounce_map) == 0
    mock_GLib.Source.remove.assert_called_with(42)
```

Key changes:
- Pass `mock_GLib` as `GLib_module` (not None) so production code can call `GLib.Source.remove()`
- Store int `42` in `_debounce_map` instead of a MagicMock
- Assert `mock_GLib.Source.remove.assert_called_with(42)` instead of `mock_timer_source.destroy.assert_called_once()`

## Fix 3: test_project_handler.py (1 test)

### File: `tests/test_project_handler.py`
### Test: `test_creates_project_tab` (around line 82)
### Root cause: Test expects `mc.create_chat_tab` to be called, but `open_project()` no longer creates chat tabs. The comment at `project_handler.py:105` says: "NOTE: No chat tab creation here. Project view lives in LeftPanel's Projects tab."

**Fix:** Delete the entire test method. The behavior it tests was intentionally removed.

```python
# DELETE THIS ENTIRE METHOD:
def test_creates_project_tab(self, handler, mc, fake_glib):
    handler.open_project("my-project", "/path/to/my-project")
    fake_glib.dispatch_all()
    mc.create_chat_tab.assert_called_once_with("project:my-project", "Project: my-project")
```

## Verification
After all 3 fixes:
```bash
python3 -m pytest tests/test_mcp_integration.py tests/test_crabwatch_handler.py tests/test_project_handler.py -q --tb=short
```
Expected: all tests pass, 0 failures.
