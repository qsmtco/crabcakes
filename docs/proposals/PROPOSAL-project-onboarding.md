# Project Onboarding — Formal Proposal

> **Status: PARTIALLY IMPLEMENTED** — Verified in code as of 2026-05-09
> - `prompts/system/project-onboarding.md` template exists
> - `is_project_onboarded()` check in `prompt_loader.py` loads the template
> - Note: Bug exists where onboarding template loads for ALL agents, not just coder (see BUG_REPORT-identity-override.md Bug #2)

**Date:** 2026-04-26
**Author:** Qaster
**Affects:** `prompts/system/`, `utils/project_awareness.py`, `ui/handlers/chat_handler.py`

---

## 1. Objective

When an agent first interacts with a newly created project, it has no idea what the project is about. The `project.md` skeleton is all HTML comments, `context.md` is empty, and the agent is flying blind.

This proposal adds a **project onboarding flow**: a template-driven interview where the agent asks the user about the project's purpose, stack, conventions, and team — then writes the answers back into `.crabcakes/` so all future sessions start with real context.

---

## 2. Design Principles

1. **Prompt-driven** — The interview questions live in `prompts/system/project-onboarding.md`, not in code. Users can customize the onboarding experience by editing the template.
2. **Automatic detection** — No flags or settings. The agent detects a new project by checking if `project.md` is still a skeleton (all HTML comments, no real content) and `context.md` is empty.
3. **Conversational** — Ask one or two questions at a time, not a form. Acknowledge answers. Let the user volunteer extra context.
4. **Non-blocking** — The agent asks but doesn't refuse to work. If the user says "skip it, help me with this," the agent helps and circles back later.
5. **Write-back** — After the interview, the agent populates `project.md` with real content and appends a dated entry to `context.md`.

---

## 3. Trigger Detection

The agent checks two conditions on first interaction with a project:

1. `project.md` is a **skeleton** — contains only HTML comments (`<!-- ... -->`) and section headers, no actual content
2. `context.md` is **empty**

Both conditions → trigger onboarding.

Detection logic in `utils/project_awareness.py`:

```python
def is_project_onboarded(project_path: str) -> bool:
    """True if project has been onboarded (has real content in project.md or context.md)."""
    manifest = load_project_manifest(project_path)
    if manifest is None:
        return False
    # Strip HTML comments — if nothing remains, it's still a skeleton
    stripped = re.sub(r'<!--.*?-->', '', manifest, flags=re.DOTALL).strip()
    # Check for any real content beyond section headers
    content_lines = [l for l in stripped.split('\n') if l.strip() and not l.startswith('#')]
    if content_lines:
        return True
    # Also check context.md
    context = load_project_context(project_path)
    return bool(context.strip())
```

---

## 4. Template: `prompts/system/project-onboarding.md`

The template defines what to ask and how to behave during onboarding:

```markdown
You are onboarding onto a new project. The project manifest is empty — you don't know what this is yet.

## Your Task
Ask the user about the project, one or two questions at a time. Be conversational.

## Questions to Ask (in order)
1. What are we building? What's the purpose of this project?
2. What language, framework, or key dependencies are we using?
3. Where are the main entry points? What files should I look at first?
4. Any conventions? Test runner, linter, code style, formatting rules?
5. Who else is working on this? Any team members I should know about?

## Rules
- Ask one or two questions at a time — never a wall of text
- Acknowledge each answer before moving to the next
- If the user wants to skip or start working, help them — don't gate on completion
- After the interview, write what you learned to the project manifest:
  - Purpose → "## Purpose" section
  - Stack → "## Stack" section
  - Entry points → "## Entry Points" section
  - Conventions → "## Conventions" section
  - Team → update .crabcakes/team.json with roles
- Append a dated entry to context.md summarizing the onboarding

## Current Project State
Project: {{PROJECT_NAME}}
Path: {{PROJECT_PATH}}
{{CURRENT_STATE}}
```

---

## 5. Delivery Mechanism

The onboarding prompt is injected via the existing `compose_system_prompt()` pipeline.

**New logic in `compose_system_prompt()`** (`utils/prompt_loader.py`):

After loading `project-awareness.md`, check if the project is onboarded:
- If **not onboarded** → also load `project-onboarding.md`
- If **onboarded** → skip it

This means the onboarding template is included in the system prompt only when needed — first interaction with a fresh project. Once `project.md` has real content, the template stops being loaded automatically.

**Selection order in `compose_system_prompt()`:**
1. Always: `default.md`
2. If project active: `project-awareness.md`
3. If project active AND not onboarded: `project-onboarding.md` ← NEW
4. If review mode on: `code-review.md`
5. If agent is coder/debugger: role-specific template

---

## 6. Files Changed

| File | Change |
|------|--------|
| `prompts/system/project-onboarding.md` | NEW — onboarding interview template |
| `utils/project_awareness.py` | Add `is_project_onboarded()` function |
| `utils/prompt_loader.py` | Add onboarding template selection in `compose_system_prompt()` |

---

## 7. What Does NOT Change

| Component | Reason |
|-----------|--------|
| `chat_handler.py` | Awareness injection already works; onboarding is just another template |
| `project_handler.py` | Project creation unchanged — onboarding happens at first interaction |
| `agent/context.py` | Already uses `compose_system_prompt()` — picks up onboarding automatically |
| Existing templates | No changes to default.md, project-awareness.md, etc. |

---

## 8. Testing Plan

| Test | What It Verifies |
|------|-----------------|
| `test_project_awareness.py::test_is_onboarded_skeleton` | Returns False for empty skeleton |
| `test_project_awareness.py::test_is_onboarded_with_content` | Returns True when Purpose filled |
| `test_project_awareness.py::test_is_onboarded_with_context` | Returns True when context.md has content |
| `test_prompt_loader.py::test_onboarding_template_loaded_for_new_project` | Included when not onboarded |
| `test_prompt_loader.py::test_onboarding_template_skipped_for_onboarded` | Excluded when onboarded |
| Manual: create new project → send message → agent asks questions | End-to-end flow |
| Manual: answer questions → check project.md populated | Write-back verification |

---

## 9. Future Enhancements (Out of Scope)

- Custom onboarding templates per project type (Python vs web vs data pipeline)
- Onboarding progress tracking (how many questions answered)
- Skip-onboarding preference in user settings
- Post-onboarding summary sent to team members

---

*Upon approval, implementation follows the checkpoint discipline.*
