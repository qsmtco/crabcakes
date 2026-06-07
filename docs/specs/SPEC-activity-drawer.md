# SPEC: Activity Drawer

**Date:** 2026-06-01
**Author:** QTR (Kage-7) — operative code: blade that cuts time
**Status:** Draft — for implementation
**Implements:** [docs/proposals/PROPOSAL-activity-drawer.md](../proposals/PROPOSAL-activity-drawer.md)
**Depends on:** None (this is a fresh feature; supersedes PROPOSAL-activity-bubble-ux.md)
**Target branch:** main

> **Architecture compliance.** This spec strictly follows [docs/ARCHITECTURE.md](../ARCHITECTURE.md). Specifically:
> - §2 directory structure — `ui/views/activity_drawer.py` placed under `ui/views/`
> - §3 module responsibilities — drawer is a pure view (no business logic), formatter logic kept in `models/activity.py`
> - §4 data flow — event flow preserved: `ActivityHandler → callback → drawer.append_event()`
> - §5 patterns — callbacks are the communication mechanism, GLib.idle_add() for thread safety
> - §6 architectural rules — `models/` has no GTK, `ui/views/` no business logic, `ui/handlers/` no widget construction
> - §11 file inventory — new file `ui/views/activity_drawer.py` added
> - §13 principles preserved: 1 (Gateway independence), 2 (Models are pure data), 3 (Composed UI), 4 (Callbacks), 7 (Comments for humans)

---

## DISCOVERY

```
DISCOVERY:
- Read models/activity.py (138 lines): ActivityBubble dataclass — fields: type, session_key, tool_name, duration_ms, status, icon, title, steps, command, approval_id, reason, exit_code, added, modified, deleted, raw_text. ActivityType Literal: "lifecycle_start", "tool_start", "tool_end", "tool_error", "plan", "approval_request", "command_output", "patch". format_text() returns single-line text. NO agent_name, output, file_path, file_relative, or timestamp fields exist yet. Helper _friendly_tool_name() exists for tool name display. to_drawer_row() does NOT exist yet.
- Read ui/handlers/activity_handler.py (335+ lines): 6-state machine (idle|sending|reasoning|streaming|tool_use|done). on_gateway_event() fires _activity_bubble_callback for: lifecycle_start (stream=lifecycle phase=start), tool_start/tool_end/tool_error (stream=item kind=tool), plan (stream=plan), approval_request (stream=approval phase=requested), command_output (stream=command_output phase=end), patch (stream=patch phase=end). _activity_bubble_callback is set via set_on_activity_bubble(cb). The command_output branch (lines 305-315) currently extracts ONLY name/exitCode/durationMs — no command string, no output text. There is NO streaming `command_output` phase=start handler — only phase=end fires a bubble. There is NO agent_start_callback or agent_end_callback on ActivityHandler; only on_agent_start() and on_agent_end() methods that drive FeedBar state.
- Read ui/handlers/chat_handler.py (~810 lines): _render_activity_bubble(self, bubble) at line 151, _render_activity_bubble_impl(self, session_key, text, activity_type) at line 170, set_on_activity_bubble(self, cb) at line 187. set_on_activity_bubble stores callback in self._activity_bubble_callback. The set_on_activity_bubble setter in CHAT HANDLER is NOT the same as the one in ActivityHandler — chat handler's stores a callback to RECEIVE bubbles from ActivityHandler. The chain: ActivityHandler._activity_bubble_callback → ChatHandler._render_activity_bubble. To route to drawer instead, change window.py wiring.
- Read ui/handlers/chat_render_handler.py (~860 lines): render_activity(self, text, activity_type) at line 589-621 returns a centered pill (outer wrapper Gtk.Box) with inner pill (.activity-bubble CSS class) and label (.activity-bubble-text). Wraps in try/except, returns None on error. This is what we are REMOVING — not replacing with a stub.
- Read ui/views/main_content.py (~880 lines): set_chat_render_handler(handler) at line 718. scroll_chat_to_bottom(page_index=None) at line 718 — called 14+ times from chat_handler.py. get_chat_box_for_session(session_key) at line 684. create_chat_tab(session_key, agent_name) at line 242. _build() creates a vertical Gtk.Box right side — this is where the drawer will be added as a sibling.
- Read ui/window.py (495+ lines): _build() at line 89 is the composition root. ActivityHandler created at line 232-235 with set_agent_routing() at line 237. main_content = MainContent() at line 111. The right side of the horizontal Paned is set up in _build — we wrap it in a vertical Paned (new).
- Read tests/test_activity_bubbles.py (210+ lines): TestActivityBubbleModel covers format_text() for all 8 ActivityTypes. TestActivityHandlerActivityBubbles covers callback firing for each event type with exact payload structures. TestChatHandlerActivityBubbleRender covers routing logic. These tests must be updated: the chat-rendering tests get REMOVED, the model + handler tests stay.
- Read ui/styles.py: existing CSS classes .activity-bubble, .activity-bubble-text, .activity-tool_error .activity-bubble-text, .activity-approval_request .activity-bubble-text, .activity-lifecycle_start .activity-bubble-text (lines 463-510) — these become DEAD CODE after this spec and are removed. New CSS classes .activity-drawer, .activity-drawer-header, .activity-drawer-row, .activity-drawer-separator, .activity-drawer-counter are added.
- Architecture owner: ActivityBubble is owned by models/activity.py (per ARCHITECTURE.md §3.7 "no business logic"). ActivityHandler is owned by ui/handlers/activity_handler.py. The drawer is owned by ui/views/activity_drawer.py (NEW, per ARCHITECTURE.md §2 directory structure). Formatter logic stays in models/activity.py (per "models are pure data" rule).
- Existing patterns: MainContent is a Gtk.Box that owns the chat notebook + input. FeedBar (ui/views/feedbar.py) is a pure view widget injected into MainContent with state pushed from ActivityHandler. We mirror that pattern: ActivityDrawer is a pure view widget, ActivityHandler pushes state via set_on_activity_bubble callback. (We are not pushing state through the existing set_on_activity_bubble — we are changing where the callback is wired.)
- FileTree (ui/views/file_tree.py) and LeftPanel use Gtk.Paned already. The new vertical Gtk.Paned in window.py mirrors the horizontal Paned pattern at line ~120.
- AgentRuntimeHandler._do_tool_call_start at line 512 already has args.get('command', '?') available for exec_command. No 10-minute gateway debug log needed — the command string is already in args. The gateway's stream=command_output event does NOT carry the command text (verified at activity_handler.py:305-315, only name/exitCode/durationMs are extracted). The command MUST be captured at AgentRuntimeHandler level and threaded into the command_output bubble.
- **TODO before implementation:** Verify that `data.agentName` exists on `stream=item kind=tool` events (`tool_start`/`tool_end`/`tool_error`). The spec assumes it does for populating `agent_name` on non-lifecycle bubbles. If the gateway does NOT send `agentName` on tool events, `agent_name` will default to `''` and the drawer will show `[Agent]` instead of `[Coder]` for those events. In that case, the drawer must fall back to resolving the agent name from `AgentManager` via `session_key`.
- ActivityHandler.on_gateway_event()'s command_output branch (line 305-315) does NOT extract the command text or stdout/stderr output. The data dict from the gateway contains: {phase, name, exitCode, durationMs}. The output text is NOT in the gateway event payload — it is a separate stream=item kind=command event that fires with stdout/stderr chunks, OR it must be sourced from AgentRuntimeHandler's local exec tool (which has the command in args and could capture output via subprocess). For this spec, click-to-expand shows the command string captured by AgentRuntimeHandler — we do NOT add a new output field to ActivityBubble until we have a confirmed source.
```

---

## 1. Overview

### Problem Statement

Activity bubbles (centered pill-shaped indicators) are currently rendered **inline in the chat container** at `chat_render_handler.py:589-621`. Three failures result:

1. **Chat pollution.** 30+ pills per 10-minute session consume 1,400+ vertical pixels in the chat. The chat viewport is dominated by status indicators, not conversation.
2. **Scroll hijacking.** 14 `scroll_chat_to_bottom()` call sites in `chat_handler.py` re-fire on every pill append, forcing the user away from older content.
3. **Visual redundancy with FeedBar.** `ui/views/feedbar.py` already shows current agent state via the state machine. Activity pills repeat this in a more invasive location.

The data is valuable (knowing Coder ran `pytest` in 1,247ms is real signal). The delivery surface is wrong.

### Solution Summary

Replace chat-inline activity pills with a **collapsible drawer** that lives below the chat in a new vertical `Gtk.Paned`. The drawer holds all activity events in its own scrollable `Gtk.ListBox` and never touches the chat viewport.

**Six deliverables in this spec:**

1. **ActivityDrawer view** (`ui/views/activity_drawer.py`, NEW) — collapsible panel with header, count label, clear button, and scrollable row list. Pure view — receives `to_drawer_row()` dicts from a callback.
2. **Structural rewrite of `window.py._build()`** — wrap `MainContent` in a new vertical `Gtk.Paned`; drawer is the bottom pane.
3. **Activity callback rewiring** — `ActivityHandler._activity_bubble_callback` is connected to `ActivityDrawer.append_event()` instead of `ChatHandler._render_activity_bubble()`. The ChatHandler's `_render_activity_bubble()`, `_render_activity_bubble_impl()`, and `set_on_activity_bubble()` are REMOVED (dead code).
4. **Content enrichment (`ActivityBubble.to_drawer_row()`)** — new method on `ActivityBubble` that returns a structured dict with all the fields the drawer needs: agent_name, timestamp, file_path (relative), command, output (if available), icon, type_label, count metadata, duration, exit_code.
5. **New fields on `ActivityBubble`** — `agent_name: str = ""`, `command: str = ""` (used for `command_output`), `output: str = ""` (used for click-to-expand), `file_path: str = ""` (for read/write/edit events). All defaulted to empty string.
6. **Per-agent + per-type filter** — dropdown menus in the drawer header for filtering by agent and by pill type. AND semantics. All-on default. Filter survives drawer toggle, resets on app restart.
7. **Lifecycle separators + click-to-expand** — small marker rows for agent start/end; `Gtk.Revealer` for exec row click-to-expand of the last 10 lines of the captured output.
8. **New public method on ActivityHandler** — `set_on_agent_lifecycle(cb)` — fires `cb(session_key, agent_name, "start" | "end")` so the drawer can insert lifecycle separator rows.

### Scope (In/Out)

| In scope | Out of scope |
|----------|--------------|
| Drawer shell, header, list, clear button, toggle | Persisting drawer state across app restarts (Future Work §11.5) |
| Counter-collapse with per-agent scoping | Group-by-agent collapse (Future Work §11.4) |
| `to_drawer_row()` method on `ActivityBubble` | Per-agent row caps on lifecycle end (Future Work §11.1) |
| New `agent_name`, `command`, `output`, `file_path` fields on `ActivityBubble` | Search-in-drawer (Future Work §11.2) |
| Wiring ActivityHandler command_output to capture command text (via AgentRuntimeHandler) | Export drawer history to file (Future Work §11.3) |
| Removing chat-inline activity rendering | Changing FeedBar behavior (FeedBar stays) |
| Per-agent + per-type filter dropdowns | Filter persistence to disk |
| Lifecycle separator rows (start, end, summary) | Custom activity icons per agent type |
| Click-to-expand for exec/command_output rows via `Gtk.Revealer` | Configurable output line count (hard-coded at 10) |
| CSS classes for new drawer widgets | Light theme variant (uses default theme) |
| Tests for new drawer (pytest) and updated tests for removed chat-rendering path | UI/UX manual testing (out of band) |

