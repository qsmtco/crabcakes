# Task List Tool

View all tasks in the current session task list.

## When to Use

- See what tasks are available to work on
- Check overall progress on a project
- Find tasks that are blocked and need dependencies resolved
- After completing a task, check for newly unblocked work

## Output

Returns a summary of each task:
- **subject**: Brief description
- **status**: pending, in_progress, or completed
- **owner**: Assigned agent ID (empty if available)
- **blockedBy**: Tasks that must be resolved first

## Best Practices

Work on tasks in ID order (lowest first) when multiple are available — earlier tasks often set up context for later ones.

Use TaskGet to view full details of a specific task by ID.
