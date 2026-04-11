# Task Management Tool

Update the task list for the current session. Track progress and organize complex work.

## When to Use

Proactively manage tasks when:
- Starting work on a multi-step task
- Completing a task
- Discovering new tasks during implementation
- User provides a list of things to do

## Task States

- **pending**: Not yet started
- **in_progress**: Currently working on (limit to ONE)
- **completed**: Finished successfully

## Best Practices

- Mark tasks as in_progress BEFORE starting
- Update status in real-time
- Mark complete immediately when done
- Keep exactly ONE task in_progress
- Remove tasks no longer relevant
- Never mark complete if:
  - Tests are failing
  - Implementation is partial
  - Errors remain unresolved

## Task Fields

Each task needs:
- **content**: Imperative form (e.g., "Run tests")
- **activeForm**: Present continuous (e.g., "Running tests")