### Architecture Principles Applied

- **Principle 2 (Models are pure data).** `ActivityBubble` is extended with new fields. All formatting logic stays in the model. The view receives a dict and renders — no GTK in the model.
- **Principle 3 (UI is composed, not inherited).** `MainWindow._build()` instantiates `ActivityDrawer` and wires it. The drawer is a leaf widget.
- **Principle 4 (Callbacks are the communication mechanism).** `ActivityHandler._activity_bubble_callback` is rewired. No direct method calls on sibling components.
- **Principle 5 (Checkpoints over shortcuts).** Day 1 (structural) ships independently. Day 2-3 add value.
- **Principle 7 (Comments for humans).** New code is documented; why-decisions are explained.

---

## 2. Changes by File

### 2.1 `models/activity.py` — Add fields and `to_drawer_row()` method

**Change type:** Modify. New fields, one new method. Existing fields and `format_text()` unchanged. Backward compatible — existing tests pass.

**Imports (existing):**
```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
```

**New import added:**
```python
import datetime
```

**New fields on `ActivityBubble`** (appended after `raw_text: str = ""` field):

```python
    agent_name: str = ""           # Display name of the agent that emitted this event (e.g. "Coder")
    command: str = ""              # For command_output: the shell command that ran (e.g. "pytest tests/")
    output: str = ""               # For click-to-expand: last 10 lines of stdout/stderr (truncated)
    file_path: str = ""            # For tool_start/tool_end: relative path of the file being touched
```

**New method `to_drawer_row()`** (added to `ActivityBubble` class, after `format_text()`):

```python
    def to_drawer_row(self) -> dict:
        """Convert to structured dict for ActivityDrawer row rendering.

        Returns all the fields the drawer needs in a flat dict:
        - timestamp: HH:MM wall-clock time (set at conversion time, not event time — for v1)
        - agent: agent display name (defaults to "Agent" if agent_name is empty)
        - icon: emoji prefix (e.g. "🔧")
        - type_label: the activity type as a short label (e.g. "exec", "read", "plan")
        - file_path: relative path for file events; "" otherwise
        - command: command string for command_output; tool_name otherwise
        - exit_code: integer for command_output; None for non-exec types
        - duration: formatted duration string (e.g. "4.2s", "83ms")
        - activity_type: the type as a string, used by the drawer for filter matching
        - output: stdout/stderr tail for click-to-expand; "" otherwise
        - raw_text: one-line text from format_text(), used as fallback detail
        - duration_ms: integer milliseconds, for arithmetic (counter sum, sorting)

        Pure function — no GTK, no I/O. Safe to call from any thread.
        """
        return {
            "timestamp": datetime.datetime.now().strftime("%H:%M"),
            "agent": self.agent_name or "Agent",
            "icon": self.icon,
            "type_label": _type_label(self.type),
            "file_path": self.file_path,
            "command": self.command or _friendly_tool_name(self.tool_name),
            "exit_code": self.exit_code if self.type == "command_output" else None,
            "duration": _format_duration(self.duration_ms),
            "activity_type": self.type,
            "output": self.output,
            "raw_text": self.format_text(),
            "duration_ms": self.duration_ms,
        }
```

**New module-level helpers** (added at bottom of `models/activity.py`):

```python
def _type_label(activity_type: str) -> str:
    """Map ActivityType to a short human label for the drawer row.

    Examples:
        "tool_start" with tool_name="exec" → "exec"
        "tool_start" with tool_name="read_file" → "read"
        "command_output" → "exec"
        "lifecycle_start" → "lifecycle"
        "plan" → "plan"
        "approval_request" → "approval"
        "patch" → "patch"
    """
    if activity_type == "command_output":
        return "exec"
    if activity_type in ("tool_start", "tool_end", "tool_error"):
        # Use the tool_name's friendly form to disambiguate exec vs read vs write
        return ""  # caller should use friendly_tool_name
    if activity_type == "lifecycle_start":
        return "lifecycle"
    if activity_type == "plan":
        return "plan"
    if activity_type == "approval_request":
        return "approval"
    if activity_type == "patch":
        return "patch"
    return activity_type


def _format_duration(ms: int) -> str:
    # Keep in sync with ui/views/activity_drawer.py:_format_duration
    # Duplicated to avoid circular import (model → view).
    """Format milliseconds as '83ms' or '4.2s' or '1m 23s'.

    Args:
        ms: integer milliseconds (0 → "0ms")

    Returns:
        Compact human-readable duration string.
    """
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes, secs = divmod(ms // 1000, 60)
    return f"{minutes}m {secs}s"
```

**Line count estimate:** +70 lines (4 fields, 1 method, 2 helpers, comments).

**Verified against source:** `ActivityBubble` is a `@dataclass` — adding defaulted fields at the end is backward compatible. The existing `format_text()` is untouched. `to_drawer_row()` is a new method that does not conflict with anything.

---

### 2.2 `ui/views/activity_drawer.py` — NEW FILE

**Change type:** Create. Pure view widget. ~280 lines.

**Imports:**

```python
from __future__ import annotations

from typing import Callable

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk, Pango
```

**Full class implementation:**

