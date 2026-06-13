# PHASE 9 of 9 — Final verification + completion report

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.16, §3 (Data Flow), §4 (File Change Summary), §5 (Implementation Order), §6 (Acceptance Criteria), §7 (Edge Cases).

## This is the WRAP-UP phase.

There is no new code. Your job is to **verify that every spec requirement is satisfied** and produce a single comprehensive completion report documenting the state of the spec.

## Files to change

1. `docs/specs/PHASE-9-COMPLETION-REPORT.md` — NEW. The single source of truth documenting that the LLM Provider Settings Dialogue spec is complete. ~300-500 lines, organized by spec section (§2.16, §3, §4, §5, §6, §7). Each checkbox in §6 must have a status (✅ DONE / ⚠️ DEFERRED / ❌ MISSING) and evidence (file:line, test name, or command output).

2. **No other code or test files.** This phase is verification + documentation only.

3. **Optional but recommended:** commit the work in a clean way. See "Commit strategy" below.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT modify any code or test files.** This is verification only. If you find a bug, **report it** in the completion report under "Outstanding issues" but do NOT fix it — that's a post-Phase-9 task.
- **Every status must have evidence.** No "trust me" claims. Paste command output, file paths, test names, line numbers.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` — the entire spec. This is your checklist.
2. `PHASE-1-INSTRUCTIONS.md` through `PHASE-8-INSTRUCTIONS.md` — your previous work, for cross-reference.
3. All audit reports from the project channel (the conversation history with the Qaster). These are the authoritative audit records for each phase.
4. The actual code (git status, git diff) — the ground truth.

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 9.1: §2.16 verification (Files NOT changed)

Run the following verification and document the results:

```bash
cd /home/q/projects/crabcakes

# These files must have NO modifications (untracked is OK; modification is not)
for f in agent/enforcement.py agent/context.py agent/tools.py ui/views/left_panel.py; do
    if git diff --stat "$f" 2>/dev/null | grep -q .; then
        echo "FAIL: $f was modified"
    else
        echo "OK: $f unchanged"
    fi
done

# gateway/ directory must have no modifications
if git diff --stat gateway/ 2>/dev/null | grep -q .; then
    echo "FAIL: gateway/ was modified"
else
    echo "OK: gateway/ unchanged"
fi

# prompts/default_agents/*.yaml must have no modifications
if git diff --stat prompts/default_agents/ 2>/dev/null | grep -q .; then
    echo "FAIL: prompts/default_agents/ was modified"
else
    echo "OK: prompts/default_agents/ unchanged"
fi
```

In the report, for each of the six files/dirs from §2.16, write: `agent/enforcement.py: ✅ unchanged` (or whatever the result is).

## SUB-PHASE 9.2: §3 Data Flow verification

Trace through each of the six flows (3.1 - 3.6) and confirm the code matches. For each flow, write a short trace like:

```
### §3.1 Startup: status dot initial state

Trace:
1. crabcakes.py starts → window.__init__ → window._build() — verified at ui/window.py:90-93
2. self._settings_handler = SettingsHandler(...) — verified at ui/window.py:216-219
3. load_providers() → list[ProviderConfig] — verified at utils/providers_store.py
4. has_any_verified_provider(providers) → bool — verified at utils/providers_store.py
5. toolbar.set_settings_status(bool) → status_dot.set_visible(not bool) — verified via wire_settings_handler
   call in ui/window.py:225-229

Evidence: [paste the relevant grep output]
Status: ✅ DONE
```

Do this for all six flows.

## SUB-PHASE 9.3: §4 File Change Summary verification

For each row in the §4 table, verify the file exists and matches the expected change type. Use `git status` and `ls` to confirm:

```bash
cd /home/q/projects/crabcakes

# New files
for f in models/providers.py utils/providers_store.py utils/provider_test.py \
         ui/handlers/settings_handler.py ui/views/settings_dialog.py \
         tests/test_providers_store.py tests/test_provider_test.py \
         tests/test_settings_handler.py tests/test_settings_dialog.py \
         tests/test_agent_config_yaml_fallback.py tests/test_agent_builder_no_provider_keys.py; do
    if [ -f "$f" ]; then
        echo "OK: $f exists ($(wc -l < $f) lines)"
    else
        echo "FAIL: $f missing"
    fi
done

# Modified files
for f in agent/config.py agent/special_agents.py agent/runtime.py \
         ui/toolbar.py ui/views/agent_builder.py ui/window.py ui/styles.py \
         utils/agent_defs.py; do
    if git diff --stat "$f" 2>/dev/null | grep -q .; then
        echo "OK: $f modified: $(git diff --stat "$f" | tail -1)"
    else
        echo "WARN: $f not modified (may be a regression or may be a no-op per spec)"
    fi
