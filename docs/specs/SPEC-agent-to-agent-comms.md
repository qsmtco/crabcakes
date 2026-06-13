---
status: PARTIAL
---
# Implementation Specification: Agent-to-Agent Communication

**Date:** 2026-05-10
**Author:** Qaster
**Status:** Ready for implementation
**Precedes:** PROPOSAL-agent-to-agent-comms.md (Qrusher, 2026-05-08)
**Architecture compliance:** Full — all changes respect ARCHITECTURE.md §2–§13

---

## 0. Problem Statement

Three unsolved problems block the original proposal from being buildable:

1. **Thread identity across transport layers.** Gateway agents route messages through `gw.send_message()`. Special agents route through `AgentRuntimeHandler.send_to_special_agent()`. These are two completely separate message paths. When Coder (special agent) needs to ask QTR (gateway agent) a question, the thread must cross both transport layers while maintaining a coherent identity that maps back to the project tab.

2. **Response routing.** When Agent A sends `@AgentB a question`, the response from Agent B must route back into the same conversation thread in the project tab — regardless of which transport layer Agent B uses. Today, each agent's responses flow through exactly one callback chain. Agent-to-agent communication requires responses to be injected into a conversation the responding agent doesn't know about.

3. **`@` mention resolution for special agents.** `_resolve_mention()` in `command_handler.py` only searches `AgentManager.get_names_ref()`, which contains gateway agents only. Special agents (`special:coder`, `special:debugger`) are tracked in `AgentRuntimeHandler.get_special_agents()`. Typing `@Coder` in a project tab today returns "Unknown agent: @Coder".

This specification solves all three problems within the existing architecture.

---

## 1. Design Decisions

### 1.1 A2A threads are project-scoped, not persistent sessions

Agent-to-agent conversations are **ephemeral relays** — they exist for the duration of a consultation and are destroyed when convergence closes the thread. They are NOT new persistent sessions or conversations in `AgentRuntime`.

**Rationale:** Special agents already have a `session_key` tied to their tab (`special:coder`). Creating additional sessions would require new conversation management, duplicate `AgentRuntime` state, and new tab routing. Relay mode reuses the existing conversation by injecting the relayed message as a user message with a prefix identifying the source.

### 1.2 The project tab is the thread display surface

All A2A exchanges appear in the project tab — same as today's fan-out messages. No new tabs, no new chat boxes. The PM sees the exchange inline in the project feed.

**Rationale:** ARCHITECTURE.md §4.4 already routes project member responses to `project:<name>` tab. A2A messages piggyback on this routing. No new `create_chat_tab()` calls needed.

### 1.3 Relay through ChatHandler, not direct agent-to-agent

Agents never send messages directly to each other. The flow is:

```
Agent A responds with @AgentB question
  → ChatHandler detects @mention in the response
  → ChatHandler relays the question to Agent B
  → Agent B's response arrives via existing callback chain
  → ChatHandler captures it and displays in project tab
  → Convergence detector monitors the exchange
```

**Rationale:** ChatHandler already owns all message routing (§3.14). It knows about both transport layers. Direct agent-to-agent messaging would bypass ChatHandler's routing logic and violate the handler pattern (§8.6).

### 1.4 Convergence via existing `converge/` module

The `converge/converge.py` module exists, is tested, and provides `should_stop(responses, turn) → bool`. It uses a pre-trained Random Forest on 10 conversational signals. The A2A handler calls this after each response in the A2A exchange.

---

## 2. Architecture Overview

### 2.1 New components

| Component | File | Responsibility |
|-----------|------|----------------|
| `CollabManager` | `ui/handlers/collab_manager.py` | Owns A2A thread lifecycle: relay, response capture, convergence, cleanup |
| `collab.md` | `prompts/system/collab.md` | Shared prompt teaching agents the A2A protocol |

### 2.2 Modified components

| Component | File | Change |
|-----------|------|--------|
| `CommandHandler` | `ui/handlers/command_handler.py` | Extend `_resolve_mention()` to search special agents |
| `ChatHandler` | `ui/handlers/chat_handler.py` | Detect `@` mentions in agent responses, relay via CollabManager |
| `AgentRuntimeHandler` | `ui/handlers/agent_runtime_handler.py` | Intercept special agent responses for A2A relay |
| `prompt_loader.py` | `utils/prompt_loader.py` | Compose `collab.md` into all agent system prompts |
| `window.py` | `ui/window.py` | Wire CollabManager to ChatHandler and AgentRuntimeHandler |

