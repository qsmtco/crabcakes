# SPECIFICATION: Agent Response Command Parsing — Agent-Initiated A2A

**Document:** SPEC (implementation-ready)
**Date:** 2026-05-12
**Author:** Qaster
**Status:** ✅ DONE — implemented as Phase 6.2. See `ui/handlers/agent_command_handler.py` (25K). Parses backtick commands from agent response text via `on_agent_response` callback and routes through `CommandHandler.process_input()`. Answer relay via `pending-ask` tracking (`ui/window.py:496`).
**Phase:** 6.2 (builds on Phase 6.1 — A2A simplification)
**Related:** `docs/ARCHITECTURE.md` §3.14, §3.21a, §3.21d, §4.5, §4.11, §5, §8.6

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` This spec was implemented as Phase 6.2 and shipped. See `ui/handlers/agent_command_handler.py` (25K, dated 2026-06-10). The handler parses backtick commands from agent response text (`on_agent_response` callback) and routes them through `CommandHandler.process_input()`. The "asking agent never sees the answer" problem identified in this spec was solved via `pending-ask` tracking (answers are routed back to the asking agent's session via the relay mechanism at `ui/window.py:496`). See also `docs/proposals/AGENT_COMMAND_HOOK_PROPOSAL.md` (proposal-level ancestor) and `PLAN-a2a-simplification.md` (Phase 6.1 ancestor).

---

## 0. Problem Statement

The command-based A2A system (Phase 6.1) works for **human-initiated** consultations: a human types `` `ask @Coder question` `` in a project tab, `CommandHandler.process_input()` parses it, and the message routes to the target agent. This path works and has been tested.

However, **agent-initiated** consultations do not work. When an agent includes a backtick command in its response text (e.g., Coder writes `` `ask @Debugger is this edge case valid?` ``), the command renders as plain text in a chat bubble. It is never parsed or routed.

**Root cause:** `CommandHandler.process_input()` is called only from `ChatHandler.on_send()` — the human input path. Agent responses flow through `_handle_final_response()` (gateway agents) or `_do_response_complete()` (special agents). Neither path parses backtick commands.

**Additional problem (discovered during review):** Even if commands are routed, the asking agent never receives the answer. Agent responses are rendered as bubbles in the project tab, but agents cannot see each other's bubbles — each agent has its own isolated conversation context. Without a relay mechanism, agent-initiated `ask` commands are pointless.

**Impact:** Agents cannot consult each other. The A2A system is human-only.

**Evidence:**
- `collab.md` already instructs agents to use backtick commands for consultation
- ARCHITECTURE.md §4.11 states "agents that need another agent's input include a backtick command in their response text"
- Tested 2026-05-12: human `` `ask @Coder` `` works; agent `` `ask @QTR` `` in response text does nothing

---

## 1. Design Decision

Add a **command parsing hook** to both agent response pipelines. After an agent's final response is rendered as a chat bubble, scan the response text for backtick commands. If found, parse and route them through the existing `CommandHandler.process_input()` pipeline — the same path used for human input.

Add a **relay mechanism** so the answering agent's response is delivered back to the asking agent. When Agent A asks Agent B, the system records the pending request. When Agent B responds, the response is relayed back to Agent A as a context message prefixed with the source agent's identity.

The relay is **open-ended** — if Agent B's response also contains a command (e.g., `ask @C`), the chain continues. The only stop condition is a configurable depth limit (`_MAX_CHAIN_DEPTH`).

**Architecture:**
- New handler: `AgentCommandHandler` in `ui/handlers/agent_command_handler.py`
- Follows §8.6 handler pattern: receives dependencies via setters, never imports other handlers
- Callbacks wired by `window.py` into both `ChatHandler` and `AgentRuntimeHandler`
- No changes to `CommandHandler`, `CollabHandler`, or the rendering pipeline

---

## 2. Architecture Alignment

### Handler pattern (§8.6)
- One handler per subsystem — this is "agent response command parsing + relay"
- New file: `ui/handlers/agent_command_handler.py`
- Receives `CommandHandler`, `AgentRuntimeHandler`, `GatewayClient`, `AgentManager`, `AgentRoutingTable` via setters
- Never imports from `ui/handlers/`
- `window.py` creates and wires all dependencies

### Callback pattern (§5)
- `ChatHandler` and `AgentRuntimeHandler` receive an `on_agent_response` callback via setter
- They call the callback after rendering the final response — they do not know what it does
- No component reaches into another component's internals

### Routing reuse
- `CommandHandler.process_input()` is called as-is (no modification)
- `CollabHandler.cmd_ask()` etc. are called as-is (no modification)
- Transport routing (special vs. gateway) is duplicated in `AgentCommandHandler._route_to_target()` because handlers cannot import each other (§8.6 rule 2). The logic is minimal and stable.

---

## 3. Scope

### In Scope
- Parsing backtick commands from agent response text
- Routing parsed commands through the existing command pipeline
- Relay mechanism: delivering the answering agent's response back to the asking agent
- Supporting both special agent (AgentRuntime) and gateway agent response paths
- Fenced code block filtering (avoid false positives on code examples)
- Rate limiting (configurable chain depth + per-response command limit)
- Project awareness prefix for first-time gateway agent targets

### Out of Scope
- Modifying `CommandHandler` or `CollabHandler`
- Modifying the rendering pipeline
- Changing the `collab.md` prompt
- Echo bubble rendering for agent-initiated commands (no "→ @Agent: ..." bubble)

---

## 4. Implementation

### 4.1 New File: `ui/handlers/agent_command_handler.py`

```python
"""
Agent Response Command Parser — agent-initiated A2A with relay (Phase 6.2).

Scans agent response text for backtick commands after the response is rendered,
routes them through CommandHandler.process_input(), and relays answers back
to the asking agent.

Relay mechanism: when Agent A sends `ask @B question`, the system records
_pending_asks[B] = A. When B responds, the response is delivered back to A
as a context message. If B's response also contains a command, the chain
continues. The chain is bounded by _MAX_CHAIN_DEPTH.

Thread safety: on_agent_response() is called from main thread via GLib.idle_add()
in both response pipelines (ChatHandler._handle_final_response and
AgentRuntimeHandler._do_response_complete). No additional dispatch needed.
"""

