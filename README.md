# 🦀 CrabCakes

A native GTK4 desktop client for [OpenClaw](https://github.com/openclaw/openclaw) — chat with your AI agents, manage prompts, run project group chats, and dictate with your voice. Built for Linux.

![Python](https://img.shields.io/badge/Python-3.12-blue) ![GTK4](https://img.shields.io/badge/GTK-4.0-green) ![Tests](https://img.shields.io/badge/tests-95%20passing-brightgreen)

---

## Features

- **Multi-Agent Chat** — Connect to your OpenClaw gateway, discover agents, open chat tabs for each one
- **Prompt Library** — Load `.md` prompt files from the `prompts/` directory, inject them into conversations
- **Project Group Chat** — Open a project directory, fan-out messages to all member agents, route responses back to a single project tab
- **Membership Management** — Add/remove agents from projects with +/− toggles
- **Speech-to-Text** — Push-to-talk voice input via [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
- **Prompt Improvement** — One-click prompt refinement via MiniMax API
- **Session Switching** — Multiple sessions per agent, switch via popover menu

## Architecture

```
crabcakes/
├── gateway/          WebSocket client + Ed25519 device auth
├── models/           Pure data — agent state, color palettes
├── ui/
│   ├── window.py     Main window — assembles and wires everything
│   ├── handlers/     Extracted logic (chat, gateway, media)
│   └── views/        GTK4 widgets (tabs, sidebar, file tree)
├── utils/            File I/O, STT engine, prompt improvement
├── prompts/          70+ prompt templates
└── tests/            95 tests, all passing
```

**Design principles:**
- Strict layer separation — `gateway/` and `models/` never import `ui/`
- Callback-based composition — components communicate through callbacks, not direct imports
- Thread-safe — background threads dispatch all GTK calls via `GLib.idle_add()`

## Requirements

- Python 3.12+
- PyGObject (GTK4 bindings)
- `websockets`
- `cryptography`
- OpenClaw gateway running locally (default `ws://localhost:18789`)

**Optional (for voice input):**
- [`whisper.cpp`](https://github.com/ggerganov/whisper.cpp) built binary
- `arecord` (alsa-utils)
- GGML whisper model (~1.6GB)

## Installation

```bash
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install pygobject websockets cryptography
```

## Running

```bash
python main.py
```

Click **Connect** to hook into your OpenClaw gateway. Agents will appear in the sidebar — click one to open a chat tab.

### Debug Mode

```bash
CRABCAKES_DEBUG=1 python main.py
```

## Configuration

| Environment Variable | Default | Purpose |
|---------------------|---------|---------|
| `CRABCAKES_GATEWAY_URL` | `ws://localhost:18789` | OpenClaw gateway URL |
| `CRABCAKES_PROJECTS_DIR` | `~/projects` | Root directory for projects |
| `WHISPER_CLI` | `~/whisper.cpp/build/bin/whisper-cli` | Whisper binary path |
| `WHISPER_MODEL` | `~/whisper.cpp/models/ggml-large-v3-turbo.bin` | Whisper model path |

## Testing

```bash
pytest
```

95 tests covering agent management, chat routing, gateway lifecycle, project I/O, media handling, and prompt improvement.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the authoritative codebase reference (module APIs, data flows, naming conventions, GTK4 patterns)
- [`docs/HANDLER_EXTRACTION_PLAN.md`](docs/HANDLER_EXTRACTION_PLAN.md) — handler refactoring roadmap

## License

See [LICENSE](LICENSE).

---

*Part of the Qontinuum Bridge project.*
