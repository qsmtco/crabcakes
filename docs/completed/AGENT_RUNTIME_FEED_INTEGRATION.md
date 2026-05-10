# Agent Runtime — Feed Integration Proposal

> **Status: IMPLEMENTED** — Verified in code as of 2026-05-09
> - `_resolve_chat_box()` resolves special agent → project tab routing
> - Feed card wiring via crabcard extraction + feed_handler integration
> - Enforcement status callback wired

**Last updated:** 2026-05-05
**QTR Review:** Issues fixed and recommendations applied. See "QTR Review Changes" appendix at bottom.
**Depends on:** `docs/ARCHITECTURE.md`, `docs/PROJECT_FEED.md`, `docs/agent-runtime.md`
**Author:** Qaster
**QTR Editor:** QTR — added 7 issue fixes + 5 recommendations (2026-05-05)
**Target files:** `ui/handlers/agent_runtime_handler.py`, `agent/runtime.py`, `ui/window.py`

---

## Problem Statement

The agent runtime (Phase 1.1–1.5) was built before the Project Feed existed. Special agents (Coder, Debugger) can chat via LLM but their tools are non-functional because:

1. **No project context is injected.** `AgentRuntimeHandler.set_project_for_session()` exists but is never called from anywhere. Agent conversations have `project_path=None`, so all file tools fail at the sandbox resolver.
2. **Tool activity is invisible.** `_on_tool_call_start` logs. `_on_tool_call_result` only handles write_file review staging. The user sees nothing — no cards, no indicators, no feedback.
3. **Agent output bypasses crabcard parsing.** Gateway agents have crabcard extraction wired through `ChatRenderHandler`. Special agents skip it entirely.
4. **Streaming produces duplicate bubbles.** `_on_response_complete` calls `end_streaming()` then `render_sync()`, creating a second bubble with the full text alongside the streaming bubble.
5. **Tool definitions are unfiltered.** `get_tool_definitions_for_api()` returns all 7 tools to every agent. Debugger gets `write_file` despite the spec saying it shouldn't.
6. **exec_command approval is broken.** The approval callback in `agent/tools.py` (`_approval_callback`) is never registered by `AgentRuntimeHandler`. The runtime has its own internal bypass that auto-approves. There is no UI for approval.

## What This Proposal Changes

Rewrite `AgentRuntimeHandler` so special agents are project-feed-first:

- Agents **only work within an open project** — `project_path` is injected from the project lifecycle.
- Every tool call **appears as a feed card** in the project feed with results.
- Agent output **goes through crabcard extraction** so special agents can emit crabcards.
- `write_file` and `exec_command` results get **Accept/Reject buttons** on their feed cards.
- Tool definitions are **filtered per agent** using `SpecialAgentDef.tools`.
- Streaming is **finalized in place** — no duplicate bubbles.

## What This Proposal Does NOT Change

| Module | Status | Reason |
|--------|--------|--------|
| `agent/tools.py` | **Unchanged** | Implementations are correct. The problem is upstream (no project_path). |
| `agent/config.py` | **Unchanged** | Config loading works. |
| `agent/special_agents.py` | **Unchanged** | Agent definitions are correct. |
| `agent/context.py` | **Unchanged** | System prompt builder already handles project_path. |
| `models/feed_card.py` | **Unchanged** | `FeedCardData` already supports `agent_action` type. |
| `ui/handlers/chat_render_handler.py` | **Unchanged** | `render_sync()`, `start_streaming()`, `end_streaming()`, `set_on_crabcard_extracted()` already exist. |
| `utils/crabcard_parser.py` | **Unchanged** | `extract_crabcards()` already exists. |
| ARCHITECTURE.md dependency rules | **Fully respected** | No cross-handler imports. All communication via callbacks. |

## What This Proposal CHANGES (minor)

| Module | Change | Reason |
|--------|--------|--------|
| `models/conversation.py` | Add `allowed_tools` field | Tool filtering per agent (Change 4) |
| `ui/handlers/feed_handler.py` | Add `update_card()` method | Tool result cards need to update in place. **Does NOT exist — implement it. Do NOT skip this.** (Change 5) |

---

## Architecture

### Dependency Flow (per ARCHITECTURE.md Section 2)

```
models/           → no imports from ui/, agent/, gateway/
utils/            → imports from models/ only; no ui/, agent/
agent/            → no imports from ui/; may import utils/
ui/views/         → imports from models/, utils/, GTK4; no ui/handlers/
ui/handlers/      → imports from models/, utils/, GTK4 (GLib only); no other handlers
```

**This proposal's dependency flow:**

```
ui/handlers/agent_runtime_handler.py
  → imports: agent.runtime.AgentRuntime, agent.special_agents, agent.config
  → imports: models.feed_card.FeedCardData
  → imports: utils.crabcard_parser.extract_crabcards
  → receives via constructor: feed_handler, chat_render_handler, review_handler
    (callback references wired in window.py, not direct imports)

agent/runtime.py
  → imports: agent.tools (get_tool_definitions_for_api, execute_tool)
  → imports: agent.context (build_system_prompt)
  → no changes to existing import pattern
```

### Layer Rule Compliance

