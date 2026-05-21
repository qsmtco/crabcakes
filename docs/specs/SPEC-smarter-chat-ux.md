# SPEC: Smarter Chat UX — Bug Fix + Activity Bubbles

**Date:** 2026-05-21
**Author:** Qaster
**Status:** Phase 1 implemented — spec archived (see implementation notes below)
**Implements:** `docs/proposals/PROPOSAL-smarter-chat-ux.md`
**Target branch:** main (or feature branch)

> **⚠️ Implementation Divergence Note (2026-05-21):**
> Phase 1 was implemented by QTR and then revised by Qaster after adversarial review.
> The key architectural change: `_chat_final_rendered` guard and render decisions moved
> from ActivityHandler to ChatHandler. ActivityHandler now only tracks state and fires
> callbacks; ChatHandler owns all rendering. A `set_on_agent_start(cb)` callback was
> added to clear the render guard between rounds. See ARCHITECTURE.md §3.14 and §3.23
> for the authoritative current API. The code sections below describe the original spec
> and are kept for historical reference only.

---

## Overview

Two changes to CrabCakes chat:

1. **Phase 1 — Bug Fix:** Assistant messages sometimes never appear. Fix by rendering a fallback bubble from buffered `agent` event text when the `chat` `final` event arrives empty.
2. **Phase 2 — Activity Bubbles:** Show lightweight system bubbles for tool calls, plan updates, approvals, command output, and file edits — so the user sees the agent working instead of staring at a blank chat.

---

## Phase 1: Bug Fix — Missing Assistant Messages

### 1.1 Root Cause

The gateway sends `chat` events with `state: "final"` for bubble rendering. Sometimes the `message` field is `undefined` (empty) because the gateway's internal text buffer wasn't populated before lifecycle end. CrabCakes silently drops these:

```python
# chat_handler.py line ~502-504
elif state == "final":
    final_text = self._extract_text(msg_obj)
    if not final_text:
        return   # ← SILENTLY DROPPED — the user sees nothing
```

Meanwhile, the gateway ALSO sends the full assistant text as `agent` events with `stream: "assistant"`, which CrabCakes currently ignores entirely.

### 1.2 Fix Strategy

Buffer the last `stream: "assistant"` text. When `lifecycle` `phase: "end"` fires, check if a `chat` `final` already rendered for that `runId`. If not, render the buffered text as a fallback bubble.

### 1.3 Files to Modify

#### File 1: `ui/handlers/activity_handler.py`

**Add new instance variables** in `__init__` (after line ~48, alongside other dict declarations):

```python
# Bug fix: fallback rendering when chat final has no message
self._assistant_text_buffer: dict[str, str] = {}    # session_key → last assistant text
self._chat_final_rendered: dict[str, bool] = {}     # run_id → True when chat final rendered
self._on_fallback_render = None                      # callback set by window.py
```

**Add public setter** (after `__init__`, alongside other setter methods):

```python
def set_on_fallback_render(self, cb):
    """Set callback for fallback bubble render: cb(session_key, text).

    Called when lifecycle end fires but no chat final rendered.
    Wired by window.py to ChatHandler._handle_final_response().
    """
    self._on_fallback_render = cb
```

**Modify `on_gateway_event()`** (currently at line ~129). Add new logic inside the existing `if event == "agent":` block. Here's the exact insertion point — the method currently has this structure:

```python
def on_gateway_event(self, event, payload):
    # ... phase 2 progress tracking (lines 130-145) ...

    if event == "agent":
        stream = payload.get("stream", "")
        if stream == "lifecycle":
            phase = payload.get("data", {}).get("phase", "")
        else:
            phase = payload.get("phase", "")
        if phase == "start":
            self.on_agent_start(session_key, payload)
        elif phase == "end":
            self.on_agent_end(session_key, payload)    # ← EXISTING
        elif phase == "error":
            self.on_agent_error(session_key)
    elif event == "chat":
        # ... existing chat handling ...
```

**New logic to add** — insert BEFORE the existing `if event == "agent":` block:

```python
    # ── Bug fix: buffer assistant text for fallback rendering ──────────
    if event == "agent":
        stream = payload.get("stream", "")
        if stream == "assistant":
            text = payload.get("data", {}).get("text", "")
            if text:
                sk = payload.get("sessionKey", "")
                if sk:
                    self._assistant_text_buffer[sk] = text
        elif stream == "lifecycle":
            phase = payload.get("data", {}).get("phase", "")
            if phase == "end":
                run_id = payload.get("runId", "")
                sk = payload.get("sessionKey", "")
                if run_id and not self._chat_final_rendered.get(run_id):
                    text = self._assistant_text_buffer.get(sk, "")
                    if text and self._on_fallback_render:
                        _logger.info("[fallback] Rendering fallback bubble for runId=%s session=%s (%d chars)", run_id, sk, len(text))
                        # Resolve target tab same way ChatHandler does
                        project_name = self._mc._agent_to_project.get_project(sk) if hasattr(self._mc, '_agent_to_project') and self._mc._agent_to_project else None
                        target_tab = f"project:{project_name}" if project_name else sk
                        self._on_fallback_render(target_tab, sk, text)
                # Cleanup
                if sk:
                    self._assistant_text_buffer.pop(sk, None)
                if run_id:
                    self._chat_final_rendered.pop(run_id, None)

    # ── Bug fix: track chat final renders to avoid double-rendering ────
    if event == "chat":
        state = payload.get("state", "")
        if state == "final":
            run_id = payload.get("runId", "")
            if run_id:
                self._chat_final_rendered[run_id] = True
    # ── End bug fix additions ──────────────────────────────────────────
```

