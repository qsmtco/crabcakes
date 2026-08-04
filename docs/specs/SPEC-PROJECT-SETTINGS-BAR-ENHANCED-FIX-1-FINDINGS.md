# Round 2 Re-Audit Findings — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1

**Spec under audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md`
**Original spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Round 1 findings:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md` (18 bugs)
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ❌ **FAIL — the revised spec is not ready to implement.**

## Round 1 verification table

| # | Round 1 finding | Status | Evidence |
|---:|---|---|---|
| 1 | Invented `_auto_accept_state_str` import | ✅ FIXED | Revised spec removes the import and uses `FeedHandler.get_auto_accept_level()`. |
| 2 | `list(Gtk.Box)` iteration | ✅ FIXED | Revised spec introduces `_clear_settings_bar()` using `get_first_child()`. |
| 3 | Empty project leaves bar visible | ✅ FIXED | `update_project_settings()` hides and clears on falsy project name. |
| 4 | Setter bypasses `_refresh_auto_accept_state()` | ✅ FIXED | `set_auto_accept_level()` commits through `_refresh_auto_accept_state()`. |
| 5 | Invented `_settings_dialog` path | ✅ FIXED | Gear callback routes to `MainWindow._open_settings()`. |
| 6 | Invented `_active_project` tuple | ✅ FIXED | Branch worker uses `ProjectHandler.get_active_project_path()`. |
| 7 | Invented `SpecialAgentDef.session_key` | ✅ FIXED | Revised path uses `AgentRuntimeHandler.get_special_agents()` mapping. |
| 8 | GTK3 `set_relief()` / `Gtk.ReliefStyle` | ✅ FIXED | Revised code uses GTK4 `set_has_frame(False)`. |
| 9 | `"files"` and `"all"` indistinguishable | ✅ FIXED | Revised mapping distinguishes files-only from all-four-types. |
| 10 | Summary omitted exec state | ✅ FIXED | Spec explicitly scopes the label to file changes and documents exec as separate. |
| 11 | Warning gate bypass | ✅ FIXED | Enabling states route through `_show_auto_accept_warning`; commit occurs on confirmation. |
| 12 | Detached HEAD unspecified | ✅ FIXED | `(detached HEAD)` is displayed verbatim; failed lookup becomes `—`. |
| 13 | Blocking `get_branch()` on GTK thread | ⚠️ PARTIAL | A worker is specified, but the scheduling condition is wrong and the worker has stale-project races. See BUG #1 and BUG #2. |
| 14 | Wrong architecture citation | ✅ FIXED | Revised spec acknowledges §3.7 was wrong and requires documentation under MainContent's actual section. |
| 15 | Callback dispatch overstated | ⚠️ PARTIAL | Lifecycle call sites are correctly identified, but the proposed solo-change callback is referenced without an implementation/wiring sample. See BUG #4. |
| 16 | Per-tab overlay/reparenting omitted | ⚠️ PARTIAL | Reparenting is mentioned, but asynchronous branch completion is not guarded against tab/project changes. See BUG #2. |
| 17 | One-member cycle called three-state | ✅ FIXED | Revised spec correctly calls it a two-state cycle. |
| 18 | Dead color variable | ✅ FIXED | Revised code removes the dead variable and relies on CSS. |

**13 fixed, 3 partial.**

## New bugs found in Round 2

### BUG #1 — CRITICAL (new in Round 2)
**Assumption violated:** The revised `_on_feed_bar_update()` schedules a background branch refresh when needed.
**Attack vector:** Open any project and inspect the branch refresh path.
**Reproduction:**

```python
if branch_name is None and self._pending_branch_refresh is None \
        and self._project_handler is not None:
    self._schedule_branch_refresh(...)
```

`_pending_branch_refresh` is initialized as `False`, not `None`. Therefore `False is None` is always false, and `_schedule_branch_refresh()` is never called. The branch remains `—`/stale cached data and `get_branch()` is never executed.
**Root cause:** Boolean state is checked with an identity comparison against `None`.
**Fix:**

```python
if (
    branch_name is None
    and not self._pending_branch_refresh
    and self._project_handler is not None
):
```

Add a regression test proving a worker is started when `_pending_branch_refresh == False`.

### BUG #2 — HIGH (new in Round 2)
**Assumption violated:** A background branch result belongs to the project for which it was requested.
**Attack vector:** Open project A, immediately switch/close it, then open project B before the branch worker completes.
**Reproduction:** `_resolve_branch_worker()` receives `project_name` but obtains the path dynamically:

```python
path = self._project_handler.get_active_project_path()
```

The active path may now be project B while the callback still dispatches:

```python
self._on_feed_bar_update(project_name, ..., branch_name=branch)
```

This can display project B's branch in project A's captured update, or update a closed project's bar.
**Root cause:** The worker captures the project name but not the corresponding path/generation, and the completion callback has no active-project identity check.
**Fix:** Capture `project_path` and a refresh generation/token before starting the worker. On the GTK thread, discard results unless the token and active project/path still match.

### BUG #3 — HIGH (new in Round 2)
**Assumption violated:** Auto-accept cycling preserves the current project member count.
**Attack vector:** Open a project with members, click the auto-accept label.
**Reproduction:**

```python
self._on_feed_bar_update(
    self._project_handler.get_active_project_name() or "",
    0,
    auto_accept_level=...,
)
```

The callback passes `member_count=0` unconditionally. The bar then rebuilds as `Project · 0 members` after every auto-accept click.
**Root cause:** The auto-accept callback does not query current members before rebuilding the bar.
**Fix:**