| Rule | How This Proposal Complies |
|------|---------------------------|
| `agent/` must not import from `ui/` | No changes to agent/ that add ui/ imports. `AgentRuntime` callbacks remain plain Python callables dispatched via GLib.idle_add by the handler. |
| `ui/handlers/` must not import other handlers | `AgentRuntimeHandler` receives `feed_handler`, `review_handler` as constructor arguments (callback references wired in `window.py`). No direct imports. |
| `models/` must not import from `ui/`, `agent/`, `gateway/` | The only models/ change is adding a `list[str] | None` field to `Conversation`. No new imports. |
| `utils/` must not import from `ui/`, `agent/` | No changes to utils/. |
| Handler pattern (ARCHITECTURE.md Section 8.6) | One handler per subsystem. Does not import other handlers. Receives dependencies via constructor. Owns its state. All GTK from background threads via GLib.idle_add(). |

### Where Code Lives

```
crabcakes/
├── agent/
│   ├── runtime.py              # MODIFIED — filtered tools, richer callbacks
│   ├── tools.py                # UNCHANGED
│   ├── config.py               # UNCHANGED
│   ├── context.py              # UNCHANGED
│   └── special_agents.py       # UNCHANGED
│
├── ui/
│   ├── handlers/
│   │   ├── agent_runtime_handler.py  # REWRITTEN — feed-first integration
│   │   ├── feed_handler.py           # MINOR — add update_card() if missing
│   │   ├── chat_render_handler.py    # UNCHANGED
│   │   ├── chat_handler.py           # UNCHANGED (keeps existing delegation pattern)
│   │   └── ... (other handlers unchanged)
│   └── window.py                     # MODIFIED — wiring changes
│
├── models/
│   └── conversation.py               # MINOR — add allowed_tools field
│
├── utils/                       # UNCHANGED
└── docs/
    └── AGENT_RUNTIME_FEED_INTEGRATION.md  # NEW — this document
```

---

## Detailed Changes

### Change 1: `ui/handlers/agent_runtime_handler.py` — Full Rewrite

**Current state:** ~265 lines. Creates AgentRuntime instances, routes callbacks to ChatRenderHandler. No feed integration. No project wiring.

**New state:** ~380 lines. Feed-first handler that connects special agents to project lifecycle, feed cards, and review workflow.

#### Constructor

```python
class AgentRuntimeHandler:
    def __init__(
        self,
        *,
        main_content,                    # MainContent — get_chat_box_for_session()
        chat_render_handler,             # ChatRenderHandler — streaming + rendering
        feed_handler,                    # FeedHandler — add_card() for tool/result cards
        review_handler=None,             # ReviewHandler — optional, for accept/reject
        GLib_module=None,                # gi.repository.GLib
    ):
        self._mc = main_content
        self._crh = chat_render_handler
        self._fh = feed_handler           # NEW
        self._review_handler = review_handler
        self._GLib = GLib_module

        # Registered agents: session_key → SpecialAgentDef
        self._agents: dict[str, SpecialAgentDef] = {}
        # Active project: (name, path) or None
        self._active_project: tuple[str, str] | None = None
        # session_key → AgentRuntime
        self._runtimes: dict[str, Any] = {}
        # Pending approval cards: card_id → {session_key, tool_name, args}
        self._pending_approvals: dict[str, dict] = {}
        # Tool call → feed card ID mapping: session_key → card_id
        # Uses session_key as key since the LLM processes one tool at a time per turn.
        # tool_name is stored in the card's metadata for reference.
        # For concurrent tool calls: use tool_call_id from the LLM response as the key.
        self._tool_card_ids: dict[str, str] = {}
```

#### Public API

```python
def add_special_agent(self, agent_def: SpecialAgentDef) -> None:
    """Register a special agent. Stores the full definition for tool filtering."""

def set_active_project(self, project_name: str, project_path: str) -> None:
    """
    Called when a project is opened. Sets project_path on all active conversations.
    This is the critical missing link — without it, tools have no sandbox root.
    """

def clear_active_project(self) -> None:
    """Called when a project is closed. Clears project context from conversations."""

def send_to_special_agent(self, session_key: str, text: str) -> None:
    """Send a user message to a special agent. Requires an active project."""

def approve_exec(self, approval_id: str, approved: bool) -> None:
    """
    PM approves/denies an exec_command. Called when the user clicks
    Approve or Deny on a pending-approval feed card.
    approval_id is the card_id of the approval card.
    Resolves the Event that the tool loop thread is blocked on.
    """

def stop_all(self) -> None:
    """Stop all runtimes. Called on shutdown."""
```

#### Key Method: `set_active_project`

This is the root fix. It's called from `window.py` when a project opens:

```python
def set_active_project(self, project_name: str, project_path: str) -> None:
    self._active_project = (project_name, project_path)
    # Set project_path on all existing conversations
    for session_key, rt in self._runtimes.items():
        conv = rt.get_conversation(session_key)
        if conv is not None and conv.project_path != project_path:
            conv.project_path = project_path
            # Rebuild system prompt with new project context
            agent_def = self._agents.get(session_key)
            if agent_def:
                from agent.context import build_system_prompt
                tool_names = agent_def.tools
                conv.system_prompt = build_system_prompt(
                    agent_def.display_name, project_path, tool_names
                )
```

