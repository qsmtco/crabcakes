# Proposal: Agent Output Command Hook

**Author:** Lieutenant Qrusher
**Date:** 2026-05-12
**Status:** ✅ SHIPPED — implemented as `AgentCommandHandler.on_agent_response()` in `ui/handlers/agent_command_handler.py` (25K). See `docs/proposals/AGENT_COMMAND_HOOK_PROPOSAL.md` body for details.
**Tracking issue:** #ACMH-1

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` Shipped as part of Phase 6.2 (agent-initiated A2A with relay). Implemented in `ui/handlers/agent_command_handler.py` (25K file, dated 2026-06-10). The proposed "agent response command hook" is now the `AgentCommandHandler.on_agent_response()` callback, which scans agent response text for backtick commands (e.g. `` `ask @QTR ...` ``) and routes them through `CommandHandler.process_input()`. The relay mechanism (asking agent never sees the answer in its own bubble) is implemented via the `pending-ask` tracking mentioned in `ui/window.py:496`. See `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md` for the quoted-payload format spec.

---

## 1. Problem Statement

CrabCakes already has a fully functional backtick command pipeline for human input:

```
Human types `ask @Coder is this edge case covered?`
  → ChatHandler.on_send() → CommandHandler.process_input() → CollabHandler.cmd_ask()
  → CommandResult(forward_to=..., forward_text=...) → ChatHandler routes via gateway
```

When a **special agent** (Coder, Debugger) emits a backtick command in its response text, nothing happens. The command is rendered as a bubble and ignored. The agent's output is a dead end.

**Example failure case:**
```
Coder's response contains:
  "I've considered the main cases, but `ask @Debugger is the null-pointer edge case handled correctly?`"

Expected: CrabCakes parses the backtick command, resolves @Debugger, forwards the question
Actual: Rendered as plain text bubble. Coder gets no answer. Loop broken.
```

The new system is a stripped-down version of the old one — it only works when a human types the command. The agent-to-agent consultation feature is incomplete.

---

## 2. Design Goals

1. **Zero new mechanisms** — reuse the existing `CommandHandler.process_input()` pipeline exactly as-is. The same parsing, resolution, and routing logic must apply to agent output as to human input.

2. **Minimal interception point** — insert the hook at the natural moments in the response pipeline where text has been finalized but not yet persisted/displayed.

3. **Two distinct pipelines, one hook** — agent responses arrive through two separate paths:
   - **Gateway agents** → `ChatHandler._handle_final_response()` → final text ready
   - **Special agents** (Coder/Debugger) → `AgentRuntimeHandler` callbacks → final text ready

   Both paths must be intercepted with the same command-parsing hook.

4. **No loops** — an agent's command should be forwarded, not fed back to the originating agent. The forward is sent to the target, not echoed back.

5. **Isolated from display** — the hook runs before the bubble is appended. If a command is found, the hook's echo (the "→ @Agent: question" bubble) is what the user sees — not the raw command text.

---

## 3. Architecture

### 3.1 Where the Hook Goes

Two insertion points, same hook function:

**Pipeline A — Gateway agents** (`ui/handlers/chat_handler.py`):
```
_handle_final_response(tab, session_key, final_text)
  → strip backtick commands from final_text → cleaned_text + command_list
  → if commands found:
      render hook_echo bubble (cleaned text with command stripped)
      → for each command: process via CommandHandler.process_input()
      → route results
  → else:
      → render normal bubble (final_text)
```

**Pipeline B — Special agents** (`ui/handlers/agent_runtime_handler.py`):
```
on_response_complete callback (already receives full response text)
  → strip backtick commands → cleaned_text + command_list
  → if commands found:
      render hook_echo bubble
      → for each command: process via CommandHandler.process_input()
      → route results
  → else:
      → render normal bubble
