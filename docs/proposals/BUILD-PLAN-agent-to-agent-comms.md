# Build Plan: Agent-to-Agent Communication

**Companion to:** `docs/proposals/SPEC-agent-to-agent-comms.md`
**Date:** 2026-05-10
**Author:** Qaster
**Total steps:** 19 across 5 phases
**Estimated new code:** ~430 lines | **Modified code:** ~110 lines across 5 files

---

## Phase 1 — @ Mention Resolution

**Goal:** Make `@Coder` and `@Debugger` resolve from project tab input. Standalone useful — no A2A relay needed for this to work.

**Why first:** Every other phase depends on @mentions resolving for special agents. Today `@Coder` returns "Unknown agent" because `_resolve_mention()` only searches `AgentManager.get_names_ref()` which is gateway-only.

### Step 1.1 — Add `set_special_agents()` to CommandHandler

**File:** `ui/handlers/command_handler.py`

Add to `__init__()`:
```python
self._special_agents: dict[str, str] = {}  # {session_key: display_name}
```

Add new setter method:
```python
def set_special_agents(self, agents: dict[str, str]) -> None:
    """Set special agent registry for @mention resolution.
    Called by window.py after AgentRuntimeHandler is created.
    Dict format: {session_key: display_name} e.g. {"special:coder": "Coder"}
    """
    self._special_agents = agents
```

**Verification:** File compiles. No runtime test yet (not wired).

---

### Step 1.2 — Extend `_resolve_mention()` to search special agents

**File:** `ui/handlers/command_handler.py`

**Location:** `_resolve_mention()` method, after the existing `AgentManager` search block (after the `if self._agent_mgr is not None:` block that checks `names_ref`).

Add a second search block:
```python
# Search special agents (Coder, Debugger, etc.)
for sk, display_name in self._special_agents.items():
    if display_name.lower() == name.lower():
        return sk
if len(name) >= 2:
    matches = [sk for sk, dn in self._special_agents.items()
               if dn.lower().startswith(name.lower())]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = [self._special_agents[sk] for sk in matches]
        return CommandResult(
            handled=True,
            response_text=f"Multiple agents match @{name}: {', '.join(names)}",
        )
```

This mirrors the exact same search pattern as the gateway agent block — exact match first, then prefix match, then ambiguity error.

**Verification:** `python -c "import ast; ast.parse(open('ui/handlers/command_handler.py').read())"`

---

### Step 1.3 — Wire in window.py

**File:** `ui/window.py`

**Location:** In `_build()` method, after `self._command_handler` is created and after `self._agent_runtime_handler` is created (after the special agent registration loop around line 150–152).

Add:
```python
self._command_handler.set_special_agents(self._agent_runtime_handler.get_special_agents())
```

**Verification:** `python -c "import ast; ast.parse(open('ui/window.py').read())"`

---

### Step 1.4 — Test: @ mention resolution

**File:** `tests/test_command_handler.py` (extend existing tests)

Add test cases:
- `@Coder` resolves to `special:coder`
- `@Debugger` resolves to `special:debugger`
- `@Co` resolves to `special:coder` via prefix match
- `@C` does NOT resolve (single char, below prefix minimum of 2)
- `@Unknown` returns error `CommandResult`
- `@Coder` still works when gateway agents are also registered (no collision)
- Mixed: gateway agent `@QTR` resolves via existing path, special agent `@Coder` resolves via new path

**Gate:** All tests pass. `pytest tests/test_command_handler.py -v`

---

## Phase 2 — Shared Prompt

**Goal:** All agents (gateway + special) receive collaboration instructions in their system prompt. This teaches agents the A2A protocol so they know to use `@AgentName` for consultations.

**Why second:** Agents need to know the protocol before CollabManager can use it. The prompt is what makes agents emit `@mentions` naturally in their responses.

### Step 2.1 — Create `prompts/system/collab.md`

**File:** `prompts/system/collab.md` (**new**)

Content (from spec §9):
```markdown
# Agent Collaboration

You are working alongside other agents in a shared project chat. Sometimes you
need expertise from another agent.

## Consulting Another Agent

When you need input from another agent, include @AgentName in your response.
For example: "@Debugger — should I treat an empty string as invalid input?"

Rules:
- Use @AgentName (exact name, case-insensitive) to address another agent
- Ask a specific, focused question
- The PM sees the full exchange in the project feed
- After the consultation, continue your original task with the new information

## Receiving a Consultation

When you receive a message prefixed with [A2A relay from ...]:
- Answer the question directly and thoroughly
- This is a relay from another agent — treat it as a normal work question
- Do NOT say "I'm done" or "stopping" — the system detects when the exchange is complete

## Limitations

- Only one @mention per response
- The consultation runs for a maximum of 15 turns
- After convergence, the thread closes automatically
```