### 2.3 Component interaction diagram

```
Project tab: user says "@Coder implement auth"
         │
         ▼
  ┌─────────────┐    send_to_special_agent()
  │ ChatHandler  │──────────────────────────▶ AgentRuntimeHandler
  └──────┬──────┘                                │
         │                        _on_response_complete()
         │ @AgentB detected in response           │
         ▼                                        ▼
  ┌──────────────┐   relay_to(target_sk, text)   ┌─────────────────┐
  │ CollabManager │◀──────────────────────────────│ AgentRuntime    │
  │              │                               │ Handler         │
  │ tracks thread│   relay_to(target_sk, text)   │ (captures resp) │
  │ responses[]  │──────────────────────────▶    └─────────────────┘
  │ convergence  │          gw.send_message()
  │              │              OR
  │              │   send_to_special_agent()
  └──────┬───────┘
         │
         │ response arrives (gateway event OR special agent callback)
         │ ChatHandler/AgentRuntimeHandler routes to CollabManager
         ▼
  Project tab: shows full exchange inline
```

---

## 3. Thread Identity

### 3.1 Thread ID format

```
a2a:<project_name>:<initiator_sk>:<target_sk>
```

Examples:
- `a2a:manopea:special:coder:agent:qtr:telegram:direct:7478874934`
- `a2a:manopea:special:coder:special:debugger`
- `a2a:manopea:agent:qtr:main:special:coder`

The thread ID is **deterministic** — given two session keys, there is exactly one thread ID (order: initiator first, target second). CollabManager uses this as the dict key for thread state.

### 3.2 Thread state

```python
@dataclass
class A2AThread:
    thread_id: str
    project_name: str
    initiator_sk: str          # session key of the agent that started the consultation
    target_sk: str             # session key of the consulted agent
    responses: list[dict]      # [{"text": ..., "from": session_key}] — for convergence
    turn: int                  # current turn count (starts at 1 after relay)
    active: bool               # False after convergence closes
```

### 3.3 Thread lifecycle

```
1. Agent A's response contains "@AgentB question"
2. ChatHandler detects @mention, calls CollabManager.start_relay()
   → creates A2AThread, sends relay message to Agent B
3. Agent B responds
   → ChatHandler/AgentRuntimeHandler routes response to CollabManager.capture_response()
   → appends to thread.responses, increments turn
   → if turn >= 3: calls should_stop(responses, turn)
4. If should_stop() returns True:
   → CollabManager.close_thread()
   → posts "Consultation complete" card to project feed
   → sets thread.active = False
5. If should_stop() returns False and turn < 15:
   → relay Agent B's response back to Agent A (as context for next turn)
   → wait for Agent A's next response (may contain another @AgentB)
   → repeat from step 3
```

---

## 4. Response Routing

### 4.1 The routing problem

There are two response callback chains:

**Gateway agents** → `GatewayClient.on_event` → `window._on_ws_event` → `ChatHandler.on_chat_event` → `_handle_final_response`

**Special agents** → `AgentRuntime.on_response_complete` → `AgentRuntimeHandler._on_response_complete` → `_do_response_complete`

When a relay message is sent to an agent, its response must be **intercepted** and routed to the CollabManager instead of (or in addition to) normal display.

### 4.2 Solution: response capture via pending-relay registry

CollabManager maintains a **pending relay set**: `_pending_relays: set[str]` containing session keys that are currently being consulted in an A2A thread.

When a response arrives for a session key that's in the pending relay set:

1. The response is **displayed normally** in the project tab (the PM sees it)
2. The response text is **also captured** by CollabManager for convergence checking
3. If the conversation is not converged, the response is **relayed back** to the initiating agent as a contextual message

### 4.3 Gateway agent response capture

In `ChatHandler._handle_final_response()`, after the normal rendering:

```python
# After existing rendering logic...
if self._collab_manager is not None:
    self._collab_manager.capture_response(session_key, final_text)
```

### 4.4 Special agent response capture

In `AgentRuntimeHandler._do_response_complete()`, after existing rendering:

```python
# After existing rendering logic...
if self._collab_manager is not None:
    self._collab_manager.capture_response(session_key, text)
```

### 4.5 Relay message format