import re
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

# ── Constants ──

# Max nested command chains before cutoff.
# Open-ended relay: chains continue as long as agents keep issuing commands,
# up to this depth. Change this value to allow more or fewer hops.
_MAX_CHAIN_DEPTH = 3

# Max commands parsed from a single agent response.
_MAX_COMMANDS_PER_RESPONSE = 3

# Regex for single-backtick-quoted content: `command text`
# Does NOT match triple-backtick fenced blocks (```...```) because those
# are stripped by _strip_fenced_blocks() before this runs.
_BACKTICK_COMMAND = re.compile(r"`([^`\n]+)`")


class AgentCommandHandler:
    """
    Parses backtick commands from agent response text, routes them to target
    agents, and relays responses back to the asking agent.

    Wired via window.py. Receives all dependencies through setters.
    Never imports from ui/handlers/.
    """

    def __init__(self, *, GLib_module=None):
        """
        Args:
            GLib_module: gi.repository.GLib or None (reserved, not currently used
                         since on_agent_response runs on main thread).
        """
        self._GLib = GLib_module
        self._command_handler = None       # CommandHandler
        self._agent_runtime_handler = None  # AgentRuntimeHandler
        self._gw = None                     # GatewayClient
        self._agent_mgr = None              # AgentManager
        self._agent_to_project = None       # AgentRoutingTable
        self._project_handler = None        # ProjectHandler — for awareness prefix
        self._awareness_sent: set[str] | None = None  # Shared set from ChatHandler

        # Chain depth: session_key → depth counter
        # Increments each hop. When depth >= _MAX_CHAIN_DEPTH, commands are dropped.
        self._chain_depth: dict[str, int] = {}

        # Pending asks: target_session_key → source_session_key
        # When Agent A asks Agent B, we record _pending_asks[B] = A.
        # When B responds, we relay B's answer back to A.
        # Supports open-ended relay: if B also asks C, then _pending_asks[C] = B,
        # and when C responds, C's answer goes to B, then B's answer (including
        # the relay from C) goes to A.
        # Only set for response-expecting commands (ask, delegate). `tell` is
        # one-way and does NOT create a pending ask.
        self._pending_asks: dict[str, str] = {}

        # Last command name processed — used to distinguish ask/delegate from tell.
        # Set during on_agent_response() before _route_command() is called.
        self._last_command_name: str = ""

    # ── Setters (wired by window.py) ──────────────────────────────────────

    def set_command_handler(self, handler) -> None:
        """CommandHandler — provides process_input() and get_command_names()."""
        self._command_handler = handler

    def set_agent_runtime_handler(self, handler) -> None:
        """AgentRuntimeHandler — for special agent routing."""
        self._agent_runtime_handler = handler

    def set_gateway_client(self, gw) -> None:
        """GatewayClient — for gateway agent routing. May be None if offline."""
        self._gw = gw

    def set_agent_manager(self, mgr) -> None:
        """AgentManager — for display name resolution."""
        self._agent_mgr = mgr

    def set_agent_routing(self, routing_table) -> None:
        """AgentRoutingTable — for project→agent lookups."""
        self._agent_to_project = routing_table

    def set_project_handler(self, handler) -> None:
        """ProjectHandler — for project_path (awareness prefix in agent-initiated
        gateway messages). Without this, _build_awareness_prefix() degrades to "".
        """
        self._project_handler = handler

    def set_awareness_sent(self, awareness_set: set[str]) -> None:
        """Shared _awareness_sent set from ChatHandler — for first-time
        project awareness prefix injection on gateway agent sends."""
        self._awareness_sent = awareness_set

    # ── Core ──────────────────────────────────────────────────────────────

    def on_agent_response(self, session_key: str, text: str,
                          project_name: str | None) -> None:
        """
        Called after an agent's final response is rendered.

        Two responsibilities:
        1. RELAY: If this agent has a pending ask (someone asked it a question),
           relay its response back to the asking agent.
        2. COMMAND SCAN: Scan the response text for backtick commands.
           If found, parse and route them to target agents.

        Args:
            session_key: The responding agent's session key
                         (e.g. "special:coder" or "agent:qaster:...")
            text: The agent's full response text
            project_name: Active project name, or None
        """
        if not text:
            return

        # ── Step 1: Relay answer back to asking agent ─────────────────────

        source_sk = self._pending_asks.pop(session_key, None)
        if source_sk is not None:
            self._relay_response(source_sk, session_key, text, project_name)

        # ── Step 2: Scan for new commands ─────────────────────────────────

        if not self._command_handler:
            return

        # Chain depth guard — prevent runaway command chains
        depth = self._chain_depth.get(session_key, 0)
        if depth >= _MAX_CHAIN_DEPTH:
            logger.warning(
                "[agent-cmd] Chain depth limit (%d) reached for %s — dropping commands",
                _MAX_CHAIN_DEPTH, session_key
            )
            self._chain_depth.pop(session_key, None)
            return

        # Strip fenced code blocks to avoid false positives
        clean_text = self._strip_fenced_blocks(text)

        # Extract and filter backtick commands
        matches = _BACKTICK_COMMAND.findall(clean_text)
        if not matches:
            self._chain_depth.pop(session_key, None)
            return

        known_commands = self._command_handler.get_command_names()
        command_count = 0

        for raw_match in matches:
            if command_count >= _MAX_COMMANDS_PER_RESPONSE:
                logger.warning(
                    "[agent-cmd] Per-response command limit (%d) reached — skipping remaining",
                    _MAX_COMMANDS_PER_RESPONSE
                )
                break

            # Reconstruct with backtick prefix for process_input
            candidate = f"`{raw_match}"
            first_word = raw_match.strip().split()[0].lower() if raw_match.strip() else ""

            # Implicit ask: @AgentName → treat as "ask"
            if first_word.startswith("@"):
                first_word = "ask"

            if first_word not in known_commands:
                continue  # Not a recognized command — skip

            result = self._command_handler.process_input(session_key, candidate)
            if result.handled and result.forward_to and result.forward_text:
                # Store command name for _route_command to check relay eligibility
                self._last_command_name = first_word
                self._route_command(result, project_name, depth, source_sk=session_key)
                command_count += 1
            elif result.handled and result.broadcast_targets and result.forward_text:
                for target in result.broadcast_targets:
                    self._route_to_target(
                        target, result.forward_text, project_name
                    )
                command_count += 1

        # Clear chain depth for this session (its response is complete)
        self._chain_depth.pop(session_key, None)

    # ── Relay ─────────────────────────────────────────────────────────────

    def _relay_response(self, source_sk: str, target_sk: str,
                        text: str, project_name: str | None) -> None:
        """Relay an agent's response back to the agent that asked it a question.

        The response is wrapped in a context prefix identifying the source agent,
        then sent to the asking agent via the normal routing mechanism.

        Args:
            source_sk: The session key of the agent that asked the question (recipient)
            target_sk: The session key of the agent that answered (responder)
            text: The responder's full response text
            project_name: Active project name, or None
        """
        # Resolve display name of the answering agent
        display_name = self._resolve_display_name(target_sk)
        relay_text = f"[{display_name} responded]: {text}"

        logger.info(
            "[agent-cmd] Relaying response from %s (%s) back to %s, chain_depth=%d",
            display_name, target_sk, source_sk,
            self._chain_depth.get(source_sk, 0)
        )

        # Clear chain depth for source — the relay is a new context message,
        # not a command chain hop from source
        self._chain_depth.pop(source_sk, None)

        self._route_to_target(source_sk, relay_text, project_name)

    # ── Routing ──────────────────────────────────────────────────────────

    def _route_command(self, result, project_name: str | None,
                       current_depth: int, source_sk: str) -> None:
        """Route a single CommandResult to the target agent and record pending ask.

        Only records a pending ask for commands that expect a response (ask, delegate).
        `tell` is one-way and does NOT set up a relay.

        Args:
            result: CommandResult from CommandHandler.process_input()
            project_name: Active project name, or None
            current_depth: Current chain depth of the source agent
            source_sk: Session key of the agent that issued the command
        """
        target_sk = result.forward_to

        # Record pending ask ONLY for response-expecting commands.
        # `tell` is one-way information sharing — no relay needed.
        # Only `ask` and `delegate` expect a response.
        if self._last_command_name != "tell":
            self._pending_asks[target_sk] = source_sk

        # Increment chain depth for the target
        self._chain_depth[target_sk] = current_depth + 1

        # Route the message to the target
        self._route_to_target(target_sk, result.forward_text, project_name)

    def _route_to_target(self, target_sk: str, text: str,
                         project_name: str | None) -> None:
        """Send message to a target agent via the correct transport."""
        is_special = (self._agent_runtime_handler is not None
                      and target_sk in self._agent_runtime_handler.get_special_agents())

        if is_special:
            self._agent_runtime_handler.send_to_special_agent(target_sk, text)
        elif self._gw is not None and self._gw.is_connected():
            # Inject awareness prefix for first-time (project, agent) pairs
            prefix = ""
            if project_name and self._awareness_sent is not None:
                key = f"{project_name}:{target_sk}"
                if key not in self._awareness_sent:
                    prefix = self._build_awareness_prefix(project_name)
                    self._awareness_sent.add(key)
            self._gw.send_message(target_sk, prefix + text)
        else:
            logger.debug(
                "[agent-cmd] Cannot route to %s — no gateway connection", target_sk
            )

    def _resolve_display_name(self, session_key: str) -> str:
        """Resolve a session key to a human-readable display name."""
        # Check special agents first
        if self._agent_runtime_handler is not None:
            specials = self._agent_runtime_handler.get_special_agents()
            if session_key in specials:
                return specials[session_key]
        # Then agent manager
        if self._agent_mgr is not None:
            name = self._agent_mgr.get_name(session_key)
            if name:
                return name
        # Fallback: last segment of session key
        return session_key.split("/")[-1]

    def _build_awareness_prefix(self, project_name: str) -> str:
        """Build project awareness prefix for gateway agent messages.

        NOTE: This method is intentionally duplicated from ChatHandler
        because handlers cannot import each other (§8.6 rule 2).
        The logic is stable and unlikely to diverge.
        """
        if not self._agent_to_project:
            return ""
        if not self._project_handler:
            return ""
        project_path = self._project_handler.get_active_project_path()
        if not project_path:
            return ""
        parts = []
        try:
            from utils.project_awareness import build_awareness_block
            block = build_awareness_block(project_path)
            if block.strip():
                parts.append(block.strip())
        except Exception:
            pass  # Awareness is best-effort
        # Append collab protocol so gateway agents know the consultation protocol
        try:
            from utils.prompt_loader import load_prompt_template
            collab = load_prompt_template("collab")
            if collab and collab.strip():
                parts.append(collab.strip())
        except Exception:
            pass
        if not parts:
            return ""
        return "\n\n".join(parts) + "\n\n"

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _strip_fenced_blocks(text: str) -> str:
        """Remove fenced code blocks (```...```) from text.

        Prevents false-positive command detection on code examples.
        Handles both ```language\\ncode``` and ```inline``` forms.
        """
        return re.sub(r"```.*?```", "", text, flags=re.DOTALL)
