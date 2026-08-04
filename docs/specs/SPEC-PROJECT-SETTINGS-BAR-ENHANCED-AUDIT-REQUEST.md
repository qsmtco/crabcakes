# Spec Audit Request — SPEC-PROJECT-SETTINGS-BAR-ENHANCED

**Spec to audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

Adversarially audit the spec at `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md` against the actual codebase. You are NOT verifying the code works — you are proving the spec is wrong. Find every way the spec's assumptions are broken, every code sample that won't actually run, every function signature that doesn't match reality, every edge case the spec didn't consider, every architectural violation the spec papered over.

The implementer (Coder) will follow this spec verbatim. If the spec is wrong, the implementation is wrong. Be ruthless.

**Files to verify** (use `read_file` with `offset`/`limit` or `search_files`):
- `ui/views/main_content.py` — spec cites 118-140, 258-271, 319, 695-755
- `ui/window.py` — spec cites 435, 522-562, 1053-1066
- `ui/handlers/feed_handler.py` — spec cites 96-111
- `ui/handlers/project_handler.py` — spec cites 127, 364, 376
- `ui/views/session_menu.py` — spec cites 117-145
- `ui/styles.py` — spec cites line 33
- `utils/git_ops.py` — spec cites line 87 (get_branch)
- `models/feed_card.py` — spec cites _prefs.file_changes structure and `_auto_accept_state_str`
- `docs/ARCHITECTURE.md` — spec cites §2, §3.6, §3.7, §3.16, §7, §13.4

**Adversarial focus areas:**

1. Stale line numbers / wrong signatures. Spec cites `feed_handler.py:96-111` for `set_on_project_settings_update` etc. — does that match? Spec cites `project_handler.py:127` for `get_project_members` — actually at 282.
2. Invented APIs. Spec introduces `get_auto_accept_summary`, `set_auto_accept_state`, `set_on_settings_clicked`, `set_on_agent_cycle`, `set_on_autoaccept_cycle`, etc. Do they exist?
3. Wrong import paths. Spec says `from models.feed_card import _auto_accept_state_str` — does that symbol exist? If not, the import will fail.
4. `get_branch` behavior. Spec assumes it returns `GitResult(success=True, stdout="main")`. Read the actual function — does it return that, or something else? What about unborn HEAD? Detached HEAD? Path with no .git?
5. `get_project_members` return shape. Spec assumes a list of session_keys. Is that what it returns?
6. `get_solo_target` return type. Spec assumes `str | None`. Verify.
7. `_on_feed_bar_update` call sites. Spec says lines 540, 554, 561, 1046 call `_on_feed_bar_update`. Do they? If the signature changes, do they break?
8. CSS class conflict. Spec adds `.project-bar-agent`, `.project-bar-autoaccept`, `.project-bar-gear`. Run `grep -n "project-bar" ui/styles.py` — do these exist already? Collision risk?
9. Auto-accept "all" vs "files" mapping. Both map to "all four enabled". The cycle should be distinguishable. Design defect?
10. `_on_feed_bar_update` backward compat. Defaults fill in, but trace each call site with the defaults — do they produce wrong state?
11. Agent label click cycling with 1 member. Spec §7 says "3-state cycle: ALL → member → ALL" but spec §2.2 logic is 2-state when members=1. Verify contradiction.
12. Threading. Spec calls `get_branch()` on the main thread in `_on_feed_bar_update`. Is that safe? Spec says it can be slow (10s timeout). Will this freeze the UI?
13. `_save_feed_prefs_idle()` — does this method exist on `FeedHandler`? If not, the persistence claim is wrong.
14. Missing ARCHITECTURE.md citations. Spec says §3.7, §3.16, §3.6 — do those sections exist?
15. Glyphs in Pango. Spec uses ⚡, ⎇, ⚙. Are any known to break Pango? (We've had Pango issues before — see the bug journal.)
16. **Per-tab reparenting.** `_project_settings` is per-tab (`_tab_project_settings[page_idx]`) with overlay reparenting in `_on_notebook_switch_page` (uses `widget.unparent()` because `Gtk.Overlay` has no `.remove()`). Spec treats it as a singleton — structural conflict.
17. **`escape_for_pango` rename.** Renamed to `xml_escape_text` per recent refactor. Spec still uses the old name.
18. **Dead import.** `from models.feed_card import _auto_accept_state_str` — underscore prefix, not used anywhere.

**Output format** (per `prompts/adversarialDebugger.md`):

```
BUG #[N]
Severity: [CRITICAL/HIGH/MEDIUM/LOW]
Assumption violated: [what the spec assumed]
Attack vector: [how to break it]
Reproduction: [exact steps to reproduce — file/line/code]
Root cause: [why the spec is wrong]
Fix: [what the spec needs to change]
```

Sort by severity (CRITICAL first). At the end, add a **Summary** section:
- Total bug count by severity
- Pass/fail verdict: is this spec ready to implement, or does it need fixes?
- Top 3 must-fix items if any CRITICAL or HIGH bugs

**Do NOT delegate. Do NOT modify the spec. Do NOT implement. Audit only.** Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md` AND report back here.

If the spec is clean (or only has LOW/cosmetic issues), say so explicitly with evidence. Don't manufacture bugs to look thorough.
