# Agent Collaboration — Specification

**Date:** 2026-04-19
**Status:** Pre-build spec
**Build Phase:** 4 (depends on Phase 0: Commands, Phase 1: Agent Runtime, Phase 3: Task Layer)
**Related:** `docs/convergence-detection.md` (termination math)

---

## Overview

Agents in a project can collaborate through the project feed. They don't talk directly — CrabCakes routes messages on their behalf. The PM watches, intervenes only when needed.

**Core principle:** Agents collaborate through the feed, not with each other. CrabCakes is the router. The PM is the manager.

---

## How It Works Today (Existing Code)

CrabCakes already has the plumbing:

1. **`gateway.send_message(session_key, text)`** — sends a message to any agent
2. **`AgentRoutingTable.get_project(session_key)`** — maps agent to project
3. **`ChatHandler.on_chat_event()`** — routes agent responses to `project:<name>` tab if agent is a project member

When Debugger responds to any message, `on_chat_event` checks if Debugger is a project member, sees yes, routes the response to the project feed. **This already works. No routing code needs to be written.**

The only missing piece is the `ask` command that triggers the initial message from one agent to another.

---

## The `ask` Command

### Agent-Initiated

```
Coder: I'm hitting a segfault in test_auth.py
Coder: `ask @Debugger — segfault in test_auth.py line 47, any ideas?
```

CrabCakes intercepts the `` `ask `` command:
1. Parses `@Debugger` → resolves to Debugger's session key (empty `@` = all project members)
2. Sends the question text to Debugger via `gateway.send_message()`
3. Displays a delegation card in the project feed
4. Debugger responds → response automatically routes to project feed (existing code)

### PM-Initiated

```
PM: `delegate @Debugger — Coder needs help with the segfault in test_auth.py
```

Same routing. Same result. The PM just decided to start it instead of the agent.

### PM Stop

```
PM: `stop
```

Terminates the active collaboration. No more messages routed between the agents. Final state written to project feed as a card.

---

## Collaboration Lifecycle

### Exchange Model

Every collaboration is a bounded series of exchanges. An exchange is one message from each direction.

**Default: 3 exchanges.**

```
Exchange 1: Question → Answer
Exchange 2: Follow-up → Response
Exchange 3: Acknowledgment → Confirmation
→ Done.
```

After exchange 3, convergence detection runs (see `docs/convergence-detection.md`). If the math says the conversation is still active (convergence score < 0.55), one more exchange is allowed. Re-evaluate after each extension.

**Hard cap: 10 exchanges.** No exceptions. Pull-the-plug limit.

### State Machine

```
                    ┌──────────┐
                    │  Idle    │
                    └────┬─────┘
                         │ `ask or `delegate
                         ▼
                    ┌──────────┐
              ┌─────│  Active  │─────┐
              │     └──────────┘     │
              │ `stop               │ exchange 3 reached
              ▼                      ▼
         ┌──────────┐         ┌──────────────┐
         │ Stopped  │         │ Evaluating   │
         │ (by PM)  │         └──────┬───────┘
         └──────────┘                │
                              ┌──────┴──────┐
                              │             │
                         C >= 0.55      C < 0.55
                              │             │
                              ▼             ▼
                        ┌──────────┐  ┌──────────┐
                        │ Complete │  │ Extended │
                        │          │  │ (+1)     │
                        └──────────┘  └────┬─────┘
                                           │
                                           │ (loop back to Active,
                                           │  increment exchange count)
                                           └──→ Active
```

### Collaboration Card in Feed

When a collaboration starts, a live card appears in the project feed:

```
┌─────────────────────────────────────────────┐
│ 🔗 Coder ↔ Debugger · Exchange 1/3          │
│ Budget: $0.12 spent · $0.88 remaining       │
│                                              │
│ Topic: segfault in test_auth.py              │
│ Latest: Debugger investigating...            │
│                                              │
│ [Stop]                                       │
└─────────────────────────────────────────────┘
```

Card updates in place as exchanges happen. Exchange counter ticks up. Budget debits. "Latest" field shows the most recent message summary (first 80 chars).

When complete:
```
┌─────────────────────────────────────────────┐
│ ✅ Coder ↔ Debugger · Complete              │
│ 3 exchanges · $0.14 · 2m 32s                │
│                                              │
│ Outcome: Found use-after-free at line 47     │
│ Fix: defer session cleanup                   │
│                                              │
│ [View Thread]                                │
└─────────────────────────────────────────────┘
```

---

## Visibility in the Feed

Agent collaboration messages appear as normal chat bubbles in the project feed, just like PM messages. Agent names on the left, text on the right, alternating as the conversation flows.

```
Coder: `ask @Debugger — segfault in test_auth.py line 47
┌─────────────────────────────────────────────┐
│ 🔗 Coder → Debugger · Exchange 1/3          │
└─────────────────────────────────────────────┘
Debugger: Looking at it... found it. Use-after-free at line 47.
Debugger: Session object freed before response sent. Fix: defer cleanup to on_finish().
Coder: Applied the fix. Tests passing.
┌─────────────────────────────────────────────┐
│ ✅ Coder ↔ Debugger · Complete · 3 exchanges │
└─────────────────────────────────────────────┘
```

The PM watches this like watching two teammates in a group chat. No special UI. Same bubbles. Same scroll.

---

## Convergence Detection

Full spec in `docs/convergence-detection.md`. Summary:

After exchange 3, compute convergence score C from 5 signals:

1. Response Length Decay — responses shrinking = converging
2. Semantic Novelty — new info dropping = converging
3. Perplexity — model certainty rising = converging
4. Entropy — word diversity dropping = converging
5. Question Density — questions dropping = converging