```

### 4.2 Edit: `ui/handlers/chat_handler.py`

**Three changes:**

#### 4.2.1 Add init field (line 65, after `_awareness_sent`)

```python
        self._awareness_sent: set[str] = set()  # track "project:agent" pairs that received awareness
        self._on_agent_response = None  # injected via set_on_agent_response() — Phase 6.2
        self._agent_mgr = None  # injected via set_agent_manager() after gateway connect
```

#### 4.2.2 Add setter (after `set_agent_manager` method)

```python
    def set_on_agent_response(self, cb):
        """Set callback for agent response command parsing (Phase 6.2).
        Called by window.py to inject AgentCommandHandler.on_agent_response."""
        self._on_agent_response = cb
```

#### 4.2.3 Call callback in `_handle_final_response()` (line ~560, at end of method)

After the last line `chat_box.record('Agent', final_text)` and before the method ends, add:

```python
        # Agent command parsing hook (Phase 6.2)
        if self._on_agent_response is not None and final_text:
            project_name = self._agent_to_project.get_project(session_key) if self._agent_to_project else None
            self._on_agent_response(session_key, final_text, project_name)
```

**Insertion context** — the method currently ends like this (lines 558-561):
```python
        if chat_box is not None and hasattr(chat_box, 'record'):
            chat_box.record('Agent', final_text)

    def _extract_text(self, msg_obj) -> str:
```

Insert the callback call between the `record` call and the method exit, before `_extract_text`.

### 4.3 Edit: `ui/handlers/agent_runtime_handler.py`

**Three changes:**

#### 4.3.1 Add init field (line ~76, after `_streaming_text`)

```python
        # Accumulated streaming text: session_key → cumulative text
        # AgentRuntime sends incremental deltas; ChatRenderHandler expects cumulative.
        self._streaming_text: dict[str, str] = {}
        self._on_agent_response = None  # injected via set_on_agent_response() — Phase 6.2
```

#### 4.3.2 Add setter (after existing setters, e.g., after `set_on_agent_end`)

```python
    def set_on_agent_response(self, cb):
        """Set callback for agent response command parsing (Phase 6.2).
        Called by window.py to inject AgentCommandHandler.on_agent_response."""
        self._on_agent_response = cb
```

#### 4.3.3 Call callback in `_do_response_complete()` (at end of method, before lifecycle fire)

The method currently ends like this (lines 633-637):
```python
        # Fire lifecycle: agent finished → ActivityHandler progress bar
        if self._on_agent_end_cb:
            self._on_agent_end_cb(session_key)
```

Insert the callback call BEFORE the lifecycle fire:

```python
        # Agent command parsing hook (Phase 6.2)
        if self._on_agent_response is not None and text:
            project_name = self._active_project[0] if self._active_project else None
            self._on_agent_response(session_key, text, project_name)

        # Fire lifecycle: agent finished → ActivityHandler progress bar
        if self._on_agent_end_cb:
            self._on_agent_end_cb(session_key)
```

**Note on Bug 1 (QTR audit):** The callback fires AFTER the bubble render attempt. If
`_resolve_chat_box(session_key)` returns `None` (no direct tab and no routing table
entry), the bubble does not render but the callback STILL fires with the full text. The
relay mechanism works correctly regardless. However, the display bug (missing bubble)
is a separate pre-existing issue that should be fixed: `_resolve_chat_box` should
fall back to the active project tab when the routing table lookup fails. This is a
defensive improvement, not a blocking issue for Phase 6.2.

### 4.4 Edit: `ui/handlers/command_handler.py`

**One change — add `get_command_names()` method:**

After the existing public methods, add:

```python
    def get_command_names(self) -> set[str]:
        """Return registered command names.

        Used by AgentCommandHandler to filter backtick-quoted text for
        known commands only (avoiding false positives on code examples).

        Phase 6.2 amendment (QTR 2026-05-12): uses list_commands() —
        CommandRegistry does not expose keys(); list_commands() is the public API.
        """
        return set(self._registry.list_commands())
```

The `_registry` is a `CommandRegistry` instance that has `list_commands()`.
This is a read-only accessor with no behavioral changes.

### 4.5 Edit: `ui/window.py`

**Wire the new handler in `_build()` method.**

After the existing CommandHandler wiring (around line 350-375, after `self._agent_runtime_handler.set_on_agent_end(...)`), add:

```python
        # ── Agent Command Handler (Phase 6.2) ────────────────────────────
        from ui.handlers.agent_command_handler import AgentCommandHandler
        self._agent_command_handler = AgentCommandHandler(GLib_module=GLib)
        self._agent_command_handler.set_command_handler(self._command_handler)
        self._agent_command_handler.set_agent_runtime_handler(self._agent_runtime_handler)

        # Wire callbacks into agent response pipelines
        self._chat_handler.set_on_agent_response(self._agent_command_handler.on_agent_response)
        self._agent_runtime_handler.set_on_agent_response(self._agent_command_handler.on_agent_response)
```

In `_sync_gateway_to_chat_handler()` (called after gateway connect), add:

```python
        # Wire AgentCommandHandler with live gateway + manager references
        self._agent_command_handler.set_gateway_client(gw)
        self._agent_command_handler.set_agent_manager(self._gateway_handler.agent_mgr)
        self._agent_command_handler.set_agent_routing(self._agent_to_project)
        self._agent_command_handler.set_awareness_sent(self._chat_handler._awareness_sent)
        self._agent_command_handler.set_project_handler(self._project_handler)  # Phase 6.2 amendment QTR 2026-05-12