**IMPORTANT:** The above new blocks go BEFORE the existing `if event == "agent":` routing block. The existing block continues to work unchanged — it handles state machine transitions. The new blocks only add buffering and tracking.

**Add `_logger` import** at the top of the file if not already present:
```python
import logging
_logger = logging.getLogger(__name__)
```

#### File 2: `ui/window.py`

**In `_build()` method**, after the ActivityHandler is created (around line ~370-395), add wiring:

```python
# Wire fallback render: ActivityHandler → ChatHandler
self._activity_handler.set_on_fallback_render(
    lambda tab, sk, text: self._chat_handler._handle_final_response(tab, sk, text)
)
```

Find the exact insertion point by looking for where other ActivityHandler wiring happens. Search for `set_on_agent_start` or `set_on_agent_end` in window.py — the new wiring goes in the same section.

**Why a lambda:** `_handle_final_response` expects `(tab, session_key, text)` but is a method on `self._chat_handler`. The lambda bridges the two.

#### File 3: `tests/test_missing_message_fix.py` (NEW FILE)

```python
# tests/test_missing_message_fix.py
# Tests for the fallback render path when chat final has no message.

import pytest
from unittest.mock import MagicMock, patch


class TestAssistantTextBuffer:
    """ActivityHandler should buffer agent stream=assistant text."""

    def test_buffer_stores_last_text(self):
        """Multiple assistant events — buffer keeps the last one."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        
        handler.on_gateway_event("agent", {
            "stream": "assistant",
            "sessionKey": "agent:test:1",
            "runId": "run-1",
            "data": {"text": "Hello"}
        })
        handler.on_gateway_event("agent", {
            "stream": "assistant",
            "sessionKey": "agent:test:1",
            "runId": "run-1",
            "data": {"text": "Hello world, here is the full response."}
        })
        
        assert handler._assistant_text_buffer.get("agent:test:1") == "Hello world, here is the full response."

    def test_buffer_per_session(self):
        """Different sessions have independent buffers."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        
        handler.on_gateway_event("agent", {
            "stream": "assistant", "sessionKey": "sk-1", "runId": "r1",
            "data": {"text": "Response for session 1"}
        })
        handler.on_gateway_event("agent", {
            "stream": "assistant", "sessionKey": "sk-2", "runId": "r2",
            "data": {"text": "Response for session 2"}
        })
        
        assert handler._assistant_text_buffer["sk-1"] == "Response for session 1"
        assert handler._assistant_text_buffer["sk-2"] == "Response for session 2"


class TestChatFinalTracking:
    """ActivityHandler should track when chat final renders."""

    def test_chat_final_marks_run_id(self):
        """Receiving chat final marks the runId as rendered."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        
        handler.on_gateway_event("chat", {
            "state": "final",
            "runId": "run-abc",
            "sessionKey": "sk-1"
        })
        
        assert handler._chat_final_rendered.get("run-abc") is True

    def test_lifecycle_end_skips_when_chat_final_rendered(self):
        """If chat final already rendered, lifecycle end does NOT call fallback."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        fallback = MagicMock()
        handler.set_on_fallback_render(fallback)
        
        # Buffer text
        handler.on_gateway_event("agent", {
            "stream": "assistant", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"text": "Hello world"}
        })
        # Chat final renders (with message — normal path)
        handler.on_gateway_event("chat", {
            "state": "final", "runId": "run-1", "sessionKey": "sk-1"
        })
        # Lifecycle end
        handler.on_gateway_event("agent", {
            "stream": "lifecycle", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"phase": "end"}
        })
        
        fallback.assert_not_called()

    def test_lifecycle_end_renders_fallback_when_no_chat_final(self):
        """If no chat final arrived, lifecycle end calls fallback with buffered text."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        fallback = MagicMock()
        handler.set_on_fallback_render(fallback)
        
        # Buffer text
        handler.on_gateway_event("agent", {
            "stream": "assistant", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"text": "This is the full response"}
        })
        # Lifecycle end — NO chat final event arrived
        handler.on_gateway_event("agent", {
            "stream": "lifecycle", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"phase": "end"}
        })
        
        fallback.assert_called_once_with("sk-1", "sk-1", "This is the full response")

    def test_lifecycle_end_no_fallback_when_no_buffered_text(self):
        """If no assistant text was buffered, no fallback (empty response is valid)."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        fallback = MagicMock()
        handler.set_on_fallback_render(fallback)
        
        # Lifecycle end with no prior assistant events
        handler.on_gateway_event("agent", {
            "stream": "lifecycle", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"phase": "end"}
        })
        
        fallback.assert_not_called()

    def test_cleanup_after_lifecycle_end(self):
        """Buffer and tracking cleaned up after lifecycle end."""
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock())
        handler.set_on_fallback_render(MagicMock())
        
        handler.on_gateway_event("agent", {
            "stream": "assistant", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"text": "Hello"}
        })
        handler.on_gateway_event("agent", {
            "stream": "lifecycle", "sessionKey": "sk-1", "runId": "run-1",
            "data": {"phase": "end"}
        })
        
        assert "sk-1" not in handler._assistant_text_buffer
        assert "run-1" not in handler._chat_final_rendered
```

