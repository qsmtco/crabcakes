# Sub-Agent Tool

Spawn specialized agents to handle delegated work. Use when a task matches an agent's description or when parallelization would help.

## When to Use

**Research:** Fork open-ended questions when research can be broken into independent parts. Forks inherit context and share cache.

**Implementation:** Prefer forks for implementation work requiring more than a couple of edits. Do research before jumping to implementation.

**Delegation:** When a specialized agent exists for a specific task.

## Forks vs Subagents

**Forks** are lightweight — they share your prompt cache and are cheap to create. Good for:
- Parallel research tasks
- Independent subtasks
- When you need quick parallelization

**Subagents** are more isolated — better for:
- Tasks requiring different context
- Long-running independent work
- Tasks needing specific agent types

## Best Practices

**Don't duplicate work.** If you delegate research to a subagent, don't also perform the same searches yourself.

**Give clear context.** Pass the original request, relevant files, and your approach to the verifier.

**Protect context.** Forks are cheap but subagents can protect your main context from excessive results.

**Don't over-use.** Each spawned agent costs resources. Only fork when the benefit outweighs the cost.