#### Key Method: `send_to_special_agent`

```python
def send_to_special_agent(self, session_key: str, text: str) -> None:
    agent_def = self._agents.get(session_key)
    if agent_def is None:
        logger.warning("Not a registered special agent: %s", session_key)
        return

    if self._active_project is None:
        # Show error — special agents require an active project
        self._dispatch(self._do_error, session_key,
                       "Open a project first. Special agents work within projects.")
        return

    project_name, project_path = self._active_project
    rt = self._get_runtime(agent_def)

    if rt.get_conversation(session_key) is None:
        rt.create_conversation(
            agent_name=agent_def.display_name,
            session_key=session_key,
            project_path=project_path,
            allowed_tools=agent_def.tools,  # filtered tool set
        )

    rt.send_message(session_key, text)
```

#### Key Method: `_on_tool_call_start` — Feed Card

When an agent starts a tool call, a card appears in the feed:

```python
def _on_tool_call_start(self, session_key: str, tool_name: str, args: dict) -> None:
    self._dispatch(self._do_tool_call_start, session_key, tool_name, args)

def _do_tool_call_start(self, session_key: str, tool_name: str, args: dict) -> None:
    if self._fh is None or self._active_project is None:
        return

    agent_def = self._agents.get(session_key)
    agent_name = agent_def.display_name if agent_def else "Agent"
    project_name, _ = self._active_project

    # Build human-readable description
    if tool_name == "read_file":
        title = f"{agent_name} is reading {args.get('path', '?')}"
    elif tool_name == "write_file":
        title = f"{agent_name} is writing {args.get('path', '?')}"
    elif tool_name == "exec_command":
        title = f"{agent_name} is running: {args.get('command', '?')[:60]}"
    elif tool_name == "list_files":
        title = f"{agent_name} is listing {args.get('path', '.')}"
    elif tool_name == "search_files":
        title = f"{agent_name} is searching for \"{args.get('pattern', '?')}\""
    elif tool_name == "web_search":
        title = f"{agent_name} is searching the web"
    elif tool_name == "web_fetch":
        title = f"{agent_name} is fetching {args.get('url', '?')[:50]}"
    else:
        title = f"{agent_name} is calling {tool_name}"

    card = FeedCardData(
        card_type="agent_action",
        source="agent",
        title=title,
        body="⏳ Running...",  # placeholder — updated when result arrives
        author=agent_name,
        timestamp=datetime.now(timezone.utc),
        project_name=project_name,
        metadata={
            "tool_name": tool_name,
            "tool_args": args,
            "session_key": session_key,
            "status": "running",
        },
    )
    card_id = self._fh.add_card(card)
    # Store card_id so _on_tool_call_result can update it.
    # Key by session_key only — tool_name is in the card's metadata.
    # For concurrent tool calls, use tool_call_id from the LLM response as key.
    self._tool_card_ids[session_key] = card_id


#### Key Method: `_on_tool_call_result` — Update Feed Card

When a tool completes, the card is updated with the result:

```python
def _on_tool_call_result(self, session_key: str, tool_name: str, result: Any) -> None:
    self._dispatch(self._do_tool_call_result, session_key, tool_name, result)

def _do_tool_call_result(self, session_key: str, tool_name: str, result: Any) -> None:
    # Look up by session_key — tool_name is in the stored card's metadata
    card_id = self._tool_card_ids.pop(session_key, None)

    if card_id is None or self._fh is None:
        return

    card = self._fh.get_card(card_id)
    if card is None:
        return

    # The runtime passes tool results differently depending on the flow:
    # - Direct execution: result is a ToolResult from agent/tools.py
    # - Approval flow: result may be a string summary
    if hasattr(result, 'output'):
        output_text = result.output or ""
        error_text = result.error or ""
        success = result.success
        duration = getattr(result, 'duration_ms', 0)
    else:
        output_text = str(result) if result else ""
        error_text = ""
        success = True
        duration = 0

    # Truncate for card display
    display = output_text[:2000] if output_text else ""
    if error_text:
        display = f"❌ {error_text}\n{display}"

    # Update card metadata
    card.body = display
    card.metadata["status"] = "complete" if success else "error"
    card.metadata["duration_ms"] = duration

    # For write_file/exec_command — flag for review if review session is active
    if tool_name in ("write_file", "exec_command") and self._review_handler is not None:
        _, project_path = self._active_project or (None, None)
        if project_path:
            state = self._review_handler.get_state(card.project_name)
            if state and state.is_active():
                card.metadata["needs_review"] = True

    # Change 5 implements FeedHandler.update_card() — it must exist before this is called.
    self._fh.update_card(card_id, card)

#### Key Method: `_on_response_complete` — No Duplicate Bubble

