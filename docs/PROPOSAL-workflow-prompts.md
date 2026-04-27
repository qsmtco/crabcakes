# Workflow Prompts — Formal Proposal

**Date:** 2026-04-26
**Author:** Qaster
**Status:** Proposed — Awaiting Captain JAQx Approval
**Affects:** `prompts/`, `prompts/system/`, `utils/workflow_state.py`

---

## 1. Objective

Create a library of workflow prompts that guide the PM and agent through the phases between onboarding and implementation. Each prompt is user-loadable from the Prompts tab, reads previous phase output, produces the next phase's deliverable, and auto-suggests the following step.

The five phases covered by this proposal:

1. **Workflow Guide** — meta-prompt, presents the map
2. **Discovery** — requirements gathering
3. **Architecture & Design** — solution design
4. **Task Planning** — break design into engine-consumable tasks
5. **Implementation** — the engine runs (no separate prompt, but guidance exists)

Post-implementation phases (comprehensive testing, code review, ship) are handled by the engine cycle and will be addressed in a separate proposal.

---

## 2. Design Principles

1. **Prompts are guides, not gates.** The PM can skip phases, work out of order, or ignore them entirely. A PM who says "fix this bug" to an agent should get a working fix — no workflow required.
2. **Each prompt reads previous output.** Discovery reads `project.md`. Architecture reads `project.md` + `requirements.md`. Task planning reads all three. This chain ensures continuity.
3. **Each prompt writes to `.crabcakes/`.** Phase output goes to versioned, agent-readable files. Any agent, any session, can pick up where the last one left off.
4. **Auto-suggest, don't auto-start.** After each phase completes, the agent suggests the next phase and which prompt to load. The PM decides whether to proceed.
5. **Quick-fix mode always works.** The workflow is for structured builds. Ad-hoc requests ("fix this bug", "add a logging line") work without it. The system supports both modes natively.

---

## 3. The Workflow Chain

```
PM creates project
    ↓
Onboarding (system prompt — auto-triggers on skeleton project.md)
    ↓ writes project.md, context.md
    ↓ agent suggests: "Load workflow-guide from the prompt library"
    ↓
Workflow Guide (user loads prompt)
    ↓ presents all phases, PM decides which to use
    ↓
Discovery (user loads prompt)
    ↓ reads project.md → writes requirements.md
    ↓ updates workflow.md: discovery = done
    ↓ agent suggests: "Load architecture-design from the prompt library"
    ↓
Architecture & Design (user loads prompt)
    ↓ reads project.md + requirements.md → writes architecture.md
    ↓ updates workflow.md: architecture = done
    ↓ agent suggests: "Load task-planning from the prompt library"
    ↓
Task Planning (user loads prompt)
    ↓ reads project.md + requirements.md + architecture.md
    ↓ creates tasks via conversation → PM approves
    ↓ agent runs `task add` for each approved task
    ↓ updates workflow.md: task-planning = done
    ↓ agent suggests: "Ready to build. Run `task run to start the engine."
    ↓
