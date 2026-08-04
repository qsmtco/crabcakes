# Audit Findings — SPEC-PROJECT-SETTINGS-BAR-ENHANCED

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Auditor:** Debugger (loaded `prompts/adversarialDebugger.md` fresh)
**Date:** 2026-07-31
**Verdict:** ❌ **FAIL — not ready to implement**

## Summary

**Bug count: 18**
- CRITICAL: 4
- HIGH: 7
- MEDIUM: 5
- LOW: 2

**Top 3 must-fix items:**

1. Remove the nonexistent `_auto_accept_state_str` import and correct the invented APIs/fields (`_active_project`, `AgentDefinition.session_key`, settings-dialog path).
2. Replace all GTK-invalid container iteration and GTK3 button APIs (`list(Gtk.Box)`, `Gtk.ReliefStyle`, `set_relief()`).
3. Redesign auto-accept state handling: preserve distinct `"files"`/`"all"` semantics, include or explicitly exclude exec state, call `_refresh_auto_accept_state()`, and retain the existing warning gate.

---

## BUG #1 — CRITICAL
**Assumption violated:** The proposed `_on_feed_bar_update()` can import `_auto_accept_state_str` from `models.feed_card`.
**Attack vector:** Open any project while `auto_accept_state == "off"` (the default).
**Reproduction:** `from models.feed_card import _auto_accept_state_str` — symbol does not exist.
**Root cause:** Spec self-audit claims this private helper exists, but it does not. Import is also unused.
**Fix:** Remove the import. If a helper is required, define a public, tested API in the owning handler.

## BUG #2 — CRITICAL
**Assumption violated:** GTK4 `Gtk.Box` instances can be converted to lists and iterated with `list(self._project_settings)`.
**Attack vector:** Call `update_project_settings()` or the existing `set_project_settings_text()`.
**Reproduction:** `for child in list(self._project_settings): self._project_settings.remove(child)` — `Gtk.Box` does not provide Python container iteration in PyGObject (same bug class as the `in`-operator fix).
**Root cause:** Spec repeats the unsupported Python iteration pattern.
**Fix:** Use GTK4 sibling walk (`get_first_child()` / `get_next_sibling()`) and `unparent()`, or use the shared helper from `utils/gtk_containers.py`.

## BUG #3 — CRITICAL
**Assumption violated:** The new `update_project_settings()` preserves the existing hidden state when no project is active.
**Attack vector:** Close a project, causing `_on_feed_bar_update(None, 0)`.
**Reproduction:** Proposed implementation always ends with `self._project_settings.set_visible(True)`. `_on_feed_bar_update()` calls `update_project_settings("", 0, None, "off", None)` and returns. The bar becomes visible instead of hidden.
**Root cause:** New method has no empty-project branch, while the existing `_update_project_settings_from_project()` explicitly hides the bar.
**Fix:** `update_project_settings()` must hide and return for an empty project, OR `_on_feed_bar_update()` must explicitly hide the bar.

## BUG #4 — CRITICAL
**Assumption violated:** `FeedHandler.set_auto_accept_state()` updates the handler's complete canonical state.
**Attack vector:** Click the auto-accept control, then create a new actionable feed card.
**Reproduction:** Proposed setter mutates `self._prefs.file_changes`, then calls `self._save_feed_prefs_idle()`. It does not call `_refresh_auto_accept_state()`. Therefore `_auto_accept_enabled` remains stale, FeedTab is not updated, and `_is_card_auto_acceptable()` can continue returning `False` after the UI says auto-accept is enabled.
**Root cause:** Spec bypasses the existing state-transition method that synchronizes derived state, the view, and persistence.
**Fix:** Call `_refresh_auto_accept_state()` after mutation. Do not invoke the persistence helper as a substitute.

