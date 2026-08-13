<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Do not rename or delete — referenced by the workflow guide. -->

# Spec Planning Phase (`cc-spec-planning`)

Turn the architecture into concrete, orderable Work Units. Each Work Unit carries a required spec file — the atomic implementation contract — that a builder will execute and an auditor will verify.

Replace the old flat-task model. A **Work Unit** bundles a title, a `spec_path`, a status, a priority, dependency IDs, and supervisor/builder/auditor assignments.

---

## What You Do

1. Read `.crabcakes/project.md`, `.crabcakes/requirements.md`, and `.crabcakes/architecture.md`
2. Propose Work Units ordered by dependency, each with a required `spec_path`
3. Present the plan to me for review
4. I approve, modify, or reject Work Units
5. Create approved Work Units using `/work` commands (typed in the project feed, NOT a shell CLI)
6. Wait for approval before any creation or readiness transition
7. Update `.crabcakes/workflow.md` — mark spec-planning as done, only after approved Work Units/spec stubs are recorded
8. Append to `.crabcakes/context.md`

---

## Work Unit Guidelines

### One Concern Per Work Unit
Each Work Unit does one thing. Don't combine unrelated changes.

### Ordered by Dependency
What blocks what? Work Units must be listed in execution order and reference `depends_on`.

### A Required Spec Per Work Unit
Every Work Unit MUST have a `spec_path` — the relative path to its spec file, the atomic implementation contract. The spec file defines behavior, acceptance criteria, and edge cases before any build.

### Required `spec_path`
Each proposed unit carries a `spec_path`. Creation starts at `status="draft"` with an empty `spec_path`; the spec author marks it `spec-ready` only after the relative spec file actually exists.

---

## Work Unit Format

Propose each Work Unit like this:

```
## Work Unit: {title}
**Spec Path:** {relative path, e.g. docs/specs/SPEC-1-{slug}.md}
**Status:** draft | spec-pending | spec-ready
**Priority:** low | medium | high | critical
**Depends On:** {unit id or "none"}
**Supervisor:** {role or blank}
**Builder:** {role or blank}
**Auditor:** {role or blank}
```

---

## My Review

I will:
- Approve Work Units as-is
- Modify scope, priority, or assignments
- Reject Work Units that don't fit the architecture
- Ask you to split oversized units before approval

Wait for my approval before creating Work Units or transitioning readiness.

---

## After Approval

Use `/work` commands (typed in the project feed) to create and manage Work Units — never flat `/task` prose:

- `/work "Title"` — create a Work Unit as `status="draft"`
- `/work assign #N @agent` — set supervisor/builder/auditor
- `/work priority #N level` — set priority (low/med/high/critical)
- `/work spec-ready #N <spec_path>` — mark ready after `<spec_path>` exists
- `/work start #N` — trigger the implementation loop (hands off to the Supervisor)

**Important:** These are CrabCakes slash commands, NOT shell/terminal commands. Do not run them in a terminal.

> **`.crabcakes/tasks.md` is GENERATED from `.crabcakes/work.json` — do not hand-write it.** Work units live in `.crabcakes/work.json`; the markdown summary is a generated artifact, not a source of truth.

---

## Implementation Handoff

The implementation phase is **not** an autonomous engine. It is triggered **manually** via `/work start #N`, which hands off to the Supervisor (who loads `prompts/implementationLoop.md`). The Supervisor orchestrates the builder/auditor trio per Work Unit.

---

## After Completion

1. Update `.crabcakes/workflow.md` — find the spec-planning row, change its status to ✅ done, set started/completed dates
2. Append to `context.md`: "Spec Planning phase complete. {N} Work Units created."
3. Suggest: "Work Units approved. Use `/work list` to review, or `/work start #N` to begin implementation."
