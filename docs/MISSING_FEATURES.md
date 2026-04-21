# CrabCakes — Missing Features Analysis

**Date:** 2026-04-19
**Status:** Tracked — some have spec files, some are untracked

---

## Features Now Spec'd Elsewhere

| # | Feature | Spec File | Build Phase |
|---|---------|-----------|-------------|
| 1 | Task management (task cards, `/` commands) | `docs/task-layer.md` | Phase 3 |
| 3 | Agent-to-agent delegation | `docs/task-layer.md` | Phase 3 |

---

## Remaining Untracked Features

### 2. Agent Memory Across Sessions

**The problem:** Agents wake up fresh every session. If Coder spent 4 hours refactoring the auth system yesterday, today it starts from zero. It can read the code, but it doesn't remember *why* it made certain decisions, what it tried that failed, or what the PM told it to avoid.

**What it could look like:**
- Project-level memory file (e.g., `.crabcakes/agent-memory/<agent-id>.md`)
- Agents read their memory file on startup
- Agents write to it after each session: decisions made, approaches rejected, PM preferences, lessons learned
- Example: "Tried approach X, PM rejected because Y. Using approach Z instead. Do not modify the config parser — PM was explicit about this."
- Similar to OpenClaw's MEMORY.md pattern, but per-agent per-project
- Agents use `/note — <text>` command to write to memory during a session

**Priority:** High — immediate quality-of-life improvement. Small effort.

---

### 4. Test Runner Integration

**What:** Lint-after-write catches syntax errors. But who runs the test suite? After accepting changes, there should be an optional "run tests" step. If tests fail, the accept is blocked or warned.

**How:** ReviewHandler gains an optional post-accept hook. Runs `python -m pytest` or `npm test` (auto-detected). Results rendered as a card. PM can override if needed.

**Priority:** Medium — natural extension of lint-after-write.

---

### 5. Project Onboarding Context

**What:** When you add a new agent to a project mid-stream, how does it know what's already been done?

**How:** Generate a project brief from chat history + task list + git log. New agents receive this as their first message when added to a project. "Here's what this project is, what's been done, and what you need to know."

**Priority:** Low — nice to have. Agents can already read git log.

---

### 6. Agent Performance Tracking

**What:** Which agent produces accepted code vs rejected code? Average cost per completed task?

**How:** Track per-agent stats: tasks completed, acceptance rate, average cost, average time. Display in the Agents tab or via `/cost` summary. Without this, you can't tell if Coder is actually good or just expensive.

**Priority:** Low — useful but not blocking.

---

## Priority Assessment

| # | Feature | Impact | Effort | Priority |
|---|---------|--------|--------|----------|
| 2 | Agent memory | High | Small | High |
| 4 | Test runner integration | Medium | Small | Medium |
| 5 | Project onboarding context | Medium | Small | Low |
| 6 | Agent performance tracking | Medium | Medium | Low |

---

*Feature #2 (Agent Memory) should be spec'd before Build Phase 1 begins, since it affects the agent runtime architecture.*