```

**Note on `_awareness_sent` sharing:** `AgentCommandHandler` receives a reference to `ChatHandler._awareness_sent` (a set object). Since Python sets are mutable and passed by reference, both handlers share the same tracking state. This prevents duplicate awareness prefixes whether the first message was human-initiated or agent-initiated.

---

## 5. Data Flow

### 5.1 Single Ask — Coder asks Debugger, Debugger answers, relay back

```
Human types in project tab: "Coder, implement the file watcher"
         │
         ▼
Coder responds: "I've written the initial watcher. `ask @Debugger should I use
                observer or polling for the debounce timer?`"
         │
         ▼
AgentRuntimeHandler._do_response_complete("special:coder", text)
  → renders bubble in project tab ✅ (unchanged)
  → calls on_agent_response("special:coder", text, "crabwatch")
         │
         ▼
AgentCommandHandler.on_agent_response("special:coder", text, "crabwatch")
  → Step 1 (relay): no pending ask for "special:coder" → skip
  → Step 2 (command scan):
       _strip_fenced_blocks → clean_text
       regex finds: "ask @Debugger should I use observer or polling for the debounce timer?"
       CommandHandler.process_input → CommandResult(forward_to="special:debugger", ...)
       _route_command():
         _pending_asks["special:debugger"] = "special:coder"   ← records who asked
         _chain_depth["special:debugger"] = 1
         send_to_special_agent("special:debugger", "should I use observer or polling...")
         │
         ▼
Debugger receives the question, processes it, and responds:
         │
         ▼
AgentRuntimeHandler._do_response_complete("special:debugger", text)
  → renders bubble in project tab ✅
  → calls on_agent_response("special:debugger", "Use an observer pattern...", "crabwatch")
         │
         ▼
AgentCommandHandler.on_agent_response("special:debugger", "Use an observer pattern...", "crabwatch")
  → Step 1 (relay):
       source_sk = _pending_asks.pop("special:debugger") → "special:coder"   ← found!
       display_name = "Debugger"
       relay_text = "[Debugger responded]: Use an observer pattern..."
       _route_to_target("special:coder", relay_text, "crabwatch")
       send_to_special_agent("special:coder", "[Debugger responded]: Use an observer pattern...")
       Coder now has the answer in its conversation context ✅
  → Step 2 (command scan):
       no backtick commands in Debugger's response → done
       _chain_depth["special:debugger"] cleared
```

**Result in project tab:**
```
┌─────────────────────────────────────────────────┐
│  You: Coder, implement the file watcher          │
│                                                   │
│  Coder: I've written the initial watcher.         │
│  `ask @Debugger should I use observer or polling?`│
│                                                   │
│  Debugger: Use an observer pattern. Integrate     │
│  natively with watchdog's event system.           │
│                                                   │
│  [input box]                                      │
└─────────────────────────────────────────────────┘
```

**What Coder sees in its conversation context:**
- Original human message: "Coder, implement the file watcher"
- Coder's own response (in its context): the ask command
- Relay message: "[Debugger responded]: Use an observer pattern..."

Coder can now continue working with Debugger's answer.

### 5.2 Multi-Hop Relay — Coder → Debugger → Qaster

```
Coder: "Let me check. `ask @Debugger should I use X?"
  → _pending_asks["special:debugger"] = "special:coder"
  → chain_depth["special:debugger"] = 1

Debugger: "X is good for local use. But `ask @Qaster is X compatible with
           the gateway API?"
  → RELAY back to Coder: "[Debugger responded]: X is good for local use..."
     Coder gets Debugger's partial answer ✅
  → NEW COMMAND: _pending_asks["agent:qaster:..."] = "special:debugger"
     chain_depth["agent:qaster:..."] = 2
  → gw.send_message to Qaster

Qaster: "Yes, X is compatible. Here's the config."
  → RELAY back to Debugger: "[Qaster responded]: Yes, X is compatible..."
     Debugger gets Qaster's answer ✅
  → No new commands → done
  → chain_depth["agent:qaster:..."] cleared

Debugger: receives relay "[Qaster responded]: Yes, X is compatible..."
  → Debugger responds (if it has more to say) or just acknowledges
  → No pending ask for Debugger → no relay
  → No commands → done
```

**Chain depth trace:**
- Coder asks Debugger → depth 1
- Debugger asks Qaster → depth 2
- If Qaster tried to ask anyone → depth 3 (allowed, it equals `_MAX_CHAIN_DEPTH - 1`)
- If Qaster's target tried to ask → depth 3, depth check: 3 >= 3 → **DROPPED**

### 5.3 Chain Depth Guard — Cycle Prevention

```
Agent A → `ask @B question`  →  depth[B] = 1
Agent B → `ask @C question`  →  depth[C] = 2
Agent C → `ask @A question`  →  depth[A] = 3
Agent A → `ask @D question`  →  depth check: depth[A]=3 >= _MAX_CHAIN_DEPTH(3) → DROPPED
```

### 5.4 Gateway Agent Response Path

Same relay logic, but the response arrives via gateway event:

```
Coder asks Qaster (gateway agent):
  → _pending_asks["agent:qaster:..."] = "special:coder"
  → gw.send_message("agent:qaster:...", awareness_prefix + text)
         │
         ▼
Gateway routes message to Qaster
  → Qaster responds → gateway sends chat event sessionKey="agent:qaster:..."
  → ChatHandler.on_chat_event() → _handle_final_response()
  → renders bubble in project tab ✅
  → calls on_agent_response("agent:qaster:...", text, "crabwatch")
         │
         ▼