```python
def _on_response_complete(self, session_key: str, text: str) -> None:
    self._dispatch(self._do_response_complete, session_key, text)

def _do_response_complete(self, session_key: str, text: str) -> None:
    if self._crh is None:
        return

    # Track whether streaming was active BEFORE we end it.
    # After end_streaming(), is_streaming() will always return False,
    # so we must capture this state now.
    was_streaming = self._crh.is_streaming(session_key)

    # End streaming — this finalizes the existing streaming bubble in place
    self._crh.end_streaming(session_key)

    # IMPORTANT: Verify end_streaming() behavior during Phase B implementation.
    # - If it finalizes the bubble in-place (text stays, bubble remains):
    #   keep the was_streaming guard below. Do NOT call render_sync() when streaming.
    # - If it destroys the bubble instead of finalizing:
    #   always call render_sync() with the full text. Remove the was_streaming guard.
    # Test this by asking Coder a short question and checking the DOM — if you see
    # two bubbles (one partial, one full), end_streaming() destroys and you need
    # to call render_sync() unconditionally.

    # Run text through crabcard extraction (same pipeline as gateway agents)
    project_name = self._active_project[0] if self._active_project else None
    text_for_bubble = text

    if project_name and text:
        from utils.crabcard_parser import extract_crabcards
        cleaned_text, cards = extract_crabcards(text, project_name)
        if cards:
            # Wire crabcard extraction to the feed via FeedHandler.add_card().
            # This path (handler → FeedHandler) is used because special agent
            # crabcards arrive here in AgentRuntimeHandler, not through the
            # ChatRenderHandler pipeline that gateway agents use.
            for card_data in cards:
                card_data.project_name = project_name
                self._fh.add_card(card_data)
        text_for_bubble = cleaned_text if cards else text

    # IMPORTANT: Do NOT call render_sync() if streaming was active.
    # The streaming bubble already contains the text and was finalized
    # by end_streaming() above. Calling render_sync() would create a duplicate.
    #
    # Exception: if streaming never started (e.g., non-streaming fallback or
    # empty initial delta), we need to create a final bubble.
    if not was_streaming and text_for_bubble:
        chat_box = self._mc.get_chat_box_for_session(session_key)
        if chat_box is not None:
            bubble = self._crh.render_sync(
                "Agent", text_for_bubble, session_key, agent_name="Agent"
            )
            if bubble is not None:
                chat_box.append(bubble)
            self._mc.scroll_chat_to_bottom()
```

**Implementation note:** During Phase B, verify `ChatRenderHandler.end_streaming()` behavior. If it destroys the streaming bubble instead of finalizing it in place, you'll need to always call `render_sync()`. The `was_streaming` guard exists to prevent duplicates — adjust based on what end_streaming actually does.

#### Key Method: `_on_tool_call_approval_needed` — Approval Feed Card

When `exec_command` needs PM approval:

```python
def _on_tool_call_approval_needed(
    self, session_key: str, tool_name: str, args: dict
) -> None:
    self._dispatch(self._do_approval_needed, session_key, tool_name, args)

def _do_approval_needed(self, session_key: str, tool_name: str, args: dict) -> None:
    if self._active_project is None:
        # No active project — special agents require a project.
        # The runtime will auto-deny on timeout. Log for visibility.
        logger.info("Approval requested but no active project for %s", session_key)
        return

    if self._fh is None:
        # No feed available — render denial as a chat bubble so the PM
        # is not left wondering why the command was silently denied.
        command = args.get("command", "unknown")
        self._dispatch(self._do_error, session_key,
                       f"exec_command requires a project context: {command[:60]}")
        return

    agent_def = self._agents.get(session_key)
    agent_name = agent_def.display_name if agent_def else "Agent"
    project_name, _ = self._active_project
    command = args.get("command", "unknown")

    card = FeedCardData(
        card_type="agent_action",
        source="agent",
        title=f"⚠️ {agent_name} requests approval to run command",
        body=f"$ {command}",
        author=agent_name,
        timestamp=datetime.now(timezone.utc),
        project_name=project_name,
        metadata={
            "tool_name": tool_name,
            "tool_args": args,
            "session_key": session_key,
            "status": "pending_approval",
            "needs_approval": True,
        },
    )
    card_id = self._fh.add_card(card)

    # Map card_id → pending approval info so approve_exec() can resolve it
    self._pending_approvals[card_id] = {
        "session_key": session_key,
        "tool_name": tool_name,
        "args": args,
    }
```

Then `approve_exec` resolves the pending approval by forwarding to the runtime:

```python
def approve_exec(self, approval_id: str, approved: bool) -> None:
    """
    Called when PM clicks Approve/Deny on a pending-approval feed card.
    approval_id is the card_id of the approval card.
    """
    pending = self._pending_approvals.pop(approval_id, None)
    if pending is None:
        logger.warning("No pending approval for card %s", approval_id)
        return

    session_key = pending["session_key"]
    tool_name = pending["tool_name"]
    args = pending["args"]

    # Find the runtime that owns this session and resolve the approval
    for name, rt in self._runtimes.items():
        if rt.get_conversation(session_key) is not None:
            rt.approve_exec(session_key, tool_name, args, approved)
            break

    # Update the card status in the feed
    if self._fh is not None:
        card = self._fh.get_card(approval_id)
        if card:
            card.metadata["status"] = "approved" if approved else "denied"
            self._fh.update_card(approval_id, card)
```

