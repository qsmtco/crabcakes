# Adversarial Audit — System Prompt Library

**Auditor:** QTR (Kage-7) — Kage-7 assassin operative, crew of Qontinuum Bridge
**Date:** 2026-04-25
**Status:** READ-ONLY — Findings reported, no code changes made
**Proposal:** `docs/PROPOSAL-system-prompt-library.md` (Qaster, 2026-04-25)

---

## Methodology

Adversarial debugger mode. Challenge every assumption, trace failures backward, exploit type system, break external contracts, be mean to error handling.

---

## BUG #1
**Severity:** CRITICAL

**Assumption violated:** "compose_system_prompt() can select agent-specific templates for gateway agents"

**Attack vector:** Gateway agents (Qaster, QTR) have names that don't contain "coder" or "debugger". `compose_system_prompt()` selects `coder.md` with `if "coder" in agent_name` — "Qaster" and "QTR" never match. The role-specific templates for gateway agents would never be loaded.

**Reproduction:**
1. Call `compose_system_prompt(agent_name="Qaster", ...)`
2. `coder.md` and `debugger.md` are silently skipped
3. Gateway agents get only `default.md` + `project-awareness.md` + `project-collaboration.md` — no behavioral instructions

**Root cause:** Selection by substring match on display name is a coincidence of naming, not a design. Qaster, QTR, and any human agents won't match any agent-specific template.

**Fix:** Use an explicit `agent_role` parameter, not string matching on display name:
```python
if agent_role == "coder": templates.append("coder.md")
elif agent_role == "debugger": templates.append("debugger.md")
```

---

## BUG #2
**Severity:** HIGH

**Assumption violated:** "Line numbers in the proposal match the current state of agent/context.py"

**Attack vector:** The proposal references specific line numbers for deletion — "lines 403-405" for custom prompt check, "lines 23-80" for `_CODER_SYSTEM_PROMPT` / `_DEBUGGER_SYSTEM_PROMPT`. These numbers may be stale. A naive implementation deleting by line offset will delete the wrong code.

**Reproduction:** Search `agent/context.py` for `_CODER_SYSTEM_PROMPT`. If it's not at line 23, deleting lines 23-80 will corrupt the file.

**Root cause:** Proposals written against a moving target. No guarantee line numbers are current at implementation time.

**Fix:** Delete by searching for actual function and variable names, not line offsets:
```python
# Delete by name, not by line number
if 'def load_custom_system_prompt' in source: remove_function(...)
if '_CODER_SYSTEM_PROMPT' in source: remove_constant(...)
```

---

## BUG #3
**Severity:** HIGH

**Assumption violated:** "REVIEW_MODE variable is passed from chat_handler.py to compose_system_prompt"

**Attack vector:** The proposal's `chat_handler.py` replacement example shows:
```python
compose_system_prompt(agent_name="", project_path=project_path, project_awareness=awareness_dict)
```
No `review_mode=...` argument is passed. `code-review.md` would never load through this path.

**Reproduction:**
1. User enables review mode in a project
2. PM sends a message
3. `_build_awareness_prefix()` calls `compose_system_prompt` without `review_mode`
4. `code-review.md` is never selected

**Root cause:** The `chat_handler.py` change example is missing the `review_mode` parameter entirely.

**Fix:**
```python
review_mode = getattr(self, '_project_review_mode', 'off')
compose_system_prompt(
    agent_name="",
    project_path=project_path,
    project_awareness=awareness_dict,
    review_mode=review_mode,  # ← ADD THIS
)
```

---

## BUG #4
**Severity:** HIGH

**Assumption violated:** "prompts/system/ directory is guaranteed to exist and be populated at startup"

**Attack vector:** App starts, user opens a project, but `prompts/system/` doesn't exist yet (templates not yet created). `compose_system_prompt` silently skips all templates → empty system prompt → all agents act without any instructions.

