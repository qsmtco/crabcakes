# SPEC: Tier 1.3 — Agent-Role Gating for Project Onboarding Template

**Date:** 2026-06-12
**Status:** ✅ IMPLEMENTED — auto_add_to_projects field, get_project_onboarding_agents(), auto-add in project_handler.open_project
**Proposal:** `docs/proposals/PROPOSAL-project-onboarding.md`
**Roadmap:** Tier 1.3, item #3 in priority list
**Bug report:** `docs/bugs/BUG_REPORT-identity-override.md` (Bug #2)

---

## 1. Problem

`utils/prompt_loader.py:compose_system_prompt()` loads the `project-onboarding.md` template whenever `project_path` is set AND `is_project_onboarded(project_path)` returns `False`. The check does NOT gate on `agent_role`.

**Effect:** For any newly created project (skeleton manifest + empty context.md), the onboarding interview template is concatenated into the system prompt for **every** agent — gateway agents, debugger agents, coder agents, all of them. Gateway agents that just route messages get a 3.3K onboarding interview appended to their context for no reason.

**Severity:** correctness bug. Affects every non-Coder agent's first message in every fresh project.

**Documented in:** `BUG_REPORT-identity-override.md` Bug #2, `PROPOSAL-project-onboarding.md` status field.

---

## 2. Fix

Single-line change in `utils/prompt_loader.py:184`.

**Before (line 184):**
```python
            if not is_project_onboarded(project_path):
```

**After:**
```python
            if agent_role == "coder" and not is_project_onboarded(project_path):
```

The onboarding template now only loads for `agent_role == "coder"`. Non-coder agents (debugger, gateway/empty) skip the onboarding gate entirely.

---

## 3. Why "coder" only?

- **Coder writes to the project.** Onboarding teaches Coder about the project's purpose, stack, and conventions so it can produce work that fits.
- **Debugger reads the project.** It diagnoses existing code; it doesn't need the onboarding interview injected into its prompt. The `project-awareness` template (which already loads for all agents with `project_path`) gives it enough context.
- **Gateway agents route messages.** They never see project files directly; onboarding is noise.
- **Empty `agent_role` (gateway)** falls into the "skip" branch. This matches the design intent in the proposal's design principles (§2 of the proposal): onboarding is a Coder-only flow.

This matches the BUG_REPORT identity-override's stated assumption: "The project onboarding template is loaded only for the special agent being onboarded (Coder), not for every gateway agent in an unonboarded project." (BUG_REPORT-identity-override.md:47)

---

## 4. What this SPEC does NOT do (out of scope)

- Does NOT change the onboarding template content (`prompts/system/project-onboarding.md`)
- Does NOT change `is_project_onboarded()` detection logic
- Does NOT add a more sophisticated agent-role allowlist
- Does NOT change other template gating (default, project-awareness, collab, crabcakes-context, crabcakes-commands, code-review, coder, debugger all stay as-is)
- Does NOT add a regression test for the `BUG_REPORT-identity-override.md` attack vector (that's a separate Tier 2/3 item)

---

## 5. Tests

### New test (in `tests/test_prompt_loader.py`)

Add to the existing `TestComposeSystemPrompt` class (after `test_default_template_loaded`, before `test_coder_template_included`):

```python
def test_onboarding_only_loaded_for_coder(self, tmp_path):
    """Onboarding template loads for coder agents only, not for gateway/debugger.

    Per BUG_REPORT-identity-override.md Bug #2: the onboarding interview
    should not be injected into every agent's prompt in a fresh project.
    """
    onboarding_marker = "ONBOARDING_TEST_MARKER"
    # The project-onboarding.md template uses {{AGENT_NAME}} — we check
    # for a string unique to onboarding by loading it directly.
    from utils.prompt_loader import load_prompt_template
    onboarding_template = load_prompt_template("project-onboarding")
    # Onboarding template should mention "onboarding" or "interview"
    assert onboarding_template is not None, "onboarding template should exist"

    # Helper: does this prompt contain the onboarding template's content?
    def has_onboarding(prompt: str) -> bool:
        # Onboarding has distinctive heading(s) — check for one
        return "Onboarding" in prompt or "onboard" in prompt.lower()

    # Coder in an unonboarded project → onboarding IS loaded
    coder_prompt = compose_system_prompt(
        agent_name="Coder", agent_role="coder", project_path=str(tmp_path),
    )
    assert has_onboarding(coder_prompt), (
        "Coder should get onboarding template in unonboarded project"
    )

    # Debugger in same project → onboarding is NOT loaded
    debugger_prompt = compose_system_prompt(
        agent_name="Debugger", agent_role="debugger", project_path=str(tmp_path),
    )
    assert not has_onboarding(debugger_prompt), (
        "Debugger should NOT get onboarding template (Bug #2 fix)"
    )

    # Gateway (empty agent_role) in same project → onboarding is NOT loaded
    gateway_prompt = compose_system_prompt(
        agent_name="Gateway", agent_role="", project_path=str(tmp_path),
    )
    assert not has_onboarding(gateway_prompt), (
        "Gateway agent should NOT get onboarding template (Bug #2 fix)"
    )
```

**Why this test pattern:** A fresh `tmp_path` has no `.crabcakes/` directory, so `is_project_onboarded()` returns `False`. The check for "Onboarding"/"onboard" in the prompt verifies the template was or wasn't loaded. No need to mock the template loader.

**Note on the marker:** Real production tests should not hardcode template internals. If the onboarding template text changes, this test may need updating. Acceptable tradeoff for a one-time gating bug fix.

### Existing tests that must still pass

- `test_coder_template_included` (line ~70)
- `test_debugger_template_included` (line ~76)
- `test_review_mode_adds_template` (line ~82)
- `test_tools_included` (line ~87)
- `test_no_project_no_project_template` (line ~93)
- `test_returns_string` (line ~98)
- All `test_context.py` tests (`build_system_prompt` with Coder/Debugger/Gateway)

No existing test asserts that onboarding loads for non-coder agents. The fix is safe.

---

## 6. Verification commands

Run these from `/home/q/projects/crabcakes`:

1. **Import check:** `python3 -c "from utils.prompt_loader import compose_system_prompt; print('import OK')"`
2. **New test:** `pytest tests/test_prompt_loader.py::TestComposeSystemPrompt::test_onboarding_only_loaded_for_coder -v`
3. **Full prompt_loader tests:** `pytest tests/test_prompt_loader.py -v`
4. **Context tests (which call compose_system_prompt transitively):** `pytest tests/test_context.py -v`
5. **Grep confirms gating:** `grep -n "agent_role == .coder. and not is_project_onboarded" utils/prompt_loader.py`
6. **No regression in related gating:** `grep -n "if agent_role\|if not is_project_onboarded" utils/prompt_loader.py` — should show the new combined check at line 184 and the old "if not is_project_onboarded" should now also include the agent_role gate

---

## 7. Files modified

- `utils/prompt_loader.py` — 1 line changed (line 184)
- `tests/test_prompt_loader.py` — 1 new test added (~30 lines)

No other files. No new files. No new template content.

---

## 8. Risk assessment

**Low risk:**
- Single-line change, easy to revert
- No callers need updating (`agent_role` is already a parameter of `compose_system_prompt()`)
- No existing test asserts the buggy behavior
- The fix matches the design intent documented in both the proposal and the BUG_REPORT

**Watch out for:**
- Some existing tests pass `project_path` without `agent_role` — they default to `""` and will now skip onboarding. Verify these tests still pass.
- The `crabcakes.md` template (line 34) tells agents "When you receive the onboarding prompt..." — this is a Coder-only instruction and is now correctly matched by the fix.
