<!-- 🦀 CRABCAKES WORKFLOW PROMPT -->
<!-- This prompt is part of the CrabCakes development workflow. -->
<!-- Auto-injected by the engine during BUILD stroke. NOT shown in Prompts tab. -->

You are executing task **#{{TASK_ID}}: {{TASK_TITLE}}**

---

## Context

- **Architecture:** read `.crabcakes/architecture.md`
- **Requirements:** read `.crabcakes/requirements.md`
- **Previous notes:** read `.crabcakes/context.md`

---

## Your Task

{{task description from the task object}}

---

## Acceptance Criteria

{{criteria from the task object}}

---

## Build Rules

- Follow the architecture doc — don't improvise structure
- Work in small, verified steps
- Write or update tests for what you build
- If tests exist: run them after each change
- Commit with task reference: `feat(task-{id}): {description}`
- If stuck after 3 attempts: mark blocked and report to PM

---

## After Building

1. Run tests: `{{test command}}` (check project.md for how to run tests)
2. If tests pass: commit, you're done
3. If tests fail: fix and retest (max 3 retries)
4. Report completion to PM
