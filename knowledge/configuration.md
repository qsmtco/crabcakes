# Configuration Guide

## agent.json

Located at `~/.config/crabcakes/agent.json`. This file configures LLM API providers.

### Structure

```json
{
  "providers": {
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-...",
      "default_model": "gpt-4o",
      "max_tokens": 128000
    }
  },
  "default_provider": "openai",
  "default_model": "openai/gpt-4o"
}
```

### Supported Providers

| Provider | base_url | Notes |
|----------|----------|-------|
| OpenAI | `https://api.openai.com/v1` | Standard OpenAI API |
| MiniMax | `https://api.minimax.chat/v1` | Large context (1M+ tokens) |
| OpenRouter | `https://openrouter.ai/api/v1` | Multi-model aggregator, free models available |

### Adding a Provider

Edit `agent.json` and add an entry under `providers`:

```json
"my-provider": {
  "base_url": "https://my-api.example.com/v1",
  "api_key": "your-key-here",
  "default_model": "my-model",
  "max_tokens": 128000
}
```

### Default Provider

The `default_provider` field controls which provider is used when an agent doesn't specify one. Special agents (Coder, Debugger) can override this in their YAML definition.

## Common Settings

| Field | Default | Description |
|-------|---------|-------------|
| `max_tool_iterations` | 50 | Max tool calls per conversation turn |
| `tool_timeout_seconds` | 120 | Timeout for each tool call |
| `cost_limit` | null | Per-conversation USD spending cap |
| `step_limit` | null | Per-conversation turn limit |

## Security

Run `chmod 600 ~/.config/crabcakes/agent.json` to restrict API key access. Crabcakes checks permissions on startup and warns if the file is group/world-readable.