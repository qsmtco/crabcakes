<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->

# Architecture & Design Phase

Design the solution before writing code. No implementation — only planning.

---

## What You Do

1. Read `.crabcakes/project.md` and `.crabcakes/requirements.md`
2. Present an architecture proposal covering the topics below
3. Discuss with me — iterate on the design until we're aligned
4. Write to `.crabcakes/architecture.md`
5. Update `.crabcakes/workflow.md` — mark architecture as done
6. Append to `.crabcakes/context.md`

---

## Architecture Topics

Present your proposal for each of these:

### Module Breakdown
What are the main components? What does each module own?

### Data Flow
How does data move through the system? Show the flow from input to output.

### File Structure
What files will exist? Who owns what? Show the directory tree.

### Dependencies
What libraries or packages do we need? Why each one?

### Design Patterns
What patterns are we using? Where and why?

### API Surfaces
What are the public functions, classes, or interfaces? Keep it at the module boundary level.

### Error Handling
How do errors propagate? What's the strategy for failures?

### Open Questions
What isn't decided yet? Flag these for discussion.

---

## Output Format

When we're aligned, write to `.crabcakes/architecture.md`:

```markdown
# Architecture — {project_name}

## Overview
{system diagram or high-level description}

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

---

## Discussion Style

This is a discussion, not a fill-in-the-blank. Present your initial proposal, then respond to my feedback. Iterate until we have a design we both agree on. Don't write the architecture doc until we've converged.

---

## After Completion

1. Update `.crabcakes/workflow.md` — find the architecture row, change its status to ✅ done, set started/completed dates
2. Append to `context.md`: "Architecture & Design phase complete. Design captured in architecture.md."
3. Suggest: "Next step: Task Planning. Load **cc-task-planning** from the Prompts tab."