### 1.4 Verification Steps

1. Run the new tests: `cd /home/q/projects/crabcakes && python -m pytest tests/test_missing_message_fix.py -v`
2. Run the full test suite: `python -m pytest tests/ -v`
3. Manual test: Start CrabCakes in debug mode, send a message to an agent, verify the response appears as a bubble. Then check terminal logs for `[fallback]` messages to confirm the path is working (it should NOT trigger on normal runs — only when chat final has no message).

### 1.5 Edge Cases to Consider

- **Empty assistant response:** Some agent runs produce no text (e.g., `NO_REPLY`). No assistant event fires, buffer is empty, no fallback renders. This is correct behavior.
- **Multiple runs on same session:** Each run has a unique `runId`. Buffer is keyed by `sessionKey` (overwritten per run), tracking is keyed by `runId`. Cleanup happens on lifecycle end.
- **Agent events arrive but no lifecycle end:** Buffer stays populated. No harm — it gets overwritten on the next run for that session, or cleaned up when lifecycle end eventually fires.
- **Race between chat final and lifecycle end:** Both arrive via `GLib.idle_add` and are processed sequentially on the GTK main thread. No actual race — whichever arrives first sets the state, the second sees it.

---


## Phase 2: Activity Bubbles

> **Updated:** 2026-05-21 by Qaster. Rewritten to match current architecture after Phase 1 adversarial review.
> **Key change:** ActivityHandler fires callbacks → ChatHandler renders. ActivityHandler never renders directly.
> The `set_on_activity_bubble(cb)` callback follows the same pattern as `set_on_assistant_buffer`, `set_on_lifecycle_completed`, and `set_on_agent_start`.

### 2.1 Concept

When the gateway sends `agent` events for tool calls, plans, approvals, etc., render lightweight "system bubbles" inline in the chat. These are NOT conversation messages — they're ephemeral status indicators that show the user what's happening.

**Gateway event catalog** (from `docs/proposals/PROPOSAL-smarter-chat-ux.md`):

| Stream | What it carries | Data fields |
|--------|----------------|-------------|
| `lifecycle` | Run start/end/error | `phase` (start/end/error), `startedAt`, `endedAt`, `stopReason` |
| `tool` | Tool invocations | `phase` (start/update/end), `name`, `args`, `result`, `durationMs` |
| `plan` | Plan updates | `phase`, `title`, `explanation`, `steps[]`, `source` |
| `approval` | Exec approval requests | `phase`, `kind`, `command`, `host`, `reason`, `approvalId` |
| `command_output` | Shell command output | `phase` (start/end), `name`, `output`, `exitCode`, `durationMs`, `cwd` |
| `patch` | File edit summaries | `phase`, `name`, `added[]`, `modified[]`, `deleted[]` |

All of these arrive as `event == "agent"` with `payload.stream` set to the stream type. ActivityHandler already handles `lifecycle` and `assistant` streams for Phase 1. Phase 2 adds handling for `tool`, `plan`, `approval`, `command_output`, and `patch`.

### 2.2 New File: `models/activity.py`

**No changes from original spec.** This file is a pure data model — no dependency on handler architecture. Use the original spec's `ActivityType` enum and `ActivityBubble` dataclass exactly as written.

Key details:
- `ActivityType` enum: `TOOL_START`, `TOOL_END`, `TOOL_ERROR`, `PLAN`, `APPROVAL`, `COMMAND_OUTPUT`, `PATCH`, `AGENT_START`
- `ActivityBubble` dataclass with `format_text()` method that returns display string
- Inline import in handlers (lazy) to avoid circular deps

<details>
<summary>Full models/activity.py code (click to expand)</summary>