```python
class ActivityDrawer(Gtk.Box):
    """Collapsible activity event panel below the chat.

    Pure view — no business logic, no gateway calls, no state mutations
    beyond its own widget tree. Receives activity events via append_event()
    and lifecycle events via on_agent_start()/on_agent_end().

    Architecture (per ARCHITECTURE.md §3.7 / §3.21):
    - Lives in ui/views/ — no imports from gateway/, models/, or agent/
    - Receives data via callbacks set by ActivityHandler / window.py._build()
    - No GLib.idle_add() — append_event() must be called on the GTK main thread
      (ActivityHandler already does GLib dispatch before firing callbacks)
    """

    MAX_ROWS = 100  # global cap; oldest 25 trimmed at once when exceeded
    TRIM_BATCH = 25  # rows to remove per trim
    DEFAULT_VISIBLE_PX = 200  # max_content_height for the inner ScrolledWindow
    OUTPUT_LINE_CAP = 10  # lines of stdout/stderr shown in click-to-expand

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("activity-drawer")

        # ── State ─────────────────────────────────────────────────────
        # Filter state — independent AND filters
        # _visible_agents: set of agent names that pass the filter; empty set = all
        # _visible_types: set of activity types that pass the filter; empty set = all
        # Default = both empty (no filtering, all rows pass)
        self._visible_agents: set[str] = set()
        self._visible_types: set[str] = set()

        # Per-agent counter state — the (agent, type) key of the last appended row,
        # so the next matching event mutates that row's count in place.
        self._last_row_key: tuple[str, str] | None = None
        self._last_row_widget: Gtk.Box | None = None  # backing widget for in-place mutation

        # Per-agent counter dict — {agent_name: {"count": int, "duration_ms": int, "last_command": str}}
        # Popped on that agent's lifecycle_end so its next start begins a fresh counter.
        self._agent_counters: dict[str, dict] = {}

        # Known agent list — collected from events as they arrive. Used to populate
        # the agent filter dropdown. Cleared on clear_events().
        self._known_agents: set[str] = set()

        # Known type list — same idea, for the type filter dropdown.
        self._known_types: set[str] = set()

        # Lifecycle separator tracking — when a separator was last inserted, what agent
        # and which side (start, end). Used to prevent double-separator inserts.
        self._last_separator_agent: tuple[str, str] | None = None  # (agent, "start"|"end")

        # Row counter for the header label (total events ever appended, not visible)
        self._total_count: int = 0

        # Currently expanded row widgets (click-to-expand state) — we re-collapse
        # on clear_events() to free the revealers.
        self._expanded_rows: set[Gtk.Box] = set()

        # ── Build widgets ────────────────────────────────────────────
        self._build_header()
        self._build_list()

        # Start collapsed (header-only visible) per proposal §10.1
        self._expanded = False
        self._apply_expanded_state()

    # ── Construction helpers ──────────────────────────────────────

    def _build_header(self) -> None:
        """Build the drawer header bar: toggle, count label, clear button, filter menus."""
        self._header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._header.add_css_class("activity-drawer-header")

        # Toggle button (▼/▶)
        self._toggle_btn = Gtk.Button(label="▶ Activity")
        self._toggle_btn.connect("clicked", self._on_toggle_clicked)
        self._header.append(self._toggle_btn)

        # Count label — shows "0 events" initially
        self._count_label = Gtk.Label(label="0 events")
        self._count_label.set_xalign(0.0)
        self._count_label.set_hexpand(True)
        self._header.append(self._count_label)

        # Agent filter dropdown — menu button. Label is "Agent: all" by default.
        self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
        self._agent_filter_btn.connect("clicked", self._on_agent_filter_clicked)
        self._header.append(self._agent_filter_btn)

        # Type filter dropdown — menu button. Label is "Type: all" by default.
        self._type_filter_btn = Gtk.MenuButton(label="Type: all")
        self._type_filter_btn.connect("clicked", self._on_type_filter_clicked)
        self._header.append(self._type_filter_btn)

        # Clear button
        self._clear_btn = Gtk.Button(label="Clear")
        self._clear_btn.connect("clicked", self._on_clear_clicked)
        self._header.append(self._clear_btn)

        self.append(self._header)

    def _build_list(self) -> None:
        """Build the scrollable row list inside a Gtk.ScrolledWindow."""
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # set_max_content_height caps the scrolled area; GTK 4.10+ required.
        # This project ships GTK 4.14 (verified by Gtk.get_major_version() at runtime).
        self._scrolled.set_max_content_height(self.DEFAULT_VISIBLE_PX)
        self._scrolled.set_propagate_natural_height(True)
        # Hide the scrolled window when the drawer is collapsed
        self._scrolled.set_visible(False)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._scrolled.set_child(self._list)

        self.append(self._scrolled)

    # ── Public API (called by ActivityHandler via callbacks) ─────

    def append_event(self, row: dict) -> None:
        """Append an activity event row from a to_drawer_row() dict.

        Per-agent counter-collapse: if the last row's (agent, activity_type) matches
        the new event's (agent, activity_type), mutate the existing row in place
        (count++, duration sum, last_command refresh). Otherwise append a new row.

        If the row does not pass the current filter, do nothing (do not append,
        do not count).

        Must be called on the GTK main thread.

        Args:
            row: dict from ActivityBubble.to_drawer_row()
        """
        agent = row.get("agent", "Agent")
        activity_type = row.get("activity_type", "")
        key = (agent, activity_type)

        # Filter check — drop the row if filtered out
        if not self._passes_filter(agent, activity_type):
            self._total_count += 1  # still counted in total, just not visible
            self._update_count_label()
            return

        # Track known agents/types for the filter dropdowns
        self._known_agents.add(agent)
        self._known_types.add(activity_type)

        # Counter-collapse check
        if self._last_row_key == key and self._last_row_widget is not None:
            self._mutate_counter_row(self._last_row_widget, row)
            self._total_count += 1
            self._update_count_label()
            return

        # Append new row
        row_widget = self._build_row_widget(row, count=1)
        self._list.append(row_widget)
        self._last_row_key = key
        self._last_row_widget = row_widget

        self._total_count += 1
        self._update_count_label()
        self._trim_if_needed()
        self._auto_scroll_to_bottom()

    def on_agent_start(self, session_key: str, agent_name: str) -> None:
        """Called when an agent turn starts (lifecycle phase=start).

        Inserts a subtle separator row. Breaks the per-agent counter chain for
        that agent (next event from that agent starts a fresh counter).

        Must be called on the GTK main thread.
        """
        # Prevent double-separator for the same agent
        if self._last_separator_agent == (agent_name, "start"):
            return

        sep = self._build_separator_widget(
            f"── {agent_name} started ──────────────────"
        )
        self._list.append(sep)

        # Break this agent's counter chain
        self._last_row_key = None
        self._last_row_widget = None
        self._last_separator_agent = (agent_name, "start")

    def on_agent_end(self, session_key: str, agent_name: str) -> None:
        """Called when an agent turn ends (lifecycle phase=end).

        Inserts a summary separator row with per-agent stats.
        Pops this agent's counter state from _agent_counters.

        Must be called on the GTK main thread.
        """
        if self._last_separator_agent == (agent_name, "end"):
            return

        counter = self._agent_counters.pop(agent_name, None)
        if counter is not None and counter.get("count", 0) > 0:
            summary = (
                f"── {agent_name}: {counter['count']} events in "
                f"{_format_duration(int(counter.get('total_duration_ms', 0)))} ────"
            )
        else:
            summary = f"── {agent_name}: ended ────────────────"

        sep = self._build_separator_widget(summary)
        self._list.append(sep)

        # Break this agent's counter chain
        self._last_row_key = None
        self._last_row_widget = None
        self._last_separator_agent = (agent_name, "end")

    def clear_events(self) -> None:
        """Remove all rows and reset all state.

        Called by the Clear button, by the window on lifecycle reset,
        or by the window on project switch (to prevent counters/rows from
        Project A carrying into Project B).
        """
        # Remove all rows
        while True:
            row = self._list.get_row_at_index(0)
            if row is None:
                break
            self._list.remove(row)

        # Reset state
        self._last_row_key = None
        self._last_row_widget = None
        self._agent_counters.clear()
        self._last_separator_agent = None
        self._total_count = 0
        self._expanded_rows.clear()
        self._update_count_label()
        self._auto_scroll_to_bottom()

    def toggle(self) -> None:
        """Programmatically toggle expanded/collapsed state.

        Public so the window or a keyboard shortcut can trigger it.
        """
        self._expanded = not self._expanded
        self._apply_expanded_state()

    # ── Row construction ────────────────────────────────────────

    def _build_row_widget(self, row: dict, count: int) -> Gtk.Box:
        """Build a single row widget from a to_drawer_row() dict.

        Returns a Gtk.Box (one row of the Gtk.ListBox). The widget stores
        metadata on itself for in-place mutation.

        The row format is:
        [timestamp] [agent] [icon] [type_label] [×count] [file_path/command] [exit_badge] [duration]

        For exec/command_output rows, the box also contains a Gtk.Revealer that
        expands on click to show the last OUTPUT_LINE_CAP lines of the output.
        """
        # Outer row box
        row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        row_box.add_css_class("activity-drawer-row")
        # Add type-specific CSS class for color/styling
        activity_type = row.get("activity_type", "")
        row_box.add_css_class(f"activity-drawer-row-{activity_type}")

        # Single-line summary
        summary = self._format_summary(row, count=count)
        label = Gtk.Label(label=summary)
        label.set_xalign(0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row_box.append(label)

        # Click-to-expand for exec/command_output
        if activity_type in ("command_output", "tool_end", "tool_error") and row.get("output"):
            revealer, toggle = self._build_revealer(row, activity_type)
            row_box.append(revealer)
            # Make the summary clickable — clicking the row toggles the revealer
            gesture = Gtk.GestureClick.new()
            gesture.connect("pressed", lambda g, n, x, y, t=toggle: t())
            row_box.add_controller(gesture)

        # Store metadata on the row box for in-place mutation
        row_box._row_meta = {  # type: ignore[attr-defined]
            "agent": row.get("agent", "Agent"),
            "activity_type": activity_type,
            "summary_label": label,
        }
        return row_box

    def _format_summary(self, row: dict, count: int) -> str:
        """Format a single-line summary for the row.

        Format: HH:MM  [Agent]  icon  type  [×N]  detail  [exit]  duration

        Where:
        - HH:MM is the row's timestamp
        - [Agent] is the agent display name in brackets
        - icon is the emoji prefix
        - type is the type label
        - ×N is the count (only if N > 1)
        - detail is file_path for file events, command for exec, raw_text for others
        - exit is ✓ 0 / ✗ N for command_output with exit_code
        - duration is the formatted duration
        """
        parts: list[str] = []
        ts = row.get("timestamp", "")
        if ts:
            parts.append(ts)
        agent = row.get("agent", "Agent")
        parts.append(f"[{agent}]")
        icon = row.get("icon", "")
        if icon:
            parts.append(icon)
        type_label = row.get("type_label", "") or _type_label(row.get("activity_type", ""))
        parts.append(type_label)
        if count > 1:
            parts.append(f"×{count}")

        # Detail: file_path > command > raw_text
        file_path = row.get("file_path", "")
        command = row.get("command", "")
        if file_path:
            parts.append(file_path)
        elif command:
            parts.append(command)
        else:
            raw = row.get("raw_text", "")
            if raw:
                parts.append(raw)

        # Exit badge
        exit_code = row.get("exit_code")
        if exit_code is not None:
            if exit_code == 0:
                parts.append("✓ 0")
            else:
                parts.append(f"✗ {exit_code}")

        # Duration
        duration = row.get("duration", "")
        if duration and duration != "0ms":
            parts.append(duration)

        return "  ".join(parts)

    def _build_revealer(self, row: dict, activity_type: str) -> tuple[Gtk.Revealer, Callable[[], None]]:
        """Build a Gtk.Revealer for click-to-expand output display.

        Returns (revealer, toggle_callable). The toggle_callable is bound to the
        row's click gesture so clicking the summary toggles expansion.

        The revealer contains a multi-line label with the last OUTPUT_LINE_CAP
        lines of the row's `output` field. If output is empty, no revealer is
        built (handled by caller).
        """
        output = row.get("output", "")
        if not output:
            return None, lambda: None  # type: ignore[return-value]

        # Tail the output to the last N lines
        lines = output.splitlines()[-self.OUTPUT_LINE_CAP:]
        if len(output.splitlines()) > self.OUTPUT_LINE_CAP:
            truncated_count = len(output.splitlines()) - self.OUTPUT_LINE_CAP
            text = f"... {truncated_count} lines earlier ...\n" + "\n".join(lines)
        else:
            text = "\n".join(lines)

        output_label = Gtk.Label(label=text)
        output_label.set_xalign(0.0)
        output_label.set_yalign(0.0)
        output_label.set_wrap(True)
        output_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        output_label.set_selectable(True)
        output_label.add_css_class("activity-drawer-output")

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)
        revealer.set_child(output_label)

        def toggle() -> None:
            new_state = not revealer.get_reveal_child()
            revealer.set_reveal_child(new_state)
            if new_state:
                self._expanded_rows.add(revealer)
            else:
                self._expanded_rows.discard(revealer)

        return revealer, toggle

    def _mutate_counter_row(self, row_widget: Gtk.Box, new_row: dict) -> None:
        """Update an existing row widget in place when counter-collapse fires.

        Updates the summary label text, the agent's running totals in
        _agent_counters, and the stored metadata.
        """
        meta = getattr(row_widget, "_row_meta", None)
        if meta is None:
            return

        agent = meta.get("agent", new_row.get("agent", "Agent"))
        # Update the agent's running counter
        counter = self._agent_counters.setdefault(
            agent, {"count": 1, "total_duration_ms": 0, "last_command": ""}
        )
        counter["count"] += 1
        counter["total_duration_ms"] += new_row.get("duration_ms", 0)
        counter["last_command"] = new_row.get("command", "")

        # Update the summary label
        label = meta.get("summary_label")
        if label is not None:
            label.set_text(self._format_summary(new_row, count=counter["count"]))

    def _build_separator_widget(self, text: str) -> Gtk.Box:
        """Build a subtle separator row (lifecycle marker).

        Returns a Gtk.Box with a single centered label. No interaction.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("activity-drawer-separator")

        label = Gtk.Label(label=text)
        label.set_xalign(0.5)
        label.set_hexpand(True)
        box.append(label)

        return box

    def _trim_if_needed(self) -> None:
        """If the row count exceeds MAX_ROWS, remove the oldest TRIM_BATCH rows."""
        # We can't get row count from Gtk.ListBox directly in GTK4; iterate
        # via get_row_at_index. Trim is rare (only every MAX_ROWS appends)
        # so O(n) iteration is acceptable.
        # NOTE: GTK 4.14 has get_row_count, but we use the portable loop.
        # Row index 0 is the first row.
        # To avoid O(n) per append, we track _total_count and only check
        # when it crosses MAX_ROWS threshold.
        # For v1 we keep this simple.
        pass  # Implemented in Day 3 polish; see _trim_old_rows_if_needed below

    def _trim_old_rows_if_needed(self) -> None:
        """Trim the oldest TRIM_BATCH rows when total exceeds MAX_ROWS.

        Skips separator rows when counting toward the cap (separators are
        not events). Uses Gtk.ListBox.get_row_at_index to iterate.
        """
        # Iterate from the top; count non-separator rows; trim when > MAX_ROWS
        to_remove: list[Gtk.ListBoxRow] = []
        non_sep_count = 0
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is None or "activity-drawer-separator" in child.get_css_classes():
                idx += 1
                continue
            non_sep_count += 1
            if non_sep_count > self.MAX_ROWS:
                to_remove.append(lb_row)
                if len(to_remove) >= self.TRIM_BATCH:
                    break
            idx += 1
        for r in to_remove:
            self._list.remove(r)

    def _auto_scroll_to_bottom(self) -> None:
        """Scroll the drawer's internal scrolled window to the bottom."""
        # The Gtk.ListBox is inside a Gtk.ScrolledWindow. We scroll the scrolled
        # window's vertical adjustment to its upper bound minus page size.
        vadj = self._scrolled.get_vadjustment()
        if vadj is not None:
            upper = vadj.get_upper()
            page_size = vadj.get_page_size()
            vadj.set_value(upper - page_size)

    def _update_count_label(self) -> None:
        """Update the count label to show 'N events' or 'N visible / M total' if filtering."""
        if not self._visible_agents and not self._visible_types:
            # No filter active
            self._count_label.set_text(f"{self._total_count} events")
        else:
            visible = self._count_visible_rows()
            self._count_label.set_text(f"{visible} visible / {self._total_count} total")

    def _count_visible_rows(self) -> int:
        """Count rows that pass the current filter (for the visible/total label)."""
        count = 0
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is not None:
                meta = getattr(child, "_row_meta", None)
                if meta is not None:
                    if self._passes_filter(meta["agent"], meta["activity_type"]):
                        count += 1
            idx += 1
        return count

    def _passes_filter(self, agent: str, activity_type: str) -> bool:
        """True if this (agent, activity_type) passes the current filter state.

        AND semantics: both an empty set and a containing set pass.
        - If _visible_agents is empty, all agents pass.
        - If _visible_agents is non-empty, agent must be in it.
        - Same for _visible_types.
        """
        if self._visible_agents and agent not in self._visible_agents:
            return False
        if self._visible_types and activity_type not in self._visible_types:
            return False
        return True

    # ── Event handlers ──────────────────────────────────────────

    def _on_toggle_clicked(self, _btn) -> None:
        self.toggle()

    def _apply_expanded_state(self) -> None:
        """Apply the current _expanded flag to the toggle label and scrolled visibility."""
        if self._expanded:
            self._toggle_btn.set_label("▼ Activity")
            self._scrolled.set_visible(True)
        else:
            self._toggle_btn.set_label("▶ Activity")
            self._scrolled.set_visible(False)

    def _on_clear_clicked(self, _btn) -> None:
        self.clear_events()

    def _on_agent_filter_clicked(self, _btn) -> None:
        """Open a popover menu listing all known agents with checkboxes."""
        self._show_filter_popover(self._agent_filter_btn, "agent", self._known_agents,
                                  self._visible_agents, self._agent_filter_btn,
                                  new_label_fn=lambda n: f"Agent: {n}" if n else "Agent: all")

    def _on_type_filter_clicked(self, _btn) -> None:
        """Open a popover menu listing all known types with checkboxes."""
        self._show_filter_popover(self._type_filter_btn, "type", self._known_types,
                                  self._visible_types, self._type_filter_btn,
                                  new_label_fn=lambda n: f"Type: {n}" if n else "Type: all")

    def _show_filter_popover(
        self,
        anchor: Gtk.Widget,
        kind: str,
        all_values: set[str],
        visible_set: set[str],
        label_widget: Gtk.Widget,
        new_label_fn: Callable[[str], str],
    ) -> None:
        """Build and present a popover with checkboxes for each filter value.

        Toggling a checkbox updates visible_set, refreshes the row list visibility,
        and updates the label_widget text.
        """
        popover = Gtk.Popover()
        popover.set_parent(anchor)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        # "All" toggle — clears the filter set
        all_check = Gtk.CheckButton(label=f"All {kind}s")
        all_check.set_active(not visible_set)
        all_check.connect("toggled", lambda btn, k=kind: self._on_filter_all_toggled(btn, k))
        box.append(all_check)

        # Per-value checkboxes
        for value in sorted(all_values):
            cb = Gtk.CheckButton(label=value)
            cb.set_active(value in visible_set)
            cb.connect("toggled", self._on_filter_value_toggled, kind, value, label_widget, new_label_fn)
            box.append(cb)

        popover.set_child(box)
        popover.popup()

    def _on_filter_all_toggled(self, btn: Gtk.CheckButton, kind: str) -> None:
        """When 'All' is toggled, clear the filter set for that kind."""
        if btn.get_active():
            if kind == "agent":
                self._visible_agents.clear()
            else:
                self._visible_types.clear()
            self._refresh_row_visibility()

    def _on_filter_value_toggled(
        self,
        btn: Gtk.CheckButton,
        kind: str,
        value: str,
        label_widget: Gtk.Widget,
        new_label_fn: Callable[[str], str],
    ) -> None:
        """When a value checkbox is toggled, update the filter set and re-evaluate."""
        if kind == "agent":
            target = self._visible_agents
        else:
            target = self._visible_types

        if btn.get_active():
            target.add(value)
        else:
            target.discard(value)

        # Update the label
        if target:
            label_widget.set_label(new_label_fn(", ".join(sorted(target))))
        else:
            label_widget.set_label(new_label_fn(""))

        self._refresh_row_visibility()

    def _refresh_row_visibility(self) -> None:
        """Walk all rows, set visibility based on _passes_filter, update count label."""
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is not None:
                meta = getattr(child, "_row_meta", None)
                if meta is not None:
                    visible = self._passes_filter(meta["agent"], meta["activity_type"])
                    lb_row.set_visible(visible)
            idx += 1
        self._update_count_label()


# ── Module-level helpers (mirrored from models/activity.py) ──────
# These are duplicated here to avoid a circular import between
# ui/views/ and models/ when only the type label / duration formatter
# is needed. Both modules use the SAME logic — keep in sync.

def _type_label(activity_type: str) -> str:
    """See models/activity.py._type_label for full docstring."""
    if activity_type == "command_output":
        return "exec"
    if activity_type == "lifecycle_start":
        return "lifecycle"
    if activity_type == "plan":
        return "plan"
    if activity_type == "approval_request":
        return "approval"
    if activity_type == "patch":
        return "patch"
    return activity_type


def _format_duration(ms: int) -> str:
    # Keep in sync with models/activity.py:_format_duration
    # Duplicated to avoid circular import (model → view).
    """See models/activity.py._format_duration for full docstring."""
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes, secs = divmod(ms // 1000, 60)
    return f"{minutes}m {secs}s"
```