**Verification:** File exists. UTF-8, no BOM. ~35 lines.

---

### Step 2.2 — Load collab.md in prompt_loader.py

**File:** `utils/prompt_loader.py`

**Location:** In `compose_system_prompt()`, after the `# 1. Always load default` block (after `parts.append(default)`) and before `# 2. Project awareness`.

Add:
```python
# 1b. Collaboration protocol (all agents)
collab = load_prompt_template("collab")
if collab:
    parts.append(collab)
```

**Why position 1b:** Collaboration instructions apply to all agents regardless of whether a project is active, what review mode is set, or what role the agent has. It goes right after the default prompt so every agent gets it.

**Verification:** Compile check. Then set `CRABCAKES_PROMPT_DEBUG=1` and verify the composed prompt includes the collaboration section.

---

### Step 2.3 — Test: Prompt composition includes collab

**File:** `tests/test_context.py` (extend existing)

Add test cases:
- `compose_system_prompt(agent_name="Coder", agent_role="coder")` includes "Agent Collaboration"
- `compose_system_prompt(agent_name="Agent", agent_role="")` includes "Agent Collaboration" (gateway agent path)
- `compose_system_prompt()` with no arguments still includes it
- Prompt is composed in correct order: default → collab → project-awareness → role-specific

**Gate:** All tests pass. `pytest tests/test_context.py -v`

---

## Phase 3 — CollabManager Core

**Goal:** Build the A2A thread lifecycle handler. This is the heart of the feature — manages threads, relays messages, runs convergence detection, posts feed cards.

**Why third:** Needs @mention resolution (Phase 1) to identify targets, and needs the prompt (Phase 2) so agents know the protocol. But this phase creates the engine before wiring it into the response pipeline.

### Step 3.1 — Create CollabManager with A2AThread dataclass

**File:** `ui/handlers/collab_manager.py` (**new**)

Create the file with:
- `A2AThread` dataclass: `thread_id`, `project_name`, `initiator_sk`, `target_sk`, `responses: list[dict]`, `turn: int`, `active: bool`
- `CollabManager.__init__()`: takes `GLib`, `feed_handler`, `agent_runtime_handler`, `gw`, `agent_mgr` (all optional except GLib)
- Internal state: `_threads: dict[str, A2AThread]`, `_pending_relays: set[str]`, `_sk_to_thread: dict[str, str]`, `_lock: threading.Lock`
- Setter stubs: `set_agent_runtime_handler()`, `set_gateway_client()`, `set_agent_mgr()`
- Helper stubs: `_build_thread_id()`, `_resolve_agent_name()`, `is_pending_relay()`

**Verification:** File compiles. `python -c "import ast; ast.parse(open('ui/handlers/collab_manager.py').read())"`

---

### Step 3.2 — Implement relay methods

**File:** `ui/handlers/collab_manager.py`

Implement:

**`start_relay(project_name, initiator_sk, target_sk, question_text) -> str | None`:**
1. Build `thread_id = f"a2a:{project_name}:{initiator_sk}:{target_sk}"`
2. Check `_threads[thread_id].active` — if active, return None
3. Create `A2AThread(...)` with turn=0, active=True
4. Add `target_sk` to `_pending_relays`
5. Map `target_sk → thread_id` in `_sk_to_thread`
6. Post intent card to feed handler:
   - `card_type="agent_action"`, `title=f"Consulting @{target_name} on {topic_summary}"`, `body=f"Initiated by @{initiator_name}"`
7. Build relay message: `f"[A2A relay from {initiator_name} in {project_name}] {question_text}"`
8. Send via `_send_relay(target_sk, relay_message)`
9. Return thread_id

**`_send_relay(target_sk, text) -> None`:**
1. Check if `target_sk` is a special agent
2. If yes: `self._agent_runtime_handler.send_to_special_agent(target_sk, text)`
3. If no: check `gw.is_connected()`, then `self._gw.send_message(target_sk, text)`

**`_build_relay_message(from_sk, text, project_name) -> str`:**
- Resolve `from_sk` to display name
- Return `f"[A2A relay from {name} in {project_name}] {text}"`

**Verification:** Compile check.

---

### Step 3.3 — Implement capture_response with convergence

**File:** `ui/handlers/collab_manager.py`

Implement:

**`capture_response(session_key, text) -> None`:**
1. Look up `thread_id` via `_sk_to_thread[session_key]`
2. Get `A2AThread` from `_threads[thread_id]`
3. If thread not active, return
4. Append `{"text": text, "from": session_key}` to `thread.responses`
5. Increment `thread.turn`
6. Call `should_stop(thread.responses, thread.turn)` from `converge.converge`
7. If converged OR turn ≥ 15: call `_close_thread_internal(thread_id)`
8. If not converged and turn < 15:
   - Build relay message from the response
   - Send relay to `thread.initiator_sk` (relay the response back)
   - Add `initiator_sk` to `_pending_relays`
   - Map `initiator_sk → thread_id` in `_sk_to_thread`

**Import:** `from converge.converge import should_stop`

**Verification:** Compile check.

---

### Step 3.4 — Implement close_thread

**File:** `ui/handlers/collab_manager.py`

Implement:

**`_close_thread_internal(thread_id) -> None`:**
1. Set `thread.active = False`
2. Remove `thread.target_sk` and `thread.initiator_sk` from `_pending_relays`
3. Remove their entries from `_sk_to_thread`
4. Post closing card to feed handler:
   - `card_type="agent_action"`, `title="Consultation complete"`, `body=f"Exchange between @{initiator_name} and @{target_name} ({thread.turn} turns)"`

**`clear_project(project_name) -> None`:**
1. Find all threads where `thread.project_name == project_name`
2. Call `_close_thread_internal()` on each
3. Called from `ProjectHandler.on_project_closed()`

**Verification:** Compile check.

---

### Step 3.5 — Test: CollabManager unit tests

**File:** `tests/test_collab_manager.py` (**new**)

Test cases (~150 lines):
- `_build_thread_id()` produces deterministic IDs
- `start_relay()` creates thread, adds to pending_relays, posts intent card, sends relay
- `start_relay()` returns None when thread already active (duplicate prevention)
- `start_relay()` with offline gateway silently skips send for gateway target
- `capture_response()` appends to thread.responses, increments turn
- `capture_response()` triggers close when convergence returns True (mock should_stop)
- `capture_response()` relays response back to initiator when not converged
- `capture_response()` ignores inactive threads
- `capture_response()` ignores unknown session keys
- `close_thread()` sets active=False, cleans up pending_relays and sk_to_thread
- `close_thread()` posts closing card
- `clear_project()` closes all threads for a project
- `is_pending_relay()` returns correct state
- `_send_relay()` routes to special agent handler for special:coder
- `_send_relay()` routes to gateway for non-special session keys
- Edge case: agent @mentions itself (target == initiator) — handled by caller, verify no crash
- Convergence: turn ≤ 2 never triggers close, turn ≥ 15 always triggers close

**Gate:** `pytest tests/test_collab_manager.py -v` — all pass

---

## Phase 4 — Response Routing Hooks

**Goal:** Wire CollabManager into the existing response pipelines so that @mentions in agent responses trigger A2A relays and responses are captured for convergence.

**Why fourth:** Needs CollabManager (Phase 3) to exist before handlers can reference it. This phase connects the engine to the live message flow.

### Step 4.1 — Add A2A hooks to ChatHandler

**File:** `ui/handlers/chat_handler.py`

**Add setter:**
```python
def set_collab_manager(self, manager) -> None:
    """Set CollabManager for A2A relay. Called by window.py."""
    self._collab_manager = manager
```

**In `_handle_final_response()`, after existing rendering logic, before method return:**

```python
# ── A2A response capture (gateway agents) ────────────────────────────────
if self._collab_manager is not None:
    if self._collab_manager.is_pending_relay(session_key):
        self._collab_manager.capture_response(session_key, final_text)

# ── A2A relay detection ──────────────────────────────────────────────────
if self._collab_manager is not None and session_key and final_text:
    project_name = self._agent_to_project.get_project(session_key)
    if project_name:
        relay = CollabManager.detect_a2a_mention(
            final_text, session_key, project_name, self._command_handler
        )
        if relay is not None:
            self._collab_manager.start_relay(
                project_name=project_name,
                initiator_sk=session_key,
                target_sk=relay["target_sk"],
                question_text=relay["question"],
            )
```

**Important order:** Response capture runs BEFORE relay detection. This way an agent's response can be captured as part of an existing thread AND trigger a new relay in the same call.

**Verification:** Compile check.

---

### Step 4.2 — Add A2A hooks to AgentRuntimeHandler

**File:** `ui/handlers/agent_runtime_handler.py`

**Add setter:**
```python
def set_collab_manager(self, manager) -> None:
    """Set CollabManager for A2A relay. Called by window.py."""
    self._collab_manager = manager
```

