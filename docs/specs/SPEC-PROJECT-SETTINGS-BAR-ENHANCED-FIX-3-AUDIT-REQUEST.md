# Spec Audit Request — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3 (Round 4)

**Spec to audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3.md` (NEW, supersedes FIX-2, 58.7 KB)
**Previous spec (for diff):** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md`
**Round 3 findings to verify addressed:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2-FINDINGS.md` (7 bugs: 1 CRIT, 3 HIGH, 3 MED)
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

This is the **Round 4 re-audit**. Coder produced FIX-3.md to address the 7 Round 3 findings. The Coder claims 24 code blocks all pass `ast.parse()` with zero errors.

## 1. Verify each of the 7 Round 3 findings is actually fixed

For each, mark ✅ FIXED / ⚠️ PARTIAL / ❌ NOT FIXED / 🆕 REGRESSED with evidence.

- **BUG #1 (CRIT — SyntaxError in lambda):** FIX-3 claims to replace the lambda-insertion with a **named `_on_project_closed(name)` method** registered as its own `set_on_project_closed` callback, leaving existing tuple lambdas untouched. Verify:
  - The named method exists with a normal `def` body (assignment statements are valid there)
  - The handler's registration is append-based/multi-callback (Coder claims `self._on_project_closed: list`, `for cb: cb(closing_name)`) — confirm against actual `project_handler.py`
  - Window.py already has two existing `set_on_project_closed` registrations; verify the spec adds a third that coexists

- **BUG #2 (HIGH — cache write before identity check):** FIX-3 claims `_on_branch_result` runs all checks (token, path, active-name, active-path) BEFORE any cache write. Verify the ordering in the code sample: identity checks first, then `_cached_branch_by_path[...] = branch`, never the reverse.

- **BUG #3 (HIGH — no project validation in set_solo_target):** FIX-3 claims Option A (strict): validates via `_get_project_path` before mutating. Verify the validation is real and a no-op for unknown projects.

- **BUG #4 (HIGH — bar doesn't update after async auto-accept confirmation):** FIX-3 adds `set_on_auto_accept_level_changed` + `_emit_auto_accept_level_changed` fired in `_commit_auto_accept_level` AFTER `_refresh_auto_accept_state()`. Verify:
  - `_on_autoaccept_cycle_clicked` no longer optimistically rebuilds the bar
  - The callback is wired in window.py to `_refresh_settings_bar_for_active` (or equivalent)
  - The Coder's claim about v2 warning wiring `(category, agent, on_confirm, on_cancel)` at window.py:483 is real

- **BUG #5 (MED — cache not keyed by path):** FIX-3 uses `_cached_branch_by_path: dict[str, str]`. Verify the spec uses this consistently and never falls back to a single unkeyed `_cached_branch`.

- **BUG #6 (MED — refresh condition doesn't check cache ownership):** FIX-3 splits `needs_resolution` (cache miss for active path) from `already_running` (token is not None). Verify the scheduling condition uses both checks.

- **BUG #7 (MED — special-agent fallback returns None):** FIX-3 uses `.get()` with truthiness check. Verify the fallback returns the session_key when the mapping value is empty/None.

## 2. Verify the ast.parse() claim independently

The Coder claims "24 python code blocks, 0 SyntaxError, 0 assignment-inside-lambda". **Re-run this verification yourself.** Extract every fenced ```python code block from FIX-3.md and parse each with `ast.parse()`. Report any errors. If the Coder's count (24) differs from your count, flag it.

## 3. Sanity-check the flagged design decision

The Coder flagged: "on project close I intentionally do NOT clear `_cached_branch_by_path` — per BUG #5/#6 the path-keyed cache should persist so a re-open reuses it, and only in-flight state (token/active/path) is invalidated on close."

Evaluate this tradeoff:
- Pro: re-open is instant (cached branch reused)
- Con: stale cache if the branch changed while the project was closed (e.g., user switched branches in a terminal)
- Is the tradeoff acceptable for v1? Should there be a TTL or always-refresh-on-open?

## 4. Run a fresh adversarial probe (all 11 sections)

The spec has grown to 58.7 KB / 826+ lines. Bigger surface = more places for bugs. Look especially for:

- **State-machine consistency:** the new `_on_project_opened(name, path)` invalidation — does it conflict with the existing project-open wiring? Are there now two open callbacks fighting?
- **Token monotonicity:** how is `_branch_request_token` incremented? Is it per-MainWindow or per-call?
- **Callback signature drift:** the new `set_on_auto_accept_level_changed(cb)` — does `cb` take `(level: str)` or `(level: str, project_name: str)`? Verify against the actual FeedHandler patterns.
- **The two-callbacks-coexist claim:** Coder says window.py already has TWO `set_on_project_closed` registrations and the spec adds a third. Verify this is actually safe (append-based, not overwrite).
- **Dead code from earlier rounds:** grep FIX-3 for any of the 18 original R1 bugs + 7 R2 bugs + 7 R3 bugs to confirm none regressed.
- **`_get_project_path` for BUG #3 validation:** does this method actually exist on ProjectHandler? What does it return for an unknown project?

## Output format

**Round 3 verification table** (per-bug status)

**ast.parse() verification** (your independent re-run, with block count and any errors)

**Design decision evaluation** (the cache-on-close tradeoff)

**New bugs found in Round 4** (if any)

**Summary:** pass/fail verdict, top 3 must-fix items, recommended next step (re-fix round vs. ready for implementation)

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3-FINDINGS.md` AND report back here.

If the spec is now clean (or only LOW/cosmetic issues), say so explicitly with evidence. Don't manufacture bugs to look thorough. We've been at this for 3 rounds; if it's good enough, say so.
