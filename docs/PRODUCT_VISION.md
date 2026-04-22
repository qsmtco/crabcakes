# CrabCakes — Product Vision

**Last updated:** 2026-04-21

---

## What CrabCakes Is

A GTK4 desktop AI development environment. Two execution systems under one surface:

- **Command System** — gateway pipeline, OpenClaw agents, remote sessions
- **Agent Runtime System** — local LLM calls, tool execution, no gateway needed

Same UI. Same chat tabs. Same render pipeline. Different execution paths, transparent routing.

---

## What's Built

### Command System ✅
Gateway-based agent communication. CrabCakes connects to an OpenClaw gateway via WebSocket. Agents live on the gateway. CrabCakes sends messages, receives events, renders chat. Handles agent lifecycle, presence, session management. This is how Qaster, Qrusher, and other OpenClaw agents are reached.

Spec: `docs/command-system.md`

### Agent Runtime ✅
Local agent execution engine. LLM API calls go directly to OpenAI, MiniMax, Anthropic. Tool loop executes locally — file reads/writes, exec commands, web search. PM approval gates for exec_command. Streaming SSE support. Cost tracking per conversation. Conversation persistence to disk.

21 bugs found in adversarial audit, all 21 fixed. 73 agent-runtime tests passing.

Spec: `docs/agent-runtime.md` · Audit: `docs/ADVERSARIAL_AUDIT_AGENT_RUNTIME.md`

### Convergence Detection ✅
Determines when a multi-agent conversation has naturally concluded. Random Forest classifier with 10 features, trained on 266 real conversation fixtures. 261/266 classify correctly. Intended as the stop condition for agent-to-agent loops.

Currently dead code — nothing in CrabCakes imports it. Plugs in when agent collaboration is built.

Spec: `docs/convergence-detection.md` · Audit: `docs/ADVERSARIAL_AUDIT_CONVERGENCE.md`

### GTK4 Port ✅
Full port from GTK3 to GTK4. All 14 phases complete. End-to-end working: connect → agent tabs → send/receive messages. 8 bugs found and fixed during port.

### UI Extraction ✅
Handler extraction from monolithic window.py into separate modules:
- `ui/handlers/chat_handler.py` — send, fan-out, routing
- `ui/handlers/gateway_handler.py` — connect, agents, lifecycle
- `ui/handlers/media_handler.py` — STT + prompt improvement
- `ui/handlers/agent_runtime_handler.py` — local agent callbacks (partial, Phase 1.4 incomplete)

### Agent Cards ✅
SVG avatar rendering (circle + hexagon + initials). Agent list with sorting. Left panel integration.

---

## Build Layers (dependency order)

```
1. Agent Runtime          ← ✅ DONE (Phase 1.1–1.3b)
2. Phase 1.4 — UI wiring  ← ✅ DONE (2026-04-21)
3. Phase 1.5 — Staging writes (runtime-side review hookup) ← ✅ DONE (2026-04-21)
4. Review Layer           ← ✅ DONE (2026-04-21) — git-backed code review (tracked → isolated/AgentFS)
5. Task Layer             — task cards, / commands, assign work, track progress
```
- Open a project
- Launch Coder or Debugger
- Assign a task
- Agent reads, writes, executes
- Writes captured by review layer
- PM reviews diffs, accepts/rejects
- Task marked complete

Full loop. One agent at a time. That's v1.0.

---

## Post-v1.0 (multi-agent and beyond)

| Feature | Description | Spec Status |
|---------|-------------|-------------|
| Agent Routing | Which agent gets which task. The switchboard. | In ARCHITECTURE.md as `models/routing.py` |
| Agent Collaboration | Coder + Debugger working together. Convergence stops the loop. | `docs/agent-collaboration.md` |
| Agent Memory | Per-agent per-project memory files. Agents remember across sessions. | Not spec'd yet |
| Test Runner | Post-accept pytest/npm test. Blocks or warns on failures. | Not spec'd yet |
| Project Onboarding | New agents get briefed on project history + git log + chat context. | Not spec'd yet |
| Performance Tracking | Per-agent stats: acceptance rate, cost, time. Know who's actually good. | Not spec'd yet |

These make CrabCakes *more powerful*. But they're not needed to ship.

---

## Spec Map

| System | Spec File | Status |
|--------|-----------|--------|
| Command System | `docs/command-system.md` | ✅ Built |
| Agent Runtime (Phases 1.1–1.5) | `docs/agent-runtime.md` | ✅ Built + shipped |
| Review Layer | `docs/review-layer.md` | ✅ Built (2026-04-21) |
| Convergence Detection | `docs/convergence-detection.md` + `converge/` | ⚠️ Built (dead code — nothing imports it) |
| Architecture | `docs/ARCHITECTURE.md` | Living doc |
| Audit — Agent Runtime | `docs/ADVERSARIAL_AUDIT_AGENT_RUNTIME.md` | 21/21 resolved |
| Audit — Convergence | `docs/ADVERSARIAL_AUDIT_CONVERGENCE.md` | 13 bugs documented |

---

## Project Tab — Agent Cognition Interface

The Project tab's FileTree is reimagined as a live oversight layer, not a file browser. Three features form the core:

**Live Attention** — files light up in real-time as the agent reads them during a session. A dim glow indicates exploratory reads; brighter indicators signal active engagement. The PM watches the agent's focus unfold live, not as a post-hoc log.


**Breadcrumb Trail** — each file node carries a conversation link. Click it and the chat scrolls to every message where that file was mentioned or acted on. The PM sees the discussion context behind each file change before reviewing the diff.


**One-Click Diff** — click any modified file in the tree → immediately see its diff in the review layer. The action layer of the oversight loop.


These three form a complete loop: *see* (attention) → *understand* (breadcrumbs) → *act* (diff + accept/reject). They build from existing data — conversation history is already persisted, file ↔ message linkage is an indexing problem, diff already exists in the review layer. No new infrastructure required beyond the tree UI.


---

## The Philosophy

The jump from "doesn't exist" to "single-agent coding assistant with review and task management" is the big one. Everything after that is iterative. The ship is never really done — you just keep adding rooms.
