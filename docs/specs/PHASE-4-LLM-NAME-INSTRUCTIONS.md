# PHASE 4 of 6 — `ui/views/agent_builder.py` (rename `provider` → `llm_name`)

## Master spec
`docs/specs/SPEC-AGENT-LLM-NAME.md` §2.1, §6, §7

## Scope
`ui/views/agent_builder.py` ONLY. Do NOT touch test files. Do NOT touch any other file.

## Hard rules
- Use `prompts/steelFramedCodeWriter.md` exactly. Operating from authorized channel (trigger word `write` is in this delegation).
- **Backward-compat for reads:** when loading existing agent_defs, use `agent_def.get("llm_name") or agent_def.get("provider", "")`.
- `set_provider_options(providers)` keeps its current name and signature.
- You MUST include a literal `**COMPLETENESS:**` block at the end of your report.

## Discovery — read these first
1. `docs/specs/SPEC-AGENT-LLM-NAME.md` §2.1
2. `ui/views/agent_builder.py` — full file. Constructor (1-100), form layout (100-200), `get_values()` (~150-178), `_fill_form()` (~608), `_get_selected_provider_id()` (~399), and any other `agent_def.get("provider", ...)` reads.

Output a DISCOVERY block listing each section read and what you learned.

## Edits

### Edit 1 — `get_values()` (line ~150-178)
Change dict key `"provider"` → `"llm_name"`. Remove `"model": model,` line. Value semantics unchanged.

### Edit 2 — Rename `_get_selected_provider_id()` → `_get_selected_llm_name()`
Body/signature unchanged. Update ALL call sites within `agent_builder.py` with grep. Verify: `grep -n "_get_selected_provider_id" ui/views/agent_builder.py` → 0 matches.

### Edit 3 — `_fill_form()` and other read sites (~608)
For every `agent_def.get("provider", "")` or `agent_def.get("provider")`, change to: `agent_def.get("llm_name") or agent_def.get("provider", "")`. This keeps backward-compat with legacy agent_defs.

### Edit 4 — Remove `model` from `get_values()` output
Per spec, `model` key is removed from new agent YAMLs. Read sites of `agent_def.get("model", "")` for backward-compat with OLD YAMLs STAY (don't remove `_get_selected_model` if it exists, just stop calling it from `get_values()`).

## Verification
```bash
cd /home/q/projects/crabcakes
grep -n '_get_selected_provider_id\|_get_selected_llm_name\|llm_name' ui/views/agent_builder.py | head -20
python3 -c 'from ui.views.agent_builder import AgentBuilderDialog; print(hasattr(AgentBuilderDialog, "_get_selected_provider_id"), hasattr(AgentBuilderDialog, "_get_selected_llm_name"))'
python3 -m pytest tests/test_agent_builder_dialog.py tests/test_agent_builder_no_model_dropdown.py tests/test_agent_builder_no_provider_keys.py -q --tb=line 2>&1 | tail -10
```

## Acceptance
- [ ] `get_values()` returns `"llm_name"`, not `"provider"`. No `"model"` key.
- [ ] `_get_selected_provider_id` renamed to `_get_selected_llm_name`. Zero old-name refs.
- [ ] All call sites of renamed method updated.
- [ ] `_fill_form()` and read sites use `or` pattern for backward-compat.
- [ ] `set_provider_options()` unchanged.
- [ ] `test_agent_builder_dialog.py`, `test_agent_builder_no_model_dropdown.py`, `test_agent_builder_no_provider_keys.py` all pass (or only pre-existing failures).
- [ ] No new regressions: 9 pre-existing failures baseline, 0 new.
- [ ] `**COMPLETENESS:**` block at end.

## Report format
```
PHASE 4 of 6 — COMPLETE
Files changed: ui/views/agent_builder.py — <git diff --stat>
Verification: <paste outputs of every command above>
**COMPLETENESS:**
- [x] Edit 1: llm_name key, no model — evidence: <diff lines>
- [x] Edit 2: renamed, all calls updated — evidence: <grep 0 old refs>
- [x] Edit 3: _fill_form with backward-compat — evidence: <diff>
- [x] hasattr smoke: False True
- [x] pytest: dialog + no_model_dropdown + no_provider_keys green — evidence: <paste>
**Related issues found (not fixed in this phase):** ...
**Implementation choices made:** ...
```

When done, write: `Phase 4 of 6 complete — ready for audit.`