**Rule:**
- C >= 0.75 → stop (converged)
- C >= 0.55 → extend by 1 (borderline)
- C < 0.55 → continue (still working)
- Hard cap: 10 exchanges

---

## Budget

Every collaboration has a cost budget. Default: $1.00 per collaboration.

- Each exchange debits the budget (tokens × model cost)
- When budget drops below 25%: warning card in feed
- When budget hits 0: collaboration pauses, card asks PM to extend or end
- PM can extend with `` `stop `` or by clicking [+ $1.00] on the card

Budget is the safety net. Convergence is the primary mechanism. Budget catches the edge cases where agents say novel but useless things.

---

## Delegation Modes

PM controls how freely agents can collaborate:

| Mode | Agent can `ask` | PM approval needed |
|------|----------------|-------------------|
| **Auto** | Yes | No (budget only) |
| **Suggest** | Yes (as suggestion card) | Yes (PM clicks approve) |
| **Off** | No | N/A |

**Default for new projects:** Suggest

**Configured per-project** in `.crabcakes/project-config.json`:
```json
{
  "delegation_mode": "suggest",
  "delegation_budget": 1.00,
  "max_exchanges": 10
}
```

---

## PM Controls

| Action | How | Effect |
|--------|-----|--------|
| Start collaboration | `` `delegate @agent — message `` (empty `@` = all members) | PM-initiated collaboration |
| Stop collaboration | `` `stop `` | Kills active collaboration immediately |
| Change delegation mode | `.crabcakes/project-config.json` | Auto/Suggest/Off |
| Adjust budget | `.crabcakes/project-config.json` | Per-collaboration dollar limit |
| View thread | Click [View Thread] on card | Scroll to full exchange in feed |

---

## Information Sharing (`tell`)

Agents can share information with each other without waiting for a response:

```
Coder: `tell @Debugger — I found a race condition in auth_handler.py, might be relevant
```

CrabCakes routes the message to Debugger via `gateway.send_message()`. Debugger sees it in their session. No response expected. No convergence check runs. This is fire-and-forget — the sending agent decides whether information is relevant enough to share.

This replaces the need for a shared context bulletin board. Agents convey context through collaboration commands (`ask`, `tell`) directly in the project feed.

---

## Architecture Compliance

### Module Placement

```
crabcakes/
├── ui/
│   └── handlers/
│       └── collaboration_handler.py   # NEW — collaboration lifecycle, exchange counting, budget
├── models/
│   └── collaboration.py               # NEW — Collaboration, CollaborationState dataclasses
└── utils/
    └── convergence.py                  # NEW — convergence score computation (5 signals)
```

### Layer Rules

| Module | Imports | Does NOT import |
|--------|---------|-----------------|
| `models/collaboration.py` | Nothing | No `ui/`, no `gateway/`, no GTK |
| `utils/convergence.py` | Standard library only (math, collections) | No `ui/`, no GTK |
| `ui/handlers/collaboration_handler.py` | `models/collaboration.py`, `utils/convergence.py` | No other handlers directly |

| Module | Imports | Does NOT import |
|--------|---------|-----------------|
| `models/collaboration.py` | Nothing | No `ui/`, no `gateway/`, no GTK |
| `utils/convergence.py` | Standard library only (math, collections) | No `ui/`, no GTK |
| `ui/handlers/collaboration_handler.py` | `models/collaboration.py`, `utils/convergence.py` | No other handlers directly |

### Wiring

- `CollaborationHandler` created and wired in `window.py`
- `` `ask `` command handler in `CommandHandler` delegates to `CollaborationHandler.start_collaboration()`
- `` `stop `` command handler delegates to `CollaborationHandler.stop_collaboration()`
- No handler-to-handler imports. Window is the composition root.

---

## Phase Plan — Build Phase 4: Agent Collaboration

### Step 4.1 — Data Models + Convergence Math

1. Create `models/collaboration.py` — `Collaboration` dataclass, `CollaborationState` enum
2. Create `utils/convergence.py` — `compute_convergence()` function (5 signals, weighted sum)
3. Write `tests/test_convergence.py` — test with synthetic response sequences
4. Write `tests/test_collaboration_models.py`
5. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Given a sequence of responses, `compute_convergence()` returns a score. Unit tests verify it detects convergence in politeness loops and non-convergence in active debugging.

### Step 4.2 — Collaboration Handler

1. Create `ui/handlers/collaboration_handler.py`
2. Wire into `ui/window.py` — create handler, connect to CommandHandler
3. Register `` `ask ``, `` `delegate ``, `` `stop `` commands in CommandHandler
4. Wire exchange counting, convergence check, budget tracking
5. Write `tests/test_collaboration_handler.py`
6. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Type `` `ask @Debugger — test question `` in a project tab → message routes to Debugger → Debugger responds → response appears in project feed → exchange counter increments → after 3 exchanges, convergence check runs.

### Step 4.3 — Collaboration Cards + Feed Integration

1. Add collaboration card CSS to `ui/styles.py`
2. Add card rendering to `ui/views/chat_bubble.py`
3. Wire live card updates (exchange count, budget, status)
4. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Collaboration cards render in the project feed. Cards update in real-time as exchanges happen. Completed collaborations show outcome summary.

### Step 4.4 — Information Sharing (`tell`)

1. Add `tell` command to CommandHandler
2. Wire as fire-and-forget (no response expected, no convergence check)
3. Test: agent sends info to teammate → teammate receives it in project feed
4. Update `docs/ARCHITECTURE.md`

**Checkpoint:** `` `tell @Debugger — I found a race condition`` → Debugger receives message in project feed. No card shown. No exchange counting.

---

*This spec covers the collaboration lifecycle, routing, convergence, budget, and PM controls. Information sharing is handled via the `tell` command. Convergence math details are in `docs/convergence-detection.md`.*