```python
# models/activity.py
# Data model for activity bubbles — ephemeral status indicators in chat.

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ActivityType(Enum):
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    PLAN = "plan"
    APPROVAL = "approval"
    COMMAND_OUTPUT = "command_output"
    PATCH = "patch"
    AGENT_START = "agent_start"


@dataclass
class ActivityBubble:
    """A single activity event to display as a system bubble."""
    activity_type: ActivityType
    session_key: str
    run_id: str

    # Tool events
    tool_name: str = ""
    duration_ms: int = 0

    # Plan events
    plan_title: str = ""
    plan_steps: list[str] = field(default_factory=list)

    # Approval events
    approval_command: str = ""
    approval_host: str = ""

    # Command output events
    exit_code: int | None = None
    cwd: str = ""

    # Patch events
    files_added: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        """Return the display text for this activity bubble."""
        if self.activity_type == ActivityType.AGENT_START:
            return "⏳ Agent working..."
        elif self.activity_type == ActivityType.TOOL_START:
            return f"🔧 {self.tool_name}..."
        elif self.activity_type == ActivityType.TOOL_END:
            ms = self._format_duration(self.duration_ms)
            return f"✅ {self.tool_name} ({ms})"
        elif self.activity_type == ActivityType.TOOL_ERROR:
            return f"❌ {self.tool_name} — error"
        elif self.activity_type == ActivityType.PLAN:
            steps_text = ""
            if self.plan_steps:
                step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(self.plan_steps[:8]))
                if len(self.plan_steps) > 8:
                    step_list += f"\n  ... +{len(self.plan_steps) - 8} more"
                steps_text = f"\n{step_list}"
            return f"📋 {self.plan_title}{steps_text}"
        elif self.activity_type == ActivityType.APPROVAL:
            host = f" on {self.approval_host}" if self.approval_host else ""
            return f"🔒 Approval needed: {self.approval_command}{host}"
        elif self.activity_type == ActivityType.COMMAND_OUTPUT:
            ms = self._format_duration(self.duration_ms)
            code = self.exit_code if self.exit_code is not None else "?"
            return f"💻 {self.tool_name}: exit {code} ({ms})"
        elif self.activity_type == ActivityType.PATCH:
            a, m, d = len(self.files_added), len(self.files_modified), len(self.files_deleted)
            parts = []
            if a: parts.append(f"+{a}")
            if m: parts.append(f"~{m}")
            if d: parts.append(f"-{d}")
            summary = " ".join(parts) if parts else "no changes"
            return f"✏️ {self.tool_name}: {summary} files"
        return ""

    @staticmethod
    def _format_duration(ms: int) -> str:
        if ms <= 0:
            return "?"
        if ms < 1000:
            return f"{ms}ms"
        return f"{ms / 1000:.1f}s"
```

</details>

### 2.3 Modify: `ui/handlers/activity_handler.py`

**Architecture:** ActivityHandler only tracks state and fires callbacks. It never renders. ChatHandler receives the callback and makes all render decisions.

#### 2.3.1 Add to `__init__`

After the existing Phase 1 callbacks (around line 60):

```python
# Activity bubbles (Phase 2)
self._on_activity_bubble: Callable[[object, str], None] | None = None  # cb(ActivityBubble, target_tab)
```

The type hint uses `object` instead of `ActivityBubble` to avoid importing the model at module level (lazy import pattern).

#### 2.3.2 Add setter

After the existing `set_on_agent_start()` method (around line 140):

```python
def set_on_activity_bubble(self, cb):
    """Set callback for activity bubble: cb(activity: ActivityBubble, target_tab: str).

    ActivityHandler calls this for tool/plan/approval/command_output/patch events.
    ChatHandler receives the callback and renders the bubble.

    Architecture: same callback pattern as set_on_assistant_buffer and
    set_on_lifecycle_completed — ActivityHandler fires, ChatHandler renders.
    """
    self._on_activity_bubble = cb
```

#### 2.3.3 Add to `on_gateway_event()`

**Where:** Inside the existing `if event == "agent":` block, AFTER the Phase 1 bug-fix code (assistant buffer + lifecycle completed) and BEFORE the "Route to state-transition handlers" comment (around line 227).

The activity bubble code runs on EVERY `agent` event that has a relevant `stream` value. It sits in the same `if event == "agent":` block that already handles `stream == "assistant"` and `stream == "lifecycle"`.

**What to add** — a new block that checks for activity-bubble streams and fires the callback:

```python
            # ── Activity bubbles (Phase 2) ────────────────────────────────
            if self._on_activity_bubble and stream in ("tool", "plan", "approval", "command_output", "patch"):
                data = payload.get("data", {})
                sk = payload.get("sessionKey", "") or session_key
                run_id = payload.get("runId", "") or ""
                # Resolve target tab — same routing logic as ChatHandler._route_chat_event()
                target_tab = sk
                if self._agent_to_project is not None:
                    project_name = self._agent_to_project.get_project(sk)
                    if project_name:
                        target_tab = f"project:{project_name}"

                from models.activity import ActivityBubble, ActivityType

                if stream == "tool":
                    phase = data.get("phase", "")
                    name = data.get("name", "")
                    if phase == "start":
                        self._on_activity_bubble(
                            ActivityBubble(
                                activity_type=ActivityType.TOOL_START,
                                session_key=sk, run_id=run_id,
                                tool_name=name,
                            ), target_tab
                        )
                    elif phase == "end":
                        is_error = data.get("isError", False)
                        bubble_type = ActivityType.TOOL_ERROR if is_error else ActivityType.TOOL_END
                        self._on_activity_bubble(
                            ActivityBubble(
                                activity_type=bubble_type,
                                session_key=sk, run_id=run_id,
                                tool_name=name,
                                duration_ms=data.get("durationMs", 0),
                            ), target_tab
                        )

                elif stream == "plan":
                    self._on_activity_bubble(
                        ActivityBubble(
                            activity_type=ActivityType.PLAN,
                            session_key=sk, run_id=run_id,
                            plan_title=data.get("title", ""),
                            plan_steps=data.get("steps", []),
                        ), target_tab
                    )

                elif stream == "approval":
                    phase = data.get("phase", "")
                    if phase == "requested":
                        self._on_activity_bubble(
                            ActivityBubble(
                                activity_type=ActivityType.APPROVAL,
                                session_key=sk, run_id=run_id,
                                approval_command=data.get("command", ""),
                                approval_host=data.get("host", ""),
                            ), target_tab
                        )

                elif stream == "command_output":
                    phase = data.get("phase", "")
                    if phase == "end":
                        self._on_activity_bubble(
                            ActivityBubble(
                                activity_type=ActivityType.COMMAND_OUTPUT,
                                session_key=sk, run_id=run_id,
                                tool_name=data.get("name", "exec"),
                                exit_code=data.get("exitCode"),
                                duration_ms=data.get("durationMs", 0),
                                cwd=data.get("cwd", ""),
                            ), target_tab
                        )

                elif stream == "patch":
                    phase = data.get("phase", "")
                    if phase == "end":
                        self._on_activity_bubble(
                            ActivityBubble(
                                activity_type=ActivityType.PATCH,
                                session_key=sk, run_id=run_id,
                                tool_name=data.get("name", "edit"),
                                files_added=data.get("added", []),
                                files_modified=data.get("modified", []),
                                files_deleted=data.get("deleted", []),
                            ), target_tab
                        )
```

**Important:** The `from models.activity import ...` is inline (inside the method) to avoid circular import issues at module load time.

#### 2.3.4 Tab routing reference

The `_agent_to_project` reference needs explanation. In the current codebase:

- `ActivityHandler.__init__` receives `main_content` as `self._mc`
- `main_content` does NOT have `_agent_to_project` directly — it's on `ChatHandler` as `self._agent_to_project`
- **But** `window.py` injects an `AgentRoutingTable` via `self._chat_handler._agent_to_project`
- ActivityHandler should receive its own reference to the routing table

**Change needed in `window.py`** (see §2.7): pass `agent_to_project` to ActivityHandler's constructor or add a setter.

**Simplest approach:** Add `agent_to_project` parameter to `ActivityHandler.__init__`:

```python
# In ActivityHandler.__init__ (add parameter):
def __init__(self, feedbar, main_content, GLib_module, agent_to_project=None):
    ...
    self._agent_to_project = agent_to_project  # AgentRoutingTable or None
```

Then in `window.py` (see §2.7), pass it:

```python
self._activity_handler = ActivityHandler(
    feedbar=self._main_content.feedbar,
    main_content=self._main_content,
    GLib_module=GLib,
    agent_to_project=self._agent_routing_table,  # same table ChatHandler uses
)
```

**Why not use `self._mc._agent_to_project`?** Because `MainContent` doesn't have `_agent_to_project`. It's on `ChatHandler`. Adding it to ActivityHandler's constructor is clean and testable.

### 2.4 Modify: `ui/handlers/chat_handler.py`

#### 2.4.1 Add new method `_render_activity_bubble()`

Add this as a public method (called from the callback wired in `window.py`):

```python
def render_activity_bubble(self, activity, target_tab: str):
    """Render an activity bubble in the chat.

    Activity bubbles are lightweight system-styled status indicators.
    They use distinct CSS classes to differentiate from conversation messages.

    Called by ActivityHandler's on_activity_bubble callback, wired in window.py.

    Args:
        activity: ActivityBubble instance (from models.activity)
        target_tab: tab key to render in (session key or "project:<name>")
    """
    text = activity.format_text()
    if not text:
        return

    chat_box = self._mc.get_chat_box_for_session(target_tab)
    if chat_box is None:
        return

    if self._chat_render_handler is None:
        return

    bubble = self._chat_render_handler.render_activity(text, activity.activity_type.value)
    if bubble is not None:
        chat_box.append(bubble)
        self._mc.scroll_chat_to_bottom()
```

**Thread safety:** `on_gateway_event()` runs on the main thread (dispatched via `GLib.idle_add` from the gateway client). The callback fires synchronously within that main-thread call. No additional `_dispatch` needed.

### 2.5 Modify: `ui/handlers/chat_render_handler.py`

#### 2.5.1 Add new method `render_activity()`

Add after the existing `render_event_card()` method (around line 680):

