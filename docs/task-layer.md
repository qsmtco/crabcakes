# CrabCakes Task Layer — Inspiration Document

**Date:** 2026-04-19
**Status:** Inspiration — will become the spec
**Build Phase:** 3 (depends on Phase 1: Agent Runtime + Phase 2: Review Layer)
**Core principle:** The conversation IS the project management system.

---

## The Idea

No Kanban board. No ticket list. No status page. No sidebar panels.

Tasks live as special bubbles in the chat — inline with the conversation, the code review, the agent responses. Everything is one stream. You scroll up to see what happened. You scroll down to see what's happening. The conversation is the project.

---

## Task Cards

Tasks are born from conversation, not from forms. The PM types a `/task` command and it becomes a special card in the chat:

```
PM: let's get the login flow working
PM: /task Coder — implement JWT auth with refresh tokens
┌─────────────────────────────────────────────┐
│ 📋 Task #3 · Coder · ○ Todo                 │
│ Implement JWT auth with refresh tokens       │
│                                              │
│ [▶ Start] [↑ Priority] [✕ Cancel]           │
└─────────────────────────────────────────────┘
Coder: on it. I'll start with the auth middleware...
Coder: /done #3 — JWT auth implemented, tests passing
┌─────────────────────────────────────────────┐
│ ✅ Task #3 · Coder · Done                    │
│ Implement JWT auth with refresh tokens       │
│ [Review Changes →]                           │
└─────────────────────────────────────────────┘
```

### What makes this different

- **Tasks aren't in a separate database** you have to context-switch to
- **Tasks are born from conversation** — the PM's thought process is right there above the card
- **Tasks have full conversational context** above and below them — questions, clarifications, agent thinking
- **Completing a task links naturally to the review layer** — "Review Changes →" opens a diff review
- **Everything is in one scroll** — no tabs, no panels, no context switching

### Task card states

| State | Visual | Who sets it |
|-------|--------|-------------|
| Todo | 📋 ○ Todo | PM (on creation) |
| In Progress | 🔄 ● Working | Agent (on `/start #N`) |
| Review | 🔍 ⏳ Review | Agent (on `/done #N`) |
| Done | ✅ Done | PM (after accepting review) or auto |
| Blocked | 🚫 Blocked | Agent (on `/blocked #N — reason`) |
| Cancelled | ✕ Cancelled | PM (on `/cancel #N`) |

### Task card anatomy

```
┌─────────────────────────────────────────────┐
│ 📋 Task #3 · Coder · ○ Todo          [⋮]    │  ← header: icon, number, assignee, status, menu
│ Implement JWT auth with refresh tokens       │  ← description
│                                              │
│ [▶ Start] [↑ Priority] [✕ Cancel]           │  ← action buttons (context-sensitive)
└─────────────────────────────────────────────┘
```

**Header:** Task icon, number, assigned agent (with color dot), status badge, overflow menu (⋮) for reassign/edit/delete.

**Description:** The task text, from the `/task` command. Editable by PM via overflow menu.

**Action buttons:** Change based on state and who's viewing:
- Todo state: Start, Priority, Cancel
- In Progress state: (agent working — no PM actions needed)
- Review state: Review Changes, Reject
- Done state: (closed — "Review Changes" if not yet reviewed)
- Blocked state: Unblocked, Reassign, Cancel

---

## Slash Commands — The PM's API Surface

Every feature in CrabCakes is accessible through a `/` command. UI buttons and panels are just visual shortcuts for the same commands. This means:

1. **Everything is scriptable.** Power users type faster than they click.
2. **Everything is visible.** Commands appear in chat as bubbles — the conversation is a complete audit trail of PM decisions.
3. **Everything is teachable.** New users see commands in context and learn by watching the conversation.
4. **Agents use the same commands.** When Coder types `/done #3`, it's the same system. PM and agents share the same vocabulary.

### Command Reference