```

### 3.2 New Module: `utils/command_stripper.py`

A pure utility module (no GTK, no network) that extracts backtick commands from text.

**Public API:**
```python
@dataclass ExtractedCommand:
    command_text: str     # full backtick string including backticks, e.g. "`ask @Coder — is this ok?`"
    command_body: str     # text between backticks, e.g. "ask @Coder — is this ok?"
    start_index: int     # byte offset in original text where backtick opens
    end_index: int       # byte offset where closing backtick closes

def extract_commands(text: str) -> tuple[str, list[ExtractedCommand]]:
    """
    Scan text for backtick-delimited commands.

    Returns:
        (cleaned_text, commands)
        cleaned_text: original text with command spans replaced by ""
                   (preserves surrounding whitespace/structure)
        commands: list of ExtractedCommand in the order they appear

    Algorithm:
      - Scan for opening backtick (`)
      - Find matching closing backtick (first unescaped `)
      - Extract content between
      - If content looks like a command (starts with known command word
        OR starts with @), include it
      - Otherwise skip (treat as inline code, not a command)
      - Skip `...` (triple backtick = code block delimiter)
    """
```

**Decision rule for "looks like a command":**
A backtick-delimited span is treated as a command (not inline code) if:
- The first token (split on whitespace) matches a registered command name (`ask`, `delegate`, `stop`, `tell`, `task`, `done`, `start`, `blocked`, `cancel`, `tasks`, `assign`, `priority`, `help`, `session`, `review`, `check`, `accept`, `reject`, `branch`)
- OR the first character after the backtick is `@`

This prevents inline code like `` `my_variable` `` from being misidentified as a command.

**Cleaned text construction:**
- Replace the command span (from `start_index` to `end_index`) with empty string
- Trim any resulting double-spaces
- If the command was the entire text, return empty string

### 3.3 Hook Function: `process_agent_commands()`

Lives in a new file `ui/handlers/agent_command_hook.py`.

```python
class AgentCommandHook:
    """
    Parses backtick commands from agent output and routes them through
    the CommandHandler pipeline, just as human input is routed.

    Integration points:
      - ChatHandler._handle_final_response() — gateway agent responses
      - AgentRuntimeHandler.on_response_complete — special agent responses

    This is NOT a handler per se — it does not own state or GTK widgets.
    It is a pure routing function that orchestrates CommandHandler.

    Thread safety: All GTK calls dispatched via GLib.idle_add().
    """

    def __init__(
        self,
        command_handler: CommandHandler,        # shared CommandHandler instance
        agent_runtime_handler,                 # AgentRuntimeHandler or None
        chat_render_handler,                   # ChatRenderHandler for bubble rendering
        main_content,                         # MainContent for scroll/tab ops
        GLib_module=None,                      # gi.repository.GLib or None
    ):
        self._cmd = command_handler
        self._agent_runtime = agent_runtime_handler
        self._render = chat_render_handler
        self._mc = main_content
        self._GLib = GLib_module

    def process_response(
        self,
        agent_name: str,
        text: str,
        session_key: str,
        tab_key: str,
    ) -> str:
        """
        Entry point for both pipelines.

        Scans text for backtick commands. If found:
          - Renders cleaned text (commands stripped) as bubble
          - Processes each command via CommandHandler.process_input()
          - Routes results (forward_to / broadcast / response_text)

        If no commands found:
          - Returns text unchanged (caller renders normally)

        Returns:
          The cleaned text (commands stripped) if commands were found,
          or the original text if no commands were found.
          The return value tells the caller whether to render (and with what)
          or skip rendering (commands already rendered).
        """
```

**Internal routing logic (mirrors ChatHandler.on_send() command handling):**

```python
def _route_command_result(self, result, session_key, tab_key, cleaned_text):
    """
    Route a CommandResult from process_input() to its destination.

    Three cases (same as ChatHandler.on_send()):
      1. forward_to + forward_text → echo + route to target
      2. broadcast_targets + forward_text → echo + fan-out to all targets
      3. response_text → echo the response text as a bubble
         (CommandHandler already dispatched any display_card callbacks)

    The "→ @Agent: question" echo bubble uses the cleaned_text as content
    (commands stripped), so the raw backtick text does not appear twice.

    Thread safety: all GTK via GLib.idle_add().
    """