Implementation Engine (`task run)
    ↓ reads tasks from TaskStore + tasks.md
    ↓ runs PICK → BUILD → TEST → REVIEW → RECORD for each task
    ↓ (no user-loaded prompt — engine handles it via awareness injection)
    ↓ after all tasks complete → engine updates workflow.md
    ↓ agent suggests: "All tasks complete. Ready for comprehensive testing."
    ↓
[Post-engine phases — future proposal]
```

---

## 4. Prompt Specifications

### 4.1 `prompts/cc-workflow-guide.md` — The Map

**Loaded by:** PM clicks it from the Prompts tab.
**Purpose:** Present the full workflow, explain each phase, help the PM decide which ones they need.
**Reads:** `.crabcakes/project.md`, `.crabcakes/workflow.md` (if exists)
**Writes:** Nothing. Purely informational.

**Content:**
- List of all 8 phases with brief descriptions
- Which phases are recommended vs. optional
- What each phase produces and what the next phase needs
- Quick-fix mode explanation — "just tell the agent what to do"
- Phase status — reads workflow.md and shows which phases are done

**Auto-suggestion trigger:** Loaded after onboarding completes. Agent says: "Want to see the full workflow? Load **cc-workflow-guide** from the Prompts tab."

---

### 4.2 `prompts/cc-discovery.md` — Requirements Gathering

**Loaded by:** PM clicks it from the Prompts tab.
**Purpose:** Understand the problem deeply before building anything. Produce a requirements document.
**Reads:** `.crabcakes/project.md`
**Writes:** `.crabcakes/requirements.md`, updates `.crabcakes/workflow.md`

**What the agent does (instructed by the prompt):**

1. Read `project.md` for project context
2. Ask the PM about requirements, one topic at a time:
   - **MVP scope** — what must work in the first version?
   - **Out of scope** — what are we explicitly NOT building?
   - **Users** — who uses this? What are their workflows?
   - **Edge cases** — what could go wrong? Error states?
   - **Acceptance criteria** — what does "done" look like? How do we verify?
   - **Constraints** — performance, security, compatibility, deadlines
3. Write findings to `.crabcakes/requirements.md`:
```markdown
# Requirements — {project_name}

## Problem Statement
{one paragraph}

## MVP Scope
{what's included}

## Out of Scope
{what's explicitly excluded}

## User Stories
- As a {user}, I want to {action} so that {benefit}

## Acceptance Criteria
- {criterion 1}
- {criterion 2}

## Constraints
- {constraint 1}
- {constraint 2}

## Edge Cases
- {edge case 1}
```
4. Update `workflow.md` — mark discovery phase as `done`
5. Append dated entry to `context.md`: "Discovery phase complete. Requirements captured in requirements.md."
6. Suggest: "Next step: Architecture & Design. Load **cc-architecture-design** from the Prompts tab."

**Prompt format:** Conversational — agent asks questions one at a time, acknowledges answers, produces the doc at the end.

---

### 4.3 `prompts/cc-architecture-design.md` — Solution Design

**Loaded by:** PM clicks it from the Prompts tab.
**Purpose:** Design the solution before writing code. No implementation — only planning.
**Reads:** `.crabcakes/project.md`, `.crabcakes/requirements.md`
**Writes:** `.crabcakes/architecture.md`, updates `.crabcakes/workflow.md`

**What the agent does:**

1. Read project.md and requirements.md
2. Present an architecture proposal covering:
   - **Module breakdown** — what are the main components?
   - **Data flow** — how does data move through the system?
   - **File structure** — what files will exist? Who owns what?
   - **Dependencies** — what libraries/packages? Why?
   - **Patterns** — what design patterns are we using?
   - **API surfaces** — functions, classes, interfaces
   - **Error handling** — how do errors propagate?
3. Discuss with PM — iterate on the design
4. Write to `.crabcakes/architecture.md`:
```markdown
# Architecture — {project_name}

## Overview
{system diagram or description}

## Modules
### {module_1}
- **Responsibility:** {what it does}
- **Files:** {file list}
- **Dependencies:** {what it needs}

### {module_2}
...

## Data Flow
{how data moves through the system}

## File Structure
{tree of all files that will be created}

## Dependencies
- {dep} — {why}

## Patterns
- {pattern} — {where used and why}

## Error Handling
{strategy}

## Open Questions
- {things not yet decided}
```
5. Update `workflow.md` — mark architecture phase as `done`
6. Append dated entry to `context.md`
7. Suggest: "Next step: Task Planning. Load **cc-task-planning** from the Prompts tab."

---

### 4.4 `prompts/cc-task-planning.md` — Break Design Into Tasks

**Loaded by:** PM clicks it from the Prompts tab.
**Purpose:** Break the architecture into concrete, ordered, assignable tasks that the engine can execute.
**Reads:** `.crabcakes/project.md`, `.crabcakes/requirements.md`, `.crabcakes/architecture.md`
**Writes:** Creates tasks via `` `task add ``, updates `.crabcakes/workflow.md`

**What the agent does:**

1. Read project.md, requirements.md, and architecture.md
2. Propose a task breakdown:
   - **Ordered by dependency** — what blocks what
   - **One concern per task** — each task does one thing
   - **Clear acceptance criteria** — how to verify each task is done
   - **Complexity estimate** — S (one cycle), M (2-3 cycles), L (break it down)
   - **Suggested assignee** — based on team roles
3. Present the plan to the PM for review
4. PM approves, modifies, or rejects tasks
5. Agent creates each task via `` `task add @agent — description ``
6. Update `workflow.md` — mark task-planning phase as `done`
7. Append dated entry to `context.md`
8. Suggest: "All tasks created. Run `` `task run `` to start the engine, or review with `` `task list ``."

**Task size guidelines (encoded in the prompt):**
- **S (Small):** Single file, <50 lines, straightforward. Engine completes in 1 cycle.
- **M (Medium):** 2-3 files, some complexity. Engine may need 2-3 cycles (build → test fail → fix → pass).
- **L (Large):** Multi-module, complex logic. **Engine refuses L tasks.** Agent must split into S/M tasks before the PM approves the plan.

---

### 4.5 `prompts/system/cc-implementation.md` — Engine Guidance

**Loaded by:** Agent receives this context automatically through awareness injection during engine cycles. NOT loaded by PM from Prompts tab.
**Purpose:** Tell the agent how to behave during the BUILD stroke of the engine cycle.
**Where it lives:** `prompts/system/cc-implementation.md` — auto-injected when the engine is running.

**What it contains:**

```markdown
You are executing task #{TASK_ID}: {TASK_TITLE}

## Context
- Architecture: read .crabcakes/architecture.md
- Requirements: read .crabcakes/requirements.md
- Previous task notes: read .crabcakes/context.md

## Your Task
{task description from the task object}

## Acceptance Criteria
{criteria from the task object}

## Build Rules
- Follow the architecture doc — don't improvise structure
- Work in small, verified steps
- Write tests for what you build
- Commit with task reference: feat(task-{id}): {description}
- If stuck after 3 attempts, mark blocked and report to PM

## After Building
- Run tests: {test command from project.md conventions}
- If tests pass: commit, you're done
- If tests fail: fix and retest (max 3 retries)
```

This prompt is assembled by the EngineHandler during the BUILD stroke. It reads the task details + project context and sends it to the agent as a message. The agent follows it and produces code.

---

## 5. Auto-Suggestion Mechanism

### How the agent knows to suggest the next phase

**Location:** `prompts/system/project-awareness.md` — add a small section:

```markdown
## Workflow Suggestions
If this project recently completed a workflow phase (check workflow.md), suggest
the next phase to the PM:
- Onboarding complete → suggest loading cc-workflow-guide from Prompts tab
- Discovery complete → suggest loading cc-architecture-design
- Architecture complete → suggest loading cc-task-planning
- Tasks planned → suggest running `task run
- All tasks done → suggest comprehensive testing (future)

Keep suggestions brief — one line. Don't repeat if already suggested this session.
```

This is a nudge, not a gate. The agent mentions it once, then moves on. The PM can ignore it.

### How the agent detects phase completion

The agent reads `workflow.md` at the start of each session (via awareness injection). If a phase was just completed, the agent knows to suggest the next one. The detection is:

1. Agent receives awareness block with workflow.md state
2. Agent checks: is there a phase marked `done` with no subsequent phase started?
3. If yes → suggest the next phase and which prompt to load
4. If all phases done → suggest post-engine steps

### Quick-fix mode

If the PM sends a message that's clearly a direct request ("fix the auth bug", "add logging to the watcher"), the agent should:
1. Detect: this is an ad-hoc request, not a workflow phase
2. Execute: fix the bug, add the logging, whatever's needed
3. Skip: no discovery, no architecture, no task planning
4. Record: append to `context.md` what was done

No workflow enforcement. The agent helps however the PM wants to work.

---

## 6. Phase State Tracking

Each prompt updates `.crabcakes/workflow.md` when its phase completes. The `workflow_state.py` utility (from the engine proposal) handles this.

**Phase completion flow:**
1. Prompt instructs agent to write phase output (requirements.md, architecture.md, etc.)
2. Agent calls `workflow_state.advance_phase(project_path, phase_name)`
3. `workflow.md` updates: current phase marked `done`, next phase set to current
4. Agent appends to `context.md`: "{Phase} complete. Output in {filename}."
5. Agent suggests next phase to PM

**workflow.md example after task-planning:**

```markdown
## Phase History
| # | Phase | Status | Started | Completed | Notes |
|---|-------|--------|---------|-----------|-------|
| 0 | onboarding | ✅ done | 2026-04-26 | 2026-04-26 | project.md populated |
| 1 | discovery | ✅ done | 2026-04-26 | 2026-04-26 | requirements.md |
| 2 | architecture | ✅ done | 2026-04-26 | 2026-04-26 | architecture.md |
| 3 | task-planning | ✅ done | 2026-04-26 | 2026-04-26 | 6 tasks created |
| 4 | implementation | 🔄 current | 2026-04-26 | — | 0/6 tasks done |
```

---

## 7. Files Changed

| File | Action | Purpose |
|------|--------|---------|
| `prompts/cc-workflow-guide.md` | NEW | Meta-prompt: the workflow map |
| `prompts/cc-discovery.md` | NEW | Requirements gathering prompt |
| `prompts/cc-architecture-design.md` | NEW | Solution design prompt |
| `prompts/cc-task-planning.md` | NEW | Task breakdown prompt |
| `prompts/system/cc-implementation.md` | NEW | Auto-injected during engine BUILD stroke |
| `prompts/system/project-awareness.md` | MODIFY | Add workflow suggestion nudge |

**No code changes.** All changes are prompt files. The auto-suggestion mechanism uses the existing awareness injection system. Phase state tracking uses `utils/workflow_state.py` from the engine proposal.

### Naming Convention

All CrabCakes workflow prompts use the `cc-` prefix:
- **Namespaces** them from user-added prompts
- **Makes them searchable** — typing `cc` in the Prompts tab search bar surfaces all workflow prompts instantly
- **Signals importance** — these are built-in system prompts, not casual additions

### Header Stamp

Every `cc-` prompt file begins with this HTML comment block:

```markdown
<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->
```

- Invisible when rendered as markdown in chat
- Visible to anyone editing the file
- Prevents accidental deletion (other prompts reference these by filename)
- The 🦀 crab emoji is on-brand

---

## 8. Prompt File Details

### Output File Conventions

| Phase | Output File | Format |
|-------|------------|--------|
| Discovery | `.crabcakes/requirements.md` | Structured markdown (sections defined in prompt) |
| Architecture | `.crabcakes/architecture.md` | Structured markdown (sections defined in prompt) |
| Task Planning | Tasks in TaskStore + `.crabcakes/tasks.md` | Created via `` `task add `` commands |
| Implementation | Code files + git commits | Engine handles |

### Prompt Interdependencies

```
cc-workflow-guide.md
  └── references all other cc- prompts by name

cc-discovery.md
  ├── reads: project.md
  └── writes: requirements.md

cc-architecture-design.md
  ├── reads: project.md, requirements.md
  └── writes: architecture.md

cc-task-planning.md
  ├── reads: project.md, requirements.md, architecture.md
  └── writes: tasks (via `task add)