When CollabManager relays a message to an agent, it prefixes the text so the agent understands the context:

```
[A2A relay from Coder in manopea] @Debugger — should I treat empty string as invalid input?
```

The `[A2A relay from <Agent> in <Project>]` prefix tells the responding agent:
- This is an inter-agent consultation, not a user message
- Which agent asked the question
- Which project context this relates to

The prefix is added by CollabManager when constructing the relay message. It is NOT part of the agent's conversation history — it's injected as the user message text for that turn.

### 4.6 Relay message routing

CollabManager determines the transport layer from the target session key:

```python
def _send_relay(self, target_sk: str, text: str) -> None:
    """Send a relay message to the target agent via the correct transport."""
    is_special = (self._agent_runtime_handler is not None
                  and target_sk in self._agent_runtime_handler.get_special_agents())
    if is_special:
        self._agent_runtime_handler.send_to_special_agent(target_sk, text)
    else:
        if self._gw is not None and self._gw.is_connected():
            self._gw.send_message(target_sk, text)
```

This mirrors the existing transport split in `ChatHandler.on_send()` (lines 162–179, 383–415).

---

## 5. @ Mention Resolution for Special Agents

### 5.1 Current state

`CommandHandler._resolve_mention()` (line 377) only searches `AgentManager.get_names_ref()`:

```python
if self._agent_mgr is not None:
    names_ref = self._agent_mgr.get_names_ref()  # gateway agents only
    for sk, n in names_ref.items():
        if n.lower() == name.lower():
            return sk
```

Special agents are tracked in `AgentRuntimeHandler.get_special_agents()` which returns `{session_key: display_name}`. They are invisible to `_resolve_mention()`.

### 5.2 Fix

Add a new setter on `CommandHandler` to receive the special agents dict, then search both in `_resolve_mention()`:

**In `command_handler.py`:**

```python
class CommandHandler:
    def __init__(self, ...):
        ...
        self._special_agents: dict[str, str] = {}  # {session_key: display_name}

    def set_special_agents(self, agents: dict[str, str]) -> None:
        """Set special agent registry for @mention resolution.
        Called by window.py after AgentRuntimeHandler is created."""
        self._special_agents = agents

    def _resolve_mention(self, mention: str, session_key: str = "") -> str | list[str] | CommandResult:
        name = mention[1:]  # strip @
        ...
        # After existing gateway agent search, add:
        if self._agent_mgr is not None:
            names_ref = self._agent_mgr.get_names_ref()
            for sk, n in names_ref.items():
                if n.lower() == name.lower():
                    return sk
            if len(name) >= 2:
                matches = [sk for sk, n in names_ref.items() if n.lower().startswith(name.lower())]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    ...  # existing ambiguity handling

        # NEW: Search special agents
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

        return CommandResult(handled=True, response_text=f"Unknown agent: @{name}")
```

**In `window.py`:**

After creating `CommandHandler` and `AgentRuntimeHandler`:

```python
self._command_handler.set_special_agents(self._agent_runtime_handler.get_special_agents())
```

### 5.3 What this enables

- `@Coder` → resolves to `special:coder`
- `@Debugger` → resolves to `special:debugger`
- `@QTR` → resolves to `agent:qtr:telegram:direct:...` (existing gateway resolution)
- `@Co` → resolves to `special:coder` (prefix match, if unambiguous)
- `@all` → broadcasts to all project members including special agents (existing behavior)

---

## 6. CollabManager — Full Specification

### 6.1 File: `ui/handlers/collab_manager.py`

New handler. Follows handler pattern (§8.6). No imports from other handlers — receives dependencies via constructor/setters.