```

### 3.4 Pipeline A — Gateway Agents

**File:** `ui/handlers/chat_handler.py`
**Method:** `_handle_final_response()`

Current code (simplified):
```python
def _handle_final_response(self, tab, session_key, final_text):
    ...
    if self._chat_render_handler.is_streaming(session_key):
        self._chat_render_handler.end_streaming(session_key)
    else:
        bubble = self._chat_render_handler.render_sync(
            "Agent", final_text, session_key,
            on_forward_click=self._on_forward_message, tab_key=tab)
        if bubble is not None and chat_box is not None:
            chat_box.append(bubble)
            self._mc.scroll_chat_to_bottom()
```

New code:
```python
def _handle_final_response(self, tab, session_key, final_text):
    ...
    # ── Agent Command Hook ──────────────────────────────────────────────────
    if self._agent_command_hook is not None:
        cleaned = self._agent_command_hook.process_response(
            agent_name="Agent",   # actual agent name available from payload if needed
            text=final_text,
            session_key=session_key,
            tab_key=tab,
        )
        if cleaned:  # commands were found and rendered; skip normal render
            return
    # ── End Agent Command Hook ───────────────────────────────────────────────

    if self._chat_render_handler.is_streaming(session_key):
        self._chat_render_handler.end_streaming(session_key)
    else:
        bubble = self._chat_render_handler.render_sync(
            "Agent", final_text, session_key,
            on_forward_click=self._on_forward_message, tab_key=tab)
        ...
```

**Injection in `_build()` / setter:**
```python
def set_agent_command_hook(self, hook) -> None:
    """Inject AgentCommandHook. Called by window.py._build()."""
    self._agent_command_hook = hook
```

### 3.5 Pipeline B — Special Agents

**File:** `ui/handlers/agent_runtime_handler.py`
**Callback:** `on_response_complete(session_key, response_text, ...)`

Current signature (from architecture §3.21m):
```python
def __init__(self, ..., on_response_complete, ...)
```

The `on_response_complete` callback fires when a special agent finishes a response. This is the natural interception point.

**Wire the hook:**
```python
# In AgentRuntimeHandler:
self._on_response_complete = on_response_complete

def _fire_response_complete(self, session_key, response_text, ...):
    # Intercept with command hook before calling original callback
    if self._agent_command_hook is not None:
        cleaned = self._agent_command_hook.process_response(
            agent_name=session_key,  # or resolve display name
            text=response_text,
            session_key=session_key,
            tab_key=session_key,  # special agents use their own tab key
        )
        if cleaned:
            return  # hook rendered; skip original callback
    self._on_response_complete(session_key, response_text, ...)
```

**Injection:**
```python
def set_agent_command_hook(self, hook) -> None:
    """Inject AgentCommandHook. Called by window.py._build()."""
    self._agent_command_hook = hook
```

### 3.6 Wiring in `window.py`

```python
# In window._build():
from ui.handlers.agent_command_hook import AgentCommandHook

agent_command_hook = AgentCommandHook(
    command_handler=command_handler,           # already wired
    agent_runtime_handler=agent_runtime_handler,  # already wired
    chat_render_handler=chat_render_handler,  # already wired
    main_content=main_content,                # already wired
    GLib_module=GLib,
)

# Wire into ChatHandler
chat_handler.set_agent_command_hook(agent_command_hook)