**In `_do_response_complete()`, after existing rendering (after the `if not was_streaming` block), before `on_agent_end_cb` fire:**

```python
# ── A2A response capture (special agents) ────────────────────────────────
if self._collab_manager is not None:
    if self._collab_manager.is_pending_relay(session_key):
        self._collab_manager.capture_response(session_key, text)

# ── A2A relay from special agent ─────────────────────────────────────────
if self._collab_manager is not None and self._active_project:
    project_name = self._active_project[0]
    relay = CollabManager.detect_a2a_mention(
        text, session_key, project_name, self._command_handler
    )
    if relay is not None:
        self._collab_manager.start_relay(
            project_name=project_name,
            initiator_sk=session_key,
            target_sk=relay["target_sk"],
            question_text=relay["question"],
        )
```

**Verification:** Compile check.

---

### Step 4.3 — Extract shared detect_a2a_mention

**File:** `ui/handlers/collab_manager.py`

Add as a static method on CollabManager (so both handlers can call it without importing each other):

```python
@staticmethod
def detect_a2a_mention(text: str, source_sk: str, project_name: str,
                       command_handler) -> dict | None:
    """
    Detect @AgentName in agent response text.
    Returns {"target_sk": str, "question": str} or None.

    Uses command_handler.resolve_inline_mention() to resolve the name
    across both gateway and special agents.
    """
    import re
    mention_match = re.search(r'@([A-Za-z][A-Za-z0-9_]+)', text)
    if not mention_match:
        return None

    agent_name = mention_match.group(1)
    from models.command import MentionResolution
    resolution = command_handler.resolve_inline_mention(f"@{agent_name}", source_sk)

    if (hasattr(resolution, 'target_session_key')
            and resolution.target_session_key
            and resolution.target_session_key != source_sk):
        return {
            "target_sk": resolution.target_session_key,
            "question": text,
        }
    return None
```

**Verification:** Compile check. Unit test with mock command_handler.

---

### Step 4.4 — Wire in window.py

**File:** `ui/window.py`

**In `_build()` method, after AgentRuntimeHandler and FeedHandler are created:**

```python
# ── CollabManager (A2A relay) ────────────────────────────────────────────
from ui.handlers.collab_manager import CollabManager
self._collab_manager = CollabManager(
    GLib=GLib,
    feed_handler=self._feed_handler,
    agent_runtime_handler=self._agent_runtime_handler,
    gw=self._gw,
)
self._collab_manager.set_agent_mgr(
    self._gateway_handler.agent_mgr if self._gateway_handler else None
)

# Wire to response handlers
self._chat_handler.set_collab_manager(self._collab_manager)
self._agent_runtime_handler.set_collab_manager(self._collab_manager)
```

**In `_on_ws_connect()`, after gateway connects:**
```python
self._collab_manager.set_gateway_client(self._gw)
self._collab_manager.set_agent_mgr(self._gateway_handler.agent_mgr)
```

**In `_on_disconnect_gateway()`:**
```python
self._collab_manager.set_gateway_client(None)
```

**Note:** Step 1.3 (`set_special_agents`) wiring goes here too if not already done.

**Verification:** App starts without errors. `python crabcakes.py` opens window.

---

### Step 4.5 — AgentRuntimeHandler needs command_handler reference

**File:** `ui/handlers/agent_runtime_handler.py`

The `detect_a2a_mention()` call needs a `command_handler` to resolve @mentions. Add a setter:

```python
def set_command_handler(self, handler) -> None:
    """Set CommandHandler for @mention resolution in A2A relay."""
    self._command_handler = handler
```

**Wire in `window.py`:**
```python
self._agent_runtime_handler.set_command_handler(self._command_handler)
```

**Verification:** Compile check.

---

### Step 4.6 — Test: Integration

**File:** `tests/test_collab_manager.py` (extend)

Integration test cases:
- Mock `AgentRuntimeHandler` with special agents, mock `GatewayClient`
- Simulate: Coder response contains "@Debugger should empty string be invalid?"
  - Verify `start_relay()` called with `special:debugger` as target
  - Verify relay message sent via `send_to_special_agent()`
  - Verify intent card posted to feed
- Simulate: Debugger responds
  - Verify `capture_response()` called
  - Verify response appended to thread
  - If converged: verify `close_thread()` called, closing card posted
  - If not converged: verify relay sent back to Coder
- Simulate: Gateway agent response contains "@Coder"
  - Verify `start_relay()` called with `special:coder` as target
  - Verify relay sent via `send_to_special_agent()` (not gateway)

