# BUG: Agent Card Conversation Snapshot Never Created in Project Sessions

**Severity:** HIGH  
**Date filed:** 2026-05-04  
**Filed by:** Qaster  
**Status:** Open  
**Affects:** Conversation Snapshot feature — agent cards only  
**Does NOT affect:** System/CrabWatch cards (diff snapshots work correctly)

---

## Symptom

When clicking **Review** on an agent-sourced feed card (from a `` ```crabcard `` block), the context panel does NOT expand. No conversation snapshot is shown. The Review button injects text into the input box and switches to the feed tab, but the expand/collapse panel is absent.

System cards (CrabWatch file change events) work correctly — their diff context panel expands as expected.

---

## Root Cause

### The Session Key Mismatch

There are **two different session keys** in play during a project group chat, and the conversation snapshot code uses the **wrong one** to look up the chat box.

#### What the code does:

1. Agent sends a response via the gateway. The gateway event carries `sessionKey = "agent:qaster:telegram:direct:7478874934"` (the agent's real session key).

2. `ChatHandler.on_chat_event()` routes the response:
   ```python
   # ui/handlers/chat_handler.py line 402-405
   project_name = self._agent_to_project.get_project(session_key)
   target_tab = f"project:{project_name}" if project_name else session_key
   # target_tab = "project:crabwatch"
   ```

3. `_handle_final_response(tab, session_key, txt)` renders the bubble:
   ```python
   # ui/handlers/chat_handler.py line 490
   bubble = self._chat_render_handler.render_sync("Agent", final_text, session_key, ...)
   #                                                                  ^^^^^^^^^^^
   #                                         Uses AGENT key, not tab key
   ```

4. Inside `render_sync`, crabcard extraction fires:
   ```python
   # ui/handlers/chat_render_handler.py line 358-359
   if cards:
       self._on_crabcard_extracted(cards, session_key or "")
   #                                           ^^^^^^^^^^^
   #                               Still the AGENT key
   ```

5. `window.py` stores it on the card:
   ```python
   # ui/window.py line 286
   card.metadata["session_key"] = session_key  # "agent:qaster:..."
   ```

6. `FeedHandler._maybe_create_snapshot()` tries to find the chat box:
   ```python
   # ui/handlers/feed_handler.py line 519-520
   session_key = card_data.metadata.get("session_key", "")  # "agent:qaster:..."
   chat_box = self._get_chat_box_for_session(session_key)   # looks for agent tab
   ```

7. `MainContent.get_chat_box_for_session()` searches `_tab_sessions`:
   ```python
   # ui/views/main_content.py line 631-635
   for page_idx, sk in self._tab_sessions.items():
       if sk == session_key:  # Looking for "agent:qaster:..."
           return self._tab_chat_boxes.get(page_idx)
   return None  # NOT FOUND — tab is registered as "project:crabwatch"
   ```

8. `chat_box` is `None` → snapshot is never created → no context panel.

#### What the code SHOULD do:

The chat box for project group chats is registered in `_tab_sessions` as `"project:crabwatch"` (see `window.py` line 307: `self._main_content.create_chat_tab(f"project:{n}", ...)`). The snapshot lookup should use `"project:crabwatch"`, not `"agent:qaster:..."`.

---

## Detailed Trace

### The Two Keys

| Context | Key | Example |
|---------|-----|---------|
| Agent's gateway session | `session_key` (from gateway event) | `agent:qaster:telegram:direct:7478874934` |
| Project tab in MainContent | `target_tab` (computed by routing) | `project:crabwatch` |

The chat bubbles are rendered into the `target_tab` chat box. The crabcard extraction receives `session_key`. The snapshot lookup uses `session_key` to find the chat box. **Mismatch.**

### Why System Cards Work

System/CrabWatch cards go through a completely different path in `_maybe_create_snapshot`:

```python
# ui/handlers/feed_handler.py line 526-528
elif card_data.source in ("system", "crabwatch"):
    project_path = ...
    if project_path and card_data.file_path:
        snapshot = conversation_store.snapshot_from_git_diff(project_path, card_data.file_path)
```

No `session_key` lookup at all — it uses `project_path` + `file_path` to get a git diff. That's why system cards work.

### Why Direct Agent Chats Would Work

If an agent is NOT a project member, routing falls back:
```python
target_tab = session_key  # No project → tab key = agent key
```

In this case, the tab IS registered under the agent's key, so `get_chat_box_for_session(session_key)` succeeds. The snapshot would be created correctly.

**The bug only manifests in project group chat sessions** where the agent is a project member.

---

## Affected Code Paths

| File | Line(s) | Issue |
|------|---------|-------|
| `ui/handlers/chat_handler.py` | 490 | `render_sync` receives `session_key` (agent key) instead of `tab` (project key) |
| `ui/handlers/chat_render_handler.py` | 358-359 | Passes `session_key` through to crabcard callback |
| `ui/window.py` | 286 | Stores agent key in `card.metadata["session_key"]` |
| `ui/handlers/feed_handler.py` | 519-520 | Looks up chat box using wrong key |

---

## Dead Code Note

`ChatHandler._show_agent_response()` (line 522-533) uses the **correct** key (`tab`) in its `render_sync` call. But this method is **never called** — it's dead code. The active path goes through `_handle_final_response` which uses the wrong key.

---

## Proposed Fix

### Option A: Store the target tab key on the card (Recommended)

**Where:** `ui/window.py` — the `_on_crabcards_extracted` callback

**What:** Instead of storing the raw `session_key`, resolve it to the project tab key before storing it:

```python
# ui/window.py — _on_crabcards_extracted
def _on_crabcards_extracted(cards: list, session_key: str):
    from ui.views.chat_bubble import _set_crabcards_registry
    _set_crabcards_registry(cards, _on_show_feed_subtab)
    
    # Resolve session_key to the correct chat tab key.
    # Project group chats register tabs as "project:<name>", not the agent key.
    lookup_key = session_key
    if self._project_handler:
        project_name = self._agent_to_project.get_project(session_key)
        if project_name:
            lookup_key = f"project:{project_name}"
    
    for card in cards:
        card.metadata["session_key"] = session_key       # keep original for reference
        card.metadata["chat_tab_key"] = lookup_key        # NEW: key for chat box lookup
        self._feed_handler.add_card(card)
```

Then update `_maybe_create_snapshot` to use `chat_tab_key`:

```python
# ui/handlers/feed_handler.py — _maybe_create_snapshot
if card_data.source == "agent" and self._get_chat_box_for_session:
    lookup_key = card_data.metadata.get("chat_tab_key", "") or card_data.metadata.get("session_key", "")
    chat_box = self._get_chat_box_for_session(lookup_key)
    if chat_box is not None:
        messages_raw = self._extract_messages_from_chat_box(chat_box)
        snapshot = conversation_store.snapshot_from_messages(
            messages_raw, lookup_key, total_available=len(messages_raw)
        )
```

**Why this approach:**
- Minimal change — only touches 2 files
- Preserves original `session_key` for reference/debugging
- Uses the routing table that already exists (`_agent_to_project`)
- Falls back to raw `session_key` if no project mapping exists (direct chats)
- No changes to `chat_render_handler.py` or `chat_handler.py`

### Option B: Pass both keys through the render pipeline

**Not recommended.** This would require changing the `render_sync` signature and the `set_on_crabcard_extracted` callback signature to carry both keys, touching more files for no additional benefit.

---

## Edge Cases to Consider

### 1. Solo DM in project
When using solo DM mode (right-click → agent name), messages go directly to the agent's session key. The agent response comes back on the agent's key. `_agent_to_project.get_project()` still maps it to the project. So `target_tab = "project:crabwatch"`, and the fix works correctly.

### 2. Agent not in any project
`_agent_to_project.get_project()` returns None → `lookup_key` stays as `session_key` → falls back to direct chat tab lookup → works as before.

### 3. Multiple projects open
Each project has its own routing entries. `get_project(session_key)` returns the correct project name for that agent. The chat box lookup finds the right project tab.

### 4. Chat box empty or no bubbles
If the agent's first message contains a crabcard, the chat box may only have the user's message (no agent bubbles yet). `_extract_messages_from_chat_box` would extract whatever exists. This is acceptable — a partial snapshot is better than no snapshot.

### 5. Session closed, chat box destroyed
`get_chat_box_for_session()` returns None → snapshot skipped → card has no context panel. Graceful degradation. Same as current behavior for direct chats when the tab is closed.

---

## Verification Steps

After fix:

1. Open a project in CrabCakes
2. Chat with an agent in the project group chat
3. Ask the agent to do something that produces a crabcard
4. When the crabcard appears in the feed, click **Review**
5. Context panel should expand showing mini-bubbles of the conversation
6. Click **Review** again — panel should collapse
7. Close and reopen the project — persisted cards with snapshots should restore correctly

Regression check:
1. Chat with an agent directly (not in a project)
2. Get a crabcard from that direct chat
3. Click **Review** — snapshot should still work (fallback path)
