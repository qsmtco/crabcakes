<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->

# Discovery Phase

Understand the problem deeply before building anything. This phase produces a requirements document.

---

## What You Do

1. Read `.crabcakes/project.md` for project context
2. Ask me about requirements, one topic at a time
3. Write findings to `.crabcakes/requirements.md`
4. Update `.crabcakes/workflow.md` — mark discovery as done
5. Append to `.crabcakes/context.md`

---

## Questions to Cover

Ask me one topic at a time. Acknowledge my answers before moving to the next topic.

### MVP Scope
**What must work in the first version?**
What is the smallest set of features that delivers value?

### Out of Scope
**What are we explicitly NOT building?**
What might seem obvious but isn't included?

### Users
**Who uses this? What are their workflows?**
Describe the primary user and how they'll interact with the system.

### Edge Cases
**What could go wrong? Error states?**
How does the system behave when things break or inputs are unexpected?

### Acceptance Criteria
**What does "done" look like?**
How do we verify each feature works? What tests or checks apply?

### Constraints
**Performance, security, compatibility, deadlines?**
Any non-negotiable limits or requirements?

---

## Output Format

When the conversation is complete, write to `.crabcakes/requirements.md`:

```markdown
# Requirements — {project_name}

## Problem Statement
{one paragraph describing the core problem this project solves}

## MVP Scope
{what's included in the first version}

## Out of Scope
{what's explicitly excluded}

## User Stories
- As a {user}, I want to {action} so that {benefit}
- ...

## Acceptance Criteria
- {criterion 1}
- {criterion 2}
- ...

## Constraints
- {constraint 1}
- {constraint 2}
- ...

## Edge Cases
- {edge case 1}
- {edge case 2}
- ...
```

---

## After Completion

1. Update `.crabcakes/workflow.md` — find the discovery row, change its status to ✅ done, set started/completed dates
2. Append to `context.md`: "Discovery phase complete. Requirements captured in requirements.md."
3. Suggest: "Next step: Architecture & Design. Load **cc-architecture-design** from the Prompts tab."