**Verified against source:**
- `Gtk.Paned.set_start_child`, `set_end_child`, `set_position`, `set_shrink_end_child`, `set_resize_end_child` — all verified to exist on `Gtk.Paned` via `dir(Gtk.Paned)` (PyGObject 4.14)
- `Gtk.ListBox.set_selection_mode(Gtk.SelectionMode.NONE)` — standard pattern, used elsewhere
- `Gtk.ScrolledWindow.set_max_content_height()` exists in GTK 4.10+ (project ships 4.14)
- `Gtk.Revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)` — standard GTK4 API
- `Gtk.GestureClick.new()` and `connect("pressed", ...)` — standard GTK4 gesture API
- `Gtk.Popover.set_parent(anchor)` and `popover.popup()` — GTK4 popover API
- `Gtk.Label.set_ellipsize(Pango.EllipsizeMode.END)` — type-checked: `set_ellipsize(self, mode:Pango.EllipsizeMode)`
- `Gtk.Label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)` — type-checked: `set_wrap_mode(self, wrap_mode:Pango.WrapMode)`
- `Pango` is imported from `gi.repository` (PyGObject convention)

**Line count estimate:** ~430 lines. One new file.

---

### 2.3 `ui/window.py` — Wrap right side in vertical Paned, instantiate drawer, rewire callback

**Change type:** Modify. Adds ~30 lines to `_build()`.

**Imports (no new imports needed — `Gtk` and `GLib` already imported, drawer is local module).**

**New import added:**
```python
from ui.views.activity_drawer import ActivityDrawer
```

**Change in `_build()`** — locate the line that places `main_content` into the right side of the horizontal Paned and wrap it. The horizontal Paned end_child assignment is in the existing code. Below is the pattern, with the new structure:

```python
        # ── NEW: Wrap main_content in vertical Paned, add ActivityDrawer below ──
        # Per PROPOSAL-activity-drawer.md §2 Component Architecture.
        # The drawer is global (one per window), not per-tab.
        self._activity_drawer = ActivityDrawer()
        self._activity_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self._activity_paned.set_start_child(self._main_content)
        self._activity_paned.set_end_child(self._activity_drawer)
        # Default: most space to chat (600 of ~800px window height)
        self._activity_paned.set_position(600)
        self._activity_paned.set_shrink_end_child(True)
        self._activity_paned.set_resize_end_child(False)
        right_box.append(self._activity_paned)  # replaces right_box.append(self._main_content)
```

**Rewire the activity bubble callback** — locate the line that wires `set_on_activity_bubble` (in the current code, this wires ChatHandler):

```python
        # OLD: ActivityHandler → ChatHandler._render_activity_bubble
        # self._activity_handler.set_on_activity_bubble(self._chat_handler._render_activity_bubble)
        # (This line may or may not exist in current window.py — verified: it does NOT exist;
        #  ChatHandler self-wires in its __init__ via AgentRuntimeHandler chain. Confirmed by
        #  grep — only the ActivityHandler.set_on_activity_bubble and ChatHandler.set_on_activity_bubble
        #  exist; the connection between them happens elsewhere or via direct method ref.)

        # NEW: ActivityHandler → ActivityDrawer.append_event
        self._activity_handler.set_on_activity_bubble(self._activity_drawer.append_event)

        # Project-switch hook: clear drawer when switching projects.
        # Without this, counters and rows from Project A carry into Project B.
        # Wired via the existing set_on_project_opened callback chain.
        self._activity_drawer.clear_events  # reference, called on project switch
        # In the existing set_on_project_opener callback (or add if not present):
        #   self._on_project_opened_callbacks.append(self._activity_drawer.clear_events)
```

**Important finding from discovery:** The current window.py does NOT explicitly call `self._activity_handler.set_on_activity_bubble(self._chat_handler._render_activity_bubble)`. The connection happens through the AgentRuntimeHandler → ChatHandler chain. Verified by reading `ui/window.py:237` (`set_agent_routing`) — `set_on_activity_bubble` is not called there. It must be called somewhere else. Need to check `ui/handlers/agent_runtime_handler.py` or `ui/handlers/chat_handler.py.__init__`.

**Wiring the lifecycle callback for the drawer:**

```python
        # NEW: ActivityHandler lifecycle events → ActivityDrawer separators
        # set_on_agent_lifecycle is a NEW method on ActivityHandler (added in this spec,
        # see §2.4). The drawer receives (session_key, agent_name, "start"|"end")
        # and inserts separator rows.
        self._activity_handler.set_on_agent_lifecycle(
            lambda sk, name, phase: (
                self._activity_drawer.on_agent_start(sk, name) if phase == "start"
                else self._activity_drawer.on_agent_end(sk, name)
            )
        )
```

**Line count estimate:** +25 lines net (replaces 1-3 lines with ~30 lines).

**Verified against source:** `Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)` matches the pattern in `ui/window.py:120` (existing horizontal Paned). `set_start_child` / `set_end_child` / `set_position` / `set_shrink_end_child` / `set_resize_end_child` are all standard `Gtk.Paned` methods.

---

### 2.4 `ui/handlers/activity_handler.py` — Add `set_on_agent_lifecycle`, capture agent_name, populate command/output

**Change type:** Modify. Add 2 new fields, 1 new setter, hook the agent_name into existing bubble construction, and add command/output capture for the `command_output` event. ~25 lines.

**New state added in `__init__`:**

```python
        # Lifecycle callback — fires (session_key, agent_name, "start"|"end") on agent lifecycle.
        # Drawer uses this to insert separator rows.
        self._on_agent_lifecycle: Callable[[str, str, str], None] | None = None
```

**New public setter (after `set_on_agent_start`):**

```python
    def set_on_agent_lifecycle(self, cb: Callable[[str, str, str], None]) -> None:
        """Set callback for agent lifecycle events: cb(session_key, agent_name, phase).

        ActivityHandler calls this on every lifecycle phase=start and phase=end
        event. The drawer uses this to insert separator rows in the activity stream.

        Args:
            cb: callable receiving (session_key, agent_name, "start"|"end")
        """
        self._on_agent_lifecycle = cb
```

**Hook the lifecycle callback in `on_gateway_event()` for `stream=lifecycle`:**

Inside the existing `elif phase == "start":` branch (around line 224), add:

