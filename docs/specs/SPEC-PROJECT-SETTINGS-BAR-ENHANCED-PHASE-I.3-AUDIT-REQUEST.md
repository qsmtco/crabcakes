# Phase I.3 Audit Request — MainContent settings bar widget refactor

**Code to audit:** `ui/views/main_content.py` — new methods + legacy fixes:
- `_clear_settings_bar()` (line ~273)
- `update_project_settings(...)` (line ~278)
- `_resolve_agent_display_name(...)` with `.get()` + truthiness (line ~348)
- `_on_agent_label_clicked`, `_on_autoaccept_label_clicked`, `_on_settings_btn_clicked` (lines ~374/379/384)
- `set_on_settings_clicked`, `set_on_agent_cycle`, `set_on_autoaccept_cycle` (lines ~388/391/394)
- `_settings_btn` init in `__init__` (line ~136)
- Fixed `set_project_settings_text` and `set_feed_bar_text` (lines ~398, ~416 — sibling-walk + gear re-append)

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` §2.1
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

## Mission

Adversarially probe the new MainContent code. Load `prompts/adversarialDebugger.md` fresh. Work through all 11 sections. This touches GTK4 widget construction, Pango markup, button click handlers, and the gear-preservation invariant.

## Known out-of-scope item (already flagged for Phase I.4)

The legacy `_update_project_settings_from_project` method (still called by window.py:1055) still uses `escape_for_pango(project_name)` — the BUG #6 injection pattern. This is correctly out of I.3 scope; Phase I.4 retires it by re-pointing `_on_feed_bar_update` to the new `update_project_settings`. **Do NOT report this as a bug** — it's a known, tracked follow-up. Focus on the NEW code.

## Adversarial focus areas

1. **`_clear_settings_bar` sibling-walk.** Verify it's `while get_first_child() is not None: remove(get_first_child())` — NOT `for child in list(...)`. GTK4 `Gtk.Box` is iterable-but-not-with-Python-`list()`.

2. **Empty-project branch.** `update_project_settings("", 0, None, "off", None)` must hide the bar AND clear it (not just hide, not just clear — both).

3. **`xml_escape_text` coverage.** The project name AND the branch text must be `xml_escape_text`'d (not `escape_for_pango` — Round 2 BUG #6). The agent/auto button labels are plain `Gtk.Button` labels (NOT Pango markup), so they don't need escaping — but verify that's actually the case.

4. **Gear-preservation in legacy methods.** `set_project_settings_text` and `set_feed_bar_text` must re-append `self._settings_btn` after `_clear_settings_bar()`. If the gear is missing, it disappears permanently until the next `update_project_settings` call.

5. **`_resolve_agent_display_name` fallback.** Round 3 BUG #7: uses `.get()` + truthiness, NOT `if sk in special`. An empty/None value in the special-agents dict must fall through to the session_key, not return a blank label.

6. **Click-handler wiring.** The 3 click handlers connect to `_on_agent_cycle`, `_on_autoaccept_cycle`, `_on_settings_clicked` — all default to None. Verify they're guarded with `is None` checks.

7. **`_settings_btn` init invariants.** `set_has_frame(False)`, `set_focus_on_click(False)`, `add_css_class("project-bar-gear")`, `set_margin_end(8)`, `connect("clicked", ...)`. No `set_relief` / `Gtk.ReliefStyle` (GTK3, removed in GTK4).

8. **Pango markup structure.** The `name_label.set_markup(...)` f-string — is it well-formed? `xml_escape_text` on project name, then `<span font_desc="Sans 10"><b>...</b>  ·  N members</span>`. Trace it for a project name like `<b>oops</b>` — does it render literally (not bolded)?

9. **Agent label text.** `Gtk.Button(label=agent_text)` where `agent_text` is either "ALL" or `_resolve_agent_display_name(solo_target)`. For special agents offline, this resolves via the ARTH dict. For gateway agents, via `_agent_mgr.get_name`. For neither, falls back to the raw session_key (which could contain `:` — safe for plain label, but ugly).

10. **Lambda capture in click handlers.** The spec uses `lambda _b: self._on_agent_label_clicked(solo_target)`. This captures `solo_target` at bar-build time. If `solo_target` changes after the bar is built (but before the user clicks), does the click fire with the OLD value? (This is actually correct behavior — the button reflects the bar's state at build time. But verify the click handler is consistent.)

## Independent verification (run yourself)

- `grep -n "def _clear_settings_bar\|def update_project_settings\|def _resolve_agent_display_name\|def _on_agent_label_clicked\|def set_on_settings_clicked" ui/views/main_content.py` — confirm 9 definitions.
- `grep -n "Gtk.ReliefStyle\|set_relief\|for child in list" ui/views/main_content.py` — confirm 0 matches (comments documenting the absence are OK).
- Construct a fake `Gtk` and run `update_project_settings` with a few inputs; check the child count and visibility.

## Output format

BUG #[N] format from `adversarialDebugger.md`. Sort by severity. End with:
- Pass/fail verdict (ready for Phase I.4, or needs fixes)
- Top 3 must-fix items

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-PHASE-I.3-FINDINGS.md` AND report back here.