**Manual integration test:**
1. Open CrabCakes, open a project with Coder and QTR as members
2. Send: `@Coder implement auth`
3. Coder responds with `@Debugger should empty string be invalid?`
4. Verify intent card appears in project feed
5. Debugger responds
6. Verify exchange appears in project tab inline
7. Wait for convergence or 15-turn limit
8. Verify closing card appears in project feed

**Gate:** All unit tests pass. Manual test confirms end-to-end flow.

---

## Phase 5 — Documentation

**Goal:** Update architecture docs so future contributors understand the A2A system.

**Why last:** Code changes must be verified before documenting them. Documentation should reflect what actually exists.

### Step 5.1 — Update ARCHITECTURE.md

**File:** `docs/ARCHITECTURE.md`

Updates required:

**§2 Directory Structure** — Add to `ui/handlers/`:
```
│   ├── collab_manager.py    # CollabManager — A2A consultation thread lifecycle (Phase A2A)
```

Add to `prompts/system/` section if it exists:
```
│   ├── collab.md             # Shared collaboration protocol prompt (Phase A2A)
```

**§3 Module Responsibilities** — Add new section:

```
### 3.XX `ui/handlers/collab_manager.py` — A2A Consultation Manager (Phase A2A)

**Responsibility:** Manages ephemeral agent-to-agent consultation threads within
a project. Detects @mentions in agent responses, relays questions to target agents,
captures responses, runs convergence detection, and posts feed cards.

**Owns:** A2AThread dataclass, thread lifecycle, relay routing, convergence integration.

**Does NOT own:** GTK widgets, LLM calls, conversation state.

**Public API:**
```python
class CollabManager:
    def __init__(GLib, feed_handler, agent_runtime_handler=None, gw=None, agent_mgr=None)
    def set_agent_runtime_handler(handler) -> None
    def set_gateway_client(gw) -> None
    def set_agent_mgr(agent_mgr) -> None
    def start_relay(project_name, initiator_sk, target_sk, question_text) -> str | None
    def capture_response(session_key, text) -> None
    def close_thread(thread_id) -> None
    def clear_project(project_name) -> None
    def is_pending_relay(session_key) -> bool

    @staticmethod
    def detect_a2a_mention(text, source_sk, project_name, command_handler) -> dict | None
```

**Thread safety:** State protected by `_lock`. GTK dispatch via `GLib.idle_add()`.
```

**§4 Data Flow** — Add A2A data flow subsection:

```
### 4.X A2A Consultation Flow

1. Agent response contains @TargetAgent → ChatHandler/AgentRuntimeHandler detects via detect_a2a_mention()
2. CollabManager.start_relay() → creates A2AThread, posts intent card, sends relay message
3. Target agent responds → ChatHandler/AgentRuntimeHandler checks is_pending_relay()
4. CollabManager.capture_response() → appends to thread, checks convergence
5. If converged → close_thread() → posts closing card
6. If not converged → relay response back to initiator → repeat from step 3
```

**§11 File Inventory** — Add entries with line counts (fill in actual counts after implementation).

**§12 Test Inventory** — Add `tests/test_collab_manager.py` entry.

---

### Step 5.2 — Update PROJECT_STATUS.md

**File:** `docs/PROJECT_STATUS.md`

Add A2A Communication section:
- Phase A2A: Agent-to-Agent Consultation
- Status: Implemented
- Files: collab_manager.py, collab.md, modified handlers
- Depends on: Phase 7 (collab commands), converge/ module

---

## Summary

| Phase | Steps | New Files | Modified Files | Gate |
|-------|-------|-----------|----------------|------|
| 1. @ Mention Resolution | 4 | 0 | command_handler.py, window.py | Tests pass |
| 2. Shared Prompt | 3 | collab.md | prompt_loader.py | Prompt includes collab |
| 3. CollabManager Core | 5 | collab_manager.py, test_collab_manager.py | (none) | Unit tests pass |
| 4. Response Routing | 6 | 0 | chat_handler.py, agent_runtime_handler.py, window.py | Integration test |
| 5. Documentation | 2 | 0 | ARCHITECTURE.md, PROJECT_STATUS.md | Doc review |
| **Total** | **20** | **3** | **7** | |

**Dependencies:** Phase 1 → Phase 4 (mention resolution needed for routing). Phase 2 → Phase 4 (prompt needed before agents use protocol). Phase 3 → Phase 4 (CollabManager must exist before wiring). Phase 5 is last. Phases 1 and 2 can run in parallel. Phase 3 can start while Phase 2 finishes.