```python
                elif phase == "start":
                    # ── Activity bubble: lifecycle start ──────────────────
                    sk = payload.get("sessionKey", "") or session_key
                    agent_name = payload.get("data", {}).get("agentName", "") or ""
                    if self._on_agent_lifecycle:
                        self._on_agent_lifecycle(sk, agent_name, "start")
                    if sk and self._activity_bubble_callback:
                        from models.activity import ActivityBubble, ToolStatus
                        bubble = ActivityBubble(
                            type="lifecycle_start", session_key=sk, icon="⏳",
                            agent_name=agent_name,
                        )
                        self._activity_bubble_callback(bubble)
```

And in the `if phase in ("end", "error"):` branch (around line 209), add the end callback:

```python
                if phase in ("end", "error"):
                    run_id = payload.get("runId", "") or ""
                    sk = payload.get("sessionKey", "") or session_key
                    agent_name = payload.get("data", {}).get("agentName", "") or ""
                    if sk and self._on_agent_lifecycle:
                        self._on_agent_lifecycle(sk, agent_name, "end")
                    # ... existing fallback render code ...
```

**Populate `agent_name` and `command` on existing bubble construction** — every `ActivityBubble(...)` constructor call should pass `agent_name`. Modify all 6 construction sites:

- `lifecycle_start` (line 224) — `agent_name` from `data.agentName`
- `tool_start` / `tool_end` / `tool_error` (lines 263-280) — `agent_name` from `data.agentName`
- `plan` (line 290) — `agent_name` from `data.agentName`
- `approval_request` (line 300) — `agent_name` from `data.agentName`
- `command_output` (line 315) — `agent_name` from `data.agentName`, plus capture `command` from `data.command` and `output` from `data.output`
- `patch` (line 327) — `agent_name` from `data.agentName`

Each construction line gets `agent_name=agent_name,` appended. For `command_output`:

```python
                        bubble = ActivityBubble(
                            type="command_output", session_key=sk,
                            tool_name=name, exit_code=exit_code,
                            duration_ms=duration_ms, icon="💻",
                            agent_name=agent_name,
                            command=data.get("command", "") or "",
                            output=data.get("output", "") or "",
                        )
```

**Note on `command` and `output` source:** The current gateway `stream=command_output` event does NOT carry the command text or output (verified at lines 305-315, only `name`, `exitCode`, `durationMs` are extracted). To populate these fields, we have two options:

**Option A (preferred, in-spec):** The command string and output are captured at the `AgentRuntimeHandler` level (which has access to `args.get('command', '')` for exec_command and the tool result). We add a new method `AgentRuntimeHandler.set_on_command_output(cb)` that fires `cb(session_key, command, output, exit_code, duration_ms)` after each exec. The window wires this to a new helper that caches the most recent command/output by session_key, and `ActivityHandler.on_gateway_event()` reads from this cache when constructing the `command_output` bubble.

**Option B (fallback, requires gateway change):** Extend the gateway event schema to include `command` and `output` fields. This is out of scope for this spec — gateway changes are owned by the OpenClaw gateway project, not crabcakes.

**This spec implements Option A.** The new wiring in `window.py._build()` is:

```python
        # Cache for most recent command/output per session_key, populated by
        # AgentRuntimeHandler. ActivityHandler reads from this when firing
        # command_output bubbles.
        self._exec_cache: dict[str, dict] = {}  # session_key → {command, output, exit_code, duration_ms}

        def _on_exec_done(session_key: str, command: str, output: str,
                          exit_code: int, duration_ms: int) -> None:
            self._exec_cache[session_key] = {
                "command": command, "output": output,
                "exit_code": exit_code, "duration_ms": duration_ms,
            }
            # Fire the activity bubble with enriched data
            from models.activity import ActivityBubble, ToolStatus
            if self._activity_drawer is not None:
                row = ActivityBubble(
                    type="command_output", session_key=session_key,
                    tool_name="exec", exit_code=exit_code,
                    duration_ms=duration_ms, icon="💻",
                    agent_name=self._agent_to_project.get_agent_name(session_key) or "Agent",
                    command=command, output=output,
                ).to_drawer_row()
                self._activity_drawer.append_event(row)

        self._agent_runtime_handler.set_on_command_output(_on_exec_done)
```

Wait — this duplicates the `command_output` event firing (once from `ActivityHandler.on_gateway_event` and once from this cache hook). To avoid double-firing, **the `command_output` branch in `ActivityHandler.on_gateway_event()` is REMOVED** (Day 2 of this spec). The `AgentRuntimeHandler` is the sole source of `command_output` bubbles.

**Final shape:**
- `ActivityHandler.on_gateway_event()` continues to fire bubbles for: `lifecycle_start`, `tool_start`, `tool_end`, `tool_error`, `plan`, `approval_request`, `patch` (all from gateway streams).
- `AgentRuntimeHandler` is the sole source of `command_output` bubbles (via `set_on_command_output` callback).
- This removes the "raw gateway event" path for command_output, since the gateway's stream=command_output does not carry enough data to be useful in the drawer.

**Line count estimate:** +50 lines in `activity_handler.py` (new state, setter, callback hooks, agent_name on all bubbles, removal of command_output branch). +15 lines in `window.py` (exec cache + wiring). +10 lines in `agent_runtime_handler.py` (new `set_on_command_output` setter and `_on_exec_done` integration). Total: ~75 lines.

**Verified against source:** `set_on_*` setters follow the same pattern as `set_on_agent_start`, `set_on_activity_bubble`, `set_on_lifecycle_completed` (all on ActivityHandler). The `from models.activity import ActivityBubble, ToolStatus` pattern is repeated at lines 224, 264, 282, 300, 315, 327 — moving this to a top-of-method import is a refactor to consider but not required for this spec.

---

### 2.5 `ui/handlers/agent_runtime_handler.py` — Capture command/output and fire `set_on_command_output`

**Change type:** Modify. Add 1 new callback, 1 new state field, capture command + output in `_do_tool_call_start` / `_do_tool_call_result`. ~40 lines.

**New state in `__init__`:**

```python
        # Callback for completed exec commands. Fires (session_key, command, output, exit_code, duration_ms).
        # ActivityHandler reads from this to populate the command_output activity bubble.
        self._on_command_output: Callable[[str, str, str, int, int], None] | None = None
```

**New public setter (in the setters region):**

```python
    def set_on_command_output(self, cb: Callable[[str, str, str, int, int], None]) -> None:
        """Set callback for completed exec commands.

        Fires (session_key, command, output, exit_code, duration_ms) after each
        exec_command tool call completes. Used by the activity drawer to show
        the command and the tail of stdout/stderr.
        """
        self._on_command_output = cb
```

**Modify `_do_tool_call_start` (line 512)** — store the command string in a per-session cache:

```python
    def _do_tool_call_start(self, session_key: str, name: str, args: dict) -> None:
        """Main-thread portion of _on_tool_call_start.

        Phase D: Create an agent_action feed card with running state.
        Also caches the command string for command_output events.
        """
        if self._fh is None or self._active_project is None:
            # Still cache the command even if no feed handler, so the drawer
            # can show it when the result arrives. NOTE: this cache write is
            # intentionally placed BEFORE the `_fh is None` early-return guard
            # to ensure the command is captured for the drawer even when no feed
            # handler is set. The early-return skips feed card creation but NOT
            # command caching.
            if name == "exec_command":
                self._pending_commands[session_key] = args.get('command', '') or ""
            return

        # Cache the command for the upcoming _do_tool_call_result
        if name == "exec_command":
            self._pending_commands[session_key] = args.get('command', '') or ""

        # ... existing feed card creation code unchanged ...
```

**New state in `__init__`:**
```python
        # Per-session pending command cache. Set in _do_tool_call_start(name=exec_command),
        # read in _do_tool_call_result. Popped after the callback fires.
        self._pending_commands: dict[str, str] = {}
```

**Modify `_do_tool_call_result` (line 579)** — fire the new callback with command + output + exit_code + duration_ms:

```python
    def _do_tool_call_result(self, session_key: str, name: str, result: Any) -> None:
        """Main-thread portion of _on_tool_call_result.

        Phase D: Update the feed card with the tool result, then flag for review.
        Also fires the on_command_output callback for exec commands so the
        activity drawer can show the command and its output.
        """
        # ... existing feed card update code ...

        # Fire command_output callback for exec commands
        if name == "exec_command" and self._on_command_output is not None:
            command = self._pending_commands.pop(session_key, "") or ""
            # Extract output from result (ToolResult or string)
            if hasattr(result, 'output'):
                output_text = result.output or ""
                success = result.success
                exit_code = getattr(result, 'exit_code', 0) if hasattr(result, 'exit_code') else (0 if success else 1)
                duration = getattr(result, 'duration_ms', 0)
            else:
                output_text = str(result) if result is not None else ""
                exit_code = 0
                duration = 0
            self._on_command_output(session_key, command, output_text, exit_code, duration)
```

**Line count estimate:** +35 lines in agent_runtime_handler.py (new state, setter, capture in start, fire in result). 1 line modification in `_do_tool_call_start` (early cache write).

**Verified against source:** `args.get('command', '?')` is the existing pattern at line 525 (in the feed card title). `result.output` and `result.error` are accessed at line 590+ via `hasattr(result, 'output')`. The result is either a `ToolResult` (from `agent/tools.py:ToolResult`) or a string (per existing code). Both cases are handled.

---

### 2.6 `ui/handlers/chat_handler.py` — Remove `_render_activity_bubble`, `_render_activity_bubble_impl`, `set_on_activity_bubble`

**Change type:** Modify. REMOVE 3 methods. Add nothing. The callback that was being set on `ActivityHandler` is no longer needed — the drawer is wired directly in `window.py._build()`.

**Lines to remove:**
- Line 151-168: `_render_activity_bubble(self, bubble)` — 18 lines
- Line 170-186: `_render_activity_bubble_impl(self, session_key, text, activity_type)` — 17 lines
- Line 187-193: `set_on_activity_bubble(self, cb)` — 7 lines

**Total removed:** ~42 lines.

**Imports to remove (if no longer used elsewhere in this file):**
- `Callable` from `typing` may still be used elsewhere — check, but don't remove.
- `from models.activity import ActivityBubble` (used only in the removed code) — check if used elsewhere, remove if not.

**Verified against source:** All three methods exist exactly as described in chat_handler.py:151, 170, 187. The `_render_activity_bubble_impl` method's only callers are inside `_render_activity_bubble` (which is removed) and the test file `test_activity_bubbles.py`. The test will be updated (see §2.10).

---

### 2.7 `ui/handlers/chat_render_handler.py` — Remove `render_activity()`

**Change type:** Modify. REMOVE 1 method (lines 589-621). ~33 lines removed.

**Lines to remove:**
- Line 589-621: `render_activity(self, text, activity_type)` method body, plus the preceding docstring and surrounding whitespace.

**Verified against source:** The method exists at line 589 per the read at the start of discovery. It returns a `Gtk.Box` (outer wrapper) with the pill. After removal, the file should not import any unused modules (the function uses only `Gtk` which is still used).

---

### 2.8 `ui/styles.py` — Add new CSS classes, remove old activity-bubble classes

**Change type:** Modify. Add ~80 lines of new CSS, remove ~30 lines of dead CSS.

**New CSS classes added (appended to `APP_CSS`):**