```python
project_name = self._project_handler.get_active_project_name() or ""
members = (
    self._project_handler.get_project_members(project_name)
    if project_name else []
)
self._on_feed_bar_update(
    project_name,
    len(members),
    auto_accept_level=...
)
```

Add a regression test asserting the count remains unchanged after each level transition.

### BUG #4 — HIGH (Round 1 BUG #15 only partially fixed)
**Assumption violated:** Right-click solo-target selection will refresh the settings bar.
**Attack vector:** Right-click a project tab and select a different member or "All."
**Reproduction:** The revised data flow says `ProjectHandler.set_solo_target()` will invoke `_on_solo_target_changed(project_name)`, but the spec does not provide the actual `ProjectHandler` code sample or the `set_on_solo_target_changed()` setter implementation. It only refers to "§2.5," which does not exist in the supplied revised spec structure.

Current source confirms `set_solo_target()` only assigns:

```python
self._solo_targets[project_name] = member_session_key
```

There is no existing callback. Without an exact implementation and window wiring, the bar remains stale after right-click selection.
**Root cause:** The fix is described in prose but omitted from the actionable implementation section.
**Fix:** Add a complete `project_handler.py` sample:

```python
self._on_solo_target_changed: Callable[[str], None] | None = None

def set_on_solo_target_changed(self, cb):
    self._on_solo_target_changed = cb

def set_solo_target(...):
    self._solo_targets[project_name] = member_session_key
    if self._on_solo_target_changed is not None:
        self._on_solo_target_changed(project_name)
```

Then show the exact `window.py` wiring and define callback behavior for a closed/non-active project.

### BUG #5 — MEDIUM (new in Round 2)
**Assumption violated:** Existing `set_project_settings_text()` backward compatibility is preserved.
**Attack vector:** Call the existing method after the new gear button has been initialized.
**Reproduction:** The revised spec says `set_project_settings_text()` should call `_clear_settings_bar()`, then append only a label. It does not reappend `self._settings_btn`. The gear button disappears permanently until a later `update_project_settings()` rebuild. `set_feed_bar_text()` has the same problem.
**Root cause:** Clearing the bar removes the singleton gear widget, but legacy methods rebuild only the old label.
**Fix:** Either preserve the gear button in both legacy methods or explicitly document that legacy calls replace the entire bar. For backward compatibility, append the settings button after the legacy label.

### BUG #6 — MEDIUM (new in Round 2)
**Assumption violated:** A plain project name can safely be passed through `escape_for_pango()`.
**Attack vector:** Create/open a project named `<b>Injected</b>` or containing another supported Pango tag.
**Reproduction:**

```python
safe_name = escape_for_pango(project_name)
name_label.set_markup(f"...<b>{safe_name}</b>...")
```

`escape_for_pango()` intentionally preserves known Pango tags. A project name containing `<b>`, `<span>`, or similar markup is interpreted rather than rendered literally.
**Root cause:** `escape_for_pango()` is for mixed trusted markup, not untrusted plain text.
**Fix:** Use `xml_escape_text(project_name)` for the project name, just as the revised code does for branch text. The claim that `escape_for_pango()` exists is true, but its semantics make it inappropriate here.

### BUG #7 — MEDIUM (new in Round 2)
**Assumption violated:** The branch worker's `_pending_branch_refresh` state is thread-safe and reset reliably.
**Attack vector:** Start a refresh, then trigger another refresh or cause an exception before the idle callback runs.
**Reproduction:** `_pending_branch_refresh` is read/written from both GTK and worker threads without a lock or generation token. The worker sets it to `False` before scheduling `GLib.idle_add()`. A second refresh can begin before the first result is applied, and an older result can overwrite a newer cached branch.
**Root cause:** The boolean is being used as a cross-thread state machine without synchronization or request identity.
**Fix:** Keep all request-state transitions on the GTK thread, or protect them with a lock and use a monotonically increasing request token. Do not rely on a bare boolean for asynchronous project state.

## Additional source verification

- `escape_for_pango()` does exist in `utils/escaping.py`; the revised spec is correct that it remains available.
- `xml_escape_text()` also exists and is the safer choice for plain project/branch strings.
- `AgentRuntimeHandler.get_special_agents()` returns a `dict[str, str]`, so the revised special-agent lookup direction is correct.
- `ProjectHandler.get_active_project_path()` exists.
- `get_branch()` returns `"(detached HEAD)"` with `success=True` for detached HEAD.
- Current `ProjectHandler.set_solo_target()` has no solo-change callback; the new callback is necessary if right-click changes must update the bar.
- Current `MainContent.set_on_project_settings_update()` only stores a callback; it does not itself dispatch updates.
- Current source has no existing `_on_feed_bar_update` richer signature; implementation must add it.

## Summary

**Round 1 fixes:** 13 ✅ FIXED, 3 ⚠️ PARTIAL, 0 ❌ NOT FIXED

**New Round 2 bugs:** 7 (1 CRITICAL, 3 HIGH, 3 MEDIUM, 0 LOW)

**Verdict:** ❌ **FAIL — the revised spec is not ready to implement.**

**Top 3 must-fix items:**

1. Fix the branch scheduling condition from `self._pending_branch_refresh is None` to `not self._pending_branch_refresh`; otherwise branch resolution never runs.
2. Make branch refresh project-safe by capturing the path and using a generation/token check before applying asynchronous results.
3. Fix the auto-accept callback's member count and complete the solo-target callback section: do not pass `0` for the current member count, and provide the missing `ProjectHandler` callback implementation/wiring.