```python
class CollabManager:
    """
    Manages agent-to-agent consultation threads within a project.

    Thread lifecycle:
      1. start_relay() — create thread, send relay message to target agent
      2. capture_response() — append response, check convergence
      3. close_thread() — convergence detected, post closing card

    Thread safety: All GTK via GLib.idle_add(). State protected by _lock.
    """

    def __init__(
        self,
        *,
        GLib,                              # gi.repository.GLib
        feed_handler,                      # FeedHandler — for posting cards
        agent_runtime_handler=None,        # AgentRuntimeHandler — for special agent routing
        gw=None,                           # GatewayClient — for gateway agent routing
    ):
        self._GLib = GLib
        self._feed_handler = feed_handler
        self._agent_runtime_handler = agent_runtime_handler
        self._gw = gw

        self._threads: dict[str, A2AThread] = {}    # thread_id → A2AThread
        self._pending_relays: set[str] = set()       # session_keys with pending A2A responses
        self._sk_to_thread: dict[str, str] = {}      # session_key → thread_id (reverse lookup)
        self._lock = threading.Lock()

    # ── Setters ─────────────────────────────────────────────────────────────

    def set_agent_runtime_handler(self, handler) -> None: ...
    def set_gateway_client(self, gw) -> None: ...

    # ── Thread lifecycle ────────────────────────────────────────────────────

    def start_relay(
        self,
        project_name: str,
        initiator_sk: str,
        target_sk: str,
        question_text: str,
    ) -> str | None:
        """
        Start an A2A consultation thread.

        1. Build thread_id from project_name + initiator + target
        2. Create A2AThread
        3. Add target_sk to _pending_relays
        4. Map target_sk → thread_id in _sk_to_thread
        5. Post intent card to project feed
        6. Send relay message to target agent

        Returns thread_id, or None if a thread already exists for this pair.
        """

    def capture_response(self, session_key: str, text: str) -> None:
        """
        Called from ChatHandler / AgentRuntimeHandler when a response arrives
        for a session key that is in _pending_relays.

        1. Look up thread_id via _sk_to_thread
        2. Append {"text": text, "from": session_key} to thread.responses
        3. Increment thread.turn
        4. If turn >= 3: check should_stop(responses, turn)
        5. If converged or turn >= 15: close_thread()
        6. If not converged: relay response back to initiator agent
        """

    def close_thread(self, thread_id: str) -> None:
        """
        Close an A2A thread.

        1. Set thread.active = False
        2. Remove session keys from _pending_relays
        3. Remove from _sk_to_thread
        4. Post closing card to project feed
        """

    def is_pending_relay(self, session_key: str) -> bool:
        """Check if a session key has a pending A2A relay. Used by ChatHandler
        and AgentRuntimeHandler to decide whether to route response here."""

    # ── Internal ────────────────────────────────────────────────────────────

    def _send_relay(self, target_sk: str, text: str) -> None:
        """Route relay message through correct transport (gateway or special agent)."""

    def _build_relay_message(self, from_sk: str, question_text: str, project_name: str) -> str:
        """Build relay message with [A2A relay from <Agent> in <Project>] prefix."""

    def _resolve_agent_name(self, session_key: str) -> str:
        """Resolve session_key to display name for relay prefix and cards."""
```

### 6.2 Thread ID construction

```python
def _build_thread_id(self, project_name: str, initiator_sk: str, target_sk: str) -> str:
    return f"a2a:{project_name}:{initiator_sk}:{target_sk}"
```

### 6.3 Intent card format

When `start_relay()` is called, an intent card is posted to the project feed:

```python
FeedCardData(
    card_type="agent_action",
    source="system",
    title=f"Consulting @{target_name} on {topic_summary}",
    body=f"Initiated by @{initiator_name}",
    author="System",
    timestamp=datetime.now(timezone.utc),
    project_name=project_name,
)
```

`topic_summary` is the first 80 characters of `question_text`.

### 6.4 Closing card format

When `close_thread()` is called:

```python
FeedCardData(
    card_type="agent_action",
    source="system",
    title="Consultation complete",
    body=f"Exchange between @{initiator_name} and @{target_name} ({turn} turns)",
    author="System",
    timestamp=datetime.now(timezone.utc),
    project_name=project_name,
)
```

### 6.5 Agent name resolution

CollabManager needs to resolve session keys to display names. It checks both sources:

```python
def _resolve_agent_name(self, session_key: str) -> str:
    # Check special agents first
    if self._agent_runtime_handler is not None:
        special = self._agent_runtime_handler.get_special_agents()
        if session_key in special:
            return special[session_key]
    # Check gateway agents
    # (CollabManager receives an agent_mgr or name resolver via setter)
    if self._agent_mgr is not None:
        name = self._agent_mgr.get_name(session_key)
        if name:
            return name
    return session_key.split(":")[-1]  # fallback
```

---

## 7. ChatHandler Changes

### 7.1 Detecting @ mentions in agent responses

When an agent's response text contains `@AgentName` and the response is in a project tab, ChatHandler relays it through CollabManager.

**Location:** `_handle_final_response()` in `chat_handler.py`.

