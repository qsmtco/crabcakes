# SPEC: Fix 25 Stale Test Failures

**Date:** 2026-06-01
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** QTR's RED priority from institutional memory assessment
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md): This spec only modifies test files under `tests/`. No production code changes. All fixes bring test mocks/fakes into alignment with the current production API surface.

---

## DISCOVERY

- **Read `tests/test_create_project.py`:** 11 tests, all calling `_make_handler()` which passes `main_content=MagicMock()` to `ProjectHandler.__init__()`. The constructor no longer accepts `main_content` — it was removed during the Phase 3 extraction. Current signature: `__init__(self, left_panel, projects_module, agent_to_project, GLib_module=None, awareness_module=None)`. **Fix: update `_make_handler()` to match current constructor.**

- **Read `tests/test_chat_handler.py:67-147`:** `FakeMainContent` class — test double for `MainContent`. Missing `get_chat_box_for_session(session_key)` method which was added to `MainContent` at `ui/views/main_content.py:684`. Production code calls `self._mc.get_chat_box_for_session(tab)` at `chat_handler.py:646`. The method iterates `_tab_sessions` dict and returns the matching chat box. **Fix: add method to `FakeMainContent`.**

- **Read `tests/test_special_agents.py:105-145`:** 3 failing tests assert against `coder.tools`, `coder.model`, and `coder.get_self_improvement_config()`. Tests expect values from `prompts/default_agents/coder.yaml` (which has `write_file`, model `MiniMax-M2.7`, enforcement=True). But `~/.config/crabcakes/agents/coder.yaml` overrides with a stripped-down config (no `write_file`, model `minimax/MiniMax-M2.7`, enforcement=False). The registry loads user overrides. **Fix: mock `load_agent_defs()` or `_ensure_loaded()` to return a controlled coder def, so tests are isolated from user config.**

- **Read `tests/test_mcp_integration.py:154`:** `monkeypatch.setattr(ad_mod, "_seed_defaults_if_empty", lambda: None)` — references `_seed_defaults_if_empty` which was removed from `utils/agent_defs.py` during a refactor. The function no longer exists. **Fix: remove or guard the monkeypatch. Read the test to determine if this setup is still needed.**

- **Read `tests/test_agent_command_handler.py:817,959`:** Tests assert `entries[0]["target_role"] == "unknown"`. But `resolve_default_target_role()` in `utils/feedback_processor.py` now finds `crabcakes` agent as a writing agent (it has `write_file` in tools per its YAML) and returns `"crabcakes"` instead of `"unknown"`. This is correct behavior — the test expectation is stale. **Fix: update assertion to match current behavior, or mock `resolve_default_target_role` to return `"unknown"` for test isolation.**

- **Read `tests/test_crabwatch_handler.py:195-235`:** Test creates `mock_timer_source = MagicMock()`, puts it in `_debounce_map`, then asserts `mock_timer_source.destroy.assert_called_once()`. But production code at `crabwatch_handler.py:350` calls `GLib.Source.remove(source_id)` — it passes the source ID (int) to `GLib.Source.remove()`, not calling `.destroy()` on a mock object. The test stores a MagicMock where an int source ID should be. **Fix: store an int in `_debounce_map` and mock `GLib.Source.remove` instead.**

- **Read `tests/test_project_handler.py:82`:** `mc.create_chat_tab.assert_called_once_with("project:my-project", "Project: my-project")`. The test expects `create_chat_tab` called with `(session_key, display_name)`. The actual `open_project()` method may have changed its tab creation call signature or routing. **Fix: read current `open_project()` to determine correct expected call and update assertion.**

---

## 1. Overview

### Problem
25 tests have been failing since approximately May 19, 2026. They are NOT regressions in production code — they are stale test fixtures that drifted out of sync with API changes. The failing tests degrade signal-to-noise: a permanently red suite trains developers to ignore failures, which means real regressions get missed.

### Solution
Fix all 25 stale tests by updating test doubles, assertions, and mock setup to match the current production API surface. No production code changes.

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| Fix all 25 failing tests | Production code changes |
| Update `FakeMainContent` test double | Adding new test coverage |
| Fix mock constructor calls | Refactoring test architecture |
| Fix stale assertions | Changing test framework |
| Isolate tests from user config |  |

### Architecture Principles
- **§8.5 Testing:** Tests live in `tests/`, follow existing patterns
- Test doubles (fakes/mocks) must match current production API
- Tests must be isolated from user environment (`~/.config/`)