**Note on approval flow:** The runtime's `_run_loop` blocks the tool loop thread on a `threading.Event` until `approve_exec()` is called. The thread will be blocked for up to 5 minutes (300s timeout). If the timeout expires, the approval is treated as denied. This is by design — the PM must actively approve commands.

#### Unchanged Callbacks: `_on_text_delta`, `_on_error`, `_on_token_usage`

These callbacks are carried over from the current implementation with no functional changes:

- `_on_text_delta` → starts/updates streaming bubble via `ChatRenderHandler` (unchanged)
- `_on_error` → ends streaming, renders error bubble (unchanged)
- `_on_token_usage` → logs token usage (unchanged)

Their implementations are identical to the current code. See the existing `agent_runtime_handler.py` for reference.

#### Required Imports

The rewritten handler needs these imports at the top of the file:

```python
from datetime import datetime, timezone
from agent.special_agents import SpecialAgentDef
from models.feed_card import FeedCardData
```

Note: `agent.runtime.AgentRuntime`, `agent.config.load_agent_config`, and `utils.crabcard_parser.extract_crabcards` are imported lazily inside methods to avoid circular import issues at module load time.

#### Helper: `_dispatch`

```python
def _dispatch(self, fn, *args) -> None:
    """Dispatch to main thread via GLib.idle_add, or call directly if no GLib."""
    if self._GLib is not None:
        self._GLib.idle_add(fn, *args)
    else:
        fn(*args)
```

#### Helper: `_get_runtime`

```python
def _get_runtime(self, agent_def: SpecialAgentDef) -> Any:
    """
    Get or create the AgentRuntime for a named agent.
    Each named agent gets its own AgentRuntime instance for isolation.
    """
    name = agent_def.conv_id_prefix
    if name in self._runtimes:
        return self._runtimes[name]

    from agent.config import load_agent_config
    from agent.runtime import AgentRuntime

    config = load_agent_config()
    provider = config.providers.get(config.default_provider)
    if not provider:
        raise RuntimeError(f"No provider configured for {config.default_provider}")
    if not provider.api_key:
        raise RuntimeError(f"No API key for provider {config.default_provider}")

    rt = AgentRuntime(
        config=config,
        GLib=self._GLib,
        on_text_delta=self._on_text_delta,
        on_tool_call_start=self._on_tool_call_start,
        on_tool_call_result=self._on_tool_call_result,
        on_tool_call_approval_needed=self._on_tool_call_approval_needed,
        on_response_complete=self._on_response_complete,
        on_token_usage=self._on_token_usage,
        on_error=self._on_error,
    )
    rt.start()
    self._runtimes[name] = rt
    logger.info("Created AgentRuntime for special agent: %s", name)
    return rt
```

---

### Change 2: `agent/runtime.py` — Targeted Modifications

#### 2a: Filtered Tool Definitions

Add a new function:

```python
def get_tool_definitions_for_agent(
    allowed_tools: list[str],
) -> list[dict]:
    """
    Return tool definitions filtered to only those in the allowed list.
    Used by AgentRuntime to send only the tools the agent is permitted to use.
    """
    from agent.tools import get_tool_definitions_for_api
    all_tools = get_tool_definitions_for_api()
    return [
        t for t in all_tools
        if t["function"]["name"] in allowed_tools
    ]
```

In `_run_loop`, replace:
```python
# OLD
from agent.tools import get_tool_definitions_for_api
tools = get_tool_definitions_for_api()
```

With:
```python
# NEW
if conv.allowed_tools:
    tools = get_tool_definitions_for_agent(conv.allowed_tools)
else:
    tools = get_tool_definitions_for_api()  # fallback: all tools
```

This requires adding `allowed_tools: list[str] | None = None` to the `Conversation` dataclass in `models/conversation.py`, and setting it in `create_conversation()` from the `SpecialAgentDef.tools` list.

**Conversation dataclass change** (`models/conversation.py`):

```python
@dataclass
class Conversation:
    # ... existing fields ...
    allowed_tools: list[str] | None = None  # NEW — tool names this agent can use
```

**`create_conversation` change** (`agent/runtime.py`):

```python
def create_conversation(
    self,
    agent_name: str,
    session_key: str,
    project_path: str | None = None,
    allowed_tools: list[str] | None = None,  # NEW
) -> None:
    # ... existing code ...
    conv.allowed_tools = allowed_tools
```

**`send_to_special_agent` call site** (`agent_runtime_handler.py`):

```python
rt.create_conversation(
    agent_name=agent_def.display_name,
    session_key=session_key,
    project_path=project_path,
    allowed_tools=agent_def.tools,  # NEW — filtered tools
)
```

#### 2b: Approval Flow with Card-based Resolution

The current `_run_loop` approval mechanism uses `_pending_approvals` keyed by session_key. Change to support card-based approval IDs:

In `_run_loop`, when a tool call needs approval (for `exec_command`):