**Task management:**
- `/task <agent> — <description>` — create a task card assigned to an agent
- `/done <task#> [— notes]` — agent marks task complete (transitions to Review state)
- `/start <task#>` — agent starts working (transitions to In Progress)
- `/blocked <task#> — <reason>` — agent signals blocker
- `/cancel <task#>` — PM cancels a task
- `/assign <task#> <agent>` — reassign a task
- `/priority <task#> <low|medium|high|critical>` — set priority
- `/tasks` — render a summary card of all project tasks

**Review layer:**
- `/review` — PM starts a review session (checkpoint now)
- `/check` — check what changed since checkpoint
- `/accept` — accept all pending changes
- `/reject — <reason>` — reject all pending changes
- `/accept-file <file>` — accept a single file's changes
- `/reject-file <file> — <reason>` — reject a single file
- `/mode <off|review|isolated>` — change review mode

**Project management:**
- `/status` — render a project status summary card
- `/agents` — list project agents and their current state
- `/cost` — show spending summary for this project
- `/delegate <from-agent> <to-agent> — <message>` — PM asks one agent to help another
- `/context <file>` — inject a file into the active agent's context

**Agent actions:**
- `/ask <agent> — <question>` — agent asks another agent a question in the project feed
- `/note — <text>` — agent writes a note to its memory file for future sessions
- `/found <issue>` — Debugger reports a finding (creates a finding card)

**Utility:**
- `/undo` — revert last accepted change
- `/help` — list all available commands
- `/rename <task#> — <new description>` — edit a task description

### Command recognition

Commands are recognized by the ChatHandler before message routing:
1. PM types `/task Coder — fix the login bug`
2. ChatHandler detects `/` prefix
3. Parses command name (`task`) and arguments (`Coder`, `fix the login bug`)
4. Dispatches to the appropriate handler (TaskHandler, ReviewHandler, etc.)
5. Handler creates the card/bubble and appends it to the chat
6. Command bubble is rendered in the chat as a visual card (not plain text)

If the `/` command is unrecognized → render it as a plain message with a subtle "unknown command" hint.

### Autocomplete

When the PM types `/`, show an autocomplete popup:
- Lists all available commands with brief descriptions
- Filters as you type
- Tab to complete
- Shows required arguments as placeholder text

---

## The Conversation IS the Project

This is the core insight. Every other project management tool separates the conversation from the work. Slack is where you talk. Jira is where you track. GitHub is where you review. CrabCakes makes all three the same thing.

### What the conversation contains

A project conversation contains, in chronological order:
- PM instructions and questions
- Agent responses and questions
- **Task cards** (created, started, completed, blocked)
- **Diff cards** (from review layer)
- **Status cards** (from `/status`, `/tasks`, `/cost`)
- **Finding cards** (from Debugger investigations)
- **Event cards** (file reads, tool calls, errors)
- Slash commands and their results

Scrolling through the project tab IS reading the project's history. There is no other place to look.

### Summary cards (when you need the 10,000-foot view)

`/status` renders a summary card in the chat:

```
┌─────────────────────────────────────────────┐
│ 📊 Project Status · kalshi-ata              │
│                                              │
│ Tasks: 12 total · 7 done · 3 in progress    │
│        · 2 todo                              │
│                                              │
│ Coder: ● Working on #11 (rate limiter)       │
│ Debugger: ○ Idle                             │
│                                              │
│ Last review: 2h ago · 3 files accepted       │
│ Session cost: $4.32 · 42K tokens             │
│                                              │
│ [/tasks] [/agents] [/cost]                   │
└─────────────────────────────────────────────┘
```

`/tasks` renders a task summary:

```
┌─────────────────────────────────────────────┐
│ 📋 Tasks · kalshi-ata · 12 total            │
│                                              │
│ 🔄 In Progress                               │
│  #11 Coder — Implement rate limiter    2h    │
│  #14 Coder — Add input validation     45m    │
│  #15 Debugger — Investigate memory leak 30m  │
│                                              │
│ ○ Todo                                       │
│  #16 — Write integration tests               │
│  #17 — Update API documentation              │
│                                              │
│ ✅ Done (7)                                   │
│  #3 JWT auth · #4 User model · #5 Routes     │
│  #8 Tests · #10 CORS fix · #12 Logging       │
│  #13 Error handling                          │
│                                              │
│ [/task] [/status]                            │
└─────────────────────────────────────────────┘
```

