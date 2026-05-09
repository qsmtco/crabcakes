# Proposal: Agent-to-Agent Communication

**Author:** Lieutenant Qrusher
**Date:** 2026-05-08
**Status:** Proposed
**Target:** Crabcakes Phase 7 (completion) + Phase 5 (convergence wiring)

---

## 1. Overview

This proposal implements direct agent-to-agent communication via `@` mentions within project group chat. When an agent needs input from another agent, it posts an **intent crabcard** to the project feed and opens a private conversational thread. The PM observes the exchange in the group chat. **Convergence detection** automatically closes the thread when the agents have finished collaborating.

### What this enables

```
Captain:  @Coder implement the auth spec
          [Message fans out to Coder]

Coder:    [posts intent card] Consulting @QTR on token format
          [crabcard appears in project feed]

          [Coder ↔ QTR exchange in private thread]
          [project chat shows the full exchange as it happens]

          [convergence detected → thread closes]

Coder:    Ready. Auth spec implemented.
          [crabcard: diff — auth.py]
```

The PM sees a coherent narrative in the project feed: consultation intent → exchange → result. No hidden side conversations. No manual thread management.

---

## 2. Architecture

### 2.1 Design principles

| Principle | Rationale |
|-----------|-----------|
| Shared injected prompt, not per-agent files | All agents (gateway + special) get new behavior by adding one prompt file |
| `gateway/` and `models/` must never import from `ui/` | Architecture hard rule from ARCHITECTURE.md |
| Agents speak via existing infrastructure | Gateway `send_message` for remote agents; AgentRuntime for Coder/Debugger |
| PM always sees the exchange | Conversation threads replay into project chat via ChatHandler fan-out |
| Convergence auto-closes threads | No manual `/done` or stop command required |

### 2.2 Component map

```
project group chat
    │
    ├── CollabHandler.cmd_ask()      → returns CommandResult(forward_to, forward_text)
    │                                  (already exists, no changes needed)
    │
    ├── ChatHandler._route_command() → forwards to target agent via gateway
    │                                  (already exists, no changes needed)
    │
    ├── NEW: prompts/system/collab.md
    │         ↳ composed into ALL agent system prompts
    │         ↳ instructs agents to emit intent crabcards + use @ mentions
    │
    ├── Agent (receives @ mention)
    │         │
    │         ├── NEW: emits intent crabcard (type: agent_action)
    │         │         "Consulting @TargetAgent on <topic>"
    │         │
    │         ├── uses @ mention in reply → ChatHandler routes to target agent
    │         │
    │         └── response triggers converge.should_stop() check
    │                   │
    │                   └── if True → ChatHandler closes thread
    │                              → posts closing crabcard to project feed
    │
    └── FeedHandler
              └── displays crabcards in project feed (already exists)
```

---

## 3. Shared Collaboration Prompt

**File:** `prompts/system/collab.md`

This file is composed into every agent's system prompt (gateway agents and special agents alike) via the existing `prompt_loader.py` template system. No per-agent files.

### Content

```markdown
# Collaboration

You are working alongside other agents in a shared project chat.

## Consulting Another Agent

When you need expertise from another agent, use this protocol:

1. **Post an intent card** in your response:
   ```
   type: agent_action
   title: Consulting @TargetAgent on <specific topic>
   agent: YOUR_NAME
   action: consultation
   target: TargetAgent
   topic: <what you need help with>
   ```

   Emit this as a crabcard block at the start of your response:

   ```crabcard
   type: agent_action
   title: Consulting @QTR on token validation
   agent: Coder
   action: consultation
   target: QTR
   topic: token validation edge cases
   ```

2. **Ask your question directly** using `@TargetAgent` in the message body.
   Example: `@QTR — for the token validation, should I treat an empty string as invalid?`

3. The PM sees your intent card in the project feed and watches the consultation happen.

## Receiving a Consultation

When another agent @mentions you:

- Answer the question directly and thoroughly.
- Use `@OriginalAgent` to reply, continuing the thread.
- After your final response, the conversation will automatically close when
  convergence is detected. Do NOT manually signal done — the system handles it.

## Ending a Consultation

Do NOT say "I'm done" or "stopping". The convergence detector notices when
the conversation has wound down naturally and closes the thread for you.

## Crabcard Reference

Available crabcard `type` values:
- `diff` — file changes (additions/deletions)
- `agent_action` — agent activity signals (consultation intent, decisions, completions)
- `review_request` — PM review requests

Required crabcard fields by type:
- `diff`: `type`, `title`
- `agent_action`: `type`, `title`, `agent`, `action`
```

---

## 4. Prompt Loader Modification

**File:** `utils/prompt_loader.py`

The prompt loader must compose `collab.md` into all agent system prompts. The loader already supports composing multiple prompt files — we add `collab.md` as a base layer.

