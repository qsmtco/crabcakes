# Spec Audit Request — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2 (Round 3)

**Spec to audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md` (NEW, supersedes FIX-1)
**Previous specs (for diff context):** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md`, `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Round 2 findings to verify addressed:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-FINDINGS.md` (7 bugs: 1 CRITICAL, 3 HIGH, 3 MEDIUM)
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

This is the **Round 3 re-audit**. The Coder produced FIX-2.md to address the 7 Round 2 findings. Your job:

## 1. Verify each of the 7 Round 2 findings is actually fixed

Read FIX-2.md end-to-end. For each of the 7 Round 2 findings, confirm the fix is real:

- **BUG #1 (CRITICAL — `is None` dead code):** The fix replaces `_pending_branch_refresh: bool` with a monotonic integer `_branch_active_token: int | None`, guarded via `is None`. Verify the initialization matches the check (both must use `int | None`, not `bool`). Trace the worker start path.

- **BUG #2 (HIGH — async branch results crossing project boundaries):** The fix captures `project_path` and a `request_token` in the worker. The completion callback must compare the captured token AND path against the active project's current state, and silently discard on mismatch. Verify the discard logic also covers the project-closed case.

- **BUG #3 (HIGH — auto-accept callback clobbers member count to 0):** The fix reads `len(get_project_members(...))` before calling `_on_feed_bar_update`. Verify the call site actually uses the live member count, not 0.

- **BUG #4 (HIGH — solo-target callback section incomplete):** The fix adds complete code samples for `project_handler.py` (callback slot + setter + modified `set_solo_target` that fires on real change) and the `window.py` wiring. Verify the wiring shows both the registration AND the callback body. Verify the "no-op on identical re-selection" claim (Coder said it skips firing when target is unchanged).

- **BUG #5 (MEDIUM — legacy methods clear the gear button):** The fix re-appends `self._settings_btn` after the legacy label in both `set_project_settings_text` and `set_feed_bar_text`. Verify the gear is preserved across both legacy methods.

- **BUG #6 (MEDIUM — `escape_for_pango` preserves Pango tags):** The fix uses `xml_escape_text(project_name)` and `xml_escape_text(branch_text)` for all untrusted plain text. The Coder noted agent/auto labels are `Gtk.Button` labels (plain text, inherently safe). Verify there are NO remaining `escape_for_pango(project_name)` or `escape_for_pango(branch_text)` sites in the spec's code samples.

- **BUG #7 (MEDIUM — `_pending_branch_refresh` thread-safety):** The fix unifies this with BUG #2's token approach. Verify the token is monotonically increasing, only mutated on the GTK thread, and the worker just dispatches the result.

## 2. Run a fresh adversarial probe (all 11 sections of `adversarialDebugger.md`)

The new spec may have introduced NEW bugs while addressing the old ones. Look especially for:

- **The Coder's claim:** "no-op on identical re-selection" for `set_solo_target` — verify this is correct and doesn't introduce a race where a no-op skips a legitimate callback fire.
- **The new `_branch_active_token` lifecycle:** the Coder said "project-close bumps the token" — verify this is wired in `close_project` or wherever the project-close path lives.
- **`xml_escape_text` coverage:** grep the entire spec for any remaining unescaped interpolation of `project_name`, `branch_text`, or any user-controlled string into Pango markup.
- **The new `set_on_solo_target_changed` callback:** verify it has a no-op default (callers can leave it unwired) and that the wiring in `window.py` is correct.
- **Token monotonicity:** how is the token incremented? Per-call? Per-project? Verify there's no overflow risk for long-lived sessions and no collision risk for rapid successive refreshes.
- **The `AgentRuntimeHandler.get_special_agents()` claim from Round 1:** the Debugger in Round 1 said the dict path is `{sk: display_name}`. Verify FIX-2's name-resolution path uses this correctly (no new off-by-one or `.get(...)` fallback issues).
- **Pattern sweep:** run `grep` for any of the 18 original Round 1 bugs to confirm none regressed.

## 3. Sanity-check the design decisions in FIX-2

- Is replacing the bool with an int `request_token` the right approach, or would a `threading.Event` or `GLib.idle_add` callback token be cleaner? Note: the spec must use what the rest of the codebase uses.
- Is the new `set_on_solo_target_changed` callback the right hook, or should the bar subscribe to the existing `set_on_members_changed`? Trace the existing callback pattern in `ProjectHandler`.
- The 826-line spec is getting long. Are there sections that could be tightened without losing precision?

## 4. Verify scope coverage

- The spec claims to address all 7 Round 2 findings — confirm via §9 (or whatever the traceability table is).
- Confirm 5-file scope: `main_content.py`, `window.py`, `feed_handler.py`, `project_handler.py`, `styles.py`. Is the project_handler.py change truly additive (one new slot + setter + 1-line callback fire)?

## Output format

**Round 2 verification table** (per-bug, ✅ FIXED / ⚠️ PARTIAL / ❌ NOT FIXED / 🆕 REGRESSED)

**New bugs found in Round 3** (if any)

**Summary:** pass/fail verdict, top 3 must-fix items, recommended next step (re-fix round vs. ready for implementation)

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2-FINDINGS.md` AND report back here.

If the spec is now clean (or only LOW/cosmetic issues), say so explicitly with evidence. Don't manufacture bugs to look thorough.
