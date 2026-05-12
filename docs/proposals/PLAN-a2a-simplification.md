# A2A Simplification Plan — Remove Automatic Relay, Implement Command-Based Consultation

**Date:** 2026-05-11
**Author:** Qaster
**Status:** Pending approval
**Context:** A2A auto-detection of @mentions causes infinite relay loops with gateway agents

---

## 0. Problem Statement

The current A2A system auto-detects @mentions in every agent response and automatically opens relay threads. This is fundamentally flawed because gateway agent messages (from Telegram, CrabCakes, etc.) all flow through the same `_handle_final_response()` path, and any casual mention of an agent name triggers a relay. The system cannot distinguish intentional consultation from casual conversation.

## 1. Design Decision

Replace automatic @mention detection with an explicit command-based trigger. Instead of agents accidentally triggering relays by mentioning a name, they deliberately use the existing backtick command system (`ask @AgentName question`). This uses the same command infrastructure that already exists for human users.

---

## 2. Implementation Plan

### Phase 1 — Remove Dead A2A Code (PRIORITY: do first, before any new code)

**Files to delete entirely:**
- `ui/handlers/collab_manager.py` (409 lines) — the entire automatic relay engine
- `tests/test_collab_manager.py` (499 lines) — tests for the removed relay engine

**Code to remove from `chat_handler.py`:**
- Import of `CollabManager` (line 18)
- `set_collab_manager()` setter (lines 78-80)
- A2A response capture block in `_handle_final_response()` (lines 558-561)
- A2A relay detection block in `_handle_final_response()` (lines 565-581)
- `_collab_manager` instance variable init (line 66)

**Code to remove from `agent_runtime_handler.py`:**
- `set_collab_manager()` setter (lines 93-95)
- `set_command_handler()` setter (lines 97-99) — only used for A2A mention resolution
- A2A response capture block in `_do_response_complete()` (lines 646-648)
- A2A relay detection block in `_do_response_complete()` (lines 651-665)
- `_collab_manager` instance variable init (line 83)

**Code to remove from `window.py`:**
- Import of `CollabManager` (line 142)
- CollabManager construction block (lines 160-172)
- `set_feed_handler` wiring for CollabManager (lines 270-271)
- CollabManager wiring in `_on_ws_connect()` (lines 618-619)
- `_command_handler.set_special_agents()` call (only used for A2A resolution, line 367)
- `_agent_runtime_handler.set_command_handler()` call (only used for A2A, line 369)

**Code to keep:**
- `ui/handlers/collab_handler.py` — `ask`, `delegate`, `stop`, `tell` commands stay
- `prompts/system/collab.md` — will be rewritten in Phase 2, but file stays
- All transport routing (gateway + special agent sends)
- Project fan-out (unchanged)
- Feed cards (from CrabWatch and other sources)

**Code to remove from `docs/ARCHITECTURE.md`:**
- §3.21n (CollabManager module section)
- §4.11 (A2A data flow section)
- collab_manager.py entries in §2 directory structure and §12 file inventory
- test_collab_manager.py entry in §12

**Verify:** After Phase 1, CrabCakes compiles, all remaining tests pass, no dead imports, no dead methods.

---

### Phase 2 — Rewrite `collab.md` Prompt for Command-Based A2A

Replace the current prompt with instructions for the `ask` command:
- To consult another agent, use `` `ask @AgentName your question` ``
- Never use @mentions in normal text for consultation
- The `ask` command is the only way to start a consultation
- Receiving a relay: answer directly, don't echo mentions

---

### Phase 3 — Enhance `ask` Command for Agent-Initiated Consultation

The existing `ask` command already forwards a message to a target agent. It works for human users typing in the project tab. For agents to use it, the prompt in Phase 2 instructs them to include the backtick command syntax in their response.

Flow:
1. User types `` `ask @Debugger is this edge case valid?` `` in project tab
2. CommandHandler parses it, routes to CollabHandler.cmd_ask()
3. CollabHandler returns CommandResult with forward_to and forward_text
4. ChatHandler sends the question to the target agent
5. Target responds, response displays in project tab normally
6. No automatic relay loop — one-shot question/answer
7. If follow-up needed, human or agent uses `ask` again

This is deliberately simpler than the old relay system. No threads, no convergence, no capture loops. One question, one answer, done.

---

### Phase 4 — Update ARCHITECTURE.md

Document the simplified A2A system:
- Remove all CollabManager references
- Document the `ask`/`delegate`/`stop`/`tell` commands as the A2A mechanism
- Update §4 data flow to show command-based consultation instead of automatic relay

---

## 3. What This Plan Preserves
- All transport routing (gateway + special agent sends still work)
- The `ask`, `delegate`, `stop`, `tell` commands in CollabHandler
- Project fan-out (unchanged)
- Feed cards (from CrabWatch and other sources)
- The `collab.md` prompt (rewritten, not deleted)

## 4. What This Plan Removes
- The entire automatic @mention detection system
- The relay thread engine (CollabManager)
- All sanitization code (thinking tokens, mention stripping)
- All loop guards (`[A2A relay from` checks)
- The capture_response/start_relay/is_pending_relay flow
- ~900 lines of code that caused nothing but problems

## 5. Files Changed Summary

| File | Action | Notes |
|------|--------|-------|
| `ui/handlers/collab_manager.py` | DELETE | Entire file |
| `tests/test_collab_manager.py` | DELETE | Entire file |
| `ui/handlers/chat_handler.py` | EDIT | Remove ~20 lines of A2A hooks |
| `ui/handlers/agent_runtime_handler.py` | EDIT | Remove ~20 lines of A2A hooks |
| `ui/window.py` | EDIT | Remove CollabManager wiring |
| `prompts/system/collab.md` | REWRITE | Command-based instructions |
| `docs/ARCHITECTURE.md` | EDIT | Remove CollabManager sections |