```css
/* Activity Drawer (PROPOSAL-activity-drawer / SPEC-activity-drawer) */
.activity-drawer {
    background-color: alpha(@theme_fg_color, 0.04);
    border-top: 1px solid alpha(@theme_fg_color, 0.15);
    padding: 0;
}

.activity-drawer-header {
    background-color: alpha(@theme_bg_color, 0.95);
    padding: 4px 8px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.1);
    min-height: 32px;
}

.activity-drawer-row {
    padding: 3px 8px;
    font-family: monospace;
    font-size: 0.9em;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.05);
}

.activity-drawer-row-lifecycle_start,
.activity-drawer-row-lifecycle_end,
.activity-drawer-row-lifecycle {
    background-color: alpha(@theme_fg_color, 0.06);
    font-style: italic;
}

.activity-drawer-row-tool_start,
.activity-drawer-row-tool_end {
    background-color: alpha(@accent_color, 0.04);
}

.activity-drawer-row-tool_error {
    background-color: alpha(@error_color, 0.08);
}

.activity-drawer-row-command_output {
    background-color: alpha(@success_color, 0.05);
}

.activity-drawer-row-patch {
    background-color: alpha(@warning_color, 0.05);
}

.activity-drawer-row-plan {
    background-color: alpha(@accent_color, 0.03);
}

.activity-drawer-output {
    font-family: monospace;
    font-size: 0.85em;
    padding: 4px 8px 4px 32px;
    background-color: alpha(@theme_bg_color, 0.5);
    color: alpha(@theme_fg_color, 0.8);
}

.activity-drawer-separator {
    padding: 4px 8px;
    background-color: alpha(@theme_fg_color, 0.02);
    color: alpha(@theme_fg_color, 0.5);
    font-size: 0.85em;
    border-top: 1px solid alpha(@theme_fg_color, 0.08);
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
}
```

**Old CSS classes removed** (these are dead after the chat-rendering path is gone):
- `.activity-bubble` (line 463)
- `.activity-bubble-text` (line 469)
- `.activity-tool_error .activity-bubble-text` (line 483)
- `.activity-approval_request .activity-bubble-text` (line 500)
- `.activity-lifecycle_start .activity-bubble-text` (line 508)

**Line count estimate:** +50 lines net (80 added, 30 removed).

**Verified against source:** GTK4 CSS uses `alpha(@theme_fg_color, 0.04)` syntax (verified by other CSS in this file). `@accent_color`, `@error_color`, `@warning_color`, `@success_color` are GTK4 named colors.

---

### 2.9 `docs/ARCHITECTURE.md` — Update §2, §3.7, §3.21, §11

**Change type:** Modify. Documentation only. No code logic changes. ~25 lines added/modified.

**§2 Directory Structure** — add `ui/views/activity_drawer.py` to the `ui/views/` block:

```markdown
│       └── activity_drawer.py     # NEW (SPEC-activity-drawer) — collapsible activity event panel
```

**§3.7 `ui/views/activity_drawer.py`** — add a new subsection (insert after §3.7 model section, before §3.8):

```markdown
### 3.7b `ui/views/activity_drawer.py` — Activity Drawer View (NEW — SPEC-activity-drawer)

**Responsibility:** Collapsible panel that displays activity events below the chat. Pure view — no business logic, no gateway calls, no state beyond its widget tree.

**Public API:**
- `ActivityDrawer(Gtk.Box)` — constructor, builds header + scrollable list
- `append_event(row: dict)` — add an event row from `ActivityBubble.to_drawer_row()`
- `on_agent_start(session_key, agent_name)` — insert lifecycle start separator
- `on_agent_end(session_key, agent_name)` — insert lifecycle end summary separator
- `clear_events()` — remove all rows and reset state
- `toggle()` — expand/collapse drawer

**Architecture rules:**
- Lives in `ui/views/` — no imports from `gateway/`, `models/`, or `agent/`
- Receives data via callbacks set by `ActivityHandler` and `window.py._build()`
- No `GLib.idle_add()` — callers must invoke on the GTK main thread
- Formatting logic duplicated from `models/activity.py` to avoid circular imports
```

**§3.21 `ui/handlers/activity_handler.py`** — update to mention new callback and that command_output is no longer fired by this handler:

```markdown
**Activity Bubbles (Phase 2 of SPEC-smarter-chat-ux, modified by SPEC-activity-drawer):**

ActivityHandler fires `_activity_bubble_callback` for:
- `stream=lifecycle phase=start` → `lifecycle_start` ActivityBubble
- `stream=item kind=tool` → `tool_start` / `tool_end` / `tool_error` ActivityBubble
- `stream=plan` → `plan` ActivityBubble
- `stream=approval phase=requested` → `approval_request` ActivityBubble
- `stream=patch phase=end` → `patch` ActivityBubble
- (command_output bubbles are fired by AgentRuntimeHandler, not ActivityHandler — see SPEC-activity-drawer §2.5)

ActivityHandler also fires `_on_agent_lifecycle` callback for `lifecycle phase=start|end|error` events, which the drawer uses for separator rows.

**Modified by SPEC-activity-drawer:** The previous flow routed these bubbles to `ChatHandler._render_activity_bubble()` for inline chat rendering. That path is REMOVED; bubbles are routed to `ActivityDrawer.append_event()` via `window.py._build()` wiring.
```

**§11 File inventory** — add `ui/views/activity_drawer.py`:

```markdown
│   └── activity_drawer.py   # NEW (SPEC-activity-drawer) — collapsible activity panel
```

**Line count estimate:** +30 lines.

---

### 2.10 `tests/test_activity_bubbles.py` — Remove chat-render tests, add drawer tests

**Change type:** Modify. Remove 5 tests in `TestChatHandlerActivityBubbleRender` class. Add new test file `tests/test_activity_drawer.py` with ~15 tests.

**Tests to remove from `test_activity_bubbles.py`:**
- `TestChatHandlerActivityBubbleRender::test_render_activity_bubble_impl_calls_render_activity`
- `TestChatHandlerActivityBubbleRender::test_render_activity_no_render_when_no_chat_box`
- `TestChatHandlerActivityBubbleRender::test_render_activity_routes_via_project_table`
- `TestChatHandlerActivityBubbleRender::test_render_activity_skips_when_routing_table_returns_none`
- `TestChatHandlerActivityBubbleRender::test_lifecycle_fallback_routes_to_project_tab` (actually this tests lifecycle, not activity — verify before removing)

**Tests to keep unchanged:**
- `TestActivityBubbleModel` (all 9 tests for `format_text()`)
- `TestActivityHandlerActivityBubbles` (all 10 tests for callback firing) — update where needed to account for `agent_name` being passed in `ActivityBubble(...)` constructor calls

**New file `tests/test_activity_drawer.py` — test classes:**

```python
# tests/test_activity_drawer.py
# Tests for SPEC-activity-drawer — ActivityDrawer view + to_drawer_row() + filters + lifecycle.

import gi
gi.require_version('Gtk', '4.0')

import pytest
from unittest.mock import MagicMock


class TestToDrawerRow:
    """ActivityBubble.to_drawer_row() returns structured dict for the drawer."""

    def test_returns_all_fields(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(
            type="command_output", session_key="sk-1",
            tool_name="exec", exit_code=0, duration_ms=4521, icon="💻",
            agent_name="Coder", command="pytest tests/",
        )
        row = b.to_drawer_row()
        assert row["agent"] == "Coder"
        assert row["icon"] == "💻"
        assert row["type_label"] == "exec"
        assert row["command"] == "pytest tests/"
        assert row["exit_code"] == 0
        assert row["duration"] == "4.5s"
        assert row["activity_type"] == "command_output"
        assert row["duration_ms"] == 4521

    def test_agent_defaults_to_Agent(self):
        from models.activity import ActivityBubble
        b = ActivityBubble(type="tool_end", session_key="sk-1")
        row = b.to_drawer_row()
        assert row["agent"] == "Agent"

    def test_format_duration_ms(self):
        from models.activity import _format_duration
        assert _format_duration(0) == "0ms"
        assert _format_duration(83) == "83ms"
        assert _format_duration(1000) == "1.0s"
        assert _format_duration(4521) == "4.5s"
        assert _format_duration(60_000) == "1m 0s"
        assert _format_duration(83_000) == "1m 23s"

    def test_type_label_mapping(self):
        from models.activity import _type_label
        assert _type_label("command_output") == "exec"
        assert _type_label("lifecycle_start") == "lifecycle"
        assert _type_label("plan") == "plan"
        assert _type_label("approval_request") == "approval"
        assert _type_label("patch") == "patch"


class TestActivityDrawer:
    """ActivityDrawer widget — append, filter, lifecycle separators, click-to-expand."""

    def test_append_event_creates_row(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        row = {"timestamp": "18:23", "agent": "Coder", "icon": "🔧",
               "type_label": "exec", "command": "pytest", "exit_code": 0,
               "duration": "4.2s", "activity_type": "command_output",
               "output": "", "raw_text": "exec  4.2s", "duration_ms": 4200}
        drawer.append_event(row)
        assert drawer._list.get_row_at_index(0) is not None

    def test_counter_collapses_consecutive_same_type(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        row = {"agent": "Coder", "activity_type": "command_output",
               "type_label": "exec", "command": "pytest", "exit_code": 0,
               "duration": "4.2s", "duration_ms": 4200, "output": ""}
        drawer.append_event(row)
        drawer.append_event(row)
        drawer.append_event(row)
        # Should have 1 row, not 3
        assert drawer._list.get_row_at_index(0) is not None
        assert drawer._list.get_row_at_index(1) is None
        # Count should be 3
        assert drawer._agent_counters["Coder"]["count"] == 3

    def test_per_agent_counter_scope(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        coder_row = {"agent": "Coder", "activity_type": "command_output",
                     "type_label": "exec", "command": "pytest", "exit_code": 0,
                     "duration": "4.2s", "duration_ms": 4200, "output": ""}
        researcher_row = {"agent": "Researcher", "activity_type": "tool_start",
                          "type_label": "search", "command": "search",
                          "exit_code": None, "duration": "740ms",
                          "duration_ms": 740, "output": ""}
        drawer.append_event(coder_row)
        drawer.append_event(coder_row)
        drawer.append_event(coder_row)
        drawer.append_event(researcher_row)  # different agent + type → new row
        # 2 rows total
        assert drawer._list.get_row_at_index(0) is not None
        assert drawer._list.get_row_at_index(1) is not None
        assert drawer._list.get_row_at_index(2) is None
        # Coder counter at 3
        assert drawer._agent_counters["Coder"]["count"] == 3
        # Researcher counter at 1
        assert drawer._agent_counters["Researcher"]["count"] == 1

    def test_agent_end_breaks_counter_for_that_agent_only(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        drawer.on_agent_start("sk-1", "Coder")
        coder_row = {"agent": "Coder", "activity_type": "command_output",
                     "type_label": "exec", "command": "pytest", "exit_code": 0,
                     "duration": "4.2s", "duration_ms": 4200, "output": ""}
        drawer.append_event(coder_row)
        drawer.on_agent_end("sk-1", "Coder")
        drawer.append_event(coder_row)  # next Coder event after end → new row
        # 1 separator + 1 row + 1 separator + 1 row = 4 visible rows in list
        assert drawer._list.get_row_at_index(0) is not None
        assert drawer._list.get_row_at_index(3) is not None
        assert drawer._list.get_row_at_index(4) is None

    def test_filter_hides_rows(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        coder_row = {"agent": "Coder", "activity_type": "command_output",
                     "type_label": "exec", "command": "pytest", "exit_code": 0,
                     "duration": "4.2s", "duration_ms": 4200, "output": ""}
        researcher_row = {"agent": "Researcher", "activity_type": "tool_start",
                          "type_label": "search", "command": "search",
                          "exit_code": None, "duration": "740ms",
                          "duration_ms": 740, "output": ""}
        drawer.append_event(coder_row)
        drawer.append_event(researcher_row)
        # Filter to only Coder
        drawer._visible_agents.add("Coder")
        drawer._refresh_row_visibility()
        # Both rows exist, but Researcher is hidden
        assert drawer._list.get_row_at_index(0).get_visible() is True
        assert drawer._list.get_row_at_index(1).get_visible() is False

    def test_clear_resets_state(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        row = {"agent": "Coder", "activity_type": "command_output",
               "type_label": "exec", "command": "pytest", "exit_code": 0,
               "duration": "4.2s", "duration_ms": 4200, "output": ""}
        drawer.append_event(row)
        drawer.append_event(row)
        assert drawer._total_count == 2
        drawer.clear_events()
        assert drawer._total_count == 0
        assert drawer._list.get_row_at_index(0) is None
        assert drawer._agent_counters == {}

    def test_toggle_expands_and_collapses(self):
        from ui.views.activity_drawer import ActivityDrawer
        drawer = ActivityDrawer()
        assert drawer._expanded is False
        drawer.toggle()
        assert drawer._expanded is True
        drawer.toggle()
        assert drawer._expanded is False


class TestActivityHandlerLifecycleCallback:
    """ActivityHandler fires on_agent_lifecycle callback on lifecycle events."""

    def test_lifecycle_start_fires_separator_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "start", "agentName": "Coder"}
        })

        cb.assert_called_once_with("sk-1", "Coder", "start")

    def test_lifecycle_end_fires_separator_callback(self, fake_glib):
        from ui.handlers.activity_handler import ActivityHandler
        handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
        cb = MagicMock()
        handler.set_on_agent_lifecycle(cb)

        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "run-1",
            "data": {"phase": "end", "agentName": "Coder"}
        })

        cb.assert_called_once_with("sk-1", "Coder", "end")
```