After existing rendering logic, before method return:

```python
# ── A2A relay detection ──────────────────────────────────────────────────
if self._collab_manager is not None and session_key and final_text:
    # Only in project context
    project_name = self._agent_to_project.get_project(session_key)
    if project_name:
        relay = self._detect_a2a_mention(final_text, session_key, project_name)
        if relay is not None:
            self._collab_manager.start_relay(
                project_name=project_name,
                initiator_sk=session_key,
                target_sk=relay["target_sk"],
                question_text=relay["question"],
            )
```

### 7.2 A2A mention detection

```python
def _detect_a2a_mention(self, text: str, source_sk: str, project_name: str) -> dict | None:
    """
    Detect @AgentName in agent response text.
    Returns {"target_sk": str, "question": str} or None.

    Uses the same @mention resolution as CommandHandler —
    searches both gateway and special agents.
    """
    import re
    mention_match = re.search(r'@([A-Za-z][A-Za-z0-9_]+)', text)
    if not mention_match:
        return None

    agent_name = mention_match.group(1)

    # Resolve via CommandHandler's existing logic
    if self._command_handler is not None:
        from models.command import MentionResolution
        resolution = self._command_handler.resolve_inline_mention(f"@{agent_name}", source_sk)
        if resolution.target_session_key and resolution.target_session_key != source_sk:
            # Don't let an agent @mention itself
            return {
                "target_sk": resolution.target_session_key,
                "question": text,
            }
    return None
```

### 7.3 Response capture hook

In `_handle_final_response()`, after rendering:

```python
# ── A2A response capture ─────────────────────────────────────────────────
if self._collab_manager is not None:
    if self._collab_manager.is_pending_relay(session_key):
        self._collab_manager.capture_response(session_key, final_text)
```

This runs AFTER the relay detection (§7.1) so that the agent's own response can trigger a new relay AND be captured as part of an existing thread in the same call.

### 7.4 Setter

```python
def set_collab_manager(self, manager) -> None:
    """Set CollabManager for A2A relay. Called by window.py."""
    self._collab_manager = manager
```

---

## 8. AgentRuntimeHandler Changes

### 8.1 Response capture for special agents

In `_do_response_complete()`, after existing rendering logic (after the `if not was_streaming` block and before the `on_agent_end_cb` fire):

```python
# ── A2A response capture ─────────────────────────────────────────────────
if self._collab_manager is not None:
    if self._collab_manager.is_pending_relay(session_key):
        self._collab_manager.capture_response(session_key, text)
```

### 8.2 A2A mention detection in special agent responses

Same logic as §7.1 but for special agents. After the response capture:

```python
# ── A2A relay from special agent ──────────────────────────────────────────
if self._collab_manager is not None and self._active_project:
    project_name = self._active_project[0]
    relay = self._detect_a2a_mention(text, session_key, project_name)
    if relay is not None:
        self._collab_manager.start_relay(
            project_name=project_name,
            initiator_sk=session_key,
            target_sk=relay["target_sk"],
            question_text=relay["question"],
        )
```

The `_detect_a2a_mention()` method is the same as the one on ChatHandler (§7.2). To avoid duplication, it can be extracted as a standalone function in a new `utils/collab_utils.py` or placed on CollabManager as a static/class method:

```python
# In CollabManager (or utils/collab_utils.py):
@staticmethod
def detect_a2a_mention(text: str, source_sk: str, project_name: str,
                       command_handler) -> dict | None:
    """Detect @AgentName in text. Returns {target_sk, question} or None."""
    import re
    mention_match = re.search(r'@([A-Za-z][A-Za-z0-9_]+)', text)
    if not mention_match:
        return None
    agent_name = mention_match.group(1)
    resolution = command_handler.resolve_inline_mention(f"@{agent_name}", source_sk)
    if resolution.target_session_key and resolution.target_session_key != source_sk:
        return {"target_sk": resolution.target_session_key, "question": text}
    return None
```

### 8.3 Setter

```python
def set_collab_manager(self, manager) -> None:
    """Set CollabManager for A2A relay. Called by window.py."""
    self._collab_manager = manager
```

---

## 9. Prompt File: `prompts/system/collab.md`

This file is composed into all agent system prompts (both gateway and special agents) by `prompt_loader.py`.

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

### 9.1 Prompt loader integration

