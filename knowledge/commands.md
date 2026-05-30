# Command Reference

## Slash Commands

Commands are typed in the chat input and processed by the project or agent.

### Project Commands

| Command | Description |
|---------|-------------|
| `/status` | Show project status (members, tasks, review state) |
| `/agents` | List project members and their state |
| `/cost` | Spending summary for current project |
| `/solo @Agent` | Switch to solo DM with one agent |
| `/solo all` | Return to broadcast mode |
| `/review` | Start code review session |
| `/review stop` | End code review session |

### Agent Commands

| Command | Description |
|---------|-------------|
| `/ask @Agent "question"` | Consult an agent for their expertise |
| `/delegate @Agent "task"` | Assign a task to an agent |
| `/tell @Agent "information"` | Share info without expecting a response |
| `/stop @Agent` | Remove agent from project collaboration |

### Task Commands

| Command | Description |
|---------|-------------|
| `/task create "title"` | Create a new task for a project member |
| `/task list` | List all tasks for the project |
| `/task status <id>` | Show detailed status for a task |
| `/task update <id> <field> <value>` | Update a task field |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in message input |
| `Ctrl+Space` | Push-to-talk voice input |
| `Ctrl+,` | Open Settings |

## Command Syntax Rules

- Commands start with `/` at the beginning of a message
- Agent mentions use `@AgentName`
- Payloads in quotes: `/ask @Agent "your question here"`
- Max 3 commands per message
- Unrecognized commands are sent as regular messages