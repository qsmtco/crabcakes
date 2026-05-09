# CrabCakes

**The world's first Project Development Environment.**

Where your project is the goup chat. Where the social media style project feed is the dashboard. Where agents are your team.

---

## What is this?

CrabCakes is a **native GTK4 desktop application** that turns multi-agent chat into a project development environment. It connects to an [OpenClaw](https://github.com/openclaw/openclaw) gateway, discovers your agents, and gives them a shared workspace — complete with project group chat, task management, git-backed code review, and automatic convergence detection.

This isn't an IDE with a chatbot bolted on. This is a fundamentally different mental model:

> **The project IS the chat. The feed IS the dashboard. Agents are first-class collaborators you manage like a team.**

You create a project. You bring in your agents. You work together in a shared feed. Everything that happens — decisions, code changes, consultations, task completions — appears as structured cards in a real-time project feed. You never switch windows. You never lose context. You just work.

---

## Why it exists

Every AI coding tool makes the same trade-off: either the agent works alone (great for speed, terrible for quality) or a human supervises every action (great for control, terrible for scale). The moment you want two agents to collaborate — one writing, one reviewing, one debugging — you're duct-taping prompts together and hoping the output doesn't confuse the agent

The real problem isn't making agents do things. The real problem is **orchestrating agents as a team** — giving them shared context, a shared feed, a shared task system, and a shared review layer. That's what CrabCakes solves.

It was designed around one insight: **the model is the commodity. The harness is the differentiator.** CrabCakes is that harness.

---

## Features

### 🌊 Project Group Chat
Your entire project team — human and agents alike — in one tab. Open a project, type a message, and it fans out to every member simultaneously. Responses route back to the project tab. Every exchange is visible to you, so you always know exactly what's happening and why.

```
Project: ManoPea
Members: QTR, Qaster, Coder, Debugger (you)

──────────────────────────────────────────────────────
You:     @Coder — implement the booking flow endpoint
Coder:   On it. Starting with the Prisma schema...
QTR:     @Coder I already have the schema ready in 
         auth/models.py — check there first
Coder:   Perfect, using your schema. Consultation 
         card posted.
         [Consultation card appears in project feed]
```

### 🤖 Special Agents — Coder & Debugger
Two agents run **locally**, directly on your machine, without a gateway. They have full file access, shell execution, and enforcement guards that verify every write: syntax checks, test runs, and lint validation — automatically, after every change.

- **Coder** — reads your architecture docs, writes production code, emits diff cards for every file change
- **Debugger** — attaches to failed sessions, analyzes errors, proposes and validates fixes

Both agents are project-aware from the first message. They read your `.crabcakes/` project docs (architecture, requirements, context, tasks) and stay aligned with your codebase's conventions at all times.

### 🔍 Convergence Detection
Agents always respond — that's what LLMs do. The hard problem is knowing when they're *done*. CrabCakes implements a **convergence detection system** trained on 266 real multi-agent conversations. It reads 10 behavioral signals — response length decay, semantic novelty, word entropy, topic stability — and automatically closes consultation threads when the work is naturally finished.

No hard turn limits. No magic keywords. No manual "stop" required.

```
Coder:   Ready. Auth flow implemented.
         [convergence detected → consultation closes 
          automatically]
```

Built on a Random Forest with 200 trees. **99.1% accuracy.** Runs locally in sub-millisecond time. No GPU, no cloud dependency.

### 📋 Task System
Structured task management baked into the project feed. Create tasks, assign them to agents, track priority and status.

| Command | What it does |
|---------|-------------|
| `` `task @Coder — fix the null pointer in user.py `` | Creates a task, assigns to Coder |
| `` `start #3 `` | Begins work on task #3 |
| `` `done #3 — resolved with a guard clause `` | Marks task complete with notes |
| `` `blocked #5 — waiting on API spec `` | Reports a blocker |
| `` `tasks `` | Shows all tasks in the project feed |
| `` `priority #2 high `` | Sets priority level |

Every task command emits a card to the project feed. The full task history is always visible.

### 🪵 CrabCards — Structured Project Feed
Every significant action in the project generates a **CrabCard** — a structured activity card in the feed. Not a wall of chat text. Not a raw terminal dump. A scannable, actionable signal.

**Types:**

- **`diff`** — a file was changed. Shows additions, deletions, and the actual diff. Click to review.
  ```
  ┌─────────────────────────────────────────────┐
  │ 📄 auth/middleware.py                      │
  │ +12 −3  ·  Coder                           │
  │ ─ def old():                               │
  │ + def new():                               │
  │ +     if user is None:                     │
  │ +         raise ValueError(...)             │
  └─────────────────────────────────────────────┘
  ```

- **`agent_action`** — an agent signaled intent or a decision. Used for consultation starts, consultation closes, and task completions.
  ```
  ┌─────────────────────────────────────────────┐
  │ 💬 Consulting @QTR on token validation     │
  │ Coder · consultation                        │
  └─────────────────────────────────────────────┘
  ```

- **`review_request`** — a block of code is ready for PM review.

### 🔬 Enforcement Layer
When Coder writes a file, three things happen automatically, in sequence:

1. **Syntax guard** — `py_compile` / `node --check` / equivalent runs immediately after every write
2. **Test runner** — detects the test framework, finds relevant tests, runs them against the changed file
3. **Lint check** — detects the linter, runs it on the changed file

If any step fails, Coder receives the error output and self-corrects before the file is considered done. No prompt reminders. No hoping the model remembers to verify. The enforcement layer *makes* it happen.

### 🦀 CrabWatch — Live Filesystem Monitoring
Every file in your project is watched in real time. Changes made outside CrabCakes (git operations, manual edits, external tools) are detected and reflected in the feed — no refresh required.

### 📝 Code Review Layer
Git-backed code review for every agent write:

1. **Checkpoint** — agent writes trigger a `git add -A` and diff against the last checkpoint
2. **Review** — you see the full unified diff in the project chat: file by file, hunk by hunk
3. **Accept/Reject** — Accept commits the changes. Reject resets to the checkpoint SHA

Agents can continue working while you review. Nothing is merged until you say so.

### 🎙️ Voice Input
Push-to-talk voice dictation powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp). No cloud. No latency. Hold a key, speak, release — your words appear in the input box. Particularly useful when you're mid-flow and switching from keyboard to voice saves a context switch.

