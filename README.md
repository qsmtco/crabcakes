# CrabCakes — The First Project Development Environment

**Not an AI assistant. Not a chatbot. A complete development environment where your project is the team.**

---

## What is it?

CrabCakes is a standalone desktop application that reimagines project management as a social feed. Your project has its own group chat. Your agents are team members. Your feed is the dashboard. Everything happens in one window — decisions, code, reviews, tasks — visible in real time, searchable, persistent.

You can open it right now and start working. **No gateway required.** Coder and Debugger are built in, running locally on your machine with full file and shell access. Connect to OpenClaw and you gain access to your remote agents too — but you don't need to.

This is the first PDE. A Project Development Environment.

---

## The core idea

Every tool today makes the same trade-off: agents work alone (fast, uncontrolled) or humans supervise every action (safe, unscalable). The moment you want two agents to collaborate — one writing, one reviewing — you're duct-taping prompts together and hoping nothing breaks.

The real problem isn't making agents do things. It's **orchestrating them as a team**.

CrabCakes solves this by making the project itself the social context. Not a prompt you feed them. Not a task list you manage. The actual project — its files, its history, its team — is what they operate inside.

> **The project IS the chat. The feed IS the dashboard. Agents are teammates you manage.**

---

## What you get

### 🏠 Standalone — Runs With or Without OpenClaw

CrabCakes launches and is immediately functional. Two built-in agents — **Coder** and **Debugger** — run locally on your machine. They have full file access, shell execution, and enforcement guards that verify every change: syntax check → test run → lint validation — automatically, after every write.

No gateway. No cloud. No account required.

When you do connect to OpenClaw, your remote agents join the project chat seamlessly. The toolbar shows your connection state at all times. Offline mode is a first-class feature, not a degraded fallback.

---

### 💬 Project Group Chat — The Project IS the Chat

Open a project and the team appears. Every member — you, Coder, Debugger, your OpenClaw agents — shares a single conversation. Type a message, it fans out to everyone simultaneously. Responses route back to the project tab.

```
Project: CargoAPI — 4 members online

You:       @Coder — implement the rate limiter
Coder:     On it. Starting with the token bucket.
QTR:        @Coder I left a draft in lib/ratelimit.py 
            from last week — use that as a base
Coder:     Perfect. Consulting QTR first.
            [consultation opens with QTR]
```

You see everything. You control what gets merged. Agents collaborate with each other and you watch it happen in real time.

---

### 🐟 Convergence Detection — Agents Know When They're Done

Agents always respond. The hard part is knowing when they're *finished*.

CrabCakes runs a **convergence detection engine** trained on 266 real multi-agent conversations. It reads 10 behavioral signals — response length decay, semantic novelty, word entropy, topic stability — and automatically closes consultation threads when the work is naturally done.

```
Coder:   Ready. Auth middleware is passing all tests.
         [convergence detected → consultation closes]
QTR:     Confirmed. Reviewing the diff now.
```

No hard turn limits. No magic keywords. No manual "stop" required. Built on a Random Forest with 200 trees. **99.1% accuracy.** Runs locally in sub-millisecond time.

---

### 📋 Task System — No Context Switching

Task management baked into the project feed. Create, assign, track, and close tasks without leaving the conversation.

| Command | Result |
|---------|--------|
| `` `task @Coder — implement the auth middleware `` | Creates task, assigns to Coder |
| `` `start #3 `` | Begins work, emits card to feed |
| `` `done #3 — all tests passing `` | Closes task with notes |
| `` `blocked #7 — waiting on API spec `` | Escalates to feed |
| `` `priority #2 high `` | Reorders work queue |
| `` `tasks `` | Shows full project task board in feed |

Every action emits a structured card to the project feed. Full history always visible.

---

### 📰 Project Feed — Your Social Dashboard

Every significant action generates a **card** — not a wall of chat text, not a raw terminal dump. A scannable, actionable signal.

**Diff cards** — a file was changed. Shows additions, deletions, the full diff. Click to review.
```
┌──────────────────────────────────────────────────┐
│ 📄 auth/middleware.py — Coder                  │
│ +12 −3                                          │
│  ─ def old():                                  │
│  + def new():                                  │
│  +     if user is None:                         │
│  +         raise ValueError(...)                │
└──────────────────────────────────────────────────┘
```

**Task cards** — created, started, completed, blocked.

**Review cards** — checkpoint diff ready for your review. Accept or reject with one click.

**Agent action cards** — consultation opens, consultation closes, agent signals a decision.

---

### 🔍 Git-Backed Code Review

Every agent write is checkpointed before it reaches your codebase:

1. **Checkpoint** — agent writes trigger a `git add -A` against the last clean state
2. **Diff** — you see the full unified diff: file by file, hunk by hunk
3. **Accept / Reject** — Accept commits the change. Reject resets to the checkpoint SHA

Agents can keep working while you review. Nothing touches your codebase until you approve it. Multiple agents can be writing simultaneously — each writes to its own branch, and you accept or reject each diff independently.

---

### 🤖 Built-In Coding Agents — Coder & Debugger

**Coder** — reads your architecture docs, your `.crabcakes/` project context, your team roster. Writes production code. Emits a diff card for every file change. Self-corrects on enforcement failures before the file is considered done.

**Debugger** — attaches to failed sessions, analyzes the error, proposes a fix, validates it against your test suite, and reports back.

Both are project-aware from the first message. They know your conventions, your project structure, your .gitignore. They don't start cold — they read your docs first.