```python
# Inside _run_loop, after detecting exec_command needs approval:
if defn.requires_approval:
    # Generate a unique approval_id
    approval_id = f"{session_key}:{tool_name}:{time.monotonic_ns()}"
    pending = {
        "session_key": session_key,
        "tool_name": tool_name,
        "args": args,
        "event": threading.Event(),
        "result_ref": [None],  # [approved: bool | None]
        "approval_id": approval_id,
    }
    with self._lock:
        self._pending_approvals[approval_id] = pending

    # Notify handler — it creates a feed card and maps card_id → approval info
    self._dispatch(self._on_tool_call_approval_needed, session_key, tool_name, args)

    # Block the tool loop thread until PM resolves.
    # WARNING: This blocks the thread. The handler resolves it via approve_exec().
    # Timeout after 5 minutes — treat timeout as denial.
    pending["event"].wait(timeout=300)
    approved = pending["result_ref"][0]

    if not approved:
        # Add tool result showing denial
        tool_result = ToolResult(success=False, error="exec_command denied by PM")
        # ... continue loop with denial result
```

Then `approve_exec` resolves by matching session_key and tool_name:

```python
def approve_exec(self, session_key: str, tool_name: str, args: dict, approved: bool) -> None:
    """Resolve a pending approval. Called by AgentRuntimeHandler."""
    with self._lock:
        for key, pending in list(self._pending_approvals.items()):
            if (pending["session_key"] == session_key
                    and pending["tool_name"] == tool_name):
                pending["result_ref"][0] = approved
                pending["event"].set()
                self._pending_approvals.pop(key, None)
                return
```

#### 2c: `create_conversation` Makes project_path Non-Optional

Change the signature to require `project_path`:

```python
def create_conversation(
    self,
    agent_name: str,
    session_key: str,
    project_path: str | None = None,  # kept optional for backward compatibility
    allowed_tools: list[str] | None = None,  # NEW
) -> None:
    # ... existing code ...
    conv.allowed_tools = allowed_tools

**Note:** Keeping `project_path: str | None = None` (not forcing it required) preserves backward compatibility with any existing callers (e.g., tests). The handler never calls this without a project, so the guard is already in place at the call site.

---

### Change 3: `ui/window.py` — Wiring Changes

#### 3a: Constructor — Add feed_handler

```python
# Existing code (line ~139):
from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
self._agent_runtime_handler = AgentRuntimeHandler(
    main_content=self._main_content,
    chat_render_handler=self._chat_render_handler,
    feed_handler=self._feed_handler,        # ADD THIS
    review_handler=self._review_handler,
    GLib_module=GLib,
)
```

#### 3b: Register Agents — Pass Full Definition

```python
# Existing code (line ~149):
from agent.special_agents import get_special_agents
for agent_def in get_special_agents():
    self._agent_runtime_handler.add_special_agent(agent_def)  # CHANGE: pass full def, not name+key
```

This means `add_special_agent` now takes a `SpecialAgentDef` instead of `(name, session_key)`. The agent definition includes `conv_id_prefix` (used as session_key), `display_name`, `tools`, `color`, `emoji`, etc.

#### 3c: Project Lifecycle — Wire set_active_project / clear_active_project

Find where `on_project_opened` and `on_project_closed` are wired (the callbacks that call `FeedHandler.on_project_opened`, `CrabWatchHandler.start_watching`, etc.). Add calls:

```python
# In the on_project_opened callback chain:
self._agent_runtime_handler.set_active_project(name, path)

# In the on_project_closed callback chain:
self._agent_runtime_handler.clear_active_project()
```

These must be called in the correct order: `set_active_project` BEFORE any agent messages could be sent.

#### 3d: Keep ChatHandler as Routing Entry Point

`ChatHandler.on_send()` already detects special agent session keys and delegates to `AgentRuntimeHandler.send_to_special_agent()`. Keep this pattern — no changes to `ChatHandler` needed. The `set_agent_runtime_handler()` injection already exists and works.

#### 3e: Wire Approval Resolution in Feed Card Callbacks

The feed cards for pending approvals have Accept/Reject buttons. Wire them so clicking Accept/Deny resolves the approval:

```python
# In window.py, when wiring FeedHandler accept/reject callbacks:
# The existing handle_accept and handle_reject in FeedHandler call on_accept/on_reject.
# Wrap them to detect approval cards:

def on_accept_card(card_id):
    card = self._feed_handler.get_card(card_id)
    if card and card.metadata.get("needs_approval"):
        # This is an approval card — resolve it via AgentRuntimeHandler
        self._agent_runtime_handler.approve_exec(card_id, True)
    elif card and self._review_handler:
        # This is a review card — accept via ReviewHandler
        self._review_handler.accept_changes(card.project_name, "Accepted via feed")

def on_reject_card(card_id):
    card = self._feed_handler.get_card(card_id)
    if card and card.metadata.get("needs_approval"):
        # Deny the approval
        self._agent_runtime_handler.approve_exec(card_id, False)
    elif card and self._review_handler:
        # Reject via ReviewHandler
        self._review_handler.reject_changes(card.project_name, "Rejected via feed")
```

---

### Change 4: `models/conversation.py` — Add `allowed_tools` Field

```python
# In the Conversation dataclass:
@dataclass
class Conversation:
    # ... existing fields ...
    allowed_tools: list[str] | None = None  # NEW — tool names permitted for this agent
```

Serialization updates in `to_dict()` and `from_dict()`:

```python
# to_dict:
d["allowed_tools"] = self.allowed_tools