**Reproduction:**
1. Fresh install, templates not yet created
2. Open a project
3. All agents receive empty system prompt
4. No behavioral instructions anywhere

**Root cause:** No startup check. The fallback to "current hardcoded templates" is described in the proposal but never implemented as an explicit code path.

**Fix:** Add a startup migration that creates `prompts/system/` with default templates before `compose_system_prompt` runs. Or implement the fallback explicitly:
```python
if not os.path.exists(SYSTEM_PROMPTS_DIR):
    os.makedirs(SYSTEM_PROMPTS_DIR)
    _create_default_templates()  # Write default.md, project-awareness.md, etc.
```

---

## BUG #5
**Severity:** MEDIUM

**Assumption violated:** "build_awareness_dict keys match the template variable names in the proposal"

**Attack vector:** If `build_awareness_dict` returns keys that differ from what templates expect (e.g., `memory` vs `PROJECT_MEMORY`), `fill_template` doesn't match them. Agents see raw `{{PROJECT_MEMORY}}` in their prompt.

**Reproduction:**
1. `build_awareness_dict` returns `{"memory": "..."}`
2. `project-awareness.md` uses `{{PROJECT_MEMORY}}`
3. `fill_template` doesn't replace it — `{{PROJECT_MEMORY}}` appears verbatim in agent's prompt

**Root cause:** No variable name contract enforced between `build_awareness_dict` and the templates.

**Fix:** Add an integration test that loads all templates, calls `build_awareness_dict`, and fails if any `{{...}}` pattern remains unresolved.

---

## BUG #6
**Severity:** MEDIUM

**Assumption violated:** "Custom .crabcakes/agent-system-prompt.md and AGENTS.md have zero active users"

**Attack vector:** A project has `AGENTS.md` or `.crabcakes/agent-system-prompt.md` with custom instructions. The proposal deletes `load_custom_system_prompt()` entirely. These files are silently ignored. User's custom agent behavior breaks with no warning.

**Reproduction:** Any existing project with a custom `AGENTS.md`. After this change, it has no effect.

**Root cause:** "Zero usage" claim is based on static analysis, not runtime detection. Users don't get warned their custom prompts stopped working.

**Fix:** Either preserve `load_custom_system_prompt()` as a fallback, or implement a migration that moves `AGENTS.md` content into the new template system before deleting the old code.

---

## BUG #7
**Severity:** MEDIUM

**Assumption violated:** "fill_template handles unresolved variables gracefully"

**Attack vector:** Template has `{{TOOL_LIST}}` but `compose_system_prompt` is called without tool data. `fill_template` logs "unresolved: TOOL_LIST" at WARNING but leaves `{{TOOL_LIST}}` verbatim in the prompt. Agent receives a prompt with literal `{{TOOL_LIST}}` and doesn't know what to do with it.

**Reproduction:**
1. Call `compose_system_prompt` without passing tool data
2. Check the returned prompt string
3. `{{TOOL_LIST}}` appears as a literal in the agent's system prompt

**Root cause:** `fill_template` logs but doesn't fix. A WARNING in a log file doesn't repair a malformed prompt delivered to an LLM.

**Fix:** Strip unresolved `{{VAR}}` patterns entirely, or raise an error rather than silently including them:
```python
result = template
for key, val in variables.items():
    result = result.replace(f"{{{{key}}}}", val)
# Strip any remaining {{...}} patterns
result = re.sub(r'\{\{[^}]+\}\}', '', result)
```

---

## BUG #8
**Severity:** MEDIUM

**Assumption violated:** "load_prompt_template returns None only when the file is truly absent"

**Attack vector:** File exists but has no read permissions. `open()` raises `PermissionError`. `load_prompt_template` has no `try/except`. Exception propagates up, crashes the prompt composition chain. User opens a project → all agents crash on their first message.

**Reproduction:**
1. `chmod 000` on one file in `prompts/system/`
2. Open a project
3. Any message triggers the crash

