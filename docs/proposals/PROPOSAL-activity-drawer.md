# PROPOSAL: Activity Drawer — Replace Chat-Inline Activity Bubbles

**Date:** 2026-06-01
**Author:** Qaster
**Status:** Proposal — pending Captain approval
**Priority:** High
**Effort:** 4-5 days (3 days for Qaster's core plan + 1 day for content enrichment + 0.5-1 day for per-agent + per-type filter)

---

## 1. Why

### The Problem

Activity bubbles — centered pill-shaped indicators showing agent tool calls, plan steps, exec results, and lifecycle events — are **architecturally sound but UX-hostile**. Three independent issues:

1. **Chat pollution.** Every activity event appends a centered pill directly into the chat container (`chat_render_handler.py:589-621`). A typical 10-minute Coder session produces 30+ pills consuming 1,400+ vertical pixels. Actual conversation gets pushed off-screen.

2. **Scroll hijacking.** Activity bubble renders trigger `scroll_chat_to_bottom()` via the chat render pipeline. The chat "runs away" from users reading older content. There are 14 `scroll_chat_to_bottom()` call sites in `chat_handler.py` alone.

3. **Redundancy with FeedBar.** The FeedBar (`ui/views/feedbar.py`) already shows current agent state (`⚙ exec`). Activity pills repeat this information in a more invasive location.

### Why It Matters

The data in activity bubbles is genuinely useful — knowing Coder ran `pytest` in 1,247ms is real signal. But the delivery mechanism treats every event as equally important. Users are asking to suppress the data because the data is loud. **The right fix is to keep the data and change the delivery surface.**

### Why Not QTR's Proposal (System Chat Bubble Container)

QTR's proposal (`PROPOSAL-activity-bubble-ux.md`) addresses the same problem with a 5-fix, 6-7 day plan centered on a custom nested ScrolledWindow container inside the chat. My concerns:

- **GTK container nesting risk.** A bounded-height `Gtk.ScrolledWindow` inside a chat container with its own scroll is the exact pattern that causes resize loops and scroll jitter in GTK4.
- **5 interdependent fixes.** Fix 1.1 (counter-collapse) depends on 1.4 (container) which depends on 1.5 (content enrichment). If 1.4 hits GTK snags, the chain stalls.
- **Complexity budget.** The counter-collapse state machine (per-session, per-turn, per-type, with mutate-in-place widget updates) is solving a problem that may not exist once the data leaves the chat entirely.

This proposal achieves the same outcome — data preserved, chat clean — in 3 days with zero GTK container nesting.

---

## 2. What

Replace chat-inline activity pills with an **Activity Drawer** — a collapsible panel below the chat that holds all activity events in its own scrollable list. The drawer never touches the chat viewport.

### Visual Model

```
┌──────────────────────────────────────┐
│ [You]     Fix the auth flow          │  ← Chat (Gtk.Notebook tab page)
│ [Coder]   Working on it...           │
│ [Coder]   Done, pushed the fix.      │
│                                      │
│ [You]     Thanks!                    │
├──────────────────────────────────────┤  ← Gtk.Paned divider (drag to resize)
│ ▼ Activity                    [×]    │  ← Drawer header (collapsible)
│ exec ×5  pytest tests/auth.py  4.2s  │  ← Last 3 rows visible by default
│ read    auth/login.py          83ms  │
│ exec    ruff check             1.1s  │
└──────────────────────────────────────┘
```

### Component Architecture

```
MainWindow (existing)
├── _toolbar: Toolbar (existing)
├── _paned: Gtk.Paned (horizontal, existing) ← left panel | right side
│   ├── start_child: LeftPanel (existing)
│   └── end_child: Gtk.Box (vertical, modified)
│       ├── _activity_paned: Gtk.Paned (vertical, NEW)
│       │   ├── start_child: MainContent (existing notebook + input)
│       │   └── end_child: ActivityDrawer (NEW, global)
```

The `Gtk.Paned` (vertical) wraps the existing MainContent widget in the top pane and adds the ActivityDrawer in the bottom pane. Since the drawer is **global** (not per-tab), it lives in MainWindow's layout, not inside MainContent's notebook pages. The divider is draggable.

### Drawer Layout

```
ActivityDrawer (Gtk.Box, vertical)
├── _header: Gtk.Box (horizontal)
│   ├── _toggle_btn: Gtk.Button "▼ Activity" / "▶ Activity"
│   ├── _count_label: Gtk.Label "12 events"
│   └── _clear_btn: Gtk.Button "Clear"
└── _scrolled: Gtk.ScrolledWindow
    └── _list: Gtk.ListBox
        ├── row: icon + "exec ×5  pytest tests/auth.py  4.2s"
        ├── row: icon + "read   auth/login.py          83ms"
        └── row: icon + "exec   ruff check             1.1s"
```

**Header behavior:**
- `▼ Activity` — drawer expanded. Click collapses to header-only.
- `▶ Activity` — drawer collapsed. Only header visible (~32px).
- `N events` — total event count. Updates on each append.
- `Clear` — empties the list and resets the counter.

**Row format:**
```
{icon}  {type_label}  ×{count}  {command_or_detail}  {duration}
```

Where:
- `{icon}` — Unicode emoji from the event type (🔧 exec, 📖 read, 📋 plan, etc.)
- `{count}` — consecutive same-type count (incremented when last row is same type)
- `{command_or_detail}` — tool name or plan title
- `{duration}` — formatted duration (83ms, 4.2s)

**Drawer Scope: Global (Confirmed) — Added by QTR (Kage-7), 2026-06-01**

*Per Captain's instruction (msg #5207): the drawer is **global**, shared across all tabs and agents.*

This is a deliberate Captain call against the alternative of "per-tab drawer." The trade-offs:

- **Pro:** Cross-agent awareness. In project mode (Coder + Researcher + Reviewer), the user sees one consolidated activity stream.
- **Pro:** One event counter. No per-tab "is anything happening over there?" questions.
- **Con:** Visual noise. Researcher's web searches appear while Coder is running.
- **Con:** Per-agent filtering becomes necessary (see Per-Agent + Per-Type Filter below).

Implication for the implementation: every activity bubble callback must include the `agent_name` field (set via content enrichment) so the drawer can filter by agent.

---

## 3. Implementation Plan

### Day 1: Structural Change — Drawer Shell + Remove Inline Bubbles

**Goal:** Remove all activity pills from the chat. Replace with an empty drawer. Chat immediately becomes clean.

**Files changed:**

| File | Change |
|------|--------|
| `ui/views/activity_drawer.py` | **NEW** — `ActivityDrawer(Gtk.Box)` class |
| `ui/views/main_content.py` | No structural change. Drawer is outside MainContent. |
| `ui/window.py` | Wrap MainContent in `Gtk.Paned` (vertical). Add drawer as bottom pane. Rewire activity callback from ChatHandler to drawer. |
| `ui/handlers/chat_handler.py` | Remove `_render_activity_bubble()` and `_render_activity_bubble_impl()`. Remove `set_on_activity_bubble()` setter. |
| `ui/handlers/chat_render_handler.py` | Remove `render_activity()` method. |
| `ui/handlers/activity_handler.py` | Change `set_on_activity_bubble()` callback target from ChatHandler to ActivityDrawer. |
| `ui/styles.py` | Add `.activity-drawer`, `.activity-drawer-header`, `.activity-drawer-row` CSS classes. |
| `docs/ARCHITECTURE.md` | Add `ui/views/activity_drawer.py` to §2, §3, §12. Update `window.py` description (new Paned layout). Update `chat_handler.py` description (no more activity bubble rendering). |

**`ui/views/activity_drawer.py` — new file:**

```python
class ActivityDrawer(Gtk.Box):
    """Collapsible activity event panel below the chat.
    
    Pure view — no business logic. All data comes from
    ActivityHandler via the activity_bubble callback.
    """
    
    def __init__(self):
        # Vertical box: header + scrollable list
        self._header = Gtk.Box(horizontal)
        self._toggle_btn = Gtk.Button(label="▼ Activity")
        self._count_label = Gtk.Label(label="0 events")
        self._clear_btn = Gtk.Button(label="Clear")
        
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scrolled.set_max_content_height(200)
        self._scrolled.set_propagate_natural_height(True)
        
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._scrolled.set_child(self._list)
    
    def append_event(self, icon: str, type_label: str, detail: str, duration: str):
        """Add an activity event row. Collapses consecutive same-type events."""
        # If last row has same type_label, increment its count instead of adding new row
        ...
    
    def clear_events(self):
        """Remove all rows and reset counter."""
        ...
    
    def toggle(self):
        """Expand or collapse the drawer."""
        ...
    
    def get_event_count(self) -> int:
        """Return total event count (for header label)."""
        ...
```

**`ui/window.py` changes:**

The current layout in `MainWindow._build()` places `MainContent` directly into the right side of the horizontal Paned. The change wraps it:

```python
# Before (simplified):
right_box.append(main_content)  # MainContent fills right side

# After:
self._activity_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
self._activity_paned.set_start_child(main_content)
self._activity_paned.set_end_child(self._activity_drawer)
self._activity_paned.set_position(600)  # default: most space to chat
self._activity_paned.set_shrink_end_child(True)
right_box.append(self._activity_paned)
```

The `Gtk.Paned` divider sits between the chat and the drawer. User can drag to resize. The drawer collapses to header-only when toggled.

**Activity bubble routing change:**

Current flow:
```
ActivityHandler → callback → ChatHandler._render_activity_bubble() → ChatRenderHandler.render_activity() → pill in chat
```

New flow:
```
ActivityHandler → callback → ActivityDrawer.append_event() → row in drawer
```

The callback set via `set_on_activity_bubble()` in `ActivityHandler` is rewired in `window.py._build()` from `chat_handler._render_activity_bubble` to `activity_drawer.append_event`. ChatHandler no longer knows about activity bubbles.

**Removals from `ui/handlers/chat_handler.py`:**
- `_render_activity_bubble(self, bubble)` method
- `_render_activity_bubble_impl(self, session_key, text, activity_type)` method
- `set_on_activity_bubble(self, cb)` setter (ActivityHandler wires directly to drawer)
- The `_activity_bubble_callback` field

**Removals from `ui/handlers/chat_render_handler.py`:**
- `render_activity(self, text, activity_type)` method (lines 589-621)

**Verification:** Run app. Verify:
1. Chat is clean — no pills appear in conversation
2. Activity events appear in the drawer below chat
3. Drawer collapses/expands with toggle button
4. Dragging the Paned divider resizes chat and drawer
5. Chat scroll is never triggered by activity events

### Day 2: Row Content — Counter-Collapse + Rich Display

**Goal:** Activity rows show useful information with consecutive same-type collapsing.

**Files changed:**

| File | Change |
|------|--------|
| `ui/views/activity_drawer.py` | Add counter-collapse logic, formatted rows, auto-scroll |
| `models/activity.py` | Add `ActivityBubble.to_drawer_row()` method returning structured dict |
| `ui/styles.py` | Add row-type CSS variants (`.activity-drawer-row-exec`, `.activity-drawer-row-read`, etc.) |

**Counter-collapse (simple version):**

No state machine. On each `append_event()`:
1. Check if `_list` has a last row
2. If last row's `activity_type` matches the new event's type → increment count label, update detail text to latest, sum durations
3. If different → append new row

This is a simple visual compression — 5 consecutive EXEC events become one row showing `exec ×5  ruff check  4.2s`. No lifecycle tracking, no per-session state, no mutate-in-place. Just "does the last row match?"

**`models/activity.py` — new method:**

```python
@dataclass ActivityBubble:
    # ... existing fields ...
    
    def to_drawer_row(self) -> dict:
        """Convert to structured dict for ActivityDrawer row rendering."""
        return {
            "icon": self._icon_for_type(),
            "type_label": self.activity_type,
            "detail": self._format_detail(),
            "duration": self._format_duration(),
            "activity_type": self.activity_type,
        }
```

This keeps the formatting logic in the model (pure Python, no GTK) and the view just renders what it receives.

**Auto-scroll:** When a new row is appended, scroll the drawer to the bottom (its own internal scroll, NOT the chat scroll). This is `self._scrolled.get_vadjustment().set_value(upper - page_size)`.

#### Content Enrichment (Command + Agent) — Added by QTR (Kage-7), 2026-06-01

*Per Captain's instruction (msg #5207): adopt Fix 1.5 from the prior proposal into this proposal, since the data is needed regardless of where the bubbles live.*

**Problem:** The OpenClaw gateway's `command_output` event payload contains only `name: "exec"`, `exitCode`, and `durationMs` — NOT the actual command string or the agent name. Today, every exec row in the drawer would show `exec  1,247ms` with no context. Same problem as before; same fix path.

**Proposed solution:** Client-side correlation. The active tool (command string + agent name) is captured at `agent_runtime_handler.py:_do_tool_call_start` time, cached by `session_key`, and looked up at `ActivityHandler` time when the `command_output` event arrives.

**Files changed (in addition to Day 2's list):**

| File | Change |
|------|--------|
| `ui/handlers/agent_runtime_handler.py` | Add `self._active_tools: dict[str, dict] = {}` cache. Write at top of `_do_tool_call_start`. Clear at top of `_do_tool_call_result`. Add public `get_active_tool(session_key) -> dict \| None` method. |
| `ui/handlers/activity_handler.py` | Add `set_active_tool_lookup(callable)` public method. In each `command_output` / `tool_*` emission, look up the active tool and populate `bubble.command` and `bubble.agent_name` before firing the callback. |
| `models/activity.py` | Extend `command` field use to `command_output` type (currently only used for `approval_request`). Add `agent_name: str = ""` field. Extend `format_text()` `command_output` branch to include `agent_name  command  duration`. Extend `to_drawer_row()` to include `agent` and `command` keys. |
| `ui/window.py` | After `set_agent_routing`, call `self._activity_handler.set_active_tool_lookup(self._agent_runtime_handler.get_active_tool)`. |

**Implementation sketch — `agent_runtime_handler.py`:**

```python
# In _do_tool_call_start, after the existing early-return guard:
agent_def = self._agents.get(session_key)
agent_name_for_cache = agent_def.display_name if agent_def else "Agent"
self._active_tools[session_key] = {
    "agent_name": agent_name_for_cache,
    "tool_name": name,
    "command": args.get("command", "") if name == "exec_command" else "",
    "started_at": time.monotonic(),
}

# In _do_tool_call_result, at the top of the method:
self._active_tools.pop(session_key, None)

# New public method:
def get_active_tool(self, session_key: str) -> dict | None:
    return self._active_tools.get(session_key)
```

**Implementation sketch — `activity_handler.py`:**

```python
# In each command_output / tool_start / tool_end / tool_error emission,
# BEFORE the callback fires:
if self._active_tool_lookup is not None:
    cached = self._active_tool_lookup(bubble.session_key)
    if cached:
        if bubble.type == "command_output" and not bubble.command:
            bubble.command = cached.get("command", "")
        if not bubble.agent_name:
            bubble.agent_name = cached.get("agent_name", "")
```

**Implementation sketch — `models/activity.py` extended `format_text()`:**

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

**Drawer row format after enrichment:**

```
[Coder]    exec ×5   pytest tests/test_auth.py   4,247ms
[Researcher]  search ×2   openclaw gateway schema   1,832ms
[Coder]    read    ui/views/main.py    83ms
```

The agent prefix `[Coder]` is the agent-name label that the per-agent filter (below) toggles on/off.

**Pre-flight debug log (10-minute investigation):** Before implementing the correlation cache, add a one-time `print(payload)` at `ui/handlers/activity_handler.py:308` and trigger one command. If the gateway IS sending the command under a field we don't extract (e.g., `data["command"]` or `data["args"]["command"]`), the whole fix becomes 10 minutes of field extraction. If it's not, proceed with the correlation cache.

**Cost:** 10 minutes if gateway sends it; 4-6 hours if not. The first 10 minutes of work determines the cost.

### Day 3: Polish — Header State, Clear, Lifecycle Boundaries

**Goal:** Drawer responds to agent lifecycle events and provides clear/reset.

**Files changed:**

| File | Change |
|------|--------|
| `ui/views/activity_drawer.py` | Add `on_agent_start()` and `on_agent_end()` methods |
| `ui/handlers/activity_handler.py` | Wire lifecycle events to drawer for section markers |
| `ui/window.py` | Wire lifecycle callbacks to drawer |
| `ui/styles.py` | Add `.activity-drawer-separator` CSS for lifecycle dividers |

**Lifecycle separators (per-agent, drawer is global):**

When a new agent turn starts (`lifecycle phase=start`), insert a subtle separator row in the drawer labeled with the agent name:

```
── Coder started ──────────────────
── Researcher started ─────────────
── Coder: 12 events in 2m 14s ──────
```

Because the drawer is **global** (Captain's decision, see "Drawer Scope: Global (Confirmed)" below), the per-agent event count must be tracked **per-agent**, not globally. The summary row at lifecycle end must say `Coder: 12 events in 2m 14s`, not `12 events in 2m 14s`, or the label is misleading in a multi-agent setup.

**Implementation:** The drawer maintains a `dict[str, int]` mapping `agent_name → event_count` and a `dict[str, float]` mapping `agent_name → first_event_time`. On lifecycle end, look up the agent's count and elapsed time, format the summary, reset the per-agent counters.

When a new turn starts for an agent, insert a start-separator labeled with the agent name. On end, insert a summary-separator labeled with the agent name and per-agent stats.

**Clear button:** Resets the drawer to empty. Useful for long sessions.

**No auto-collapse.** Per Captain decision (msg #8317): drawer stays expanded until manually collapsed.

#### Per-Agent + Per-Type Filter — Added by QTR (Kage-7), 2026-06-01 (revised msg #5219)

*Per Captain's instruction (msg #5207, revised msg #5219): "Change the color code filter to an agent filter we don't wanna do color coating. We wanna do filtering per agent, so remove all the color, coating stuff and change it to be able to filter per agent whatever agent is admitting pills in the drawer, they should be able to be filtered. We also want a filter on pill type."*

*All color-coating removed. The drawer is purely text-based: agent name as a text prefix, no colors anywhere in this section.*

**Problem:** With a global drawer in a multi-agent project (Coder + Researcher + Reviewer), the user sees one merged stream. Two common cases:
- The user is focused on Coder and wants to ignore Researcher's web searches for the next few minutes.
- The user wants to mute all `command_output` pills (noisy) but keep `lifecycle_start` / `tool_error` (signal).

Currently both are impossible.

**Proposed solution:** Two independent filters in the drawer header:
- **Agent filter** — toggles per-agent visibility (Coder, Researcher, Reviewer, ...)
- **Pill-type filter** — toggles per-pill-type visibility (exec, read, write, plan, patch, approval, lifecycle, command_output, ...)

Both are toggle dropdowns / chips in the header. Filtered-out rows are completely removed (not dimmed, not greyed). Filter state is per-drawer (single drawer, in-memory per session).

**Visual model — drawer header with both filter dropdowns:**

```
▼ Activity    [12 visible / 47 total]    [Agent: Coder, Researcher ▾]  [Type: exec, read, plan ▾]  [Clear]
```

- `[Agent: Coder, Researcher ▾]` — dropdown. Click to open. Shows all agents with checkboxes. Checked = visible. Unchecking removes that agent's rows from the list.
- `[Type: exec, read, plan ▾]` — same pattern but for pill types.
- `[12 visible / 47 total]` — counter shows visible vs. total so the user knows filtering is active.
- The agent/type chips only appear after at least one event of that kind has fired (so a brand-new session doesn't show "Type: ▾" with nothing in it).

**Visual model — filtered rows (Coder + exec only, everything else hidden):**

```
[Coder]    exec ×5   pytest tests/test_auth.py   4,247ms
[Coder]    exec    git commit -m "fix auth"   340ms
```

All other rows (Researcher, reads, plans, patches) are filtered out — not rendered at all. The list shows only the user's current focus.

**Files changed (in addition to Day 3's list):**

| File | Change |
|------|--------|
| `ui/views/activity_drawer.py` | Add `self._visible_agents: set[str]` (default: all visible). Add `self._visible_types: set[str]` (default: all visible). On `append_event(agent_name, type, ...)`, check both sets; if either excludes, skip the row. Add `_render_filter_bar()` method that creates two `Gtk.DropDown` widgets (agent + type) in the header. On dropdown change, re-render the visible list. |
| `ui/handlers/activity_handler.py` | The `agent_name` and `type` fields are already populated. Pass them through in the callback args. |
| `ui/styles.py` | No new color classes. Add `.activity-drawer-filter-dropdown` and `.activity-drawer-filter-summary` for the chip styling. |

**Visual CSS (no colors, only neutral chips):**

```css
.activity-drawer-filter-dropdown {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.85em;
    color: rgba(255, 255, 255, 0.7);
}
.activity-drawer-filter-summary {
    color: rgba(255, 255, 255, 0.4);
    font-size: 0.8em;
    margin-right: 8px;
}
```

**Behavior rules:**

1. **New agent appearing:** auto-added to the agent dropdown as visible by default.
2. **New pill type appearing:** auto-added to the type dropdown as visible by default.
3. **Click dropdown:** opens a popup with checkboxes for each known agent/type. Toggle freely.
4. **Filter is AND'd:** a row is visible only if BOTH its agent AND its type are in the visible sets. (If Coder is visible but `exec` is hidden, Coder's exec rows are hidden; Coder's read rows are still visible.)
5. **"All" implicit:** if no agents or no types are explicitly hidden, all are visible. The dropdown chip shows the count of visible items, not "All."
6. **Filter state persists for the session** (in-memory; not persisted across app restarts).
7. **Clear button:** empties the list. Filter state (visible agents + visible types) is unchanged. The dropdowns stay as-is.
8. **Lifecycle separator visibility:** if an agent is hidden, its start/end separators are also hidden. The user sees a clean stream without start/end markers for filtered-out agents.

**Counter collapse interaction with filter:** If Coder is visible and Researcher is hidden, and we get Coder exec, Researcher search, Coder exec — the counter for Coder increments (Researcher is hidden, doesn't break the Coder counter streak). The hidden Researcher row is not in the list at all, so it has no effect on counter collapse. This is correct behavior.

Similarly, if `exec` is hidden but `read` is visible, a Coder exec → Coder read sequence shows only the read row (no counter to break because the exec was hidden).

**Dropdown data sources:**

- **Agent list:** maintained by the drawer as agents appear in the stream. `set[str]` of all agent names seen. The dropdown is rebuilt when a new agent appears.
- **Type list:** static — the 8 `ActivityType` values are known at compile time: `lifecycle_start`, `tool_start`, `tool_end`, `tool_error`, `plan`, `approval_request`, `command_output`, `patch`. The dropdown is built once at drawer init and never changes.

**Cost:** ~4-6 hours. Mostly dropdown widget construction and filter logic. No new business logic.

**Open questions for Captain:**

1. **AND vs OR semantics for the two filters?** Current proposal: AND (a row is visible only if BOTH its agent AND its type pass). Alternative: OR (a row is visible if EITHER passes). AND is more restrictive (focus mode); OR is more permissive (broad view). Captain's preference?
2. **Should the filter bar always be visible, or only when 2+ agents OR 2+ active types have appeared?** Default proposal: visible once the drawer has more than 1 unique agent or 2+ unique types in its history. Hidden when there's nothing to filter yet.
3. **Should the "Clear" button reset filter state too?** Default proposal: no — Clear only empties the list, filter survives. But "Clear all" (list + filter) is a valid alternative.
4. **Persist filter across app restarts?** Default proposal: no (in-memory). Persist via `~/.config/crabcakes/config.json` if the Captain wants it.
5. **Dropdown vs. multi-select chips?** Current proposal: `Gtk.DropDown` with checkboxes. Alternative: a row of toggle chips in the header (e.g., `[Coder] [Researcher] [Reviewer]` with strikethrough on hidden). Chips are faster to scan, dropdown is more compact. Captain's preference?

---

## 4. What This Does NOT Change

| Component | Status |
|-----------|--------|
| FeedBar (`ui/views/feedbar.py`) | **Untouched.** Continues showing current state. |
| ActivityHandler (`ui/handlers/activity_handler.py`) | **Modified.** Callback target changes (ChatHandler → ActivityDrawer). Adds `set_active_tool_lookup` for content enrichment. State machine logic unchanged. |
| `models/activity.py` | **Extended.** New `to_drawer_row()` method, `agent_name` field, extended `format_text()` `command_output` branch, `command` field use extended to `command_output` type. |
| AgentRuntimeHandler (`ui/handlers/agent_runtime_handler.py`) | **Modified.** New `_active_tools` cache and `get_active_tool()` public method for content enrichment. |
| Activity bubble CSS classes (`.activity-bubble`, etc.) | **Kept for backward compat.** Not removed — drawer rows use new classes. |
| Chat rendering pipeline | **Unchanged.** `render_sync()`, `render()`, `render_event_card()` all untouched. |
| Any other handler | **Untouched.** No cross-handler changes. |

---

## 5. Architecture Compliance

### §2 — Directory Structure

New file `ui/views/activity_drawer.py` follows the view convention — pure widget, no business logic. Added to `ui/views/` alongside other views.

### §3 — Module Responsibilities

**`ui/views/activity_drawer.py`** is a **view** per §9.2:
- Uses `widget.add_css_class()` only — never defines CSS
- No business logic — all data comes via `append_event()` calls
- No imports from handlers or gateway

**No handler changes except re-routing the callback.** ActivityHandler's existing `set_on_activity_bubble()` callback is simply pointed at the drawer instead of ChatHandler. This follows the callback pattern (§5) perfectly — components communicate through callbacks wired by `window.py`.

### §5 — Callback Pattern

```
window.py wires:
  ActivityHandler.set_on_activity_bubble(activity_drawer.append_event)
```

ActivityHandler doesn't know about ActivityDrawer. It just calls the callback. ActivityDrawer doesn't know about ActivityHandler. It just receives data via its public API. Window.py connects them. Clean.

### §6 — Naming Conventions

- File: `activity_drawer.py` (snake_case) ✓
- Class: `ActivityDrawer` (PascalCase) ✓
- CSS classes: `activity-drawer`, `activity-drawer-row` (component-element) ✓

### §7 — GTK4 Patterns

- `Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)` for the split — standard GTK4 pattern (§7.5)
- `Gtk.ScrolledWindow` with `set_propagate_natural_height(True)` for the drawer content
- All widget construction follows the kwargs pattern (§7.2)

### §8.2 — Adding a New UI Component

Checklist:
1. ✅ Created `ui/views/activity_drawer.py`
2. ✅ Component accepts data via `append_event()` — no callbacks needed (pure data sink)
3. ✅ Component never imports other UI components
4. ✅ Component exposes widget reference via property for Paned integration
5. ✅ `ui/window.py` wires the component

### §8.6 — Handler Pattern

No new handler needed. The drawer is a pure view — it receives data via its public API and renders it. The existing `ActivityHandler` continues to own all state machine logic. Only the callback target changes.

If future drawer features need business logic (e.g., filtering, search, export), that logic would go in a new `ui/handlers/activity_drawer_handler.py` per the handler pattern.

### §9 — CSS

All new CSS goes in `ui/styles.py`. New classes:

```css
.activity-drawer { ... }
.activity-drawer-header { ... }
.activity-drawer-header-btn { ... }
.activity-drawer-count { ... }
.activity-drawer-row { ... }
.activity-drawer-row-icon { ... }
.activity-drawer-row-text { ... }
.activity-drawer-row-duration { ... }
.activity-drawer-row-count { ... }
.activity-drawer-separator { ... }
```

No inline CSS. No `load_from_data()` in view code.

---

## 6. Dependency Chain

```
Day 1 (structural): drawer shell + remove inline bubbles
    ↓ no dependency on Day 2
Day 2 (content): counter-collapse + rich rows
    ↓ no dependency on Day 3
Day 3 (polish): lifecycle separators
```

Each day produces a shippable state. Day 1 alone solves the core UX problem (chat pollution + scroll hijacking). Days 2 and 3 are incremental improvements.

**No external dependencies.** No new packages. No GTK version changes. Uses existing `Gtk.Paned`, `Gtk.ScrolledWindow`, `Gtk.ListBox` — all already used elsewhere in the codebase.

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `Gtk.Paned` divider position resets on tab switch | Low | Drawer is global (not per-tab), so position persists across tab switches. No per-tab storage needed |
| Drawer steals vertical space from short chat tabs | Low | Set `set_shrink_end_child(True)` so drawer shrinks first. Default position gives 80%+ to chat |
| `Gtk.ListBox` performance with 500+ rows | Low | Cap at 100 rows (trim oldest 25). Rows are lightweight (icon + label) |
| Counter-collapse shows wrong count on lifecycle boundaries | Low | Day 3 adds lifecycle separators that break the counter chain |
| `set_propagate_natural_height(True)` causes drawer to expand unboundedly | Medium | Set `set_max_content_height(200)` on ScrolledWindow |

---

## 8. Success Metrics

| Metric | Before | After Day 1 | After Day 3 |
|--------|--------|-------------|-------------|
| Activity widgets in chat viewport | 30-50 per session | **0** | **0** |
| Chat scroll triggers from activity | 30-50 per session | **0** | **0** |
| Vertical pixels consumed in chat by activity | 1,400px | **0px** | **0px** |
| Activity data accessible to user | Yes (in chat) | Yes (in drawer) | Yes (in drawer + lifecycle groups) |
| Lines of code removed from ChatHandler | — | ~40 lines | ~40 lines |
| New files | — | 1 (activity_drawer.py) | 1 (activity_drawer.py) |

---

## 9. Relationship to QTR's Proposal

This proposal is a **simpler alternative** to QTR's `PROPOSAL-activity-bubble-ux.md`. Key differences:

| Aspect | QTR's Proposal | This Proposal |
|--------|---------------|---------------|
| Delivery surface | Nested container inside chat | Separate drawer below chat |
| Duration | 6-7 days | 3 days |
| Number of fixes | 5 interdependent fixes | 3 independent phases |
| Custom GTK containers | Yes (bounded ScrolledWindow in chat) | No (standard Paned + ScrolledWindow) |
| Counter-collapse | Per-session, per-turn state machine with widget mutation | Simple "last row matches?" check |
| Content enrichment | 4-6 hours of gateway investigation + cache | Same investigation, but not blocking — drawer shows what it has |
| Toggle | Separate toggle button in control bar | Built into drawer header |
| Scroll interference | Must carefully avoid nested scroll conflicts | Impossible — drawer has its own scroll, chat has its own |

**If approved, QTR's proposal should be marked superseded.** The content enrichment investigation (QTR Fix 1.5) is still worth doing independently — it improves what the drawer rows display.

---

## 10. Decisions (All Confirmed)

1. **Drawer default state:** Collapsed on launch.

2. **Auto-collapse:** None. Stay expanded until manually collapsed.

3. **Row limit:** 100 rows. After that, oldest 25 are removed in bulk.

4. **Scope:** Global — one drawer shared across all tabs.

5. **Filter UI:** Dropdown menu. Click "Filter" button → popover with checkboxes. Header stays clean.

6. **Filter combination:** AND. Both agent and type must pass. "Coder + exec" = only Coder's exec events.

7. **Default filter state:** All-on. Show everything by default. User narrows down.

8. **Filter persistence:** Survives drawer toggle, resets on app restart.

9. **Agent list source:** Only agents that have actually emitted events. Not from AgentManager.

**Implementation implication of global drawer:** The ActivityDrawer is wired into `MainWindow._build()`, not `MainContent`. It sits outside the notebook — below the entire MainContent widget. This means it persists across tab switches and shows a unified activity stream from all agents and projects.

---

**Standing by for your approval, Captain.**