```python
def render_activity(self, text: str, activity_type: str = "") -> Gtk.Widget | None:
    """Render a lightweight activity bubble.

    Activity bubbles use muted styling and are clearly not conversation messages.
    Returns a Gtk.Box widget, or None on error.

    Args:
        text: Display text (already formatted by ActivityBubble.format_text())
        activity_type: ActivityType value string (for CSS class targeting)
    """
    try:
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        container.add_css_class("activity-bubble")
        if activity_type:
            container.add_css_class(f"activity-{activity_type}")

        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
        label.add_css_class("activity-bubble-text")
        label.add_css_class("monospace")
        label.add_css_class("caption")

        container.append(label)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(2)
        container.set_margin_bottom(2)
        return container
    except Exception as e:
        _logger.warning("Failed to render activity bubble: %s", e)
        return None
```

### 2.6 Modify: `ui/styles.py`

**Where:** In the existing CSS provider string, after the `.bubble-streaming` rule (around line 408) and before `.chat-bubble-actions`.

**Add:**

```css
/* Activity bubbles — ephemeral status indicators (Phase 2) */
.activity-bubble {
    background-color: alpha(@view_fg_color, 0.05);
    border-radius: 6px;
    padding: 4px 8px;
}
.activity-bubble-text {
    color: alpha(@view_fg_color, 0.6);
}
.activity-tool_error .activity-bubble-text {
    color: @error_color;
}
.activity-approval .activity-bubble-text {
    color: @warning_color;
}
```

**Fallback if `@view_fg_color` / `@error_color` / `@warning_color` don't resolve** (non-Adwaita themes):

```css
.activity-bubble {
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 6px;
    padding: 4px 8px;
}
.activity-bubble-text {
    color: rgba(255, 255, 255, 0.5);
}
.activity-tool_error .activity-bubble-text {
    color: #ef4444;
}
.activity-approval .activity-bubble-text {
    color: #f59e0b;
}
```

Use whichever set works with the current theme. The existing codebase uses both named colors and hex, so check the surrounding CSS for consistency.

### 2.7 Modify: `ui/window.py`

**Two changes:**

#### 2.7.1 Pass `agent_to_project` to ActivityHandler

Around line 199, change the ActivityHandler construction:

```python
# Before (current):
self._activity_handler = ActivityHandler(
    feedbar=self._main_content.feedbar,
    main_content=self._main_content,
    GLib_module=GLib,
)

# After:
self._activity_handler = ActivityHandler(
    feedbar=self._main_content.feedbar,
    main_content=self._main_content,
    GLib_module=GLib,
    agent_to_project=self._agent_routing_table,  # for activity bubble tab routing
)
```

**Note:** `self._agent_routing_table` is the `AgentRoutingTable` instance created in `_build()`. Check where it's defined — it might be `self._chat_handler._agent_to_project` or a local variable. Find the `AgentRoutingTable()` construction and ensure it's accessible.

#### 2.7.2 Wire the activity bubble callback

In `_sync_gateway_to_chat_handler()`, after the existing Phase 1 wiring (around line 710):

```python
# Wire activity bubbles: ActivityHandler → ChatHandler render
# Architecture: same callback pattern as Phase 1 — AH fires, CH renders.
self._activity_handler.set_on_activity_bubble(
    self._chat_handler.render_activity_bubble
)
```

### 2.8 New File: `tests/test_activity_bubbles.py`