### Change

In `build_system_prompt()` (or equivalent), after loading `default.md`, additionally load `prompts/system/collab.md` and append it to the system prompt block.

The file path:
```
SYSTEM_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "system")
                                        ↑
                                    crabcakes/
                                    utils/prompt_loader.py → ../.. → crabcakes/
```

```python
# After loading default.md content
collab_path = os.path.join(SYSTEM_DIR, "collab.md")
if os.path.isfile(collab_path):
    try:
        with open(collab_path, "r", encoding="utf-8") as f:
            collab_content = f.read()
        # Append to system block
        parts.append(collab_content)
    except OSError:
        pass
```

This is added in the same function that currently loads `default.md`, `coder.md`, `debugger.md`, etc.

---

## 5. Intent Crabcard Display

**File:** `ui/handlers/feed_handler.py` (existing, may need modification)

**File:** `ui/views/feed_card.py` (existing)

The `agent_action` crabcard type must render in the project feed. The `FeedCardData` dataclass and `css_class_for_type()` in `feed_card.py` already handle `agent_action` as a valid type. Verify:

1. `FeedCardData` accepts `action` and `target` metadata fields.
2. The feed card template renders `action: consultation` cards with distinct styling (e.g., a "discussion" icon or color).

If not, add the missing fields to `FeedCardData` and update the card widget factory.

---

## 6. Convergence Wiring

**File:** `ui/handlers/chat_handler.py`

**Method:** `ChatHandler._handle_final_response()`

This method is called when an agent response is confirmed by the gateway (`res` event). It is the canonical insertion point for convergence detection.

### Current signature (approximate)

```python
def _handle_final_response(self, session_key: str, text: str, agent_name: str | None = None) -> None:
    # renders the final response bubble
```

### Required change

1. **Import `should_stop`** at module level:
   ```python
   from converge.converge import should_stop
   ```

2. **Track responses per thread.** Each agent-to-agent thread needs a running list of responses to pass to `should_stop()`. Use a dict on `ChatHandler`:
   ```python
   self._thread_responses: dict[str, list[dict]] = {}
   # key: thread_id (session_key of the initiating agent tab, or a sub-thread key)
   # value: list of {"text": str} dicts
   ```

3. **In `_handle_final_response`**, after rendering the bubble:
   ```python
   # Append to thread responses
   if session_key not in self._thread_responses:
       self._thread_responses[session_key] = []
   self._thread_responses[session_key].append({"text": text})

   # Check convergence
   turn = len(self._thread_responses[session_key])
   if turn >= 3:  # should_stop allows turn <= 2 to continue
       if should_stop(self._thread_responses[session_key], turn):
           self._close_thread(session_key)
   ```

4. **`_close_thread()` method**:
   ```python
   def _close_thread(self, session_key: str) -> None:
       """
       Close an agent-to-agent consultation thread.
       Removes from tracking, posts closing crabcard to project feed,
       and sends a stop hint to the target agent.
       """
       self._thread_responses.pop(session_key, None)
       # Post closing card to project feed
       if self._feed_handler is not None:
           closing_card = FeedCardData(
               type="agent_action",
               title=f"Consultation complete",
               agent="System",
               metadata={"action": "consultation_close", "session_key": session_key},
           )
           self._feed_handler.add_card(closing_card)
       # Optionally send "stop" to the target agent
       if self._gw is not None and self._gw.is_connected():
           self._gw.send_message(session_key, "stop")
   ```

**Note:** `_close_thread()` must be added as a new method on `ChatHandler`. `FeedHandler` is accessed via `self._feed_handler` which is already settable via `set_feed_handler()`.

---

## 7. Agent Runtime — Intent Card Emission

**File:** `agent/runtime.py`

Special agents (Coder, Debugger) are driven by `AgentRuntime`. The `on_response_complete` callback receives the full response text. Before sending the response to the UI, the runtime should check for consultation intent.

### Option A — In the enforcement hook (recommended)

The enforcement hook in `AgentRuntime` already runs post-generation. We extend it to detect `@TargetAgent` patterns and inject an intent card:

```python
def _enforcement_hook(self, conversation, response_text) -> str:
    """
    Post-write hook: check for @mentions, inject intent crabcards.
    Called after LLM generates a response and before it is returned.
    """
    # Detect @mention patterns
    mention_pattern = re.compile(r'@([A-Z][a-zA-Z]+)')
    mentions = mention_pattern.findall(response_text)

    if mentions and not self._intent_card_injected(conversation.session_key):
        intent_text = f"Consulting @{mentions[0]} on task"
        intent_card = f'\n\n```crabcard\ntype: agent_action\ntitle: {intent_text}\nagent: {conversation.agent_name}\naction: consultation\ntarget: {mentions[0]}\n```\n\n'
        response_text = intent_card + response_text
        self._mark_intent_injected(conversation.session_key)

    return response_text
```