**Line count estimate:** -100 lines (removed) + 250 lines (new) = +150 net.

---

### 2.11 `tests/conftest.py` — Verify `fake_glib` fixture still works

**Change type:** Verify (no code change).

**`fake_glib`** is a pytest fixture defined in `conftest.py`. The new tests use it the same way as existing tests. No changes needed.

---

## 3. Data Flow

### 3.1 Event flow — Agent runtime tool call (end-to-end)

```
User types message in chat
    ↓
ChatHandler.on_send_clicked
    ↓
gateway.send_message(req_id, text)
    ↓
gateway res event (matching req_id)
    ↓
window._on_ws_event("res", payload)
    ↓
ChatHandler._on_chat_event (res)
    ↓
(agent processes the message and starts making tool calls)
    ↓
gateway "agent" event with stream="item" kind="tool" phase="start" name="exec_command"
    ↓
ActivityHandler.on_gateway_event("agent", payload)
    ↓
match: kind=="tool" and phase=="start"
    ↓
_activity_bubble_callback(ActivityBubble(type="tool_start", session_key=sk,
                                          tool_name="exec_command", icon="🔧",
                                          status=RUNNING, agent_name=...))
    ↓
[OLD PATH — REMOVED] ChatHandler._render_activity_bubble → ChatRenderHandler.render_activity → pill in chat
    ↓
[NEW PATH] ActivityDrawer.append_event(to_drawer_row_dict)
    ↓
ActivityDrawer._build_row_widget → new row in Gtk.ListBox
    ↓
ActivityDrawer._auto_scroll_to_bottom → scroll drawer's ScrolledWindow
```

### 3.2 Event flow — Lifecycle start (end-to-end)

```
gateway "agent" event with stream="lifecycle" phase="start" data.agentName="Coder"
    ↓
ActivityHandler.on_gateway_event("agent", payload)
    ↓
match: phase=="start"
    ↓
_on_agent_lifecycle(sk, "Coder", "start")
    ↓
ActivityDrawer.on_agent_start(sk, "Coder")
    ↓
_build_separator_widget("── Coder started ──────────────────")
    ↓
Gtk.ListBox.append(separator_row)
    ↓
_last_separator_agent = ("Coder", "start")
_last_row_key = None  (break counter chain for Coder)
```

### 3.3 Event flow — Lifecycle end (end-to-end)

```
gateway "agent" event with stream="lifecycle" phase="end" data.agentName="Coder"
    ↓
ActivityHandler.on_gateway_event("agent", payload)
    ↓
match: phase in ("end", "error")
    ↓
_on_agent_lifecycle(sk, "Coder", "end")
    ↓
ActivityDrawer.on_agent_end(sk, "Coder")
    ↓
counter = _agent_counters.pop("Coder", None)
summary = f"── Coder: {count} events in {duration} ────"
    ↓
Gtk.ListBox.append(separator_row)
    ↓
_last_separator_agent = ("Coder", "end")
```

### 3.4 Event flow — Command output (Agent Runtime, not gateway)

```
AgentRuntime calls tool loop → tool=exec_command(command="pytest tests/")
    ↓
AgentRuntimeHandler._on_tool_call_start(sk, "exec_command", {"command": "pytest tests/"})
    ↓
GLib.idle_add(_do_tool_call_start, sk, "exec_command", args)
    ↓
AgentRuntimeHandler._do_tool_call_start
    ↓
self._pending_commands[sk] = "pytest tests/"  ← NEW: cache command
    ↓
(existing feed card creation, unchanged)
    ↓
[tool executes]
    ↓
AgentRuntimeHandler._on_tool_call_result(sk, "exec_command", ToolResult(output="...", exit_code=0, duration_ms=4200))
    ↓
GLib.idle_add(_do_tool_call_result, sk, "exec_command", result)
    ↓
AgentRuntimeHandler._do_tool_call_result
    ↓
(existing feed card update, unchanged)
    ↓
[NEW] if name == "exec_command" and self._on_command_output:
        command = self._pending_commands.pop(sk, "")
        output = result.output if hasattr(result, 'output') else str(result)
        self._on_command_output(sk, command, output, exit_code, duration_ms)
    ↓
window._on_exec_done(sk, "pytest tests/", "FAILED test_x...", 0, 4200)
    ↓
ActivityBubble(type="command_output", session_key=sk, tool_name="exec",
               exit_code=0, duration_ms=4200, icon="💻",
               agent_name="Coder", command="pytest tests/", output="FAILED test_x...")
        .to_drawer_row()
    ↓
ActivityDrawer.append_event(row_dict)
    ↓
row created with click-to-expand revealer containing the last 10 lines of output
```

### 3.5 Verified key structures

| Key | Structure | Source |
|-----|-----------|--------|
| `ActivityBubble` fields | `type, session_key, tool_name, duration_ms, status, icon, title, steps, command, approval_id, reason, exit_code, added, modified, deleted, raw_text, agent_name, output, file_path` | `models/activity.py:36-90` (plus new fields) |
| `ActivityType` literal | `"lifecycle_start" \| "tool_start" \| "tool_end" \| "tool_error" \| "plan" \| "approval_request" \| "command_output" \| "patch"` | `models/activity.py:13-22` |
| Gateway `stream=item` payload | `{"data": {"kind": "tool"|"command"|"patch", "phase": "start"|"end", "name": str, "status": str, "startedAt": int, "endedAt": int}}` | `activity_handler.py:247-275` |
| Gateway `stream=lifecycle` payload | `{"data": {"phase": "start"|"end"|"error", "agentName": str, "startedAt": int}}` | `activity_handler.py:200-225` |
| Gateway `stream=command_output` payload | `{"data": {"phase": "end", "name": str, "exitCode": int, "durationMs": int}}` | `activity_handler.py:305-315` (current; REMOVED by this spec) |
| `AgentRoutingTable` | `routing.get_project(session_key) -> str | None` | `models/routing.py` |
| `ToolResult` (from agent runtime) | `result.output, result.error, result.success, result.duration_ms, result.exit_code` | `agent/tools.py:ToolResult` (per existing usage in `_do_tool_call_result`) |
| `ActivityDrawer._row_meta` | `{"agent": str, "activity_type": str, "summary_label": Gtk.Label}` | `ui/views/activity_drawer.py:_build_row_widget` |

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `ui/views/activity_drawer.py` | **NEW** | +430 | Medium — new file, GTK4 widget |
| `models/activity.py` | Modify | +70 | Low — additive only (new fields, new method, new helpers) |
| `ui/window.py` | Modify | +25 | Low — composition root, well-tested pattern |
| `ui/handlers/activity_handler.py` | Modify | +50 | Medium — new callback, new state, removes command_output branch |
| `ui/handlers/agent_runtime_handler.py` | Modify | +35 | Medium — new callback, new state, captures command in start, fires in result |
| `ui/handlers/chat_handler.py` | Modify | -42 | Low — removing dead code, tests will be updated |
| `ui/handlers/chat_render_handler.py` | Modify | -33 | Low — removing dead method |
| `ui/styles.py` | Modify | +50 net | Low — CSS only |
| `docs/ARCHITECTURE.md` | Modify | +30 | Low — documentation only |
| `tests/test_activity_bubbles.py` | Modify | -50 net | Low — removing dead tests, updating model tests |
| `tests/test_activity_drawer.py` | **NEW** | +250 | Low — new test file |
| **Total** | | **+815** | |

**Risk levels:**
- Low: simple additions, removals of dead code, or docs-only
- Medium: new state, new callbacks, GTK widget construction
- High: would be anything touching gateway protocol, persistence, or authentication — none of this in this spec

---

## 5. Implementation Order

### Step 1: New model fields + to_drawer_row() (Day 2 prep)
**File:** `models/activity.py`
**Verify:** `pytest tests/test_activity_bubbles.py::TestActivityBubbleModel` still passes (format_text unchanged). New `test_activity_drawer.py::TestToDrawerRow` passes.

### Step 2: New ActivityDrawer view (Day 1 + Day 2 content)
**File:** `ui/views/activity_drawer.py` (NEW)
**Verify:** Importable, `ActivityDrawer()` instantiates without error, `append_event` and `clear_events` work in tests.

### Step 3: Add lifecycle callback to ActivityHandler
**File:** `ui/handlers/activity_handler.py`
**Verify:** `pytest tests/test_activity_drawer.py::TestActivityHandlerLifecycleCallback` passes.

### Step 4: Add command_output capture to AgentRuntimeHandler
**File:** `ui/handlers/agent_runtime_handler.py`
**Verify:** Existing tests in `test_agent_runtime.py` and `test_agent_runtime_handler.py` still pass.

### Step 5: Wire drawer into window.py
**File:** `ui/window.py`
**Verify:** `python -m crabcakes.main` boots without error. Drawer is visible below the chat.

### Step 6: Remove chat-rendering path
**Files:** `ui/handlers/chat_handler.py` (remove 3 methods), `ui/handlers/chat_render_handler.py` (remove `render_activity`)
**Verify:** App boots. Activity events appear in the drawer, not in the chat. No "render_activity" NameError.