---

## 2. Changes by File

### 2.1 `tests/test_create_project.py` — Fix constructor signature

**What changed in production:** `ProjectHandler.__init__()` no longer accepts `main_content` parameter. Current signature:
```python
def __init__(self, left_panel, projects_module, agent_to_project, GLib_module=None, awareness_module=None)
```

**Current test code (line 19-27):**
```python
ph = ProjectHandler(
    main_content=MagicMock(),
    left_panel=MagicMock(),
    projects_module=projects_mod,
    agent_to_project=AgentRoutingTable(),
    awareness_module=pa,
)
```

**Fix — update `_make_handler()` to match current constructor:**
```python
def _make_handler(projects_dir: str) -> ProjectHandler:
    """Create a ProjectHandler with mocked deps and a real projects dir."""
    projects_mod = MagicMock()
    projects_mod._PROJECTS_DIR_REF = [projects_dir]
    projects_mod.load_projects.return_value = []

    ph = ProjectHandler(
        left_panel=MagicMock(),
        projects_module=projects_mod,
        agent_to_project=AgentRoutingTable(),
        awareness_module=pa,
    )
    return ph
```

Remove `main_content=MagicMock()` from the constructor call. No other changes needed — the 11 tests all go through `_make_handler()`.

**Tests fixed:** 11 (`test_creates_directory`, `test_creates_crabcakes_dir`, `test_default_path_is_under_projects_dir`, `test_custom_path`, `test_rejects_empty_name`, `test_rejects_whitespace_name`, `test_rejects_duplicate`, `test_rejects_existing_directory`, `test_strips_name_whitespace`, `test_calls_open_project`, `test_sets_active_project`)

---

### 2.2 `tests/test_chat_handler.py` — Add missing method to FakeMainContent

**What changed in production:** `MainContent` gained `get_chat_box_for_session(session_key)` at line 684. The method iterates `_tab_sessions` and returns the matching chat box.

**Fix — add to `FakeMainContent` class (after `_get_page_for_session` method, around line 123):**
```python
def get_chat_box_for_session(self, session_key: str):
    """Match MainContent.get_chat_box_for_session() — returns the fake chat box
    if session_key is in _tab_sessions, else None."""
    for idx, sk in self._tab_sessions.items():
        if sk == session_key:
            return self._fake_chat_box
    return None
```

This matches the production behavior: iterate `_tab_sessions`, return the chat box for the matching session key, or `None` if no match.

**Tests fixed:** 6 (`test_routes_to_project_tab_when_agent_in_project`, `test_routes_to_agent_tab_when_not_in_project`, `test_routes_to_correct_project_when_agent_in_multiple_projects`, `test_unknown_agent_routes_to_agent_tab`, `test_content_as_list_text_blocks_extracted`, `test_content_wrong_type_does_not_crash`)

---

### 2.3 `tests/test_special_agents.py` — Isolate from user config

**Root cause:** Tests assert against default `coder.yaml` values, but `~/.config/crabcakes/agents/coder.yaml` overrides them. The agent registry merges user config on top of defaults.

**Strategy:** Mock `load_agent_defs` to return a controlled coder definition for the 3 failing tests. This isolates tests from the user's local config.

**Fix for `test_coder_has_write_tools` (line 115):**
```python
def test_coder_has_write_tools(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file", "edit_file", "exec_command",
               "list_files", "search_files", "web_search", "web_fetch"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        assert coder is not None
        assert "write_file" in coder.tools
        assert coder.can_write is True
```

**Fix for `test_coder_has_provider_model` (line 130):**
```python
def test_coder_has_provider_model(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        assert coder.provider == "minimax"
        assert coder.model == "MiniMax-M2.7"
```

**Fix for `test_coder_si_full_stack` (line 136):**
```python
def test_coder_si_full_stack(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
        self_improvement={
            "bug_journal": True,
            "project_rules": True,
            "enforcement": True,
            "structured_feedback": True,
            "dream_consolidation": True,
        },
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        si = coder.get_self_improvement_config()
        assert si["bug_journal"] is True
        assert si["enforcement"] is True
        assert si["structured_feedback"] is True
        assert si["dream_consolidation"] is True
```

**Important:** The `fresh_registry` autouse fixture calls `reload_registry()` at the start of each test, so the mock must be active when `reload_registry()` runs. Using `with patch(...)` around the `reload_registry()` + assertions ensures the mock is active during the reload.