## BUG #5 — HIGH
**Assumption violated:** The proposed settings-dialog callback can find the existing settings dialog through `self._settings_dialog`.
**Attack vector:** Click the new ⚙ button.
**Reproduction:** `ui/window.py` constructs `SettingsHandler` and wires the toolbar to `_open_settings`, but the reviewed window construction does not establish the proposed `_settings_dialog` attribute. The callback silently does nothing when the attribute is absent.
**Root cause:** Spec confuses the existing settings-opening path with a persistent `_settings_dialog` instance.
**Fix:** Reuse `_open_settings()` or route the button to the actual settings handler/dialog factory used by the toolbar.

## BUG #6 — HIGH
**Assumption violated:** `window.py` owns an `_active_project` tuple `(name, path)`.
**Attack vector:** Open a project and allow `_on_feed_bar_update()` to resolve the branch.
**Reproduction:** Spec checks `hasattr(self, "_active_project")` and indexes `self._active_project[1]`. The actual project state is owned by `ProjectHandler` as `_active_project_name` and `_active_project_path`, with public accessors such as `get_active_project_path()`. The spec's tuple is not established on `MainWindow`.
**Root cause:** Branch lookup targets an invented window field.
**Fix:** Use `self._project_handler.get_active_project_path()` and handle `None`.

## BUG #7 — HIGH
**Assumption violated:** The local-special-agent fallback uses an `AgentDefinition.session_key` attribute.
**Attack vector:** Run offline with a project member that is a special agent and no connected `AgentManager`.
**Reproduction:** `for agent_def in ...: if agent_def.session_key == session_key:` — the existing code identifies special agents using `conv_id_prefix`; the reviewed window code uses `agent_def.conv_id_prefix` for this purpose. `session_key` is not established by the actual special-agent definition contract.
**Root cause:** Spec invents the wrong field name.
**Fix:** Use the actual special-agent identifier (`conv_id_prefix`) and add a test for offline/local members.

## BUG #8 — HIGH
**Assumption violated:** `Gtk.ReliefStyle` and `Gtk.Button.set_relief()` are valid GTK4 APIs.
**Attack vector:** Construct `MainContent`.
**Reproduction:** Spec uses `set_relief(Gtk.ReliefStyle.NONE)` repeatedly. GTK4 removed the GTK3 relief API. Existing code uses GTK4-compatible `set_has_frame(False)` instead.
**Root cause:** Spec copied a GTK3 button API into GTK4 code.
**Fix:** Use `set_has_frame(False)` and CSS classes.

## BUG #9 — HIGH
**Assumption violated:** Auto-accept state changes can be represented by four distinct persisted states using the existing file-change preferences.
**Attack vector:** Click through `off → files → diffs → all`, then refresh or reopen the project.
**Reproduction:** Both `"files"` and `"all"` set all four file-change entries to `enabled=True`. `get_auto_accept_summary()` then returns `"all"` for either state, so `"files"` cannot remain distinguishable.
**Root cause:** Spec explicitly maps two UI states to the same underlying representation.
**Fix:** Define separate semantics or remove one state. If `"files"` and `"all"` are intended to differ, specify the exact file-type mapping and persist it.

## BUG #10 — HIGH
**Assumption violated:** `get_auto_accept_summary()` reports the complete auto-accept state.
**Attack vector:** Enable exec auto-accept while all file-change types are disabled.
**Reproduction:** `AutoAcceptPrefs.any_enabled()` includes `exec_command`, but the proposed summary only inspects `self._prefs.file_changes`. It returns `"off"` even when exec auto-accept is active.
**Root cause:** The new summary API silently ignores an existing auto-accept category.
**Fix:** Either define the bar as file-change-only and document that explicitly, or include exec mode in the state model. Do not call the result a complete auto-accept summary if it omits exec.

## BUG #11 — HIGH
**Assumption violated:** Clicking the new auto-accept control preserves the existing warning/approval safety behavior.
**Attack vector:** Click from `"off"` to `"files"` or `"all"`.
**Reproduction:** `_on_autoaccept_cycle_clicked()` directly invokes `set_auto_accept_state(next_state)`. Existing FeedHandler toggle methods invoke the injected warning callback before enabling file auto-accept.
**Root cause:** Spec adds a second activation path that bypasses the warning dialog.
**Fix:** Route activation through FeedHandler's existing warning-aware methods, or explicitly add warning handling to the new setter/cycle path.

