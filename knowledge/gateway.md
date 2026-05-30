# Gateway Guide

## What is the Gateway?

The OpenClaw gateway is the central AI orchestration server that Crabcakes connects to. It manages agent sessions, WebSocket connections, and tool execution for gateway-connected agents.

## Connection

Crabcakes connects to the gateway via WebSocket using Ed25519 device authentication:

1. Click **Connect** in the toolbar
2. Crabcakes authenticates with the configured gateway URL
3. On success, the toolbar shows "Connected" and gateway agents appear in the left panel

## Gateway vs Special Agents

Crabcakes has two types of agents:

### Gateway Agents
- Managed by the OpenClaw gateway
- Appear in the left panel after connecting
- Sessions can be switched from the session menu
- Tool execution handled by the gateway

### Special Agents
- Run locally within Crabcakes
- Configured via YAML in `~/.config/crabcakes/agents/`
- Have direct access to local files and tools
- Include Coder, Debugger, and Crabcakes

## Configuration

The gateway URL is configured in `~/.config/crabcakes/settings.json`:

```json
{
  "gateway_url": "http://localhost:18797"
}
```

Or set the `CRABCAKES_GATEWAY_URL` environment variable.

## Troubleshooting

- **"Offline" status** — Check that the gateway is running. Run `openclaw gateway status` to verify.
- **Auth errors** — Check that your device key is registered. Run `openclaw device list` to see registered devices.
- **No agents appear** — Gateway must have active sessions for agents to appear. Create sessions via `openclaw session create`.
- **Connection timeout** — Verify the gateway URL is correct and the port is accessible. Check firewall rules.