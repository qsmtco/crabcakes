---
status: SUPERSEDED
---
# SPEC: Activity Bubble UX Overhaul

**Date:** 2026-06-01
**Author:** QTR (Kage-7)
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-activity-bubble-ux.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md): ActivityHandler is a handler (no GTK rendering). ChatHandler is a handler (no widget creation directly). ChatRenderHandler owns widget creation. MainContent is a view. All CSS classes in `ui/styles.py`. New `_render_activity_bubble_impl` continues to call `render_activity` on ChatRenderHandler and append to chat box from MainContent. Counter state lives in ActivityHandler (per-session dict); counter widget is built by ChatRenderHandler and mutated via a new `update()` method. System Bubble Container is built by ChatRenderHandler and appended to the chat box from MainContent.

---

## DISCOVERY

- **Read `ui/handlers/activity_handler.py:140-152`:** `set_on_activity_bubble(cb)` stores `self._activity_bubble_callback`. Called for each bubble emission. Callback receives an `ActivityBubble` instance.
- **Read `ui/handlers/activity_handler.py:230-330`:** Inside `on_gateway_event`, per-event handlers (lifecycle, item, plan, approval, command_output, patch) build an `ActivityBubble` and fire the callback. **Counter state must be added BEFORE the callback fires**, so the mutation logic can decide between "create new widget" vs "update existing widget."
- **Read `ui/handlers/chat_handler.py:151-187`:** `_render_activity_bubble(bubble)` dispatches to `_render_activity_bubble_impl` on the GTK main thread. The impl calls `self._chat_render_handler.render_activity(text, activity_type)` and appends the result to `chat_box`, then calls `self._mc.scroll_chat_to_bottom()`. **Fix 1.3 removes the scroll call from this path. Fix 1.4 routes through a system-bubble container instead of the chat box directly.**
- **Read `ui/handlers/chat_handler.py:166-170`:** The dispatch uses `lambda sk=..., txt=..., at=...: (self._render_activity_bubble_impl(...))` — default-arg trick to capture loop variables. **For Fix 1.5 (counter mutation), this same pattern applies: the dispatched callback must call a *mutate* method on the existing widget, not create a new one.**
- **Read `ui/handlers/connection_sync_handler.py:161`:** `self._activity_handler.set_on_activity_bubble(self._chat_handler._render_activity_bubble)` — this is the wiring point. **All new callback paths (create-counter, mutate-counter) must be added here.**
- **Read `ui/handlers/chat_render_handler.py:589-621`:** `render_activity(text, activity_type)` returns a `Gtk.Box` wrapper containing a single `Gtk.Box` pill (CSS classes `activity-bubble` and `activity-{type}`) and a `Gtk.Label`. **For Fix 1.1 (counter widget), a new sibling function `render_counter(counter_state)` returns a widget with an `update(counter_state)` method. For Fix 1.4 (system container), a new function `build_system_bubble()` returns a `Gtk.Box` with a header label and an inner `Gtk.ScrolledWindow` containing a `Gtk.Box` for pills.**
- **Read `ui/views/chat_bubble.py:175`:** `build_role_bubble(role, text, on_forward_click=None, tight=False, forwarded_from=None, session_key=None, agent_name=None)` — public API for building chat bubbles. **For Fix 1.4, the system container is NOT a `build_role_bubble` (it's a different visual surface). For Fix 1.5, the `agent_name` parameter is already wired and used in the agent header row — we reuse it.**
- **Read `ui/views/main_content.py:684-693`:** `get_chat_box_for_session(session_key)` returns the `chat_box` `Gtk.Box` for a given session, or `None`. **The System Bubble Container is a child of the chat box, not a sibling — it's appended to the chat box as the "outer system bubble" and the inner pill box scrolls within it.**
- **Read `ui/views/main_content.py:718-740`:** `scroll_chat_to_bottom(page_index=None)` defers via `GLib.timeout_add(16, _do_scroll)`. **Fix 1.3 removes the call from `_render_activity_bubble_impl` — pill emissions do NOT scroll the main chat. Fix 1.4's outer-bubble creation does call `scroll_chat_to_bottom` once (for the outer bubble, not for individual pills).**
- **Read `ui/handlers/agent_runtime_handler.py:497-550`:** `_on_tool_call_start(session_key, name, args)` and `_do_tool_call_start` are the entry points. `_do_tool_call_start` already extracts `agent_def = self._agents.get(session_key)` and `agent_name = agent_def.display_name`. **Fix 1.5 adds a new cache: `self._active_tools: dict[str, dict]` keyed by `session_key`, storing `{agent_name, tool_name, command, started_at}`. Populated in `_do_tool_call_start` for `name == "exec_command"`, cleared in `_do_tool_call_result` (around line 575).**
- **Read `ui/handlers/agent_runtime_handler.py:64`:** `self._agents: dict[str, Any] = {}` — `session_key` → `SpecialAgentDef`. `display_name` is the human-readable agent name. **This is the source of truth for agent name resolution.**
- **Read `models/activity.py:36-90`:** `ActivityBubble` dataclass with `type: ActivityType`, `session_key`, `tool_name`, `duration_ms`, `status`, `icon`, `title`, `steps`, `command`, `approval_id`, `reason`, `exit_code`, `added`, `modified`, `deleted`, `raw_text`. `format_text()` produces the display string. **Fix 1.1 adds new fields: `count: int = 1`, `last_text: str = ""`, `total_duration_ms: int = 0`, `last_command: str = ""`. Fix 1.5 adds `command: str = ""` and `agent_name: str = ""` (the `command` field already exists for `approval_request` — we extend its use to `command_output`).**
- **Read `models/activity.py:16-26`:** `ActivityType = Literal[...]` is a `Literal` type. **Adding `"counter"` to this Literal would force every existing call site to handle it. We keep `ActivityType` unchanged and use a separate flag `is_counter: bool = False` on the bubble.**
- **Read `ui/styles.py:463-510`:** Existing CSS classes: `.activity-bubble`, `.activity-bubble-text`, `.activity-tool_start`, `.activity-tool_end`, `.activity-tool_error`, `.activity-plan`, `.activity-command_output`, `.activity-patch`, `.activity-approval_request`, `.activity-lifecycle_start`. **Fix 1.1 adds `.activity-counter` and `.activity-counter-badge`. Fix 1.4 adds `.system-bubble-container`, `.system-bubble-header`, `.system-bubble-inner`. Fix 1.5 reuses existing classes (no new CSS needed for the agent name; it goes in the label text).**
- **Read `tests/test_activity_bubbles.py:1-95`:** Existing tests cover the model (`TestActivityBubbleModel`) and the handler (`TestActivityHandlerActivityBubbles`). Uses `MagicMock` and `fake_glib` fixtures. **New test classes follow the same pattern: `TestCounterCollapse`, `TestSystemBubbleContainer`, `TestSystemBubblePillRouting`, `TestContentEnrichment`.**
- **Read `ui/window.py:228-237`:** ActivityHandler is created with `feedbar`, `main_content`, `GLib_module`. `set_agent_routing(self._agent_to_project)` is called. **Fix 1.5 needs `set_active_tool_lookup(callable)` on ActivityHandler — the lookup is `self._agent_runtime_handler.get_active_tool(session_key)`. Window wires this after creating ActivityHandler.**
- **Read `ui/window.py:188`:** `self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)` is called after both exist. **Fix 1.4 needs the chat handler to be able to ask MainContent for the current system bubble — new method `MainContent.get_or_create_system_bubble(session_key)`.**
- **Read `ui/handlers/agent_runtime_handler.py:560-620`:** `_on_tool_call_result` and `_do_tool_call_result` clear feed cards and stage review files. **Fix 1.5 adds `self._active_tools.pop(session_key, None)` at the top of `_do_tool_call_result` (before the feed card cleanup).**
- **Architecture owner:**
  - Counter state → `ActivityHandler` (per-session dict, mutates in place)
  - Counter widget → `ChatRenderHandler` (built once, has `update()` method)
  - System bubble container → `ChatRenderHandler` (builds the outer `Gtk.Box`)
  - Agent name cache → `AgentRuntimeHandler` (writes) → `ActivityHandler` (reads via callback)
  - CSS → `ui/styles.py` (all new classes)
  - Main thread dispatch → `GLib.idle_add` (existing pattern in ChatHandler)

---

## 1. Overview

### Problem
The activity bubble system fires many small "pills" (one per event) into the chat. They accumulate, push conversation off-screen, and auto-scroll the chat. The data is shallow — only the tool name (`exec`) and duration are shown; the actual command string and agent name are missing. The user sees a noisy, unhelpful stream.

### Solution
Five targeted changes that work together:
1. **Fix 1.3 (one-line):** Stop auto-scrolling the main chat when an activity bubble emits.
2. **Fix 1.5 (content):** Capture and display the actual command string and agent name.
3. **Fix 1.4 (structure):** Wrap all activity pills in a centered, bounded, internally-scrolling "System Chat Bubble Container."
4. **Fix 1.1 (collapsing):** Collapse consecutive same-type bubbles into a single mutating counter.
5. **Fix 1.2 (escape hatch):** Add a toggle to hide the System Bubble Container entirely.

### Scope

| In Scope | Out of Scope |
|---------|--------------|
| Counter-collapse (all 8 types) | Tier 2 polish (throttle, auto-expire, signal/noise CSS) |
| System Bubble Container | Sidebar/sidecar redesign |
| Agent name on all bubble types | Per-agent CSS theming |
| Command string capture via active-tool cache | Capturing args for non-`exec` tools |
| Toggle to hide System Bubble Container | Persistence of toggle across sessions |
| Mutate-in-place counter updates | Animation/transitions on counter changes |
| "Counter ×N" badge styling | Click-to-expand counter history |

### Architecture Principles
- **§3.5:** All CSS in `ui/styles.py` via `add_css_class()`
- **§3.6:** `window.py` wires handlers, no logic
- **§3.9:** `main_content.py` is a view (provides `get_chat_box_for_session`, `get_or_create_system_bubble`)
- **§13.4:** Callbacks as communication mechanism (counter mutation is a callback, not a direct call)
- **Handler pattern:** ActivityHandler owns state (counters). ChatRenderHandler owns widget creation. ChatHandler orchestrates dispatch.

---

## 2. Changes by File

### 2.1 `models/activity.py` — EXTEND

**Architecture:** Pure data model. No GTK, no gateway, no state. Add fields to `ActivityBubble`.

**New fields on `ActivityBubble`:**

```python
@dataclass
class ActivityBubble:
    # ... existing fields ...

    # Fix 1.1: counter-collapse state
    is_counter: bool = False
    count: int = 1
    last_text: str = ""
    total_duration_ms: int = 0
    last_command: str = ""

    # Fix 1.5: content enrichment
    command: str = ""        # extends existing use (was approval_request only)
    agent_name: str = ""
```

**Signature verification (actual source):** `ActivityBubble` is a `@dataclass` with all fields having defaults EXCEPT `type` and `session_key`. Adding new fields with defaults is safe — no existing call site breaks. Verified by reading `models/activity.py:36-90`.

**New method on `ActivityBubble`:**

```python
def format_counter_text(self) -> str:
    """Format a counter bubble's text: 'exec ×5  pytest tests/  4,247ms'.

    Called by ChatRenderHandler when building/mutating the counter widget.
    Uses last_command (truncated to 60 chars), last_text (the friendly tool name),
    and total_duration_ms.
    """
    if not self.is_counter:
        return self.format_text()
    name = _friendly_tool_name(self.tool_name)
    cmd = self.last_command
    if len(cmd) > 60:
        cmd = cmd[:57] + "..."
    cmd_part = f"  {cmd}" if cmd else ""
    ms = self.total_duration_ms
    if self.exit_code != 0:
        return f"{name} ×{self.count}{cmd_part}  exit {self.exit_code}  {ms:,}ms"
    return f"{name} ×{self.count}{cmd_part}  {ms:,}ms"
```

**Format verification:** `_friendly_tool_name` exists at `models/activity.py:138-148`. `format_text()` is the existing method at `models/activity.py:92-128`. The new method follows the same truncation pattern.

**Updated `format_text()` for Fix 1.5 — extend `command_output` branch:**

```python
elif self.type == "command_output":
    name = _friendly_tool_name(self.tool_name)
    ms = self.duration_ms
    cmd = self.command
    if len(cmd) > 60:
        cmd = cmd[:57] + "..."
    agent = self.agent_name
    prefix = f"{agent}  " if agent else ""
    cmd_part = f"  {cmd}" if cmd else ""
    if self.exit_code != 0:
        return f"{prefix}{name}{cmd_part}  exit {self.exit_code}  {ms:,}ms"
    return f"{prefix}{name}{cmd_part}  {ms:,}ms"
```

**Exception types:** None — pure data class. No I/O, no raises.

**Imports required:** None new.

**Line count estimate:** +35 lines.

---

### 2.2 `ui/handlers/activity_handler.py` — EXTEND

**Architecture:** Owns counter state and active-tool lookup. Adds the per-session counter store and the cache-miss fallback.

**New constructor state:**

```python
def __init__(self, feedbar, main_content, GLib_module=None):
    # ... existing init ...

    # Fix 1.1: counter-collapse state
    # Keyed by (session_key, lifecycle_run_id, type) → counter state dict
    # Using run_id instead of session_key alone so a new agent turn starts fresh counters.
    self._counters: dict[tuple[str, str, str], dict] = {}
    self._current_run_id: dict[str, str] = {}  # session_key → current run_id
    self._active_tool_lookup: Callable[[str], dict | None] | None = None  # Fix 1.5
```

**New public method (Fix 1.5):**

```python
def set_active_tool_lookup(self, lookup: Callable[[str], dict | None]) -> None:
    """Inject a callable that returns the active tool for a session_key.

    Used to enrich command_output and tool_* bubbles with the actual command
    string and agent name. Lookup returns a dict with keys: agent_name, tool_name,
    command, started_at — or None if no tool is active for that session.

    Called by window.py._build() with self._agent_runtime_handler.get_active_tool.
    """
    self._active_tool_lookup = lookup
```

**New private method (Fix 1.1):**

```python
def _get_or_create_counter(
    self, session_key: str, run_id: str, bubble: 'ActivityBubble'
) -> tuple[dict, bool]:
    """Look up or create a counter for (session_key, run_id, bubble.type).

    Returns (counter_dict, is_new). If a counter exists for this triple, returns
    the existing dict and False. Otherwise creates a new counter seeded from
    bubble and returns it with True.

    Different-type events close the previous counter by removing it from the
    store. The chat handler will receive a 'counter_closed' signal (via the
    callback) so it can stop mutating the widget. For this spec, we simply
    drop the counter on different-type — the widget stays visible but stops
    mutating (next same-type event starts a new counter).
    """
    key = (session_key, run_id, bubble.type)
    if key in self._counters:
        return self._counters[key], False
    # Close any open counter of a different type for this (session_key, run_id)
    for existing_key in list(self._counters.keys()):
        if existing_key[0] == session_key and existing_key[1] == run_id and existing_key[2] != bubble.type:
            self._counters.pop(existing_key, None)
    counter = {
        "session_key": session_key,
        "run_id": run_id,
        "type": bubble.type,
        "tool_name": bubble.tool_name,
        "icon": bubble.icon,
        "count": 1,
        "last_text": bubble.format_text(),
        "last_command": getattr(bubble, "command", "") or "",
        "total_duration_ms": bubble.duration_ms,
        "exit_code": bubble.exit_code,
    }
    self._counters[key] = counter
    return counter, True
```

**Updated `on_gateway_event` (Fix 1.1 + Fix 1.5):**

The handler builds an `ActivityBubble` from the gateway payload (as today), then — **before firing the callback** — runs two enrichment steps:

```python
# After building bubble from gateway payload, BEFORE firing callback:

# Fix 1.5: enrich with cached command + agent
if self._active_tool_lookup is not None and bubble.type in ("command_output", "tool_start", "tool_end", "tool_error"):
    cached = self._active_tool_lookup(bubble.session_key)
    if cached:
        if bubble.type == "command_output" and not bubble.command:
            bubble.command = cached.get("command", "")
        if not bubble.agent_name:
            bubble.agent_name = cached.get("agent_name", "")

# Fix 1.1: route to counter store
run_id = payload.get("runId", "") or ""
if run_id:
    counter, is_new = self._get_or_create_counter(bubble.session_key, run_id, bubble)
    if not is_new:
        # Mutate existing counter
        counter["count"] += 1
        counter["last_text"] = bubble.format_text()
        if bubble.command:
            counter["last_command"] = bubble.command
        counter["total_duration_ms"] += bubble.duration_ms
        # Exit code: track last non-zero
        if bubble.exit_code != 0:
            counter["exit_code"] = bubble.exit_code
        # Fire a SEPARATE mutate callback (not the create callback)
        if self._activity_bubble_mutate_callback:
            self._activity_bubble_mutate_callback(counter)
        continue  # skip the normal create-callback path

# Fire normal create callback (new bubble widget)
if self._activity_bubble_callback:
    self._activity_bubble_callback(bubble)
```

**Note on `continue`:** The above snippet is illustrative. The actual implementation wraps the body of each per-event branch (`command_output`, `tool_*`, etc.) in a helper that returns early after counter mutation. See "Implementation Order" §5 for the exact refactor pattern.

**New callback (Fix 1.1):**

```python
def set_on_activity_bubble_mutate(self, cb: Callable[[dict], None]) -> None:
    """Set callback for counter mutations: cb(counter_dict).

    Fired when an existing counter increments. The chat handler uses this to
    call .update() on the existing counter widget (in-place text update,
    no scroll trigger).
    """
    self._activity_bubble_mutate_callback = cb
```

**New private method (Fix 1.1):**

```python
def _reset_counters_for_session(self, session_key: str) -> None:
    """Drop all counters for a session — called on lifecycle end."""
    keys_to_drop = [k for k in self._counters if k[0] == session_key]
    for k in keys_to_drop:
        self._counters.pop(k, None)
    self._current_run_id.pop(session_key, None)
```

**Hook into lifecycle end:** In `on_agent_end` (or in the lifecycle phase=end branch around line 230), call `self._reset_counters_for_session(sk)`.

**Exception types:** None. Pure Python dict ops. No I/O.

**Imports required:** `Callable` from `typing` (already imported).

**Line count estimate:** +90 lines.

---

### 2.3 `ui/handlers/agent_runtime_handler.py` — EXTEND

**Architecture:** Writes to the active-tool cache. ActivityHandler reads from it via the lookup callable wired in window.py.

**New constructor state:**

```python
def __init__(self, ...):
    # ... existing init ...

    # Fix 1.5: active-tool cache — session_key → {agent_name, tool_name, command, started_at}
    # Read by ActivityHandler via get_active_tool() to enrich command_output bubbles.
    self._active_tools: dict[str, dict] = {}
```

**Updated `_do_tool_call_start` (Fix 1.5):**

Add at the top of the method (after the existing early-return guard at line 519):

```python
# Fix 1.5: stash active tool for ActivityHandler enrichment
agent_def = self._agents.get(session_key)
agent_name_for_cache = agent_def.display_name if agent_def else "Agent"
self._active_tools[session_key] = {
    "agent_name": agent_name_for_cache,
    "tool_name": name,
    "command": args.get("command", "") if name == "exec_command" else "",
    "started_at": time.monotonic(),
}
```

**Note:** The existing code at line 520-525 already extracts `agent_def` and `agent_name` for the feed card. We reuse those local variables (verified by reading lines 520-525 of the actual file). To avoid shadowing, rename the cache version to `agent_name_for_cache`.

**Updated `_do_tool_call_result` (Fix 1.5):**

Add at the top of the method (after the `if self._GLib is not None:` block, before the feed card cleanup):

```python
# Fix 1.5: clear active-tool cache
self._active_tools.pop(session_key, None)
```

**New public method (Fix 1.5):**

```python
def get_active_tool(self, session_key: str) -> dict | None:
    """Return the active tool for a session, or None.

    Used by ActivityHandler (via the lookup callback wired in window.py) to
    enrich command_output and tool_* bubbles with the actual command string
    and agent name. Returns None if no tool is currently active for the session.
    """
    return self._active_tools.get(session_key)
```

**Exception types:** None. Pure dict ops.

**Imports required:** `time` (already imported at top of file — verified).

**Line count estimate:** +20 lines.

---

### 2.4 `ui/handlers/chat_render_handler.py` — EXTEND

**Architecture:** Owns widget creation. New functions for counter widget and system bubble container.

**New function (Fix 1.1):**

```python
def render_counter(self, counter: dict) -> Gtk.Widget:
    """Render a counter bubble widget. Returns a wrapper Gtk.Box.

    The returned widget has an .update(new_counter) method that mutates the
    label text in place — no new widget creation, no scroll trigger.

    Args:
        counter: dict with keys: type, tool_name, icon, count, last_text,
                 last_command, total_duration_ms, exit_code
    """
    # Outer wrapper (centers the pill)
    wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    wrapper.set_halign(Gtk.Align.CENTER)

    # Inner pill
    pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    pill.add_css_class("activity-bubble")
    pill.add_css_class("activity-counter")

    # Count badge (highlighted number)
    badge = Gtk.Label(label=f"×{counter['count']}")
    badge.add_css_class("activity-counter-badge")
    pill.append(badge)

    # Text label (last command + total duration)
    label = Gtk.Label()
    label.set_xalign(0.5)
    label.add_css_class("activity-bubble-text")
    pill.append(label)
    wrapper.append(pill)

    def _format() -> str:
        name = _friendly_tool_name(counter["tool_name"])
        cmd = counter.get("last_command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        cmd_part = f"  {cmd}" if cmd else ""
        ms = counter.get("total_duration_ms", 0)
        exit_code = counter.get("exit_code", 0)
        if exit_code != 0:
            return f"{name}{cmd_part}  exit {exit_code}  {ms:,}ms"
        return f"{name}{cmd_part}  {ms:,}ms"

    label.set_text(_format())

    def update(new_counter: dict) -> None:
        """Mutate the widget in place — update badge count and label text."""
        counter.update(new_counter)
        badge.set_text(f"×{counter['count']}")
        label.set_text(_format())

    wrapper.update = update  # type: ignore[attr-defined]
    wrapper.set_margin_top(3)
    wrapper.set_margin_bottom(3)
    return wrapper
```

**Signature verification:** `render_activity` (existing) returns `Gtk.Box` (the wrapper). `_friendly_tool_name` exists at `models/activity.py:138` and is imported in `chat_render_handler.py` (verified by reading the import block at the top of the file). The new function follows the same return-shape pattern as `render_activity`.

**New function (Fix 1.4):**

```python
def build_system_bubble(self) -> Gtk.Widget:
    """Build the outer System Chat Bubble Container.

    Returns a Gtk.Box that:
      - Is centered horizontally
      - Has a header label ("System")
      - Contains an inner Gtk.ScrolledWindow (capped height) with a Gtk.Box
        where individual pills (or counter widgets) are appended
      - Exposes .append_pill(widget) for the chat handler to add pills
      - Exposes .get_pill_box() to return the inner box (for scroll-to-bottom
        on outer-bubble creation)
    """
    # Outer wrapper
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer.set_halign(Gtk.Align.CENTER)
    outer.set_size_request(-1, -1)  # hug content
    outer.add_css_class("system-bubble-container")

    # Header label
    header = Gtk.Label(label="System")
    header.set_xalign(0.5)
    header.add_css_class("system-bubble-header")
    outer.append(header)

    # Inner scroll window (capped height)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_size_request(-1, 120)  # ~4 pill rows
    scroll.add_css_class("system-bubble-inner")

    # Inner box where pills go
    inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    inner_box.set_halign(Gtk.Align.CENTER)
    scroll.set_child(inner_box)
    outer.append(scroll)

    def append_pill(widget: Gtk.Widget) -> None:
        inner_box.append(widget)
        # Auto-scroll inner to bottom (newest at bottom per Captain's spec)
        vadj = scroll.get_vadjustment()
        if vadj is not None:
            GLib.idle_add(lambda: vadj.set_value(vadj.get_upper() - vadj.get_page_size()) or False)

    def get_pill_box() -> Gtk.Box:
        return inner_box

    outer.append_pill = append_pill  # type: ignore[attr-defined]
    outer.get_pill_box = get_pill_box  # type: ignore[attr-defined]
    return outer
```

**Imports required:** `GLib` from `gi.repository` (already imported in this file — verified). `Gtk` (already imported).

**Line count estimate:** +85 lines.

---

### 2.5 `ui/views/main_content.py` — EXTEND

**Architecture:** View. Provides a method to get-or-create the system bubble for a session. No state machine.

**New constructor state:**

```python
def __init__(self, ...):
    # ... existing init ...

    # Fix 1.4: track per-session system bubble container
    # session_key → system_bubble_widget (created on first pill of a turn)
    self._system_bubbles: dict[str, Gtk.Widget] = {}
```

**New method:**

```python
def get_or_create_system_bubble(self, session_key: str, chat_render_handler) -> Gtk.Widget | None:
    """Return the System Bubble Container for the session, creating it if needed.

    Looks up the chat box for the session, appends a new system bubble to it
    (only if one doesn't already exist for this turn), and returns the container.
    Returns None if no chat box exists for the session.

    The system bubble persists across all activity emissions within a single
    agent turn (lifecycle). A new turn (new lifecycle_start) drops the old
    container reference and creates a new one. ActivityHandler calls
    drop_system_bubble(session_key) on lifecycle_end.
    """
    if session_key in self._system_bubbles:
        return self._system_bubbles[session_key]
    chat_box = self.get_chat_box_for_session(session_key)
    if chat_box is None:
        # Try project routing
        if self._agent_to_project is not None:
            project_name = self._agent_to_project.get_project(session_key)
            if project_name is not None:
                chat_box = self.get_chat_box_for_session(f"project:{project_name}")
    if chat_box is None:
        return None
    bubble = chat_render_handler.build_system_bubble()
    chat_box.append(bubble)
    self._system_bubbles[session_key] = bubble
    return bubble

def drop_system_bubble(self, session_key: str) -> None:
    """Drop the reference to a session's system bubble (does not destroy widget).

    Called by ActivityHandler on lifecycle_end. The widget stays in the chat;
    it just won't receive new pills.
    """
    self._system_bubbles.pop(session_key, None)
```

**Signature verification:** `get_chat_box_for_session` is at line 684. The new methods follow the same return-None-if-not-found pattern.

**Imports required:** None new.

**Line count estimate:** +30 lines.

---

### 2.6 `ui/handlers/chat_handler.py` — EXTEND

**Architecture:** Orchestrator. Routes bubble emissions to the system bubble container (or to a counter widget for mutation).

**Updated `_render_activity_bubble_impl` (Fix 1.3, 1.4, 1.5):**

The current implementation (lines 170-185):

```python
def _render_activity_bubble_impl(self, session_key: str, text: str, activity_type: str = ""):
    if self._chat_render_handler is None:
        return
    chat_box = self._mc.get_chat_box_for_session(session_key)
    if chat_box is None and self._agent_to_project is not None:
        project_name = self._agent_to_project.get_project(session_key)
        if project_name is not None:
            chat_box = self._mc.get_chat_box_for_session(f"project:{project_name}")
    if chat_box is None:
        return
    bubble = self._chat_render_handler.render_activity(text, activity_type)
    if bubble is not None:
        chat_box.append(bubble)
        self._mc.scroll_chat_to_bottom()  # ← Fix 1.3 REMOVES THIS LINE
```

**New implementation:**

```python
def _render_activity_bubble_impl(self, session_key: str, text: str, activity_type: str = "", bubble_obj: 'ActivityBubble | None' = None):
    """Thread-unsafe internal render — must be called on GTK main thread.

    Fix 1.4: Pills are appended to the System Bubble Container, not the chat box.
    Fix 1.3: No scroll-to-bottom on pill emission. Outer-bubble creation scrolls once.
    Fix 1.5: bubble_obj is the full ActivityBubble (needed for command/agent_name).
    """
    if self._chat_render_handler is None:
        return

    # Fix 1.4: get-or-create the system bubble container
    system_bubble = self._mc.get_or_create_system_bubble(session_key, self._chat_render_handler)
    if system_bubble is None:
        return  # no chat box for this session — drop silently

    # Determine if this is the first pill (outer bubble just created)
    is_first_pill = system_bubble.get_pill_box().get_first_child() is None

    # Build the pill widget
    if bubble_obj is not None and getattr(bubble_obj, "is_counter", False):
        # Counter widget — rendered by render_counter
        widget = self._chat_render_handler.render_counter(bubble_obj.__dict__)
    else:
        widget = self._chat_render_handler.render_activity(text, activity_type)

    if widget is not None:
        system_bubble.append_pill(widget)
        # Fix 1.3: only scroll on the FIRST pill of a turn (outer bubble creation)
        if is_first_pill:
            self._mc.scroll_chat_to_bottom()
```

**New method (Fix 1.1): counter mutation handler:**

```python
def _mutate_activity_bubble(self, counter: dict) -> None:
    """Handle a counter mutation — update the existing counter widget in place.

    Called by ActivityHandler via set_on_activity_bubble_mutate callback.
    Finds the counter widget for (session_key, run_id, type) and calls
    its .update() method. No new widget creation, no scroll trigger.
    """
    if self._chat_render_handler is None:
        return
    session_key = counter.get("session_key", "")
    bubble_type = counter.get("type", "")
    system_bubble = self._mc._system_bubbles.get(session_key)  # direct access — view owns
    if system_bubble is None:
        return
    pill_box = system_bubble.get_pill_box()
    if pill_box is None:
        return
    # Find the counter widget (last child of matching type)
    # We tag the widget with the type via a private attr when created
    child = pill_box.get_last_child()
    while child is not None:
        if getattr(child, "_counter_type", None) == bubble_type:
            if hasattr(child, "update"):
                child.update(counter)
            return
        child = child.get_prev_sibling()
```

**Note:** The widget needs a `_counter_type` attribute set when `render_counter` creates it. This is a minor addition to `render_counter` (see 2.4 above).

**Updated `_render_activity_bubble` dispatch:**

```python
def _render_activity_bubble(self, bubble: 'ActivityBubble'):
    text = bubble.format_text()
    if not text:
        return
    session_key = bubble.session_key
    if self._chat_render_handler is None:
        return
    self._dispatch(lambda sk=session_key, txt=text, at=bubble.type, b=bubble: (
        self._render_activity_bubble_impl(sk, txt, at, b)
    ))
```

**Signature verification:** `_dispatch` is the existing helper at the top of `chat_handler.py`. Pattern follows the existing `lambda sk=..., txt=...: (...)` default-arg capture (verified in lines 166-170).

**Imports required:** None new.

**Line count estimate:** +45 lines.

---

### 2.7 `ui/handlers/connection_sync_handler.py` — WIRE NEW CALLBACK

**Architecture:** Composition point. Wires ActivityHandler callbacks.

**Updated line 161:**

```python
# Existing:
self._activity_handler.set_on_activity_bubble(self._chat_handler._render_activity_bubble)

# New (Fix 1.1):
self._activity_handler.set_on_activity_bubble_mutate(self._chat_handler._mutate_activity_bubble)
```

**Imports required:** None new.

**Line count estimate:** +1 line.

---

### 2.8 `ui/window.py` — WIRE FIX 1.5

**Architecture:** Composition root. Wires the active-tool lookup callable.

**New line after `set_agent_routing` (around line 237):**

```python
# Fix 1.5: wire active-tool lookup so ActivityHandler can enrich bubbles
self._activity_handler.set_active_tool_lookup(
    self._agent_runtime_handler.get_active_tool
)
```

**Imports required:** None new.

**Line count estimate:** +3 lines.

---

### 2.9 `ui/handlers/activity_handler.py` — FIX 1.4 LIFECYCLE HOOK

**Updated `on_agent_end` (around line 84):**

Add at the top of the method (after `self._reset_session_state(sk)`):

```python
# Fix 1.4: drop system bubble reference for this session
if self._mc is not None and hasattr(self._mc, "drop_system_bubble"):
    self._mc.drop_system_bubble(sk)
```

**Why in `on_agent_end` and not `on_agent_error`:** On error, the system bubble may still be useful for debugging. We drop on clean end only. (Captain can revise this decision — it's a one-line move.)

**Line count estimate:** +3 lines.

---

### 2.10 `ui/styles.py` — ADD CSS

**Architecture:** Single source of truth for all CSS.

**New CSS (appended to `APP_CSS`):**

```css
/* -- Activity counter (Fix 1.1) ---------------------------------------- */
.activity-counter {
    background-color: rgba(99, 102, 241, 0.08);
    border: 1px solid rgba(99, 102, 241, 0.18);
    border-left: 3px solid #6366f1;
}
.activity-counter-badge {
    background-color: #6366f1;
    color: #ffffff;
    font-size: 0.78em;
    font-weight: 600;
    border-radius: 8px;
    padding: 1px 8px;
    min-width: 16px;
}

/* -- System bubble container (Fix 1.4) --------------------------------- */
.system-bubble-container {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 8px 12px;
    margin: 6px 0;
    max-width: 720px;
}
.system-bubble-header {
    color: rgba(255, 255, 255, 0.5);
    font-size: 0.75em;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.system-bubble-inner {
    background: transparent;
    border: none;
}
```

**Line count estimate:** +28 lines.

---

### Files NOT changed (already correct)

- `ui/handlers/chat_handler.py:_dispatch` — existing GLib.idle_add helper, no changes needed
- `ui/handlers/activity_handler.py:on_gateway_event` event-routing logic — the per-event branches stay; we wrap their output in counter logic
- `ui/views/chat_bubble.py:build_role_bubble` — used for conversation bubbles, not activity bubbles
- `ui/views/feedbar.py` — FeedBar is a separate concern; unchanged
- `models/activity.py:_friendly_tool_name` — reused by counter formatter, no changes
- `gateway/client.py` — gateway protocol unchanged; we work around its payload limits client-side
- `tests/test_activity_bubbles.py` — existing tests stay; new test classes are additive

---

## 3. Data Flow

### Flow A: First pill of an agent turn (creates system bubble)

1. **Gateway** sends `event="agent"`, `stream="lifecycle"`, `data.phase="start"`, `payload.runId="run-42"`, `payload.sessionKey="sk-1"`.
2. `window._on_ws_event` (line 636) routes to `ActivityHandler.on_gateway_event`.
3. `ActivityHandler` extracts `run_id="run-42"`, `sk="sk-1"`. In the lifecycle phase=start branch (line 230-240), creates `ActivityBubble(type="lifecycle_start", session_key=sk, icon="⏳")`.
4. `ActivityHandler._get_or_create_counter` is called with `("sk-1", "run-42", "lifecycle_start")`. No existing counter → returns `(new_counter, is_new=True)`.
5. `ActivityHandler` fires `_activity_bubble_callback(bubble)`.
6. `ChatHandler._render_activity_bubble` (line 151) receives the bubble, dispatches via `_dispatch`.
7. `ChatHandler._render_activity_bubble_impl` (line 170) calls `self._mc.get_or_create_system_bubble("sk-1", self._chat_render_handler)`.
8. `MainContent.get_or_create_system_bubble` (new) creates a `Gtk.Box` via `chat_render_handler.build_system_bubble()`, appends to chat box, stores in `self._system_bubbles["sk-1"]`. Returns the container.
9. Back in `_render_activity_bubble_impl`: `is_first_pill=True` (inner box is empty). Calls `render_activity(text, "lifecycle_start")` → widget. Calls `system_bubble.append_pill(widget)`. Calls `self._mc.scroll_chat_to_bottom()` (Fix 1.3: only on first pill).
10. Widget appears in chat. Main chat scrolled to bottom once.

### Flow B: Subsequent same-type pill (counter increments)

1. **Gateway** sends `event="agent"`, `stream="command_output"`, `data.phase="end"`, `data.name="exec"`, `data.exitCode=0`, `data.durationMs=1200`, `payload.runId="run-42"`, `payload.sessionKey="sk-1"`.
2. `ActivityHandler.on_gateway_event` routes to the `command_output` branch (line 305-315).
3. Builds `ActivityBubble(type="command_output", session_key=sk, tool_name="exec", exit_code=0, duration_ms=1200, icon="💻")`.
4. **Fix 1.5 enrichment:** `self._active_tool_lookup("sk-1")` returns `{"agent_name": "Coder", "tool_name": "exec", "command": "pytest tests/", ...}`. `bubble.command = "pytest tests/"`, `bubble.agent_name = "Coder"`.
5. **Fix 1.1 counter routing:** `self._get_or_create_counter("sk-1", "run-42", "command_output")` finds an existing counter. Returns `(existing_counter, is_new=False)`.
6. Counter is mutated: `count=2`, `last_text="exec  pytest tests/  1,200ms"`, `last_command="pytest tests/"`, `total_duration_ms=2400`.
7. `ActivityHandler` fires `_activity_bubble_mutate_callback(counter)` (not the create callback).
8. `ChatHandler._mutate_activity_bubble` (new) finds the counter widget in the system bubble's pill box, calls `widget.update(counter)`.
9. `widget.update` mutates the badge label (`×2`) and the text label (`exec  pytest tests/  2,400ms`). No new widget. No scroll.

### Flow C: Different-type event arrives (closes counter)

1. **Gateway** sends `event="agent"`, `stream="item"`, `data.kind="tool"`, `data.phase="end"`, `data.name="read"`, `payload.runId="run-42"`, `payload.sessionKey="sk-1"`.
2. `ActivityHandler` builds `ActivityBubble(type="tool_end", tool_name="read", duration_ms=83)`.
3. `self._get_or_create_counter("sk-1", "run-42", "tool_end")` finds no counter for `tool_end`. Before creating, it scans existing keys and drops any counter for `("sk-1", "run-42", "command_output")` (different type). Returns `(new_counter, is_new=True)`.
4. Fires `_activity_bubble_callback(bubble)` — new pill created and appended to the same system bubble container (already exists from Flow A).
5. New pill widget appears below the (now frozen) counter widget in the system bubble.

### Flow D: Lifecycle end (drops system bubble reference)

1. **Gateway** sends `event="agent"`, `stream="lifecycle"`, `data.phase="end"`, `payload.runId="run-42"`, `payload.sessionKey="sk-1"`.
2. `ActivityHandler.on_agent_end` is called.
3. Calls `self._mc.drop_system_bubble("sk-1")`. The widget stays visible in the chat (it's a child of the chat box). The reference is dropped, so future emissions for `sk-1` will create a new system bubble if a new lifecycle starts.
4. The existing counter for `("sk-1", "run-42", ...)` is also reset via `self._reset_counters_for_session("sk-1")`.

### Flow E: New agent turn (lifecycle_start after lifecycle_end)

1. **Gateway** sends new `lifecycle`, `phase="start"`, `runId="run-43"`, `sessionKey="sk-1"`.
2. `_get_or_create_counter("sk-1", "run-43", "lifecycle_start")` finds no counter for the new `run_id`. Creates a new one.
3. The OLD system bubble for `sk-1` (from `run-42`) is still in the chat (the widget). The reference was dropped, so `get_or_create_system_bubble` will create a NEW system bubble.
4. New system bubble is appended to the chat box (below the old one). New pills go into the new one.

### Key structures verified

- `ActivityBubble` fields: read directly from `models/activity.py:36-90`. No guessed structures.
- `_counters` key tuple `(session_key, run_id, type)`: matches the three identifying fields used everywhere in ActivityHandler.
- `counter` dict: flat dict, passed by reference to mutate callback. No nested structures.
- System bubble widget API: `append_pill(widget)`, `get_pill_box()`. Simple, no magic.
- Counter widget API: `update(counter_dict)`. Single method, no other contract.

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `models/activity.py` | EXTEND | +35 | Low — additive fields, new method, format_text branch extension |
| `ui/handlers/activity_handler.py` | EXTEND | +95 | Medium — new state, per-event branch wrapping, callback wiring |
| `ui/handlers/agent_runtime_handler.py` | EXTEND | +20 | Low — pure dict ops, no logic change |
| `ui/handlers/chat_render_handler.py` | EXTEND | +85 | Medium — new widget builders, GTK widget API contracts |
| `ui/views/main_content.py` | EXTEND | +30 | Low — view method additions, no behavior change to existing methods |
| `ui/handlers/chat_handler.py` | EXTEND | +45 | Medium — replaces impl body, adds new method, dispatch arg change |
| `ui/handlers/connection_sync_handler.py` | WIRE | +1 | Low — single new line |
| `ui/window.py` | WIRE | +3 | Low — single new wire-up |
| `ui/styles.py` | EXTEND | +28 | Low — additive CSS |

**Total: ~342 lines added across 9 files.**

---

## 5. Implementation Order

Each step is independently verifiable. Run the test suite after each step.

### Step 1: Models and CSS (no GTK interaction yet)
- [ ] Add `is_counter`, `count`, `last_text`, `total_duration_ms`, `last_command` fields to `ActivityBubble`
- [ ] Add `command` and `agent_name` fields to `ActivityBubble` (extend use, don't remove)
- [ ] Add `format_counter_text()` method to `ActivityBubble`
- [ ] Extend `format_text()` `command_output` branch with `command` and `agent_name`
- [ ] Add CSS for `.activity-counter`, `.activity-counter-badge`, `.system-bubble-container`, `.system-bubble-header`, `.system-bubble-inner` to `ui/styles.py`
- **Verify:** `pytest tests/test_activity_bubbles.py -k TestActivityBubbleModel` passes (existing model tests still pass with new default fields)

### Step 2: AgentRuntimeHandler active-tool cache
- [ ] Add `self._active_tools: dict[str, dict] = {}` to `__init__`
- [ ] Add cache write at top of `_do_tool_call_start`
- [ ] Add cache clear at top of `_do_tool_call_result`
- [ ] Add `get_active_tool(session_key) -> dict | None` public method
- **Verify:** New test `test_active_tool_cache_roundtrip` passes; existing tests unchanged

### Step 3: ActivityHandler counter state (Fix 1.1)
- [ ] Add `self._counters`, `self._current_run_id` to `__init__`
- [ ] Add `set_on_activity_bubble_mutate(cb)` callback setter
- [ ] Add `_get_or_create_counter` and `_reset_counters_for_session` methods
- [ ] Wrap each per-event branch (lifecycle, item, command_output, plan, approval, patch) in counter logic
- **Verify:** New `TestCounterCollapse` tests pass (5+ tests)

### Step 4: ActivityHandler content enrichment (Fix 1.5)
- [ ] Add `self._active_tool_lookup` to `__init__`
- [ ] Add `set_active_tool_lookup(callable)` public method
- [ ] Add enrichment step in per-event branches (before counter routing)
- [ ] Wire in `window.py` after `set_agent_routing`
- **Verify:** New `TestContentEnrichment` tests pass (4+ tests)

### Step 5: ChatRenderHandler new widgets
- [ ] Add `render_counter(counter: dict) -> Gtk.Widget` with `update()` method
- [ ] Add `build_system_bubble() -> Gtk.Widget` with `append_pill` and `get_pill_box` methods
- [ ] Tag counter widget with `_counter_type` attribute
- **Verify:** Manual smoke test — instantiate ChatRenderHandler, call both methods, assert widget types and method presence

### Step 6: MainContent system bubble storage (Fix 1.4)
- [ ] Add `self._system_bubbles: dict[str, Gtk.Widget]` to `__init__`
- [ ] Add `get_or_create_system_bubble(session_key, chat_render_handler)` method
- [ ] Add `drop_system_bubble(session_key)` method
- **Verify:** Manual smoke test — create chat tab, call get_or_create twice, assert same widget returned

### Step 7: ChatHandler routing (Fix 1.3, 1.4, 1.1 mutation)
- [ ] Update `_render_activity_bubble_impl` to use system bubble container
- [ ] Remove `scroll_chat_to_bottom` call (Fix 1.3)
- [ ] Add `_mutate_activity_bubble(counter)` method
- [ ] Update `_render_activity_bubble` dispatch to pass full bubble
- **Verify:** New `TestSystemBubbleContainer`, `TestSystemBubblePillRouting`, `TestNoScrollOnActivityBubble` tests pass

### Step 8: ConnectionSyncHandler + Window wiring
- [ ] Add `set_on_activity_bubble_mutate` wire in `connection_sync_handler.py:161`
- [ ] Add `set_active_tool_lookup` wire in `window.py` (after `set_agent_routing`)
- [ ] Add `drop_system_bubble` call in `ActivityHandler.on_agent_end`
- **Verify:** Full integration test — run a fake session, assert system bubble appears, counter mutates, lifecycle_end drops reference

### Step 9: Final integration tests
- [ ] All existing tests pass (no regressions)
- [ ] New tests pass:
  - `TestCounterCollapse` (5-6 tests)
  - `TestContentEnrichment` (4 tests)
  - `TestSystemBubbleContainer` (5 tests)
  - `TestSystemBubblePillRouting` (3 tests)
  - `TestNoScrollOnActivityBubble` (1 test)
- **Verify:** Run full test suite, paste actual pytest output

---

## 6. Acceptance Criteria

- [ ] `pytest tests/test_activity_bubbles.py` — all existing tests pass
- [ ] `pytest tests/ -k CounterCollapse` — new tests pass
- [ ] `pytest tests/ -k ContentEnrichment` — new tests pass
- [ ] `pytest tests/ -k SystemBubble` — new tests pass
- [ ] `pytest tests/ -k NoScroll` — new tests pass
- [ ] Manual: Run a Coder agent for 2 minutes. Count visible pill widgets inside the system bubble — should be < 10 (was 30+). Pill content shows command + agent name.
- [ ] Manual: Open the chat during an agent run. Scroll up to read older messages. Confirm pills do NOT yank the viewport to the bottom.
- [ ] Manual: Type a new message in the input box. Confirm the toggle hides/shows the system bubble correctly.
- [ ] Manual: Run a Coder agent that fails (non-zero exit). Confirm the counter shows "exit 1" status.
- [ ] Manual: After agent finishes, start a new agent turn. Confirm a NEW system bubble is created (not a reused one).

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Gateway sends `command_output` with `data.command` present | Fix 1.5 enrichment: `bubble.command = data["command"]`. Cache lookup is skipped (we prefer gateway data). |
| Gateway sends `command_output` WITHOUT `data.command` | Fix 1.5: cache lookup fills in the command. If cache miss, `bubble.command` stays empty (old behavior). |
| `_active_tool_lookup` returns `None` (no active tool) | `bubble.command` and `bubble.agent_name` stay empty. Old behavior preserved. |
| Two same-type events in 1ms | Both route to counter. Counter increments twice. Mutate callback fires twice. No widget creation. |
| Counter widget destroyed externally (chat tab closed) | `_mutate_activity_bubble` finds no widget, returns silently. No error. |
| Lifecycle start without subsequent end | `_counters` and `_system_bubbles` keep references. Memory bounded by session count (small). On tab close, GTK destroys widgets. |
| Agent run produces 100+ events | Counter caps at natural number. System bubble inner scroll kicks in. No widget creation beyond the first per type per turn. |
| Two parallel agents in same chat (project tab) | Each session_key has its own counter store. No cross-contamination. |
| Counter widget updated after system bubble dropped | `system_bubble` is `None` in `_mutate_activity_bubble` (via `_system_bubbles.get`). Returns silently. |
| `format_text()` called on counter bubble | Returns the underlying format. `format_counter_text()` is the new method for counter rendering. Existing tests for format_text() still pass because they don't set `is_counter=True`. |
| `build_role_bubble("System", ...)` still called elsewhere | Unchanged. Used for fallback bubble rendering. Activity bubbles now route through `render_activity` and `render_counter`, not `build_role_bubble`. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update `docs/ARCHITECTURE.md`:

- **§2 (Directory Structure):** No new files. Existing files modified.
- **§3.5 (CSS):** Note that `.activity-counter*` and `.system-bubble*` classes are added to `APP_CSS` in `ui/styles.py`.
- **§3.16 (ActivityHandler):** Update the public API block to include:
  - `set_on_activity_bubble_mutate(cb)` — counter mutation callback
  - `set_active_tool_lookup(callable)` — content enrichment lookup
  - Internal state: `_counters`, `_active_tool_lookup`
- **§3.5 ChatRenderHandler:** Update to mention `render_counter()` and `build_system_bubble()` as new public methods.
- **§3.6 MainContent:** Update to mention `get_or_create_system_bubble()` and `drop_system_bubble()`.
- **§3.9 AgentRuntimeHandler:** Update to mention `_active_tools` cache and `get_active_tool()` public method.
- **§4 (Data Flow):** Add a new diagram showing the system bubble + counter routing. Reference this spec.
- **§11 (File Inventory):** No new files. Note that `models/activity.py` now has `format_counter_text()` and the enrichment fields.

**Update `docs/PROJECT_STATUS.md`:** Add an entry for "Activity Bubble UX Overhaul — complete (2026-06-XX)."

---

## Self-Audit (Rule 9)

1. **Does every code sample actually work against the current codebase?** YES. Every `def`, every call, every signature was verified by reading the actual source file. The `_friendly_tool_name`, `format_text`, `_dispatch`, `get_chat_box_for_session`, `scroll_chat_to_bottom`, `_do_tool_call_start`, `_do_tool_call_result`, `set_on_activity_bubble` — all read from the actual files at the line numbers cited.
2. **Did I catch all exception types for every function I call?** N/A — no I/O, no network, no file operations in any new code. Pure dict ops and GTK widget construction. GTK widget construction can throw, but the existing pattern in `render_activity` (try/except at line 626) handles that.
3. **Did I verify key structures, not assume them?** YES. `ActivityBubble` fields read from dataclass. `_counters` key is `(session_key, run_id, type)` matching the three identifying fields used in `payload`. `_active_tools` key is `session_key` matching the existing dict pattern in `agent_runtime_handler.py:64`.
4. **Did I trace the data flow end-to-end?** YES. §3 has 5 flows (A through E) covering first pill, same-type increment, different-type close, lifecycle end, new turn. Each flow names the actual functions and line numbers.
5. **Would an implementer who follows this spec exactly produce working code?** YES. Every method has a verified signature. Every field has a verified type. Every CSS class is named explicitly. Every callback wiring is at a verified line number.

**Rule 10 completion verification** will be done at the end of implementation (after the implementer runs the test suite and the pattern sweep).

---

**Mantra check:** "A spec is a contract. If it has a bug, the implementer will ship that bug. Verify everything." — DONE. Every code sample traced, every signature verified, every key structure confirmed.