But these cards live in the chat. They're not separate screens. They're snapshots rendered inline, and the conversation continues below them.

---

## Agent-to-Agent Collaboration

Agents can communicate with each other in the project feed:

```
Coder: I'm getting a segfault in the test suite when running test_auth.py
Coder: /ask Debugger — can you check what's causing the segfault in test_auth.py?
┌─────────────────────────────────────────────┐
│ 🔗 Coder → Debugger · Question              │
│ What's causing the segfault in test_auth.py? │
│ [Investigating...]                           │
└─────────────────────────────────────────────┘
Debugger: /found — Segfault caused by use-after-free in auth_middleware.py:47
┌─────────────────────────────────────────────┐
│ 🐛 Finding · Debugger                        │
│ Segfault in auth_middleware.py:47             │
│ Use-after-free: session object freed before  │
│ response is sent. Fix: defer session cleanup. │
│                                              │
│ [Create Task → Coder]                        │
└─────────────────────────────────────────────┘
Coder: got it, fixing now
```

The PM watches this unfold. No action needed. If the PM wants to intervene, they type. If not, the agents sort it out. The PM is a manager, not a switchboard.

---

## Task Lifecycle — Complete Flow

```
1. PM creates task
   /task Coder — implement JWT auth
   → Task card appears in chat (Todo state)
   → Coder receives task in their agent conversation

2. Coder starts
   /start #3
   → Task card updates to In Progress
   → PM sees status change in project feed

3. Coder works
   → File writes, tool calls appear as event cards
   → Auto-commits after each write (if review mode = off)
   → Or checkpoints accumulate (if review mode = review)

4. Coder completes
   /done #3 — JWT auth implemented, tests passing
   → Task card updates to Review state
   → "Review Changes" button appears on card

5. PM reviews
   → Clicks "Review Changes" on task card
   → Diff cards appear below in chat
   → PM clicks Accept or Reject

6a. Accept
   → Task card updates to Done ✅
   → Changes committed
   → Natural close

6b. Reject
   → PM types reason or clicks Reject with comment
   → Task card reverts to In Progress
   → Coder receives rejection and reason
   → Cycle continues
```

---

## What This Doesn't Do (On Purpose)

- **No Kanban board.** The chat IS the board. Tasks flow top to bottom chronologically. Status is on each card.
- **No Gantt chart.** Tasks are assigned, not scheduled. Agents work as fast as they can.
- **No separate ticket database.** Tasks live in the chat history and a lightweight JSON file for state persistence. Not SQLite, not a server.
- **No email notifications.** Everything is real-time in the chat. If you weren't there, scroll up.
- **No multi-project portfolio view.** Each project is its own tab, its own conversation. Switch tabs to switch projects.

---

## Where Tasks Live (Implementation Notes)

Task state needs to persist across sessions. Lightweight approach:

- `.crabcakes/tasks/<project-name>/tasks.json` — task list with state, assignees, descriptions
- Task cards reference this file for state, but render from chat context for conversation history
- On project open, CrabCakes scans the task file and renders a summary card if there are active tasks

This keeps tasks lightweight and file-based, consistent with the rest of the CrabCakes architecture.

---

## CSS Classes (Preview)

```css
.task-card { /* base task card style */ }
.task-card-header { /* icon + number + agent + status */ }
.task-card-description { /* task text */ }
.task-card-actions { /* button row */ }
.task-badge-todo { /* ○ gray */ }
.task-badge-progress { /* ● blue */ }
.task-badge-review { /* ⏳ amber */ }
.task-badge-done { /* ✅ green */ }
.task-badge-blocked { /* 🚫 red */ }
.task-badge-cancelled { /* ✕ muted */ }
.cmd-bubble { /* slash command rendering */ }
.cmd-unknown { /* unrecognized command hint */ }
```

---

*This document captures the inspiration for the task layer. It will evolve into a full spec with module APIs, data structures, and phase plan.*