In `utils/prompt_loader.py`, `compose_system_prompt()`, after loading `default.md`:

```python
# After step 1 (default) and before step 2 (project-awareness):
# Load collaboration protocol for all agents
collab = load_prompt_template("collab")
if collab:
    parts.append(collab)
```

This applies to ALL agents — gateway agents get it via the composed system prompt (sent through the gateway), and special agents get it via `build_system_prompt()` which calls `compose_system_prompt()`.

---

## 10. Window Wiring

### 10.1 In `window.py` `_build()` method

After creating `AgentRuntimeHandler` and `FeedHandler`:

```python
# ── CollabManager ─────────────────────────────────────────────────────────
from ui.handlers.collab_manager import CollabManager

self._collab_manager = CollabManager(
    GLib=GLib,
    feed_handler=self._feed_handler,
    agent_runtime_handler=self._agent_runtime_handler,
    gw=self._gw,  # may be None at construction, set later
)
self._collab_manager.set_agent_mgr(self._gateway_handler.agent_mgr)

# Wire to handlers
self._chat_handler.set_collab_manager(self._collab_manager)
self._agent_runtime_handler.set_collab_manager(self._collab_manager)
self._command_handler.set_special_agents(self._agent_runtime_handler.get_special_agents())
```

### 10.2 Gateway connect/disconnect sync

In `_on_ws_connect()` (after gateway connects):

```python
self._collab_manager.set_gateway_client(self._gw)
self._collab_manager.set_agent_mgr(self._gateway_handler.agent_mgr)
```

In `_on_disconnect_gateway()`:

```python
self._collab_manager.set_gateway_client(None)
```

---

## 11. Convergence Integration

### 11.1 Import

```python
from converge.converge import should_stop
```

### 11.2 Checking convergence

In `CollabManager.capture_response()`:

```python
def capture_response(self, session_key: str, text: str) -> None:
    with self._lock:
        thread_id = self._sk_to_thread.get(session_key)
        if thread_id is None:
            return
        thread = self._threads.get(thread_id)
        if thread is None or not thread.active:
            return

        thread.responses.append({"text": text, "from": session_key})
        thread.turn += 1

        if should_stop(thread.responses, thread.turn):
            self._close_thread_internal(thread_id)
        elif thread.turn < 15:
            # Relay response back to initiator for next turn
            initiator = thread.initiator_sk
            relay_text = self._build_relay_message(session_key, text, thread.project_name)
            self._send_relay(initiator, relay_text)
            # Track initiator as pending for their next response
            self._pending_relays.add(initiator)
            self._sk_to_thread[initiator] = thread_id
```

### 11.3 Convergence guarantees

- `should_stop()` always returns `False` for turn ≤ 2 (QAC form) — minimum 3-turn exchange
- `should_stop()` always returns `True` for turn ≥ 15 (hard wall) — prevents runaway
- Between turns 3–14, Random Forest classifies based on 10 conversational signals

---

## 12. Edge Cases and Error Handling

### 12.1 Agent @mentions itself

`detect_a2a_mention()` checks `target_session_key != source_sk`. Self-mentions are silently ignored.

### 12.2 Target agent is offline (gateway agent)

`_send_relay()` checks `gw.is_connected()` before sending. If offline, the relay fails silently — the initiating agent's response still displays in the project tab, but no consultation starts. The intent card is not posted.

### 12.3 Target agent doesn't exist

`resolve_inline_mention()` returns an error `MentionResolution`. `detect_a2a_mention()` returns `None` — treated as if no @mention was found. Agent's response displays normally.

### 12.4 Multiple @mentions in one response

`re.search()` returns the first match. Only one consultation per response. If the agent needs to consult multiple agents, it does so sequentially.

### 12.5 Thread already exists for the same pair

`start_relay()` checks `_threads` for an existing thread with the same `thread_id`. Returns `None` if already active — prevents duplicate threads.

### 12.6 Project closes during active A2A

`CollabManager` must expose a `clear_project(project_name)` method called from `ProjectHandler.on_project_closed()`. This closes all A2A threads for the project and cleans up pending relays.

### 12.7 Concurrent A2A threads

Multiple A2A threads can be active simultaneously (e.g., Coder↔QTR and Debugger↔QTR). Each has a unique `thread_id`. `_pending_relays` and `_sk_to_thread` track which session keys belong to which thread.

---

## 13. Implementation Order