# Wire into AgentRuntimeHandler
agent_runtime_handler.set_agent_command_hook(agent_command_hook)
```

---

## 4. Data Flow Diagrams

### 4.1 Full Data Flow — Gateway Agent with Command

```
Gateway → window._on_ws_event()
  → ChatHandler.on_chat_event("chat", final, payload)
    → _handle_final_response(tab, session_key, final_text)
      → AgentCommandHook.process_response(agent_name, text, session_key, tab)
        → extract_commands(text)
          → returns (cleaned_text, [ExtractedCommand(...)])
        → render cleaned_text bubble via ChatRenderHandler
        → for each ExtractedCommand:
            → CommandHandler.process_input(session_key, cmd.command_body)
              → CollabHandler.cmd_ask() → CommandResult(forward_to=..., forward_text=...)
            → route via _route_command_result():
                → echo "→ @Agent: question" bubble
                → is_special → AgentRuntimeHandler.send_to_special_agent()
                → else → gw.send_message(target, question_text)
      → return cleaned (skip normal render)

Coder responds to question → cycle repeats
```

### 4.2 Full Data Flow — Special Agent with Command

```
AgentRuntime.on_response_complete(session_key, response_text)
  → AgentRuntimeHandler._fire_response_complete(...)
    → AgentCommandHook.process_response(agent_name, text, session_key, tab)
      → extract_commands(text)
      → same pipeline as above
    → if handled: return (skip normal callback)
    → else: call original on_response_complete → render normally
```

### 4.3 Text Cleaning — Before/After

**Original agent output:**
```
I've handled the main authentication flow. One thing I want to verify:
`ask @Debugger — does the null-pointer check in auth.py line 42 cover the
token-refresh race condition?`

Let me know what you find.
```

**After `extract_commands()`:**
```
cleaned_text = "I've handled the main authentication flow. One thing I want to verify:\n\nLet me know what you find."

commands = [ExtractedCommand(
    command_text="`ask @Debugger — does the null-pointer check...`",
    command_body="ask @Debugger — does the null-pointer check in auth.py line 42 cover the token-refresh race condition?",
    start_index=...,
    end_index=...,
)]
```

**Rendered to user:**
```
[Agent bubble]: "I've handled the main authentication flow. One thing I want to verify:

Let me know what you find."
[You bubble]: "→ @Debugger: does the null-pointer check in auth.py line 42 cover the token-refresh race condition?"
```

---

## 5. File Inventory

### 5.1 New Files

| File | Lines | Purpose |
|------|-------|---------|
| `utils/command_stripper.py` | ~120 | Pure function: `extract_commands()` |
| `ui/handlers/agent_command_hook.py` | ~280 | `AgentCommandHook` class + `_route_command_result()` |
| `tests/test_command_stripper.py` | ~180 | Unit tests: basic, edge cases, multiple commands, no commands |
| `tests/test_agent_command_hook.py` | ~220 | Integration tests: gateway pipeline, special agent pipeline, routing |

### 5.2 Modified Files

| File | Change |
|------|--------|
| `ui/handlers/chat_handler.py` | Add `_agent_command_hook` setter + intercept in `_handle_final_response()` |
| `ui/handlers/agent_runtime_handler.py` | Add `_agent_command_hook` setter + intercept in `_fire_response_complete()` |
| `ui/window.py` | Create `AgentCommandHook` instance; wire to both handlers |
| `docs/ARCHITECTURE.md` | Add §3.21o (AgentCommandHook), update §4.12 (agent command routing), update §11 (file inventory) |
| `docs/PROJECT_STATUS.md` | Add Phase 8 entry |

### 5.3 Line Count Delta

| | Before | After |
|--|--------|-------|
| `chat_handler.py` | 639 | ~665 (+26) |
| `agent_runtime_handler.py` | ~400 | ~430 (+30) |
| `window.py` | 926 | ~945 (+19) |

---

## 6. Detailed Implementation

### 6.1 `utils/command_stripper.py`

```python
# ui/handlers/agent_command_hook.py
# Agent command hook — parses backtick commands from agent output, routes via CommandHandler.
#
# Manifest:
#   reads:   CommandHandler (shared), models.command
#   writes:  nothing
#   network: via CommandHandler → gateway OR AgentRuntimeHandler
#   GTK:     via ChatRenderHandler + MainContent (GLib-dispatched)
#
# Owns:
#   - Command extraction from agent response text
#   - Routing decisions (forward_to, broadcast, display_text)
#   - Echo bubble rendering for forwarded commands
#
# Does NOT own:
#   - CommandHandler (shared, injected)
#   - AgentRuntimeHandler (shared, injected)
#   - GTK widget lifecycle
#
# Thread safety: All GTK operations dispatched via GLib.idle_add().

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ui.handlers.command_handler import CommandHandler
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    from ui.handlers.chat_render_handler import ChatRenderHandler
    from ui.views.main_content import MainContent

