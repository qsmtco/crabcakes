# Loop State — SPEC-PROJECT-SETTINGS-BAR-ENHANCED

**Spec:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md` (29 KB)
**Audit request:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-AUDIT-REQUEST.md`
**Working dir:** `/home/q/projects/crabcakes`

**Loop protocol (per `prompts/implementationSupervisor.md`):**
spec → audit by Debugger → fix by Coder (if bugs) → re-audit → clean → phased implementation (per phase) → audit each phase → final post-mortem.

## Phases of the loop

### Phase S — Spec audit loop (in progress)
1. ⏳ Round 1: Debugger audits spec → findings doc
2. ⏸️ Round 1 fixes (Coder, if bugs found)
3. ⏸️ Round 2: re-audit (if fixes were needed)
4. ⏸️ ... repeat until spec clean

### Phase I — Implementation (only after Phase S is clean)
- I.1 CSS (low-risk, no deps)
- I.2 FeedHandler methods (low-risk, isolated)
- I.3 MainContent widget construction (mid-risk, view changes)
- I.4 Window.py wiring (HIGH-risk — integration, multi-edit)
- I.5 Tests (per phase as needed)
- I.6 ARCHITECTURE.md update

Each implementation phase gets its own audit by Debugger before moving to the next.

## Round 1 — Spec audit dispatched

**Status:** ✅ AUDIT COMPLETE (18 findings, verdict FAIL) → **Round 1 fixes DONE** (by Coder) → awaiting Round 2 re-audit.

