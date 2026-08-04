# Phase I.2 Audit Request — FeedHandler auto-accept level methods

**Code to audit:** `ui/handlers/feed_handler.py` — new methods:
- `get_auto_accept_level()` (line ~426)
- `set_auto_accept_level()` (line ~448)
- `_commit_auto_accept_level()` (line ~479)
- `_emit_auto_accept_level_changed()` (line ~474) — scope deviation, justified by spec verbatim code
- `_on_auto_accept_level_changed` init field (line ~116) — scope deviation

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` §2.3
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

## Mission

Adversarially probe the 5 new pieces in `ui/handlers/feed_handler.py`. Load `prompts/adversarialDebugger.md` fresh. Work through all 11 sections. This is real state-transition code touching the warning gate, persistence, and view sync.

## Scope-deviation note (already justified by Coder)

The phase delegation asked for 3 methods but the spec §2.3 verbatim code references `self._emit_auto_accept_level_changed(level)` and reads `self._on_auto_accept_level_changed`. The Coder added 2 extra pieces (emit helper + init field) so the spec's code is functional. The callback setter `set_on_auto_accept_level_changed` belongs to Phase I.4 (window wiring), NOT this phase. **Confirm this deviation is correct** (the 3 main methods would otherwise `AttributeError` at runtime).

## Adversarial focus areas

1. **Round-trip correctness.** The 4 states (`off`/`diffs`/`files`/`all`) must be distinct and round-trippable. Trace `set → get` for each. Does `get_auto_accept_level()` correctly read back what `set_auto_accept_level` writes? Specifically: `"files"` sets diff=OFF but file_created/modified/deleted=ON — does `get_auto_accept_level()` return `"files"` (not `"all"` or `"off"`)?

2. **Warning gate routing.** Enabling states (`diffs`/`files`/`all`) must route through `_show_auto_accept_warning`. Does the category match the v2 contract (`"diffs"` or `"files"`)? Does `on_confirm` commit and `on_cancel` NOT commit? Trace both branches.

3. **`_refresh_auto_accept_state()` vs `_save_feed_prefs_idle()`.** The commit must call `_refresh_auto_accept_state()` (which syncs view + debounced save), NOT `_save_feed_prefs_idle()` directly. Verify the code path.

4. **Exec auto-accept untouched.** The 4 new methods must ONLY mutate `self._prefs.file_changes` (the 4 file keys). `exec_command` mode must be untouched. Grep for `exec` in the new code.

5. **Invalid level no-op.** `set_auto_accept_level("bogus")` must be a no-op (no state mutation, no callback fire).

6. **`off` path emits.** The `off` path in `set_auto_accept_level` calls `_refresh_auto_accept_state()` then returns — does it also emit `_emit_auto_accept_level_changed`? The spec FIX-3 §2.3 says `set_auto_accept_level` emits for the `"off"` path. Verify the code matches the spec.

7. **`_emit_auto_accept_level_changed` guard.** Does it guard `self._on_auto_accept_level_changed is not None`? What happens if it's called before window wiring (Phase I.4 hasn't run)?

8. **`_prefs is None` guard.** `set_auto_accept_level` must guard `self._prefs is None`. What happens if `_prefs` is None and level is valid?

9. **The `lambda lvl=level:` default-arg capture.** The `on_confirm=lambda lvl=level: self._commit_auto_accept_level(lvl)` uses a default-arg capture to avoid late-binding. Is this correct? Trace it.

10. **`_resolve_agent_name_for_dialog()`.** Does this method exist on FeedHandler? The warning call passes it as the agent name. Verify it exists and returns a sensible value.

11. **Re-entrancy.** If `on_confirm` is called twice (user double-clicks confirm), does the state stay correct? What if `on_cancel` is called after `on_confirm`?

## Independent verification (run yourself)

- `grep -n "def get_auto_accept_level\|def set_auto_accept_level\|def _commit_auto_accept_level\|def _emit_auto_accept_level_changed\|_on_auto_accept_level_changed" ui/handlers/feed_handler.py`
- Construct a `FeedHandler` with a mock `AutoAcceptPrefs` (no GTK), run the round-trip test, paste the actual output.
- Wire a mock `_show_auto_accept_warning`, run the warning-gate test, paste output.

## Output format

Use the BUG #[N] format from `adversarialDebugger.md`. Sort by severity. End with:
- Pass/fail verdict (ready for Phase I.3, or needs fixes)
- Top 3 must-fix items

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-PHASE-I.2-FINDINGS.md` AND report back here.