import re

# Known command names — must stay in sync with CommandRegistry registrations
# in window.py (CollabHandler, TaskHandler, etc.)
KNOWN_COMMANDS = frozenset({
    "ask", "delegate", "stop", "tell",
    "task", "done", "start", "blocked", "cancel", "tasks", "assign", "priority",
    "help", "session",
    "review", "check", "accept", "reject", "branch",
})


@dataclass
class ExtractedCommand:
    """A backtick command found in agent output."""
    command_text: str      # e.g. "`ask @Coder — is this ok?`"
    command_body: str      # e.g. "ask @Coder — is this ok?"
    start_index: int
    end_index: int


def extract_commands(text: str) -> tuple[str, list[ExtractedCommand]]:
    """
    Scan text for backtick-delimited commands.

    A backtick span is treated as a command (not inline code) if:
      - The first token matches a known command name, OR
      - The first non-whitespace character is '@'

    Args:
        text: Raw agent response text.

    Returns:
        (cleaned_text, commands)
        cleaned_text: text with command spans replaced by "", trimmed.
        commands: list of ExtractedCommand in order of appearance.
    """
    if not text:
        return "", []

    commands: list[ExtractedCommand] = []
    # We'll build the cleaned text by tracking which ranges to delete
    # Use a list of (start, end) ranges to remove
    remove_ranges: list[tuple[int, int]] = []

    i = 0
    while i < len(text):
        if text[i] != '`':
            i += 1
            continue

        # Check for triple backtick (code block delimiter) — skip
        if i + 2 < len(text) and text[i:i+3] == '```':
            i += 3
            continue

        # Opening backtick found at i
        start = i
        i += 1  # move past opening backtick

        # Find closing backtick (first unescaped backtick)
        end = -1
        while i < len(text):
            if text[i] == '\\' and i + 1 < len(text) and text[i+1] == '`':
                i += 2  # skip escaped backtick
                continue
            if text[i] == '`':
                end = i
                break
            i += 1

        if end == -1:
            # No closing backtick — not a valid command span
            i += 1
            continue

        # Extract content between backticks
        body = text[start + 1:end]
        full_text = text[start:end + 1]

        # Decide if this is a command
        is_command = False
        first_token = body.split()[0].lower() if body.split() else ""

        if first_token in KNOWN_COMMANDS:
            is_command = True
        elif body.lstrip().startswith('@'):
            is_command = True

        if is_command:
            remove_ranges.append((start, end + 1))
            commands.append(ExtractedCommand(
                command_text=full_text,
                command_body=body,
                start_index=start,
                end_index=end + 1,
            ))

        i = end + 1

    # Build cleaned text by removing command ranges
    if not remove_ranges:
        return text, []

    # Sort ranges and merge overlapping (shouldn't happen but be safe)
    remove_ranges.sort()
    cleaned_parts: list[str] = []
    last_end = 0
    for start, end in remove_ranges:
        cleaned_parts.append(text[last_end:start])
        last_end = end
    cleaned_parts.append(text[last_end:])

    cleaned = "".join(cleaned_parts)
    # Normalize whitespace: replace 3+ newlines with 2, trim
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned, commands


