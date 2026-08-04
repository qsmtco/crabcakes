# Round 3 Re-Audit Findings — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2

**Spec under audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md`
**Previous spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md`
**Round 2 findings:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-FINDINGS.md` (7 bugs)
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ❌ **FAIL — not ready for implementation. Re-fix round required.**

## Round 2 verification table

| # | Round 2 finding | Status | Evidence |
|---:|---|---|---|
| 1 | Branch scheduling used `bool is None` dead check | ✅ FIXED | FIX-2 initializes `_branch_active_token: int \| None = None` and checks `self._branch_active_token is None`. |
| 2 | Branch results could cross project boundaries | ⚠️ PARTIAL | Path and token are captured and checked, and active-project name is checked. However, stale results can still write `_cached_branch` before the active-project check; project-open invalidation is also not clearly specified. See BUG #2. |
| 3 | Auto-accept callback passed member count `0` | ✅ FIXED | `_on_autoaccept_cycle_clicked()` queries current members and passes `len(members)`. |
| 4 | Solo-target callback implementation/wiring incomplete | ⚠️ PARTIAL | Complete slot, setter, `set_solo_target()` sample, and window registration are present. However, the stated "known/active project" behavior is not implemented, and the callback does not refresh auto-accept/branch state explicitly. See BUG #3. |
| 5 | Legacy methods dropped gear button | ✅ FIXED | Both `set_project_settings_text()` and `set_feed_bar_text()` append `self._settings_btn`. |
| 6 | `escape_for_pango()` used for untrusted project names | ✅ FIXED | Project and branch strings use `xml_escape_text()`. No remaining `escape_for_pango(project_name)` or `escape_for_pango(branch_text)` appears in the revised samples. |
| 7 | Branch refresh bool was not thread-safe | ✅ FIXED | The bool is replaced with integer request/active tokens. Worker reads captured data and dispatches through `GLib.idle_add`; window state changes are specified on the GTK thread. |

**Round 2 status:** 4 fully fixed, 2 partial, 1 fully fixed but with a related new lifecycle defect.

## New bugs found in Round 3

### BUG #1 — CRITICAL
**Assumption violated:** The project-close token invalidation sample can be inserted into the existing lifecycle callback.
**Attack vector:** Implement the instructions literally in the existing project-closed callback.
**Reproduction:** The existing callback is a tuple-returning lambda:

```python
self._project_handler.set_on_project_closed(
    lambda name: (
        self._feed_handler.on_project_closed(name),
        ...
        self._on_feed_bar_update(None, 0),
        clear_active_project_path(),
    )
)
```

FIX-2 instructs the implementer to append statements such as:

```python
self._branch_request_token += 1
self._branch_active_token = None
self._branch_request_path = None
self._cached_branch = None
```

inside that lambda. Assignment statements cannot appear inside a lambda, so literal implementation is a `SyntaxError`.
**Root cause:** The spec describes imperative invalidation code but the actual callback is an expression-only tuple lambda.
**Fix:** Require a named `_on_project_closed(name)` method, or add a dedicated `ProjectHandler` close callback helper that performs invalidation before/after the existing lifecycle operations.

### BUG #2 — HIGH (Round 2 BUG #2 only partially fixed)
**Assumption violated:** A stale branch result cannot contaminate the active project's cached branch.
**Attack vector:** Resolve project A asynchronously, then switch to project B before the worker completes.
**Reproduction:** `_on_branch_result()` performs:

```python
if token != self._branch_request_token \
        or path != self._branch_request_path:
    return
self._cached_branch = branch

current_name = self._project_handler.get_active_project_name()
if current_name != project_name:
    return
```

If project B becomes active without token/path invalidation, the token and path checks can pass, then `_cached_branch` is set to project A's branch before the active-name mismatch returns. The next B refresh displays A's cached branch until another worker completes.
**Root cause:** The cached branch is assigned before validating the active project identity. Also, FIX-2 only explicitly bumps the token on close; it does not define an open-project/switch invalidation path.
**Fix:** Check the active project name and active path before assigning `_cached_branch`. Invalidate/bump the token and clear cache whenever a new project opens or becomes active, not only when one closes.

### BUG #3 — HIGH (Round 2 BUG #4 only partially fixed)
**Assumption violated:** `set_solo_target()` only fires for a known/active project, as its docstring and spec claim.
**Attack vector:** Call `set_solo_target("deleted-project", "agent:x")`, or select a stale project menu after the project closes.
**Reproduction:** The proposed implementation is:

```python
old = self._solo_targets.get(project_name)
if old == member_session_key:
    return
self._solo_targets[project_name] = member_session_key
if self._on_solo_target_changed is not None:
    self._on_solo_target_changed(project_name)