```python
# tests/test_activity_bubbles.py
# Tests for Phase 2 activity bubbles (SPEC-smarter-chat-ux §2.8)

import pytest
from unittest.mock import MagicMock


# ── Fixtures ─────────────────────────────────────────────────────────────────

class FakeGLib:
    """Fake GLib for testing — runs callbacks immediately (no idle_add dispatch)."""
    def timeout_add(self, *a, **k): return 1
    def timeout_add_seconds(self, *a, **k): return 1
    def source_remove(self, tid): pass
    def idle_add(self, fn, *a, **k): fn(*a); return 1


@pytest.fixture
def fake_glib():
    return FakeGLib()


def _make_handler(agent_to_project=None, fake_glib=None):
    """Create an ActivityHandler with test defaults."""
    from ui.handlers.activity_handler import ActivityHandler
    mc = MagicMock()
    mc.get_current_session_key = MagicMock(return_value=None)
    return ActivityHandler(
        feedbar=MagicMock(), main_content=mc, GLib_module=fake_glib or FakeGLib(),
        agent_to_project=agent_to_project,
    )


# ── ActivityBubble model tests ───────────────────────────────────────────────

class TestActivityBubbleModel:
    """Test models/activity.py — format_text() output."""

    def test_tool_start_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.TOOL_START, session_key="sk", run_id="r", tool_name="read")
        assert "read" in b.format_text()
        assert "🔧" in b.format_text()

    def test_tool_end_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.TOOL_END, session_key="sk", run_id="r",
                           tool_name="exec", duration_ms=2500)
        text = b.format_text()
        assert "exec" in text
        assert "2.5s" in text

    def test_tool_error_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.TOOL_ERROR, session_key="sk", run_id="r", tool_name="edit")
        assert "❌" in b.format_text()

    def test_plan_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.PLAN, session_key="sk", run_id="r",
                           plan_title="Build feature", plan_steps=["Step 1", "Step 2"])
        text = b.format_text()
        assert "Build feature" in text
        assert "Step 1" in text

    def test_approval_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.APPROVAL, session_key="sk", run_id="r",
                           approval_command="rm -rf /", approval_host="sandbox")
        text = b.format_text()
        assert "rm -rf /" in text
        assert "sandbox" in text

    def test_command_output_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.COMMAND_OUTPUT, session_key="sk", run_id="r",
                           tool_name="exec", exit_code=0, duration_ms=500)
        text = b.format_text()
        assert "exit 0" in text
        assert "500ms" in text

    def test_patch_text(self):
        from models.activity import ActivityBubble, ActivityType
        b = ActivityBubble(activity_type=ActivityType.PATCH, session_key="sk", run_id="r",
                           tool_name="edit", files_added=["a.py"], files_modified=["b.py", "c.py"])
        text = b.format_text()
        assert "+1" in text
        assert "~2" in text

    def test_format_duration_zero(self):
        from models.activity import ActivityBubble
        assert ActivityBubble._format_duration(0) == "?"
        assert ActivityBubble._format_duration(500) == "500ms"
        assert ActivityBubble._format_duration(1500) == "1.5s"


# ── ActivityHandler callback tests ───────────────────────────────────────────

class TestActivityBubbleCallbacks:
    """Test ActivityHandler fires on_activity_bubble callback for each stream type."""

    def test_tool_start_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "read_file"}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].tool_name == "read_file"
        assert bubbles[0][1] == "sk-1"

    def test_tool_end_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "end", "name": "exec", "durationMs": 1200}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].duration_ms == 1200

    def test_tool_error_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "end", "name": "edit", "isError": True}
        })

        from models.activity import ActivityType
        assert bubbles[0][0].activity_type == ActivityType.TOOL_ERROR

    def test_plan_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "plan",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"title": "My Plan", "steps": ["a", "b"]}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].plan_title == "My Plan"

    def test_approval_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "approval",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "requested", "command": "rm -rf /", "host": "sandbox"}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].approval_command == "rm -rf /"

    def test_command_output_end_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "command_output",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "end", "name": "exec", "exitCode": 1, "durationMs": 300}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].exit_code == 1

    def test_patch_end_fires_callback(self, fake_glib):
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "patch",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "end", "name": "edit", "added": ["a.py"], "modified": [], "deleted": []}
        })

        assert len(bubbles) == 1
        assert bubbles[0][0].files_added == ["a.py"]

    def test_no_bubble_when_callback_not_set(self, fake_glib):
        """No crash when on_activity_bubble is not wired."""
        handler = _make_handler(fake_glib=fake_glib)
        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "read_file"}
        })
        # No assertion needed — just verify no exception

    def test_no_bubble_for_filtered_events(self, fake_glib):
        """Events we intentionally skip don't fire callback."""
        handler = _make_handler(fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        # tool phase=update should not fire
        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "update", "name": "exec", "output": "..."}
        })

        # command_output phase=start should not fire
        handler.on_gateway_event("agent", {
            "stream": "command_output",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "exec"}
        })

        # patch phase=start should not fire
        handler.on_gateway_event("agent", {
            "stream": "patch",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "edit"}
        })

        assert len(bubbles) == 0


class TestActivityBubbleTabRouting:
    """Test that activity bubbles route to the correct tab."""

    def test_default_tab_is_session_key(self, fake_glib):
        handler = _make_handler(agent_to_project=None, fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "agent:coder:1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "read_file"}
        })

        assert bubbles[0][1] == "agent:coder:1"

    def test_project_tab_routing(self, fake_glib):
        mock_routing = MagicMock()
        mock_routing.get_project.return_value = "myproject"
        handler = _make_handler(agent_to_project=mock_routing, fake_glib=fake_glib)
        bubbles = []
        handler.set_on_activity_bubble(lambda a, t: bubbles.append((a, t)))

        handler.on_gateway_event("agent", {
            "stream": "tool",
            "sessionKey": "agent:coder:1",
            "runId": "r-1",
            "data": {"phase": "start", "name": "read_file"}
        })

        assert bubbles[0][1] == "project:myproject"


# ── ChatHandler integration tests ────────────────────────────────────────────

class TestChatHandlerActivityBubble:
    """Test ChatHandler.render_activity_bubble() renders correctly."""

    def _make_chat_handler(self, fake_glib):
        from ui.handlers.chat_handler import ChatHandler
        mc = MagicMock()
        mc.get_current_session_key = MagicMock(return_value=None)
        mc.get_chat_box_for_session.return_value = MagicMock()
        ch = ChatHandler(
            main_content=mc,
            gateway_client=MagicMock(),
            agent_to_project=MagicMock(),
            projects_module=MagicMock(),
            GLib_module=fake_glib,
        )
        return ch, mc

    def test_renders_activity_bubble(self, fake_glib):
        ch, mc = self._make_chat_handler(fake_glib)
        fake_box = MagicMock()
        mc.get_chat_box_for_session.return_value = fake_box
        fake_render = MagicMock()
        fake_widget = MagicMock()
        fake_render.render_activity.return_value = fake_widget
        ch._chat_render_handler = fake_render

        from models.activity import ActivityBubble, ActivityType
        activity = ActivityBubble(
            activity_type=ActivityType.TOOL_START,
            session_key="sk-1", run_id="r-1",
            tool_name="read"
        )
        ch.render_activity_bubble(activity, "sk-1")

        # Should have rendered via render_activity and appended to chat box
        fake_render.render_activity.assert_called_once_with("🔧 read...", "tool_start")
        fake_box.append.assert_called_once_with(fake_widget)

    def test_no_render_when_no_chat_box(self, fake_glib):
        ch, mc = self._make_chat_handler(fake_glib)
        mc.get_chat_box_for_session.return_value = None
        fake_render = MagicMock()
        ch._chat_render_handler = fake_render

        from models.activity import ActivityBubble, ActivityType
        activity = ActivityBubble(
            activity_type=ActivityType.TOOL_START,
            session_key="sk-1", run_id="r-1",
            tool_name="read"
        )
        ch.render_activity_bubble(activity, "sk-1")

        fake_render.render_activity.assert_not_called()

    def test_no_render_when_no_render_handler(self, fake_glib):
        ch, mc = self._make_chat_handler(fake_glib)
        mc.get_chat_box_for_session.return_value = MagicMock()
        ch._chat_render_handler = None

        from models.activity import ActivityBubble, ActivityType
        activity = ActivityBubble(
            activity_type=ActivityType.TOOL_START,
            session_key="sk-1", run_id="r-1",
            tool_name="read"
        )
        # Should not crash
        ch.render_activity_bubble(activity, "sk-1")
```