**Tests fixed:** 3 (`test_coder_has_write_tools`, `test_coder_has_provider_model`, `test_coder_si_full_stack`)

---

### 2.4 `tests/test_mcp_integration.py` — Remove reference to deleted function

**Root cause:** `_seed_defaults_if_empty` was removed from `utils/agent_defs.py` during a refactor. The test monkeypatches it.

**Fix — read the test at line 154 to determine what the monkeypatch was guarding:**

The monkeypatch `monkeypatch.setattr(ad_mod, "_seed_defaults_if_empty", lambda: None)` was preventing the registry from seeding defaults during test setup. Since the function no longer exists, the monkeypatch call itself raises `AttributeError`.

**Fix:** Remove the `monkeypatch.setattr` line. If the test still needs to prevent default seeding, check if the replacement mechanism exists and monkeypatch that instead. If not (i.e., the test passes without it), simply delete the line.

**Verification:** After removing the line, run the test. If it passes, no further changes needed.

**Tests fixed:** 1 (`test_mcp_servers_coerced_in_load_registry`)

---

### 2.5 `tests/test_agent_command_handler.py` — Fix stale target_role assertion

**Root cause:** `resolve_default_target_role()` in `feedback_processor.py` now resolves the `crabcakes` agent as a writing agent (its YAML has `write_file` in tools), so returns `"crabcakes"` instead of `"unknown"`. The test expected `"unknown"`.

**Strategy:** The tests should be isolated from the agent registry state. Mock `resolve_default_target_role` to return `"unknown"` so the tests verify the audit processing logic, not the role resolution logic.

**Fix for `test_audit_report_logged_to_review_log` (line 817):**
Add a mock for `resolve_default_target_role`:
```python
with patch("ui.handlers.agent_command_handler.resolve_default_target_role", return_value="unknown"):
    handler.on_agent_response("session:qaster:123", text, "test-project")
```

**Fix for `test_audit_report_emits_feed_card_callback` (line 959):**
Same pattern — wrap the `on_agent_response` call in the same mock.

**Tests fixed:** 2 (`test_audit_report_logged_to_review_log`, `test_audit_report_emits_feed_card_callback`)

---

### 2.6 `tests/test_crabwatch_handler.py` — Fix GLib mock mismatch

**Root cause:** Test stores a `MagicMock()` in `_debounce_map` and asserts `.destroy()` was called on it. Production code stores int source IDs and calls `GLib.Source.remove(source_id)`.