### Option B — In the tools

When an agent calls a tool that requires consultation (e.g., `read_file` on an unfamiliar domain), the tool result handler detects this and the subsequent response generation includes the intent card.

**Recommendation:** Option A is simpler and covers all cases where the agent self-selects for consultation.

### `_intent_card_injected` tracking

Add to `AgentRuntime`:
```python
self._intent_injected: set[str] = set()  # session_keys that have already injected an intent card

def _intent_card_injected(self, session_key: str) -> bool:
    return session_key in self._intent_injected

def _mark_intent_injected(self, session_key: str) -> None:
    self._intent_injected.add(session_key)
```

---

## 8. Special Agent Routing — Thread Identity

**Files:** `agent/runtime.py`, `ui/handlers/agent_runtime_handler.py`

Agent-to-agent threads need stable session keys that map to the correct project context. When Agent A opens a thread with Agent B:

1. Agent A's system prompt includes project awareness (already the case via `build_system_prompt`)
2. The thread session key follows the pattern: `a2a:{project_name}:{agent_a}:{agent_b}:{thread_id}`
   - Example: `a2a:manopea:Coder:QTR:abc123`
3. `ChatHandler` maps this to the project tab for display

**Existing infrastructure:** `AgentRuntimeHandler._resolve_chat_box()` already has fallback logic to route to project chat when no direct tab exists. No new routing infrastructure needed.

---

## 9. Feed Handler — Closing Card

**File:** `ui/handlers/feed_handler.py`

`FeedHandler.add_card()` already accepts `FeedCardData`. The closing card from `_close_thread()` uses `type: agent_action` with `action: consultation_close`. The feed card renderer should display this with a "check" icon and "Consultation complete" text.

If the current feed card renderer doesn't handle `consultation_close` action specifically, add a branch in the card widget factory:

```python
if card.metadata.get("action") == "consultation_close":
    # render with check icon, muted styling
```

---

## 10. Implementation Order

### Step 1 — Prompt file
- Create `prompts/system/collab.md` with collaboration instructions
- Verify `prompt_loader.py` composes it into agent system prompts (may need update)

### Step 2 — Convergence wiring
- In `ChatHandler`, import `should_stop` from `converge.converge`
- Add `_thread_responses` dict and `_close_thread()` method
- Call `should_stop()` in `_handle_final_response` after rendering
- Inject `set_feed_handler()` call if not already wired

### Step 3 — Intent card injection (special agents)
- In `AgentRuntime._enforcement_hook()` (or similar post-generation hook), detect `@TargetAgent` patterns
- Prepend intent crabcard to response text when consultation detected

### Step 4 — Intent card display
- Verify `FeedCardData` accepts `agent`, `action`, `target` metadata fields
- Update `feed_card.py` widget factory to render `consultation` action cards distinctly

### Step 5 — Closing card
- In `FeedHandler`, add rendering for `agent_action` cards with `action: consultation_close`
- Style with check icon / "complete" color

### Step 6 — Documentation
- Update `docs/ARCHITECTURE.md` with new shared prompt: `prompts/system/collab.md`
- Update `docs/BUILD_ORDER.md` to mark Steps 1–5 complete

---

## 11. Files to Modify

| File | Change |
|------|--------|
| `prompts/system/collab.md` | **New file** — shared collaboration prompt |
| `utils/prompt_loader.py` | Compose `collab.md` into all agent system prompts |
| `ui/handlers/chat_handler.py` | Add `should_stop()` wiring, `_thread_responses`, `_close_thread()` |
| `ui/handlers/feed_handler.py` | Render `consultation_close` action cards |
| `ui/views/feed_card.py` | Ensure `agent_action` + `consultation` renders distinctly |
| `agent/runtime.py` | Intent card injection in enforcement hook or response handler |
| `models/feed_card.py` | Verify `action`/`target` metadata fields exist on `FeedCardData` |
| `docs/ARCHITECTURE.md` | Document `prompts/system/collab.md`, convergence wiring |
| `docs/BUILD_ORDER.md` | Mark steps complete |

---

## 12. Out of Scope

- Persistent group chat history for agents (per earlier decision — agents don't read chat history)
- Per-agent coder.md/debugger.md overrides (handled via shared prompt only)
- Agent-initiated spontaneous messaging outside of project context
- Multi-turn thread tracking beyond a single consultation exchange

---

## 13. Success Criteria

1. When `@Coder` asks `@QTR` a question from the project chat, the feed shows an intent card followed by the exchange
2. When the exchange naturally concludes, convergence detection posts a closing card without manual intervention
3. All agents (gateway and special) use the same collaboration protocol via the shared prompt
4. The PM can follow the entire consultation in the project feed without opening separate tabs