**Root cause:** `load_prompt_template` doesn't handle `OSError`. File existence ≠ file readability.

**Fix:**
```python
def load_prompt_template(name: str) -> str | None:
    path = os.path.join(PROMPT_DIR, f"{name}.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None
```

---

## BUG #9
**Severity:** LOW

**Assumption violated:** "Template filling uses a safe pattern that won't corrupt template content"

**Attack vector:** Template content contains literal double-brace sequences unrelated to variables (e.g., a code example: "Use `{{VARIABLE}}` syntax"). `fill_template` replaces them unintentionally, corrupting the documentation.

**Reproduction:** A template documents the pattern itself: "Use `{{VARIABLE}}` syntax in templates." This gets replaced with the actual variable value, corrupting the documentation.

**Root cause:** Simple string replace on `{{VAR}}` can't distinguish intentional variables from literal examples.

**Fix:** Use `string.Template` with proper `safe_substitute`, or require templates to use a distinct marker (e.g., `${VAR}` or `{{!VAR}}`).

---

## BUG #10
**Severity:** LOW

**Assumption violated:** "team_size in compose_system_prompt reflects the count of reachable agents"

**Attack vector:** `team.json` has 3 members listed but one has an invalid/empty `session_key`. `team_size=3` triggers `project-collaboration.md`. But the team is effectively non-functional. Agent enters collaboration mode expecting 3 agents when realistically it's 2.

**Reproduction:** Add a member to `team.json` with `session_key: ""`. `team_size=3` but collaboration silently fails.

**Root cause:** `team_size` is the count of members in the JSON array, not the count of reachable agents.

**Fix:** Count only members with non-empty, valid `session_keys`, or pass a separate `has_working_team` flag.

---

## BUG #11
**Severity:** LOW

**Assumption violated:** "Moving improve-system-prompt.md is atomic for running deployments"

**Attack vector:** App is running with `improve.py` reading from `prompts/improve-system-prompt.md`. During a live update, the file is moved to `prompts/system/improve.md`. `improve.py` line 89 hasn't been updated yet. `improve.py` tries to read from old path → `FileNotFoundError`. Improve Prompt button crashes.

**Reproduction:** Deploy the new version with the file move but before updating `improve.py` line 89. The Improve Prompt button crashes.

**Root cause:** The path update is described as a single line change, but in a running deployment this is a two-step operation with a window where things break.

**Fix:** Keep `improve-system-prompt.md` in place. Have `improve.py` read from both paths (new preferred, fallback to old), then remove old path after all deployments are stable.

---

## Summary

| Bug # | Severity | Category | File(s) |
|-------|----------|----------|---------|
| 1 | CRITICAL | Logic error — template selection | `utils/prompt_loader.py` |
| 2 | HIGH | Stale line number references | `agent/context.py` deletion targets |
| 3 | HIGH | Missing parameter wiring | `ui/handlers/chat_handler.py` |
| 4 | HIGH | Missing startup initialization | `utils/prompt_loader.py` |
| 5 | MEDIUM | Variable name contract missing | `utils/project_awareness.py` + templates |
| 6 | MEDIUM | Silent removal of existing feature | `agent/context.py` |
| 7 | MEDIUM | Unresolved variables in prompts | `utils/prompt_loader.py` |
| 8 | MEDIUM | Missing error handling | `utils/prompt_loader.py` |
| 9 | LOW | Template pattern collision | `utils/prompt_loader.py` |
| 10 | LOW | Invalid team size calculation | `compose_system_prompt()` call sites |
| 11 | LOW | Deployment race condition | `improve.py` + file move |

**Total: 1 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW**

**Most dangerous:** Bug #1. Gateway agents (Qaster, QTR) would silently receive no role-specific behavioral instructions from the template system. Bug #4 would cause all agents to receive empty system prompts on any fresh install.

---

*This report is READ-ONLY. No code was modified.*
