# Quick Start Guide

## How do I install CrabCakes?

See the detailed guide: **[Installing CrabCakes](install.md)**

```bash
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
sudo apt install python3-gi python3-gi-cairo libgtk-4-dev libadwaita-1-dev
pip install -e .
```

**Requirements:** Python 3.12+, GTK 4.0+, PyGObject. Linux only.

## How do I configure providers?

See **[Configuration Guide](configuration.md)** and **[Providers Guide](providers.md)**.

Providers are configured in `~/.config/crabcakes/providers.yaml`. On first launch, the `local-kb` provider is auto-seeded — Auxilium can answer install and config questions immediately without any external API key.

To use Coder, Debugger, or other agents that need a real LLM, add a provider:

```bash
# Edit providers.yaml
nano ~/.config/crabcakes/providers.yaml
```

Add your API key and set the caller field (e.g. `openai`, `openrouter`, `minimax`).

## How do I start CrabCakes?

```bash
cd ~/projects/crabcakes
python3 main.py
```

Or with debug logging:

```bash
CRABCAKES_DEBUG=1 python3 main.py
```

## What happens on first launch?

1. `~/.config/crabcakes/` is created with default config
2. `ensure_kb_provider()` seeds the `local-kb` provider into `providers.yaml`
3. Auxilium's `llm_name` is set to `local-kb` (if empty)
4. KB HTTP server starts on `localhost:18790` (if KB index is available)
5. Auxilium auto-opens — you can immediately ask install/config questions

## How do I connect to the OpenClaw gateway?

See **[Gateway Guide](gateway.md)**.

1. Start the gateway: `openclaw gateway start`
2. Click **Connect** in CrabCakes toolbar
3. Gateway agents appear in the left panel

## How do I create a project?

1. Click **New Project** in the left panel
2. Enter a project name and path
3. A `.crabcakes/` directory is initialized with project config
4. Add agents with the **+** button
5. Start chatting in the project tab

See **[Projects Guide](projects.md)** for details.

## Where do I get help?

- Ask **Auxilium** (🦀) — click its tab and type your question
- See **[Troubleshooting](troubleshooting.md)** for common errors
- Check logs at `~/.config/crabcakes/logs/`
