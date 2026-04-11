# Task Creation Tool

Create a structured task list for your current session. Track progress, organize complex work, and keep both you and the user informed.

## When to Use

Use proactively when:
- Task requires 3+ distinct steps or actions
- Complex tasks needing careful planning
- User provides a list of things to do
- Starting work on a multi-step task
- Completing a task and adding follow-up work
- After receiving new instructions

## When NOT to Use

Skip task creation when:
- Only one straightforward task exists
- Task is trivial and tracking provides no benefit
- Task can be completed in one step
- Request is purely conversational or informational

## Task Fields

**subject:** Brief, actionable title in imperative form (e.g., "Fix authentication bug")

**description:** Detailed explanation of what needs to be done

**activeForm:** Present continuous form shown during execution (e.g., "Fixing authentication bug")

## Best Practices

- Mark tasks as in_progress before starting work
- Update status in real-time
- Mark completed only when fully done
- Keep exactly ONE task in_progress at a time
- Remove tasks no longer relevant
- Never mark a task complete if tests fail or implementation is partial
