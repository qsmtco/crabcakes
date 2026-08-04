# Spec Audit Request — SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1 (Round 2)

**Spec to audit:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md` (NEW — supersedes original)
**Original spec (for diff):** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Round 1 findings to verify addressed:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md` (18 bugs: 4 CRITICAL, 7 HIGH, 5 MEDIUM, 2 LOW)
**Audit prompt to load:** `prompts/adversarialDebugger.md`
**Working dir:** `/home/q/projects/crabcakes`

This is the **Round 2 re-audit** after the Coder rewrote the spec to address Round 1 findings. Your job:

1. **Verify each of the 18 Round 1 findings is actually fixed** in the new spec. Read both specs side by side. For each bug, confirm the fix is real (not just papered over with a different incorrect approach) and the new code sample would actually work.

2. **Run a fresh adversarial probe** of the new spec using all 11 sections of `adversarialDebugger.md`. The new spec may have introduced NEW bugs while addressing the old ones. Look especially for:
   - New code samples that look correct but won't actually run
   - New invented APIs (the original spec's failure mode was inventing `_auto_accept_state_str`, `_active_project` tuple, `AgentDefinition.session_key`)
   - New GTK3 APIs ported into GTK4 code
   - New thread-safety risks
   - New Pango-unsafe markup

3. **Verify the empirical probe claims** the Coder made. Specifically:
   - The 4-state round-trip `set_auto_accept_level` ↔ `get_auto_accept_level` — is the new design distinct, lossless, and persisted? Trace the code path.
   - The `SpecialAgentDef` `conv_id_prefix` claim — confirm that's the real identifier and that the spec's name-resolution path actually works.
   - The `get_branch` `(detached HEAD)` handling — confirm the spec decides how to display it.
   - The `escape_for_pango` vs `xml_escape_text` question — the Coder claims `escape_for_pango` still exists at `utils/escaping.py:97`. Verify this against the actual file. (This is important because the original spec was wrong about this in a different way.)

4. **Sanity-check the new design decision flagged by the Coder:** the new `set_on_solo_target_changed` callback added to `ProjectHandler`. Is this the right pattern? Or would a simpler approach (e.g., calling the bar update directly from `set_solo_target`) be better? Trace the existing `set_solo_target` call sites to see if the new callback would actually fire when needed.

5. **Verify scope coverage:**
   - The new spec claims to address all 18 findings — confirm by reading §9 (or whatever the traceability table is called).
   - Check the 4-file scope (main_content.py, window.py, feed_handler.py, styles.py) plus the one new addition to project_handler.py. Is anything else needed?

**Output format** (same as Round 1):

```
BUG #[N]
Severity: [CRITICAL/HIGH/MEDIUM/LOW]
Finding: [which Round 1 bug this addresses, OR "new bug found in Round 2"]
Assumption violated: [what the new spec assumed]
Attack vector: [how to break it]
Reproduction: [exact steps — file/line/code]
Root cause: [why the new spec is wrong]
Fix: [what the new spec needs to change]
```

**Output structure:**
1. **Round 1 verification table** — for each of the 18 findings, mark: ✅ FIXED / ⚠️ PARTIAL / ❌ NOT FIXED / 🆕 REGRESSED
2. **New bugs found in Round 2** (if any)
3. **Summary:** pass/fail verdict, top 3 must-fix items

Save findings to `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-FINDINGS.md` AND report back here.

If the spec is now clean (or only has LOW/cosmetic issues), say so explicitly with evidence. Don't manufacture bugs to look thorough.
