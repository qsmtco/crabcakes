<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->

# Task Planning Phase

Break the architecture into concrete, ordered, assignable tasks that the engine can execute.

---

## What You Do

1. Read `.crabcakes/project.md`, `.crabcakes/requirements.md`, and `.crabcakes/architecture.md`
2. Propose a task breakdown ordered by dependency
3. Present the plan to me for review
4. I approve, modify, or reject tasks
5. Create each approved task using CrabCakes slash commands (typed in the project feed, NOT a shell CLI)
6. Update `.crabcakes/workflow.md` — mark task-planning as done
7. Append to `.crabcakes/context.md`

---

## Task Guidelines

### One Concern Per Task
Each task does one thing. Don't combine unrelated changes.

### Ordered by Dependency
What blocks what? Tasks must be listed in execution order.

### Clear Acceptance Criteria
How do we verify the task is done? What does success look like?

### Size Estimates

| Size | When to Use | Engine Behavior |
|------|-------------|-----------------|
| **S** (Small) | Single file, <50 lines, straightforward | Completes in 1 cycle |
| **M** (Medium) | 2–3 files, some complexity | May need 2–3 cycles (build → fail → fix → pass) |
| **L** (Large) | Multi-module, complex logic | **Engine refuses L tasks.** Split into S/M first. |

### Suggested Assignee
Based on team roles. Leave blank if unsure.

---

## Task Format

For each task, propose:

```
## Task: {title}
**Size:** S | M | L
**Description:** {what to do}
**Acceptance Criteria:** {how to verify done}
**Depends On:** {task number or "none"}
**Assignee:** {role or blank}
```

---

## My Review

I will:
- Approve tasks as-is
- Modify task scope or size
- Reject tasks that don't fit the architecture
- Ask you to split L tasks into S/M before approval

Wait for my approval before creating tasks.

---

## After Approval

For each approved task, ask the PM to create it in CrabCakes using the slash command (typed in the project feed):
```
/task @assignee — description
```
Or create it yourself if you have access to the CrabCakes command system.

**Important:** This is a CrabCakes slash command, NOT a shell/terminal command. Do not run `/task` in a terminal.

Then write a summary to `.crabcakes/tasks.md`:
```markdown
# Task Plan — {project_name}

| # | Task | Size | Status |
|---|------|------|--------|
| 1 | {task 1} | S | created |
| 2 | {task 2} | M | created |
| ...
```

---

## After Completion

1. Update `.crabcakes/workflow.md` — find the task-planning row, change its status to ✅ done, set started/completed dates
2. Append to `context.md`: "Task Planning phase complete. {N} tasks created."
3. Suggest: "All tasks created. Use `` /tasks `` to review, or tell the assigned agent to `` /start #1 ``."
