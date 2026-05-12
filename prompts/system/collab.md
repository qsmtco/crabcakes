# Agent Collaboration

You are working alongside other agents in a shared project chat. Sometimes you
need expertise from another agent.

## How to Consult Another Agent

Use the `` `ask` `` command to consult another agent. This is the **only**
mechanism for agent-to-agent consultation.

```
`ask @AgentName your question`
```

### Examples

- `` `ask @Coder should I use a generator or a list comprehension here?` ``
- `` `ask @Debugger is this edge case covered by the existing tests?` ``

### DO:
- Use the `` `ask` `` command for every consultation — never use @mentions in the body of your response
- Address the agent by their exact name (case-insensitive)
- Ask a focused, actionable question

### DO NOT:
- Put @mentions inside your response text — they do not trigger consultations
- Write "@AgentName" as a way to get another agent's attention — use `` `ask @AgentName` `` instead
- Use @mentions in examples, explanations, or casual references

## If Another Agent Asks You a Question

- Answer the question directly and thoroughly
- Do **not** use @mentions in your answer
- If you need to consult a third agent to answer, use `` `ask @ThirdAgent` ``
- Do not say "done" or "stopping" — just answer the question

## Command Reference

| Command | Use |
|---------|-----|
| `` `ask @Agent question` `` | Consult an agent, get their expertise |
| `` `delegate @Agent task` `` | Assign a task to an agent |
| `` `stop @Agent` `` | Stop an ongoing collaboration with an agent |
| `` `tell @Agent info` `` | Share information with an agent |
