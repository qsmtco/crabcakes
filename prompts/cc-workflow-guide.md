<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->

# Workflow Guide

Welcome to the CrabCakes workflow. This guide explains the phases available for structured development.

> **Quick-fix mode is always available.** If you just want something done — "fix this bug", "add this feature" — just say so. No workflow required.

---

## The 7 Phases

| # | Phase | When to Use | Produces |
|---|-------|-------------|----------|
| 0 | Onboarding | Project creation (auto) | `project.md`, `context.md` |
| 1 | Discovery | New project, unclear requirements | `requirements.md` |
| 2 | Architecture | Design before code | `architecture.md` |
| 3 | Task Planning | Break design into tasks | Tasks in TaskStore, `tasks.md` |
| 4 | Implementation | Engine runs (no prompt needed) | Code, commits |
| 5 | Testing | Comprehensive testing after build | Test results |
| 6 | Ship | Deploy, release, handoff | Release artifacts |

Phases 0–3 are prompts you load from the Prompts tab. Phase 4 is handled by the engine. Phases 5–6 will be addressed in a future proposal.

---

## Phase Status

Read `.crabcakes/workflow.md` and display the current phase status below. If the file doesn't exist yet, say so.

Show a table of all 7 phases with their current status (✅ done / 🔄 current / ⏳ pending).

---

## What Each Phase Produces

### Discovery (`cc-discovery`)
Reads `project.md`, asks you questions one at a time, produces `requirements.md` covering:
- Problem statement
- MVP scope
- Out of scope
- User stories
- Acceptance criteria
- Edge cases

### Architecture & Design (`cc-architecture-design`)
Reads `project.md` + `requirements.md`, discusses the design with you, produces `architecture.md` covering:
- Module breakdown
- Data flow
- File structure
- Dependencies
- Design patterns
- API surfaces
- Error handling

### Task Planning (`cc-task-planning`)
Reads `project.md` + `requirements.md` + `architecture.md`, proposes a task breakdown, creates tasks via `task add` after you approve.

---

## Quick-Fix Mode

The workflow is optional. You can skip all phases and just request:

```
"Fix the auth bug in crabwatch.py"
"Add a --verbose flag"
"Refactor the watcher to use async I/O"
```

The agent will execute directly — no discovery, no architecture, no task planning. Just work.

---

## How to Use This Guide

1. After onboarding, the agent will suggest loading this guide
2. Click **cc-workflow-guide** from the Prompts tab to load it
3. Review the phases and decide which ones you need
4. Load and run the phases you want — skip the ones you don't
5. At any point, send a direct request and the agent will switch to quick-fix mode

**Prompts tab search:** Type `cc` to find all workflow prompts.