### Phase 1 — @ mention resolution (no A2A yet)

1. Add `set_special_agents()` to `CommandHandler`
2. Extend `_resolve_mention()` to search special agents
3. Wire in `window.py`
4. **Test:** `@Coder` and `@Debugger` resolve from project tab input

### Phase 2 — Shared prompt

1. Create `prompts/system/collab.md`
2. Add collab.md loading to `prompt_loader.py` `compose_system_prompt()`
3. **Test:** Verify composed prompt includes collaboration section

### Phase 3 — CollabManager core

1. Create `ui/handlers/collab_manager.py` with `A2AThread` dataclass and `CollabManager`
2. Implement `start_relay()`, `_send_relay()`, `_build_relay_message()`
3. Implement `capture_response()` with convergence integration
4. Implement `close_thread()` with closing card
5. **Test:** Unit tests for thread lifecycle, convergence, edge cases

### Phase 4 — Response routing hooks

1. Add `set_collab_manager()` to `ChatHandler`
2. Add A2A detection and capture in `_handle_final_response()`
3. Add `set_collab_manager()` to `AgentRuntimeHandler`
4. Add A2A detection and capture in `_do_response_complete()`
5. Wire in `window.py`
6. **Test:** Integration test — Coder @mentions Debugger, exchange happens, convergence closes

### Phase 5 — Documentation

1. Update `docs/ARCHITECTURE.md`:
   - §2: Add `ui/handlers/collab_manager.py` to directory structure
   - §3: Add CollabManager module responsibility section
   - §4: Add A2A data flow section
   - §11: Add `prompts/system/collab.md` to file inventory
   - §12: Add `collab_manager.py` to file inventory with line count
2. Update `docs/PROJECT_STATUS.md`

---

## 14. Files Changed Summary

| File | Action | Approximate changes |
|------|--------|-------------------|
| `ui/handlers/collab_manager.py` | **New** | ~200 lines |
| `prompts/system/collab.md` | **New** | ~35 lines |
| `ui/handlers/command_handler.py` | Modify | +20 lines (special agent resolution) |
| `ui/handlers/chat_handler.py` | Modify | +40 lines (A2A detection, capture, setter) |
| `ui/handlers/agent_runtime_handler.py` | Modify | +30 lines (A2A detection, capture, setter) |
| `utils/prompt_loader.py` | Modify | +5 lines (collab.md loading) |
| `ui/window.py` | Modify | +15 lines (CollabManager creation + wiring) |
| `docs/ARCHITECTURE.md` | Modify | +60 lines (new sections) |
| `tests/test_collab_manager.py` | **New** | ~150 lines |

**Total new code:** ~430 lines
**Total modified code:** ~110 lines across 5 files

---

## 15. What This Does NOT Do

- **No persistent A2A history.** Threads are ephemeral. Once closed, their state is discarded.
- **No agent-initiated conversations outside project context.** A2A only works within an active project.
- **No multi-agent consultations.** One @mention per response, one target per thread.
- **No new chat tabs.** All A2A exchanges appear in the project tab.
- **No special agent conversation sharing.** Each special agent still has one conversation per project. A2A relay messages are injected into the existing conversation, not a new session.
- **No changes to `converge/`.** The existing convergence detector is used as-is.

---

## 16. Testing Strategy

### 16.1 Unit tests: `tests/test_collab_manager.py`

- Thread ID construction
- `start_relay()` creates thread, posts intent card, sends relay
- `capture_response()` appends to thread, checks convergence
- `close_thread()` cleans up state, posts closing card
- Edge cases: self-mention, offline gateway, non-existent agent, duplicate thread
- Convergence: turn ≤ 2 never stops, turn ≥ 15 always stops, mock `should_stop` for mid-range

### 16.2 Unit tests: `tests/test_command_handler.py` (extend)

- `@Coder` resolves to `special:coder`
- `@Debugger` resolves to `special:debugger`
- `@Co` resolves via prefix match
- `@Unknown` returns error
- Mixed gateway + special agent results

### 16.3 Integration test (manual)

1. Open a project with Coder and QTR as members
2. Send: `@Coder implement auth`
3. Coder responds with `@Debugger should empty string be invalid?`
4. Verify intent card appears in project feed
5. Debugger responds
6. Verify exchange appears in project tab
7. Wait for convergence or 15-turn limit
8. Verify closing card appears in project feed