**Fix — rewrite `test_stop_watching_clears_debounce_timers`:**
```python
@patch("gi.repository.Gio.File.new_for_path")
@patch("gi.repository.Gio.File.monitor_directory")
def test_stop_watching_clears_debounce_timers(self, mock_monitor_dir, mock_new_for_path):
    from ui.handlers.crabwatch_handler import CrabWatchHandler
    from unittest.mock import patch as patch2
    
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

**Tests fixed:** 1 (`test_stop_watching_clears_debounce_timers`)

---

### 2.7 `tests/test_project_handler.py` — Fix tab creation assertion

**Root cause:** Test expects `mc.create_chat_tab.assert_called_once_with("project:my-project", "Project: my-project")` but `open_project()` at `project_handler.py:77` no longer creates a chat tab at all. Line 105 comment: `"NOTE: No chat tab creation here. Project view lives in LeftPanel's Projects tab."`

The test is testing dead behavior. It should either:
1. Be deleted (the behavior it tests no longer exists), or
2. Be updated to test what `open_project()` actually does (sets `_active_project_name`, calls `_awareness.init_project_config`, calls `_auto_add_onboarding_agents`, calls `init_workflow`, refreshes agents, populates routing table, notifies callbacks)

**Recommended fix:** Delete `test_creates_project_tab`. It tests behavior that was intentionally removed. If the team wants coverage of `open_project()`, a new test should be written against the current behavior — but that's a new test, not a fix for a stale one.

**Tests fixed:** 1 (`test_creates_project_tab` — delete)

---

## 3. Data Flow

No production data flow changes. All changes are in test setup and assertions.

## 4. File Change Summary

| File | Change Type | Tests Fixed | Risk |
|------|-------------|-------------|------|
| `tests/test_create_project.py` | Fix constructor call in `_make_handler()` | 11 | Low |
| `tests/test_chat_handler.py` | Add method to `FakeMainContent` | 6 | Low |
| `tests/test_special_agents.py` | Mock `load_agent_defs` for 3 tests | 3 | Low |
| `tests/test_mcp_integration.py` | Remove deleted function reference | 1 | Low |
| `tests/test_agent_command_handler.py` | Mock `resolve_default_target_role` | 2 | Low |
| `tests/test_crabwatch_handler.py` | Fix GLib mock to match production pattern | 1 | Low |
| `tests/test_project_handler.py` | Fix tab creation assertion | 1 | Low |

**Total: 25 tests fixed across 7 files.**

**Files NOT changed** (already correct):
- `ui/views/main_content.py` — `get_chat_box_for_session()` exists and works correctly
- `ui/handlers/project_handler.py` — constructor is correct
- `agent/special_agents.py` — registry loading is correct
- All other test files that are currently passing

## 5. Implementation Order

1. **Phase 1:** Fix `test_create_project.py` (11 tests, single function change)
2. **Phase 2:** Fix `test_chat_handler.py` (6 tests, add one method to fake)
3. **Phase 3:** Fix `test_special_agents.py` (3 tests, mock `load_agent_defs`)
4. **Phase 4:** Fix `test_mcp_integration.py` + `test_crabwatch_handler.py` + `test_project_handler.py` (3 tests, 3 files, independent simple fixes)
5. **Phase 5:** Fix `test_agent_command_handler.py` (2 tests, mock role resolution)
6. **Phase 6:** Run full test suite, confirm 0 failures (excluding any pre-existing failures not in scope)

**Verification at each phase:**
- Run the specific test file: `python3 -m pytest tests/test_X.py -q --tb=short`
- Confirm all previously-failing tests in that file now pass
- Confirm no previously-passing tests in that file are now broken

## 6. Acceptance Criteria

- [ ] All 25 previously-failing tests now pass
- [ ] No previously-passing tests are broken (run full suite)
- [ ] No production code was modified
- [ ] Test doubles match current production API signatures
- [ ] Tests are isolated from user config (`~/.config/`)
- [ ] `grep -rn 'main_content=' tests/test_create_project.py` returns 0 matches
- [ ] `grep -rn '_seed_defaults_if_empty' tests/` returns 0 matches

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| User has no `~/.config/crabcakes/agents/` directory | `test_special_agents.py` tests pass regardless (mocked) |
| User has custom coder.yaml with different tools | `test_special_agents.py` tests pass regardless (mocked) |
| `FakeMainContent.get_chat_box_for_session()` called with unknown session | Returns `None`, matching production behavior |
| `GLib.Source.remove` raises on invalid ID | Not in scope — test uses mock GLib, no real GLib involved |
| Multiple debounce timers in crabwatch | All cleared, `GLib.Source.remove` called for each |

## 8. ARCHITECTURE.md Updates Required

None. This spec only modifies test files.

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `ProjectHandler.__init__` signature verified: `grep -n "def __init__" ui/handlers/project_handler.py` → line 47, 5 params ✅
   - `get_chat_box_for_session` exists at `main_content.py:684` ✅
   - `_seed_defaults_if_empty` removed from `agent_defs.py` (grep returns 0) ✅
   - `resolve_default_target_role` returns `"crabcakes"` due to user config ✅
   - `GLib.Source.remove(source_id)` is the actual production pattern at `crabwatch_handler.py:350` ✅

2. **Did I catch all exception types?**
   - No exception handling changes in this spec — all changes are test setup/assertions ✅

3. **Did I verify key structures?**
   - `_tab_sessions` is `dict[int, str]` (page_idx → session_key) ✅
   - `_debounce_map` is `dict[str, int]` (path → GLib source ID) ✅
   - `SpecialAgentDef` has `tools`, `model`, `provider`, `can_write`, `self_improvement` fields ✅

4. **Did I trace the data flow end-to-end?**
   - All failure root causes traced to specific API changes ✅
   - Each fix mapped to the exact production change that caused the drift ✅

5. **Would an implementer produce working code?**
   - Yes, each fix is a specific edit to a specific test with exact before/after code ✅
   - Phase 4 (`test_project_handler.py`) needs implementer to read `open_project()` first — flagged in spec ✅

**Investigation resolved:** Section 2.7 — `open_project()` no longer creates chat tabs (line 105 comment confirms intentional removal). Test should be deleted.
