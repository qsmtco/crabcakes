# Phase I.4 Audit Request — Window wiring + ProjectHandler + FeedHandler setter

**Code to audit:** 3 files
- `ui/window.py` — extended `_on_feed_bar_update`, branch worker (`_schedule_branch_refresh`/`_resolve_branch_worker`/`_on_branch_result`), named `_on_project_closed`/`_on_project_opened`, 5 callback impls, 7 wiring callables, 4 init fields, legacy retirement
- `ui/handlers/project_handler.py` — `set_on_solo_target_changed` + modified `set_solo_target` (validation + fire-on-change)
- `ui/handlers/feed_handler.py` — `set_on_auto_accept_level_changed` setter

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` §2.2/§2.4/§2.3
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

## Mission

This is the HIGH-RISK integration phase. Adversarially probe the token-guarded async branch worker, the project lifecycle invalidation, the solo-target callback, the legacy retirement, and the 7 wiring callables. Load `prompts/adversarialDebugger.md` fresh. Work through all 11 sections.

## Adversarial focus areas (the hard parts)

### 1. Token-guarded branch worker (the hardest part — 4 rounds of spec audit)

- **`_schedule_branch_refresh`:** captures `project_path` + bumps `_branch_request_token` + sets `_branch_active_token` + sets `_branch_request_path`. Verify the guard is `if self._branch_active_token is not None: return` (NOT `is None` on a bool — Round 2 BUG #1).
- **`_resolve_branch_worker`:** reads ONLY the captured `path` (NOT `get_active_project_path()` live — Round 2 BUG #2). Dispatches via `GLib.idle_add` to `_on_branch_result`.
- **`_on_branch_result`:** ALL checks (token, path, active-name, active-path) run BEFORE `_cached_branch_by_path[path] = branch`. Round 3 BUG #2 — the cache write must come AFTER the identity check, never before. Trace the exact ordering.
- **Cache keying:** `_cached_branch_by_path` is keyed by `project_path` (Round 3 BUG #5). Verify no single `_cached_branch` field remains.

### 2. Project-close/open invalidation (named methods — Round 3 BUG #1)

- `_on_project_closed(name)` — bumps `_branch_request_token`, clears `_branch_active_token`/`_branch_request_path`. Does NOT clear `_cached_branch_by_path` (path-keyed cache persists for re-open — Round 4 design decision). MUST be a named `def` method, NOT a lambda (Round 3 BUG #1 was a SyntaxError from assignment-in-lambda).
- `_on_project_opened(name, path)` — bumps token, clears in-flight. **Round 4 build-time fix:** after invalidation, calls `_on_feed_bar_update(name, ...)` to force re-evaluation so the new project gets its branch scheduled even if a worker was in-flight for the previous project. Verify this re-trigger call is present.
- Verify both are registered via `set_on_project_closed`/`set_on_project_opened` (append-based, multi-callback — confirm the handler supports multiple callbacks).

### 3. Solo-target callback (Round 2 BUG #4, Round 3 BUG #3)

- `set_solo_target` validates project via `_get_project_path(project_name) is not None` (Option A strict). Unknown project → no-op.
- Fires `_on_solo_target_changed(project_name)` ONLY on real change (`old == new` → return early).
- Window's `_on_solo_target_changed(project_name)` guards active-project identity.

### 4. Auto-accept cycle (Round 3 BUG #4)

- `_on_autoaccept_cycle_clicked` calls `FeedHandler.set_auto_accept_level(next)` but does NOT optimistically rebuild the bar.
- The bar updates via `set_on_auto_accept_level_changed` callback, fired from `_commit_auto_accept_level` AFTER `_refresh_auto_accept_state()`.
- Window wires `set_on_auto_accept_level_changed` to a method that refreshes the bar.
- Member count is preserved (Round 2 BUG #3 — never passes `0`).

### 5. Legacy retirement (Round 2 BUG #6)

- `grep -c "_update_project_settings_from_project" ui/window.py` MUST return `0`. The old `escape_for_pango` path is retired.
- The new `_on_feed_bar_update` calls `update_project_settings` (the xml_escape_text'd method from Phase I.3).

### 6. Backward-compat of the 4 lifecycle call sites

Window.py:540 (opened), 554 (closed), 561 (members-changed), 1046 (_close_project_tab) all call `_on_feed_bar_update(name, count)` with 2 positional args. The new signature uses keyword-only defaults for the 3 new params. Verify these 2-arg calls still work (defaults fill in, then handlers resolve the real state).

### 7. Thread safety

- All `_branch_*` state mutations on the GTK thread.
- Worker reads ONLY captured `path` + `token`; never touches window state directly.
- `GLib.idle_add` dispatches the result back to the GTK thread.

### 8. `_open_settings()` correctness

`_on_settings_btn_clicked` calls `self._open_settings()`. Verify `_open_settings` exists on MainWindow and opens a fresh SettingsDialog (not a persistent `_settings_dialog` attribute — Round 1 BUG #5).

### 9. Detached HEAD handling

`get_branch` returns `GitResult(success=True, stdout="(detached HEAD)")`. The bar should display `⎇ (detached HEAD)` verbatim. Verify the worker doesn't special-case this.

### 10. Re-entrancy

- Two rapid branch refreshes: second supersedes first (token increments). Only newest result applies.
- `on_confirm` called twice: state stays correct (idempotent commit).
- `set_solo_target` called with same value: no-op (no callback fire).

## Independent verification (run yourself)

- `grep -n "def _on_feed_bar_update\|def _schedule_branch_refresh\|def _resolve_branch_worker\|def _on_branch_result\|def _on_project_closed\|def _on_project_opened\|def _on_agent_cycle_clicked\|def _on_autoaccept_cycle_clicked\|def _on_solo_target_changed\|def _on_settings_btn_clicked\|def _on_auto_accept_level_changed\|def _refresh_settings_bar_for_active" ui/window.py`
- `grep -c "_update_project_settings_from_project" ui/window.py` — MUST be 0
- `grep -n "Gtk.ReliefStyle\|set_relief\|for child in list\|escape_for_pango" ui/window.py` — MUST be 0
- `grep -n "_branch_active_token\|_branch_request_token\|_branch_request_path\|_cached_branch_by_path" ui/window.py` — confirm 4 fields
- Run `tests/test_project_handler.py` yourself — confirm 35/35 pass.

## Output format

BUG #[N] format. Sort by severity. End with:
- Pass/fail verdict (ready for Phase I.5, or needs fixes)
- Top 3 must-fix items

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-PHASE-I.4-FINDINGS.md` AND report back here.
