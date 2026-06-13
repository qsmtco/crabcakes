# Smarter Chat UX — Agent Event Bubbles + Missing Message Fix

**Date:** 2026-05-21
**Authors:** Qaster (with Captain JAQx)
**Status:** Draft — Awaiting approval

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — **Phase 1 (missing message recovery bug fix) is DONE** and shipped. `chat_handler.py:60-68` has `_assistant_text_buffer` dict and `_chat_final_rendered` guard; `_buffer_assistant_text()` and `_clear_render_guard()` methods exist; the missing-message recovery is in `chat_handler.py:68,131` (Phase 1 implemented by QTR, revised by Qaster). **Phase 2 (activity bubbles for tool calls, plan updates, approvals, command output, file edits) was ABANDONED** — the `SPEC-smarter-chat-ux.md` spec itself says "Phase 1 implemented — spec archived" and "Implementation Divergence Note: Phase 2 was replaced by activity-drawer." The production approach is now `ui/views/activity_drawer.py` (32K). Additionally, the `if not final_text: return` bug (Phase 1's sibling bug) was **NOT fixed** — `chat_handler.py:568-569` still has the early-return that silently drops empty final events. **Marked PARTIAL; Phase 1 done, Phase 2 abandoned, a related bug still open.**
**Repository:** github.com/qsmtco/crabcakes
**Depends on:** None (standalone)

---

## Problem Statement

### Bug: Assistant messages occasionally don't appear in chat

The gateway sends `chat` `final` events with no `message` field when the assistant text wasn't buffered before lifecycle end. CrabCakes silently drops these (line 502-504 in `chat_handler.py` — `if not final_text: return`). The user sees nothing. The agent finished, but the response is lost.

**Root cause confirmed from gateway source** (`server-chat-Bvm45tyg.js` `emitChatFinal()`):
```javascript
message: text && !shouldSuppressSilent ? { ... } : void 0
```
When `text` is empty (buffer not populated in time), `message` is `undefined`.

### UX Gap: User has no visibility into what the agent is doing

While an agent runs, the user sees only a spinner/progress bar (from `ActivityHandler`). The gateway is sending a rich stream of events — tool calls, tool results, thinking, plan updates, command output, errors — but CrabCakes ignores almost all of it. The user sits there wondering: "Is it working? Did it hang? What's taking so long?"

---

## Gateway Event Catalog (what we have to work with)

The gateway sends `agent` events with these `stream` types:

| Stream | What it carries | Data fields |
|--------|----------------|-------------|
| `lifecycle` | Run start/end/error | `phase` (start/end/error), `startedAt`, `endedAt`, `stopReason`, `livenessState` |
| `assistant` | Cumulative assistant text | `text` (full text so far), `delta` (new text since last) |
| `thinking` | Reasoning/thinking text | `text`, `delta` |
| `tool` | Tool invocations | `phase` (start/update/end), `name`, `args`, `result`, `durationMs` |
| `item` | High-level run items | `phase` (start/end), `itemId`, `kind`, `title`, `name` |
| `plan` | Plan updates (from `update_plan`) | `phase`, `title`, `explanation`, `steps[]`, `source` |
| `approval` | Exec approval requests | `phase`, `kind`, `command`, `host`, `reason`, `approvalId` |
| `command_output` | Shell command output | `phase` (start/end), `name`, `output`, `exitCode`, `durationMs`, `cwd` |
| `patch` | File edit summaries | `phase`, `name`, `added[]`, `modified[]`, `deleted[]` |
| `error` | Sequence gaps / protocol errors | `reason`, `expected`, `received` |

Additionally, the gateway sends `chat` events:
| State | What it carries |
|-------|----------------|
| `delta` | `deltaText` (throttled to 150ms), `message` with cumulative text |
| `final` | `message` with final text, `stopReason` |
| `error` | `errorMessage`, `errorKind` |

**Current CrabCakes usage:** Only `chat` events with `state: "final"` → bubble render. Everything else is ignored or used only for the progress bar.

---

## Proposal

### Part 1: Bug Fix — Lifecycle End Renders Buffered Assistant Text

**Problem:** `chat` `final` arrives with no `message`, CrabCakes drops it, user sees nothing.

**Fix:** Buffer the last `stream: "assistant"` text in `ActivityHandler`. When `lifecycle` `phase: "end"` fires, check if a chat final was already rendered for this `runId`. If not, render the buffered text as a fallback bubble.

**Implementation:**

In `activity_handler.py`:
```python
# New state
_assistant_text_buffer: dict[str, str] = {}  # session_key → last assistant text
_chat_final_rendered: dict[str, bool] = {}    # run_id → whether chat final rendered

def on_gateway_event(self, event, payload):
    # ... existing code ...

    # NEW: Buffer assistant text
    if event == "agent":
        stream = payload.get("stream", "")
        if stream == "assistant":
            text = payload.get("data", {}).get("text", "")
            if text:
                session_key = payload.get("sessionKey", "")
                self._assistant_text_buffer[session_key] = text

        elif stream == "lifecycle":
            phase = payload.get("data", {}).get("phase", "")
            if phase == "end":
                session_key = payload.get("sessionKey", "")
                run_id = payload.get("runId", "")
                # If no chat final rendered for this run, render fallback
                if not self._chat_final_rendered.get(run_id):
                    text = self._assistant_text_buffer.get(session_key, "")
                    if text:
                        self._render_fallback_bubble(session_key, text)
                # Cleanup
                self._assistant_text_buffer.pop(session_key, None)
                self._chat_final_rendered.pop(run_id, None)

    # NEW: Track when chat final renders (so we don't double-render)
    elif event == "chat":
        state = payload.get("state", "")
        if state == "final":
            run_id = payload.get("runId", "")
            self._chat_final_rendered[run_id] = True
```

The `_render_fallback_bubble` callback routes to `ChatHandler._handle_final_response()` using the same path as a normal `chat` final — just triggered from the lifecycle end instead.

**Why this works:** If the `chat` final arrives normally (with a message), `chat_handler` renders it and `_chat_final_rendered` is set to True. The lifecycle end handler sees True and skips. If the `chat` final never arrives or arrives with no message, the lifecycle end handler catches it with the buffered text.

### Part 2: Agent Activity Bubbles

**Design philosophy:** Show the user what's happening without overwhelming them. System bubbles are lightweight, monospace-styled, and auto-collapse when the final answer arrives. Think of them as a "build log" that shows while running and tucks away when done.

#### What to show (and what NOT to show)

| Event | Show? | How | Rationale |
|-------|-------|-----|-----------|
| `lifecycle` phase=start | ✅ | Brief "⏳ Working..." system bubble | Confirms agent started |
| `tool` phase=start | ✅ | "🔧 Running {name}..." system bubble | Shows progress — user knows what tool is active |
| `tool` phase=end | ✅ | Update the tool bubble: "✅ {name} ({durationMs}ms)" | Confirms tool completed |
| `tool` phase=end with error | ✅ | "❌ {name} — error" | Important to surface |
| `plan` | ✅ | "📋 Plan: {title}" + step list | Shows agent's intended steps |
| `approval` phase=requested | ✅ | "🔒 Approval needed: {command}" | Critical — user may need to act |
| `command_output` phase=end | ✅ (brief) | "💻 {name}: exit {exitCode} ({durationMs}ms)" | Useful for exec_command visibility |
| `patch` phase=end | ✅ (brief) | "✏️ {name}: +{added} ~{modified} -{deleted} files" | Shows what changed |
| `thinking` | ❌ | Skip | Too noisy, not meaningful to user |
| `assistant` (delta text) | ❌ | Skip (we already handle via `chat` events) | Redundant with existing chat stream |
| `item` phase=start | ⚠️ Optional | Only if `title` is present | Some items are too low-level |
| `error` (seq gap) | ❌ | Skip | Internal protocol detail |
| `command_output` phase=start | ❌ | Skip | End is enough |
| `tool` phase=update | ❌ | Skip | Too noisy (intermediate progress) |

#### Visual Design

System bubbles use a distinct visual style — muted background, monospace font, smaller text. They're clearly NOT part of the conversation. They're ephemeral status indicators.

```
┌─────────────────────────────────────────────────┐
│ ⏳ Agent started...                              │  ← system bubble
├─────────────────────────────────────────────────┤
│ 🔧 Running web_search...                        │  ← system bubble  
│ ✅ web_search (1,247ms)                         │  ← system bubble (updated)
│ 🔧 Running read_file...                         │  ← system bubble
│ ✅ read_file (83ms)                             │  ← system bubble (updated)
│ 🔧 Running exec_command...                      │  ← system bubble
│ 💻 exec_command: exit 0 (4,521ms)              │  ← system bubble (updated)
│ ✏️ edit_file: +1 ~3 -0 files                   │  ← system bubble
├─────────────────────────────────────────────────┤
│ 🤖 Here's the analysis you requested...          │  ← normal assistant bubble
│                                                  │
│ The code in question has three issues...         │
└─────────────────────────────────────────────────┘
```

#### Post-Answer Behavior

When the final assistant message renders, all system bubbles from that run can optionally collapse to a single summary line:

```
│ 🔧 3 tools ran in 5.9s — expand for details    │  ← collapsed
```

Clicking expands back to the full list. This keeps the chat scrollable when agents do many tool calls. This is a polish feature — implement in Phase 2.

#### Configuration

Per-agent toggle in agent YAML:
```yaml
show_activity_bubbles: true   # default true — set false to disable
```

And a global preference in CrabCakes config:
```json
{
  "chat": {
    "activity_bubbles": true,
    "collapse_after_answer": true
  }
}
```

---

## Implementation Plan

### Phase 1 — Bug Fix (do this first)

| File | Change |
|------|--------|
| `ui/handlers/activity_handler.py` | Buffer `stream: "assistant"` text; on `lifecycle` `phase: "end"`, render fallback if no `chat` final arrived |
| `ui/handlers/chat_handler.py` | Add `mark_chat_final_rendered(run_id)` method so ActivityHandler can track whether a chat final already rendered |
| `ui/window.py` | Wire ActivityHandler fallback render callback to ChatHandler |
| `tests/test_activity_bubbles.py` | Tests for the fallback render path |

**Effort:** ~2-3 hours

### Phase 2 — Activity Bubbles

| File | Change |
|------|--------|
| `ui/handlers/activity_handler.py` | New `on_agent_activity()` method — processes tool, plan, approval, command_output, patch events into activity bubble data |
| `ui/handlers/chat_handler.py` | New `_render_activity_bubble()` method — creates system-styled bubbles |
| `ui/views/chat_render_handler.py` | New bubble style: muted background, smaller font, system icon prefix |
| `ui/views/main_content.py` | (minimal) pass-through if needed |
| `ui/window.py` | Wire ActivityHandler activity events to ChatHandler render |
| `models/activity.py` | New — `ActivityBubble` dataclass (type, tool_name, duration, status, etc.) |
| `ui/styles.py` | CSS for `.activity-bubble`, `.activity-collapsed` |

**Effort:** ~4-5 hours

### Phase 3 — Polish (optional, later)

- Collapse system bubbles into summary after answer
- Expand/collapse toggle on collapsed summary
- Show activity count badge on tab while running
- Per-agent and global config for activity bubbles

---

## What This Gives Us

1. **No more lost messages.** The lifecycle-end fallback catches every case where `chat` final fails.
2. **User confidence.** The user sees tool calls happening in real-time — they know the agent is working, not hung.
3. **Debugging visibility.** When something goes wrong, the system bubbles show exactly which tool failed and when.
4. **Future extensibility.** The `ActivityBubble` model and render pipeline can be extended to show more event types (thinking summaries, approval flows, etc.) without architectural changes.

---

## Appendix: Gateway Event Examples (for reference)

These are the actual payloads CrabCakes receives via WebSocket:

### Agent lifecycle start
```json
{
  "type": "event", "event": "agent",
  "payload": {
    "runId": "69959879-c6ac-4896-bf49-8cd43c3a2f96",
    "stream": "lifecycle",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 1, "ts": 1779378412345,
    "data": { "phase": "start", "startedAt": 1779378412345 }
  }
}
```

### Agent tool start
```json
{
  "type": "event", "event": "agent",
  "payload": {
    "runId": "69959879-...",
    "stream": "tool",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 15, "ts": 1779378412600,
    "data": {
      "phase": "start",
      "name": "web_search",
      "args": { "query": "MCP transport comparison" }
    }
  }
}
```

### Agent tool end
```json
{
  "type": "event", "event": "agent",
  "payload": {
    "runId": "69959879-...",
    "stream": "tool",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 16, "ts": 1779378413847,
    "data": {
      "phase": "end",
      "name": "web_search",
      "durationMs": 1247,
      "result": { "count": 5 }
    }
  }
}
```

### Agent assistant text (cumulative)
```json
{
  "type": "event", "event": "agent",
  "payload": {
    "runId": "69959879-...",
    "stream": "assistant",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 884, "ts": 1779378415234,
    "data": {
      "text": "Here's my take on the transport question...",
      "delta": "the transport question..."
    }
  }
}
```

### Agent lifecycle end
```json
{
  "type": "event", "event": "agent",
  "payload": {
    "runId": "69959879-...",
    "stream": "lifecycle",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 885, "ts": 1779378415655,
    "data": {
      "phase": "end",
      "endedAt": 1779378415655,
      "stopReason": "stop",
      "livenessState": "working"
    }
  }
}
```

### Chat final (the one that sometimes has no message)
```json
{
  "type": "event", "event": "chat",
  "payload": {
    "runId": "69959879-...",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 3,
    "state": "final",
    "stopReason": "stop",
    "message": {
      "role": "assistant",
      "content": [{ "type": "text", "text": "Here's my take..." }],
      "timestamp": 1779378415655
    }
  }
}
```

When the bug hits, that last event looks like:
```json
{
  "type": "event", "event": "chat",
  "payload": {
    "runId": "69959879-...",
    "sessionKey": "agent:qaster:telegram:direct:7478874934",
    "seq": 3,
    "state": "final",
    "stopReason": "stop"
    // ← no "message" field at all
  }
}
```

CrabCakes calls `self._extract_text(msg_obj)` on the missing message → gets empty string → `return` → bubble never renders.