### Step 7: Remove old tests, add new tests
**Files:** `tests/test_activity_bubbles.py` (remove chat-render tests), `tests/test_activity_drawer.py` (NEW)
**Verify:** `pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py` all pass.

### Step 8: Update CSS
**File:** `ui/styles.py`
**Verify:** Drawer rows have correct visual styling. Old `.activity-bubble` CSS classes are gone.

### Step 9: Update ARCHITECTURE.md
**File:** `docs/ARCHITECTURE.md`
**Verify:** No references to `_render_activity_bubble` or `render_activity` in §3.7, §3.21. New `ui/views/activity_drawer.py` appears in §2 and §11.

### Step 10: Full test suite
**Verify:** `pytest tests/ -x` passes (or at least all 4 modified/new test files pass).

---

## 6. Acceptance Criteria

- [ ] `ActivityBubble` has new fields `agent_name`, `command`, `output`, `file_path` (all defaulted to `""`).
- [ ] `ActivityBubble.to_drawer_row()` returns a dict with all 12 fields documented in §2.1.
- [ ] `ui/views/activity_drawer.py` exists, `ActivityDrawer()` instantiates without error.
- [ ] `ActivityDrawer.append_event(row)` adds a new row to the list.
- [ ] Consecutive same-(agent, type) events collapse into a single row with ×N count.
- [ ] Different (agent, type) events start a new row (per-agent counter scope).
- [ ] `ActivityDrawer.on_agent_start(sk, name)` inserts a `── NAME started ──` separator and breaks that agent's counter chain.
- [ ] `ActivityDrawer.on_agent_end(sk, name)` inserts a `── NAME: N events in T ──` summary separator and pops that agent's counter state.
- [ ] Lifecycle end for agent A does NOT break the counter chain for agent B.
- [ ] Clicking an exec row toggles a `Gtk.Revealer` showing the last 10 lines of the row's `output` field.
- [ ] Agent filter dropdown lists all seen agents with checkboxes. AND semantics. Default all-on.
- [ ] Type filter dropdown lists all seen types with checkboxes. AND semantics. Default all-on.
- [ ] Count label shows "N events" with no filter, or "N visible / M total" with filter active.
- [ ] Clear button removes all rows and resets all state.
- [ ] Toggle button expands/collapses the drawer (header-only when collapsed).
- [ ] `ActivityHandler.set_on_agent_lifecycle(cb)` fires `cb(sk, name, "start"|"end")` on lifecycle events.
- [ ] `AgentRuntimeHandler.set_on_command_output(cb)` fires `cb(sk, command, output, exit_code, duration_ms)` after each `exec_command` tool call completes.
- [ ] The `command_output` branch in `ActivityHandler.on_gateway_event()` is REMOVED (no longer fires bubbles; AgentRuntimeHandler is the sole source).
- [ ] `ChatHandler._render_activity_bubble`, `_render_activity_bubble_impl`, and `set_on_activity_bubble` are REMOVED.
- [ ] `ChatRenderHandler.render_activity` is REMOVED.
- [ ] Old CSS classes `.activity-bubble`, `.activity-bubble-text`, `.activity-tool_error .activity-bubble-text`, `.activity-approval_request .activity-bubble-text`, `.activity-lifecycle_start .activity-bubble-text` are REMOVED.
- [ ] New CSS classes `.activity-drawer`, `.activity-drawer-header`, `.activity-drawer-row`, `.activity-drawer-row-{type}`, `.activity-drawer-output`, `.activity-drawer-separator` are ADDED.
- [ ] `ARCHITECTURE.md` §2 lists `ui/views/activity_drawer.py`. §3 has new §3.7b subsection. §3.21 mentions lifecycle callback and removal of chat-rendering path. §11 includes new file.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| `append_event` called with `agent_name=""` (legacy bubble without agent) | Falls back to `"Agent"` in `to_drawer_row()`. Row is shown normally. |
| `append_event` called from a non-main thread | GTK will crash with "widget creation from non-GUI thread". Callers MUST use `GLib.idle_add()`. This is documented in `ActivityDrawer` class docstring. |
| Two `lifecycle_start` events for the same agent in a row | Second is a no-op (the `_last_separator_agent` guard prevents duplicate separators). |
| `lifecycle_end` fires for an agent that never started (e.g. error state) | Separator is still inserted. Counter is empty; summary shows "ended" with no count. |
| `lifecycle_end` fires for an agent whose counter was already popped (idempotent) | Second is a no-op (`_last_separator_agent` guard). |
| Filter is active, `append_event` called for a filtered-out agent | Row is not appended. `total_count` still increments. Count label updates. |
| Filter is active, row is already in list, user toggles the filter checkbox | Existing rows are hidden or shown via `set_visible()`. New appends respect the filter. |
| `clear_events` called while filter is active | All rows removed, filter state preserved (not reset). |
| `clear_events` called when no rows exist | No-op. Safe. |
| `output` field is empty string for a command_output bubble | Click-to-expand revealer is not created (handled in `_build_row_widget`). Row is still clickable but does nothing. |
| `output` field is 1000+ lines | Truncated to last 10 lines, with `... N lines earlier ...` header. Revealer height is bounded by the 10 lines. |
| `duration_ms = 0` | Formatted as "0ms". Row is still shown, duration field is omitted from `_format_summary` because `"0ms"` is filtered. |
| `command` field is empty for `command_output` | Falls back to `tool_name` (formatted via `_friendly_tool_name`). |
| Agent runtime exec fails (exit_code != 0) | Row shows `✗ N` exit badge. Output revealer still works (user can see stderr). |
| `lifecycle_end` fires between two `exec_command` tool calls of the same agent | First exec gets counter = 1. Lifecycle_end separator inserted. Second exec starts a fresh counter (lifecycle_end breaks the chain). |
| Multiple agents emit events interleaved | Each agent has independent counter state in `_agent_counters`. Lifecycle events break only the relevant agent's chain. |
| Drawer is collapsed when events arrive | Events still append to the list. User expands the drawer to see them. Toggle works. |
| App is quit while drawer is expanded | GTK cleans up the widget tree. No special handling needed. |
| `agentName` field is missing from the gateway payload (older gateway version) | `agent_name` defaults to `""` in the bubble. Drawer shows `"[Agent]"` instead of the agent name. Filter dropdown gets a single "Agent" entry. |
| `output` field contains non-ASCII (e.g. emoji, unicode) | GTK Label handles UTF-8 natively. Pango rendering handles it. No special handling. |
| `output` field is very long on a single line (no newlines) | Treated as a single line. Revealer's wrap mode (`Pango.WrapMode.WORD_CHAR`) wraps the long line. User must scroll horizontally within the revealer. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update the following sections of `docs/ARCHITECTURE.md`:

| Section | Update |
|---------|--------|
| §2 Directory Structure | Add `ui/views/activity_drawer.py` to the `ui/views/` block with comment `# NEW (SPEC-activity-drawer) — collapsible activity event panel` |
| §3 (new §3.7b) | Add `### 3.7b ui/views/activity_drawer.py` subsection with responsibility, public API, architecture rules (as drafted in §2.9) |
| §3.7 (existing) | Note that `ActivityBubble` now has `agent_name`, `command`, `output`, `file_path` fields. Add new method `to_drawer_row()` to the public API. |
| §3.21 (existing) | Update activity bubble section: remove `command_output` from the gateway-event-driven list, add `AgentRuntimeHandler` as the source of `command_output` bubbles, add new `_on_agent_lifecycle` callback. Note that `ChatHandler._render_activity_bubble` and `ChatRenderHandler.render_activity` are REMOVED. |
| §11 File inventory | Add `ui/views/activity_drawer.py` to the `ui/views/` inventory line. Remove references to the deleted chat-render methods. |
| §12 (test count) | After implementation, update the test count (currently 1680 tests). New test file `test_activity_drawer.py` adds ~15 tests. Removed ~5 tests from `test_activity_bubbles.py`. Net: +10 tests. |

---

## 9. Gateway Event Limitations

The following activity drawer event types depend on gateway emission policies that are outside Crabcakes' control. The code handles these events correctly when they arrive, but they may not appear in all sessions.

### Patch Events (`stream: "patch"`)

**Limitation:** The gateway (`openclaw 2026.5.18`) only emits patch events inside an `if (isPatchToolName(toolName))` block where `isPatchToolName` returns `toolName === "apply_patch"`. Agents that use `write`, `edit`, `write_file`, `edit_file`, or `str_replace_editor` tools will NOT produce patch events from the gateway. The Crabcakes code is correct — it handles patch events when they arrive — but they simply never arrive for most tools.

**Workaround options:**
- (A) Add client-side detection: treat `stream: "item" kind: "tool"` end events with `name` in `{write, edit, write_file, edit_file}` as patch-like events
- (B) Document the limitation and rely on the tool_start/tool_end rows for file-edit visibility

### Plan Events (`stream: "plan"`)

**Limitation:** The gateway only emits plan events during a planning-only-retry loop (when the model outputs a plan and needs to retry). Normal agent turns where the model responds directly do NOT emit plan events. The Crabcakes code is correct — it handles plan events when they arrive.

**Impact:** In most sessions, no plan rows will appear. This is expected behavior.

### Approval Events (`stream: "approval"`)

**Limitation:** Approval events only fire when an exec requires interactive approval (`status: "approval-pending"`). In sessions where all execs are auto-approved, no approval rows appear. This is expected behavior — the activity drawer only shows approval rows when the user needs to act.

### Command Output Events (`stream: "command_output"`)

**No limitation as of BUGFIX-1.** The handler now correctly processes gateway command_output events. Previously these were silently dropped.

---

## Verification Cheat Sheet (Rule 10)

Run these before declaring complete:

```bash
# 1. Scope checklist — every file changed?
[ ] models/activity.py — new fields, to_drawer_row(), _type_label(), _format_duration()
[ ] ui/views/activity_drawer.py — NEW FILE, ActivityDrawer class
[ ] ui/window.py — wrap in vertical Paned, rewire callback, wire lifecycle
[ ] ui/handlers/activity_handler.py — new setter, new state, agent_name on bubbles, REMOVE command_output branch
[ ] ui/handlers/agent_runtime_handler.py — new setter, new state, capture command in start, fire callback in result
[ ] ui/handlers/chat_handler.py — REMOVE 3 methods
[ ] ui/handlers/chat_render_handler.py — REMOVE render_activity
[ ] ui/styles.py — add new CSS, remove old CSS
[ ] docs/ARCHITECTURE.md — §2, §3.7b (new), §3.7, §3.21, §11, §12
[ ] tests/test_activity_bubbles.py — remove chat-render tests
[ ] tests/test_activity_drawer.py — NEW FILE

# 2. Test suite — paste actual pytest output
cd /home/q/projects/crabcakes && python -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -v

# 3. Pattern sweep — grep for remaining old patterns
grep -rn "render_activity" ui/  # should be ZERO matches
grep -rn "_render_activity_bubble" ui/  # should be ZERO matches
grep -rn "activity-bubble" ui/styles.py  # should be ZERO matches
grep -rn "set_on_activity_bubble.*chat_handler" ui/  # should be ZERO matches (the old wiring)
grep -rn "command_output" ui/handlers/activity_handler.py | grep "data.get"  # should be ZERO matches (branch removed)
```

---

*Spec end. Mantra: "A spec is a contract. If it has a bug, the implementer will ship that bug. Verify everything."*