cc-implementation.md (system prompt, auto-injected)
  ├── reads: architecture.md, requirements.md, context.md
  └── receives: task details from engine
```

Each prompt explicitly tells the agent which files to read at the start. This ensures continuity across sessions — even if a different agent picks up a phase.

---

## 9. Quick-Fix Mode — How It Works Without the Workflow

The PM can bypass the entire workflow by simply typing a request in the project chat:

```
PM: "Fix the auth bug in crabwatch.py"
PM: "Add a --verbose flag to gitdiary.py"
PM: "Refactor the file watcher to use async I/O"
```

The agent:
1. Receives the message with project awareness (knows the codebase, git state, team)
2. Reads relevant files to understand the context
3. Makes the change
4. Runs tests (if they exist)
5. Commits with a descriptive message
6. Reports back

No workflow phases. No task creation. Just work. The workflow prompts are there for when the PM wants structure. They're invisible when the PM doesn't.

---

## 10. Architecture Compliance

- [x] All changes are prompt files — no code modifications (except `project-awareness.md` nudge)
- [x] Prompts in `prompts/` are user-loadable, not auto-injected (Section 2 directory structure)
- [x] `prompts/system/cc-implementation.md` is auto-injected only during engine BUILD strokes
- [x] Phase output in `.crabcakes/` follows existing directory conventions
- [x] `utils/workflow_state.py` is pure Python (defined in engine proposal)
- [x] No cross-handler imports, no new handlers, no GTK changes

---

## 11. Implementation Order

| Phase | What | Depends On |
|-------|------|-----------|
| 1 | Write `prompts/cc-workflow-guide.md` | Nothing |
| 2 | Write `prompts/cc-discovery.md` | Nothing |
| 3 | Write `prompts/cc-architecture-design.md` | Nothing |
| 4 | Write `prompts/cc-task-planning.md` | Engine proposal (`` `task add `` command) |
| 5 | Write `prompts/system/cc-implementation.md` | Engine proposal (engine BUILD stroke) |
| 6 | Add suggestion nudge to `prompts/system/project-awareness.md` | Nothing |
| 7 | Test the full chain on crabwatch | All above + engine proposal |

Phases 1-3 and 6 have zero code dependencies. They're just markdown files. Can be written and tested immediately.

---

## 12. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| PM finds prompts too rigid, skips them | High | Quick-fix mode always works. Prompts are optional. |
| Agent over-suggests next phase, becomes annoying | Medium | Suggest once per session. Don't repeat. Brief — one line. |
| Requirements/architecture docs become stale after implementation changes | Medium | Agent updates docs during RECORD stroke if files changed |
| Task planning creates tasks that don't match architecture | Low | Task planning prompt reads architecture.md. Agent cross-references. |
| L-size tasks slip through planning | Low | Task planning prompt refuses L tasks. Must split before approval. |

---

*Upon approval, prompts can be written immediately. Phases 1-3 and 6 have zero code dependencies.*