done
```

Document any discrepancies. For example, `ui/views/agent_builder.py` is expected to be REVISED per §4 but is UNCHANGED in our work because it's Phase C deferred. Document that as "⚠️ DEFERRED TO PHASE C".

## SUB-PHASE 9.4: §5 Implementation Order verification

Confirm that all 13 implementation steps are complete or explicitly deferred:

| # | Step | Status |
|---|------|--------|
| 1 | models/providers.py | ✅ done (Phase 1) |
| 2 | utils/providers_store.py | ✅ done (Phase 1) |
| 3 | utils/provider_test.py | ✅ done (Phase 2) |
| 4 | agent/config.py | ✅ done (Phase 3 + Phase 8) |
| 5 | agent/special_agents.py | ✅ done (Phase 3) |
| 6 | agent/runtime.py | ✅ done (Phase 3) |
| 7 | utils/agent_defs.py | ✅ done (Phase 3) |
| 8 | ui/handlers/settings_handler.py | ✅ done (Phase 4) |
| 9 | ui/styles.py | ✅ done (Phase 5 + Phase 6) |
| 10 | ui/views/settings_dialog.py | ✅ done (Phase 6) |
| 11 | ui/toolbar.py | ✅ done (Phase 5) |
| 12 | ui/window.py | ✅ done (Phase 7) |
| 13 | ui/views/agent_builder.py | ⏸ DEFERRED (Phase C, see §2.10) |
| 14 | Tests | ✅ done (Phases 1-8) |

For each step, paste the relevant evidence (file:line or git log entry).

## SUB-PHASE 9.5: §6 Acceptance Criteria verification

Go through every checkbox in §6.1, §6.2, §6.3. For each, write:

```
- [✅/⚠️/❌] <criterion text>
  Evidence: <file:line, test name, or command output>
  Status: DONE / DEFERRED (reason) / MISSING (reason)
```

§6.1 Functional (11 items):
- providers.yaml created with 0o600 — verified at utils/providers_store.py
- parent dir 0o700 — verified at utils/providers_store.py
- ⚙ opens dialog with one card per provider — verified at ui/views/settings_dialog.py
- Adding new provider writes single YAML record and refreshes agent edit dropdown — ⚠️ PARTIAL (yaml write yes; agent edit dropdown refresh is Phase C)
- Removing last verified provider re-shows red dot — verified at settings_handler.py + wiring
- Successful Test Connection shows ✅ with latency, clears red dot — verified at settings_handler.py
- Failed Test Connection shows ❌ with error message — verified at settings_handler.py
- MiniMax body-level errors handled — verified at utils/provider_test.py
- Special agents authenticate using providers.yaml key — verified at agent/runtime.py (Phase 3)
- agent.json providers section is fallback only — verified at agent/config.py (Phase 8)
- agent.json enforcement, default_provider, cost_limit, step_limit continue to work — verified (no changes to those fields)

§6.2 Negative (5 items):
- No agent YAML contains api_key/provider_keys after save — ⚠️ DEFERRED (Phase C)
- validate_agent_def does NOT reject for missing API key — verified (Phase 8 tests pass)
- Agent edit dialog does not show API key entry — ⚠️ DEFERRED (Phase C)
- Hardcoded _PROVIDERS and _PROVIDER_MODELS constants gone — ⚠️ DEFERRED (Phase C)
- app_title still flows to X-Title header — verified (no changes to SpecialAgentDef.app_title)

§6.3 Non-functional (4 items):
- Test Connection completes within 8s timeout — verified at utils/provider_test.py:18
- Settings dialog opens within 100ms — verified (no network calls in __init__)
- File writes are atomic — verified at utils/providers_store.py (write to .tmp, rename)
- No import cycle — verified (utils/providers_store.py imports nothing UI/GTK; ui/views/settings_dialog.py imports handler only)

## SUB-PHASE 9.6: §7 Edge Cases verification

For each edge case in §7, write a short status:

```
| Case | Status | Evidence |
|------|--------|----------|
| providers.yaml empty [] | ✅ | tested in test_settings_dialog.test_with_no_providers_shows_empty_state |
| providers.yaml malformed | ✅ | tested in test_providers_store |
| providers.yaml read-only | ✅ | tested in test_providers_store (raises OSError on save) |
| ... (etc) |
```

## SUB-PHASE 9.7: Full test suite

Run the full test suite and capture the final result:

```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

This should be the canonical "final" result. Document it in the report.

## SUB-PHASE 9.8: Completion report structure

The completion report `PHASE-9-COMPLETION-REPORT.md` should follow this structure:

```markdown
# PHASE 9 of 9 — LLM Provider Settings Dialogue: COMPLETION REPORT

**Spec:** docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md
**Date:** <today>
**Status:** ✅ SPEC COMPLETE (with documented deferrals)
**Test result:** <X passed, Y failed, Z skipped, W xfailed in Ts>

## 1. Executive summary

<2-3 paragraph overview: what was built, what's deferred, what's the current state of the codebase.>

## 2. §2.16 verification (Files NOT changed)

<results of the 6 files/dirs from §2.16>

## 3. §3 Data Flow verification

<trace through §3.1 - §3.6>

## 4. §4 File Change Summary

<table of file status>

## 5. §5 Implementation Order

<status of all 13 steps>

## 6. §6 Acceptance Criteria

<status of all 20+ checkboxes with evidence>

## 7. §7 Edge Cases

<status of all 11 edge cases with evidence>

## 8. Outstanding issues

<list any bugs, gaps, or concerns found during the audit>

## 9. Phase C work (deferred)

<list all Phase C items that are NOT done, with clear references to spec sections>

## 10. Recommendations for next steps

<what should the team do after this spec? E.g.>
- Begin Phase C work for agent_builder.py
- Add integration test for the full flow
- Update ARCHITECTURE.md per spec §8
- Consider the `get_api_key` side-effect issue from Phase 8 Finding 1

## 11. Test results

<paste the full test suite summary>

**COMPLETENESS:**
- [x] 9.1 §2.16 files verified — evidence: <grep output>
- [x] 9.2 §3.1-3.6 flows traced — evidence: <each flow has file:line ref>
- [x] 9.3 §4 file change summary matches — evidence: <status table>
- [x] 9.4 §5 all 13 steps done or explicitly deferred — evidence: <status table>
- [x] 9.5 §6 all 20+ criteria checked — evidence: <per-criterion status>
- [x] 9.6 §7 all 11 edge cases verified — evidence: <per-case status>
- [x] 9.7 full test suite run — evidence: <test summary line>
- [x] 9.8 completion report structure follows the spec — evidence: <this report>

**Overall verdict: SPEC COMPLETE — ready for production (with documented Phase C work remaining).**
```

## Commit strategy (recommended but optional)

After completing the report, you may organize the work into clean commits. The recommendation:

```bash
cd /home/q/projects/crabcakes

# Option A: one big commit per phase (most readable history)
git add agent/config.py agent/runtime.py agent/special_agents.py \
        models/providers.py utils/providers_store.py utils/provider_test.py \
        ui/handlers/settings_handler.py ui/views/settings_dialog.py \
        ui/views/agent_builder.py ui/wiring.py \
        ui/styles.py ui/toolbar.py ui/window.py \
        utils/agent_defs.py
git add tests/test_providers_store.py tests/test_provider_test.py \
        tests/test_settings_handler.py tests/test_settings_dialog.py \
        tests/test_agent_config_yaml_fallback.py \
        tests/test_agent_builder_no_provider_keys.py \
        tests/test_toolbar.py tests/test_window_settings_wiring.py \
        tests/test_agent_builder_handler.py tests/test_agent_defs.py \
        tests/test_bug_fixes.py

git commit -m "feat: LLM provider settings dialogue (Phases 1-9)

Implements the full spec at docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md.

New files:
- models/providers.py (ProviderConfig dataclass)
- utils/providers_store.py (yaml persistence, 0o600)
- utils/provider_test.py (Test Connection engine with 8s timeout)
- ui/handlers/settings_handler.py (logic + GLib dispatch)
- ui/views/settings_dialog.py (pure GTK view)
- ui/wiring.py (testable wiring helper)
- 7 new test files

Revised files:
- agent/config.py (yaml-canonical provider loading, fall back to agent.json)
- agent/special_agents.py (drop api_key resolution)
- agent/runtime.py (resolve API key from providers.yaml)
- ui/toolbar.py (⚙ button + red status dot)
- ui/window.py (wire SettingsHandler + dialog)
- ui/styles.py (settings-* CSS classes)
- utils/agent_defs.py (drop api_key validation, get_available_providers from yaml)
- 3 modified test files

Deferred to Phase C (out of scope for this spec):
- ui/views/agent_builder.py simplification (drop _PROVIDERS, drop API key field)

See docs/specs/PHASE-9-COMPLETION-REPORT.md for full status."

# Then commit the spec docs and report
git add docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md \
        docs/proposals/PROPOSAL-llm-provider-settings-dialogue.md \
        docs/specs/PHASE-*-INSTRUCTIONS.md \
        docs/specs/PHASE-9-COMPLETION-REPORT.md

git commit -m "docs: LLM provider settings dialogue spec + phase reports

- SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md: the canonical spec
- PROPOSAL-llm-provider-settings-dialogue.md: the design proposal
- PHASE-1 through PHASE-9 instructions + completion report
"
```

If the user prefers per-phase commits, alternative: 9 commits, one per phase. **QTR: ask the user via the project channel which they prefer if unclear. Document the choice in the report.**