### ✨ Prompt Library
70+ curated prompt templates organized in a searchable sidebar. Load a prompt into the input with one click. Prompts can include template variables (`{{VARIABLE_NAME}}`) that get filled from the current project context (project name, team roster, current git state, project memory). Use the built-in prompt improver to refine any template via the MiniMax API before loading it.

### 🔀 Session Switching
Every agent maintains multiple concurrent sessions. Right-click any agent tab to open a popover session switcher — create new sessions, rename them, or switch between ongoing threads. Each session is a fully independent conversation context.

---

## Architecture

CrabCakes is built on strict layer separation — a principle that makes it readable, maintainable, and trustworthy:

```
┌─────────────────────────────────────────────────────────┐
│  ui/                                                  │
│  GTK4 widgets, handlers, views                        │
│  Never imports gateway/ or models/                     │
├─────────────────────────────────────────────────────────┤
│  gateway/          models/          agent/            │
│  WebSocket client  Pure data        Local agent        │
│  No UI deps       No UI deps        runtime           │
│                   No gateway deps   No UI deps        │
├─────────────────────────────────────────────────────────┤
│  utils/                                                  │
│  Pure Python — file I/O, prompts, STT, config          │
└─────────────────────────────────────────────────────────┘
```

**The rule:** `gateway/` and `models/` must never import from `ui/`. They are the foundation that the UI depends on — not the other way around. This means the gateway client is testable, the data models are deterministic, and the agent runtime is scriptable — all without loading a single GTK widget.

