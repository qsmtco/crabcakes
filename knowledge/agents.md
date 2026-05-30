# Agents Guide

## Built-in Agents

Crabcakes ships with three built-in special agents:

| Agent | Emoji | Role | Writes Files |
|-------|-------|------|-------------|
| Coder | 🛠️ | Full-stack code writing | Yes |
| Debugger | 🐛 | Read-only analysis and debugging | No |
| Crabcakes | 🦀 | Platform help and onboarding | Config only |

## Creating a Custom Agent

### Via UI

1. Click the **+** button in the left panel's Agents section
2. Fill in the agent's name, emoji, role, and tools
3. Select a provider and model
4. Write a system prompt (or use the default)
5. Click **Save**

### Via YAML

Create a file at `~/.config/crabcakes/agents/my-agent.yaml`:

```yaml
name: My Agent
emoji: "🤖"
role: my-agent
prompts:
  - system/my-agent.md
tools:
  - read_file
  - write_file
  - exec_command
provider: openai
model: gpt-4o
```

The system prompt file goes in `prompts/system/my-agent.md` (in the Crabcakes install directory).

## Agent Fields Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name in the UI |
| `emoji` | Yes | Avatar emoji |
| `role` | Yes | Matches `prompts/system/{role}.md` |
| `tools` | Yes | Tool names the agent can use |
| `provider` | Yes | LLM provider (from agent.json) |
| `model` | No | Model override (defaults to provider default) |
| `auto_open` | No | Open tab on every launch |
| `auto_add_to_projects` | No | Auto-add to new project teams |

## Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Write to a file |
| `edit_file` | Targeted edits within a file |
| `exec_command` | Run shell commands |
| `list_files` | List directory contents |
| `search_files` | Search for patterns in files |
| `web_search` | Search the web |
| `web_fetch` | Fetch a URL and extract content |

## Agent System Prompts

System prompts are Markdown files in `prompts/system/`. They support `{{VARIABLE}}` template substitution for project context injection. The agent's role field in YAML determines which prompt file is loaded.