AgentCommandHandler.on_agent_response("agent:qaster:...", text, "crabwatch")
  → RELAY: _pending_asks.pop("agent:qaster:...") → "special:coder"
     display_name = "Qaster"
     relay_text = "[Qaster responded]: ..."
     _route_to_target("special:coder", relay_text, "crabwatch")
     send_to_special_agent("special:coder", relay_text)
     Coder gets Qaster's answer ✅
  → COMMAND SCAN: no commands → done
```

---

## 6. Edge Cases and Guards

### 6.1 Code Block False Positives

**Problem:** Agent responses often contain fenced code blocks with backtick-quoted content (e.g., `` `print("hello")` `` inside a Python example).

**Solution:** `_strip_fenced_blocks()` removes all ```...``` fenced blocks before regex matching. Only single-backtick commands outside code fences are detected.

**Example:**
```
Here's the fix:

```python
result = `ask @Debugger`  # This is NOT a command
```

But `ask @Debugger is this right?`  ← This IS a command
```

After `_strip_fenced_blocks()`, the fenced block is removed. Only the second `` `ask @Debugger is this right?` `` remains for matching.

### 6.2 Multiple Commands Per Response

**Limit:** `_MAX_COMMANDS_PER_RESPONSE = 3`. An agent response with 10 backtick commands only processes the first 3. This prevents a single response from spawning excessive agent calls.

**Why 3?** Common case is 1 command. Rare case is 2 (ask two agents). 3 is generous. More than 3 is likely a code listing or prompt injection.

### 6.3 Chain Depth (Configurable)

**Limit:** `_MAX_CHAIN_DEPTH = 3`. After 3 nested hops, commands are dropped.

**Configurable:** Change the constant to adjust. Set to 1 for single-hop only. Set to 5 for longer chains. The relay is open-ended up to this limit.

**Why 3 by default?** One hop (Coder → Debugger) is the common case. Two hops (Coder → Debugger → Qaster) is rare but reasonable. Three is the safety cutoff for default operation.

### 6.4 No Echo Bubble

Human-initiated commands show an echo bubble ("→ @Coder: question"). Agent-initiated commands do NOT. Reason: the agent's response is already in the chat bubble with the command text visible. Adding an echo would be redundant and cluttering.

### 6.5 Relay Message Format

Relayed responses are prefixed with `[AgentName responded]:` so the receiving agent knows the message is a relay from another agent, not a new human message. This preserves conversation context for the receiving agent.

### 6.6 Relay Does NOT Create Chain Depth

When a response is relayed back to the asking agent, the asking agent's chain depth is **cleared** before the relay is sent. The relay is a new context message, not a continuation of the chain. If the asking agent's response to the relay contains a new command, that starts fresh at depth 0.

**Exception:** If the answering agent's response contains BOTH a command AND triggers a relay, the relay goes first, then the command is processed. The command target gets depth = answering agent's depth + 1 (incrementing the existing chain).

### 6.7 Offline Gateway

If the gateway is disconnected, gateway agent targets are silently skipped (logged at debug level). Special agent targets still work (they're local, no gateway needed). Pending asks for offline gateway agents remain in `_pending_asks` until the agent responds or the entry is cleaned up on window close.

### 6.8 No Active Project

If `project_name` is None (no project open), special agent routing is skipped (they require a project context). Gateway agent routing still works (no project dependency). Relays to special agents will fail gracefully.

### 6.9 Awareness Prefix

For gateway agent targets, the first message from a (project, agent) pair includes the project awareness prefix. `AgentCommandHandler` shares the `_awareness_sent` set with `ChatHandler`, so if a human already messaged the agent from this project, the prefix is not duplicated.

---

## 7. Test Specification

**File:** `tests/test_agent_command_handler.py`

**Test patterns:** Follow `tests/test_chat_handler.py` — mock at the boundary, test behavior not internals.

### Helper Classes

```python
from models.command import CommandResult


class FakeCommandHandler:
    """Mock CommandHandler that records calls."""
    def __init__(self):
        self._commands = {"ask", "tell"}
        self.processed = []

    def get_command_names(self):
        return self._commands

    def process_input(self, session_key, text):
        self.processed.append((session_key, text))
        if text.startswith("`ask @"):
            rest = text[6:]
            parts = rest.split(" ", 1)
            target = parts[0]
            msg = parts[1].rstrip("`") if len(parts) > 1 else ""
            return CommandResult(handled=True, forward_to=target, forward_text=msg)
        elif text.startswith("`tell @"):
            rest = text[7:]
            parts = rest.split(" ", 1)
            target = parts[0]
            msg = parts[1].rstrip("`") if len(parts) > 1 else ""
            return CommandResult(handled=True, forward_to=target, forward_text=msg)
        return CommandResult(handled=False)


class FakeAgentRuntimeHandler:
    """Mock AgentRuntimeHandler."""
    def __init__(self, special_agents=None):
        self._agents = special_agents or {}
        self.sent = []

    def get_special_agents(self):
        return self._agents

    def send_to_special_agent(self, sk, text):
        self.sent.append((sk, text))


class FakeGateway:
    def __init__(self, connected=True):
        self._connected = connected
        self.sent = []

    def is_connected(self):
        return self._connected

    def send_message(self, sk, text):
        self.sent.append((sk, text))