---

## The stack

| Layer | Technology |
|-------|-----------|
| UI framework | GTK4 (PyGObject) |
| Network | `websockets` + `cryptography` (Ed25519 device auth) |
| Agent runtime | OpenAI / MiniMax / Anthropic APIs |
| Voice input | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (local) |
| Code review | GitPython |
| Threading | GLib main context dispatch |

---

## Running

```bash
# Install dependencies
pip install pygobject websockets cryptography gitpython

# Start the OpenClaw gateway (if not already running)
openclaw gateway start

# Launch CrabCakes
python main.py
```

Click **Connect** to link to your gateway. Agents appear in the left sidebar — click any one to open a chat tab. Open a project directory to activate project group chat, task management, and the full development environment.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CRABCAKES_GATEWAY_URL` | `ws://localhost:18789` | OpenClaw gateway WebSocket URL |
| `CRABCAKES_PROJECTS_DIR` | `~/projects` | Root directory for project workspaces |
| `WHISPER_CLI` | `~/whisper.cpp/build/bin/whisper-cli` | Path to whisper.cpp binary |
| `WHISPER_MODEL` | `~/whisper.cpp/models/ggml-large-v3-turbo.bin` | Whisper model file |
| `CRABCAKES_DEBUG` | `0` | Set to `1` for verbose debug output |

---

## Testing

```bash
pytest
```

95 tests covering agent management, chat routing, gateway lifecycle, project I/O, media handling, and prompt improvement. All passing.

---

## What's in the box

```
crabcakes/
├── main.py                      # Entry point
├── gateway/                     # WebSocket client + v3 device auth
│   └── client.py                # Threaded, auto-reconnecting
├── models/                      # Pure data: agents, tasks, feed cards, reviews
├── agent/                       # Local runtime for Coder + Debugger
│   ├── runtime.py               # Tool loop, streaming, cost tracking
│   ├── tools.py                 # read_file, write_file, edit_file, exec_command, ...
│   ├── context.py               # System prompt builder + project awareness
│   ├── enforcement.py           # Post-write syntax + test + lint guards
│   └── special_agents.py        # Coder + Debugger agent definitions
├── ui/
│   ├── window.py                # Main window — composition root
│   ├── handlers/                # Extracted logic modules
│   │   ├── chat_handler.py      # Send, fan-out, routing, convergence
│   │   ├── collab_handler.py    # ask / delegate / stop / tell commands
│   │   ├── task_handler.py      # Task CRUD commands
│   │   ├── review_handler.py    # Review session lifecycle
│   │   └── agent_runtime_handler.py  # Coder/Debugger UI bridge
│   └── views/                   # GTK4 widget factories
│       ├── feed_card.py         # CrabCard renderers
│       ├── diff_card.py         # Unified diff viewer
│       └── chat_bubble.py       # Chat bubble factories
├── converge/                    # Convergence detection engine
│   ├── converge.py              # Random Forest convergence classifier
│   └── model.pkl                # Pre-trained model (200 trees)
├── utils/
│   ├── prompt_loader.py         # System prompt composition engine
│   ├── crabcard_parser.py        # CrabCard block parser
│   ├── feed_store.py            # Feed JSON persistence
│   ├── git_ops.py               # GitPython wrapper
│   └── stt.py                   # Whisper.cpp push-to-talk engine
└── prompts/
    └── system/                  # 70+ agent prompt templates
        ├── default.md           # Identity + tool instructions
        ├── coder.md             # Full engineering methodology
        ├── debugger.md          # Systematic diagnosis
        ├── collab.md            # Agent-to-agent collaboration
        └── ...
```

---

## A note on the name

CrabCakes is named after the Chesapeake Bay delicacy — sweet, rich, and built from parts that other people throw away. The project started as a way to make multi-agent collaboration actually work in practice, not just in demos. It now runs production systems.

---

*Part of the Qontinuum Bridge project.*
*CrabCakes: where your project is the chat.*