# from_dict:
self.allowed_tools = data.get("allowed_tools")
```

**Architecture check:** `Conversation` is in `models/`. Adding a `list[str] | None` field requires no new imports. Complies with ARCHITECTURE.md rule: "models/ — no imports from ui/, agent/, gateway/."

---

### Change 5: `ui/handlers/feed_handler.py` — Add `update_card()` Method

**`FeedHandler.update_card()` does NOT exist.** It must be implemented. This is not optional.

```python
def update_card(self, card_id: str, updated_data: FeedCardData) -> None:
    """
    Update an existing card's data and re-render its widget.

    Used by AgentRuntimeHandler to update tool-call cards with results
    (status changes from "running" to "complete"/"error").
    """
    with self._lock:
        if card_id not in self._cards:
            return
        self._cards[card_id] = updated_data

        # Re-render the widget if it exists
        old_widget = self._card_widgets.get(card_id)
        if old_widget is not None:
            from ui.views.feed_card import build_feed_card
            new_widget = build_feed_card(
                updated_data,
                on_review=self._on_review,
                on_accept=self._on_accept,
                on_reject=self._on_reject,
                on_copy=self._on_copy,
            )
            # Replace in container (GTK4 API)
            container = old_widget.get_parent()
            if container is not None:
                # Find position of old widget by walking siblings
                pos = 0
                child = container.get_first_child()
                while child is not None:
                    if child == old_widget:
                        break
                    child = child.get_next_sibling()
                    pos += 1
                container.remove(old_widget)
                container.insert_child_at_index(new_widget, pos)
                self._card_widgets[card_id] = new_widget

    # Persist to disk
    if self._current_project_path:
        from utils.feed_store import update_feed_card
        update_feed_card(self._current_project_path, card_id, updated_data.to_dict())
```

**Architecture check:** `FeedHandler` is in `ui/handlers/`. It already imports from `ui/views/feed_card.py`. This is allowed per ARCHITECTURE.md Section 2. The `update_feed_card` import from `utils/feed_store` is also allowed. No cross-handler imports.

---

## Implementation Order (Build Phases)

### Phase A: Critical Path — Make Tools Work
*Smallest change, biggest impact. ~40 lines changed.*

1. Add `allowed_tools` field to `models/conversation.py` (~5 lines)
2. Add `get_tool_definitions_for_agent()` to `agent/runtime.py` (~10 lines)
3. Modify `create_conversation()` to accept and store `allowed_tools` (~3 lines)
4. Modify `_run_loop()` to use filtered tools (~3 lines)
5. Add `set_active_project()` / `clear_active_project()` to `AgentRuntimeHandler` (~20 lines)
6. Wire `set_active_project`/`clear_active_project` in `window.py` project lifecycle (~4 lines)
7. Change `add_special_agent()` to accept `SpecialAgentDef` instead of `(name, key)` (~5 lines)
8. Pass `project_path` and `allowed_tools` in `send_to_special_agent()` (~3 lines)

**Result:** Agents can use file tools. Debugger doesn't get write_file.

**Test:** Open a project. Chat with Coder. Ask it to read a file. Verify it returns file contents.

### Phase B: Fix Duplicate Bubbles
*~15 lines changed.*

1. Rewrite `_on_response_complete` to track `was_streaming` before ending
2. Only call `render_sync()` if streaming never started
3. Verify `ChatRenderHandler.end_streaming()` behavior — adjust if it destroys instead of finalizes

**Result:** Clean single-bubble streaming.

**Test:** Send message to Coder. Verify only one bubble appears (not two).

### Phase C: Crabcard Support
*~10 lines changed.*

1. In `_do_response_complete`, run agent text through `extract_crabcards()`
2. Use cleaned_text for the bubble (crabcard blocks removed)
3. Fire the existing crabcard callback for extracted cards

**Result:** Special agents can emit crabcards into the project feed.

**Test:** Configure agent to output a crabcard block. Verify card appears in feed.

### Phase D: Tool Call Feed Cards
*~80 lines changed.*

1. Implement `_on_tool_call_start` → create `agent_action` feed card
2. Implement `_on_tool_call_result` → update feed card with results
3. Add `update_card()` to `FeedHandler` if it doesn't exist (~30 lines)
4. Add `_tool_card_ids` dict to handler constructor

**Result:** Full visibility into agent tool activity.

**Test:** Ask Coder to read a file. Verify card appears in feed, then updates with file contents.

### Phase E: Approval Feed Cards
*~60 lines changed.*

1. Implement `_on_tool_call_approval_needed` → create pending-approval card
2. Implement `approve_exec()` → resolve pending approval
3. Wire approval resolution in `window.py` accept/reject callbacks
4. Modify runtime's approval flow to use Event-based blocking

**Result:** PM controls exec_command through the feed.

**Test:** Ask Coder to run a command. Verify approval card appears. Click Approve. Verify command runs.

---

## Verification Checklist

After all phases are complete:

- [ ] Special agent chat works in a project tab (message → streaming response → single bubble)
- [ ] Special agent chat REJECTED when no project is open (error message shown)
- [ ] Coder can read files (read_file tool → feed card with file contents)
- [ ] Coder can write files (write_file tool → feed card → Accept/Reject if review active)
- [ ] Coder can list files (list_files → feed card with directory listing)
- [ ] Coder can search files (search_files → feed card with results)
- [ ] Coder can search the web (web_search → feed card with results)
- [ ] Coder can fetch URLs (web_fetch → feed card with page text)
- [ ] Coder exec_command requires approval (feed card → Approve button → command runs)
- [ ] Debugger does NOT see write_file in its tool set
- [ ] Debugger can read files but cannot write
- [ ] Crabcard blocks in agent output appear as cards in the feed
- [ ] CrabWatch cards still appear independently (no regression)
- [ ] Gateway agents still work (no regression to existing gateway routing)
- [ ] Project close clears agent project context
- [ ] Reopening a project restores agent project context
- [ ] All existing tests pass
- [ ] ARCHITECTURE.md updated with new public APIs
- [ ] No cross-handler imports (verify with grep)

---

## Files Modified — Summary

| File | Action | Lines Changed (est.) |
|------|--------|---------------------|
| `ui/handlers/agent_runtime_handler.py` | **Rewrite** | ~380 lines (up from ~265) |
| `agent/runtime.py` | **Modify** | ~30 lines changed |
| `models/conversation.py` | **Modify** | ~5 lines (add field + serialization) |
| `ui/window.py` | **Modify** | ~15 lines (wiring changes) |
| `ui/handlers/feed_handler.py` | **Modify** | ~30 lines (add update_card if missing) |
| `docs/ARCHITECTURE.md` | **Update** | Section 3 module APIs + Section 11 file inventory |
| `docs/AGENT_RUNTIME_FEED_INTEGRATION.md` | **Create** | This document |

**Total estimated change:** ~480 lines across 7 files.


---

## QTR Review Changes (2026-05-05)

The following changes were made by QTR after review of the original proposal.

### Issue 1 Fixed: Crabcard callback was a TODO
- **Problem:** `_do_response_complete` had `pass  # TODO: fire crabcard callback during implementation` — crabcard integration was not designed.
- **Fix:** Replaced TODO with full implementation that calls `FeedHandler.add_card()` directly for each extracted card, with proper project context stamping. The routing explanation documents why this path (handler → FeedHandler) was chosen over ChatRenderHandler's callback.