### 2.9 Events NOT Shown

These `agent` event streams are intentionally NOT rendered as activity bubbles:

| Stream | Reason |
|--------|--------|
| `assistant` | Already handled by Phase 1 buffer + chat events; redundant |
| `thinking` | Too noisy, not meaningful to the user |
| `tool` phase=`update` | Intermediate progress — only start/end matters |
| `command_output` phase=`start` | Only the end (with exit code + duration) is useful |
| `patch` phase=`start` | Only the end (with file list) is useful |
| `item` | Most items are too low-level; skip unless specifically requested |
| `error` (seq gap) | Internal protocol detail, not user-facing |
| `lifecycle` phase=`end`/`error` | Already handled by Phase 1 fallback render |

### 2.10 Verification Steps

1. `cd /home/q/projects/crabcakes && python -m pytest tests/test_activity_bubbles.py -v` — all new tests pass
2. `python -m pytest tests/test_missing_message_fix.py -v` — Phase 1 still passes
3. `python -m pytest tests/ -v` — full suite (6 pre-existing failures in `test_chat_handler.py` are expected)
4. Manual test: Start CrabCakes, send a message that triggers tool calls (e.g., "search for X"), verify activity bubbles appear between user message and agent response
5. Verify activity bubbles have muted styling (semi-transparent, smaller text, not visually identical to agent responses)

---

## Implementation Order

1. **Phase 1** — ✅ COMPLETE (with Qaster's fixes: guard-clearing, dead code removal)
2. **Phase 2** — implement in this order:
   1. `models/activity.py` — pure data model, no dependencies
   2. `ui/handlers/activity_handler.py` — add `_on_activity_bubble`, `set_on_activity_bubble()`, and event parsing in `on_gateway_event()`
   3. `ui/handlers/chat_render_handler.py` — add `render_activity()` method
   4. `ui/styles.py` — add CSS for `.activity-bubble` classes
   5. `ui/handlers/chat_handler.py` — add `render_activity_bubble()` method
   6. `ui/window.py` — wire callback + pass `agent_to_project` to ActivityHandler
   7. `tests/test_activity_bubbles.py` — write and run all tests
3. Run full test suite after all changes

## Gotchas

- **Lazy import in ActivityHandler:** `from models.activity import ...` must be inside the method body, not at module top level, to avoid circular dependency issues.
- **`chat_box.append()` is how widgets are added** — always use `.append()` for rendering, never `.record()` (which is a data-layer method that may not exist on bare Gtk.Box).
- **Thread safety is already handled:** `on_gateway_event()` runs on the main thread (gateway client dispatches via `GLib.idle_add`). The callback fires synchronously within that call. No additional dispatch needed.
- **`agent_to_project` routing:** ActivityHandler needs its own reference to the `AgentRoutingTable` (passed via constructor). Do NOT reach into `self._mc._agent_to_project` — `MainContent` doesn't have that attribute.
- **Activity bubbles do NOT go through `_handle_final_response` or `_chat_final_rendered`:** They're separate from the conversation message flow. No guard interaction.
- **Phase 1 callback pattern is the template:** `set_on_activity_bubble(cb)` follows the exact same wiring pattern as `set_on_assistant_buffer`, `set_on_lifecycle_completed`, and `set_on_agent_start`. When in doubt, look at how those are wired.
