# CrabCakes Docs — Index

**Last organized:** 2026-05-09

Every doc has a status banner at the top (after the title). Check it before reading — many docs are historical (completed/superseded/obsolete).

---

## Top-Level (Active Docs)

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | Authoritative codebase reference. Read before writing code. |
| `PRODUCT_VISION.md` | What CrabCakes is and where it's going. |
| `BUILD_ORDER.md` | Active build roadmap for Coder enhancements. Phases 1-4, 6-7 done. |
| `CONVENTIONS.md` | Project conventions (file formats, naming, etc.) |
| `PROJECT_STATUS.md` | Phase completion tracker. **OUTDATED** — needs refresh. |

## `bugs/` — Open & Fixed Bug Reports

All bugs verified against code as of 2026-05-09. Status banners show which are fixed and which are still open.

| File | Status |
|------|--------|
| `BUG_REPORT-identity-override.md` | ⚠️ STILL OPEN — Gateway agents get identity injection as user message content |
| `BUG_INVESTIGATION-members-not-persisting-on-reopen.md` | ⚠️ PARTIALLY FIXED — Session key matching improved, but team.json still saves ephemeral keys |
| `BUG_AGENT_CARD_SNAPSHOT.md` | ✅ FIXED — tab_key now used for chat box lookup |
| `BUGS-special-agent-solo-dm.md` | ✅ FIXED — Solo DM routes through AgentRuntimeHandler |

## `completed/` — Implemented Specs & Proposals

These were pre-build specs or proposals that have been fully implemented. Kept for design context and historical reference.

| File | What Was Built |
|------|---------------|
| `agent-runtime.md` | Agent runtime (tool loop, 3 LLM providers, streaming) |
| `AGENT_RUNTIME_FEED_INTEGRATION.md` | Agent runtime → feed card wiring |
| `agent-collaboration.md` | CollabHandler (ask, delegate, stop, tell) |
| `CODER_PROMPT_FRAMEWORK_ENHANCEMENT_PROPOSAL.md` | Enhanced coder prompts + tool descriptions |
| `command-system.md` | Backtick command parser and routing |
| `CONVERSATION_SNAPSHOT_PROPOSAL.md` | Feed card conversation snapshots |
| `ENFORCEMENT_LAYER_SPEC.md` | Post-write verification (syntax, tests, lint) |
| `PHASE5_SPEC.md` | CrabWatch filesystem watcher |
| `PROJECT_FEED.md` | Project Feed spec (superseded by correction doc) |
| `PROJECT_FEED_CORRECTION.md` | Corrected Project Feed implementation |
| `PROPOSAL-agent-display-name-fix.md` | Agent name fallback fix |
| `PROPOSAL-extract-command-handlers.md` | Command handler extraction from window.py |
| `PROPOSAL-new-project-creation.md` | Project creation flow (partially implemented) |
| `PROPOSAL-project-awareness.md` | Project awareness system |
| `PROPOSAL-system-prompt-library.md` | System prompt template system |
| `PROPOSAL-workflow-prompts.md` | Workflow phase prompts |
| `review-layer.md` | Git review layer (checkpoint, diff, accept/reject) |
| `task-layer.md` | Task management via chat commands |

## `proposals/` — Not Yet Implemented

Still active proposals awaiting build decisions.

| File | Status |
|------|--------|
| `PROPOSAL-agent-to-agent-comms.md` | Not started — no inter-agent messaging infrastructure |
| `PROPOSAL-feed-card-wiring.md` | Partially done — task cards wired, git operation cards not yet |
| `PROPOSAL-implementation-engine.md` | Not started — no engine module found |
| `PROPOSAL-project-onboarding.md` | Partially done — template exists but applies to all agents (see identity override bug) |

## `reference/` — Living Reference Docs

Accurate descriptions of how things work. Not specs — read these to understand existing systems.

| File | Covers |
|------|--------|
| `CODEBASE_DEEP_DIVE.md` | Full architecture walkthrough |
| `FORMATTING_EXAMPLES.md` | Chat rendering pipeline and supported formatting |
| `TEST_PLAN.md` | Command system test plan |

## `research/` — Research & Investigation Reports

Historical research that informed design decisions. Not implementation docs.

| File | Status |
|------|--------|
| `ADVERSARIAL_DEBUG_REPORT_QTR_PROMPT_IMPL.md` | Mostly fixed — QTR's prompt refactor audit |
| `CODING_AGENT_ENFORCEMENT_RESEARCH.md` | Reference — informed enforcement layer design |
| `convergence-detection.md` | **OBSOLETE** — built but dead code, nothing imports it |
| `feedbar-state-machine.md` | Reference — FeedBar state machine documentation |
| `MINIMAX_TOOL_CALLING_INVESTIGATION.md` | **FIXED** — MiniMax tool call assembly bug resolved |
| `stoplight-summary.md` | **BUILT BUT DEAD CODE** — 99.1% accurate convergence detection, unused |