```

### Test Cases

| # | Test Method | Description | Assertions |
|---|-------------|-------------|------------|
| 1 | `test_no_commands_no_action` | Response with no backtick commands | No calls to process_input |
| 2 | `test_ask_command_routes` | Response contains `` `ask @Debugger question` `` | process_input called, send_to_special_agent called with correct args |
| 3 | `test_ask_records_pending` | After ask, pending_asks records target→source | `_pending_asks["special:debugger"] == "special:coder"` |
| 4 | `test_relay_delivers_response` | Target agent responds, pending ask exists | Response relayed to source with `[Debugger responded]:` prefix |
| 5 | `test_relay_clears_pending` | After relay, pending ask is removed | target_sk not in `_pending_asks` |
| 6 | `test_multi_hop_relay` | Coder→Debugger→Qaster chain | Debugger gets Qaster's answer; Coder gets Debugger's answer |
| 7 | `test_tell_command_routes` | Response contains `` `tell @Debugger info` `` | send_to_special_agent called (tell does not set pending ask) |
| 8 | `test_non_command_backtick_ignored` | Response contains `` `print("hello")` `` | process_input NOT called |
| 9 | `test_fenced_code_block_ignored` | Response contains fenced code block with `` `ask @Foo` `` inside | No routing triggered for the fenced content |
| 10 | `test_command_outside_fence_detected` | Fenced block with code + command after fence | Only the post-fence command is routed |
| 11 | `test_multiple_commands_capped` | Response has 5 `` `ask` `` commands | Only first 3 are processed |
| 12 | `test_chain_depth_limit` | Set chain_depth[sk]=3, then on_agent_response called | Commands dropped, warning logged |
| 13 | `test_chain_depth_incremented` | After routing a command, target depth = source depth + 1 | `_chain_depth[target] == source_depth + 1` |
| 14 | `test_chain_depth_cleared_on_response` | After response completes, source depth cleared | source sk not in `_chain_depth` |
| 15 | `test_relay_clears_source_depth` | Relay delivered to source, source depth was set | Source chain_depth cleared before relay sent |
| 16 | `test_gateway_agent_routing` | Target is gateway agent (not in special_agents) | gw.send_message called with correct args |
| 17 | `test_gateway_agent_relay` | Gateway agent responds to pending ask | Response relayed back via send_to_special_agent |
| 18 | `test_no_command_handler_set` | CommandHandler is None | No crash, silent return |
| 19 | `test_no_gateway_connected` | Gateway disconnected, target is gateway agent | Send skipped, no crash |
| 20 | `test_empty_text` | text="" or text=None | No action, no crash |
| 21 | `test_implicit_at_ask` | Response contains `` `@Debugger question` `` (no "ask" keyword) | Routed as ask command |
| 22 | `test_unknown_command_ignored` | Response contains `` `foobar @Agent text` `` | Not routed (unknown command) |
| 23 | `test_relay_message_format` | Check relay message format | Starts with `[DisplayName responded]:` |
| 24 | `test_no_pending_ask_no_relay` | Agent responds with no pending ask | No relay sent, just command scan |

### Example Test Implementations

```python
def test_ask_records_pending():
    """Ask command records pending ask for relay."""
    handler = AgentCommandHandler()
    fake_cmd = FakeCommandHandler()
    fake_rt = FakeAgentRuntimeHandler(special_agents={"special:debugger": "Debugger"})
    handler.set_command_handler(fake_cmd)
    handler.set_agent_runtime_handler(fake_rt)

    handler.on_agent_response(
        "special:coder",
        "`ask @Debugger should I use X or Y?`",
        "crabwatch"
    )

    assert "special:debugger" in handler._pending_asks
    assert handler._pending_asks["special:debugger"] == "special:coder"


def test_tell_does_not_record_pending():
    """Tell command does NOT record pending ask — it's one-way."""
    handler = AgentCommandHandler()
    fake_cmd = FakeCommandHandler()
    fake_rt = FakeAgentRuntimeHandler(special_agents={"special:debugger": "Debugger"})
    handler.set_command_handler(fake_cmd)
    handler.set_agent_runtime_handler(fake_rt)

    handler.on_agent_response(
        "special:coder",
        "`tell @Debugger the feed.json has been cleared`",
        "crabwatch"
    )

    # Message should be sent to Debugger
    assert len(fake_rt.sent) == 1
    # But NO pending ask should be recorded
    assert "special:debugger" not in handler._pending_asks


def test_relay_delivers_response():
    """When Debugger responds and there's a pending ask, relay back to Coder."""
    handler = AgentCommandHandler()
    fake_cmd = FakeCommandHandler()
    fake_rt = FakeAgentRuntimeHandler(special_agents={
        "special:debugger": "Debugger",
        "special:coder": "Coder",
    })
    handler.set_command_handler(fake_cmd)
    handler.set_agent_runtime_handler(fake_rt)

    # Simulate Coder asking Debugger (sets up pending ask)
    handler._pending_asks["special:debugger"] = "special:coder"

    # Debugger responds
    handler.on_agent_response(
        "special:debugger",
        "Use the observer pattern. It integrates natively with watchdog.",
        "crabwatch"
    )

    # Relay should have been sent to Coder
    assert len(fake_rt.sent) == 1
    target_sk, relay_text = fake_rt.sent[0]
    assert target_sk == "special:coder"
    assert relay_text.startswith("[Debugger responded]:")
    assert "observer pattern" in relay_text

    # Pending ask should be cleared
    assert "special:debugger" not in handler._pending_asks


def test_multi_hop_relay():
    """Coder→Debugger→Qaster: relays chain correctly."""
    handler = AgentCommandHandler()
    fake_cmd = FakeCommandHandler()
    fake_rt = FakeAgentRuntimeHandler(special_agents={
        "special:debugger": "Debugger",
        "special:coder": "Coder",
    })
    fake_gw = FakeGateway()
    handler.set_command_handler(fake_cmd)
    handler.set_agent_runtime_handler(fake_rt)
    handler.set_gateway_client(fake_gw)

    # Step 1: Coder asks Debugger
    handler.on_agent_response(
        "special:coder",
        "`ask @Debugger should I use X?`",
        "crabwatch"
    )
    assert handler._pending_asks["special:debugger"] == "special:coder"
    assert len(fake_rt.sent) == 1  # sent to Debugger

    # Step 2: Debugger responds and asks Qaster
    handler.on_agent_response(
        "special:debugger",
        "X is good locally. But `ask @Qaster is X compatible with the API?`",
        "crabwatch"
    )
    # Relay to Coder: "[Debugger responded]: X is good locally..."
    assert any(sk == "special:coder" for sk, _ in fake_rt.sent)
    # New command to Qaster via gateway
    assert len(fake_gw.sent) == 1
    assert handler._pending_asks.get("agent:qaster:telegram:direct:7478874934") == "special:debugger"