class AgentCommandHook:
    """
    Parses backtick commands from agent output and routes them through
    the CommandHandler pipeline, just as human input is routed.

    Two integration points:
      - ChatHandler._handle_final_response() — gateway agent responses
      - AgentRuntimeHandler response callbacks — special agent responses

    The hook is stateless — it holds references to shared components
    but does not own any persistent state.
    """

    def __init__(
        self,
        command_handler: "CommandHandler",
        agent_runtime_handler: "AgentRuntimeHandler | None",
        chat_render_handler: "ChatRenderHandler",
        main_content: "MainContent",
        GLib_module=None,
    ):
        self._cmd = command_handler
        self._agent_runtime = agent_runtime_handler
        self._render = chat_render_handler
        self._mc = main_content
        self._GLib = GLib_module

    def process_response(
        self,
        agent_name: str,
        text: str,
        session_key: str,
        tab_key: str,
    ) -> str | None:
        """
        Entry point for both pipelines.

        Args:
            agent_name: Display name of the responding agent (e.g. "Coder").
            text: The agent's full response text.
            session_key: Session key of the responding agent.
            tab_key: The tab key for rendering (may differ from session_key
                     for project tabs).

        Returns:
            cleaned_text if commands were found (caller must NOT render normally),
            None if no commands were found (caller renders text as-is).

        Thread safety: All GTK via GLib.idle_add().
        """
        if not text:
            return None

        cleaned_text, commands = extract_commands(text)

        if not commands:
            return None  # no commands — let caller render normally

        # ── Render cleaned text bubble ───────────────────────────────────────
        def _render_cleaned():
            chat_box = self._mc.get_chat_box_for_session(tab_key)
            if chat_box is None:
                return
            bubble = self._render.render_sync(
                "Agent",
                cleaned_text,
                session_key,
                on_forward_click=None,
                tab_key=tab_key,
            )
            if bubble is not None:
                chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

        self._dispatch(_render_cleaned)

        # ── Process each command ─────────────────────────────────────────────
        for extracted in commands:
            cmd_body = extracted.command_body
            result = self._cmd.process_input(session_key, cmd_body)
            if result.handled:
                self._route_command_result(result, session_key, tab_key)
            # If not handled (unknown command), silently skip — don't route

        return cleaned_text  # signal to caller: already rendered, skip normal render

    def _route_command_result(
        self,
        result: "CommandResult",
        session_key: str,
        tab_key: str,
    ) -> None:
        """
        Route a CommandResult to its destination, rendering echo bubbles.

        Mirrors ChatHandler.on_send() command handling logic.

        Three cases:
          1. forward_to + forward_text → echo + route to single target
          2. broadcast_targets + forward_text → echo + fan-out to all targets
          3. response_text only → echo the response text as a system bubble

        Thread safety: all GTK via GLib.idle_add().
        """
        from models.command import CommandResult

        def _do():
            chat_box = self._mc.get_chat_box_for_session(tab_key)
            if chat_box is None:
                return

            if result.forward_to and result.forward_text:
                # Forward to single agent
                target_name = result.forward_to.split("/")[-1]
                echo_text = f"→ @{target_name}: {result.forward_text}"
                bubble = self._render.render_sync(
                    "You", echo_text, session_key,
                    on_forward_click=None, tab_key=tab_key,
                )
                if bubble is not None:
                    chat_box.append(bubble)
                    self._mc.scroll_chat_to_bottom()

                # Route to target
                is_special = (
                    self._agent_runtime is not None
                    and result.forward_to in self._agent_runtime.get_special_agents()
                )
                if is_special:
                    self._agent_runtime.send_to_special_agent(result.forward_to, result.forward_text)
                else:
                    # Gateway send — go through the gateway client
                    # We access it via ChatHandler's gateway reference
                    # The hook doesn't hold _gw directly; route via _cmd which holds it
                    # Actually: CommandHandler holds _gw; we need to expose send_message
                    # Best approach: have ChatHandler own the forward route and expose
                    # a callback. For now, use a simpler approach:
                    pass  # see note below

            elif result.broadcast_targets and result.forward_text:
                echo_text = f"→ @all: {result.forward_text}"
                bubble = self._render.render_sync(
                    "You", echo_text, session_key,
                    on_forward_click=None, tab_key=tab_key,
                )
                if bubble is not None:
                    chat_box.append(bubble)
                    self._mc.scroll_chat_to_bottom()

                for target in result.broadcast_targets:
                    is_special = (
                        self._agent_runtime is not None
                        and target in self._agent_runtime.get_special_agents()
                    )
                    if is_special:
                        self._agent_runtime.send_to_special_agent(target, result.forward_text)

            elif result.response_text:
                # Display command response
                bubble = self._render.render_sync(
                    "System", result.response_text, session_key,
                    on_forward_click=None, tab_key=tab_key,
                )
                if bubble is not None:
                    chat_box.append(bubble)
                    self._mc.scroll_chat_to_bottom()

        self._dispatch(_do)

    def _dispatch(self, fn: Callable) -> None:
        """Call fn on the GTK main thread."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
```

**Note on `_route_command_result` gateway forwarding:**

The hook needs to send messages to agents via the gateway. Options:

1. **Pass gateway_client to hook** — simplest, just add it as a constructor dependency
2. **Pass a send callback** — `on_forward_to_agent(session_key, text)` injected by window.py
3. **Have ChatHandler own the routing** — hook returns a structured result; ChatHandler does the actual send

Option 2 is cleanest and matches the existing callback pattern. The hook receives `on_forward_to_agent` at construction:

```python
def __init__(self, ..., on_forward_to_agent=None, ...):
    self._on_forward_to_agent = on_forward_to_agent
```

Then in `_route_command_result`:
```python
if self._on_forward_to_agent is not None:
    self._on_forward_to_agent(result.forward_to, result.forward_text)
```

Window.py wires this as:
```python
chat_handler.on_forward_to_agent(result.forward_to, result.forward_text)
# which ultimately calls: gw.send_message(result.forward_to, result.forward_text)
```

However, the cleanest approach is to **inject a `gateway_client` reference directly** since the hook already needs to know about `AgentRuntimeHandler` (for special agent routing). A single `_gw` reference covers gateway agents; `AgentRuntimeHandler` covers special agents.

---

## 7. Edge Cases

### 7.1 Multiple Commands in One Response
If an agent emits multiple backtick commands in one response, all are processed in order:
```
`ask @Debugger — check X`
`delegate @Coder — fix Y`
```
Each generates its own echo bubble and routing.

### 7.2 Nested Backticks
Inline code like "use `my_list.append()`" won't be treated as a command (doesn't start with known command or @). The `KNOWN_COMMANDS` whitelist ensures only real commands are extracted.

### 7.3 Triple Backticks
Code blocks delimited by ``` are skipped — triple backticks never trigger command extraction.

### 7.4 Agent Asks About Its Own Question
If `@Coder` asks `@Coder` something (self-referential), it still gets forwarded. No loop guard needed because:
- The forward goes to the **target's session** (not back to the originator)
- The command is stripped from the response before routing

### 7.5 Response with Only a Command
If the agent's entire response is just `` `ask @Debugger is this ok?` ``:
- Cleaned text = "" → empty bubble (or skip bubble entirely)
- Command is processed and routed
- User sees only the "→ @Debugger: is this ok?" echo bubble

### 7.6 Unknown Command in Backtick
If agent writes `` `foo @Bar — thing` `` (unknown command):
- `process_input()` returns `handled=False` (unknown command)
- Hook skips routing silently
- The backtick span is stripped from cleaned_text
- The cleaned text bubble is rendered without the unknown command

### 7.7 Special Agent Forwarding to Gateway Agent
Coder emits `` `ask @Qat is this right?` ``:
- `resolve_mention("Qat")` → gateway session key
- `is_special` = False
- Hook forwards via gateway client

### 7.8 Command After Normal Text
```
I've done the refactor. `ask @Debugger — is the thread safety correct?`
```
- Cleaned text = "I've done the refactor."
- Bubble shows only the narrative text
- Echo bubble shows → @Debugger: is the thread safety correct?

### 7.9 Whitespace Preservation
Commands embedded mid-paragraph:
```
Before `ask @Coder — check` after.
```
Cleaned → "Before  after." (double space, normalized to single)
Cleaned → "Before after."

---

## 8. Acceptance Criteria

### 8.1 Functional Criteria

| # | Criterion | Test |
|---|-----------|------|
| 1 | Agent output containing `` `ask @Agent — question` `` is parsed and routed | `test_agent_command_hook.py::test_gateway_agent_ask_command` |
| 2 | Agent output with no backtick commands renders normally | `test_agent_command_hook.py::test_no_commands_renders_normally` |
| 3 | Multiple commands in one response are each routed | `test_agent_command_hook.py::test_multiple_commands` |
| 4 | Inline code (backtick not a command) is not treated as a command | `test_command_stripper.py::test_inline_code_not_command` |
| 5 | Triple backtick code blocks are not parsed | `test_command_stripper.py::test_code_block_not_command` |
| 6 | Gateway agent command routes via gateway | `test_agent_command_hook.py::test_gateway_forward` |
| 7 | Special agent command routes via AgentRuntimeHandler | `test_agent_command_hook.py::test_special_agent_forward` |
| 8 | Broadcast commands fan out to all project members | `test_agent_command_hook.py::test_broadcast_command` |
| 9 | Special agent's on_response_complete intercept works | `test_agent_command_hook.py::test_special_agent_pipeline` |
| 10 | Unknown backtick command is stripped, not routed | `test_command_stripper.py::test_unknown_command_stripped` |

### 8.2 Non-Functional Criteria

| # | Criterion |
|---|-----------|
| N1 | No new GTK widget classes created |
| N2 | No changes to existing models (`models/`) |
| N3 | Hook is < 300 lines |
| N4 | `command_stripper.py` is < 150 lines, pure function, no imports from `ui/` or `agent/` |
| N5 | All GTK via GLib.idle_add() |
| N6 | ARCHITECTURE.md updated atomically with the code |

---

## 9. Open Questions

1. **Empty bubble handling:** If cleaned text is empty (agent's response was 100% command), should we skip rendering the cleaned text bubble entirely, or render a placeholder?

2. **Command echo attribution:** The echo bubble ("→ @Agent: question") is rendered as "You" role. Should it instead be rendered as "System" to indicate it came from a parsed command rather than user input?

3. **Special agent response intercept point:** The `on_response_complete` callback is the recommended intercept point. If `on_response_complete` doesn't exist or isn't fired in all code paths (e.g., streaming responses), we may need additional intercept points.

4. **Rate limiting:** If a malicious or buggy agent emits a flood of commands, should there be a guard? (Recommended: no — the agent's PM should monitor and intervene.)

---

## 10. Phasing

**Phase 8.1 — Core:** `utils/command_stripper.py` + `ui/handlers/agent_command_hook.py` + Pipeline A (gateway agents only). Special agent pipeline deferred.

**Phase 8.2 — Special Agents:** Pipeline B (AgentRuntimeHandler intercept). Can ship 8.1 first since gateway agents cover the most common use cases.

**Phase 8.3 — Tests:** `tests/test_command_stripper.py` + `tests/test_agent_command_hook.py`

**Phase 8.4 — Documentation:** ARCHITECTURE.md §3.21o, §4.12, file inventory update.

---

*This proposal is aligned with ARCHITECTURE.md §3, §4, and §8. It does not introduce new architectural patterns — it extends existing ones (callback wiring, handler pattern, command registry).*
