# Bug Report: Special Agent Solo DM Bypasses AgentRuntimeHandler

> **Status: FIXED** — Verified in code as of 2026-05-09
> - ✅ BUG #1 (CRITICAL): Solo DM path now checks `is_special` and routes through `AgentRuntimeHandler.send_to_special_agent()` (chat_handler.py ~line 352)
> - ✅ BUG #2 (MEDIUM): `AgentRuntimeHandler._resolve_chat_box()` resolves special agent key to project tab via routing table (agent_runtime_handler.py ~line 280)

**Date:** 2026-05-06
**Found during:** Agent runtime feed integration testing
**Status:** Fixed

---

## Symptom

User sends a message to Coder via the project group chat solo DM path (right-click → select "special:coder"). The message goes to the **gateway** instead of **AgentRuntimeHandler**. Response comes back with gateway session key `agent:main:special:coder` which has no matching tab. Message is lost — no UI rendering.

Terminal shows:
```
[gateway>>] {"type":"event","event":"agent","payload":{"sessionKey":"agent:main:special:coder",...}}
ui.views.main_content WARNING [tab-dot] No tab found for session_key='agent:main:special:coder' — cannot update dot
```

---

## BUG #1 — CRITICAL

**Assumption violated:** "Messages to special agents always come from a special agent tab (session_key starts with `special:`)"

**Attack vector:**
1. Open a project (crabwatch)
2. Add Coder to project via `+` button
3. Right-click in project group chat → select "special:coder" as DM target
4. Type a message in the project group chat input and send
5. Message goes to gateway instead of AgentRuntimeHandler
6. Gateway creates session `agent:main:special:coder` (wrong path)
7. Response comes back with gateway session key
8. No tab found → message lost

**Root cause:** `chat_handler.on_send()` only checks for special agents when `session_key` directly matches a registered special agent key (line 156). When the message comes from a project group chat (`session_key="project:crabwatch"`) with a solo target pointing to a special agent, the special agent check is skipped, and the message is routed through the gateway instead of AgentRuntimeHandler.

**Code path (broken):**
```
chat_handler.on_send("project:crabwatch", text)
  → special agent check: "project:crabwatch" in get_special_agents() → False
  → falls through to gateway path
  → solo DM path detects solo_target = "special:coder"
  → self._gw.send_message("special:coder", text)  ← WRONG: goes to gateway
  → gateway creates session "agent:main:special:coder"
  → response arrives with key "agent:main:special:coder"
  → no tab found → message lost
```

**Expected path:**
```
chat_handler.on_send("project:crabwatch", text)
  → solo DM path detects solo_target = "special:coder"
  → detects special agent → routes through AgentRuntimeHandler
  → self._agent_runtime_handler.send_to_special_agent("special:coder", text)
  → response rendered in project group chat tab
```

**Fix location:** `ui/handlers/chat_handler.py`, solo DM path (around lines 348-356)

**Fix approach:** In the solo DM path, check if `solo_target` is a registered special agent. If so, route through `AgentRuntimeHandler.send_to_special_agent()` instead of `self._gw.send_message()`.

---

## BUG #2 — MEDIUM

**Assumption violated:** "The project group chat tab can display responses for any session key"

**Root cause:** Even after fixing Bug #1, the solo DM path needs to handle the special case where the response comes from AgentRuntimeHandler (not gateway) and render it in the project group chat tab. Currently, AgentRuntimeHandler callbacks route to a chat box looked up by the special agent's session key (`special:coder`), but the user is typing in a project group chat tab (`project:crabwatch`).

**Fix location:** `ui/handlers/agent_runtime_handler.py`, callback routing

**Fix approach:** When a message is sent from a project group chat context, AgentRuntimeHandler's callbacks (`_do_text_delta`, `_do_response_complete`, `_do_error`) need to render into the project group chat box, not look up a tab by the special agent's session key.

---

## Related Files

| File | Role |
|------|------|
| `ui/handlers/chat_handler.py` | Message routing — lines 156 (special agent check), 348-356 (solo DM path) |
| `ui/handlers/agent_runtime_handler.py` | Special agent runtime — `send_to_special_agent()`, callback rendering |
| `ui/handlers/project_handler.py` | Solo DM target management — `get_solo_target()`, `set_solo_target()` |
| `agent/special_agents.py` | Special agent definitions — `conv_id_prefix="special:coder"` |

## Test Coverage

No automated tests exist for this path. Manual reproduction steps documented above.