```

There is no known-project or active-project check. Any arbitrary project name creates state and fires the callback.
**Root cause:** The implementation does not match its stated "known/active project" contract.
**Fix:** Validate the project against project membership/storage, or make the contract explicitly "any named project." The window callback must also ignore updates for non-active projects.

### BUG #4 — HIGH
**Assumption violated:** The settings bar reflects a newly confirmed auto-accept level when the warning dialog is asynchronous.
**Attack vector:** Click `off → diffs/files/all` while the warning dialog is wired.
**Reproduction:**

1. `_on_autoaccept_cycle_clicked()` calls `FeedHandler.set_auto_accept_level(next_level)`.
2. `set_auto_accept_level()` displays the warning and does not commit yet.
3. The window immediately calls `_on_feed_bar_update(...)`.
4. `get_auto_accept_level()` still returns the old level, so the bar remains `off`.
5. User confirms; `_commit_auto_accept_level()` calls `_refresh_auto_accept_state()`, which updates FeedTab/persistence but does not notify `MainWindow` to rebuild this bar.

The indicator remains stale until another unrelated project update.
**Root cause:** The new FeedHandler commit path has no callback to refresh the settings bar after asynchronous confirmation.
**Fix:** Add an `on_auto_accept_level_changed` callback, or make the cycle handler update the bar from the confirmation callback after commit. The bar should not be optimistically rebuilt before confirmation.

### BUG #5 — MEDIUM
**Assumption violated:** `_cached_branch` represents the active project.
**Attack vector:** Open project A, resolve its branch, then open project B without a close callback.
**Reproduction:** `_cached_branch` is documented as "last successfully resolved branch for the ACTIVE project," but it is not keyed by project path and is not cleared in the project-open path. If `_on_feed_bar_update()` runs for B before a new branch worker completes, it passes the cached A branch to `update_project_settings()`.
**Root cause:** A single unkeyed cache is used across projects, while the scheduling condition only checks the active token, not cache ownership.
**Fix:** Store `(project_path, branch)` or clear the cache and invalidate the token on every project open. Only display a cached branch when its path matches the active project path.

### BUG #6 — MEDIUM
**Assumption violated:** Branch refreshes are started only when a current branch is unavailable.
**Attack vector:** Trigger repeated member changes or solo-target changes after a branch has already resolved.
**Reproduction:** `_on_feed_bar_update()` schedules whenever:

```python
branch_name is None and self._branch_active_token is None
```

It does not check whether `_cached_branch` belongs to the current project. After every lifecycle update, the worker can be launched again even when the current project's branch is already cached.
**Root cause:** The FIX-2 comment says "if we don't yet have a cached branch for the CURRENT project," but the condition does not test the cache or cache path.
**Fix:** Track the cached path and skip scheduling when it matches the active project path. If periodic refresh is desired, specify an explicit timer/invalidation policy instead of accidental repeated subprocess calls.

### BUG #7 — MEDIUM
**Assumption violated:** The special-agent fallback is robust when the handler mapping contains missing or non-string values.
**Attack vector:** Use an offline special-agent mapping where the key exists but its value is empty or `None`.
**Reproduction:**

```python
if session_key in special:
    return special[session_key]
```

This returns `None` or an empty string instead of falling through to the session key. `Gtk.Button(label=None)` or an empty label can result in a blank agent indicator.
**Root cause:** The fallback tests key membership, not the returned display-name value.
**Fix:**

```python
name = special.get(session_key)
if name:
    return name
return session_key
```

## Fresh adversarial probe notes

- **GTK APIs:** `set_has_frame(False)` is appropriate for GTK4; no `Gtk.ReliefStyle`, `set_relief()`, or `Gtk.Container` remains in the proposed code.
- **Pango:** `xml_escape_text()` is the correct utility for project and branch strings. Button labels are plain text, so agent/auto labels are safe from Pango markup injection.
- **Token design:** A monotonic Python integer is suitable; overflow is not a practical concern. The worker correctly avoids mutating token state directly.
- **Solo callback:** A dedicated `set_on_solo_target_changed` hook is appropriate because existing `set_on_members_changed` does not fire for right-click solo selection. However, the callback must be guarded against stale/non-active project names.
- **Scope:** The five-file scope is plausible: `main_content.py`, `window.py`, `feed_handler.py`, `project_handler.py`, and `styles.py`. The project-handler change is additive in principle, but the spec's close-invalidation change must be implemented through a named callback rather than invalid lambda syntax.

## Summary

**Round 2 fixes:** 4 ✅ FIXED, 2 ⚠️ PARTIAL, 1 fully fixed but with related new defect.

**New Round 3 bugs:** 7 (1 CRITICAL, 3 HIGH, 3 MEDIUM, 0 LOW)

**Verdict:** ❌ **FAIL — not ready for implementation. Re-fix round required.**

**Top 3 must-fix items:**

1. Replace the invalid project-close lambda assignment instructions with a syntactically valid named callback/helper.
2. Fix asynchronous branch lifecycle handling: invalidate on project open/switch, verify active name/path before assigning `_cached_branch`, and key/clear the cache by project path.
3. Add a post-confirmation auto-accept callback so the bar updates after the warning dialog commits the new level.

**Recommended next step:** **Re-fix round required** before implementation. The next revision should specifically include executable lifecycle code for project close/open, a path-keyed branch cache/token state machine, and an asynchronous auto-accept confirmation-to-bar update path.