**Findings file:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md` (18 bugs: 4 CRIT, 7 HIGH, 5 MED, 2 LOW)

**Round 1 fixes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md` (NEW, supersedes the original spec). All 18 findings addressed — see §9 table. Key corrections:
- Removed nonexistent `_auto_accept_state_str` import (BUG #1)
- Replaced `list(Gtk.Box)` with `_clear_settings_bar()` sibling-walk (BUG #2)
- `update_project_settings` hides bar on empty project (BUG #3)
- Auto-accept commits via `_refresh_auto_accept_state()` + warning gate (BUG #4/#11)
- Distinct round-trippable states off/diffs/files/all (BUG #9) — **empirically verified**: 4/4 set→get and 4/4 persist→get round-trips OK via probe
- Branch via `get_active_project_path()` background thread (BUG #6/#13), detached HEAD handled (BUG #12)
- Agent name via `ARTH.get_special_agents()` dict, no `session_key` attr (BUG #7) — **empirically verified**: SpecialAgentDef has no `session_key`, uses `conv_id_prefix`
- ⚙ via `_open_settings()` fresh dialog (BUG #5); `set_has_frame(False)` not relief (BUG #8)

**Audit request file:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-AUDIT-REQUEST.md`

## Round 2 — Spec re-audit dispatched

**Status:** ✅ ROUND 2 AUDIT COMPLETE (7 findings: 1 CRIT, 3 HIGH, 3 MED, verdict FAIL) → **Round 2 fixes DONE** (by Coder) → awaiting Round 3 re-audit.

**Round 2 findings:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-FINDINGS.md` (7 bugs)
- #1 CRIT: branch scheduling dead-code (`is None` on a bool — worker never ran)
- #2 HIGH: async branch results crossing project boundaries
- #3 HIGH: auto-accept callback clobbered member count to 0
- #4 HIGH: missing `ProjectHandler.set_on_solo_target_changed` code sample + wiring
- #5 MED: legacy `set_project_settings_text`/`set_feed_bar_text` dropped the gear button
- #6 MED: `escape_for_pango` injection risk (preserves `<b>`)
- #7 MED: `_pending_branch_refresh` boolean not thread-safe

**Round 2 fixes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md` (NEW, supersedes FIX-1). All 7 addressed — see §9 table. Key corrections:
- Branch schedule guard `_branch_active_token is None` (token-based, not bool-`is-None`) (BUG #1)
- Worker captures `project_path` + monotonic `request_token`; `_on_branch_result` discards stale results (BUG #2/#7); project-closed invalidation bumps token
- Auto-accept callback reads real `len(get_project_members(project_name))` (BUG #3)
- Complete `ProjectHandler` `_on_solo_target_changed` slot + setter + fire in `set_solo_target`; window wiring sample (BUG #4)
- Gear re-appended in both legacy methods (BUG #5)
- `xml_escape_text` for project name/branch; `Gtk.Button` labels are plain text (BUG #6) — **empirically probed**: `escape_for_pango('<b>x</b>')` preserves `<b>`, `xml_escape_text` neutralizes
- **Empirically verified:** `ProjectHandler.set_solo_target` (line 376) currently has NO callback — new slot is genuinely additive

**Pre-flight verification (what I confirmed before dispatching):**

| Spec claim | Verified | Note |
|------------|----------|------|
| `get_solo_target` at project_handler.py:364 | ✅ | Signature `(project_name: str) -> str \| None` ✓ |
| `set_solo_target` at project_handler.py:376 | ✅ | Signature `(project_name, member_session_key: str \| None)` ✓ |
| `get_project_members` at project_handler.py:127 | ❌ | Actually at line **282** (off by 155). Code is correct, spec line number is stale. |
| `get_branch` at git_ops.py:87 | ✅ | But spec omits the `(detached HEAD)` case (line 64-65: `return GitResult(success=True, stdout="(detached HEAD)", error="")`). Spec only models the normal case. |
| `get_branch` returns `GitResult(success=True, stdout="main")` | ⚠️ | True for normal branches, but returns `"(detached HEAD)"` string for detached HEAD — bar will display literal text "(detached HEAD)" if that case hits. Spec doesn't address. |
| `escape_for_pango` import | ❌ | Renamed to `xml_escape_text` per recent refactor (`.crabcakes/feed.json:1358495`). Spec still uses the old name. Import will likely fail or be aliased. |
| `from models.feed_card import _auto_accept_state_str` | ❌ | Underscore-prefixed name. Not used anywhere in the codebase per `search_files`. Unused dead import in `_on_feed_bar_update` (the actual logic uses `get_auto_accept_summary()`). |
| `_project_settings` lifecycle | ⚠️ | Spec treats as singleton. Actual code has `_tab_project_settings[page_idx]` per-tab dict with overlay reparenting in `_on_notebook_switch_page` (uses `widget.unparent()` because `Gtk.Overlay` has no `.remove()`). The spec's `update_project_settings` will need to update ALL per-tab bars, not a singleton. |
| Spec self-audit claims "verified" | ❌ | Spec self-audit claims all signatures verified. Three claims are wrong/stale (above). |
| `Gtk.Overlay.remove` works | ❌ | GTK4's `Gtk.Overlay` is not a `Gtk.Container`; it has no `.remove()`. Spec's `for child in list(self._project_settings): self._project_settings.remove(child)` — this works at the **box** level (not overlay), since `self._project_settings` is the `Gtk.Box`. OK. But the per-tab reparenting uses `unparent()`, not `.remove()`. Spec doesn't address the per-tab dance. |

## Round 3 — Spec re-audit dispatched

**Status:** ✅ ROUND 3 AUDIT COMPLETE (7 findings: 1 CRIT, 3 HIGH, 3 MED, verdict FAIL) → **Round 3 fixes DONE** (by Coder) → awaiting Round 4 re-audit.

**Round 3 findings:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2-FINDINGS.md` (7 bugs)
- #1 CRIT: project-close invalidation inserted into existing tuple lambda → `SyntaxError` (assignments inside lambda are illegal)
- #2 HIGH: stale branch result writes `_cached_branch` before active-project check; no open/switch invalidation
- #3 HIGH: `set_solo_target()` doesn't validate the project name (contract mismatch)
- #4 HIGH: bar doesn't update after async auto-accept warning confirmation
- #5 MED: `_cached_branch` not keyed by project
- #6 MED: branch refresh condition doesn't check cache ownership
- #7 MED: special-agent fallback returns `None`/`""` for empty values

**Round 3 fixes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` (NEW, supersedes FIX-2). All 7 addressed — see §9 table. Key corrections:
- **BUG #1 (CRIT):** project-close/open invalidation moved into NAMED `_on_project_closed(name)` / `_on_project_opened(name, path)` methods, registered as their OWN `set_on_project_closed`/`set_on_project_opened` callbacks (handler is append-based, multi-callback — verified). The existing tuple lambdas are left untouched.
- **BUG #2:** `_on_branch_result` runs ALL checks (token, path, active-name, active-path) BEFORE writing the cache; open/switch invalidation added via `_on_project_opened`.
- **BUG #3 (Option A — strict):** `set_solo_target` validates `_get_project_path(project_name) is not None`; window `_on_solo_target_changed` guards active-project identity.
- **BUG #4:** new `set_on_auto_accept_level_changed` callback + `_emit_auto_accept_level_changed` fired in `_commit_auto_accept_level` after `_refresh_auto_accept_state()`; `_on_autoaccept_cycle_clicked` no longer optimistically rebuilds.
- **BUG #5:** `_cached_branch` → `_cached_branch_by_path: dict[str, str]`.
- **BUG #6:** scheduling split into `needs_resolution` (cache check) + `already_running` (in-flight check).
- **BUG #7:** `_resolve_agent_display_name` uses `.get()` + truthiness, not `if sk in special`.

**Verification:** 24 python code blocks in FIX-3 all pass `ast.parse()` with 0 SyntaxError and 0 assignment-inside-lambda (Round 3 BUG #1 was a `SyntaxError` in a FIX-2 code sample). Empirical probes confirmed: `set_on_project_closed` is append-based/fires `cb(closing_name)`; `get_special_agents() -> dict[str, str]`; `_refresh_auto_accept_state` doesn't notify MainWindow (callback required); TWO existing `set_on_project_closed` registrations already exist in window.py (multi-callback design confirmed).

## Phase I status — ✅ COMPLETE

All 6 implementation phases done and audited:
- I.1 CSS — ✅ (8 rules, GTK parse OK)
- I.2 FeedHandler — ✅ (5 pieces, 16/16 ad-hoc tests, 1 LOW deferred)
- I.3 MainContent — ✅ (9 methods + 2 legacy fixes, 27/27 tests, 0 bugs)
- I.4 Window wiring — ✅ (13 methods + 7 callbacks, 19/19 spec compliance, 7/7 scenarios, 0 CRIT/HIGH)
- I.5 Tests — ✅ (37 new tests, 8/10 mutation-caught, 3 coverage gaps deferred)
- I.6 ARCHITECTURE.md — ✅ (4 sections updated, correct §3.9 not stale §3.7)

Post-mortem: `docs/post-mortems/2026-07-31-PROJECT-SETTINGS-BAR-ENHANCED-POST-MORTEM.md`

Grade: A- (90/100). 39 total bugs found (32 spec + 7 impl), 0 reached production uncaught. Dispatch:

```
/ask @Debugger "Please audit per docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-AUDIT-REQUEST.md. Load prompts/adversarialDebugger.md fresh. Save findings to docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3-FINDINGS.md."
```

## Dispatch pattern (PM-facing)

When ready to delegate, fire in chat:

```
/ask @Debugger "Please audit per docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-AUDIT-REQUEST.md. Load prompts/adversarialDebugger.md fresh. Save findings to docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md."
```

When fixes are needed, fire:

```
/ask @Coder "Please write the spec fix per docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-INSTRUCTIONS.md. Use prompts/steelFramedCodeWriter.md."
```

After the spec is clean, dispatch implementation phases one at a time, each followed by an audit handoff.
