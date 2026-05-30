# Crabcakes Setup Guide

## Installation

Crabcakes is a native GTK4 Linux desktop app for multi-agent AI development.

### Quick Start

```bash
cd ~/projects/crabcakes
pip install -e .
```

### Requirements
- Python 3.12+
- GTK 4.0+
- A running OpenClaw gateway (for gateway agents)

### First Launch

1. Run `crabcakes` from your terminal
2. On first launch, `~/.config/crabcakes/agent.json` is created with example provider configurations
3. Add your API keys to get started

## Configuration Directory

All configuration lives in `~/.config/crabcakes/`:

| File | Purpose |
|------|---------|
| `agent.json` | LLM API providers and model settings |
| `agents/` | Agent YAML definitions (Coder, Debugger, etc.) |

## Connecting to a Gateway

1. Click the **Connect** button in the toolbar
2. The gateway URL defaults to your configured OpenClaw endpoint
3. Once connected, gateway agents appear in the left panel under "Agents"

## Project Setup

1. Click **New Project** in the left panel's Projects tab
2. Enter a project name
3. The project directory is created under `$CRABCAKES_PROJECTS_DIR` (defaults to `~/crabcakes-projects/`)
4. A `.crabcakes/` directory is initialized with project configuration files
5. Git is auto-initialized with an initial commit

## Next Steps

- Add API keys → see `knowledge/configuration.md`
- Create custom agents → see `knowledge/agents.md`
- Explore features → see `knowledge/features.md`