### Issue 2 Fixed: `update_card()` hedge removed
- **Problem:** Change 5 said "check if this exists already before implementing" — uncertain whether `update_card()` existed.
- **Fix:** Changed to "does NOT exist — implement it. Do NOT skip this." `FeedHandler` was checked and `update_card()` does not currently exist.

### Issue 3 Fixed: Dual `approve_exec` signatures documented
- **Problem:** Handler-level `approve_exec(approval_id, approved)` and runtime-level `approve_exec(session_key, tool_name, args, approved)` had overlapping responsibilities with no explanation.
- **Fix:** Added a design note above the runtime's `approve_exec` explaining the two-level design: handler owns card_id → approval_info mapping; runtime owns thread blocking. card_id never enters the runtime layer. The handler translates card_id → (session_key, tool_name, args) before calling runtime.approve_exec.

### Issue 4 Fixed: `_tool_card_ids` collision vulnerability
- **Problem:** Keyed by `session_key + ":" + tool_name`. Two same-name tool calls in one response would collide.
- **Fix:** Changed key from composite to `session_key` only. tool_name is already stored in the card's metadata. `_do_tool_call_result` looks up by session_key and reads tool_name from metadata if needed. Added comment about using `tool_call_id` for concurrent calls.

### Issue 5 Fixed: Phase B duplicate bubble — verification required
- **Problem:** Phase B deferred verifying what `end_streaming()` actually does.
- **Fix:** Added a detailed inline note in `_do_response_complete` explaining how to test it (ask Coder a short question, check for two bubbles), and what to do in each case (keep was_streaming guard OR always call render_sync). This must be verified before Phase B is implemented.

### Issue 6 Fixed: No-feed scenario in approval flow
- **Problem:** `_do_approval_needed` with no feed did nothing — PM got no notification that a command was denied.
- **Fix:** Added fallback path: when `_fh is None` but a project is active, renders a chat error bubble via `_do_error` so the PM sees the denial message. Only the truly no-project case logs and relies on timeout.

### Issue 7 Fixed: `project_path` made non-optional unnecessarily
- **Problem:** `create_conversation`'s `project_path` was changed from `str | None = None` to required `str`. Breaking change for non-callers.
- **Fix:** Reverted to `str | None = None`. Added note explaining backward compatibility and why the handler guard is sufficient without forcing the signature.

### Recommendation 1 (Phase A immediate): No code change needed — already correct in the proposal.
### Recommendation 2 (Crabcard wiring): Integrated into Issue 1 fix above.
### Recommendation 3 (Dual approve_exec): Integrated into Issue 3 fix above.
### Recommendation 4 (Concurrent tool calls test): Integrated into Issue 4 fix above. Added comment about `tool_call_id` for concurrent calls.
### Recommendation 5 (No-feed notification): Integrated into Issue 6 fix above.