def test_no_pending_ask_no_relay():
    """Agent responds with no pending ask — no relay, just command scan."""
    handler = AgentCommandHandler()
    fake_cmd = FakeCommandHandler()
    fake_rt = FakeAgentRuntimeHandler(special_agents={"special:debugger": "Debugger"})
    handler.set_command_handler(fake_cmd)
    handler.set_agent_runtime_handler(fake_rt)

    handler.on_agent_response(
        "special:coder",
        "No commands here, just a regular response.",
        "crabwatch"
    )

    # No relay, no routing
    assert len(fake_rt.sent) == 0
    assert len(handler._pending_asks) == 0
```

---

## 8. Files Changed Summary

| File | Action | Size of Change |
|------|--------|---------------|
| `ui/handlers/agent_command_handler.py` | **CREATE** | ~230 lines — new handler with relay |
| `tests/test_agent_command_handler.py` | **CREATE** | ~350 lines — 24 test cases |
| `ui/handlers/chat_handler.py` | EDIT | +8 lines — init field, setter, callback call |
| `ui/handlers/agent_runtime_handler.py` | EDIT | +8 lines — init field, setter, callback call |
| `ui/handlers/command_handler.py` | EDIT | +5 lines — `get_command_names()` method |
| `ui/window.py` | EDIT | +12 lines — create + wire handler |
| `docs/ARCHITECTURE.md` | EDIT | Add §3 module section, update §4.11, update §12 inventory |

**Total:** ~580 new lines, ~33 edit lines across 4 existing files.

---

## 9. ARCHITECTURE.md Updates

### §3 — New Module Section

Add after §3.21d (CollabHandler):

```markdown
### 3.21e `ui/handlers/agent_command_handler.py` — Agent Response Command Parser + Relay (Phase 6.2)

**Responsibility:** Scans agent response text for backtick commands after rendering,
parses them via `CommandHandler.process_input()`, routes to target agents, and
relays responses back to the asking agent.

**Public API:**
\`\`\`python
class AgentCommandHandler:
    # Setters (wired by window.py)
    def set_command_handler(handler)
    def set_agent_runtime_handler(handler)
    def set_gateway_client(gw)
    def set_agent_manager(mgr)
    def set_agent_routing(routing_table)
    def set_project_handler(handler)
    def set_awareness_sent(awareness_set)

    # Core
    def on_agent_response(session_key, text, project_name)
\`\`\`

**Key design:**
- Called from both `ChatHandler._handle_final_response()` and
  `AgentRuntimeHandler._do_response_complete()` via injected callback.
- **Relay:** When Agent A asks Agent B (`ask @B`), records _pending_asks[B] = A.
  When B responds, relays B's answer back to A as `[B responded]: text`.
- **Open-ended relay:** Chains continue as long as agents keep issuing commands,
  bounded by `_MAX_CHAIN_DEPTH` (default 3, configurable).
- Per-response command limit: 3 commands per agent response.
- Strips fenced code blocks before regex matching to avoid false positives.
- Shares `_awareness_sent` set with ChatHandler for awareness prefix tracking.
```

**Note:** Existing §3.21e (SessionHandler) and following sections shift down by one letter.

### §4.11 — Update Architecture Rule

Replace the current rule:

> Agents that need another agent's input include a backtick command in their response text. The backtick command is parsed by CommandHandler like any other human input — no special casing, no detection, no loops.

With:

> Agents that need another agent's input include a backtick command in their response text. `AgentCommandHandler` scans agent responses after rendering and routes backtick commands through `CommandHandler.process_input()`. When Agent A asks Agent B, the response is relayed back to A as a context message (`[B responded]: text`). The relay is open-ended — chains continue as long as agents issue commands, bounded by `_MAX_CHAIN_DEPTH` (default 3, configurable). Per-response limit: 3 commands. The original response text is preserved in the chat bubble — commands are extracted, not stripped.

### §12 — File Inventory

Add to `ui/handlers/` section:
```
│   │   ├── agent_command_handler.py  # ~230 lines — agent response command parser + relay (Phase 6.2)
```

Add to `tests/` section:
```
    ├── test_agent_command_handler.py  # ~350 lines — agent response command parsing + relay tests (Phase 6.2)
```

---

## 10. What This Does NOT Do

- **No automatic relay threads** — command parsing and relay happen inline during the response callback, no persistent threads
- **No echo bubbles** — agent-initiated commands don't show "→ @Agent: ..." bubbles (the command is already visible in the agent's response)
- **No relay for `tell` commands** — `tell` is one-way information sharing. `_route_command()` checks `_last_command_name` and only records `_pending_asks` for response-expecting commands (`ask`, `delegate`). `tell` sends the message but does not set up a relay.
- **No relay deduplication** — if an agent is asked the same question by two different agents, both pending asks are tracked independently. Only the most recent ask is relayed (dict key = target, value = source — last writer wins).

This is intentionally simpler than the old CollabManager system (Phase 6.0). It enables agent-to-agent consultation with open-ended relay, bounded by a configurable depth limit, without the complexity that caused infinite relay loops.