Enforcement runs automatically after every write:
1. **Syntax guard** — `py_compile` / `node --check` runs immediately
2. **Test runner** — detects your test framework, runs relevant tests
3. **Lint check** — runs your configured linter on the changed file

If anything fails, the agent receives the error and self-corrects. No prompts. No reminders.

---

### 🎙️ Voice Input

Push-to-talk voice dictation powered by faster-whisper. No cloud. No latency. Hold a key, speak, release — your words land in the input box. Particularly useful when you're mid-flow and grabbing the keyboard would break your concentration.

---

### ✨ Prompt Improvement

Every prompt in the library can be refined before loading. The built-in prompt improver sends your template to the MiniMax API and returns a rewritten version with better structure, clearer instructions, and sharper edge cases. Templates can include variables (`{{PROJECT_NAME}}`, `{{TEAM}}`, `{{GIT_STATE}}`) that fill from the current project context.

---

### 💎 Chat Formatting — Readable at a Glance

Chat bubbles are formatted for comprehension, not just display:

- **Pango-aware escaping** — your code and special characters never break the layout
- **Markdown rendering** — code blocks with syntax highlighting, inline code, bold, italic, links
- **Segmented rendering** — text, code, URLs, and actions in a single bubble each styled correctly
- **Action buttons** — forward messages, copy text, reply in-context
- **Role differentiation** — visual distinction between You, Agent, System, and Error bubbles
- **Thinking indicator** — animated indicator while agents are processing

---

### 📂 Project Browser — Always in Context

File tree in the left panel shows your project structure. Open any file directly from the tree. Browse directories, see what's changed. The project you're working in is never more than a click away.

Create new projects from the Projects tab. Open existing ones. Member management — add and remove agents from your project team — handled directly in the panel.

---

### 🔗 OpenClaw Integration — Optional

When the gateway is running, CrabCakes connects to it and discovers your remote agents automatically. Remote agents appear alongside your local ones in the project chat. You can chat with them directly, add them to project teams, and collaborate across the full team — local and remote.

When the gateway is offline, local agents keep working. The toolbar shows your connection state. You're never blocked by the gateway.

---

## Architecture

Strict layer separation — makes the codebase readable, trustworthy, and testable:

```
┌─────────────────────────────────────────────────────────┐
│  ui/                                                   │
│  GTK4 widgets, handlers, views                         │
│  Never imports gateway/ or models/                     │
├─────────────────────────────────────────────────────────┤
│  gateway/        models/           agent/              │
│  WebSocket       Pure data         Local agent         │
│  No UI deps      No UI deps        runtime             │
│                  No gateway deps   No UI deps          │
├─────────────────────────────────────────────────────────┤
│  converge/                                           │
│  Convergence detection engine — Random Forest          │
├─────────────────────────────────────────────────────────┤
│  utils/                                               │
│  Pure Python — file I/O, prompts, STT, config          │
└─────────────────────────────────────────────────────────┘
```

---

## Running

```bash
# Install dependencies
pip install pygobject websockets cryptography gitpython

# Launch — works immediately, no gateway required
python main.py

# If you want to connect to OpenClaw agents:
openclaw gateway start
# Then click Connect in the toolbar
```

---

## Environment variables

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

---

## What's inside

```
crabcakes/
├── main.py                        # Entry point — creates app, runs Gtk.main()
├── gateway/                       # WebSocket client — threaded, auto-reconnecting
│   └── client.py                  # v3 device auth, event dispatch
├── models/                        # Pure data: agents, tasks, feed cards, routing
├── agent/                         # Local agent runtime
│   ├── runtime.py                 # Tool loop, streaming, cost tracking
│   ├── context.py                 # System prompt builder + project awareness
│   ├── tools.py                   # read_file, write_file, edit_file, exec_command
│   ├── enforcement.py            # Post-write syntax + test + lint guards
│   └── special_agents.py         # Coder + Debugger agent definitions
├── converge/                      # Convergence detection engine
│   ├── converge.py                # Random Forest — 200 trees, 10 signals
│   └── model.pkl                  # Pre-trained model
├── ui/
│   ├── window.py                  # Main window — composition root
│   ├── toolbar.py                 # Connection state + connect button
│   ├── handlers/                  # Extracted logic
│   │   ├── chat_handler.py       # Send, fan-out, routing, convergence
│   │   ├── collab_handler.py     # ask / delegate / stop / tell
│   │   ├── task_handler.py       # Task CRUD commands
│   │   ├── review_handler.py     # Review session lifecycle
│   │   ├── agent_runtime_handler.py  # Coder/Debugger lifecycle bridge
│   │   └── chat_render_handler.py    # Escape + markdown + bubble pipeline
│   └── views/
│       ├── feed_card.py           # Diff, task, review, action card renderers
│       ├── chat_bubble.py         # Bubble factories + segment rendering
│       └── diff_card.py           # Unified diff viewer
└── utils/
    ├── escaping.py               # Pango-aware XML escape
    ├── markdown.py               # Markdown → Pango Markup converter
    ├── stt.py                    # faster-whisper push-to-talk
    ├── improve.py               # MiniMax prompt improvement API
    └── git_ops.py               # GitPython wrapper
```

---

## A note on the name

CrabCakes is named after the Chesapeake Bay delicacy — sweet, rich, and built from parts other people throw away. The project started as a way to make multi-agent collaboration actually work in practice, not just in demos. It now runs production systems.

---

*Part of the Qontinuum Bridge project.*
*CrabCakes: where your project is the chat.*
*The first PDE.*