## BUG #12 — MEDIUM
**Assumption violated:** `get_branch()` returns `stdout="main"` or an error for all non-normal repository states.
**Attack vector:** Use a detached HEAD or an unborn repository.
**Reproduction:** `utils/git_ops.get_branch()` returns `GitResult(success=True, stdout="(detached HEAD)", error="")` for detached HEAD. It may return a failure for an unborn branch.
**Root cause:** Spec omits the actual detached-HEAD contract and does not define how the UI should display it.
**Fix:** Document and test detached HEAD explicitly; decide whether to display `(detached HEAD)` or `—`.

## BUG #13 — MEDIUM
**Assumption violated:** `get_branch()` is safe to call synchronously from the GTK main thread.
**Attack vector:** Use a slow, inaccessible, network-mounted, or damaged repository.
**Reproduction:** Spec invokes `get_branch()` directly inside `_on_feed_bar_update()`. The audit request itself acknowledges a possible 10-second timeout.
**Root cause:** A potentially blocking GitPython operation is placed in a UI callback.
**Fix:** Resolve branch state in a background worker and dispatch the result back with `GLib.idle_add()`, or use a cached branch value and refresh asynchronously.

## BUG #14 — MEDIUM
**Assumption violated:** The architecture citations identify the correct owning modules.
**Attack vector:** Implement according to the cited sections and public-API documentation.
**Evidence:** `docs/ARCHITECTURE.md` §3.7 documents `ui/views/left_panel.py`, not `ui/views/main_content.py`. The spec says §3.7 documents the new MainContent API.
**Root cause:** Spec's architecture references are stale/misassigned.
**Fix:** Correct the cited section and add the MainContent API under the actual MainContent responsibility section.

## BUG #15 — MEDIUM
**Assumption violated:** The `set_on_project_settings_update` signature is the actual event contract that must be extended.
**Attack vector:** Search all call sites and invoke project lifecycle updates.
**Evidence:** `MainContent.set_on_project_settings_update()` only stores a callback; lifecycle callbacks in `MainWindow` directly invoke `_on_feed_bar_update()` from project-open, project-close, and member-change handlers. The spec's claim that an existing callback "fires with new solo_target" is not true without additional wiring in `ProjectHandler`/`MainWindow`.
**Root cause:** Spec conflates callback registration with callback dispatch and overstates existing behavior.
**Fix:** Specify the actual lifecycle call sites and define which component owns each state lookup.

## BUG #16 — MEDIUM
**Assumption violated:** The project settings bar is a singleton in a stable parent.
**Attack vector:** Open multiple tabs and switch between them while the project bar is visible.
**Evidence:** `MainContent._on_notebook_switch_page()` reparents `_project_settings` between per-tab `Gtk.Overlay` instances using `unparent()`. The spec's rebuild logic assumes a stable parent and does not address updates racing with reparenting.
**Root cause:** Spec omits the existing per-tab overlay lifecycle.
**Fix:** State the reparenting invariant, ensure updates occur on the GTK main thread, and test switching tabs during bar updates.

## BUG #17 — LOW
**Assumption violated:** A one-member project has a distinct three-state cycle `ALL → member → ALL`.
**Attack vector:** Click repeatedly with exactly one member.
**Evidence:** There are only two distinct states: `None`/ALL and the one member. The spec's "3-state" wording contradicts its own two-state logic.
**Root cause:** The acceptance/edge-case language is internally inconsistent.
**Fix:** Describe this as a two-state cycle for one member and a `(N + 1)`-state cycle generally.

## BUG #18 — LOW
**Assumption violated:** The proposed agent label's computed `color` variable controls rendering.
**Attack vector:** Inspect the generated widget styling.
**Evidence:** The implementation computes `color = "#4ade80"` but never applies it to markup or a CSS provider. The CSS class supplies a fixed color.
**Root cause:** Dead variable and misleading implementation sample.
**Fix:** Remove `color`, or apply the intended agent-specific color through a supported CSS/attribute mechanism.