## Verification commands for the audit

```bash
cd /home/q/projects/crabcakes

# 9.1: §2.16 verification
echo "=== 9.1 §2.16 files unchanged ==="
for f in agent/enforcement.py agent/context.py agent/tools.py ui/views/left_panel.py; do
    diff=$(git diff --stat "$f" 2>/dev/null)
    if [ -n "$diff" ]; then
        echo "FAIL: $f was modified"
    else
        echo "OK: $f unchanged"
    fi
done
git diff --stat gateway/ 2>/dev/null || echo "OK: gateway/ unchanged"
git diff --stat prompts/default_agents/ 2>/dev/null || echo "OK: prompts/default_agents/ unchanged"
echo "---"

# 9.2: §3 flow evidence
echo "=== 9.2 §3 flows — startup trace ==="
grep -n "_settings_handler\|wire_settings_handler\|SettingsHandler" ui/window.py | head -10
echo "---"
echo "=== 9.2 §3 flows — save/refresh trace ==="
grep -n "on_providers_changed\|refresh_providers" ui/handlers/settings_handler.py ui/views/settings_dialog.py | head -10
echo "---"

# 9.3: §4 file existence
echo "=== 9.3 §4 file existence ==="
ls -1 models/providers.py utils/providers_store.py utils/provider_test.py \
     ui/handlers/settings_handler.py ui/views/settings_dialog.py 2>&1
echo "---"

# 9.4: §5 already-done
echo "=== 9.4 §5 all 13 steps done or deferred ==="
echo "Phase C: agent_builder.py is the only deferred step"
echo "---"

# 9.5: §6 criteria
echo "=== 9.5 §6 criteria — file mode check ==="
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from utils.providers_store import save_providers
from models.providers import ProviderConfig
save_providers([ProviderConfig(name='p', base_url='https://x', api_key='k', default_model='m')])
import pathlib
yaml = pathlib.Path.home() / '.config' / 'crabcakes' / 'providers.yaml'
print('providers.yaml mode:', oct(os.stat(yaml).st_mode & 0o777))
print('parent dir mode:', oct(os.stat(yaml.parent).st_mode & 0o777))
"
echo "---"

# 9.6: §7 edge cases
echo "=== 9.6 §7 edge cases — empty yaml ==="
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from utils.providers_store import load_providers
print('empty yaml load:', load_providers())
"
echo "---"

# 9.7: full suite
echo "=== 9.7 full test suite ==="
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -8
echo "---"
```

## Acceptance criteria for this phase

- [ ] `docs/specs/PHASE-9-COMPLETION-REPORT.md` exists
- [ ] §2.16 verification section: all 6 files/dirs confirmed unchanged
- [ ] §3 Data Flow section: all 6 flows (3.1-3.6) traced with file:line evidence
- [ ] §4 File Change Summary: all expected files exist or are explicitly deferred
- [ ] §5 Implementation Order: all 13 steps done or explicitly deferred
- [ ] §6 Acceptance Criteria: every checkbox has status + evidence
- [ ] §7 Edge Cases: every case has status + evidence
- [ ] Outstanding issues section: empty or has clear bug reports
- [ ] Phase C work section: lists all deferred items with spec references
- [ ] Full test suite runs cleanly (pre-existing failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 9 of 9 — COMPLETE

Files changed:
- docs/specs/PHASE-9-COMPLETION-REPORT.md — NEW, +N lines (paste wc -l)
- (no code changes)

Verification (paste outputs of every command listed above):
- 9.1 §2.16 files unchanged: ...
- 9.2 §3 flows traced: ...
- 9.3 §4 file existence: ...
- 9.4 §5 implementation order: ...
- 9.5 §6 criteria file mode: ...
- 9.6 §7 edge cases: ...
- 9.7 full test suite: ...

**COMPLETENESS:**
- [x] 9.1 §2.16 files verified — evidence: <grep output>
- [x] 9.2 §3.1-3.6 flows traced — evidence: <each flow has file:line ref>
- [x] 9.3 §4 file change summary matches — evidence: <status table>
- [x] 9.4 §5 all 13 steps done or explicitly deferred — evidence: <status table>
- [x] 9.5 §6 all 20+ criteria checked — evidence: <per-criterion status>
- [x] 9.6 §7 all 11 edge cases verified — evidence: <per-case status>
- [x] 9.7 full test suite run — evidence: <test summary line>
- [x] 9.8 completion report structure follows the spec — evidence: <this report>

**Outstanding issues found:**
- (list any bugs, gaps, or concerns found during this audit)

**Phase C work remaining:**
- (list all deferred items with spec references)

When done, please write: `Phase 9 complete — ready for final audit. Spec is complete (with documented Phase C deferrals).`
```

When done, please write: `Phase 9 complete — ready for final audit.`
